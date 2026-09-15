"""Contratos provider-neutral para fuentes Knowledge.

El dominio distingue expresamente:

discover
    descubre identidades disponibles;

fetch
    obtiene la representación nativa del proveedor;

to_knowledge_item
    transforma esa representación en KnowledgeItem canónico.

Este módulo no conoce HTTP, XML, JSON, HTML, SQLite ni IA.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Protocol,
    TypeVar,
    runtime_checkable,
)

from .items import KnowledgeItem
from .legal_structure import (
    KnowledgeStructuredDocument,
)
from .source_registry import (
    get_knowledge_source,
    normalize_source_key,
)


PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True, slots=True)
class KnowledgeItemReference:
    """Referencia estable a una pieza descubierta en una fuente."""

    source_key: str
    external_id: str
    canonical_uri: str = ""

    def __post_init__(self) -> None:
        source_key = normalize_source_key(self.source_key)

        # Fail-closed: no permitimos referencias a fuentes
        # inexistentes en el registro canónico.
        get_knowledge_source(source_key)

        external_id = str(self.external_id or "").strip()
        canonical_uri = str(self.canonical_uri or "").strip()

        if not external_id:
            raise ValueError(
                "Knowledge reference external_id no puede estar vacío"
            )

        object.__setattr__(self, "source_key", source_key)
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(
            self,
            "canonical_uri",
            canonical_uri,
        )

    @property
    def canonical_key(self) -> str:
        return f"{self.source_key}:{self.external_id}"


@dataclass(frozen=True, slots=True)
class KnowledgeDiscoveryBatch:
    """Resultado inmutable de una operación de descubrimiento."""

    source_key: str
    items: tuple[KnowledgeItemReference, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        source_key = normalize_source_key(self.source_key)
        get_knowledge_source(source_key)

        items = tuple(self.items)

        for item in items:
            if not isinstance(item, KnowledgeItemReference):
                raise TypeError(
                    "Knowledge discovery items deben ser "
                    "KnowledgeItemReference"
                )

            if item.source_key != source_key:
                raise ValueError(
                    "Knowledge discovery batch contiene referencias "
                    "de otra fuente"
                )

        next_cursor = self.next_cursor

        if next_cursor is not None:
            next_cursor = str(next_cursor).strip() or None

        object.__setattr__(self, "source_key", source_key)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "next_cursor", next_cursor)


@runtime_checkable
class KnowledgeProvider(Protocol[PayloadT]):
    """Contrato mínimo de cualquier proveedor Knowledge."""

    @property
    def source_key(self) -> str:
        ...

    def discover(
        self,
        *,
        cursor: str | None = None,
    ) -> KnowledgeDiscoveryBatch:
        ...

    def fetch(
        self,
        reference: KnowledgeItemReference,
    ) -> PayloadT:
        ...

    def to_knowledge_item(
        self,
        reference: KnowledgeItemReference,
        payload: PayloadT,
    ) -> KnowledgeItem:
        ...


def validate_provider_source(
    provider: KnowledgeProvider[Any],
) -> str:
    """Valida y devuelve la fuente canónica de un provider."""

    source_key = normalize_source_key(provider.source_key)
    get_knowledge_source(source_key)
    return source_key


def validate_discovery_batch(
    provider: KnowledgeProvider[Any],
    batch: KnowledgeDiscoveryBatch,
) -> KnowledgeDiscoveryBatch:
    """Impide que un provider publique referencias de otra fuente."""

    source_key = validate_provider_source(provider)

    if batch.source_key != source_key:
        raise ValueError(
            "Knowledge provider devolvió discovery batch "
            "para una fuente distinta"
        )

    for reference in batch.items:
        if reference.source_key != source_key:
            raise ValueError(
                "Knowledge provider devolvió referencia "
                "para una fuente distinta"
            )

    return batch


def validate_transformed_item(
    provider: KnowledgeProvider[Any],
    reference: KnowledgeItemReference,
    item: KnowledgeItem,
) -> KnowledgeItem:
    """Valida provenance e identidad después de canonicalizar."""

    source_key = validate_provider_source(provider)

    if reference.source_key != source_key:
        raise ValueError(
            "Knowledge reference no pertenece al provider"
        )

    if item.source_key != source_key:
        raise ValueError(
            "Knowledge item transformado pertenece a otra fuente"
        )

    if item.external_id != reference.external_id:
        raise ValueError(
            "Knowledge item transformado cambió external_id"
        )

    return item



@runtime_checkable
class KnowledgeStructuredProvider(
    Protocol[PayloadT]
):
    """Capacidad estructural opcional de un KnowledgeProvider.

    Un provider que implemente este contrato puede transformar
    el MISMO payload nativo usado para KnowledgeItem en una
    KnowledgeStructuredDocument provider-neutral.

    KnowledgeProvider continúa siendo el contrato mínimo.
    """

    @property
    def source_key(
        self,
    ) -> str:
        ...

    def to_structured_document(
        self,
        reference: KnowledgeItemReference,
        payload: PayloadT,
    ) -> KnowledgeStructuredDocument:
        ...


def validate_structured_document(
    provider: KnowledgeProvider[Any],
    reference: KnowledgeItemReference,
    item: KnowledgeItem,
    document: KnowledgeStructuredDocument,
) -> KnowledgeStructuredDocument:
    """Valida identidad y coherencia item ↔ estructura.

    Se ejecuta ANTES de persistir el KnowledgeItem para que
    defectos de transformación estructural fallen cerrados
    antes de cualquier escritura de aplicación.
    """

    source_key = validate_provider_source(
        provider
    )

    if not isinstance(
        document,
        KnowledgeStructuredDocument,
    ):
        raise TypeError(
            "Structured provider debe devolver "
            "KnowledgeStructuredDocument"
        )

    if (
        reference.source_key
        != source_key
    ):
        raise ValueError(
            "Knowledge reference no pertenece "
            "al structured provider"
        )

    if (
        item.source_key
        != source_key
        or document.source_key
        != source_key
    ):
        raise ValueError(
            "KnowledgeItem/estructura pertenecen "
            "a otra fuente"
        )

    if (
        item.external_id
        != reference.external_id
        or document.external_id
        != reference.external_id
    ):
        raise ValueError(
            "KnowledgeItem/estructura cambiaron "
            "external_id"
        )

    if (
        document.current_content_text
        != item.content_text
    ):
        raise ValueError(
            "La vista vigente estructurada "
            "no coincide con KnowledgeItem"
        )

    return document
