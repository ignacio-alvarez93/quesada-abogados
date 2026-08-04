"""
Revisión y consolidación de propuestas de nómina de expedientes.

Este servicio:
- permite corregir propuestas extraídas;
- permite confirmarlas o descartarlas;
- consolida únicamente propuestas confirmadas o aplicadas;
- no modifica el diagnóstico económico del expediente.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services import (
    expedient_payroll_proposal_service
    as proposal_service,
)


DEFAULT_DB_PATH = proposal_service.DEFAULT_DB_PATH

STATUS_PENDING = "PENDIENTE_REVISION"
STATUS_CONFIRMED = "CONFIRMADA"
STATUS_DISCARDED = "DESCARTADA"
STATUS_APPLIED = "APLICADA"

VALID_REVIEW_STATUSES = {
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_DISCARDED,
    STATUS_APPLIED,
}

EDITABLE_FIELDS = {
    "period_year",
    "period_month",
    "employee_name",
    "employee_identity",
    "company_name",
    "company_tax_id",
    "total_accrued_centimos",
    "total_deductions_centimos",
    "net_pay_centimos",
    "contribution_base_centimos",
    "irpf_centimos",
}

MONEY_FIELDS = {
    "total_accrued_centimos",
    "total_deductions_centimos",
    "net_pay_centimos",
    "contribution_base_centimos",
    "irpf_centimos",
}


def _now() -> str:
    return datetime.now().isoformat(
        timespec="seconds"
    )


def _optional_int(
    value: Any,
) -> int | None:
    if value in (None, ""):
        return None

    return int(value)


def _period_key(
    year: int | None,
    month: int | None,
) -> str:
    if not year or not month:
        return ""

    return f"{int(year):04d}-{int(month):02d}"


def _validate_period(
    year: int | None,
    month: int | None,
) -> None:
    if year is not None and year < 1900:
        raise ValueError(
            "El año del periodo no es válido"
        )

    if (
        month is not None
        and not 1 <= month <= 12
    ):
        raise ValueError(
            "El mes debe estar entre 1 y 12"
        )


def _validate_money(
    field: str,
    value: int | None,
) -> None:
    if value is not None and value < 0:
        raise ValueError(
            f"{field} no puede ser negativo"
        )


def _proposal_to_dict(row):
    return (
        proposal_service
        ._proposal_row_to_dict(row)
    )


def get_proposal(
    proposal_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    proposal_service.ensure_schema(
        db_path=db_path
    )

    with proposal_service._connection(
        db_path
    ) as conn:
        row = conn.execute(
            """
            SELECT
                p.*,
                d.expediente_id,
                d.source_name,
                d.source_path,
                d.sha256 AS document_sha256
            FROM expedient_payroll_proposals p
            JOIN expedient_income_evidence_documents d
              ON d.id = p.document_id
            WHERE p.id = ?
            """,
            (int(proposal_id),),
        ).fetchone()

    return _proposal_to_dict(row)


def list_expedient_proposals(
    expediente_id: int,
    *,
    include_discarded: bool = True,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    proposal_service.ensure_schema(
        db_path=db_path
    )

    conditions = [
        "d.expediente_id = ?",
    ]
    params: list[Any] = [
        int(expediente_id),
    ]

    if not include_discarded:
        conditions.append(
            "p.review_status <> ?"
        )
        params.append(
            STATUS_DISCARDED
        )

    where_sql = " AND ".join(
        conditions
    )

    with proposal_service._connection(
        db_path
    ) as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.*,
                d.expediente_id,
                d.source_name,
                d.source_path,
                d.sha256 AS document_sha256
            FROM expedient_payroll_proposals p
            JOIN expedient_income_evidence_documents d
              ON d.id = p.document_id
            WHERE {where_sql}
            ORDER BY
                COALESCE(p.period_year, 0),
                COALESCE(p.period_month, 0),
                p.document_id,
                p.sequence,
                p.id
            """,
            params,
        ).fetchall()

    return [
        _proposal_to_dict(row)
        for row in rows
    ]


def update_proposal(
    proposal_id: int,
    corrections: dict,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    proposal_service.ensure_schema(
        db_path=db_path
    )

    corrections = dict(
        corrections or {}
    )

    unknown_fields = (
        set(corrections)
        - EDITABLE_FIELDS
    )

    if unknown_fields:
        raise ValueError(
            "Campos no editables: "
            + ", ".join(
                sorted(unknown_fields)
            )
        )

    if not corrections:
        current = get_proposal(
            proposal_id,
            db_path=db_path,
        )

        if not current:
            raise ValueError(
                "No existe la propuesta"
            )

        return current

    normalized = {}

    for field, value in corrections.items():
        if field in {
            "period_year",
            "period_month",
        }:
            normalized[field] = (
                _optional_int(value)
            )
        elif field in MONEY_FIELDS:
            normalized[field] = (
                _optional_int(value)
            )
            _validate_money(
                field,
                normalized[field],
            )
        else:
            normalized[field] = str(
                value or ""
            ).strip()

    with proposal_service._connection(
        db_path
    ) as conn:
        current = conn.execute(
            """
            SELECT *
            FROM expedient_payroll_proposals
            WHERE id = ?
            """,
            (int(proposal_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "No existe la propuesta"
            )

        current_data = dict(current)

        year = normalized.get(
            "period_year",
            current_data.get("period_year"),
        )
        month = normalized.get(
            "period_month",
            current_data.get("period_month"),
        )

        _validate_period(
            year,
            month,
        )

        normalized["period_key"] = (
            _period_key(year, month)
        )

        assignments = [
            f"{field} = ?"
            for field in normalized
        ]
        assignments.append(
            "updated_at = ?"
        )

        values = [
            normalized[field]
            for field in normalized
        ]
        values.extend(
            [
                _now(),
                int(proposal_id),
            ]
        )

        conn.execute(
            f"""
            UPDATE expedient_payroll_proposals
            SET {", ".join(assignments)}
            WHERE id = ?
            """,
            values,
        )

    result = get_proposal(
        proposal_id,
        db_path=db_path,
    )

    if not result:
        raise RuntimeError(
            "No se pudo recuperar la propuesta"
        )

    return result


def confirm_proposal(
    proposal_id: int,
    *,
    corrections: dict | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    if corrections:
        update_proposal(
            proposal_id,
            corrections,
            db_path=db_path,
        )

    proposal_service.ensure_schema(
        db_path=db_path
    )

    with proposal_service._connection(
        db_path
    ) as conn:
        current = conn.execute(
            """
            SELECT *
            FROM expedient_payroll_proposals
            WHERE id = ?
            """,
            (int(proposal_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "No existe la propuesta"
            )

        current_data = dict(current)

        if (
            current_data.get("period_year")
            is None
            or current_data.get(
                "period_month"
            )
            is None
        ):
            raise ValueError(
                "No se puede confirmar sin periodo"
            )

        if (
            current_data.get(
                "net_pay_centimos"
            )
            is None
        ):
            raise ValueError(
                "No se puede confirmar sin "
                "líquido a percibir"
            )

        conn.execute(
            """
            UPDATE expedient_payroll_proposals
            SET review_status = ?,
                requires_manual_review = 0,
                reviewed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                STATUS_CONFIRMED,
                _now(),
                _now(),
                int(proposal_id),
            ),
        )

    result = get_proposal(
        proposal_id,
        db_path=db_path,
    )

    if not result:
        raise RuntimeError(
            "No se pudo recuperar la propuesta"
        )

    return result


def discard_proposal(
    proposal_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    proposal_service.ensure_schema(
        db_path=db_path
    )

    with proposal_service._connection(
        db_path
    ) as conn:
        current = conn.execute(
            """
            SELECT id
            FROM expedient_payroll_proposals
            WHERE id = ?
            """,
            (int(proposal_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "No existe la propuesta"
            )

        conn.execute(
            """
            UPDATE expedient_payroll_proposals
            SET review_status = ?,
                requires_manual_review = 0,
                reviewed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                STATUS_DISCARDED,
                _now(),
                _now(),
                int(proposal_id),
            ),
        )

    result = get_proposal(
        proposal_id,
        db_path=db_path,
    )

    if not result:
        raise RuntimeError(
            "No se pudo recuperar la propuesta"
        )

    return result


def reopen_proposal(
    proposal_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    proposal_service.ensure_schema(
        db_path=db_path
    )

    with proposal_service._connection(
        db_path
    ) as conn:
        current = conn.execute(
            """
            SELECT id
            FROM expedient_payroll_proposals
            WHERE id = ?
            """,
            (int(proposal_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "No existe la propuesta"
            )

        conn.execute(
            """
            UPDATE expedient_payroll_proposals
            SET review_status = ?,
                requires_manual_review = 1,
                reviewed_at = NULL,
                applied_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                STATUS_PENDING,
                _now(),
                int(proposal_id),
            ),
        )

    result = get_proposal(
        proposal_id,
        db_path=db_path,
    )

    if not result:
        raise RuntimeError(
            "No se pudo recuperar la propuesta"
        )

    return result


def _month_index(
    year: int,
    month: int,
) -> int:
    return (
        int(year) * 12
        + int(month)
        - 1
    )


def _period_from_index(
    value: int,
) -> str:
    year, month_index = divmod(
        int(value),
        12,
    )

    return (
        f"{year:04d}-"
        f"{month_index + 1:02d}"
    )


def consolidate_expedient_payrolls(
    expediente_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    proposals = list_expedient_proposals(
        expediente_id,
        include_discarded=False,
        db_path=db_path,
    )

    confirmed = [
        item
        for item in proposals
        if item.get("review_status")
        in {
            STATUS_CONFIRMED,
            STATUS_APPLIED,
        }
    ]

    pending = [
        item
        for item in proposals
        if item.get("review_status")
        == STATUS_PENDING
    ]

    period_groups: dict[
        str,
        list[dict],
    ] = {}

    for item in confirmed:
        key = _period_key(
            item.get("period_year"),
            item.get("period_month"),
        )

        if key:
            period_groups.setdefault(
                key,
                [],
            ).append(item)

    duplicate_periods = sorted(
        key
        for key, items
        in period_groups.items()
        if len(items) > 1
    )

    unique_periods = sorted(
        period_groups
    )

    missing_periods = []

    if len(unique_periods) >= 2:
        first_year, first_month = (
            int(part)
            for part in unique_periods[0]
            .split("-")
        )
        last_year, last_month = (
            int(part)
            for part in unique_periods[-1]
            .split("-")
        )

        first_index = _month_index(
            first_year,
            first_month,
        )
        last_index = _month_index(
            last_year,
            last_month,
        )

        present = {
            _month_index(
                int(period[:4]),
                int(period[5:7]),
            )
            for period in unique_periods
        }

        missing_periods = [
            _period_from_index(index)
            for index in range(
                first_index,
                last_index + 1,
            )
            if index not in present
        ]

    net_values = [
        int(item["net_pay_centimos"])
        for item in confirmed
        if item.get(
            "net_pay_centimos"
        )
        is not None
    ]

    average_net = (
        round(
            sum(net_values)
            / len(net_values)
        )
        if net_values
        else None
    )

    minimum_net = (
        min(net_values)
        if net_values
        else None
    )

    maximum_net = (
        max(net_values)
        if net_values
        else None
    )

    variation = (
        maximum_net - minimum_net
        if (
            minimum_net is not None
            and maximum_net is not None
        )
        else None
    )

    blocking_reasons = []

    if not confirmed:
        blocking_reasons.append(
            "No hay nóminas confirmadas."
        )

    if duplicate_periods:
        blocking_reasons.append(
            "Hay periodos duplicados."
        )

    if any(
        item.get("net_pay_centimos")
        is None
        for item in confirmed
    ):
        blocking_reasons.append(
            "Hay nóminas confirmadas sin "
            "líquido a percibir."
        )

    suggested_income = (
        average_net
        if (
            average_net is not None
            and not duplicate_periods
        )
        else None
    )

    return {
        "expediente_id": int(
            expediente_id
        ),
        "proposal_count": len(
            proposals
        ),
        "pending_review_count": len(
            pending
        ),
        "confirmed_payroll_count": len(
            confirmed
        ),
        "periods": unique_periods,
        "duplicate_periods": (
            duplicate_periods
        ),
        "missing_periods": (
            missing_periods
        ),
        "average_net_centimos": (
            average_net
        ),
        "minimum_net_centimos": (
            minimum_net
        ),
        "maximum_net_centimos": (
            maximum_net
        ),
        "net_variation_centimos": (
            variation
        ),
        (
            "suggested_monthly_"
            "income_centimos"
        ): suggested_income,
        "blocking_reasons": (
            blocking_reasons
        ),
        "requires_manual_review": True,
        "ready_for_application": (
            suggested_income is not None
            and not blocking_reasons
        ),
        "applied_to_diagnosis": False,
    }
