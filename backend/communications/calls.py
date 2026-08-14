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
