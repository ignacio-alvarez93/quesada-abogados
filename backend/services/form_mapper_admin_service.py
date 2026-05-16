import json
import sqlite3
from pathlib import Path

from backend.services import form_mapper_service

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def _normalize_code(value):
    return str(value or "").strip().upper().replace(" ", "_")


def _json_dumps(value, fallback):
    if value in (None, ""):
        value = fallback

    if isinstance(value, str):
        # Validamos que sea JSON correcto.
        json.loads(value)
        return value

    return json.dumps(value, ensure_ascii=False, indent=2)


def _json_loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def initialize_mapper_admin_schema():
    form_mapper_service.initialize_form_mapper_schema()

    blocks_schema = Path(__file__).resolve().parents[2] / "database" / "form_mapper_blocks_schema.sql"
    if blocks_schema.exists():
        with _connect() as conn:
            conn.executescript(blocks_schema.read_text(encoding="utf-8"))
            conn.commit()


def list_mapper_templates(active_only=False):
    initialize_mapper_admin_schema()

    sql = """
        SELECT
            m.*,
            t.nombre AS tipo_expediente_nombre,
            s.nombre AS subtipo_expediente_nombre
        FROM form_mapper_templates m
        LEFT JOIN config_tipos_expediente t ON t.id = m.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente s ON s.id = m.subtipo_expediente_id
    """

    params = []

    if active_only:
        sql += " WHERE m.activo = 1"

    sql += """
        ORDER BY
            m.tipo_destino ASC,
            COALESCE(t.nombre, '') ASC,
            COALESCE(s.nombre, '') ASC,
            m.version DESC,
            m.nombre ASC
    """

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    result = []
    for row in rows:
        item = _dict(row)
        item["mapper"] = _json_loads(item.get("mapper_json"), {})
        item["required_fields"] = _json_loads(item.get("required_fields_json"), [])
        result.append(item)

    return result


def get_mapper_template(template_id):
    initialize_mapper_admin_schema()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                m.*,
                t.nombre AS tipo_expediente_nombre,
                s.nombre AS subtipo_expediente_nombre
            FROM form_mapper_templates m
            LEFT JOIN config_tipos_expediente t ON t.id = m.tipo_expediente_id
            LEFT JOIN config_subtipos_expediente s ON s.id = m.subtipo_expediente_id
            WHERE m.id = ?
            """,
            (int(template_id),),
        ).fetchone()

    item = _dict(row)
    if not item:
        return None

    item["mapper"] = _json_loads(item.get("mapper_json"), {})
    item["required_fields"] = _json_loads(item.get("required_fields_json"), [])

    return item


def create_mapper_template(data):
    initialize_mapper_admin_schema()

    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = str(data.get("nombre") or "").strip()
    tipo_destino = _normalize_code(data.get("tipo_destino"))

    if not codigo:
        raise ValueError("El código del mapper es obligatorio")
    if not nombre:
        raise ValueError("El nombre del mapper es obligatorio")
    if not tipo_destino:
        raise ValueError("El tipo destino es obligatorio")

    mapper_json = _json_dumps(data.get("mapper_json", data.get("mapper")), {})
    required_fields_json = _json_dumps(
        data.get("required_fields_json", data.get("required_fields")),
        [],
    )

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO form_mapper_templates (
                codigo,
                nombre,
                tipo_destino,
                activo,
                tipo_expediente_id,
                subtipo_expediente_id,
                mapper_json,
                required_fields_json,
                version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                codigo,
                nombre,
                tipo_destino,
                int(data.get("activo", 1)),
                data.get("tipo_expediente_id"),
                data.get("subtipo_expediente_id"),
                mapper_json,
                required_fields_json,
                int(data.get("version") or 1),
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_mapper_template(template_id, data):
    initialize_mapper_admin_schema()

    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = str(data.get("nombre") or "").strip()
    tipo_destino = _normalize_code(data.get("tipo_destino"))

    if not codigo:
        raise ValueError("El código del mapper es obligatorio")
    if not nombre:
        raise ValueError("El nombre del mapper es obligatorio")
    if not tipo_destino:
        raise ValueError("El tipo destino es obligatorio")

    mapper_json = _json_dumps(data.get("mapper_json", data.get("mapper")), {})
    required_fields_json = _json_dumps(
        data.get("required_fields_json", data.get("required_fields")),
        [],
    )

    with _connect() as conn:
        conn.execute(
            """
            UPDATE form_mapper_templates
            SET codigo = ?,
                nombre = ?,
                tipo_destino = ?,
                activo = ?,
                tipo_expediente_id = ?,
                subtipo_expediente_id = ?,
                mapper_json = ?,
                required_fields_json = ?,
                version = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                codigo,
                nombre,
                tipo_destino,
                int(data.get("activo", 1)),
                data.get("tipo_expediente_id"),
                data.get("subtipo_expediente_id"),
                mapper_json,
                required_fields_json,
                int(data.get("version") or 1),
                int(template_id),
            ),
        )
        conn.commit()


def delete_mapper_template(template_id):
    initialize_mapper_admin_schema()

    with _connect() as conn:
        conn.execute(
            "DELETE FROM form_mapper_templates WHERE id = ?",
            (int(template_id),),
        )
        conn.commit()


def set_mapper_template_active(template_id, active):
    initialize_mapper_admin_schema()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE form_mapper_templates
            SET activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if active else 0, int(template_id)),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Bloques reutilizables de mapper
# ---------------------------------------------------------------------------

def list_mapper_blocks(active_only=False):
    initialize_mapper_admin_schema()

    sql = "SELECT * FROM form_mapper_blocks"
    params = []

    if active_only:
        sql += " WHERE activo = 1"

    sql += " ORDER BY codigo ASC, version DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    result = []
    for row in rows:
        item = _dict(row)
        item["mapper"] = _json_loads(item.get("mapper_json"), {})
        item["required_fields"] = _json_loads(item.get("required_fields_json"), [])
        result.append(item)

    return result


def get_mapper_block(block_id):
    initialize_mapper_admin_schema()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM form_mapper_blocks
            WHERE id = ?
            """,
            (int(block_id),),
        ).fetchone()

    item = _dict(row)
    if not item:
        return None

    item["mapper"] = _json_loads(item.get("mapper_json"), {})
    item["required_fields"] = _json_loads(item.get("required_fields_json"), [])

    return item


def get_mapper_block_by_code(codigo):
    initialize_mapper_admin_schema()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM form_mapper_blocks
            WHERE codigo = ?
            ORDER BY version DESC, id DESC
            LIMIT 1
            """,
            (_normalize_code(codigo),),
        ).fetchone()

    item = _dict(row)
    if not item:
        return None

    item["mapper"] = _json_loads(item.get("mapper_json"), {})
    item["required_fields"] = _json_loads(item.get("required_fields_json"), [])

    return item


def create_mapper_block(data):
    initialize_mapper_admin_schema()

    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = str(data.get("nombre") or "").strip()
    descripcion = str(data.get("descripcion") or "").strip()

    if not codigo:
        raise ValueError("El código del bloque es obligatorio")
    if not nombre:
        raise ValueError("El nombre del bloque es obligatorio")

    mapper_json = _json_dumps(data.get("mapper_json", data.get("mapper")), {})
    required_fields_json = _json_dumps(
        data.get("required_fields_json", data.get("required_fields")),
        [],
    )

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO form_mapper_blocks (
                codigo,
                nombre,
                descripcion,
                mapper_json,
                required_fields_json,
                activo,
                version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                codigo,
                nombre,
                descripcion,
                mapper_json,
                required_fields_json,
                int(data.get("activo", 1)),
                int(data.get("version") or 1),
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_mapper_block(block_id, data):
    initialize_mapper_admin_schema()

    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = str(data.get("nombre") or "").strip()
    descripcion = str(data.get("descripcion") or "").strip()

    if not codigo:
        raise ValueError("El código del bloque es obligatorio")
    if not nombre:
        raise ValueError("El nombre del bloque es obligatorio")

    mapper_json = _json_dumps(data.get("mapper_json", data.get("mapper")), {})
    required_fields_json = _json_dumps(
        data.get("required_fields_json", data.get("required_fields")),
        [],
    )

    with _connect() as conn:
        conn.execute(
            """
            UPDATE form_mapper_blocks
            SET codigo = ?,
                nombre = ?,
                descripcion = ?,
                mapper_json = ?,
                required_fields_json = ?,
                activo = ?,
                version = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                codigo,
                nombre,
                descripcion,
                mapper_json,
                required_fields_json,
                int(data.get("activo", 1)),
                int(data.get("version") or 1),
                int(block_id),
            ),
        )
        conn.commit()


def delete_mapper_block(block_id):
    initialize_mapper_admin_schema()

    with _connect() as conn:
        conn.execute(
            "DELETE FROM form_mapper_blocks WHERE id = ?",
            (int(block_id),),
        )
        conn.commit()


def set_mapper_block_active(block_id, active):
    initialize_mapper_admin_schema()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE form_mapper_blocks
            SET activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if active else 0, int(block_id)),
        )
        conn.commit()


def build_mapper_from_blocks(block_codes):
    """
    Compone un mapper final a partir de bloques reutilizables.

    Regla:
    - Si dos bloques definen el mismo campo destino, gana el último bloque.
    - Los required_fields se unen sin duplicados.
    """
    initialize_mapper_admin_schema()

    mapper = {}
    required_fields = []

    for code in block_codes or []:
        block = get_mapper_block_by_code(code)
        if not block:
            raise ValueError(f"Bloque mapper no encontrado: {code}")

        mapper.update(block.get("mapper") or {})

        for field in block.get("required_fields") or []:
            if field not in required_fields:
                required_fields.append(field)

    return {
        "mapper": mapper,
        "required_fields": required_fields,
    }
