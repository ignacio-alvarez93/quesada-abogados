import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_to_dict(row):
    return dict(row) if row else None


def _normalize_code(value):
    return (value or "").strip().upper().replace(" ", "_")


def _normalize_text(value):
    return (value or "").strip().upper()


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _is_absolute_user_path(value):
    """
    Detecta rutas absolutas Windows/Linux.
    Ejemplos no permitidos:
    - C:/Users/Nacho/Box
    - C:\\Users\\Nacho\\Box
    - /home/user/Box
    """
    raw = (value or "").strip()
    if not raw:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return True
    return Path(raw).is_absolute()


def normalize_box_relative_path(value):
    """
    Normaliza una ruta Box para guardarla en configuración.

    Regla del proyecto:
    - No guardar rutas absolutas.
    - Guardar rutas relativas al escritorio del usuario.
    - Ejemplo recomendado: Box/NACIONALIDADES/2023
    """
    raw = (value or "").strip().replace("\\", "/")
    raw = raw.strip("/")
    raw = raw.replace("//", "/")
    if not raw:
        raise ValueError("La ruta Box es obligatoria")

    if _is_absolute_user_path(raw):
        raise ValueError(
            "No guardes rutas absolutas tipo C:/Users/... "
            "Guarda una ruta relativa desde el Escritorio, por ejemplo: Box/NACIONALIDADES/2023"
        )

    # Evitar rutas peligrosas.
    parts = [p for p in raw.split("/") if p]
    if any(p == ".." for p in parts):
        raise ValueError("La ruta relativa no puede contener '..'")

    return "/".join(parts)


def resolve_box_relative_path(relative_path):
    """
    Resuelve una ruta guardada en configuración.

    Regla práctica para Quesada Abogados:
    - Si la ruta empieza por Box/..., se prueba primero ~/Box/...
      porque Box Drive suele estar en C:/Users/<usuario>/Box.
    - Después se prueba Escritorio.
    - No modifica archivos. Solo calcula ruta.
    """
    relative = normalize_box_relative_path(relative_path)
    home = Path.home()

    candidates = []

    # Caso habitual real:
    # ruta guardada: Box/NACIONALIDADES/2019
    # ruta resuelta: C:/Users/Nacho/Box/NACIONALIDADES/2019
    candidates.append(home / relative)

    # Fallbacks si el usuario tiene Box dentro del Escritorio.
    candidates.append(home / "Desktop" / relative)
    candidates.append(home / "Escritorio" / relative)

    # Evitar duplicados manteniendo orden.
    unique_candidates = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)

    for candidate in unique_candidates:
        if candidate.exists():
            return str(candidate)

    # Si no existe, devolvemos la opción principal esperada.
    return str(unique_candidates[0])

def initialize_config_schema():
    schema_path = Path(__file__).resolve().parents[2] / "database" / "config_schema.sql"
    with _connect() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    ensure_config_runtime_schema()


def _column_exists(conn, table_name, column_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(row["name"] == column_name for row in rows)
    except Exception:
        return False


def _initialize_dynamic_forms_runtime_schema():
    schema_path = Path(__file__).resolve().parents[2] / "database" / "expedient_dynamic_forms_schema.sql"
    if not schema_path.exists():
        return
    with _connect() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def ensure_config_runtime_schema():
    """
    Migración defensiva de configuración.

    Añade soporte para subtipos de expediente sin depender todavía
    de modificar manualmente config_schema.sql.
    """
    _initialize_dynamic_forms_runtime_schema()

    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config_subtipos_expediente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_expediente_id INTEGER NOT NULL,
                codigo TEXT NOT NULL,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tipo_expediente_id) REFERENCES config_tipos_expediente(id),
                UNIQUE(tipo_expediente_id, codigo)
            )
            """
        )


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config_global (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        if _column_exists(conn, "config_documentos_requeridos", "subtipo_expediente_id") is False:
            conn.execute("ALTER TABLE config_documentos_requeridos ADD COLUMN subtipo_expediente_id INTEGER")

        if _column_exists(conn, "config_nomenclaturas_documentales", "subtipo_expediente_id") is False:
            conn.execute("ALTER TABLE config_nomenclaturas_documentales ADD COLUMN subtipo_expediente_id INTEGER")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_config_subtipos_tipo
            ON config_subtipos_expediente(tipo_expediente_id, activo, orden, nombre)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_config_docs_subtipo
            ON config_documentos_requeridos(subtipo_expediente_id)
            """
        )
        conn.commit()


def list_records(table, where_active=None, order_by="orden ASC, nombre ASC"):
    sql = f"SELECT * FROM {table}"
    params = []
    if where_active is not None:
        sql += " WHERE activo = ?"
        params.append(1 if where_active else 0)
    sql += f" ORDER BY {order_by}"
    with _connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def get_record(table, record_id):
    with _connect() as conn:
        return _row_to_dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone())


def delete_record(table, record_id):
    with _connect() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
        conn.commit()


def set_active(table, record_id, active):
    with _connect() as conn:
        conn.execute(f"UPDATE {table} SET activo = ? WHERE id = ?", (1 if active else 0, record_id))
        conn.commit()


def create_tipo_expediente(data):
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    descripcion = (data.get("descripcion") or "").strip()
    url_presentacion = (data.get("url_presentacion") or "").strip()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_tipos_expediente (codigo, nombre, descripcion, url_presentacion, activo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (codigo, nombre, descripcion, url_presentacion, int(data.get("activo", 1))),
        )
        conn.commit()
        return cur.lastrowid


def update_tipo_expediente(record_id, data):
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    descripcion = (data.get("descripcion") or "").strip()
    url_presentacion = (data.get("url_presentacion") or "").strip()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_tipos_expediente
            SET codigo = ?, nombre = ?, descripcion = ?, url_presentacion = ?, activo = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (codigo, nombre, descripcion, url_presentacion, int(data.get("activo", 1)), record_id),
        )
        conn.commit()


def get_tipos_expediente(active_only=False):
    return list_records("config_tipos_expediente", True if active_only else None, "nombre ASC")


def create_subtipo_expediente(data):
    ensure_config_runtime_schema()
    tipo_id = int(data.get("tipo_expediente_id"))
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    descripcion = (data.get("descripcion") or "").strip()
    orden = int(data.get("orden") or 0)
    activo = int(data.get("activo", 1))
    if not nombre:
        raise ValueError("El nombre del subtipo es obligatorio")
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_subtipos_expediente
            (tipo_expediente_id, codigo, nombre, descripcion, orden, activo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tipo_id, codigo, nombre, descripcion, orden, activo),
        )
        conn.commit()
        return cur.lastrowid


def update_subtipo_expediente(record_id, data):
    ensure_config_runtime_schema()
    tipo_id = int(data.get("tipo_expediente_id"))
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    descripcion = (data.get("descripcion") or "").strip()
    orden = int(data.get("orden") or 0)
    activo = int(data.get("activo", 1))
    if not nombre:
        raise ValueError("El nombre del subtipo es obligatorio")
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_subtipos_expediente
            SET tipo_expediente_id = ?,
                codigo = ?,
                nombre = ?,
                descripcion = ?,
                orden = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (tipo_id, codigo, nombre, descripcion, orden, activo, int(record_id)),
        )
        conn.commit()


def get_subtipos_expediente(tipo_expediente_id=None, active_only=False):
    ensure_config_runtime_schema()
    sql = """
        SELECT s.*, t.nombre AS tipo_expediente_nombre
        FROM config_subtipos_expediente s
        JOIN config_tipos_expediente t ON t.id = s.tipo_expediente_id
    """
    params = []
    conditions = []
    if tipo_expediente_id:
        conditions.append("s.tipo_expediente_id = ?")
        params.append(int(tipo_expediente_id))
    if active_only:
        conditions.append("s.activo = 1")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY t.nombre ASC, s.orden ASC, s.nombre ASC"
    with _connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def create_documento_requerido(data):
    codigo = _normalize_code(data.get("codigo_documento") or data.get("nombre_documento"))
    nombre = _normalize_text(data.get("nombre_documento"))
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_documentos_requeridos
            (tipo_expediente_id, subtipo_expediente_id, codigo_documento, nombre_documento, obligatorio, orden, activo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(data.get("tipo_expediente_id")),
                _int_or_none(data.get("subtipo_expediente_id")),
                codigo,
                nombre,
                int(data.get("obligatorio", 1)),
                int(data.get("orden") or 0),
                int(data.get("activo", 1)),
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_documento_requerido(record_id, data):
    codigo = _normalize_code(data.get("codigo_documento") or data.get("nombre_documento"))
    nombre = _normalize_text(data.get("nombre_documento"))
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_documentos_requeridos
            SET tipo_expediente_id = ?, subtipo_expediente_id = ?, codigo_documento = ?, nombre_documento = ?,
                obligatorio = ?, orden = ?, activo = ?
            WHERE id = ?
            """,
            (
                int(data.get("tipo_expediente_id")),
                _int_or_none(data.get("subtipo_expediente_id")),
                codigo,
                nombre,
                int(data.get("obligatorio", 1)),
                int(data.get("orden") or 0),
                int(data.get("activo", 1)),
                record_id,
            ),
        )
        conn.commit()


def get_documentos_requeridos(tipo_expediente_id=None, subtipo_expediente_id=None, active_only=False):
    sql = """
        SELECT d.*, t.nombre AS tipo_expediente_nombre, s.nombre AS subtipo_expediente_nombre
        FROM config_documentos_requeridos d
        JOIN config_tipos_expediente t ON t.id = d.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente s ON s.id = d.subtipo_expediente_id
    """
    params = []
    conditions = []
    if tipo_expediente_id:
        conditions.append("d.tipo_expediente_id = ?")
        params.append(int(tipo_expediente_id))
    if subtipo_expediente_id:
        conditions.append("(d.subtipo_expediente_id IS NULL OR d.subtipo_expediente_id = ?)")
        params.append(int(subtipo_expediente_id))
    if active_only:
        conditions.append("d.activo = 1")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY t.nombre ASC, d.orden ASC, d.nombre_documento ASC"
    with _connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def create_estado_expediente(data):
    return _create_catalog_record("config_estados_expediente", data)


def update_estado_expediente(record_id, data):
    _update_catalog_record("config_estados_expediente", record_id, data)


def get_estados_expediente(active_only=False):
    return list_records("config_estados_expediente", True if active_only else None)


def create_prioridad(data):
    return _create_catalog_record("config_prioridades", data)


def update_prioridad(record_id, data):
    _update_catalog_record("config_prioridades", record_id, data)


def get_prioridades(active_only=False):
    return list_records("config_prioridades", True if active_only else None)


def _create_catalog_record(table, data):
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    color = (data.get("color") or "#0057B8").strip()
    with _connect() as conn:
        cur = conn.execute(
            f"""
            INSERT INTO {table} (codigo, nombre, color, orden, activo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (codigo, nombre, color, int(data.get("orden") or 0), int(data.get("activo", 1))),
        )
        conn.commit()
        return cur.lastrowid


def _update_catalog_record(table, record_id, data):
    codigo = _normalize_code(data.get("codigo") or data.get("nombre"))
    nombre = _normalize_text(data.get("nombre"))
    color = (data.get("color") or "#0057B8").strip()
    with _connect() as conn:
        conn.execute(
            f"""
            UPDATE {table}
            SET codigo = ?, nombre = ?, color = ?, orden = ?, activo = ?
            WHERE id = ?
            """,
            (codigo, nombre, color, int(data.get("orden") or 0), int(data.get("activo", 1)), record_id),
        )
        conn.commit()


def create_box_ruta(data):
    ruta_relativa = normalize_box_relative_path(data.get("ruta_box") or "")
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_box_rutas (tipo_expediente_id, ruta_box, activo)
            VALUES (?, ?, ?)
            """,
            (int(data.get("tipo_expediente_id")), ruta_relativa, int(data.get("activo", 1))),
        )
        conn.commit()
        return cur.lastrowid


def update_box_ruta(record_id, data):
    ruta_relativa = normalize_box_relative_path(data.get("ruta_box") or "")
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_box_rutas
            SET tipo_expediente_id = ?, ruta_box = ?, activo = ?
            WHERE id = ?
            """,
            (int(data.get("tipo_expediente_id")), ruta_relativa, int(data.get("activo", 1)), record_id),
        )
        conn.commit()


def get_box_rutas(active_only=False, include_resolved=False):
    sql = """
        SELECT r.*, t.nombre AS tipo_expediente_nombre
        FROM config_box_rutas r
        JOIN config_tipos_expediente t ON t.id = r.tipo_expediente_id
    """
    if active_only:
        sql += " WHERE r.activo = 1"
    sql += " ORDER BY t.nombre ASC, r.ruta_box ASC"
    with _connect() as conn:
        rows = [_row_to_dict(r) for r in conn.execute(sql).fetchall()]

    if include_resolved:
        for row in rows:
            resolved = resolve_box_relative_path(row.get("ruta_box") or "")
            row["ruta_resuelta"] = resolved
            row["ruta_existe"] = 1 if Path(resolved).exists() else 0

    return rows


def get_box_ruta(record_id, include_resolved=True):
    with _connect() as conn:
        row = _row_to_dict(
            conn.execute(
                """
                SELECT r.*, t.nombre AS tipo_expediente_nombre
                FROM config_box_rutas r
                JOIN config_tipos_expediente t ON t.id = r.tipo_expediente_id
                WHERE r.id = ?
                """,
                (int(record_id),),
            ).fetchone()
        )

    if row and include_resolved:
        resolved = resolve_box_relative_path(row.get("ruta_box") or "")
        row["ruta_resuelta"] = resolved
        row["ruta_existe"] = 1 if Path(resolved).exists() else 0

    return row


def create_nomenclatura(data):
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO config_nomenclaturas_documentales
            (tipo_expediente_id, documento_id, patron_nombre, extension_permitida, activo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(data.get("tipo_expediente_id")),
                int(data.get("documento_id")),
                (data.get("patron_nombre") or "").strip().upper(),
                (data.get("extension_permitida") or "pdf,jpg,jpeg,png").strip().lower(),
                int(data.get("activo", 1)),
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_nomenclatura(record_id, data):
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_nomenclaturas_documentales
            SET tipo_expediente_id = ?, documento_id = ?, patron_nombre = ?,
                extension_permitida = ?, activo = ?
            WHERE id = ?
            """,
            (
                int(data.get("tipo_expediente_id")),
                int(data.get("documento_id")),
                (data.get("patron_nombre") or "").strip().upper(),
                (data.get("extension_permitida") or "pdf,jpg,jpeg,png").strip().lower(),
                int(data.get("activo", 1)),
                record_id,
            ),
        )
        conn.commit()


def get_nomenclaturas(active_only=False):
    sql = """
        SELECT n.*, t.nombre AS tipo_expediente_nombre, d.nombre_documento
        FROM config_nomenclaturas_documentales n
        JOIN config_tipos_expediente t ON t.id = n.tipo_expediente_id
        JOIN config_documentos_requeridos d ON d.id = n.documento_id
    """
    if active_only:
        sql += " WHERE n.activo = 1"
    sql += " ORDER BY t.nombre ASC, d.orden ASC, n.patron_nombre ASC"
    with _connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql).fetchall()]


def upsert_columna_tabla(data):
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO config_columnas_tabla (tabla, campo, visible, orden, ancho)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tabla, campo) DO UPDATE SET
                visible = excluded.visible,
                orden = excluded.orden,
                ancho = excluded.ancho
            """,
            (
                (data.get("tabla") or "").strip(),
                (data.get("campo") or "").strip(),
                int(data.get("visible", 1)),
                int(data.get("orden") or 0),
                int(data.get("ancho") or 160),
            ),
        )
        conn.commit()


def get_columnas_tabla(tabla):
    with _connect() as conn:
        return [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM config_columnas_tabla WHERE tabla = ? ORDER BY orden ASC, campo ASC",
                (tabla,),
            ).fetchall()
        ]


def seed_config_defaults():
    initialize_config_schema()

    tipos = [
        ("ARRAIGO_SOCIAL", "ARRAIGO SOCIAL"),
        ("ARRAIGO_FAMILIAR", "ARRAIGO FAMILIAR"),
        ("NACIONALIDAD", "NACIONALIDAD"),
        ("ESTANCIA_ESTUDIOS", "ESTANCIA ESTUDIOS"),
        ("ASILO", "ASILO"),
        ("RECURSO", "RECURSO"),
        ("RENOVACION", "RENOVACIÓN"),
    ]

    estados = [
        ("PENDIENTE_DOCUMENTACION", "PENDIENTE DOCUMENTACION", "#B54708", 10),
        ("EN_PREPARACION", "EN PREPARACION", "#0057B8", 20),
        ("PRESENTADO", "PRESENTADO", "#0369A1", 30),
        ("REQUERIDO", "REQUERIDO", "#B42318", 40),
        ("FINALIZADO", "FINALIZADO", "#027A48", 50),
        ("ARCHIVADO", "ARCHIVADO", "#475569", 60),
    ]

    prioridades = [
        ("BAJA", "BAJA", "#475569", 10),
        ("MEDIA", "MEDIA", "#0057B8", 20),
        ("ALTA", "ALTA", "#B54708", 30),
        ("URGENTE", "URGENTE", "#B42318", 40),
    ]

    with _connect() as conn:
        for codigo, nombre in tipos:
            conn.execute(
                """
                INSERT OR IGNORE INTO config_tipos_expediente (codigo, nombre, descripcion, activo)
                VALUES (?, ?, '', 1)
                """,
                (codigo, nombre),
            )

        for codigo, nombre, color, orden in estados:
            conn.execute(
                """
                INSERT OR IGNORE INTO config_estados_expediente (codigo, nombre, color, orden, activo)
                VALUES (?, ?, ?, ?, 1)
                """,
                (codigo, nombre, color, orden),
            )

        for codigo, nombre, color, orden in prioridades:
            conn.execute(
                """
                INSERT OR IGNORE INTO config_prioridades (codigo, nombre, color, orden, activo)
                VALUES (?, ?, ?, ?, 1)
                """,
                (codigo, nombre, color, orden),
            )

        for orden, campo in enumerate(["nombre", "nie_pasaporte", "nacionalidad", "edad", "telefono", "estado", "ficha"], start=1):
            conn.execute(
                """
                INSERT OR IGNORE INTO config_columnas_tabla (tabla, campo, visible, orden, ancho)
                VALUES ('clientes', ?, 1, ?, 160)
                """,
                (campo, orden),
            )

        conn.commit()


def get_database_tables(include_config=True):
    """
    Devuelve las tablas reales de SQLite.

    include_config=True permite configurar también tablas de configuración.
    En producción se podrán ocultar si interesa.
    """
    excluded_prefixes = ("sqlite_",)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name ASC
            """
        ).fetchall()

    tables = []
    for row in rows:
        name = row["name"]
        if name.startswith(excluded_prefixes):
            continue
        if not include_config and name.startswith("config_"):
            continue
        tables.append(name)

    return tables


def get_database_columns(table_name):
    """
    Devuelve los campos reales de una tabla SQLite mediante PRAGMA table_info.
    """
    table_name = (table_name or "").strip()
    if not table_name:
        return []

    with _connect() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()

    columns = []
    for row in rows:
        columns.append(
            {
                "cid": row["cid"],
                "name": row["name"],
                "type": row["type"],
                "notnull": row["notnull"],
                "default_value": row["dflt_value"],
                "pk": row["pk"],
            }
        )

    return columns


def sync_columnas_tabla_from_db(table_name):
    """
    Crea configuración inicial de columnas para una tabla real.

    No elimina configuraciones existentes.
    No pisa anchos, orden ni visibilidad ya definidos.
    """
    table_name = (table_name or "").strip()
    if not table_name:
        return []

    columns = get_database_columns(table_name)

    with _connect() as conn:
        for index, column in enumerate(columns, start=1):
            conn.execute(
                """
                INSERT OR IGNORE INTO config_columnas_tabla
                (tabla, campo, visible, orden, ancho)
                VALUES (?, ?, 1, ?, 160)
                """,
                (table_name, column["name"], index),
            )
        conn.commit()

    return get_columnas_tabla(table_name)


def update_columna_tabla(record_id, data):
    with _connect() as conn:
        conn.execute(
            """
            UPDATE config_columnas_tabla
            SET visible = ?, orden = ?, ancho = ?
            WHERE id = ?
            """,
            (
                int(data.get("visible", 1)),
                int(data.get("orden") or 0),
                int(data.get("ancho") or 160),
                int(record_id),
            ),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Configuración global: Representante / presentador Mercurio
# ---------------------------------------------------------------------------

REPRESENTANTE_CONFIG_KEYS = [
    # Identidad básica solicitada inicialmente
    "representante_nombre",
    "representante_apellido1",
    "representante_apellido2",
    "representante_tipo_documento",
    "representante_documento",

    # Identidad exacta usada por Mercurio en tab-datos_presentador
    "representante_nombre_razon_social",

    # Datos profesionales
    "representante_colegio",
    "representante_numero_colegiado",

    # Domicilio completo del presentador/a en Mercurio
    "representante_tipo_via",
    "representante_domicilio",
    "representante_numero",
    "representante_piso",
    "representante_letra",
    "representante_escalera",
    "representante_bloque",
    "representante_kilometro",
    "representante_hectometro",
    "representante_provincia",
    "representante_municipio",
    "representante_localidad",
    "representante_codigo_postal",

    # Contacto
    "representante_telefono",
    "representante_telefono_movil",
    "representante_email",

    # Documento físico/digital en Box
    "representante_ruta_box_dni",

    # Representante legal del presentador/a, si procede
    "representante_legal_nombre",
    "representante_legal_tipo_documento",
    "representante_legal_documento",
    "representante_legal_titulo",
    "representante_legal_telefono_movil",
    "representante_legal_email",

    # Datos notariales / Apodera / CSV, si procede
    "representante_opcion_notarial",
    "representante_csv",
    "representante_codigo_notario",
    "representante_codigo_notaria",
    "representante_fecha_escritura",
    "representante_num_protocolo",
    "representante_num_bis",
]


def get_config(key, default=""):
    """
    Lee un valor de configuración global en formato clave/valor.
    """
    ensure_config_runtime_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM config_global WHERE key = ?",
            (key,),
        ).fetchone()
        return row["value"] if row else default


def set_config(key, value):
    """
    Guarda un valor de configuración global en formato clave/valor.
    """
    ensure_config_runtime_schema()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO config_global (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        conn.commit()


def validate_representante_ruta_box_dni(value):
    """
    Valida que la ruta del DNI del representante sea relativa.
    No se permiten rutas absolutas Windows/macOS/Linux.
    """
    raw = (value or "").strip()

    if not raw:
        raise ValueError("La ruta Box DNI del representante es obligatoria")

    if raw.startswith("/"):
        raise ValueError("La ruta Box DNI debe ser relativa, no puede empezar por /")

    if raw.upper().startswith("C:\\"):
        raise ValueError("La ruta Box DNI debe ser relativa, no puede empezar por C:\\")

    if ":\\" in raw or ":/" in raw:
        raise ValueError("La ruta Box DNI debe ser relativa, no puede contener unidad de disco")

    return raw.replace("\\", "/")


def _normalize_representante_data(data):
    normalized = {}
    for key in REPRESENTANTE_CONFIG_KEYS:
        normalized[key] = str((data or {}).get(key) or "").strip()

    # Si el usuario rellena nombre y apellidos separados pero deja vacío el campo
    # exacto de Mercurio, construimos Nombre/Razón Social automáticamente.
    if not normalized["representante_nombre_razon_social"]:
        partes = [
            normalized["representante_nombre"],
            normalized["representante_apellido1"],
            normalized["representante_apellido2"],
        ]
        normalized["representante_nombre_razon_social"] = " ".join(p for p in partes if p).strip()

    normalized["representante_ruta_box_dni"] = validate_representante_ruta_box_dni(
        normalized["representante_ruta_box_dni"]
    )

    return normalized


def get_representante_config():
    """
    Devuelve la configuración global del representante/presentador.
    """
    return {key: get_config(key, "") for key in REPRESENTANTE_CONFIG_KEYS}


def save_representante_config(data):
    """
    Guarda la configuración global del representante/presentador.

    Campos obligatorios para considerar completa la configuración:
    - identidad
    - documento
    - domicilio mínimo de Mercurio
    - ruta relativa del DNI en Box
    """
    normalized = _normalize_representante_data(data)

    required = {
        "representante_nombre_razon_social": "Nombre/Razón social",
        "representante_tipo_documento": "Tipo documento",
        "representante_documento": "Documento",
        "representante_tipo_via": "Tipo de vía",
        "representante_domicilio": "Domicilio",
        "representante_numero": "Número",
        "representante_provincia": "Provincia",
        "representante_municipio": "Municipio",
        "representante_localidad": "Localidad",
        "representante_codigo_postal": "Código postal",
        "representante_ruta_box_dni": "Ruta Box DNI",
    }

    for key, label in required.items():
        if not normalized.get(key):
            raise ValueError(f"{label} es obligatorio")

    for key, value in normalized.items():
        set_config(key, value)

    return normalized

