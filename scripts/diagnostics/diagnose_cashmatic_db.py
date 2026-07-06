from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.cashmatic_query_service import (  # noqa: E402
    get_cashmatic_dashboard_summary,
    list_cashmatic_batches,
    list_cashmatic_movements,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico de staging Cashmatic importado en SQLite."
    )
    parser.add_argument("--db", default="database/quesada.db")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--status", default="")
    parser.add_argument("--operation", default="")
    parser.add_argument("--search", default="")
    parser.add_argument("--include-ignored", action="store_true")

    args = parser.parse_args()

    summary = get_cashmatic_dashboard_summary(db_path=args.db)
    batches = list_cashmatic_batches(db_path=args.db)
    page = list_cashmatic_movements(
        db_path=args.db,
        page=args.page,
        page_size=args.page_size,
        movement_status=args.status or None,
        operation=args.operation or None,
        search=args.search or None,
        include_ignored=args.include_ignored,
    )

    print("")
    print("== Resumen Cashmatic DB ==")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("")
    print("== Batches ==")
    for batch in batches:
        print(
            f"- #{batch['id']} {batch['source_file_name']} | "
            f"filas={batch['total_rows']} | "
            f"únicos_insertados={batch['inserted_unique_movements']} | "
            f"candidatos_export={batch['candidate_payment_rows']} | "
            f"cuarentena_export={batch['quarantine_rows']}"
        )

    print("")
    print(
        f"== Movimientos página {page.page}/{page.total_pages} "
        f"({page.total_items} total) =="
    )
    for item in page.items:
        print(
            f"- #{item['id']} {item.get('start_time') or '-'} | "
            f"{item.get('operation') or '-'} | "
            f"{item.get('movement_status')} | "
            f"{item.get('net_amount_eur')} € | "
            f"{item.get('reason_raw') or '-'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
