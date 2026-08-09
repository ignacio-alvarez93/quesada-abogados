from datetime import datetime

from backend.services import (
    calendar_alert_application_service,
    calendar_alert_service,
)


SOURCE_PREFIX = "NOTIFICATION_TRACKING:EXP:"
ORIGEN_TIPO = "TRAZABILIDAD"
ALERT_TYPE = "SEGUIMIENTO_NOTIFICACION"
ALERT_TITLE = "En espera de notificación"


ACTIVE_STATE_DESCRIPTIONS = {
    "ESPERA_NUMERO_EXPEDIENTE":
        "Esperando número de expediente.",

    "ESPERA_ADMISION_TRAMITE":
        "Esperando admisión a trámite.",

    "ESPERA_RESOLUCION":
        "Esperando resolución.",
}


RESOLVED_STATES = {
    "CERRADO_FAVORABLE",
    "CERRADO_DENEGATORIO",
}


CANCELLED_STATES = {
    "CANCELADO_SIN_PRESENTACION",
}


def _text(value):
    return str(
        value or ""
    ).strip()


def _upper(value):
    return _text(
        value
    ).upper()


def build_source_key(
    expediente_id,
):
    return (
        f"{SOURCE_PREFIX}"
        f"{int(expediente_id)}"
    )


def _find_tracking_alert(
    expediente_id,
    *,
    db_path=(
        calendar_alert_service
        .DEFAULT_DB_PATH
    ),
):
    source_key = build_source_key(
        expediente_id
    )

    alerts = (
        calendar_alert_service
        .list_alerts(
            expediente_id=(
                int(expediente_id)
            ),
            include_archived=True,
            db_path=db_path,
        )
    )

    for alert in alerts:
        if (
            _text(
                alert.get(
                    "source_key"
                )
            )
            == source_key
        ):
            return alert

    return None


def _event_datetime():
    return datetime.now().replace(
        microsecond=0
    )


def _active_projection(
    tracking_result,
    *,
    db_path,
):
    expediente_id = int(
        tracking_result[
            "expediente_id"
        ]
    )

    cliente_id = (
        tracking_result.get(
            "cliente_id"
        )
    )

    tracking_id = (
        tracking_result.get(
            "tracking_id"
        )
    )

    estado = _upper(
        tracking_result.get(
            "estado_nuevo"
        )
    )

    description = (
        ACTIVE_STATE_DESCRIPTIONS[
            estado
        ]
    )

    source_key = build_source_key(
        expediente_id
    )

    existing = _find_tracking_alert(
        expediente_id,
        db_path=db_path,
    )

    now = _event_datetime()

    if not existing:
        created = (
            calendar_alert_application_service
            .create_calendar_alert(
                titulo=ALERT_TITLE,
                descripcion=description,
                cliente_id=cliente_id,
                expediente_id=(
                    expediente_id
                ),
                tipo=ALERT_TYPE,
                prioridad="NORMAL",
                fecha_evento=now,
                fecha_inicio_aviso=now,
                origen_tipo=ORIGEN_TIPO,
                origen_id=(
                    str(tracking_id)
                    if tracking_id
                    is not None
                    else str(
                        expediente_id
                    )
                ),
                source_key=source_key,
                created_by="ERP",
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "CREATED",
            "source_key":
                source_key,
            "alert":
                created["alert"],
        }

    alert = existing

    needs_update = (
        _text(
            alert.get(
                "titulo"
            )
        )
        != ALERT_TITLE
        or _text(
            alert.get(
                "descripcion"
            )
        )
        != description
        or _upper(
            alert.get(
                "tipo"
            )
        )
        != ALERT_TYPE
        or _upper(
            alert.get(
                "origen_tipo"
            )
        )
        != ORIGEN_TIPO
    )

    if needs_update:
        updated = (
            calendar_alert_application_service
            .update_calendar_alert(
                alert["id"],
                titulo=ALERT_TITLE,
                descripcion=description,
                cliente_id=cliente_id,
                expediente_id=(
                    expediente_id
                ),
                tipo=ALERT_TYPE,
                prioridad="NORMAL",
                fecha_evento=now,
                fecha_inicio_aviso=now,
                origen_tipo=ORIGEN_TIPO,
                origen_id=(
                    str(tracking_id)
                    if tracking_id
                    is not None
                    else str(
                        expediente_id
                    )
                ),
                source_key=source_key,
                db_path=db_path,
            )
        )

        alert = updated["alert"]

    if (
        _upper(
            alert.get(
                "estado"
            )
        )
        != "ACTIVO"
    ):
        reopened = (
            calendar_alert_application_service
            .reopen_calendar_alert(
                alert["id"],
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "REOPENED",
            "source_key":
                source_key,
            "alert":
                reopened["alert"],
        }

    return {
        "ok": True,
        "action": (
            "UPDATED"
            if needs_update
            else "UNCHANGED"
        ),
        "source_key":
            source_key,
        "alert":
            alert,
    }


def _closed_projection(
    tracking_result,
    *,
    db_path,
):
    expediente_id = int(
        tracking_result[
            "expediente_id"
        ]
    )

    estado = _upper(
        tracking_result.get(
            "estado_nuevo"
        )
    )

    source_key = build_source_key(
        expediente_id
    )

    alert = _find_tracking_alert(
        expediente_id,
        db_path=db_path,
    )

    # Muy importante:
    # cerrar un tracking que nunca generó
    # una ALERT no debe crear una ALERT
    # únicamente para cerrarla.
    if not alert:
        return {
            "ok": True,
            "action": "NO_ALERT",
            "source_key":
                source_key,
            "alert": None,
        }

    current_state = _upper(
        alert.get(
            "estado"
        )
    )

    if estado in CANCELLED_STATES:
        if current_state == "CANCELADO":
            return {
                "ok": True,
                "action": "UNCHANGED",
                "source_key":
                    source_key,
                "alert": alert,
            }

        cancelled = (
            calendar_alert_application_service
            .cancel_calendar_alert(
                alert["id"],
                db_path=db_path,
            )
        )

        return {
            "ok": True,
            "action": "CANCELLED",
            "source_key":
                source_key,
            "alert":
                cancelled,
        }

    if current_state == "RESUELTO":
        return {
            "ok": True,
            "action": "UNCHANGED",
            "source_key":
                source_key,
            "alert": alert,
        }

    resolved = (
        calendar_alert_application_service
        .resolve_calendar_alert(
            alert["id"],
            db_path=db_path,
        )
    )

    return {
        "ok": True,
        "action": "RESOLVED",
        "source_key":
            source_key,
        "alert":
            resolved,
    }


def sync_from_tracking_result(
    tracking_result,
    *,
    db_path=(
        calendar_alert_service
        .DEFAULT_DB_PATH
    ),
):
    """
    Proyecta notification_tracking sobre Calendar.

    No interpreta documentos.
    No decide el estado administrativo.
    No modifica notification_tracking.

    Recibe exclusivamente el resultado canónico
    de notification_tracking_service.reconcile_expedient().
    """

    result = dict(
        tracking_result or {}
    )

    if not result.get(
        "ok",
        False,
    ):
        return {
            "ok": False,
            "action": "TRACKING_ERROR",
            "alert": None,
            "error": _text(
                result.get(
                    "error"
                )
            ),
        }

    expediente_id = (
        result.get(
            "expediente_id"
        )
    )

    if expediente_id is None:
        raise ValueError(
            "El resultado de tracking "
            "no contiene expediente_id."
        )

    estado = _upper(
        result.get(
            "estado_nuevo"
        )
    )

    activo = int(
        result.get(
            "activo"
        )
        or 0
    )

    if (
        activo
        and estado
        in ACTIVE_STATE_DESCRIPTIONS
    ):
        return _active_projection(
            result,
            db_path=db_path,
        )

    if (
        not activo
        or estado in RESOLVED_STATES
        or estado in CANCELLED_STATES
    ):
        return _closed_projection(
            result,
            db_path=db_path,
        )

    return {
        "ok": True,
        "action": "IGNORED",
        "source_key":
            build_source_key(
                expediente_id
            ),
        "alert": None,
        "estado": estado,
    }
