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
    Parsea la configuración JSON de autocompletado/auto-relleno de un campo dinámico.

    Compatibilidad quirúrgica:
    - expedients_view.py ya llama a esta función.
    - Si opciones_json contiene un dict JSON, se devuelve ese dict.
    - Si contiene una lista de opciones clásica o texto simple, devuelve {}.
    - Nunca lanza excepción hacia la vista.
    """
    if not value:
        return {}
    if isinstance(value, dict):
        return value

    raw = str(value or "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except Exception:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _is_contact_autocomplete_type(tipo):
    tipo = str(tipo or "").strip().lower()
    return tipo in (
        "contacto_cliente",
        "autocomplete_familiar",
        "empleador_empresa",
        "autocomplete_empleador",
        "representante_legal",
        "autocomplete_representante_legal",
    )


def _is_cliente_autocomplete_type(tipo):
    tipo = str(tipo or "").strip().lower()
    return tipo in (
        "dato_cliente",
        "autocomplete_cliente",
    )

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


def _parse_autocomplete_record_id(value):
    """Extrae el id inicial de un valor AppAutocomplete: '11 - Nombre · NIE'."""
    raw = str(value or "").strip()
    if not raw:
        return None

    token = raw.split(" - ", 1)[0].strip()
    if token.isdigit():
        return int(token)
    return None


def _clean_derived_value(value):
    return str(value or "").strip()


def _full_name(row):
    return " ".join(
        _clean_derived_value(row.get(key))
        for key in ("nombre", "primer_apellido", "segundo_apellido")
        if _clean_derived_value(row.get(key))
    ).strip()


def _document_value(row):
    return (
        _clean_derived_value(row.get("nie"))
        or _clean_derived_value(row.get("dni"))
        or _clean_derived_value(row.get("pasaporte"))
    )


def _fetch_row_by_id(conn, table_name, record_id):
    if not record_id:
        return None
    try:
        row = conn.execute(
            f"SELECT * FROM {table_name} WHERE id = ? LIMIT 1",
            (int(record_id),),
        ).fetchone()
        return _dict(row)
    except Exception:
        return None


def _build_prefixed_row_values(prefix, row, id_suffix):
    """
    Convierte una fila cliente/contacto en datos específicos derivados.

    Ejemplo para representante_legal:
    - representante_legal_contacto_id
    - representante_legal_nombre
    - representante_legal_primer_apellido
    - representante_legal_nombre_completo
    - representante_legal_documento
    - representante_legal_parentesco

    Además expone cualquier columna escalar disponible con el prefijo del campo,
    para poder usarla después en snapshots, Mercurio o mappers sin nuevos parches.
    """
    if not prefix or not row:
        return {}

    derived = {
        f"{prefix}_{id_suffix}": _clean_derived_value(row.get("id")),
        f"{prefix}_nombre_completo": _full_name(row),
        f"{prefix}_documento": _document_value(row),
    }

    for key, value in row.items():
        if isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
            continue
        derived[f"{prefix}_{_normalize_code(key)}"] = _clean_derived_value(value)

    return {key: value for key, value in derived.items() if value != ""}


def _build_autocomplete_derived_values(conn, campos, values):
    """Genera datos derivados de campos autocomplete dinámicos."""
    derived = {}

    for campo in campos:
        codigo = campo.get("codigo")
        tipo = str(campo.get("tipo_campo") or "").lower().strip()
        if not codigo or codigo not in values:
            continue

        record_id = _parse_autocomplete_record_id(values.get(codigo))
        if not record_id:
            continue

        if _is_contact_autocomplete_type(tipo):
            row = _fetch_row_by_id(conn, "cliente_contactos", record_id)
            derived.update(_build_prefixed_row_values(codigo, row, "contacto_id"))

        elif _is_cliente_autocomplete_type(tipo):
            row = _fetch_row_by_id(conn, "clientes", record_id)
            derived.update(_build_prefixed_row_values(codigo, row, "cliente_id"))

    return derived


def _delete_previous_autocomplete_derivatives(conn, expediente_id, formulario_id, campos):
    """
    Borra derivados antiguos de los autocompletes del formulario antes de regenerarlos.
    Solo borra registros técnicos con campo_id NULL, nunca valores manuales configurados.
    """
    for campo in campos:
        codigo = campo.get("codigo")
        tipo = str(campo.get("tipo_campo") or "").lower().strip()
        if not codigo:
            continue
        if not (_is_contact_autocomplete_type(tipo) or _is_cliente_autocomplete_type(tipo)):
            continue

        conn.execute(
            """
            DELETE FROM expediente_datos_especificos
            WHERE expediente_id = ?
              AND formulario_id = ?
              AND codigo LIKE ?
            """,
            (int(expediente_id), int(formulario_id), f"{codigo}_%"),
        )



def _get_or_create_derived_campo_id(conn, formulario_id, codigo):
    """
    Garantiza un campo técnico para un dato derivado de autocomplete.

    La tabla expediente_datos_especificos exige campo_id NOT NULL y además
    usa ON CONFLICT(expediente_id, campo_id). Por eso cada derivado necesita
    su propio campo_id técnico, no puede guardarse con NULL ni reutilizar el
    campo_id del autocomplete principal.
    """
    codigo = str(codigo or "").strip()
    if not codigo:
        return None

    row = conn.execute(
        """
        SELECT id
        FROM config_campos_formulario_expediente
        WHERE formulario_id = ?
          AND codigo = ?
        LIMIT 1
        """,
        (int(formulario_id), codigo),
    ).fetchone()
    if row:
        return int(row["id"])

    cur = conn.execute(
        """
        INSERT INTO config_campos_formulario_expediente (
            formulario_id, codigo, etiqueta, tipo_campo, obligatorio,
            opciones_json, placeholder, ayuda, valor_defecto, orden, activo
        )
        VALUES (?, ?, ?, ?, 0, '', '', ?, '', 9999, 0)
        """,
        (
            int(formulario_id),
            codigo,
            codigo,
            "derivado_autocomplete",
            "Campo técnico generado desde autocomplete dinámico. No mostrar en formulario.",
        ),
    )
    return int(cur.lastrowid)

def _insert_autocomplete_derivatives(conn, expediente_id, formulario_id, derived_values):
    """Persiste derivados técnicos con campo_id propio para que entren en snapshot."""
    for codigo, valor in (derived_values or {}).items():
        codigo = str(codigo or "").strip()
        if not codigo:
            continue

        campo_id = _get_or_create_derived_campo_id(conn, formulario_id, codigo)
        if not campo_id:
            continue

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
                int(campo_id),
                codigo,
                str(valor or ""),
            ),
        )

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
                SELECT id, codigo, tipo_campo, opciones_json
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

        _delete_previous_autocomplete_derivatives(conn, expediente_id, formulario_id, campos)
        derived_values = _build_autocomplete_derived_values(conn, campos, values)
        _insert_autocomplete_derivatives(conn, expediente_id, formulario_id, derived_values)

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

