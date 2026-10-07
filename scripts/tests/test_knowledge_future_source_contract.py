"""Prueba de extensibilidad: una fuente nueva debe poder entrar en el
motor de Knowledge (KnowledgeIngestionService + KnowledgeRepository)
sin ninguna rama específica de fuente en el núcleo.

El único punto de acoplamiento admitido es el registro canónico de
fuentes (source_registry). Este test registra temporalmente una
fuente futura ficticia mediante monkeypatch, implementa un provider
100% fake (sin HTTP, sin scraping) y verifica que el pipeline
completo de ingestión (discover -> fetch -> to_knowledge_item ->
persist) funciona igual que para BOE/EUR-Lex, sin tocar
ingestion.py, repository.py, providers.py ni sqlite_repository.py.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.knowledge import (
    KnowledgeAuthority,
    KnowledgeDiscoveryBatch,
    KnowledgeItemKind,
    KnowledgeItemReference,
    KnowledgeProvider,
    KnowledgeSourceDefinition,
    KnowledgeSourceKind,
    build_knowledge_item,
)
from backend.knowledge import source_registry
from backend.knowledge.ingestion import KnowledgeIngestionService
from backend.knowledge.revisions import KnowledgeRevisionStatus
from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


FUTURE_SOURCE = KnowledgeSourceDefinition(
    key="FUTURE_TEST_SOURCE",
    provider="FUTURE_TEST_SOURCE",
    display_name="Fuente futura de prueba de extensibilidad",
    source_kind=KnowledgeSourceKind.EXTERNAL_GUIDANCE,
    authority=KnowledgeAuthority.EXTERNAL_REFERENCE,
)


@pytest.fixture()
def registered_future_source(monkeypatch):
    """Registra una fuente futura solo para la duración del test.

    No modifica el registro canónico de producción: usa monkeypatch
    sobre el dict interno para simular exactamente el único paso de
    integración que requeriría una fuente real nueva.
    """

    patched_sources = dict(source_registry._SOURCES)
    patched_sources[FUTURE_SOURCE.key] = FUTURE_SOURCE

    monkeypatch.setattr(
        source_registry,
        "_SOURCES",
        patched_sources,
    )

    return FUTURE_SOURCE


class FakeFutureSourceTransport:
    """Doble de un futuro transporte de red (fixture-based, sin HTTP)."""

    def __init__(self):
        self.text = "Contenido de prueba de la fuente futura."
        self.revision = "rev-1"

    def discover(self):
        return (
            {
                "id": "FUTURE-0001",
                "url": "https://example.invalid/future/0001",
            },
        )

    def fetch(self, external_id: str):
        if external_id != "FUTURE-0001":
            raise KeyError(external_id)

        return {
            "id": external_id,
            "title": "Documento futuro de prueba",
            "text": self.text,
            "published_on": date(2026, 9, 28),
            "revision": self.revision,
        }


class FakeFutureSourceProvider:
    """Provider mínimo que satisface KnowledgeProvider genéricamente.

    No hereda de ningún tipo base de BOE/EUR-Lex: demuestra que el
    contrato es estructural (Protocol), no por herencia.
    """

    def __init__(self, transport: FakeFutureSourceTransport):
        self._transport = transport

    @property
    def source_key(self) -> str:
        return FUTURE_SOURCE.key

    def discover(self, *, cursor=None) -> KnowledgeDiscoveryBatch:
        references = tuple(
            KnowledgeItemReference(
                source_key=self.source_key,
                external_id=raw["id"],
                canonical_uri=raw["url"],
            )
            for raw in self._transport.discover()
        )

        return KnowledgeDiscoveryBatch(
            source_key=self.source_key,
            items=references,
            next_cursor=None,
        )

    def fetch(self, reference: KnowledgeItemReference):
        if reference.source_key != self.source_key:
            raise ValueError(
                "FakeFutureSourceProvider solo acepta "
                "referencias de su propia fuente"
            )

        return self._transport.fetch(reference.external_id)

    def to_knowledge_item(self, reference, payload):
        if reference.source_key != self.source_key:
            raise ValueError(
                "FakeFutureSourceProvider solo transforma "
                "referencias de su propia fuente"
            )

        return build_knowledge_item(
            source_key=self.source_key,
            external_id=reference.external_id,
            title=payload["title"],
            item_kind=KnowledgeItemKind.GUIDANCE,
            content_text=payload["text"],
            canonical_uri=reference.canonical_uri,
            source_revision=payload["revision"],
            published_on=payload["published_on"],
        )


def test_future_source_satisfies_generic_provider_protocol(
    registered_future_source,
):
    provider = FakeFutureSourceProvider(
        FakeFutureSourceTransport()
    )

    assert isinstance(provider, KnowledgeProvider)
    assert provider.source_key == "FUTURE_TEST_SOURCE"


def test_future_source_flows_through_ingestion_engine_unmodified(
    tmp_path,
    registered_future_source,
):
    repository = SQLiteKnowledgeRepository(
        tmp_path / "future_source.db"
    )
    repository.initialize_schema()

    service = KnowledgeIngestionService(repository)

    provider = FakeFutureSourceProvider(
        FakeFutureSourceTransport()
    )

    first = service.discover_and_ingest(provider)

    assert first.source_key == "FUTURE_TEST_SOURCE"
    assert first.discovered_count == 1
    assert first.written_count == 1
    assert (
        first.results[0].status
        is KnowledgeRevisionStatus.NEW
    )

    stored = repository.get_current(
        "FUTURE_TEST_SOURCE",
        "FUTURE-0001",
    )

    assert stored is not None
    assert stored.content_sha256 == (
        first.results[0].content_sha256
    )

    second = service.discover_and_ingest(provider)

    assert (
        second.results[0].status
        is KnowledgeRevisionStatus.UNCHANGED
    )
    assert second.written_count == 0


def test_future_source_rejected_before_registration():
    """Sin el único paso de integración admitido (registro de la
    fuente), el contrato falla cerrado, tal y como falla para
    cualquier fuente desconocida hoy."""

    with pytest.raises(KeyError):
        KnowledgeItemReference(
            source_key="FUTURE_TEST_SOURCE",
            external_id="FUTURE-0001",
        )
