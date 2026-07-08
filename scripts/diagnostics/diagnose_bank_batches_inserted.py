from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path("database/quesada.db")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("== Batches bancarios con movimientos realmente insertados ==")

    rows = conn.execute("""
        SELECT
            b.id,
            b.source_type,
            b.source_file_name,
            b.file_sha256,
            b.total_rows,
            b.candidate_payment_rows,
            b.quarantine_rows,
            b.created_at,
            COUNT(m.id) AS inserted_movements,
            MIN(m.id) AS first_movement_id,
            MAX(m.id) AS last_movement_id,
            MIN(m.created_at) AS first_movement_created_at,
            MAX(m.created_at) AS last_movement_created_at
        FROM economic_import_batches b
        LEFT JOIN bank_movements m
               ON m.batch_id = b.id
        WHERE b.source_type LIKE 'BANK_%'
        GROUP BY b.id
        ORDER BY b.id DESC
        LIMIT 30
    """).fetchall()

    for row in rows:
        print(dict(row))

    print("\n== Resumen por banco ==")
    for bank in ["SANTANDER", "ING", "CAJA_RURAL"]:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                MAX(id) AS max_id,
                MAX(created_at) AS last_created
            FROM bank_movements
            WHERE bank_name = ?
        """, (bank,)).fetchone()
        print(bank, dict(row))

    conn.close()


if __name__ == "__main__":
    main()
