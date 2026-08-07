"""
Adaptador de compatibilidad para notificaciones de tareas.

La outbox canónica es ahora:

    scheduled_notifications

Este módulo conserva la API utilizada por el dominio de tareas
y por los tests existentes.
"""

from backend.services import (
    scheduled_notification_service as scheduled,
)


DEFAULT_DB_PATH = scheduled.DEFAULT_DB_PATH
CANAL_TELEGRAM = scheduled.CANAL_TELEGRAM

ESTADO_PENDIENTE = scheduled.ESTADO_PENDIENTE
ESTADO_PROCESANDO = scheduled.ESTADO_PROCESANDO
ESTADO_ENVIADA = scheduled.ESTADO_ENVIADA
ESTADO_ERROR = scheduled.ESTADO_ERROR
ESTADO_CANCELADA = scheduled.ESTADO_CANCELADA


def ensure_notification_schema(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return scheduled.ensure_schema(
        conn=conn,
        db_path=db_path,
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
    return scheduled.create_notification(
        source_type=scheduled.SOURCE_TASK,
        source_id=task_id,
        scheduled_at=scheduled_at,
        notification_type=notification_type,
        canal=canal,
        source_key=source_key,
        conn=conn,
        db_path=db_path,
    )


def get_notifications_for_task(
    task_id,
    *,
    include_inactive=False,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return scheduled.list_for_source(
        scheduled.SOURCE_TASK,
        task_id,
        include_inactive=include_inactive,
        conn=conn,
        db_path=db_path,
    )


def list_due_notifications(
    *,
    now=None,
    limit=100,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    items = scheduled.list_due_notifications(
        now=now,
        limit=limit,
        conn=conn,
        db_path=db_path,
    )

    result = []

    for item in items:
        if item.get("source_type") != "TASK":
            continue

        context = (
            item.get(
                "delivery_context"
            )
            or {}
        )

        task = (
            context.get("source")
            or {}
        )

        merged = dict(item)
        merged.pop(
            "delivery_context",
            None,
        )

        merged.update(
            {
                "task_id":
                    task.get("id"),
                "titulo":
                    task.get("titulo"),
                "descripcion":
                    task.get("descripcion"),
                "prioridad":
                    task.get("prioridad"),
                "fecha_vencimiento":
                    task.get(
                        "fecha_vencimiento"
                    ),
                "cliente_id":
                    task.get("cliente_id"),
                "expediente_id":
                    task.get(
                        "expediente_id"
                    ),
                "numero_expediente":
                    task.get(
                        "numero_expediente"
                    ),
                "cliente_nombre":
                    task.get(
                        "cliente_nombre"
                    ),
                "cliente_primer_apellido":
                    task.get(
                        "cliente_primer_apellido"
                    ),
                "cliente_segundo_apellido":
                    task.get(
                        "cliente_segundo_apellido"
                    ),
            }
        )

        result.append(
            merged
        )

    return result


def mark_processing(
    notification_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return scheduled.mark_processing(
        notification_id,
        conn=conn,
        db_path=db_path,
    )


def mark_sent(
    notification_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return scheduled.mark_sent(
        notification_id,
        conn=conn,
        db_path=db_path,
    )


def mark_error(
    notification_id,
    error,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return scheduled.mark_error(
        notification_id,
        error,
        conn=conn,
        db_path=db_path,
    )


def cancel_pending_for_task(
    task_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return scheduled.cancel_pending_for_source(
        scheduled.SOURCE_TASK,
        task_id,
        conn=conn,
        db_path=db_path,
    )


def schedule_default_telegram_notifications(
    task,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    return scheduled.schedule_task_notifications(
        task,
        conn=conn,
        db_path=db_path,
    )
