from pathlib import Path
import sqlite3

from backend.services import company_service

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "database" / "quesada.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "company_fiscal_schema.sql"

FISCAL_YEAR_FIELDS = [
    "company_id", "fiscal_year", "accounting_close_date", "net_revenue",
    "operating_result", "profit_before_tax", "profit_after_tax", "equity",
    "assets_total", "liabilities_total", "average_employees",
    "source_document_id", "verified", "notes",
]

TAX_DOCUMENT_FIELDS = [
    "company_id", "fiscal_year", "period", "document_type", "model_number",
    "document_date", "filing_date", "valid_until", "box_path", "file_name",
    "file_hash", "status", "verified", "notes",
]

FINANCIAL_METRIC_FIELDS = [
    "company_id", "fiscal_year", "tax_document_id", "metric_key",
    "metric_label", "metric_value", "metric_unit", "source_page",
    "confidence", "reviewed", "notes",
]

EXPEDIENT_DOCUMENT_FIELDS = [
    "expedient_id", "company_id", "tax_document_id", "contract_id",
    "usage_type", "required_for", "notes",
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


def _dict(row):
    return dict(row) if row is not None else None


def _clean(value):
    return str(value).strip() if value is not None else ""


def _to_int_or_none(value):
    if value in (None, "", 0, "0"):
        return None
    return int(value)


def _to_year(value):
    if value in (None, ""):
        return None
    return int(value)


def _to_bool_int(value, default=0):
    if value is None:
        return int(default)
    return 0 if str(value).strip().lower() in {"0", "false", "no", "n"} else 1


def ensure_schema(conn=None):
    """Asegura el schema fiscal/económico de empresas.

    Se apoya en company_service.ensure_schema para garantizar que existen
    companies, company_representatives, client_companies y expedient_contracts.
    """
    if conn is not None:
        company_service.ensure_schema(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        return

    with sqlite3.connect(DB_PATH) as local_conn:
        local_conn.execute("PRAGMA foreign_keys = ON")
        company_service.ensure_schema(local_conn)
        local_conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        local_conn.commit()


def _normalize_fiscal_year(company_id, fiscal_year, data=None):
    data = data or {}
    values = {field: _clean(data.get(field)) for field in FISCAL_YEAR_FIELDS}
    values["company_id"] = int(company_id or data.get("company_id") or 0)
    values["fiscal_year"] = int(fiscal_year or data.get("fiscal_year") or 0)
    values["source_document_id"] = _to_int_or_none(data.get("source_document_id"))
    values["verified"] = _to_bool_int(data.get("verified"), default=0)
    if not values["company_id"]:
        raise ValueError("company_id es obligatorio")
    if not values["fiscal_year"]:
        raise ValueError("fiscal_year es obligatorio")
    return values


def list_fiscal_years(company_id):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT fy.*, d.document_type AS source_document_type, d.file_name AS source_file_name
            FROM company_fiscal_years fy
            LEFT JOIN company_tax_documents d ON d.id = fy.source_document_id
            WHERE fy.company_id = ?
            ORDER BY fy.fiscal_year DESC
            """,
            (int(company_id),),
        ).fetchall()
        return [_dict(row) for row in rows]


def get_fiscal_year(company_id, fiscal_year):
    with _connect() as conn:
        return _dict(conn.execute(
            "SELECT * FROM company_fiscal_years WHERE company_id = ? AND fiscal_year = ?",
            (int(company_id), int(fiscal_year)),
        ).fetchone())


def upsert_fiscal_year(company_id, fiscal_year, data=None):
    values = _normalize_fiscal_year(company_id, fiscal_year, data)
    existing = get_fiscal_year(values["company_id"], values["fiscal_year"])
    fields = list(values.keys())

    with _connect() as conn:
        if existing:
            assignments = ", ".join(f"{field} = ?" for field in fields)
            conn.execute(
                f"UPDATE company_fiscal_years SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [values[field] for field in fields] + [existing["id"]],
            )
            new_id = existing["id"]
        else:
            placeholders = ", ".join("?" for _ in fields)
            cur = conn.execute(
                f"INSERT INTO company_fiscal_years ({', '.join(fields)}) VALUES ({placeholders})",
                [values[field] for field in fields],
            )
            new_id = cur.lastrowid
        conn.commit()

    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM company_fiscal_years WHERE id = ?", (new_id,)).fetchone())


def delete_fiscal_year(company_id, fiscal_year):
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM company_fiscal_years WHERE company_id = ? AND fiscal_year = ?",
            (int(company_id), int(fiscal_year)),
        )
        conn.commit()
        return cur.rowcount > 0


def _normalize_tax_document(company_id, data=None):
    data = data or {}
    values = {field: _clean(data.get(field)) for field in TAX_DOCUMENT_FIELDS}
    values["company_id"] = int(company_id or data.get("company_id") or 0)
    values["fiscal_year"] = _to_year(data.get("fiscal_year"))
    values["document_type"] = _clean(data.get("document_type"))
    values["status"] = _clean(data.get("status")) or "pendiente"
    values["verified"] = _to_bool_int(data.get("verified"), default=0)
    if not values["company_id"]:
        raise ValueError("company_id es obligatorio")
    if not values["document_type"]:
        raise ValueError("document_type es obligatorio")
    return values


def list_tax_documents(company_id, fiscal_year=None, document_type=None):
    sql = "SELECT * FROM company_tax_documents WHERE company_id = ?"
    params = [int(company_id)]
    if fiscal_year not in (None, ""):
        sql += " AND fiscal_year = ?"
        params.append(int(fiscal_year))
    if document_type:
        sql += " AND document_type = ?"
        params.append(str(document_type))
    sql += " ORDER BY COALESCE(fiscal_year, 0) DESC, document_date DESC, id DESC"
    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_tax_document(document_id):
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM company_tax_documents WHERE id = ?", (int(document_id),)).fetchone())


def create_tax_document(company_id, data=None):
    values = _normalize_tax_document(company_id, data)
    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO company_tax_documents ({', '.join(fields)}) VALUES ({placeholders})",
            [values[field] for field in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_tax_document(new_id)


def update_tax_document(document_id, data):
    current = get_tax_document(document_id)
    if not current:
        raise ValueError("Documento fiscal no encontrado")
    values = _normalize_tax_document(current["company_id"], {**current, **(data or {})})
    fields = list(values.keys())
    assignments = ", ".join(f"{field} = ?" for field in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE company_tax_documents SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [values[field] for field in fields] + [int(document_id)],
        )
        conn.commit()
    return get_tax_document(document_id)


def delete_tax_document(document_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM company_tax_documents WHERE id = ?", (int(document_id),))
        conn.commit()
        return cur.rowcount > 0


def _normalize_metric(company_id, data=None):
    data = data or {}
    values = {field: _clean(data.get(field)) for field in FINANCIAL_METRIC_FIELDS}
    values["company_id"] = int(company_id or data.get("company_id") or 0)
    values["fiscal_year"] = _to_year(data.get("fiscal_year"))
    values["tax_document_id"] = _to_int_or_none(data.get("tax_document_id"))
    values["source_page"] = _to_int_or_none(data.get("source_page"))
    values["confidence"] = None if data.get("confidence") in (None, "") else float(data.get("confidence"))
    values["reviewed"] = _to_bool_int(data.get("reviewed"), default=0)
    values["metric_key"] = _clean(data.get("metric_key"))
    if not values["company_id"]:
        raise ValueError("company_id es obligatorio")
    if not values["metric_key"]:
        raise ValueError("metric_key es obligatorio")
    return values


def list_financial_metrics(company_id, fiscal_year=None, tax_document_id=None):
    sql = "SELECT * FROM company_financial_metrics WHERE company_id = ?"
    params = [int(company_id)]
    if fiscal_year not in (None, ""):
        sql += " AND fiscal_year = ?"
        params.append(int(fiscal_year))
    if tax_document_id not in (None, ""):
        sql += " AND tax_document_id = ?"
        params.append(int(tax_document_id))
    sql += " ORDER BY COALESCE(fiscal_year, 0) DESC, metric_key COLLATE NOCASE ASC, id ASC"
    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, params).fetchall()]


def create_financial_metric(company_id, data=None):
    values = _normalize_metric(company_id, data)
    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO company_financial_metrics ({', '.join(fields)}) VALUES ({placeholders})",
            [values[field] for field in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM company_financial_metrics WHERE id = ?", (new_id,)).fetchone())


def delete_financial_metric(metric_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM company_financial_metrics WHERE id = ?", (int(metric_id),))
        conn.commit()
        return cur.rowcount > 0


def link_tax_document_to_expedient(expedient_id, company_id, tax_document_id, data=None):
    data = data or {}
    values = {
        "expedient_id": int(expedient_id or data.get("expedient_id") or 0),
        "company_id": int(company_id or data.get("company_id") or 0),
        "tax_document_id": int(tax_document_id or data.get("tax_document_id") or 0),
        "contract_id": _to_int_or_none(data.get("contract_id")),
        "usage_type": _clean(data.get("usage_type")) or "fiscal",
        "required_for": _clean(data.get("required_for")),
        "notes": _clean(data.get("notes")),
    }
    if not values["expedient_id"]:
        raise ValueError("expedient_id es obligatorio")
    if not values["company_id"]:
        raise ValueError("company_id es obligatorio")
    if not values["tax_document_id"]:
        raise ValueError("tax_document_id es obligatorio")

    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO expedient_company_documents ({', '.join(fields)}) VALUES ({placeholders})",
            [values[field] for field in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_expedient_company_document(new_id)


def get_expedient_company_document(link_id):
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM expedient_company_documents WHERE id = ?", (int(link_id),)).fetchone())


def list_expedient_company_documents(expedient_id):
    sql = """
        SELECT ecd.*, d.document_type, d.model_number, d.fiscal_year, d.period,
               d.box_path, d.file_name, d.status, d.verified,
               c.name AS company_name, c.tax_id AS company_tax_id
        FROM expedient_company_documents ecd
        JOIN company_tax_documents d ON d.id = ecd.tax_document_id
        JOIN companies c ON c.id = ecd.company_id
        WHERE ecd.expedient_id = ?
        ORDER BY c.name COLLATE NOCASE ASC, COALESCE(d.fiscal_year, 0) DESC, d.id DESC
    """
    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, (int(expedient_id),)).fetchall()]


def unlink_tax_document_from_expedient(link_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM expedient_company_documents WHERE id = ?", (int(link_id),))
        conn.commit()
        return cur.rowcount > 0
