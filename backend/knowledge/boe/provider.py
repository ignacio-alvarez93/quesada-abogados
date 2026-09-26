"""Provider del diario BOE desacoplado del transporte."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from backend.knowledge import (
    KnowledgeDiscoveryBatch,
    KnowledgeItem,
    KnowledgeItemReference,
)

from .parser import (
    parse_boe_discovery_payload,
    parse_boe_document_payload,
)


class BoeTransport(Protocol):
    """Puerto requerido por BOEProvider.

    Para discovery, cursor representa la fecha AAAAMMDD.
    La implementación HTTP real se añadirá por separado.
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


class BoeProvider:
    """Adaptador de publicaciones diarias BOE a Knowledge."""

    def __init__(
        self,
        transport: BoeTransport,
    ) -> None:
        self._transport = transport

    @property
    def source_key(self) -> str:
        return "BOE"

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> KnowledgeDiscoveryBatch:
        payload = self._transport.discover(
            cursor=cursor,
        )

        references = parse_boe_discovery_payload(
            payload
        )

        # La API oficial del sumario es date-addressed
        # y no documenta paginación.
        return KnowledgeDiscoveryBatch(
            source_key=self.source_key,
            items=references,
            next_cursor=None,
        )

    def fetch(
        self,
        reference: KnowledgeItemReference,
    ) -> Mapping[str, object]:
        if reference.source_key != self.source_key:
            raise ValueError(
                "BOEProvider solo puede obtener referencias BOE"
            )

        return self._transport.fetch(
            reference.external_id
        )

    def to_knowledge_item(
        self,
        reference: KnowledgeItemReference,
        payload: Mapping[str, object],
    ) -> KnowledgeItem:
        if reference.source_key != self.source_key:
            raise ValueError(
                "BOEProvider solo puede transformar referencias BOE"
            )

        return parse_boe_document_payload(
            reference,
            payload,
        )
