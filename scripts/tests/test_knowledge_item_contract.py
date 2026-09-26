from datetime import date

import pytest

from backend.knowledge import (
    KnowledgeItemKind,
    build_knowledge_item,
    compute_content_sha256,
)


def _boe_item(**overrides):
    data = {
        "source_key": "BOE",
        "external_id": "BOE-A-2026-12345",
        "title": "Disposición de prueba",
        "item_kind": KnowledgeItemKind.LEGISLATION,
        "content_text": "Artículo 1.\nContenido jurídico.",
        "canonical_uri": (
            "https://www.boe.es/buscar/doc.php?id=BOE-A-2026-12345"
        ),
        "published_on": date(2026, 9, 14),
        "metadata": {
            "department": "Ministerio de prueba",
            "section": "I",
        },
    }

    data.update(overrides)
    return build_knowledge_item(**data)


def test_canonical_item_normalizes_source_and_identity():
    item = _boe_item(source_key=" boe ")

    assert item.source_key == "BOE"
    assert item.external_id == "BOE-A-2026-12345"
    assert item.source_identity == (
        "BOE",
        "BOE-A-2026-12345",
    )
    assert item.canonical_key == "BOE:BOE-A-2026-12345"


def test_content_hash_is_stable_across_line_endings():
    unix = "Artículo 1.\nContenido jurídico."
    windows = "Artículo 1.\r\nContenido jurídico.\r\n"

    assert compute_content_sha256(unix) == compute_content_sha256(
        windows
    )


def test_item_stores_hash_of_normalized_content():
    item = _boe_item(
        content_text="  Artículo 1.\r\nContenido jurídico.  "
    )

    assert item.content_text == (
        "Artículo 1.\nContenido jurídico."
    )
    assert item.content_sha256 == compute_content_sha256(
        item.content_text
    )


def test_metadata_is_normalized_and_ordered():
    item = _boe_item(
        metadata={
            "section": " I ",
            "department": " Ministerio de prueba ",
        }
    )

    assert item.metadata == (
        ("department", "Ministerio de prueba"),
        ("section", "I"),
    )


def test_item_rejects_unregistered_source():
    with pytest.raises(
        KeyError,
        match="Fuente Knowledge no registrada",
    ):
        _boe_item(source_key="UNKNOWN")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("external_id", " "),
        ("title", ""),
        ("content_text", "\r\n "),
    ],
)
def test_item_rejects_missing_required_content(field, value):
    with pytest.raises(ValueError):
        _boe_item(**{field: value})


def test_item_preserves_publication_and_provenance_fields():
    item = _boe_item()

    assert item.published_on == date(2026, 9, 14)
    assert item.language == "es"
    assert item.canonical_uri.startswith("https://www.boe.es/")
