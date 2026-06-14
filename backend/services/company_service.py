from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "database" / "quesada.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "companies_schema.sql"

COMPANY_FIELDS = [
    "entity_type", "name", "trade_name", "document_type", "tax_id", "codigo_cuenta_cotizacion",
    "first_name", "last_name_1", "last_name_2", "company_type",
    "cnae_code", "cnae_description", "main_activity", "phone", "email",
    "website", "address", "tipo_via", "nombre_via", "numero", "piso",
    "puerta", "escalera", "postal_code", "city", "province", "country", "notes",
]

REPRESENTATIVE_FIELDS = ["full_name", "document_type", "document_number", "position", "phone", "email", "notes"]
VALID_ENTITY_TYPES = {"juridica", "autonomo", "persona_fisica"}


def _table_columns(conn, table_name):
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
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
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"No existe el schema de empresas: {SCHEMA_PATH}")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _ensure_column(conn, "companies", "codigo_cuenta_cotizacion", "TEXT")
    if own:
        conn.commit()
        conn.close()


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


def _normalize_company_data(data):
    data = data or {}
    normalized = {field: _clean(data.get(field)) for field in COMPANY_FIELDS}
    normalized["entity_type"] = normalized.get("entity_type") or "juridica"
    if normalized["entity_type"] not in VALID_ENTITY_TYPES:
        normalized["entity_type"] = "juridica"
    normalized["country"] = normalized.get("country") or "España"
    if not normalized["name"]:
        parts = [normalized.get("first_name"), normalized.get("last_name_1"), normalized.get("last_name_2")]
        normalized["name"] = " ".join(p for p in parts if p).strip()
    if not normalized["name"]:
        raise ValueError("El nombre o razón social de la entidad es obligatorio")
    return normalized


def _normalize_representative_data(data):
    data = data or {}
    normalized = {field: _clean(data.get(field)) for field in REPRESENTATIVE_FIELDS}
    if not normalized["full_name"]:
        raise ValueError("El nombre del representante de empresa es obligatorio")
    return normalized


def list_companies(search=None, entity_type=None, limit=200):
    where, params = [], []
    if search:
        like = f"%{str(search).strip()}%"
        where.append("(name LIKE ? OR trade_name LIKE ? OR tax_id LIKE ? OR codigo_cuenta_cotizacion LIKE ? OR main_activity LIKE ?)")
        params.extend([like, like, like, like, like])
    if entity_type:
        where.append("entity_type = ?")
        params.append(str(entity_type).strip())
    sql = "SELECT * FROM companies"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY name COLLATE NOCASE ASC LIMIT ?"
    params.append(int(limit or 200))
    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_company(company_id):
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone())


def create_company(data):
    values = _normalize_company_data(data)
    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO companies ({', '.join(fields)}) VALUES ({placeholders})",
            [values[f] for f in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_company(new_id)


def update_company(company_id, data):
    current = get_company(company_id)
    if not current:
        raise ValueError("Empresa no encontrada")
    values = _normalize_company_data({**current, **(data or {})})
    assignments = ", ".join(f"{field} = ?" for field in values.keys())
    with _connect() as conn:
        conn.execute(
            f"UPDATE companies SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [values[f] for f in values.keys()] + [company_id],
        )
        conn.commit()
    return get_company(company_id)


def delete_company(company_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        conn.commit()
        return cur.rowcount > 0


def list_company_representatives(company_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM company_representatives WHERE company_id = ? ORDER BY full_name COLLATE NOCASE ASC",
            (company_id,),
        ).fetchall()
        return [_dict(row) for row in rows]


def get_company_representative(representative_id):
    with _connect() as conn:
        return _dict(conn.execute("SELECT * FROM company_representatives WHERE id = ?", (representative_id,)).fetchone())


def create_company_representative(company_id, data):
    if not get_company(company_id):
        raise ValueError("Empresa no encontrada")
    values = _normalize_representative_data(data)
    values["company_id"] = int(company_id)
    fields = list(values.keys())
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO company_representatives ({', '.join(fields)}) VALUES ({placeholders})",
            [values[f] for f in fields],
        )
        conn.commit()
        new_id = cur.lastrowid
    return get_company_representative(new_id)


def update_company_representative(representative_id, data):
    current = get_company_representative(representative_id)
    if not current:
        raise ValueError("Representante de empresa no encontrado")
    values = _normalize_representative_data({**current, **(data or {})})
    assignments = ", ".join(f"{field} = ?" for field in values.keys())
    with _connect() as conn:
        conn.execute(
            f"UPDATE company_representatives SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [values[f] for f in values.keys()] + [representative_id],
        )
        conn.commit()
    return get_company_representative(representative_id)


def delete_company_representative(representative_id):
    with _connect() as conn:
        cur = conn.execute("DELETE FROM company_representatives WHERE id = ?", (representative_id,))
        conn.commit()
        return cur.rowcount > 0
