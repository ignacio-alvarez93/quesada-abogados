from backend.knowledge import (
    KnowledgeCatalogTier,
    KnowledgeCatalogWriteStatus,
)
from backend.knowledge.catalog_seed import (
    EU_CORE_KNOWLEDGE_CATALOG_SEED,
    seed_eu_core_knowledge_catalog,
)
from backend.knowledge.sqlite_catalog_repository import (
    SQLiteKnowledgeCatalogRepository,
)


EXPECTED = {
    ("EUR_LEX", "12016M/TXT"),
    ("EUR_LEX", "12016E/TXT"),
    ("EUR_LEX", "12016P/TXT"),
    (
        "EUR_LEX_CONSOLIDATED",
        "32016R0399",
    ),
    (
        "EUR_LEX_CONSOLIDATED",
        "32009R0810",
    ),
    (
        "EUR_LEX_CONSOLIDATED",
        "32017R2226",
    ),
    (
        "EUR_LEX_CONSOLIDATED",
        "32018R1240",
    ),
    (
        "EUR_LEX_CONSOLIDATED",
        "32021L1883",
    ),
    ("EUR_LEX", "32024L1233"),
}


def test_eu_core_seed_contains_governed_legal_corpus():
    assert (
        len(
            EU_CORE_KNOWLEDGE_CATALOG_SEED
        )
        == 9
    )

    identities = {
        (
            entry.source_key,
            entry.external_id,
        )
        for entry
        in EU_CORE_KNOWLEDGE_CATALOG_SEED
    }

    assert identities == EXPECTED

    for entry in (
        EU_CORE_KNOWLEDGE_CATALOG_SEED
    ):
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
            >= 95
        )


def test_single_permit_does_not_claim_unusable_spanish_consolidation():
    matches = [
        entry
        for entry
        in EU_CORE_KNOWLEDGE_CATALOG_SEED
        if (
            entry.external_id
            == "32024L1233"
        )
    ]

    assert len(matches) == 1

    assert (
        matches[0].source_key
        == "EUR_LEX"
    )


def test_mutable_schengen_and_visa_rules_watch_consolidated_identity():
    identities = {
        (
            entry.source_key,
            entry.external_id,
        )
        for entry
        in EU_CORE_KNOWLEDGE_CATALOG_SEED
    }

    assert (
        "EUR_LEX_CONSOLIDATED",
        "32016R0399",
    ) in identities

    assert (
        "EUR_LEX_CONSOLIDATED",
        "32009R0810",
    ) in identities


def test_eu_core_seed_is_idempotent(
    tmp_path,
):
    repository = (
        SQLiteKnowledgeCatalogRepository(
            tmp_path
            / "eu_core_catalog.db"
        )
    )

    repository.initialize_schema()

    first = (
        seed_eu_core_knowledge_catalog(
            repository
        )
    )

    second = (
        seed_eu_core_knowledge_catalog(
            repository
        )
    )

    assert len(first) == 9
    assert len(second) == 9

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

    assert len(entries) == 9

    assert {
        (
            entry.source_key,
            entry.external_id,
        )
        for entry in entries
    } == EXPECTED
