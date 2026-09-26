"""Auditoría de integridad temporal provider-neutral.

Endurece el modelo temporal existente detectando, sin corregirlas
silenciosamente, anomalías que impedirían confiar en una cronología
como evidencia jurídica:

- ``UNDATED_VERSION``: alguna versión carece de ``effective_from``
  oficial;
- ``NON_MONOTONIC_TIMELINE``: el orden de versiones contradice
  ``effective_from``;
- ``DUPLICATE_EFFECTIVE_DATE``: dos versiones del mismo bloque
  comparten fecha efectiva (empate irresoluble sin evidencia
  adicional);
- ``CURRENT_NOT_LATEST``: la versión marcada vigente no es la última
  en orden observado;
- ``VALIDITY_BEFORE_LATEST_EFFECTIVE``: la fecha de fin de vigencia
  declarada por la fuente es anterior a una versión de bloque cuya
  vigencia comienza después. Es un intervalo imposible: no se corrige,
  se reporta para revisión.

Estos códigos ya eran usados por ``KnowledgeQueryService.get_block_history``
y ``get_changes``; este módulo los centraliza para que también puedan
auditarse a nivel de documento completo, incluida su relación con
``KnowledgeDocumentValidity``.

No realiza persistencia, HTTP, UI ni IA.
"""

from __future__ import annotations

from dataclasses import dataclass

from .legal_structure import (
    KnowledgeBlockVersion,
    KnowledgeStructuredDocument,
)
from .validity import (
    KnowledgeDocumentValidity,
    KnowledgeValidityStatus,
)


def block_timeline_issues(
    versions: tuple[
        KnowledgeBlockVersion,
        ...,
    ],
) -> tuple[str, ...]:
    """Códigos de anomalía de la cronología de un único bloque.

    ``versions`` debe llegar ya ordenada por ``version_position``,
    como devuelve ``KnowledgeStructuredDocument.versions_for_block``.
    """

    issues: list[str] = []

    if any(
        version.effective_from is None
        for version in versions
    ):
        issues.append(
            "UNDATED_VERSION"
        )

    dated = [
        version
        for version in versions
        if version.effective_from
        is not None
    ]

    for previous, current in zip(
        dated,
        dated[1:],
    ):
        assert previous.effective_from
        assert current.effective_from

        if (
            current.effective_from
            < previous.effective_from
        ):
            issues.append(
                "NON_MONOTONIC_TIMELINE"
            )
            break

    dates = [
        version.effective_from
        for version in dated
    ]

    if len(dates) != len(
        set(dates)
    ):
        issues.append(
            "DUPLICATE_EFFECTIVE_DATE"
        )

    if versions:
        current_versions = [
            version
            for version in versions
            if version.is_current
        ]

        if (
            current_versions
            and current_versions[0]
            is not versions[-1]
        ):
            issues.append(
                "CURRENT_NOT_LATEST"
            )

    return tuple(issues)


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeDocumentIntegrityReport:
    """Auditoría agregada de integridad temporal de un documento."""

    source_key: str
    external_id: str

    # block_id -> códigos de anomalía de ese bloque.
    block_issues: tuple[
        tuple[
            str,
            tuple[str, ...],
        ],
        ...,
    ] = ()

    # Anomalías que no pertenecen a un único bloque (p. ej. relación
    # entre validez documental y cronología de bloques).
    document_issues: tuple[
        str,
        ...,
    ] = ()

    @property
    def clean(
        self,
    ) -> bool:
        return (
            not self.block_issues
            and not self.document_issues
        )

    @property
    def affected_block_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            block_id
            for block_id, issues
            in self.block_issues
            if issues
        )


def audit_document_temporal_integrity(
    document: KnowledgeStructuredDocument,
    *,
    validity: (
        KnowledgeDocumentValidity
        | None
    ) = None,
) -> KnowledgeDocumentIntegrityReport:
    """Audita cada bloque y, si se aporta, la validez documental.

    ``validity`` es opcional y ortogonal: su ausencia nunca genera una
    anomalía. Cuando se aporta y declara ``end_date``, se comprueba
    que ninguna versión de bloque tenga ``effective_from`` posterior
    a esa fecha, lo que sería un intervalo jurídicamente imposible
    (texto que "entra en vigor" después de que la norma terminó su
    vigencia).
    """

    if not isinstance(
        document,
        KnowledgeStructuredDocument,
    ):
        raise TypeError(
            "document debe ser "
            "KnowledgeStructuredDocument"
        )

    if (
        validity is not None
        and not isinstance(
            validity,
            KnowledgeDocumentValidity,
        )
    ):
        raise TypeError(
            "validity debe ser "
            "KnowledgeDocumentValidity o None"
        )

    block_issues = []

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

        issues = block_timeline_issues(
            versions
        )

        if issues:
            block_issues.append(
                (
                    block.block_id,
                    issues,
                )
            )

    document_issues = []

    if (
        validity is not None
        and validity.status
        in (
            KnowledgeValidityStatus.REPEALED,
            KnowledgeValidityStatus.EXPLICIT_END_OF_VALIDITY,
        )
        and validity.end_date
        is not None
    ):
        for version in document.versions:
            if (
                version.effective_from
                is not None
                and version.effective_from
                > validity.end_date
            ):
                document_issues.append(
                    "VALIDITY_BEFORE_LATEST_EFFECTIVE"
                )
                break

    return KnowledgeDocumentIntegrityReport(
        source_key=document.source_key,
        external_id=document.external_id,
        block_issues=tuple(
            block_issues
        ),
        document_issues=tuple(
            document_issues
        ),
    )
