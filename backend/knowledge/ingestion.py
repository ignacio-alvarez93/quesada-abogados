"""Servicio de aplicación para la ingestión canónica de Knowledge.

Esta capa coordina providers, clasificación de revisiones y repository.
No conoce HTTP, BOE internamente, SQLite ni PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass

from .items import KnowledgeItem
from .providers import (
    KnowledgeItemReference,
    KnowledgeProvider,
    KnowledgeStructuredProvider,
    validate_discovery_batch,
    validate_structured_document,
    validate_transformed_item,
)
from .legal_structure import (
    KnowledgeStructuredDocument,
)
from .structure_repository import (
    KnowledgeStructureRepository,
)
from .repository import (
    KnowledgeRepository,
)
from .revisions import (
    KnowledgeRevisionDecision,
    KnowledgeRevisionStatus,
    classify_knowledge_revision,
)


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionResult:
    canonical_key: str
    status: KnowledgeRevisionStatus

    revision_number: int
    written: bool

    content_sha256: str
    source_revision: str

    structure_supported: bool = False
    structure_written: bool = False

    structure_block_count: int = 0
    structure_version_count: int = 0


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionPreview:
    canonical_key: str
    status: KnowledgeRevisionStatus

    content_sha256: str
    source_revision: str


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionBatchResult:
    source_key: str

    discovered_count: int
    attempted_count: int
    written_count: int
    unchanged_count: int

    next_cursor: str | None

    results: tuple[
        KnowledgeIngestionResult,
        ...,
    ]

    structured_written_count: int = 0


@dataclass(frozen=True, slots=True)
class _PreparedKnowledgeReference:
    item: KnowledgeItem
    decision: KnowledgeRevisionDecision

    structure_supported: bool
    structure: KnowledgeStructuredDocument | None


class KnowledgeIngestionService:
    """Orquestador provider-neutral de Knowledge."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        structure_repository: (
            KnowledgeStructureRepository
            | None
        ) = None,
    ) -> None:
        if not isinstance(
            repository,
            KnowledgeRepository,
        ):
            raise TypeError(
                "repository debe implementar "
                "KnowledgeRepository"
            )

        if (
            structure_repository
            is not None
            and not isinstance(
                structure_repository,
                KnowledgeStructureRepository,
            )
        ):
            raise TypeError(
                "structure_repository debe implementar "
                "KnowledgeStructureRepository o ser None"
            )

        self._repository = repository
        self._structure_repository = (
            structure_repository
        )

    @property
    def repository(
        self,
    ) -> KnowledgeRepository:
        return self._repository

    @property
    def structure_repository(
        self,
    ) -> KnowledgeStructureRepository | None:
        return self._structure_repository

    def _prepare_reference(
        self,
        provider: KnowledgeProvider,
        reference: KnowledgeItemReference,
    ) -> _PreparedKnowledgeReference:
        payload = provider.fetch(
            reference
        )

        item = provider.to_knowledge_item(
            reference,
            payload,
        )

        validate_transformed_item(
            provider,
            reference,
            item,
        )

        previous = (
            self._repository.get_current(
                item.source_key,
                item.external_id,
            )
        )

        decision = classify_knowledge_revision(
            previous=previous,
            current=item,
        )

        structure_supported = isinstance(
            provider,
            KnowledgeStructuredProvider,
        )

        structure = None

        # La estructuración solo se activa cuando el caller ha
        # inyectado explícitamente un repositorio estructural.
        #
        # Así preservamos compatibilidad completa con el pipeline
        # V1 existente para cualquier provider.
        if (
            structure_supported
            and self._structure_repository
            is not None
        ):
            structure = (
                provider.to_structured_document(
                    reference,
                    payload,
                )
            )

            validate_structured_document(
                provider,
                reference,
                item,
                structure,
            )

        return _PreparedKnowledgeReference(
            item=item,
            decision=decision,
            structure_supported=(
                structure_supported
            ),
            structure=structure,
        )

    def preview_reference(
        self,
        provider: KnowledgeProvider,
        reference: KnowledgeItemReference,
    ) -> KnowledgeIngestionPreview:
        """Clasifica una referencia sin persistirla."""

        prepared = (
            self._prepare_reference(
                provider,
                reference,
            )
        )

        item = prepared.item
        decision = prepared.decision

        return KnowledgeIngestionPreview(
            canonical_key=item.canonical_key,
            status=decision.status,
            content_sha256=(
                item.content_sha256
            ),
            source_revision=(
                item.source_revision
            ),
        )

    def ingest_reference(
        self,
        provider: KnowledgeProvider,
        reference: KnowledgeItemReference,
    ) -> KnowledgeIngestionResult:
        prepared = (
            self._prepare_reference(
                provider,
                reference,
            )
        )

        item = prepared.item
        decision = prepared.decision

        # La estructura ya ha sido construida y validada antes
        # de esta primera escritura.
        write_result = (
            self._repository.persist(
                item,
                decision,
            )
        )

        structure_result = None

        if (
            prepared.structure
            is not None
        ):
            assert (
                self._structure_repository
                is not None
            )

            structure_result = (
                self._structure_repository.persist(
                    prepared.structure
                )
            )

        if (
            write_result.status
            is not decision.status
        ):
            raise RuntimeError(
                "KnowledgeRepository devolvió "
                "un estado distinto de la decisión "
                "de revisión"
            )

        if (
            write_result.canonical_key
            != item.canonical_key
        ):
            raise RuntimeError(
                "KnowledgeRepository devolvió "
                "canonical_key incompatible"
            )

        return KnowledgeIngestionResult(
            canonical_key=item.canonical_key,
            status=decision.status,
            revision_number=(
                write_result.revision_number
            ),
            written=write_result.written,
            content_sha256=(
                item.content_sha256
            ),
            source_revision=(
                item.source_revision
            ),
            structure_supported=(
                prepared.structure_supported
            ),
            structure_written=(
                structure_result.written
                if structure_result
                is not None
                else False
            ),
            structure_block_count=(
                structure_result.block_count
                if structure_result
                is not None
                else 0
            ),
            structure_version_count=(
                structure_result.version_count
                if structure_result
                is not None
                else 0
            ),
        )

    def discover_and_ingest(
        self,
        provider: KnowledgeProvider,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> KnowledgeIngestionBatchResult:
        if limit is not None:
            if (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or limit <= 0
            ):
                raise ValueError(
                    "limit debe ser entero positivo"
                )

        batch = provider.discover(
            cursor=cursor
        )

        validate_discovery_batch(
            provider,
            batch,
        )

        references = tuple(
            batch.items
        )

        selected = (
            references
            if limit is None
            else references[:limit]
        )

        results = tuple(
            self.ingest_reference(
                provider,
                reference,
            )
            for reference in selected
        )

        written_count = sum(
            1
            for result in results
            if result.written
        )

        unchanged_count = sum(
            1
            for result in results
            if (
                result.status
                is KnowledgeRevisionStatus.UNCHANGED
            )
        )

        return KnowledgeIngestionBatchResult(
            source_key=provider.source_key,
            discovered_count=len(
                references
            ),
            attempted_count=len(
                selected
            ),
            written_count=written_count,
            unchanged_count=unchanged_count,
            next_cursor=batch.next_cursor,
            results=results,
            structured_written_count=sum(
                1
                for result in results
                if result.structure_written
            ),
        )
