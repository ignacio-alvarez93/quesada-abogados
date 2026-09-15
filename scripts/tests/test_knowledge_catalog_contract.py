import pytest

from backend.knowledge import (
    KnowledgeCatalogTier,
    build_knowledge_catalog_entry,
)


def test_catalog_identity_is_source_plus_external_id():
    entry = build_knowledge_catalog_entry(
        source_key="boe_consolidated",
        external_id=" BOE-A-2000-544 ",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
    )

    assert (
        entry.source_key
        == "BOE_CONSOLIDATED"
    )

    assert (
        entry.external_id
        == "BOE-A-2000-544"
    )

    assert (
        entry.canonical_key
        == (
            "BOE_CONSOLIDATED:"
            "BOE-A-2000-544"
        )
    )


@pytest.mark.parametrize(
    "tier",
    [
        KnowledgeCatalogTier.CORE,
        KnowledgeCatalogTier.FOLLOWED,
    ],
)
def test_active_tiers_require_watch_updates(
    tier,
):
    with pytest.raises(
        ValueError,
    ):
        build_knowledge_catalog_entry(
            source_key="BOE_CONSOLIDATED",
            external_id="BOE-A-2000-544",
            tier=tier,
            watch_updates=False,
        )


def test_discovered_may_exist_without_active_watch():
    entry = build_knowledge_catalog_entry(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2026-8284",
        tier=(
            KnowledgeCatalogTier.DISCOVERED
        ),
        watch_updates=False,
        priority=20,
        added_reason=(
            "Descubierta desde relación jurídica."
        ),
    )

    assert (
        entry.watch_updates
        is False
    )
