from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation import (  # noqa: E402
    get_bank_dashboard_summary,
    get_cashmatic_dashboard_summary,
    list_bank_movements,
    list_cashmatic_movements,
)


def main() -> int:
    cashmatic_summary = get_cashmatic_dashboard_summary()
    bank_summary = get_bank_dashboard_summary()

    cashmatic_page = list_cashmatic_movements(page=1, page_size=3)
    bank_page = list_bank_movements(page=1, page_size=3)

    print("== Economic reconciliation backend stack ==")

    print("")
    print("== Cashmatic ==")
    print(json.dumps(cashmatic_summary, ensure_ascii=False, indent=2))
    print("Página Cashmatic:", {
        "page": cashmatic_page.page,
        "page_size": cashmatic_page.page_size,
        "total_items": cashmatic_page.total_items,
        "total_pages": cashmatic_page.total_pages,
        "items": len(cashmatic_page.items),
    })

    print("")
    print("== Banco ==")
    print(json.dumps(bank_summary, ensure_ascii=False, indent=2))
    print("Página Banco:", {
        "page": bank_page.page,
        "page_size": bank_page.page_size,
        "total_items": bank_page.total_items,
        "total_pages": bank_page.total_pages,
        "items": len(bank_page.items),
    })

    cashmatic_links = cashmatic_summary["movements"]["manually_linked_movements"]
    bank_links = bank_summary["totals"]["manually_linked_movements"]

    if cashmatic_links != 0:
        raise SystemExit(f"ERROR: quedan vínculos Cashmatic de prueba: {cashmatic_links}")

    if bank_links != 0:
        raise SystemExit(f"ERROR: quedan vínculos banco de prueba: {bank_links}")

    print("")
    print("OK: backend económico importable, Cashmatic + Banco, sin vínculos de prueba.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
