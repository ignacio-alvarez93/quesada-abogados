"""Puerto de persistencia del catálogo Knowledge.

Este puerto es independiente de KnowledgeRepository.

KnowledgeRepository conserva contenido y revisiones jurídicas.
KnowledgeCatalogRepository conserva política interna del despacho.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .catalog import (
    KnowledgeCatalogEntry,
    KnowledgeCatalogTier,
)


class KnowledgeCatalogWriteStatus(str, Enum):
    NEW = "NEW"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class KnowledgeCatalogWriteResult:
    canonical_key: str
    status: KnowledgeCatalogWriteStatus
    written: bool


@runtime_checkable
class KnowledgeCatalogRepository(Protocol):
    """Puerto intercambiable SQLite/PostgreSQL del catálogo."""

    def initialize_schema(self) -> None:
        ...

    def get_entry(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeCatalogEntry | None:
        ...

    def upsert(
        self,
        entry: KnowledgeCatalogEntry,
    ) -> KnowledgeCatalogWriteResult:
        ...

    def list_entries(
        self,
        *,
        tier: KnowledgeCatalogTier | None = None,
        watch_only: bool = False,
    ) -> tuple[
        KnowledgeCatalogEntry,
        ...,
    ]:
        ...
