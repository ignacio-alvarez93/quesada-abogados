"""
Dominio puro de llamadas del núcleo de Comunicaciones.

No contiene persistencia.
No conoce SQLite.
No conoce Supabase.
No conoce Flet.
No conoce SeleniumBase.

Una llamada puede existir aunque todavía no esté vinculada
a un cliente, expediente o conversación del CRM.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any


CALL_STATUS_CREATED = "CREATED"
CALL_STATUS_DIALING = "DIALING"
CALL_STATUS_RINGING = "RINGING"
CALL_STATUS_ANSWERED = "ANSWERED"
CALL_STATUS_ENDED = "ENDED"
CALL_STATUS_MISSED = "MISSED"
CALL_STATUS_REJECTED = "REJECTED"
CALL_STATUS_BUSY = "BUSY"
CALL_STATUS_FAILED = "FAILED"
CALL_STATUS_CANCELLED = "CANCELLED"


CALL_DIRECTION_INBOUND = "INBOUND"
CALL_DIRECTION_OUTBOUND = "OUTBOUND"


CALL_ALLOWED_TRANSITIONS = {
    CALL_STATUS_CREATED: frozenset(
        {
            CALL_STATUS_DIALING,
            CALL_STATUS_RINGING,
            CALL_STATUS_FAILED,
            CALL_STATUS_CANCELLED,
        }
    ),
    CALL_STATUS_DIALING: frozenset(
        {
            CALL_STATUS_RINGING,
            CALL_STATUS_ANSWERED,
            CALL_STATUS_MISSED,
            CALL_STATUS_REJECTED,
            CALL_STATUS_BUSY,
            CALL_STATUS_FAILED,
            CALL_STATUS_CANCELLED,
        }
    ),
    CALL_STATUS_RINGING: frozenset(
        {
            CALL_STATUS_ANSWERED,
            CALL_STATUS_MISSED,
            CALL_STATUS_REJECTED,
            CALL_STATUS_BUSY,
            CALL_STATUS_FAILED,
            CALL_STATUS_CANCELLED,
        }
    ),
    CALL_STATUS_ANSWERED: frozenset(
        {
            CALL_STATUS_ENDED,
        }
    ),
}


CALL_TERMINAL_STATUSES = frozenset(
    {
        CALL_STATUS_ENDED,
        CALL_STATUS_MISSED,
        CALL_STATUS_REJECTED,
        CALL_STATUS_BUSY,
        CALL_STATUS_FAILED,
        CALL_STATUS_CANCELLED,
    }
)


@dataclass(frozen=True)
class CommunicationCall:
    """
    Representa una llamada independientemente de su proveedor.

    client_id, expedient_id y thread_id son opcionales para
    soportar llamadas con interlocutores todavía no identificados
    y el futuro Enlace móvil.
    """

    id: int | None

    channel: str
    direction: str
    phone_number: str

    thread_id: int | None = None
    client_id: int | None = None
    expedient_id: int | None = None

    display_name_snapshot: str | None = None

    reason_code: str | None = None
    reason_detail: str | None = None

    status: str = CALL_STATUS_CREATED
    outcome_code: str | None = None

    provider: str | None = None
    provider_call_id: str | None = None
    external_call_key: str | None = None

    created_at: str | None = None
    dialed_at: str | None = None
    ringing_at: str | None = None
    answered_at: str | None = None
    ended_at: str | None = None

    ring_duration_seconds: int | None = None
    talk_duration_seconds: int | None = None
    total_duration_seconds: int | None = None

    notes: str | None = None
    created_by: str | None = None

    metadata: dict[str, Any] | None = None


class InvalidCallTransition(ValueError):
    """Transición de estado de llamada no permitida."""


def can_transition_call_status(
    current_status,
    target_status,
):
    """
    Comprueba una transición sin modificar la llamada.

    Repetir el mismo estado es válido e idempotente.
    """
    current = str(
        current_status
        or ""
    ).strip().upper()

    target = str(
        target_status
        or ""
    ).strip().upper()

    if not current or not target:
        return False

    if current == target:
        return True

    return target in (
        CALL_ALLOWED_TRANSITIONS.get(
            current,
            frozenset(),
        )
    )


def _validate_initial_transition(
    call,
    target_status,
):
    """
    Protege el primer salto según la dirección.

    Entrante:
        CREATED -> RINGING

    Saliente:
        CREATED -> DIALING

    FAILED/CANCELLED siguen permitidos como cierres técnicos
    tempranos en ambos sentidos.
    """
    if call.status != CALL_STATUS_CREATED:
        return

    target = str(
        target_status
        or ""
    ).strip().upper()

    if target in {
        CALL_STATUS_FAILED,
        CALL_STATUS_CANCELLED,
        CALL_STATUS_CREATED,
    }:
        return

    direction = str(
        call.direction
        or ""
    ).strip().upper()

    if (
        direction == CALL_DIRECTION_INBOUND
        and target != CALL_STATUS_RINGING
    ):
        raise InvalidCallTransition(
            "Una llamada entrante debe pasar "
            "de CREATED a RINGING."
        )

    if (
        direction == CALL_DIRECTION_OUTBOUND
        and target != CALL_STATUS_DIALING
    ):
        raise InvalidCallTransition(
            "Una llamada saliente debe pasar "
            "de CREATED a DIALING."
        )


def transition_call_status(
    call,
    target_status,
):
    """
    Devuelve una nueva CommunicationCall con el estado pedido.

    El dominio es inmutable: nunca modifica la instancia original.

    Una repetición del mismo estado devuelve la misma instancia
    para soportar eventos duplicados de proveedores.
    """
    target = str(
        target_status
        or ""
    ).strip().upper()

    current = str(
        call.status
        or ""
    ).strip().upper()

    if current == target:
        return call

    _validate_initial_transition(
        call,
        target,
    )

    if not can_transition_call_status(
        current,
        target,
    ):
        raise InvalidCallTransition(
            "Transición de llamada no permitida: "
            f"{current or '<EMPTY>'} -> "
            f"{target or '<EMPTY>'}"
        )

    return replace(
        call,
        status=target,
    )


class InvalidCallTimestamp(ValueError):
    """Timestamp de llamada inválido o fuera de orden."""


def _parse_call_timestamp(value):
    """
    Convierte un timestamp ISO-8601 a datetime.

    Admite tanto +HH:MM como el sufijo Z.
    No consulta el reloj del sistema.
    """
    if isinstance(
        value,
        datetime,
    ):
        return value

    raw = str(
        value
        or ""
    ).strip()

    if not raw:
        raise InvalidCallTimestamp(
            "El timestamp de llamada es obligatorio."
        )

    normalized = raw

    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    try:
        return datetime.fromisoformat(
            normalized
        )

    except ValueError as exc:
        raise InvalidCallTimestamp(
            "Timestamp de llamada no válido: "
            f"{raw}"
        ) from exc


def _call_timestamp_text(value):
    if isinstance(
        value,
        datetime,
    ):
        return value.isoformat()

    raw = str(
        value
        or ""
    ).strip()

    _parse_call_timestamp(
        raw
    )

    return raw


def _elapsed_seconds(
    start,
    end,
):
    if not start or not end:
        return None

    start_dt = _parse_call_timestamp(
        start
    )

    end_dt = _parse_call_timestamp(
        end
    )

    try:
        elapsed = (
            end_dt
            - start_dt
        ).total_seconds()

    except TypeError as exc:
        raise InvalidCallTimestamp(
            "No se pueden mezclar timestamps "
            "con y sin zona horaria."
        ) from exc

    if elapsed < 0:
        raise InvalidCallTimestamp(
            "Los timestamps de la llamada "
            "están fuera de orden."
        )

    return int(
        elapsed
    )


def _validate_call_event_order(
    call,
    event_at,
):
    event_dt = _parse_call_timestamp(
        event_at
    )

    existing = (
        call.dialed_at,
        call.ringing_at,
        call.answered_at,
        call.ended_at,
    )

    for timestamp in existing:
        if not timestamp:
            continue

        previous_dt = (
            _parse_call_timestamp(
                timestamp
            )
        )

        try:
            out_of_order = (
                event_dt
                < previous_dt
            )

        except TypeError as exc:
            raise InvalidCallTimestamp(
                "No se pueden mezclar timestamps "
                "con y sin zona horaria."
            ) from exc

        if out_of_order:
            raise InvalidCallTimestamp(
                "El evento de llamada es anterior "
                "a un evento ya registrado."
            )


def _calculate_call_durations(
    call,
):
    """
    Calcula únicamente duraciones definitivas.

    Mientras la llamada siga activa, talk/total permanecen None.
    """
    ring_duration = None
    talk_duration = None
    total_duration = None

    if call.ringing_at:
        ring_end = (
            call.answered_at
            or call.ended_at
        )

        if ring_end:
            ring_duration = (
                _elapsed_seconds(
                    call.ringing_at,
                    ring_end,
                )
            )

    if call.ended_at:
        if call.answered_at:
            talk_duration = (
                _elapsed_seconds(
                    call.answered_at,
                    call.ended_at,
                )
            )
        else:
            talk_duration = 0

        total_start = (
            call.dialed_at
            or call.ringing_at
        )

        if total_start:
            total_duration = (
                _elapsed_seconds(
                    total_start,
                    call.ended_at,
                )
            )

    return replace(
        call,
        ring_duration_seconds=(
            ring_duration
        ),
        talk_duration_seconds=(
            talk_duration
        ),
        total_duration_seconds=(
            total_duration
        ),
    )


def transition_call_status_at(
    call,
    target_status,
    event_at,
):
    """
    Aplica una transición y registra su timestamp.

    Es dominio puro:
    - no consulta el reloj;
    - no persiste;
    - no conoce proveedores;
    - eventos repetidos son NOOP.
    """
    target = str(
        target_status
        or ""
    ).strip().upper()

    current = str(
        call.status
        or ""
    ).strip().upper()

    if current == target:
        return call

    event_text = (
        _call_timestamp_text(
            event_at
        )
    )

    _validate_call_event_order(
        call,
        event_text,
    )

    transitioned = (
        transition_call_status(
            call,
            target,
        )
    )

    changes = {}

    if (
        target
        == CALL_STATUS_DIALING
    ):
        changes[
            "dialed_at"
        ] = event_text

    elif (
        target
        == CALL_STATUS_RINGING
    ):
        changes[
            "ringing_at"
        ] = event_text

    elif (
        target
        == CALL_STATUS_ANSWERED
    ):
        changes[
            "answered_at"
        ] = event_text

    if target in CALL_TERMINAL_STATUSES:
        changes[
            "ended_at"
        ] = event_text

    timed = replace(
        transitioned,
        **changes,
    )

    return _calculate_call_durations(
        timed
    )
