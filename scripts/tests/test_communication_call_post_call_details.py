import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from backend.communications.calls import (
    CALL_STATUS_ANSWERED,
    CALL_STATUS_DIALING,
    CALL_STATUS_ENDED,
    CALL_STATUS_FAILED,
)
from backend.communications.models import (
    CHANNEL_PHONE,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_call_service import (
    CommunicationCallService,
)


class CommunicationCallPostCallDetailsTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(
                self.temp_dir.name
            )
            / "post_call.db"
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

        self.repo = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        self.repo.ensure_schema()

        self.service = (
            CommunicationCallService(
                repository=self.repo
            )
        )


    def tearDown(
        self,
    ):
        self.temp_dir.cleanup()


    def _ended_call(
        self,
    ):
        call = (
            self.service
            .create_outbound_call(
                channel=CHANNEL_PHONE,
                phone_number=(
                    "+34600123123"
                ),
                provider=(
                    "TEST_PHONE"
                ),
                external_call_key=(
                    "post-call-test-1"
                ),
            )
        )

        call = (
            self.service
            .apply_call_event(
                call.id,
                status=(
                    CALL_STATUS_DIALING
                ),
                event_at=(
                    "2026-08-16T17:00:00+02:00"
                ),
            )
        )

        call = (
            self.service
            .apply_call_event(
                call.id,
                status=(
                    CALL_STATUS_ANSWERED
                ),
                event_at=(
                    "2026-08-16T17:00:05+02:00"
                ),
            )
        )

        return (
            self.service
            .apply_call_event(
                call.id,
                status=(
                    CALL_STATUS_ENDED
                ),
                event_at=(
                    "2026-08-16T17:02:05+02:00"
                ),
            )
        )


    def test_saves_reason_and_notes_after_ended_call(
        self,
    ):
        ended = self._ended_call()

        saved = (
            self.service
            .save_post_call_details(
                ended.id,
                reason_code=(
                    "LEGAL_CONSULTATION"
                ),
                reason_detail=(
                    "Consulta sobre renovación"
                ),
                notes=(
                    "Se explican requisitos "
                    "y documentación pendiente."
                ),
            )
        )

        self.assertEqual(
            saved.status,
            CALL_STATUS_ENDED,
        )

        self.assertEqual(
            saved.reason_code,
            "LEGAL_CONSULTATION",
        )

        self.assertEqual(
            saved.reason_detail,
            "Consulta sobre renovación",
        )

        self.assertEqual(
            saved.notes,
            (
                "Se explican requisitos "
                "y documentación pendiente."
            ),
        )


    def test_invalid_reason_is_rejected_without_write(
        self,
    ):
        ended = self._ended_call()

        with self.assertRaises(
            ValueError
        ):
            (
                self.service
                .save_post_call_details(
                    ended.id,
                    reason_code=(
                        "NOT_A_REAL_REASON"
                    ),
                    notes="No debe persistir",
                )
            )

        stored = self.repo.get_call(
            ended.id
        )

        self.assertIsNone(
            stored.reason_code
        )

        self.assertIsNone(
            stored.notes
        )


    def test_non_ended_call_cannot_be_completed(
        self,
    ):
        call = (
            self.service
            .create_outbound_call(
                channel=CHANNEL_PHONE,
                phone_number=(
                    "+34600123999"
                ),
            )
        )

        with self.assertRaises(
            ValueError
        ):
            (
                self.service
                .save_post_call_details(
                    call.id,
                    reason_code=(
                        "LEGAL_CONSULTATION"
                    ),
                )
            )


    def test_details_write_cannot_modify_lifecycle_or_provider(
        self,
    ):
        ended = self._ended_call()

        poisoned = replace(
            ended,
            status=(
                CALL_STATUS_FAILED
            ),
            provider="OTHER_PROVIDER",
            provider_call_id=(
                "OTHER-PROVIDER-ID"
            ),
            external_call_key=(
                "OTHER-EXTERNAL-KEY"
            ),
            outcome_code="RESOLVED",
            reason_code=(
                "EXPEDIENT_STATUS"
            ),
            notes=(
                "Nota de prueba"
            ),
        )

        saved = (
            self.repo
            .update_call_details(
                poisoned
            )
        )

        self.assertEqual(
            saved.status,
            CALL_STATUS_ENDED,
        )

        self.assertEqual(
            saved.provider,
            ended.provider,
        )

        self.assertEqual(
            saved.provider_call_id,
            ended.provider_call_id,
        )

        self.assertEqual(
            saved.external_call_key,
            ended.external_call_key,
        )

        self.assertEqual(
            saved.outcome_code,
            ended.outcome_code,
        )

        self.assertEqual(
            saved.reason_code,
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            saved.notes,
            "Nota de prueba",
        )


    def test_save_is_idempotent(
        self,
    ):
        ended = self._ended_call()

        first = (
            self.service
            .save_post_call_details(
                ended.id,
                reason_code="FOLLOW_UP",
                notes="Seguimiento realizado",
            )
        )

        second = (
            self.service
            .save_post_call_details(
                ended.id,
                reason_code="FOLLOW_UP",
                notes="Seguimiento realizado",
            )
        )

        self.assertEqual(
            first.reason_code,
            second.reason_code,
        )

        self.assertEqual(
            first.notes,
            second.notes,
        )


    def test_reason_catalog_is_exposed_by_service(
        self,
    ):
        options = (
            self.service
            .list_reason_options()
        )

        codes = {
            option.code
            for option in options
        }

        self.assertIn(
            "LEGAL_CONSULTATION",
            codes,
        )

        self.assertIn(
            "EXPEDIENT_STATUS",
            codes,
        )

        self.assertIn(
            "OTHER",
            codes,
        )


if __name__ == "__main__":
    unittest.main()
