"""
Orquestación transaccional de avisos del Calendario.

La UI no debe llamar directamente a calendar_alert_service para
operaciones que impliquen planificación de Telegram.

Garantías:

CREATE
    aviso + notificación en una transacción.

UPDATE
    modificación + cancelación de planificación obsoleta +
    nueva revisión cuando cambian las fechas relevantes.

RESOLVE / CANCEL
    cambio de estado + cancelación de notificaciones pendientes.

REOPEN
    reapertura + nueva revisión de planificación.
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from backend.services import calendar_alert_service
from backend.services import scheduled_notification_service


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


ACTIVE_ALERT_STATES = {
    "ACTIVO",
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
            connection.execute(
                "BEGIN"
            )

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


def _revision_key(alert):
    """
    Identifica una revisión concreta de planificación.

    time_ns evita colisiones cuando varias modificaciones suceden
    durante el mismo segundo.
    """

    return (
        f"{int(alert['id'])}-"
        f"{time.time_ns()}"
    )


def _schedule(
    alert,
    *,
    conn,
    db_path,
):
    if not alert:
        return None

    if str(
        alert.get("estado")
        or ""
    ).upper() not in ACTIVE_ALERT_STATES:
        return None

    return (
        scheduled_notification_service
        .schedule_alert_notification(
            alert,
            revision_key=_revision_key(
                alert
            ),
            conn=conn,
            db_path=db_path,
        )
    )


def create_calendar_alert(
    *,
    titulo,
    fecha_evento,
    descripcion="",
    cliente_id=None,
    expediente_id=None,
    documento_id=None,
    tipo="GENERAL",
    prioridad="NORMAL",
    fecha_inicio_aviso=None,
    origen_tipo="MANUAL",
    origen_id="",
    source_key="",
    created_by="ERP",
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        result = (
            calendar_alert_service
            .create_alert(
                titulo=titulo,
                fecha_evento=fecha_evento,
                descripcion=descripcion,
                cliente_id=cliente_id,
                expediente_id=expediente_id,
                documento_id=documento_id,
                tipo=tipo,
                prioridad=prioridad,
                fecha_inicio_aviso=(
                    fecha_inicio_aviso
                ),
                origen_tipo=origen_tipo,
                origen_id=origen_id,
                source_key=source_key,
                created_by=created_by,
                conn=connection,
                db_path=db_path,
            )
        )

        alert = result["alert"]

        notification = None

        if result["created"]:
            notification = _schedule(
                alert,
                conn=connection,
                db_path=db_path,
            )

        return {
            "created": result["created"],
            "alert": alert,
            "notification": notification,
        }


def update_calendar_alert(
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
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        before = (
            calendar_alert_service
            .get_alert(
                alert_id,
                conn=connection,
                db_path=db_path,
            )
        )

        if not before:
            raise ValueError(
                "Aviso no encontrado."
            )

        alert = (
            calendar_alert_service
            .update_alert(
                alert_id,
                titulo=titulo,
                descripcion=descripcion,
                cliente_id=cliente_id,
                expediente_id=expediente_id,
                documento_id=documento_id,
                tipo=tipo,
                prioridad=prioridad,
                fecha_evento=fecha_evento,
                fecha_inicio_aviso=(
                    fecha_inicio_aviso
                ),
                origen_tipo=origen_tipo,
                origen_id=origen_id,
                source_key=source_key,
                conn=connection,
                db_path=db_path,
            )
        )

        schedule_changed = (
            before.get(
                "fecha_evento"
            )
            != alert.get(
                "fecha_evento"
            )
            or before.get(
                "fecha_inicio_aviso"
            )
            != alert.get(
                "fecha_inicio_aviso"
            )
        )

        notification = None

        if schedule_changed:
            (
                scheduled_notification_service
                .cancel_pending_for_source(
                    "ALERT",
                    alert_id,
                    conn=connection,
                    db_path=db_path,
                )
            )

            notification = _schedule(
                alert,
                conn=connection,
                db_path=db_path,
            )

        return {
            "alert": alert,
            "schedule_changed":
                schedule_changed,
            "notification":
                notification,
        }


def resolve_calendar_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        alert = (
            calendar_alert_service
            .resolve_alert(
                alert_id,
                conn=connection,
                db_path=db_path,
            )
        )

        (
            scheduled_notification_service
            .cancel_pending_for_source(
                "ALERT",
                alert_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return alert


def cancel_calendar_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        alert = (
            calendar_alert_service
            .cancel_alert(
                alert_id,
                conn=connection,
                db_path=db_path,
            )
        )

        (
            scheduled_notification_service
            .cancel_pending_for_source(
                "ALERT",
                alert_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return alert


def reopen_calendar_alert(
    alert_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        alert = (
            calendar_alert_service
            .reopen_alert(
                alert_id,
                conn=connection,
                db_path=db_path,
            )
        )

        (
            scheduled_notification_service
            .cancel_pending_for_source(
                "ALERT",
                alert_id,
                conn=connection,
                db_path=db_path,
            )
        )

        notification = _schedule(
            alert,
            conn=connection,
            db_path=db_path,
        )

        return {
            "alert": alert,
            "notification":
                notification,
        }
