"""
Orquestación transaccional de tareas del Calendario.

La UI no debe llamar directamente a task_service para operaciones
que impliquen planificación de Telegram.

Garantías:

CREATE
    tarea + notificaciones en una transacción.

UPDATE
    actualización + cancelación de planificación obsoleta +
    nueva planificación cuando corresponda.

COMPLETE / CANCEL
    cambio de estado + cancelación de notificaciones pendientes.

REOPEN
    reapertura + nueva revisión de planificación.
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from backend.services import task_service
from backend.services import scheduled_notification_service


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


ACTIVE_TASK_STATES = {
    "PENDIENTE",
    "EN_CURSO",
}


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
def _transaction(
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
        if owns_connection:
            connection.execute("BEGIN")

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


def _revision_key(task):
    """
    Identificador de una revisión concreta de planificación.

    time_ns evita colisiones cuando dos operaciones ocurren
    dentro del mismo segundo, algo posible en tests/UI.
    """
    return (
        f"{int(task['id'])}-"
        f"{time.time_ns()}"
    )


def _schedule(
    task,
    *,
    conn,
    db_path,
):
    if not task:
        return []

    if str(
        task.get("estado") or ""
    ).upper() not in ACTIVE_TASK_STATES:
        return []

    return (
        scheduled_notification_service
        .schedule_task_notifications(
            task,
            revision_key=_revision_key(
                task
            ),
            conn=conn,
            db_path=db_path,
        )
    )


def create_calendar_task(
    *,
    titulo,
    fecha_vencimiento,
    descripcion="",
    cliente_id=None,
    expediente_id=None,
    tipo="GENERAL",
    prioridad="NORMAL",
    responsable="",
    fecha_inicio="",
    created_by="ERP",
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        result = task_service.create_task(
            titulo=titulo,
            fecha_vencimiento=fecha_vencimiento,
            descripcion=descripcion,
            cliente_id=cliente_id,
            expediente_id=expediente_id,
            tipo=tipo,
            prioridad=prioridad,
            responsable=responsable,
            fecha_inicio=fecha_inicio,
            origen_tipo="MANUAL",
            created_by=created_by,
            conn=connection,
            db_path=db_path,
        )

        task = result["task"]

        notifications = []

        if result["created"]:
            notifications = _schedule(
                task,
                conn=connection,
                db_path=db_path,
            )

        return {
            "created": result["created"],
            "task": task,
            "notifications": notifications,
        }


def update_calendar_task(
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
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        before = task_service.get_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )

        if not before:
            raise ValueError(
                "Tarea no encontrada."
            )

        task = task_service.update_task(
            task_id,
            titulo=titulo,
            descripcion=descripcion,
            cliente_id=cliente_id,
            expediente_id=expediente_id,
            tipo=tipo,
            prioridad=prioridad,
            responsable=responsable,
            fecha_inicio=fecha_inicio,
            fecha_vencimiento=fecha_vencimiento,
            conn=connection,
            db_path=db_path,
        )

        schedule_changed = (
            before.get("fecha_vencimiento")
            != task.get("fecha_vencimiento")
            or before.get("prioridad")
            != task.get("prioridad")
        )

        notifications = []

        if schedule_changed:
            (
                scheduled_notification_service
                .cancel_pending_for_source(
                    "TASK",
                    task_id,
                    conn=connection,
                    db_path=db_path,
                )
            )

            notifications = _schedule(
                task,
                conn=connection,
                db_path=db_path,
            )

        return {
            "task": task,
            "schedule_changed":
                schedule_changed,
            "notifications":
                notifications,
        }


def start_calendar_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        return task_service.start_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )


def complete_calendar_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        task = task_service.complete_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )

        (
            scheduled_notification_service
            .cancel_pending_for_source(
                "TASK",
                task_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return task


def cancel_calendar_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        task = task_service.cancel_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )

        (
            scheduled_notification_service
            .cancel_pending_for_source(
                "TASK",
                task_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return task


def reopen_calendar_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        task = task_service.reopen_task(
            task_id,
            conn=connection,
            db_path=db_path,
        )

        (
            scheduled_notification_service
            .cancel_pending_for_source(
                "TASK",
                task_id,
                conn=connection,
                db_path=db_path,
            )
        )

        notifications = _schedule(
            task,
            conn=connection,
            db_path=db_path,
        )

        return {
            "task": task,
            "notifications":
                notifications,
        }
