from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import threading
import unittest

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_READY,
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_DIRECTION_OUTBOUND,
    WHATSAPP_CALL_DIRECTION_UNKNOWN,
    WHATSAPP_CALL_PHASE_ABSENT,
    WHATSAPP_CALL_PHASE_ACTIVE,
    WHATSAPP_CALL_PHASE_CONNECTING,
    WHATSAPP_CALL_PHASE_ENDED_TRANSIENT,
    WHATSAPP_CALL_PHASE_OUTGOING_DIALING,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WhatsAppActiveChatFingerprint,
    WhatsAppCallSnapshot,
)
from backend.services.whatsapp_call_realtime_service import (
    WHATSAPP_CALL_REALTIME_DISABLED,
    WHATSAPP_CALL_REALTIME_NOT_ACTIONABLE,
    WHATSAPP_CALL_REALTIME_RECONCILED,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_call_service import (
    CommunicationCallService,
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

        self.close_result = True
        self.close_error = None

        self.status = (
            SESSION_STATUS_READY
        )

        self.sent = []
        self.sync_snapshots = []

        self.active_chat_fingerprints = []
        self.sidebar_chat_fingerprints = []

        self.call_snapshots = []
        self.call_snapshot_thread_ids = []

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

        self.active_phone_verification_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        self.active_phone_verification_calls = []


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

        if self.close_error is not None:
            raise self.close_error

        if not self.close_result:
            return False

        self.browser = None

        return True

    def read_call_snapshot(
        self,
    ):
        self.call_snapshot_thread_ids.append(
            threading.get_ident()
        )

        if self.call_snapshots:
            return self.call_snapshots.pop(
                0
            )

        return WhatsAppCallSnapshot(
            present=False,
            phase=(
                WHATSAPP_CALL_PHASE_ABSENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
        )


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

    def get_sidebar_chat_fingerprint(
        self,
        *,
        viewport_only=True,
    ):
        if not self.sidebar_chat_fingerprints:
            # Compatibilidad con tests históricos:
            # si no preparan sidebar explícitamente,
            # se considera una bandeja estable vacía.
            return {}

        value = (
            self.sidebar_chat_fingerprints
            .pop(0)
        )

        if isinstance(
            value,
            BaseException,
        ):
            raise value

        return dict(
            value
        )

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

    def _verify_active_chat_phone(
        self,
        phone,
        *,
        timeout=10,
    ):
        self.active_phone_verification_calls.append(
            (
                phone,
                timeout,
            )
        )

        result = dict(
            self.active_phone_verification_result
        )

        result[
            "expected_phone"
        ] = str(
            result.get(
                "expected_phone"
            )
            or phone
        )

        return result



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
        self.latest_provider_message_id = None
        self.sidebar_discovery_calls = []
        self.sidebar_discovery_result = None

    def discover_whatsapp_sidebar_thread(
        self,
        **kwargs,
    ):
        self.sidebar_discovery_calls.append(
            dict(
                kwargs
            )
        )

        if (
            self.sidebar_discovery_result
            is not None
        ):
            return dict(
                self.sidebar_discovery_result
            )

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

    def get_latest_thread_provider_message_id(
        self,
        thread_id,
    ):
        if (
            self.thread is None
            or int(thread_id)
            != int(self.thread.id)
        ):
            raise ValueError(
                "Conversación no encontrada"
            )

        return (
            self.latest_provider_message_id
        )

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


class FakeSuccessfulOutboundService:
    def __init__(
        self,
    ):
        self.calls = []

    def send_text_message(
        self,
        **kwargs,
    ):
        self.calls.append(
            dict(
                kwargs
            )
        )

        return {
            "ok": True,
            "uncertain": False,
            "message": None,
            "attempt": None,
            "provider_snapshot": None,
            "error": None,
        }


class FakeCallService:
    def __init__(
        self,
    ):
        self.snapshots = []
        self.thread_ids = []

    def reconcile_provider_call(
        self,
        snapshot,
    ):
        self.snapshots.append(
            snapshot
        )

        self.thread_ids.append(
            threading.get_ident()
        )

        return SimpleNamespace(
            id=len(
                self.snapshots
            ),
            provider=(
                snapshot.provider
            ),
            external_call_key=(
                snapshot.external_call_key
            ),
            status=(
                snapshot.status
            ),
        )


class WhatsAppRuntimeServiceTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        FakeConnector.instances = []

    def _runtime(
        self,
        *,
        call_service=None,
        call_clock=None,
    ):
        return WhatsAppRuntimeService(
            profile_key="test_profile",
            headless=True,
            communication_service=(
                FakeCommunicationService()
            ),
            call_service=(
                call_service
            ),
            call_clock=(
                call_clock
            ),
            connector_factory=(
                FakeConnector
            ),
        )

    def test_observe_and_sync_call_is_disabled_without_call_service(
        self,
    ):
        clock_called = []

        def forbidden_clock():
            clock_called.append(
                True
            )
            raise AssertionError(
                "No debe consultarse reloj "
                "si persistencia está deshabilitada"
            )

        runtime = self._runtime(
            call_clock=forbidden_clock,
        )

        connector = runtime.start()

        connector.call_snapshots = [
            WhatsAppCallSnapshot(
                present=True,
                phase=(
                    WHATSAPP_CALL_PHASE_INCOMING_RINGING
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_INBOUND
                ),
                provider_call_id="CALL-DISABLED",
                external_call_key=(
                    "opaque-disabled"
                ),
                participant_lid="remote@lid",
                participant_phone_id=(
                    "34600111222@c.us"
                ),
                participant_phone=(
                    "+34600111222"
                ),
                is_video=False,
                identity_complete=True,
            )
        ]

        result = (
            runtime
            .observe_and_sync_call(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_DISABLED,
        )

        self.assertEqual(
            clock_called,
            [],
        )


    def test_observe_and_sync_call_reconciles_on_runtime_worker(
        self,
    ):
        call_service = (
            FakeCallService()
        )

        runtime = self._runtime(
            call_service=call_service,
            call_clock=lambda: (
                "2026-08-15T09:40:00+00:00"
            ),
        )

        connector = runtime.start()

        connector.call_snapshots = [
            WhatsAppCallSnapshot(
                present=True,
                phase=(
                    WHATSAPP_CALL_PHASE_OUTGOING_DIALING
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_OUTBOUND
                ),
                provider_call_id="CALL-RT-001",
                external_call_key=(
                    "opaque-rt-001"
                ),
                participant_lid="remote@lid",
                participant_phone_id=(
                    "34600111222@c.us"
                ),
                participant_phone=(
                    "+34600111222"
                ),
                participant_display_name=(
                    "Contacto"
                ),
                is_video=False,
                identity_complete=True,
            )
        ]

        result = (
            runtime
            .observe_and_sync_call(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result.action,
            WHATSAPP_CALL_REALTIME_RECONCILED,
        )

        self.assertEqual(
            len(
                call_service.snapshots
            ),
            1,
        )

        self.assertEqual(
            call_service.thread_ids,
            [
                runtime._worker_thread_id
            ],
        )

        projected = (
            call_service.snapshots[0]
        )

        self.assertEqual(
            projected.external_call_key,
            "opaque-rt-001",
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_dialing_at"
            ],
            "2026-08-15T09:40:00+00:00",
        )


    def test_observe_and_sync_call_late_active_does_not_fake_timestamps(
        self,
    ):
        call_service = (
            FakeCallService()
        )

        runtime = self._runtime(
            call_service=call_service,
            call_clock=lambda: (
                "2026-08-15T09:45:00+00:00"
            ),
        )

        connector = runtime.start()

        connector.call_snapshots = [
            WhatsAppCallSnapshot(
                present=True,
                phase=(
                    WHATSAPP_CALL_PHASE_ACTIVE
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_INBOUND
                ),
                provider_call_id="CALL-LATE-001",
                external_call_key=(
                    "opaque-late-001"
                ),
                participant_lid="remote@lid",
                participant_phone_id=(
                    "34600111222@c.us"
                ),
                participant_phone=(
                    "+34600111222"
                ),
                is_video=False,
                identity_complete=True,
            )
        ]

        result = (
            runtime
            .observe_and_sync_call(
                wait_timeout=1,
            )
        )

        projected = (
            result.provider_snapshot
        )

        self.assertEqual(
            projected.status,
            "ANSWERED",
        )

        self.assertIsNone(
            projected.dialed_at
        )

        self.assertIsNone(
            projected.ringing_at
        )

        self.assertIsNone(
            projected.answered_at
        )

        self.assertIsNone(
            projected.ended_at
        )

        self.assertEqual(
            projected.metadata[
                "crm_observed_answered_at"
            ],
            "2026-08-15T09:45:00+00:00",
        )


    def test_raw_observe_call_still_never_persists(
        self,
    ):
        call_service = (
            FakeCallService()
        )

        runtime = self._runtime(
            call_service=call_service,
            call_clock=lambda: (
                "2026-08-15T09:50:00+00:00"
            ),
        )

        connector = runtime.start()

        connector.call_snapshots = [
            WhatsAppCallSnapshot(
                present=True,
                phase=(
                    WHATSAPP_CALL_PHASE_ACTIVE
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_INBOUND
                ),
                provider_call_id="CALL-RAW-001",
                external_call_key=(
                    "opaque-raw-001"
                ),
                participant_lid="remote@lid",
                participant_phone_id=(
                    "34600111222@c.us"
                ),
                participant_phone=(
                    "+34600111222"
                ),
                is_video=False,
                identity_complete=True,
            )
        ]

        runtime.observe_call(
            wait_timeout=1,
        )

        self.assertEqual(
            call_service.snapshots,
            [],
        )


    def test_unchanged_call_observation_does_not_reconcile_twice(
        self,
    ):
        call_service = (
            FakeCallService()
        )

        runtime = self._runtime(
            call_service=call_service,
            call_clock=lambda: (
                "2026-08-15T09:55:00+00:00"
            ),
        )

        connector = runtime.start()

        repeated = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_ACTIVE
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_OUTBOUND
            ),
            provider_call_id="CALL-IDEMP-001",
            external_call_key=(
                "opaque-idemp-001"
            ),
            participant_lid="remote@lid",
            participant_phone_id=(
                "34600111222@c.us"
            ),
            participant_phone=(
                "+34600111222"
            ),
            is_video=False,
            identity_complete=True,
        )

        connector.call_snapshots = [
            repeated,
            repeated,
        ]

        first = (
            runtime
            .observe_and_sync_call(
                wait_timeout=1,
            )
        )

        second = (
            runtime
            .observe_and_sync_call(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            first.action,
            WHATSAPP_CALL_REALTIME_RECONCILED,
        )

        self.assertEqual(
            second.action,
            WHATSAPP_CALL_REALTIME_NOT_ACTIONABLE,
        )

        self.assertEqual(
            len(
                call_service.snapshots
            ),
            1,
        )


    def test_observe_and_sync_call_persists_and_advances_same_real_call(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = (
                Path(temp_dir)
                / "runtime_call_integration.db"
            )

            conn = sqlite3.connect(
                str(db_path)
            )

            try:
                conn.executescript(
                    """
                    PRAGMA foreign_keys = ON;

                    CREATE TABLE clientes (
                        id INTEGER PRIMARY KEY,
                        nombre TEXT NOT NULL
                    );

                    CREATE TABLE expedientes (
                        id INTEGER PRIMARY KEY,
                        cliente_id INTEGER
                    );
                    """
                )

                conn.commit()

            finally:
                conn.close()

            repository = (
                SQLiteCommunicationRepository(
                    db_path
                )
            )

            call_service = (
                CommunicationCallService(
                    repository=repository
                )
            )

            observed_times = iter(
                (
                    "2026-08-15T10:00:00+00:00",
                    "2026-08-15T10:00:05+00:00",
                )
            )

            runtime = self._runtime(
                call_service=call_service,
                call_clock=lambda: next(
                    observed_times
                ),
            )

            connector = runtime.start()

            ringing_snapshot = WhatsAppCallSnapshot(
                present=True,
                phase=(
                    WHATSAPP_CALL_PHASE_INCOMING_RINGING
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_INBOUND
                ),
                provider_call_id=(
                    "CALL-REAL-001"
                ),
                external_call_key=(
                    "opaque-real-001"
                ),
                participant_lid=(
                    "remote@lid"
                ),
                participant_phone_id=(
                    "34600111222@c.us"
                ),
                participant_phone=(
                    "+34600111222"
                ),
                participant_display_name=(
                    "Contacto"
                ),
                is_video=False,
                identity_complete=True,
            )

            active_snapshot = WhatsAppCallSnapshot(
                present=True,
                phase=(
                    WHATSAPP_CALL_PHASE_ACTIVE
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_INBOUND
                ),
                provider_call_id=(
                    "CALL-REAL-001"
                ),
                external_call_key=(
                    "opaque-real-001"
                ),
                participant_lid=(
                    "remote@lid"
                ),
                participant_phone_id=(
                    "34600111222@c.us"
                ),
                participant_phone=(
                    "+34600111222"
                ),
                participant_display_name=(
                    "Contacto"
                ),
                is_video=False,
                identity_complete=True,
            )

            connector.call_snapshots = [
                ringing_snapshot,
                active_snapshot,
            ]

            first = (
                runtime
                .observe_and_sync_call(
                    wait_timeout=1,
                )
            )

            second = (
                runtime
                .observe_and_sync_call(
                    wait_timeout=1,
                )
            )

            self.assertEqual(
                first.action,
                WHATSAPP_CALL_REALTIME_RECONCILED,
            )

            self.assertEqual(
                second.action,
                WHATSAPP_CALL_REALTIME_RECONCILED,
            )

            self.assertEqual(
                first.persisted_call.id,
                second.persisted_call.id,
            )

            stored = (
                repository
                .get_call_by_provider_identity(
                    provider="WHATSAPP_WEB",
                    external_call_key=(
                        "opaque-real-001"
                    ),
                )
            )

            self.assertIsNotNone(
                stored
            )

            self.assertEqual(
                stored.id,
                first.persisted_call.id,
            )

            self.assertEqual(
                stored.status,
                "ANSWERED",
            )

            self.assertEqual(
                stored.provider_call_id,
                "CALL-REAL-001",
            )

            self.assertIsNone(
                stored.ringing_at
            )

            self.assertIsNone(
                stored.answered_at
            )

            self.assertEqual(
                stored.metadata[
                    "crm_observed_ringing_at"
                ],
                "2026-08-15T10:00:00+00:00",
            )

            self.assertEqual(
                stored.metadata[
                    "crm_observed_answered_at"
                ],
                "2026-08-15T10:00:05+00:00",
            )

            self.assertEqual(
                stored.metadata[
                    "crm_observed_ringing_provider_phase"
                ],
                WHATSAPP_CALL_PHASE_INCOMING_RINGING,
            )

            self.assertEqual(
                stored.metadata[
                    "crm_observed_answered_provider_phase"
                ],
                WHATSAPP_CALL_PHASE_ACTIVE,
            )

            self.assertNotIn(
                "provider_phase",
                stored.metadata,
            )

            runtime.close()


    def test_read_call_snapshot_runs_on_single_runtime_worker(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        expected = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
            provider_call_id="CALL-001",
            external_call_key=(
                "false_remote@lid_CALL-001"
            ),
            participant_lid="remote@lid",
            participant_phone_id=(
                "34600111222@c.us"
            ),
            participant_phone="+34600111222",
            participant_display_name="Contacto",
            is_video=False,
            visible_state="Llamada",
            can_accept=True,
            can_reject=True,
            can_hangup=False,
            identity_complete=True,
        )

        connector.call_snapshots = [
            expected
        ]

        caller_thread_id = (
            threading.get_ident()
        )

        observed = (
            runtime.read_call_snapshot(
                wait_timeout=1,
            )
        )

        self.assertIs(
            observed,
            expected,
        )

        self.assertEqual(
            len(
                connector
                .call_snapshot_thread_ids
            ),
            1,
        )

        self.assertEqual(
            connector
            .call_snapshot_thread_ids[0],
            runtime._worker_thread_id,
        )

        self.assertNotEqual(
            connector
            .call_snapshot_thread_ids[0],
            caller_thread_id,
        )

        self.assertEqual(
            len(
                FakeConnector.instances
            ),
            1,
        )


    def test_read_call_snapshot_preserves_absent_provider_snapshot(
        self,
    ):
        runtime = self._runtime()

        observed = (
            runtime.read_call_snapshot(
                wait_timeout=1,
            )
        )

        self.assertFalse(
            observed.present
        )

        self.assertEqual(
            observed.phase,
            WHATSAPP_CALL_PHASE_ABSENT,
        )

        self.assertEqual(
            observed.direction,
            WHATSAPP_CALL_DIRECTION_UNKNOWN,
        )

        self.assertIsNone(
            observed.provider_call_id
        )

        self.assertFalse(
            observed.identity_complete
        )


    def test_read_call_snapshot_does_not_keep_runtime_call_state(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        ringing = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
            provider_call_id="CALL-002",
            external_call_key=(
                "false_remote@lid_CALL-002"
            ),
            participant_lid="remote@lid",
            participant_phone_id=(
                "34600111222@c.us"
            ),
            participant_phone="+34600111222",
            participant_display_name="Contacto",
            can_accept=True,
            can_reject=True,
            identity_complete=True,
        )

        absent = WhatsAppCallSnapshot(
            present=False,
            phase=(
                WHATSAPP_CALL_PHASE_ABSENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
        )

        connector.call_snapshots = [
            ringing,
            absent,
        ]

        first = runtime.read_call_snapshot(
            wait_timeout=1,
        )

        second = runtime.read_call_snapshot(
            wait_timeout=1,
        )

        self.assertIs(
            first,
            ringing,
        )

        self.assertIs(
            second,
            absent,
        )

        # read_call_snapshot() continúa siendo una API
        # de transporte pura: no alimenta el tracker stateful.
        self.assertIsNone(
            runtime
            ._call_observation_tracker
            .active
        )

        self.assertEqual(
            connector.call_snapshot_thread_ids,
            [
                runtime._worker_thread_id,
                runtime._worker_thread_id,
            ],
        )


    def test_observe_call_retains_identity_until_surface_disappears(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        connecting = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_CONNECTING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
            can_hangup=True,
            identity_complete=False,
        )

        dialing = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_OUTGOING_DIALING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_OUTBOUND
            ),
            provider_call_id="CALL-RUNTIME-001",
            external_call_key=(
                "opaque-CALL-RUNTIME-001"
            ),
            participant_lid="remote@lid",
            participant_phone_id=(
                "34600111222@c.us"
            ),
            participant_phone="+34600111222",
            participant_display_name="Contacto",
            can_hangup=True,
            identity_complete=True,
        )

        ended = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_ENDED_TRANSIENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_OUTBOUND
            ),
            provider_call_id="CALL-RUNTIME-001",
            external_call_key=(
                "opaque-CALL-RUNTIME-001"
            ),
            identity_complete=False,
        )

        absent = WhatsAppCallSnapshot(
            present=False,
            phase=(
                WHATSAPP_CALL_PHASE_ABSENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
        )

        connector.call_snapshots = [
            connecting,
            dialing,
            ended,
            absent,
        ]

        first = runtime.observe_call(
            wait_timeout=1,
        )

        second = runtime.observe_call(
            wait_timeout=1,
        )

        third = runtime.observe_call(
            wait_timeout=1,
        )

        fourth = runtime.observe_call(
            wait_timeout=1,
        )

        self.assertEqual(
            first.change_type,
            "CALL_SURFACE_APPEARED",
        )

        self.assertEqual(
            second.change_type,
            "CALL_UPDATED",
        )

        self.assertEqual(
            third.change_type,
            "CALL_UPDATED",
        )

        self.assertEqual(
            third.active.participant_phone,
            "+34600111222",
        )

        self.assertTrue(
            third.active.identity_complete
        )

        self.assertEqual(
            fourth.change_type,
            "CALL_SURFACE_DISAPPEARED",
        )

        self.assertEqual(
            fourth
            .disappeared
            .provider_call_id,
            "CALL-RUNTIME-001",
        )

        self.assertIsNone(
            runtime
            ._call_observation_tracker
            .active
        )

        self.assertTrue(
            all(
                thread_id
                == runtime._worker_thread_id
                for thread_id
                in connector.call_snapshot_thread_ids
            )
        )


    def test_observe_call_does_not_classify_ringing_disappearance(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        ringing = WhatsAppCallSnapshot(
            present=True,
            phase=(
                WHATSAPP_CALL_PHASE_INCOMING_RINGING
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_INBOUND
            ),
            provider_call_id="CALL-RUNTIME-IN",
            external_call_key=(
                "opaque-CALL-RUNTIME-IN"
            ),
            participant_lid="remote@lid",
            participant_phone_id=(
                "34600111222@c.us"
            ),
            participant_phone="+34600111222",
            can_accept=True,
            can_reject=True,
            identity_complete=True,
        )

        absent = WhatsAppCallSnapshot(
            present=False,
            phase=(
                WHATSAPP_CALL_PHASE_ABSENT
            ),
            direction=(
                WHATSAPP_CALL_DIRECTION_UNKNOWN
            ),
        )

        connector.call_snapshots = [
            ringing,
            absent,
        ]

        runtime.observe_call(
            wait_timeout=1,
        )

        result = runtime.observe_call(
            wait_timeout=1,
        )

        self.assertEqual(
            result.change_type,
            "CALL_SURFACE_DISAPPEARED",
        )

        self.assertEqual(
            result.disappeared.phase,
            WHATSAPP_CALL_PHASE_INCOMING_RINGING,
        )

        self.assertFalse(
            hasattr(
                result,
                "status",
            )
        )

        self.assertFalse(
            hasattr(
                result,
                "outcome",
            )
        )


    def test_close_resets_call_observation_tracker(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        connector.call_snapshots = [
            WhatsAppCallSnapshot(
                present=True,
                phase=(
                    WHATSAPP_CALL_PHASE_OUTGOING_DIALING
                ),
                direction=(
                    WHATSAPP_CALL_DIRECTION_OUTBOUND
                ),
                provider_call_id="CALL-CLOSE-001",
                external_call_key=(
                    "opaque-CALL-CLOSE-001"
                ),
                participant_lid="remote@lid",
                participant_phone_id=(
                    "34600111222@c.us"
                ),
                participant_phone="+34600111222",
                can_hangup=True,
                identity_complete=True,
            )
        ]

        result = runtime.observe_call(
            wait_timeout=1,
        )

        self.assertEqual(
            result
            .active
            .provider_call_id,
            "CALL-CLOSE-001",
        )

        self.assertIsNotNone(
            runtime
            ._call_observation_tracker
            .active
        )

        runtime.close()

        self.assertIsNone(
            runtime
            ._call_observation_tracker
            .active
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


    def test_close_failure_preserves_connector_services_and_executor(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        executor = runtime._executor

        outbound_service = object()
        sync_service = object()

        runtime._outbound_service = (
            outbound_service
        )

        runtime._sync_service = (
            sync_service
        )

        connector.close_result = False

        try:
            result = runtime.close()

            self.assertFalse(
                result
            )

            self.assertEqual(
                connector.close_calls,
                1,
            )

            self.assertIs(
                runtime.connector,
                connector,
            )

            self.assertTrue(
                runtime.started
            )

            self.assertIs(
                runtime._executor,
                executor,
            )

            self.assertIs(
                runtime._outbound_service,
                outbound_service,
            )

            self.assertIs(
                runtime._sync_service,
                sync_service,
            )

            # El mismo owner puede volver a intentar el cierre.
            connector.close_result = True

            self.assertTrue(
                runtime.close()
            )

            self.assertEqual(
                connector.close_calls,
                2,
            )

            self.assertIsNone(
                runtime.connector
            )

            self.assertIsNone(
                runtime._executor
            )

            self.assertIsNone(
                runtime._outbound_service
            )

            self.assertIsNone(
                runtime._sync_service
            )

        finally:
            if runtime.connector is not None:
                connector.close_result = True
                connector.close_error = None
                runtime.close()


    def test_close_exception_preserves_connector_and_executor(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        executor = runtime._executor

        connector.close_error = RuntimeError(
            "shutdown simulado"
        )

        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "shutdown simulado",
            ):
                runtime.close()

            self.assertEqual(
                connector.close_calls,
                1,
            )

            self.assertIs(
                runtime.connector,
                connector,
            )

            self.assertTrue(
                runtime.started
            )

            self.assertIs(
                runtime._executor,
                executor,
            )

            connector.close_error = None

            self.assertTrue(
                runtime.close()
            )

            self.assertEqual(
                connector.close_calls,
                2,
            )

            self.assertIsNone(
                runtime.connector
            )

            self.assertIsNone(
                runtime._executor
            )

        finally:
            if runtime.connector is not None:
                connector.close_error = None
                connector.close_result = True
                runtime.close()


    def test_close_without_connector_still_releases_executor(
        self,
    ):
        runtime = self._runtime()

        # get_status() está serializado y por ello puede crear
        # el worker aunque nunca llegue a existir connector.
        self.assertEqual(
            runtime.get_status(),
            "NOT_STARTED",
        )

        executor = runtime._executor

        self.assertIsNotNone(
            executor
        )

        self.assertFalse(
            runtime.close()
        )

        self.assertIsNone(
            runtime.connector
        )

        self.assertIsNone(
            runtime._executor
        )


    def test_open_thread_for_selection_uses_light_route_without_preverify(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        result = (
            runtime
            .open_thread_for_selection(
                7,
                wait_timeout=1,
                routing_timeout=9,
            )
        )

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

        # La selección visual NO abre/verifica el perfil.
        self.assertEqual(
            connector.active_phone_verification_calls,
            [],
        )

        self.assertTrue(
            result[
                "routing"
            ][
                "opened"
            ]
        )

        self.assertTrue(
            result[
                "routing"
            ][
                "selection_light"
            ]
        )

        self.assertFalse(
            result[
                "routing"
            ][
                "send_preverified"
            ]
        )

        self.assertIsNone(
            runtime._verified_send_thread_id
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

    def test_light_selection_requires_strong_verify_on_first_send(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        # Selección: navegación ligera.
        selected = (
            runtime
            .open_thread_for_selection(
                7,
                wait_timeout=1,
                routing_timeout=9,
            )
        )

        self.assertTrue(
            selected[
                "routing"
            ][
                "opened"
            ]
        )

        self.assertIsNone(
            runtime._verified_send_thread_id
        )

        # El primer envío debe entrar por la barrera fuerte.
        connector.routing_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        outbound = (
            FakeSuccessfulOutboundService()
        )

        runtime._outbound_service = (
            outbound
        )

        sent = runtime.send_text_message(
            thread_id=7,
            body_text=(
                "Mensaje tras selección ligera"
            ),
            wait_timeout=1,
            routing_timeout=9,
        )

        self.assertTrue(
            sent[
                "ok"
            ]
        )

        # Primera llamada = selección ligera.
        # Segunda llamada = STRONG_VERIFY previo al envío.
        self.assertEqual(
            connector.open_phone_calls,
            [
                (
                    "+34 600 111 222",
                    "Test Contact",
                    False,
                    9,
                ),
                (
                    "+34 600 111 222",
                    "Test Contact",
                    True,
                    9,
                ),
            ],
        )

        self.assertEqual(
            len(
                outbound.calls
            ),
            1,
        )


    def test_verify_and_open_thread_preverifies_for_first_send(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        connector.routing_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        fingerprint = (
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name=(
                    "Test Contact"
                ),
                active_identity=(
                    "test contact"
                ),
                visible_message_count=10,
                last_provider_message_id=(
                    "MSG-10"
                ),
            )
        )

        # 1. recordar cache tras selección;
        # 2. validar cache al primer envío.
        connector.active_chat_fingerprints = [
            fingerprint,
            fingerprint,
        ]

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity: {
                "matched": True,
                "ambiguous": False,
                "match_basis":
                    "DISPLAY_NAME",
                "thread":
                    runtime.communication_service.thread,
                "matches": [
                    runtime.communication_service.thread,
                ],
                "identity":
                    identity,
            }
        )

        result = (
            runtime.verify_and_open_thread(
                7,
                wait_timeout=1,
                routing_timeout=9,
            )
        )

        self.assertTrue(
            result[
                "routing"
            ][
                "verified"
            ]
        )

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

        self.assertEqual(
            runtime._verified_send_thread_id,
            7,
        )

        outbound = (
            FakeSuccessfulOutboundService()
        )

        runtime._outbound_service = (
            outbound
        )

        sent = runtime.send_text_message(
            thread_id=7,
            body_text="Primer mensaje",
            wait_timeout=1,
            routing_timeout=9,
        )

        self.assertTrue(
            sent["ok"]
        )

        # La primera pulsación de Enviar NO debe repetir la
        # verificación fuerte que ya se hizo al seleccionar.
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


    def test_active_chat_watch_emits_sidebar_only_change(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        active = (
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            )
        )

        connector.active_chat_fingerprints = [
            active,
            active,
            active,
        ]

        connector.sidebar_chat_fingerprints = [
            {
                "alla": {
                    "identity":
                        "alla",
                    "display_name":
                        "Alla",
                    "primary_detail":
                        "13:40",
                    "preview":
                        "Vale",
                    "unread_count":
                        0,
                    "position":
                        4,
                    "virtual_offset":
                        304,
                    "ambiguous":
                        False,
                },
            },
            {
                "alla": {
                    "identity":
                        "alla",
                    "display_name":
                        "Alla",
                    "primary_detail":
                        "13:56",
                    "preview":
                        "Nuevo mensaje",
                    "unread_count":
                        1,
                    "position":
                        0,
                    "virtual_offset":
                        0,
                    "ambiguous":
                        False,
                },
            },
        ]

        received = []
        event = threading.Event()

        def on_change(
            result,
        ):
            if result.get(
                "sidebar_changed"
            ):
                received.append(
                    result
                )
                event.set()

        runtime.start_active_chat_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            event.wait(
                timeout=1,
            )
        )

        runtime.stop_active_chat_watch()

        self.assertGreaterEqual(
            len(
                received
            ),
            1,
        )

        result = received[
            0
        ]

        self.assertEqual(
            result[
                "change_type"
            ],
            "UNCHANGED",
        )

        self.assertTrue(
            result[
                "sidebar_changed"
            ]
        )

        self.assertEqual(
            result[
                "sidebar_changes"
            ][0][
                "identity"
            ],
            "alla",
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


    def test_send_text_message_reuses_verified_route_for_same_active_thread(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.routing_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        fingerprint = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name=(
                "Test Contact"
            ),
            active_identity=(
                "test contact"
            ),
            visible_message_count=10,
            last_provider_message_id=(
                "MSG-10"
            ),
        )

        # Primera huella:
        # cache tras verificación fuerte.
        #
        # Segunda huella:
        # validación del fast-path.
        connector.active_chat_fingerprints = [
            fingerprint,
            fingerprint,
        ]

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity: {
                "matched": True,
                "ambiguous": False,
                "match_basis":
                    "DISPLAY_NAME",
                "thread":
                    runtime.communication_service.thread,
                "matches": [
                    runtime.communication_service.thread,
                ],
                "identity":
                    identity,
            }
        )

        outbound = (
            FakeSuccessfulOutboundService()
        )

        runtime._outbound_service = (
            outbound
        )

        first = runtime.send_text_message(
            thread_id=7,
            body_text="Primero",
            wait_timeout=1,
            routing_timeout=9,
        )

        second = runtime.send_text_message(
            thread_id=7,
            body_text="Segundo",
            wait_timeout=1,
            routing_timeout=9,
        )

        self.assertTrue(
            first["ok"]
        )

        self.assertTrue(
            second["ok"]
        )

        # Solo el primer envío exige verificación fuerte.
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

        self.assertEqual(
            len(
                outbound.calls
            ),
            2,
        )


    def test_send_text_message_rejects_cache_after_manual_chat_change(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.routing_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        expected_fingerprint = (
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name=(
                    "Test Contact"
                ),
                active_identity=(
                    "test contact"
                ),
                visible_message_count=10,
                last_provider_message_id=(
                    "MSG-10"
                ),
            )
        )

        other_fingerprint = (
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name=(
                    "Other Contact"
                ),
                active_identity=(
                    "other contact"
                ),
                visible_message_count=5,
                last_provider_message_id=(
                    "OTHER-5"
                ),
            )
        )

        # 1. recordar primera verificación;
        # 2. detectar que el usuario cambió de chat;
        # 3. recordar de nuevo la ruta tras fallback fuerte.
        connector.active_chat_fingerprints = [
            expected_fingerprint,
            other_fingerprint,
            expected_fingerprint,
        ]

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity: {
                "matched": True,
                "ambiguous": False,
                "thread":
                    runtime.communication_service.thread,
                "matches": [
                    runtime.communication_service.thread,
                ],
                "identity":
                    identity,
            }
        )

        outbound = (
            FakeSuccessfulOutboundService()
        )

        runtime._outbound_service = (
            outbound
        )

        runtime.send_text_message(
            thread_id=7,
            body_text="Primero",
            wait_timeout=1,
            routing_timeout=9,
        )

        runtime.send_text_message(
            thread_id=7,
            body_text="Segundo",
            wait_timeout=1,
            routing_timeout=9,
        )

        # Al cambiar el chat activo, el segundo envío
        # vuelve obligatoriamente por strong verification.
        self.assertEqual(
            len(
                connector.open_phone_calls
            ),
            2,
        )


    def test_send_text_message_rejects_cache_when_identity_is_ambiguous(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        connector.routing_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        fingerprint = WhatsAppActiveChatFingerprint(
            chat_open=True,
            active_display_name=(
                "Test Contact"
            ),
            active_identity=(
                "test contact"
            ),
            visible_message_count=10,
            last_provider_message_id=(
                "MSG-10"
            ),
        )

        connector.active_chat_fingerprints = [
            fingerprint,
            fingerprint,
            fingerprint,
        ]

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            lambda identity: {
                "matched": False,
                "ambiguous": True,
                "thread": None,
                "matches": [
                    object(),
                    object(),
                ],
                "identity":
                    identity,
            }
        )

        outbound = (
            FakeSuccessfulOutboundService()
        )

        runtime._outbound_service = (
            outbound
        )

        runtime.send_text_message(
            thread_id=7,
            body_text="Primero",
            wait_timeout=1,
            routing_timeout=9,
        )

        runtime.send_text_message(
            thread_id=7,
            body_text="Segundo",
            wait_timeout=1,
            routing_timeout=9,
        )

        # Un nombre ambiguo nunca autoriza fast-path.
        self.assertEqual(
            len(
                connector.open_phone_calls
            ),
            2,
        )


    def test_close_clears_verified_send_route(
        self,
    ):
        runtime = self._runtime()

        runtime.start()

        runtime._verified_send_thread_id = 7
        runtime._verified_send_phone = (
            "+34 600 111 222"
        )
        runtime._verified_send_identity = (
            "test contact"
        )

        runtime.close()

        self.assertIsNone(
            runtime._verified_send_thread_id
        )

        self.assertIsNone(
            runtime._verified_send_phone
        )

        self.assertIsNone(
            runtime._verified_send_identity
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


    def test_observe_and_sync_sidebar_first_snapshot_is_baseline(
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
        ]

        connector.sidebar_chat_fingerprints = [
            {
                "alla": {
                    "identity":
                        "alla",
                    "display_name":
                        "Alla",
                    "primary_detail":
                        "13:40",
                    "preview":
                        "Hola",
                    "unread_count":
                        1,
                    "position":
                        0,
                    "virtual_offset":
                        0,
                    "ambiguous":
                        False,
                },
            },
        ]

        result = (
            runtime
            .observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            result[
                "sidebar_change_type"
            ],
            "SIDEBAR_INITIAL",
        )

        self.assertFalse(
            result[
                "sidebar_changed"
            ]
        )

        self.assertEqual(
            result[
                "sidebar_changes"
            ],
            [],
        )

        self.assertIn(
            "alla",
            result[
                "sidebar"
            ],
        )

    def test_initial_unread_phone_sidebar_is_passively_discovered(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        active = (
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            )
        )

        connector.active_chat_fingerprints = [
            active,
        ]

        connector.sidebar_chat_fingerprints = [
            {
                "34 600 999 888": {
                    "identity":
                        "34 600 999 888",
                    "display_name":
                        "+34 600 999 888",
                    "primary_detail":
                        "13:05",
                    "preview":
                        "Hola",
                    "unread_count":
                        1,
                    "position":
                        0,
                    "virtual_offset":
                        0,
                    "ambiguous":
                        False,
                },
            },
        ]

        service = (
            runtime.communication_service
        )

        service.sidebar_discovery_result = {
            "discovered": True,
            "created": True,
            "reused": False,
            "reason": None,
            "thread":
                service.thread,
            "match": {
                "matched": False,
                "client": None,
            },
            "phone":
                "+34600999888",
            "external_thread_key":
                "phone:34600999888",
        }

        result = (
            runtime
            .observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertEqual(
            len(
                service.sidebar_discovery_calls
            ),
            1,
        )

        call = (
            service.sidebar_discovery_calls[
                0
            ]
        )

        self.assertEqual(
            call["display_name"],
            "+34 600 999 888",
        )

        self.assertEqual(
            call["unread_count"],
            1,
        )

        discoveries = (
            result[
                "sidebar_discoveries"
            ]
        )

        self.assertEqual(
            len(
                discoveries
            ),
            1,
        )

        discovery = discoveries[0]

        self.assertTrue(
            discovery["discovered"]
        )

        self.assertTrue(
            discovery["created"]
        )

        self.assertEqual(
            discovery["thread_id"],
            service.thread.id,
        )

        self.assertEqual(
            discovery[
                "external_thread_key"
            ],
            "phone:34600999888",
        )

        # Discovery lateral no sincroniza ni navega
        # por sí mismo el chat activo.
        self.assertIsNone(
            result["sync"]
        )

    def test_sidebar_discovery_ignores_zero_unread_baseline(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        active = (
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            )
        )

        connector.active_chat_fingerprints = [
            active,
        ]

        connector.sidebar_chat_fingerprints = [
            {
                "34 600 999 888": {
                    "identity":
                        "34 600 999 888",
                    "display_name":
                        "+34 600 999 888",
                    "primary_detail":
                        "Ayer",
                    "preview":
                        "Histórico",
                    "unread_count":
                        0,
                    "position":
                        4,
                    "virtual_offset":
                        304,
                    "ambiguous":
                        False,
                },
            },
        ]

        result = (
            runtime
            .observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        service = (
            runtime.communication_service
        )

        self.assertEqual(
            service.sidebar_discovery_calls,
            [],
        )

        self.assertEqual(
            result[
                "sidebar_discoveries"
            ],
            [],
        )

        self.assertIsNone(
            result["sync"]
        )


    def test_observe_and_sync_sidebar_change_sets_global_changed(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        active = (
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            )
        )

        connector.active_chat_fingerprints = [
            active,
            active,
        ]

        connector.sidebar_chat_fingerprints = [
            {
                "alla": {
                    "identity":
                        "alla",
                    "display_name":
                        "Alla",
                    "primary_detail":
                        "13:40",
                    "preview":
                        "Vale",
                    "unread_count":
                        0,
                    "position":
                        4,
                    "virtual_offset":
                        304,
                    "ambiguous":
                        False,
                },
            },
            {
                "alla": {
                    "identity":
                        "alla",
                    "display_name":
                        "Alla",
                    "primary_detail":
                        "13:55",
                    "preview":
                        "Necesito hablar contigo",
                    "unread_count":
                        1,
                    "position":
                        0,
                    "virtual_offset":
                        0,
                    "ambiguous":
                        False,
                },
            },
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        result = (
            runtime
            .observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        # El chat activo no ha cambiado.
        self.assertEqual(
            result[
                "change_type"
            ],
            "UNCHANGED",
        )

        # Pero el resultado global sí debe notificarse.
        self.assertTrue(
            result[
                "changed"
            ]
        )

        self.assertTrue(
            result[
                "sidebar_changed"
            ]
        )

        self.assertEqual(
            result[
                "sidebar_change_type"
            ],
            "SIDEBAR_CHANGED",
        )

        self.assertEqual(
            len(
                result[
                    "sidebar_changes"
                ]
            ),
            1,
        )

        change = result[
            "sidebar_changes"
        ][0]

        self.assertEqual(
            change[
                "identity"
            ],
            "alla",
        )

        self.assertEqual(
            change[
                "change_type"
            ],
            "SIDEBAR_THREAD_CHANGED",
        )

        self.assertTrue(
            change[
                "preview_changed"
            ]
        )

        self.assertTrue(
            change[
                "unread_changed"
            ]
        )

        # Un cambio lateral jamás debe intentar
        # sincronizar el chat activo por sí mismo.
        self.assertIsNone(
            result[
                "sync"
            ]
        )

    def test_observe_and_sync_sidebar_reorder_is_not_content_change(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        active = (
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                10,
                "MSG-10",
            )
        )

        connector.active_chat_fingerprints = [
            active,
            active,
        ]

        base = {
            "identity":
                "alla",
            "display_name":
                "Alla",
            "primary_detail":
                "13:40",
            "preview":
                "Vale",
            "unread_count":
                0,
            "position":
                4,
            "virtual_offset":
                304,
            "ambiguous":
                False,
        }

        connector.sidebar_chat_fingerprints = [
            {
                "alla":
                    dict(
                        base
                    ),
            },
            {
                "alla": {
                    **base,
                    "position":
                        0,
                    "virtual_offset":
                        0,
                },
            },
        ]

        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        result = (
            runtime
            .observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        self.assertTrue(
            result[
                "sidebar_changed"
            ]
        )

        change = result[
            "sidebar_changes"
        ][0]

        self.assertEqual(
            change[
                "change_type"
            ],
            "SIDEBAR_THREAD_REORDERED",
        )

        self.assertFalse(
            change[
                "content_changed"
            ]
        )

        self.assertIsNone(
            result[
                "sync"
            ]
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

        self.assertEqual(
            sync_calls[
                0
            ][
                "after_provider_message_id"
            ],
            "MSG-10",
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


    def test_observe_and_sync_chat_changed_resolves_and_syncs(
        self,
    ):
        runtime = self._runtime()
        connector = runtime.start()

        runtime.communication_service.thread = (
            FakeThread(
                thread_id=77,
                external_address=(
                    "+34 671 225 902"
                ),
                external_display_name=(
                    "Deneb"
                ),
            )
        )

        runtime.communication_service.latest_provider_message_id = (
            "DENEB-19"
        )

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

        # Baseline inicial.
        runtime.observe_and_sync_active_chat(
            wait_timeout=1,
        )

        resolved_thread = type(
            "ResolvedThread",
            (),
            {
                "thread_id": 77,
            },
        )()

        resolution_calls = []

        def resolve(
            identity,
        ):
            resolution_calls.append(
                identity
            )

            return {
                "matched": True,
                "ambiguous": False,
                "match_basis":
                    "DISPLAY_NAME",
                "thread":
                    resolved_thread,
                "matches": [
                    resolved_thread,
                ],
                "identity":
                    identity,
            }

        runtime.communication_service.resolve_whatsapp_thread_by_identity = (
            resolve
        )

        sync_calls = []

        class SyncService:
            def sync_open_chat_messages(
                self,
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
                        "scanned": 20,
                        "created": 1,
                        "reused": 19,
                        "status_advanced": 0,
                        "skipped": 0,
                        "errors": 0,
                    },
                    "items": [],
                    "error": False,
                    "aborted": False,
                    "abort_reason": None,
                }

        runtime._sync_service = (
            SyncService()
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

        self.assertEqual(
            resolution_calls,
            [
                "deneb",
            ],
        )

        self.assertEqual(
            len(
                sync_calls
            ),
            1,
        )

        self.assertEqual(
            sync_calls[0][
                "thread_id"
            ],
            77,
        )

        self.assertEqual(
            sync_calls[0][
                "expected_active_identity"
            ],
            "deneb",
        )

        self.assertEqual(
            sync_calls[0][
                "expected_last_provider_message_id"
            ],
            "DENEB-20",
        )

        self.assertEqual(
            sync_calls[0][
                "after_provider_message_id"
            ],
            "DENEB-19",
        )

        self.assertFalse(
            result["sync"][
                "aborted"
            ]
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


    def test_status_only_fingerprint_change_is_message_changed(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        connector.active_chat_fingerprints = [
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                20,
                "MSG-STATUS-1",
                "SENT",
            ),
            WhatsAppActiveChatFingerprint(
                True,
                "Mama",
                "mama",
                20,
                "MSG-STATUS-1",
                "READ",
            ),
        ]

        first = runtime.observe_active_chat(
            wait_timeout=1,
        )

        second = runtime.observe_active_chat(
            wait_timeout=1,
        )

        self.assertEqual(
            first["change_type"],
            "INITIAL",
        )

        self.assertTrue(
            second["changed"]
        )

        self.assertEqual(
            second["change_type"],
            "MESSAGE_CHANGED",
        )

        self.assertEqual(
            second[
                "previous"
            ].last_provider_message_status,
            "SENT",
        )

        self.assertEqual(
            second[
                "current"
            ].last_provider_message_status,
            "READ",
        )


    def test_active_chat_watch_default_interval_is_500ms(
        self,
    ):
        import inspect

        signature = inspect.signature(
            WhatsAppRuntimeService.start_active_chat_watch
        )

        self.assertEqual(
            signature.parameters[
                "interval_seconds"
            ].default,
            0.5,
        )

    def test_active_chat_watch_loop_uses_interruptible_event_wait(
        self,
    ):
        from pathlib import Path

        source = Path(
            "backend/services/whatsapp_runtime_service.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    def _active_chat_watch_loop("
        )

        end = source.index(
            "\n    def start_active_chat_watch(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "stop_event.wait(",
            block,
        )

        self.assertIn(
            "interval_seconds",
            block,
        )

        self.assertNotIn(
            "time.sleep(interval_seconds)",
            block,
        )




    def test_unknown_unread_sidebar_to_explicit_selection_to_phone_sync(
        self,
    ):
        """Simula el ciclo completo de un número desconocido.

        Contratos demostrados:
        1. unread lateral puede descubrir el thread;
        2. discovery NO navega al chat;
        3. solo la selección explícita abre el teléfono;
        4. el cambio de chat se resuelve por PHONE;
        5. el nuevo thread entra en sync incremental.
        """
        runtime = self._runtime()
        connector = runtime.start()

        service = (
            runtime.communication_service
        )

        # Representamos el thread que habría sido creado
        # realmente por CommunicationService en A4.
        service.thread = FakeThread(
            thread_id=77,
            external_address=(
                "+34600999888"
            ),
            external_display_name=(
                "+34 600 999 888"
            ),
        )

        service.sidebar_discovery_result = {
            "discovered": True,
            "created": True,
            "reused": False,
            "reason": None,
            "thread":
                service.thread,
            "match": {
                "matched": False,
                "ambiguous": False,
                "client": None,
            },
            "phone":
                "+34600999888",
            "external_thread_key":
                "phone:34600999888",
        }

        old_chat = (
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name=(
                    "Chat anterior"
                ),
                active_identity=(
                    "chat anterior"
                ),
                visible_message_count=5,
                last_provider_message_id=(
                    "OLD-5"
                ),
            )
        )

        unknown_chat = (
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name=(
                    "+34 600 999 888"
                ),
                active_identity=(
                    "+34 600 999 888"
                ),
                visible_message_count=1,
                last_provider_message_id=(
                    "A7-SIM-1"
                ),
            )
        )

        connector.active_chat_fingerprints = [
            old_chat,
            unknown_chat,
        ]

        sidebar_unknown = {
            "34600999888": {
                "identity":
                    "34600999888",
                "display_name":
                    "+34 600 999 888",
                "primary_detail":
                    "13:31",
                "preview":
                    "QA-A7-SIM",
                "unread_count":
                    1,
                "position":
                    0,
                "virtual_offset":
                    0,
                "ambiguous":
                    False,
            },
        }

        connector.sidebar_chat_fingerprints = [
            sidebar_unknown,
            sidebar_unknown,
        ]

        # ----------------------------------------------------
        # PASO 1 · discovery pasivo
        # ----------------------------------------------------

        first = (
            runtime
            .observe_and_sync_active_chat(
                wait_timeout=1,
            )
        )

        discoveries = (
            first.get(
                "sidebar_discoveries"
            )
            or []
        )

        self.assertEqual(
            len(
                discoveries
            ),
            1,
        )

        discovery = discoveries[0]

        self.assertTrue(
            discovery["discovered"]
        )

        self.assertTrue(
            discovery["created"]
        )

        self.assertEqual(
            discovery["thread_id"],
            77,
        )

        self.assertEqual(
            discovery[
                "external_thread_key"
            ],
            "phone:34600999888",
        )

        # INVARIANTE CRÍTICO:
        # descubrir el unread NO puede navegar.
        self.assertEqual(
            connector.open_phone_calls,
            [],
        )

        self.assertIsNone(
            first.get(
                "sync"
            )
        )

        # ----------------------------------------------------
        # PASO 2 · selección EXPLÍCITA del usuario
        # ----------------------------------------------------

        selected = (
            runtime
            .open_thread_for_selection(
                77,
                wait_timeout=1,
                routing_timeout=9,
            )
        )

        self.assertTrue(
            selected[
                "routing"
            ][
                "opened"
            ]
        )

        self.assertTrue(
            selected[
                "routing"
            ][
                "selection_light"
            ]
        )

        self.assertFalse(
            selected[
                "routing"
            ][
                "send_preverified"
            ]
        )

        self.assertEqual(
            connector.open_phone_calls,
            [
                (
                    "+34600999888",
                    "+34 600 999 888",
                    False,
                    9,
                )
            ],
        )

        # La lectura/selección sigue sin convertirse
        # en autorización fuerte para envío.
        self.assertIsNone(
            runtime._verified_send_thread_id
        )

        # ----------------------------------------------------
        # PASO 3 · WhatsApp ya está en el nuevo chat.
        # El watcher debe resolverlo por teléfono.
        # ----------------------------------------------------

        resolve_calls = []

        # El resolver productivo devuelve un ThreadOverview.
        # Su identificador público es thread_id.
        resolved_overview = SimpleNamespace(
            thread_id=77,
            external_address=(
                "+34600999888"
            ),
            external_display_name=(
                "+34 600 999 888"
            ),
        )

        def resolve(
            identity,
        ):
            resolve_calls.append(
                identity
            )

            if (
                identity
                == "+34 600 999 888"
            ):
                return {
                    "matched": True,
                    "ambiguous": False,
                    "match_basis":
                        "PHONE",
                    "thread":
                        resolved_overview,
                    "matches": [
                        resolved_overview,
                    ],
                    "identity":
                        identity,
                }

            return {
                "matched": False,
                "ambiguous": False,
                "match_basis": None,
                "thread": None,
                "matches": [],
                "identity":
                    identity,
            }

        service.resolve_whatsapp_thread_by_identity = (
            resolve
        )

        service.latest_provider_message_id = (
            None
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
                    "scanned": 1,
                    "created": 1,
                    "reused": 0,
                    "status_advanced": 0,
                    "skipped": 0,
                    "errors": 0,
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
                sync_open_chat_messages=(
                    sync
                )
            )
        )

        second = (
            runtime
            .observe_and_sync_active_chat(
                wait_timeout=1,
                sync_limit=200,
            )
        )

        self.assertEqual(
            second[
                "change_type"
            ],
            "CHAT_CHANGED",
        )

        self.assertEqual(
            resolve_calls,
            [
                "+34 600 999 888",
            ],
        )

        self.assertEqual(
            second[
                "resolution"
            ][
                "match_basis"
            ],
            "PHONE",
        )

        self.assertEqual(
            second[
                "resolution"
            ][
                "thread"
            ].thread_id,
            77,
        )

        self.assertEqual(
            len(
                sync_calls
            ),
            1,
        )

        sync_call = (
            sync_calls[0]
        )

        self.assertEqual(
            sync_call[
                "thread_id"
            ],
            77,
        )

        self.assertEqual(
            sync_call[
                "expected_active_identity"
            ],
            "+34 600 999 888",
        )

        self.assertEqual(
            sync_call[
                "expected_last_provider_message_id"
            ],
            "A7-SIM-1",
        )

        self.assertIsNone(
            sync_call[
                "after_provider_message_id"
            ]
        )

        self.assertFalse(
            second[
                "sync"
            ][
                "aborted"
            ]
        )

        # Solo existe una navegación y ocurrió DESPUÉS
        # de la selección explícita.
        self.assertEqual(
            len(
                connector.open_phone_calls
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
