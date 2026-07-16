from __future__ import annotations

import sqlite3
from calendar import monthrange
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")

VALID_QUARTERS = {1, 2, 3, 4}

CONFIRMED_INVOICE_STATES = {
    "APROBADA",
    "EXPORTADA",
}

PROVISIONAL_INVOICE_STATES = {
    "EMITIDA",
    "APROBADA",
    "EXPORTADA",
}

CONFIRMED_EXPENSE_STATES = {
    "DEDUCIBLE",
    "PARCIALMENTE_DEDUCIBLE",
}

PENDING_EXPENSE_STATES = {
    "PENDIENTE_REVISION",
    "PENDIENTE_REVISIÓN",
}


@dataclass(frozen=True)
class FiscalPeriod:
    year: int
    quarter: int
    start_date: str
    end_date: str
    cumulative_start_date: str


@contextmanager
def _connect(
    db_path: Path | str = DEFAULT_DB_PATH,
):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    try:
        yield conn
    finally:
        conn.close()


def _dict(row: sqlite3.Row | None) -> dict:
    return dict(row) if row else {}


def _money_to_centimos(value: Any) -> int:
    try:
        return int(round(float(value or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize(value: Any) -> str:
    return str(value or "").strip().upper()


def _percentage(value: Any) -> float:
    percentage = _float(value)

    if percentage < 0:
        return 0.0

    if percentage > 100:
        return 100.0

    return percentage


def _apply_percentage(
    amount_centimos: Any,
    percentage: Any,
) -> int:
    amount = _int(amount_centimos)
    rate = _percentage(percentage)

    return int(round(amount * rate / 100.0))


def resolve_period(
    year: int,
    quarter: int,
) -> FiscalPeriod:
    year = int(year)
    quarter = int(quarter)

    if quarter not in VALID_QUARTERS:
        raise ValueError(
            "El trimestre debe estar entre 1 y 4"
        )

    if year < 2000 or year > 2200:
        raise ValueError(
            "El ejercicio fiscal no es válido"
        )

    start_month = ((quarter - 1) * 3) + 1
    end_month = start_month + 2
    end_day = monthrange(year, end_month)[1]

    return FiscalPeriod(
        year=year,
        quarter=quarter,
        start_date=date(
            year,
            start_month,
            1,
        ).isoformat(),
        end_date=date(
            year,
            end_month,
            end_day,
        ).isoformat(),
        cumulative_start_date=date(
            year,
            1,
            1,
        ).isoformat(),
    )


def _invoice_is_confirmed(invoice: dict) -> bool:
    if not _int(invoice.get("activo", 1)):
        return False

    if _normalize(invoice.get("tipo_fiscal")) == "SUPLIDO":
        return False

    if _normalize(invoice.get("estado")) not in (
        CONFIRMED_INVOICE_STATES
    ):
        return False

    return bool(
        _int(invoice.get("exportada_holded"))
        or _normalize(invoice.get("estado"))
        in CONFIRMED_INVOICE_STATES
    )


def _invoice_is_provisional(invoice: dict) -> bool:
    if not _int(invoice.get("activo", 1)):
        return False

    if _normalize(invoice.get("tipo_fiscal")) == "SUPLIDO":
        return False

    return (
        _normalize(invoice.get("estado"))
        in PROVISIONAL_INVOICE_STATES
    )


def _expense_is_confirmed(
    expense: dict,
    *,
    tax_kind: str,
) -> bool:
    if not _int(expense.get("activo", 1)):
        return False

    state = _normalize(
        expense.get("estado_fiscal")
    )

    if state not in CONFIRMED_EXPENSE_STATES:
        return False

    if tax_kind == "iva":
        return bool(
            _int(expense.get("iva_deducible"))
        )

    if tax_kind == "irpf":
        return bool(
            _int(
                expense.get(
                    "deducible_irpf",
                    expense.get("deducible"),
                )
            )
        )

    raise ValueError(
        f"Tipo fiscal no soportado: {tax_kind}"
    )


def _expense_is_provisional(
    expense: dict,
    *,
    tax_kind: str,
) -> bool:
    if not _int(expense.get("activo", 1)):
        return False

    state = _normalize(
        expense.get("estado_fiscal")
    )

    if state in {
        "NO_DEDUCIBLE",
        "EXCLUIDO",
        "EXCLUIDA",
    }:
        return False

    if state not in (
        CONFIRMED_EXPENSE_STATES
        | PENDING_EXPENSE_STATES
    ):
        return False

    if tax_kind == "iva":
        return bool(
            _int(expense.get("iva_deducible"))
        )

    if tax_kind == "irpf":
        return bool(
            _int(
                expense.get(
                    "deducible_irpf",
                    expense.get("deducible"),
                )
            )
        )

    raise ValueError(
        f"Tipo fiscal no soportado: {tax_kind}"
    )


def _load_invoices(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            id,
            numero_factura,
            fecha_factura,
            base_imponible,
            iva,
            irpf,
            suplidos,
            total,
            tipo_fiscal,
            tipo_factura,
            factura_rectificada_id,
            estado,
            exportada_holded,
            activo
        FROM eco_facturas
        WHERE fecha_factura >= ?
          AND fecha_factura <= ?
          AND COALESCE(activo, 1) = 1
        ORDER BY fecha_factura, id
        """,
        (
            date_from,
            date_to,
        ),
    ).fetchall()

    return [dict(row) for row in rows]


def _load_expenses(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            id,
            COALESCE(
                NULLIF(fecha_factura, ''),
                fecha_gasto
            ) AS fecha_fiscal,
            fecha_factura,
            fecha_gasto,
            proveedor,
            concepto,
            numero_factura,
            base_imponible_centimos,
            iva_centimos,
            total_centimos,
            porcentaje_deducible,
            iva_deducible,
            deducible_irpf,
            deducible,
            estado_fiscal,
            estado_documental,
            activo
        FROM eco_gastos
        WHERE COALESCE(
                NULLIF(fecha_factura, ''),
                fecha_gasto
              ) >= ?
          AND COALESCE(
                NULLIF(fecha_factura, ''),
                fecha_gasto
              ) <= ?
          AND COALESCE(activo, 1) = 1
        ORDER BY fecha_fiscal, id
        """,
        (
            date_from,
            date_to,
        ),
    ).fetchall()

    return [dict(row) for row in rows]


def list_model_303_entries(
    year: int,
    quarter: int,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    period = resolve_period(year, quarter)

    with _connect(db_path) as conn:
        invoices = _load_invoices(
            conn,
            period.start_date,
            period.end_date,
        )
        expenses = _load_expenses(
            conn,
            period.start_date,
            period.end_date,
        )

    invoice_entries = []

    for invoice in invoices:
        confirmed = _invoice_is_confirmed(invoice)
        provisional = _invoice_is_provisional(invoice)

        invoice_entries.append(
            {
                **invoice,
                "base_centimos":
                    _money_to_centimos(
                        invoice.get("base_imponible")
                    ),
                "iva_centimos":
                    _money_to_centimos(
                        invoice.get("iva")
                    ),
                "confirmed": confirmed,
                "provisional": provisional,
                "included_reason": (
                    "FACTURA_APROBADA"
                    if confirmed
                    else (
                        "FACTURA_EMITIDA_PENDIENTE"
                        if provisional
                        else "FACTURA_EXCLUIDA"
                    )
                ),
            }
        )

    expense_entries = []

    for expense in expenses:
        percentage = _percentage(
            expense.get("porcentaje_deducible")
        )

        deductible_vat = _apply_percentage(
            expense.get("iva_centimos"),
            percentage,
        )

        confirmed = _expense_is_confirmed(
            expense,
            tax_kind="iva",
        )
        provisional = _expense_is_provisional(
            expense,
            tax_kind="iva",
        )

        expense_entries.append(
            {
                **expense,
                "iva_deducible_centimos":
                    deductible_vat,
                "confirmed": confirmed,
                "provisional": provisional,
                "included_reason": (
                    "GASTO_REVISADO"
                    if confirmed
                    else (
                        "GASTO_PENDIENTE"
                        if provisional
                        else "GASTO_EXCLUIDO"
                    )
                ),
            }
        )

    return {
        "model": "303",
        "year": period.year,
        "quarter": period.quarter,
        "period_start": period.start_date,
        "period_end": period.end_date,
        "invoices": invoice_entries,
        "expenses": expense_entries,
    }


def estimate_model_303(
    year: int,
    quarter: int,
    *,
    compensation_previous_centimos: int = 0,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    entries = list_model_303_entries(
        year,
        quarter,
        db_path=db_path,
    )

    invoices = entries["invoices"]
    expenses = entries["expenses"]

    confirmed_output_vat = sum(
        _int(item.get("iva_centimos"))
        for item in invoices
        if item.get("confirmed")
    )

    provisional_output_vat = sum(
        _int(item.get("iva_centimos"))
        for item in invoices
        if item.get("provisional")
    )

    confirmed_input_vat = sum(
        _int(item.get("iva_deducible_centimos"))
        for item in expenses
        if item.get("confirmed")
    )

    provisional_input_vat = sum(
        _int(item.get("iva_deducible_centimos"))
        for item in expenses
        if item.get("provisional")
    )

    compensation = max(
        0,
        _int(compensation_previous_centimos),
    )

    confirmed_result = (
        confirmed_output_vat
        - confirmed_input_vat
        - compensation
    )

    provisional_result = (
        provisional_output_vat
        - provisional_input_vat
        - compensation
    )

    return {
        "model": "303",
        "year": entries["year"],
        "quarter": entries["quarter"],
        "period_start": entries["period_start"],
        "period_end": entries["period_end"],
        "confirmed": {
            "output_vat_centimos":
                confirmed_output_vat,
            "deductible_input_vat_centimos":
                confirmed_input_vat,
            "compensation_previous_centimos":
                compensation,
            "result_centimos":
                confirmed_result,
            "result_type": (
                "A_PAGAR"
                if confirmed_result > 0
                else (
                    "A_COMPENSAR"
                    if confirmed_result < 0
                    else "CERO"
                )
            ),
        },
        "provisional": {
            "output_vat_centimos":
                provisional_output_vat,
            "deductible_input_vat_centimos":
                provisional_input_vat,
            "compensation_previous_centimos":
                compensation,
            "result_centimos":
                provisional_result,
            "result_type": (
                "A_PAGAR"
                if provisional_result > 0
                else (
                    "A_COMPENSAR"
                    if provisional_result < 0
                    else "CERO"
                )
            ),
        },
        "counts": {
            "invoices_total": len(invoices),
            "invoices_confirmed": sum(
                1
                for item in invoices
                if item.get("confirmed")
            ),
            "invoices_provisional": sum(
                1
                for item in invoices
                if item.get("provisional")
            ),
            "expenses_total": len(expenses),
            "expenses_confirmed": sum(
                1
                for item in expenses
                if item.get("confirmed")
            ),
            "expenses_provisional": sum(
                1
                for item in expenses
                if item.get("provisional")
            ),
            "expenses_pending_review": sum(
                1
                for item in expenses
                if _normalize(
                    item.get("estado_fiscal")
                ) in PENDING_EXPENSE_STATES
            ),
        },
        "warnings": _build_warnings(
            invoices=invoices,
            expenses=expenses,
        ),
    }


def list_model_130_entries(
    year: int,
    quarter: int,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    period = resolve_period(year, quarter)

    with _connect(db_path) as conn:
        invoices = _load_invoices(
            conn,
            period.cumulative_start_date,
            period.end_date,
        )
        expenses = _load_expenses(
            conn,
            period.cumulative_start_date,
            period.end_date,
        )

    invoice_entries = []

    for invoice in invoices:
        confirmed = _invoice_is_confirmed(invoice)
        provisional = _invoice_is_provisional(invoice)

        invoice_entries.append(
            {
                **invoice,
                "income_base_centimos":
                    _money_to_centimos(
                        invoice.get("base_imponible")
                    ),
                "retention_centimos":
                    _money_to_centimos(
                        invoice.get("irpf")
                    ),
                "confirmed": confirmed,
                "provisional": provisional,
            }
        )

    expense_entries = []

    for expense in expenses:
        percentage = _percentage(
            expense.get("porcentaje_deducible")
        )

        deductible_base = _apply_percentage(
            expense.get(
                "base_imponible_centimos"
            ),
            percentage,
        )

        confirmed = _expense_is_confirmed(
            expense,
            tax_kind="irpf",
        )
        provisional = _expense_is_provisional(
            expense,
            tax_kind="irpf",
        )

        expense_entries.append(
            {
                **expense,
                "deductible_base_centimos":
                    deductible_base,
                "confirmed": confirmed,
                "provisional": provisional,
            }
        )

    return {
        "model": "130",
        "year": period.year,
        "quarter": period.quarter,
        "period_start":
            period.cumulative_start_date,
        "period_end": period.end_date,
        "invoices": invoice_entries,
        "expenses": expense_entries,
    }


def _calculate_model_130_level(
    *,
    invoices: list[dict],
    expenses: list[dict],
    level: str,
    payment_rate: float,
    previous_positive_payments_centimos: int,
    advisory_reduction_centimos: int,
    other_adjustments_centimos: int,
    apply_difficult_to_justify_expenses: bool,
    difficult_expense_rate: float,
    difficult_expense_annual_limit_centimos: int,
) -> dict:
    income_base = sum(
        _int(item.get("income_base_centimos"))
        for item in invoices
        if item.get(level)
    )

    registered_deductible_expenses = sum(
        _int(
            item.get(
                "deductible_base_centimos"
            )
        )
        for item in expenses
        if item.get(level)
    )

    retained_irpf = sum(
        _int(item.get("retention_centimos"))
        for item in invoices
        if item.get(level)
    )

    preliminary_net_income = (
        income_base
        - registered_deductible_expenses
    )

    positive_preliminary_net_income = max(
        0,
        preliminary_net_income,
    )

    difficult_expenses = 0

    if apply_difficult_to_justify_expenses:
        calculated_difficult_expenses = int(
            round(
                positive_preliminary_net_income
                * difficult_expense_rate
                / 100.0
            )
        )

        difficult_expenses = min(
            calculated_difficult_expenses,
            max(
                0,
                _int(
                    difficult_expense_annual_limit_centimos
                ),
            ),
        )

    net_income_after_difficult_expenses = (
        preliminary_net_income
        - difficult_expenses
    )

    positive_net_income = max(
        0,
        net_income_after_difficult_expenses,
    )

    gross_payment = int(
        round(
            positive_net_income
            * payment_rate
            / 100.0
        )
    )

    previous_positive_payments = max(
        0,
        _int(
            previous_positive_payments_centimos
        ),
    )

    advisory_reduction = max(
        0,
        _int(
            advisory_reduction_centimos
        ),
    )

    other_adjustments = _int(
        other_adjustments_centimos
    )

    raw_result = (
        gross_payment
        - retained_irpf
        - previous_positive_payments
        - advisory_reduction
        + other_adjustments
    )

    return {
        "income_base_centimos":
            income_base,

        "registered_deductible_expenses_centimos":
            registered_deductible_expenses,

        # Alias temporal para consumidores de la V1.
        "deductible_expenses_centimos":
            registered_deductible_expenses,

        "preliminary_net_income_centimos":
            preliminary_net_income,

        "positive_preliminary_net_income_centimos":
            positive_preliminary_net_income,

        "apply_difficult_to_justify_expenses":
            bool(
                apply_difficult_to_justify_expenses
            ),

        "difficult_expense_rate":
            difficult_expense_rate,

        "difficult_expense_annual_limit_centimos":
            max(
                0,
                _int(
                    difficult_expense_annual_limit_centimos
                ),
            ),

        "difficult_to_justify_expenses_centimos":
            difficult_expenses,

        "net_income_centimos":
            net_income_after_difficult_expenses,

        "positive_net_income_centimos":
            positive_net_income,

        "payment_rate":
            payment_rate,

        "gross_payment_centimos":
            gross_payment,

        "retained_irpf_centimos":
            retained_irpf,

        "previous_positive_payments_centimos":
            previous_positive_payments,

        # Alias temporal para consumidores de la V1.
        "previous_payments_centimos":
            previous_positive_payments,

        "advisory_reduction_centimos":
            advisory_reduction,

        "other_adjustments_centimos":
            other_adjustments,

        # Alias temporal para consumidores de la V1.
        "manual_adjustments_centimos":
            other_adjustments,

        "raw_result_centimos":
            raw_result,

        "result_centimos":
            max(
                0,
                raw_result,
            ),

        "result_type": (
            "A_PAGAR"
            if raw_result > 0
            else "CERO"
        ),
    }


def estimate_model_130(
    year: int,
    quarter: int,
    *,
    payment_rate: float = 20.0,
    previous_positive_payments_centimos: int = 0,
    advisory_reduction_centimos: int = 0,
    other_adjustments_centimos: int = 0,
    apply_difficult_to_justify_expenses: bool = True,
    difficult_expense_rate: float = 5.0,
    difficult_expense_annual_limit_centimos: int = 200000,
    previous_payments_centimos: int | None = None,
    manual_adjustments_centimos: int | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    """
    Estima el modelo 130 de forma acumulada desde el 1 de enero.

    Los parámetros previous_payments_centimos y
    manual_adjustments_centimos se conservan temporalmente como
    alias compatibles con la versión inicial del servicio.
    """
    payment_rate_value = _float(
        payment_rate
    )

    difficult_expense_rate_value = _float(
        difficult_expense_rate
    )

    if (
        payment_rate_value < 0
        or payment_rate_value > 100
    ):
        raise ValueError(
            "El porcentaje del pago fraccionado "
            "debe estar entre 0 y 100"
        )

    if (
        difficult_expense_rate_value < 0
        or difficult_expense_rate_value > 100
    ):
        raise ValueError(
            "El porcentaje de gastos de difícil "
            "justificación debe estar entre 0 y 100"
        )

    if previous_payments_centimos is not None:
        legacy_previous = _int(
            previous_payments_centimos
        )

        if (
            _int(
                previous_positive_payments_centimos
            )
            not in (0, legacy_previous)
        ):
            raise ValueError(
                "No indiques simultáneamente dos valores "
                "distintos para pagos anteriores"
            )

        previous_positive_payments_centimos = (
            legacy_previous
        )

    if manual_adjustments_centimos is not None:
        legacy_adjustments = _int(
            manual_adjustments_centimos
        )

        if (
            _int(other_adjustments_centimos)
            not in (0, legacy_adjustments)
        ):
            raise ValueError(
                "No indiques simultáneamente dos valores "
                "distintos para otros ajustes"
            )

        other_adjustments_centimos = (
            legacy_adjustments
        )

    entries = list_model_130_entries(
        year,
        quarter,
        db_path=db_path,
    )

    invoices = entries["invoices"]
    expenses = entries["expenses"]

    common_parameters = {
        "invoices": invoices,
        "expenses": expenses,
        "payment_rate":
            payment_rate_value,
        "previous_positive_payments_centimos":
            previous_positive_payments_centimos,
        "advisory_reduction_centimos":
            advisory_reduction_centimos,
        "other_adjustments_centimos":
            other_adjustments_centimos,
        "apply_difficult_to_justify_expenses":
            bool(
                apply_difficult_to_justify_expenses
            ),
        "difficult_expense_rate":
            difficult_expense_rate_value,
        "difficult_expense_annual_limit_centimos":
            difficult_expense_annual_limit_centimos,
    }

    confirmed = _calculate_model_130_level(
        level="confirmed",
        **common_parameters,
    )

    provisional = _calculate_model_130_level(
        level="provisional",
        **common_parameters,
    )

    return {
        "model": "130",
        "year": entries["year"],
        "quarter": entries["quarter"],
        "period_start":
            entries["period_start"],
        "period_end":
            entries["period_end"],

        "configuration": {
            "payment_rate":
                payment_rate_value,

            "apply_difficult_to_justify_expenses":
                bool(
                    apply_difficult_to_justify_expenses
                ),

            "difficult_expense_rate":
                difficult_expense_rate_value,

            "difficult_expense_annual_limit_centimos":
                max(
                    0,
                    _int(
                        difficult_expense_annual_limit_centimos
                    ),
                ),

            "previous_positive_payments_centimos":
                max(
                    0,
                    _int(
                        previous_positive_payments_centimos
                    ),
                ),

            "advisory_reduction_centimos":
                max(
                    0,
                    _int(
                        advisory_reduction_centimos
                    ),
                ),

            "other_adjustments_centimos":
                _int(
                    other_adjustments_centimos
                ),
        },

        "confirmed":
            confirmed,

        "provisional":
            provisional,

        "counts": {
            "invoices_total":
                len(invoices),

            "invoices_confirmed":
                sum(
                    1
                    for item in invoices
                    if item.get("confirmed")
                ),

            "invoices_provisional":
                sum(
                    1
                    for item in invoices
                    if item.get("provisional")
                ),

            "expenses_total":
                len(expenses),

            "expenses_confirmed":
                sum(
                    1
                    for item in expenses
                    if item.get("confirmed")
                ),

            "expenses_provisional":
                sum(
                    1
                    for item in expenses
                    if item.get("provisional")
                ),
        },

        "warnings": _build_warnings(
            invoices=invoices,
            expenses=expenses,
        ),
    }


def _build_warnings(
    *,
    invoices: list[dict],
    expenses: list[dict],
) -> list[dict]:
    warnings = []

    provisional_invoices = [
        item
        for item in invoices
        if item.get("provisional")
    ]

    confirmed_invoices = [
        item
        for item in invoices
        if item.get("confirmed")
    ]

    pending_expenses = [
        item
        for item in expenses
        if _normalize(
            item.get("estado_fiscal")
        ) in PENDING_EXPENSE_STATES
    ]

    expenses_without_document = [
        item
        for item in expenses
        if _normalize(
            item.get("estado_documental")
        ) == "SIN_JUSTIFICANTE"
    ]

    if not provisional_invoices:
        warnings.append(
            {
                "code": "NO_INCOME_INVOICES",
                "severity": "WARNING",
                "message": (
                    "No hay facturas de ingresos "
                    "incluibles en el periodo."
                ),
            }
        )

    elif not confirmed_invoices:
        warnings.append(
            {
                "code": "NO_CONFIRMED_INVOICES",
                "severity": "INFO",
                "message": (
                    "Hay facturas emitidas, pero ninguna "
                    "está fiscalmente confirmada."
                ),
            }
        )

    if pending_expenses:
        warnings.append(
            {
                "code": "EXPENSES_PENDING_REVIEW",
                "severity": "WARNING",
                "count": len(pending_expenses),
                "message": (
                    f"Hay {len(pending_expenses)} gastos "
                    "pendientes de revisión fiscal."
                ),
            }
        )

    if expenses_without_document:
        warnings.append(
            {
                "code": "EXPENSES_WITHOUT_DOCUMENT",
                "severity": "WARNING",
                "count":
                    len(expenses_without_document),
                "message": (
                    f"Hay {len(expenses_without_document)} "
                    "gastos sin justificante."
                ),
            }
        )

    return warnings


def estimate_fiscal_summary(
    year: int,
    quarter: int,
    *,
    compensation_previous_303_centimos: int = 0,
    previous_payments_130_centimos: int = 0,
    manual_adjustments_130_centimos: int = 0,
    payment_rate_130: float = 20.0,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    model_303 = estimate_model_303(
        year,
        quarter,
        compensation_previous_centimos=(
            compensation_previous_303_centimos
        ),
        db_path=db_path,
    )

    model_130 = estimate_model_130(
        year,
        quarter,
        payment_rate=payment_rate_130,
        previous_payments_centimos=(
            previous_payments_130_centimos
        ),
        manual_adjustments_centimos=(
            manual_adjustments_130_centimos
        ),
        db_path=db_path,
    )

    confirmed_total = (
        max(
            0,
            _int(
                model_303["confirmed"][
                    "result_centimos"
                ]
            ),
        )
        + max(
            0,
            _int(
                model_130["confirmed"][
                    "result_centimos"
                ]
            ),
        )
    )

    provisional_total = (
        max(
            0,
            _int(
                model_303["provisional"][
                    "result_centimos"
                ]
            ),
        )
        + max(
            0,
            _int(
                model_130["provisional"][
                    "result_centimos"
                ]
            ),
        )
    )

    return {
        "year": int(year),
        "quarter": int(quarter),
        "model_303": model_303,
        "model_130": model_130,
        "combined": {
            "confirmed_to_pay_centimos":
                confirmed_total,
            "provisional_to_pay_centimos":
                provisional_total,
        },
    }
