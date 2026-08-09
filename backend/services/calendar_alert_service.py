"""
Avisos temporales del calendario.

Diferencia fundamental:

TASK
    = trabajo que debe ejecutarse.

CALENDAR ALERT
    = información que debe recordarse o vigilarse.

Ejemplo:

TASK:
    Presentar expediente
    2026-01-13

ALERT:
    Los antecedentes penales caducan
    2026-01-14

Ambos podrán mostrarse posteriormente en una única
vista de calendario y generar avisos por Telegram.
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


ESTADO_ACTIVO = "ACTIVO"
ESTADO_RESUELTO = "RESUELTO"
ESTADO_CANCELADO = "CANCELADO"

VALID_STATES = {
    ESTADO_ACTIVO,
    ESTADO_RESUELTO,
    ESTADO_CANCELADO,
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
ORIGEN_DOCUMENTO = "DOCUMENTO"
ORIGEN_DEHU = "DEHU"
ORIGEN_EXPEDIENTE = "EXPEDIENTE"
ORIGEN_SISTEMA = "SISTEMA"


def _connect(db_path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

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


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _optional_int(value):
    if value in (None, ""):
        return None

    return int(value)


def _normalize_datetime(
    value,
    *,
    required=False,
):
    if isinstance(value, datetime):
        return value.replace(
            microsecond=0
        ).isoformat(
            sep=" "
        )

    raw = _text(value)

    if not raw:
        if required:
            raise ValueError(
                "La fecha es obligatoria."
            )

        return None

    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    )

    for pattern in formats:
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
        "Debe utilizar formato ISO."
    )


def ensure_calendar_alert_schema(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
                calendar_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    cliente_id INTEGER,
                    expediente_id INTEGER,
                    documento_id INTEGER,

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
                        DEFAULT 'ACTIVO'
                        CHECK (
                            estado IN (
                                'ACTIVO',
                                'RESUELTO',
                                'CANCELADO'
                            )
                        ),

                    fecha_evento TEXT NOT NULL,
                    fecha_inicio_aviso TEXT,

                    origen_tipo TEXT NOT NULL
                        DEFAULT 'MANUAL',
                    origen_id TEXT,

                    source_key TEXT,

                    created_by TEXT,

                    resolved_at TEXT,
                    cancelled_at TEXT,

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
                idx_calendar_alerts_event
            ON calendar_alerts(
                activo,
                estado,
                fecha_evento
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_calendar_alerts_cliente
            ON calendar_alerts(cliente_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_calendar_alerts_expediente
            ON calendar_alerts(expediente_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_calendar_alerts_origen
            ON calendar_alerts(
                origen_tipo,
                origen_id
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_calendar_alerts_source_key
            ON calendar_alerts(source_key)
            WHERE
                source_key IS NOT NULL
                AND TRIM(source_key) <> ''
            """
        )


def _decorate_alert(alert):
    if not alert:
        return None

    result = dict(alert)

    result["abierto"] = (
        result.get("activo") == 1
        and result.get("estado")
        == ESTADO_ACTIVO
    )

    return result


def get_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_calendar_alert_schema(
            conn=connection,
            db_path=db_path,
        )

        row = connection.execute(
            """
            SELECT
                a.*,

                c.nombre
                    AS cliente_nombre,

                c.primer_apellido
                    AS cliente_primer_apellido,

                c.segundo_apellido
                    AS cliente_segundo_apellido,

                e.numero_expediente
                    AS numero_expediente

            FROM calendar_alerts a

            LEFT JOIN clientes c
              ON c.id = a.cliente_id

            LEFT JOIN expedientes e
              ON e.id = a.expediente_id

            WHERE a.id = ?
            """,
            (int(alert_id),),
        ).fetchone()

        return (
            _decorate_alert(row)
            if row
            else None
        )


def create_alert(
    *,
    titulo,
    fecha_evento,
    descripcion="",
    cliente_id=None,
    expediente_id=None,
    documento_id=None,
    tipo="GENERAL",
    prioridad=PRIORIDAD_NORMAL,
    fecha_inicio_aviso=None,
    origen_tipo=ORIGEN_MANUAL,
    origen_id="",
    source_key="",
    created_by="ERP",
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    clean_title = _text(titulo)

    if not clean_title:
        raise ValueError(
            "El aviso necesita un título."
        )

    clean_priority = (
        _upper(prioridad)
        or PRIORIDAD_NORMAL
    )

    if clean_priority not in VALID_PRIORITIES:
        raise ValueError(
            "Prioridad de aviso no válida."
        )

    event_at = _normalize_datetime(
        fecha_evento,
        required=True,
    )

    warning_from = _normalize_datetime(
        fecha_inicio_aviso,
        required=False,
    )

    clean_source_key = _text(
        source_key
    )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_calendar_alert_schema(
            conn=connection,
            db_path=db_path,
        )

        if clean_source_key:
            existing = connection.execute(
                """
                SELECT id
                FROM calendar_alerts
                WHERE source_key = ?
                LIMIT 1
                """,
                (clean_source_key,),
            ).fetchone()

            if existing:
                return {
                    "created": False,
                    "alert": get_alert(
                        existing["id"],
                        conn=connection,
                        db_path=db_path,
                    ),
                }

        cursor = connection.execute(
            """
            INSERT INTO calendar_alerts (
                cliente_id,
                expediente_id,
                documento_id,

                titulo,
                descripcion,
                tipo,
                prioridad,

                fecha_evento,
                fecha_inicio_aviso,

                origen_tipo,
                origen_id,
                source_key,

                created_by
            )
            VALUES (
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?
            )
            """,
            (
                _optional_int(cliente_id),
                _optional_int(expediente_id),
                _optional_int(documento_id),

                clean_title,
                _text(descripcion),
                _upper(tipo) or "GENERAL",
                clean_priority,

                event_at,
                warning_from,

                (
                    _upper(origen_tipo)
                    or ORIGEN_MANUAL
                ),
                _text(origen_id),
                (
                    clean_source_key
                    or None
                ),

                _text(created_by) or "ERP",
            ),
        )

        return {
            "created": True,
            "alert": get_alert(
                cursor.lastrowid,
                conn=connection,
                db_path=db_path,
            ),
        }


def update_alert(
    alert_id,
    *,
    titulo=None,
    descripcion=None,
    cliente_id=None,
    expediente_id=None,
    documento_id=None,
    tipo=None,
    prioridad=None,
    fecha_evento=None,
    fecha_inicio_aviso=None,
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

        ensure_calendar_alert_schema(
            conn=connection,
            db_path=db_path,
        )

        current = connection.execute(
            """
            SELECT *
            FROM calendar_alerts
            WHERE id = ?
            """,
            (int(alert_id),),
        ).fetchone()

        if not current:
            raise ValueError(
                "Aviso no encontrado."
            )

        current = dict(current)

        new_title = (
            _text(titulo)
            if titulo is not None
            else current["titulo"]
        )

        if not new_title:
            raise ValueError(
                "El aviso necesita un título."
            )

        new_priority = (
            _upper(prioridad)
            if prioridad is not None
            else current["prioridad"]
        )

        if new_priority not in VALID_PRIORITIES:
            raise ValueError(
                "Prioridad de aviso no válida."
            )

        new_event_at = (
            _normalize_datetime(
                fecha_evento,
                required=True,
            )
            if fecha_evento is not None
            else current["fecha_evento"]
        )

        if fecha_inicio_aviso is None:
            new_warning_from = (
                current["fecha_inicio_aviso"]
            )
        elif _text(fecha_inicio_aviso):
            new_warning_from = (
                _normalize_datetime(
                    fecha_inicio_aviso
                )
            )
        else:
            new_warning_from = None

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
            UPDATE calendar_alerts
            SET
                cliente_id = ?,
                expediente_id = ?,
                documento_id = ?,

                titulo = ?,
                descripcion = ?,
                tipo = ?,
                prioridad = ?,

                fecha_evento = ?,
                fecha_inicio_aviso = ?,

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
                    else current["cliente_id"]
                ),
                (
                    _optional_int(expediente_id)
                    if expediente_id is not None
                    else current["expediente_id"]
                ),
                (
                    _optional_int(documento_id)
                    if documento_id is not None
                    else current["documento_id"]
                ),

                new_title,

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

                new_priority,

                new_event_at,
                new_warning_from,

                (
                    _upper(origen_tipo)
                    if origen_tipo is not None
                    else current["origen_tipo"]
                ),

                (
                    _text(origen_id)
                    if origen_id is not None
                    else current["origen_id"]
                ),

                new_source_key,

                int(alert_id),
            ),
        )

        return get_alert(
            alert_id,
            conn=connection,
            db_path=db_path,
        )


def resolve_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_state(
        alert_id,
        ESTADO_RESUELTO,
        conn=conn,
        db_path=db_path,
    )


def cancel_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_state(
        alert_id,
        ESTADO_CANCELADO,
        conn=conn,
        db_path=db_path,
    )


def reopen_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_state(
        alert_id,
        ESTADO_ACTIVO,
        conn=conn,
        db_path=db_path,
    )


def _set_state(
    alert_id,
    new_state,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    normalized = _upper(
        new_state
    )

    if normalized not in VALID_STATES:
        raise ValueError(
            "Estado de aviso no válido."
        )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_calendar_alert_schema(
            conn=connection,
            db_path=db_path,
        )

        exists = connection.execute(
            """
            SELECT id
            FROM calendar_alerts
            WHERE id = ?
            """,
            (int(alert_id),),
        ).fetchone()

        if not exists:
            raise ValueError(
                "Aviso no encontrado."
            )

        resolved_sql = (
            "CURRENT_TIMESTAMP"
            if normalized == ESTADO_RESUELTO
            else "NULL"
        )

        cancelled_sql = (
            "CURRENT_TIMESTAMP"
            if normalized == ESTADO_CANCELADO
            else "NULL"
        )

        connection.execute(
            f"""
            UPDATE calendar_alerts
            SET
                estado = ?,
                resolved_at =
                    {resolved_sql},
                cancelled_at =
                    {cancelled_sql},
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized,
                int(alert_id),
            ),
        )

        return get_alert(
            alert_id,
            conn=connection,
            db_path=db_path,
        )


def archive_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_calendar_alert_schema(
            conn=connection,
            db_path=db_path,
        )

        cursor = connection.execute(
            """
            UPDATE calendar_alerts
            SET
                activo = 0,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(alert_id),),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "Aviso no encontrado."
            )

        return get_alert(
            alert_id,
            conn=connection,
            db_path=db_path,
        )


def list_alerts(
    *,
    estado=None,
    cliente_id=None,
    expediente_id=None,
    prioridad=None,
    event_from=None,
    event_to=None,
    include_archived=False,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_calendar_alert_schema(
            conn=connection,
            db_path=db_path,
        )

        sql = """
            SELECT
                a.*,

                c.nombre
                    AS cliente_nombre,

                c.primer_apellido
                    AS cliente_primer_apellido,

                c.segundo_apellido
                    AS cliente_segundo_apellido,

                e.numero_expediente
                    AS numero_expediente

            FROM calendar_alerts a

            LEFT JOIN clientes c
              ON c.id = a.cliente_id

            LEFT JOIN expedientes e
              ON e.id = a.expediente_id

            WHERE 1 = 1
        """

        params = []

        if not include_archived:
            sql += """
                AND a.activo = 1
            """

        if estado:
            sql += """
                AND a.estado = ?
            """
            params.append(
                _upper(estado)
            )

        if cliente_id is not None:
            sql += """
                AND a.cliente_id = ?
            """
            params.append(
                int(cliente_id)
            )

        if expediente_id is not None:
            sql += """
                AND a.expediente_id = ?
            """
            params.append(
                int(expediente_id)
            )

        if prioridad:
            sql += """
                AND a.prioridad = ?
            """
            params.append(
                _upper(prioridad)
            )

        if event_from:
            sql += """
                AND datetime(
                    a.fecha_evento
                ) >= datetime(?)
            """
            params.append(
                _normalize_datetime(
                    event_from,
                    required=True,
                )
            )

        if event_to:
            sql += """
                AND datetime(
                    a.fecha_evento
                ) <= datetime(?)
            """
            params.append(
                _normalize_datetime(
                    event_to,
                    required=True,
                )
            )

        sql += """
            ORDER BY
                datetime(
                    a.fecha_evento
                ) ASC,

                CASE a.prioridad
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

                a.id ASC
        """

        return [
            _decorate_alert(row)
            for row in connection.execute(
                sql,
                params,
            ).fetchall()
        ]
