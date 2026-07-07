from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.manual_reconciliation_group_service import (  # noqa: E402
    add_cobro_to_group,
    add_reconciliation_group_item,
    create_reconciliation_group,
    get_reconciliation_group_detail,
    group_detail_to_dict,
)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _first_existing_column(columns: set[str], candidates: list[str]) -> str | None:
    for column_name in candidates:
        if column_name in columns:
            return column_name
    return None


def _first_cobro_id() -> int | None:
    with sqlite3.connect("database/quesada.db") as conn:
        table_name = None
        for candidate in ["eco_cobros", "cobros", "economic_cobros", "payments", "pagos"]:
            if _table_exists(conn, candidate):
                table_name = candidate
                break

        if not table_name:
            print("SKIP: no existe tabla de cobros compatible.")
            return None

        columns = _columns(conn, table_name)

        amount_column = _first_existing_column(
            columns,
            [
                "importe_centimos",
                "amount_centimos",
                "total_centimos",
                "importe_total_centimos",
                "importe_cobrado_centimos",
                "cantidad_centimos",
            ],
        )

        if amount_column:
            where = f"COALESCE({amount_column}, 0) > 0"
        else:
            amount_column = _first_existing_column(
                columns,
                ["importe", "amount", "total", "importe_total", "importe_cobrado", "cantidad"],
            )
            if not amount_column:
                print(f"SKIP: tabla {table_name} sin columna de importe compatible: {sorted(columns)}")
                return None
            where = f"COALESCE({amount_column}, 0) > 0"

        row = conn.execute(
            f"""
            SELECT id
            FROM {table_name}
            WHERE {where}
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    return int(row[0]) if row else None


def main() -> int:
    cobro_id = _first_cobro_id()

    if cobro_id is None:
        return 0

    group_id = create_reconciliation_group(
        group_type="BANK_TRANSFER",
        title="TEST cobro real como expected",
        group_date="2026-07-07",
        notes="Grupo de prueba; se elimina al final.",
    )

    add_cobro_to_group(
        group_id=group_id,
        cobro_id=cobro_id,
        role="EXPECTED",
    )

    detail = get_reconciliation_group_detail(group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo tras añadir cobro")

    expected = detail.group.expected_amount_centimos

    add_reconciliation_group_item(
        group_id=group_id,
        source_type="MANUAL_ADJUSTMENT",
        role="ACTUAL",
        amount_centimos=expected,
        label="Ajuste real equivalente para test",
    )

    detail = get_reconciliation_group_detail(group_id)
    if detail is None:
        raise RuntimeError("No se pudo recuperar grupo final")

    print("")
    print("== Test cobro real como EXPECTED ==")
    print(json.dumps(group_detail_to_dict(detail), ensure_ascii=False, indent=2))

    if detail.group.status != "BALANCED":
        raise RuntimeError(f"Grupo debería quedar BALANCED y quedó {detail.group.status}")

    with sqlite3.connect("database/quesada.db") as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "DELETE FROM economic_reconciliation_groups WHERE id = ?",
            (group_id,),
        )
        conn.commit()

    print("")
    print(f"OK: add_cobro_to_group funciona con cobro_id={cobro_id}. Grupo de prueba eliminado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
