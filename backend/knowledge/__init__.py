"""Dominio Knowledge de Quesada Abogados."""

from .contracts import (
    KnowledgeAuthority,
    KnowledgeItemKind,
    KnowledgeSourceDefinition,
    KnowledgeSourceKind,
)
from .items import (
    KnowledgeItem,
    build_knowledge_item,
    compute_content_sha256,
    normalize_knowledge_text,
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
    "KnowledgeItem",
    "KnowledgeItemKind",
    "KnowledgeSourceDefinition",
    "KnowledgeSourceKind",
    "build_knowledge_item",
    "compute_content_sha256",
    "get_knowledge_source",
    "knowledge_source_exists",
    "list_knowledge_sources",
    "normalize_knowledge_text",
    "normalize_source_key",
]
