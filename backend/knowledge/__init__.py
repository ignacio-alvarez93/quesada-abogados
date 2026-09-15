"""Dominio Knowledge de Quesada Abogados."""

from .catalog import (
    KnowledgeCatalogEntry,
    KnowledgeCatalogTier,
    build_knowledge_catalog_entry,
)
from .catalog_repository import (
    KnowledgeCatalogRepository,
    KnowledgeCatalogWriteResult,
    KnowledgeCatalogWriteStatus,
)
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
from .relation_discovery import (
    KnowledgeRelationDiscoveryResult,
    KnowledgeRelationDiscoveryService,
    resolve_relation_source_key,
)
from .revisions import (
    KnowledgeRevisionDecision,
    KnowledgeRevisionStatus,
    classify_knowledge_revision,
    knowledge_record_sha256,
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
    BOE_CONSOLIDATED_SOURCE,
    BOE_SOURCE,
    get_knowledge_source,
    knowledge_source_exists,
    list_knowledge_sources,
    normalize_source_key,
)

__all__ = [
    "resolve_relation_source_key",
    "KnowledgeRelationDiscoveryService",
    "KnowledgeRelationDiscoveryResult",
    "build_knowledge_catalog_entry",
    "KnowledgeCatalogWriteStatus",
    "KnowledgeCatalogWriteResult",
    "KnowledgeCatalogTier",
    "KnowledgeCatalogRepository",
    "KnowledgeCatalogEntry",
    "BOE_CONSOLIDATED_SOURCE",
    "BOE_SOURCE",
    "KnowledgeAuthority",
    "KnowledgeDiscoveryBatch",
    "KnowledgeItem",
    "KnowledgeItemKind",
    "KnowledgeItemReference",
    "KnowledgeProvider",
    "KnowledgeRevisionDecision",
    "KnowledgeRevisionStatus",
    "KnowledgeSourceDefinition",
    "KnowledgeSourceKind",
    "build_knowledge_item",
    "classify_knowledge_revision",
    "compute_content_sha256",
    "get_knowledge_source",
    "knowledge_record_sha256",
    "knowledge_source_exists",
    "list_knowledge_sources",
    "normalize_knowledge_text",
    "normalize_source_key",
    "validate_discovery_batch",
    "validate_provider_source",
    "validate_transformed_item",
]
