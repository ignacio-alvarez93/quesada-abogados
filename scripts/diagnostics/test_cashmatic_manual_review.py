from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.cashmatic_query_service import (  # noqa: E402
    append_cashmatic_movement_note,
    get_cashmatic_dashboard_summary,
    get_cashmatic_movement_detail,
    list_cashmatic_movements,
    mark_cashmatic_movement_ignored,
    mark_cashmatic_movement_reviewed,
    reset_cashmatic_movement_review,
    restore_cashmatic_movement,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prueba acciones manuales Cashmatic sin vincular cliente/expediente/cobro."
    )
    parser.add_argument("--db", default="database/quesada.db")
    parser.add_argument("--movement-id", type=int, default=0)

    args = parser.parse_args()

    movement_id = args.movement_id
    if not movement_id:
        page = list_cashmatic_movements(
            db_path=args.db,
            page=1,
            page_size=1,
            candidate_payment=True,
            only_unlinked=True,
        )
        if not page.items:
            raise SystemExit("No hay movimiento candidato no vinculado para probar.")
        movement_id = int(page.items[0]["id"])

    print(f"== Movimiento prueba: {movement_id} ==")
    before = get_cashmatic_movement_detail(movement_id, db_path=args.db)
    print("Antes:", {
        "id": before.get("id") if before else None,
        "review_status": before.get("review_status") if before else None,
        "link_notes": before.get("link_notes") if before else None,
        "linked_client_id": before.get("linked_client_id") if before else None,
        "linked_expedient_id": before.get("linked_expedient_id") if before else None,
        "linked_payment_id": before.get("linked_payment_id") if before else None,
    })

    print("Añadir nota:", append_cashmatic_movement_note(
        movement_id,
        "Prueba automática: nota interna sin vinculación.",
        db_path=args.db,
    ))

    print("Marcar revisado:", mark_cashmatic_movement_reviewed(
        movement_id,
        "Prueba automática: revisado manualmente sin vincular.",
        db_path=args.db,
    ))

    reviewed = get_cashmatic_movement_detail(movement_id, db_path=args.db)
    print("Revisado:", {
        "review_status": reviewed.get("review_status") if reviewed else None,
        "link_notes": reviewed.get("link_notes") if reviewed else None,
        "linked_client_id": reviewed.get("linked_client_id") if reviewed else None,
        "linked_expedient_id": reviewed.get("linked_expedient_id") if reviewed else None,
        "linked_payment_id": reviewed.get("linked_payment_id") if reviewed else None,
    })

    print("Reset revisión:", reset_cashmatic_movement_review(movement_id, db_path=args.db))

    print("Ignorar:", mark_cashmatic_movement_ignored(
        movement_id,
        "Prueba automática: ignorado temporalmente.",
        db_path=args.db,
    ))

    ignored = get_cashmatic_movement_detail(movement_id, db_path=args.db)
    print("Ignorado:", {
        "review_status": ignored.get("review_status") if ignored else None,
        "ignored_reason": ignored.get("ignored_reason") if ignored else None,
        "linked_client_id": ignored.get("linked_client_id") if ignored else None,
        "linked_expedient_id": ignored.get("linked_expedient_id") if ignored else None,
        "linked_payment_id": ignored.get("linked_payment_id") if ignored else None,
    })

    print("Restaurar:", restore_cashmatic_movement(movement_id, db_path=args.db))

    after = get_cashmatic_movement_detail(movement_id, db_path=args.db)
    print("Después:", {
        "review_status": after.get("review_status") if after else None,
        "ignored_reason": after.get("ignored_reason") if after else None,
        "linked_client_id": after.get("linked_client_id") if after else None,
        "linked_expedient_id": after.get("linked_expedient_id") if after else None,
        "linked_payment_id": after.get("linked_payment_id") if after else None,
    })

    summary = get_cashmatic_dashboard_summary(db_path=args.db)
    print("manual_links:", summary["movements"]["manually_linked_movements"])

    if summary["movements"]["manually_linked_movements"] != 0:
        raise SystemExit("ERROR: se ha creado alguna vinculación automática.")

    print("OK: acciones manuales probadas sin vinculación automática.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
