from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("database/quesada.db")


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except Exception:
        return set()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (table_name,),
    ).fetchone()
    return bool(row)


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> bool:
    if not _table_exists(conn, table_name):
        return False

    if column_name in _columns(conn, table_name):
        return False

    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
    return True


def migrate(db_path: str | Path = DEFAULT_DB_PATH) -> dict:
    db_path = Path(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        added = []

        for table_name in ["cashmatic_movements", "bank_movements"]:
            if not _table_exists(conn, table_name):
                continue

            if _add_column_if_missing(conn, table_name, "linked_gasto_id", "INTEGER"):
                added.append(f"{table_name}.linked_gasto_id")

            if _add_column_if_missing(conn, table_name, "linked_amount_centimos", "INTEGER NOT NULL DEFAULT 0"):
                added.append(f"{table_name}.linked_amount_centimos")

            if _add_column_if_missing(conn, table_name, "linked_target_type", "TEXT"):
                added.append(f"{table_name}.linked_target_type")

            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_linked_gasto_id
                ON {table_name}(linked_gasto_id)
                """
            )

            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_linked_target_type
                ON {table_name}(linked_target_type)
                """
            )

        conn.commit()

        result = {
            "db_path": str(db_path),
            "added": added,
            "cashmatic_columns": sorted(_columns(conn, "cashmatic_movements")),
            "bank_columns": sorted(_columns(conn, "bank_movements")),
        }

    return result


if __name__ == "__main__":
    import json
    print(json.dumps(migrate(), ensure_ascii=False, indent=2))
