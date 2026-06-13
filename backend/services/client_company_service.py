from pathlib import Path
import sqlite3

from backend.services import company_service

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "database" / "quesada.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    company_service.ensure_schema(conn)
    return conn


def _dict(row):
    return dict(row) if row is not None else None


def _clean(value):
    return str(value).strip() if value is not None else ""


def _normalize(data):
    data = data or {}
    values = {
        "client_id": int(data.get("client_id") or 0),
        "company_id": int(data.get("company_id") or 0),
        "representative_id": data.get("representative_id") or None,
        "relationship_type": _clean(data.get("relationship_type")) or "empleador",
        "start_date": _clean(data.get("start_date")),
        "end_date": _clean(data.get("end_date")),
        "is_active": 1 if str(data.get("is_active", "1")).lower() not in {"0", "false", "no"} else 0,
        "notes": _clean(data.get("notes")),
    }
    if not values["client_id"]:
        raise ValueError("client_id es obligatorio")
    if not values["company_id"]:
        raise ValueError("company_id es obligatorio")
    if values["representative_id"] in {"", 0, "0"}:
        values["representative_id"] = None
    return values


def list_client_companies(client_id, active_only=False):
    sql = """
        SELECT cc.*, c.name AS company_name, c.tax_id AS company_tax_id, c.entity_type,
               c.cnae_code, c.cnae_description, c.main_activity,
               cr.full_name AS representative_name, cr.document_number AS representative_document
        FROM client_companies cc
        JOIN companies c ON c.id = cc.company_id
        LEFT JOIN company_representatives cr ON cr.id = cc.representative_id
        WHERE cc.client_id = ?
    """
    params = [client_id]
    if active_only:
        sql += " AND cc.is_active = 1"
    sql += " ORDER BY cc.is_active DESC, c.name COLLATE NOCASE ASC"
    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_client_company(client_company_id):
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM client_companies WHERE id = ?", (client_company_id,)).fetchone())


def link_company_to_client(client_id, company_id, data=None):
    values = _normalize({**(data or {}), "client_id": client_id, "company_id": company_id})
    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO client_companies ({', '.join(fields)}) VALUES ({placeholders})",
            [values[f] for f in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_client_company(new_id)


def update_client_company(client_company_id, data):
    current = get_client_company(client_company_id)
    if not current:
        raise ValueError("Relación cliente-empresa no encontrada")
    values = _normalize({**current, **(data or {})})
    assignments = ", ".join(f"{field} = ?" for field in values.keys())
    with _connect() as conn:
        conn.execute(
            f"UPDATE client_companies SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [values[f] for f in values.keys()] + [client_company_id],
        )
        conn.commit()
    return get_client_company(client_company_id)


def unlink_company_from_client(client_company_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM client_companies WHERE id = ?", (client_company_id,))
        conn.commit()
        return cur.rowcount > 0
