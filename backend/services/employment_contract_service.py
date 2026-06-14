from pathlib import Path
import sqlite3

from backend.services import company_service

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "database" / "quesada.db"

CONTRACT_FIELDS = [
    "client_company_id", "expedient_id", "is_primary",
    "contract_type", "contract_code", "collective_agreement", "collective_agreement_code",
    "contract_position", "contract_cno_code", "contract_cno_description",
    "contract_start_date", "contract_end_date", "contract_hours",
    "salary_amount", "salary_period",
    "work_center_address", "work_center_tipo_via", "work_center_nombre_via",
    "work_center_numero", "work_center_piso", "work_center_puerta", "work_center_escalera",
    "work_center_postal_code", "work_center_city", "work_center_province",
    "box_contract_path", "notes",
]


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


def _dict(row):
    return dict(row) if row is not None else None


def _clean(value):
    return str(value).strip() if value is not None else ""


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows]
    except Exception:
        return []


def _ensure_column(conn, table_name, column_name, definition="TEXT"):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def ensure_schema(conn=None):
    own = conn is None
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    company_service.ensure_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS employment_contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_company_id INTEGER NOT NULL,
            expedient_id INTEGER,
            is_primary INTEGER DEFAULT 1,
            contract_type TEXT,
            contract_code TEXT,
            collective_agreement TEXT,
            collective_agreement_code TEXT,
            contract_position TEXT,
            contract_cno_code TEXT,
            contract_cno_description TEXT,
            contract_start_date TEXT,
            contract_end_date TEXT,
            contract_hours TEXT,
            salary_amount TEXT,
            salary_period TEXT,
            work_center_address TEXT,
            work_center_tipo_via TEXT,
            work_center_nombre_via TEXT,
            work_center_numero TEXT,
            work_center_piso TEXT,
            work_center_puerta TEXT,
            work_center_escalera TEXT,
            work_center_postal_code TEXT,
            work_center_city TEXT,
            work_center_province TEXT,
            box_contract_path TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_company_id) REFERENCES client_companies(id) ON DELETE CASCADE,
            FOREIGN KEY (expedient_id) REFERENCES expedientes(id) ON DELETE SET NULL
        )
        """
    )
    if _table_exists(conn, "expedient_contracts"):
        _ensure_column(conn, "expedient_contracts", "contract_code", "TEXT")
        _ensure_column(conn, "expedient_contracts", "collective_agreement", "TEXT")
        _ensure_column(conn, "expedient_contracts", "collective_agreement_code", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_employment_contracts_client_company_id ON employment_contracts(client_company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_employment_contracts_expedient_id ON employment_contracts(expedient_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_employment_contracts_primary ON employment_contracts(client_company_id, is_primary)")
    if own:
        conn.commit()
        conn.close()


def _normalize_contract_data(data):
    data = data or {}
    normalized = {field: _clean(data.get(field)) for field in CONTRACT_FIELDS}
    normalized["client_company_id"] = int(data.get("client_company_id") or 0)
    if normalized["client_company_id"] <= 0:
        raise ValueError("El contrato debe estar vinculado a una relación cliente-empresa")
    normalized["expedient_id"] = int(data.get("expedient_id") or 0) or None
    normalized["is_primary"] = int(data.get("is_primary", 1) or 0)
    return normalized


def create_contract(client_company_id, data=None):
    payload = dict(data or {})
    payload["client_company_id"] = int(client_company_id)
    values = _normalize_contract_data(payload)
    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        if values.get("is_primary"):
            conn.execute(
                "UPDATE employment_contracts SET is_primary = 0 WHERE client_company_id = ?",
                (values["client_company_id"],),
            )
        cur = conn.execute(
            f"INSERT INTO employment_contracts ({', '.join(fields)}) VALUES ({placeholders})",
            [values[field] for field in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_contract(new_id)


def get_contract(contract_id):
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM employment_contracts WHERE id = ?", (contract_id,)).fetchone())


def list_contracts_by_client_company(client_company_id):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM employment_contracts
            WHERE client_company_id = ?
            ORDER BY is_primary DESC, COALESCE(contract_start_date, created_at) DESC, id DESC
            """,
            (int(client_company_id),),
        ).fetchall()
        return [_dict(row) for row in rows]


def list_contracts_by_client(client_id):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT ec.*, cc.client_id, cc.company_id, c.name AS company_name, c.tax_id AS company_tax_id
            FROM employment_contracts ec
            INNER JOIN client_companies cc ON cc.id = ec.client_company_id
            LEFT JOIN companies c ON c.id = cc.company_id
            WHERE cc.client_id = ?
            ORDER BY ec.is_primary DESC, COALESCE(ec.contract_start_date, ec.created_at) DESC, ec.id DESC
            """,
            (int(client_id),),
        ).fetchall()
        return [_dict(row) for row in rows]


def update_contract(contract_id, data):
    current = get_contract(contract_id)
    if not current:
        raise ValueError("Contrato no encontrado")
    values = _normalize_contract_data({**current, **(data or {})})
    assignments = ", ".join(f"{field} = ?" for field in values.keys())
    with _connect() as conn:
        if values.get("is_primary"):
            conn.execute(
                "UPDATE employment_contracts SET is_primary = 0 WHERE client_company_id = ? AND id != ?",
                (values["client_company_id"], int(contract_id)),
            )
        conn.execute(
            f"UPDATE employment_contracts SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [values[field] for field in values.keys()] + [int(contract_id)],
        )
        conn.commit()
    return get_contract(contract_id)


def delete_contract(contract_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM employment_contracts WHERE id = ?", (int(contract_id),))
        conn.commit()
        return cur.rowcount > 0
