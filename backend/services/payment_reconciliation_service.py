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


def list_pending_advanced_payment_clients(
    *, db_path: str | Path = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT DISTINCT
                cl.id,
                cl.nombre,
                cl.primer_apellido,
                cl.segundo_apellido
            FROM clientes cl
            JOIN eco_cobros c ON c.cliente_id = cl.id
            WHERE COALESCE(c.activo, 1) = 1
              AND UPPER(COALESCE(c.tipo_cobro, '')) = 'SUPLIDO_ADELANTADO'
              AND UPPER(COALESCE(c.tipo_fiscal, '')) = 'SUPLIDO'
              AND UPPER(COALESCE(c.estado_conciliacion, 'PENDIENTE'))
                  IN ('PENDIENTE', 'PARCIAL')
            ORDER BY cl.nombre, cl.primer_apellido, cl.segundo_apellido, cl.id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def list_pending_advanced_payments(
    client_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT c.*
            FROM eco_cobros c
            WHERE c.cliente_id = ?
              AND COALESCE(c.activo, 1) = 1
              AND UPPER(COALESCE(c.tipo_cobro, '')) = 'SUPLIDO_ADELANTADO'
              AND UPPER(COALESCE(c.tipo_fiscal, '')) = 'SUPLIDO'
              AND UPPER(COALESCE(c.estado_conciliacion, 'PENDIENTE'))
                  IN ('PENDIENTE', 'PARCIAL')
            ORDER BY c.fecha_cobro DESC, c.id DESC
            """,
            (int(client_id),),
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        totals = reconciliation_totals(int(data["id"]), db_path=db_path)
        data.update(
            {
                "total_centimos": totals["total_centimos"],
                "applied_centimos": totals["applied_centimos"],
                "pending_centimos": totals["pending_centimos"],
            }
        )
        if totals["pending_centimos"] > 0:
            result.append(data)
    return result


def bank_movement_summary(
    movement_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        movement = conn.execute(
            "SELECT * FROM bank_movements WHERE id = ?",
            (int(movement_id),),
        ).fetchone()
        if not movement:
            raise ValueError("No existe el movimiento bancario.")
        total = abs(int(movement["amount_centimos"] or 0))
        applied = int(
            conn.execute(
                """
                SELECT COALESCE(SUM(amount_centimos), 0) AS total
                FROM economic_reconciliation_applications
                WHERE source_type = 'bank' AND source_movement_id = ?
                """,
                (int(movement_id),),
            ).fetchone()["total"]
            or 0
        )
        applications = conn.execute(
            """
            SELECT a.*, c.numero_cobro, c.fecha_cobro,
                   c.concepto, c.importe
            FROM economic_reconciliation_applications a
            JOIN eco_cobros c ON c.id = a.payment_id
            WHERE a.source_type = 'bank' AND a.source_movement_id = ?
            ORDER BY a.created_at, a.id
            """,
            (int(movement_id),),
        ).fetchall()
        return {
            "movement": dict(movement),
            "total_centimos": total,
            "applied_centimos": applied,
            "pending_centimos": max(0, total - applied),
            "applications": [dict(row) for row in applications],
        }


def _sync_bank_movement_summary(
    conn: sqlite3.Connection, movement_id: int
) -> dict[str, Any]:
    summary = conn.execute(
        """
        SELECT
            COALESCE(SUM(a.amount_centimos), 0) AS total,
            MIN(a.payment_id) AS payment_id,
            MIN(c.cliente_id) AS client_id,
            MIN(c.expediente_id) AS expedient_id
        FROM economic_reconciliation_applications a
        LEFT JOIN eco_cobros c ON c.id = a.payment_id
        WHERE a.source_type = 'bank' AND a.source_movement_id = ?
        """,
        (int(movement_id),),
    ).fetchone()
    total = int(summary["total"] or 0)
    conn.execute(
        """
        UPDATE bank_movements
        SET linked_payment_id = ?,
            linked_client_id = ?,
            linked_expedient_id = ?,
            linked_amount_centimos = ?,
            linked_target_type = CASE WHEN ? > 0 THEN 'COBRO' ELSE NULL END,
            linked_at = CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE NULL END,
            review_status = CASE
                WHEN ? > 0 THEN 'MANUALLY_LINKED'
                ELSE 'PENDING_MANUAL_REVIEW'
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            summary["payment_id"],
            summary["client_id"],
            summary["expedient_id"],
            total,
            total,
            total,
            total,
            int(movement_id),
        ),
    )
    return {"applied_centimos": total}


def apply_negative_bank_movement_to_advanced_payment(
    *,
    movement_id: int,
    payment_id: int,
    amount_centimos: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    amount_centimos = int(amount_centimos)
    if amount_centimos <= 0:
        raise ValueError("El importe aplicado debe ser mayor que cero.")
    with _connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        movement = conn.execute(
            "SELECT * FROM bank_movements WHERE id = ?",
            (int(movement_id),),
        ).fetchone()
        payment = conn.execute(
            """
            SELECT * FROM eco_cobros
            WHERE id = ? AND COALESCE(activo, 1) = 1
            """,
            (int(payment_id),),
        ).fetchone()
        if not movement or int(movement["amount_centimos"] or 0) >= 0:
            raise ValueError("El origen debe ser un movimiento bancario negativo.")
        if not payment:
            raise ValueError("No existe el cobro seleccionado.")
        if (
            str(payment["tipo_cobro"] or "").upper() != "SUPLIDO_ADELANTADO"
            or str(payment["tipo_fiscal"] or "").upper() != "SUPLIDO"
        ):
            raise ValueError("El cobro no es un SUPLIDO_ADELANTADO conciliable.")
        movement_applied = int(
            conn.execute(
                """
                SELECT COALESCE(SUM(amount_centimos), 0) AS total
                FROM economic_reconciliation_applications
                WHERE source_type = 'bank' AND source_movement_id = ?
                """,
                (int(movement_id),),
            ).fetchone()["total"]
            or 0
        )
        payment_applied = int(
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
        movement_pending = max(
            0, abs(int(movement["amount_centimos"] or 0)) - movement_applied
        )
        payment_pending = max(
            0,
            int(round(float(payment["importe"] or 0) * 100)) - payment_applied,
        )
        if amount_centimos > movement_pending:
            raise ValueError("El importe supera el pendiente del movimiento.")
        if amount_centimos > payment_pending:
            raise ValueError("El importe supera el pendiente del cobro.")
        existing = conn.execute(
            """
            SELECT id, amount_centimos
            FROM economic_reconciliation_applications
            WHERE source_type = 'bank'
              AND source_movement_id = ?
              AND payment_id = ?
            """,
            (int(movement_id), int(payment_id)),
        ).fetchone()
        if existing:
            application_id = int(existing["id"])
            conn.execute(
                """
                UPDATE economic_reconciliation_applications
                SET amount_centimos = amount_centimos + ?,
                    client_id = ?, expedient_id = ?,
                    notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    amount_centimos,
                    int(payment["cliente_id"]),
                    payment["expediente_id"],
                    str(notes or "").strip(),
                    application_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO economic_reconciliation_applications(
                    source_type, source_movement_id, payment_id,
                    client_id, expedient_id, amount_centimos, notes
                )
                VALUES ('bank', ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(movement_id),
                    int(payment_id),
                    int(payment["cliente_id"]),
                    payment["expediente_id"],
                    amount_centimos,
                    str(notes or "").strip(),
                ),
            )
            application_id = int(cursor.lastrowid)
        _sync_bank_movement_summary(conn, int(movement_id))
        conn.commit()
    payment_totals = sync_payment_status(payment_id, db_path=db_path)
    return {
        "application_id": application_id,
        "payment": payment_totals,
        "movement": bank_movement_summary(movement_id, db_path=db_path),
    }


def remove_negative_bank_payment_application(
    application_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM economic_reconciliation_applications
            WHERE id = ? AND source_type = 'bank'
            """,
            (int(application_id),),
        ).fetchone()
        if not row:
            raise ValueError("No existe la aplicación bancaria.")
        movement_id = int(row["source_movement_id"])
        payment_id = int(row["payment_id"])
        conn.execute(
            "DELETE FROM economic_reconciliation_applications WHERE id = ?",
            (int(application_id),),
        )
        _sync_bank_movement_summary(conn, movement_id)
        conn.commit()
    return {
        "payment": sync_payment_status(payment_id, db_path=db_path),
        "movement": bank_movement_summary(movement_id, db_path=db_path),
    }
