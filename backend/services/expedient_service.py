import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def _normalize_text(value):
    return (value or "").strip().upper()


def _normalize_code(value):
    return _normalize_text(value).replace(" ", "_")


def _date_or_none(value):
    value = (value or "").strip()
    return value or None


def initialize_expedients_schema():
    schema_path = Path(__file__).resolve().parents[2] / "database" / "expedients_schema.sql"
    with _connect() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    ensure_expedients_runtime_schema()


def _column_exists(conn, table_name, column_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(row["name"] == column_name for row in rows)
    except Exception:
        return False


def ensure_expedients_runtime_schema():
    """
    Migración defensiva para permitir subtipos de expediente.

    Conserva el campo de texto subtipo_expediente y añade
    subtipo_expediente_id para vincularlo con configuración.
    """
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
        if not _column_exists(conn, "expedientes", "subtipo_expediente_id"):
            conn.execute("ALTER TABLE expedientes ADD COLUMN subtipo_expediente_id INTEGER")
        if not _column_exists(conn, "expedientes", "numero_expediente_mercurio"):
            conn.execute("ALTER TABLE expedientes ADD COLUMN numero_expediente_mercurio TEXT")

        # Preparación documental Mercurio / Box.
        # No altera el flujo Mercurio ni automatiza subidas: solo guarda estado detectado.
        if not _column_exists(conn, "expedientes", "box_root_folder_id"):
            conn.execute("ALTER TABLE expedientes ADD COLUMN box_root_folder_id INTEGER")
        if not _column_exists(conn, "expedientes", "box_root_folder_url"):
            conn.execute("ALTER TABLE expedientes ADD COLUMN box_root_folder_url TEXT")
        if not _column_exists(conn, "expedientes", "box_para_presentar_folder_id"):
            conn.execute("ALTER TABLE expedientes ADD COLUMN box_para_presentar_folder_id INTEGER")
        if not _column_exists(conn, "expedientes", "box_para_presentar_folder_url"):
            conn.execute("ALTER TABLE expedientes ADD COLUMN box_para_presentar_folder_url TEXT")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_expedientes_subtipo
            ON expedientes(subtipo_expediente_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_expedientes_box_para_presentar
            ON expedientes(box_para_presentar_folder_id)
            """
        )
        conn.commit()


def seed_expedients_defaults():
    initialize_expedients_schema()

    estados_documentales = [
        ("PENDIENTE_DOCUMENTACION", "PENDIENTE DE DOCUMENTACIÓN", "#B54708", 10),
        ("DOCUMENTACION_INCOMPLETA", "DOCUMENTACIÓN INCOMPLETA", "#B42318", 20),
        ("DOCUMENTACION_COMPLETA", "DOCUMENTACIÓN COMPLETA", "#027A48", 30),
        ("PENDIENTE_ESCANEAR", "PENDIENTE DE ESCANEAR", "#B54708", 40),
        ("ESCANEADO_PARCIAL", "ESCANEADO PARCIAL", "#026AA2", 50),
        ("ESCANEADO_COMPLETO", "ESCANEADO COMPLETO", "#027A48", 60),
    ]

    estados_administrativos = [
        ("NO_PRESENTADO", "NO PRESENTADO", "#475569", 10),
        ("EN_PREPARACION", "EN PREPARACIÓN", "#0057B8", 20),
        ("PRESENTADO", "PRESENTADO", "#0369A1", 30),
        ("ADMITIDO", "ADMITIDO", "#027A48", 40),
        ("EN_TRAMITE", "EN TRÁMITE", "#026AA2", 50),
        ("REQUERIDO", "REQUERIDO", "#B42318", 60),
        ("RESUELTO_FAVORABLE", "RESUELTO FAVORABLE", "#027A48", 70),
        ("RESUELTO_DENEGADO", "RESUELTO DENEGADO", "#B42318", 80),
        ("ARCHIVADO", "ARCHIVADO", "#475569", 90),
        ("FINALIZADO", "FINALIZADO", "#027A48", 100),
    ]

    with _connect() as conn:
        for codigo, nombre, color, orden in estados_documentales:
            conn.execute(
                """
                INSERT OR IGNORE INTO config_estados_documentales
                (codigo, nombre, color, orden, activo)
                VALUES (?, ?, ?, ?, 1)
                """,
                (codigo, nombre, color, orden),
            )

        for codigo, nombre, color, orden in estados_administrativos:
            conn.execute(
                """
                INSERT OR IGNORE INTO config_estados_administrativos
                (codigo, nombre, color, orden, activo)
                VALUES (?, ?, ?, ?, 1)
                """,
                (codigo, nombre, color, orden),
            )

        conn.commit()


def list_catalog(table, active_only=True):
    """
    Lista catálogos de configuración.

    Algunas tablas, como config_tipos_expediente, no tienen columna orden.
    Por eso se determina el ORDER BY según la tabla.
    """
    sql = f"SELECT * FROM {table}"
    params = []

    if active_only:
        sql += " WHERE activo = ?"
        params.append(1)

    if table == "config_tipos_expediente":
        sql += " ORDER BY nombre ASC"
    else:
        sql += " ORDER BY orden ASC, nombre ASC"

    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql, params).fetchall()]


def get_tipos_expediente():
    return list_catalog("config_tipos_expediente", active_only=True)


def get_subtipos_expediente(tipo_expediente_id=None, active_only=True):
    initialize_expedients_schema()
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
        return [_dict(r) for r in conn.execute(sql, params).fetchall()]


def get_prioridades():
    return list_catalog("config_prioridades", active_only=True)


def get_estados_documentales():
    return list_catalog("config_estados_documentales", active_only=True)


def get_estados_administrativos():
    return list_catalog("config_estados_administrativos", active_only=True)


def get_clientes_for_select():
    """
    Clientes mínimos para selector de expediente.
    No modifica Clientes ni depende de la vista CRM.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, nombre, primer_apellido, segundo_apellido, nie, pasaporte, dni
            FROM clientes
            WHERE COALESCE(activo, 1) = 1
            ORDER BY nombre ASC, primer_apellido ASC, segundo_apellido ASC
            """
        ).fetchall()

    result = []
    for r in rows:
        item = _dict(r)
        nombre = " ".join(
            [
                item.get("nombre") or "",
                item.get("primer_apellido") or "",
                item.get("segundo_apellido") or "",
            ]
        ).strip() or f"CLIENTE {item['id']}"
        documento = item.get("nie") or item.get("pasaporte") or item.get("dni") or ""
        item["display"] = f"{item['id']} - {nombre}" + (f" · {documento}" if documento else "")
        result.append(item)

    return result


def _next_numero_expediente():
    year = date.today().year
    prefix = f"EXP-{year}-"
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT numero_expediente
            FROM expedientes
            WHERE numero_expediente LIKE ?
            ORDER BY numero_expediente DESC
            LIMIT 1
            """,
            (prefix + "%",),
        ).fetchone()

    if not row:
        return prefix + "0001"

    try:
        last_number = int(row["numero_expediente"].split("-")[-1])
    except Exception:
        last_number = 0

    return prefix + str(last_number + 1).zfill(4)


def create_expediente(data):
    numero = _normalize_text(data.get("numero_expediente")) or _next_numero_expediente()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO expedientes (
                cliente_id,
                numero_expediente,
                numero_expediente_mercurio,
                tipo_expediente_id,
                subtipo_expediente_id,
                subtipo_expediente,
                estado_documental_id,
                estado_administrativo_id,
                estado_presentacion,
                prioridad_id,
                responsable,
                fecha_apertura,
                fecha_presentacion,
                fecha_resolucion,
                numero_registro,
                organo_presentacion,
                provincia,
                observaciones,
                observaciones_internas,
                box_folder_path,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(data.get("cliente_id")),
                numero,
                _normalize_text(data.get("numero_expediente_mercurio")),
                _int_or_none(data.get("tipo_expediente_id")),
                _int_or_none(data.get("subtipo_expediente_id")),
                _normalize_text(data.get("subtipo_expediente")),
                _int_or_none(data.get("estado_documental_id")),
                _int_or_none(data.get("estado_administrativo_id")),
                _normalize_text(data.get("estado_presentacion") or "NO PRESENTADO"),
                _int_or_none(data.get("prioridad_id")),
                _normalize_text(data.get("responsable")),
                _date_or_none(data.get("fecha_apertura")),
                _date_or_none(data.get("fecha_presentacion")),
                _date_or_none(data.get("fecha_resolucion")),
                _normalize_text(data.get("numero_registro")),
                _normalize_text(data.get("organo_presentacion")),
                _normalize_text(data.get("provincia")),
                (data.get("observaciones") or "").strip(),
                (data.get("observaciones_internas") or "").strip(),
                (data.get("box_folder_path") or "").strip(),
                int(data.get("activo", 1)),
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_expediente(expediente_id, data):
    with _connect() as conn:
        conn.execute(
            """
            UPDATE expedientes
            SET cliente_id = ?,
                numero_expediente = ?,
                numero_expediente_mercurio = ?,
                tipo_expediente_id = ?,
                subtipo_expediente_id = ?,
                subtipo_expediente = ?,
                estado_documental_id = ?,
                estado_administrativo_id = ?,
                estado_presentacion = ?,
                prioridad_id = ?,
                responsable = ?,
                fecha_apertura = ?,
                fecha_presentacion = ?,
                fecha_resolucion = ?,
                numero_registro = ?,
                organo_presentacion = ?,
                provincia = ?,
                observaciones = ?,
                observaciones_internas = ?,
                box_folder_path = ?,
                activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(data.get("cliente_id")),
                _normalize_text(data.get("numero_expediente")),
                _normalize_text(data.get("numero_expediente_mercurio")),
                _int_or_none(data.get("tipo_expediente_id")),
                _int_or_none(data.get("subtipo_expediente_id")),
                _normalize_text(data.get("subtipo_expediente")),
                _int_or_none(data.get("estado_documental_id")),
                _int_or_none(data.get("estado_administrativo_id")),
                _normalize_text(data.get("estado_presentacion") or "NO PRESENTADO"),
                _int_or_none(data.get("prioridad_id")),
                _normalize_text(data.get("responsable")),
                _date_or_none(data.get("fecha_apertura")),
                _date_or_none(data.get("fecha_presentacion")),
                _date_or_none(data.get("fecha_resolucion")),
                _normalize_text(data.get("numero_registro")),
                _normalize_text(data.get("organo_presentacion")),
                _normalize_text(data.get("provincia")),
                (data.get("observaciones") or "").strip(),
                (data.get("observaciones_internas") or "").strip(),
                (data.get("box_folder_path") or "").strip(),
                int(data.get("activo", 1)),
                int(expediente_id),
            ),
        )
        conn.commit()


def archive_expediente(expediente_id):
    with _connect() as conn:
        conn.execute(
            """
            UPDATE expedientes
            SET activo = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(expediente_id),),
        )
        conn.commit()


def get_expediente(expediente_id):
    sql = _base_query() + " WHERE e.id = ?"
    with _connect() as conn:
        return _dict(conn.execute(sql, (int(expediente_id),)).fetchone())


def get_expedientes(cliente_id=None, active_only=True):
    sql = _base_query()
    params = []
    conditions = []

    if active_only:
        conditions.append("e.activo = 1")

    if cliente_id:
        conditions.append("e.cliente_id = ?")
        params.append(int(cliente_id))

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY e.created_at DESC, e.id DESC"

    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql, params).fetchall()]


def search_expedientes(filters=None):
    filters = filters or {}
    sql = _base_query()
    params = []
    conditions = []

    if filters.get("active_only", True):
        conditions.append("e.activo = 1")

    if filters.get("cliente_id"):
        conditions.append("e.cliente_id = ?")
        params.append(int(filters["cliente_id"]))

    if filters.get("tipo_expediente_id"):
        conditions.append("e.tipo_expediente_id = ?")
        params.append(int(filters["tipo_expediente_id"]))

    if filters.get("subtipo_expediente_id"):
        conditions.append("e.subtipo_expediente_id = ?")
        params.append(int(filters["subtipo_expediente_id"]))

    if filters.get("estado_documental_id"):
        conditions.append("e.estado_documental_id = ?")
        params.append(int(filters["estado_documental_id"]))

    if filters.get("estado_administrativo_id"):
        conditions.append("e.estado_administrativo_id = ?")
        params.append(int(filters["estado_administrativo_id"]))

    if filters.get("prioridad_id"):
        conditions.append("e.prioridad_id = ?")
        params.append(int(filters["prioridad_id"]))

    text = (filters.get("text") or "").strip().upper()
    if text:
        conditions.append(
            """
            (
                e.numero_expediente LIKE ?
                OR COALESCE(e.subtipo_expediente, '') LIKE ?
                OR COALESCE(e.responsable, '') LIKE ?
                OR COALESCE(e.numero_registro, '') LIKE ?
                OR COALESCE(c.nombre, '') LIKE ?
                OR COALESCE(c.primer_apellido, '') LIKE ?
                OR COALESCE(c.segundo_apellido, '') LIKE ?
                OR COALESCE(c.nie, '') LIKE ?
                OR COALESCE(c.pasaporte, '') LIKE ?
                OR COALESCE(c.dni, '') LIKE ?
                OR COALESCE(e.box_folder_path, '') LIKE ?
            )
            """
        )
        like = f"%{text}%"
        params.extend([like] * 11)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY e.created_at DESC, e.id DESC"

    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql, params).fetchall()]


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _base_query():
    return """
        SELECT
            e.*,
            c.nombre AS cliente_nombre,
            c.primer_apellido AS cliente_primer_apellido,
            c.segundo_apellido AS cliente_segundo_apellido,
            c.nie AS cliente_nie,
            c.pasaporte AS cliente_pasaporte,
            c.dni AS cliente_dni,
            te.nombre AS tipo_expediente_nombre,
            st.nombre AS subtipo_expediente_nombre,
            st.codigo AS subtipo_expediente_codigo,
            ed.nombre AS estado_documental_nombre,
            ed.color AS estado_documental_color,
            ea.nombre AS estado_administrativo_nombre,
            ea.color AS estado_administrativo_color,
            p.nombre AS prioridad_nombre,
            p.color AS prioridad_color
        FROM expedientes e
        JOIN clientes c ON c.id = e.cliente_id
        LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente st ON st.id = e.subtipo_expediente_id
        LEFT JOIN config_estados_documentales ed ON ed.id = e.estado_documental_id
        LEFT JOIN config_estados_administrativos ea ON ea.id = e.estado_administrativo_id
        LEFT JOIN config_prioridades p ON p.id = e.prioridad_id
    """


def cliente_nombre_from_expediente(expediente):
    return " ".join(
        [
            expediente.get("cliente_nombre") or "",
            expediente.get("cliente_primer_apellido") or "",
            expediente.get("cliente_segundo_apellido") or "",
        ]
    ).strip()


def calcular_estado_cliente(cliente_id):
    """
    Propuesta funcional para estado dinámico del cliente.

    En fase 1 NO actualiza la tabla clientes.
    Devuelve un estado calculado desde expedientes.

    Fase futura:
    - incorporar cobros vencidos
    - incorporar documentos pendientes
    - incorporar alertas Box/OCR
    """
    expedientes = get_expedientes(cliente_id=cliente_id, active_only=True)

    if not expedientes:
        return "SIN EXPEDIENTE ACTIVO"

    admin_states = {
        (e.get("estado_administrativo_nombre") or "").upper()
        for e in expedientes
    }

    doc_states = {
        (e.get("estado_documental_nombre") or "").upper()
        for e in expedientes
    }

    if "REQUERIDO" in admin_states:
        return "PENDIENTE DOCUMENTACIÓN"

    if "PRESENTADO" in admin_states or "ADMITIDO" in admin_states or "EN TRÁMITE" in admin_states:
        return "EN TRAMITACIÓN"

    if "EN PREPARACIÓN" in admin_states or "NO PRESENTADO" in admin_states:
        return "EXPEDIENTE ABIERTO"

    if "DOCUMENTACIÓN INCOMPLETA" in doc_states or "PENDIENTE DE DOCUMENTACIÓN" in doc_states:
        return "PENDIENTE DE DOCUMENTACIÓN"

    final_states = {"FINALIZADO", "ARCHIVADO", "RESUELTO FAVORABLE", "RESUELTO DENEGADO"}
    if admin_states and admin_states.issubset(final_states):
        return "FINALIZADO"

    return "EXPEDIENTE ABIERTO"


# === QUESADA MERCURIO BOX PRECHECK START ===

PARA_PRESENTAR_FOLDER_NAME = "PARA PRESENTAR"


def _norm_box_path(value):
    return str(value or "").replace("\\", "/").rstrip("/")


def _folder_url_from_path(path):
    """
    En fase local Box Drive no tenemos URL cloud de Box.
    Guardamos una referencia abrible localmente. En futuro se podrá sustituir por URL/API Box.
    """
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        p = Path(raw)
        if p.exists():
            return p.resolve().as_uri()
    except Exception:
        pass
    return raw


def _find_para_presentar_in_disk(root_path):
    """
    Fallback solo lectura: comprueba si existe subcarpeta directa PARA PRESENTAR.
    No crea carpetas, no mueve archivos, no escribe en Box.
    """
    try:
        root = Path(str(root_path or "").strip())
        if not root.exists() or not root.is_dir():
            return None
        for child in root.iterdir():
            try:
                if child.is_dir() and child.name.strip().upper() == PARA_PRESENTAR_FOLDER_NAME:
                    return {
                        "id": None,
                        "ruta": str(child),
                        "nombre_carpeta": child.name,
                        "source": "disk_readonly",
                    }
            except Exception:
                continue
    except Exception:
        return None
    return None


def get_expediente_mercurio_box_status(expediente_id, persist=True):
    """
    Detecta estructura documental previa a Mercurio.

    Reglas:
    - lee expediente.box_folder_path;
    - busca subcarpeta directa exacta PARA PRESENTAR;
    - mayúsculas/minúsculas indiferentes;
    - ignora espacios laterales;
    - solo acepta carpetas;
    - no modifica Box;
    - opcionalmente persiste ids/urls detectados en expedientes.
    """
    initialize_expedients_schema()
    expediente = get_expediente(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    root_path = str(expediente.get("box_folder_path") or "").strip()
    root_norm = _norm_box_path(root_path)

    result = {
        "expediente_id": int(expediente_id),
        "box_root_folder_id": None,
        "box_root_folder_path": root_path,
        "box_root_folder_url": _folder_url_from_path(root_path),
        "box_para_presentar_folder_id": None,
        "box_para_presentar_folder_path": "",
        "box_para_presentar_folder_url": "",
        "tiene_carpeta_para_presentar": False,
        "estado": "SIN_RUTA_BOX" if not root_path else "FALTA_PARA_PRESENTAR",
        "mensaje": "El expediente no tiene ruta Box vinculada" if not root_path else "Falta carpeta PARA PRESENTAR",
    }

    if not root_path:
        if persist:
            _persist_mercurio_box_status(result)
        return result

    with _connect() as conn:
        root_row = conn.execute(
            """
            SELECT id, ruta, nombre_carpeta
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
              AND REPLACE(ruta, char(92), '/') = ?
            LIMIT 1
            """,
            (root_norm,),
        ).fetchone()

        child_row = conn.execute(
            """
            SELECT id, ruta, nombre_carpeta
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
              AND REPLACE(ruta, char(92), '/') LIKE ?
              AND INSTR(SUBSTR(REPLACE(ruta, char(92), '/'), LENGTH(?) + 2), '/') = 0
              AND UPPER(TRIM(nombre_carpeta)) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (root_norm + "/%", root_norm, PARA_PRESENTAR_FOLDER_NAME),
        ).fetchone()

    if root_row:
        root_dict = _dict(root_row)
        result["box_root_folder_id"] = root_dict.get("id")
        result["box_root_folder_path"] = root_dict.get("ruta") or root_path
        result["box_root_folder_url"] = _folder_url_from_path(result["box_root_folder_path"])

    if child_row:
        child = _dict(child_row)
    else:
        child = _find_para_presentar_in_disk(root_path)

    if child:
        result["box_para_presentar_folder_id"] = child.get("id")
        result["box_para_presentar_folder_path"] = child.get("ruta") or ""
        result["box_para_presentar_folder_url"] = _folder_url_from_path(result["box_para_presentar_folder_path"])
        result["tiene_carpeta_para_presentar"] = True
        result["estado"] = "OK"
        result["mensaje"] = "Carpeta PARA PRESENTAR encontrada"

    if persist:
        _persist_mercurio_box_status(result)

    return result


def _persist_mercurio_box_status(status):
    with _connect() as conn:
        conn.execute(
            """
            UPDATE expedientes
            SET box_root_folder_id = ?,
                box_root_folder_url = ?,
                box_para_presentar_folder_id = ?,
                box_para_presentar_folder_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status.get("box_root_folder_id"),
                status.get("box_root_folder_url") or "",
                status.get("box_para_presentar_folder_id"),
                status.get("box_para_presentar_folder_url") or "",
                int(status.get("expediente_id")),
            ),
        )
        conn.commit()


def scan_expediente_box_folder(expediente_id, calculate_hash=False):
    """
    Escaneo individual de la ruta Box del expediente.

    Uso previsto: al abrir la ficha del expediente.
    Seguridad: solo lectura sobre Box. No crea, no mueve, no borra, no renombra.
    """
    expediente = get_expediente(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    root_path = str(expediente.get("box_folder_path") or "").strip()
    if not root_path:
        return {
            "scanned": False,
            "reason": "SIN_RUTA_BOX",
            "status": get_expediente_mercurio_box_status(expediente_id, persist=True),
        }

    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return {
            "scanned": False,
            "reason": "RUTA_NO_EXISTE",
            "status": get_expediente_mercurio_box_status(expediente_id, persist=True),
        }

    from backend.services import box_watch_service

    scan_result = box_watch_service.scan_local_box_path(
        str(root),
        progress_callback=None,
        calculate_hash=bool(calculate_hash),
    )
    status = get_expediente_mercurio_box_status(expediente_id, persist=True)

    return {
        "scanned": True,
        "reason": "OK",
        "scan_result": scan_result,
        "status": status,
    }


def validate_expediente_para_presentar_ready(expediente_id):
    status = get_expediente_mercurio_box_status(expediente_id, persist=True)
    if not status.get("tiene_carpeta_para_presentar"):
        raise ValueError(
            'No se puede iniciar la presentación.\n'
            'El expediente no dispone de carpeta "PARA PRESENTAR" en Box.'
        )
    return status


def open_box_folder_path(folder_path):
    """
    Abre carpeta local Box Drive. No modifica Box.
    """
    import os
    import subprocess
    import sys

    path = Path(str(folder_path or "").strip())
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"No existe la carpeta: {path}")

    if sys.platform.startswith("win"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])

    return True

# === QUESADA MERCURIO BOX PRECHECK END ===
