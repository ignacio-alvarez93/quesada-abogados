"""
Orquestación de sincronización entre WhatsApp Web y Comunicaciones.

Responsabilidades V1:
- recorrer snapshots ya visibles de WhatsApp;
- abrir y clasificar conversaciones;
- resolver identidad estable de contactos individuales por teléfono;
- ejecutar matching contra clientes;
- opcionalmente crear/reutilizar communication_threads.

No contiene SQL.
No conoce Flet.
No persiste grupos sin identidad estable.
"""

from backend.automation.connectors.whatsapp_connector import (
    CHAT_KIND_GROUP,
    CHAT_KIND_INDIVIDUAL,
    CHAT_KIND_SELF,
    CHAT_KIND_UNKNOWN,
)
from backend.communications.phone_normalization import (
    normalize_phone,
)
from backend.services.communication_service import (
    CommunicationService,
)


SYNC_STATUS_READY = "READY"
SYNC_STATUS_SKIPPED = "SKIPPED"
SYNC_STATUS_ERROR = "ERROR"

SYNC_REASON_GROUP_IDENTITY_PENDING = (
    "GROUP_IDENTITY_PENDING"
)

SYNC_REASON_SELF_PENDING = (
    "SELF_PENDING"
)

SYNC_REASON_UNKNOWN_CHAT = (
    "UNKNOWN_CHAT"
)

SYNC_REASON_PHONE_MISSING = (
    "PHONE_MISSING"
)

SYNC_REASON_PHONE_INVALID = (
    "PHONE_INVALID"
)

SYNC_REASON_OPEN_FAILED = (
    "OPEN_FAILED"
)

SYNC_REASON_PROFILE_OPEN_FAILED = (
    "PROFILE_OPEN_FAILED"
)


class WhatsAppSyncService:
    def __init__(
        self,
        *,
        connector,
        communication_service=None,
    ):
        if connector is None:
            raise ValueError(
                "connector es obligatorio"
            )

        self.connector = connector

        self.communication_service = (
            communication_service
            or CommunicationService()
        )

    @staticmethod
    def build_phone_thread_key(
        phone,
    ):
        normalized = normalize_phone(
            phone
        )

        if not normalized.valid:
            return None

        return (
            f"phone:{normalized.digits}"
        )

    def inspect_snapshot(
        self,
        snapshot,
        *,
        persist=False,
    ):
        result = {
            "position":
                int(snapshot.position),
            "display_name":
                snapshot.display_name,
            "kind":
                CHAT_KIND_UNKNOWN,
            "status":
                SYNC_STATUS_ERROR,
            "reason":
                None,
            "phone":
                None,
            "normalized_phone":
                None,
            "external_thread_key":
                None,
            "matched":
                False,
            "ambiguous":
                False,
            "client_id":
                None,
            "thread_id":
                None,
            "persisted":
                False,
        }

        opened = (
            self.connector.open_chat(
                snapshot.position
            )
        )

        if not opened.get("opened"):
            result["reason"] = (
                SYNC_REASON_OPEN_FAILED
            )
            return result

        profile_open = (
            self.connector
            .open_contact_profile(
                expected_display_name=(
                    snapshot.display_name
                ),
            )
        )

        if not profile_open:
            result["reason"] = (
                SYNC_REASON_PROFILE_OPEN_FAILED
            )
            return result

        classification = (
            self.connector
            .classify_open_profile()
        )

        kind = classification.get(
            "kind",
            CHAT_KIND_UNKNOWN,
        )

        result["kind"] = kind

        if kind == CHAT_KIND_GROUP:
            result["status"] = (
                SYNC_STATUS_SKIPPED
            )
            result["reason"] = (
                SYNC_REASON_GROUP_IDENTITY_PENDING
            )
            return result

        if kind == CHAT_KIND_SELF:
            result["status"] = (
                SYNC_STATUS_SKIPPED
            )
            result["reason"] = (
                SYNC_REASON_SELF_PENDING
            )
            return result

        if kind != CHAT_KIND_INDIVIDUAL:
            result["status"] = (
                SYNC_STATUS_SKIPPED
            )
            result["reason"] = (
                SYNC_REASON_UNKNOWN_CHAT
            )
            return result

        phone = (
            self.connector
            .get_open_contact_phone()
        )

        result["phone"] = phone

        if not phone:
            result["status"] = (
                SYNC_STATUS_SKIPPED
            )
            result["reason"] = (
                SYNC_REASON_PHONE_MISSING
            )
            return result

        normalized = normalize_phone(
            phone
        )

        result["normalized_phone"] = (
            normalized.e164
        )

        if not normalized.valid:
            result["status"] = (
                SYNC_STATUS_SKIPPED
            )
            result["reason"] = (
                SYNC_REASON_PHONE_INVALID
            )
            return result

        external_thread_key = (
            self.build_phone_thread_key(
                phone
            )
        )

        result["external_thread_key"] = (
            external_thread_key
        )

        match = (
            self.communication_service
            .match_client_by_phone(
                phone
            )
        )

        result["matched"] = bool(
            match.get("matched")
        )

        result["ambiguous"] = bool(
            match.get(
                "ambiguous",
                False,
            )
        )

        client = match.get(
            "client"
        )

        if client:
            result["client_id"] = (
                client.get("id")
            )

        result["status"] = (
            SYNC_STATUS_READY
        )

        if not persist:
            return result

        persisted = (
            self.communication_service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    external_thread_key
                ),
                phone=phone,
                display_name=(
                    snapshot.display_name
                ),
                metadata={
                    "source":
                        "whatsapp_web_sync",
                    "chat_kind":
                        CHAT_KIND_INDIVIDUAL,
                },
            )
        )

        thread = persisted["thread"]
        final_match = persisted["match"]

        result["thread_id"] = (
            thread.id
        )

        result["persisted"] = True

        result["matched"] = bool(
            final_match.get("matched")
        )

        final_client = (
            final_match.get("client")
        )

        result["client_id"] = (
            final_client.get("id")
            if final_client
            else None
        )

        return result

    def inspect_visible_chats(
        self,
        *,
        limit=5,
        persist=False,
    ):
        snapshots = (
            self.connector
            .list_visible_chat_snapshots()
        )

        effective_limit = max(
            0,
            int(limit),
        )

        if effective_limit:
            snapshots = (
                snapshots[
                    :effective_limit
                ]
            )
        else:
            snapshots = []

        results = []

        for snapshot in snapshots:
            try:
                item = (
                    self.inspect_snapshot(
                        snapshot,
                        persist=persist,
                    )
                )
            except Exception as exc:
                item = {
                    "position":
                        int(
                            snapshot.position
                        ),
                    "display_name":
                        snapshot.display_name,
                    "kind":
                        CHAT_KIND_UNKNOWN,
                    "status":
                        SYNC_STATUS_ERROR,
                    "reason":
                        type(exc).__name__,
                    "error":
                        str(exc),
                    "persisted":
                        False,
                }

            results.append(
                item
            )

        summary = {
            "scanned":
                len(results),
            "ready":
                sum(
                    1
                    for item in results
                    if item.get("status")
                    == SYNC_STATUS_READY
                ),
            "skipped":
                sum(
                    1
                    for item in results
                    if item.get("status")
                    == SYNC_STATUS_SKIPPED
                ),
            "errors":
                sum(
                    1
                    for item in results
                    if item.get("status")
                    == SYNC_STATUS_ERROR
                ),
            "individual":
                sum(
                    1
                    for item in results
                    if item.get("kind")
                    == CHAT_KIND_INDIVIDUAL
                ),
            "groups":
                sum(
                    1
                    for item in results
                    if item.get("kind")
                    == CHAT_KIND_GROUP
                ),
            "matched":
                sum(
                    1
                    for item in results
                    if item.get("matched")
                ),
            "persisted":
                sum(
                    1
                    for item in results
                    if item.get("persisted")
                ),
        }

        return {
            "summary":
                summary,
            "items":
                results,
        }
