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

import unicodedata

from backend.communications.models import (
    ATTEMPT_STATUS_ERROR,
    ATTEMPT_STATUS_SENT,
    ATTEMPT_STATUS_STARTED,
    CHANNEL_WHATSAPP,
    CommunicationAccount,
    CommunicationMessage,
    CommunicationMessageAttempt,
    CommunicationThread,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    MESSAGE_STATUS_DELIVERED,
    MESSAGE_TYPE_DOCUMENT,
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


def _normalize_whatsapp_display_identity(
    value,
):
    """Normaliza una identidad visible sin conocer el transporte.

    Se usa únicamente para comparar títulos visibles ya obtenidos
    frente a los nombres persistidos en Comunicaciones.

    No resuelve por similitud aproximada: la coincidencia final
    sigue siendo exacta sobre el valor normalizado.
    """
    raw = str(
        value
        or ""
    ).strip()

    if not raw:
        return ""

    decomposed = unicodedata.normalize(
        "NFKD",
        raw.casefold(),
    )

    characters = []

    for char in decomposed:
        if unicodedata.combining(
            char
        ):
            continue

        if char.isalnum():
            characters.append(
                char
            )
        else:
            characters.append(
                " "
            )

    return " ".join(
        "".join(
            characters
        ).split()
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

    def get_thread(
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
            .get_thread(
                int(thread_id)
            )
        )

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

    def list_latest_thread_messages(
        self,
        thread_id,
        *,
        limit=50,
    ):
        """Devuelve la ventana más reciente del historial del thread."""
        if thread_id in (
            None,
            "",
        ):
            return []

        thread = (
            self.repository
            .get_thread(
                int(
                    thread_id
                )
            )
        )

        if not thread:
            raise ValueError(
                "Conversación no encontrada"
            )

        return (
            self.repository
            .list_latest_messages(
                thread.id,
                limit=max(
                    1,
                    int(
                        limit
                    ),
                ),
            )
        )

    def list_thread_messages_before(
        self,
        thread_id,
        *,
        before_message_id,
        limit=50,
    ):
        """Devuelve una página histórica anterior al mensaje cursor."""
        if thread_id in (
            None,
            "",
        ):
            return []

        if before_message_id in (
            None,
            "",
        ):
            return []

        thread = (
            self.repository
            .get_thread(
                int(
                    thread_id
                )
            )
        )

        if not thread:
            raise ValueError(
                "Conversación no encontrada"
            )

        return (
            self.repository
            .list_messages_before(
                thread.id,
                before_message_id=int(
                    before_message_id
                ),
                limit=max(
                    1,
                    int(
                        limit
                    ),
                ),
            )
        )

    def get_latest_thread_provider_message_id(
        self,
        thread_id,
    ):
        """Obtiene el último provider_message_id persistido del thread."""
        if thread_id in (
            None,
            "",
        ):
            return None

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

        message = (
            self.repository
            .get_latest_provider_message(
                thread.id
            )
        )

        if message is None:
            return None

        return (
            str(
                message.provider_message_id
                or ""
            ).strip()
            or None
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

    def resolve_whatsapp_thread_by_identity(
        self,
        identity,
        *,
        limit=5000,
    ):
        """Resuelve una cabecera WhatsApp contra threads CRM.

        Solo devuelve matched=True cuando existe exactamente una
        coincidencia inequívoca.

        Prioridad:
        1. teléfono normalizado;
        2. nombre visible normalizado.

        Nunca selecciona arbitrariamente entre duplicados.
        """
        raw_identity = str(
            identity
            or ""
        ).strip()

        empty_result = {
            "matched": False,
            "ambiguous": False,
            "match_basis": None,
            "thread": None,
            "matches": [],
            "identity": raw_identity,
        }

        if not raw_identity:
            return empty_result

        overview = (
            self.list_thread_overviews(
                channel=CHANNEL_WHATSAPP,
                include_archived=False,
                limit=limit,
            )
        )

        threads = list(
            overview.get(
                "items",
                [],
            )
        )

        # ----------------------------------------------------
        # 1. Teléfono: señal más fuerte
        # ----------------------------------------------------

        observed_phone = normalize_phone(
            raw_identity
        )

        if observed_phone.valid:
            phone_matches = []

            for thread in threads:
                candidate = normalize_phone(
                    thread.external_address
                )

                if (
                    candidate.valid
                    and candidate.digits
                    == observed_phone.digits
                ):
                    phone_matches.append(
                        thread
                    )

            if phone_matches:
                return {
                    "matched":
                        len(
                            phone_matches
                        )
                        == 1,
                    "ambiguous":
                        len(
                            phone_matches
                        )
                        > 1,
                    "match_basis":
                        "PHONE",
                    "thread":
                        (
                            phone_matches[0]
                            if len(
                                phone_matches
                            )
                            == 1
                            else None
                        ),
                    "matches":
                        phone_matches,
                    "identity":
                        raw_identity,
                }

        # ----------------------------------------------------
        # 2. Display name: exacto tras normalización
        # ----------------------------------------------------

        normalized_identity = (
            _normalize_whatsapp_display_identity(
                raw_identity
            )
        )

        if not normalized_identity:
            return empty_result

        name_matches = []

        for thread in threads:
            candidate_identity = (
                _normalize_whatsapp_display_identity(
                    thread.external_display_name
                )
            )

            if (
                candidate_identity
                and candidate_identity
                == normalized_identity
            ):
                name_matches.append(
                    thread
                )

        if not name_matches:
            return {
                **empty_result,
                "normalized_identity":
                    normalized_identity,
            }

        return {
            "matched":
                len(
                    name_matches
                )
                == 1,
            "ambiguous":
                len(
                    name_matches
                )
                > 1,
            "match_basis":
                "DISPLAY_NAME",
            "thread":
                (
                    name_matches[0]
                    if len(
                        name_matches
                    )
                    == 1
                    else None
                ),
            "matches":
                name_matches,
            "identity":
                raw_identity,
            "normalized_identity":
                normalized_identity,
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

    def discover_whatsapp_sidebar_thread(
        self,
        *,
        identity,
        display_name=None,
        preview=None,
        primary_detail=None,
        unread_count=0,
    ):
        """Descubre pasivamente un thread telefónico del sidebar.

        Contrato de seguridad:
        - no conoce SeleniumBase;
        - no abre chats;
        - no navega;
        - solo persiste cuando la identidad visible permite
          obtener un teléfono válido;
        - utiliza la misma clave canónica phone:<digits>
          que el inventario WhatsApp.
        """
        raw_identity = str(
            identity
            or ""
        ).strip()

        raw_display_name = str(
            display_name
            or ""
        ).strip()

        # En un contacto no guardado WhatsApp suele mostrar
        # el propio teléfono como nombre visible. Probamos
        # primero el display original porque conserva símbolos
        # como "+" que la identidad normalizada puede perder.
        phone_source = (
            raw_display_name
            or raw_identity
        )

        normalized = normalize_phone(
            phone_source
        )

        if (
            not normalized.valid
            and raw_identity
            and raw_identity != phone_source
        ):
            normalized = normalize_phone(
                raw_identity
            )

        if not normalized.valid:
            return {
                "discovered": False,
                "created": False,
                "reused": False,
                "reason":
                    "SIDEBAR_IDENTITY_NOT_PHONE",
                "thread": None,
                "match": None,
                "phone": None,
                "external_thread_key": None,
            }

        external_thread_key = (
            f"phone:{normalized.digits}"
        )

        persisted = (
            self.get_or_create_whatsapp_thread(
                external_thread_key=(
                    external_thread_key
                ),
                phone=normalized.e164,
                display_name=(
                    raw_display_name
                    or raw_identity
                    or normalized.e164
                ),
                metadata={
                    "source":
                        "whatsapp_sidebar_discovery",
                    "discovery":
                        "PASSIVE",
                    "preview":
                        str(
                            preview
                            or ""
                        ).strip(),
                    "primary_detail":
                        str(
                            primary_detail
                            or ""
                        ).strip(),
                    "unread_count":
                        max(
                            0,
                            int(
                                unread_count
                                or 0
                            ),
                        ),
                },
            )
        )

        created = bool(
            persisted.get(
                "created",
                False,
            )
        )

        return {
            "discovered": True,
            "created": created,
            "reused": not created,
            "reason": None,
            "thread":
                persisted.get(
                    "thread"
                ),
            "match":
                persisted.get(
                    "match"
                ),
            "phone":
                normalized.e164,
            "external_thread_key":
                external_thread_key,
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

    def get_message(
        self,
        message_id,
    ):
        return (
            self.repository
            .get_message(
                int(message_id)
            )
        )

    def update_message_status(
        self,
        message_id,
        status,
        *,
        sent_by=None,
    ):
        return (
            self.repository
            .update_message_status(
                int(message_id),
                status,
                sent_by=sent_by,
            )
        )

    def attach_message_provider_identity(
        self,
        message_id,
        *,
        provider_message_id,
        provider_timestamp=None,
    ):
        return (
            self.repository
            .attach_message_provider_identity(
                int(message_id),
                provider_message_id=(
                    provider_message_id
                ),
                provider_timestamp=(
                    provider_timestamp
                ),
            )
        )

    def start_message_attempt(
        self,
        *,
        message_id,
        transport,
        metadata=None,
    ):
        message = (
            self.repository
            .get_message(
                int(message_id)
            )
        )

        if not message:
            raise ValueError(
                "Mensaje de comunicación no encontrado"
            )

        attempts = (
            self.repository
            .list_attempts(
                message.id
            )
        )

        attempt_number = (
            max(
                (
                    int(
                        attempt.attempt_number
                    )
                    for attempt in attempts
                ),
                default=0,
            )
            + 1
        )

        return (
            self.repository
            .create_attempt(
                CommunicationMessageAttempt(
                    id=None,
                    message_id=(
                        message.id
                    ),
                    transport=(
                        str(
                            transport
                            or ""
                        ).strip()
                    ),
                    attempt_number=(
                        attempt_number
                    ),
                    status=(
                        ATTEMPT_STATUS_STARTED
                    ),
                    metadata=metadata,
                )
            )
        )

    def finish_message_attempt(
        self,
        attempt_id,
        *,
        status,
        error_code=None,
        error_message=None,
        metadata=None,
    ):
        normalized_status = (
            str(
                status
                or ""
            )
            .strip()
            .upper()
        )

        if normalized_status not in (
            ATTEMPT_STATUS_SENT,
            ATTEMPT_STATUS_ERROR,
        ):
            raise ValueError(
                "Estado final de intento no válido"
            )

        return (
            self.repository
            .finish_attempt(
                int(attempt_id),
                status=(
                    normalized_status
                ),
                error_code=(
                    error_code
                ),
                error_message=(
                    error_message
                ),
                metadata=metadata,
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

        normalized_metadata = dict(
            metadata
            or {}
        )

        message_type = str(
            normalized_metadata.get(
                "message_type"
            )
            or ""
        ).strip().upper()

        document_filename = str(
            normalized_metadata.get(
                "filename"
            )
            or ""
        ).strip()

        is_document = (
            message_type
            == MESSAGE_TYPE_DOCUMENT
        )

        if (
            not text
            and not is_document
        ):
            raise ValueError(
                "El mensaje no puede estar vacío"
            )

        if (
            is_document
            and not document_filename
        ):
            raise ValueError(
                "Un mensaje DOCUMENT requiere filename"
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
                    metadata=(
                        normalized_metadata
                        or None
                    ),
                )
            )
        )
