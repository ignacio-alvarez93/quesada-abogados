from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from backend.services import suplido_service


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
SOURCE_TYPE = "payment"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _effective_recovered(conn: sqlite3.Connection, suplido_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COALESCE(SUM(amount_centimos), 0) AS total
            FROM economic_suplido_recovery_applications
            WHERE suplido_id = ?
            """,
            (int(suplido_id),),
        ).fetchone()["total"]
        or 0
    )


def _sync_suplido(conn: sqlite3.Connection, suplido_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, amount_centimos, active
        FROM economic_suplidos
        WHERE id = ?
        """,
        (int(suplido_id),),
    ).fetchone()
    if not row:
        raise ValueError("No existe el suplido adelantado.")
    total = int(row["amount_centimos"] or 0)
    recovered = _effective_recovered(conn, suplido_id)
    if recovered > total:
        raise ValueError("La recuperación conciliada supera el importe del suplido.")
    if not int(row["active"] or 0):
        status = suplido_service.STATUS_CANCELLED
    elif recovered == 0:
        status = suplido_service.STATUS_PENDING
    elif recovered < total:
        status = suplido_service.STATUS_PARTIAL
    else:
        status = suplido_service.STATUS_RECOVERED
    conn.execute(
        """
        UPDATE economic_suplidos
        SET recovered_amount_centimos = ?, status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (recovered, status, int(suplido_id)),
    )
    return {
        "suplido_id": int(suplido_id),
        "total_centimos": total,
        "recovered_centimos": recovered,
        "status": status,
    }


def link_cobro_to_suplido(
    *,
    cobro_id: int,
    suplido_id: int,
    amount_centimos: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    suplido_service.ensure_schema(db_path)
    amount_centimos = int(amount_centimos)
    if amount_centimos <= 0:
        raise ValueError("El importe vinculado debe ser mayor que cero.")
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cobro = conn.execute(
            """
            SELECT id, cliente_id, importe, tipo_cobro, tipo_fiscal, activo
            FROM eco_cobros WHERE id = ?
            """,
            (int(cobro_id),),
        ).fetchone()
        suplido = conn.execute(
            """
            SELECT id, client_id, amount_centimos, active
            FROM economic_suplidos WHERE id = ?
            """,
            (int(suplido_id),),
        ).fetchone()
        if not cobro or not int(cobro["activo"] or 0):
            raise ValueError("No existe el cobro o está inactivo.")
        if not suplido or not int(suplido["active"] or 0):
            raise ValueError("No existe el suplido o está inactivo.")
        if (
            str(cobro["tipo_cobro"] or "").upper()
            != "SUPLIDO_ADELANTADO"
            and str(cobro["tipo_fiscal"] or "").upper()
            != "SUPLIDO"
        ):
            raise ValueError(
                "El cobro debe ser de tipo SUPLIDO_ADELANTADO."
            )
        if int(cobro["cliente_id"]) != int(suplido["client_id"]):
            raise ValueError("El cobro y el suplido pertenecen a clientes distintos.")
        cobro_total = int(round(float(cobro["importe"] or 0) * 100))
        cobro_aplicado = int(
            conn.execute(
                """
                SELECT COALESCE(SUM(amount_centimos), 0) AS total
                FROM economic_suplido_recovery_applications
                WHERE source_type = ? AND source_id = ?
                """,
                (SOURCE_TYPE, int(cobro_id)),
            ).fetchone()["total"]
            or 0
        )
        if cobro_aplicado + amount_centimos > cobro_total:
            raise ValueError("La vinculación supera el importe del cobro.")
        suplido_aplicado = int(
            conn.execute(
                """
                SELECT COALESCE(SUM(amount_centimos), 0) AS total
                FROM economic_suplido_recovery_applications
                WHERE suplido_id = ?
                """,
                (int(suplido_id),),
            ).fetchone()["total"]
            or 0
        )
        if suplido_aplicado + amount_centimos > int(suplido["amount_centimos"]):
            raise ValueError("La vinculación supera el pendiente del suplido.")
        conn.execute(
            """
            INSERT INTO economic_suplido_recovery_applications(
                source_type, source_id, suplido_id, amount_centimos, notes
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_type, source_id, suplido_id)
            DO UPDATE SET
                amount_centimos = amount_centimos + excluded.amount_centimos,
                notes = CASE WHEN excluded.notes = '' THEN notes ELSE excluded.notes END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                SOURCE_TYPE,
                int(cobro_id),
                int(suplido_id),
                amount_centimos,
                str(notes or "").strip(),
            ),
        )
        sync = _sync_suplido(conn, int(suplido_id))
        conn.execute(
            """
            INSERT INTO eco_eventos(
                entidad, entidad_id, tipo_evento, titulo, descripcion,
                estado_nuevo
            )
            VALUES ('ECONOMIC_SUPLIDOS', ?, 'VINCULACION_COBRO',
                    'COBRO VINCULADO A SUPLIDO', ?, ?)
            """,
            (
                int(suplido_id),
                f"Cobro #{int(cobro_id)}; {amount_centimos} céntimos",
                sync["status"],
            ),
        )
        conn.commit()
        return sync


def sync_for_cobro(
    cobro_id: int, *, db_path: str | Path = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        required_tables = {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name IN (
                      'economic_suplidos',
                      'economic_suplido_recovery_applications'
                  )
                """
            ).fetchall()
        }
        if required_tables != {
            "economic_suplidos",
            "economic_suplido_recovery_applications",
        }:
            return []
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT DISTINCT suplido_id
            FROM economic_suplido_recovery_applications
            WHERE source_type = ? AND source_id = ?
            """,
            (SOURCE_TYPE, int(cobro_id)),
        ).fetchall()
        result = [_sync_suplido(conn, int(row["suplido_id"])) for row in rows]
        conn.commit()
        return result
