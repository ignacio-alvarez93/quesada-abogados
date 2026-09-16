"""Archivo histórico autoritativo de artículos EUR-Lex.

Esta capa NO persiste datos.

Responsabilidades:

- descubrir el catálogo consolidado completo publicado por Cellar;
- exigir revisiones fechadas y ordenarlas cronológicamente;
- recuperar la representación española de cada revisión;
- construir snapshots estructurales de todas las revisiones;
- construir la historia temporal únicamente sobre el catálogo completo;
- exponer una huella del catálogo usado;
- impedir silenciosamente backfills/rewrite cuando exista
  posteriormente un catálogo previamente materializado.

El builder genérico ``build_eurlex_article_history`` continúa siendo
útil para tests, análisis parciales y composición pura, pero una futura
ruta de persistencia EUR-Lex deberá consumir este contrato autoritativo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol

from .article_history import (
    EurLexArticleHistory,
    build_eurlex_article_history,
)
from .article_structure import (
    EurLexArticleSnapshot,
    parse_eurlex_article_snapshot,
)
from .parser import (
    consolidated_revision_date,
    list_consolidated_celex_revisions,
    normalize_celex,
    parse_tree_notice_identifiers,
)


class EurLexAuthoritativeArchiveTransport(
    Protocol
):
    """Puerto mínimo para materializar el archivo histórico completo."""

    def fetch_tree_notice(
        self,
        celex: str,
    ):
        ...

    def fetch_consolidated_content(
        self,
        consolidated_celex: str,
    ):
        ...


def _chronological_catalogue(
    *,
    original_celex: str,
    tree_notice_xml: bytes,
) -> tuple[str, ...]:
    original = normalize_celex(
        original_celex
    )

    if original.startswith(
        "0"
    ):
        raise ValueError(
            "Archivo autoritativo EUR-Lex "
            "requiere CELEX original"
        )

    if not isinstance(
        tree_notice_xml,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "EUR-Lex tree notice debe ser bytes"
        )

    identifiers = (
        parse_tree_notice_identifiers(
            bytes(
                tree_notice_xml
            )
        )
    )

    candidates = (
        list_consolidated_celex_revisions(
            original,
            identifiers,
        )
    )

    if not candidates:
        raise ValueError(
            "EUR-Lex no expone revisiones "
            "consolidadas para el acto"
        )

    dated = []

    for revision in candidates:
        effective_from = (
            consolidated_revision_date(
                revision
            )
        )

        if effective_from is None:
            raise ValueError(
                "Catálogo EUR-Lex contiene "
                "revisión consolidada sin fecha: "
                f"{revision}"
            )

        dated.append(
            (
                effective_from,
                revision,
            )
        )

    dated.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    dates = tuple(
        item[0]
        for item
        in dated
    )

    if (
        len(
            dates
        )
        != len(
            set(
                dates
            )
        )
    ):
        raise ValueError(
            "Catálogo EUR-Lex contiene "
            "fechas de revisión duplicadas"
        )

    return tuple(
        revision
        for _,
        revision
        in dated
    )


def _validate_chronological_revisions(
    revisions,
    *,
    field_name: str,
) -> tuple[str, ...]:
    values = tuple(
        normalize_celex(
            revision
        )
        for revision
        in revisions
    )

    if not values:
        return ()

    dated = []

    for revision in values:
        if not revision.startswith(
            "0"
        ):
            raise ValueError(
                f"{field_name} requiere "
                "CELEX consolidados sector 0"
            )

        effective_from = (
            consolidated_revision_date(
                revision
            )
        )

        if effective_from is None:
            raise ValueError(
                f"{field_name} contiene "
                "revisión sin fecha: "
                f"{revision}"
            )

        dated.append(
            effective_from
        )

    if (
        len(
            dated
        )
        != len(
            set(
                dated
            )
        )
    ):
        raise ValueError(
            f"{field_name} contiene "
            "fechas duplicadas"
        )

    if tuple(
        dated
    ) != tuple(
        sorted(
            dated
        )
    ):
        raise ValueError(
            f"{field_name} debe estar "
            "ordenado cronológicamente"
        )

    return values


def validate_eurlex_catalogue_append_only(
    previous_revisions,
    current_revisions,
) -> tuple[str, ...]:
    """Valida crecimiento histórico monotónico.

    Una actualización ordinaria puede:

        [2016, 2017]
        ->
        [2016, 2017, 2024]

    No puede integrar silenciosamente:

        [2017, 2024]
        ->
        [2016, 2017, 2024]

    ni eliminar/reordenar/reemplazar una frontera histórica.

    Ese caso requiere reconciliación gobernada antes de persistir.
    """

    previous = (
        _validate_chronological_revisions(
            previous_revisions,
            field_name=(
                "previous_revisions"
            ),
        )
    )

    current = (
        _validate_chronological_revisions(
            current_revisions,
            field_name=(
                "current_revisions"
            ),
        )
    )

    if not previous:
        return current

    if len(
        current
    ) < len(
        previous
    ):
        raise ValueError(
            "EUR-Lex catalogue historical rewrite: "
            "el catálogo actual perdió revisiones"
        )

    if (
        current[
            :len(
                previous
            )
        ]
        != previous
    ):
        raise ValueError(
            "EUR-Lex catalogue historical backfill "
            "or rewrite detected"
        )

    return current


@dataclass(
    frozen=True,
    slots=True,
)
class EurLexAuthoritativeArticleArchive:
    """Historia de artículos construida sobre todo el catálogo Cellar."""

    original_celex: str

    catalogue_revisions: tuple[
        str,
        ...,
    ]

    snapshots: tuple[
        EurLexArticleSnapshot,
        ...,
    ]

    history: EurLexArticleHistory

    catalogue_sha256: str = field(
        init=False
    )

    def __post_init__(
        self,
    ) -> None:
        original = normalize_celex(
            self.original_celex
        )

        catalogue = (
            _validate_chronological_revisions(
                self.catalogue_revisions,
                field_name=(
                    "catalogue_revisions"
                ),
            )
        )

        snapshots = tuple(
            self.snapshots
        )

        if not catalogue:
            raise ValueError(
                "Archivo autoritativo requiere "
                "al menos una revisión"
            )

        if (
            len(
                snapshots
            )
            != len(
                catalogue
            )
        ):
            raise ValueError(
                "Snapshots EUR-Lex no cubren "
                "todo el catálogo"
            )

        snapshot_revisions = tuple(
            snapshot.consolidated_celex
            for snapshot
            in snapshots
        )

        if (
            snapshot_revisions
            != catalogue
        ):
            raise ValueError(
                "Snapshots EUR-Lex no coinciden "
                "con el catálogo autoritativo"
            )

        if (
            self.history.original_celex
            != original
        ):
            raise ValueError(
                "Historia EUR-Lex pertenece "
                "a otro acto original"
            )

        if (
            self.history.revisions
            != catalogue
        ):
            raise ValueError(
                "Historia EUR-Lex no cubre "
                "todo el catálogo autoritativo"
            )

        serialized = "\n".join(
            catalogue
        )

        object.__setattr__(
            self,
            "original_celex",
            original,
        )

        object.__setattr__(
            self,
            "catalogue_revisions",
            catalogue,
        )

        object.__setattr__(
            self,
            "snapshots",
            snapshots,
        )

        object.__setattr__(
            self,
            "catalogue_sha256",
            sha256(
                serialized.encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

    @property
    def oldest_revision(
        self,
    ) -> str:
        return self.catalogue_revisions[
            0
        ]

    @property
    def latest_revision(
        self,
    ) -> str:
        return self.catalogue_revisions[
            -1
        ]


def build_authoritative_eurlex_article_archive(
    *,
    original_celex: str,
    transport: EurLexAuthoritativeArchiveTransport,
) -> EurLexAuthoritativeArticleArchive:
    """Materializa historia de artículos desde TODO el catálogo oficial.

    Si una revisión catalogada no dispone de representación española
    utilizable, la excepción del transporte se propaga. No se permite
    construir una historia "autoritative" saltando revisiones.
    """

    original = normalize_celex(
        original_celex
    )

    if original.startswith(
        "0"
    ):
        raise ValueError(
            "Archivo autoritativo EUR-Lex "
            "requiere CELEX original"
        )

    notice = transport.fetch_tree_notice(
        original
    )

    notice_body = getattr(
        notice,
        "body",
        None,
    )

    if not isinstance(
        notice_body,
        (
            bytes,
            bytearray,
        ),
    ):
        raise TypeError(
            "fetch_tree_notice debe devolver "
            "respuesta con body bytes"
        )

    catalogue = (
        _chronological_catalogue(
            original_celex=original,
            tree_notice_xml=bytes(
                notice_body
            ),
        )
    )

    snapshots = []

    for revision in catalogue:
        response = (
            transport.fetch_consolidated_content(
                revision
            )
        )

        body = getattr(
            response,
            "body",
            None,
        )

        if not isinstance(
            body,
            (
                bytes,
                bytearray,
            ),
        ):
            raise TypeError(
                "fetch_consolidated_content debe "
                "devolver respuesta con body bytes"
            )

        snapshots.append(
            parse_eurlex_article_snapshot(
                bytes(
                    body
                ),
                original_celex=original,
                consolidated_celex=revision,
            )
        )

    snapshots_tuple = tuple(
        snapshots
    )

    history = (
        build_eurlex_article_history(
            snapshots_tuple
        )
    )

    return (
        EurLexAuthoritativeArticleArchive(
            original_celex=original,
            catalogue_revisions=(
                catalogue
            ),
            snapshots=(
                snapshots_tuple
            ),
            history=history,
        )
    )
