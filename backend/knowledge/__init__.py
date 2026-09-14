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
from .providers import (
    KnowledgeDiscoveryBatch,
    KnowledgeItemReference,
    KnowledgeProvider,
    validate_discovery_batch,
    validate_provider_source,
    validate_transformed_item,
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
    "KnowledgeDiscoveryBatch",
    "KnowledgeItem",
    "KnowledgeItemKind",
    "KnowledgeItemReference",
    "KnowledgeProvider",
    "KnowledgeSourceDefinition",
    "KnowledgeSourceKind",
    "build_knowledge_item",
    "compute_content_sha256",
    "get_knowledge_source",
    "knowledge_source_exists",
    "list_knowledge_sources",
    "normalize_knowledge_text",
    "normalize_source_key",
    "validate_discovery_batch",
    "validate_provider_source",
    "validate_transformed_item",
]
