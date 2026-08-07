"""
Outbox universal de notificaciones programadas.

Fuentes soportadas:

TASK
    trabajo ejecutable.

ALERT
    información temporal que debe recordarse.

Canal inicial:

TELEGRAM

El envío físico se implementará posteriormente mediante
telegram_service + worker.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from backend.services import task_service
from backend.services import calendar_alert_service


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


SOURCE_TASK = "TASK"
SOURCE_ALERT = "ALERT"

VALID_SOURCE_TYPES = {
    SOURCE_TASK,
    SOURCE_ALERT,
}


CANAL_TELEGRAM = "TELEGRAM"


ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_PROCESANDO = "PROCESANDO"
ESTADO_ENVIADA = "ENVIADA"
ESTADO_ERROR = "ERROR"
ESTADO_CANCELADA = "CANCELADA"


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


def _normalize_datetime(value):
    if isinstance(value, datetime):
        return value.replace(
            microsecond=0
        ).isoformat(
            sep=" "
        )

    raw = _text(value)

    if not raw:
        raise ValueError(
            "scheduled_at es obligatorio."
        )

    try:
        parsed = datetime.fromisoformat(
            raw.replace("T", " ")
        )

    except ValueError as exc:
        raise ValueError(
            "Fecha/hora de notificación no válida."
        ) from exc

    return parsed.replace(
        microsecond=0
    ).isoformat(
        sep=" "
    )


def ensure_schema(
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
                scheduled_notifications (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,

                    source_type TEXT NOT NULL,

                    source_id INTEGER NOT NULL,

                    canal TEXT NOT NULL
                        DEFAULT 'TELEGRAM',

                    notification_type TEXT NOT NULL,

                    scheduled_at TEXT NOT NULL,

                    estado TEXT NOT NULL
                        DEFAULT 'PENDIENTE',

                    attempt_count INTEGER NOT NULL
                        DEFAULT 0,

                    sent_at TEXT,
                    last_attempt_at TEXT,
                    last_error TEXT,

                    source_key TEXT NOT NULL,

                    activo INTEGER NOT NULL
                        DEFAULT 1,

                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_scheduled_notifications_source_key
            ON scheduled_notifications(source_key)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_scheduled_notifications_due
            ON scheduled_notifications(
                activo,
                estado,
                scheduled_at
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_scheduled_notifications_source
            ON scheduled_notifications(
                source_type,
                source_id
            )
            """
        )


def _source_exists(
    connection,
    source_type,
    source_id,
):
    source_type = _upper(
        source_type
    )

    if source_type == SOURCE_TASK:
        row = connection.execute(
            """
            SELECT id
            FROM tasks
            WHERE id = ?
            """,
            (int(source_id),),
        ).fetchone()

        return bool(row)

    if source_type == SOURCE_ALERT:
        row = connection.execute(
            """
            SELECT id
            FROM calendar_alerts
            WHERE id = ?
            """,
            (int(source_id),),
        ).fetchone()

        return bool(row)

    return False


def create_notification(
    *,
    source_type,
    source_id,
    scheduled_at,
    notification_type,
    source_key,
    canal=CANAL_TELEGRAM,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    clean_source_type = _upper(
        source_type
    )

    if clean_source_type not in VALID_SOURCE_TYPES:
        raise ValueError(
            "source_type no soportado."
        )

    clean_channel = (
        _upper(canal)
        or CANAL_TELEGRAM
    )

    if clean_channel != CANAL_TELEGRAM:
        raise ValueError(
            "Canal no soportado."
        )

    clean_type = _upper(
        notification_type
    )

    if not clean_type:
        raise ValueError(
            "notification_type es obligatorio."
        )

    clean_source_key = _text(
        source_key
    )

    if not clean_source_key:
        raise ValueError(
            "source_key es obligatorio."
        )

    normalized_schedule = (
        _normalize_datetime(
            scheduled_at
        )
    )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        existing = connection.execute(
            """
            SELECT *
            FROM scheduled_notifications
            WHERE source_key = ?
            LIMIT 1
            """,
            (clean_source_key,),
        ).fetchone()

        if existing:
            return {
                "created": False,
                "notification": dict(existing),
            }

        if not _source_exists(
            connection,
            clean_source_type,
            source_id,
        ):
            raise ValueError(
                "El origen de la notificación "
                "no existe."
            )

        cursor = connection.execute(
            """
            INSERT INTO scheduled_notifications (
                source_type,
                source_id,
                canal,
                notification_type,
                scheduled_at,
                source_key
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clean_source_type,
                int(source_id),
                clean_channel,
                clean_type,
                normalized_schedule,
                clean_source_key,
            ),
        )

        row = connection.execute(
            """
            SELECT *
            FROM scheduled_notifications
            WHERE id = ?
            """,
            (int(cursor.lastrowid),),
        ).fetchone()

        return {
            "created": True,
            "notification": dict(row),
        }


def list_for_source(
    source_type,
    source_id,
    *,
    include_inactive=False,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    clean_source_type = _upper(
        source_type
    )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        sql = """
            SELECT *
            FROM scheduled_notifications
            WHERE source_type = ?
              AND source_id = ?
        """

        params = [
            clean_source_type,
            int(source_id),
        ]

        if not include_inactive:
            sql += """
                AND activo = 1
            """

        sql += """
            ORDER BY
                datetime(scheduled_at) ASC,
                id ASC
        """

        return [
            dict(row)
            for row in connection.execute(
                sql,
                params,
            ).fetchall()
        ]


def list_due_notifications(
    *,
    now=None,
    limit=100,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    current = (
        now or datetime.now()
    ).replace(
        microsecond=0
    ).isoformat(
        sep=" "
    )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        rows = connection.execute(
            """
            SELECT *
            FROM scheduled_notifications
            WHERE activo = 1

              AND estado IN (
                    'PENDIENTE',
                    'ERROR'
              )

              AND datetime(
                    scheduled_at
                  ) <= datetime(?)

            ORDER BY
                datetime(scheduled_at) ASC,
                id ASC

            LIMIT ?
            """,
            (
                current,
                int(limit),
            ),
        ).fetchall()

        result = []

        for row in rows:
            notification = dict(row)

            context = get_delivery_context(
                notification,
                conn=connection,
                db_path=db_path,
            )

            if context is None:
                continue

            notification[
                "delivery_context"
            ] = context

            result.append(
                notification
            )

        return result


def get_delivery_context(
    notification,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    if not notification:
        return None

    source_type = _upper(
        notification.get(
            "source_type"
        )
    )

    source_id = int(
        notification[
            "source_id"
        ]
    )

    if source_type == SOURCE_TASK:
        task = task_service.get_task(
            source_id,
            conn=conn,
            db_path=db_path,
        )

        if not task:
            return None

        if int(task.get("activo") or 0) != 1:
            return None

        if task.get("estado") not in {
            "PENDIENTE",
            "EN_CURSO",
        }:
            return None

        return {
            "source_type": SOURCE_TASK,
            "source": task,
        }

    if source_type == SOURCE_ALERT:
        alert = (
            calendar_alert_service
            .get_alert(
                source_id,
                conn=conn,
                db_path=db_path,
            )
        )

        if not alert:
            return None

        if int(alert.get("activo") or 0) != 1:
            return None

        if alert.get("estado") != "ACTIVO":
            return None

        return {
            "source_type": SOURCE_ALERT,
            "source": alert,
        }

    return None


def mark_processing(
    notification_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return _set_delivery_state(
        notification_id,
        ESTADO_PROCESANDO,
        increment_attempt=True,
        conn=conn,
        db_path=db_path,
    )


def mark_sent(
    notification_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        connection.execute(
            """
            UPDATE scheduled_notifications
            SET
                estado = 'ENVIADA',
                sent_at = CURRENT_TIMESTAMP,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(notification_id),),
        )

        return _load(
            connection,
            notification_id,
        )


def mark_error(
    notification_id,
    error,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        connection.execute(
            """
            UPDATE scheduled_notifications
            SET
                estado = 'ERROR',
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                _text(error),
                int(notification_id),
            ),
        )

        return _load(
            connection,
            notification_id,
        )


def _set_delivery_state(
    notification_id,
    state,
    *,
    increment_attempt=False,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        if increment_attempt:
            connection.execute(
                """
                UPDATE scheduled_notifications
                SET
                    estado = ?,
                    attempt_count =
                        attempt_count + 1,
                    last_attempt_at =
                        CURRENT_TIMESTAMP,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    state,
                    int(notification_id),
                ),
            )

        else:
            connection.execute(
                """
                UPDATE scheduled_notifications
                SET
                    estado = ?,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    state,
                    int(notification_id),
                ),
            )

        return _load(
            connection,
            notification_id,
        )


def cancel_pending_for_source(
    source_type,
    source_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_schema(
            conn=connection,
            db_path=db_path,
        )

        cursor = connection.execute(
            """
            UPDATE scheduled_notifications
            SET
                estado = 'CANCELADA',
                activo = 0,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE source_type = ?
              AND source_id = ?
              AND estado IN (
                    'PENDIENTE',
                    'ERROR'
              )
              AND activo = 1
            """,
            (
                _upper(source_type),
                int(source_id),
            ),
        )

        return cursor.rowcount


def _load(
    connection,
    notification_id,
):
    row = connection.execute(
        """
        SELECT *
        FROM scheduled_notifications
        WHERE id = ?
        """,
        (int(notification_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "Notificación no encontrada."
        )

    return dict(row)


def _task_policy(priority):
    priority = _upper(
        priority
    )

    if priority == "URGENTE":
        return (
            (
                "24H_ANTES",
                timedelta(hours=24),
            ),
            (
                "2H_ANTES",
                timedelta(hours=2),
            ),
            (
                "VENCIMIENTO",
                timedelta(),
            ),
        )

    if priority == "ALTA":
        return (
            (
                "24H_ANTES",
                timedelta(hours=24),
            ),
            (
                "VENCIMIENTO",
                timedelta(),
            ),
        )

    return (
        (
            "VENCIMIENTO",
            timedelta(),
        ),
    )


def schedule_task_notifications(
    task,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    if not task:
        raise ValueError(
            "La tarea es obligatoria."
        )

    task_id = int(
        task["id"]
    )

    due_at = datetime.fromisoformat(
        _text(
            task["fecha_vencimiento"]
        ).replace(
            "T",
            " ",
        )
    )

    results = []

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        for (
            notification_type,
            offset,
        ) in _task_policy(
            task.get("prioridad")
        ):
            results.append(
                create_notification(
                    source_type=SOURCE_TASK,
                    source_id=task_id,
                    scheduled_at=(
                        due_at - offset
                    ),
                    notification_type=(
                        notification_type
                    ),
                    source_key=(
                        f"TASK:{task_id}:"
                        f"TELEGRAM:"
                        f"{notification_type}"
                    ),
                    conn=connection,
                    db_path=db_path,
                )
            )

    return results


def schedule_alert_notification(
    alert,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    if not alert:
        raise ValueError(
            "El aviso es obligatorio."
        )

    alert_id = int(
        alert["id"]
    )

    schedule_at = (
        alert.get(
            "fecha_inicio_aviso"
        )
        or alert.get(
            "fecha_evento"
        )
    )

    if not schedule_at:
        raise ValueError(
            "El aviso no tiene fecha."
        )

    return create_notification(
        source_type=SOURCE_ALERT,
        source_id=alert_id,
        scheduled_at=schedule_at,
        notification_type=(
            "AVISO_CALENDARIO"
        ),
        source_key=(
            f"ALERT:{alert_id}:"
            "TELEGRAM:"
            "AVISO_CALENDARIO"
        ),
        conn=conn,
        db_path=db_path,
    )
