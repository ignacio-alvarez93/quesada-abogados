import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.communications.call_snapshots import (
    ProviderCallSnapshot,
)
from backend.communications.calls import (
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


if __name__ == "__main__":
    unittest.main()
