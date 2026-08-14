import time
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
    MESSAGE_DIRECTION_INBOUND,
    MESSAGE_DIRECTION_OUTBOUND,
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

SYNC_REASON_ACCOUNT_CHANGED = (
    "ACCOUNT_CHANGED"
)

SYNC_REASON_GROUP_LEFT = (
    "GROUP_LEFT"
)

SYNC_REASON_GROUP_READ_ONLY = (
    "GROUP_READ_ONLY"
)

SYNC_REASON_SYSTEM_CHAT = (
    "SYSTEM_CHAT"
)

SYNC_REASON_IDENTITY_UNVERIFIABLE = (
    "IDENTITY_UNVERIFIABLE"
)

SYNC_REASON_MESSAGE_ID_MISSING = (
    "MESSAGE_ID_MISSING"
)

SYNC_REASON_MESSAGE_DIRECTION_UNKNOWN = (
    "MESSAGE_DIRECTION_UNKNOWN"
)

SYNC_REASON_MESSAGE_IMPORT_ERROR = (
    "MESSAGE_IMPORT_ERROR"
)


# Fallos de inventario que pueden deberse a un estado
# transitorio del DOM, perfil o extracción de identidad.
#
# No incluimos grupos/self/system/account-changed porque
# representan estados terminales conocidos, no fallos
# transitorios de descubrimiento.
INVENTORY_RETRYABLE_REASONS = {
    SYNC_REASON_OPEN_FAILED,
    SYNC_REASON_PROFILE_OPEN_FAILED,
    SYNC_REASON_UNKNOWN_CHAT,
    SYNC_REASON_PHONE_MISSING,
    SYNC_REASON_PHONE_INVALID,
    SYNC_REASON_IDENTITY_UNVERIFIABLE,
}


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

    def sync_open_chat_messages(
        self,
        *,
        thread_id,
        limit=200,
        expected_active_identity=None,
        expected_last_provider_message_id=None,
        after_provider_message_id=None,
    ):
        """Sincroniza los mensajes ya cargados del chat abierto.

        No navega a otra conversación.
        No descubre identidad.
        No conoce SQLite.
        """
        normalized_thread_id = int(
            thread_id
        )


        snapshots = (
            self.connector
            .list_visible_message_snapshots(
                limit=max(
                    1,
                    int(limit),
                )
            )
        )


        expected_identity = str(
            expected_active_identity
            or ""
        ).strip()

        expected_last_id = str(
            expected_last_provider_message_id
            or ""
        ).strip()

        after_provider_id = str(
            after_provider_message_id
            or ""
        ).strip()

        guard = None

        if expected_identity:
            post_extract_fingerprint = (
                self.connector
                .get_active_chat_fingerprint()
            )

            observed_identity = str(
                getattr(
                    post_extract_fingerprint,
                    "active_identity",
                    "",
                )
                or ""
            ).strip()

            observed_last_id = str(
                getattr(
                    post_extract_fingerprint,
                    "last_provider_message_id",
                    "",
                )
                or ""
            ).strip()

            snapshot_provider_ids = {
                str(
                    getattr(
                        snapshot,
                        "provider_message_id",
                        "",
                    )
                    or ""
                ).strip()
                for snapshot in snapshots
                if str(
                    getattr(
                        snapshot,
                        "provider_message_id",
                        "",
                    )
                    or ""
                ).strip()
            }

            guard = {
                "expected_active_identity":
                    expected_identity,
                "observed_active_identity":
                    observed_identity
                    or None,
                "expected_last_provider_message_id":
                    expected_last_id
                    or None,
                "observed_last_provider_message_id":
                    observed_last_id
                    or None,
                "chat_open":
                    bool(
                        getattr(
                            post_extract_fingerprint,
                            "chat_open",
                            False,
                        )
                    ),
                "expected_message_present":
                    (
                        not expected_last_id
                        or expected_last_id
                        in snapshot_provider_ids
                    ),
            }

            guard_ok = (
                guard["chat_open"]
                and observed_identity
                == expected_identity
                and (
                    not expected_last_id
                    or observed_last_id
                    == expected_last_id
                )
                and guard[
                    "expected_message_present"
                ]
            )

            guard["passed"] = (
                guard_ok
            )

            if not guard_ok:
                return {
                    "summary": {
                        "thread_id":
                            normalized_thread_id,
                        "scanned":
                            len(
                                snapshots
                            ),
                        "created":
                            0,
                        "reused":
                            0,
                        "status_advanced":
                            0,
                        "skipped":
                            0,
                        "errors":
                            0,
                    },
                    "items": [],
                    "aborted": True,
                    "abort_reason":
                        "ACTIVE_CHAT_CHANGED",
                    "guard": guard,
                }

        snapshots_to_process = snapshots

        incremental = False
        anchor_found = False

        if after_provider_id:
            anchor_index = None

            for index, snapshot in enumerate(
                snapshots
            ):
                provider_id = str(
                    getattr(
                        snapshot,
                        "provider_message_id",
                        "",
                    )
                    or ""
                ).strip()

                if provider_id == after_provider_id:
                    anchor_index = index
                    break

            if anchor_index is not None:
                anchor_found = True
                incremental = True

                # El anchor también se reprocesa.
                #
                # No solo buscamos mensajes nuevos: el último
                # mensaje ya conocido puede haber avanzado de
                # SENT -> DELIVERED -> READ conservando exactamente
                # el mismo provider_message_id.
                #
                # La importación es idempotente, por lo que un
                # anchor sin cambios simplemente será reused.
                snapshots_to_process = (
                    snapshots[
                        anchor_index:
                    ]
                )

        items = []


        summary = {
            "thread_id":
                normalized_thread_id,
            "scanned":
                len(
                    snapshots_to_process
                ),
            "extracted":
                len(snapshots),
            "sync_mode":
                (
                    "INCREMENTAL"
                    if incremental
                    else (
                        "FULL_FALLBACK"
                        if after_provider_id
                        else "FULL"
                    )
                ),
            "anchor_provider_message_id":
                after_provider_id
                or None,
            "anchor_found":
                anchor_found,
            "created":
                0,
            "reused":
                0,
            "status_advanced":
                0,
            "skipped":
                0,
            "errors":
                0,
        }

        for snapshot in snapshots_to_process:
            provider_id = str(
                getattr(
                    snapshot,
                    "provider_message_id",
                    "",
                )
                or ""
            ).strip()

            direction = str(
                getattr(
                    snapshot,
                    "direction",
                    "",
                )
                or ""
            ).strip().upper()

            item = {
                "provider_message_id":
                    provider_id
                    or None,
                "direction":
                    direction
                    or None,
                "created":
                    False,
                "reused":
                    False,
                "status_advanced":
                    False,
                "skipped":
                    False,
                "error":
                    False,
                "reason":
                    None,
                "message_id":
                    None,
            }

            if not provider_id:
                item["skipped"] = True
                item["reason"] = (
                    SYNC_REASON_MESSAGE_ID_MISSING
                )
                summary["skipped"] += 1
                items.append(item)
                continue

            if direction not in (
                MESSAGE_DIRECTION_INBOUND,
                MESSAGE_DIRECTION_OUTBOUND,
            ):
                item["skipped"] = True
                item["reason"] = (
                    SYNC_REASON_MESSAGE_DIRECTION_UNKNOWN
                )
                summary["skipped"] += 1
                items.append(item)
                continue

            metadata = dict(
                getattr(
                    snapshot,
                    "metadata",
                    None,
                )
                or {}
            )

            metadata.setdefault(
                "source",
                "whatsapp_web_message_sync",
            )

            metadata[
                "message_type"
            ] = getattr(
                snapshot,
                "message_type",
                None,
            )

            sender = getattr(
                snapshot,
                "sender",
                None,
            )

            if sender:
                metadata["sender"] = sender

            try:
                imported = (
                    self.communication_service
                    .import_provider_message(
                        thread_id=(
                            normalized_thread_id
                        ),
                        direction=direction,
                        body_text=(
                            getattr(
                                snapshot,
                                "body_text",
                                "",
                            )
                            or ""
                        ),
                        provider_message_id=(
                            provider_id
                        ),
                        provider_timestamp=(
                            getattr(
                                snapshot,
                                "provider_timestamp",
                                None,
                            )
                        ),
                        status=(
                            getattr(
                                snapshot,
                                "provider_status",
                                None,
                            )
                        ),
                        metadata=metadata,
                    )
                )

                message = imported[
                    "message"
                ]

                created = bool(
                    imported.get(
                        "created",
                        False,
                    )
                )

                reused = bool(
                    imported.get(
                        "reused",
                        not created,
                    )
                )

                status_advanced = bool(
                    imported.get(
                        "status_advanced",
                        False,
                    )
                )

                item["message_id"] = (
                    message.id
                )

                item["created"] = created
                item["reused"] = reused

                item[
                    "status_advanced"
                ] = status_advanced

                if created:
                    summary["created"] += 1

                if reused:
                    summary["reused"] += 1

                if status_advanced:
                    summary[
                        "status_advanced"
                    ] += 1

            except Exception as exc:
                item["error"] = True
                item["reason"] = (
                    SYNC_REASON_MESSAGE_IMPORT_ERROR
                )

                item["error_type"] = (
                    type(exc).__name__
                )

                summary["errors"] += 1

            items.append(item)



        return {
            "summary":
                summary,
            "items":
                items,
            "aborted":
                False,
            "abort_reason":
                None,
            "guard":
                guard,
        }

    @staticmethod
    def _is_inventory_retryable_item(
        item,
    ):
        if not isinstance(
            item,
            dict,
        ):
            return True

        if (
            item.get(
                "status"
            )
            == SYNC_STATUS_ERROR
        ):
            return True

        return (
            item.get(
                "reason"
            )
            in INVENTORY_RETRYABLE_REASONS
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

    @staticmethod
    def classify_non_writable_chat(
        *,
        display_name,
        open_result,
    ):
        """Interpreta estados terminales tras una apertura no verificable."""
        main_text = str(
            open_result.get(
                "main_text"
            )
            or ""
        )

        lowered = (
            main_text
            .casefold()
        )

        composer_aria_label = str(
            open_result.get(
                "composer_aria_label"
            )
            or ""
        ).strip()

        lowered_composer_aria = (
            composer_aria_label
            .casefold()
        )

        name = str(
            display_name
            or ""
        ).strip()

        # WhatsApp puede abrir correctamente un grupo
        # pero no exponer active_display_name en el header.
        #
        # En ese caso open_chat() rechaza la navegación por
        # CHAT_IDENTITY_MISMATCH —correctamente, porque no
        # debemos relajar la verificación genérica—, pero el
        # propio composer identifica de forma inequívoca que
        # estamos ante un grupo.
        #
        # Ejemplo real:
        # "Escribir un mensaje para el grupo 🃏"
        if (
            "para el grupo "
            in lowered_composer_aria
        ):
            return {
                "recognized": True,
                "kind":
                    CHAT_KIND_GROUP,
                "reason":
                    SYNC_REASON_GROUP_IDENTITY_PENDING,
            }

        if (
            "conectado a una nueva cuenta de whatsapp"
            in lowered
            and
            "ya no está activa"
            in lowered
        ):
            return {
                "recognized": True,
                "kind":
                    CHAT_KIND_INDIVIDUAL,
                "reason":
                    SYNC_REASON_ACCOUNT_CHANGED,
            }

        if (
            "no puedes enviar mensajes a este grupo"
            in lowered
            and
            "ya no eres miembro"
            in lowered
        ):
            return {
                "recognized": True,
                "kind":
                    CHAT_KIND_GROUP,
                "reason":
                    SYNC_REASON_GROUP_LEFT,
            }

        if (
            "solo admins. de la comunidad pueden enviar mensajes"
            in lowered
            or
            "solo administradores"
            in lowered
            and
            "pueden enviar mensajes"
            in lowered
        ):
            return {
                "recognized": True,
                "kind":
                    CHAT_KIND_GROUP,
                "reason":
                    SYNC_REASON_GROUP_READ_ONLY,
            }

        # Meta AI se presenta en WhatsApp Web como un
        # contacto individual con composer y drawer de
        # "Info. del contacto", pero no expone teléfono.
        #
        # No es una identidad de cliente y no debe quedar
        # como PHONE_MISSING recuperable.
        if (
            name.casefold()
            == "meta ai"
        ):
            return {
                "recognized": True,
                "kind":
                    CHAT_KIND_UNKNOWN,
                "reason":
                    SYNC_REASON_SYSTEM_CHAT,
            }

        if (
            name.casefold()
            == "whatsapp"
            and
            "cuenta oficial de whatsapp"
            in lowered
            and
            "solo whatsapp puede enviar mensajes"
            in lowered
        ):
            return {
                "recognized": True,
                "kind":
                    CHAT_KIND_UNKNOWN,
                "reason":
                    SYNC_REASON_SYSTEM_CHAT,
            }

        group_markers = (
            "info. del grupo",
            " miembro ·",
            " miembros ·",
            "creado por ",
        )

        if any(
            marker in lowered
            for marker in group_markers
        ):
            return {
                "recognized": True,
                "kind":
                    CHAT_KIND_GROUP,
                "reason":
                    SYNC_REASON_GROUP_IDENTITY_PENDING,
            }

        return {
            "recognized": False,
            "kind":
                CHAT_KIND_UNKNOWN,
            "reason":
                SYNC_REASON_OPEN_FAILED,
        }

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
            "created":
                False,
            "reused":
                False,
        }

        display_name = str(
            snapshot.display_name
            or ""
        ).strip()

        # Meta AI es una conversación propia del proveedor,
        # no un contacto CRM. WhatsApp Web la expone como
        # contacto individual sin número de teléfono.
        if (
            display_name.casefold()
            == "meta ai"
        ):
            result["status"] = (
                SYNC_STATUS_SKIPPED
            )

            result["reason"] = (
                SYNC_REASON_SYSTEM_CHAT
            )

            return result

        virtual_offset = getattr(
            snapshot,
            "virtual_offset",
            None,
        )

        if virtual_offset is not None:
            opened = (
                self.connector
                .open_chat_by_virtual_offset(
                    virtual_offset,
                    expected_display_name=(
                        snapshot.display_name
                    ),
                )
            )
        else:
            opened = (
                self.connector.open_chat(
                    snapshot.position,
                    expected_display_name=(
                        snapshot.display_name
                    ),
                )
            )

        if not opened.get("opened"):
            special = (
                self.classify_non_writable_chat(
                    display_name=(
                        snapshot.display_name
                    ),
                    open_result=opened,
                )
            )

            if special.get(
                "recognized"
            ):
                result["kind"] = (
                    special.get(
                        "kind",
                        CHAT_KIND_UNKNOWN,
                    )
                )

                result["status"] = (
                    SYNC_STATUS_SKIPPED
                )

                result["reason"] = (
                    special.get(
                        "reason"
                    )
                )

                return result

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

        created = bool(
            persisted.get(
                "created",
                False,
            )
        )

        result["created"] = created
        result["reused"] = not created

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

    def inspect_all_chats(
        self,
        *,
        persist=False,
        retries=1,
        step_ratio=0.02,
        wait_seconds=0.35,
    ):
        """Recorre la lista virtual y recupera huecos de cobertura."""
        import time

        prepared = (
            self.connector
            .prepare_chat_interface()
        )

        if not prepared.get("ready"):
            raise RuntimeError(
                "Interfaz WhatsApp no preparada"
            )

        expected_rows = int(
            prepared
            .get(
                "chat_list",
                {},
            )
            .get(
                "total_rows",
                0,
            )
            or 0
        )

        step = float(
            step_ratio
        )

        if (
            step <= 0
            or step > 1
        ):
            raise ValueError(
                "step_ratio debe estar entre 0 y 1"
            )

        max_retries = max(
            0,
            int(retries),
        )

        wait = max(
            0.0,
            float(wait_seconds),
        )

        visited_offsets = set()

        # Último resultado conocido por posición virtual.
        # Permite reintentar una fila previamente visitada
        # sin duplicarla en el resultado final.
        result_by_offset = {}

        # Posiciones localizadas pero todavía no resueltas
        # de forma terminal.
        retry_pending_offsets = set()

        # Número de posiciones pendientes que sí quedaron
        # resueltas durante el recovery pass.
        retry_recovered_offsets = set()

        def build_ratios(
            pass_step,
        ):
            ratios = []
            current = 0.0

            while current < 1.0:
                ratios.append(
                    round(
                        current,
                        6,
                    )
                )

                current += pass_step

            if (
                not ratios
                or ratios[-1] != 1.0
            ):
                ratios.append(
                    1.0
                )

            return ratios

        def process_snapshot(
            snapshot,
            virtual_offset,
        ):
            item = None

            for attempt in range(
                max_retries + 1
            ):
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
                        "created":
                            False,
                        "reused":
                            False,
                    }

                item[
                    "virtual_offset"
                ] = virtual_offset

                item[
                    "attempts"
                ] = attempt + 1

                if not self._is_inventory_retryable_item(
                    item
                ):
                    break

                if (
                    attempt
                    < max_retries
                    and wait
                ):
                    time.sleep(
                        min(
                            1.0,
                            max(
                                0.1,
                                wait,
                            ),
                        )
                    )

            return item

        def run_pass(
            pass_step,
            *,
            retry_pending=False,
        ):
            discovered_before = len(
                visited_offsets
            )

            recovered_before = len(
                retry_recovered_offsets
            )

            for ratio in build_ratios(
                pass_step
            ):
                movement = (
                    self.connector
                    .scroll_chat_list_to_ratio(
                        ratio
                    )
                )

                if not movement.get(
                    "moved"
                ):
                    continue

                if wait:
                    time.sleep(
                        wait
                    )

                snapshots = (
                    self.connector
                    .list_visible_chat_snapshots(
                        viewport_only=True,
                    )
                )

                snapshots = sorted(
                    snapshots,
                    key=lambda item: (
                        item.virtual_offset
                        if item.virtual_offset
                        is not None
                        else float("inf")
                    ),
                )

                for snapshot in snapshots:
                    virtual_offset = getattr(
                        snapshot,
                        "virtual_offset",
                        None,
                    )

                    if virtual_offset is None:
                        continue

                    virtual_offset = int(
                        virtual_offset
                    )

                    already_visited = (
                        virtual_offset
                        in visited_offsets
                    )

                    if already_visited:
                        if not (
                            retry_pending
                            and virtual_offset
                            in retry_pending_offsets
                        ):
                            continue
                    else:
                        visited_offsets.add(
                            virtual_offset
                        )

                    was_pending = (
                        virtual_offset
                        in retry_pending_offsets
                    )

                    item = (
                        process_snapshot(
                            snapshot,
                            virtual_offset,
                        )
                    )

                    result_by_offset[
                        virtual_offset
                    ] = item

                    if self._is_inventory_retryable_item(
                        item
                    ):
                        retry_pending_offsets.add(
                            virtual_offset
                        )
                    else:
                        retry_pending_offsets.discard(
                            virtual_offset
                        )

                        if was_pending:
                            retry_recovered_offsets.add(
                                virtual_offset
                            )

            return {
                "discovered_rows": (
                    len(
                        visited_offsets
                    )
                    - discovered_before
                ),
                "recovered_rows": (
                    len(
                        retry_recovered_offsets
                    )
                    - recovered_before
                ),
            }

        initial_pass_result = (
            run_pass(
                step
            )
        )

        initial_pass_rows = (
            initial_pass_result[
                "discovered_rows"
            ]
        )

        recovery_pass_used = bool(
            (
                expected_rows > 0
                and len(
                    visited_offsets
                )
                < expected_rows
            )
            or retry_pending_offsets
        )

        recovery_pass_rows = 0
        recovery_retry_rows = 0

        if recovery_pass_used:
            recovery_step = max(
                0.005,
                min(
                    step / 2.0,
                    0.01,
                ),
            )

            recovery_result = (
                run_pass(
                    recovery_step,
                    retry_pending=True,
                )
            )

            recovery_pass_rows = (
                recovery_result[
                    "discovered_rows"
                ]
            )

            recovery_retry_rows = (
                recovery_result[
                    "recovered_rows"
                ]
            )

        results = [
            result_by_offset[
                offset
            ]
            for offset in sorted(
                result_by_offset
            )
        ]

        unique_phone_threads = {
            item.get(
                "external_thread_key"
            )
            for item in results
            if item.get(
                "external_thread_key"
            )
        }

        summary = {
            "expected_rows":
                expected_rows,
            "visited_rows":
                len(
                    visited_offsets
                ),
            "coverage_complete":
                (
                    expected_rows > 0
                    and len(
                        visited_offsets
                    )
                    == expected_rows
                ),
            "initial_pass_rows":
                initial_pass_rows,
            "recovery_pass_used":
                recovery_pass_used,
            "recovery_pass_rows":
                recovery_pass_rows,

            # Filas previamente visitadas que estaban
            # pendientes y pudieron recuperarse.
            "recovery_retry_rows":
                recovery_retry_rows,

            # Cobertura DOM e integridad de inventario son
            # conceptos distintos.
            "retry_pending_rows":
                len(
                    retry_pending_offsets
                ),
            "retry_pending_offsets":
                sorted(
                    retry_pending_offsets
                ),
            "retry_recovered_rows":
                len(
                    retry_recovered_offsets
                ),

            "integrity_complete":
                (
                    expected_rows > 0
                    and len(
                        visited_offsets
                    )
                    == expected_rows
                    and not retry_pending_offsets
                ),

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
            "self":
                sum(
                    1
                    for item in results
                    if item.get("kind")
                    == CHAT_KIND_SELF
                ),
            "unknown":
                sum(
                    1
                    for item in results
                    if item.get("kind")
                    == CHAT_KIND_UNKNOWN
                ),
            "matched":
                sum(
                    1
                    for item in results
                    if item.get("matched")
                ),
            "ambiguous":
                sum(
                    1
                    for item in results
                    if item.get("ambiguous")
                ),
            "persisted":
                sum(
                    1
                    for item in results
                    if item.get("persisted")
                ),
            "created":
                sum(
                    1
                    for item in results
                    if item.get("created")
                ),
            "reused":
                sum(
                    1
                    for item in results
                    if item.get("reused")
                ),
            "unique_phone_threads":
                len(
                    unique_phone_threads
                ),
        }

        return {
            "summary":
                summary,
            "items":
                results,
        }

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
                    "created":
                        False,
                    "reused":
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
            "created":
                sum(
                    1
                    for item in results
                    if item.get("created")
                ),
            "reused":
                sum(
                    1
                    for item in results
                    if item.get("reused")
                ),
        }

        return {
            "summary":
                summary,
            "items":
                results,
        }
