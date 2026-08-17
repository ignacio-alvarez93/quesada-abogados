"""
Modelos de dominio del núcleo de Comunicaciones.

No contienen persistencia.
No conocen SQLite.
No conocen Supabase.
No conocen Flet.
"""

from dataclasses import dataclass
from typing import Any


CHANNEL_WHATSAPP = "WHATSAPP"
CHANNEL_EMAIL = "EMAIL"
CHANNEL_PHONE = "PHONE"
CHANNEL_SMS = "SMS"

DIRECTION_INBOUND = "INBOUND"
DIRECTION_OUTBOUND = "OUTBOUND"

MESSAGE_STATUS_DRAFT = "DRAFT"
MESSAGE_STATUS_PENDING = "PENDING"
MESSAGE_STATUS_QUEUED = "QUEUED"
MESSAGE_STATUS_SENDING = "SENDING"
MESSAGE_STATUS_SENT = "SENT"
MESSAGE_STATUS_DELIVERED = "DELIVERED"
MESSAGE_STATUS_READ = "READ"
MESSAGE_STATUS_RECEIVED = "RECEIVED"
MESSAGE_STATUS_ERROR = "ERROR"
MESSAGE_STATUS_CANCELLED = "CANCELLED"


# Tipo semántico del contenido.
#
# No representa el transporte ni el proveedor.
# Se persiste actualmente dentro de metadata_json para
# mantener el núcleo de Comunicaciones portable.
MESSAGE_TYPE_TEXT = "TEXT"
MESSAGE_TYPE_DOCUMENT = "DOCUMENT"

THREAD_MATCH_MATCHED = "MATCHED"
THREAD_MATCH_UNMATCHED = "UNMATCHED"

ATTEMPT_STATUS_STARTED = "STARTED"
ATTEMPT_STATUS_SENT = "SENT"
ATTEMPT_STATUS_ERROR = "ERROR"


@dataclass(frozen=True)
class CommunicationAccount:
    id: int | None
    code: str
    channel: str
    display_name: str
    transport: str
    environment: str
    profile_key: str | None = None
    is_active: bool = True
    is_default: bool = False
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class CommunicationThread:
    id: int | None
    account_id: int
    client_id: int | None
    external_thread_key: str
    external_address: str | None = None
    external_display_name: str | None = None
    match_status: str = THREAD_MATCH_UNMATCHED
    is_archived: bool = False
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class CommunicationClientContext:
    client_id: int
    full_name: str
    document: str | None
    phone: str | None
    email: str | None
    nationality: str | None
    status: str | None


@dataclass(frozen=True)
class CommunicationExpedientContext:
    expedient_id: int
    number: str | None
    family_name: str | None
    type_name: str | None
    subtype_name: str | None
    documentary_status: str | None
    administrative_status: str | None
    box_folder_path: str | None = None


@dataclass(frozen=True)
class CommunicationThreadContext:
    thread_id: int
    client: CommunicationClientContext | None
    expedients: tuple[CommunicationExpedientContext, ...]


@dataclass(frozen=True)
class CommunicationThreadOverview:
    thread_id: int
    account_id: int
    channel: str
    client_id: int | None
    client_name: str | None
    external_thread_key: str
    external_address: str | None
    external_display_name: str | None
    match_status: str
    is_archived: bool
    last_message_at: str | None = None
    last_message_preview: str | None = None
    message_count: int = 0


@dataclass(frozen=True)
class CommunicationMessage:
    id: int | None
    thread_id: int
    client_id: int | None
    expedient_id: int | None
    direction: str
    body_text: str
    status: str = MESSAGE_STATUS_PENDING
    provider_message_id: str | None = None
    provider_timestamp: str | None = None
    created_by: str | None = None
    sent_by: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class CommunicationMessageAttempt:
    id: int | None
    message_id: int
    transport: str
    attempt_number: int
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] | None = None
