from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")

MIGRATION_PATH = Path(
    "database/migrations/"
    "20260716_create_fiscal_period_management.sql"
)

VALID_MODELS = {"303", "130"}
VALID_QUARTERS = {1, 2, 3, 4}
VALID_STATUSES = {"OPEN", "REVIEWED", "CLOSED"}

VALID_ADVISORY_RESULT_TYPES = {
    "A_PAGAR",
    "A_COMPENSAR",
    "A_DEVOLVER",
    "CERO",
    "OTRO",
}


@contextmanager
def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    try:
        ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def ensure_schema(
    conn: sqlite3.Connection,
) -> None:
    if not MIGRATION_PATH.exists():
        raise FileNotFoundError(
            f"No existe la migración fiscal: "
            f"{MIGRATION_PATH}"
        )

    conn.executescript(
        MIGRATION_PATH.read_text(
            encoding="utf-8"
        )
    )


def _dict(
    row: sqlite3.Row | None,
) -> dict | None:
    return dict(row) if row else None


def _int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _text(
    value: Any,
) -> str:
    return str(value or "").strip()


def _optional_text(
    value: Any,
) -> str | None:
    normalized = _text(value)
    return normalized or None


def _bool_int(
    value: Any,
    default: bool = False,
) -> int:
    if value is None:
        return int(bool(default))

    if isinstance(value, bool):
        return int(value)

    normalized = _text(value).lower()

    if normalized in {
        "0",
        "false",
        "no",
        "n",
        "off",
    }:
        return 0

    if normalized in {
        "1",
        "true",
        "yes",
        "sí",
        "si",
        "s",
        "on",
    }:
        return 1

    return int(bool(value))


def _validate_period(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
) -> tuple[int, int, str]:
    year = _int(fiscal_year)
    quarter_value = _int(quarter)
    model = _text(model_number).upper()

    if year < 2000 or year > 2200:
        raise ValueError(
            "El ejercicio fiscal no es válido"
        )

    if quarter_value not in VALID_QUARTERS:
        raise ValueError(
            "El trimestre debe estar entre 1 y 4"
        )

    if model not in VALID_MODELS:
        raise ValueError(
            "El modelo fiscal debe ser 303 o 130"
        )

    return year, quarter_value, model


def _normalize_settings(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    data: dict | None = None,
) -> dict:
    year, quarter_value, model = _validate_period(
        fiscal_year,
        quarter,
        model_number,
    )

    payload = dict(data or {})

    status = _text(
        payload.get("status") or "OPEN"
    ).upper()

    if status not in VALID_STATUSES:
        raise ValueError(
            "Estado fiscal no válido"
        )

    payment_rate = _float(
        payload.get("payment_rate"),
        20.0,
    )

    difficult_expense_rate = _float(
        payload.get(
            "difficult_expense_rate"
        ),
        5.0,
    )

    if not 0 <= payment_rate <= 100:
        raise ValueError(
            "El porcentaje del modelo 130 "
            "debe estar entre 0 y 100"
        )

    if not 0 <= difficult_expense_rate <= 100:
        raise ValueError(
            "El porcentaje de difícil justificación "
            "debe estar entre 0 y 100"
        )

    normalized = {
        "fiscal_year": year,
        "quarter": quarter_value,
        "model_number": model,
        "status": status,

        "compensation_previous_centimos":
            max(
                0,
                _int(
                    payload.get(
                        "compensation_previous_centimos"
                    )
                ),
            ),

        "payment_rate":
            payment_rate,

        "previous_positive_payments_centimos":
            max(
                0,
                _int(
                    payload.get(
                        "previous_positive_payments_centimos"
                    )
                ),
            ),

        "apply_difficult_to_justify_expenses":
            _bool_int(
                payload.get(
                    "apply_difficult_to_justify_expenses"
                ),
                default=True,
            ),

        "difficult_expense_rate":
            difficult_expense_rate,

        "difficult_expense_annual_limit_centimos":
            max(
                0,
                _int(
                    payload.get(
                        "difficult_expense_annual_limit_centimos",
                        200000,
                    )
                ),
            ),

        "advisory_reduction_centimos":
            max(
                0,
                _int(
                    payload.get(
                        "advisory_reduction_centimos"
                    )
                ),
            ),

        "other_adjustments_centimos":
            _int(
                payload.get(
                    "other_adjustments_centimos"
                )
            ),

        "notes":
            _optional_text(
                payload.get("notes")
            ),

        "reviewed_at":
            _optional_text(
                payload.get("reviewed_at")
            ),

        "closed_at":
            _optional_text(
                payload.get("closed_at")
            ),
    }

    if model == "303":
        normalized[
            "previous_positive_payments_centimos"
        ] = 0
        normalized["payment_rate"] = 20.0
        normalized[
            "apply_difficult_to_justify_expenses"
        ] = 0
        normalized[
            "difficult_expense_rate"
        ] = 5.0
        normalized[
            "difficult_expense_annual_limit_centimos"
        ] = 200000
        normalized[
            "advisory_reduction_centimos"
        ] = 0
        normalized[
            "other_adjustments_centimos"
        ] = 0

    if model == "130":
        normalized[
            "compensation_previous_centimos"
        ] = 0

    return normalized


def get_period_settings(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    *,
    create_default: bool = False,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    year, quarter_value, model = _validate_period(
        fiscal_year,
        quarter,
        model_number,
    )

    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM fiscal_period_settings
            WHERE fiscal_year = ?
              AND quarter = ?
              AND model_number = ?
            """,
            (
                year,
                quarter_value,
                model,
            ),
        ).fetchone()

    if row:
        return _dict(row)

    if not create_default:
        return None

    return upsert_period_settings(
        year,
        quarter_value,
        model,
        {},
        db_path=db_path,
    )


def upsert_period_settings(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    data: dict | None = None,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    values = _normalize_settings(
        fiscal_year,
        quarter,
        model_number,
        data,
    )

    fields = list(values)

    placeholders = ", ".join(
        "?" for _ in fields
    )

    update_fields = [
        field
        for field in fields
        if field not in {
            "fiscal_year",
            "quarter",
            "model_number",
        }
    ]

    assignments = ", ".join(
        f"{field} = excluded.{field}"
        for field in update_fields
    )

    with _connect(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO fiscal_period_settings (
                {", ".join(fields)}
            )
            VALUES ({placeholders})
            ON CONFLICT (
                fiscal_year,
                quarter,
                model_number
            )
            DO UPDATE SET
                {assignments},
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                values[field]
                for field in fields
            ],
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM fiscal_period_settings
            WHERE fiscal_year = ?
              AND quarter = ?
              AND model_number = ?
            """,
            (
                values["fiscal_year"],
                values["quarter"],
                values["model_number"],
            ),
        ).fetchone()

    return _dict(row) or {}


def list_period_settings(
    *,
    fiscal_year: int | None = None,
    model_number: str | None = None,
    status: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    where = []
    params = []

    if fiscal_year is not None:
        where.append("fiscal_year = ?")
        params.append(_int(fiscal_year))

    if model_number:
        model = _text(
            model_number
        ).upper()

        if model not in VALID_MODELS:
            raise ValueError(
                "El modelo fiscal debe ser 303 o 130"
            )

        where.append("model_number = ?")
        params.append(model)

    if status:
        normalized_status = _text(
            status
        ).upper()

        if normalized_status not in VALID_STATUSES:
            raise ValueError(
                "Estado fiscal no válido"
            )

        where.append("status = ?")
        params.append(normalized_status)

    sql = """
        SELECT *
        FROM fiscal_period_settings
    """

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += """
        ORDER BY
            fiscal_year DESC,
            quarter DESC,
            model_number ASC
    """

    with _connect(db_path) as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def set_period_status(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    status: Any,
    *,
    notes: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    current = get_period_settings(
        fiscal_year,
        quarter,
        model_number,
        create_default=True,
        db_path=db_path,
    ) or {}

    normalized_status = _text(
        status
    ).upper()

    if normalized_status not in VALID_STATUSES:
        raise ValueError(
            "Estado fiscal no válido"
        )

    now = datetime.now().isoformat(
        timespec="seconds"
    )

    payload = {
        **current,
        "status": normalized_status,
        "notes": (
            notes
            if notes is not None
            else current.get("notes")
        ),
    }

    if normalized_status == "OPEN":
        payload["reviewed_at"] = None
        payload["closed_at"] = None

    elif normalized_status == "REVIEWED":
        payload["reviewed_at"] = (
            current.get("reviewed_at")
            or now
        )
        payload["closed_at"] = None

    elif normalized_status == "CLOSED":
        payload["reviewed_at"] = (
            current.get("reviewed_at")
            or now
        )
        payload["closed_at"] = now

    return upsert_period_settings(
        fiscal_year,
        quarter,
        model_number,
        payload,
        db_path=db_path,
    )


def _normalize_comparison(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    data: dict | None = None,
) -> dict:
    year, quarter_value, model = _validate_period(
        fiscal_year,
        quarter,
        model_number,
    )

    payload = dict(data or {})

    confirmed = payload.get(
        "crm_confirmed_result_centimos"
    )
    provisional = payload.get(
        "crm_provisional_result_centimos"
    )
    advisory = payload.get(
        "advisory_result_centimos"
    )

    confirmed_value = (
        None
        if confirmed in (None, "")
        else _int(confirmed)
    )

    provisional_value = (
        None
        if provisional in (None, "")
        else _int(provisional)
    )

    advisory_value = (
        None
        if advisory in (None, "")
        else _int(advisory)
    )

    difference = None

    if (
        advisory_value is not None
        and confirmed_value is not None
    ):
        difference = (
            advisory_value
            - confirmed_value
        )

    result_type = _text(
        payload.get(
            "advisory_result_type"
        )
    ).upper()

    if not result_type:
        result_type = None

    if (
        result_type is not None
        and result_type
        not in VALID_ADVISORY_RESULT_TYPES
    ):
        raise ValueError(
            "Tipo de resultado de asesoría no válido"
        )

    return {
        "fiscal_year":
            year,

        "quarter":
            quarter_value,

        "model_number":
            model,

        "crm_confirmed_result_centimos":
            confirmed_value,

        "crm_provisional_result_centimos":
            provisional_value,

        "advisory_result_centimos":
            advisory_value,

        "difference_centimos":
            difference,

        "advisory_result_type":
            result_type,

        "explanation":
            _optional_text(
                payload.get("explanation")
            ),

        "advisory_notes":
            _optional_text(
                payload.get("advisory_notes")
            ),

        "document_path":
            _optional_text(
                payload.get("document_path")
            ),

        "document_name":
            _optional_text(
                payload.get("document_name")
            ),

        "compared_at":
            _optional_text(
                payload.get("compared_at")
            ),

        "reviewed_by":
            _optional_text(
                payload.get("reviewed_by")
            ),
    }


def upsert_advisory_comparison(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    data: dict | None = None,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    values = _normalize_comparison(
        fiscal_year,
        quarter,
        model_number,
        data,
    )

    if (
        values["advisory_result_centimos"]
        is not None
        and not values["compared_at"]
    ):
        values["compared_at"] = (
            datetime.now().isoformat(
                timespec="seconds"
            )
        )

    fields = list(values)

    placeholders = ", ".join(
        "?" for _ in fields
    )

    update_fields = [
        field
        for field in fields
        if field not in {
            "fiscal_year",
            "quarter",
            "model_number",
        }
    ]

    assignments = ", ".join(
        f"{field} = excluded.{field}"
        for field in update_fields
    )

    with _connect(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO fiscal_advisory_comparisons (
                {", ".join(fields)}
            )
            VALUES ({placeholders})
            ON CONFLICT (
                fiscal_year,
                quarter,
                model_number
            )
            DO UPDATE SET
                {assignments},
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                values[field]
                for field in fields
            ],
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM fiscal_advisory_comparisons
            WHERE fiscal_year = ?
              AND quarter = ?
              AND model_number = ?
            """,
            (
                values["fiscal_year"],
                values["quarter"],
                values["model_number"],
            ),
        ).fetchone()

    return _dict(row) or {}


def get_advisory_comparison(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    year, quarter_value, model = _validate_period(
        fiscal_year,
        quarter,
        model_number,
    )

    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM fiscal_advisory_comparisons
            WHERE fiscal_year = ?
              AND quarter = ?
              AND model_number = ?
            """,
            (
                year,
                quarter_value,
                model,
            ),
        ).fetchone()

    return _dict(row)


def list_advisory_comparisons(
    *,
    fiscal_year: int | None = None,
    model_number: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    where = []
    params = []

    if fiscal_year is not None:
        where.append("fiscal_year = ?")
        params.append(
            _int(fiscal_year)
        )

    if model_number:
        model = _text(
            model_number
        ).upper()

        if model not in VALID_MODELS:
            raise ValueError(
                "El modelo fiscal debe ser 303 o 130"
            )

        where.append("model_number = ?")
        params.append(model)

    sql = """
        SELECT *
        FROM fiscal_advisory_comparisons
    """

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += """
        ORDER BY
            fiscal_year DESC,
            quarter DESC,
            model_number ASC
    """

    with _connect(db_path) as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def delete_advisory_comparison(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    year, quarter_value, model = _validate_period(
        fiscal_year,
        quarter,
        model_number,
    )

    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            DELETE
            FROM fiscal_advisory_comparisons
            WHERE fiscal_year = ?
              AND quarter = ?
              AND model_number = ?
            """,
            (
                year,
                quarter_value,
                model,
            ),
        )

        conn.commit()

        deleted = cursor.rowcount > 0

    return deleted


def estimate_configured_period(
    fiscal_year: Any,
    quarter: Any,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    from backend.services.fiscal_estimation_service import (
        estimate_model_303,
        estimate_model_130,
    )

    year, quarter_value, _ = _validate_period(
        fiscal_year,
        quarter,
        "303",
    )

    settings_303 = get_period_settings(
        year,
        quarter_value,
        "303",
        create_default=False,
        db_path=db_path,
    ) or {}

    settings_130 = get_period_settings(
        year,
        quarter_value,
        "130",
        create_default=False,
        db_path=db_path,
    ) or {}

    model_303 = estimate_model_303(
        year,
        quarter_value,
        compensation_previous_centimos=_int(
            settings_303.get(
                "compensation_previous_centimos"
            )
        ),
        db_path=db_path,
    )

    model_130 = estimate_model_130(
        year,
        quarter_value,
        payment_rate=_float(
            settings_130.get(
                "payment_rate"
            ),
            20.0,
        ),
        previous_positive_payments_centimos=_int(
            settings_130.get(
                "previous_positive_payments_centimos"
            )
        ),
        advisory_reduction_centimos=_int(
            settings_130.get(
                "advisory_reduction_centimos"
            )
        ),
        other_adjustments_centimos=_int(
            settings_130.get(
                "other_adjustments_centimos"
            )
        ),
        apply_difficult_to_justify_expenses=bool(
            _int(
                settings_130.get(
                    "apply_difficult_to_justify_expenses",
                    1,
                )
            )
        ),
        difficult_expense_rate=_float(
            settings_130.get(
                "difficult_expense_rate"
            ),
            5.0,
        ),
        difficult_expense_annual_limit_centimos=_int(
            settings_130.get(
                "difficult_expense_annual_limit_centimos",
                200000,
            )
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
        "year": year,
        "quarter": quarter_value,

        "model_303":
            model_303,

        "model_130":
            model_130,

        "combined": {
            "confirmed_to_pay_centimos":
                confirmed_total,

            "provisional_to_pay_centimos":
                provisional_total,
        },

        "settings": {
            "303": settings_303 or None,
            "130": settings_130 or None,
        },

        "comparisons": {
            "303": get_advisory_comparison(
                year,
                quarter_value,
                "303",
                db_path=db_path,
            ),

            "130": get_advisory_comparison(
                year,
                quarter_value,
                "130",
                db_path=db_path,
            ),
        },
    }


def snapshot_advisory_comparison_from_current_estimate(
    fiscal_year: Any,
    quarter: Any,
    model_number: Any,
    advisory_data: dict | None = None,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    year, quarter_value, model = _validate_period(
        fiscal_year,
        quarter,
        model_number,
    )

    summary = estimate_configured_period(
        year,
        quarter_value,
        db_path=db_path,
    )

    model_result = summary[
        f"model_{model}"
    ]

    payload = {
        **dict(advisory_data or {}),
        "crm_confirmed_result_centimos":
            model_result["confirmed"][
                "result_centimos"
            ],
        "crm_provisional_result_centimos":
            model_result["provisional"][
                "result_centimos"
            ],
    }

    return upsert_advisory_comparison(
        year,
        quarter_value,
        model,
        payload,
        db_path=db_path,
    )
