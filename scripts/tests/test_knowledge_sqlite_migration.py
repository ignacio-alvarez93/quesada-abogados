from pathlib import Path
import sqlite3

from backend.knowledge.sqlite_repository import (
    DEFAULT_DB_PATH,
    SQLiteKnowledgeRepository,
)


PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)

MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "20260914_create_knowledge_storage.sql"
)


def _objects(
    connection,
    object_type,
):
    return {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = ?
            """,
            (object_type,),
        )
    }


def test_canonical_migration_exists():
    assert MIGRATION_PATH.exists()


def test_default_database_path_is_main_erp_database():
    assert DEFAULT_DB_PATH == (
        PROJECT_ROOT
        / "database"
        / "quesada.db"
    )


def test_migration_creates_expected_tables(tmp_path):
    db_path = (
        tmp_path
        / "migration.db"
    )

    sql = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    with sqlite3.connect(
        db_path
    ) as connection:
        connection.executescript(
            sql
        )

        tables = _objects(
            connection,
            "table",
        )

    assert "knowledge_items" in tables
    assert (
        "knowledge_item_revisions"
        in tables
    )


def test_migration_creates_expected_indexes(tmp_path):
    db_path = (
        tmp_path
        / "migration.db"
    )

    sql = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    with sqlite3.connect(
        db_path
    ) as connection:
        connection.executescript(
            sql
        )

        indexes = _objects(
            connection,
            "index",
        )

    assert (
        "idx_knowledge_items_source"
        in indexes
    )
    assert (
        "idx_knowledge_items_published_on"
        in indexes
    )
    assert (
        "idx_knowledge_items_kind"
        in indexes
    )
    assert (
        "idx_knowledge_revisions_identity"
        in indexes
    )
    assert (
        "idx_knowledge_revisions_status"
        in indexes
    )


def test_migration_is_idempotent(tmp_path):
    db_path = (
        tmp_path
        / "migration.db"
    )

    sql = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    with sqlite3.connect(
        db_path
    ) as connection:
        connection.executescript(
            sql
        )
        connection.executescript(
            sql
        )

        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                  'knowledge_items',
                  'knowledge_item_revisions'
              )
            """
        ).fetchone()[0]

    assert count == 2


def test_migration_preserves_existing_erp_tables(
    tmp_path,
):
    db_path = (
        tmp_path
        / "erp_existing.db"
    )

    sql = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    with sqlite3.connect(
        db_path
    ) as connection:
        connection.execute(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            INSERT INTO clientes (
                id,
                nombre
            )
            VALUES (
                1,
                'Cliente existente'
            )
            """
        )

        connection.executescript(
            sql
        )

        existing = connection.execute(
            """
            SELECT nombre
            FROM clientes
            WHERE id = 1
            """
        ).fetchone()

    assert existing == (
        "Cliente existente",
    )


def test_repository_initialization_uses_migration(
    tmp_path,
):
    db_path = (
        tmp_path
        / "repository.db"
    )

    repository = (
        SQLiteKnowledgeRepository(
            db_path
        )
    )

    repository.initialize_schema()

    with sqlite3.connect(
        db_path
    ) as connection:
        tables = _objects(
            connection,
            "table",
        )

    assert "knowledge_items" in tables
    assert (
        "knowledge_item_revisions"
        in tables
    )


def test_repository_default_construction_does_not_create_db():
    db_path = DEFAULT_DB_PATH

    existed_before = (
        db_path.exists()
    )

    repository = (
        SQLiteKnowledgeRepository()
    )

    assert (
        repository.db_path
        == db_path
    )

    # Construir el adapter no puede crear la DB.
    assert (
        db_path.exists()
        == existed_before
    )
