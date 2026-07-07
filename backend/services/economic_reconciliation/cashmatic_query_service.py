from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.economic_reconciliation.cashmatic_import_service import (
    DEFAULT_DB_PATH,
    connect,
    ensure_schema,
)


@dataclass(frozen=True)
class CashmaticPage:
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def _normalize_page(page: int) -> int:
    try:
        value = int(page)
    except Exception:
        value = 1
    return max(1, value)


def _normalize_page_size(page_size: int) -> int:
    try:
        value = int(page_size)
    except Exception:
        value = 50

    # No se impone límite artificial al histórico.
    # La paginación decide cuántos registros se piden en cada caso.
    return max(1, value)


    # El visor de Económico > Movimientos carga en memoria para filtrar/paginar
    # localmente. Cashmatic puede tener varios miles de movimientos.
    # Límite seguro temporal hasta migrar a paginación backend real.
    return min(max(1, value), 5000)


def cents_to_eur(value: int | None) -> float:
    return round((int(value or 0) / 100), 2)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)

    for key in [
        "requested_centimos",
        "inserted_centimos",
        "dispensed_centimos",
        "not_dispensed_centimos",
        "net_amount_centimos",
    ]:
        if key in data:
            data[key.replace("_centimos", "_eur")] = cents_to_eur(data.get(key))

    if "candidate_payment" in data:
        data["candidate_payment"] = bool(data["candidate_payment"])

    if "warnings_json" in data:
        try:
            data["warnings"] = json.loads(data.get("warnings_json") or "[]")
        except Exception:
            data["warnings"] = []
    return data


def get_cashmatic_dashboard_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        ensure_schema(conn)

        batches = conn.execute(
            """
            SELECT
                COUNT(*) AS total_batches,
                COALESCE(SUM(total_rows), 0) AS total_export_rows,
                COALESCE(SUM(candidate_payment_rows), 0) AS total_export_candidate_rows,
                COALESCE(SUM(quarantine_rows), 0) AS total_export_quarantine_rows
            FROM economic_import_batches
            WHERE source_type = 'CASHMATIC'
            """
        ).fetchone()

        movements = conn.execute(
            """
            SELECT
                COUNT(*) AS total_unique_movements,
                COALESCE(SUM(CASE WHEN candidate_payment = 1 THEN 1 ELSE 0 END), 0) AS candidate_payment_movements,
                COALESCE(SUM(CASE WHEN movement_status = 'PAYMENT_REVIEW_REQUIRED' THEN 1 ELSE 0 END), 0) AS review_required_movements,
                COALESCE(SUM(CASE WHEN movement_status = 'INTERNAL_CASHMATIC_MOVEMENT' THEN 1 ELSE 0 END), 0) AS internal_movements,
                COALESCE(SUM(CASE WHEN movement_status = 'QUARANTINE' THEN 1 ELSE 0 END), 0) AS quarantine_movements,
                COALESCE(SUM(CASE WHEN review_status = 'IGNORED' THEN 1 ELSE 0 END), 0) AS ignored_movements,
                COALESCE(SUM(CASE WHEN linked_client_id IS NOT NULL OR linked_expedient_id IS NOT NULL OR linked_payment_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS manually_linked_movements,
                COALESCE(SUM(CASE WHEN candidate_payment = 1 THEN net_amount_centimos ELSE 0 END), 0) AS candidate_net_centimos
            FROM cashmatic_movements
            """
        ).fetchone()

        by_status = conn.execute(
            """
            SELECT movement_status, COUNT(*) AS total
            FROM cashmatic_movements
            GROUP BY movement_status
            ORDER BY movement_status
            """
        ).fetchall()

        by_operation = conn.execute(
            """
            SELECT operation, COUNT(*) AS total
            FROM cashmatic_movements
            GROUP BY operation
            ORDER BY operation
            """
        ).fetchall()

        result = {
            "batches": dict(batches or {}),
            "movements": dict(movements or {}),
            "by_status": [dict(row) for row in by_status],
            "by_operation": [dict(row) for row in by_operation],
            "manual_linking_policy": (
                "La vinculación con cliente, expediente o cobro es manual. "
                "Este servicio solo consulta y clasifica movimientos Cashmatic."
            ),
        }

        result["movements"]["candidate_net_eur"] = cents_to_eur(
            result["movements"].get("candidate_net_centimos")
        )
        return result


def list_cashmatic_batches(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        ensure_schema(conn)

        rows = conn.execute(
            """
            SELECT
                b.*,
                (
                    SELECT COUNT(*)
                    FROM cashmatic_movements m
                    WHERE m.batch_id = b.id
                ) AS inserted_unique_movements
            FROM economic_import_batches b
            WHERE b.source_type = 'CASHMATIC'
            ORDER BY b.created_at DESC, b.id DESC
            """
        ).fetchall()

        return [_row_to_dict(row) for row in rows]


def list_cashmatic_movements(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    page: int = 1,
    page_size: int = 50,
    movement_status: str | None = None,
    operation: str | None = None,
    review_status: str | None = None,
    candidate_payment: bool | None = None,
    batch_id: int | None = None,
    search: str | None = None,
    only_unlinked: bool = False,
    include_ignored: bool = False,
) -> CashmaticPage:
    page = _normalize_page(page)
    page_size = _normalize_page_size(page_size)
    offset = (page - 1) * page_size

    where = ["1 = 1"]
    params: list[Any] = []

    if movement_status:
        where.append("m.movement_status = ?")
        params.append(movement_status)

    if operation:
        where.append("m.operation = ?")
        params.append(operation)

    if review_status:
        where.append("m.review_status = ?")
        params.append(review_status)

    if candidate_payment is not None:
        where.append("m.candidate_payment = ?")
        params.append(1 if candidate_payment else 0)

    if batch_id is not None:
        where.append("m.batch_id = ?")
        params.append(int(batch_id))

    if search:
        like = f"%{search.strip()}%"
        where.append(
            """
            (
                m.reason_raw LIKE ?
                OR m.reference_raw LIKE ?
                OR m.cashmatic_id LIKE ?
                OR m.source_raw LIKE ?
                OR m.user_username LIKE ?
            )
            """
        )
        params.extend([like, like, like, like, like])

    if only_unlinked:
        where.append(
            """
            m.linked_client_id IS NULL
            AND m.linked_expedient_id IS NULL
            AND m.linked_payment_id IS NULL
            """
        )

    if not include_ignored:
        where.append("m.review_status != 'IGNORED'")

    where_sql = " AND ".join(f"({part})" for part in where)

    with connect(db_path) as conn:
        ensure_schema(conn)

        total_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM cashmatic_movements m
            WHERE {where_sql}
            """,
            params,
        ).fetchone()

        total_items = int((total_row or {"total": 0})["total"])
        total_pages = max(1, (total_items + page_size - 1) // page_size)

        rows = conn.execute(
            f"""
            SELECT
                m.*,
                b.source_file_name,
                b.file_sha256 AS batch_file_sha256
            FROM cashmatic_movements m
            JOIN economic_import_batches b ON b.id = m.batch_id
            WHERE {where_sql}
            ORDER BY
                COALESCE(m.start_time, '') DESC,
                m.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

        return CashmaticPage(
            items=[_row_to_dict(row) for row in rows],
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )


def get_cashmatic_movement_detail(
    movement_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        ensure_schema(conn)

        row = conn.execute(
            """
            SELECT
                m.*,
                b.source_file_name,
                b.source_file_path,
                b.file_sha256 AS batch_file_sha256,
                b.created_at AS batch_created_at
            FROM cashmatic_movements m
            JOIN economic_import_batches b ON b.id = m.batch_id
            WHERE m.id = ?
            """,
            (int(movement_id),),
        ).fetchone()

        if not row:
            return None
        return _row_to_dict(row)


def mark_cashmatic_movement_ignored(
    movement_id: int,
    reason: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Debes indicar un motivo para ignorar el movimiento.")

    with connect(db_path) as conn:
        ensure_schema(conn)

        cursor = conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                review_status = 'IGNORED',
                ignored_at = CURRENT_TIMESTAMP,
                ignored_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND linked_client_id IS NULL
              AND linked_expedient_id IS NULL
              AND linked_payment_id IS NULL
            """,
            (reason, int(movement_id)),
        )
        conn.commit()
        return cursor.rowcount > 0


def restore_cashmatic_movement(
    movement_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    with connect(db_path) as conn:
        ensure_schema(conn)

        cursor = conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                review_status = 'PENDING_MANUAL_REVIEW',
                ignored_at = NULL,
                ignored_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(movement_id),),
        )
        conn.commit()
        return cursor.rowcount > 0


def mark_cashmatic_movement_reviewed(
    movement_id: int,
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Marca un movimiento como revisado sin vincularlo.

    Esta acción NO crea cliente, expediente, cobro ni conciliación.
    Sirve para dejar constancia de revisión humana previa.
    """
    notes = (notes or "").strip()

    with connect(db_path) as conn:
        ensure_schema(conn)

        cursor = conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                review_status = 'REVIEWED',
                link_notes = CASE
                    WHEN ? = '' THEN link_notes
                    WHEN link_notes IS NULL OR link_notes = '' THEN ?
                    ELSE link_notes || char(10) || ?
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND review_status != 'IGNORED'
              AND linked_client_id IS NULL
              AND linked_expedient_id IS NULL
              AND linked_payment_id IS NULL
            """,
            (notes, notes, notes, int(movement_id)),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_cashmatic_movement_notes(
    movement_id: int,
    notes: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Actualiza la nota interna del movimiento.

    No vincula el movimiento. Solo guarda observación humana.
    """
    notes = (notes or "").strip()

    with connect(db_path) as conn:
        ensure_schema(conn)

        cursor = conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                link_notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (notes, int(movement_id)),
        )
        conn.commit()
        return cursor.rowcount > 0


def append_cashmatic_movement_note(
    movement_id: int,
    note: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Añade una nota al movimiento sin sustituir notas anteriores."""
    note = (note or "").strip()
    if not note:
        raise ValueError("Debes indicar una nota.")

    with connect(db_path) as conn:
        ensure_schema(conn)

        cursor = conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                link_notes = CASE
                    WHEN link_notes IS NULL OR link_notes = '' THEN ?
                    ELSE link_notes || char(10) || ?
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (note, note, int(movement_id)),
        )
        conn.commit()
        return cursor.rowcount > 0


def reset_cashmatic_movement_review(
    movement_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Devuelve un movimiento revisado a pendiente de revisión.

    No modifica campos de vinculación manual.
    """
    with connect(db_path) as conn:
        ensure_schema(conn)

        cursor = conn.execute(
            """
            UPDATE cashmatic_movements
            SET
                review_status = 'PENDING_MANUAL_REVIEW',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND review_status = 'REVIEWED'
              AND linked_client_id IS NULL
              AND linked_expedient_id IS NULL
              AND linked_payment_id IS NULL
            """,
            (int(movement_id),),
        )
        conn.commit()
        return cursor.rowcount > 0
