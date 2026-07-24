from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


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


def _normalize_date(
    value: str | None,
) -> str:
    raw = str(value or "").strip()

    if not raw:
        return ""

    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(
                raw,
                fmt,
            ).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(
        f"Fecha no válida: {raw}. "
        "Utiliza YYYY-MM-DD o DD/MM/YYYY."
    )


def _centimos_from_euros(
    value: Any,
) -> int:
    try:
        return int(
            round(float(value or 0) * 100)
        )
    except (TypeError, ValueError):
        return 0


def _percentage(
    value: Any,
    default: float = 100.0,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default

    return max(
        0.0,
        min(100.0, result),
    )


def _date_conditions(
    column: str,
    *,
    date_from: str,
    date_to: str,
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if date_from:
        conditions.append(
            f"date({column}) >= date(?)"
        )
        params.append(date_from)

    if date_to:
        conditions.append(
            f"date({column}) <= date(?)"
        )
        params.append(date_to)

    return conditions, params


def _income_row(
    row: sqlite3.Row,
) -> dict[str, Any]:
    data = dict(row)

    amount_centimos = _centimos_from_euros(
        data.get("importe")
    )
    fiscal_type = str(
        data.get("tipo_fiscal")
        or "PROVISION"
    ).strip().upper()

    is_suplido = fiscal_type == "SUPLIDO"

    invoice_base_centimos = (
        _centimos_from_euros(
            data.get("invoice_base_imponible")
        )
    )
    invoice_vat_centimos = (
        _centimos_from_euros(
            data.get("invoice_iva")
        )
    )
    invoice_withholding_centimos = (
        _centimos_from_euros(
            data.get("invoice_irpf")
        )
    )
    invoice_total_centimos = (
        _centimos_from_euros(
            data.get("invoice_total")
        )
    )

    invoice_active = bool(
        int(
            data.get("invoice_active")
            or 0
        )
    )

    invoice_matches_collection = (
        invoice_active
        and invoice_total_centimos > 0
        and abs(
            invoice_total_centimos
            - amount_centimos
        ) <= 1
    )

    if is_suplido:
        computable_centimos = 0
        output_vat_centimos = 0
        withholding_centimos = 0
        recognition_status = "SUPLIDO"

    elif invoice_matches_collection:
        computable_centimos = (
            invoice_base_centimos
        )
        output_vat_centimos = (
            invoice_vat_centimos
        )
        withholding_centimos = (
            invoice_withholding_centimos
        )
        recognition_status = "FACTURADO"

    else:
        try:
            vat_percentage = float(
                data.get("iva_porcentaje")
                or 0
            )
        except (TypeError, ValueError):
            vat_percentage = 0.0

        try:
            withholding_percentage = float(
                data.get("irpf_porcentaje")
                or 0
            )
        except (TypeError, ValueError):
            withholding_percentage = 0.0

        divisor = (
            1
            + vat_percentage / 100
            - withholding_percentage / 100
        )

        if divisor <= 0:
            raise ValueError(
                "La fiscalidad del cobro "
                f"#{data.get('id')} no permite "
                "calcular su base imponible."
            )

        computable_centimos = int(
            round(
                amount_centimos
                / divisor
            )
        )

        output_vat_centimos = int(
            round(
                computable_centimos
                * vat_percentage
                / 100
            )
        )

        withholding_centimos = (
            computable_centimos
            + output_vat_centimos
            - amount_centimos
        )

        recognition_status = "PROVISIONAL"

    return {
        **data,
        "amount_centimos": amount_centimos,
        "is_suplido": is_suplido,
        "invoice_matches_collection": (
            invoice_matches_collection
        ),
        "recognition_status": (
            recognition_status
        ),
        "output_vat_centimos": (
            output_vat_centimos
        ),
        "withholding_centimos": (
            withholding_centimos
        ),
        "computable_centimos": (
            computable_centimos
        ),
    }


def _expense_row(
    row: sqlite3.Row,
) -> dict[str, Any]:
    data = dict(row)

    base_centimos = max(
        0,
        int(
            data.get(
                "base_imponible_centimos"
            )
            or 0
        ),
    )
    iva_centimos = max(
        0,
        int(
            data.get("iva_centimos")
            or 0
        ),
    )
    other_taxes_centimos = int(
        data.get(
            "otros_impuestos_centimos"
        )
        or 0
    )

    total_centimos = int(
        data.get("total_centimos")
        or 0
    )

    if (
        base_centimos == 0
        and iva_centimos == 0
        and other_taxes_centimos == 0
    ):
        fallback = (
            total_centimos
            if total_centimos != 0
            else _centimos_from_euros(
                data.get("importe")
            )
        )

        base_centimos = max(
            0,
            fallback,
        )

    iva_deducible = bool(
        int(
            data.get("iva_deducible")
            or 0
        )
    )

    non_deductible_iva_centimos = (
        0
        if iva_deducible
        else iva_centimos
    )

    deductible_percentage = _percentage(
        data.get("porcentaje_deducible"),
        100.0,
    )

    gross_economic_centimos = (
        base_centimos
        + non_deductible_iva_centimos
        + other_taxes_centimos
    )

    economic_centimos = int(
        round(
            gross_economic_centimos
            * deductible_percentage
            / 100
        )
    )

    category = str(
        data.get("categoria")
        or "Sin categoría"
    ).strip() or "Sin categoría"

    category_code = str(
        data.get("expense_category_code")
        or ""
    ).strip().upper()

    subcategory_code = str(
        data.get("expense_subcategory_code")
        or ""
    ).strip().upper()

    document_type = str(
        data.get("tipo_justificante")
        or ""
    ).strip().upper()

    is_payroll = (
        bool(
            int(
                data.get("is_payroll_expense")
                or 0
            )
        )
        or document_type == "NOMINA"
        or (
            category_code == "PERSONAL"
            and subcategory_code == "NOMINAS"
        )
    )

    is_employer_social_security = (
        bool(
            int(
                data.get(
                    "is_employer_social_security_expense"
                )
                or 0
            )
        )
        or document_type == "SEGUROS_SOCIALES"
        or (
            category_code == "PERSONAL"
            and subcategory_code
            == "SEGURIDAD_SOCIAL_EMPRESA"
        )
    )

    if is_payroll:
        group = "PERSONAL_NOMINAS"
        group_label = "Nóminas"
    elif is_employer_social_security:
        group = "PERSONAL_SEGURIDAD_SOCIAL"
        group_label = (
            "Seguridad Social empresa"
        )
    else:
        group = "OPERATIVOS"
        group_label = "Gastos operativos"

    return {
        **data,
        "category_label": category,
        "result_group": group,
        "result_group_label": group_label,
        "economic_base_centimos": (
            base_centimos
        ),
        "non_deductible_iva_centimos": (
            non_deductible_iva_centimos
        ),
        "economic_other_taxes_centimos": (
            other_taxes_centimos
        ),
        "deductible_percentage": (
            deductible_percentage
        ),
        "economic_centimos": (
            economic_centimos
        ),
    }


def list_income_detail(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    include_suplidos: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    normalized_from = _normalize_date(
        date_from
    )
    normalized_to = _normalize_date(
        date_to
    )

    conditions = [
        "COALESCE(c.activo, 1) = 1",
    ]
    params: list[Any] = []

    date_sql, date_params = _date_conditions(
        "c.fecha_cobro",
        date_from=normalized_from,
        date_to=normalized_to,
    )
    conditions.extend(date_sql)
    params.extend(date_params)

    if not include_suplidos:
        conditions.append(
            """
            UPPER(
                TRIM(
                    COALESCE(
                        c.tipo_fiscal,
                        'PROVISION'
                    )
                )
            ) <> 'SUPLIDO'
            """
        )

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.*,
                cl.nombre,
                cl.primer_apellido,
                cl.segundo_apellido,
                e.numero_expediente,
                f.numero_factura,
                f.base_imponible
                    AS invoice_base_imponible,
                f.iva
                    AS invoice_iva,
                f.irpf
                    AS invoice_irpf,
                f.total
                    AS invoice_total,
                COALESCE(f.activo, 0)
                    AS invoice_active,
                f.estado
                    AS invoice_status
            FROM eco_cobros c
            LEFT JOIN clientes cl
              ON cl.id = c.cliente_id
            LEFT JOIN expedientes e
              ON e.id = c.expediente_id
            LEFT JOIN eco_facturas f
              ON f.id = c.factura_id
            WHERE {' AND '.join(conditions)}
            ORDER BY
                c.fecha_cobro,
                c.id
            """,
            params,
        ).fetchall()

    return [
        _income_row(row)
        for row in rows
    ]


def list_expense_detail(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    normalized_from = _normalize_date(
        date_from
    )
    normalized_to = _normalize_date(
        date_to
    )

    conditions = [
        "COALESCE(g.activo, 1) = 1",
    ]
    params: list[Any] = []

    date_sql, date_params = _date_conditions(
        "g.fecha_gasto",
        date_from=normalized_from,
        date_to=normalized_to,
    )
    conditions.extend(date_sql)
    params.extend(date_params)

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                g.*,
                COALESCE(
                    NULLIF(
                        g.supplier_name_snapshot,
                        ''
                    ),
                    NULLIF(g.proveedor, ''),
                    'Sin proveedor'
                ) AS supplier_display_name,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM worker_payrolls wp
                        WHERE wp.salary_expense_id = g.id
                          AND COALESCE(wp.active, 1) = 1
                    )
                    THEN 1
                    ELSE 0
                END AS is_payroll_expense,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM labor_social_security_periods sp
                        WHERE sp.employer_expense_id = g.id
                          AND COALESCE(sp.active, 1) = 1
                    )
                    THEN 1
                    ELSE 0
                END AS is_employer_social_security_expense
            FROM eco_gastos g
            WHERE {' AND '.join(conditions)}
            ORDER BY
                g.fecha_gasto,
                g.id
            """,
            params,
        ).fetchall()

    return [
        _expense_row(row)
        for row in rows
    ]


def profit_and_loss_summary(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    normalized_from = _normalize_date(
        date_from
    )
    normalized_to = _normalize_date(
        date_to
    )

    if (
        normalized_from
        and normalized_to
        and normalized_from > normalized_to
    ):
        raise ValueError(
            "La fecha inicial no puede ser "
            "posterior a la fecha final."
        )

    income_rows = list_income_detail(
        date_from=normalized_from,
        date_to=normalized_to,
        include_suplidos=True,
        db_path=db_path,
    )
    expense_rows = list_expense_detail(
        date_from=normalized_from,
        date_to=normalized_to,
        db_path=db_path,
    )

    collected_total = sum(
        int(row["amount_centimos"])
        for row in income_rows
    )
    suplidos_total = sum(
        int(row["amount_centimos"])
        for row in income_rows
        if row["is_suplido"]
    )
    computable_income = sum(
        int(row["computable_centimos"])
        for row in income_rows
    )
    output_vat_total = sum(
        int(row["output_vat_centimos"])
        for row in income_rows
    )
    withholding_total = sum(
        int(row["withholding_centimos"])
        for row in income_rows
    )
    provisional_income = sum(
        int(row["computable_centimos"])
        for row in income_rows
        if row["recognition_status"]
        == "PROVISIONAL"
    )
    invoiced_income = sum(
        int(row["computable_centimos"])
        for row in income_rows
        if row["recognition_status"]
        == "FACTURADO"
    )

    expense_groups = defaultdict(int)
    expense_categories = defaultdict(int)

    for row in expense_rows:
        amount = int(
            row["economic_centimos"]
            or 0
        )
        expense_groups[
            row["result_group"]
        ] += amount
        expense_categories[
            row["category_label"]
        ] += amount

    operating_expenses = int(
        expense_groups["OPERATIVOS"]
    )
    payroll_expenses = int(
        expense_groups["PERSONAL_NOMINAS"]
    )
    employer_ss_expenses = int(
        expense_groups[
            "PERSONAL_SEGURIDAD_SOCIAL"
        ]
    )

    total_expenses = (
        operating_expenses
        + payroll_expenses
        + employer_ss_expenses
    )
    result_centimos = (
        computable_income
        - total_expenses
    )

    margin_percentage = (
        round(
            result_centimos
            * 100
            / computable_income,
            2,
        )
        if computable_income
        else 0.0
    )

    return {
        "period": {
            "date_from": normalized_from,
            "date_to": normalized_to,
        },
        "income": {
            "collection_count": len(
                income_rows
            ),
            "collected_total_centimos": (
                collected_total
            ),
            "suplidos_centimos": (
                suplidos_total
            ),
            "output_vat_centimos": (
                output_vat_total
            ),
            "withholding_centimos": (
                withholding_total
            ),
            "provisional_centimos": (
                provisional_income
            ),
            "invoiced_centimos": (
                invoiced_income
            ),
            "computable_centimos": (
                computable_income
            ),
        },
        "expenses": {
            "expense_count": len(
                expense_rows
            ),
            "operating_centimos": (
                operating_expenses
            ),
            "payroll_centimos": (
                payroll_expenses
            ),
            "employer_social_security_centimos": (
                employer_ss_expenses
            ),
            "total_centimos": (
                total_expenses
            ),
            "by_category": [
                {
                    "category": category,
                    "amount_centimos": amount,
                }
                for category, amount
                in sorted(
                    expense_categories.items(),
                    key=lambda item: (
                        -item[1],
                        item[0],
                    ),
                )
            ],
        },
        "result_centimos": result_centimos,
        "margin_percentage": margin_percentage,
        "income_detail": income_rows,
        "expense_detail": expense_rows,
    }


def monthly_profit_and_loss(
    *,
    year: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    year = int(year)

    if year < 1900 or year > 9999:
        raise ValueError(
            "El año indicado no es válido."
        )

    result = []

    for month in range(1, 13):
        date_from = (
            f"{year:04d}-{month:02d}-01"
        )

        if month == 12:
            next_month = (
                f"{year + 1:04d}-01-01"
            )
        else:
            next_month = (
                f"{year:04d}-{month + 1:02d}-01"
            )

        with _connect(db_path) as conn:
            last_day_row = conn.execute(
                """
                SELECT date(
                    ?,
                    '-1 day'
                ) AS last_day
                """,
                (next_month,),
            ).fetchone()

        date_to = str(
            last_day_row["last_day"]
        )

        summary = profit_and_loss_summary(
            date_from=date_from,
            date_to=date_to,
            db_path=db_path,
        )

        result.append(
            {
                "year": year,
                "month": month,
                "period_label": (
                    f"{month:02d}/{year}"
                ),
                "date_from": date_from,
                "date_to": date_to,
                "income_centimos": int(
                    summary["income"][
                        "computable_centimos"
                    ]
                ),
                "suplidos_centimos": int(
                    summary["income"][
                        "suplidos_centimos"
                    ]
                ),
                "operating_expenses_centimos": int(
                    summary["expenses"][
                        "operating_centimos"
                    ]
                ),
                "payroll_centimos": int(
                    summary["expenses"][
                        "payroll_centimos"
                    ]
                ),
                "employer_social_security_centimos": int(
                    summary["expenses"][
                        "employer_social_security_centimos"
                    ]
                ),
                "total_expenses_centimos": int(
                    summary["expenses"][
                        "total_centimos"
                    ]
                ),
                "result_centimos": int(
                    summary["result_centimos"]
                ),
                "margin_percentage": float(
                    summary["margin_percentage"]
                ),
            }
        )

    return result


def available_profit_and_loss_years(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[int]:
    years = set()

    with _connect(db_path) as conn:
        income_rows = conn.execute(
            """
            SELECT DISTINCT
                CAST(
                    strftime(
                        '%Y',
                        fecha_cobro
                    )
                    AS INTEGER
                ) AS year
            FROM eco_cobros
            WHERE COALESCE(activo, 1) = 1
              AND fecha_cobro IS NOT NULL
              AND TRIM(fecha_cobro) <> ''
            """
        ).fetchall()

        expense_rows = conn.execute(
            """
            SELECT DISTINCT
                CAST(
                    strftime(
                        '%Y',
                        fecha_gasto
                    )
                    AS INTEGER
                ) AS year
            FROM eco_gastos
            WHERE COALESCE(activo, 1) = 1
              AND fecha_gasto IS NOT NULL
              AND TRIM(fecha_gasto) <> ''
            """
        ).fetchall()

    for row in [
        *income_rows,
        *expense_rows,
    ]:
        year = int(row["year"] or 0)

        if year > 0:
            years.add(year)

    return sorted(
        years,
        reverse=True,
    )
