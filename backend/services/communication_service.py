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
    MESSAGE_STATUS_PENDING,
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

        return (
            self.repository
            .create_message(
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
