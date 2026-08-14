"""
Dominio puro del seguimiento operativo de llamadas.

Una llamada y su seguimiento son conceptos distintos:

- CommunicationCall describe qué ocurrió telefónicamente.
- CommunicationCallFollowUp describe trabajo pendiente del despacho.

No contiene persistencia.
No conoce SQLite.
No conoce Flet.
No conoce WhatsApp.
No conoce Enlace móvil.
"""

from dataclasses import dataclass, replace


CALL_FOLLOW_UP_PENDING = "PENDING"
CALL_FOLLOW_UP_IN_PROGRESS = "IN_PROGRESS"
CALL_FOLLOW_UP_RESOLVED = "RESOLVED"


CALL_FOLLOW_UP_ALLOWED_TRANSITIONS = {
    CALL_FOLLOW_UP_PENDING: frozenset(
        {
            CALL_FOLLOW_UP_IN_PROGRESS,
            CALL_FOLLOW_UP_RESOLVED,
        }
    ),
    CALL_FOLLOW_UP_IN_PROGRESS: frozenset(
        {
            CALL_FOLLOW_UP_PENDING,
            CALL_FOLLOW_UP_RESOLVED,
        }
    ),
}


@dataclass(frozen=True)
class CommunicationCallFollowUp:
    """
    Trabajo operativo asociado a una llamada.

    Normalmente source_call_id será una llamada entrante MISSED.

    La ausencia de una fila de seguimiento significa que
    la llamada no genera trabajo pendiente.
    """

    id: int | None
    source_call_id: int

    status: str = CALL_FOLLOW_UP_PENDING

    resolved_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class CommunicationCallCallback:
    """
    Relaciona una llamada perdida con un intento de devolución.

    Una misma llamada perdida puede tener múltiples callbacks.
    """

    id: int | None

    source_call_id: int
    callback_call_id: int

    created_at: str | None = None


@dataclass(frozen=True)
class CommunicationCallFollowUpOverview:
    """
    Proyección de lectura para el inventario operativo.

    Combina el seguimiento con el contexto mínimo de la
    llamada origen sin introducir SQL en frontend/Flet.
    """

    follow_up_id: int
    source_call_id: int

    follow_up_status: str

    channel: str
    phone_number: str

    display_name_snapshot: str | None = None

    thread_id: int | None = None
    client_id: int | None = None
    expedient_id: int | None = None

    source_call_status: str | None = None

    source_call_created_at: str | None = None
    source_call_ringing_at: str | None = None
    source_call_ended_at: str | None = None

    callback_count: int = 0
    latest_callback_at: str | None = None


class InvalidCallFollowUpTransition(
    ValueError
):
    """Transición operativa de llamada no permitida."""


def can_transition_call_follow_up(
    current_status,
    target_status,
):
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
        CALL_FOLLOW_UP_ALLOWED_TRANSITIONS.get(
            current,
            frozenset(),
        )
    )


def transition_call_follow_up(
    follow_up,
    target_status,
    *,
    resolved_at=None,
):
    """
    Devuelve un nuevo seguimiento inmutable.

    Repetir el estado es NOOP.

    RESOLVED requiere resolved_at explícito:
    el dominio no consulta el reloj del sistema.
    """
    current = str(
        follow_up.status
        or ""
    ).strip().upper()

    target = str(
        target_status
        or ""
    ).strip().upper()

    if current == target:
        return follow_up

    if not can_transition_call_follow_up(
        current,
        target,
    ):
        raise InvalidCallFollowUpTransition(
            "Transición de seguimiento "
            "no permitida: "
            f"{current or '<EMPTY>'} -> "
            f"{target or '<EMPTY>'}"
        )

    if (
        target
        == CALL_FOLLOW_UP_RESOLVED
    ):
        resolved_value = str(
            resolved_at
            or ""
        ).strip()

        if not resolved_value:
            raise ValueError(
                "resolved_at es obligatorio "
                "al resolver un seguimiento"
            )

        return replace(
            follow_up,
            status=target,
            resolved_at=resolved_value,
        )

    return replace(
        follow_up,
        status=target,
        resolved_at=None,
    )
