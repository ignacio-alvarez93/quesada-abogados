"""
Outbox de avisos asociados a tareas.

La tabla task_notifications separa:

- creación del trabajo;
- programación del aviso;
- entrega real por Telegram.

Esto garantiza que un error externo nunca impida
crear o actualizar una tarea.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


CANAL_TELEGRAM = "TELEGRAM"

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_PROCESANDO = "PROCESANDO"
ESTADO_ENVIADA = "ENVIADA"
ESTADO_ERROR = "ERROR"
ESTADO_CANCELADA = "CANCELADA"

ACTIVE_DELIVERY_STATES = {
    ESTADO_PENDIENTE,
    ESTADO_ERROR,
}


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


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _dict(row):
    return dict(row) if row else None


def _normalize_datetime(value):
    if isinstance(value, datetime):
        return value.replace(
            microsecond=0
        ).isoformat(sep=" ")

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
    ).isoformat(sep=" ")


def ensure_notification_schema(
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
                task_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    task_id INTEGER NOT NULL,

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
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (task_id)
                        REFERENCES tasks(id)
                        ON DELETE CASCADE
                )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_task_notifications_source_key
            ON task_notifications(source_key)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_task_notifications_due
            ON task_notifications(
                activo,
                estado,
                scheduled_at
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_task_notifications_task
            ON task_notifications(task_id)
            """
        )


def create_notification(
    *,
    task_id,
    scheduled_at,
    notification_type,
    canal=CANAL_TELEGRAM,
    source_key,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    clean_source_key = _text(source_key)

    if not clean_source_key:
        raise ValueError(
            "source_key es obligatorio."
        )

    clean_type = _upper(
        notification_type
    )

    if not clean_type:
        raise ValueError(
            "notification_type es obligatorio."
        )

    clean_channel = (
        _upper(canal)
        or CANAL_TELEGRAM
    )

    if clean_channel != CANAL_TELEGRAM:
        raise ValueError(
            "Canal no soportado."
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

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        existing = connection.execute(
            """
            SELECT *
            FROM task_notifications
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

        task_exists = connection.execute(
            """
            SELECT id
            FROM tasks
            WHERE id = ?
            """,
            (int(task_id),),
        ).fetchone()

        if not task_exists:
            raise ValueError(
                "Tarea no encontrada."
            )

        cursor = connection.execute(
            """
            INSERT INTO task_notifications (
                task_id,
                canal,
                notification_type,
                scheduled_at,
                source_key
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(task_id),
                clean_channel,
                clean_type,
                normalized_schedule,
                clean_source_key,
            ),
        )

        row = connection.execute(
            """
            SELECT *
            FROM task_notifications
            WHERE id = ?
            """,
            (int(cursor.lastrowid),),
        ).fetchone()

        return {
            "created": True,
            "notification": dict(row),
        }


def get_notifications_for_task(
    task_id,
    *,
    include_inactive=False,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        sql = """
            SELECT *
            FROM task_notifications
            WHERE task_id = ?
        """

        params = [
            int(task_id)
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

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        rows = connection.execute(
            """
            SELECT
                tn.*,

                t.titulo,
                t.descripcion,
                t.prioridad,
                t.fecha_vencimiento,
                t.cliente_id,
                t.expediente_id,

                e.numero_expediente,

                c.nombre
                    AS cliente_nombre,
                c.primer_apellido
                    AS cliente_primer_apellido,
                c.segundo_apellido
                    AS cliente_segundo_apellido

            FROM task_notifications tn

            JOIN tasks t
              ON t.id = tn.task_id

            LEFT JOIN expedientes e
              ON e.id = t.expediente_id

            LEFT JOIN clientes c
              ON c.id = t.cliente_id

            WHERE tn.activo = 1
              AND tn.estado IN (
                    'PENDIENTE',
                    'ERROR'
              )
              AND datetime(
                    tn.scheduled_at
                  ) <= datetime(?)

              AND t.activo = 1

              AND t.estado IN (
                    'PENDIENTE',
                    'EN_CURSO'
              )

            ORDER BY
                datetime(
                    tn.scheduled_at
                ) ASC,
                tn.id ASC

            LIMIT ?
            """,
            (
                current,
                int(limit),
            ),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


def mark_processing(
    notification_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        connection.execute(
            """
            UPDATE task_notifications
            SET
                estado = 'PROCESANDO',
                attempt_count =
                    attempt_count + 1,
                last_attempt_at =
                    CURRENT_TIMESTAMP,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(notification_id),),
        )

        return _load_notification(
            connection,
            notification_id,
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

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        connection.execute(
            """
            UPDATE task_notifications
            SET
                estado = 'ENVIADA',
                sent_at =
                    CURRENT_TIMESTAMP,
                last_error = NULL,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(notification_id),),
        )

        return _load_notification(
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

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        connection.execute(
            """
            UPDATE task_notifications
            SET
                estado = 'ERROR',
                last_error = ?,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                _text(error),
                int(notification_id),
            ),
        )

        return _load_notification(
            connection,
            notification_id,
        )


def cancel_pending_for_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        cursor = connection.execute(
            """
            UPDATE task_notifications
            SET
                estado = 'CANCELADA',
                activo = 0,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE task_id = ?
              AND estado IN (
                    'PENDIENTE',
                    'ERROR'
              )
              AND activo = 1
            """,
            (int(task_id),),
        )

        return cursor.rowcount


def _load_notification(
    conn,
    notification_id,
):
    row = conn.execute(
        """
        SELECT *
        FROM task_notifications
        WHERE id = ?
        """,
        (int(notification_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "Notificación no encontrada."
        )

    return dict(row)


def _policy_offsets(priority):
    priority = _upper(priority)

    if priority == "URGENTE":
        return (
            ("24H_ANTES", timedelta(hours=24)),
            ("2H_ANTES", timedelta(hours=2)),
            ("VENCIMIENTO", timedelta()),
        )

    if priority == "ALTA":
        return (
            ("24H_ANTES", timedelta(hours=24)),
            ("VENCIMIENTO", timedelta()),
        )

    return (
        ("VENCIMIENTO", timedelta()),
    )


def schedule_default_telegram_notifications(
    task,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    if not task:
        raise ValueError(
            "La tarea es obligatoria."
        )

    task_id = int(task["id"])

    due_raw = _text(
        task.get("fecha_vencimiento")
    )

    if not due_raw:
        raise ValueError(
            "La tarea no tiene vencimiento."
        )

    due_at = datetime.fromisoformat(
        due_raw.replace("T", " ")
    )

    results = []

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        ensure_notification_schema(
            conn=connection,
            db_path=db_path,
        )

        for (
            notification_type,
            offset,
        ) in _policy_offsets(
            task.get("prioridad")
        ):

            scheduled_at = (
                due_at - offset
            )

            source_key = (
                f"TASK:{task_id}:"
                f"TELEGRAM:"
                f"{notification_type}"
            )

            results.append(
                create_notification(
                    task_id=task_id,
                    canal=CANAL_TELEGRAM,
                    notification_type=(
                        notification_type
                    ),
                    scheduled_at=scheduled_at,
                    source_key=source_key,
                    conn=connection,
                    db_path=db_path,
                )
            )

    return results
