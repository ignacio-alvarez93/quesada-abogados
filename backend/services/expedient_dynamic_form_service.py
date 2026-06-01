import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "database" / "expedient_dynamic_forms_schema.sql"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def _normalize_code(value):
    raw = str(value or "").strip().lower()
    raw = raw.replace(" ", "_").replace("-", "_")
    raw = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
    while "__" in raw:
        raw = raw.replace("__", "_")
    return raw.strip("_")


def initialize_dynamic_forms_schema():
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def parse_field_options(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    raw = str(value).strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return [item.strip() for item in raw.split("|") if item.strip()]


def parse_autocomplete_fill_config(value):
    """
    Interpreta opciones_json para autocompletes con autorrelleno.

    Formato recomendado:
    {
      "source": "contactos_cliente",
      "campos": {
        "nombre": "nombre",
        "primer_apellido": "primer_apellido",
        "nie": "nie"
      }
    }

    Compatibilidad: si recibe un JSON plano {"campo_destino": "campo_origen"},
    se interpreta como campos derivados usando source=contactos_cliente.
    """
    if not value:
        return {}
    if isinstance(value, dict):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}

    if not isinstance(parsed, dict):
        return {}

    if "campos" in parsed or "source" in parsed:
        campos = parsed.get("campos") or {}
        return {
            "source": str(parsed.get("source") or "contactos_cliente").strip(),
            "campos": campos if isinstance(campos, dict) else {},
        }

    return {
        "source": "contactos_cliente",
        "campos": parsed,
    }


def list_autocomplete_source_fields(source="contactos_cliente"):
    """Catálogo orientativo de campos origen disponibles para Settings."""
    source = str(source or "contactos_cliente").strip().lower()

    cliente_fields = [
        "id", "nombre", "primer_apellido", "segundo_apellido", "nombre_completo",
        "nacionalidad", "nie", "pasaporte", "dni", "documento",
        "fecha_nacimiento", "localidad_nacimiento", "pais_nacimiento",
        "nombre_padre", "nombre_madre", "estado_civil", "sexo",
        "telefono", "email", "tipo_via", "nombre_via", "domicilio_espana",
        "localidad", "codigo_postal", "provincia", "numero", "piso",
        "estado_cliente", "origen_cliente", "responsable_interno",
        "observaciones", "observaciones_internas",
    ]

    contacto_fields = [
        "id", "tipo_contacto", "parentesco", "titulo",
        "nombre", "primer_apellido", "segundo_apellido", "nombre_completo",
        "nie", "dni", "pasaporte", "documento", "email", "telefono",
        "nacionalidad", "fecha_nacimiento", "sexo", "observaciones",
    ]

    if source in ("cliente", "cliente_expediente", "clientes", "datos_cliente"):
        return cliente_fields
    if source in ("empleadores_cliente", "empleador", "empleadores"):
        return contacto_fields + ["empresa", "actividad", "cnae", "cno"]
    if source in ("catalogo_cnae", "actividad_cnae"):
        return ["valor", "codigo", "descripcion"]
    if source in ("catalogo_cno", "cno_sepe"):
        return ["valor", "codigo", "descripcion"]
    return contacto_fields


def get_formulario_for_context(tipo_expediente_id=None, subtipo_expediente_id=None):
    initialize_dynamic_forms_schema()

    if not tipo_expediente_id:
        return {"formulario": None, "campos": []}

    with _connect() as conn:
        formulario = None

        if subtipo_expediente_id:
            formulario = _dict(
                conn.execute(
                    """
                    SELECT *
                    FROM config_formularios_expediente
                    WHERE activo = 1
                      AND tipo_expediente_id = ?
                      AND subtipo_expediente_id = ?
                    ORDER BY orden ASC, id DESC
                    LIMIT 1
                    """,
                    (int(tipo_expediente_id), int(subtipo_expediente_id)),
                ).fetchone()
            )

        if not formulario:
            formulario = _dict(
                conn.execute(
                    """
                    SELECT *
                    FROM config_formularios_expediente
                    WHERE activo = 1
                      AND tipo_expediente_id = ?
                      AND subtipo_expediente_id IS NULL
                    ORDER BY orden ASC, id DESC
                    LIMIT 1
                    """,
                    (int(tipo_expediente_id),),
                ).fetchone()
            )

        if not formulario:
            return {"formulario": None, "campos": []}

        campos = [
            _dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM config_campos_formulario_expediente
                WHERE formulario_id = ?
                  AND activo = 1
                ORDER BY orden ASC, id ASC
                """,
                (int(formulario["id"]),),
            ).fetchall()
        ]

    return {"formulario": formulario, "campos": campos}


def load_datos_especificos(expediente_id):
    initialize_dynamic_forms_schema()

    if not expediente_id:
        return {}

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT codigo, valor
            FROM expediente_datos_especificos
            WHERE expediente_id = ?
            """,
            (int(expediente_id),),
        ).fetchall()

    return {row["codigo"]: row["valor"] for row in rows}


def save_datos_especificos(expediente_id, formulario_id, values):
    initialize_dynamic_forms_schema()

    if not expediente_id or not formulario_id:
        return

    values = values or {}

    with _connect() as conn:
        campos = [
            _dict(row)
            for row in conn.execute(
                """
                SELECT id, codigo
                FROM config_campos_formulario_expediente
                WHERE formulario_id = ?
                  AND activo = 1
                """,
                (int(formulario_id),),
            ).fetchall()
        ]

        for campo in campos:
            codigo = campo["codigo"]
            valor = values.get(codigo, "")
            conn.execute(
                """
                INSERT INTO expediente_datos_especificos (
                    expediente_id, formulario_id, campo_id, codigo, valor, updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(expediente_id, campo_id)
                DO UPDATE SET
                    valor = excluded.valor,
                    codigo = excluded.codigo,
                    formulario_id = excluded.formulario_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(expediente_id),
                    int(formulario_id),
                    int(campo["id"]),
                    codigo,
                    str(valor or ""),
                ),
            )

        conn.commit()


def create_formulario(data):
    initialize_dynamic_forms_schema()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_formularios_expediente (
                tipo_expediente_id, subtipo_expediente_id, codigo, nombre,
                descripcion, orden, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(data.get("tipo_expediente_id")),
                data.get("subtipo_expediente_id"),
                _normalize_code(data.get("codigo") or data.get("nombre")).upper(),
                str(data.get("nombre") or "").strip(),
                str(data.get("descripcion") or "").strip(),
                int(data.get("orden") or 0),
                int(data.get("activo", 1)),
            ),
        )
        conn.commit()
        return cur.lastrowid


def create_campo_formulario(formulario_id, data):
    initialize_dynamic_forms_schema()
    opciones = data.get("opciones_json") or data.get("opciones") or ""
    if isinstance(opciones, list):
        opciones = json.dumps(opciones, ensure_ascii=False)

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_campos_formulario_expediente (
                formulario_id, codigo, etiqueta, tipo_campo, obligatorio,
                opciones_json, placeholder, ayuda, valor_defecto, orden, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(formulario_id),
                _normalize_code(data.get("codigo") or data.get("etiqueta")),
                str(data.get("etiqueta") or "").strip(),
                str(data.get("tipo_campo") or "texto").strip().lower(),
                int(data.get("obligatorio", 0)),
                str(opciones or ""),
                str(data.get("placeholder") or ""),
                str(data.get("ayuda") or ""),
                str(data.get("valor_defecto") or ""),
                int(data.get("orden") or 0),
                int(data.get("activo", 1)),
            ),
        )
        conn.commit()
        return cur.lastrowid

def list_formularios(active_only=False):
    initialize_dynamic_forms_schema()

    sql = """
        SELECT
            f.*,
            t.nombre AS tipo_expediente_nombre,
            s.nombre AS subtipo_expediente_nombre
        FROM config_formularios_expediente f
        JOIN config_tipos_expediente t ON t.id = f.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente s ON s.id = f.subtipo_expediente_id
    """
    params = []

    if active_only:
        sql += " WHERE f.activo = 1"

    sql += " ORDER BY t.nombre ASC, COALESCE(s.nombre, '') ASC, f.orden ASC, f.nombre ASC"

    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_formulario(formulario_id):
    initialize_dynamic_forms_schema()
    with _connect() as conn:
        return _dict(
            conn.execute(
                """
                SELECT
                    f.*,
                    t.nombre AS tipo_expediente_nombre,
                    s.nombre AS subtipo_expediente_nombre
                FROM config_formularios_expediente f
                JOIN config_tipos_expediente t ON t.id = f.tipo_expediente_id
                LEFT JOIN config_subtipos_expediente s ON s.id = f.subtipo_expediente_id
                WHERE f.id = ?
                """,
                (int(formulario_id),),
            ).fetchone()
        )


def update_formulario(formulario_id, data):
    initialize_dynamic_forms_schema()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_formularios_expediente
            SET tipo_expediente_id = ?,
                subtipo_expediente_id = ?,
                codigo = ?,
                nombre = ?,
                descripcion = ?,
                orden = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(data.get("tipo_expediente_id")),
                data.get("subtipo_expediente_id"),
                _normalize_code(data.get("codigo") or data.get("nombre")).upper(),
                str(data.get("nombre") or "").strip(),
                str(data.get("descripcion") or "").strip(),
                int(data.get("orden") or 0),
                int(data.get("activo", 1)),
                int(formulario_id),
            ),
        )
        conn.commit()


def delete_formulario(formulario_id):
    initialize_dynamic_forms_schema()
    with _connect() as conn:
        conn.execute("DELETE FROM config_formularios_expediente WHERE id = ?", (int(formulario_id),))
        conn.commit()


def list_campos_formulario(formulario_id=None, active_only=False):
    initialize_dynamic_forms_schema()

    sql = """
        SELECT
            c.*,
            f.nombre AS formulario_nombre,
            f.codigo AS formulario_codigo
        FROM config_campos_formulario_expediente c
        JOIN config_formularios_expediente f ON f.id = c.formulario_id
    """
    params = []
    conditions = []

    if formulario_id:
        conditions.append("c.formulario_id = ?")
        params.append(int(formulario_id))

    if active_only:
        conditions.append("c.activo = 1")

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY f.nombre ASC, c.orden ASC, c.id ASC"

    with _connect() as conn:
        return [_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_campo_formulario(campo_id):
    initialize_dynamic_forms_schema()
    with _connect() as conn:
        return _dict(
            conn.execute(
                "SELECT * FROM config_campos_formulario_expediente WHERE id = ?",
                (int(campo_id),),
            ).fetchone()
        )


def update_campo_formulario(campo_id, data):
    initialize_dynamic_forms_schema()

    opciones = data.get("opciones_json") or data.get("opciones") or ""
    if isinstance(opciones, list):
        opciones = json.dumps(opciones, ensure_ascii=False)

    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_campos_formulario_expediente
            SET formulario_id = ?,
                codigo = ?,
                etiqueta = ?,
                tipo_campo = ?,
                obligatorio = ?,
                opciones_json = ?,
                placeholder = ?,
                ayuda = ?,
                valor_defecto = ?,
                orden = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(data.get("formulario_id")),
                _normalize_code(data.get("codigo") or data.get("etiqueta")),
                str(data.get("etiqueta") or "").strip(),
                str(data.get("tipo_campo") or "texto").strip().lower(),
                int(data.get("obligatorio", 0)),
                str(opciones or ""),
                str(data.get("placeholder") or ""),
                str(data.get("ayuda") or ""),
                str(data.get("valor_defecto") or ""),
                int(data.get("orden") or 0),
                int(data.get("activo", 1)),
                int(campo_id),
            ),
        )
        conn.commit()


def delete_campo_formulario(campo_id):
    initialize_dynamic_forms_schema()
    with _connect() as conn:
        conn.execute("DELETE FROM config_campos_formulario_expediente WHERE id = ?", (int(campo_id),))
        conn.commit()

