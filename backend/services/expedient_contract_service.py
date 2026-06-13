from pathlib import Path
import sqlite3

from backend.services import company_service

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "database" / "quesada.db"

CONTRACT_FIELDS = [
    "expedient_id", "client_company_id", "is_primary", "contract_type",
    "contract_position", "contract_cno_code", "contract_cno_description",
    "contract_start_date", "contract_end_date", "contract_hours",
    "salary_amount", "salary_period", "work_center_address",
    "work_center_tipo_via", "work_center_nombre_via", "work_center_numero",
    "work_center_piso", "work_center_puerta", "work_center_escalera",
    "work_center_postal_code", "work_center_city", "work_center_province",
    "box_contract_path", "notes",
]


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
    values = {field: _clean(data.get(field)) for field in CONTRACT_FIELDS}
    values["expedient_id"] = int(data.get("expedient_id") or 0)
    values["client_company_id"] = int(data.get("client_company_id") or 0)
    values["is_primary"] = 1 if str(data.get("is_primary", "1")).lower() not in {"0", "false", "no"} else 0
    if not values["expedient_id"]:
        raise ValueError("expedient_id es obligatorio")
    if not values["client_company_id"]:
        raise ValueError("client_company_id es obligatorio")
    return values


def list_expedient_contracts(expedient_id):
    sql = """
        SELECT ec.*, cc.client_id, cc.company_id, cc.representative_id,
               c.name AS company_name, c.tax_id AS company_tax_id, c.entity_type,
               c.cnae_code, c.cnae_description, c.main_activity,
               cr.full_name AS representative_name, cr.document_number AS representative_document,
               cr.position AS representative_position
        FROM expedient_contracts ec
        JOIN client_companies cc ON cc.id = ec.client_company_id
        JOIN companies c ON c.id = cc.company_id
        LEFT JOIN company_representatives cr ON cr.id = cc.representative_id
        WHERE ec.expedient_id = ?
        ORDER BY ec.is_primary DESC, ec.id DESC
    """
    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, (expedient_id,)).fetchall()]


def get_expedient_contract(contract_id):
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM expedient_contracts WHERE id = ?", (contract_id,)).fetchone())


def get_primary_contract(expedient_id):
    contracts = list_expedient_contracts(expedient_id)
    return contracts[0] if contracts else None


def create_expedient_contract(expedient_id, client_company_id, data=None):
    values = _normalize({**(data or {}), "expedient_id": expedient_id, "client_company_id": client_company_id})
    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        if values.get("is_primary"):
            conn.execute("UPDATE expedient_contracts SET is_primary = 0 WHERE expedient_id = ?", (expedient_id,))
        cur = conn.execute(
            f"INSERT INTO expedient_contracts ({', '.join(fields)}) VALUES ({placeholders})",
            [values[f] for f in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_expedient_contract(new_id)


def update_expedient_contract(contract_id, data):
    current = get_expedient_contract(contract_id)
    if not current:
        raise ValueError("Contrato de expediente no encontrado")
    values = _normalize({**current, **(data or {})})
    assignments = ", ".join(f"{field} = ?" for field in values.keys())
    with _connect() as conn:
        if values.get("is_primary"):
            conn.execute(
                "UPDATE expedient_contracts SET is_primary = 0 WHERE expedient_id = ? AND id <> ?",
                (values["expedient_id"], contract_id),
            )
        conn.execute(
            f"UPDATE expedient_contracts SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [values[f] for f in values.keys()] + [contract_id],
        )
        conn.commit()
    return get_expedient_contract(contract_id)


def delete_expedient_contract(contract_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM expedient_contracts WHERE id = ?", (contract_id,))
        conn.commit()
        return cur.rowcount > 0
