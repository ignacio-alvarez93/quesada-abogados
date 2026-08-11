import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.communications.models import (
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    THREAD_MATCH_MATCHED,
    THREAD_MATCH_UNMATCHED,
)
from backend.communications.phone_normalization import (
    normalize_phone,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_service import (
    CommunicationService,
)


class CommunicationServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "communications.db"
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
                    nombre TEXT NOT NULL,
                    primer_apellido TEXT,
                    segundo_apellido TEXT,
                    telefono TEXT
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER
                );

                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido,
                    telefono
                )
                VALUES (
                    10,
                    'CLIENTE',
                    'PRUEBA',
                    NULL,
                    '600 123 456'
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

        repository = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        self.service = (
            CommunicationService(
                repository=repository
            )
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_spanish_mobile_normalization(self):
        phone = normalize_phone(
            "600 123 456"
        )

        self.assertTrue(phone.valid)

        self.assertEqual(
            phone.digits,
            "34600123456",
        )

        self.assertEqual(
            phone.e164,
            "+34600123456",
        )

    def test_whatsapp_dev_account_is_idempotent(
        self,
    ):
        first = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        second = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        self.assertEqual(
            first.profile_key,
            "whatsapp_dev",
        )

    def test_thread_matches_client_by_phone(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente prueba"
                ),
            )
        )

        thread = result["thread"]

        self.assertEqual(
            thread.client_id,
            10,
        )

        self.assertEqual(
            thread.match_status,
            THREAD_MATCH_MATCHED,
        )

    def test_unknown_phone_is_unmatched(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "34600999888"
                ),
                phone="+34 600 999 888",
                display_name="Desconocido",
            )
        )

        thread = result["thread"]

        self.assertIsNone(
            thread.client_id
        )

        self.assertEqual(
            thread.match_status,
            THREAD_MATCH_UNMATCHED,
        )

    def test_whatsapp_thread_is_idempotent(
        self,
    ):
        first = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente prueba"
                ),
                metadata={
                    "source":
                        "whatsapp_web_sync",
                },
            )
        )

        second = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente prueba"
                ),
                metadata={
                    "source":
                        "whatsapp_web_sync",
                },
            )
        )

        first_thread = (
            first["thread"]
        )

        second_thread = (
            second["thread"]
        )

        self.assertTrue(
            first["created"]
        )

        self.assertFalse(
            second["created"]
        )

        self.assertEqual(
            first_thread.id,
            second_thread.id,
        )

        self.assertEqual(
            first_thread.external_thread_key,
            "phone:34600123456",
        )

        self.assertEqual(
            second_thread.external_thread_key,
            "phone:34600123456",
        )

        self.assertEqual(
            first_thread.client_id,
            10,
        )

        self.assertEqual(
            second_thread.client_id,
            10,
        )

        account = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        threads = (
            self.service
            .repository
            .list_threads(
                account_id=account.id,
                limit=100,
            )
        )

        matching = [
            thread
            for thread in threads
            if (
                thread.external_thread_key
                == "phone:34600123456"
            )
        ]

        self.assertEqual(
            len(matching),
            1,
        )

    def test_register_inbound_and_outbound(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "34600123456"
                ),
                phone="600123456",
            )
        )

        thread = result["thread"]

        inbound = (
            self.service
            .register_inbound_message(
                thread_id=thread.id,
                body_text="Hola",
                provider_message_id=(
                    "wa-in-1"
                ),
            )
        )

        outbound = (
            self.service
            .create_outbound_message(
                thread_id=thread.id,
                body_text="Buenos días",
                expedient_id=20,
                created_by="TEST",
            )
        )

        self.assertEqual(
            inbound.direction,
            DIRECTION_INBOUND,
        )

        self.assertEqual(
            outbound.direction,
            DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            outbound.expedient_id,
            20,
        )


if __name__ == "__main__":
    unittest.main()
