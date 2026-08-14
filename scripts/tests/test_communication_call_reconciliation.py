import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.communications.call_followups import (
    CALL_FOLLOW_UP_PENDING,
)
from backend.communications.call_snapshots import (
    ProviderCallReconciliationConflict,
    ProviderCallSnapshot,
)
from backend.communications.calls import (
    CALL_STATUS_ANSWERED,
    CALL_STATUS_ENDED,
    CALL_STATUS_MISSED,
    CALL_STATUS_RINGING,
)
from backend.communications.models import (
    CHANNEL_PHONE,
    DIRECTION_INBOUND,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_call_service import (
    CommunicationCallService,
)


class CommunicationCallReconciliationTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "call_reconciliation.db"
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

                INSERT INTO clientes (
                    id,
                    nombre
                )
                VALUES (
                    10,
                    'CLIENTE TEST'
                );

                INSERT INTO expedientes (
                    id,
                    cliente_id
                )
                VALUES (
                    20,
                    10
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

    def test_historical_missed_call_creates_call_and_follow_up(
        self,
    ):
        call = (
            self.service
            .reconcile_provider_call(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="history-001",
                    provider_call_id="raw-history-001",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600830001",
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T10:00:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T10:00:14+02:00"
                    ),
                )
            )
        )

        self.assertEqual(
            call.status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            call.ring_duration_seconds,
            14,
        )

        self.assertEqual(
            call.talk_duration_seconds,
            0,
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
            CALL_FOLLOW_UP_PENDING,
        )

    def test_realtime_ringing_reconciles_to_same_missed_call(
        self,
    ):
        created = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600830002",
                client_id=10,
                expedient_id=20,
                display_name_snapshot="CRM NAME",
                reason_code="EXPEDIENT_STATUS",
                provider="MOBILE_LINK",
                external_call_key="history-002",
            )
        )

        ringing = (
            self.service
            .apply_call_event(
                created.id,
                status=CALL_STATUS_RINGING,
                event_at=(
                    "2026-08-14T11:00:00+02:00"
                ),
            )
        )

        reconciled = (
            self.service
            .reconcile_provider_call(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="history-002",
                    provider_call_id="raw-history-002",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="600830002",
                    display_name_snapshot="PROVIDER NAME",
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T11:00:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T11:00:11+02:00"
                    ),
                    metadata={
                        "source":
                            "provider_history",
                    },
                )
            )
        )

        self.assertEqual(
            reconciled.id,
            ringing.id,
        )

        self.assertEqual(
            reconciled.status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            reconciled.client_id,
            10,
        )

        self.assertEqual(
            reconciled.expedient_id,
            20,
        )

        self.assertEqual(
            reconciled.reason_code,
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            reconciled.display_name_snapshot,
            "CRM NAME",
        )

        self.assertEqual(
            reconciled.provider_call_id,
            "raw-history-002",
        )

        self.assertEqual(
            reconciled.total_duration_seconds,
            11,
        )

        self.assertEqual(
            reconciled.metadata["source"],
            "provider_history",
        )

    def test_repeated_historical_snapshot_is_idempotent(
        self,
    ):
        snapshot = ProviderCallSnapshot(
            provider="MOBILE_LINK",
            external_call_key="history-003",
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600830003",
            status=CALL_STATUS_MISSED,
            ringing_at=(
                "2026-08-14T12:00:00+02:00"
            ),
            ended_at=(
                "2026-08-14T12:00:08+02:00"
            ),
        )

        first = (
            self.service
            .reconcile_provider_call(
                snapshot
            )
        )

        first_follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                first.id
            )
        )

        second = (
            self.service
            .reconcile_provider_call(
                snapshot
            )
        )

        second_follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                second.id
            )
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        self.assertEqual(
            first_follow_up.id,
            second_follow_up.id,
        )

    def test_historical_answered_call_does_not_create_follow_up(
        self,
    ):
        call = (
            self.service
            .reconcile_provider_call(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="history-004",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600830004",
                    status=CALL_STATUS_ENDED,
                    ringing_at=(
                        "2026-08-14T13:00:00+02:00"
                    ),
                    answered_at=(
                        "2026-08-14T13:00:04+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T13:02:04+02:00"
                    ),
                )
            )
        )

        self.assertEqual(
            call.status,
            CALL_STATUS_ENDED,
        )

        self.assertEqual(
            call.talk_duration_seconds,
            120,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                call.id
            )
        )

        self.assertIsNone(
            follow_up
        )

    def test_terminal_conflict_is_rejected_without_mutation(
        self,
    ):
        missed = (
            self.service
            .reconcile_provider_call(
                ProviderCallSnapshot(
                    provider="MOBILE_LINK",
                    external_call_key="history-005",
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600830005",
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T14:00:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T14:00:10+02:00"
                    ),
                )
            )
        )

        with self.assertRaises(
            ProviderCallReconciliationConflict
        ):
            (
                self.service
                .reconcile_provider_call(
                    ProviderCallSnapshot(
                        provider="MOBILE_LINK",
                        external_call_key="history-005",
                        channel=CHANNEL_PHONE,
                        direction=DIRECTION_INBOUND,
                        phone_number="+34600830005",
                        status=CALL_STATUS_ENDED,
                    )
                )
            )

        stored = (
            self.service.get_call(
                missed.id
            )
        )

        self.assertEqual(
            stored.status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            stored.ended_at,
            "2026-08-14T14:00:10+02:00",
        )

    def test_stale_snapshot_cannot_regress_answered_call(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600830006",
                provider="MOBILE_LINK",
                external_call_key="history-006",
            )
        )

        self.service.apply_call_event(
            call.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T15:00:00+02:00"
            ),
        )

        answered = (
            self.service
            .apply_call_event(
                call.id,
                status=CALL_STATUS_ANSWERED,
                event_at=(
                    "2026-08-14T15:00:05+02:00"
                ),
            )
        )

        with self.assertRaises(
            ProviderCallReconciliationConflict
        ):
            (
                self.service
                .reconcile_provider_call(
                    ProviderCallSnapshot(
                        provider="MOBILE_LINK",
                        external_call_key="history-006",
                        channel=CHANNEL_PHONE,
                        direction=DIRECTION_INBOUND,
                        phone_number="+34600830006",
                        status=CALL_STATUS_RINGING,
                        ringing_at=(
                            "2026-08-14T15:00:00+02:00"
                        ),
                    )
                )
            )

        stored = (
            self.service.get_call(
                answered.id
            )
        )

        self.assertEqual(
            stored.status,
            CALL_STATUS_ANSWERED,
        )


if __name__ == "__main__":
    unittest.main()
