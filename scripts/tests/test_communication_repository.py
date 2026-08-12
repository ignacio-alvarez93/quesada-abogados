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
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    MESSAGE_STATUS_DELIVERED,
    MESSAGE_STATUS_READ,
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

    def test_provider_message_is_idempotent(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "provider-idempotency"
                ),
                external_address=(
                    "+34600111111"
                ),
            )
        )

        candidate = CommunicationMessage(
            id=None,
            thread_id=thread.id,
            client_id=None,
            expedient_id=None,
            direction=DIRECTION_INBOUND,
            body_text="Mensaje único",
            status=MESSAGE_STATUS_PENDING,
            provider_message_id=(
                "wa-provider-001"
            ),
            provider_timestamp=(
                "2026-08-10T10:00:00"
            ),
        )

        first, first_created = (
            self.repo
            .get_or_create_message_with_status(
                candidate
            )
        )

        second, second_created = (
            self.repo
            .get_or_create_message_with_status(
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

        messages = self.repo.list_messages(
            thread.id
        )

        self.assertEqual(
            len(messages),
            1,
        )


    def test_historical_message_does_not_rewind_thread(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "historical-order"
                ),
                external_address=(
                    "+34600222222"
                ),
            )
        )

        newer = CommunicationMessage(
            id=None,
            thread_id=thread.id,
            client_id=None,
            expedient_id=None,
            direction=DIRECTION_INBOUND,
            body_text="Nuevo",
            status=MESSAGE_STATUS_PENDING,
            provider_message_id=(
                "wa-newer"
            ),
            provider_timestamp=(
                "2026-08-10T10:00:00"
            ),
        )

        older = CommunicationMessage(
            id=None,
            thread_id=thread.id,
            client_id=None,
            expedient_id=None,
            direction=DIRECTION_INBOUND,
            body_text="Antiguo",
            status=MESSAGE_STATUS_PENDING,
            provider_message_id=(
                "wa-older"
            ),
            provider_timestamp=(
                "2026-06-01T10:00:00"
            ),
        )

        self.repo.get_or_create_message_with_status(
            newer
        )

        self.repo.get_or_create_message_with_status(
            older
        )

        with self.repo._connection() as conn:
            row = conn.execute(
                """
                SELECT last_message_at
                FROM communication_threads
                WHERE id = ?
                """,
                (
                    int(thread.id),
                ),
            ).fetchone()

        self.assertIsNotNone(
            row
        )

        self.assertEqual(
            row["last_message_at"],
            "2026-08-10T10:00:00",
        )

    def test_provider_status_advances_without_duplicate(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "provider-status-progress"
                ),
                external_address=(
                    "+34600333333"
                ),
            )
        )

        delivered = CommunicationMessage(
            id=None,
            thread_id=thread.id,
            client_id=None,
            expedient_id=None,
            direction=DIRECTION_OUTBOUND,
            body_text="Estado proveedor",
            status=MESSAGE_STATUS_DELIVERED,
            provider_message_id=(
                "wa-status-progress-1"
            ),
            provider_timestamp=(
                "2026-08-12T09:59:00"
            ),
        )

        first, first_created = (
            self.repo
            .get_or_create_message_with_status(
                delivered
            )
        )

        read_candidate = CommunicationMessage(
            id=None,
            thread_id=thread.id,
            client_id=None,
            expedient_id=None,
            direction=DIRECTION_OUTBOUND,
            body_text="Estado proveedor",
            status=MESSAGE_STATUS_READ,
            provider_message_id=(
                "wa-status-progress-1"
            ),
            provider_timestamp=(
                "2026-08-12T09:59:00"
            ),
        )

        second, second_created = (
            self.repo
            .get_or_create_message_with_status(
                read_candidate
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

        self.assertEqual(
            second.status,
            MESSAGE_STATUS_READ,
        )

        downgrade_candidate = (
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="Estado proveedor",
                status=(
                    MESSAGE_STATUS_DELIVERED
                ),
                provider_message_id=(
                    "wa-status-progress-1"
                ),
                provider_timestamp=(
                    "2026-08-12T09:59:00"
                ),
            )
        )

        third, third_created = (
            self.repo
            .get_or_create_message_with_status(
                downgrade_candidate
            )
        )

        self.assertFalse(
            third_created
        )

        self.assertEqual(
            third.id,
            first.id,
        )

        self.assertEqual(
            third.status,
            MESSAGE_STATUS_READ,
        )

        messages = (
            self.repo.list_messages(
                thread.id
            )
        )

        self.assertEqual(
            len(messages),
            1,
        )

    def test_get_message_by_provider_identity(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "provider-lookup"
                ),
                external_address=(
                    "+34600666666"
                ),
            )
        )

        created = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_INBOUND,
                body_text="Lookup",
                status=MESSAGE_STATUS_PENDING,
                provider_message_id=(
                    "wa-provider-lookup-1"
                ),
            )
        )

        found = (
            self.repo
            .get_message_by_provider_identity(
                thread_id=thread.id,
                provider_message_id=(
                    "wa-provider-lookup-1"
                ),
            )
        )

        missing = (
            self.repo
            .get_message_by_provider_identity(
                thread_id=thread.id,
                provider_message_id=(
                    "wa-provider-missing"
                ),
            )
        )

        self.assertIsNotNone(
            found
        )

        self.assertEqual(
            found.id,
            created.id,
        )

        self.assertIsNone(
            missing
        )


if __name__ == "__main__":
    unittest.main()
