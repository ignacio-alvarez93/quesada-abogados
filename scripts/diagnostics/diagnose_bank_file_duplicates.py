from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "database" / "quesada.db"


def diagnose(source: str, file_path: str) -> None:
    source = source.lower().strip()
    path = Path(file_path)

    if source == "ing":
        from backend.services.economic_reconciliation.bank_ing_parser_service import diagnose_ing_bank_file
        report = diagnose_ing_bank_file(path)
        bank_name = "ING"
    elif source == "santander":
        from backend.services.economic_reconciliation.bank_santander_parser_service import diagnose_santander_bank_file
        report = diagnose_santander_bank_file(path)
        bank_name = "SANTANDER"
    else:
        raise SystemExit("Uso: ing|santander <archivo>")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    existing_hashes = {
        r["row_hash"]
        for r in conn.execute(
            "SELECT row_hash FROM bank_movements WHERE bank_name = ?",
            (bank_name,),
        ).fetchall()
    }

    duplicates = []
    new_rows = []

    for row in report.rows:
        if row.row_hash in existing_hashes:
            duplicates.append(row)
        else:
            new_rows.append(row)

    print("source:", source)
    print("file:", path)
    print("detected_format:", getattr(report, "detected_format", None))
    print("total_rows:", report.total_rows)
    print("valid_rows:", getattr(report, "valid_rows", len(report.rows)))
    print("income_rows:", report.income_rows)
    print("expense_rows:", report.expense_rows)
    print("quarantine_rows:", report.quarantine_rows)
    print("existing_duplicates:", len(duplicates))
    print("new_rows:", len(new_rows))

    print("\n== Primeras filas nuevas ==")
    for row in new_rows[:10]:
        print(row)

    print("\n== Primeras filas duplicadas ==")
    for row in duplicates[:10]:
        print(row)

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Uso: python scripts/diagnostics/diagnose_bank_file_duplicates.py ing|santander <archivo>")
    diagnose(sys.argv[1], sys.argv[2])
