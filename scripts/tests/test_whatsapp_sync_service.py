import unittest
from types import SimpleNamespace

from backend.automation.connectors.whatsapp_connector import WhatsAppActiveChatFingerprint
from backend.automation.connectors.whatsapp_connector import (
    CHAT_KIND_GROUP,
    CHAT_KIND_INDIVIDUAL,
    MESSAGE_DIRECTION_INBOUND,
    MESSAGE_DIRECTION_OUTBOUND,
    MESSAGE_STATUS_DELIVERED,
    MESSAGE_STATUS_READ,
    MESSAGE_STATUS_RECEIVED,
    MESSAGE_TYPE_STICKER,
    MESSAGE_TYPE_TEXT,
    WhatsAppMessageSnapshot,
)
from backend.services.whatsapp_sync_service import (
    SYNC_REASON_ACCOUNT_CHANGED,
    SYNC_REASON_GROUP_IDENTITY_PENDING,
    SYNC_REASON_GROUP_LEFT,
    SYNC_REASON_GROUP_READ_ONLY,
    SYNC_REASON_SYSTEM_CHAT,
    SYNC_STATUS_READY,
    SYNC_STATUS_SKIPPED,
    WhatsAppSyncService,
)


class FakeConnector:
    def __init__(
        self,
        *,
        kind=CHAT_KIND_INDIVIDUAL,
        phone="+34 600 123 456",
        open_result=None,
    ):
        self.kind = kind
        self.phone = phone
        self.open_result = (
            open_result
            or {
                "opened": True,
            }
        )

        self.snapshots = [
            SimpleNamespace(
                position=0,
                display_name="CLIENTE",
                virtual_offset=None,
            ),
        ]

        self.viewport_snapshots = {
            0.0: [
                SimpleNamespace(
                    position=0,
                    display_name="CLIENTE A",
                    virtual_offset=0,
                ),
                SimpleNamespace(
                    position=1,
                    display_name="CLIENTE B",
                    virtual_offset=76,
                ),
            ],
            0.5: [
                SimpleNamespace(
                    position=0,
                    display_name="CLIENTE B",
                    virtual_offset=76,
                ),
                SimpleNamespace(
                    position=1,
                    display_name="CLIENTE C",
                    virtual_offset=152,
                ),
            ],
            1.0: [
                SimpleNamespace(
                    position=0,
                    display_name="CLIENTE C",
                    virtual_offset=152,
                ),
            ],
        }

        self.current_ratio = 0.0

    def prepare_chat_interface(
        self,
    ):
        return {
            "ready": True,
            "chat_list": {
                "total_rows": 3,
            },
        }

    def scroll_chat_list_to_ratio(
        self,
        ratio,
    ):
        self.current_ratio = float(
            ratio
        )

        return {
            "moved": True,
            "ratio":
                self.current_ratio,
        }

    def list_visible_chat_snapshots(
        self,
        *,
        viewport_only=False,
    ):
        if not viewport_only:
            return self.snapshots

        key = min(
            self.viewport_snapshots,
            key=lambda candidate: abs(
                candidate
                - self.current_ratio
            ),
        )

        return (
            self.viewport_snapshots[
                key
            ]
        )

    def open_chat_by_virtual_offset(
        self,
        virtual_offset,
        *,
        expected_display_name=None,
    ):
        result = dict(
            self.open_result
        )

        result[
            "virtual_offset"
        ] = int(
            virtual_offset
        )

        return result

    def open_chat(
        self,
        _position,
        *,
        expected_display_name=None,
    ):
        return dict(
            self.open_result
        )

    def open_contact_profile(
        self,
        *,
        expected_display_name=None,
    ):
        return True

    def classify_open_profile(
        self,
    ):
        return {
            "kind": self.kind,
        }

    def get_open_contact_phone(
        self,
    ):
        return self.phone


class FakeCommunicationService:
    def __init__(
        self,
        *,
        created=True,
    ):
        self.persist_calls = []
        self.created = bool(
            created
        )

    def match_client_by_phone(
        self,
        phone,
    ):
        if phone == "+34 600 123 456":
            return {
                "matched": True,
                "ambiguous": False,
                "client": {
                    "id": 10,
                },
            }

        return {
            "matched": False,
            "ambiguous": False,
            "client": None,
        }

    def get_or_create_whatsapp_thread(
        self,
        **kwargs,
    ):
        self.persist_calls.append(
            kwargs
        )

        return {
            "thread":
                SimpleNamespace(
                    id=50,
                ),
            "match": {
                "matched": True,
                "client": {
                    "id": 10,
                },
            },
            "created":
                self.created,
        }


class StatefulFakeCommunicationService(
    FakeCommunicationService
):
    def __init__(self):
        super().__init__(
            created=True,
        )

        self.thread_ids = {}
        self.next_thread_id = 50

    def get_or_create_whatsapp_thread(
        self,
        **kwargs,
    ):
        self.persist_calls.append(
            kwargs
        )

        external_thread_key = (
            kwargs[
                "external_thread_key"
            ]
        )

        created = (
            external_thread_key
            not in self.thread_ids
        )

        if created:
            self.thread_ids[
                external_thread_key
            ] = self.next_thread_id

            self.next_thread_id += 1

        thread_id = (
            self.thread_ids[
                external_thread_key
            ]
        )

        return {
            "thread":
                SimpleNamespace(
                    id=thread_id,
                ),
            "match": {
                "matched": True,
                "client": {
                    "id": 10,
                },
            },
            "created":
                created,
        }


class FakeMessageConnector:
    def __init__(
        self,
        snapshots,
        fingerprints=None,
    ):
        self.snapshots = list(
            snapshots
        )

        self.limits = []

        self.fingerprints = list(
            fingerprints
            or []
        )

    def get_active_chat_fingerprint(
        self,
    ):
        if not self.fingerprints:
            raise AssertionError(
                "No hay fingerprint preparado"
            )

        value = self.fingerprints.pop(
            0
        )

        if isinstance(
            value,
            BaseException,
        ):
            raise value

        return value

    def list_visible_message_snapshots(
        self,
        *,
        limit=200,
    ):
        self.limits.append(
            int(limit)
        )

        return self.snapshots[
            -int(limit):
        ]


class FakeMessageCommunicationService:
    def __init__(self):
        self.calls = []
        self._messages = {}
        self._next_id = 1

    def import_provider_message(
        self,
        **kwargs,
    ):
        self.calls.append(
            dict(kwargs)
        )

        provider_id = (
            kwargs[
                "provider_message_id"
            ]
        )

        candidate_status = (
            kwargs.get(
                "status"
            )
        )

        existing = (
            self._messages.get(
                provider_id
            )
        )

        created = (
            existing is None
        )

        status_advanced = False

        ranks = {
            "SENT": 1,
            "DELIVERED": 2,
            "READ": 3,
        }

        if created:
            existing = SimpleNamespace(
                id=self._next_id,
                status=candidate_status,
            )

            self._next_id += 1

            self._messages[
                provider_id
            ] = existing

        else:
            current_rank = ranks.get(
                existing.status,
                0,
            )

            candidate_rank = ranks.get(
                candidate_status,
                0,
            )

            if (
                candidate_rank
                > current_rank
            ):
                existing.status = (
                    candidate_status
                )

                status_advanced = True

        return {
            "message":
                existing,
            "created":
                created,
            "reused":
                not created,
            "status_advanced":
                status_advanced,
        }


class WhatsAppSyncServiceTest(
    unittest.TestCase
):
    def test_classifies_account_changed(
        self,
    ):
        result = (
            WhatsAppSyncService
            .classify_non_writable_chat(
                display_name=(
                    "Juan Espinosa"
                ),
                open_result={
                    "main_text": (
                        "Este número de teléfono "
                        "está conectado a una nueva "
                        "cuenta de WhatsApp. "
                        "No puedes enviar mensajes "
                        "a esta cuenta porque ya "
                        "no está activa."
                    ),
                },
            )
        )

        self.assertTrue(
            result["recognized"]
        )

        self.assertEqual(
            result["reason"],
            SYNC_REASON_ACCOUNT_CHANGED,
        )

    def test_classifies_group_left(
        self,
    ):
        result = (
            WhatsAppSyncService
            .classify_non_writable_chat(
                display_name=(
                    "Cumpleaños enrique"
                ),
                open_result={
                    "main_text": (
                        "No puedes enviar mensajes "
                        "a este grupo porque ya "
                        "no eres miembro."
                    ),
                },
            )
        )

        self.assertTrue(
            result["recognized"]
        )

        self.assertEqual(
            result["kind"],
            CHAT_KIND_GROUP,
        )

        self.assertEqual(
            result["reason"],
            SYNC_REASON_GROUP_LEFT,
        )

    def test_classifies_group_read_only(
        self,
    ):
        result = (
            WhatsAppSyncService
            .classify_non_writable_chat(
                display_name=(
                    "Chats De Viciar"
                ),
                open_result={
                    "main_text": (
                        "Solo admins. de la comunidad "
                        "pueden enviar mensajes"
                    ),
                },
            )
        )

        self.assertTrue(
            result["recognized"]
        )

        self.assertEqual(
            result["kind"],
            CHAT_KIND_GROUP,
        )

        self.assertEqual(
            result["reason"],
            SYNC_REASON_GROUP_READ_ONLY,
        )

    def test_classifies_system_chat(
        self,
    ):
        result = (
            WhatsAppSyncService
            .classify_non_writable_chat(
                display_name="WhatsApp",
                open_result={
                    "main_text": (
                        "Cuenta oficial de WhatsApp. "
                        "Solo WhatsApp puede enviar "
                        "mensajes."
                    ),
                },
            )
        )

        self.assertTrue(
            result["recognized"]
        )

        self.assertEqual(
            result["reason"],
            SYNC_REASON_SYSTEM_CHAT,
        )

    def test_known_non_writable_chat_is_skipped(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        connector = FakeConnector(
            open_result={
                "opened": False,
                "composer_found": False,
                "active_display_name":
                    "Juan Espinosa",
                "main_text": (
                    "Este número de teléfono "
                    "está conectado a una nueva "
                    "cuenta de WhatsApp. "
                    "No puedes enviar mensajes "
                    "a esta cuenta porque ya "
                    "no está activa."
                ),
            },
        )

        connector.snapshots = [
            SimpleNamespace(
                position=0,
                display_name=(
                    "Juan Espinosa"
                ),
                virtual_offset=None,
            ),
        ]

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = (
            service.inspect_visible_chats(
                limit=1,
                persist=True,
            )
        )

        item = result[
            "items"
        ][0]

        self.assertEqual(
            item["status"],
            SYNC_STATUS_SKIPPED,
        )

        self.assertEqual(
            item["reason"],
            SYNC_REASON_ACCOUNT_CHANGED,
        )

        self.assertEqual(
            item["kind"],
            CHAT_KIND_INDIVIDUAL,
        )

        self.assertFalse(
            item["persisted"]
        )

        self.assertEqual(
            communication.persist_calls,
            [],
        )

    def test_builds_stable_phone_key(
        self,
    ):
        service = WhatsAppSyncService(
            connector=FakeConnector(),
            communication_service=(
                FakeCommunicationService()
            ),
        )

        self.assertEqual(
            service.build_phone_thread_key(
                "600 123 456"
            ),
            "phone:34600123456",
        )

    def test_dry_run_does_not_persist(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=FakeConnector(),
            communication_service=communication,
        )

        result = (
            service.inspect_visible_chats(
                limit=1,
                persist=False,
            )
        )

        item = result["items"][0]

        self.assertEqual(
            item["status"],
            SYNC_STATUS_READY,
        )

        self.assertEqual(
            item["external_thread_key"],
            "phone:34600123456",
        )

        self.assertTrue(
            item["matched"]
        )

        self.assertEqual(
            item["client_id"],
            10,
        )

        self.assertFalse(
            item["persisted"]
        )

        self.assertFalse(
            item["created"]
        )

        self.assertFalse(
            item["reused"]
        )

        self.assertEqual(
            communication.persist_calls,
            [],
        )

    def test_group_is_skipped(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=FakeConnector(
                kind=CHAT_KIND_GROUP,
                phone=None,
            ),
            communication_service=communication,
        )

        result = (
            service.inspect_visible_chats(
                limit=1,
                persist=False,
            )
        )

        item = result["items"][0]

        self.assertEqual(
            item["status"],
            SYNC_STATUS_SKIPPED,
        )

        self.assertEqual(
            item["reason"],
            SYNC_REASON_GROUP_IDENTITY_PENDING,
        )

        self.assertEqual(
            communication.persist_calls,
            [],
        )

    def test_classify_group_from_composer_aria(
        self,
    ):
        result = (
            WhatsAppSyncService
            .classify_non_writable_chat(
                display_name="🃏",
                open_result={
                    "opened": False,
                    "composer_found": True,
                    "composer_aria_label":
                        "Escribir un mensaje para el grupo 🃏",
                    "active_display_name": "",
                    "main_text":
                        "Suizo salió del grupo.",
                    "reason":
                        "CHAT_IDENTITY_MISMATCH",
                },
            )
        )

        self.assertTrue(
            result["recognized"]
        )

        self.assertEqual(
            result["kind"],
            CHAT_KIND_GROUP,
        )

        self.assertEqual(
            result["reason"],
            SYNC_REASON_GROUP_IDENTITY_PENDING,
        )


    def test_group_composer_identity_mismatch_is_terminal_group(
        self,
    ):
        connector = FakeConnector(
            open_result={
                "opened": False,
                "composer_found": True,
                "composer_aria_label":
                    "Escribir un mensaje para el grupo 🃏",
                "active_display_name": "",
                "main_text":
                    "Suizo salió del grupo. Escribe un mensaje",
                "reason":
                    "CHAT_IDENTITY_MISMATCH",
            },
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                FakeCommunicationService()
            ),
        )

        snapshot = SimpleNamespace(
            position=36,
            display_name="🃏",
            virtual_offset=None,
        )

        result = service.inspect_snapshot(
            snapshot,
            persist=True,
        )

        self.assertEqual(
            result["status"],
            SYNC_STATUS_SKIPPED,
        )

        self.assertEqual(
            result["kind"],
            CHAT_KIND_GROUP,
        )

        self.assertEqual(
            result["reason"],
            SYNC_REASON_GROUP_IDENTITY_PENDING,
        )

        self.assertFalse(
            result["persisted"]
        )

        self.assertFalse(
            service._is_inventory_retryable_item(
                result
            )
        )


    def test_meta_ai_is_terminal_system_chat(
        self,
    ):
        connector = FakeConnector(
            kind=CHAT_KIND_INDIVIDUAL,
            phone=None,
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                FakeCommunicationService()
            ),
        )

        snapshot = SimpleNamespace(
            position=31,
            display_name="Meta AI",
            virtual_offset=2983,
        )

        result = service.inspect_snapshot(
            snapshot,
            persist=True,
        )

        self.assertEqual(
            result["status"],
            SYNC_STATUS_SKIPPED,
        )

        self.assertEqual(
            result["reason"],
            SYNC_REASON_SYSTEM_CHAT,
        )

        self.assertFalse(
            result["persisted"]
        )

        self.assertFalse(
            service._is_inventory_retryable_item(
                result
            )
        )


    def test_full_traversal_deduplicates_virtual_offsets(
        self,
    ):
        service = WhatsAppSyncService(
            connector=FakeConnector(),
            communication_service=(
                FakeCommunicationService()
            ),
        )

        result = (
            service.inspect_all_chats(
                persist=False,
                retries=0,
                step_ratio=0.5,
                wait_seconds=0,
            )
        )

        summary = result[
            "summary"
        ]

        self.assertEqual(
            summary["expected_rows"],
            3,
        )

        self.assertEqual(
            summary["visited_rows"],
            3,
        )

        self.assertTrue(
            summary[
                "coverage_complete"
            ]
        )

        self.assertTrue(
            summary[
                "integrity_complete"
            ]
        )

        self.assertEqual(
            summary[
                "retry_pending_rows"
            ],
            0,
        )

        self.assertEqual(
            summary[
                "initial_pass_rows"
            ],
            3,
        )

        self.assertFalse(
            summary[
                "recovery_pass_used"
            ]
        )

        self.assertEqual(
            summary[
                "recovery_pass_rows"
            ],
            0,
        )

        offsets = [
            item[
                "virtual_offset"
            ]
            for item in result[
                "items"
            ]
        ]

        self.assertEqual(
            offsets,
            [
                0,
                76,
                152,
            ],
        )

    def test_full_traversal_recovers_missing_virtual_offset(
        self,
    ):
        connector = FakeConnector()

        connector.viewport_snapshots = {
            0.0: [
                SimpleNamespace(
                    position=0,
                    display_name="CLIENTE A",
                    virtual_offset=0,
                ),
            ],
            0.25: [
                SimpleNamespace(
                    position=1,
                    display_name="CLIENTE RECUPERADO",
                    virtual_offset=114,
                ),
            ],
            0.5: [
                SimpleNamespace(
                    position=2,
                    display_name="CLIENTE B",
                    virtual_offset=76,
                ),
            ],
            1.0: [
                SimpleNamespace(
                    position=3,
                    display_name="CLIENTE C",
                    virtual_offset=152,
                ),
            ],
        }

        def prepare():
            return {
                "ready": True,
                "chat_list": {
                    "total_rows": 4,
                },
            }

        connector.prepare_chat_interface = (
            prepare
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                FakeCommunicationService()
            ),
        )

        result = (
            service.inspect_all_chats(
                persist=False,
                retries=0,
                step_ratio=0.5,
                wait_seconds=0,
            )
        )

        summary = result[
            "summary"
        ]

        self.assertEqual(
            summary[
                "expected_rows"
            ],
            4,
        )

        self.assertEqual(
            summary[
                "initial_pass_rows"
            ],
            3,
        )

        self.assertTrue(
            summary[
                "recovery_pass_used"
            ]
        )

        self.assertEqual(
            summary[
                "recovery_pass_rows"
            ],
            1,
        )

        self.assertEqual(
            summary[
                "visited_rows"
            ],
            4,
        )

        self.assertTrue(
            summary[
                "coverage_complete"
            ]
        )

        offsets = {
            item[
                "virtual_offset"
            ]
            for item in result[
                "items"
            ]
        }

        self.assertEqual(
            offsets,
            {
                0,
                76,
                114,
                152,
            },
        )

    def test_full_traversal_retries_retryable_visited_offset(
        self,
    ):
        connector = FakeConnector()

        connector.viewport_snapshots = {
            0.0: [
                SimpleNamespace(
                    position=0,
                    display_name="CLIENTE A",
                    virtual_offset=0,
                ),
            ],
            0.5: [
                SimpleNamespace(
                    position=1,
                    display_name="CLIENTE B",
                    virtual_offset=76,
                ),
            ],
            1.0: [
                SimpleNamespace(
                    position=2,
                    display_name="CLIENTE C",
                    virtual_offset=152,
                ),
            ],
        }

        connector.prepare_chat_interface = lambda: {
            "ready": True,
            "chat_list": {
                "total_rows": 3,
            },
        }

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                FakeCommunicationService()
            ),
        )

        original_inspect = (
            service.inspect_snapshot
        )

        calls = {
            76: 0,
        }

        def inspect_snapshot(
            snapshot,
            *,
            persist=False,
        ):
            if snapshot.virtual_offset == 76:
                calls[76] += 1

                if calls[76] == 1:
                    return {
                        "position":
                            snapshot.position,
                        "display_name":
                            snapshot.display_name,
                        "kind":
                            CHAT_KIND_INDIVIDUAL,
                        "status":
                            SYNC_STATUS_SKIPPED,
                        "reason":
                            SYNC_REASON_PHONE_MISSING,
                        "persisted":
                            False,
                        "created":
                            False,
                        "reused":
                            False,
                    }

            return original_inspect(
                snapshot,
                persist=persist,
            )

        service.inspect_snapshot = (
            inspect_snapshot
        )

        result = service.inspect_all_chats(
            persist=False,
            retries=0,
            step_ratio=0.5,
            wait_seconds=0,
        )

        summary = result["summary"]

        self.assertTrue(
            summary["coverage_complete"]
        )

        self.assertTrue(
            summary["recovery_pass_used"]
        )

        self.assertEqual(
            calls[76],
            2,
        )

        self.assertEqual(
            summary["retry_pending_rows"],
            0,
        )

        self.assertEqual(
            summary["retry_recovered_rows"],
            1,
        )

        self.assertEqual(
            summary["recovery_retry_rows"],
            1,
        )

        self.assertTrue(
            summary["integrity_complete"]
        )


    def test_full_traversal_reports_pending_integrity_failure(
        self,
    ):
        connector = FakeConnector()

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                FakeCommunicationService()
            ),
        )

        original_inspect = (
            service.inspect_snapshot
        )

        def inspect_snapshot(
            snapshot,
            *,
            persist=False,
        ):
            if snapshot.virtual_offset == 76:
                return {
                    "position":
                        snapshot.position,
                    "display_name":
                        snapshot.display_name,
                    "kind":
                        CHAT_KIND_INDIVIDUAL,
                    "status":
                        SYNC_STATUS_SKIPPED,
                    "reason":
                        SYNC_REASON_PHONE_MISSING,
                    "persisted":
                        False,
                    "created":
                        False,
                    "reused":
                        False,
                }

            return original_inspect(
                snapshot,
                persist=persist,
            )

        service.inspect_snapshot = (
            inspect_snapshot
        )

        result = service.inspect_all_chats(
            persist=False,
            retries=0,
            step_ratio=0.5,
            wait_seconds=0,
        )

        summary = result["summary"]

        self.assertTrue(
            summary["coverage_complete"]
        )

        self.assertEqual(
            summary["retry_pending_rows"],
            1,
        )

        self.assertEqual(
            summary["retry_pending_offsets"],
            [76],
        )

        self.assertFalse(
            summary["integrity_complete"]
        )


    def test_full_traversal_persistence_is_idempotent(
        self,
    ):
        communication = (
            StatefulFakeCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=FakeConnector(),
            communication_service=communication,
        )

        first = (
            service.inspect_all_chats(
                persist=True,
                retries=0,
                step_ratio=0.5,
                wait_seconds=0,
            )
        )

        first_summary = (
            first["summary"]
        )

        self.assertTrue(
            first_summary[
                "coverage_complete"
            ]
        )

        self.assertEqual(
            first_summary[
                "visited_rows"
            ],
            3,
        )

        self.assertEqual(
            first_summary[
                "persisted"
            ],
            3,
        )

        self.assertEqual(
            first_summary[
                "created"
            ],
            1,
        )

        self.assertEqual(
            first_summary[
                "reused"
            ],
            2,
        )

        self.assertEqual(
            first_summary[
                "unique_phone_threads"
            ],
            1,
        )

        self.assertEqual(
            first_summary[
                "persisted"
            ],
            (
                first_summary[
                    "created"
                ]
                + first_summary[
                    "reused"
                ]
            ),
        )

        self.assertEqual(
            len(
                communication.thread_ids
            ),
            1,
        )

        first_thread_ids = {
            item[
                "thread_id"
            ]
            for item in first[
                "items"
            ]
            if item.get(
                "persisted"
            )
        }

        self.assertEqual(
            len(
                first_thread_ids
            ),
            1,
        )

        second = (
            service.inspect_all_chats(
                persist=True,
                retries=0,
                step_ratio=0.5,
                wait_seconds=0,
            )
        )

        second_summary = (
            second["summary"]
        )

        self.assertTrue(
            second_summary[
                "coverage_complete"
            ]
        )

        self.assertEqual(
            second_summary[
                "persisted"
            ],
            3,
        )

        self.assertEqual(
            second_summary[
                "created"
            ],
            0,
        )

        self.assertEqual(
            second_summary[
                "reused"
            ],
            3,
        )

        self.assertEqual(
            second_summary[
                "persisted"
            ],
            (
                second_summary[
                    "created"
                ]
                + second_summary[
                    "reused"
                ]
            ),
        )

        self.assertEqual(
            len(
                communication.thread_ids
            ),
            1,
        )


    def test_persist_creates_thread(
        self,
    ):
        communication = (
            FakeCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=FakeConnector(),
            communication_service=communication,
        )

        result = (
            service.inspect_visible_chats(
                limit=1,
                persist=True,
            )
        )

        item = result["items"][0]

        self.assertTrue(
            item["persisted"]
        )

        self.assertTrue(
            item["created"]
        )

        self.assertFalse(
            item["reused"]
        )

        self.assertEqual(
            result["summary"]["persisted"],
            1,
        )

        self.assertEqual(
            result["summary"]["created"],
            1,
        )

        self.assertEqual(
            result["summary"]["reused"],
            0,
        )

        self.assertEqual(
            item["thread_id"],
            50,
        )

        self.assertEqual(
            len(
                communication.persist_calls
            ),
            1,
        )

        call = (
            communication
            .persist_calls[0]
        )

        self.assertEqual(
            call[
                "external_thread_key"
            ],
            "phone:34600123456",
        )


    def test_persist_reuses_existing_thread(
        self,
    ):
        communication = (
            FakeCommunicationService(
                created=False,
            )
        )

        service = WhatsAppSyncService(
            connector=FakeConnector(),
            communication_service=communication,
        )

        result = (
            service.inspect_visible_chats(
                limit=1,
                persist=True,
            )
        )

        item = result["items"][0]

        self.assertTrue(
            item["persisted"]
        )

        self.assertFalse(
            item["created"]
        )

        self.assertTrue(
            item["reused"]
        )

        self.assertEqual(
            result["summary"]["persisted"],
            1,
        )

        self.assertEqual(
            result["summary"]["created"],
            0,
        )

        self.assertEqual(
            result["summary"]["reused"],
            1,
        )

    def test_sync_open_chat_messages_imports_normalized_snapshots(
        self,
    ):
        snapshots = [
            WhatsAppMessageSnapshot(
                provider_message_id=(
                    "wa-message-in-1"
                ),
                direction=(
                    MESSAGE_DIRECTION_INBOUND
                ),
                body_text="Entrada",
                provider_timestamp=(
                    "2026-08-12T09:20:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_RECEIVED
                ),
                sender="CLIENTE",
                metadata={
                    "transport":
                        "WHATSAPP_WEB",
                },
            ),
            WhatsAppMessageSnapshot(
                provider_message_id=(
                    "wa-message-out-1"
                ),
                direction=(
                    MESSAGE_DIRECTION_OUTBOUND
                ),
                body_text="Salida",
                provider_timestamp=(
                    "2026-08-12T09:21:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_DELIVERED
                ),
                metadata={
                    "transport":
                        "WHATSAPP_WEB",
                },
            ),
        ]

        connector = (
            FakeMessageConnector(
                snapshots
            )
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
                limit=200,
            )
        )

        summary = result[
            "summary"
        ]

        self.assertEqual(
            summary["scanned"],
            2,
        )

        self.assertEqual(
            summary["created"],
            2,
        )

        self.assertEqual(
            summary["reused"],
            0,
        )

        self.assertEqual(
            summary["errors"],
            0,
        )

        self.assertEqual(
            len(
                communication.calls
            ),
            2,
        )

        first_call = (
            communication.calls[0]
        )

        self.assertEqual(
            first_call["thread_id"],
            50,
        )

        self.assertEqual(
            first_call[
                "provider_message_id"
            ],
            "wa-message-in-1",
        )

        self.assertEqual(
            first_call[
                "metadata"
            ][
                "message_type"
            ],
            MESSAGE_TYPE_TEXT,
        )

        self.assertEqual(
            first_call[
                "metadata"
            ][
                "sender"
            ],
            "CLIENTE",
        )


    def test_sync_open_chat_messages_is_idempotent_and_tracks_status_progress(
        self,
    ):
        delivered = (
            WhatsAppMessageSnapshot(
                provider_message_id=(
                    "wa-progress-1"
                ),
                direction=(
                    MESSAGE_DIRECTION_OUTBOUND
                ),
                body_text="Mensaje",
                provider_timestamp=(
                    "2026-08-12T09:30:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_DELIVERED
                ),
            )
        )

        connector = FakeMessageConnector(
            [delivered]
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        first = (
            service.sync_open_chat_messages(
                thread_id=50,
            )
        )

        second = (
            service.sync_open_chat_messages(
                thread_id=50,
            )
        )

        self.assertEqual(
            first["summary"]["created"],
            1,
        )

        self.assertEqual(
            second["summary"]["created"],
            0,
        )

        self.assertEqual(
            second["summary"]["reused"],
            1,
        )

        read = (
            WhatsAppMessageSnapshot(
                provider_message_id=(
                    "wa-progress-1"
                ),
                direction=(
                    MESSAGE_DIRECTION_OUTBOUND
                ),
                body_text="Mensaje",
                provider_timestamp=(
                    "2026-08-12T09:30:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_READ
                ),
            )
        )

        connector.snapshots = [
            read
        ]

        third = (
            service.sync_open_chat_messages(
                thread_id=50,
            )
        )

        self.assertEqual(
            third[
                "summary"
            ][
                "created"
            ],
            0,
        )

        self.assertEqual(
            third[
                "summary"
            ][
                "reused"
            ],
            1,
        )

        self.assertEqual(
            third[
                "summary"
            ][
                "status_advanced"
            ],
            1,
        )


    def test_incremental_anchor_can_advance_provider_status(
        self,
    ):
        delivered = WhatsAppMessageSnapshot(
            provider_message_id="MSG-STATUS-ANCHOR",
            direction=MESSAGE_DIRECTION_OUTBOUND,
            body_text="Mensaje",
            provider_timestamp=(
                "2026-08-14T08:30:00"
            ),
            message_type=MESSAGE_TYPE_TEXT,
            provider_status=MESSAGE_STATUS_DELIVERED,
        )

        connector = FakeMessageConnector(
            [
                delivered,
            ]
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=communication,
        )

        first = service.sync_open_chat_messages(
            thread_id=50,
        )

        self.assertEqual(
            first["summary"]["created"],
            1,
        )

        read = WhatsAppMessageSnapshot(
            provider_message_id="MSG-STATUS-ANCHOR",
            direction=MESSAGE_DIRECTION_OUTBOUND,
            body_text="Mensaje",
            provider_timestamp=(
                "2026-08-14T08:30:00"
            ),
            message_type=MESSAGE_TYPE_TEXT,
            provider_status=MESSAGE_STATUS_READ,
        )

        connector.snapshots = [
            read,
        ]

        second = service.sync_open_chat_messages(
            thread_id=50,
            after_provider_message_id=(
                "MSG-STATUS-ANCHOR"
            ),
        )

        self.assertEqual(
            second["summary"]["sync_mode"],
            "INCREMENTAL",
        )

        self.assertTrue(
            second["summary"]["anchor_found"]
        )

        self.assertEqual(
            second["summary"]["scanned"],
            1,
        )

        self.assertEqual(
            second["summary"]["created"],
            0,
        )

        self.assertEqual(
            second["summary"]["reused"],
            1,
        )

        self.assertEqual(
            second["summary"]["status_advanced"],
            1,
        )

        self.assertEqual(
            second["items"][0][
                "provider_message_id"
            ],
            "MSG-STATUS-ANCHOR",
        )

        self.assertTrue(
            second["items"][0][
                "status_advanced"
            ]
        )


    def test_sync_open_chat_messages_incremental_processes_only_after_anchor(
        self,
    ):
        snapshots = [
            WhatsAppMessageSnapshot(
                provider_message_id="MSG-10",
                direction=(
                    MESSAGE_DIRECTION_INBOUND
                ),
                body_text="Anterior",
                provider_timestamp=(
                    "2026-08-13T09:00:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_RECEIVED
                ),
            ),
            WhatsAppMessageSnapshot(
                provider_message_id="MSG-11",
                direction=(
                    MESSAGE_DIRECTION_INBOUND
                ),
                body_text="Nuevo 1",
                provider_timestamp=(
                    "2026-08-13T09:01:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_RECEIVED
                ),
            ),
            WhatsAppMessageSnapshot(
                provider_message_id="MSG-12",
                direction=(
                    MESSAGE_DIRECTION_INBOUND
                ),
                body_text="Nuevo 2",
                provider_timestamp=(
                    "2026-08-13T09:02:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_RECEIVED
                ),
            ),
        ]

        connector = FakeMessageConnector(
            snapshots
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
                after_provider_message_id=(
                    "MSG-10"
                ),
            )
        )

        summary = result["summary"]

        self.assertEqual(
            summary["extracted"],
            3,
        )

        self.assertEqual(
            summary["scanned"],
            3,
        )

        self.assertEqual(
            summary["sync_mode"],
            "INCREMENTAL",
        )

        self.assertTrue(
            summary["anchor_found"]
        )

        self.assertEqual(
            [
                call[
                    "provider_message_id"
                ]
                for call in communication.calls
            ],
            [
                "MSG-10",
                "MSG-11",
                "MSG-12",
            ],
        )


    def test_sync_open_chat_messages_incremental_falls_back_when_anchor_missing(
        self,
    ):
        snapshots = [
            WhatsAppMessageSnapshot(
                provider_message_id="MSG-21",
                direction=(
                    MESSAGE_DIRECTION_INBOUND
                ),
                body_text="Uno",
                provider_timestamp=(
                    "2026-08-13T09:01:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_RECEIVED
                ),
            ),
            WhatsAppMessageSnapshot(
                provider_message_id="MSG-22",
                direction=(
                    MESSAGE_DIRECTION_INBOUND
                ),
                body_text="Dos",
                provider_timestamp=(
                    "2026-08-13T09:02:00"
                ),
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_RECEIVED
                ),
            ),
        ]

        connector = FakeMessageConnector(
            snapshots
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=(
                communication
            ),
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
                after_provider_message_id=(
                    "MSG-NO-VISIBLE"
                ),
            )
        )

        summary = result["summary"]

        self.assertEqual(
            summary["extracted"],
            2,
        )

        self.assertEqual(
            summary["scanned"],
            2,
        )

        self.assertEqual(
            summary["sync_mode"],
            "FULL_FALLBACK",
        )

        self.assertFalse(
            summary["anchor_found"]
        )

        self.assertEqual(
            len(
                communication.calls
            ),
            2,
        )


    def test_sync_open_chat_messages_skips_unknown_identity(
        self,
    ):
        snapshots = [
            WhatsAppMessageSnapshot(
                provider_message_id="",
                direction=(
                    MESSAGE_DIRECTION_INBOUND
                ),
                body_text="Sin id",
                provider_timestamp=None,
                message_type=(
                    MESSAGE_TYPE_TEXT
                ),
                provider_status=(
                    MESSAGE_STATUS_RECEIVED
                ),
            ),
            WhatsAppMessageSnapshot(
                provider_message_id=(
                    "wa-unknown-direction"
                ),
                direction="UNKNOWN",
                body_text="",
                provider_timestamp=None,
                message_type=(
                    MESSAGE_TYPE_STICKER
                ),
                provider_status="UNKNOWN",
            ),
        ]

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=(
                FakeMessageConnector(
                    snapshots
                )
            ),
            communication_service=(
                communication
            ),
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
            )
        )

        self.assertEqual(
            result["summary"]["scanned"],
            2,
        )

        self.assertEqual(
            result["summary"]["skipped"],
            2,
        )

        self.assertEqual(
            result["summary"]["created"],
            0,
        )

        self.assertEqual(
            communication.calls,
            [],
        )


    def test_sync_open_chat_messages_guard_allows_stable_chat(
        self,
    ):
        snapshot = WhatsAppMessageSnapshot(
            provider_message_id="MSG-11",
            direction=MESSAGE_DIRECTION_INBOUND,
            body_text="Mensaje nuevo",
            provider_timestamp=None,
            message_type=MESSAGE_TYPE_TEXT,
            provider_status=MESSAGE_STATUS_RECEIVED,
        )

        connector = FakeMessageConnector(
            [snapshot],
            fingerprints=[
                WhatsAppActiveChatFingerprint(
                    chat_open=True,
                    active_display_name="Mama",
                    active_identity="mama",
                    visible_message_count=11,
                    last_provider_message_id="MSG-11",
                ),
            ],
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=communication,
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
                expected_active_identity="mama",
                expected_last_provider_message_id="MSG-11",
            )
        )

        self.assertFalse(
            result["aborted"]
        )

        self.assertIsNone(
            result["abort_reason"]
        )

        self.assertTrue(
            result["guard"]["passed"]
        )

        self.assertEqual(
            result["summary"]["created"],
            1,
        )

        self.assertEqual(
            len(
                communication.calls
            ),
            1,
        )


    def test_sync_open_chat_messages_guard_aborts_if_identity_changes(
        self,
    ):
        snapshot = WhatsAppMessageSnapshot(
            provider_message_id="MSG-11",
            direction=MESSAGE_DIRECTION_INBOUND,
            body_text="Mensaje",
            provider_timestamp=None,
            message_type=MESSAGE_TYPE_TEXT,
            provider_status=MESSAGE_STATUS_RECEIVED,
        )

        connector = FakeMessageConnector(
            [snapshot],
            fingerprints=[
                WhatsAppActiveChatFingerprint(
                    chat_open=True,
                    active_display_name="Deneb",
                    active_identity="deneb",
                    visible_message_count=20,
                    last_provider_message_id="DENEB-20",
                ),
            ],
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=communication,
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
                expected_active_identity="mama",
                expected_last_provider_message_id="MSG-11",
            )
        )

        self.assertTrue(
            result["aborted"]
        )

        self.assertEqual(
            result["abort_reason"],
            "ACTIVE_CHAT_CHANGED",
        )

        self.assertFalse(
            result["guard"]["passed"]
        )

        self.assertEqual(
            result["summary"]["created"],
            0,
        )

        self.assertEqual(
            communication.calls,
            [],
        )


    def test_sync_open_chat_messages_guard_aborts_if_last_message_changes(
        self,
    ):
        snapshot = WhatsAppMessageSnapshot(
            provider_message_id="MSG-11",
            direction=MESSAGE_DIRECTION_INBOUND,
            body_text="Mensaje",
            provider_timestamp=None,
            message_type=MESSAGE_TYPE_TEXT,
            provider_status=MESSAGE_STATUS_RECEIVED,
        )

        connector = FakeMessageConnector(
            [snapshot],
            fingerprints=[
                WhatsAppActiveChatFingerprint(
                    chat_open=True,
                    active_display_name="Mama",
                    active_identity="mama",
                    visible_message_count=12,
                    last_provider_message_id="MSG-12",
                ),
            ],
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=communication,
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
                expected_active_identity="mama",
                expected_last_provider_message_id="MSG-11",
            )
        )

        self.assertTrue(
            result["aborted"]
        )

        self.assertEqual(
            result["abort_reason"],
            "ACTIVE_CHAT_CHANGED",
        )

        self.assertEqual(
            communication.calls,
            [],
        )


    def test_sync_open_chat_messages_guard_requires_expected_message_in_snapshots(
        self,
    ):
        snapshot = WhatsAppMessageSnapshot(
            provider_message_id="OTHER-1",
            direction=MESSAGE_DIRECTION_INBOUND,
            body_text="Otro mensaje",
            provider_timestamp=None,
            message_type=MESSAGE_TYPE_TEXT,
            provider_status=MESSAGE_STATUS_RECEIVED,
        )

        connector = FakeMessageConnector(
            [snapshot],
            fingerprints=[
                WhatsAppActiveChatFingerprint(
                    chat_open=True,
                    active_display_name="Mama",
                    active_identity="mama",
                    visible_message_count=11,
                    last_provider_message_id="MSG-11",
                ),
            ],
        )

        communication = (
            FakeMessageCommunicationService()
        )

        service = WhatsAppSyncService(
            connector=connector,
            communication_service=communication,
        )

        result = (
            service.sync_open_chat_messages(
                thread_id=50,
                expected_active_identity="mama",
                expected_last_provider_message_id="MSG-11",
            )
        )

        self.assertTrue(
            result["aborted"]
        )

        self.assertFalse(
            result[
                "guard"
            ][
                "expected_message_present"
            ]
        )

        self.assertEqual(
            communication.calls,
            [],
        )



if __name__ == "__main__":
    unittest.main()
