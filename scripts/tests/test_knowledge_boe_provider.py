import json
from datetime import date
from pathlib import Path

import pytest

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeProvider,
    validate_discovery_batch,
    validate_transformed_item,
)
from backend.knowledge.boe import (
    BoeProvider,
    parse_boe_discovery_payload,
    parse_boe_document_payload,
)
from backend.knowledge.boe.parser import (
    parse_boe_publication_date,
)


FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "knowledge"
    / "boe"
)


def _load_fixture(name):
    return json.loads(
        (FIXTURE_DIR / name).read_text(
            encoding="utf-8"
        )
    )


class FixtureBoeTransport:
    def discover(self, *, cursor=None):
        assert cursor in (
            None,
            "20260914",
        )
        return _load_fixture(
            "daily_summary.json"
        )

    def fetch(self, external_id):
        if external_id != "BOE-A-2026-20001":
            raise KeyError(external_id)

        return _load_fixture(
            "document_20001.json"
        )


def _provider():
    return BoeProvider(
        FixtureBoeTransport()
    )


def test_boe_provider_satisfies_generic_provider_contract():
    provider = _provider()

    assert isinstance(
        provider,
        KnowledgeProvider,
    )
    assert provider.source_key == "BOE"


def test_boe_discovery_maps_official_summary_shape():
    provider = _provider()

    batch = provider.discover(
        cursor="20260914"
    )

    validate_discovery_batch(
        provider,
        batch,
    )

    assert len(batch.items) == 2
    assert batch.items[0].canonical_key == (
        "BOE:BOE-A-2026-20001"
    )
    assert batch.items[1].canonical_key == (
        "BOE:BOE-A-2026-20002"
    )

    # El sumario BOE oficial no documenta paginación.
    assert batch.next_cursor is None


def test_boe_summary_publication_date_is_preserved_contractually():
    payload = _load_fixture(
        "daily_summary.json"
    )

    assert parse_boe_publication_date(
        payload
    ) == date(2026, 9, 14)


def test_boe_fetch_and_canonicalize_fixture():
    provider = _provider()
    reference = provider.discover(
        cursor="20260914"
    ).items[0]

    payload = provider.fetch(reference)
    item = provider.to_knowledge_item(
        reference,
        payload,
    )

    validate_transformed_item(
        provider,
        reference,
        item,
    )

    assert item.source_key == "BOE"
    assert item.external_id == "BOE-A-2026-20001"
    assert (
        item.item_kind
        is KnowledgeItemKind.OFFICIAL_PUBLICATION
    )
    assert item.published_on.isoformat() == "2026-09-14"
    assert "fixture sintético" in item.content_text


def test_boe_document_metadata_is_preserved():
    provider = _provider()
    reference = provider.discover().items[0]

    item = provider.to_knowledge_item(
        reference,
        provider.fetch(reference),
    )

    assert item.metadata == (
        ("department", "MINISTERIO DE PRUEBA"),
        ("section", "I. Disposiciones generales"),
    )


def test_discovery_rejects_duplicate_external_ids():
    payload = _load_fixture(
        "daily_summary.json"
    )

    items = (
        payload["data"]["sumario"]["diario"][0]
        ["seccion"][0]["departamento"][0]
        ["epigrafe"][0]["item"]
    )

    items[1]["identificador"] = (
        items[0]["identificador"]
    )

    with pytest.raises(
        ValueError,
        match="id duplicado",
    ):
        parse_boe_discovery_payload(
            payload
        )


def test_discovery_rejects_invalid_publication():
    payload = _load_fixture(
        "daily_summary.json"
    )

    payload["data"]["sumario"]["metadatos"][
        "publicacion"
    ] = "BORME"

    with pytest.raises(
        ValueError,
        match="publicación inesperada",
    ):
        parse_boe_discovery_payload(
            payload
        )


def test_document_rejects_identity_mismatch():
    provider = _provider()
    reference = provider.discover().items[0]

    payload = _load_fixture(
        "document_20001.json"
    )
    payload["id"] = "BOE-A-2026-OTHER"

    with pytest.raises(
        ValueError,
        match="no coincide",
    ):
        parse_boe_document_payload(
            reference,
            payload,
        )


def test_document_rejects_invalid_publication_date():
    provider = _provider()
    reference = provider.discover().items[0]

    payload = _load_fixture(
        "document_20001.json"
    )
    payload["published_on"] = "14/09/2026"

    with pytest.raises(
        ValueError,
        match="formato ISO",
    ):
        parse_boe_document_payload(
            reference,
            payload,
        )
