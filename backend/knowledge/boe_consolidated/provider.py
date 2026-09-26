"""Provider BOE Legislación Consolidada desacoplado del transporte."""

from __future__ import annotations

import json

from collections.abc import Mapping
from typing import Protocol

from backend.knowledge import (
    KnowledgeDiscoveryBatch,
    KnowledgeItem,
    KnowledgeItemReference,
)

from .parser import (
    SOURCE_KEY,
    parse_boe_consolidated_discovery_payload,
    parse_boe_consolidated_document_payload,
    parse_boe_consolidated_structure,
)


class BoeConsolidatedTransport(
    Protocol
):
    """Puerto requerido por BoeConsolidatedProvider.

    ``cursor`` representa una fecha de última actualización
    en formato AAAAMMDD.
    """

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> Mapping[str, object]:
        ...

    def fetch(
        self,
        external_id: str,
    ) -> Mapping[str, object]:
        ...


class BoeConsolidatedProvider:
    """Adaptador de legislación consolidada BOE a Knowledge."""

    def __init__(
        self,
        transport: BoeConsolidatedTransport,
    ) -> None:
        self._transport = transport

    @property
    def source_key(self) -> str:
        return SOURCE_KEY

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> KnowledgeDiscoveryBatch:
        payload = (
            self._transport.discover(
                cursor=cursor,
            )
        )

        references = (
            parse_boe_consolidated_discovery_payload(
                payload
            )
        )

        return KnowledgeDiscoveryBatch(
            source_key=self.source_key,
            items=references,
            next_cursor=None,
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
                "BoeConsolidatedProvider "
                "solo acepta referencias "
                "BOE_CONSOLIDATED"
            )

        return self._transport.fetch(
            reference.external_id
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
                "BoeConsolidatedProvider "
                "solo transforma referencias "
                "BOE_CONSOLIDATED"
            )

        return (
            parse_boe_consolidated_document_payload(
                reference,
                payload,
            )
        )


    def to_structured_document(
        self,
        reference: KnowledgeItemReference,
        payload: Mapping[str, object],
    ):
        """Transforma el payload BOE en estructura jurídica completa.

        Reutiliza la misma representación nativa obtenida por fetch;
        no realiza una segunda llamada HTTP.
        """

        if (
            reference.source_key
            != self.source_key
        ):
            raise ValueError(
                "BoeConsolidatedProvider "
                "solo estructura referencias "
                "BOE_CONSOLIDATED"
            )

        # Reutilizamos la canonicalización documental para obtener
        # el índice normalizado que ya forma parte de su metadata.
        item = (
            parse_boe_consolidated_document_payload(
                reference,
                payload,
            )
        )

        metadata = dict(
            item.metadata
        )

        raw_index = metadata.get(
            "block_index_json",
            "",
        )

        if not raw_index:
            raise ValueError(
                "BOE Consolidado no produjo "
                "block_index_json"
            )

        block_index = json.loads(
            raw_index
        )

        raw_xml = payload.get(
            "text_xml"
        )

        if not isinstance(
            raw_xml,
            (
                bytes,
                bytearray,
            ),
        ):
            raise TypeError(
                "BOE Consolidado structured "
                "requiere text_xml bytes"
            )

        return (
            parse_boe_consolidated_structure(
                reference.external_id,
                bytes(
                    raw_xml
                ),
                block_index=(
                    block_index
                ),
            )
        )
