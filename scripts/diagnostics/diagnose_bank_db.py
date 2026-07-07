from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.bank_query_service import (  # noqa: E402
    get_bank_dashboard_summary,
    list_bank_batches,
    list_bank_movements,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico de staging bancario importado en SQLite."
    )
    parser.add_argument("--db", default="database/quesada.db")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--status", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--search", default="")
    parser.add_argument("--income", action="store_true")
    parser.add_argument("--expense", action="store_true")
    parser.add_argument("--include-ignored", action="store_true")

    args = parser.parse_args()

    summary = get_bank_dashboard_summary(db_path=args.db)
    batches = list_bank_batches(db_path=args.db)
    page = list_bank_movements(
        db_path=args.db,
        page=args.page,
        page_size=args.page_size,
        movement_status=args.status or None,
        movement_type=args.type or None,
        search=args.search or None,
        only_income=args.income,
        only_expense=args.expense,
        include_ignored=args.include_ignored,
    )

    print("")
    print("== Resumen Banco DB ==")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("")
    print("== Batches Banco ==")
    for batch in batches:
        print(
            f"- #{batch['id']} {batch['source_file_name']} | "
            f"filas={batch['total_rows']} | "
            f"únicos_insertados={batch['inserted_unique_movements']} | "
            f"ingresos_export={batch['candidate_payment_rows']} | "
            f"cuarentena_export={batch['quarantine_rows']}"
        )

    print("")
    print(
        f"== Movimientos banco página {page.page}/{page.total_pages} "
        f"({page.total_items} total) =="
    )
    for item in page.items:
        print(
            f"- #{item['id']} {item.get('operation_date') or '-'} | "
            f"{item.get('movement_type') or '-'} | "
            f"{item.get('movement_status')} | "
            f"{item.get('amount_eur')} € | "
            f"{item.get('concept') or '-'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
