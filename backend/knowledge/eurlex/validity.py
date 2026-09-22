"""Resolución de validez documental para EUR-Lex.

La ingestión EUR-Lex actual (``parser.py``) no captura todavía ningún
campo estructurado equivalente a las banderas de derogación/vigencia
de BOE Consolidado (p. ej. "Date of end of validity" de Cellar). Por
tanto este resolver declara ``UNKNOWN`` de forma explícita para toda
identidad EUR-Lex, en lugar de fabricar un estado.

Cuando la ingestión EUR-Lex incorpore esa metadata, este módulo debe
ampliarse siguiendo el mismo patrón que
``boe_consolidated.validity.resolve_boe_consolidated_validity``.

No realiza HTTP, persistencia, UI ni IA.
"""

from __future__ import annotations

from ..items import KnowledgeItem
from ..validity import (
    KnowledgeDocumentValidity,
    unknown_validity,
)
from .parser import (
    EUR_LEX_CONSOLIDATED_SOURCE_KEY,
    EUR_LEX_SOURCE_KEY,
)


_SUPPORTED_SOURCES = frozenset(
    {
        EUR_LEX_SOURCE_KEY,
        EUR_LEX_CONSOLIDATED_SOURCE_KEY,
    }
)


def resolve_eurlex_validity(
    item: KnowledgeItem,
) -> KnowledgeDocumentValidity:
    """Siempre ``UNKNOWN``: EUR-Lex aún no expone evidencia de vigencia."""

    if not isinstance(
        item,
        KnowledgeItem,
    ):
        raise TypeError(
            "item debe ser KnowledgeItem"
        )

    if item.source_key not in _SUPPORTED_SOURCES:
        raise ValueError(
            "resolve_eurlex_validity solo "
            "acepta KnowledgeItem EUR_LEX "
            "o EUR_LEX_CONSOLIDATED"
        )

    return unknown_validity(
        source_key=item.source_key,
        external_id=item.external_id,
        reason=(
            "La ingestión EUR-Lex actual no "
            "captura evidencia estructurada de "
            "derogación/fin de vigencia; el "
            "horizonte de evidencia debe "
            "consultarse por separado."
        ),
    )
