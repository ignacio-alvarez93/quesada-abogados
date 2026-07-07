from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation import (  # noqa: E402
    get_cashmatic_dashboard_summary,
    list_cashmatic_batches,
    list_cashmatic_movements,
)


def main() -> int:
    summary = get_cashmatic_dashboard_summary()
    batches = list_cashmatic_batches()
    page = list_cashmatic_movements(page=1, page_size=3)

    print("== Cashmatic backend stack ==")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("")
    print("Batches:", len(batches))
    print("Página:", {
        "page": page.page,
        "page_size": page.page_size,
        "total_items": page.total_items,
        "total_pages": page.total_pages,
        "items": len(page.items),
    })

    manual_links = summary["movements"]["manually_linked_movements"]
    if manual_links != 0:
        raise SystemExit(f"ERROR: quedan vinculaciones manuales de prueba: {manual_links}")

    print("")
    print("OK: backend Cashmatic importable desde paquete y sin vínculos de prueba.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
