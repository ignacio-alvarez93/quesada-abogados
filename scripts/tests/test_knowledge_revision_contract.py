from datetime import date

import pytest

from backend.knowledge import (
    KnowledgeItemKind,
    KnowledgeRevisionStatus,
    build_knowledge_item,
    classify_knowledge_revision,
    knowledge_record_sha256,
)


def _item(**overrides):
    data = {
        "source_key": "BOE",
        "external_id": "BOE-A-2026-15300",
        "title": "Disposición de prueba",
        "item_kind": KnowledgeItemKind.OFFICIAL_PUBLICATION,
        "content_text": "Artículo 1.\nContenido original.",
        "canonical_uri": (
            "https://www.boe.es/eli/es/ai/2026/06/17/(1)"
        ),
        "source_revision": "20260720145601",
        "published_on": date(2026, 7, 14),
        "language": "es",
        "metadata": {
            "rango": "Acuerdo Internacional",
            "departamento": "Ministerio de prueba",
        },
    }

    data.update(overrides)

    return build_knowledge_item(
        **data
    )


def test_first_observation_is_new():
    current = _item()

    decision = classify_knowledge_revision(
        previous=None,
        current=current,
    )

    assert (
        decision.status
        is KnowledgeRevisionStatus.NEW
    )
    assert decision.canonical_key == current.canonical_key
    assert decision.previous_record_sha256 is None
    assert decision.current_source_revision == (
        "20260720145601"
    )


def test_identical_observation_is_unchanged():
    previous = _item()
    current = _item()

    decision = classify_knowledge_revision(
        previous=previous,
        current=current,
    )

    assert (
        decision.status
        is KnowledgeRevisionStatus.UNCHANGED
    )
    assert decision.content_changed is False
    assert decision.record_changed is False


def test_source_revision_change_without_content_change_is_metadata_revision():
    previous = _item(
        source_revision="20260720145601"
    )
    current = _item(
        source_revision="20260721101010"
    )

    decision = classify_knowledge_revision(
        previous=previous,
        current=current,
    )

    assert (
        decision.status
        is KnowledgeRevisionStatus.METADATA_REVISED
    )
    assert decision.content_changed is False
    assert decision.record_changed is True


def test_title_change_without_content_change_is_metadata_revision():
    previous = _item()

    current = _item(
        title="Disposición de prueba corregida"
    )

    decision = classify_knowledge_revision(
        previous=previous,
        current=current,
    )

    assert (
        decision.status
        is KnowledgeRevisionStatus.METADATA_REVISED
    )
    assert decision.content_changed is False


def test_metadata_change_without_content_change_is_metadata_revision():
    previous = _item()

    current = _item(
        metadata={
            "rango": "Acuerdo Internacional",
            "departamento": "Otro Ministerio",
        }
    )

    decision = classify_knowledge_revision(
        previous=previous,
        current=current,
    )

    assert (
        decision.status
        is KnowledgeRevisionStatus.METADATA_REVISED
    )


def test_content_change_is_material_revision():
    previous = _item()

    current = _item(
        content_text=(
            "Artículo 1.\n"
            "Contenido jurídicamente modificado."
        ),
        source_revision="20260722121212",
    )

    decision = classify_knowledge_revision(
        previous=previous,
        current=current,
    )

    assert (
        decision.status
        is KnowledgeRevisionStatus.CONTENT_REVISED
    )
    assert decision.content_changed is True
    assert decision.record_changed is True


def test_different_identity_cannot_be_compared():
    previous = _item()

    current = _item(
        external_id="BOE-A-2026-99999"
    )

    with pytest.raises(
        ValueError,
        match="identidades Knowledge distintas",
    ):
        classify_knowledge_revision(
            previous=previous,
            current=current,
        )


def test_record_fingerprint_is_stable_for_metadata_order():
    left = _item(
        metadata={
            "rango": "Acuerdo Internacional",
            "departamento": "Ministerio de prueba",
        }
    )

    right = _item(
        metadata={
            "departamento": "Ministerio de prueba",
            "rango": "Acuerdo Internacional",
        }
    )

    assert knowledge_record_sha256(
        left
    ) == knowledge_record_sha256(
        right
    )


def test_source_revision_is_normalized():
    item = _item(
        source_revision=" 20260720145601 "
    )

    assert item.source_revision == (
        "20260720145601"
    )
