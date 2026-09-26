from backend.knowledge import (
    KnowledgeCatalogTier,
    KnowledgeCatalogWriteStatus,
)
from backend.knowledge.catalog_seed import (
    CORE_KNOWLEDGE_CATALOG_SEED,
    seed_core_knowledge_catalog,
)
from backend.knowledge.sqlite_catalog_repository import (
    SQLiteKnowledgeCatalogRepository,
)


EXPECTED_IDS = {
    "BOE-A-2000-544",
    "BOE-A-2024-24099",
    "BOE-A-2015-10565",
    "BOE-A-2015-11724",
}


def test_core_seed_defines_first_four_governed_norms():
    assert (
        len(
            CORE_KNOWLEDGE_CATALOG_SEED
        )
        == 4
    )

    assert {
        entry.external_id
        for entry
        in CORE_KNOWLEDGE_CATALOG_SEED
    } == EXPECTED_IDS

    for entry in (
        CORE_KNOWLEDGE_CATALOG_SEED
    ):
        assert (
            entry.source_key
            == "BOE_CONSOLIDATED"
        )
        assert (
            entry.tier
            is KnowledgeCatalogTier.CORE
        )
        assert (
            entry.watch_updates
            is True
        )
        assert (
            entry.priority
            == 100
        )


def test_core_seed_is_idempotent_on_catalog_only_database(
    tmp_path,
):
    repository = (
        SQLiteKnowledgeCatalogRepository(
            tmp_path
            / "core_catalog.db"
        )
    )

    repository.initialize_schema()

    first = seed_core_knowledge_catalog(
        repository
    )

    second = seed_core_knowledge_catalog(
        repository
    )

    assert {
        result.status
        for result in first
    } == {
        KnowledgeCatalogWriteStatus.NEW
    }

    assert {
        result.status
        for result in second
    } == {
        KnowledgeCatalogWriteStatus.UNCHANGED
    }

    entries = repository.list_entries(
        tier=KnowledgeCatalogTier.CORE
    )

    assert len(entries) == 4

    assert {
        entry.external_id
        for entry in entries
    } == EXPECTED_IDS
