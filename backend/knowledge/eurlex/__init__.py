"""Integración EUR-Lex de Knowledge.

La capa EUR-Lex mantiene separados:

- EUR_LEX:
  acto oficial original;

- EUR_LEX_CONSOLIDATED:
  representación consolidada informativa.

Este paquete no modifica los contratos provider-neutral de Knowledge.
"""

from .parser import (
    EUR_LEX_CONSOLIDATED_SOURCE_KEY,
    EUR_LEX_SOURCE_KEY,
    consolidated_base_celex,
    consolidated_revision_date,
    is_consolidated_celex,
    normalize_celex,
    parse_tree_notice_eli_uris,
    parse_tree_notice_identifiers,
    select_latest_consolidated_celex,
)

__all__ = [
    "EUR_LEX_CONSOLIDATED_SOURCE_KEY",
    "EUR_LEX_SOURCE_KEY",
    "consolidated_base_celex",
    "consolidated_revision_date",
    "is_consolidated_celex",
    "normalize_celex",
    "parse_tree_notice_eli_uris",
    "parse_tree_notice_identifiers",
    "select_latest_consolidated_celex",
]
