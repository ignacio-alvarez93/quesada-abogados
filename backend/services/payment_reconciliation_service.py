from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


def _connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS economic_reconciliation_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_movement_id INTEGER NOT NULL,
            payment_id INTEGER NOT NULL,
            client_id INTEGER,
            expedient_id INTEGER,
            amount_centimos INTEGER NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_type, source_movement_id, payment_id)
        )
        """
    )


def reconciliation_totals(
    payment_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        payment = conn.execute(
            """
            SELECT id, importe, estado_conciliacion
            FROM eco_cobros
            WHERE id = ? AND COALESCE(activo, 1) = 1
            """,
            (int(payment_id),),
        ).fetchone()
        if not payment:
            raise ValueError("No existe el cobro o está inactivo.")
        total = int(round(float(payment["importe"] or 0) * 100))
        applications = int(
            conn.execute(
                """
                SELECT COALESCE(SUM(amount_centimos), 0) AS total
                FROM economic_reconciliation_applications
                WHERE payment_id = ?
                """,
                (int(payment_id),),
            ).fetchone()["total"]
            or 0
        )
        bank_legacy = 0
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bank_movements'"
        ).fetchone():
            bank_legacy = int(
                conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        ABS(COALESCE(NULLIF(b.linked_amount_centimos, 0),
                                     b.amount_centimos, 0))
                    ), 0) AS total
                    FROM bank_movements b
                    WHERE b.linked_payment_id = ?
                      AND b.ignored_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM economic_reconciliation_applications a
                          WHERE a.source_type = 'bank'
                            AND a.source_movement_id = b.id
                            AND a.payment_id = b.linked_payment_id
                      )
                    """,
                    (int(payment_id),),
                ).fetchone()["total"]
                or 0
            )
        cashmatic_legacy = 0
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cashmatic_movements'"
        ).fetchone():
            cashmatic_legacy = int(
                conn.execute(
                    """
                    SELECT COALESCE(SUM(
                        ABS(COALESCE(NULLIF(c.linked_amount_centimos, 0),
                                     c.requested_centimos,
                                     c.net_amount_centimos, 0))
                    ), 0) AS total
                    FROM cashmatic_movements c
                    WHERE c.linked_payment_id = ?
                      AND c.ignored_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM economic_reconciliation_applications a
                          WHERE a.source_type = 'cashmatic'
                            AND a.source_movement_id = c.id
                            AND a.payment_id = c.linked_payment_id
                      )
                    """,
                    (int(payment_id),),
                ).fetchone()["total"]
                or 0
            )
        applied = applications + bank_legacy + cashmatic_legacy
        if applied <= 0:
            status = "PENDIENTE"
        elif applied < total:
            status = "PARCIAL"
        elif applied == total:
            status = "CONCILIADO"
        else:
            status = "SOBRANTE_REVISION"
        return {
            "payment_id": int(payment_id),
            "total_centimos": total,
            "applied_centimos": applied,
            "pending_centimos": max(0, total - applied),
            "status": status,
        }


def sync_payment_status(
    payment_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    totals = reconciliation_totals(payment_id, db_path=db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE eco_cobros
            SET estado_conciliacion = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (totals["status"], int(payment_id)),
        )
        conn.commit()
    return totals


def set_application(
    *,
    source_type: str,
    source_movement_id: int,
    payment_id: int,
    amount_centimos: int,
    client_id: int | None = None,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    amount_centimos = int(amount_centimos)
    if amount_centimos <= 0:
        raise ValueError("El importe aplicado debe ser mayor que cero.")
    with _connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO economic_reconciliation_applications(
                source_type, source_movement_id, payment_id,
                client_id, amount_centimos, notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_type, source_movement_id, payment_id)
            DO UPDATE SET amount_centimos = excluded.amount_centimos,
                          client_id = excluded.client_id,
                          notes = excluded.notes,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(source_type).strip().lower(),
                int(source_movement_id),
                int(payment_id),
                client_id,
                amount_centimos,
                str(notes or "").strip(),
            ),
        )
        conn.commit()
    return sync_payment_status(payment_id, db_path=db_path)


def remove_application(
    *,
    source_type: str,
    source_movement_id: int,
    payment_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            DELETE FROM economic_reconciliation_applications
            WHERE source_type = ?
              AND source_movement_id = ?
              AND payment_id = ?
            """,
            (
                str(source_type).strip().lower(),
                int(source_movement_id),
                int(payment_id),
            ),
        )
        conn.commit()
    return sync_payment_status(payment_id, db_path=db_path)
