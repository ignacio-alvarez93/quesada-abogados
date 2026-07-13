from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.economic_reconciliation.bank_import_service import (
    ensure_bank_schema,
)
from backend.services.economic_reconciliation.cashmatic_import_service import (
    DEFAULT_DB_PATH,
    connect,
)


@dataclass(frozen=True)
class BankPage:
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

    # No se impone límite artificial al histórico bancario.
    # La vista puede pedir todo el histórico para filtrado/paginación local.
    return max(1, value)



def cents_to_eur(value: int | None) -> float:
    return round((int(value or 0) / 100), 2)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)

    for key in ["amount_centimos", "balance_centimos"]:
        if key in data:
            data[key.replace("_centimos", "_eur")] = cents_to_eur(data.get(key))

    if "warnings_json" in data:
        try:
            data["warnings"] = json.loads(data.get("warnings_json") or "[]")
        except Exception:
            data["warnings"] = []

    return data


def get_bank_dashboard_summary(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    bank_name: str | None = None,
) -> dict[str, Any]:
    where = ["1 = 1"]
    params: list[Any] = []

    if bank_name:
        where.append("bank_name = ?")
        params.append(bank_name)

    where_sql = " AND ".join(f"({part})" for part in where)

    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        batches = conn.execute(
            """
            SELECT
                COUNT(*) AS total_batches,
                COALESCE(SUM(total_rows), 0) AS total_export_rows,
                COALESCE(SUM(candidate_payment_rows), 0) AS total_export_income_rows,
                COALESCE(SUM(quarantine_rows), 0) AS total_export_quarantine_rows
            FROM economic_import_batches
            WHERE source_type IN ('BANK_SANTANDER', 'BANK_CAJA_RURAL', 'BANK_ING')
            """
        ).fetchone()

        totals = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_unique_movements,
                COALESCE(SUM(CASE WHEN amount_centimos > 0 THEN 1 ELSE 0 END), 0) AS income_movements,
                COALESCE(SUM(CASE WHEN amount_centimos < 0 THEN 1 ELSE 0 END), 0) AS expense_movements,
                COALESCE(SUM(CASE WHEN amount_centimos = 0 THEN 1 ELSE 0 END), 0) AS zero_amount_movements,
                COALESCE(SUM(CASE WHEN movement_status = 'QUARANTINE' THEN 1 ELSE 0 END), 0) AS quarantine_movements,
                COALESCE(SUM(CASE WHEN review_status = 'IGNORED' THEN 1 ELSE 0 END), 0) AS ignored_movements,
                COALESCE(SUM(CASE WHEN linked_client_id IS NOT NULL OR linked_expedient_id IS NOT NULL OR linked_payment_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS manually_linked_movements,
                COALESCE(SUM(CASE WHEN amount_centimos > 0 THEN amount_centimos ELSE 0 END), 0) AS total_income_centimos,
                COALESCE(SUM(CASE WHEN amount_centimos < 0 THEN amount_centimos ELSE 0 END), 0) AS total_expense_centimos,
                COALESCE(SUM(amount_centimos), 0) AS net_amount_centimos
            FROM bank_movements
            WHERE {where_sql}
            """,
            params,
        ).fetchone()

        by_status = conn.execute(
            f"""
            SELECT movement_status, COUNT(*) AS total
            FROM bank_movements
            WHERE {where_sql}
            GROUP BY movement_status
            ORDER BY movement_status
            """,
            params,
        ).fetchall()

        by_type = conn.execute(
            f"""
            SELECT movement_type, COUNT(*) AS total
            FROM bank_movements
            WHERE {where_sql}
            GROUP BY movement_type
            ORDER BY movement_type
            """,
            params,
        ).fetchall()

        by_bank = conn.execute(
            """
            SELECT bank_name, COUNT(*) AS total
            FROM bank_movements
            GROUP BY bank_name
            ORDER BY bank_name
            """
        ).fetchall()

        result = {
            "batches": dict(batches or {}),
            "totals": dict(totals or {}),
            "by_status": [dict(row) for row in by_status],
            "by_type": [dict(row) for row in by_type],
            "by_bank": [dict(row) for row in by_bank],
            "manual_linking_policy": (
                "El banco se consulta como movimiento bancario bruto. "
                "No crea cobros, facturas ni vínculos automáticos."
            ),
        }

        for key in [
            "total_income_centimos",
            "total_expense_centimos",
            "net_amount_centimos",
        ]:
            result["totals"][key.replace("_centimos", "_eur")] = cents_to_eur(
                result["totals"].get(key)
            )

        return result


def list_bank_batches(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        rows = conn.execute(
            """
            SELECT
                b.*,
                (
                    SELECT COUNT(*)
                    FROM bank_movements m
                    WHERE m.batch_id = b.id
                ) AS inserted_unique_movements
            FROM economic_import_batches b
            WHERE b.source_type IN ('BANK_SANTANDER', 'BANK_CAJA_RURAL', 'BANK_ING')
            ORDER BY b.created_at DESC, b.id DESC
            """
        ).fetchall()

        return [_row_to_dict(row) for row in rows]


def list_bank_movements(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    page: int = 1,
    page_size: int = 50,
    bank_name: str | None = None,
    movement_status: str | None = None,
    movement_type: str | None = None,
    review_status: str | None = None,
    batch_id: int | None = None,
    only_income: bool = False,
    only_expense: bool = False,
    only_unlinked: bool = False,
    include_ignored: bool = False,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> BankPage:
    page = _normalize_page(page)
    page_size = _normalize_page_size(page_size)
    offset = (page - 1) * page_size

    where = ["1 = 1"]
    params: list[Any] = []

    if bank_name:
        where.append("m.bank_name = ?")
        params.append(bank_name)

    if movement_status:
        where.append("m.movement_status = ?")
        params.append(movement_status)

    if movement_type:
        where.append("m.movement_type = ?")
        params.append(movement_type)

    if review_status:
        where.append("m.review_status = ?")
        params.append(review_status)

    if batch_id is not None:
        where.append("m.batch_id = ?")
        params.append(int(batch_id))

    if only_income:
        where.append("m.amount_centimos > 0")

    if only_expense:
        where.append("m.amount_centimos < 0")

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

    if search:
        like = f"%{search.strip()}%"
        where.append(
            """
            (
                m.concept LIKE ?
                OR m.bank_name LIKE ?
                OR m.account_label LIKE ?
                OR m.account_iban LIKE ?
            )
            """
        )
        params.extend([like, like, like, like])

    if date_from:
        where.append("m.operation_date >= ?")
        params.append(date_from)

    if date_to:
        where.append("m.operation_date <= ?")
        params.append(date_to)

    where_sql = " AND ".join(f"({part})" for part in where)

    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        total_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM bank_movements m
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
            FROM bank_movements m
            JOIN economic_import_batches b ON b.id = m.batch_id
            WHERE {where_sql}
            ORDER BY
                COALESCE(m.operation_date, '') DESC,
                m.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

        return BankPage(
            items=[_row_to_dict(row) for row in rows],
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )


def get_bank_movement_detail(
    movement_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        row = conn.execute(
            """
            SELECT
                m.*,
                b.source_file_name,
                b.source_file_path,
                b.file_sha256 AS batch_file_sha256,
                b.created_at AS batch_created_at
            FROM bank_movements m
            JOIN economic_import_batches b ON b.id = m.batch_id
            WHERE m.id = ?
            """,
            (int(movement_id),),
        ).fetchone()

        if not row:
            return None
        return _row_to_dict(row)


def mark_bank_movement_ignored(
    movement_id: int,
    reason: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Debes indicar un motivo para ignorar el movimiento bancario.")

    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        cursor = conn.execute(
            """
            UPDATE bank_movements
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


def restore_bank_movement(
    movement_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    with connect(db_path) as conn:
        ensure_bank_schema(conn)

        cursor = conn.execute(
            """
            UPDATE bank_movements
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

def _ensure_bank_invoiceability_columns(conn) -> None:
    columns = {
        row["name"] if hasattr(row, "keys") else row[1]
        for row in conn.execute(
            'PRAGMA table_info("bank_movements")'
        ).fetchall()
    }

    migrations = [
        (
            "invoiceability_status",
            """
            ALTER TABLE bank_movements
            ADD COLUMN invoiceability_status
            TEXT NOT NULL DEFAULT 'PENDING'
            """,
        ),
        (
            "invoiceability_reason",
            """
            ALTER TABLE bank_movements
            ADD COLUMN invoiceability_reason TEXT
            """,
        ),
        (
            "invoiceability_updated_at",
            """
            ALTER TABLE bank_movements
            ADD COLUMN invoiceability_updated_at TEXT
            """,
        ),
    ]

    for column, sql in migrations:
        if column not in columns:
            conn.execute(sql)

    conn.execute(
        """
        UPDATE bank_movements
        SET invoiceability_status = 'PENDING'
        WHERE invoiceability_status IS NULL
           OR TRIM(invoiceability_status) = ''
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_bank_movements_invoiceability_status
        ON bank_movements(invoiceability_status)
        """
    )


def mark_bank_movement_non_invoiceable(
    movement_id: int,
    reason: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    reason = str(reason or "").strip()

    if not reason:
        raise ValueError(
            "Debes indicar el motivo por el que "
            "el movimiento no es facturable."
        )

    with connect(db_path) as conn:
        ensure_bank_schema(conn)
        _ensure_bank_invoiceability_columns(conn)

        row = conn.execute(
            """
            SELECT id, amount_centimos
            FROM bank_movements
            WHERE id = ?
            """,
            (int(movement_id),),
        ).fetchone()

        if not row:
            return False

        if int(row["amount_centimos"] or 0) <= 0:
            raise ValueError(
                "Solo los ingresos bancarios positivos pueden "
                "clasificarse como no facturables."
            )

        cursor = conn.execute(
            """
            UPDATE bank_movements
            SET invoiceability_status = 'NON_INVOICEABLE',
                invoiceability_reason = ?,
                invoiceability_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (reason, int(movement_id)),
        )

        conn.commit()
        return cursor.rowcount > 0


def restore_bank_movement_invoiceability(
    movement_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    with connect(db_path) as conn:
        ensure_bank_schema(conn)
        _ensure_bank_invoiceability_columns(conn)

        cursor = conn.execute(
            """
            UPDATE bank_movements
            SET invoiceability_status = 'PENDING',
                invoiceability_reason = NULL,
                invoiceability_updated_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(movement_id),),
        )

        conn.commit()
        return cursor.rowcount > 0
