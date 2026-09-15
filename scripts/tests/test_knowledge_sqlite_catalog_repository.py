from backend.knowledge import (
    KnowledgeCatalogTier,
    KnowledgeCatalogWriteStatus,
    build_knowledge_catalog_entry,
)
from backend.knowledge.sqlite_catalog_repository import (
    SQLiteKnowledgeCatalogRepository,
)


def _entry(
    *,
    tier=KnowledgeCatalogTier.DISCOVERED,
    watch=False,
    priority=20,
):
    return build_knowledge_catalog_entry(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2026-8284",
        tier=tier,
        watch_updates=watch,
        priority=priority,
        added_reason="test",
    )


def test_catalog_can_exist_without_knowledge_item_table(
    tmp_path,
):
    db_path = (
        tmp_path
        / "catalog_only.db"
    )

    repository = (
        SQLiteKnowledgeCatalogRepository(
            db_path
        )
    )

    repository.initialize_schema()

    first = repository.upsert(
        _entry()
    )

    assert (
        first.status
        is KnowledgeCatalogWriteStatus.NEW
    )

    # El catálogo debe poder existir antes
    # de materializar knowledge_items.
    import sqlite3

    connection = sqlite3.connect(
        db_path
    )

    try:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }
    finally:
        connection.close()

    assert (
        "knowledge_catalog_entries"
        in tables
    )

    assert (
        "knowledge_items"
        not in tables
    )


def test_catalog_upsert_is_idempotent_and_promotable(
    tmp_path,
):
    repository = (
        SQLiteKnowledgeCatalogRepository(
            tmp_path
            / "catalog.db"
        )
    )

    repository.initialize_schema()

    discovered = _entry()

    first = repository.upsert(
        discovered
    )

    second = repository.upsert(
        discovered
    )

    assert (
        first.status
        is KnowledgeCatalogWriteStatus.NEW
    )

    assert (
        second.status
        is KnowledgeCatalogWriteStatus.UNCHANGED
    )

    assert first.written is True
    assert second.written is False

    followed = _entry(
        tier=(
            KnowledgeCatalogTier.FOLLOWED
        ),
        watch=True,
        priority=80,
    )

    promoted = repository.upsert(
        followed
    )

    assert (
        promoted.status
        is KnowledgeCatalogWriteStatus.UPDATED
    )

    stored = repository.get_entry(
        "BOE_CONSOLIDATED",
        "BOE-A-2026-8284",
    )

    assert stored is not None
    assert (
        stored.tier
        is KnowledgeCatalogTier.FOLLOWED
    )
    assert stored.watch_updates is True
    assert stored.priority == 80


def test_catalog_lists_by_tier_and_watch_policy(
    tmp_path,
):
    repository = (
        SQLiteKnowledgeCatalogRepository(
            tmp_path
            / "catalog.db"
        )
    )

    repository.initialize_schema()

    repository.upsert(
        build_knowledge_catalog_entry(
            source_key="BOE_CONSOLIDATED",
            external_id="BOE-A-2000-544",
            tier=KnowledgeCatalogTier.CORE,
            watch_updates=True,
            priority=100,
        )
    )

    repository.upsert(
        build_knowledge_catalog_entry(
            source_key="BOE_CONSOLIDATED",
            external_id="BOE-A-2026-8284",
            tier=(
                KnowledgeCatalogTier.DISCOVERED
            ),
            watch_updates=False,
            priority=20,
        )
    )

    core = repository.list_entries(
        tier=KnowledgeCatalogTier.CORE
    )

    watched = repository.list_entries(
        watch_only=True
    )

    assert len(core) == 1
    assert (
        core[0].external_id
        == "BOE-A-2000-544"
    )

    assert len(watched) == 1
    assert (
        watched[0].tier
        is KnowledgeCatalogTier.CORE
    )
