"""
Estado persistente de las cards del monitor ICP Plus.

No contiene SQL.

Persistencia V1:
    config_service

Contrato lógico:
    provider + flow_key + office_key

Se conservan separadamente:
- última observación;
- última observación ONLINE válida;
- últimas citas conocidas.

Un BLOCKED/DOWN/DEGRADED/UNKNOWN nunca borra una
disponibilidad válida anterior ni sus citas conocidas.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from threading import RLock

from backend.services import config_service


CONFIG_KEY = (
    "icpplus_monitor_cards_v1"
)

HISTORY_CONFIG_KEY = (
    "icpplus_monitor_history_v1"
)

HISTORY_LIMIT = 250

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


def _loads(raw):
    if isinstance(
        raw,
        dict,
    ):
        return deepcopy(
            raw
        )

    raw = _text(
        raw
    )

    if not raw:
        return {}

    try:
        value = json.loads(
            raw
        )
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return {}

    if not isinstance(
        value,
        dict,
    ):
        return {}

    return value


def _load_unlocked():
    return _loads(
        config_service.get_config(
            CONFIG_KEY,
            "",
        )
    )


def _save_unlocked(data):
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
    )

    config_service.set_config(
        CONFIG_KEY,
        encoded,
    )

    return True


def _load_history_unlocked():
    raw = config_service.get_config(
        HISTORY_CONFIG_KEY,
        "",
    )

    if isinstance(
        raw,
        list,
    ):
        return deepcopy(
            raw
        )

    raw = _text(
        raw
    )

    if not raw:
        return []

    try:
        value = json.loads(
            raw
        )

    except Exception:
        return []

    if not isinstance(
        value,
        list,
    ):
        return []

    return [
        deepcopy(item)
        for item in value
        if isinstance(
            item,
            dict,
        )
    ]


def _save_history_unlocked(
    items,
):
    items = list(
        items
        or []
    )[-HISTORY_LIMIT:]

    config_service.set_config(
        HISTORY_CONFIG_KEY,
        json.dumps(
            items,
            ensure_ascii=False,
            sort_keys=True,
        ),
    )

    return True


def _card_key(
    provider,
    flow_key,
    office_key,
):
    return "|".join(
        (
            _text(provider).upper(),
            _text(flow_key).upper(),
            _text(office_key).upper(),
        )
    )


def _appointments(value):
    result = []

    for item in (
        value
        or []
    ):
        if isinstance(
            item,
            dict,
        ):
            normalized = {
                "date":
                    _text(
                        item.get(
                            "date"
                        )
                    ),
                "time":
                    _text(
                        item.get(
                            "time"
                        )
                    ),
            }

        else:
            normalized = {
                "date":
                    _text(item),
                "time":
                    "",
            }

        if (
            normalized["date"]
            or normalized["time"]
        ):
            result.append(
                normalized
            )

    return result


def record_result(
    *,
    provider,
    flow_key,
    province_key=None,
    procedure_key=None,
    office_key,
    office_text=None,
    result,
    checked_at=None,
):
    """
    Inserta/actualiza una card.

    El estado actual siempre avanza.

    last_valid solo avanza con:
        ONLINE + AVAILABLE/UNAVAILABLE

    last_known_appointments solo avanza cuando una respuesta
    válida contiene citas. Un BLOCKED nunca lo vacía.
    """

    provider = (
        _text(provider)
        .upper()
        or "ICP_PLUS"
    )

    flow_key = (
        _text(flow_key)
        .upper()
    )

    office_key = (
        _text(office_key)
        .upper()
    )

    if not flow_key:
        raise ValueError(
            "flow_key obligatorio"
        )

    if not office_key:
        raise ValueError(
            "office_key obligatorio"
        )

    result = dict(
        result
        or {}
    )

    checked_at = (
        _text(
            checked_at
        )
        or _now_iso()
    )

    portal_status = (
        _text(
            result.get(
                "portal_status"
            )
        ).upper()
        or "UNKNOWN"
    )

    availability_status = (
        _text(
            result.get(
                "availability_status"
            )
        ).upper()
        or "UNKNOWN"
    )

    appointments = _appointments(
        result.get(
            "appointments"
        )
    )

    observation = {
        "checked_at":
            checked_at,

        "page":
            _text(
                result.get(
                    "page"
                )
            )
            or "UNKNOWN",

        "portal_status":
            portal_status,

        "availability_status":
            availability_status,

        "result_class":
            _text(
                result.get(
                    "result_class"
                )
            )
            or availability_status,

        "support_id":
            (
                _text(
                    result.get(
                        "support_id"
                    )
                )
                or None
            ),

        "navigation_error":
            (
                _text(
                    result.get(
                        "navigation_error"
                    )
                )
                or None
            ),

        "appointments":
            appointments,

        "appointment_count":
            len(
                appointments
            ),
    }

    key = _card_key(
        provider,
        flow_key,
        office_key,
    )

    with _LOCK:
        store = (
            _load_unlocked()
        )

        previous = dict(
            store.get(
                key
            )
            or {}
        )

        card = {
            "key":
                key,

            "provider":
                provider,

            "flow_key":
                flow_key,

            "province_key":
                (
                    _text(
                        province_key
                    ).upper()
                    or previous.get(
                        "province_key"
                    )
                ),

            "procedure_key":
                (
                    _text(
                        procedure_key
                    ).upper()
                    or previous.get(
                        "procedure_key"
                    )
                ),

            "office_key":
                office_key,

            "office_text":
                (
                    _text(
                        office_text
                    )
                    or previous.get(
                        "office_text"
                    )
                    or office_key
                ),

            "current":
                observation,

            "last_valid":
                deepcopy(
                    previous.get(
                        "last_valid"
                    )
                ),

            "last_known_appointments":
                deepcopy(
                    previous.get(
                        "last_known_appointments"
                    )
                    or []
                ),
        }

        reliable = (
            portal_status
            == "ONLINE"
            and
            availability_status
            in {
                "AVAILABLE",
                "UNAVAILABLE",
            }
        )

        if reliable:
            card[
                "last_valid"
            ] = deepcopy(
                observation
            )

            # Una respuesta UNAVAILABLE actualiza correctamente
            # el estado actual, pero no destruye citas históricas.
            if appointments:
                card[
                    "last_known_appointments"
                ] = deepcopy(
                    appointments
                )

        store[
            key
        ] = card

        _save_unlocked(
            store
        )

        # ----------------------------------------------------
        # Histórico de comprobaciones.
        #
        # No sustituye las cards: añade una traza temporal
        # separada para el panel derecho del dashboard.
        # ----------------------------------------------------

        history = (
            _load_history_unlocked()
        )

        history.append(
            {
                "provider":
                    provider,

                "flow_key":
                    flow_key,

                "province_key":
                    card.get(
                        "province_key"
                    ),

                "procedure_key":
                    card.get(
                        "procedure_key"
                    ),

                "office_key":
                    office_key,

                "office_text":
                    card.get(
                        "office_text"
                    ),

                "checked_at":
                    checked_at,

                "portal_status":
                    portal_status,

                "availability_status":
                    availability_status,

                "result_class":
                    observation.get(
                        "result_class"
                    ),

                "appointment_count":
                    len(
                        appointments
                    ),

                # Snapshot exacto de ESTA pasada.
                #
                # El historial de citas debe poder representar
                # una comprobación como una sola card que
                # contiene todas las citas observadas en ella.
                "appointments":
                    deepcopy(
                        appointments
                    ),

                "support_id":
                    observation.get(
                        "support_id"
                    ),

                "navigation_error":
                    observation.get(
                        "navigation_error"
                    ),
            }
        )

        _save_history_unlocked(
            history
        )

        return deepcopy(
            card
        )


def list_history(
    *,
    limit=50,
):
    try:
        limit = int(
            limit
        )
    except Exception:
        limit = 50

    limit = max(
        1,
        min(
            limit,
            HISTORY_LIMIT,
        ),
    )

    with _LOCK:
        items = (
            _load_history_unlocked()
        )

    items = list(
        reversed(
            items
        )
    )

    return deepcopy(
        items[:limit]
    )


def list_cards():
    with _LOCK:
        store = (
            _load_unlocked()
        )

    cards = [
        deepcopy(card)
        for card
        in store.values()
        if isinstance(
            card,
            dict,
        )
    ]

    cards.sort(
        key=lambda item: (
            _text(
                item.get(
                    "provider"
                )
            ),
            _text(
                item.get(
                    "flow_key"
                )
            ),
            _text(
                item.get(
                    "office_text"
                )
            ),
        )
    )

    return cards


def get_card(
    *,
    provider,
    flow_key,
    office_key,
):
    key = _card_key(
        provider,
        flow_key,
        office_key,
    )

    with _LOCK:
        card = (
            _load_unlocked()
            .get(
                key
            )
        )

    if not isinstance(
        card,
        dict,
    ):
        return None

    return deepcopy(
        card
    )
