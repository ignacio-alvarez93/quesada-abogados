import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.communications.call_followups import (
    CALL_FOLLOW_UP_IN_PROGRESS,
    CALL_FOLLOW_UP_PENDING,
    CALL_FOLLOW_UP_RESOLVED,
)
from backend.communications.calls import (
    CALL_STATUS_ANSWERED,
    CALL_STATUS_DIALING,
    CALL_STATUS_ENDED,
    CALL_STATUS_MISSED,
    CALL_STATUS_RINGING,
    InvalidCallTransition,
)
from backend.communications.models import (
    CHANNEL_PHONE,
    CHANNEL_WHATSAPP,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_call_service import (
    CommunicationCallService,
)


class CommunicationCallServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "call_service.db"
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

    def test_create_unknown_inbound_call(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600123001",
                display_name_snapshot=(
                    "Número no identificado"
                ),
                provider="MOBILE_LINK",
            )
        )

        self.assertIsNotNone(
            call.id
        )

        self.assertEqual(
            call.direction,
            DIRECTION_INBOUND,
        )

        self.assertEqual(
            call.channel,
            CHANNEL_PHONE,
        )

        self.assertIsNone(
            call.client_id
        )

        self.assertIsNone(
            call.expedient_id
        )

    def test_create_linked_outbound_call(
        self,
    ):
        call = (
            self.service
            .create_outbound_call(
                channel=CHANNEL_WHATSAPP,
                phone_number="+34600123002",
                client_id=10,
                expedient_id=20,
                reason_code=(
                    "EXPEDIENT_STATUS"
                ),
                provider=(
                    "WHATSAPP_WEB"
                ),
            )
        )

        self.assertEqual(
            call.direction,
            DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            call.client_id,
            10,
        )

        self.assertEqual(
            call.expedient_id,
            20,
        )

        self.assertEqual(
            call.reason_code,
            "EXPEDIENT_STATUS",
        )

    def test_inbound_missed_call_creates_pending_follow_up(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600123003",
            )
        )

        ringing = (
            self.service
            .apply_call_event(
                call.id,
                status=CALL_STATUS_RINGING,
                event_at=(
                    "2026-08-14T16:00:00+02:00"
                ),
            )
        )

        missed = (
            self.service
            .apply_call_event(
                ringing.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T16:00:15+02:00"
                ),
            )
        )

        self.assertEqual(
            missed.status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            missed.talk_duration_seconds,
            0,
        )

        self.assertEqual(
            missed.total_duration_seconds,
            15,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                missed.id
            )
        )

        self.assertIsNotNone(
            follow_up
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_PENDING,
        )

    def test_duplicate_missed_event_is_idempotent(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600123004",
            )
        )

        self.service.apply_call_event(
            call.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T16:10:00+02:00"
            ),
        )

        first = (
            self.service
            .apply_call_event(
                call.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T16:10:10+02:00"
                ),
            )
        )

        first_follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                call.id
            )
        )

        repeated = (
            self.service
            .apply_call_event(
                call.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T16:10:10+02:00"
                ),
            )
        )

        repeated_follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                call.id
            )
        )

        self.assertEqual(
            repeated.status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            first.id,
            repeated.id,
        )

        self.assertEqual(
            first_follow_up.id,
            repeated_follow_up.id,
        )

    def test_outbound_unanswered_call_does_not_create_follow_up(
        self,
    ):
        call = (
            self.service
            .create_outbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600123005",
            )
        )

        self.service.apply_call_event(
            call.id,
            status=CALL_STATUS_DIALING,
            event_at=(
                "2026-08-14T16:20:00+02:00"
            ),
        )

        missed = (
            self.service
            .apply_call_event(
                call.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T16:20:20+02:00"
                ),
            )
        )

        self.assertEqual(
            missed.status,
            CALL_STATUS_MISSED,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                missed.id
            )
        )

        self.assertIsNone(
            follow_up
        )

    def test_answered_inbound_call_does_not_create_follow_up(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600123006",
            )
        )

        self.service.apply_call_event(
            call.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T16:30:00+02:00"
            ),
        )

        self.service.apply_call_event(
            call.id,
            status=CALL_STATUS_ANSWERED,
            event_at=(
                "2026-08-14T16:30:05+02:00"
            ),
        )

        ended = (
            self.service
            .apply_call_event(
                call.id,
                status=CALL_STATUS_ENDED,
                event_at=(
                    "2026-08-14T16:32:05+02:00"
                ),
            )
        )

        self.assertEqual(
            ended.talk_duration_seconds,
            120,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                ended.id
            )
        )

        self.assertIsNone(
            follow_up
        )

    def test_invalid_transition_is_rejected_before_persistence(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600123007",
            )
        )

        with self.assertRaises(
            InvalidCallTransition
        ):
            self.service.apply_call_event(
                call.id,
                status=CALL_STATUS_ENDED,
                event_at=(
                    "2026-08-14T16:40:00+02:00"
                ),
            )

        stored = (
            self.service
            .get_call(
                call.id
            )
        )

        self.assertEqual(
            stored.status,
            "CREATED",
        )

    def test_unknown_call_event_is_rejected(
        self,
    ):
        with self.assertRaisesRegex(
            ValueError,
            "no encontrada",
        ):
            self.service.apply_call_event(
                999999,
                status=CALL_STATUS_RINGING,
                event_at=(
                    "2026-08-14T16:50:00+02:00"
                ),
            )

    def test_pending_inventory_is_exposed_by_service(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600123008",
            )
        )

        self.service.apply_call_event(
            call.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T17:00:00+02:00"
            ),
        )

        self.service.apply_call_event(
            call.id,
            status=CALL_STATUS_MISSED,
            event_at=(
                "2026-08-14T17:00:07+02:00"
            ),
        )

        inventory = (
            self.service
            .list_pending_follow_ups()
        )

        self.assertEqual(
            len(inventory),
            1,
        )

        self.assertEqual(
            inventory[0].source_call_id,
            call.id,
        )

        self.assertEqual(
            inventory[0].follow_up_status,
            CALL_FOLLOW_UP_PENDING,
        )


    def test_callback_inherits_source_context(
        self,
    ):
        source = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600610001",
                client_id=10,
                expedient_id=20,
                display_name_snapshot=(
                    "CLIENTE TEST"
                ),
                reason_code=(
                    "EXPEDIENT_STATUS"
                ),
                provider="MOBILE_LINK",
            )
        )

        self.service.apply_call_event(
            source.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T18:00:00+02:00"
            ),
        )

        source = (
            self.service
            .apply_call_event(
                source.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T18:00:10+02:00"
                ),
            )
        )

        callback = (
            self.service
            .create_callback_call(
                source.id,
                created_by="TEST",
            )
        )

        self.assertEqual(
            callback.direction,
            DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            callback.channel,
            source.channel,
        )

        self.assertEqual(
            callback.phone_number,
            source.phone_number,
        )

        self.assertEqual(
            callback.client_id,
            10,
        )

        self.assertEqual(
            callback.expedient_id,
            20,
        )

        self.assertEqual(
            callback.display_name_snapshot,
            "CLIENTE TEST",
        )

        self.assertEqual(
            callback.reason_code,
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            callback.provider,
            "MOBILE_LINK",
        )

        relation = (
            self.repository
            .get_call_callback_by_callback_call(
                callback.id
            )
        )

        self.assertIsNotNone(
            relation
        )

        self.assertEqual(
            relation.source_call_id,
            source.id,
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

    def test_second_callback_is_blocked_while_follow_up_in_progress(
        self,
    ):
        source = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600610002",
            )
        )

        self.service.apply_call_event(
            source.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T18:10:00+02:00"
            ),
        )

        source = (
            self.service
            .apply_call_event(
                source.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T18:10:10+02:00"
                ),
            )
        )

        self.service.create_callback_call(
            source.id
        )

        with self.assertRaisesRegex(
            ValueError,
            "ya está en curso",
        ):
            self.service.create_callback_call(
                source.id
            )

    def test_unsuccessful_callback_returns_follow_up_to_pending(
        self,
    ):
        source = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600610003",
            )
        )

        self.service.apply_call_event(
            source.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T18:20:00+02:00"
            ),
        )

        source = (
            self.service
            .apply_call_event(
                source.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T18:20:08+02:00"
                ),
            )
        )

        callback = (
            self.service
            .create_callback_call(
                source.id
            )
        )

        self.service.apply_call_event(
            callback.id,
            status=CALL_STATUS_DIALING,
            event_at=(
                "2026-08-14T18:25:00+02:00"
            ),
        )

        self.service.apply_call_event(
            callback.id,
            status=CALL_STATUS_MISSED,
            event_at=(
                "2026-08-14T18:25:20+02:00"
            ),
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_PENDING,
        )

        callbacks = (
            self.service
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
            callback.id,
        )

    def test_answered_callback_remains_in_progress_until_resolved(
        self,
    ):
        source = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600610004",
            )
        )

        self.service.apply_call_event(
            source.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T18:30:00+02:00"
            ),
        )

        source = (
            self.service
            .apply_call_event(
                source.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T18:30:10+02:00"
                ),
            )
        )

        callback = (
            self.service
            .create_callback_call(
                source.id
            )
        )

        self.service.apply_call_event(
            callback.id,
            status=CALL_STATUS_DIALING,
            event_at=(
                "2026-08-14T18:35:00+02:00"
            ),
        )

        self.service.apply_call_event(
            callback.id,
            status=CALL_STATUS_ANSWERED,
            event_at=(
                "2026-08-14T18:35:05+02:00"
            ),
        )

        self.service.apply_call_event(
            callback.id,
            status=CALL_STATUS_ENDED,
            event_at=(
                "2026-08-14T18:37:05+02:00"
            ),
        )

        follow_up = (
            self.repository
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            follow_up.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

    def test_follow_up_can_be_resolved_explicitly(
        self,
    ):
        source = (
            self.service
            .create_inbound_call(
                channel=CHANNEL_PHONE,
                phone_number="+34600610005",
            )
        )

        self.service.apply_call_event(
            source.id,
            status=CALL_STATUS_RINGING,
            event_at=(
                "2026-08-14T18:40:00+02:00"
            ),
        )

        source = (
            self.service
            .apply_call_event(
                source.id,
                status=CALL_STATUS_MISSED,
                event_at=(
                    "2026-08-14T18:40:10+02:00"
                ),
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

        resolved = (
            self.service
            .resolve_follow_up(
                follow_up.id,
                resolved_at=(
                    "2026-08-14T18:45:00+02:00"
                ),
            )
        )

        self.assertEqual(
            resolved.status,
            CALL_FOLLOW_UP_RESOLVED,
        )

        self.assertEqual(
            resolved.resolved_at,
            "2026-08-14T18:45:00+02:00",
        )

        inventory = (
            self.service
            .list_pending_follow_ups()
        )

        self.assertNotIn(
            source.id,
            {
                item.source_call_id
                for item in inventory
            },
        )

        with self.assertRaisesRegex(
            ValueError,
            "ya está resuelto",
        ):
            self.service.create_callback_call(
                source.id
            )

        callbacks = (
            self.service
            .list_callback_calls(
                source.id
            )
        )

        self.assertEqual(
            [
                item.id
                for item in callbacks
            ],
            [
                callback.id,
            ],
        )


if __name__ == "__main__":
    unittest.main()
