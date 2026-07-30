import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.services.email_platform import (
    dehu_inbox_service,
    schema_service,
)


class DehuInboxServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "dehu_inbox_test.db"
        )

        self.schema_patch = patch.object(
            schema_service,
            "DB_PATH",
            self.db_path,
        )
        self.schema_patch.start()

        self.conn = sqlite3.connect(
            self.db_path
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        self._create_schema()
        self._insert_data()

    def tearDown(self):
        self.conn.close()
        self.schema_patch.stop()
        self.temp_dir.cleanup()

    def _create_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                numero_expediente TEXT,
                numero_expediente_extranjeria TEXT
            );

            CREATE TABLE email_messages (
                id INTEGER PRIMARY KEY,
                account_email TEXT,
                provider_message_id TEXT,
                subject TEXT,
                sender_email TEXT,
                received_at TEXT
            );

            CREATE TABLE dehu_notifications (
                id INTEGER PRIMARY KEY,
                dehu_identifier TEXT UNIQUE,
                concept TEXT,
                item_type TEXT,
                concept_type TEXT,
                reference_value TEXT,
                reference_type TEXT,
                family_hint TEXT,
                direct_access_url TEXT,
                email_expedient_number TEXT,
                dehu_expedient_number TEXT,
                expediente_id INTEGER,
                cliente_id INTEGER,
                primary_email_message_id INTEGER,
                recipient_name TEXT,
                recipient_document_masked TEXT,
                issuer_name TEXT,
                issuer_dir3 TEXT,
                relationship_type TEXT,
                deadline_at TEXT,
                portal_status TEXT,
                verification_status TEXT,
                download_status TEXT,
                document_inbox_batch_id INTEGER,
                first_seen_at TEXT,
                last_seen_at TEXT,
                accepted_at TEXT,
                rejected_at TEXT,
                downloaded_at TEXT,
                last_error TEXT,
                raw_email_data_json TEXT,
                raw_dehu_data_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE
                dehu_notification_email_sources (
                    id INTEGER PRIMARY KEY,
                    dehu_notification_id INTEGER,
                    email_message_id INTEGER,
                    provider TEXT,
                    account_id INTEGER,
                    source_folder TEXT,
                    detected_at TEXT,
                    UNIQUE(
                        dehu_notification_id,
                        email_message_id
                    )
                );
            """
        )

    def _insert_data(self):
        now = datetime.now()

        upcoming = (
            now + timedelta(days=3)
        ).strftime("%Y-%m-%d %H:%M:%S")

        expired = (
            now - timedelta(days=2)
        ).strftime("%Y-%m-%d %H:%M:%S")

        self.conn.execute(
            """
            INSERT INTO clientes (
                id,
                nombre,
                primer_apellido,
                segundo_apellido
            )
            VALUES (
                1,
                'ANA',
                'QUESADA',
                'SOLER'
            )
            """
        )

        self.conn.execute(
            """
            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente,
                numero_expediente_extranjeria
            )
            VALUES (
                1,
                1,
                'EXP-001',
                '330020260000001'
            )
            """
        )

        rows = [
            (
                1,
                "DEHU-1",
                "not_330020260000001_1_1",
                "NOTIFICATION",
                "NOT",
                "330020260000001",
                "EXTRANJERIA_NUMERIC",
                "EXTRANJERIA",
                "https://dehu.redsara.es/test/1",
                1,
                1,
                "ANA QUESADA",
                "Oficina de Extranjeria en Oviedo",
                upcoming,
                "MATCHED_PROVISIONAL",
            ),
            (
                2,
                "DEHU-2",
                "R619648/2025",
                "NOTIFICATION",
                "NACIONALIDAD_REFERENCE",
                "R619648/2025",
                "NACIONALIDAD_R",
                "NACIONALIDAD",
                "https://dehu.redsara.es/test/2",
                None,
                None,
                "MARIA PRUEBA",
                "S.G. de Nacionalidad y Estado Civil",
                expired,
                (
                    "REFERENCE_DETECTED_"
                    "FAMILY_NOT_AVAILABLE"
                ),
            ),
            (
                3,
                "DEHU-3",
                "com_330020260000003_1_1",
                "COMMUNICATION",
                "COM",
                "330020260000003",
                "EXTRANJERIA_NUMERIC",
                "EXTRANJERIA",
                "https://dehu.redsara.es/communications",
                None,
                None,
                "PEDRO PRUEBA",
                "Oficina de Extranjeria en Murcia",
                "",
                "EXPEDIENT_NOT_FOUND",
            ),
            (
                4,
                "DEHU-PORTAL-4",
                "not_330020260000004_1_1",
                "NOTIFICATION",
                "NOT",
                "330020260000004",
                "EXTRANJERIA_NUMERIC",
                "EXTRANJERIA",
                "https://dehu.redsara.es/test/4",
                None,
                None,
                "CLIENTE SIN EMAIL",
                "Oficina de Extranjeria en Oviedo",
                upcoming,
                "EXPEDIENT_NOT_FOUND",
            ),
        ]

        for row in rows:
            self.conn.execute(
                """
                INSERT INTO dehu_notifications (
                    id,
                    dehu_identifier,
                    concept,
                    item_type,
                    concept_type,
                    reference_value,
                    reference_type,
                    family_hint,
                    direct_access_url,
                    expediente_id,
                    cliente_id,
                    recipient_name,
                    issuer_name,
                    deadline_at,
                    verification_status,
                    portal_status,
                    download_status,
                    first_seen_at,
                    last_seen_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    'UNKNOWN',
                    'NOT_REQUESTED',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """,
                row,
            )

        self.conn.execute(
            """
            UPDATE dehu_notifications
            SET
                portal_status = 'VERIFIED',
                raw_dehu_data_json = ?
            WHERE id = 4
            """,
            ('{"source": "DEHU_PORTAL"}',),
        )

        self.conn.execute(
            """
            UPDATE dehu_notifications
            SET portal_status = 'ACCEPTED'
            WHERE id = 1
            """
        )

        self.conn.execute(
            """
            UPDATE dehu_notifications
            SET portal_status = 'REJECTED'
            WHERE id = 3
            """
        )

        self.conn.execute(
            """
            INSERT INTO email_messages (
                id,
                account_email,
                provider_message_id,
                subject,
                sender_email,
                received_at
            )
            VALUES (
                1,
                'buzon@test.local',
                'UID-1',
                'Nueva notificación',
                'noreply.dehu@correo.gob.es',
                CURRENT_TIMESTAMP
            )
            """
        )

        self.conn.execute(
            """
            INSERT INTO
                dehu_notification_email_sources (
                    id,
                    dehu_notification_id,
                    email_message_id,
                    provider,
                    account_id,
                    source_folder,
                    detected_at
                )
            VALUES (
                1,
                1,
                1,
                'IONOS_IMAP',
                1,
                'INBOX',
                CURRENT_TIMESTAMP
            )
            """
        )

        self.conn.commit()

    def test_summary(self):
        summary = (
            dehu_inbox_service.get_summary(
                self.conn
            )
        )

        self.assertEqual(
            summary["total"],
            4,
        )
        self.assertEqual(
            summary["notifications"],
            3,
        )
        self.assertEqual(
            summary["communications"],
            1,
        )
        self.assertEqual(
            summary["linked"],
            1,
        )
        self.assertEqual(
            summary["family_unavailable"],
            1,
        )
        self.assertEqual(
            summary["expired"],
            1,
        )
        self.assertEqual(
            summary["upcoming_7_days"],
            2,
        )
        self.assertEqual(
            summary["email_only"],
            0,
        )
        self.assertEqual(
            summary["portal_only"],
            2,
        )
        self.assertEqual(
            summary["email_and_portal"],
            1,
        )
        self.assertEqual(
            summary["origin_unknown"],
            1,
        )
        self.assertEqual(
            summary["email_detected"],
            1,
        )
        self.assertEqual(
            summary["portal_detected"],
            3,
        )

    def test_filters_by_family(self):
        result = (
            dehu_inbox_service.list_items(
                family_hint="NACIONALIDAD",
                conn=self.conn,
            )
        )

        self.assertEqual(
            result["total"],
            1,
        )
        self.assertEqual(
            result["items"][0][
                "reference_value"
            ],
            "R619648/2025",
        )

    def test_filters_by_type(self):
        result = (
            dehu_inbox_service.list_items(
                item_type="COMMUNICATION",
                conn=self.conn,
            )
        )

        self.assertEqual(
            result["total"],
            1,
        )
        self.assertEqual(
            result["items"][0][
                "item_type"
            ],
            "COMMUNICATION",
        )

    def test_searches_reference_and_issuer(self):
        by_reference = (
            dehu_inbox_service.list_items(
                search="R619648",
                conn=self.conn,
            )
        )

        by_issuer = (
            dehu_inbox_service.list_items(
                search="Murcia",
                conn=self.conn,
            )
        )

        self.assertEqual(
            by_reference["total"],
            1,
        )
        self.assertEqual(
            by_issuer["total"],
            1,
        )

    def test_filters_by_portal_status(self):
        accepted = (
            dehu_inbox_service.list_items(
                portal_status="ACCEPTED",
                conn=self.conn,
            )
        )

        rejected = (
            dehu_inbox_service.list_items(
                portal_status="REJECTED",
                conn=self.conn,
            )
        )

        pending = (
            dehu_inbox_service.list_items(
                portal_status="PENDING",
                conn=self.conn,
            )
        )

        self.assertEqual(
            accepted["total"],
            1,
        )
        self.assertEqual(
            accepted["items"][0][
                "portal_status"
            ],
            "ACCEPTED",
        )

        self.assertEqual(
            rejected["total"],
            1,
        )
        self.assertEqual(
            rejected["items"][0][
                "portal_status"
            ],
            "REJECTED",
        )

        self.assertEqual(
            pending["total"],
            1,
        )
        self.assertEqual(
            pending["items"][0][
                "portal_status"
            ],
            "UNKNOWN",
        )

    def test_deadline_filters(self):
        upcoming = (
            dehu_inbox_service.list_items(
                deadline_filter=(
                    "UPCOMING_7_DAYS"
                ),
                conn=self.conn,
            )
        )

        expired = (
            dehu_inbox_service.list_items(
                deadline_filter="EXPIRED",
                conn=self.conn,
            )
        )

        no_deadline = (
            dehu_inbox_service.list_items(
                deadline_filter="NO_DEADLINE",
                conn=self.conn,
            )
        )

        self.assertEqual(
            upcoming["total"],
            2,
        )
        self.assertEqual(
            expired["total"],
            1,
        )
        self.assertEqual(
            no_deadline["total"],
            1,
        )

    def test_paginates(self):
        first = (
            dehu_inbox_service.list_items(
                page=1,
                page_size=2,
                conn=self.conn,
            )
        )

        second = (
            dehu_inbox_service.list_items(
                page=2,
                page_size=2,
                conn=self.conn,
            )
        )

        self.assertEqual(
            first["total"],
            4,
        )
        self.assertEqual(
            first["total_pages"],
            2,
        )
        self.assertEqual(
            len(first["items"]),
            2,
        )
        self.assertEqual(
            len(second["items"]),
            2,
        )

    def test_classifies_detection_origin(self):
        result = (
            dehu_inbox_service.list_items(
                page_size=10,
                conn=self.conn,
            )
        )

        origins = {
            item["id"]:
                item["detection_origin"]
            for item in result["items"]
        }

        self.assertEqual(
            origins[1],
            "EMAIL_AND_PORTAL",
        )
        self.assertEqual(
            origins[4],
            "PORTAL_ONLY",
        )
        self.assertEqual(
            origins[2],
            "UNKNOWN",
        )
        self.assertEqual(
            origins[3],
            "PORTAL_ONLY",
        )

    def test_item_detail_contains_sources(self):
        detail = (
            dehu_inbox_service
            .get_item_detail(
                1,
                conn=self.conn,
            )
        )

        self.assertIsNotNone(detail)
        self.assertEqual(
            detail["numero_expediente"],
            "EXP-001",
        )
        self.assertEqual(
            len(detail["sources"]),
            1,
        )
        self.assertEqual(
            detail["sources"][0][
                "source_folder"
            ],
            "INBOX",
        )


if __name__ == "__main__":
    unittest.main()
