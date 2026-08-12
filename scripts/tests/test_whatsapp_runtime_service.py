from pathlib import Path
from types import SimpleNamespace
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


    def test_observe_and_sync_initial_does_not_resolve_or_sync(
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
        ]

        def forbidden_resolve(
            identity,
        ):
            raise AssertionError(
                "INITIAL no debe resolver"
            )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            forbidden_resolve
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result["change_type"],
            "INITIAL",
        )

        self.assertIsNone(
            result["resolution"]
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_unchanged_does_not_sync(
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

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        def forbidden_resolve(
            identity,
        ):
            raise AssertionError(
                "UNCHANGED no debe resolver"
            )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            forbidden_resolve
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result["change_type"],
            "UNCHANGED",
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_message_changed_syncs_unique_match_once(
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

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        resolve_calls = []

        def resolve(
            identity,
        ):
            resolve_calls.append(
                identity
            )

            return {
                "matched": True,
                "ambiguous": False,
                "match_basis":
                    "DISPLAY_NAME",
                "thread":
                    SimpleNamespace(
                        thread_id=77
                    ),
                "matches": [],
                "identity":
                    identity,
            }

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            resolve
        )

        sync_calls = []

        def sync(
            **kwargs,
        ):
            sync_calls.append(
                dict(
                    kwargs
                )
            )

            return {
                "summary": {
                    "thread_id": 77,
                    "created": 1,
                },
                "items": [],
                "aborted": False,
                "abort_reason": None,
                "guard": {
                    "passed": True,
                },
            }

        runtime._sync_service = (
            SimpleNamespace(
                sync_open_chat_messages=sync
            )
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
                sync_limit=125,
            )
        )

        self.assertEqual(
            resolve_calls,
            [
                "mama",
            ],
        )

        self.assertEqual(
            len(
                sync_calls
            ),
            1,
        )

        self.assertEqual(
            sync_calls[
                0
            ][
                "thread_id"
            ],
            77,
        )

        self.assertEqual(
            sync_calls[
                0
            ][
                "limit"
            ],
            125,
        )

        self.assertEqual(
            sync_calls[
                0
            ][
                "expected_active_identity"
            ],
            "mama",
        )

        self.assertEqual(
            sync_calls[
                0
            ][
                "expected_last_provider_message_id"
            ],
            "MSG-11",
        )

        self.assertFalse(
            result[
                "sync"
            ][
                "aborted"
            ]
        )


    def test_observe_and_sync_ambiguous_match_does_not_sync(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                11,
                "MSG-11",
            ),
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity: {
                "matched": False,
                "ambiguous": True,
                "match_basis":
                    "DISPLAY_NAME",
                "thread": None,
                "matches": [
                    object(),
                    object(),
                ],
                "identity":
                    identity,
            }
        )

        runtime._sync_service = (
            SimpleNamespace(
                sync_open_chat_messages=(
                    lambda **kwargs:
                        (_ for _ in ())
                        .throw(
                            AssertionError(
                                "AMBIGUOUS no debe sincronizar"
                            )
                        )
                )
            )
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertTrue(
            result[
                "resolution"
            ][
                "ambiguous"
            ]
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_unmatched_does_not_sync(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                True,
                "Desconocido",
                "desconocido",
                4,
                "MSG-4",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Desconocido",
                "desconocido",
                5,
                "MSG-5",
            ),
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity: {
                "matched": False,
                "ambiguous": False,
                "match_basis": None,
                "thread": None,
                "matches": [],
                "identity":
                    identity,
            }
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertFalse(
            result[
                "resolution"
            ][
                "matched"
            ]
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_chat_changed_does_not_resolve(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MAMA-10",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Deneb",
                "deneb",
                20,
                "DENEB-20",
            ),
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity:
                (_ for _ in ())
                .throw(
                    AssertionError(
                        "CHAT_CHANGED no debe resolver"
                    )
                )
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result["change_type"],
            "CHAT_CHANGED",
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_window_changed_does_not_resolve(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                15,
                "MSG-10",
            ),
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity:
                (_ for _ in ())
                .throw(
                    AssertionError(
                        "MESSAGE_WINDOW_CHANGED no debe resolver"
                    )
                )
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result["change_type"],
            "MESSAGE_WINDOW_CHANGED",
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_resolution_error_is_diagnostic(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                11,
                "MSG-11",
            ),
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        def failing_resolve(
            identity,
        ):
            raise RuntimeError(
                "resolver temporalmente caído"
            )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            failing_resolve
        )

        result = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result[
                "resolution"
            ][
                "reason"
            ],
            "RESOLUTION_ERROR",
        )

        self.assertEqual(
            result[
                "resolution"
            ][
                "error_type"
            ],
            "RuntimeError",
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_sync_error_is_diagnostic_and_next_message_retries(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                11,
                "MSG-11",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                12,
                "MSG-12",
            ),
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity: {
                "matched": True,
                "ambiguous": False,
                "match_basis":
                    "DISPLAY_NAME",
                "thread":
                    SimpleNamespace(
                        thread_id=77
                    ),
                "matches": [],
                "identity":
                    identity,
            }
        )

        calls = []

        def sync(
            **kwargs,
        ):
            calls.append(
                dict(
                    kwargs
                )
            )

            if len(
                calls
            ) == 1:
                raise RuntimeError(
                    "sync temporalmente caído"
                )

            return {
                "summary": {
                    "thread_id": 77,
                    "created": 1,
                },
                "items": [],
                "aborted": False,
                "abort_reason": None,
                "guard": {
                    "passed": True,
                },
            }

        runtime._sync_service = (
            SimpleNamespace(
                sync_open_chat_messages=sync
            )
        )

        first = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            first[
                "sync"
            ][
                "reason"
            ],
            "SYNC_ERROR",
        )

        second = (
            runtime.observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            len(
                calls
            ),
            2,
        )

        self.assertFalse(
            second[
                "sync"
            ][
                "aborted"
            ]
        )

        self.assertEqual(
            calls[
                1
            ][
                "expected_last_provider_message_id"
            ],
            "MSG-12",
        )



    def test_active_chat_watch_records_watch_error_and_recovers(
        self,
    ):
        runtime = self._runtime()

        calls = []
        recovered = threading.Event()

        def observe_and_sync_active_chat(
            *,
            wait_timeout=60,
            sync_limit=200,
        ):
            calls.append(
                len(calls) + 1
            )

            if len(calls) == 1:
                raise RuntimeError(
                    "DOM temporalmente caído"
                )

            return {
                "changed": True,
                "change_type": "INITIAL",
                "previous": None,
                "current": None,
                "resolution": None,
                "sync": None,
            }

        runtime.observe_and_sync_active_chat = (
            observe_and_sync_active_chat
        )

        def on_change(
            result,
        ):
            recovered.set()

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            recovered.wait(
                timeout=1
            )
        )

        runtime.stop_active_chat_watch()

        diagnostic = (
            runtime.active_chat_watch_last_error
        )

        self.assertIsNotNone(
            diagnostic
        )

        self.assertEqual(
            diagnostic["stage"],
            "WATCH",
        )

        self.assertEqual(
            diagnostic["reason"],
            "WATCH_ERROR",
        )

        self.assertEqual(
            diagnostic["error_type"],
            "RuntimeError",
        )

        self.assertGreaterEqual(
            len(calls),
            2,
        )


    def test_active_chat_watch_records_resolution_error(
        self,
    ):
        runtime = self._runtime()

        observed = threading.Event()

        def observe_and_sync_active_chat(
            *,
            wait_timeout=60,
            sync_limit=200,
        ):
            return {
                "changed": True,
                "change_type":
                    "MESSAGE_CHANGED",
                "previous": None,
                "current": None,
                "resolution": {
                    "matched": False,
                    "ambiguous": False,
                    "thread": None,
                    "error": True,
                    "reason":
                        "RESOLUTION_ERROR",
                    "error_type":
                        "RuntimeError",
                },
                "sync": None,
            }

        runtime.observe_and_sync_active_chat = (
            observe_and_sync_active_chat
        )

        def on_change(
            result,
        ):
            observed.set()

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            observed.wait(
                timeout=1
            )
        )

        runtime.stop_active_chat_watch()

        diagnostic = (
            runtime.active_chat_watch_last_error
        )

        self.assertEqual(
            diagnostic["stage"],
            "RESOLUTION",
        )

        self.assertEqual(
            diagnostic["reason"],
            "RESOLUTION_ERROR",
        )

        self.assertEqual(
            diagnostic["change_type"],
            "MESSAGE_CHANGED",
        )


    def test_active_chat_watch_records_sync_error_and_later_success(
        self,
    ):
        runtime = self._runtime()

        calls = []
        recovered = threading.Event()

        def observe_and_sync_active_chat(
            *,
            wait_timeout=60,
            sync_limit=200,
        ):
            calls.append(
                len(calls) + 1
            )

            if len(calls) == 1:
                return {
                    "changed": True,
                    "change_type":
                        "MESSAGE_CHANGED",
                    "previous": None,
                    "current": None,
                    "resolution": {
                        "matched": True,
                        "ambiguous": False,
                    },
                    "sync": {
                        "error": True,
                        "reason":
                            "SYNC_ERROR",
                        "error_type":
                            "RuntimeError",
                    },
                }

            return {
                "changed": True,
                "change_type":
                    "MESSAGE_CHANGED",
                "previous": None,
                "current": None,
                "resolution": {
                    "matched": True,
                    "ambiguous": False,
                },
                "sync": {
                    "summary": {
                        "thread_id": 77,
                        "created": 1,
                    },
                    "items": [],
                    "error": False,
                    "aborted": False,
                    "abort_reason": None,
                },
            }

        runtime.observe_and_sync_active_chat = (
            observe_and_sync_active_chat
        )

        def on_change(
            result,
        ):
            sync_result = result.get(
                "sync"
            )

            if (
                isinstance(
                    sync_result,
                    dict,
                )
                and not sync_result.get(
                    "error"
                )
                and not sync_result.get(
                    "aborted"
                )
            ):
                recovered.set()

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            recovered.wait(
                timeout=1
            )
        )

        runtime.stop_active_chat_watch()

        diagnostic = (
            runtime.active_chat_watch_last_error
        )

        last_sync = (
            runtime.active_chat_watch_last_sync
        )

        # El error histórico debe conservarse.
        self.assertIsNotNone(
            diagnostic
        )

        self.assertEqual(
            diagnostic["stage"],
            "SYNC",
        )

        self.assertEqual(
            diagnostic["reason"],
            "SYNC_ERROR",
        )

        # Y simultáneamente debe constar
        # que hubo recuperación posterior.
        self.assertIsNotNone(
            last_sync
        )

        self.assertEqual(
            last_sync["change_type"],
            "MESSAGE_CHANGED",
        )

        self.assertEqual(
            last_sync[
                "sync"
            ][
                "summary"
            ][
                "thread_id"
            ],
            77,
        )

        self.assertGreaterEqual(
            len(calls),
            2,
        )


    def test_active_chat_watch_records_callback_error_and_survives(
        self,
    ):
        runtime = self._runtime()

        calls = []
        diagnostic_seen = threading.Event()

        def observe_and_sync_active_chat(
            *,
            wait_timeout=60,
            sync_limit=200,
        ):
            calls.append(
                len(calls) + 1
            )

            if len(calls) > 1:
                diagnostic = (
                    runtime.active_chat_watch_last_error
                )

                if (
                    isinstance(
                        diagnostic,
                        dict,
                    )
                    and diagnostic.get(
                        "stage"
                    )
                    == "CALLBACK"
                ):
                    diagnostic_seen.set()

                return {
                    "changed": False,
                    "change_type":
                        "UNCHANGED",
                    "previous": None,
                    "current": None,
                    "resolution": None,
                    "sync": None,
                }

            return {
                "changed": True,
                "change_type": "INITIAL",
                "previous": None,
                "current": None,
                "resolution": None,
                "sync": None,
            }

        runtime.observe_and_sync_active_chat = (
            observe_and_sync_active_chat
        )

        def failing_callback(
            result,
        ):
            raise ValueError(
                "callback consumidor roto"
            )

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=failing_callback,
        )

        self.assertTrue(
            diagnostic_seen.wait(
                timeout=1
            )
        )

        runtime.stop_active_chat_watch()

        diagnostic = (
            runtime.active_chat_watch_last_error
        )

        self.assertEqual(
            diagnostic["stage"],
            "CALLBACK",
        )

        self.assertEqual(
            diagnostic["reason"],
            "CALLBACK_ERROR",
        )

        self.assertEqual(
            diagnostic["error_type"],
            "ValueError",
        )

        self.assertGreaterEqual(
            len(calls),
            2,
        )


    def test_active_chat_watch_does_not_record_aborted_guard_as_success(
        self,
    ):
        runtime = self._runtime()

        observed = threading.Event()

        def observe_and_sync_active_chat(
            *,
            wait_timeout=60,
            sync_limit=200,
        ):
            return {
                "changed": True,
                "change_type":
                    "MESSAGE_CHANGED",
                "previous": None,
                "current": None,
                "resolution": {
                    "matched": True,
                    "ambiguous": False,
                },
                "sync": {
                    "summary": {
                        "thread_id": 77,
                        "created": 0,
                    },
                    "items": [],
                    "error": False,
                    "aborted": True,
                    "abort_reason":
                        "ACTIVE_CHAT_CHANGED",
                },
            }

        runtime.observe_and_sync_active_chat = (
            observe_and_sync_active_chat
        )

        def on_change(
            result,
        ):
            observed.set()

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            observed.wait(
                timeout=1
            )
        )

        runtime.stop_active_chat_watch()

        self.assertIsNone(
            runtime.active_chat_watch_last_sync
        )

        # ACTIVE_CHAT_CHANGED es una barrera
        # de seguridad, no un error operativo.
        self.assertIsNone(
            runtime.active_chat_watch_last_error
        )



if __name__ == "__main__":
    unittest.main()
