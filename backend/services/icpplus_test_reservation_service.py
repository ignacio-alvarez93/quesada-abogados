"""
Estado persistente de la única cita que puede mantenerse
reservada con el perfil técnico/de prueba de ICP Plus.

IMPORTANTE:
- NO representa a un cliente.
- NO contiene client_id.
- NO representa una reserva de expediente.
- Solo puede existir 0 o 1 reserva activa.
- Este servicio NO reserva ni cancela en ICP Plus.
  Únicamente conserva el estado obtenido por futuros flujos
  gobernados de reserva/cancelación.

Persistencia V1:
    config_service
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from threading import RLock

from backend.services import config_service


CONFIG_KEY = (
    "icpplus_test_reservation_v1"
)

_LOCK = RLock()


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _now_iso():
    return (
        datetime.now()
        .astimezone()
        .isoformat(
            timespec="seconds"
        )
    )


def _default_state():
    return {
        "active": None,
        "history": [],
    }


def _load_unlocked():
    raw = config_service.get_config(
        CONFIG_KEY,
        "",
    )

    if isinstance(raw, dict):
        data = deepcopy(raw)
    else:
        raw = _text(raw)

        if not raw:
            return _default_state()

        try:
            data = json.loads(raw)
        except Exception:
            return _default_state()

    if not isinstance(data, dict):
        return _default_state()

    active = data.get("active")

    if not isinstance(active, dict):
        active = None

    history = data.get("history")

    if not isinstance(history, list):
        history = []

    return {
        "active": active,
        "history": history,
    }


def _save_unlocked(state):
    config_service.set_config(
        CONFIG_KEY,
        json.dumps(
            state,
            ensure_ascii=False,
            sort_keys=True,
        ),
    )

    return True


def get_state():
    with _LOCK:
        return deepcopy(
            _load_unlocked()
        )


def get_active_reservation():
    state = get_state()

    active = state.get(
        "active"
    )

    if not isinstance(
        active,
        dict,
    ):
        return None

    return deepcopy(
        active
    )


def active_reservation_count():
    return (
        1
        if get_active_reservation()
        else 0
    )


def register_active_reservation(
    data,
    *,
    reserved_at=None,
):
    """
    Registra el resultado de una futura reserva real realizada
    con EL PERFIL DE PRUEBA.

    No ejecuta ninguna acción contra ICP Plus.
    """

    payload = dict(
        data
        or {}
    )

    forbidden = {
        "client_id",
        "cliente_id",
        "expediente_id",
    }

    present_forbidden = sorted(
        key
        for key in forbidden
        if payload.get(key) is not None
    )

    if present_forbidden:
        raise ValueError(
            "ICPPLUS_TEST_RESERVATION_"
            "MUST_NOT_REFERENCE_CLIENT:"
            + ",".join(
                present_forbidden
            )
        )

    required = {
        "provider":
            payload.get("provider"),
        "province_key":
            payload.get("province_key"),
        "procedure_key":
            payload.get("procedure_key"),
        "office_key":
            payload.get("office_key"),
        "appointment_date":
            payload.get("appointment_date"),
        "appointment_time":
            payload.get("appointment_time"),
    }

    missing = [
        key
        for key, value
        in required.items()
        if not _text(value)
    ]

    if missing:
        raise ValueError(
            "ICPPLUS_TEST_RESERVATION_MISSING:"
            + ",".join(missing)
        )

    with _LOCK:
        state = (
            _load_unlocked()
        )

        if state.get(
            "active"
        ):
            raise RuntimeError(
                "ICPPLUS_TEST_RESERVATION_ALREADY_ACTIVE"
            )

        active = {
            "status":
                "RESERVED",

            "provider":
                _text(
                    payload.get(
                        "provider"
                    )
                ).upper(),

            "province_key":
                _text(
                    payload.get(
                        "province_key"
                    )
                ).upper(),

            "procedure_key":
                _text(
                    payload.get(
                        "procedure_key"
                    )
                ).upper(),

            "office_key":
                _text(
                    payload.get(
                        "office_key"
                    )
                ).upper(),

            "office_text":
                _text(
                    payload.get(
                        "office_text"
                    )
                ),

            "appointment_date":
                _text(
                    payload.get(
                        "appointment_date"
                    )
                ),

            "appointment_time":
                _text(
                    payload.get(
                        "appointment_time"
                    )
                ),

            "reserved_at":
                (
                    _text(
                        reserved_at
                    )
                    or _now_iso()
                ),
        }

        state[
            "active"
        ] = active

        _save_unlocked(
            state
        )

        return deepcopy(
            active
        )


def clear_active_reservation(
    *,
    cancelled_at=None,
    reason=None,
):
    """
    Registra que la cita de prueba dejó de estar reservada.

    Tampoco ejecuta la cancelación en ICP Plus. El futuro motor
    de cancelación llamará aquí DESPUÉS de una cancelación real.
    """

    with _LOCK:
        state = (
            _load_unlocked()
        )

        active = state.get(
            "active"
        )

        if not isinstance(
            active,
            dict,
        ):
            return None

        historical = deepcopy(
            active
        )

        historical[
            "status"
        ] = "CANCELLED"

        historical[
            "cancelled_at"
        ] = (
            _text(
                cancelled_at
            )
            or _now_iso()
        )

        historical[
            "cancel_reason"
        ] = (
            _text(reason)
            or None
        )

        state[
            "history"
        ].append(
            historical
        )

        state[
            "active"
        ] = None

        _save_unlocked(
            state
        )

        return deepcopy(
            historical
        )
