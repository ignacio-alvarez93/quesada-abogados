from __future__ import annotations

import csv
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")

CNO_CSV_PATH = Path(
    "database/catalogos_mercurio/csv/"
    "cno_sepe_2011.csv"
)

CONTRACT_FIELDS = (
    "contract_code",
    "contract_type",
    "start_date",
    "end_date",
    "trial_period_end_date",
    "workday_type",
    "weekly_hours",
    "gross_salary_centimos",
    "salary_periodicity",
    "payments_per_year",
    "contribution_group",
    "professional_category",
    "collective_agreement",
    "contract_position",
    "contract_cno_code",
    "contract_cno_description",
    "contract_cno_catalog_id",
    "document_path",
    "active",
    "notes",
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


def _float(
    value: Any,
    default: float = 0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_int(value: Any) -> int:
    if isinstance(value, str):
        return 1 if value.strip().lower() in {
            "1",
            "true",
            "sí",
            "si",
            "yes",
            "on",
        } else 0

    return 1 if bool(value) else 0


def _normalize_date(
    value: Any,
    *,
    label: str,
) -> str:
    raw = _text(value)

    if not raw:
        return ""

    for fmt in (
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(
                raw,
                fmt,
            )
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass

    raise ValueError(
        f"{label} debe tener formato DD/MM/YYYY"
    )


def _normalize_data(
    data: dict[str, Any],
) -> dict[str, Any]:
    normalized = {
        field: data.get(field)
        for field in CONTRACT_FIELDS
    }

    for field in (
        "contract_code",
        "contract_type",
        "workday_type",
        "salary_periodicity",
        "contribution_group",
        "professional_category",
        "collective_agreement",
        "contract_position",
        "contract_cno_code",
        "contract_cno_description",
        "contract_cno_catalog_id",
        "document_path",
        "notes",
    ):
        normalized[field] = _text(
            normalized.get(field)
        )

    normalized["contract_type"] = (
        normalized["contract_type"]
        or "INDEFINITE"
    ).upper()

    normalized["workday_type"] = (
        normalized["workday_type"]
        or "FULL_TIME"
    ).upper()

    normalized["salary_periodicity"] = (
        normalized["salary_periodicity"]
        or "ANNUAL"
    ).upper()

    normalized["start_date"] = _normalize_date(
        normalized.get("start_date"),
        label="La fecha de inicio",
    )

    if not normalized["start_date"]:
        raise ValueError(
            "La fecha de inicio es obligatoria"
        )

    normalized["end_date"] = _normalize_date(
        normalized.get("end_date"),
        label="La fecha de finalización",
    )

    normalized["trial_period_end_date"] = (
        _normalize_date(
            normalized.get(
                "trial_period_end_date"
            ),
            label=(
                "La fecha de fin "
                "del periodo de prueba"
            ),
        )
    )

    normalized["weekly_hours"] = max(
        0,
        _float(
            normalized.get("weekly_hours"),
            40,
        ),
    )

    normalized["gross_salary_centimos"] = max(
        0,
        _integer(
            normalized.get(
                "gross_salary_centimos"
            ),
        ),
    )

    normalized["payments_per_year"] = max(
        1,
        _integer(
            normalized.get(
                "payments_per_year"
            ),
            14,
        ),
    )

    normalized["active"] = _bool_int(
        normalized.get("active", 1)
    )

    if normalized["end_date"]:
        if (
            normalized["end_date"]
            < normalized["start_date"]
        ):
            raise ValueError(
                "La fecha de fin no puede ser "
                "anterior a la fecha de inicio"
            )

    return normalized


def load_cno_options() -> list[dict[str, str]]:
    if not CNO_CSV_PATH.exists():
        return []

    options = []

    with CNO_CSV_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            active = _text(
                row.get("activo") or "1"
            ).lower()

            if active in {
                "0",
                "false",
                "no",
            }:
                continue

            catalog_id = _text(
                row.get("codigo")
            )
            raw_description = _text(
                row.get("descripcion")
            )

            if not raw_description:
                continue

            code = ""
            description = raw_description

            if " - " in raw_description:
                possible_code, possible_description = (
                    raw_description.split(
                        " - ",
                        1,
                    )
                )

                possible_code = (
                    possible_code.strip()
                )

                if (
                    possible_code.isdigit()
                    or possible_code == "ZZZZZZZZ"
                ):
                    code = possible_code
                    description = (
                        possible_description.strip()
                    )

            if not code:
                code = catalog_id

            options.append(
                {
                    "id": code,
                    "label": (
                        f"{code} · {description}"
                    ),
                    "code": code,
                    "description": description,
                    "catalog_id": catalog_id,
                }
            )

    return options


def load_cno_autocomplete_options() -> list[str]:
    if not CNO_CSV_PATH.exists():
        return []

    options = []

    try:
        with CNO_CSV_PATH.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)

            for row in reader:
                catalog_id = _text(
                    row.get("codigo")
                )
                description = _text(
                    row.get("descripcion")
                )
                active = _text(
                    row.get("activo") or "1"
                )

                if active in {
                    "0",
                    "False",
                    "false",
                }:
                    continue

                if not catalog_id and not description:
                    continue

                if catalog_id and description:
                    options.append(
                        f"{description} · CNO {catalog_id}"
                    )
                else:
                    options.append(
                        description or catalog_id
                    )

    except Exception:
        return []

    return options


def resolve_cno_value(value: Any) -> dict[str, str]:
    raw = _text(value)

    if not raw:
        return {
            "catalog_id": "",
            "code": "",
            "description": "",
        }

    catalog_id = ""
    raw_description = raw

    if " · " in raw:
        raw_description, tail = raw.rsplit(
            " · ",
            1,
        )

        parts = tail.strip().split()

        if parts:
            catalog_id = parts[-1].strip()

    raw_description = raw_description.strip()
    occupation_code = ""
    occupation_description = raw_description

    if " - " in raw_description:
        possible_code, possible_description = (
            raw_description.split(
                " - ",
                1,
            )
        )

        possible_code = possible_code.strip()

        if (
            possible_code.isdigit()
            or possible_code == "ZZZZZZZZ"
        ):
            occupation_code = possible_code
            occupation_description = (
                possible_description.strip()
            )

    return {
        "catalog_id": catalog_id,
        "code": occupation_code,
        "description": occupation_description,
    }


def list_worker_contracts(
    worker_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM worker_contracts
            WHERE worker_id = ?
            ORDER BY
                COALESCE(active, 1) DESC,
                start_date DESC,
                id DESC
            """,
            (int(worker_id),),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def get_contract(
    contract_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM worker_contracts
            WHERE id = ?
            """,
            (int(contract_id),),
        ).fetchone()

    return dict(row) if row else None


def create_contract(
    worker_id: int,
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    normalized = _normalize_data(data)

    fields = list(CONTRACT_FIELDS)

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

        cursor = conn.execute(
            f"""
            INSERT INTO worker_contracts (
                worker_id,
                {", ".join(fields)}
            )
            VALUES (
                ?,
                {", ".join("?" for _ in fields)}
            )
            """,
            [
                int(worker_id),
                *[
                    normalized[field]
                    for field in fields
                ],
            ],
        )

        contract_id = int(
            cursor.lastrowid
        )

        conn.commit()

    return contract_id


def update_contract(
    contract_id: int,
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    normalized = _normalize_data(data)
    fields = list(CONTRACT_FIELDS)

    assignments = ", ".join(
        f"{field} = ?"
        for field in fields
    )

    with closing(_connect(db_path)) as conn:
        current = conn.execute(
            """
            SELECT id
            FROM worker_contracts
            WHERE id = ?
            """,
            (int(contract_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "Contrato no encontrado"
            )

        conn.execute(
            f"""
            UPDATE worker_contracts
            SET {assignments},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [
                *[
                    normalized[field]
                    for field in fields
                ],
                int(contract_id),
            ],
        )

        conn.commit()

    return True


def finish_contract(
    contract_id: int,
    end_date: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    normalized_end = _normalize_date(
        end_date,
        label="La fecha de finalización",
    )

    if not normalized_end:
        raise ValueError(
            "La fecha de finalización "
            "es obligatoria"
        )

    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT start_date
            FROM worker_contracts
            WHERE id = ?
            """,
            (int(contract_id),),
        ).fetchone()

        if not row:
            raise ValueError(
                "Contrato no encontrado"
            )

        if (
            row["start_date"]
            and normalized_end
            < row["start_date"]
        ):
            raise ValueError(
                "La fecha de fin no puede ser "
                "anterior a la fecha de inicio"
            )

        conn.execute(
            """
            UPDATE worker_contracts
            SET end_date = ?,
                active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized_end,
                int(contract_id),
            ),
        )

        conn.commit()

    return True
