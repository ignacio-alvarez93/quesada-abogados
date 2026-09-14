"""Dominio Knowledge de Quesada Abogados."""

from .contracts import (
    KnowledgeAuthority,
    KnowledgeSourceDefinition,
    KnowledgeSourceKind,
)
from .source_registry import (
    BOE_SOURCE,
    get_knowledge_source,
    knowledge_source_exists,
    list_knowledge_sources,
    normalize_source_key,
)

__all__ = [
    "BOE_SOURCE",
    "KnowledgeAuthority",
    "KnowledgeSourceDefinition",
    "KnowledgeSourceKind",
    "get_knowledge_source",
    "knowledge_source_exists",
    "list_knowledge_sources",
    "normalize_source_key",
]
