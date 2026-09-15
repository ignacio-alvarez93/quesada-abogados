"""Resolución temporal provider-neutral para Knowledge jurídico.

Responde una pregunta fundamental:

    ¿qué versión de este bloque jurídico estaba vigente
    en una fecha concreta?

Principios:

- usa únicamente ``effective_from`` preservado del provider;
- no inventa ni persiste ``effective_to``;
- no usa ``is_current`` para resolver el pasado;
- datos temporales incompletos o ambiguos fallan cerrados;
- la semántica es independiente de BOE/EUR-Lex.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .legal_structure import (
    KnowledgeBlockVersion,
    KnowledgeStructuredDocument,
)
from .structure_repository import (
    KnowledgeStructureRepository,
)


class KnowledgeTemporalResolutionStatus(
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

    BEFORE_FIRST_EFFECTIVE = (
        "BEFORE_FIRST_EFFECTIVE"
    )

    INCOMPLETE_EFFECTIVE_DATES = (
        "INCOMPLETE_EFFECTIVE_DATES"
    )

    NON_MONOTONIC_TIMELINE = (
        "NON_MONOTONIC_TIMELINE"
    )

    AMBIGUOUS_EFFECTIVE_DATE = (
        "AMBIGUOUS_EFFECTIVE_DATE"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeTemporalResolution:
    source_key: str
    external_id: str
    block_id: str

    as_of: date

    status: (
        KnowledgeTemporalResolutionStatus
    )

    version: (
        KnowledgeBlockVersion
        | None
    ) = None

    reason: str = ""

    @property
    def resolved(
        self,
    ) -> bool:
        return (
            self.status
            is (
                KnowledgeTemporalResolutionStatus.RESOLVED
            )
            and self.version
            is not None
        )

    @property
    def block_canonical_key(
        self,
    ) -> str:
        return (
            f"{self.source_key}:"
            f"{self.external_id}"
            f"#block:{self.block_id}"
        )


def _resolution(
    *,
    document: KnowledgeStructuredDocument,
    block_id: str,
    as_of: date,
    status: KnowledgeTemporalResolutionStatus,
    version: KnowledgeBlockVersion | None = None,
    reason: str = "",
) -> KnowledgeTemporalResolution:
    return KnowledgeTemporalResolution(
        source_key=document.source_key,
        external_id=document.external_id,
        block_id=block_id,
        as_of=as_of,
        status=status,
        version=version,
        reason=reason,
    )


def resolve_block_version_at(
    document: KnowledgeStructuredDocument,
    block_id: str,
    as_of: date,
) -> KnowledgeTemporalResolution:
    """Resuelve la versión aplicable usando fechas de inicio oficiales."""

    if not isinstance(
        document,
        KnowledgeStructuredDocument,
    ):
        raise TypeError(
            "document debe ser "
            "KnowledgeStructuredDocument"
        )

    identifier = str(
        block_id or ""
    ).strip()

    if not identifier:
        raise ValueError(
            "block_id no puede estar vacío"
        )

    if (
        not isinstance(
            as_of,
            date,
        )
    ):
        raise TypeError(
            "as_of debe ser datetime.date"
        )

    block_exists = any(
        block.block_id
        == identifier
        for block
        in document.blocks
    )

    if not block_exists:
        return _resolution(
            document=document,
            block_id=identifier,
            as_of=as_of,
            status=(
                KnowledgeTemporalResolutionStatus.BLOCK_NOT_FOUND
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

    if not versions:
        return _resolution(
            document=document,
            block_id=identifier,
            as_of=as_of,
            status=(
                KnowledgeTemporalResolutionStatus.BLOCK_NOT_FOUND
            ),
            reason=(
                "El bloque no contiene versiones."
            ),
        )

    if any(
        version.effective_from
        is None
        for version
        in versions
    ):
        return _resolution(
            document=document,
            block_id=identifier,
            as_of=as_of,
            status=(
                KnowledgeTemporalResolutionStatus.INCOMPLETE_EFFECTIVE_DATES
            ),
            reason=(
                "Existe al menos una versión "
                "sin effective_from oficial."
            ),
        )

    ordered = tuple(
        sorted(
            versions,
            key=lambda version: (
                version.version_position
            ),
        )
    )

    previous_date = None

    for version in ordered:
        effective_from = (
            version.effective_from
        )

        assert (
            effective_from
            is not None
        )

        if (
            previous_date
            is not None
            and effective_from
            < previous_date
        ):
            return _resolution(
                document=document,
                block_id=identifier,
                as_of=as_of,
                status=(
                    KnowledgeTemporalResolutionStatus.NON_MONOTONIC_TIMELINE
                ),
                reason=(
                    "El orden de versiones "
                    "contradice effective_from."
                ),
            )

        previous_date = (
            effective_from
        )

    candidates = tuple(
        version
        for version
        in ordered
        if (
            version.effective_from
            is not None
            and version.effective_from
            <= as_of
        )
    )

    if not candidates:
        return _resolution(
            document=document,
            block_id=identifier,
            as_of=as_of,
            status=(
                KnowledgeTemporalResolutionStatus.BEFORE_FIRST_EFFECTIVE
            ),
            reason=(
                "La fecha consultada es anterior "
                "a la primera vigencia conocida."
            ),
        )

    latest_effective = max(
        version.effective_from
        for version
        in candidates
        if version.effective_from
        is not None
    )

    latest = tuple(
        version
        for version
        in candidates
        if (
            version.effective_from
            == latest_effective
        )
    )

    if len(
        latest
    ) != 1:
        return _resolution(
            document=document,
            block_id=identifier,
            as_of=as_of,
            status=(
                KnowledgeTemporalResolutionStatus.AMBIGUOUS_EFFECTIVE_DATE
            ),
            reason=(
                "Más de una versión comparte "
                "la fecha efectiva resolutiva."
            ),
        )

    return _resolution(
        document=document,
        block_id=identifier,
        as_of=as_of,
        status=(
            KnowledgeTemporalResolutionStatus.RESOLVED
        ),
        version=latest[0],
        reason=(
            "Versión resuelta mediante la "
            "última effective_from oficial "
            "no posterior a la fecha consultada."
        ),
    )


class KnowledgeTemporalService:
    """Consulta temporal sobre estructura persistida."""

    def __init__(
        self,
        repository: KnowledgeStructureRepository,
    ) -> None:
        if not isinstance(
            repository,
            KnowledgeStructureRepository,
        ):
            raise TypeError(
                "repository debe implementar "
                "KnowledgeStructureRepository"
            )

        self._repository = repository

    def resolve_block_at(
        self,
        source_key: str,
        external_id: str,
        block_id: str,
        as_of: date,
    ) -> KnowledgeTemporalResolution:

        identifier = str(
            block_id or ""
        ).strip()

        if not identifier:
            raise ValueError(
                "block_id no puede estar vacío"
            )

        if not isinstance(
            as_of,
            date,
        ):
            raise TypeError(
                "as_of debe ser datetime.date"
            )

        document = (
            self._repository.get_document(
                source_key,
                external_id,
            )
        )

        if document is None:
            return KnowledgeTemporalResolution(
                source_key=str(
                    source_key or ""
                ).strip(),
                external_id=str(
                    external_id or ""
                ).strip(),
                block_id=identifier,
                as_of=as_of,
                status=(
                    KnowledgeTemporalResolutionStatus.DOCUMENT_NOT_FOUND
                ),
                version=None,
                reason=(
                    "No existe estructura jurídica "
                    "persistida para la identidad."
                ),
            )

        return resolve_block_version_at(
            document,
            identifier,
            as_of,
        )
