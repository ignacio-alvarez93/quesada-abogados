"""
Servicio de dominio transversal de Comunicaciones.

Responsabilidades:
- gestionar cuentas lógicas;
- normalizar teléfonos;
- relacionar conversaciones con clientes;
- crear conversaciones;
- registrar mensajes.

No contiene SQL.
No conoce Flet.
No conoce SeleniumBase.
"""

from backend.communications.models import (
    CHANNEL_WHATSAPP,
    CommunicationAccount,
    CommunicationMessage,
    CommunicationThread,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    MESSAGE_STATUS_DELIVERED,
    MESSAGE_STATUS_PENDING,
    MESSAGE_STATUS_READ,
    MESSAGE_STATUS_RECEIVED,
    MESSAGE_STATUS_SENT,
    THREAD_MATCH_MATCHED,
    THREAD_MATCH_UNMATCHED,
)
from backend.communications.phone_normalization import (
    normalize_phone,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)


WHATSAPP_DEV_ACCOUNT_CODE = (
    "WHATSAPP_DEV"
)


class CommunicationService:
    def __init__(
        self,
        repository=None,
    ):
        self.repository = (
            repository
            or SQLiteCommunicationRepository()
        )

    def ensure_schema(self):
        self.repository.ensure_schema()

    def ensure_whatsapp_dev_account(self):
        account = CommunicationAccount(
            id=None,
            code=WHATSAPP_DEV_ACCOUNT_CODE,
            channel=CHANNEL_WHATSAPP,
            display_name=(
                "WhatsApp personal · desarrollo"
            ),
            transport=(
                "SELENIUMBASE_WEB"
            ),
            environment=(
                "DEVELOPMENT"
            ),
            profile_key=(
                "whatsapp_dev"
            ),
            is_active=True,
            is_default=True,
            metadata={
                "purpose": (
                    "development_and_testing"
                ),
            },
        )

        return self.repository.save_account(
            account
        )

    def match_client_by_phone(
        self,
        phone,
    ):
        normalized = normalize_phone(
            phone
        )

        if not normalized.valid:
            return {
                "matched": False,
                "client": None,
                "phone": normalized,
            }

        matches = []

        for client in (
            self.repository
            .list_client_phone_candidates()
        ):
            candidate = normalize_phone(
                client.get("telefono")
            )

            if (
                candidate.valid
                and candidate.digits
                == normalized.digits
            ):
                matches.append(client)

        if len(matches) != 1:
            return {
                "matched": False,
                "ambiguous": (
                    len(matches) > 1
                ),
                "matches": matches,
                "client": None,
                "phone": normalized,
            }

        return {
            "matched": True,
            "ambiguous": False,
            "matches": matches,
            "client": matches[0],
            "phone": normalized,
        }

    def get_thread_context(
        self,
        thread_id,
    ):
        if thread_id in (
            None,
            "",
        ):
            return None

        return (
            self.repository
            .get_thread_context(
                int(thread_id)
            )
        )

    def list_thread_messages(
        self,
        thread_id,
        *,
        limit=500,
    ):
        if thread_id in (
            None,
            "",
        ):
            return []

        thread = (
            self.repository
            .get_thread(
                int(thread_id)
            )
        )

        if not thread:
            raise ValueError(
                "Conversación no encontrada"
            )

        return (
            self.repository
            .list_messages(
                thread.id,
                limit=max(
                    1,
                    int(limit),
                ),
            )
        )

    def list_thread_overviews(
        self,
        *,
        channel=None,
        client_id=None,
        linkage="ALL",
        search="",
        include_archived=False,
        limit=5000,
    ):
        normalized_channel = (
            str(
                channel
                or ""
            )
            .strip()
            .upper()
            or None
        )

        normalized_linkage = (
            str(
                linkage
                or "ALL"
            )
            .strip()
            .upper()
        )

        normalized_search = (
            str(
                search
                or ""
            )
            .strip()
            .casefold()
        )

        items = (
            self.repository
            .list_thread_overviews(
                client_id=client_id,
                channel=(
                    normalized_channel
                ),
                limit=limit,
            )
        )

        visible = []

        for item in items:
            if (
                not include_archived
                and item.is_archived
            ):
                continue

            if (
                normalized_linkage
                == "LINKED"
                and item.client_id
                is None
            ):
                continue

            if (
                normalized_linkage
                == "UNLINKED"
                and item.client_id
                is not None
            ):
                continue

            if normalized_search:
                haystack = " ".join(
                    [
                        str(
                            item.client_name
                            or ""
                        ),
                        str(
                            item.external_display_name
                            or ""
                        ),
                        str(
                            item.external_address
                            or ""
                        ),
                        str(
                            item.external_thread_key
                            or ""
                        ),
                    ]
                ).casefold()

                if (
                    normalized_search
                    not in haystack
                ):
                    continue

            visible.append(
                item
            )

        summary = {
            "total":
                len(items),
            "visible":
                len(visible),
            "linked":
                sum(
                    1
                    for item in items
                    if item.client_id
                    is not None
                ),
            "unlinked":
                sum(
                    1
                    for item in items
                    if item.client_id
                    is None
                ),
            "matched":
                sum(
                    1
                    for item in items
                    if item.match_status
                    == THREAD_MATCH_MATCHED
                ),
            "whatsapp":
                sum(
                    1
                    for item in items
                    if str(
                        item.channel
                        or ""
                    ).upper()
                    == CHANNEL_WHATSAPP
                ),
        }

        return {
            "summary":
                summary,
            "items":
                visible,
        }

    def backfill_whatsapp_thread_matches(
        self,
        *,
        limit=5000,
    ):
        account = (
            self.ensure_whatsapp_dev_account()
        )

        threads = (
            self.repository
            .list_threads(
                account_id=account.id,
                limit=limit,
            )
        )

        summary = {
            "scanned":
                len(threads),
            "already_linked":
                0,
            "updated":
                0,
            "matched":
                0,
            "ambiguous":
                0,
            "unmatched":
                0,
        }

        items = []

        for thread in threads:
            item = {
                "thread_id":
                    thread.id,
                "external_thread_key":
                    thread.external_thread_key,
                "phone":
                    thread.external_address,
                "client_id":
                    thread.client_id,
                "status":
                    None,
            }

            if (
                thread.client_id
                is not None
            ):
                summary[
                    "already_linked"
                ] += 1

                item[
                    "status"
                ] = "ALREADY_LINKED"

                items.append(
                    item
                )

                continue

            phone = (
                thread.external_address
                or ""
            )

            if not phone:
                summary[
                    "unmatched"
                ] += 1

                item[
                    "status"
                ] = "UNMATCHED"

                items.append(
                    item
                )

                continue

            match = (
                self.match_client_by_phone(
                    phone
                )
            )

            if match.get(
                "ambiguous"
            ):
                summary[
                    "ambiguous"
                ] += 1

                item[
                    "status"
                ] = "AMBIGUOUS"

                item[
                    "matches"
                ] = [
                    candidate.get(
                        "id"
                    )
                    for candidate
                    in match.get(
                        "matches",
                        [],
                    )
                ]

                items.append(
                    item
                )

                continue

            if not match.get(
                "matched"
            ):
                summary[
                    "unmatched"
                ] += 1

                item[
                    "status"
                ] = "UNMATCHED"

                items.append(
                    item
                )

                continue

            client = (
                match.get(
                    "client"
                )
            )

            if not client:
                summary[
                    "unmatched"
                ] += 1

                item[
                    "status"
                ] = "UNMATCHED"

                items.append(
                    item
                )

                continue

            updated = (
                self.repository
                .update_thread_match(
                    thread.id,
                    client_id=int(
                        client[
                            "id"
                        ]
                    ),
                    match_status=(
                        THREAD_MATCH_MATCHED
                    ),
                )
            )

            summary[
                "updated"
            ] += 1

            summary[
                "matched"
            ] += 1

            item[
                "status"
            ] = "MATCHED"

            item[
                "client_id"
            ] = updated.client_id

            items.append(
                item
            )

        return {
            "account":
                account,
            "summary":
                summary,
            "items":
                items,
        }

    def get_or_create_whatsapp_thread(
        self,
        *,
        external_thread_key,
        phone=None,
        display_name=None,
        metadata=None,
    ):
        account = (
            self.ensure_whatsapp_dev_account()
        )

        normalized = normalize_phone(
            phone
        )

        match = (
            self.match_client_by_phone(
                phone
            )
            if phone
            else {
                "matched": False,
                "client": None,
            }
        )

        client = match.get("client")

        thread, created = (
            self.repository
            .get_or_create_thread_with_status(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=(
                        int(client["id"])
                        if client
                        else None
                    ),
                    external_thread_key=str(
                        external_thread_key
                        or ""
                    ).strip(),
                    external_address=(
                        normalized.e164
                        if normalized.valid
                        else str(
                            phone
                            or ""
                        ).strip()
                    ),
                    external_display_name=(
                        str(
                            display_name
                            or ""
                        ).strip()
                        or None
                    ),
                    match_status=(
                        THREAD_MATCH_MATCHED
                        if client
                        else THREAD_MATCH_UNMATCHED
                    ),
                    metadata=metadata,
                )
            )
        )

        if (
            thread.client_id is None
            and client
        ):
            thread = (
                self.repository
                .update_thread_match(
                    thread.id,
                    client_id=int(
                        client["id"]
                    ),
                    match_status=(
                        THREAD_MATCH_MATCHED
                    ),
                )
            )

        return {
            "account": account,
            "thread": thread,
            "match": match,
            "created": bool(
                created
            ),
        }

    def import_provider_message(
        self,
        *,
        thread_id,
        direction,
        body_text,
        provider_message_id,
        provider_timestamp=None,
        status=None,
        metadata=None,
    ):
        thread = (
            self.repository
            .get_thread(
                thread_id
            )
        )

        if not thread:
            raise ValueError(
                "Conversación no encontrada"
            )

        normalized_direction = (
            str(
                direction
                or ""
            )
            .strip()
            .upper()
        )

        if normalized_direction not in (
            DIRECTION_INBOUND,
            DIRECTION_OUTBOUND,
        ):
            raise ValueError(
                "Dirección de mensaje no válida"
            )

        normalized_provider_id = (
            str(
                provider_message_id
                or ""
            )
            .strip()
        )

        if not normalized_provider_id:
            raise ValueError(
                "provider_message_id es obligatorio"
            )

        normalized_status = (
            str(
                status
                or ""
            )
            .strip()
            .upper()
        )

        if normalized_direction == DIRECTION_INBOUND:
            if (
                normalized_status
                != MESSAGE_STATUS_RECEIVED
            ):
                normalized_status = (
                    MESSAGE_STATUS_RECEIVED
                )

        else:
            allowed_outbound_statuses = {
                MESSAGE_STATUS_SENT,
                MESSAGE_STATUS_DELIVERED,
                MESSAGE_STATUS_READ,
            }

            if (
                normalized_status
                not in allowed_outbound_statuses
            ):
                normalized_status = (
                    MESSAGE_STATUS_SENT
                )

        previous = (
            self.repository
            .get_message_by_provider_identity(
                thread_id=thread.id,
                provider_message_id=(
                    normalized_provider_id
                ),
            )
        )

        message, created = (
            self.repository
            .get_or_create_message_with_status(
                CommunicationMessage(
                    id=None,
                    thread_id=thread.id,
                    client_id=thread.client_id,
                    expedient_id=None,
                    direction=(
                        normalized_direction
                    ),
                    body_text=str(
                        body_text
                        or ""
                    ),
                    status=(
                        normalized_status
                    ),
                    provider_message_id=(
                        normalized_provider_id
                    ),
                    provider_timestamp=(
                        str(
                            provider_timestamp
                            or ""
                        ).strip()
                        or None
                    ),
                    metadata=metadata,
                )
            )
        )

        status_advanced = bool(
            not created
            and previous is not None
            and str(
                previous.status
                or ""
            ).strip().upper()
            != str(
                message.status
                or ""
            ).strip().upper()
        )

        return {
            "message": message,
            "created": bool(
                created
            ),
            "reused": not bool(
                created
            ),
            "status_advanced":
                status_advanced,
        }

    def register_inbound_message(
        self,
        *,
        thread_id,
        body_text,
        provider_message_id=None,
        provider_timestamp=None,
        metadata=None,
    ):
        thread = (
            self.repository
            .get_thread(
                thread_id
            )
        )

        if not thread:
            raise ValueError(
                "Conversación no encontrada"
            )

        message, _created = (
            self.repository
            .get_or_create_message_with_status(
                CommunicationMessage(
                    id=None,
                    thread_id=thread.id,
                    client_id=thread.client_id,
                    expedient_id=None,
                    direction=(
                        DIRECTION_INBOUND
                    ),
                    body_text=str(
                        body_text
                        or ""
                    ),
                    status=(
                        MESSAGE_STATUS_PENDING
                    ),
                    provider_message_id=(
                        provider_message_id
                    ),
                    provider_timestamp=(
                        provider_timestamp
                    ),
                    metadata=metadata,
                )
            )
        )

        return message

    def register_inbound_message_with_status(
        self,
        *,
        thread_id,
        body_text,
        provider_message_id=None,
        provider_timestamp=None,
        metadata=None,
    ):
        thread = (
            self.repository
            .get_thread(
                thread_id
            )
        )

        if not thread:
            raise ValueError(
                "Conversación no encontrada"
            )

        return (
            self.repository
            .get_or_create_message_with_status(
                CommunicationMessage(
                    id=None,
                    thread_id=thread.id,
                    client_id=thread.client_id,
                    expedient_id=None,
                    direction=(
                        DIRECTION_INBOUND
                    ),
                    body_text=str(
                        body_text
                        or ""
                    ),
                    status=(
                        MESSAGE_STATUS_PENDING
                    ),
                    provider_message_id=(
                        provider_message_id
                    ),
                    provider_timestamp=(
                        provider_timestamp
                    ),
                    metadata=metadata,
                )
            )
        )

    def create_outbound_message(
        self,
        *,
        thread_id,
        body_text,
        expedient_id=None,
        created_by=None,
        metadata=None,
    ):
        text = str(
            body_text
            or ""
        ).strip()

        if not text:
            raise ValueError(
                "El mensaje no puede estar vacío"
            )

        thread = (
            self.repository
            .get_thread(
                thread_id
            )
        )

        if not thread:
            raise ValueError(
                "Conversación no encontrada"
            )

        return (
            self.repository
            .create_message(
                CommunicationMessage(
                    id=None,
                    thread_id=thread.id,
                    client_id=thread.client_id,
                    expedient_id=(
                        int(expedient_id)
                        if expedient_id
                        else None
                    ),
                    direction=(
                        DIRECTION_OUTBOUND
                    ),
                    body_text=text,
                    status=(
                        MESSAGE_STATUS_PENDING
                    ),
                    created_by=(
                        str(
                            created_by
                            or ""
                        ).strip()
                        or None
                    ),
                    metadata=metadata,
                )
            )
        )
