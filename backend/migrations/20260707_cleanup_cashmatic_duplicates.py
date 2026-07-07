from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("database/quesada.db")
BACKUP_TABLE = "cashmatic_movements_duplicates_backup_20260707"


def _scalar(cur: sqlite3.Cursor, sql: str):
    cur.execute(sql)
    return cur.fetchone()[0]


def run(db_path: str | Path = DEFAULT_DB_PATH) -> dict:
    db_path = Path(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def count_total() -> int:
        return int(_scalar(cur, "SELECT COUNT(*) FROM cashmatic_movements"))

    def count_duplicate_groups() -> int:
        return int(_scalar(cur, """
            SELECT COUNT(*)
            FROM (
                SELECT TRIM(cashmatic_id)
                FROM cashmatic_movements
                WHERE cashmatic_id IS NOT NULL
                  AND TRIM(cashmatic_id) <> ''
                GROUP BY TRIM(cashmatic_id)
                HAVING COUNT(*) > 1
            )
        """))

    def count_linked_duplicate_rows() -> int:
        return int(_scalar(cur, """
            SELECT COUNT(*)
            FROM cashmatic_movements
            WHERE TRIM(COALESCE(cashmatic_id, '')) IN (
                SELECT TRIM(cashmatic_id)
                FROM cashmatic_movements
                WHERE cashmatic_id IS NOT NULL
                  AND TRIM(cashmatic_id) <> ''
                GROUP BY TRIM(cashmatic_id)
                HAVING COUNT(*) > 1
            )
            AND (
                linked_client_id IS NOT NULL
                OR linked_expedient_id IS NOT NULL
                OR linked_payment_id IS NOT NULL
                OR linked_at IS NOT NULL
            )
        """))

    before_total = count_total()
    before_groups = count_duplicate_groups()
    linked_dups = count_linked_duplicate_rows()

    if linked_dups:
        conn.close()
        raise RuntimeError(
            "ABORTADO: hay duplicados Cashmatic con enlaces manuales. "
            "No se borra nada automáticamente."
        )

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} AS
        SELECT *
        FROM cashmatic_movements
        WHERE 1 = 0
    """)

    backup_rows = int(_scalar(cur, f"SELECT COUNT(*) FROM {BACKUP_TABLE}"))

    if backup_rows == 0:
        cur.execute(f"""
            INSERT INTO {BACKUP_TABLE}
            SELECT *
            FROM cashmatic_movements
            WHERE TRIM(COALESCE(cashmatic_id, '')) IN (
                SELECT TRIM(cashmatic_id)
                FROM cashmatic_movements
                WHERE cashmatic_id IS NOT NULL
                  AND TRIM(cashmatic_id) <> ''
                GROUP BY TRIM(cashmatic_id)
                HAVING COUNT(*) > 1
            )
        """)
        backup_inserted = cur.rowcount
    else:
        backup_inserted = 0

    cur.execute("""
        SELECT *
        FROM cashmatic_movements
        WHERE cashmatic_id IS NOT NULL
          AND TRIM(cashmatic_id) <> ''
        ORDER BY TRIM(cashmatic_id), id
    """)

    groups: dict[str, list[dict]] = {}
    for row in cur.fetchall():
        item = dict(row)
        cashmatic_id = str(item.get("cashmatic_id") or "").strip()
        groups.setdefault(cashmatic_id, []).append(item)

    def score(row: dict) -> float:
        start_time = str(row.get("start_time") or "")
        seconds = ""
        try:
            seconds = start_time.split(" ")[1].split(":")[2]
        except Exception:
            pass

        linked = any(row.get(k) is not None for k in [
            "linked_client_id",
            "linked_expedient_id",
            "linked_payment_id",
            "linked_at",
        ])

        value = 0.0

        if linked:
            value += 100000
        if seconds and seconds != "00":
            value += 1000
        if row.get("reason_raw"):
            value += 100
        if row.get("reference_raw"):
            value += 50
        if row.get("user_username"):
            value += 10

        try:
            value += int(row.get("id") or 0) / 100000000
        except Exception:
            pass

        return value

    delete_ids: list[int] = []

    for rows in groups.values():
        if len(rows) <= 1:
            continue

        keeper = sorted(rows, key=score, reverse=True)[0]

        for row in rows:
            if row["id"] != keeper["id"]:
                delete_ids.append(int(row["id"]))

    deleted = 0
    chunk_size = 500

    for i in range(0, len(delete_ids), chunk_size):
        chunk = delete_ids[i:i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        cur.execute(
            f"DELETE FROM cashmatic_movements WHERE id IN ({placeholders})",
            chunk,
        )
        deleted += cur.rowcount

    conn.commit()

    after_total = count_total()
    after_groups = count_duplicate_groups()

    conn.close()

    if after_total != before_total - len(delete_ids):
        raise RuntimeError(
            f"Total inesperado tras limpieza. Esperado={before_total - len(delete_ids)}, real={after_total}"
        )

    if after_groups != 0:
        raise RuntimeError(f"Siguen existiendo grupos duplicados Cashmatic: {after_groups}")

    return {
        "db_path": str(db_path),
        "backup_table": BACKUP_TABLE,
        "before_total": before_total,
        "before_duplicate_groups": before_groups,
        "linked_duplicate_rows": linked_dups,
        "backup_inserted": backup_inserted,
        "deleted": deleted,
        "after_total": after_total,
        "after_duplicate_groups": after_groups,
    }


if __name__ == "__main__":
    result = run()
    for key, value in result.items():
        print(f"{key}: {value}")
