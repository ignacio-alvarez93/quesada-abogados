from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.manual_reconciliation_group_service import (  # noqa: E402
    add_bank_movement_to_group,
    add_cashmatic_movement_to_group,
    add_reconciliation_group_item,
    create_reconciliation_group,
    get_reconciliation_group_detail,
    group_detail_to_dict,
)


def _first_bank_movement_id() -> int:
    with sqlite3.connect("database/quesada.db") as conn:
        row = conn.execute(
            """
            SELECT id
            FROM bank_movements
            WHERE amount_centimos > 0
            ORDER BY operation_date DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise RuntimeError("No hay movimientos bancarios positivos para probar")
    return int(row[0])


def _first_cashmatic_candidate_id() -> int:
    with sqlite3.connect("database/quesada.db") as conn:
        row = conn.execute(
            """
            SELECT id
            FROM cashmatic_movements
            WHERE movement_status = 'CANDIDATE_PAYMENT_MANUAL_LINK_REQUIRED'
            ORDER BY start_time DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise RuntimeError("No hay movimientos Cashmatic candidatos para probar")
    return int(row[0])


def main() -> int:
    bank_id = _first_bank_movement_id()
    cashmatic_id = _first_cashmatic_candidate_id()

    bank_group_id = create_reconciliation_group(
        group_type="BANK_TRANSFER",
        title="TEST movimiento banco real",
        group_date="2026-07-07",
        notes="Grupo de prueba; se elimina al final.",
    )

    bank_item_id = add_bank_movement_to_group(
        group_id=bank_group_id,
        bank_movement_id=bank_id,
        role="ACTUAL",
    )

    detail = get_reconciliation_group_detail(bank_group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo banco")

    actual = detail.group.actual_amount_centimos
    add_reconciliation_group_item(
        group_id=bank_group_id,
        source_type="PHYSICAL_RECEIPT",
        role="EXPECTED",
        amount_centimos=actual,
        label="Recibo físico equivalente a banco real",
    )

    detail = get_reconciliation_group_detail(bank_group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo banco final")

    print("")
    print("== Test item banco real ==")
    print(json.dumps(group_detail_to_dict(detail), ensure_ascii=False, indent=2))

    if detail.group.status != "BALANCED":
        raise RuntimeError(f"Grupo banco debería quedar BALANCED y quedó {detail.group.status}")

    cash_group_id = create_reconciliation_group(
        group_type="CASH_RECEIPT",
        title="TEST movimiento Cashmatic real",
        group_date="2026-07-07",
        notes="Grupo de prueba; se elimina al final.",
    )

    add_cashmatic_movement_to_group(
        group_id=cash_group_id,
        cashmatic_movement_id=cashmatic_id,
        role="ACTUAL",
    )

    detail = get_reconciliation_group_detail(cash_group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo Cashmatic")

    actual = detail.group.actual_amount_centimos
    add_reconciliation_group_item(
        group_id=cash_group_id,
        source_type="PHYSICAL_RECEIPT",
        role="EXPECTED",
        amount_centimos=actual,
        label="Recibo físico equivalente a Cashmatic real",
    )

    detail = get_reconciliation_group_detail(cash_group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo Cashmatic final")

    print("")
    print("== Test item Cashmatic real ==")
    print(json.dumps(group_detail_to_dict(detail), ensure_ascii=False, indent=2))

    if detail.group.status != "BALANCED":
        raise RuntimeError(f"Grupo Cashmatic debería quedar BALANCED y quedó {detail.group.status}")

    with sqlite3.connect("database/quesada.db") as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "DELETE FROM economic_reconciliation_groups WHERE id IN (?, ?)",
            (bank_group_id, cash_group_id),
        )
        conn.commit()

    print("")
    print(
        "OK: helpers de movimientos reales funcionan. "
        f"bank_item_id={bank_item_id}, bank_movement_id={bank_id}, cashmatic_movement_id={cashmatic_id}. "
        "Grupos de prueba eliminados."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
