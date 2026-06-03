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


CLIENT_AUTOCOMPLETE_DERIVED_FIELDS = [
    "cliente_id",
    "nombre",
    "primer_apellido",
    "segundo_apellido",
    "nombre_completo",
    "documento",
    "nie",
    "dni",
    "pasaporte",
    "nacionalidad",
    "fecha_nacimiento",
    "sexo",
    "telefono",
    "email",
    "tipo_via",
    "nombre_via",
    "numero",
    "piso",
    "domicilio_espana",
    "localidad",
    "provincia",
    "codigo_postal",
    "localidad_nacimiento",
    "pais_nacimiento",
    "nombre_padre",
    "nombre_madre",
    "estado_civil",
]

CONTACT_AUTOCOMPLETE_DERIVED_FIELDS = [
    "contacto_id",
    "tipo_contacto",
    "parentesco",
    "nombre",
    "primer_apellido",
    "segundo_apellido",
    "nombre_completo",
    "documento",
    "nie",
    "dni",
    "pasaporte",
    "nacionalidad",
    "fecha_nacimiento",
    "sexo",
    "telefono",
    "email",
    "tipo_via",
    "nombre_via",
    "numero",
    "piso",
    "domicilio_espana",
    "localidad",
    "provincia",
    "codigo_postal",
    "observaciones",
]

AUTOCOMPLETE_DERIVATIVE_PROFILES = {
    "autocomplete_cliente": {
        "source": "clientes",
        "id_suffix": "cliente_id",
        "label": "Cliente principal",
        "derived_fields": CLIENT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "dato_cliente": {
        "source": "clientes",
        "id_suffix": "cliente_id",
        "label": "Cliente principal",
        "derived_fields": CLIENT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "autocomplete_familiar": {
        "source": "cliente_contactos",
        "id_suffix": "contacto_id",
        "label": "Familiar / contacto vinculado",
        "contact_filter": "FAMILIAR",
        "derived_fields": CONTACT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "autocomplete_representante_legal": {
        "source": "cliente_contactos",
        "id_suffix": "contacto_id",
        "label": "Representante legal",
        "contact_filter": "REPRESENTANTE",
        "derived_fields": CONTACT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "representante_legal": {
        "source": "cliente_contactos",
        "id_suffix": "contacto_id",
        "label": "Representante legal",
        "contact_filter": "REPRESENTANTE",
        "derived_fields": CONTACT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "representante": {
        "source": "cliente_contactos",
        "id_suffix": "contacto_id",
        "label": "Representante",
        "contact_filter": "REPRESENTANTE",
        "derived_fields": CONTACT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "autocomplete_empleador": {
        "source": "cliente_contactos",
        "id_suffix": "contacto_id",
        "label": "Empleador registrado como contacto",
        "contact_filter": "EMPLEADOR",
        "derived_fields": CONTACT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "empleador_empresa": {
        "source": "cliente_contactos",
        "id_suffix": "contacto_id",
        "label": "Empleador registrado como contacto",
        "contact_filter": "EMPLEADOR",
        "derived_fields": CONTACT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
    "contacto_cliente": {
        "source": "cliente_contactos",
        "id_suffix": "contacto_id",
        "label": "Contacto vinculado",
        "derived_fields": CONTACT_AUTOCOMPLETE_DERIVED_FIELDS,
    },
}


def get_autocomplete_derivative_profile(tipo):
    """Devuelve el perfil real de derivados para un tipo autocomplete dinámico."""
    tipo = str(tipo or "").strip().lower()
    profile = AUTOCOMPLETE_DERIVATIVE_PROFILES.get(tipo)
    if not profile:
        return {}
    return {
        "tipo_campo": tipo,
        "source": profile.get("source"),
        "id_suffix": profile.get("id_suffix"),
        "label": profile.get("label"),
        "contact_filter": profile.get("contact_filter", ""),
        "derived_fields": list(profile.get("derived_fields") or []),
    }


def _autocomplete_profile_for_field(campo):
    return get_autocomplete_derivative_profile((campo or {}).get("tipo_campo"))


def _autocomplete_config_for_field(campo):
    return parse_autocomplete_fill_config((campo or {}).get("opciones_json"))


def _is_autocomplete_derivatives_config(config):
    """Acepta el JSON nuevo y tolera errores de escritura habituales.

    Válidos:
    - {"mode": "autocomplete_derivatives", ...}
    - {"mode": "autocomplete_derivates", ...}  # typo frecuente
    - cualquier JSON con derived_fields como lista.
    """
    if not isinstance(config, dict):
        return False

    mode = str(config.get("mode") or "").strip().lower()
    if mode in ("autocomplete_derivatives", "autocomplete_derivates"):
        return True

    return isinstance(config.get("derived_fields"), list)


def _autocomplete_derived_fields_for_field(campo, profile):
    config = _autocomplete_config_for_field(campo)

    # Compatibilidad: campos antiguos sin JSON nuevo siguen derivando todo lo escalar.
    if not _is_autocomplete_derivatives_config(config):
        return None

    if config.get("derived_enabled") is False:
        return []

    requested = config.get("derived_fields")
    if not isinstance(requested, list):
        return list(profile.get("derived_fields") or [])

    allowed = set(profile.get("derived_fields") or [])
    selected = []
    id_suffix = _normalize_code(profile.get("id_suffix"))
    for item in requested:
        code = _normalize_code(item)
        if code == "id" and id_suffix:
            code = id_suffix
        if code in allowed and code not in selected:
            selected.append(code)
    return selected

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


def _build_prefixed_row_values(prefix, row, id_suffix, derived_fields=None):
    """
    Convierte una fila cliente/contacto en datos específicos derivados.

    Si derived_fields es None, mantiene la compatibilidad antigua y expone
    todas las columnas escalares disponibles. Si llega una lista, solo expone
    los derivados elegidos para el perfil real del autocomplete.
    """
    if not prefix or not row:
        return {}

    computed = {
        id_suffix: _clean_derived_value(row.get("id")),
        "nombre_completo": _full_name(row),
        "documento": _document_value(row),
    }

    if derived_fields is None:
        derived = {f"{prefix}_{key}": value for key, value in computed.items()}
        for key, value in row.items():
            if isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
                continue
            derived[f"{prefix}_{_normalize_code(key)}"] = _clean_derived_value(value)
        return {key: value for key, value in derived.items() if value != ""}

    derived = {}
    for field in derived_fields or []:
        field = _normalize_code(field)
        if not field:
            continue
        if field in computed:
            value = computed.get(field)
        else:
            value = row.get(field)
        clean = _clean_derived_value(value)
        if clean != "":
            derived[f"{prefix}_{field}"] = clean

    return derived


def _build_autocomplete_derived_values(conn, campos, values):
    """Genera datos derivados de campos autocomplete dinámicos."""
    derived = {}

    for campo in campos:
        codigo = campo.get("codigo")
        if not codigo or codigo not in values:
            continue

        profile = _autocomplete_profile_for_field(campo)
        if not profile:
            continue

        record_id = _parse_autocomplete_record_id(values.get(codigo))
        if not record_id:
            continue

        selected_fields = _autocomplete_derived_fields_for_field(campo, profile)
        if selected_fields == []:
            continue

        row = _fetch_row_by_id(conn, profile.get("source"), record_id)
        derived.update(
            _build_prefixed_row_values(
                codigo,
                row,
                profile.get("id_suffix"),
                selected_fields,
            )
        )

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
        if not _autocomplete_profile_for_field(campo):
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


def _label_from_code(codigo):
    return str(codigo or "").replace("_", " ").strip().title()


def _derived_codigo_for_field(prefix, field, profile):
    field = _normalize_code(field)
    id_suffix = _normalize_code((profile or {}).get("id_suffix"))

    # Alias cómodo para JSON manual: permite escribir "id" aunque internamente
    # se materialice como cliente_id/contacto_id según el perfil.
    if field == "id" and id_suffix:
        field = id_suffix

    if not prefix or not field:
        return ""
    return f"{prefix}_{field}"


def materialize_autocomplete_derived_fields(campo_id, visible=True):
    """
    Crea ahora los campos derivados definidos en el JSON del autocomplete.

    Diferencia importante:
    - El JSON define la regla.
    - Esta función crea filas en config_campos_formulario_expediente para que
      los derivados existan en Settings/Formularios/EX antes de guardar un expediente.

    visible=True crea los campos activos como texto editable/visible.
    visible=False los crea técnicos/inactivos, útiles solo para snapshot/mappers.
    """
    initialize_dynamic_forms_schema()

    with _connect() as conn:
        campo = _dict(
            conn.execute(
                "SELECT * FROM config_campos_formulario_expediente WHERE id = ?",
                (int(campo_id),),
            ).fetchone()
        )

        if not campo:
            raise ValueError("Campo no encontrado")

        profile = _autocomplete_profile_for_field(campo)
        if not profile:
            raise ValueError("El campo seleccionado no es un autocomplete con perfil de derivados")

        config = _autocomplete_config_for_field(campo)
        if not _is_autocomplete_derivatives_config(config):
            raise ValueError(
                "El campo no tiene configuración JSON de derivados en opciones_json. "
                "Pulsa 'Insertar JSON autocomplete', rellena derived_fields y después crea los campos."
            )

        if config.get("derived_enabled") is False:
            raise ValueError("El JSON tiene derived_enabled=false")

        requested = config.get("derived_fields")
        if not isinstance(requested, list) or not requested:
            raise ValueError("Añade al JSON una lista derived_fields con al menos un campo")

        prefix = _normalize_code(campo.get("codigo"))
        if not prefix:
            raise ValueError("El campo principal no tiene código técnico")

        base_order = int(campo.get("orden") or 0)
        created = []
        updated = []
        skipped = []

        allowed = set(profile.get("derived_fields") or [])
        id_suffix = _normalize_code(profile.get("id_suffix"))

        for index, raw_field in enumerate(requested, start=1):
            field = _normalize_code(raw_field)
            if field == "id" and id_suffix:
                field = id_suffix

            if field not in allowed:
                skipped.append(str(raw_field))
                continue

            codigo = _derived_codigo_for_field(prefix, field, profile)
            if not codigo:
                continue

            existing = conn.execute(
                """
                SELECT id
                FROM config_campos_formulario_expediente
                WHERE formulario_id = ?
                  AND codigo = ?
                LIMIT 1
                """,
                (int(campo["formulario_id"]), codigo),
            ).fetchone()

            etiqueta = _label_from_code(codigo)
            ayuda = f"Derivado de {prefix}."
            activo = 1 if visible else 0
            tipo_campo = "texto" if visible else "derivado_autocomplete"
            orden = base_order + index

            if existing:
                conn.execute(
                    """
                    UPDATE config_campos_formulario_expediente
                    SET etiqueta = ?,
                        tipo_campo = ?,
                        obligatorio = 0,
                        placeholder = '',
                        ayuda = ?,
                        valor_defecto = '',
                        orden = ?,
                        activo = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (etiqueta, tipo_campo, ayuda, int(orden), int(activo), int(existing["id"])),
                )
                updated.append(codigo)
            else:
                conn.execute(
                    """
                    INSERT INTO config_campos_formulario_expediente (
                        formulario_id, codigo, etiqueta, tipo_campo, obligatorio,
                        opciones_json, placeholder, ayuda, valor_defecto, orden, activo
                    )
                    VALUES (?, ?, ?, ?, 0, '', '', ?, '', ?, ?)
                    """,
                    (
                        int(campo["formulario_id"]),
                        codigo,
                        etiqueta,
                        tipo_campo,
                        ayuda,
                        int(orden),
                        int(activo),
                    ),
                )
                created.append(codigo)

        conn.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "visible": bool(visible),
    }

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

