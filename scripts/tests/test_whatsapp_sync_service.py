import unittest
from types import SimpleNamespace

from backend.automation.connectors.whatsapp_connector import (
    CHAT_KIND_GROUP,
    CHAT_KIND_INDIVIDUAL,
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


if __name__ == "__main__":
    unittest.main()
