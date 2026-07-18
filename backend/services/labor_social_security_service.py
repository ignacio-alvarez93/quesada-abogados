from __future__ import annotations

import calendar
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import backend.services.expense_service as expense_service
import backend.services.worker_payroll_service as payroll_service


DEFAULT_DB_PATH = Path("database/quesada.db")


def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_period(
    year: int,
    month: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM labor_social_security_periods
            WHERE period_year = ?
              AND period_month = ?
              AND active = 1
            """,
            (
                int(year),
                int(month),
            ),
        ).fetchone()

    return dict(row) if row else None


def sync_period_from_payrolls(
    year: int,
    month: int,
    *,
    payment_due_date: str = "",
    document_path: str = "",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    summary = payroll_service.period_summary(
        year,
        month,
        db_path=db_path,
    )

    if summary["payroll_count"] <= 0:
        raise ValueError(
            "No existen nóminas activas para este periodo"
        )

    employee_amount = summary["employee_ss_centimos"]
    employer_amount = summary["employer_ss_centimos"]
    total_payable = summary["tgss_total_centimos"]

    with closing(_connect(db_path)) as conn:
        current = conn.execute(
            """
            SELECT id
            FROM labor_social_security_periods
            WHERE period_year = ?
              AND period_month = ?
              AND active = 1
            """,
            (
                int(year),
                int(month),
            ),
        ).fetchone()

        if current:
            period_id = int(current["id"])

            conn.execute(
                """
                UPDATE labor_social_security_periods
                SET employee_amount_centimos = ?,
                    employer_amount_centimos = ?,
                    total_payable_centimos = ?,
                    payment_due_date = ?,
                    document_path = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    employee_amount,
                    employer_amount,
                    total_payable,
                    _text(payment_due_date),
                    _text(document_path),
                    _text(notes),
                    period_id,
                ),
            )
        else:
            cursor = conn.execute(
                """
                INSERT INTO labor_social_security_periods (
                    period_year,
                    period_month,
                    payment_due_date,
                    employee_amount_centimos,
                    employer_amount_centimos,
                    other_amount_centimos,
                    total_payable_centimos,
                    document_path,
                    status,
                    notes,
                    active
                )
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'PENDING', ?, 1)
                """,
                (
                    int(year),
                    int(month),
                    _text(payment_due_date),
                    employee_amount,
                    employer_amount,
                    total_payable,
                    _text(document_path),
                    _text(notes),
                ),
            )

            period_id = int(cursor.lastrowid)

        conn.commit()

    return period_id


def _employer_expense_payload(
    period: dict[str, Any],
) -> dict[str, Any]:
    year = int(period["period_year"])
    month = int(period["period_month"])
    employer_centimos = int(
        period["employer_amount_centimos"]
    )
    document_path = _text(
        period.get("document_path")
    )

    expense_date = (
        _text(period.get("payment_due_date"))
        or f"{year:04d}-{month:02d}-01"
    )

    last_day = calendar.monthrange(
        year,
        month,
    )[1]

    return {
        "fecha_gasto": expense_date,
        "fecha_factura": expense_date,
        "proveedor": "TESORERÍA GENERAL SEGURIDAD SOCIAL",
        "supplier_name_snapshot": (
            "TESORERÍA GENERAL SEGURIDAD SOCIAL"
        ),
        "concepto": (
            f"Seguridad Social empresa "
            f"{month:02d}/{year}"
        ),
        "categoria": (
            "Personal · Seguridad Social empresa"
        ),
        "expense_category_code": "PERSONAL",
        "expense_subcategory_code": (
            "SEGURIDAD_SOCIAL_EMPRESA"
        ),
        "classification_source": "MANUAL",
        "tipo_justificante": "SEGUROS_SOCIALES",
        "forma_pago": "DOMICILIACION",
        "base_imponible_centimos": employer_centimos,
        "iva_centimos": 0,
        "irpf_centimos": 0,
        "otros_impuestos_centimos": 0,
        "total_centimos": employer_centimos,
        "importe": employer_centimos / 100,
        "iva_porcentaje": 0,
        "irpf_porcentaje": 0,
        "porcentaje_deducible": 100,
        "deducible_irpf": 1,
        "iva_deducible": 0,
        "deducible": 1,
        "estado_documental": (
            "DOCUMENTO_REVISADO"
            if document_path
            else "SIN_JUSTIFICANTE"
        ),
        "estado_fiscal": "REGISTRADO",
        "estado_conciliacion": (
            "NO_REQUIERE_CONCILIACION"
        ),
        "documento_ruta": document_path,
        "factura_recibida_ruta": document_path,
        "periodo_desde": (
            f"{year:04d}-{month:02d}-01"
        ),
        "periodo_hasta": (
            f"{year:04d}-{month:02d}-{last_day:02d}"
        ),
        "fecha_vencimiento": (
            period.get("payment_due_date")
            or None
        ),
        "observaciones": (
            "Gasto contable correspondiente "
            "solo a la aportación empresarial. "
            "El cargo TGSS completo se concilia "
            "contra la obligación mensual."
        ),
    }


def sync_employer_expense(
    period_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM labor_social_security_periods
            WHERE id = ?
              AND active = 1
            """,
            (int(period_id),),
        ).fetchone()

    if row is None:
        raise ValueError(
            "Periodo de Seguridad Social no encontrado"
        )

    period = dict(row)
    payload = _employer_expense_payload(period)

    expense_id = _integer(
        period.get("employer_expense_id")
    )

    if expense_id:
        expense = expense_service.update_expense(
            expense_id,
            payload,
            db_path=db_path,
        )
    else:
        expense = expense_service.create_expense(
            payload,
            db_path=db_path,
        )
        expense_id = int(expense["id"])

        with closing(_connect(db_path)) as conn:
            conn.execute(
                """
                UPDATE labor_social_security_periods
                SET employer_expense_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    expense_id,
                    int(period_id),
                ),
            )
            conn.commit()

    return expense
