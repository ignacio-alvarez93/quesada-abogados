from pathlib import Path
import threading
import unittest

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_READY,
    WhatsAppActiveChatFingerprint,
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


class FakeConnector:
    instances = []

    def __init__(
        self,
        *,
        profile_key,
        headless,
    ):
        self.profile_key = profile_key
        self.headless = headless
        self.browser = None

        self.start_calls = 0
        self.close_calls = 0
        self.dismiss_calls = 0

        self.status = (
            SESSION_STATUS_READY
        )

        self.sent = []
        self.sync_snapshots = []

        self.active_chat_fingerprints = []

        self.open_phone_calls = []
        self.routing_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone": (
                "+34600111222"
            ),
            "observed_phone": (
                "+34600111222"
            ),
        }

        self.__class__.instances.append(
            self
        )

    def start(
        self,
    ):
        self.start_calls += 1
        self.browser = object()
        return self.browser

    def detect_session_status(
        self,
    ):
        return self.status

    def dismiss_known_overlays(
        self,
    ):
        self.dismiss_calls += 1

        return {
            "known_closed": 0,
            "unknown": [],
        }

    def close(
        self,
    ):
        self.close_calls += 1
        self.browser = None
        return True

    def open_chat_by_phone(
        self,
        phone,
        *,
        expected_display_name=None,
        verify_identity=True,
        timeout=15,
    ):
        self.open_phone_calls.append(
            (
                phone,
                expected_display_name,
                verify_identity,
                timeout,
            )
        )

        return dict(
            self.routing_result
        )

    def send_text_message(
        self,
        text,
        *,
        timeout=10,
    ):
        self.sent.append(
            (
                text,
                timeout,
            )
        )

        raise RuntimeError(
            "No debe probarse transporte real aquí"
        )

    def get_active_chat_fingerprint(
        self,
    ):
        if not self.active_chat_fingerprints:
            raise AssertionError(
                "No hay fingerprint preparado"
            )

        value = (
            self.active_chat_fingerprints
            .pop(0)
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
        return list(
            self.sync_snapshots[
                -int(limit):
            ]
        )


class FakeThread:
    def __init__(
        self,
        *,
        thread_id=7,
        external_address=(
            "+34 600 111 222"
        ),
        external_display_name=(
            "Test Contact"
        ),
    ):
        self.id = thread_id
        self.external_address = (
            external_address
        )
        self.external_display_name = (
            external_display_name
        )


class FakeCommunicationService:
    def __init__(
        self,
    ):
        self.thread = FakeThread()

    def get_thread(
        self,
        thread_id,
    ):
        if (
            self.thread
            and int(thread_id)
            == int(self.thread.id)
        ):
            return self.thread

        return None


class WhatsAppRuntimeServiceTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        FakeConnector.instances = []

    def _runtime(
        self,
    ):
        return WhatsAppRuntimeService(
            profile_key="test_profile",
            headless=True,
            communication_service=(
                FakeCommunicationService()
            ),
            connector_factory=(
                FakeConnector
            ),
        )

    def test_connector_is_lazy(
        self,
    ):
        runtime = self._runtime()

        self.assertIsNone(
            runtime.connector
        )

        self.assertFalse(
            runtime.started
        )

        self.assertEqual(
            len(
                FakeConnector.instances
            ),
            0,
        )

    def test_start_reuses_single_connector(
        self,
    ):
        runtime = self._runtime()

        first = runtime.start()
        second = runtime.start()

        self.assertIs(
            first,
            second,
        )

        self.assertEqual(
            len(
                FakeConnector.instances
            ),
            1,
        )

        self.assertEqual(
            first.start_calls,
            1,
        )

    def test_ensure_ready_reuses_runtime(
        self,
    ):
        runtime = self._runtime()

        first = runtime.ensure_ready(
            wait_timeout=1,
        )

        second = runtime.ensure_ready(
            wait_timeout=1,
        )

        self.assertIs(
            first,
            second,
        )

        self.assertEqual(
            first.start_calls,
            1,
        )

        self.assertEqual(
            first.dismiss_calls,
            2,
        )

    def test_status_before_start(
        self,
    ):
        runtime = self._runtime()

        self.assertEqual(
            runtime.get_status(),
            "NOT_STARTED",
        )

    def test_close_resets_runtime(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        self.assertTrue(
            runtime.close()
        )

        self.assertEqual(
            connector.close_calls,
            1,
        )

        self.assertIsNone(
            runtime.connector
        )

        self.assertFalse(
            runtime.started
        )

        replacement = runtime.start()

        self.assertIsNot(
            replacement,
            connector,
        )

        self.assertEqual(
            len(
                FakeConnector.instances
            ),
            2,
        )


    def test_verify_and_open_thread_routes_by_persisted_phone(
        self,
    ):
        runtime = self._runtime()

        result = (
            runtime
            .verify_and_open_thread(
                7,
                wait_timeout=1,
                routing_timeout=9,
            )
        )

        connector = runtime.connector

        self.assertEqual(
            connector.open_phone_calls,
            [
                (
                    "+34 600 111 222",
                    "Test Contact",
                    False,
                    9,
                )
            ],
        )

        self.assertTrue(
            result[
                "routing"
            ][
                "verified"
            ]
        )

        self.assertEqual(
            result[
                "thread"
            ].id,
            7,
        )

    def test_verify_and_open_thread_uses_lightweight_navigation(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        # La selección ordinaria de una conversación no abre
        # el perfil ni exige verificación fuerte por teléfono.
        # Esa verificación se reserva para operaciones sensibles
        # como el envío.
        connector.routing_result = {
            "opened": True,
            "verified": False,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone": None,
        }

        result = runtime.verify_and_open_thread(
            7,
            wait_timeout=1,
        )

        self.assertTrue(
            result[
                "routing"
            ][
                "opened"
            ]
        )

        self.assertEqual(
            connector.open_phone_calls,
            [
                (
                    "+34 600 111 222",
                    "Test Contact",
                    False,
                    15,
                )
            ],
        )

        self.assertEqual(
            result[
                "thread"
            ].id,
            7,
        )

    def test_observe_active_chat_detects_initial_and_unchanged_state(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        fingerprint = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name="Mama",
            active_identity="mama",
            visible_message_count=10,
            last_provider_message_id="MSG-10",
        )

        connector.active_chat_fingerprints = [
            fingerprint,
            fingerprint,
        ]

        first = runtime.observe_active_chat(
            wait_timeout=1,
        )

        second = runtime.observe_active_chat(
            wait_timeout=1,
        )

        self.assertTrue(
            first["changed"]
        )

        self.assertEqual(
            first["change_type"],
            "INITIAL",
        )

        self.assertFalse(
            second["changed"]
        )

        self.assertEqual(
            second["change_type"],
            "UNCHANGED",
        )


    def test_observe_active_chat_detects_new_message(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name="Mama",
                active_identity="mama",
                visible_message_count=10,
                last_provider_message_id="MSG-10",
            ),
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name="Mama",
                active_identity="mama",
                visible_message_count=11,
                last_provider_message_id="MSG-11",
            ),
        ]

        runtime.observe_active_chat(
            wait_timeout=1,
        )

        result = runtime.observe_active_chat(
            wait_timeout=1,
        )

        self.assertTrue(
            result["changed"]
        )

        self.assertEqual(
            result["change_type"],
            "MESSAGE_CHANGED",
        )

        self.assertEqual(
            result[
                "current"
            ].last_provider_message_id,
            "MSG-11",
        )


    def test_observe_active_chat_detects_manual_chat_change(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name="Mama",
                active_identity="mama",
                visible_message_count=10,
                last_provider_message_id="MAMA-10",
            ),
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name="Deneb",
                active_identity="deneb",
                visible_message_count=22,
                last_provider_message_id="DENEB-22",
            ),
        ]

        runtime.observe_active_chat(
            wait_timeout=1,
        )

        result = runtime.observe_active_chat(
            wait_timeout=1,
        )

        self.assertTrue(
            result["changed"]
        )

        self.assertEqual(
            result["change_type"],
            "CHAT_CHANGED",
        )

        self.assertEqual(
            result[
                "current"
            ].active_identity,
            "deneb",
        )


    def test_active_chat_watch_reuses_single_thread(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        fingerprint = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name="Mama",
            active_identity="mama",
            visible_message_count=10,
            last_provider_message_id="MSG-10",
        )

        connector.active_chat_fingerprints = [
            fingerprint,
            fingerprint,
            fingerprint,
        ]

        first = runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
        )

        second = runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
        )

        self.assertIs(
            first,
            second,
        )

        self.assertTrue(
            runtime.active_chat_watch_running
        )

        runtime.stop_active_chat_watch()

        self.assertFalse(
            runtime.active_chat_watch_running
        )


    def test_active_chat_watch_emits_only_changes(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        initial = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name="Mama",
            active_identity="mama",
            visible_message_count=10,
            last_provider_message_id="MSG-10",
        )

        changed = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name="Mama",
            active_identity="mama",
            visible_message_count=11,
            last_provider_message_id="MSG-11",
        )

        connector.active_chat_fingerprints = [
            initial,
            initial,
            changed,
        ]

        received = []
        event = threading.Event()

        def on_change(result):
            received.append(
                result["change_type"]
            )

            if (
                result["change_type"]
                == "MESSAGE_CHANGED"
            ):
                event.set()

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            event.wait(
                timeout=1
            )
        )

        runtime.stop_active_chat_watch()

        self.assertEqual(
            received,
            [
                "INITIAL",
                "MESSAGE_CHANGED",
            ],
        )


    def test_active_chat_watch_survives_temporary_observation_error(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        fingerprint = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name="Deneb",
            active_identity="deneb",
            visible_message_count=4,
            last_provider_message_id="DENEB-4",
        )

        connector.active_chat_fingerprints = [
            RuntimeError(
                "DOM temporalmente no disponible"
            ),
            fingerprint,
        ]

        received = []
        event = threading.Event()

        def on_change(result):
            received.append(
                result["change_type"]
            )
            event.set()

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            event.wait(
                timeout=1
            )
        )

        runtime.stop_active_chat_watch()

        self.assertEqual(
            received,
            [
                "INITIAL",
            ],
        )


    def test_close_stops_active_chat_watch(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        fingerprint = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name="Mama",
            active_identity="mama",
            visible_message_count=1,
            last_provider_message_id="MSG-1",
        )

        connector.active_chat_fingerprints = [
            fingerprint,
            fingerprint,
            fingerprint,
        ]

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
        )

        self.assertTrue(
            runtime.active_chat_watch_running
        )

        runtime.close()

        self.assertFalse(
            runtime.active_chat_watch_running
        )

        self.assertFalse(
            runtime.started
        )


    def test_send_text_message_requires_strong_identity_verification(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        connector.routing_result = {
            "opened": True,
            "verified": False,
            "reason":
                "PHONE_MISMATCH",
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600999888",
        }

        with self.assertRaises(
            RuntimeError
        ) as raised:
            runtime.send_text_message(
                thread_id=7,
                text="Mensaje que no debe enviarse",
                wait_timeout=1,
                routing_timeout=9,
            )

        self.assertIn(
            "PHONE_MISMATCH",
            str(
                raised.exception
            ),
        )

        # El envío sensible debe conservar la
        # verificación fuerte del destinatario.
        self.assertEqual(
            connector.open_phone_calls,
            [
                (
                    "+34 600 111 222",
                    "Test Contact",
                    True,
                    9,
                )
            ],
        )

        # La barrera de identidad debe fallar antes
        # incluso de construir el servicio outbound.
        self.assertIsNone(
            runtime._outbound_service
        )

        # Tampoco puede haberse alcanzado el transporte.
        self.assertEqual(
            connector.sent,
            [],
        )


    def test_verify_and_open_thread_rejects_missing_phone(
        self,
    ):
        runtime = self._runtime()

        runtime.communication_service.thread = (
            FakeThread(
                external_address=None,
            )
        )

        with self.assertRaises(
            ValueError
        ):
            runtime.verify_and_open_thread(
                7,
                wait_timeout=1,
            )

        self.assertEqual(
            runtime.connector.open_phone_calls,
            [],
        )


    def test_browser_operations_share_one_runtime_thread(
        self,
    ):
        runtime = self._runtime()

        thread_ids = []

        connector = runtime.start()

        original_status = (
            connector.detect_session_status
        )

        def tracked_status():
            thread_ids.append(
                threading.get_ident()
            )
            return original_status()

        connector.detect_session_status = (
            tracked_status
        )

        runtime.get_status()
        runtime.ensure_ready(
            wait_timeout=1,
        )

        self.assertGreaterEqual(
            len(thread_ids),
            2,
        )

        self.assertEqual(
            len(
                set(
                    thread_ids
                )
            ),
            1,
        )

        runtime.close()

    def test_runtime_worker_differs_from_caller_thread(
        self,
    ):
        runtime = self._runtime()

        caller_thread = (
            threading.get_ident()
        )

        runtime.start()

        self.assertIsNotNone(
            runtime._worker_thread_id
        )

        self.assertNotEqual(
            runtime._worker_thread_id,
            caller_thread,
        )

        runtime.close()


    def test_verify_thread_uses_latest_selection_contract(
        self,
    ):
        source = Path(
            "backend/services/"
            "whatsapp_runtime_service.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "self._desired_thread_id",
            source,
        )

        self.assertIn(
            '"STALE_SELECTION"',
            source,
        )

        self.assertIn(
            "def _verify_and_open_latest_thread_impl(",
            source,
        )

        self.assertIn(
            "desired_thread_id",
            source,
        )

        self.assertIn(
            "!= requested_thread_id",
            source,
        )


if __name__ == "__main__":
    unittest.main()
