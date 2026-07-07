from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.bank_import_service import (  # noqa: E402
    ensure_bank_schema,
)
from backend.services.economic_reconciliation.bank_link_service import (  # noqa: E402
    BankManualLinkRequest,
    get_bank_link_context,
    link_bank_movement_manually,
    unlink_bank_movement,
)
from backend.services.economic_reconciliation.bank_query_service import (  # noqa: E402
    get_bank_dashboard_summary,
    get_bank_movement_detail,
    list_bank_movements,
)
from backend.services.economic_reconciliation.cashmatic_import_service import (  # noqa: E402
    connect,
)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return bool(row)


def _first_id(conn: sqlite3.Connection, table_name: str) -> int | None:
    if not _table_exists(conn, table_name):
        return None
    row = conn.execute(f"SELECT id FROM {table_name} ORDER BY id LIMIT 1").fetchone()
    return int(row["id"]) if row else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prueba vinculación manual bancaria con IDs explícitos."
    )
    parser.add_argument("--db", default="database/quesada.db")
    parser.add_argument("--movement-id", type=int, default=0)
    parser.add_argument("--client-id", type=int, default=0)
    parser.add_argument("--expedient-id", type=int, default=0)
    parser.add_argument("--payment-id", type=int, default=0)
    parser.add_argument("--user-id", type=int, default=0)
    parser.add_argument("--dry-context", action="store_true")

    args = parser.parse_args()

    page = list_bank_movements(
        db_path=args.db,
        page=1,
        page_size=1,
        only_unlinked=True,
    )
    if not page.items and not args.movement_id:
        raise SystemExit("No hay movimientos bancarios no vinculados para probar.")

    movement_id = args.movement_id or int(page.items[0]["id"])

    if args.dry_context:
        context = get_bank_link_context(movement_id, db_path=args.db)
        print("== Contexto vinculación banco ==")
        print("movement_id:", context["movement"]["id"])
        print("concept:", context["movement"].get("concept"))
        print("autocomplete_targets:", context["autocomplete_targets"])
        print("rules:", context["rules"])
        return 0

    with connect(args.db) as conn:
        ensure_bank_schema(conn)

        client_id = args.client_id or _first_id(conn, "clientes")
        expedient_id = args.expedient_id or _first_id(conn, "expedientes")
        payment_id = args.payment_id or _first_id(conn, "cobros")

    if client_id is None and expedient_id is None and payment_id is None:
        raise SystemExit(
            "No hay IDs reales para probar. Crea o indica --client-id, "
            "--expedient-id o --payment-id. El servicio no inventa IDs."
        )

    print(f"== Movimiento banco prueba: {movement_id} ==")
    before = get_bank_movement_detail(movement_id, db_path=args.db)
    print("Antes:", {
        "id": before.get("id") if before else None,
        "review_status": before.get("review_status") if before else None,
        "linked_client_id": before.get("linked_client_id") if before else None,
        "linked_expedient_id": before.get("linked_expedient_id") if before else None,
        "linked_payment_id": before.get("linked_payment_id") if before else None,
    })

    linked = link_bank_movement_manually(
        BankManualLinkRequest(
            movement_id=movement_id,
            client_id=client_id,
            expedient_id=expedient_id,
            payment_id=payment_id,
            linked_by_user_id=args.user_id or None,
            notes="Prueba automática: vinculación bancaria manual con IDs explícitos.",
        ),
        db_path=args.db,
    )

    print("Vinculado:", {
        "review_status": linked.get("review_status"),
        "linked_client_id": linked.get("linked_client_id"),
        "linked_expedient_id": linked.get("linked_expedient_id"),
        "linked_payment_id": linked.get("linked_payment_id"),
        "linked_at": linked.get("linked_at"),
    })

    summary_linked = get_bank_dashboard_summary(db_path=args.db)
    print("manual_links banco tras vincular:", summary_linked["totals"]["manually_linked_movements"])

    unlinked = unlink_bank_movement(
        movement_id,
        "Prueba automática: revertir vinculación bancaria manual.",
        db_path=args.db,
    )

    print("Desvinculado:", {
        "review_status": unlinked.get("review_status"),
        "linked_client_id": unlinked.get("linked_client_id"),
        "linked_expedient_id": unlinked.get("linked_expedient_id"),
        "linked_payment_id": unlinked.get("linked_payment_id"),
        "linked_at": unlinked.get("linked_at"),
    })

    summary_final = get_bank_dashboard_summary(db_path=args.db)
    print("manual_links banco final:", summary_final["totals"]["manually_linked_movements"])

    print("OK: vinculación bancaria manual probada y revertida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
