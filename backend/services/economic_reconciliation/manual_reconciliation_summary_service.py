from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("database/quesada.db")


@dataclass(frozen=True)
class DailyReconciliationRow:
    date: str
    bank_income_centimos: int
    bank_expense_centimos: int
    bank_net_centimos: int
    bank_movements: int
    bank_unlinked_movements: int
    cashmatic_candidate_centimos: int
    cashmatic_candidate_movements: int
    cashmatic_review_movements: int
    cashmatic_quarantine_movements: int
    manual_links_total: int
    difference_bank_income_vs_cashmatic_centimos: int


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def cents_to_eur(value: int | None) -> float:
    return round((int(value or 0) / 100), 2)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _cashmatic_candidate_amount_expr(conn: sqlite3.Connection) -> str:
    """
    Devuelve expresión SQL de importe efectivo candidato Cashmatic.

    Se evita asumir una única columna porque la staging puede haber cambiado
    durante la fase de importación.
    """
    columns = _table_columns(conn, "cashmatic_movements")

    if "net_centimos" in columns:
        return "COALESCE(net_centimos, 0)"

    if "candidate_net_centimos" in columns:
        return "COALESCE(candidate_net_centimos, 0)"

    if {"inserted_centimos", "dispensed_centimos"}.issubset(columns):
        return "(COALESCE(inserted_centimos, 0) - COALESCE(dispensed_centimos, 0))"

    if {"inserted_amount_centimos", "dispensed_amount_centimos"}.issubset(columns):
        return "(COALESCE(inserted_amount_centimos, 0) - COALESCE(dispensed_amount_centimos, 0))"

    if "inserted_centimos" in columns:
        return "COALESCE(inserted_centimos, 0)"

    if "requested_centimos" in columns:
        return "COALESCE(requested_centimos, 0)"

    if "amount_centimos" in columns:
        return "COALESCE(amount_centimos, 0)"

    raise RuntimeError(
        "No se encontró columna de importe compatible en cashmatic_movements. "
        f"Columnas disponibles: {sorted(columns)}"
    )


def _date_filter_sql(alias: str, date_from: str | None, date_to: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if date_from:
        clauses.append(f"{alias} >= ?")
        params.append(date_from)
    if date_to:
        clauses.append(f"{alias} <= ?")
        params.append(date_to)

    if not clauses:
        return "", []

    return "WHERE " + " AND ".join(clauses), params


def get_daily_manual_reconciliation_summary(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 120,
) -> list[DailyReconciliationRow]:
    """
    Resumen operativo para conciliación manual.

    No crea vínculos.
    No modifica movimientos.
    No crea cobros ni facturas.
    Solo agrega señales por día para revisión humana.
    """
    with connect(db_path) as conn:
        if not _table_exists(conn, "bank_movements"):
            return []

        if not _table_exists(conn, "cashmatic_movements"):
            return []

        bank_where, bank_params = _date_filter_sql("operation_date", date_from, date_to)
        cash_where, cash_params = _date_filter_sql("substr(start_time, 1, 10)", date_from, date_to)
        cashmatic_amount_expr = _cashmatic_candidate_amount_expr(conn)

        bank_rows = conn.execute(
            f"""
            SELECT
                operation_date AS date,
                COALESCE(SUM(CASE WHEN amount_centimos > 0 THEN amount_centimos ELSE 0 END), 0) AS bank_income_centimos,
                COALESCE(SUM(CASE WHEN amount_centimos < 0 THEN amount_centimos ELSE 0 END), 0) AS bank_expense_centimos,
                COALESCE(SUM(amount_centimos), 0) AS bank_net_centimos,
                COUNT(*) AS bank_movements,
                SUM(
                    CASE
                        WHEN linked_client_id IS NULL
                         AND linked_expedient_id IS NULL
                         AND linked_payment_id IS NULL
                         AND ignored_at IS NULL
                        THEN 1 ELSE 0
                    END
                ) AS bank_unlinked_movements,
                SUM(
                    CASE
                        WHEN linked_client_id IS NOT NULL
                          OR linked_expedient_id IS NOT NULL
                          OR linked_payment_id IS NOT NULL
                        THEN 1 ELSE 0
                    END
                ) AS manual_links_total
            FROM bank_movements
            {bank_where}
            GROUP BY operation_date
            """,
            bank_params,
        ).fetchall()

        cash_rows = conn.execute(
            f"""
            SELECT
                substr(start_time, 1, 10) AS date,
                COALESCE(SUM(
                    CASE
                        WHEN movement_status = 'CANDIDATE_PAYMENT_MANUAL_LINK_REQUIRED'
                        THEN {cashmatic_amount_expr} ELSE 0
                    END
                ), 0) AS cashmatic_candidate_centimos,
                SUM(
                    CASE
                        WHEN movement_status = 'CANDIDATE_PAYMENT_MANUAL_LINK_REQUIRED'
                        THEN 1 ELSE 0
                    END
                ) AS cashmatic_candidate_movements,
                SUM(
                    CASE
                        WHEN movement_status = 'PAYMENT_REVIEW_REQUIRED'
                        THEN 1 ELSE 0
                    END
                ) AS cashmatic_review_movements,
                SUM(
                    CASE
                        WHEN movement_status = 'QUARANTINE'
                        THEN 1 ELSE 0
                    END
                ) AS cashmatic_quarantine_movements,
                SUM(
                    CASE
                        WHEN linked_client_id IS NOT NULL
                          OR linked_expedient_id IS NOT NULL
                          OR linked_payment_id IS NOT NULL
                        THEN 1 ELSE 0
                    END
                ) AS manual_links_total
            FROM cashmatic_movements
            {cash_where}
            GROUP BY substr(start_time, 1, 10)
            """,
            cash_params,
        ).fetchall()

    by_date: dict[str, dict[str, int | str]] = {}

    for row in bank_rows:
        date = str(row["date"] or "")
        if not date:
            continue
        by_date.setdefault(date, {"date": date})
        target = by_date[date]
        target["bank_income_centimos"] = int(row["bank_income_centimos"] or 0)
        target["bank_expense_centimos"] = int(row["bank_expense_centimos"] or 0)
        target["bank_net_centimos"] = int(row["bank_net_centimos"] or 0)
        target["bank_movements"] = int(row["bank_movements"] or 0)
        target["bank_unlinked_movements"] = int(row["bank_unlinked_movements"] or 0)
        target["bank_manual_links_total"] = int(row["manual_links_total"] or 0)

    for row in cash_rows:
        date = str(row["date"] or "")
        if not date:
            continue
        by_date.setdefault(date, {"date": date})
        target = by_date[date]
        target["cashmatic_candidate_centimos"] = int(row["cashmatic_candidate_centimos"] or 0)
        target["cashmatic_candidate_movements"] = int(row["cashmatic_candidate_movements"] or 0)
        target["cashmatic_review_movements"] = int(row["cashmatic_review_movements"] or 0)
        target["cashmatic_quarantine_movements"] = int(row["cashmatic_quarantine_movements"] or 0)
        target["cashmatic_manual_links_total"] = int(row["manual_links_total"] or 0)

    result: list[DailyReconciliationRow] = []

    for date in sorted(by_date.keys(), reverse=True):
        data = by_date[date]

        bank_income = int(data.get("bank_income_centimos", 0) or 0)
        bank_expense = int(data.get("bank_expense_centimos", 0) or 0)
        bank_net = int(data.get("bank_net_centimos", 0) or 0)
        cashmatic_candidate = int(data.get("cashmatic_candidate_centimos", 0) or 0)

        result.append(
            DailyReconciliationRow(
                date=date,
                bank_income_centimos=bank_income,
                bank_expense_centimos=bank_expense,
                bank_net_centimos=bank_net,
                bank_movements=int(data.get("bank_movements", 0) or 0),
                bank_unlinked_movements=int(data.get("bank_unlinked_movements", 0) or 0),
                cashmatic_candidate_centimos=cashmatic_candidate,
                cashmatic_candidate_movements=int(data.get("cashmatic_candidate_movements", 0) or 0),
                cashmatic_review_movements=int(data.get("cashmatic_review_movements", 0) or 0),
                cashmatic_quarantine_movements=int(data.get("cashmatic_quarantine_movements", 0) or 0),
                manual_links_total=(
                    int(data.get("bank_manual_links_total", 0) or 0)
                    + int(data.get("cashmatic_manual_links_total", 0) or 0)
                ),
                difference_bank_income_vs_cashmatic_centimos=bank_income - cashmatic_candidate,
            )
        )

    return result[: max(1, int(limit or 120))]


def daily_summary_to_dict(row: DailyReconciliationRow) -> dict[str, Any]:
    data = asdict(row)
    for key in [
        "bank_income_centimos",
        "bank_expense_centimos",
        "bank_net_centimos",
        "cashmatic_candidate_centimos",
        "difference_bank_income_vs_cashmatic_centimos",
    ]:
        eur_key = key.replace("_centimos", "_eur")
        data[eur_key] = cents_to_eur(data[key])
    return data


def get_daily_manual_reconciliation_summary_dict(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 120,
) -> list[dict[str, Any]]:
    return [
        daily_summary_to_dict(row)
        for row in get_daily_manual_reconciliation_summary(
            db_path=db_path,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    ]
