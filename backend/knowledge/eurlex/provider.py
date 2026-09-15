"""Providers EUR-Lex desacoplados del transporte HTTP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from backend.knowledge import (
    KnowledgeDiscoveryBatch,
    KnowledgeItem,
    KnowledgeItemReference,
)

from .parser import (
    EUR_LEX_CONSOLIDATED_SOURCE_KEY,
    EUR_LEX_SOURCE_KEY,
    normalize_celex,
    parse_eurlex_consolidated_document_payload,
    parse_eurlex_original_document_payload,
)


class EurLexTransport(
    Protocol
):
    def fetch_original(
        self,
        original_celex: str,
    ) -> Mapping[str, object]:
        ...

    def fetch_consolidated(
        self,
        original_celex: str,
    ) -> Mapping[str, object]:
        ...


def _discover_single(
    *,
    source_key: str,
    cursor: str | None,
) -> KnowledgeDiscoveryBatch:
    """Discovery gobernado V1: una identidad CELEX explícita."""

    celex = normalize_celex(
        str(
            cursor or ""
        )
    )

    if celex.startswith(
        "0"
    ):
        raise ValueError(
            "Discovery EUR-Lex requiere "
            "CELEX original sector 1/3/6"
        )

    reference = (
        KnowledgeItemReference(
            source_key=source_key,
            external_id=celex,
        )
    )

    return KnowledgeDiscoveryBatch(
        source_key=source_key,
        items=(
            reference,
        ),
        next_cursor=None,
    )


class EurLexProvider:
    """Acto oficial original EUR-Lex."""

    def __init__(
        self,
        transport: EurLexTransport,
    ) -> None:
        self._transport = transport

    @property
    def source_key(
        self,
    ) -> str:
        return EUR_LEX_SOURCE_KEY

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> KnowledgeDiscoveryBatch:
        return _discover_single(
            source_key=self.source_key,
            cursor=cursor,
        )

    def fetch(
        self,
        reference: KnowledgeItemReference,
    ) -> Mapping[str, object]:
        if (
            reference.source_key
            != self.source_key
        ):
            raise ValueError(
                "EurLexProvider solo acepta "
                "referencias EUR_LEX"
            )

        return (
            self._transport.fetch_original(
                reference.external_id
            )
        )

    def to_knowledge_item(
        self,
        reference: KnowledgeItemReference,
        payload: Mapping[str, object],
    ) -> KnowledgeItem:
        if (
            reference.source_key
            != self.source_key
        ):
            raise ValueError(
                "EurLexProvider solo transforma "
                "referencias EUR_LEX"
            )

        return (
            parse_eurlex_original_document_payload(
                reference,
                payload,
            )
        )


class EurLexConsolidatedProvider:
    """Última revisión consolidada española utilizable."""

    def __init__(
        self,
        transport: EurLexTransport,
    ) -> None:
        self._transport = transport

    @property
    def source_key(
        self,
    ) -> str:
        return (
            EUR_LEX_CONSOLIDATED_SOURCE_KEY
        )

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> KnowledgeDiscoveryBatch:
        return _discover_single(
            source_key=self.source_key,
            cursor=cursor,
        )

    def fetch(
        self,
        reference: KnowledgeItemReference,
    ) -> Mapping[str, object]:
        if (
            reference.source_key
            != self.source_key
        ):
            raise ValueError(
                "EurLexConsolidatedProvider "
                "solo acepta referencias "
                "EUR_LEX_CONSOLIDATED"
            )

        return (
            self._transport.fetch_consolidated(
                reference.external_id
            )
        )

    def to_knowledge_item(
        self,
        reference: KnowledgeItemReference,
        payload: Mapping[str, object],
    ) -> KnowledgeItem:
        if (
            reference.source_key
            != self.source_key
        ):
            raise ValueError(
                "EurLexConsolidatedProvider "
                "solo transforma referencias "
                "EUR_LEX_CONSOLIDATED"
            )

        return (
            parse_eurlex_consolidated_document_payload(
                reference,
                payload,
            )
        )
