from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path("database/quesada.db")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            c.id AS cobro_id,
            c.numero_cobro,
            c.importe AS cobro_importe_eur,
            CAST(ROUND(COALESCE(c.importe, 0) * 100) AS INTEGER) AS cobro_amount_centimos,
            c.estado_conciliacion,

            COALESCE((
                SELECT SUM(COALESCE(NULLIF(b.linked_amount_centimos, 0), b.amount_centimos, 0))
                FROM bank_movements b
                WHERE b.linked_payment_id = c.id
                  AND b.ignored_at IS NULL
            ), 0) AS bank_linked_centimos,

            COALESCE((
                SELECT SUM(COALESCE(NULLIF(cm.linked_amount_centimos, 0), cm.requested_centimos, cm.net_amount_centimos, 0))
                FROM cashmatic_movements cm
                WHERE cm.linked_payment_id = c.id
                  AND cm.ignored_at IS NULL
            ), 0) AS cashmatic_linked_centimos

        FROM eco_cobros c
        WHERE c.id IN (
            SELECT linked_payment_id FROM bank_movements WHERE linked_payment_id IS NOT NULL
            UNION
            SELECT linked_payment_id FROM cashmatic_movements WHERE linked_payment_id IS NOT NULL
        )
        ORDER BY c.id DESC
        LIMIT 100
    """).fetchall()

    print("== Diagnóstico conciliación parcial ==")

    for row in rows:
        data = dict(row)
        total = int(data["cobro_amount_centimos"] or 0)
        linked = int(data["bank_linked_centimos"] or 0) + int(data["cashmatic_linked_centimos"] or 0)
        pending = total - linked

        if linked <= 0:
            computed_status = "PENDIENTE"
        elif linked < total:
            computed_status = "PARCIAL"
        elif linked == total:
            computed_status = "CONCILIADO"
        else:
            computed_status = "SOBRANTE_REVISION"

        print({
            **data,
            "linked_total_centimos": linked,
            "pending_centimos": pending,
            "computed_status": computed_status,
        })

    conn.close()


if __name__ == "__main__":
    main()
