from backend.knowledge.boe_consolidated import (
    parse_boe_consolidated_structure,
)
from backend.knowledge.boe_consolidated.parser import (
    parse_boe_consolidated_current_text,
)

from test_knowledge_boe_consolidated_provider import (
    TARGET,
    TEXT_XML,
)


BLOCK_INDEX = [
    {
        "id": "a1",
        "title": "Articulo 1",
        "updated_on": "20241120",
        "url": "https://example/a1",
    },
    {
        "id": "a2",
        "title": "Articulo 2",
        "updated_on": "20260415",
        "url": "https://example/a2",
    },
]


def test_boe_structure_preserves_all_historical_text():
    document = (
        parse_boe_consolidated_structure(
            TARGET,
            TEXT_XML,
            block_index=BLOCK_INDEX,
        )
    )

    assert len(
        document.blocks
    ) == 2

    assert len(
        document.versions
    ) == 3

    a2_versions = (
        document.versions_for_block(
            "a2"
        )
    )

    assert len(
        a2_versions
    ) == 2

    assert (
        "Texto antiguo"
        in a2_versions[
            0
        ].content_text
    )

    assert (
        a2_versions[
            0
        ].is_current
        is False
    )

    assert (
        "Texto vigente reformado"
        in a2_versions[
            1
        ].content_text
    )

    assert (
        a2_versions[
            1
        ].is_current
        is True
    )


def test_boe_structure_preserves_temporal_provenance():
    document = (
        parse_boe_consolidated_structure(
            TARGET,
            TEXT_XML,
            block_index=BLOCK_INDEX,
        )
    )

    a2_versions = (
        document.versions_for_block(
            "a2"
        )
    )

    old = a2_versions[0]
    current = a2_versions[1]

    assert (
        old.modifier_external_id
        == TARGET
    )

    assert (
        old.published_on.isoformat()
        == "2024-11-20"
    )

    assert (
        old.effective_from.isoformat()
        == "2025-05-20"
    )

    assert (
        current.modifier_external_id
        == "BOE-A-2026-8284"
    )

    assert (
        current.published_on.isoformat()
        == "2026-04-15"
    )

    assert (
        current.effective_from.isoformat()
        == "2026-04-16"
    )


def test_boe_structure_uses_index_title_and_uri():
    document = (
        parse_boe_consolidated_structure(
            TARGET,
            TEXT_XML,
            block_index=BLOCK_INDEX,
        )
    )

    a2 = next(
        block
        for block
        in document.blocks
        if block.block_id
        == "a2"
    )

    assert (
        a2.title
        == "Articulo 2"
    )

    assert (
        a2.canonical_uri
        == "https://example/a2"
    )

    assert (
        a2.current_version_key
        == document.current_version(
            "a2"
        ).version_key
    )


def test_structured_current_text_matches_existing_document_view():
    current_text, model = (
        parse_boe_consolidated_current_text(
            TARGET,
            TEXT_XML,
        )
    )

    document = (
        parse_boe_consolidated_structure(
            TARGET,
            TEXT_XML,
            block_index=BLOCK_INDEX,
        )
    )

    assert (
        document.current_content_text
        == current_text
    )

    assert (
        len(
            document.blocks
        )
        == model[
            "block_count"
        ]
    )

    assert (
        len(
            document.versions
        )
        == model[
            "version_count"
        ]
    )


def test_structure_is_deterministic():
    first = (
        parse_boe_consolidated_structure(
            TARGET,
            TEXT_XML,
            block_index=BLOCK_INDEX,
        )
    )

    second = (
        parse_boe_consolidated_structure(
            TARGET,
            TEXT_XML,
            block_index=BLOCK_INDEX,
        )
    )

    assert tuple(
        version.version_key
        for version
        in first.versions
    ) == tuple(
        version.version_key
        for version
        in second.versions
    )
