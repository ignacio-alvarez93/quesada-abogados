import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from backend.communications.call_followups import (
    CALL_FOLLOW_UP_IN_PROGRESS,
    CALL_FOLLOW_UP_PENDING,
    CALL_FOLLOW_UP_RESOLVED,
    transition_call_follow_up,
)
from backend.communications.call_snapshots import (
    ProviderCallSnapshot,
)
from backend.communications.calls import (
    CALL_STATUS_BUSY,
    CALL_STATUS_DIALING,
    CALL_STATUS_MISSED,
    CALL_STATUS_RINGING,
)
from backend.communications.models import (
    CHANNEL_PHONE,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_call_service import (
    CommunicationCallService,
)


class CommunicationCallTransactionTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "call_transactions.db"
        )

        conn = sqlite3.connect(
            str(self.db_path)
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

        self.repository = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        self.service = (
            CommunicationCallService(
                repository=self.repository
            )
        )

        self.service.ensure_schema()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_ringing_inbound(
        self,
        *,
        key,
        phone,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number=phone,
                provider="MOBILE_LINK",
                external_call_key=key,
            )
        )

        return (
            self.service
            .apply_call_event(
                call.id,
                status=CALL_STATUS_RINGING,
                event_at=(
                    "2026-08-14T18:00:00+02:00"
                ),
            )
        )

    def test_live_missed_rolls_back_state_when_follow_up_fails(
        self,
    ):
        ringing = (
            self._create_ringing_inbound(
                key="atomic-live-001",
                phone="+34600910001",
            )
        )

        with patch.object(
            self.repository,
            (
                "_get_or_create_call_"
                "follow_up_in_connection"
            ),
            side_effect=RuntimeError(
                "Fallo follow-up simulado"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Fallo follow-up simulado",
            ):
                (
                    self.service
                    .apply_call_event(
                        ringing.id,
                        status=CALL_STATUS_MISSED,
                        event_at=(
                            "2026-08-14T18:00:10+02:00"
                        ),
                    )
                )

        stored = self.service.get_call(
            ringing.id
        )

        self.assertEqual(
            stored.status,
            CALL_STATUS_RINGING,
        )

        self.assertIsNone(
            stored.ended_at
        )

        self.assertIsNone(
            self.repository
            .get_call_follow_up_by_source_call(
                ringing.id
            )
        )

    def test_new_historical_missed_rolls_back_call_when_follow_up_fails(
        self,
    ):
        snapshot = ProviderCallSnapshot(
            provider="MOBILE_LINK",
            external_call_key=(
                "atomic-history-001"
            ),
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600910002",
            status=CALL_STATUS_MISSED,
            ringing_at=(
                "2026-08-14T18:10:00+02:00"
            ),
            ended_at=(
                "2026-08-14T18:10:08+02:00"
            ),
        )

        with patch.object(
            self.repository,
            (
                "_get_or_create_call_"
                "follow_up_in_connection"
            ),
            side_effect=RuntimeError(
                "Fallo follow-up simulado"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Fallo follow-up simulado",
            ):
                (
                    self.service
                    .reconcile_provider_call(
                        snapshot
                    )
                )

        stored = (
            self.repository
            .get_call_by_provider_identity(
                provider="MOBILE_LINK",
                external_call_key=(
                    "atomic-history-001"
                ),
            )
        )

        self.assertIsNone(
            stored
        )

    def test_existing_historical_missed_rolls_back_reconciliation(
        self,
    ):
        ringing = (
            self._create_ringing_inbound(
                key="atomic-history-002",
                phone="+34600910003",
            )
        )

        snapshot = ProviderCallSnapshot(
            provider="MOBILE_LINK",
            external_call_key=(
                "atomic-history-002"
            ),
            provider_call_id="raw-atomic-002",
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600910003",
            status=CALL_STATUS_MISSED,
            ringing_at=(
                "2026-08-14T18:00:00+02:00"
            ),
            ended_at=(
                "2026-08-14T18:00:09+02:00"
            ),
        )

        with patch.object(
            self.repository,
            (
                "_get_or_create_call_"
                "follow_up_in_connection"
            ),
            side_effect=RuntimeError(
                "Fallo follow-up simulado"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Fallo follow-up simulado",
            ):
                (
                    self.service
                    .reconcile_provider_call(
                        snapshot
                    )
                )

        stored = self.service.get_call(
            ringing.id
        )

        self.assertEqual(
            stored.status,
            CALL_STATUS_RINGING,
        )

        self.assertIsNone(
            stored.provider_call_id
        )

        self.assertIsNone(
            stored.ended_at
        )

        self.assertIsNone(
            self.repository
            .get_call_follow_up_by_source_call(
                ringing.id
            )
        )

    def test_historical_missed_successfully_commits_call_and_follow_up(
        self,
    ):
        call = (
            self.service
            .reconcile_provider_call(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key=(
                        "atomic-history-003"
                    ),
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600910004",
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T18:20:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T18:20:07+02:00"
                    ),
                )
            )
        )

        self.assertEqual(
            call.status,
            CALL_STATUS_MISSED,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                call.id
            )
        )

        self.assertIsNotNone(
            follow_up
        )

        self.assertEqual(
            follow_up.status,
            "PENDING",
        )


    def _create_missed_source(
        self,
        *,
        key,
        phone,
    ):
        ringing = (
            self._create_ringing_inbound(
                key=key,
                phone=phone,
            )
        )

        return (
            self.service
            .apply_call_event(
                ringing.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T18:00:10+02:00"
                ),
            )
        )

    def _count_outbound_calls(
        self,
    ):
        conn = sqlite3.connect(
            str(self.db_path)
        )

        try:
            return int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM communication_calls
                    WHERE direction = 'OUTBOUND'
                    """
                ).fetchone()[0]
            )

        finally:
            conn.close()

    def test_callback_workflow_commits_claim_call_and_relation(
        self,
    ):
        source = (
            self._create_missed_source(
                key="atomic-callback-001",
                phone="+34600920001",
            )
        )

        callback = (
            self.service
            .create_callback_call(
                source.id
            )
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        callbacks = (
            self.repository
            .list_callback_calls(
                source.id
            )
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

        self.assertEqual(
            len(callbacks),
            1,
        )

        self.assertEqual(
            callbacks[0].id,
            callback.id,
        )

        self.assertEqual(
            self._count_outbound_calls(),
            1,
        )

    def test_callback_workflow_rolls_back_claim_and_call_when_link_fails(
        self,
    ):
        source = (
            self._create_missed_source(
                key="atomic-callback-002",
                phone="+34600920002",
            )
        )

        with patch.object(
            self.repository,
            "_link_callback_call_in_connection",
            side_effect=RuntimeError(
                "Fallo vínculo simulado"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Fallo vínculo simulado",
            ):
                (
                    self.service
                    .create_callback_call(
                        source.id
                    )
                )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        callbacks = (
            self.repository
            .list_callback_calls(
                source.id
            )
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_PENDING,
        )

        self.assertEqual(
            callbacks,
            [],
        )

        self.assertEqual(
            self._count_outbound_calls(),
            0,
        )

    def test_second_callback_cannot_consume_in_progress_follow_up(
        self,
    ):
        source = (
            self._create_missed_source(
                key="atomic-callback-003",
                phone="+34600920003",
            )
        )

        first = (
            self.service
            .create_callback_call(
                source.id
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "ya está en curso",
        ):
            (
                self.service
                .create_callback_call(
                    source.id
                )
            )

        callbacks = (
            self.repository
            .list_callback_calls(
                source.id
            )
        )

        self.assertEqual(
            len(callbacks),
            1,
        )

        self.assertEqual(
            callbacks[0].id,
            first.id,
        )

        self.assertEqual(
            self._count_outbound_calls(),
            1,
        )

    def test_callback_claim_is_atomic_between_two_workers(
        self,
    ):
        source = (
            self._create_missed_source(
                key="atomic-callback-004",
                phone="+34600920004",
            )
        )

        repo_a = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        repo_b = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        repo_a.ensure_schema()
        repo_b.ensure_schema()

        service_a = CommunicationCallService(
            repository=repo_a
        )

        service_b = CommunicationCallService(
            repository=repo_b
        )

        barrier = Barrier(
            2
        )

        original_a = (
            repo_a.create_callback_workflow
        )

        original_b = (
            repo_b.create_callback_workflow
        )

        def delayed_a(
            *args,
            **kwargs,
        ):
            barrier.wait(
                timeout=10
            )

            return original_a(
                *args,
                **kwargs,
            )

        def delayed_b(
            *args,
            **kwargs,
        ):
            barrier.wait(
                timeout=10
            )

            return original_b(
                *args,
                **kwargs,
            )

        repo_a.create_callback_workflow = (
            delayed_a
        )

        repo_b.create_callback_workflow = (
            delayed_b
        )

        def run_worker(
            service,
        ):
            try:
                callback = (
                    service
                    .create_callback_call(
                        source.id
                    )
                )

                return (
                    "CREATED",
                    callback.id,
                )

            except Exception as exc:
                return (
                    "REJECTED",
                    type(exc).__name__,
                    str(exc),
                )

        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:
            future_a = executor.submit(
                run_worker,
                service_a,
            )

            future_b = executor.submit(
                run_worker,
                service_b,
            )

            results = [
                future_a.result(
                    timeout=20
                ),
                future_b.result(
                    timeout=20
                ),
            ]

        created = [
            result
            for result in results
            if result[0]
            == "CREATED"
        ]

        rejected = [
            result
            for result in results
            if result[0]
            == "REJECTED"
        ]

        self.assertEqual(
            len(created),
            1,
            results,
        )

        self.assertEqual(
            len(rejected),
            1,
            results,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        callbacks = (
            self.repository
            .list_callback_calls(
                source.id
            )
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

        self.assertEqual(
            len(callbacks),
            1,
        )

        self.assertEqual(
            self._count_outbound_calls(),
            1,
        )


    def _create_dialing_callback(
        self,
        *,
        key,
        phone,
    ):
        source = (
            self._create_missed_source(
                key=key,
                phone=phone,
            )
        )

        callback = (
            self.service
            .create_callback_call(
                source.id
            )
        )

        callback = (
            self.service
            .apply_call_event(
                callback.id,
                status=CALL_STATUS_DIALING,
                event_at=(
                    "2026-08-14T18:30:00+02:00"
                ),
            )
        )

        return (
            source,
            callback,
        )

    def test_callback_terminal_requeues_follow_up_atomically(
        self,
    ):
        (
            source,
            callback,
        ) = (
            self._create_dialing_callback(
                key="atomic-terminal-001",
                phone="+34600930001",
            )
        )

        terminal = (
            self.service
            .apply_call_event(
                callback.id,
                status=CALL_STATUS_BUSY,
                event_at=(
                    "2026-08-14T18:30:06+02:00"
                ),
            )
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            terminal.status,
            CALL_STATUS_BUSY,
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_PENDING,
        )

    def test_callback_terminal_requeue_rolls_back_call_when_follow_up_fails(
        self,
    ):
        (
            source,
            callback,
        ) = (
            self._create_dialing_callback(
                key="atomic-terminal-002",
                phone="+34600930002",
            )
        )

        with patch.object(
            self.repository,
            "_try_update_call_follow_up_in_connection",
            side_effect=RuntimeError(
                "Fallo requeue simulado"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Fallo requeue simulado",
            ):
                (
                    self.service
                    .apply_call_event(
                        callback.id,
                        status=CALL_STATUS_BUSY,
                        event_at=(
                            "2026-08-14T18:30:07+02:00"
                        ),
                    )
                )

        stored = self.service.get_call(
            callback.id
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            stored.status,
            CALL_STATUS_DIALING,
        )

        self.assertIsNone(
            stored.ended_at
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

    def test_resolved_follow_up_is_never_reopened_by_terminal_callback(
        self,
    ):
        (
            source,
            callback,
        ) = (
            self._create_dialing_callback(
                key="atomic-terminal-003",
                phone="+34600930003",
            )
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        resolved = (
            self.service
            .resolve_follow_up(
                follow_up.id,
                resolved_at=(
                    "2026-08-14T18:30:03+02:00"
                ),
            )
        )

        terminal = (
            self.service
            .apply_call_event(
                callback.id,
                status=CALL_STATUS_BUSY,
                event_at=(
                    "2026-08-14T18:30:08+02:00"
                ),
            )
        )

        stored_follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            terminal.status,
            CALL_STATUS_BUSY,
        )

        self.assertEqual(
            resolved.status,
            CALL_FOLLOW_UP_RESOLVED,
        )

        self.assertEqual(
            stored_follow_up.status,
            CALL_FOLLOW_UP_RESOLVED,
        )

        self.assertEqual(
            stored_follow_up.resolved_at,
            "2026-08-14T18:30:03+02:00",
        )

    def _create_identified_callback_for_history(
        self,
        *,
        source_key,
        callback_key,
        phone,
    ):
        source = (
            self._create_missed_source(
                key=source_key,
                phone=phone,
            )
        )

        callback = (
            self.service
            .create_outbound_call(
                channel=CHANNEL_PHONE,
                phone_number=phone,
                provider="MOBILE_LINK",
                external_call_key=(
                    callback_key
                ),
            )
        )

        self.repository.link_callback_call(
            source_call_id=source.id,
            callback_call_id=callback.id,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        active = transition_call_follow_up(
            follow_up,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

        self.repository.update_call_follow_up(
            active
        )

        callback = (
            self.service
            .apply_call_event(
                callback.id,
                status=CALL_STATUS_DIALING,
                event_at=(
                    "2026-08-14T18:40:00+02:00"
                ),
            )
        )

        return (
            source,
            callback,
        )

    def test_historical_callback_terminal_requeues_atomically(
        self,
    ):
        (
            source,
            callback,
        ) = (
            self._create_identified_callback_for_history(
                source_key=(
                    "atomic-history-terminal-source-001"
                ),
                callback_key=(
                    "atomic-history-terminal-callback-001"
                ),
                phone="+34600930004",
            )
        )

        reconciled = (
            self.service
            .reconcile_provider_call(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key=(
                        "atomic-history-terminal-callback-001"
                    ),
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_OUTBOUND,
                    phone_number="+34600930004",
                    status=CALL_STATUS_BUSY,
                    dialed_at=(
                        "2026-08-14T18:40:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T18:40:05+02:00"
                    ),
                )
            )
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            reconciled.id,
            callback.id,
        )

        self.assertEqual(
            reconciled.status,
            CALL_STATUS_BUSY,
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_PENDING,
        )

    def test_historical_callback_terminal_rolls_back_when_requeue_fails(
        self,
    ):
        (
            source,
            callback,
        ) = (
            self._create_identified_callback_for_history(
                source_key=(
                    "atomic-history-terminal-source-002"
                ),
                callback_key=(
                    "atomic-history-terminal-callback-002"
                ),
                phone="+34600930005",
            )
        )

        snapshot = ProviderCallSnapshot(
            provider="MOBILE_LINK",
            external_call_key=(
                "atomic-history-terminal-callback-002"
            ),
            channel=CHANNEL_PHONE,
            direction=DIRECTION_OUTBOUND,
            phone_number="+34600930005",
            status=CALL_STATUS_BUSY,
            dialed_at=(
                "2026-08-14T18:40:00+02:00"
            ),
            ended_at=(
                "2026-08-14T18:40:06+02:00"
            ),
        )

        with patch.object(
            self.repository,
            "_try_update_call_follow_up_in_connection",
            side_effect=RuntimeError(
                "Fallo requeue histórico simulado"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Fallo requeue histórico simulado",
            ):
                (
                    self.service
                    .reconcile_provider_call(
                        snapshot
                    )
                )

        stored = self.service.get_call(
            callback.id
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            stored.status,
            CALL_STATUS_DIALING,
        )

        self.assertIsNone(
            stored.ended_at
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )


    def test_callback_terminal_preserves_resolved_when_resolution_wins_after_prepare(
        self,
    ):
        (
            source,
            callback,
        ) = (
            self._create_dialing_callback(
                key="atomic-terminal-race-001",
                phone="+34600930006",
            )
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        original = (
            self.repository
            .update_call_state_with_callback_requeue
        )

        resolver_repository = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        resolver_service = (
            CommunicationCallService(
                repository=resolver_repository
            )
        )

        def resolve_between_prepare_and_cas(
            call,
            *,
            follow_up,
            expected_follow_up_status,
        ):
            (
                resolver_service
                .resolve_follow_up(
                    follow_up.id,
                    resolved_at=(
                        "2026-08-14T18:35:03+02:00"
                    ),
                )
            )

            return original(
                call,
                follow_up=follow_up,
                expected_follow_up_status=(
                    expected_follow_up_status
                ),
            )

        with patch.object(
            self.repository,
            "update_call_state_with_callback_requeue",
            side_effect=(
                resolve_between_prepare_and_cas
            ),
        ):
            terminal = (
                self.service
                .apply_call_event(
                    callback.id,
                    status=CALL_STATUS_BUSY,
                    event_at=(
                        "2026-08-14T18:35:08+02:00"
                    ),
                )
            )

        stored_follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            terminal.status,
            CALL_STATUS_BUSY,
        )

        self.assertEqual(
            stored_follow_up.status,
            CALL_FOLLOW_UP_RESOLVED,
        )

        self.assertEqual(
            stored_follow_up.resolved_at,
            "2026-08-14T18:35:03+02:00",
        )


if __name__ == "__main__":
    unittest.main()
