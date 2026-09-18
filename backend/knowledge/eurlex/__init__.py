"""Integración EUR-Lex de Knowledge.

La capa EUR-Lex mantiene separados:

- EUR_LEX:
  acto oficial original;

- EUR_LEX_CONSOLIDATED:
  representación consolidada informativa.

Este paquete no modifica los contratos provider-neutral de Knowledge.
"""

from .parser import (
    parse_tree_notice_primary_metadata,
    parse_eurlex_original_document_payload,
    parse_eurlex_document_text,
    parse_eurlex_consolidated_document_payload,
    build_consolidated_eli_uri,
    EUR_LEX_CONSOLIDATED_SOURCE_KEY,
    EUR_LEX_SOURCE_KEY,
    consolidated_base_celex,
    consolidated_revision_date,
    is_consolidated_celex,
    list_consolidated_celex_revisions,
    normalize_celex,
    parse_tree_notice_eli_uris,
    parse_tree_notice_identifiers,
    select_latest_consolidated_celex,
)

from .article_structure import (
    EurLexArticleBlock,
    EurLexArticleSnapshot,
    build_eurlex_article_block_id,
    compute_eurlex_article_semantic_sha256,
    compute_eurlex_article_legal_semantic_sha256,
    normalize_eurlex_article_identifier,
    normalize_eurlex_article_semantic_text,
    normalize_eurlex_article_legal_semantic_text,
    parse_eurlex_article_snapshot,
)

from .article_history import (
    EurLexArticleHistory,
    build_eurlex_article_history,
)

from .full_structure import (
    EurLexFullBlock,
    EurLexFullBlockKind,
    EurLexFullStructureSnapshot,
    parse_eurlex_full_structure_snapshot,
)

from .authoritative_archive import (
    EurLexAuthoritativeArticleArchive,
    build_authoritative_eurlex_article_archive,
    validate_eurlex_catalogue_append_only,
)

from .provider import (
    EurLexConsolidatedProvider,
    EurLexProvider,
)

from .evidence import (
    DEFAULT_EUR_LEX_EVIDENCE_ROOT,
    EUR_LEX_EVIDENCE_PROVIDER,
    EUR_LEX_EVIDENCE_SCHEMA_VERSION,
    EurLexEvidenceArtifact,
    EurLexEvidenceArtifactPaths,
    EurLexEvidenceError,
    EurLexEvidenceIntegrityError,
    acquire_eurlex_consolidated_evidence,
    acquire_eurlex_original_evidence,
    acquire_eurlex_tree_notice_evidence,
    import_eurlex_evidence_file,
    load_eurlex_evidence_artifact,
    save_eurlex_evidence_artifact,
    verify_eurlex_evidence_artifact,
)

from .evidence_catalog import (
    EurLexEvidenceCatalog,
    EurLexEvidenceCatalogEntry,
    EurLexEvidenceCatalogRejection,
    build_eurlex_evidence_catalog,
)

from .forensic_selection import (
    DEFAULT_EUR_LEX_FORENSIC_SELECTION_ROOT,
    EUR_LEX_FORENSIC_SELECTION_SCHEMA_VERSION,
    EurLexForensicSelection,
    EurLexForensicSelectionError,
    EurLexForensicSelectionIntegrityError,
    load_eurlex_forensic_selection,
    select_eurlex_forensic_evidence,
    verify_eurlex_forensic_selection,
)

__all__ = [
    "parse_eurlex_full_structure_snapshot",
    "EurLexFullStructureSnapshot",
    "EurLexFullBlockKind",
    "EurLexFullBlock",
    "validate_eurlex_catalogue_append_only",
    "build_authoritative_eurlex_article_archive",
    "EurLexAuthoritativeArticleArchive",
    "build_eurlex_article_history",
    "EurLexArticleHistory",
    "parse_eurlex_article_snapshot",
    "normalize_eurlex_article_semantic_text",
    "normalize_eurlex_article_legal_semantic_text",
    "compute_eurlex_article_semantic_sha256",
    "compute_eurlex_article_legal_semantic_sha256",
    "normalize_eurlex_article_identifier",
    "build_eurlex_article_block_id",
    "EurLexArticleSnapshot",
    "EurLexArticleBlock",
    "parse_tree_notice_primary_metadata",
    "parse_eurlex_original_document_payload",
    "parse_eurlex_document_text",
    "parse_eurlex_consolidated_document_payload",
    "build_consolidated_eli_uri",
    "EurLexProvider",
    "EurLexConsolidatedProvider",
    "EUR_LEX_CONSOLIDATED_SOURCE_KEY",
    "EUR_LEX_SOURCE_KEY",
    "consolidated_base_celex",
    "consolidated_revision_date",
    "is_consolidated_celex",
    "list_consolidated_celex_revisions",
    "normalize_celex",
    "parse_tree_notice_eli_uris",
    "parse_tree_notice_identifiers",
    "select_latest_consolidated_celex",
    "DEFAULT_EUR_LEX_EVIDENCE_ROOT",
    "EUR_LEX_EVIDENCE_PROVIDER",
    "EUR_LEX_EVIDENCE_SCHEMA_VERSION",
    "EurLexEvidenceArtifact",
    "EurLexEvidenceArtifactPaths",
    "EurLexEvidenceError",
    "EurLexEvidenceIntegrityError",
    "acquire_eurlex_consolidated_evidence",
    "acquire_eurlex_original_evidence",
    "acquire_eurlex_tree_notice_evidence",
    "import_eurlex_evidence_file",
    "load_eurlex_evidence_artifact",
    "save_eurlex_evidence_artifact",
    "verify_eurlex_evidence_artifact",
    "EurLexEvidenceCatalog",
    "EurLexEvidenceCatalogEntry",
    "EurLexEvidenceCatalogRejection",
    "build_eurlex_evidence_catalog",
    "DEFAULT_EUR_LEX_FORENSIC_SELECTION_ROOT",
    "EUR_LEX_FORENSIC_SELECTION_SCHEMA_VERSION",
    "EurLexForensicSelection",
    "EurLexForensicSelectionError",
    "EurLexForensicSelectionIntegrityError",
    "load_eurlex_forensic_selection",
    "select_eurlex_forensic_evidence",
    "verify_eurlex_forensic_selection",
]
