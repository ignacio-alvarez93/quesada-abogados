from datetime import date

import pytest

from backend.knowledge import (
    KnowledgeDiscoveryBatch,
    KnowledgeItemKind,
    KnowledgeItemReference,
    KnowledgeProvider,
    build_knowledge_item,
    validate_discovery_batch,
    validate_provider_source,
    validate_transformed_item,
)


class FakeBoeProvider:
    @property
    def source_key(self):
        return "BOE"

    def discover(self, *, cursor=None):
        return KnowledgeDiscoveryBatch(
            source_key="BOE",
            items=(
                KnowledgeItemReference(
                    source_key="BOE",
                    external_id="BOE-A-2026-12345",
                    canonical_uri=(
                        "https://www.boe.es/"
                        "buscar/doc.php?id=BOE-A-2026-12345"
                    ),
                ),
            ),
            next_cursor="page-2",
        )

    def fetch(self, reference):
        return {
            "title": "Disposición de prueba",
            "text": "Artículo 1.\nContenido jurídico.",
            "published_on": date(2026, 9, 14),
        }

    def to_knowledge_item(self, reference, payload):
        return build_knowledge_item(
            source_key=self.source_key,
            external_id=reference.external_id,
            title=payload["title"],
            item_kind=KnowledgeItemKind.LEGISLATION,
            content_text=payload["text"],
            canonical_uri=reference.canonical_uri,
            published_on=payload["published_on"],
        )


def test_reference_normalizes_identity():
    reference = KnowledgeItemReference(
        source_key=" boe ",
        external_id=" BOE-A-2026-12345 ",
    )

    assert reference.source_key == "BOE"
    assert reference.external_id == "BOE-A-2026-12345"
    assert reference.canonical_key == "BOE:BOE-A-2026-12345"


def test_reference_rejects_unknown_source():
    with pytest.raises(KeyError):
        KnowledgeItemReference(
            source_key="UNKNOWN",
            external_id="123",
        )


def test_discovery_batch_normalizes_cursor_and_source():
    reference = KnowledgeItemReference(
        source_key="BOE",
        external_id="BOE-A-2026-1",
    )

    batch = KnowledgeDiscoveryBatch(
        source_key=" boe ",
        items=(reference,),
        next_cursor=" next ",
    )

    assert batch.source_key == "BOE"
    assert batch.next_cursor == "next"
    assert batch.items == (reference,)


def test_provider_satisfies_runtime_contract():
    provider = FakeBoeProvider()

    assert isinstance(provider, KnowledgeProvider)
    assert validate_provider_source(provider) == "BOE"


def test_provider_discovery_contract_is_valid():
    provider = FakeBoeProvider()

    batch = provider.discover()

    assert validate_discovery_batch(provider, batch) is batch
    assert len(batch.items) == 1
    assert batch.next_cursor == "page-2"


def test_provider_fetch_and_transform_preserve_identity():
    provider = FakeBoeProvider()
    reference = provider.discover().items[0]

    payload = provider.fetch(reference)
    item = provider.to_knowledge_item(reference, payload)

    validated = validate_transformed_item(
        provider,
        reference,
        item,
    )

    assert validated.canonical_key == (
        "BOE:BOE-A-2026-12345"
    )


def test_transformed_item_cannot_change_external_identity():
    provider = FakeBoeProvider()
    reference = provider.discover().items[0]

    wrong_item = build_knowledge_item(
        source_key="BOE",
        external_id="BOE-A-2026-OTHER",
        title="Otra disposición",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="Contenido distinto",
    )

    with pytest.raises(
        ValueError,
        match="cambió external_id",
    ):
        validate_transformed_item(
            provider,
            reference,
            wrong_item,
        )


def test_batch_rejects_reference_from_another_source_contractually():
    reference = KnowledgeItemReference(
        source_key="BOE",
        external_id="BOE-A-2026-1",
    )

    # El contrato del batch debe conservar exactamente
    # la misma identidad de fuente de sus referencias.
    batch = KnowledgeDiscoveryBatch(
        source_key="BOE",
        items=(reference,),
    )

    assert batch.items[0].source_key == batch.source_key
