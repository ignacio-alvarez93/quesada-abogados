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
                    activo=False,
                    estado=(
                        calendar_alert_recurrence_service
                        .RECURRENCE_FINISHED
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
                activo=has_following,
                estado=(
                    calendar_alert_recurrence_service
                    .RECURRENCE_ACTIVE
                    if has_following
                    else
                    calendar_alert_recurrence_service
                    .RECURRENCE_FINISHED
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
