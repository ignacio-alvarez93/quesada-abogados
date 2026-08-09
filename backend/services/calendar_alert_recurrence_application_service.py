"""
Orquestación de recordatorios recurrentes para ALERT.

Contrato:

- calendar_alerts representa el evento real;
- una recurrencia NO crea nuevos calendar_alerts;
- la recurrencia genera scheduled_notifications;
- fecha_inicio_aviso es el primer recordatorio;
- fecha_evento es el límite natural máximo.

Ejemplo:

evento:
    15/08/2026 09:00

avisar desde:
    09/08/2026 09:00

cada:
    1 DAY

Resultado:

    09/08
    10/08
    11/08
    12/08
    13/08
    14/08
    15/08

Existe un único calendar_alert.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from backend.services import (
    calendar_alert_application_service,
    calendar_alert_recurrence_service,
    calendar_alert_service,
    scheduled_notification_service,
)


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


def _connect(
    db_path=DEFAULT_DB_PATH,
):
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


def _parse_datetime(value):
    if not value:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value.replace(
            microsecond=0
        )

    return datetime.fromisoformat(
        str(value).replace(
            "T",
            " ",
        )
    ).replace(
        microsecond=0
    )


def _notification_source_key(
    recurrence_id,
    occurrence_index,
):
    return (
        "ALERT_RECURRENCE:"
        f"{int(recurrence_id)}:"
        f"{int(occurrence_index)}"
    )


def _unwrap_notification(
    result,
):
    if not result:
        return None

    if (
        isinstance(result, dict)
        and "notification" in result
    ):
        return result["notification"]

    return result


def _event_limit(root):
    return _parse_datetime(
        root.get("fecha_evento")
    )


def _within_event_limit(
    root,
    scheduled_at,
):
    event_at = _event_limit(root)

    if event_at is None:
        return True

    return scheduled_at <= event_at


def create_recurring_alert(
    *,
    titulo,
    fecha_evento,
    frequency_unit,
    interval_value=1,
    end_type="NEVER",
    end_date=None,
    max_occurrences=None,
    descripcion="",
    cliente_id=None,
    expediente_id=None,
    documento_id=None,
    tipo="GENERAL",
    prioridad="NORMAL",
    fecha_inicio_aviso=None,
    origen_tipo="MANUAL",
    origen_id="",
    created_by="ERP",
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Crea un único ALERT y una regla recurrente
    para sus recordatorios.
    """

    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        root_result = (
            calendar_alert_application_service
            .create_calendar_alert(
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
                created_by=created_by,
                conn=connection,
                db_path=db_path,
            )
        )

        root = root_result["alert"]

        first_notification = (
            _unwrap_notification(
                root_result.get(
                    "notification"
                )
            )
        )

        if not first_notification:
            raise ValueError(
                "No se pudo programar "
                "el primer recordatorio."
            )

        anchor_at = (
            root.get("fecha_inicio_aviso")
            or root.get("fecha_evento")
        )

        recurrence = (
            calendar_alert_recurrence_service
            .create_recurrence(
                root_alert_id=root["id"],
                anchor_at=anchor_at,
                frequency_unit=(
                    frequency_unit
                ),
                interval_value=(
                    interval_value
                ),
                end_type=end_type,
                end_date=end_date,
                max_occurrences=(
                    max_occurrences
                ),
                conn=connection,
                db_path=db_path,
            )
        )

        (
            calendar_alert_recurrence_service
            .register_notification_occurrence(
                recurrence["id"],
                notification_id=(
                    first_notification["id"]
                ),
                occurrence_index=1,
                scheduled_at=anchor_at,
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "alert": root,
            "notification": (
                root_result.get(
                    "notification"
                )
            ),
            "recurrence": recurrence,
        }


def materialize_next_occurrence(
    recurrence_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Programa un nuevo recordatorio para
    el mismo ALERT.

    Nunca crea un calendar_alert adicional.
    """

    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        if not recurrence:
            raise ValueError(
                "Recurrencia no encontrada."
            )

        if (
            recurrence.get("estado")
            != calendar_alert_recurrence_service
            .RECURRENCE_ACTIVE
        ):
            return None

        root = (
            calendar_alert_service
            .get_alert(
                recurrence[
                    "root_alert_id"
                ],
                conn=connection,
                db_path=db_path,
            )
        )

        if not root:
            raise ValueError(
                "Aviso raíz no encontrado."
            )

        next_index = (
            int(
                recurrence[
                    "occurrences_generated"
                ]
            )
            + 1
        )

        scheduled_at = (
            calendar_alert_recurrence_service
            .occurrence_at(
                recurrence[
                    "anchor_at"
                ],
                frequency_unit=(
                    recurrence[
                        "frequency_unit"
                    ]
                ),
                interval_value=(
                    recurrence[
                        "interval_value"
                    ]
                ),
                occurrence_index=(
                    next_index
                ),
            )
        )

        allowed = (
            calendar_alert_recurrence_service
            .occurrence_allowed(
                recurrence,
                next_index,
                scheduled_at,
            )
        )

        allowed = (
            allowed
            and _within_event_limit(
                root,
                scheduled_at,
            )
        )

        if not allowed:
            (
                calendar_alert_recurrence_service
                .update_progress(
                    recurrence_id,
                    occurrences_generated=(
                        recurrence[
                            "occurrences_generated"
                        ]
                    ),
                    last_occurrence_at=(
                        recurrence[
                            "last_occurrence_at"
                        ]
                    ),
                    next_occurrence_at=None,
                    activo=True,
                    estado=(
                        calendar_alert_recurrence_service
                        .RECURRENCE_ACTIVE
                    ),
                    conn=connection,
                    db_path=db_path,
                )
            )

            return None

        created = (
            scheduled_notification_service
            .create_notification(
                source_type="ALERT",
                source_id=root["id"],
                scheduled_at=scheduled_at,
                notification_type=(
                    "AVISO_CALENDARIO"
                ),
                source_key=(
                    _notification_source_key(
                        recurrence_id,
                        next_index,
                    )
                ),
                conn=connection,
                db_path=db_path,
            )
        )

        notification = (
            created["notification"]
        )

        (
            calendar_alert_recurrence_service
            .register_notification_occurrence(
                recurrence_id,
                notification_id=(
                    notification["id"]
                ),
                occurrence_index=(
                    next_index
                ),
                scheduled_at=scheduled_at,
                conn=connection,
                db_path=db_path,
            )
        )

        following_index = (
            next_index
            + 1
        )

        following_at = (
            calendar_alert_recurrence_service
            .occurrence_at(
                recurrence[
                    "anchor_at"
                ],
                frequency_unit=(
                    recurrence[
                        "frequency_unit"
                    ]
                ),
                interval_value=(
                    recurrence[
                        "interval_value"
                    ]
                ),
                occurrence_index=(
                    following_index
                ),
            )
        )

        has_following = (
            calendar_alert_recurrence_service
            .occurrence_allowed(
                recurrence,
                following_index,
                following_at,
            )
        )

        has_following = (
            has_following
            and _within_event_limit(
                root,
                following_at,
            )
        )

        updated = (
            calendar_alert_recurrence_service
            .update_progress(
                recurrence_id,
                occurrences_generated=(
                    next_index
                ),
                last_occurrence_at=(
                    scheduled_at
                ),
                next_occurrence_at=(
                    following_at
                    if has_following
                    else None
                ),
                activo=True,
                estado=(
                    calendar_alert_recurrence_service
                    .RECURRENCE_ACTIVE
                ),
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "alert": root,
            "notification": created,
            "recurrence": updated,
            "occurrence_index": next_index,
            "scheduled_at": (
                scheduled_at.isoformat(
                    sep=" "
                )
            ),
        }


def materialize_occurrences(
    recurrence_id,
    *,
    count=3,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Programa hasta count recordatorios futuros.
    """

    maximum = max(
        0,
        int(count),
    )

    results = []

    for _ in range(maximum):
        result = (
            materialize_next_occurrence(
                recurrence_id,
                conn=conn,
                db_path=db_path,
            )
        )

        if result is None:
            break

        results.append(result)

    return results

def materialize_until_limit(
    recurrence_id,
    *,
    safety_limit=10000,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Materializa todos los recordatorios pendientes
    hasta que la propia regla indique que la serie
    ha terminado.

    El límite de seguridad evita un bucle accidental
    provocado por una configuración o regresión
    defectuosa.
    """

    maximum = int(
        safety_limit
    )

    if maximum < 1:
        raise ValueError(
            "El límite de seguridad debe "
            "ser superior a 0."
        )

    results = []

    for _ in range(maximum):
        result = (
            materialize_next_occurrence(
                recurrence_id,
                conn=conn,
                db_path=db_path,
            )
        )

        if result is None:
            return results

        results.append(
            result
        )

    raise RuntimeError(
        "La recurrencia superó el límite "
        "de seguridad de materialización."
    )

def _recurrence_notification_ids(
    recurrence_id,
    *,
    conn,
    db_path=DEFAULT_DB_PATH,
):
    mappings = (
        calendar_alert_recurrence_service
        .list_notification_occurrences(
            recurrence_id,
            conn=conn,
            db_path=db_path,
        )
    )

    return [
        int(
            item["notification_id"]
        )
        for item in mappings
    ]


def pause_recurring_alert(
    recurrence_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Pausa una serie sin cancelar el ALERT raíz.

    Las notificaciones pendientes o con error
    quedan suspendidas y fuera del worker.
    """
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        if not recurrence:
            raise ValueError(
                "Recurrencia no encontrada."
            )

        notification_ids = (
            _recurrence_notification_ids(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        paused_notifications = (
            scheduled_notification_service
            .pause_notifications(
                notification_ids,
                conn=connection,
                db_path=db_path,
            )
        )

        paused = (
            calendar_alert_recurrence_service
            .pause_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "recurrence": paused,
            "notifications_paused": (
                paused_notifications
            ),
        }


def resume_recurring_alert(
    recurrence_id,
    *,
    now=None,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Reanuda una serie pausada.

    Los recordatorios ya vencidos se marcan
    OMITIDA y no se envían de forma atrasada.
    """
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        if not recurrence:
            raise ValueError(
                "Recurrencia no encontrada."
            )

        if (
            recurrence.get("estado")
            != calendar_alert_recurrence_service
            .RECURRENCE_PAUSED
        ):
            raise ValueError(
                "Solo puede reanudarse "
                "una serie pausada."
            )

        notification_ids = (
            _recurrence_notification_ids(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        notification_result = (
            scheduled_notification_service
            .resume_notifications(
                notification_ids,
                now=now,
                conn=connection,
                db_path=db_path,
            )
        )

        resumed = (
            calendar_alert_recurrence_service
            .resume_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "recurrence": resumed,
            **notification_result,
        }


def cancel_recurring_alert(
    recurrence_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Cancela definitivamente la recurrencia
    sin cancelar el calendar_alert raíz.
    """
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        if not recurrence:
            raise ValueError(
                "Recurrencia no encontrada."
            )

        notification_ids = (
            _recurrence_notification_ids(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        cancelled_notifications = (
            scheduled_notification_service
            .cancel_notifications(
                notification_ids,
                conn=connection,
                db_path=db_path,
            )
        )

        cancelled = (
            calendar_alert_recurrence_service
            .cancel_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "recurrence": cancelled,
            "notifications_cancelled": (
                cancelled_notifications
            ),
        }

def _recurrence_for_notification(
    notification_id,
    *,
    conn,
):
    row = conn.execute(
        """
        SELECT
            r.*
        FROM
            calendar_alert_recurrence_notifications rn
        JOIN calendar_alert_recurrences r
          ON r.id = rn.recurrence_id
        WHERE rn.notification_id = ?
        LIMIT 1
        """,
        (
            int(notification_id),
        ),
    ).fetchone()

    return (
        dict(row)
        if row
        else None
    )


def _recurrence_has_operational_notifications(
    recurrence_id,
    *,
    conn,
):
    row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM
            calendar_alert_recurrence_notifications rn
        JOIN scheduled_notifications sn
          ON sn.id = rn.notification_id
        WHERE
            rn.recurrence_id = ?
            AND sn.estado IN (
                'PENDIENTE',
                'ERROR',
                'PROCESANDO',
                'PAUSADA'
            )
        """,
        (
            int(recurrence_id),
        ),
    ).fetchone()

    return int(
        row["total"]
        if row
        else 0
    ) > 0


def finalize_recurrence_if_complete(
    recurrence_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Finaliza una serie únicamente cuando su
    materialización está cerrada y ya no quedan
    recordatorios con lifecycle operativo.
    """
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        if not recurrence:
            raise ValueError(
                "Recurrencia no encontrada."
            )

        if (
            recurrence.get("estado")
            != calendar_alert_recurrence_service
            .RECURRENCE_ACTIVE
        ):
            return {
                "finalized": False,
                "recurrence": recurrence,
            }

        if recurrence.get(
            "next_occurrence_at"
        ):
            return {
                "finalized": False,
                "recurrence": recurrence,
            }

        if _recurrence_has_operational_notifications(
            recurrence_id,
            conn=connection,
        ):
            return {
                "finalized": False,
                "recurrence": recurrence,
            }

        finished = (
            calendar_alert_recurrence_service
            .finish_recurrence(
                recurrence_id,
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "finalized": True,
            "recurrence": finished,
        }


def mark_recurring_notification_sent(
    notification_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Marca ENVIADA una notificación perteneciente
    a una serie y finaliza la recurrencia si este
    era su último recordatorio operativo.

    Si la notificación no pertenece a ninguna
    recurrencia, realiza únicamente mark_sent.
    """
    with _transaction(
        conn=conn,
        db_path=db_path,
    ) as connection:

        recurrence = (
            _recurrence_for_notification(
                notification_id,
                conn=connection,
            )
        )

        notification = (
            scheduled_notification_service
            .mark_sent(
                notification_id,
                conn=connection,
                db_path=db_path,
            )
        )

        if not recurrence:
            return {
                "notification": notification,
                "recurrence": None,
                "finalized": False,
            }

        completion = (
            finalize_recurrence_if_complete(
                recurrence["id"],
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "notification": notification,
            "recurrence": completion[
                "recurrence"
            ],
            "finalized": completion[
                "finalized"
            ],
        }
