from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("database/quesada.db")


SUPPLIER_FIELDS = (
    "entity_type",
    "supplier_type",
    "legal_name",
    "trade_name",
    "document_type",
    "tax_id",
    "first_name",
    "last_name_1",
    "last_name_2",
    "category",
    "subcategory",
    "services_description",
    "phone",
    "secondary_phone",
    "email",
    "website",
    "contact_person",
    "contact_position",
    "address",
    "postal_code",
    "city",
    "province",
    "country",
    "usual_payment_method",
    "payment_terms_days",
    "iban",
    "usual_vat_rate",
    "usual_irpf_rate",
    "issues_invoice",
    "usual_document_type",
    "recurring",
    "preferred",
    "customer_reference",
    "contract_reference",
    "external_reference",
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


def ensure_schema(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    migration = Path(
        "database/migrations/"
        "20260714_create_suppliers.sql"
    )

    if migration.exists():
        sql = migration.read_text(
            encoding="utf-8"
        )
    else:
        raise RuntimeError(
            "No se encuentra la migración de proveedores"
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


def _normalize_tax_id(value: Any) -> str:
    return (
        _text(value)
        .upper()
        .replace(" ", "")
        .replace("-", "")
    )


def _normalize_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        field: data.get(field)
        for field in SUPPLIER_FIELDS
    }

    normalized["entity_type"] = (
        _text(
            normalized.get("entity_type")
            or "COMPANY"
        ).upper()
    )

    normalized["supplier_type"] = (
        _text(
            normalized.get("supplier_type")
            or "OTHER"
        ).upper()
    )

    normalized["legal_name"] = _text(
        normalized.get("legal_name")
    )

    normalized["trade_name"] = _text(
        normalized.get("trade_name")
    )

    normalized["document_type"] = (
        _text(
            normalized.get("document_type")
        ).upper()
    )

    normalized["tax_id"] = _normalize_tax_id(
        normalized.get("tax_id")
    )

    for field in (
        "first_name",
        "last_name_1",
        "last_name_2",
        "category",
        "subcategory",
        "services_description",
        "phone",
        "secondary_phone",
        "email",
        "website",
        "contact_person",
        "contact_position",
        "address",
        "postal_code",
        "city",
        "province",
        "country",
        "usual_payment_method",
        "iban",
        "usual_document_type",
        "customer_reference",
        "contract_reference",
        "external_reference",
        "notes",
    ):
        normalized[field] = _text(
            normalized.get(field)
        )

    normalized["country"] = (
        normalized.get("country") or "España"
    )

    normalized["usual_document_type"] = (
        normalized.get("usual_document_type")
        or "INVOICE"
    ).upper()

    normalized["payment_terms_days"] = max(
        0,
        _integer(
            normalized.get("payment_terms_days")
        ),
    )

    normalized["usual_vat_rate"] = max(
        0,
        _float(
            normalized.get("usual_vat_rate"),
            21,
        ),
    )

    normalized["usual_irpf_rate"] = max(
        0,
        _float(
            normalized.get("usual_irpf_rate"),
            0,
        ),
    )

    for field in (
        "issues_invoice",
        "recurring",
        "preferred",
        "active",
    ):
        value = normalized.get(field)

        if value is None:
            value = 1 if field in {
                "issues_invoice",
                "active",
            } else 0

        normalized[field] = _bool_int(value)

    return normalized


def _check_duplicate_tax_id(
    conn: sqlite3.Connection,
    tax_id: str,
    *,
    exclude_id: int | None = None,
) -> None:
    tax_id = _normalize_tax_id(tax_id)

    if not tax_id:
        return

    sql = """
        SELECT id, legal_name
        FROM suppliers
        WHERE REPLACE(
            REPLACE(
                UPPER(COALESCE(tax_id, '')),
                ' ',
                ''
            ),
            '-',
            ''
        ) = ?
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
            "Ya existe un proveedor con este "
            f"NIF/CIF: {row['legal_name']}"
        )


def list_suppliers(
    *,
    search: str | None = None,
    active: bool | None = None,
    category: str | None = None,
    supplier_type: str | None = None,
    preferred: bool | None = None,
    limit: int = 2000,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    ensure_schema(db_path)

    clauses = []
    params: list[Any] = []

    search = _text(search)

    if search:
        tokens = [
            token
            for token in search.lower().split()
            if token
        ]

        for token in tokens:
            clauses.append(
                """
                LOWER(
                    COALESCE(legal_name, '') || ' ' ||
                    COALESCE(trade_name, '') || ' ' ||
                    COALESCE(tax_id, '') || ' ' ||
                    COALESCE(category, '') || ' ' ||
                    COALESCE(subcategory, '') || ' ' ||
                    COALESCE(services_description, '') || ' ' ||
                    COALESCE(phone, '') || ' ' ||
                    COALESCE(email, '') || ' ' ||
                    COALESCE(city, '') || ' ' ||
                    COALESCE(province, '') || ' ' ||
                    COALESCE(customer_reference, '') || ' ' ||
                    COALESCE(contract_reference, '')
                ) LIKE ?
                """
            )
            params.append(f"%{token}%")

    if active is not None:
        clauses.append("active = ?")
        params.append(1 if active else 0)

    if _text(category):
        clauses.append("category = ?")
        params.append(_text(category))

    if _text(supplier_type):
        clauses.append("supplier_type = ?")
        params.append(
            _text(supplier_type).upper()
        )

    if preferred is not None:
        clauses.append("preferred = ?")
        params.append(1 if preferred else 0)

    where = (
        "WHERE " + " AND ".join(clauses)
        if clauses
        else ""
    )

    params.append(max(1, int(limit)))

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM suppliers
            {where}
            ORDER BY
                active DESC,
                preferred DESC,
                recurring DESC,
                legal_name COLLATE NOCASE ASC,
                id ASC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def get_supplier(
    supplier_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    ensure_schema(db_path)

    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM suppliers
            WHERE id = ?
            """,
            (int(supplier_id),),
        ).fetchone()

    return dict(row) if row else None


def create_supplier(
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)
    normalized = _normalize_data(data)

    if not normalized["legal_name"]:
        raise ValueError(
            "La razón social o nombre es obligatorio"
        )

    fields = list(SUPPLIER_FIELDS)
    placeholders = ", ".join(
        "?" for _ in fields
    )

    with closing(_connect(db_path)) as conn:
        _check_duplicate_tax_id(
            conn,
            normalized["tax_id"],
        )

        cursor = conn.execute(
            f"""
            INSERT INTO suppliers (
                {", ".join(fields)}
            )
            VALUES ({placeholders})
            """,
            [
                normalized[field]
                for field in fields
            ],
        )

        supplier_id = int(cursor.lastrowid)
        supplier_code = (
            f"PRV-{supplier_id:06d}"
        )

        conn.execute(
            """
            UPDATE suppliers
            SET supplier_code = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                supplier_code,
                supplier_id,
            ),
        )

        conn.commit()

    result = get_supplier(
        supplier_id,
        db_path=db_path,
    )

    if not result:
        raise RuntimeError(
            "No se pudo recuperar el proveedor creado"
        )

    return result


def update_supplier(
    supplier_id: int,
    data: dict[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    current = get_supplier(
        supplier_id,
        db_path=db_path,
    )

    if not current:
        raise ValueError(
            "El proveedor no existe"
        )

    merged = {
        **current,
        **data,
    }
    normalized = _normalize_data(merged)

    if not normalized["legal_name"]:
        raise ValueError(
            "La razón social o nombre es obligatorio"
        )

    assignments = ", ".join(
        f"{field} = ?"
        for field in SUPPLIER_FIELDS
    )

    with closing(_connect(db_path)) as conn:
        _check_duplicate_tax_id(
            conn,
            normalized["tax_id"],
            exclude_id=int(supplier_id),
        )

        conn.execute(
            f"""
            UPDATE suppliers
            SET {assignments},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [
                normalized[field]
                for field in SUPPLIER_FIELDS
            ]
            + [int(supplier_id)],
        )

        conn.commit()

    result = get_supplier(
        supplier_id,
        db_path=db_path,
    )

    if not result:
        raise RuntimeError(
            "No se pudo recuperar el proveedor actualizado"
        )

    return result


def set_supplier_active(
    supplier_id: int,
    active: bool,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    ensure_schema(db_path)

    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE suppliers
            SET active = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                1 if active else 0,
                int(supplier_id),
            ),
        )

        if cursor.rowcount <= 0:
            raise ValueError(
                "El proveedor no existe"
            )

        conn.commit()

    result = get_supplier(
        supplier_id,
        db_path=db_path,
    )

    if not result:
        raise RuntimeError(
            "No se pudo recuperar el proveedor"
        )

    return result


def supplier_metrics(
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
                    CASE WHEN active = 1
                    THEN 1 ELSE 0 END
                ) AS active,
                SUM(
                    CASE WHEN active = 0
                    THEN 1 ELSE 0 END
                ) AS inactive,
                SUM(
                    CASE WHEN preferred = 1
                    THEN 1 ELSE 0 END
                ) AS preferred,
                SUM(
                    CASE WHEN recurring = 1
                    THEN 1 ELSE 0 END
                ) AS recurring
            FROM suppliers
            """
        ).fetchone()

    return {
        "total": int(row["total"] or 0),
        "active": int(row["active"] or 0),
        "inactive": int(row["inactive"] or 0),
        "preferred": int(
            row["preferred"] or 0
        ),
        "recurring": int(
            row["recurring"] or 0
        ),
    }


def supplier_categories(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[str]:
    ensure_schema(db_path)

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT category
            FROM suppliers
            WHERE TRIM(
                COALESCE(category, '')
            ) <> ''
            ORDER BY category COLLATE NOCASE
            """
        ).fetchall()

    return [
        str(row["category"])
        for row in rows
    ]
