from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path("database/quesada.db")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            bank_name,
            operation_date,
            value_date,
            amount_centimos,
            balance_centimos,
            COUNT(*) AS total,
            GROUP_CONCAT(id) AS ids,
            GROUP_CONCAT(concept, ' || ') AS concepts,
            GROUP_CONCAT(batch_id) AS batch_ids
        FROM bank_movements
        WHERE bank_name = 'SANTANDER'
          AND ignored_at IS NULL
        GROUP BY bank_name, operation_date, value_date, amount_centimos, balance_centimos
        HAVING COUNT(*) > 1
        ORDER BY operation_date DESC, value_date DESC, amount_centimos
    """).fetchall()

    print("== Duplicados semánticos Santander ==")
    print("total grupos:", len(rows))

    for row in rows:
        print(dict(row))

    conn.close()


if __name__ == "__main__":
    main()
