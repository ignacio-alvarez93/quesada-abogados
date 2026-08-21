"""
Scheduler persistente para vigilancia ICP Plus.

Reglas de gobierno:
- múltiples schedulers activos;
- nunca más de un bot ICP Plus simultáneo;
- intervalo mínimo por scheduler: 15 minutos;
- cooldown GLOBAL: 15 minutos desde que termina un bot
  hasta que puede comenzar el siguiente;
- schedulers vencidos esperan en cola;
- no contiene Flet;
- no contiene SQL;
- no conoce clientes ni expedientes;
- no reserva citas.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from threading import RLock
import uuid

from backend.services import config_service


CONFIG_KEY = (
    "icpplus_scheduler_v1"
)

MIN_INTERVAL_MINUTES = 15
GLOBAL_COOLDOWN_MINUTES = 15
WARNING_SECONDS = 60

# El polling del worker no puede reclamar exactamente en el
# mismo microsegundo del turno previsto. Un intento programado
# válidamente dentro de la ventana admite este pequeño margen.
#
# No es un retry ni amplía la vigilancia funcionalmente:
# superado este margen, el intento se considera perdido.
CLAIM_LATE_GRACE_SECONDS = 60

ACTIVE_STATUSES = {
    "ACTIVE",
    "RUNNING",
    "PAUSED",
}

TERMINAL_STATUSES = {
    "STOPPED",
    "COMPLETED",
}

_LOCK = RLock()


def _now():
    return (
        datetime.now()
        .astimezone()
    )


def _ensure_datetime(
    value,
):
    if isinstance(
        value,
        datetime,
    ):
        result = value

    else:
        result = datetime.fromisoformat(
            str(value)
        )

    if result.tzinfo is None:
        result = result.astimezone()

    return result


def _iso(
    value,
):
    return (
        _ensure_datetime(value)
        .isoformat(
            timespec="seconds"
        )
    )


def _default_state():
    return {
        "schedules": {},
        "global": {
            "running_schedule_id":
                None,

            "last_run_finished_at":
                None,

            "last_warning_event":
                None,
        },
    }


def _load_unlocked():
    raw = config_service.get_config(
        CONFIG_KEY,
        "",
    )

    if not raw:
        return _default_state()

    if isinstance(
        raw,
        dict,
    ):
        data = deepcopy(
            raw
        )

    else:
        try:
            data = json.loads(
                str(raw)
            )

        except Exception:
            return _default_state()

    if not isinstance(
        data,
        dict,
    ):
        return _default_state()

    schedules = data.get(
        "schedules"
    )

    global_state = data.get(
        "global"
    )

    if not isinstance(
        schedules,
        dict,
    ):
        schedules = {}

    if not isinstance(
        global_state,
        dict,
    ):
        global_state = {}

    return {
        "schedules":
            schedules,

        "global": {
            "running_schedule_id":
                global_state.get(
                    "running_schedule_id"
                ),

            "last_run_finished_at":
                global_state.get(
                    "last_run_finished_at"
                ),

            "last_warning_event":
                (
                    deepcopy(
                        global_state.get(
                            "last_warning_event"
                        )
                    )
                    if isinstance(
                        global_state.get(
                            "last_warning_event"
                        ),
                        dict,
                    )
                    else None
                ),
        },
    }


def _save_unlocked(
    state,
):
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


def list_schedules(
    *,
    include_terminal=True,
):
    state = get_state()

    result = list(
        state[
            "schedules"
        ].values()
    )

    if not include_terminal:
        result = [
            item
            for item in result
            if item.get(
                "status"
            )
            not in TERMINAL_STATUSES
        ]

    result.sort(
        key=lambda item: (
            item.get(
                "created_at"
            )
            or "",
            int(
                item.get(
                    "created_order"
                )
                or 0
            ),
            item.get(
                "scheduler_id"
            )
            or "",
        )
    )

    return deepcopy(
        result
    )


def list_active():
    return [
        item
        for item in list_schedules(
            include_terminal=False
        )
        if item.get(
            "status"
        )
        in ACTIVE_STATUSES
    ]


def active_count():
    return len(
        list_active()
    )


def _same_target(
    schedule,
    *,
    province_key,
    procedure_key,
    office_key,
):
    return (
        str(
            schedule.get(
                "province_key"
            )
            or ""
        ).upper()
        == str(
            province_key
            or ""
        ).upper()

        and

        str(
            schedule.get(
                "procedure_key"
            )
            or ""
        ).upper()
        == str(
            procedure_key
            or ""
        ).upper()

        and

        str(
            schedule.get(
                "office_key"
            )
            or ""
        ).upper()
        == str(
            office_key
            or ""
        ).upper()
    )


def create_schedule(
    *,
    province_key,
    procedure_key,
    office_key,
    procedure_text=None,
    office_text=None,
    interval_minutes,
    duration_minutes,
    now=None,
):
    now = _ensure_datetime(
        now
        or _now()
    )

    interval_minutes = int(
        interval_minutes
    )

    duration_minutes = int(
        duration_minutes
    )

    if (
        interval_minutes
        < MIN_INTERVAL_MINUTES
    ):
        raise ValueError(
            "ICPPLUS_SCHEDULER_INTERVAL_"
            "MINIMUM_15_MINUTES"
        )

    if (
        duration_minutes
        < interval_minutes
    ):
        raise ValueError(
            "ICPPLUS_SCHEDULER_DURATION_"
            "MUST_COVER_INTERVAL"
        )

    province_key = str(
        province_key
        or ""
    ).strip().upper()

    procedure_key = str(
        procedure_key
        or ""
    ).strip().upper()

    office_key = str(
        office_key
        or ""
    ).strip().upper()

    if (
        not province_key
        or not procedure_key
        or not office_key
    ):
        raise ValueError(
            "ICPPLUS_SCHEDULER_TARGET_REQUIRED"
        )

    with _LOCK:
        state = (
            _load_unlocked()
        )

        for existing in (
            state[
                "schedules"
            ].values()
        ):
            if (
                existing.get(
                    "status"
                )
                in ACTIVE_STATUSES

                and

                _same_target(
                    existing,
                    province_key=province_key,
                    procedure_key=procedure_key,
                    office_key=office_key,
                )
            ):
                raise ValueError(
                    "ICPPLUS_SCHEDULER_"
                    "DUPLICATE_ACTIVE_TARGET"
                )

        scheduler_id = (
            "ICPPLUS-"
            + uuid.uuid4().hex[
                :12
            ].upper()
        )

        existing_orders = [
            int(
                item.get(
                    "created_order"
                )
                or 0
            )
            for item in (
                state[
                    "schedules"
                ].values()
            )
        ]

        created_order = (
            max(
                existing_orders,
                default=0,
            )
            + 1
        )

        first_run_at = (
            now
            + timedelta(
                minutes=(
                    interval_minutes
                )
            )
        )

        ends_at = (
            now
            + timedelta(
                minutes=(
                    duration_minutes
                )
            )
        )

        schedule = {
            "scheduler_id":
                scheduler_id,

            "provider":
                "ICP_PLUS",

            "province_key":
                province_key,

            "procedure_key":
                procedure_key,

            "procedure_text":
                str(
                    procedure_text
                    or procedure_key
                ),

            "office_key":
                office_key,

            "office_text":
                str(
                    office_text
                    or office_key
                ),

            "interval_minutes":
                interval_minutes,

            "duration_minutes":
                duration_minutes,

            "warning_seconds":
                WARNING_SECONDS,

            "created_at":
                _iso(
                    now
                ),

            "created_order":
                created_order,

            "ends_at":
                _iso(
                    ends_at
                ),

            "next_run_at":
                _iso(
                    first_run_at
                ),

            "status":
                "ACTIVE",

            "attempt_count":
                0,

            "skipped_attempt_count":
                0,

            "last_reconciled_at":
                None,

            "last_run_started_at":
                None,

            "last_run_finished_at":
                None,

            "last_result":
                None,
        }

        state[
            "schedules"
        ][
            scheduler_id
        ] = schedule

        _save_unlocked(
            state
        )

        return deepcopy(
            schedule
        )


def get_schedule(
    scheduler_id,
):
    state = get_state()

    item = (
        state[
            "schedules"
        ].get(
            str(
                scheduler_id
            )
        )
    )

    if not isinstance(
        item,
        dict,
    ):
        return None

    return deepcopy(
        item
    )


def _global_cooldown_until(
    state,
):
    value = (
        state[
            "global"
        ].get(
            "last_run_finished_at"
        )
    )

    if not value:
        return None

    return (
        _ensure_datetime(
            value
        )
        + timedelta(
            minutes=(
                GLOBAL_COOLDOWN_MINUTES
            )
        )
    )


def effective_run_at(
    schedule,
    *,
    state=None,
):
    schedule = dict(
        schedule
        or {}
    )

    next_run = schedule.get(
        "next_run_at"
    )

    if not next_run:
        return None

    desired = (
        _ensure_datetime(
            next_run
        )
    )

    state = (
        deepcopy(state)
        if state is not None
        else get_state()
    )

    cooldown_until = (
        _global_cooldown_until(
            state
        )
    )

    if (
        cooldown_until is not None
        and cooldown_until
        > desired
    ):
        return cooldown_until

    return desired


def next_candidate(
    *,
    now=None,
):
    now = _ensure_datetime(
        now
        or _now()
    )

    state = get_state()

    if (
        state[
            "global"
        ].get(
            "running_schedule_id"
        )
    ):
        return None

    candidates = []

    for schedule in (
        state[
            "schedules"
        ].values()
    ):
        if (
            schedule.get(
                "status"
            )
            != "ACTIVE"
        ):
            continue

        ends_at = _ensure_datetime(
            schedule[
                "ends_at"
            ]
        )

        run_at = effective_run_at(
            schedule,
            state=state,
        )

        if run_at is None:
            continue

        # La validez depende del turno programado,
        # no del microsegundo en que despierta el polling.
        if run_at > ends_at:
            continue

        # Evitamos ejecutar accesos antiguos tras una
        # suspensión larga del equipo/proceso.
        if (
            now
            > run_at
            + timedelta(
                seconds=(
                    CLAIM_LATE_GRACE_SECONDS
                )
            )
        ):
            continue

        candidates.append(
            (
                run_at,
                _ensure_datetime(
                    schedule[
                        "next_run_at"
                    ]
                ),
                int(
                    schedule.get(
                        "created_order"
                    )
                    or 0
                ),
                str(
                    schedule[
                        "scheduler_id"
                    ]
                ),
                schedule,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
        )
    )

    run_at, _, _, _, schedule = (
        candidates[0]
    )

    result = deepcopy(
        schedule
    )

    result[
        "effective_run_at"
    ] = _iso(
        run_at
    )

    result[
        "warning_at"
    ] = _iso(
        run_at
        - timedelta(
            seconds=(
                WARNING_SECONDS
            )
        )
    )

    result[
        "queued"
    ] = bool(
        run_at
        > _ensure_datetime(
            schedule[
                "next_run_at"
            ]
        )
    )

    return result


def get_last_warning_event():
    state = get_state()

    event = (
        state[
            "global"
        ].get(
            "last_warning_event"
        )
    )

    if not isinstance(
        event,
        dict,
    ):
        return None

    return deepcopy(
        event
    )


def record_warning(
    scheduler_id,
    *,
    effective_run_at,
    warned_at=None,
):
    scheduler_id = str(
        scheduler_id
    )

    warned_at = _ensure_datetime(
        warned_at
        or _now()
    )

    effective_run_at = (
        _ensure_datetime(
            effective_run_at
        )
    )

    with _LOCK:
        state = (
            _load_unlocked()
        )

        schedule = (
            state[
                "schedules"
            ].get(
                scheduler_id
            )
        )

        if not schedule:
            raise ValueError(
                "ICPPLUS_SCHEDULER_NOT_FOUND"
            )

        previous = (
            state[
                "global"
            ].get(
                "last_warning_event"
            )
        )

        effective_iso = _iso(
            effective_run_at
        )

        # Idempotencia: no duplicamos el mismo aviso
        # para el mismo scheduler/turno.
        if (
            isinstance(
                previous,
                dict,
            )
            and previous.get(
                "scheduler_id"
            )
            == scheduler_id
            and previous.get(
                "effective_run_at"
            )
            == effective_iso
        ):
            result = deepcopy(
                previous
            )

            result[
                "_created"
            ] = False

            return result

        event = {
            "event_id":
                (
                    "ICPPLUS-WARNING-"
                    + uuid.uuid4().hex[
                        :12
                    ].upper()
                ),

            "scheduler_id":
                scheduler_id,

            "province_key":
                schedule.get(
                    "province_key"
                ),

            "procedure_key":
                schedule.get(
                    "procedure_key"
                ),

            "procedure_text":
                schedule.get(
                    "procedure_text"
                ),

            "office_key":
                schedule.get(
                    "office_key"
                ),

            "office_text":
                schedule.get(
                    "office_text"
                ),

            "warned_at":
                _iso(
                    warned_at
                ),

            "effective_run_at":
                effective_iso,

            "status":
                "PENDING",

            "resolution":
                None,

            "resolved_at":
                None,
        }

        state[
            "global"
        ][
            "last_warning_event"
        ] = event

        _save_unlocked(
            state
        )

        result = deepcopy(
            event
        )

        result[
            "_created"
        ] = True

        return result


def handle_warning_action(
    event_id,
    *,
    action,
    acted_at=None,
):
    """
    Resuelve una acción humana sobre el aviso T-60.

    SKIP:
        omite únicamente ese intento y programa el siguiente.

    STOP:
        detiene completamente la vigilancia.

    Ninguna de estas acciones modifica el cooldown global,
    porque no se ha ejecutado ningún bot.
    """

    event_id = str(
        event_id
        or ""
    ).strip()

    action = str(
        action
        or ""
    ).strip().upper()

    acted_at = _ensure_datetime(
        acted_at
        or _now()
    )

    if action not in {
        "SKIP",
        "STOP",
    }:
        raise ValueError(
            "ICPPLUS_WARNING_ACTION_INVALID"
        )

    with _LOCK:
        state = (
            _load_unlocked()
        )

        event = (
            state[
                "global"
            ].get(
                "last_warning_event"
            )
        )

        if (
            not isinstance(
                event,
                dict,
            )
            or event.get(
                "event_id"
            )
            != event_id
        ):
            raise ValueError(
                "ICPPLUS_WARNING_EVENT_NOT_FOUND"
            )

        if (
            str(
                event.get(
                    "status"
                )
                or "PENDING"
            ).upper()
            != "PENDING"
        ):
            raise RuntimeError(
                "ICPPLUS_WARNING_ALREADY_RESOLVED"
            )

        scheduler_id = str(
            event.get(
                "scheduler_id"
            )
            or ""
        )

        schedule = (
            state[
                "schedules"
            ].get(
                scheduler_id
            )
        )

        if not schedule:
            raise ValueError(
                "ICPPLUS_SCHEDULER_NOT_FOUND"
            )

        if (
            schedule.get(
                "status"
            )
            != "ACTIVE"
        ):
            raise RuntimeError(
                "ICPPLUS_SCHEDULER_NOT_ACTIVE"
            )

        if action == "SKIP":
            effective_run_at = (
                _ensure_datetime(
                    event[
                        "effective_run_at"
                    ]
                )
            )

            if acted_at >= effective_run_at:
                raise RuntimeError(
                    "ICPPLUS_WARNING_WINDOW_EXPIRED"
                )

            next_run = (
                effective_run_at
                + timedelta(
                    minutes=int(
                        schedule[
                            "interval_minutes"
                        ]
                    )
                )
            )

            ends_at = (
                _ensure_datetime(
                    schedule[
                        "ends_at"
                    ]
                )
            )

            schedule[
                "skipped_attempt_count"
            ] = (
                int(
                    schedule.get(
                        "skipped_attempt_count"
                    )
                    or 0
                )
                + 1
            )

            schedule[
                "last_reconciled_at"
            ] = _iso(
                acted_at
            )

            if next_run > ends_at:
                schedule[
                    "status"
                ] = "COMPLETED"

                schedule[
                    "next_run_at"
                ] = None

            else:
                schedule[
                    "next_run_at"
                ] = _iso(
                    next_run
                )

        else:
            schedule[
                "status"
            ] = "STOPPED"

            schedule[
                "next_run_at"
            ] = None

        event[
            "status"
        ] = "RESOLVED"

        event[
            "resolution"
        ] = action

        event[
            "resolved_at"
        ] = _iso(
            acted_at
        )

        state[
            "global"
        ][
            "last_warning_event"
        ] = event

        _save_unlocked(
            state
        )

        return {
            "event":
                deepcopy(
                    event
                ),

            "schedule":
                deepcopy(
                    schedule
                ),
        }


def _resolve_pending_warning_unlocked(
    state,
    scheduler_id,
    *,
    resolution,
    resolved_at,
):
    event = (
        state[
            "global"
        ].get(
            "last_warning_event"
        )
    )

    if (
        not isinstance(
            event,
            dict,
        )
        or event.get(
            "scheduler_id"
        )
        != str(
            scheduler_id
        )
        or str(
            event.get(
                "status"
            )
            or "PENDING"
        ).upper()
        != "PENDING"
    ):
        return False

    event[
        "status"
    ] = "RESOLVED"

    event[
        "resolution"
    ] = str(
        resolution
    )

    event[
        "resolved_at"
    ] = _iso(
        resolved_at
    )

    return True


def reconcile_overdue(
    *,
    now=None,
):
    """
    Avanza turnos perdidos sin ejecutarlos.

    Nunca recupera en ráfaga ejecuciones que debieron ocurrir
    mientras el worker/PC estaba apagado.

    Además garantiza que el siguiente turno quede fuera de la
    ventana T-60 para poder emitir el aviso previo.
    """

    now = _ensure_datetime(
        now
        or _now()
    )

    minimum_future = (
        now
        + timedelta(
            seconds=(
                WARNING_SECONDS
            )
        )
    )

    changed = []

    with _LOCK:
        state = (
            _load_unlocked()
        )

        for scheduler_id, schedule in (
            state[
                "schedules"
            ].items()
        ):
            if (
                schedule.get(
                    "status"
                )
                != "ACTIVE"
            ):
                continue

            next_run_raw = (
                schedule.get(
                    "next_run_at"
                )
            )

            if not next_run_raw:
                continue

            next_run = (
                _ensure_datetime(
                    next_run_raw
                )
            )

            ends_at = (
                _ensure_datetime(
                    schedule[
                        "ends_at"
                    ]
                )
            )

            if now > ends_at:
                schedule[
                    "status"
                ] = "COMPLETED"

                schedule[
                    "next_run_at"
                ] = None

                _resolve_pending_warning_unlocked(
                    state,
                    scheduler_id,
                    resolution="RECONCILED",
                    resolved_at=now,
                )

                changed.append(
                    scheduler_id
                )

                continue

            if (
                next_run
                > minimum_future
            ):
                continue

            interval = timedelta(
                minutes=int(
                    schedule[
                        "interval_minutes"
                    ]
                )
            )

            skipped = 0

            while (
                next_run
                <= minimum_future
            ):
                next_run = (
                    next_run
                    + interval
                )

                skipped += 1

            if next_run > ends_at:
                schedule[
                    "status"
                ] = "COMPLETED"

                schedule[
                    "next_run_at"
                ] = None

            else:
                schedule[
                    "next_run_at"
                ] = _iso(
                    next_run
                )

            schedule[
                "skipped_attempt_count"
            ] = (
                int(
                    schedule.get(
                        "skipped_attempt_count"
                    )
                    or 0
                )
                + skipped
            )

            schedule[
                "last_reconciled_at"
            ] = _iso(
                now
            )

            _resolve_pending_warning_unlocked(
                state,
                scheduler_id,
                resolution="RECONCILED",
                resolved_at=now,
            )

            changed.append(
                scheduler_id
            )

        if changed:
            _save_unlocked(
                state
            )

    return changed


def claim_next_due(
    *,
    now=None,
):
    now = _ensure_datetime(
        now
        or _now()
    )

    with _LOCK:
        state = (
            _load_unlocked()
        )

        if (
            state[
                "global"
            ].get(
                "running_schedule_id"
            )
        ):
            return None

        candidates = []

        for schedule in (
            state[
                "schedules"
            ].values()
        ):
            if (
                schedule.get(
                    "status"
                )
                != "ACTIVE"
            ):
                continue

            ends_at = (
                _ensure_datetime(
                    schedule[
                        "ends_at"
                    ]
                )
            )

            run_at = effective_run_at(
                schedule,
                state=state,
            )

            if run_at is None:
                continue

            # El turno debe haber sido programado dentro
            # de la duración de la vigilancia.
            #
            # run_at == ends_at sigue siendo válido.
            if run_at > ends_at:
                continue

            if run_at > now:
                continue

            # Margen únicamente técnico para el polling.
            # Nunca recuperamos aquí ejecuciones antiguas.
            if (
                now
                > run_at
                + timedelta(
                    seconds=(
                        CLAIM_LATE_GRACE_SECONDS
                    )
                )
            ):
                continue

            candidates.append(
                (
                    run_at,
                    _ensure_datetime(
                        schedule[
                            "next_run_at"
                        ]
                    ),
                    int(
                        schedule.get(
                            "created_order"
                        )
                        or 0
                    ),
                    schedule[
                        "scheduler_id"
                    ],
                    schedule,
                )
            )

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
            )
        )

        schedule = (
            candidates[0][4]
        )

        scheduler_id = (
            schedule[
                "scheduler_id"
            ]
        )

        schedule[
            "status"
        ] = "RUNNING"

        schedule[
            "last_run_started_at"
        ] = _iso(
            now
        )

        state[
            "global"
        ][
            "running_schedule_id"
        ] = scheduler_id

        warning_event = (
            state[
                "global"
            ].get(
                "last_warning_event"
            )
        )

        if (
            isinstance(
                warning_event,
                dict,
            )
            and warning_event.get(
                "scheduler_id"
            )
            == scheduler_id
            and str(
                warning_event.get(
                    "status"
                )
                or "PENDING"
            ).upper()
            == "PENDING"
        ):
            warning_event[
                "status"
            ] = "RESOLVED"

            warning_event[
                "resolution"
            ] = "RUN_STARTED"

            warning_event[
                "resolved_at"
            ] = _iso(
                now
            )

        _save_unlocked(
            state
        )

        return deepcopy(
            schedule
        )


def mark_run_finished(
    scheduler_id,
    *,
    result=None,
    finished_at=None,
):
    finished_at = (
        _ensure_datetime(
            finished_at
            or _now()
        )
    )

    scheduler_id = str(
        scheduler_id
    )

    with _LOCK:
        state = (
            _load_unlocked()
        )

        schedule = (
            state[
                "schedules"
            ].get(
                scheduler_id
            )
        )

        if not schedule:
            raise ValueError(
                "ICPPLUS_SCHEDULER_NOT_FOUND"
            )

        if (
            state[
                "global"
            ].get(
                "running_schedule_id"
            )
            != scheduler_id
        ):
            raise RuntimeError(
                "ICPPLUS_SCHEDULER_NOT_RUNNING"
            )

        schedule[
            "attempt_count"
        ] = (
            int(
                schedule.get(
                    "attempt_count"
                )
                or 0
            )
            + 1
        )

        schedule[
            "last_run_finished_at"
        ] = _iso(
            finished_at
        )

        schedule[
            "last_result"
        ] = deepcopy(
            result
        )

        state[
            "global"
        ][
            "running_schedule_id"
        ] = None

        state[
            "global"
        ][
            "last_run_finished_at"
        ] = _iso(
            finished_at
        )

        next_run = (
            finished_at
            + timedelta(
                minutes=int(
                    schedule[
                        "interval_minutes"
                    ]
                )
            )
        )

        ends_at = _ensure_datetime(
            schedule[
                "ends_at"
            ]
        )

        if next_run > ends_at:
            schedule[
                "status"
            ] = "COMPLETED"

            schedule[
                "next_run_at"
            ] = None

        else:
            schedule[
                "status"
            ] = "ACTIVE"

            schedule[
                "next_run_at"
            ] = _iso(
                next_run
            )

        _save_unlocked(
            state
        )

        return deepcopy(
            schedule
        )


def stop_schedule(
    scheduler_id,
):
    scheduler_id = str(
        scheduler_id
    )

    with _LOCK:
        state = (
            _load_unlocked()
        )

        schedule = (
            state[
                "schedules"
            ].get(
                scheduler_id
            )
        )

        if not schedule:
            return False

        if (
            schedule.get(
                "status"
            )
            == "RUNNING"
        ):
            raise RuntimeError(
                "ICPPLUS_SCHEDULER_RUNNING_"
                "CANNOT_STOP_DIRECTLY"
            )

        schedule[
            "status"
        ] = "STOPPED"

        schedule[
            "next_run_at"
        ] = None

        _save_unlocked(
            state
        )

        return True
