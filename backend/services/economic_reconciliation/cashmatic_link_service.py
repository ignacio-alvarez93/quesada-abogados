from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.economic_reconciliation.cashmatic_import_service import (
    DEFAULT_DB_PATH,
    connect,
    ensure_schema,
)
from backend.services.economic_reconciliation.cashmatic_query_service import (
    get_cashmatic_movement_detail,
)


@dataclass(frozen=True)
class CashmaticManualLinkRequest:
    movement_id: int
    client_id: int | None = None
    expedient_id: int | None = None
    payment_id: int | None = None
    gasto_id: int | None = None
    linked_amount_centimos: int | None = None
    linked_by_user_id: int | None = None
    notes: str = ""


def _as_optional_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    if value == "":
        return None
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError(f"ID inválido: {value!r}") from exc
    if parsed <= 0:
        return None
    return parsed




def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except Exception:
        return set()


def _ensure_link_columns(conn: sqlite3.Connection, table_name: str) -> None:
    columns = _columns(conn, table_name)

    if "linked_gasto_id" not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN linked_gasto_id INTEGER")

    columns = _columns(conn, table_name)
    if "linked_amount_centimos" not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN linked_amount_centimos INTEGER NOT NULL DEFAULT 0")

    columns = _columns(conn, table_name)
    if "linked_target_type" not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN linked_target_type TEXT")

def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (table_name,),
    ).fetchone()
    return bool(row)


def _record_exists(conn: sqlite3.Connection, table_name: str, record_id: int) -> bool:
    if not _table_exists(conn, table_name):
        return False

    row = conn.execute(
        f"SELECT 1 FROM {table_name} WHERE id = ? LIMIT 1",
        (int(record_id),),
    ).fetchone()
    return bool(row)


def _validate_optional_fk(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    record_id: int | None,
    label: str,
) -> None:
    if record_id is None:
        return

    if not _table_exists(conn, table_name):
        raise ValueError(
            f"No se puede validar {label} #{record_id}: "
            f"la tabla {table_name!r} no existe en esta base de datos."
        )

    if not _record_exists(conn, table_name, record_id):
        raise ValueError(f"No existe {label} con id={record_id}.")


def _get_movement_for_update(
    conn: sqlite3.Connection,
    movement_id: int,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT *
        FROM cashmatic_movements
        WHERE id = ?
        LIMIT 1
        """,
        (int(movement_id),),
    ).fetchone()

    if not row:
        raise ValueError(f"No existe movimiento Cashmatic id={movement_id}.")

    return row


def _assert_can_link(row: sqlite3.Row) -> None:
    if row["review_status"] == "IGNORED":
        raise ValueError("No se puede vincular un movimiento ignorado. Restáuralo primero.")

    if row["movement_status"] == "QUARANTINE":
        raise ValueError("No se puede vincular un movimiento en cuarentena.")

    if (
        row["linked_client_id"] is not None
        or row["linked_expedient_id"] is not None
        or row["linked_payment_id"] is not None
        or ("linked_gasto_id" in row.keys() and row["linked_gasto_id"] is not None)
    ):
        raise ValueError("El movimiento ya está vinculado. Desvincúlalo antes de volver a vincular.")


def link_cashmatic_movement_manually(
    request: CashmaticManualLinkRequest,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Vincula manualmente un movimiento Cashmatic.

    Esta función NO busca clientes, expedientes ni cobros.
    La futura UI deberá obtener los IDs desde app_autocompletes y pasarlos aquí.
    """
    movement_id = int(request.movement_id)
    client_id = _as_optional_int(request.client_id)
    expedient_id = _as_optional_int(request.expedient_id)
    payment_id = _as_optional_int(request.payment_id)
    gasto_id = _as_optional_int(request.gasto_id)
    linked_by_user_id = _as_optional_int(request.linked_by_user_id)
    notes = (request.notes or "").strip()

    try:
        linked_amount_centimos = int(request.linked_amount_centimos or 0)
    except Exception as exc:
        raise ValueError("Importe conciliado inválido.") from exc

    if client_id is None and expedient_id is None and payment_id is None and gasto_id is None:
        raise ValueError("Debes indicar al menos cliente, expediente, cobro o gasto.")

    if payment_id is not None and gasto_id is not None:
        raise ValueError("No puedes vincular el mismo movimiento a cobro y gasto a la vez.")

    with connect(db_path) as conn:
        ensure_schema(conn)
        _ensure_link_columns(conn, "cashmatic_movements")

        row = _get_movement_for_update(conn, movement_id)
        _assert_can_link(row)

        # Validación estricta si las tablas existen en la base.
        # Si una tabla no existe, fallamos: no queremos crear enlaces fantasma.
        _validate_optional_fk(conn, table_name="clientes", record_id=client_id, label="cliente")
        _validate_optional_fk(conn, table_name="expedientes", record_id=expedient_id, label="expediente")

        # En el histórico del proyecto el pago real se denomina normalmente cobro.
        # La columna staging se llama linked_payment_id para mantener semántica genérica.
        # Compatibilidad: en el esquema actual la tabla real suele ser eco_cobros.
        if payment_id is not None:
            if _table_exists(conn, "eco_cobros"):
                _validate_optional_fk(conn, table_name="eco_cobros", record_id=payment_id, label="cobro")
            else:
                _validate_optional_fk(conn, table_name="cobros", record_id=payment_id, label="cobro")

        _validate_optional_fk(conn, table_name="eco_gastos", record_id=gasto_id, label="gasto")

        linked_target_type = None
        if payment_id is not None:
            linked_target_type = "COBRO"
        elif gasto_id is not None:
            linked_target_type = "GASTO"
        elif expedient_id is not None:
            linked_target_type = "EXPEDIENTE"
        elif client_id is not None:
            linked_target_type = "CLIENTE"

        conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                linked_client_id = ?,
                linked_expedient_id = ?,
                linked_payment_id = ?,
                linked_gasto_id = ?,
                linked_amount_centimos = ?,
                linked_target_type = ?,
                linked_by_user_id = ?,
                linked_at = CURRENT_TIMESTAMP,
                link_notes = CASE
                    WHEN ? = '' THEN link_notes
                    WHEN link_notes IS NULL OR link_notes = '' THEN ?
                    ELSE link_notes || char(10) || ?
                END,
                review_status = 'MANUALLY_LINKED',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                client_id,
                expedient_id,
                payment_id,
                gasto_id,
                linked_amount_centimos,
                linked_target_type,
                linked_by_user_id,
                notes,
                notes,
                notes,
                movement_id,
            ),
        )
        conn.commit()

    detail = get_cashmatic_movement_detail(movement_id, db_path=db_path)
    if not detail:
        raise ValueError(f"No se pudo recuperar movimiento vinculado id={movement_id}.")
    return detail


def unlink_cashmatic_movement(
    movement_id: int,
    reason: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Desvincula un movimiento Cashmatic.

    Conserva trazabilidad en link_notes. No borra el movimiento.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Debes indicar un motivo para desvincular.")

    movement_id = int(movement_id)

    with connect(db_path) as conn:
        ensure_schema(conn)
        _ensure_link_columns(conn, "cashmatic_movements")

        row = _get_movement_for_update(conn, movement_id)

        if (
            row["linked_client_id"] is None
            and row["linked_expedient_id"] is None
            and row["linked_payment_id"] is None
        ):
            raise ValueError("El movimiento no está vinculado.")

        note = f"Desvinculado: {reason}"

        conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                linked_client_id = NULL,
                linked_expedient_id = NULL,
                linked_payment_id = NULL,
                linked_gasto_id = NULL,
                linked_amount_centimos = 0,
                linked_target_type = NULL,
                linked_by_user_id = NULL,
                linked_at = NULL,
                link_notes = CASE
                    WHEN link_notes IS NULL OR link_notes = '' THEN ?
                    ELSE link_notes || char(10) || ?
                END,
                review_status = 'PENDING_MANUAL_REVIEW',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (note, note, movement_id),
        )
        conn.commit()

    detail = get_cashmatic_movement_detail(movement_id, db_path=db_path)
    if not detail:
        raise ValueError(f"No se pudo recuperar movimiento desvinculado id={movement_id}.")
    return detail


def get_cashmatic_link_context(
    movement_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Devuelve contexto para la futura UI de vinculación.

    La UI deberá montar app_autocompletes para cliente, expediente y cobro.
    """
    detail = get_cashmatic_movement_detail(int(movement_id), db_path=db_path)
    if not detail:
        raise ValueError(f"No existe movimiento Cashmatic id={movement_id}.")

    return {
        "movement": detail,
        "autocomplete_targets": {
            "client": {
                "component": "app_autocomplete",
                "target_table": "clientes",
                "id_field": "id",
                "destination_field": "linked_client_id",
            },
            "expedient": {
                "component": "app_autocomplete",
                "target_table": "expedientes",
                "id_field": "id",
                "destination_field": "linked_expedient_id",
            },
            "payment": {
                "component": "app_autocomplete",
                "target_table": "eco_cobros",
                "id_field": "id",
                "destination_field": "linked_payment_id",
            },
            "gasto": {
                "component": "selector",
                "target_table": "eco_gastos",
                "id_field": "id",
                "destination_field": "linked_gasto_id",
            },
        },
        "rules": [
            "La búsqueda/selección se hace en UI mediante app_autocompletes.",
            "El backend solo acepta IDs explícitos.",
            "No se vinculan movimientos ignorados.",
            "No se vinculan movimientos en cuarentena.",
            "No se permite doble vinculación sin desvincular antes.",
            "Debe indicarse al menos cliente, expediente o cobro.",
        ],
    }
