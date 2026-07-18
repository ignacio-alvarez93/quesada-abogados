from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import backend.services.expense_service as expense_service
import backend.services.worker_service as worker_service


DEFAULT_DB_PATH = Path("database/quesada.db")

PAYROLL_FIELDS = (
    "contract_id",
    "period_year",
    "period_month",
    "accrual_date",
    "payment_due_date",
    "liquidation_start_date",
    "liquidation_end_date",
    "liquidation_days",
    "gross_salary_centimos",
    "employee_social_security_centimos",
    "irpf_centimos",
    "other_deductions_centimos",
    "total_deductions_centimos",
    "net_salary_centimos",
    "employer_social_security_centimos",
    "total_employer_cost_centimos",
    "contribution_common_base_centimos",
    "contribution_accident_base_centimos",
    "irpf_base_centimos",
    "irpf_rate_basis_points",
    "contract_code_snapshot",
    "contribution_group_snapshot",
    "professional_group_snapshot",
    "salary_expense_id",
    "document_path",
    "status",
    "notes",
    "active",
)


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


def _optional_integer(value: Any) -> int | None:
    raw = _text(value)

    if not raw:
        return None

    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            "El identificador relacionado no es válido"
        )


def _normalize_date(
    value: Any,
    *,
    label: str,
    required: bool = False,
) -> str:
    raw = _text(value)

    if not raw:
        if required:
            raise ValueError(
                f"{label} es obligatoria"
            )
        return ""

    for fmt in (
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

    raise ValueError(
        f"{label} debe tener formato DD/MM/YYYY"
    )


def _non_negative_centimos(
    value: Any,
    *,
    label: str,
) -> int:
    amount = _integer(value)

    if amount < 0:
        raise ValueError(
            f"{label} no puede ser negativo"
        )

    return amount


def _normalize_payload(
    data: dict[str, Any],
) -> dict[str, Any]:
    year = _integer(data.get("period_year"))
    month = _integer(data.get("period_month"))

    if year < 2000 or year > 2200:
        raise ValueError(
            "El año de la nómina no es válido"
        )

    if month < 1 or month > 12:
        raise ValueError(
            "El mes de la nómina debe estar entre 1 y 12"
        )

    payload = {
        "contract_id": _optional_integer(
            data.get("contract_id")
        ),
        "period_year": year,
        "period_month": month,
        "accrual_date": _normalize_date(
            data.get("accrual_date"),
            label="La fecha de devengo",
            required=True,
        ),
        "payment_due_date": _normalize_date(
            data.get("payment_due_date"),
            label="La fecha prevista de pago",
        ),
        "liquidation_start_date": _normalize_date(
            data.get("liquidation_start_date"),
            label="La fecha inicial de liquidación",
        ),
        "liquidation_end_date": _normalize_date(
            data.get("liquidation_end_date"),
            label="La fecha final de liquidación",
        ),
        "liquidation_days": max(
            0,
            _integer(data.get("liquidation_days")),
        ),
        "contract_code_snapshot": _text(
            data.get("contract_code_snapshot")
        ),
        "contribution_group_snapshot": _text(
            data.get("contribution_group_snapshot")
        ),
        "professional_group_snapshot": _text(
            data.get("professional_group_snapshot")
        ),
        "salary_expense_id": _optional_integer(
            data.get("salary_expense_id")
        ),
        "document_path": _text(
            data.get("document_path")
        ),
        "status": (
            _text(data.get("status"))
            or "PENDING"
        ).upper(),
        "notes": _text(data.get("notes")),
        "active": (
            1
            if _integer(data.get("active"), 1)
            else 0
        ),
    }

    centimo_fields = {
        "gross_salary_centimos": "El total devengado",
        "employee_social_security_centimos": (
            "La Seguridad Social del trabajador"
        ),
        "irpf_centimos": "El IRPF",
        "other_deductions_centimos": (
            "Las otras deducciones"
        ),
        "total_deductions_centimos": (
            "El total retenido"
        ),
        "net_salary_centimos": (
            "El líquido a percibir"
        ),
        "employer_social_security_centimos": (
            "La aportación empresarial"
        ),
        "total_employer_cost_centimos": (
            "El coste total empresarial"
        ),
        "contribution_common_base_centimos": (
            "La base de contingencias comunes"
        ),
        "contribution_accident_base_centimos": (
            "La base de accidentes"
        ),
        "irpf_base_centimos": "La base de IRPF",
        "irpf_rate_basis_points": (
            "El porcentaje de IRPF"
        ),
    }

    for field, label in centimo_fields.items():
        payload[field] = _non_negative_centimos(
            data.get(field),
            label=label,
        )

    calculated_deductions = (
        payload["employee_social_security_centimos"]
        + payload["irpf_centimos"]
        + payload["other_deductions_centimos"]
    )

    if abs(
        payload["total_deductions_centimos"]
        - calculated_deductions
    ) > 1:
        raise ValueError(
            "El total retenido no coincide con "
            "Seguridad Social, IRPF y otras deducciones"
        )

    calculated_net = (
        payload["gross_salary_centimos"]
        - payload["total_deductions_centimos"]
    )

    if abs(
        payload["net_salary_centimos"]
        - calculated_net
    ) > 1:
        raise ValueError(
            "El líquido no coincide con el "
            "devengado menos las retenciones"
        )

    calculated_cost = (
        payload["gross_salary_centimos"]
        + payload["employer_social_security_centimos"]
    )

    if abs(
        payload["total_employer_cost_centimos"]
        - calculated_cost
    ) > 1:
        raise ValueError(
            "El coste empresarial no coincide con "
            "el devengado más la aportación empresarial"
        )

    start = payload["liquidation_start_date"]
    end = payload["liquidation_end_date"]

    if start and end and end < start:
        raise ValueError(
            "La fecha final de liquidación no "
            "puede ser anterior a la inicial"
        )

    return payload


def list_worker_payrolls(
    worker_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM worker_payrolls
            WHERE worker_id = ?
              AND active = 1
            ORDER BY
                period_year DESC,
                period_month DESC,
                id DESC
            """,
            (int(worker_id),),
        ).fetchall()

    return [dict(row) for row in rows]


def get_payroll(
    payroll_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM worker_payrolls
            WHERE id = ?
            """,
            (int(payroll_id),),
        ).fetchone()

    return dict(row) if row else None


def create_payroll(
    worker_id: int,
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    payload = _normalize_payload(data)
    fields = list(PAYROLL_FIELDS)

    with closing(_connect(db_path)) as conn:
        worker = conn.execute(
            """
            SELECT id
            FROM workers
            WHERE id = ?
            """,
            (int(worker_id),),
        ).fetchone()

        if not worker:
            raise ValueError(
                "Trabajador no encontrado"
            )

        duplicate = conn.execute(
            """
            SELECT id
            FROM worker_payrolls
            WHERE worker_id = ?
              AND period_year = ?
              AND period_month = ?
              AND active = 1
            """,
            (
                int(worker_id),
                payload["period_year"],
                payload["period_month"],
            ),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "Ya existe una nómina activa "
                "para este trabajador y periodo"
            )

        columns = ", ".join(fields)
        placeholders = ", ".join(
            "?" for _ in fields
        )

        cursor = conn.execute(
            f"""
            INSERT INTO worker_payrolls (
                worker_id,
                {columns}
            )
            VALUES (
                ?,
                {placeholders}
            )
            """,
            [
                int(worker_id),
                *[
                    payload[field]
                    for field in fields
                ],
            ],
        )

        payroll_id = int(cursor.lastrowid)
        conn.commit()

    return payroll_id


def update_payroll(
    payroll_id: int,
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    payload = _normalize_payload(data)
    fields = list(PAYROLL_FIELDS)

    with closing(_connect(db_path)) as conn:
        current = conn.execute(
            """
            SELECT worker_id
            FROM worker_payrolls
            WHERE id = ?
            """,
            (int(payroll_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "Nómina no encontrada"
            )

        duplicate = conn.execute(
            """
            SELECT id
            FROM worker_payrolls
            WHERE worker_id = ?
              AND period_year = ?
              AND period_month = ?
              AND active = 1
              AND id <> ?
            """,
            (
                int(current["worker_id"]),
                payload["period_year"],
                payload["period_month"],
                int(payroll_id),
            ),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "Ya existe otra nómina activa "
                "para este trabajador y periodo"
            )

        assignments = ", ".join(
            f"{field} = ?"
            for field in fields
        )

        conn.execute(
            f"""
            UPDATE worker_payrolls
            SET {assignments},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [
                *[
                    payload[field]
                    for field in fields
                ],
                int(payroll_id),
            ],
        )

        conn.commit()

    return True


def period_summary(
    year: int,
    month: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, int]:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS payroll_count,
                COALESCE(
                    SUM(gross_salary_centimos),
                    0
                ) AS gross_salary_centimos,
                COALESCE(
                    SUM(employee_social_security_centimos),
                    0
                ) AS employee_ss_centimos,
                COALESCE(
                    SUM(employer_social_security_centimos),
                    0
                ) AS employer_ss_centimos,
                COALESCE(
                    SUM(irpf_centimos),
                    0
                ) AS irpf_centimos,
                COALESCE(
                    SUM(net_salary_centimos),
                    0
                ) AS net_salary_centimos,
                COALESCE(
                    SUM(total_employer_cost_centimos),
                    0
                ) AS total_employer_cost_centimos
            FROM worker_payrolls
            WHERE period_year = ?
              AND period_month = ?
              AND active = 1
            """,
            (
                int(year),
                int(month),
            ),
        ).fetchone()

    result = {
        key: int(value or 0)
        for key, value in dict(row).items()
    }

    result["tgss_total_centimos"] = (
        result["employee_ss_centimos"]
        + result["employer_ss_centimos"]
    )

    return result


def _worker_full_name(
    worker: dict[str, Any],
) -> str:
    parts = [
        _text(worker.get("first_name")),
        _text(worker.get("last_name_1")),
        _text(worker.get("last_name_2")),
    ]

    return " ".join(
        part
        for part in parts
        if part
    )


def _salary_expense_payload(
    payroll: dict[str, Any],
    worker: dict[str, Any],
) -> dict[str, Any]:
    worker_name = _worker_full_name(worker)
    year = int(payroll["period_year"])
    month = int(payroll["period_month"])
    gross_centimos = int(
        payroll["gross_salary_centimos"]
    )
    document_path = _text(
        payroll.get("document_path")
    )

    return {
        "fecha_gasto": payroll["accrual_date"],
        "fecha_factura": payroll["accrual_date"],
        "proveedor": worker_name,
        "supplier_name_snapshot": worker_name,
        "supplier_tax_id_snapshot": _text(
            worker.get("tax_id")
        ),
        "concepto": (
            f"Nómina {month:02d}/{year} · "
            f"{worker_name}"
        ),
        "categoria": "Personal · Nóminas",
        "expense_category_code": "PERSONAL",
        "expense_subcategory_code": "NOMINAS",
        "classification_source": "MANUAL",
        "tipo_justificante": "NOMINA",
        "forma_pago": "TRANSFERENCIA",
        "base_imponible_centimos": gross_centimos,
        "iva_centimos": 0,
        "irpf_centimos": 0,
        "otros_impuestos_centimos": 0,
        "total_centimos": gross_centimos,
        "importe": gross_centimos / 100,
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
            payroll.get("liquidation_start_date")
            or None
        ),
        "periodo_hasta": (
            payroll.get("liquidation_end_date")
            or None
        ),
        "fecha_vencimiento": (
            payroll.get("payment_due_date")
            or None
        ),
        "observaciones": (
            "Gasto contable generado desde "
            "la nómina. El pago bancario se "
            "concilia contra el líquido de la "
            "nómina, no contra este gasto."
        ),
    }


def sync_salary_expense(
    payroll_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    payroll = get_payroll(
        payroll_id,
        db_path=db_path,
    )

    if not payroll:
        raise ValueError(
            "Nómina no encontrada"
        )

    worker = worker_service.get_worker(
        int(payroll["worker_id"]),
        db_path=db_path,
    )

    if not worker:
        raise ValueError(
            "Trabajador no encontrado"
        )

    expense_payload = _salary_expense_payload(
        payroll,
        worker,
    )

    expense_id = _optional_integer(
        payroll.get("salary_expense_id")
    )

    if expense_id:
        expense = expense_service.update_expense(
            expense_id,
            expense_payload,
            db_path=db_path,
        )
    else:
        expense = expense_service.create_expense(
            expense_payload,
            db_path=db_path,
        )
        expense_id = int(expense["id"])

        with closing(_connect(db_path)) as conn:
            conn.execute(
                """
                UPDATE worker_payrolls
                SET salary_expense_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    expense_id,
                    int(payroll_id),
                ),
            )
            conn.commit()

    return expense


def list_payrolls(
    *,
    year: int | None = None,
    month: int | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    conditions = [
        "p.active = 1",
    ]
    params: list[Any] = []

    if year is not None:
        conditions.append(
            "p.period_year = ?"
        )
        params.append(int(year))

    if month is not None:
        conditions.append(
            "p.period_month = ?"
        )
        params.append(int(month))

    where_sql = " AND ".join(conditions)

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.*,
                w.worker_code,
                w.first_name,
                w.last_name_1,
                w.last_name_2,
                w.tax_id,
                w.position
            FROM worker_payrolls p
            JOIN workers w
              ON w.id = p.worker_id
            WHERE {where_sql}
            ORDER BY
                p.period_year DESC,
                p.period_month DESC,
                w.last_name_1,
                w.last_name_2,
                w.first_name,
                p.id DESC
            """,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]
