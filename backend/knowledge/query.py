"""Servicio de consulta temporal y de evidencia provider-neutral.

Capa determinista sobre el modelo estructural existente:

    KnowledgeItem -> KnowledgeBlock -> KnowledgeBlockVersion

Responde:

    ¿qué decía esta norma/bloque en la fecha X?
    ¿qué cambió y cuándo?
    ¿de dónde procede la respuesta?

Principios:

- reutiliza ``resolve_block_version_at`` / ``resolve_document_at`` /
  ``compare_temporal_snapshots``; no duplica la lógica temporal;
- una consulta en T nunca devuelve versiones con ``effective_from > T``;
- el modelo solo conserva ``effective_from``: el fin de vigencia
  (derogación) NO está representado y se expone como tal, nunca se
  inventa. ``superseded_on`` es la fecha de la versión posterior
  observada, no una derogación;
- la procedencia es un objeto estructurado, no prosa;
- la estructura persistida es una representación DERIVADA de la fuente
  oficial; así se etiqueta en cada ``KnowledgeProvenance``;
- sin SQL, red, UI ni IA. Depende solo de puertos de repositorio.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum

from .legal_structure import (
    KnowledgeBlock,
    KnowledgeBlockVersion,
    KnowledgeStructuredDocument,
)
from .items import KnowledgeItem
from .repository import KnowledgeRepository
from .source_registry import (
    get_knowledge_source,
    normalize_source_key,
)
from .structure_repository import (
    KnowledgeStructureListing,
    KnowledgeStructureRepository,
)
from .temporal import (
    KnowledgeTemporalDocumentSnapshot,
    KnowledgeTemporalDocumentStatus,
    KnowledgeTemporalResolutionStatus,
    resolve_block_version_at,
    resolve_document_at,
)
from .temporal_diff import (
    KnowledgeTemporalBlockChangeKind,
    KnowledgeTemporalDiff,
    compare_temporal_snapshots,
)
from .evidence_horizon import (
    KnowledgeEvidenceHorizon,
    KnowledgeEvidenceHorizonStatus,
    resolve_evidence_horizon,
)
from .temporal_integrity import (
    block_timeline_issues,
)
from .validity import (
    KnowledgeDocumentValidity,
    KnowledgeValidityResolver,
    unknown_validity,
)


REPRESENTATION_DERIVED_STRUCTURED = (
    "DERIVED_STRUCTURED"
)

_IDENTIFIER_SCHEMES = {
    "BOE": "BOE_ID",
    "EUR_LEX": "CELEX",
}

DEFAULT_SEARCH_LIMIT = 50


class KnowledgeQueryCapabilityError(
    RuntimeError
):
    """El adaptador de persistencia no soporta la operación."""


class KnowledgeQueryStatus(
    str,
    Enum,
):
    RESOLVED = "RESOLVED"

    DOCUMENT_NOT_FOUND = (
        "DOCUMENT_NOT_FOUND"
    )

    BLOCK_NOT_FOUND = (
        "BLOCK_NOT_FOUND"
    )

    INCOMPLETE_TIMELINE = (
        "INCOMPLETE_TIMELINE"
    )


class KnowledgeSearchMatchKind(
    str,
    Enum,
):
    """Orden de relevancia determinista: menor rank, mayor prioridad."""

    IDENTIFIER = "IDENTIFIER"
    DOCUMENT_TITLE = "DOCUMENT_TITLE"
    BLOCK_TITLE = "BLOCK_TITLE"
    CONTENT = "CONTENT"


_MATCH_RANK = {
    KnowledgeSearchMatchKind.IDENTIFIER: 0,
    KnowledgeSearchMatchKind.DOCUMENT_TITLE: 1,
    KnowledgeSearchMatchKind.BLOCK_TITLE: 2,
    KnowledgeSearchMatchKind.CONTENT: 3,
}


# ============================================================
# PROVENANCE
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeProvenance:
    """Procedencia estructurada de una respuesta.

    Los campos de bloque/versión están vacíos en procedencia
    a nivel de documento.
    """

    source_key: str
    provider: str
    authority: str

    identifier_scheme: str
    external_id: str
    document_canonical_key: str

    representation: str = (
        REPRESENTATION_DERIVED_STRUCTURED
    )

    document_title: str = ""
    document_uri: str = ""
    source_revision: str = ""
    language: str = ""

    block_id: str = ""
    block_canonical_key: str = ""
    block_uri: str = ""

    version_key: str = ""
    version_canonical_key: str = ""
    version_position: int | None = None
    content_sha256: str = ""
    modifier_external_id: str = ""
    published_on: date | None = None
    effective_from: date | None = None
    is_current: bool | None = None

    metadata: tuple[
        tuple[str, str],
        ...,
    ] = ()


def _document_provenance(
    document: KnowledgeStructuredDocument,
    item: KnowledgeItem | None,
) -> KnowledgeProvenance:
    source = get_knowledge_source(
        document.source_key
    )

    return KnowledgeProvenance(
        source_key=document.source_key,
        provider=source.provider,
        authority=source.authority.value,
        identifier_scheme=(
            _IDENTIFIER_SCHEMES.get(
                source.provider,
                "EXTERNAL_ID",
            )
        ),
        external_id=document.external_id,
        document_canonical_key=(
            document.canonical_key
        ),
        document_title=(
            item.title
            if item is not None
            else ""
        ),
        document_uri=(
            item.canonical_uri
            if item is not None
            else ""
        ),
        source_revision=(
            item.source_revision
            if item is not None
            else ""
        ),
        language=(
            item.language
            if item is not None
            else ""
        ),
    )


def _version_provenance(
    base: KnowledgeProvenance,
    block: KnowledgeBlock,
    version: KnowledgeBlockVersion,
) -> KnowledgeProvenance:
    return replace(
        base,
        block_id=block.block_id,
        block_canonical_key=(
            block.canonical_key
        ),
        block_uri=block.canonical_uri,
        version_key=version.version_key,
        version_canonical_key=(
            version.canonical_key
        ),
        version_position=(
            version.version_position
        ),
        content_sha256=(
            version.content_sha256
        ),
        modifier_external_id=(
            version.modifier_external_id
        ),
        published_on=version.published_on,
        effective_from=(
            version.effective_from
        ),
        is_current=version.is_current,
        metadata=version.metadata,
    )


# ============================================================
# RESULT OBJECTS
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeBlockAnswer:
    """Bloque tal como resultaba aplicable en ``as_of``."""

    source_key: str
    external_id: str
    block_id: str
    as_of: date

    status: KnowledgeTemporalResolutionStatus

    version: KnowledgeBlockVersion | None = None
    provenance: KnowledgeProvenance | None = None

    # Fecha efectiva de la versión siguiente observada, si existe.
    # NO es una derogación: el modelo no representa effective_to.
    superseded_on: date | None = None

    # True si no hay versión posterior observada. Significa
    # "sin evidencia de fin", no "vigente indefinidamente".
    open_ended: bool = False

    reason: str = ""

    @property
    def resolved(
        self,
    ) -> bool:
        return (
            self.status
            is KnowledgeTemporalResolutionStatus.RESOLVED
            and self.version is not None
        )

    @property
    def content_text(
        self,
    ) -> str:
        if not self.resolved:
            return ""

        assert self.version is not None

        return self.version.content_text


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeDocumentRecord:
    """Documento con cabecera de procedencia y cobertura temporal."""

    provenance: KnowledgeProvenance
    document: KnowledgeStructuredDocument

    first_effective_from: date | None
    last_effective_from: date | None
    undated_version_count: int

    # El modelo no conserva fin de vigencia/derogación.
    end_of_validity_represented: bool = False

    @property
    def block_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            block.block_id
            for block in sorted(
                self.document.blocks,
                key=lambda item: (
                    item.position,
                    item.block_id,
                ),
            )
        )


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeDocumentAnswer:
    """Documento completo reconstruido en ``as_of``."""

    source_key: str
    external_id: str
    as_of: date

    status: KnowledgeTemporalDocumentStatus

    provenance: KnowledgeProvenance | None = None

    blocks: tuple[
        KnowledgeBlockAnswer,
        ...,
    ] = ()

    omitted_future_blocks: tuple[
        str,
        ...,
    ] = ()

    unresolved_blocks: tuple[
        str,
        ...,
    ] = ()

    # Máxima effective_from entre los bloques resueltos: fecha
    # efectiva DERIVADA de la fotografía, no un dato del documento.
    snapshot_effective_from: date | None = None

    end_of_validity_represented: bool = False

    reason: str = ""

    snapshot: (
        KnowledgeTemporalDocumentSnapshot
        | None
    ) = None

    @property
    def resolved(
        self,
    ) -> bool:
        return (
            self.status
            is KnowledgeTemporalDocumentStatus.RESOLVED
        )

    @property
    def content_text(
        self,
    ) -> str:
        if self.snapshot is None:
            return ""

        return self.snapshot.content_text


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeVersionEntry:
    provenance: KnowledgeProvenance
    valid_from: date | None
    superseded_on: date | None
    content_text: str


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeBlockHistory:
    source_key: str
    external_id: str
    block_id: str

    status: KnowledgeQueryStatus

    versions: tuple[
        KnowledgeVersionEntry,
        ...,
    ] = ()

    # Códigos de integridad temporal detectados; vacío si limpio.
    issues: tuple[str, ...] = ()

    reason: str = ""


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeChangeEvidence:
    block_id: str
    kind: KnowledgeTemporalBlockChangeKind

    from_provenance: KnowledgeProvenance | None
    to_provenance: KnowledgeProvenance | None


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeVersionComparison:
    diff: KnowledgeTemporalDiff

    changes: tuple[
        KnowledgeChangeEvidence,
        ...,
    ] = ()

    @property
    def resolved(
        self,
    ) -> bool:
        return self.diff.resolved


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeChangeEvent:
    """Entrada de versión cuya vigencia empieza dentro del rango."""

    effective_from: date
    block_id: str

    # INITIAL: primera versión observada del bloque (no implica
    # que el bloque naciera en esa fecha, solo que no hay previa).
    # AMENDED: versión posterior a otra observada.
    event: str

    provenance: KnowledgeProvenance


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeChangeLog:
    source_key: str
    external_id: str

    since: date
    until: date

    status: KnowledgeQueryStatus

    events: tuple[
        KnowledgeChangeEvent,
        ...,
    ] = ()

    unresolved_blocks: tuple[
        str,
        ...,
    ] = ()

    reason: str = ""


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeSearchHit:
    match_kind: KnowledgeSearchMatchKind
    provenance: KnowledgeProvenance

    @property
    def rank(
        self,
    ) -> int:
        return _MATCH_RANK[
            self.match_kind
        ]


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeSearchResult:
    query: str
    as_of: date | None

    # "AS_OF": versiones resueltas en la fecha.
    # "LATEST_KNOWN": versión marcada is_current; NO es "hoy".
    temporal_basis: str

    hits: tuple[
        KnowledgeSearchHit,
        ...,
    ] = ()

    truncated: bool = False

    # Bloques no evaluables (cronología incompleta o aún no
    # vigentes): (block_canonical_key, status).
    excluded_blocks: tuple[
        tuple[str, str],
        ...,
    ] = ()


# ============================================================
# HELPERS
# ============================================================


def _require_date(
    value: object,
    *,
    field_name: str,
) -> date:
    # datetime hereda de date, pero compararlo con date lanza
    # TypeError tardío o ambigüedad horaria: se rechaza aquí.
    if (
        not isinstance(
            value,
            date,
        )
        or isinstance(
            value,
            datetime,
        )
    ):
        raise TypeError(
            f"{field_name} debe ser datetime.date"
        )

    return value


def _text_key(
    value: str,
) -> str:
    return " ".join(
        str(
            value or ""
        ).casefold().split()
    )


# ============================================================
# SERVICE
# ============================================================


class KnowledgeQueryService:
    """API de consulta determinista sobre estructura persistida.

    ``item_repository`` es opcional: aporta título, URI y revisión
    de la fuente a la procedencia. Sin él, esos campos quedan vacíos
    (nunca se inventan).

    ``validity_resolvers`` es opcional: mapa ``source_key -> resolver``
    que interpreta banderas de derogación/vigencia propias de cada
    provider (p. ej. ``resolve_boe_consolidated_validity``). Sin
    resolver registrado para una fuente, la validez se reporta
    ``UNKNOWN`` en lugar de inventarse.
    """

    def __init__(
        self,
        structure_repository: KnowledgeStructureRepository,
        item_repository: (
            KnowledgeRepository | None
        ) = None,
        validity_resolvers: (
            dict[
                str,
                KnowledgeValidityResolver,
            ]
            | None
        ) = None,
    ) -> None:
        if not isinstance(
            structure_repository,
            KnowledgeStructureRepository,
        ):
            raise TypeError(
                "structure_repository debe implementar "
                "KnowledgeStructureRepository"
            )

        if (
            item_repository is not None
            and not isinstance(
                item_repository,
                KnowledgeRepository,
            )
        ):
            raise TypeError(
                "item_repository debe implementar "
                "KnowledgeRepository"
            )

        self._structures = (
            structure_repository
        )
        self._items = item_repository

        self._validity_resolvers = {
            normalize_source_key(key): resolver
            for key, resolver in (
                validity_resolvers or {}
            ).items()
        }

    # ---------------- internals ----------------

    def _load(
        self,
        source_key: str,
        external_id: str,
    ) -> tuple[
        KnowledgeStructuredDocument | None,
        KnowledgeProvenance | None,
    ]:
        document = (
            self._structures.get_document(
                source_key,
                external_id,
            )
        )

        if document is None:
            return None, None

        item = (
            self._items.get_current(
                document.source_key,
                document.external_id,
            )
            if self._items is not None
            else None
        )

        return (
            document,
            _document_provenance(
                document,
                item,
            ),
        )

    @staticmethod
    def _block_answer(
        document: KnowledgeStructuredDocument,
        base: KnowledgeProvenance,
        block_id: str,
        as_of: date,
    ) -> KnowledgeBlockAnswer:
        resolution = (
            resolve_block_version_at(
                document,
                block_id,
                as_of,
            )
        )

        if not resolution.resolved:
            return KnowledgeBlockAnswer(
                source_key=(
                    document.source_key
                ),
                external_id=(
                    document.external_id
                ),
                block_id=block_id,
                as_of=as_of,
                status=resolution.status,
                reason=resolution.reason,
            )

        version = resolution.version

        assert version is not None

        block = next(
            item
            for item in document.blocks
            if item.block_id == block_id
        )

        later = [
            candidate
            for candidate
            in document.versions_for_block(
                block_id
            )
            if candidate.version_position
            > version.version_position
        ]

        superseded_on = (
            later[0].effective_from
            if later
            else None
        )

        return KnowledgeBlockAnswer(
            source_key=document.source_key,
            external_id=(
                document.external_id
            ),
            block_id=block_id,
            as_of=as_of,
            status=resolution.status,
            version=version,
            provenance=_version_provenance(
                base,
                block,
                version,
            ),
            superseded_on=superseded_on,
            open_ended=not later,
            reason=resolution.reason,
        )

    # ---------------- public API ----------------

    def get_document(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeDocumentRecord | None:
        document, base = self._load(
            source_key,
            external_id,
        )

        if document is None:
            return None

        assert base is not None

        dates = [
            version.effective_from
            for version in document.versions
            if version.effective_from
            is not None
        ]

        return KnowledgeDocumentRecord(
            provenance=base,
            document=document,
            first_effective_from=(
                min(dates)
                if dates
                else None
            ),
            last_effective_from=(
                max(dates)
                if dates
                else None
            ),
            undated_version_count=sum(
                1
                for version
                in document.versions
                if version.effective_from
                is None
            ),
        )

    def get_effective_version(
        self,
        source_key: str,
        external_id: str,
        as_of: date,
    ) -> KnowledgeDocumentAnswer:
        """Norma completa tal como estaba en ``as_of``."""

        as_of = _require_date(
            as_of,
            field_name="as_of",
        )

        document, base = self._load(
            source_key,
            external_id,
        )

        if document is None:
            return KnowledgeDocumentAnswer(
                source_key=normalize_source_key(
                    source_key
                ),
                external_id=str(
                    external_id or ""
                ).strip(),
                as_of=as_of,
                status=(
                    KnowledgeTemporalDocumentStatus.DOCUMENT_NOT_FOUND
                ),
                reason=(
                    "No existe estructura jurídica "
                    "persistida para la identidad."
                ),
            )

        assert base is not None

        snapshot = resolve_document_at(
            document,
            as_of,
        )

        blocks = tuple(
            self._block_answer(
                document,
                base,
                block.block_id,
                as_of,
            )
            for block
            in snapshot.blocks
        )

        dates = [
            answer.version.effective_from
            for answer in blocks
            if answer.version is not None
            and answer.version.effective_from
            is not None
        ]

        return KnowledgeDocumentAnswer(
            source_key=document.source_key,
            external_id=(
                document.external_id
            ),
            as_of=as_of,
            status=snapshot.status,
            provenance=base,
            blocks=blocks,
            omitted_future_blocks=(
                snapshot.omitted_future_blocks
            ),
            unresolved_blocks=(
                snapshot.unresolved_blocks
            ),
            snapshot_effective_from=(
                max(dates)
                if dates
                else None
            ),
            reason=snapshot.reason,
            snapshot=snapshot,
        )

    def get_block(
        self,
        source_key: str,
        external_id: str,
        block_id: str,
        as_of: date,
    ) -> KnowledgeBlockAnswer:
        as_of = _require_date(
            as_of,
            field_name="as_of",
        )

        identifier = str(
            block_id or ""
        ).strip()

        if not identifier:
            raise ValueError(
                "block_id no puede estar vacío"
            )

        document, base = self._load(
            source_key,
            external_id,
        )

        if document is None:
            return KnowledgeBlockAnswer(
                source_key=normalize_source_key(
                    source_key
                ),
                external_id=str(
                    external_id or ""
                ).strip(),
                block_id=identifier,
                as_of=as_of,
                status=(
                    KnowledgeTemporalResolutionStatus.DOCUMENT_NOT_FOUND
                ),
                reason=(
                    "No existe estructura jurídica "
                    "persistida para la identidad."
                ),
            )

        assert base is not None

        return self._block_answer(
            document,
            base,
            identifier,
            as_of,
        )

    def get_evidence(
        self,
        source_key: str,
        external_id: str,
        block_id: str,
        as_of: date,
    ) -> KnowledgeProvenance | None:
        """Procedencia de la versión aplicable, o None si no resuelve.

        None significa "sin evidencia"; use ``get_block`` para el
        motivo concreto.
        """

        return self.get_block(
            source_key,
            external_id,
            block_id,
            as_of,
        ).provenance

    def get_block_history(
        self,
        source_key: str,
        external_id: str,
        block_id: str,
    ) -> KnowledgeBlockHistory:
        identifier = str(
            block_id or ""
        ).strip()

        if not identifier:
            raise ValueError(
                "block_id no puede estar vacío"
            )

        document, base = self._load(
            source_key,
            external_id,
        )

        normalized_source = (
            normalize_source_key(
                source_key
            )
        )

        clean_external = str(
            external_id or ""
        ).strip()

        if document is None:
            return KnowledgeBlockHistory(
                source_key=normalized_source,
                external_id=clean_external,
                block_id=identifier,
                status=(
                    KnowledgeQueryStatus.DOCUMENT_NOT_FOUND
                ),
                reason=(
                    "No existe estructura jurídica "
                    "persistida para la identidad."
                ),
            )

        assert base is not None

        block = next(
            (
                item
                for item in document.blocks
                if item.block_id
                == identifier
            ),
            None,
        )

        if block is None:
            return KnowledgeBlockHistory(
                source_key=document.source_key,
                external_id=(
                    document.external_id
                ),
                block_id=identifier,
                status=(
                    KnowledgeQueryStatus.BLOCK_NOT_FOUND
                ),
                reason=(
                    "El bloque no existe "
                    "en la estructura jurídica."
                ),
            )

        versions = (
            document.versions_for_block(
                identifier
            )
        )

        issues = block_timeline_issues(
            versions
        )

        entries = tuple(
            KnowledgeVersionEntry(
                provenance=_version_provenance(
                    base,
                    block,
                    version,
                ),
                valid_from=(
                    version.effective_from
                ),
                superseded_on=(
                    versions[
                        index + 1
                    ].effective_from
                    if index + 1
                    < len(versions)
                    else None
                ),
                content_text=(
                    version.content_text
                ),
            )
            for index, version
            in enumerate(versions)
        )

        return KnowledgeBlockHistory(
            source_key=document.source_key,
            external_id=document.external_id,
            block_id=identifier,
            status=(
                KnowledgeQueryStatus.INCOMPLETE_TIMELINE
                if issues
                else KnowledgeQueryStatus.RESOLVED
            ),
            versions=entries,
            issues=issues,
            reason=(
                "Cronología con anomalías: "
                "no debe usarse como evidencia."
                if issues
                else "Cronología íntegra."
            ),
        )

    def compare_versions(
        self,
        source_key: str,
        external_id: str,
        from_date: date,
        to_date: date,
    ) -> KnowledgeVersionComparison:
        """Diferencias entre dos fechas, con procedencia por cambio."""

        from_date = _require_date(
            from_date,
            field_name="from_date",
        )

        to_date = _require_date(
            to_date,
            field_name="to_date",
        )

        document, base = self._load(
            source_key,
            external_id,
        )

        if document is None:
            missing = (
                KnowledgeTemporalDocumentSnapshot(
                    source_key=normalize_source_key(
                        source_key
                    ),
                    external_id=str(
                        external_id or ""
                    ).strip(),
                    as_of=from_date,
                    status=(
                        KnowledgeTemporalDocumentStatus.DOCUMENT_NOT_FOUND
                    ),
                )
            )

            return KnowledgeVersionComparison(
                diff=compare_temporal_snapshots(
                    missing,
                    KnowledgeTemporalDocumentSnapshot(
                        source_key=(
                            missing.source_key
                        ),
                        external_id=(
                            missing.external_id
                        ),
                        as_of=to_date,
                        status=(
                            KnowledgeTemporalDocumentStatus.DOCUMENT_NOT_FOUND
                        ),
                    ),
                )
            )

        assert base is not None

        diff = compare_temporal_snapshots(
            resolve_document_at(
                document,
                from_date,
            ),
            resolve_document_at(
                document,
                to_date,
            ),
        )

        blocks = {
            block.block_id: block
            for block in document.blocks
        }

        def evidence(
            version: KnowledgeBlockVersion | None,
        ) -> KnowledgeProvenance | None:
            if version is None:
                return None

            return _version_provenance(
                base,
                blocks[version.block_id],
                version,
            )

        return KnowledgeVersionComparison(
            diff=diff,
            changes=tuple(
                KnowledgeChangeEvidence(
                    block_id=change.block_id,
                    kind=change.kind,
                    from_provenance=evidence(
                        change.from_version
                    ),
                    to_provenance=evidence(
                        change.to_version
                    ),
                )
                for change in diff.changes
            ),
        )

    def get_changes(
        self,
        source_key: str,
        external_id: str,
        since: date,
        until: date,
    ) -> KnowledgeChangeLog:
        """Versiones cuya vigencia empieza en ``(since, until]``.

        Semántica alineada con ``as_of``: un cambio efectivo en
        ``since`` ya estaba vigente en ``since`` y no se cuenta;
        uno efectivo en ``until`` sí. Bloques con cronología
        anómala se excluyen y se reportan, no se adivinan.
        """

        since = _require_date(
            since,
            field_name="since",
        )

        until = _require_date(
            until,
            field_name="until",
        )

        if until < since:
            raise ValueError(
                "until no puede ser anterior a since"
            )

        document, base = self._load(
            source_key,
            external_id,
        )

        if document is None:
            return KnowledgeChangeLog(
                source_key=normalize_source_key(
                    source_key
                ),
                external_id=str(
                    external_id or ""
                ).strip(),
                since=since,
                until=until,
                status=(
                    KnowledgeQueryStatus.DOCUMENT_NOT_FOUND
                ),
                reason=(
                    "No existe estructura jurídica "
                    "persistida para la identidad."
                ),
            )

        assert base is not None

        events = []
        unresolved = []

        for block in sorted(
            document.blocks,
            key=lambda item: (
                item.position,
                item.block_id,
            ),
        ):
            versions = (
                document.versions_for_block(
                    block.block_id
                )
            )

            if block_timeline_issues(
                versions
            ):
                unresolved.append(
                    block.block_id
                )
                continue

            for version in versions:
                effective = (
                    version.effective_from
                )

                assert effective is not None

                if not (
                    since
                    < effective
                    <= until
                ):
                    continue

                events.append(
                    KnowledgeChangeEvent(
                        effective_from=effective,
                        block_id=block.block_id,
                        event=(
                            "INITIAL"
                            if version.version_position
                            == versions[
                                0
                            ].version_position
                            else "AMENDED"
                        ),
                        provenance=_version_provenance(
                            base,
                            block,
                            version,
                        ),
                    )
                )

        positions = {
            block.block_id: block.position
            for block in document.blocks
        }

        events.sort(
            key=lambda event: (
                event.effective_from,
                positions[event.block_id],
                event.block_id,
                event.provenance.version_position
                or 0,
            )
        )

        incomplete = bool(
            unresolved
        )

        return KnowledgeChangeLog(
            source_key=document.source_key,
            external_id=document.external_id,
            since=since,
            until=until,
            status=(
                KnowledgeQueryStatus.INCOMPLETE_TIMELINE
                if incomplete
                else KnowledgeQueryStatus.RESOLVED
            ),
            events=tuple(events),
            unresolved_blocks=tuple(
                unresolved
            ),
            reason=(
                "Existen bloques con cronología "
                "anómala; la lista de cambios "
                "puede ser incompleta."
                if incomplete
                else "Cambios derivados de "
                "effective_from oficiales."
            ),
        )

    def search(
        self,
        query: str,
        *,
        source_key: str | None = None,
        as_of: date | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> KnowledgeSearchResult:
        """Búsqueda determinista sobre estructura persistida.

        Prioridad: identificador exacto, título de documento, título
        de bloque, contenido. Cada documento/bloque produce a lo sumo
        un resultado (su mejor coincidencia). Orden total:
        (rank, source_key, external_id, posición, block_id).

        Con ``as_of`` solo se busca en versiones resueltas en esa
        fecha. Sin ``as_of`` se usa la versión ``is_current`` y el
        resultado lo declara como ``LATEST_KNOWN``.
        """

        needle = _text_key(query)

        if not needle:
            raise ValueError(
                "query no puede estar vacía"
            )

        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
        ):
            raise ValueError(
                "limit debe ser entero >= 1"
            )

        if as_of is not None:
            as_of = _require_date(
                as_of,
                field_name="as_of",
            )

        if not isinstance(
            self._structures,
            KnowledgeStructureListing,
        ):
            raise KnowledgeQueryCapabilityError(
                "El repositorio no soporta "
                "list_document_identities"
            )

        identities = (
            self._structures.list_document_identities(
                source_key
            )
        )

        scored = []
        excluded = []

        for identity in sorted(
            identities
        ):
            document, base = self._load(
                *identity
            )

            if document is None:
                continue

            assert base is not None

            ordered = sorted(
                document.blocks,
                key=lambda item: (
                    item.position,
                    item.block_id,
                ),
            )

            if (
                _text_key(
                    document.external_id
                )
                == needle
            ):
                scored.append(
                    (
                        _MATCH_RANK[
                            KnowledgeSearchMatchKind.IDENTIFIER
                        ],
                        identity,
                        0,
                        "",
                        KnowledgeSearchHit(
                            KnowledgeSearchMatchKind.IDENTIFIER,
                            base,
                        ),
                    )
                )
            elif (
                needle
                in _text_key(
                    base.document_title
                )
            ):
                scored.append(
                    (
                        _MATCH_RANK[
                            KnowledgeSearchMatchKind.DOCUMENT_TITLE
                        ],
                        identity,
                        0,
                        "",
                        KnowledgeSearchHit(
                            KnowledgeSearchMatchKind.DOCUMENT_TITLE,
                            base,
                        ),
                    )
                )

            for block in ordered:
                if as_of is None:
                    version = (
                        document.current_version(
                            block.block_id
                        )
                    )
                else:
                    resolution = (
                        resolve_block_version_at(
                            document,
                            block.block_id,
                            as_of,
                        )
                    )

                    if not resolution.resolved:
                        excluded.append(
                            (
                                block.canonical_key,
                                resolution.status.value,
                            )
                        )
                        continue

                    version = (
                        resolution.version
                    )

                assert version is not None

                if needle in _text_key(
                    block.title
                ):
                    kind = (
                        KnowledgeSearchMatchKind.BLOCK_TITLE
                    )
                elif needle in _text_key(
                    version.content_text
                ):
                    kind = (
                        KnowledgeSearchMatchKind.CONTENT
                    )
                else:
                    continue

                scored.append(
                    (
                        _MATCH_RANK[kind],
                        identity,
                        block.position,
                        block.block_id,
                        KnowledgeSearchHit(
                            kind,
                            _version_provenance(
                                base,
                                block,
                                version,
                            ),
                        ),
                    )
                )

        scored.sort(
            key=lambda entry: entry[:4]
        )

        hits = tuple(
            entry[4]
            for entry in scored
        )

        return KnowledgeSearchResult(
            query=str(query).strip(),
            as_of=as_of,
            temporal_basis=(
                "LATEST_KNOWN"
                if as_of is None
                else "AS_OF"
            ),
            hits=hits[:limit],
            truncated=len(hits) > limit,
            excluded_blocks=tuple(
                sorted(excluded)
            ),
        )

    def get_document_validity(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeDocumentValidity:
        """Derogación/fin de vigencia declarados por la fuente.

        Requiere ``item_repository`` (la evidencia vive en metadata de
        ``KnowledgeItem``, no en la estructura de bloques) y un
        resolver registrado para la fuente. Sin cualquiera de los dos,
        o sin ``KnowledgeItem`` persistido, el resultado es ``UNKNOWN``
        explícito: nunca se fabrica un estado positivo.
        """

        normalized_source = (
            normalize_source_key(
                source_key
            )
        )

        clean_external = str(
            external_id or ""
        ).strip()

        if not clean_external:
            raise ValueError(
                "external_id no puede estar vacío"
            )

        if self._items is None:
            return unknown_validity(
                source_key=normalized_source,
                external_id=clean_external,
                reason=(
                    "item_repository no fue "
                    "inyectado; no puede "
                    "resolverse la validez "
                    "documental."
                ),
            )

        item = (
            self._items.get_current(
                normalized_source,
                clean_external,
            )
        )

        if item is None:
            return unknown_validity(
                source_key=normalized_source,
                external_id=clean_external,
                reason=(
                    "No existe KnowledgeItem "
                    "persistido para la identidad."
                ),
            )

        resolver = (
            self._validity_resolvers.get(
                normalized_source
            )
        )

        if resolver is None:
            return unknown_validity(
                source_key=normalized_source,
                external_id=clean_external,
                reason=(
                    "No existe resolutor de "
                    "validez estructurado "
                    "registrado para esta fuente."
                ),
            )

        return resolver(item)

    def get_evidence_horizon(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeEvidenceHorizon:
        """Completitud de la evidencia observada para una identidad.

        Requiere ``item_repository`` para acceder al historial de
        ingestión. Sin él, el horizonte es explícitamente
        ``HORIZON_UNKNOWN``.
        """

        normalized_source = (
            normalize_source_key(
                source_key
            )
        )

        clean_external = str(
            external_id or ""
        ).strip()

        if not clean_external:
            raise ValueError(
                "external_id no puede estar vacío"
            )

        if self._items is None:
            return KnowledgeEvidenceHorizon(
                source_key=normalized_source,
                external_id=clean_external,
                status=(
                    KnowledgeEvidenceHorizonStatus.HORIZON_UNKNOWN
                ),
                reason=(
                    "item_repository no fue "
                    "inyectado; no puede "
                    "determinarse el horizonte "
                    "de evidencia."
                ),
            )

        revisions = (
            self._items.list_revisions(
                normalized_source,
                clean_external,
            )
        )

        return resolve_evidence_horizon(
            source_key=normalized_source,
            external_id=clean_external,
            revisions=revisions,
        )
