import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.communications.models import (
    ATTEMPT_STATUS_ERROR,
    ATTEMPT_STATUS_SENT,
    CHANNEL_WHATSAPP,
    CommunicationAccount,
    CommunicationMessage,
    CommunicationMessageAttempt,
    CommunicationThread,
    DIRECTION_OUTBOUND,
    MESSAGE_STATUS_PENDING,
    MESSAGE_STATUS_SENT,
    THREAD_MATCH_MATCHED,
    THREAD_MATCH_UNMATCHED,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)


class CommunicationRepositoryTest(
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

        self.repo = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        self.repo.ensure_schema()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_account(self):
        return self.repo.save_account(
            CommunicationAccount(
                id=None,
                code="WHATSAPP_DEV",
                channel=CHANNEL_WHATSAPP,
                display_name=(
                    "WhatsApp desarrollo"
                ),
                transport=(
                    "SELENIUMBASE_WEB"
                ),
                environment=(
                    "DEVELOPMENT"
                ),
                profile_key=(
                    "whatsapp_dev"
                ),
                is_active=True,
                is_default=True,
            )
        )

    def test_account_is_idempotent(self):
        first = self._create_account()
        second = self._create_account()

        self.assertIsNotNone(first.id)

        self.assertEqual(
            first.id,
            second.id,
        )

        stored = (
            self.repo
            .get_account_by_code(
                "WHATSAPP_DEV"
            )
        )

        self.assertEqual(
            stored.profile_key,
            "whatsapp_dev",
        )

        self.assertTrue(
            stored.is_default
        )

    def test_unmatched_thread_can_exist(self):
        account = self._create_account()

        thread = (
            self.repo
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=None,
                    external_thread_key=(
                        "34600111222"
                    ),
                    external_address=(
                        "+34600111222"
                    ),
                    external_display_name=(
                        "Contacto personal"
                    ),
                    match_status=(
                        THREAD_MATCH_UNMATCHED
                    ),
                )
            )
        )

        self.assertIsNone(
            thread.client_id
        )

        self.assertEqual(
            thread.match_status,
            THREAD_MATCH_UNMATCHED,
        )

    def test_thread_is_deduplicated(self):
        account = self._create_account()

        first = (
            self.repo
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=10,
                    external_thread_key=(
                        "34600123456"
                    ),
                    external_address=(
                        "+34600123456"
                    ),
                    match_status=(
                        THREAD_MATCH_MATCHED
                    ),
                )
            )
        )

        second = (
            self.repo
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=10,
                    external_thread_key=(
                        "34600123456"
                    ),
                    external_address=(
                        "+34600123456"
                    ),
                    match_status=(
                        THREAD_MATCH_MATCHED
                    ),
                )
            )
        )

        self.assertEqual(
            first.id,
            second.id,
        )

    def test_thread_creation_status_is_exact(
        self,
    ):
        account = self._create_account()

        candidate = CommunicationThread(
            id=None,
            account_id=account.id,
            client_id=10,
            external_thread_key=(
                "phone:34600999111"
            ),
            external_address=(
                "+34600999111"
            ),
            match_status=(
                THREAD_MATCH_MATCHED
            ),
        )

        first, first_created = (
            self.repo
            .get_or_create_thread_with_status(
                candidate
            )
        )

        second, second_created = (
            self.repo
            .get_or_create_thread_with_status(
                candidate
            )
        )

        self.assertTrue(
            first_created
        )

        self.assertFalse(
            second_created
        )

        self.assertEqual(
            first.id,
            second.id,
        )

    def test_message_and_attempt_history(self):
        account = self._create_account()

        thread = (
            self.repo
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=10,
                    external_thread_key=(
                        "34600123456"
                    ),
                    external_address=(
                        "+34600123456"
                    ),
                    match_status=(
                        THREAD_MATCH_MATCHED
                    ),
                )
            )
        )

        message = (
            self.repo.create_message(
                CommunicationMessage(
                    id=None,
                    thread_id=thread.id,
                    client_id=10,
                    expedient_id=20,
                    direction=(
                        DIRECTION_OUTBOUND
                    ),
                    body_text=(
                        "Mensaje de prueba"
                    ),
                    status=(
                        MESSAGE_STATUS_PENDING
                    ),
                    created_by="TEST",
                )
            )
        )

        self.assertEqual(
            message.status,
            MESSAGE_STATUS_PENDING,
        )

        failed_attempt = (
            self.repo.create_attempt(
                CommunicationMessageAttempt(
                    id=None,
                    message_id=message.id,
                    transport=(
                        "SELENIUMBASE_WEB"
                    ),
                    attempt_number=1,
                    status=(
                        ATTEMPT_STATUS_ERROR
                    ),
                    error_code=(
                        "CHAT_NOT_FOUND"
                    ),
                    error_message=(
                        "No se encontró el chat"
                    ),
                )
            )
        )

        self.assertEqual(
            failed_attempt.attempt_number,
            1,
        )

        sent_attempt = (
            self.repo.create_attempt(
                CommunicationMessageAttempt(
                    id=None,
                    message_id=message.id,
                    transport=(
                        "SELENIUMBASE_WEB"
                    ),
                    attempt_number=2,
                    status=(
                        ATTEMPT_STATUS_SENT
                    ),
                )
            )
        )

        self.assertEqual(
            sent_attempt.attempt_number,
            2,
        )

        sent = (
            self.repo
            .update_message_status(
                message.id,
                MESSAGE_STATUS_SENT,
                sent_by="TEST",
            )
        )

        self.assertEqual(
            sent.status,
            MESSAGE_STATUS_SENT,
        )

        attempts = (
            self.repo
            .list_attempts(
                message.id
            )
        )

        self.assertEqual(
            len(attempts),
            2,
        )

        self.assertEqual(
            attempts[0].error_code,
            "CHAT_NOT_FOUND",
        )

        messages = (
            self.repo
            .list_messages(
                thread.id
            )
        )

        self.assertEqual(
            len(messages),
            1,
        )

        self.assertEqual(
            messages[0].body_text,
            "Mensaje de prueba",
        )


if __name__ == "__main__":
    unittest.main()
