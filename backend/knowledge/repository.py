"""Puerto provider-neutral de persistencia para Knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .items import KnowledgeItem
from .revisions import (
    KnowledgeRevisionDecision,
    KnowledgeRevisionStatus,
)


@dataclass(frozen=True, slots=True)
class KnowledgeRepositoryWriteResult:
    canonical_key: str
    status: KnowledgeRevisionStatus
    revision_number: int
    written: bool


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionSnapshot:
    revision_number: int
    revision_status: KnowledgeRevisionStatus
    item: KnowledgeItem
    record_sha256: str
    observed_at: str


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Contrato que SQLite/PostgreSQL deberán implementar."""

    def initialize_schema(self) -> None:
        ...

    def get_current(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeItem | None:
        ...

    def persist(
        self,
        item: KnowledgeItem,
        decision: KnowledgeRevisionDecision,
    ) -> KnowledgeRepositoryWriteResult:
        ...

    def list_revisions(
        self,
        source_key: str,
        external_id: str,
    ) -> tuple[KnowledgeRevisionSnapshot, ...]:
        ...
