"""
Dominio universal de tareas del ERP Quesada Abogados.

Principios:

- `tasks` es la fuente de verdad del trabajo programado.
- El calendario será una proyección de las tareas.
- Telegram se implementará como una outbox independiente.
- Una tarea activa siempre posee fecha de vencimiento.
- `VENCIDA` no se almacena como estado:
  se calcula a partir de fecha_vencimiento y estado.
- `source_key` permite idempotencia para tareas automáticas.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_EN_CURSO = "EN_CURSO"
ESTADO_COMPLETADA = "COMPLETADA"
ESTADO_CANCELADA = "CANCELADA"

VALID_STATES = {
    ESTADO_PENDIENTE,
    ESTADO_EN_CURSO,
    ESTADO_COMPLETADA,
    ESTADO_CANCELADA,
}


PRIORIDAD_BAJA = "BAJA"
PRIORIDAD_NORMAL = "NORMAL"
PRIORIDAD_ALTA = "ALTA"
PRIORIDAD_URGENTE = "URGENTE"

VALID_PRIORITIES = {
    PRIORIDAD_BAJA,
    PRIORIDAD_NORMAL,
    PRIORIDAD_ALTA,
    PRIORIDAD_URGENTE,
}


ORIGEN_MANUAL = "MANUAL"
ORIGEN_TRAZABILIDAD = "TRAZABILIDAD"
ORIGEN_DEHU = "DEHU"
ORIGEN_EXPEDIENTE = "EXPEDIENTE"
ORIGEN_CAA = "CAA"
ORIGEN_DOCUMENTO = "DOCUMENTO"
ORIGEN_SISTEMA = "SISTEMA"


def _connect(db_path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def _connection(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    owns_connection = conn is None
    connection = (
        conn
        if conn is not None
        else _connect(db_path)
    )

    try:
        yield connection

        if owns_connection:
            connection.commit()

    except Exception:
        if owns_connection:
            connection.rollback()
        raise

    finally:
        if owns_connection:
            connection.close()


def _dict(row):
    return dict(row) if row else None


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _optional_int(value):
    if value in (None, ""):
        return None

    return int(value)


def _normalize_datetime(value):
    """
    Conserva ISO-8601 como representación interna.

    Acepta:
    - datetime
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM
    - YYYY-MM-DD HH:MM:SS
    - YYYY-MM-DDTHH:MM
    - YYYY-MM-DDTHH:MM:SS
    """

    if isinstance(value, datetime):
        return value.replace(
            microsecond=0
        ).isoformat(
            sep=" "
        )

    raw = _text(value)

    if not raw:
        return ""

    candidates = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    )

    for pattern in candidates:
        try:
            parsed = datetime.strptime(
                raw,
                pattern,
            )

            return parsed.isoformat(
                sep=" "
            )

        except ValueError:
            continue

    raise ValueError(
        "Fecha/hora no válida. "
        "Debe utilizar formato ISO "
        "YYYY-MM-DD o YYYY-MM-DD HH:MM."
    )


def _parse_datetime(value):
    raw = _text(value)

    if not raw:
        return None

    try:
        return datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )
    except ValueError:
        return None


def ensure_task_schema(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                cliente_id INTEGER,
                expediente_id INTEGER,

                titulo TEXT NOT NULL,
                descripcion TEXT,

                tipo TEXT NOT NULL
                    DEFAULT 'GENERAL',

                prioridad TEXT NOT NULL
                    DEFAULT 'NORMAL'
                    CHECK (
                        prioridad IN (
                            'BAJA',
                            'NORMAL',
                            'ALTA',
                            'URGENTE'
                        )
                    ),

                estado TEXT NOT NULL
                    DEFAULT 'PENDIENTE'
                    CHECK (
                        estado IN (
                            'PENDIENTE',
                            'EN_CURSO',
                            'COMPLETADA',
                            'CANCELADA'
                        )
                    ),

                responsable TEXT,

                fecha_inicio TEXT,
                fecha_vencimiento TEXT NOT NULL,

                origen_tipo TEXT NOT NULL
                    DEFAULT 'MANUAL',
                origen_id TEXT,

                source_key TEXT,

                created_by TEXT,

                completada_at TEXT,
                cancelada_at TEXT,

                activo INTEGER NOT NULL
                    DEFAULT 1,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id),

                FOREIGN KEY (expediente_id)
                    REFERENCES expedientes(id)
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_tasks_estado_vencimiento
            ON tasks(
                activo,
                estado,
                fecha_vencimiento
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_tasks_cliente
            ON tasks(cliente_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_tasks_expediente
            ON tasks(expediente_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_tasks_responsable
            ON tasks(responsable)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_tasks_origen
            ON tasks(
                origen_tipo,
                origen_id
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_tasks_source_key
            ON tasks(source_key)
            WHERE
                source_key IS NOT NULL
                AND TRIM(source_key) <> ''
            """
        )


def _validate_task_payload(
    *,
    titulo,
    fecha_vencimiento,
    prioridad,
    estado,
):
    clean_title = _text(titulo)

    if not clean_title:
        raise ValueError(
            "La tarea necesita un título."
        )

    clean_due_at = _normalize_datetime(
        fecha_vencimiento
    )

    if not clean_due_at:
        raise ValueError(
            "La tarea necesita fecha de vencimiento."
        )

    clean_priority = (
        _upper(prioridad)
        or PRIORIDAD_NORMAL
    )

    if clean_priority not in VALID_PRIORITIES:
        raise ValueError(
            "Prioridad no válida: "
            f"{clean_priority}"
        )

    clean_state = (
        _upper(estado)
        or ESTADO_PENDIENTE
    )

    if clean_state not in VALID_STATES:
        raise ValueError(
            "Estado de tarea no válido: "
            f"{clean_state}"
        )

    return {
        "titulo": clean_title,
        "fecha_vencimiento": clean_due_at,
        "prioridad": clean_priority,
        "estado": clean_state,
    }


def create_task(
    *,
    titulo,
    fecha_vencimiento,
    descripcion="",
    cliente_id=None,
    expediente_id=None,
    tipo="GENERAL",
    prioridad=PRIORIDAD_NORMAL,
    estado=ESTADO_PENDIENTE,
    responsable="",
    fecha_inicio="",
    origen_tipo=ORIGEN_MANUAL,
    origen_id="",
    source_key="",
    created_by="ERP",
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Crea una tarea.

    Si `source_key` ya existe, devuelve la tarea existente
    y `created=False`. Esto permite que los automatismos
    sean idempotentes.
    """

    validated = _validate_task_payload(
        titulo=titulo,
        fecha_vencimiento=fecha_vencimiento,
        prioridad=prioridad,
        estado=estado,
    )

    clean_source_key = _text(source_key)

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_task_schema(
            conn=connection,
            db_path=db_path,
        )

        if clean_source_key:
            existing = connection.execute(
                """
                SELECT *
                FROM tasks
                WHERE source_key = ?
                LIMIT 1
                """,
                (clean_source_key,),
            ).fetchone()

            if existing:
                return {
                    "created": False,
                    "task": _decorate_task(
                        dict(existing)
                    ),
                }

        cursor = connection.execute(
            """
            INSERT INTO tasks (
                cliente_id,
                expediente_id,

                titulo,
                descripcion,
                tipo,

                prioridad,
                estado,
                responsable,

                fecha_inicio,
                fecha_vencimiento,

                origen_tipo,
                origen_id,
                source_key,

                created_by
            )
            VALUES (
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                _optional_int(cliente_id),
                _optional_int(expediente_id),

                validated["titulo"],
                _text(descripcion),
                _upper(tipo) or "GENERAL",

                validated["prioridad"],
                validated["estado"],
                _text(responsable),

                (
                    _normalize_datetime(
                        fecha_inicio
                    )
                    if _text(fecha_inicio)
                    else None
                ),
                validated[
                    "fecha_vencimiento"
                ],

                (
                    _upper(origen_tipo)
                    or ORIGEN_MANUAL
                ),
                _text(origen_id),
                clean_source_key or None,

                _text(created_by) or "ERP",
            ),
        )

        task_id = int(
            cursor.lastrowid
        )

        return {
            "created": True,
            "task": get_task(
                task_id,
                conn=connection,
                db_path=db_path,
            ),
        }


def get_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_task_schema(
            conn=connection,
            db_path=db_path,
        )

        row = connection.execute(
            """
            SELECT
                t.*,

                c.nombre
                    AS cliente_nombre,
                c.primer_apellido
                    AS cliente_primer_apellido,
                c.segundo_apellido
                    AS cliente_segundo_apellido,

                e.numero_expediente
                    AS numero_expediente

            FROM tasks t

            LEFT JOIN clientes c
              ON c.id = t.cliente_id

            LEFT JOIN expedientes e
              ON e.id = t.expediente_id

            WHERE t.id = ?
            """,
            (int(task_id),),
        ).fetchone()

        if not row:
            return None

        return _decorate_task(
            dict(row)
        )


def update_task(
    task_id,
    *,
    titulo=None,
    descripcion=None,
    cliente_id=None,
    expediente_id=None,
    tipo=None,
    prioridad=None,
    responsable=None,
    fecha_inicio=None,
    fecha_vencimiento=None,
    origen_tipo=None,
    origen_id=None,
    source_key=None,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_task_schema(
            conn=connection,
            db_path=db_path,
        )

        current = connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE id = ?
            """,
            (int(task_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "Tarea no encontrada."
            )

        current = dict(current)

        new_title = (
            _text(titulo)
            if titulo is not None
            else current["titulo"]
        )

        new_due_at = (
            _normalize_datetime(
                fecha_vencimiento
            )
            if fecha_vencimiento is not None
            else current["fecha_vencimiento"]
        )

        new_priority = (
            _upper(prioridad)
            if prioridad is not None
            else current["prioridad"]
        )

        validated = _validate_task_payload(
            titulo=new_title,
            fecha_vencimiento=new_due_at,
            prioridad=new_priority,
            estado=current["estado"],
        )

        if source_key is None:
            new_source_key = (
                current["source_key"]
            )
        else:
            new_source_key = (
                _text(source_key)
                or None
            )

        connection.execute(
            """
            UPDATE tasks
            SET
                cliente_id = ?,
                expediente_id = ?,

                titulo = ?,
                descripcion = ?,
                tipo = ?,

                prioridad = ?,
                responsable = ?,

                fecha_inicio = ?,
                fecha_vencimiento = ?,

                origen_tipo = ?,
                origen_id = ?,
                source_key = ?,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE id = ?
            """,
            (
                (
                    _optional_int(cliente_id)
                    if cliente_id is not None
                    else current[
                        "cliente_id"
                    ]
                ),
                (
                    _optional_int(expediente_id)
                    if expediente_id is not None
                    else current[
                        "expediente_id"
                    ]
                ),

                validated["titulo"],
                (
                    _text(descripcion)
                    if descripcion is not None
                    else current["descripcion"]
                ),
                (
                    _upper(tipo)
                    if tipo is not None
                    else current["tipo"]
                ),

                validated["prioridad"],
                (
                    _text(responsable)
                    if responsable is not None
                    else current["responsable"]
                ),

                (
                    _normalize_datetime(
                        fecha_inicio
                    )
                    if (
                        fecha_inicio is not None
                        and _text(fecha_inicio)
                    )
                    else (
                        None
                        if fecha_inicio == ""
                        else current[
                            "fecha_inicio"
                        ]
                    )
                ),
                validated[
                    "fecha_vencimiento"
                ],

                (
                    _upper(origen_tipo)
                    if origen_tipo is not None
                    else current[
                        "origen_tipo"
                    ]
                ),
                (
                    _text(origen_id)
                    if origen_id is not None
                    else current[
                        "origen_id"
                    ]
                ),
                new_source_key,

                int(task_id),
            ),
        )

        return get_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )


def start_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_task_state(
        task_id,
        ESTADO_EN_CURSO,
        conn=conn,
        db_path=db_path,
    )


def complete_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_task_state(
        task_id,
        ESTADO_COMPLETADA,
        conn=conn,
        db_path=db_path,
    )


def cancel_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_task_state(
        task_id,
        ESTADO_CANCELADA,
        conn=conn,
        db_path=db_path,
    )


def reopen_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_task_state(
        task_id,
        ESTADO_PENDIENTE,
        conn=conn,
        db_path=db_path,
    )


def _set_task_state(
    task_id,
    new_state,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    normalized_state = _upper(
        new_state
    )

    if normalized_state not in VALID_STATES:
        raise ValueError(
            "Estado de tarea no válido."
        )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_task_schema(
            conn=connection,
            db_path=db_path,
        )

        current = connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE id = ?
            """,
            (int(task_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "Tarea no encontrada."
            )

        completed_sql = (
            "CURRENT_TIMESTAMP"
            if normalized_state
            == ESTADO_COMPLETADA
            else "NULL"
        )

        cancelled_sql = (
            "CURRENT_TIMESTAMP"
            if normalized_state
            == ESTADO_CANCELADA
            else "NULL"
        )

        connection.execute(
            f"""
            UPDATE tasks
            SET
                estado = ?,
                completada_at =
                    {completed_sql},
                cancelada_at =
                    {cancelled_sql},
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized_state,
                int(task_id),
            ),
        )

        return get_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )


def archive_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_task_schema(
            conn=connection,
            db_path=db_path,
        )

        cursor = connection.execute(
            """
            UPDATE tasks
            SET
                activo = 0,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(task_id),),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "Tarea no encontrada."
            )

        return get_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )


def _decorate_task(
    task,
    *,
    now=None,
):
    if not task:
        return task

    result = dict(task)

    current = now or datetime.now()

    due_at = _parse_datetime(
        result.get(
            "fecha_vencimiento"
        )
    )

    estado = _upper(
        result.get("estado")
    )

    is_open = estado in {
        ESTADO_PENDIENTE,
        ESTADO_EN_CURSO,
    }

    result["vencida"] = bool(
        is_open
        and due_at
        and due_at < current
    )

    result["abierta"] = is_open

    return result


def list_tasks(
    *,
    estado=None,
    cliente_id=None,
    expediente_id=None,
    responsable=None,
    prioridad=None,
    due_from=None,
    due_to=None,
    include_archived=False,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_task_schema(
            conn=connection,
            db_path=db_path,
        )

        sql = """
            SELECT
                t.*,

                c.nombre
                    AS cliente_nombre,
                c.primer_apellido
                    AS cliente_primer_apellido,
                c.segundo_apellido
                    AS cliente_segundo_apellido,

                e.numero_expediente
                    AS numero_expediente

            FROM tasks t

            LEFT JOIN clientes c
              ON c.id = t.cliente_id

            LEFT JOIN expedientes e
              ON e.id = t.expediente_id

            WHERE 1 = 1
        """

        params = []

        if not include_archived:
            sql += """
                AND t.activo = 1
            """

        if estado:
            sql += """
                AND t.estado = ?
            """
            params.append(
                _upper(estado)
            )

        if cliente_id is not None:
            sql += """
                AND t.cliente_id = ?
            """
            params.append(
                int(cliente_id)
            )

        if expediente_id is not None:
            sql += """
                AND t.expediente_id = ?
            """
            params.append(
                int(expediente_id)
            )

        if responsable:
            sql += """
                AND UPPER(
                    TRIM(
                        COALESCE(
                            t.responsable,
                            ''
                        )
                    )
                ) = ?
            """
            params.append(
                _upper(responsable)
            )

        if prioridad:
            sql += """
                AND t.prioridad = ?
            """
            params.append(
                _upper(prioridad)
            )

        if due_from:
            sql += """
                AND datetime(
                    t.fecha_vencimiento
                ) >= datetime(?)
            """
            params.append(
                _normalize_datetime(
                    due_from
                )
            )

        if due_to:
            sql += """
                AND datetime(
                    t.fecha_vencimiento
                ) <= datetime(?)
            """
            params.append(
                _normalize_datetime(
                    due_to
                )
            )

        sql += """
            ORDER BY
                CASE t.prioridad
                    WHEN 'URGENTE'
                        THEN 10
                    WHEN 'ALTA'
                        THEN 20
                    WHEN 'NORMAL'
                        THEN 30
                    WHEN 'BAJA'
                        THEN 40
                    ELSE 99
                END,
                datetime(
                    t.fecha_vencimiento
                ) ASC,
                t.id ASC
        """

        rows = connection.execute(
            sql,
            params,
        ).fetchall()

        return [
            _decorate_task(
                dict(row)
            )
            for row in rows
        ]


def list_overdue_tasks(
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    items = list_tasks(
        conn=conn,
        db_path=db_path,
    )

    return [
        item
        for item in items
        if item.get("vencida")
    ]
