from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.manual_reconciliation_group_service import (  # noqa: E402
    add_reconciliation_group_item,
    create_reconciliation_group,
    get_reconciliation_group_detail,
    group_detail_to_dict,
    remove_reconciliation_group_item,
)


def main() -> int:
    group_id = create_reconciliation_group(
        group_type="CARD_SETTLEMENT",
        title="TEST liquidación TPV 400",
        group_date="2026-07-07",
        notes="Grupo de prueba; debe quedar eliminado al final.",
    )

    add_reconciliation_group_item(
        group_id=group_id,
        source_type="PHYSICAL_RECEIPT",
        role="EXPECTED",
        amount_centimos=10000,
        label="Recibo A 100",
    )
    add_reconciliation_group_item(
        group_id=group_id,
        source_type="PHYSICAL_RECEIPT",
        role="EXPECTED",
        amount_centimos=15000,
        label="Recibo B 150",
    )
    add_reconciliation_group_item(
        group_id=group_id,
        source_type="PHYSICAL_RECEIPT",
        role="EXPECTED",
        amount_centimos=15000,
        label="Recibo C 150",
    )
    bank_item_id = add_reconciliation_group_item(
        group_id=group_id,
        source_type="BANK_MOVEMENT",
        role="ACTUAL",
        amount_centimos=40000,
        label="Liquidación bancaria 400",
    )

    detail = get_reconciliation_group_detail(group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo de prueba")

    print("")
    print("== Test grupo conciliación manual ==")
    print(json.dumps(group_detail_to_dict(detail), ensure_ascii=False, indent=2))

    if detail.group.status != "BALANCED":
        raise RuntimeError(f"Estado esperado BALANCED, recibido {detail.group.status}")

    if detail.group.difference_centimos != 0:
        raise RuntimeError(f"Diferencia esperada 0, recibida {detail.group.difference_centimos}")

    remove_reconciliation_group_item(bank_item_id)
    detail = get_reconciliation_group_detail(group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo tras borrar item")

    print("")
    print("== Tras quitar movimiento bancario ==")
    print(json.dumps(group_detail_to_dict(detail), ensure_ascii=False, indent=2))

    if detail.group.status != "UNBALANCED":
        raise RuntimeError(f"Estado esperado UNBALANCED, recibido {detail.group.status}")

    # Limpiar grupo de prueba.
    with sqlite3.connect("database/quesada.db") as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM economic_reconciliation_groups WHERE id = ?", (group_id,))
        conn.commit()

    print("")
    print("OK: servicio grupos/items funciona y grupo de prueba eliminado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
