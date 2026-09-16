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
    normalize_eurlex_article_identifier,
    parse_eurlex_article_snapshot,
)

from .provider import (
    EurLexConsolidatedProvider,
    EurLexProvider,
)

__all__ = [
    "parse_eurlex_article_snapshot",
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
]
