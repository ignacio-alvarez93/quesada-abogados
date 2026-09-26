"""Comparación temporal provider-neutral de legislación estructurada.

Compara dos fotografías temporales ya resueltas por Knowledge.

No interpreta jurídicamente el motivo del cambio. Expresa únicamente
diferencias estructurales demostrables entre snapshots:

- ADDED: bloque ausente en A y presente en B;
- REMOVED: bloque presente en A y ausente en B;
- MODIFIED: mismo bloque, distinta versión canónica.

No realiza persistencia, HTTP, UI ni procesamiento IA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .legal_structure import (
    KnowledgeBlockVersion,
    KnowledgeStructuredDocument,
)
from .temporal import (
    KnowledgeTemporalDocumentSnapshot,
    KnowledgeTemporalDocumentStatus,
    KnowledgeTemporalService,
    resolve_document_at,
)


class KnowledgeTemporalBlockChangeKind(
    str,
    Enum,
):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"


class KnowledgeTemporalDiffStatus(
    str,
    Enum,
):
    RESOLVED = "RESOLVED"

    FROM_SNAPSHOT_UNAVAILABLE = (
        "FROM_SNAPSHOT_UNAVAILABLE"
    )

    TO_SNAPSHOT_UNAVAILABLE = (
        "TO_SNAPSHOT_UNAVAILABLE"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeTemporalBlockChange:
    block_id: str

    kind: KnowledgeTemporalBlockChangeKind

    from_position: int | None
    to_position: int | None

    from_title: str
    to_title: str

    from_version: KnowledgeBlockVersion | None
    to_version: KnowledgeBlockVersion | None

    @property
    def from_content_text(
        self,
    ) -> str:
        if self.from_version is None:
            return ""

        return self.from_version.content_text

    @property
    def to_content_text(
        self,
    ) -> str:
        if self.to_version is None:
            return ""

        return self.to_version.content_text


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeTemporalDiff:
    source_key: str
    external_id: str

    from_date: date
    to_date: date

    status: KnowledgeTemporalDiffStatus

    changes: tuple[
        KnowledgeTemporalBlockChange,
        ...,
    ] = ()

    unchanged_count: int = 0

    reason: str = ""

    @property
    def resolved(
        self,
    ) -> bool:
        return (
            self.status
            is KnowledgeTemporalDiffStatus.RESOLVED
        )

    @property
    def added_count(
        self,
    ) -> int:
        return sum(
            1
            for change in self.changes
            if (
                change.kind
                is KnowledgeTemporalBlockChangeKind.ADDED
            )
        )

    @property
    def removed_count(
        self,
    ) -> int:
        return sum(
            1
            for change in self.changes
            if (
                change.kind
                is KnowledgeTemporalBlockChangeKind.REMOVED
            )
        )

    @property
    def modified_count(
        self,
    ) -> int:
        return sum(
            1
            for change in self.changes
            if (
                change.kind
                is KnowledgeTemporalBlockChangeKind.MODIFIED
            )
        )

    @property
    def changed_block_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            change.block_id
            for change
            in self.changes
        )


def _snapshot_is_comparable(
    snapshot: KnowledgeTemporalDocumentSnapshot,
) -> bool:
    return (
        snapshot.status
        in (
            KnowledgeTemporalDocumentStatus.RESOLVED,
            KnowledgeTemporalDocumentStatus.BEFORE_DOCUMENT_EFFECTIVE,
        )
    )


def _snapshot_map(
    snapshot: KnowledgeTemporalDocumentSnapshot,
):
    return {
        block.block_id: block
        for block
        in snapshot.blocks
    }


def compare_temporal_snapshots(
    from_snapshot: KnowledgeTemporalDocumentSnapshot,
    to_snapshot: KnowledgeTemporalDocumentSnapshot,
) -> KnowledgeTemporalDiff:
    """Compara dos snapshots de la misma identidad Knowledge."""

    if not isinstance(
        from_snapshot,
        KnowledgeTemporalDocumentSnapshot,
    ):
        raise TypeError(
            "from_snapshot debe ser "
            "KnowledgeTemporalDocumentSnapshot"
        )

    if not isinstance(
        to_snapshot,
        KnowledgeTemporalDocumentSnapshot,
    ):
        raise TypeError(
            "to_snapshot debe ser "
            "KnowledgeTemporalDocumentSnapshot"
        )

    if (
        from_snapshot.source_key
        != to_snapshot.source_key
        or from_snapshot.external_id
        != to_snapshot.external_id
    ):
        raise ValueError(
            "No pueden compararse snapshots "
            "de identidades distintas"
        )

    if not _snapshot_is_comparable(
        from_snapshot
    ):
        return KnowledgeTemporalDiff(
            source_key=(
                from_snapshot.source_key
            ),
            external_id=(
                from_snapshot.external_id
            ),
            from_date=(
                from_snapshot.as_of
            ),
            to_date=(
                to_snapshot.as_of
            ),
            status=(
                KnowledgeTemporalDiffStatus.FROM_SNAPSHOT_UNAVAILABLE
            ),
            reason=(
                "La fotografía inicial no puede "
                "resolverse con certeza."
            ),
        )

    if not _snapshot_is_comparable(
        to_snapshot
    ):
        return KnowledgeTemporalDiff(
            source_key=(
                from_snapshot.source_key
            ),
            external_id=(
                from_snapshot.external_id
            ),
            from_date=(
                from_snapshot.as_of
            ),
            to_date=(
                to_snapshot.as_of
            ),
            status=(
                KnowledgeTemporalDiffStatus.TO_SNAPSHOT_UNAVAILABLE
            ),
            reason=(
                "La fotografía final no puede "
                "resolverse con certeza."
            ),
        )

    before = _snapshot_map(
        from_snapshot
    )

    after = _snapshot_map(
        to_snapshot
    )

    all_block_ids = (
        set(before)
        | set(after)
    )

    changes = []
    unchanged_count = 0

    def sort_key(
        block_id: str,
    ):
        before_block = before.get(
            block_id
        )
        after_block = after.get(
            block_id
        )

        if before_block is not None:
            return (
                before_block.position,
                block_id,
            )

        assert (
            after_block
            is not None
        )

        return (
            after_block.position,
            block_id,
        )

    for block_id in sorted(
        all_block_ids,
        key=sort_key,
    ):
        before_block = before.get(
            block_id
        )

        after_block = after.get(
            block_id
        )

        if (
            before_block is None
            and after_block is not None
        ):
            changes.append(
                KnowledgeTemporalBlockChange(
                    block_id=block_id,
                    kind=(
                        KnowledgeTemporalBlockChangeKind.ADDED
                    ),
                    from_position=None,
                    to_position=(
                        after_block.position
                    ),
                    from_title="",
                    to_title=(
                        after_block.title
                    ),
                    from_version=None,
                    to_version=(
                        after_block.version
                    ),
                )
            )

            continue

        if (
            before_block is not None
            and after_block is None
        ):
            changes.append(
                KnowledgeTemporalBlockChange(
                    block_id=block_id,
                    kind=(
                        KnowledgeTemporalBlockChangeKind.REMOVED
                    ),
                    from_position=(
                        before_block.position
                    ),
                    to_position=None,
                    from_title=(
                        before_block.title
                    ),
                    to_title="",
                    from_version=(
                        before_block.version
                    ),
                    to_version=None,
                )
            )

            continue

        assert (
            before_block is not None
            and after_block is not None
        )

        if (
            before_block.version.version_key
            == after_block.version.version_key
        ):
            unchanged_count += 1
            continue

        changes.append(
            KnowledgeTemporalBlockChange(
                block_id=block_id,
                kind=(
                    KnowledgeTemporalBlockChangeKind.MODIFIED
                ),
                from_position=(
                    before_block.position
                ),
                to_position=(
                    after_block.position
                ),
                from_title=(
                    before_block.title
                ),
                to_title=(
                    after_block.title
                ),
                from_version=(
                    before_block.version
                ),
                to_version=(
                    after_block.version
                ),
            )
        )

    return KnowledgeTemporalDiff(
        source_key=(
            from_snapshot.source_key
        ),
        external_id=(
            from_snapshot.external_id
        ),
        from_date=(
            from_snapshot.as_of
        ),
        to_date=(
            to_snapshot.as_of
        ),
        status=(
            KnowledgeTemporalDiffStatus.RESOLVED
        ),
        changes=tuple(
            changes
        ),
        unchanged_count=(
            unchanged_count
        ),
        reason=(
            "Comparación estructural de dos "
            "fotografías temporales resueltas."
        ),
    )


def compare_document_at_dates(
    document: KnowledgeStructuredDocument,
    from_date: date,
    to_date: date,
) -> KnowledgeTemporalDiff:
    """Resuelve ambas fotografías y las compara."""

    if not isinstance(
        document,
        KnowledgeStructuredDocument,
    ):
        raise TypeError(
            "document debe ser "
            "KnowledgeStructuredDocument"
        )

    if not isinstance(
        from_date,
        date,
    ):
        raise TypeError(
            "from_date debe ser datetime.date"
        )

    if not isinstance(
        to_date,
        date,
    ):
        raise TypeError(
            "to_date debe ser datetime.date"
        )

    return compare_temporal_snapshots(
        resolve_document_at(
            document,
            from_date,
        ),
        resolve_document_at(
            document,
            to_date,
        ),
    )


class KnowledgeTemporalDiffService:
    """Comparación temporal sobre estructura persistida."""

    def __init__(
        self,
        temporal_service: KnowledgeTemporalService,
    ) -> None:
        if not isinstance(
            temporal_service,
            KnowledgeTemporalService,
        ):
            raise TypeError(
                "temporal_service debe ser "
                "KnowledgeTemporalService"
            )

        self._temporal_service = (
            temporal_service
        )

    def compare_document(
        self,
        source_key: str,
        external_id: str,
        from_date: date,
        to_date: date,
    ) -> KnowledgeTemporalDiff:
        return compare_temporal_snapshots(
            self._temporal_service.resolve_document_at(
                source_key,
                external_id,
                from_date,
            ),
            self._temporal_service.resolve_document_at(
                source_key,
                external_id,
                to_date,
            ),
        )
