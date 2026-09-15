"""Puerto provider-neutral de persistencia estructural Knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .legal_structure import (
    KnowledgeStructuredDocument,
)


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeStructureWriteResult:
    canonical_key: str

    block_count: int
    version_count: int

    inserted_blocks: int
    updated_blocks: int

    inserted_versions: int
    updated_versions: int

    written: bool


@runtime_checkable
class KnowledgeStructureRepository(
    Protocol
):
    """Persistencia intercambiable de bloques/versiones jurídicas."""

    def initialize_schema(
        self,
    ) -> None:
        ...

    def get_document(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeStructuredDocument | None:
        ...

    def persist(
        self,
        document: KnowledgeStructuredDocument,
    ) -> KnowledgeStructureWriteResult:
        ...
