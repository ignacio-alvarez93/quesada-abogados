from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from contextlib import closing
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")

WORKER_FIELDS = (
    "first_name",
    "last_name_1",
    "last_name_2",
    "document_type",
    "tax_id",
    "birth_date",
    "social_security_number",
    "phone",
    "secondary_phone",
    "email",
    "address",
    "postal_code",
    "city",
    "province",
    "country",
    "iban",
    "position",
    "department",
    "workplace",
    "professional_category",
    "collective_agreement",
    "hire_date",
    "termination_date",
    "employment_status",
    "active",
    "notes",
)

EMPLOYMENT_STATUSES = {
    "ACTIVE",
    "TEMPORARY_LEAVE",
    "SICK_LEAVE",
    "MATERNITY_PATERNITY",
    "LEAVE_OF_ABSENCE",
    "TERMINATED",
}

DOCUMENT_TYPES = {
    "",
    "DNI",
    "NIE",
    "PASSPORT",
    "OTHER",
}


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


def ensure_schema(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    migration = Path(
        "database/migrations/"
        "20260717_create_workers.sql"
    )

    if not migration.exists():
        raise RuntimeError(
            "No se encuentra la migración de trabajadores"
        )

    sql = migration.read_text(
        encoding="utf-8"
    )

    with closing(_connect(db_path)) as conn:
        conn.executescript(sql)
        conn.commit()


def _text(value: Any) -> str:
    return str(value or "").strip()


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


def _normalize_identifier(value: Any) -> str:
    return (
        _text(value)
        .upper()
        .replace(" ", "")
        .replace("-", "")
    )


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
            return parsed.strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            pass

    raise ValueError(
        f"{label} debe tener formato DD/MM/YYYY"
    )


def _normalize_iban(value: Any) -> str:
    return re.sub(
        r"[^A-Z0-9]",
        "",
        _text(value).upper(),
    )


def _row_to_dict(row):
    return dict(row) if row else None


def _normalize_data(
    data: dict[str, Any],
) -> dict[str, Any]:
    normalized = {
        field: data.get(field)
        for field in WORKER_FIELDS
    }

    for field in (
        "first_name",
        "last_name_1",
        "last_name_2",
        "birth_date",
        "social_security_number",
        "phone",
        "secondary_phone",
        "email",
        "address",
        "postal_code",
        "city",
        "province",
        "country",
        "position",
        "department",
        "workplace",
        "professional_category",
        "collective_agreement",
        "hire_date",
        "termination_date",
        "notes",
    ):
        normalized[field] = _text(
            normalized.get(field)
        )

    normalized["first_name"] = (
        normalized["first_name"]
    )

    if not normalized["first_name"]:
        raise ValueError(
            "El nombre del trabajador es obligatorio"
        )

    normalized["birth_date"] = _normalize_date(
        normalized.get("birth_date"),
        label="La fecha de nacimiento",
    )

    normalized["hire_date"] = _normalize_date(
        normalized.get("hire_date"),
        label="La fecha de alta",
    )

    normalized["termination_date"] = _normalize_date(
        normalized.get("termination_date"),
        label="La fecha de baja",
    )

    normalized["document_type"] = (
        _text(
            normalized.get("document_type")
        ).upper()
    )

    if (
        normalized["document_type"]
        not in DOCUMENT_TYPES
    ):
        raise ValueError(
            "Tipo de documento no válido"
        )

    normalized["tax_id"] = (
        _normalize_identifier(
            normalized.get("tax_id")
        )
    )

    normalized["social_security_number"] = (
        _normalize_identifier(
            normalized.get(
                "social_security_number"
            )
        )
    )

    normalized["iban"] = _normalize_iban(
        normalized.get("iban")
    )

    normalized["country"] = (
        normalized.get("country")
        or "España"
    )

    normalized["employment_status"] = (
        _text(
            normalized.get(
                "employment_status"
            )
            or "ACTIVE"
        ).upper()
    )

    if (
        normalized["employment_status"]
        not in EMPLOYMENT_STATUSES
    ):
        raise ValueError(
            "Estado laboral no válido"
        )

    normalized["active"] = _bool_int(
        normalized.get("active", 1)
    )

    if (
        normalized["termination_date"]
        and normalized["employment_status"]
        == "ACTIVE"
    ):
        normalized["employment_status"] = (
            "TERMINATED"
        )
        normalized["active"] = 0

    return normalized


def _check_duplicate_tax_id(
    conn: sqlite3.Connection,
    tax_id: str,
    *,
    exclude_id: int | None = None,
) -> None:
    if not tax_id:
        return

    sql = """
        SELECT id
        FROM workers
        WHERE tax_id = ?
    """
    params: list[Any] = [tax_id]

    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(int(exclude_id))

    row = conn.execute(
        sql,
        params,
    ).fetchone()

    if row:
        raise ValueError(
            "Ya existe otro trabajador con ese DNI, NIE o documento"
        )


def _next_worker_code(
    worker_id: int,
) -> str:
    return f"TRB-{int(worker_id):06d}"


def list_workers(
    *,
    search: str = "",
    status: str = "ACTIVE",
    department: str = "ALL",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    ensure_schema(db_path)

    clauses = []
    params: list[Any] = []

    status = _text(status).upper()
    department = _text(department)

    if status == "ACTIVE":
        clauses.append(
            "COALESCE(w.active, 1) = 1"
        )
    elif status == "INACTIVE":
        clauses.append(
            "COALESCE(w.active, 1) = 0"
        )
    elif status not in {"", "ALL"}:
        clauses.append(
            "w.employment_status = ?"
        )
        params.append(status)

    if department and department != "ALL":
        clauses.append(
            "w.department = ?"
        )
        params.append(department)

    search = _text(search)

    if search:
        like = f"%{search}%"
        clauses.append(
            """
            (
                w.worker_code LIKE ?
                OR w.first_name LIKE ?
                OR w.last_name_1 LIKE ?
                OR w.last_name_2 LIKE ?
                OR w.tax_id LIKE ?
                OR w.social_security_number LIKE ?
                OR w.phone LIKE ?
                OR w.email LIKE ?
                OR w.position LIKE ?
                OR w.department LIKE ?
            )
            """
        )
        params.extend([like] * 10)

    where = (
        "WHERE " + " AND ".join(clauses)
        if clauses
        else ""
    )

    sql = f"""
        SELECT
            w.*,
            (
                SELECT COUNT(*)
                FROM worker_contracts c
                WHERE c.worker_id = w.id
                  AND COALESCE(c.active, 1) = 1
            ) AS active_contracts_count
        FROM workers w
        {where}
        ORDER BY
            COALESCE(w.active, 1) DESC,
            w.first_name COLLATE NOCASE,
            w.last_name_1 COLLATE NOCASE,
            w.id DESC
    """

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def get_worker(
    worker_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    ensure_schema(db_path)

    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM workers
            WHERE id = ?
            """,
            (int(worker_id),),
        ).fetchone()

    return _row_to_dict(row)


def create_worker(
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    ensure_schema(db_path)
    normalized = _normalize_data(data)

    fields = list(WORKER_FIELDS)
    placeholders = ", ".join(
        "?"
        for _ in fields
    )

    with closing(_connect(db_path)) as conn:
        _check_duplicate_tax_id(
            conn,
            normalized["tax_id"],
        )

        cursor = conn.execute(
            f"""
            INSERT INTO workers (
                {", ".join(fields)}
            )
            VALUES ({placeholders})
            """,
            [
                normalized[field]
                for field in fields
            ],
        )

        worker_id = int(
            cursor.lastrowid
        )

        worker_code = _next_worker_code(
            worker_id
        )

        conn.execute(
            """
            UPDATE workers
            SET worker_code = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                worker_code,
                worker_id,
            ),
        )

        conn.commit()

    return worker_id


def update_worker(
    worker_id: int,
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    ensure_schema(db_path)
    worker_id = int(worker_id)
    normalized = _normalize_data(data)

    fields = list(WORKER_FIELDS)
    assignments = ", ".join(
        f"{field} = ?"
        for field in fields
    )

    with closing(_connect(db_path)) as conn:
        current = conn.execute(
            """
            SELECT id
            FROM workers
            WHERE id = ?
            """,
            (worker_id,),
        ).fetchone()

        if not current:
            raise ValueError(
                "Trabajador no encontrado"
            )

        _check_duplicate_tax_id(
            conn,
            normalized["tax_id"],
            exclude_id=worker_id,
        )

        conn.execute(
            f"""
            UPDATE workers
            SET {assignments},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [
                normalized[field]
                for field in fields
            ]
            + [worker_id],
        )

        conn.commit()

    return True


def set_worker_active(
    worker_id: int,
    active: bool,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    ensure_schema(db_path)

    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE workers
            SET active = ?,
                employment_status = CASE
                    WHEN ? = 1
                    THEN 'ACTIVE'
                    ELSE 'TERMINATED'
                END,
                termination_date = CASE
                    WHEN ? = 1
                    THEN NULL
                    ELSE COALESCE(
                        termination_date,
                        DATE('now')
                    )
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                1 if active else 0,
                1 if active else 0,
                1 if active else 0,
                int(worker_id),
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "Trabajador no encontrado"
            )

        conn.commit()

    return True


def worker_metrics(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, int]:
    ensure_schema(db_path)

    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(
                    CASE
                        WHEN COALESCE(active, 1) = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS active,
                SUM(
                    CASE
                        WHEN COALESCE(active, 1) = 0
                        THEN 1
                        ELSE 0
                    END
                ) AS inactive,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(department),
                        ''
                    )
                ) AS departments
            FROM workers
            """
        ).fetchone()

    return {
        "total": int(row["total"] or 0),
        "active": int(row["active"] or 0),
        "inactive": int(
            row["inactive"] or 0
        ),
        "departments": int(
            row["departments"] or 0
        ),
    }


def worker_departments(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    ensure_schema(db_path)

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT TRIM(department)
            AS department
            FROM workers
            WHERE TRIM(
                COALESCE(department, '')
            ) <> ''
            ORDER BY department COLLATE NOCASE
            """
        ).fetchall()

    return [
        str(row["department"])
        for row in rows
    ]
