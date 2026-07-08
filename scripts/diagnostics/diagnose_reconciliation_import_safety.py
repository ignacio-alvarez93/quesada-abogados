from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path("database/quesada.db")


LINK_COLUMNS = [
    "linked_client_id",
    "linked_expedient_id",
    "linked_payment_id",
    "linked_gasto_id",
    "linked_amount_centimos",
    "linked_target_type",
    "linked_by_user_id",
    "linked_at",
    "link_notes",
]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
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


def columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not table_exists(conn, table_name):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def count_linked(conn: sqlite3.Connection, table_name: str) -> dict:
    cols = columns(conn, table_name)
    existing = [c for c in LINK_COLUMNS if c in cols]

    if not existing:
        return {"table": table_name, "exists": table_exists(conn, table_name), "linked_rows": 0, "columns": []}

    conditions = []
    for col in existing:
        if col == "linked_amount_centimos":
            conditions.append(f"COALESCE({col}, 0) <> 0")
        else:
            conditions.append(f"{col} IS NOT NULL AND TRIM(CAST({col} AS TEXT)) <> ''")

    where = " OR ".join(conditions)

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS linked_rows
        FROM {table_name}
        WHERE {where}
        """
    ).fetchone()

    status_rows = []
    if "review_status" in cols:
        status_rows = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT review_status, COUNT(*) AS total
                FROM {table_name}
                GROUP BY review_status
                ORDER BY total DESC
                """
            ).fetchall()
        ]

    return {
        "table": table_name,
        "exists": True,
        "linked_rows": int(row["linked_rows"] or 0),
        "columns": existing,
        "review_status": status_rows,
    }


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("== Diagnóstico seguridad importación/conciliación ==")
    print("DB:", DB_PATH)

    for table_name in ["cashmatic_movements", "bank_movements"]:
        data = count_linked(conn, table_name)
        print()
        print("##", table_name)
        print("exists:", data["exists"])
        print("linked_columns:", data["columns"])
        print("linked_rows:", data["linked_rows"])
        if data.get("review_status"):
            print("review_status:")
            for row in data["review_status"]:
                print(" -", row)

    conn.close()


if __name__ == "__main__":
    main()
