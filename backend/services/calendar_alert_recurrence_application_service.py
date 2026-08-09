"""
Orquestación de series recurrentes de avisos.

La recurrencia no crea directamente filas de calendar_alerts.

Cada ocurrencia se crea mediante
calendar_alert_application_service para conservar:

- lifecycle del aviso;
- planificación Telegram;
- transaccionalidad;
- comportamiento normal de Calendar.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from backend.services import (
    calendar_alert_service,
    calendar_alert_application_service,
    calendar_alert_recurrence_service,
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
    owns_connection = (
        conn is None
    )

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


def _warning_offset(
    alert,
):
    event_at = _parse_datetime(
        alert.get(
            "fecha_evento"
        )
    )

    warning_at = _parse_datetime(
        alert.get(
            "fecha_inicio_aviso"
        )
    )

    if (
        event_at is None
        or warning_at is None
    ):
        return None

    return (
        event_at
        - warning_at
    )


def _warning_for_occurrence(
    occurrence_at,
    offset,
):
    if offset is None:
        return None

    return (
        occurrence_at
        - offset
    )


def _generated_source_key(
    recurrence_id,
    occurrence_index,
):
    return (
        "CALENDAR_RECURRENCE:"
        f"{int(recurrence_id)}:"
        f"{int(occurrence_index)}"
    )


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
    Crea el aviso raíz y su regla
    dentro de una misma transacción.
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

        root = root_result[
            "alert"
        ]

        recurrence = (
            calendar_alert_recurrence_service
            .create_recurrence(
                root_alert_id=root["id"],
                anchor_at=root[
                    "fecha_evento"
                ],
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

        return {
            "alert": root,
            "notification":
                root_result.get(
                    "notification"
                ),
            "recurrence":
                recurrence,
        }


def materialize_next_occurrence(
    recurrence_id,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Materializa como máximo una nueva ocurrencia.

    Devuelve None cuando la serie ha finalizado.
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

        occurrence_at = (
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
                occurrence_at,
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
                    conn=connection,
                    db_path=db_path,
                )
            )

            return None

        offset = _warning_offset(
            root
        )

        warning_at = (
            _warning_for_occurrence(
                occurrence_at,
                offset,
            )
        )

        created = (
            calendar_alert_application_service
            .create_calendar_alert(
                titulo=root["titulo"],
                descripcion=(
                    root.get(
                        "descripcion"
                    )
                    or ""
                ),
                cliente_id=(
                    root.get(
                        "cliente_id"
                    )
                ),
                expediente_id=(
                    root.get(
                        "expediente_id"
                    )
                ),
                documento_id=(
                    root.get(
                        "documento_id"
                    )
                ),
                tipo=(
                    root.get("tipo")
                    or "GENERAL"
                ),
                prioridad=(
                    root.get(
                        "prioridad"
                    )
                    or "NORMAL"
                ),
                fecha_evento=(
                    occurrence_at
                ),
                fecha_inicio_aviso=(
                    warning_at
                ),
                origen_tipo="SISTEMA",
                origen_id=str(
                    recurrence_id
                ),
                source_key=(
                    _generated_source_key(
                        recurrence_id,
                        next_index,
                    )
                ),
                created_by="RECURRENCE",
                conn=connection,
                db_path=db_path,
            )
        )

        alert = created[
            "alert"
        ]

        (
            calendar_alert_recurrence_service
            .register_occurrence(
                recurrence_id,
                alert_id=alert["id"],
                occurrence_index=(
                    next_index
                ),
                occurrence_at=(
                    occurrence_at
                ),
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

        updated = (
            calendar_alert_recurrence_service
            .update_progress(
                recurrence_id,
                occurrences_generated=(
                    next_index
                ),
                last_occurrence_at=(
                    occurrence_at
                ),
                next_occurrence_at=(
                    following_at
                    if has_following
                    else None
                ),
                activo=has_following,
                conn=connection,
                db_path=db_path,
            )
        )

        return {
            "alert": alert,
            "notification":
                created.get(
                    "notification"
                ),
            "recurrence":
                updated,
            "occurrence_index":
                next_index,
        }


def materialize_occurrences(
    recurrence_id,
    *,
    count=3,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Materializa hasta count ocurrencias futuras.
    """

    maximum = max(
        0,
        int(count),
    )

    results = []

    for _ in range(
        maximum
    ):
        result = (
            materialize_next_occurrence(
                recurrence_id,
                conn=conn,
                db_path=db_path,
            )
        )

        if result is None:
            break

        results.append(
            result
        )

    return results
