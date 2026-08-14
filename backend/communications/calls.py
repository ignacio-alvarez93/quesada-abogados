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

from dataclasses import dataclass
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
