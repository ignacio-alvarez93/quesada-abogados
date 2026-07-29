import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.email_platform import (
    official_notice_reprocessing_service,
    schema_service,
)


class OfficialNoticeReprocessingServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "reprocessing_test.db"
        )

        self.schema_patch = patch.object(
            schema_service,
            "DB_PATH",
            self.db_path,
        )
        self.schema_patch.start()

        conn = sqlite3.connect(self.db_path)

        conn.executescript(
            """
            CREATE TABLE email_messages (
                id INTEGER PRIMARY KEY,
                account_id INTEGER,
                provider TEXT,
                provider_message_id TEXT,
                received_at TEXT,
                folder TEXT
            );

            CREATE TABLE email_processing_results (
                id INTEGER PRIMARY KEY,
                email_message_id INTEGER,
                processor_code TEXT,
                extracted_data_json TEXT
            );

            CREATE TABLE dehu_notifications (
                id INTEGER PRIMARY KEY,
                verification_status TEXT
            );

            CREATE TABLE
                dehu_notification_email_sources (
                    id INTEGER PRIMARY KEY,
                    dehu_notification_id INTEGER,
                    email_message_id INTEGER
                );
            """
        )

        messages = [
            (
                1,
                1,
                "IONOS_IMAP",
                "100",
                "2026-07-20T08:00:00",
                "INBOX",
                "NACIONALIDAD",
                "NACIONALIDAD_R",
                (
                    "REFERENCE_DETECTED_"
                    "FAMILY_NOT_AVAILABLE"
                ),
            ),
            (
                2,
                1,
                "IONOS_IMAP",
                "101",
                "2026-07-21T08:00:00",
                "INBOX",
                "EXTRANJERIA",
                "EXTRANJERIA_NUMERIC",
                "EXPEDIENT_NOT_FOUND",
            ),
            (
                3,
                2,
                "GMAIL_API",
                "G-1",
                "2026-07-22T08:00:00",
                "INBOX",
                "NACIONALIDAD",
                "NACIONALIDAD_R",
                (
                    "REFERENCE_DETECTED_"
                    "FAMILY_NOT_AVAILABLE"
                ),
            ),
        ]

        for (
            message_id,
            account_id,
            provider,
            provider_message_id,
            received_at,
            folder,
            family_hint,
            reference_type,
            verification_status,
        ) in messages:
            conn.execute(
                """
                INSERT INTO email_messages (
                    id,
                    account_id,
                    provider,
                    provider_message_id,
                    received_at,
                    folder
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    account_id,
                    provider,
                    provider_message_id,
                    received_at,
                    folder,
                ),
            )

            conn.execute(
                """
                INSERT INTO
                    email_processing_results (
                        id,
                        email_message_id,
                        processor_code,
                        extracted_data_json
                    )
                VALUES (?, ?, ?, ?)
                """,
                (
                    message_id,
                    message_id,
                    "DEHU_NOTIFICATION_NOTICE",
                    json.dumps(
                        {
                            "family_hint":
                                family_hint,
                            "expedient_reference_type":
                                reference_type,
                        }
                    ),
                ),
            )

            conn.execute(
                """
                INSERT INTO dehu_notifications (
                    id,
                    verification_status
                )
                VALUES (?, ?)
                """,
                (
                    message_id,
                    verification_status,
                ),
            )

            conn.execute(
                """
                INSERT INTO
                    dehu_notification_email_sources (
                        id,
                        dehu_notification_id,
                        email_message_id
                    )
                VALUES (?, ?, ?)
                """,
                (
                    message_id,
                    message_id,
                    message_id,
                ),
            )

        conn.commit()
        conn.close()

    def tearDown(self):
        self.schema_patch.stop()
        self.temp_dir.cleanup()

    def test_filters_by_family_and_status(self):
        rows = (
            official_notice_reprocessing_service
            .find_messages(
                family_hint="NACIONALIDAD",
                verification_status=(
                    "REFERENCE_DETECTED_"
                    "FAMILY_NOT_AVAILABLE"
                ),
            )
        )

        self.assertEqual(
            [row["id"] for row in rows],
            [1, 3],
        )

    def test_filters_by_provider_and_account(self):
        rows = (
            official_notice_reprocessing_service
            .find_messages(
                provider="IONOS_IMAP",
                account_id=1,
                folder="INBOX",
            )
        )

        self.assertEqual(
            [row["id"] for row in rows],
            [1, 2],
        )

    def test_filters_by_reference_type_and_limit(
        self,
    ):
        rows = (
            official_notice_reprocessing_service
            .find_messages(
                reference_type="NACIONALIDAD_R",
                limit=1,
            )
        )

        self.assertEqual(
            [row["id"] for row in rows],
            [1],
        )

    def test_rejects_invalid_limit(self):
        with self.assertRaises(ValueError):
            (
                official_notice_reprocessing_service
                .find_messages(limit=0)
            )

    def test_dry_run_does_not_process(self):
        with patch(
            "backend.services.email_platform."
            "official_notice_reprocessing_service."
            "email_expedient_sync_service."
            "process_message"
        ) as process_mock:
            result = (
                official_notice_reprocessing_service
                .reprocess_messages(
                    family_hint="NACIONALIDAD",
                    dry_run=True,
                )
            )

        process_mock.assert_not_called()

        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["processed"], 0)
        self.assertTrue(result["dry_run"])

    def test_reprocesses_selected_messages(self):
        with patch(
            "backend.services.email_platform."
            "official_notice_reprocessing_service."
            "email_expedient_sync_service."
            "process_message",
            return_value={
                "status": "REVIEW_REQUIRED",
                "verification_status": (
                    "REFERENCE_DETECTED_"
                    "FAMILY_NOT_AVAILABLE"
                ),
                "reason": (
                    "REFERENCIA_DETECTADA_"
                    "FAMILIA_NO_DISPONIBLE"
                ),
            },
        ) as process_mock:
            result = (
                official_notice_reprocessing_service
                .reprocess_messages(
                    family_hint="NACIONALIDAD",
                )
            )

        self.assertEqual(
            process_mock.call_count,
            2,
        )
        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["processed"], 2)
        self.assertEqual(
            result["statuses"],
            {"REVIEW_REQUIRED": 2},
        )


if __name__ == "__main__":
    unittest.main()
