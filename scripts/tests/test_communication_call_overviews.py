import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.communications.calls import (
    CALL_DIRECTION_INBOUND,
    CALL_DIRECTION_OUTBOUND,
    CALL_STATUS_DIALING,
    CALL_STATUS_MISSED,
    CALL_STATUS_RINGING,
    CommunicationCallOverview,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_call_service import (
    CommunicationCallService,
)


class CommunicationCallOverviewTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.addCleanup(
            self.temp_dir.cleanup
        )

        self.db_path = (
            Path(
                self.temp_dir.name
            )
            / "call_overview.db"
        )

        conn = sqlite3.connect(
            str(
                self.db_path
            )
        )

        try:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    primer_apellido TEXT,
                    segundo_apellido TEXT
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

        self.repository.ensure_schema()

        self.service = (
            CommunicationCallService(
                repository=(
                    self.repository
                )
            )
        )

    def _create_missed_call(
        self,
    ):
        call = (
            self.service
            .create_inbound_call(
                channel="WHATSAPP",
                phone_number=(
                    "+34600111222"
                ),
                display_name_snapshot=(
                    "Cliente prueba"
                ),
                reason_code=(
                    "CLIENT_REQUEST"
                ),
                notes=(
                    "Nota de prueba"
                ),
            )
        )

        self.service.apply_call_event(
            call.id,
            status=(
                CALL_STATUS_RINGING
            ),
            event_at=(
                "2026-08-16T10:00:00+02:00"
            ),
        )

        return (
            self.service
            .apply_call_event(
                call.id,
                status=(
                    CALL_STATUS_MISSED
                ),
                event_at=(
                    "2026-08-16T10:00:10+02:00"
                ),
            )
        )

    def _create_dialing_call(
        self,
    ):
        call = (
            self.service
            .create_outbound_call(
                channel="WHATSAPP",
                phone_number=(
                    "+34600999888"
                ),
                display_name_snapshot=(
                    "Consulta saliente"
                ),
                reason_code=(
                    "LEGAL_CONSULTATION"
                ),
            )
        )

        return (
            self.service
            .apply_call_event(
                call.id,
                status=(
                    CALL_STATUS_DIALING
                ),
                event_at=(
                    "2026-08-16T11:00:00+02:00"
                ),
            )
        )

    def test_list_overviews_returns_domain_projection(
        self,
    ):
        missed = (
            self._create_missed_call()
        )

        dialing = (
            self._create_dialing_call()
        )

        items = (
            self.service
            .list_call_overviews(
                channel="WHATSAPP",
                limit=100,
            )
        )

        self.assertEqual(
            [
                item.call_id
                for item in items
            ],
            [
                dialing.id,
                missed.id,
            ],
        )

        self.assertTrue(
            all(
                isinstance(
                    item,
                    CommunicationCallOverview,
                )
                for item in items
            )
        )

    def test_missed_call_exposes_pending_follow_up(
        self,
    ):
        missed = (
            self._create_missed_call()
        )

        items = (
            self.service
            .list_call_overviews(
                status="MISSED",
            )
        )

        self.assertEqual(
            len(
                items
            ),
            1,
        )

        item = items[0]

        self.assertEqual(
            item.call_id,
            missed.id,
        )

        self.assertEqual(
            item.direction,
            CALL_DIRECTION_INBOUND,
        )

        self.assertEqual(
            item.status,
            CALL_STATUS_MISSED,
        )

        self.assertIsNotNone(
            item.follow_up_id
        )

        self.assertEqual(
            item.follow_up_status,
            "PENDING",
        )

        self.assertEqual(
            item.callback_count,
            0,
        )

        self.assertEqual(
            item.reason_label,
            "Solicitud del cliente",
        )

        self.assertEqual(
            item.talk_duration_seconds,
            0,
        )

    def test_active_call_does_not_invent_final_duration(
        self,
    ):
        dialing = (
            self._create_dialing_call()
        )

        items = (
            self.service
            .list_call_overviews(
                direction="OUTBOUND",
            )
        )

        self.assertEqual(
            len(
                items
            ),
            1,
        )

        item = items[0]

        self.assertEqual(
            item.call_id,
            dialing.id,
        )

        self.assertEqual(
            item.direction,
            CALL_DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            item.status,
            CALL_STATUS_DIALING,
        )

        self.assertEqual(
            item.reason_label,
            "Consulta jurídica",
        )

        self.assertIsNone(
            item.talk_duration_seconds
        )

        self.assertIsNone(
            item.total_duration_seconds
        )

    def test_linked_client_name_has_priority_over_provider_alias(
        self,
    ):
        conn = sqlite3.connect(
            str(
                self.db_path
            )
        )

        try:
            conn.execute(
                """
                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    30,
                    "JEAN PIERRY",
                    "MUÑOZ",
                    "VALDEZ",
                ),
            )

            conn.commit()

        finally:
            conn.close()

        call = (
            self.service
            .create_inbound_call(
                channel="WHATSAPP",
                phone_number=(
                    "+34639156371"
                ),
                client_id=30,
                display_name_snapshot=(
                    "Mama"
                ),
            )
        )

        items = (
            self.service
            .list_call_overviews(
                search="JEAN PIERRY",
            )
        )

        self.assertEqual(
            len(
                items
            ),
            1,
        )

        item = items[0]

        self.assertEqual(
            item.call_id,
            call.id,
        )

        self.assertEqual(
            item.client_id,
            30,
        )

        self.assertEqual(
            item.display_name,
            "JEAN PIERRY MUÑOZ VALDEZ",
        )

        self.assertNotEqual(
            item.display_name,
            "Mama",
        )


    def test_search_filters_without_frontend_sql(
        self,
    ):
        self._create_missed_call()
        self._create_dialing_call()

        by_name = (
            self.service
            .list_call_overviews(
                search="cliente prueba",
            )
        )

        self.assertEqual(
            len(
                by_name
            ),
            1,
        )

        self.assertEqual(
            by_name[
                0
            ].phone_number,
            "+34600111222",
        )

        by_phone = (
            self.service
            .list_call_overviews(
                search="600999888",
            )
        )

        self.assertEqual(
            len(
                by_phone
            ),
            1,
        )

        self.assertEqual(
            by_phone[
                0
            ].status,
            CALL_STATUS_DIALING,
        )


if __name__ == "__main__":
    unittest.main()
