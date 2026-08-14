import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.communications.calls import (
    CALL_STATUS_ANSWERED,
    CALL_STATUS_CREATED,
    CALL_STATUS_ENDED,
    CALL_STATUS_MISSED,
    CALL_STATUS_RINGING,
    CommunicationCall,
    transition_call_status_at,
)
from backend.communications.models import (
    ATTEMPT_STATUS_ERROR,
    ATTEMPT_STATUS_SENT,
    CHANNEL_PHONE,
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

    def test_call_without_crm_links_roundtrips(
        self,
    ):
        created = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600999888",
                display_name_snapshot=(
                    "Número no identificado"
                ),
                status=CALL_STATUS_CREATED,
                provider="MOBILE_LINK",
                metadata={
                    "source": "TEST",
                    "sequence": 1,
                },
            )
        )

        self.assertIsNotNone(
            created.id
        )

        self.assertIsNone(
            created.thread_id
        )

        self.assertIsNone(
            created.client_id
        )

        self.assertIsNone(
            created.expedient_id
        )

        self.assertEqual(
            created.phone_number,
            "+34600999888",
        )

        self.assertIsNone(
            created.talk_duration_seconds
        )

        self.assertEqual(
            created.metadata,
            {
                "sequence": 1,
                "source": "TEST",
            },
        )

        stored = self.repo.get_call(
            created.id
        )

        self.assertEqual(
            stored,
            created,
        )

    def test_call_with_crm_links_roundtrips(
        self,
    ):
        account = self._create_account()

        thread = (
            self.repo
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=10,
                    external_thread_key=(
                        "phone:34600123456"
                    ),
                    external_address=(
                        "+34600123456"
                    ),
                    external_display_name=(
                        "CLIENTE TEST"
                    ),
                    match_status=(
                        THREAD_MATCH_MATCHED
                    ),
                )
            )
        )

        created = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_WHATSAPP,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600123456",
                thread_id=thread.id,
                client_id=10,
                expedient_id=20,
                display_name_snapshot=(
                    "CLIENTE TEST"
                ),
                reason_code=(
                    "EXPEDIENT_STATUS"
                ),
                status=CALL_STATUS_MISSED,
                ring_duration_seconds=12,
                talk_duration_seconds=0,
                total_duration_seconds=12,
                notes="Sin respuesta",
                created_by="TEST",
            )
        )

        self.assertEqual(
            created.thread_id,
            thread.id,
        )

        self.assertEqual(
            created.client_id,
            10,
        )

        self.assertEqual(
            created.expedient_id,
            20,
        )

        self.assertEqual(
            created.talk_duration_seconds,
            0,
        )

        self.assertEqual(
            created.total_duration_seconds,
            12,
        )

        stored = self.repo.get_call(
            created.id
        )

        self.assertEqual(
            stored,
            created,
        )

    def test_call_schema_rejects_negative_duration(
        self,
    ):
        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_OUTBOUND,
                    phone_number=(
                        "+34600123456"
                    ),
                    talk_duration_seconds=-1,
                )
            )

    def test_call_lifecycle_update_roundtrips(
        self,
    ):
        created = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600123456",
                display_name_snapshot=(
                    "CLIENTE TEST"
                ),
                client_id=10,
                expedient_id=20,
                reason_code=(
                    "EXPEDIENT_STATUS"
                ),
                provider="MOBILE_LINK",
            )
        )

        ringing = transition_call_status_at(
            created,
            CALL_STATUS_RINGING,
            "2026-08-14T15:00:00+02:00",
        )

        answered = transition_call_status_at(
            ringing,
            CALL_STATUS_ANSWERED,
            "2026-08-14T15:00:05+02:00",
        )

        ended = transition_call_status_at(
            answered,
            CALL_STATUS_ENDED,
            "2026-08-14T15:02:05+02:00",
        )

        stored = (
            self.repo
            .update_call_state(
                ended
            )
        )

        self.assertEqual(
            stored.status,
            CALL_STATUS_ENDED,
        )

        self.assertEqual(
            stored.ringing_at,
            "2026-08-14T15:00:00+02:00",
        )

        self.assertEqual(
            stored.answered_at,
            "2026-08-14T15:00:05+02:00",
        )

        self.assertEqual(
            stored.ended_at,
            "2026-08-14T15:02:05+02:00",
        )

        self.assertEqual(
            stored.ring_duration_seconds,
            5,
        )

        self.assertEqual(
            stored.talk_duration_seconds,
            120,
        )

        self.assertEqual(
            stored.total_duration_seconds,
            125,
        )

        # ---------------------------------------------
        # update_call_state NO debe alterar identidad
        # ni contexto de la llamada.
        # ---------------------------------------------

        self.assertEqual(
            stored.phone_number,
            "+34600123456",
        )

        self.assertEqual(
            stored.client_id,
            10,
        )

        self.assertEqual(
            stored.expedient_id,
            20,
        )

        self.assertEqual(
            stored.reason_code,
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            stored.provider,
            "MOBILE_LINK",
        )

        reloaded = self.repo.get_call(
            created.id
        )

        self.assertEqual(
            reloaded,
            stored,
        )

    def test_call_lifecycle_update_rejects_unknown_call(
        self,
    ):
        missing = CommunicationCall(
            id=999999,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600999999",
        )

        with self.assertRaisesRegex(
            ValueError,
            "no encontrada",
        ):
            self.repo.update_call_state(
                missing
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


    def test_list_latest_messages_returns_recent_window_in_ascending_order(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "latest-window-test"
                ),
                external_address=(
                    "+34600123456"
                ),
            )
        )

        samples = [
            (
                "Primero",
                "LATEST-WINDOW-1",
                "2026-08-13T08:00:00",
            ),
            (
                "Segundo",
                "LATEST-WINDOW-2",
                "2026-08-13T09:00:00",
            ),
            (
                "Tercero",
                "LATEST-WINDOW-3",
                "2026-08-13T10:00:00",
            ),
        ]

        for (
            body_text,
            provider_id,
            timestamp,
        ) in samples:
            self.repo.create_message(
                CommunicationMessage(
                    id=None,
                    thread_id=thread.id,
                    client_id=None,
                    expedient_id=None,
                    direction=DIRECTION_INBOUND,
                    body_text=body_text,
                    status=MESSAGE_STATUS_PENDING,
                    provider_message_id=(
                        provider_id
                    ),
                    provider_timestamp=(
                        timestamp
                    ),
                )
            )

        messages = (
            self.repo
            .list_latest_messages(
                thread.id,
                limit=2,
            )
        )

        self.assertEqual(
            [
                message.body_text
                for message in messages
            ],
            [
                "Segundo",
                "Tercero",
            ],
        )


    def test_list_messages_before_returns_previous_page_in_ascending_order(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "history-before-window"
                ),
                external_address=(
                    "+34600111222"
                ),
            )
        )

        created = []

        for index in range(
            1,
            7,
        ):
            message = self.repo.create_message(
                CommunicationMessage(
                    id=None,
                    thread_id=thread.id,
                    client_id=None,
                    expedient_id=None,
                    direction=DIRECTION_INBOUND,
                    body_text=(
                        f"Mensaje {index}"
                    ),
                    status=MESSAGE_STATUS_PENDING,
                    provider_message_id=(
                        f"HISTORY-BEFORE-{index}"
                    ),
                    provider_timestamp=(
                        "2026-08-13T"
                        f"{index + 7:02d}:00:00"
                    ),
                )
            )
            created.append(
                message
            )

        previous = (
            self.repo
            .list_messages_before(
                thread.id,
                before_message_id=(
                    created[4].id
                ),
                limit=3,
            )
        )

        self.assertEqual(
            [
                message.body_text
                for message in previous
            ],
            [
                "Mensaje 2",
                "Mensaje 3",
                "Mensaje 4",
            ],
        )

        oldest_page = (
            self.repo
            .list_messages_before(
                thread.id,
                before_message_id=(
                    created[0].id
                ),
                limit=3,
            )
        )

        self.assertEqual(
            oldest_page,
            [],
        )


    def test_get_latest_provider_message_returns_newest(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "latest-provider-test"
                ),
                external_address=(
                    "+34600999999"
                ),
            )
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
                "PROVIDER-OLD"
            ),
            provider_timestamp=(
                "2026-08-13T08:00:00"
            ),
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
                "PROVIDER-NEW"
            ),
            provider_timestamp=(
                "2026-08-13T09:00:00"
            ),
        )

        self.repo.get_or_create_message_with_status(
            newer
        )

        self.repo.get_or_create_message_with_status(
            older
        )

        latest = (
            self.repo
            .get_latest_provider_message(
                thread.id
            )
        )

        self.assertIsNotNone(
            latest
        )

        self.assertEqual(
            latest.provider_message_id,
            "PROVIDER-NEW",
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

    def test_attach_provider_identity_to_existing_message(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "attach-provider"
                ),
                external_address=(
                    "+34600777777"
                ),
            )
        )

        message = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="Mensaje CRM",
                status=MESSAGE_STATUS_PENDING,
            )
        )

        attached = (
            self.repo
            .attach_message_provider_identity(
                message.id,
                provider_message_id=(
                    "wa-outbound-local-1"
                ),
                provider_timestamp=(
                    "2026-08-12T12:17:00"
                ),
            )
        )

        self.assertEqual(
            attached.id,
            message.id,
        )

        self.assertEqual(
            attached.provider_message_id,
            "wa-outbound-local-1",
        )

        self.assertEqual(
            attached.provider_timestamp,
            "2026-08-12T12:17:00",
        )

        messages = self.repo.list_messages(
            thread.id
        )

        self.assertEqual(
            len(messages),
            1,
        )

    def test_attach_provider_identity_is_idempotent(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "attach-idempotent"
                ),
                external_address=(
                    "+34600888888"
                ),
            )
        )

        message = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="Idempotente",
                status=MESSAGE_STATUS_PENDING,
            )
        )

        first = (
            self.repo
            .attach_message_provider_identity(
                message.id,
                provider_message_id=(
                    "wa-idempotent-local-1"
                ),
                provider_timestamp=(
                    "2026-08-12T12:18:00"
                ),
            )
        )

        second = (
            self.repo
            .attach_message_provider_identity(
                message.id,
                provider_message_id=(
                    "wa-idempotent-local-1"
                ),
                provider_timestamp=(
                    "2026-08-12T12:18:00"
                ),
            )
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        self.assertEqual(
            second.provider_message_id,
            "wa-idempotent-local-1",
        )

    def test_attach_provider_identity_refuses_overwrite(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "attach-no-overwrite"
                ),
                external_address=(
                    "+34600999999"
                ),
            )
        )

        message = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="No sobrescribir",
                status=MESSAGE_STATUS_PENDING,
                provider_message_id=(
                    "wa-original"
                ),
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "otra identidad",
        ):
            (
                self.repo
                .attach_message_provider_identity(
                    message.id,
                    provider_message_id=(
                        "wa-different"
                    ),
                )
            )

    def test_attach_provider_identity_refuses_thread_conflict(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "attach-conflict"
                ),
                external_address=(
                    "+34600101010"
                ),
            )
        )

        first = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="Primero",
                status=MESSAGE_STATUS_PENDING,
                provider_message_id=(
                    "wa-conflict-1"
                ),
            )
        )

        second = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="Segundo",
                status=MESSAGE_STATUS_PENDING,
            )
        )

        self.assertIsNotNone(
            first.id
        )

        with self.assertRaisesRegex(
            ValueError,
            "otro mensaje",
        ):
            (
                self.repo
                .attach_message_provider_identity(
                    second.id,
                    provider_message_id=(
                        "wa-conflict-1"
                    ),
                )
            )

    def test_finish_attempt_started_to_sent(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "attempt-sent"
                ),
                external_address=(
                    "+34600111112"
                ),
            )
        )

        message = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="Attempt SENT",
                status=MESSAGE_STATUS_PENDING,
            )
        )

        attempt = self.repo.create_attempt(
            CommunicationMessageAttempt(
                id=None,
                message_id=message.id,
                transport=(
                    "SELENIUMBASE_WEB"
                ),
                attempt_number=1,
                status="STARTED",
            )
        )

        finished = (
            self.repo.finish_attempt(
                attempt.id,
                status="SENT",
            )
        )

        self.assertEqual(
            finished.id,
            attempt.id,
        )

        self.assertEqual(
            finished.status,
            "SENT",
        )

        self.assertIsNotNone(
            finished.finished_at
        )

        again = (
            self.repo.finish_attempt(
                attempt.id,
                status="SENT",
            )
        )

        self.assertEqual(
            again.status,
            "SENT",
        )

    def test_finish_attempt_started_to_error(
        self,
    ):
        account = self._create_account()

        thread = self.repo.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "attempt-error"
                ),
                external_address=(
                    "+34600111113"
                ),
            )
        )

        message = self.repo.create_message(
            CommunicationMessage(
                id=None,
                thread_id=thread.id,
                client_id=None,
                expedient_id=None,
                direction=DIRECTION_OUTBOUND,
                body_text="Attempt ERROR",
                status=MESSAGE_STATUS_PENDING,
            )
        )

        attempt = self.repo.create_attempt(
            CommunicationMessageAttempt(
                id=None,
                message_id=message.id,
                transport=(
                    "SELENIUMBASE_WEB"
                ),
                attempt_number=1,
                status="STARTED",
            )
        )

        finished = (
            self.repo.finish_attempt(
                attempt.id,
                status="ERROR",
                error_code=(
                    "SEND_STATE_UNCERTAIN"
                ),
                error_message=(
                    "No se pudo confirmar el envío"
                ),
                metadata={
                    "uncertain": True,
                },
            )
        )

        self.assertEqual(
            finished.status,
            "ERROR",
        )

        self.assertEqual(
            finished.error_code,
            "SEND_STATE_UNCERTAIN",
        )

        self.assertEqual(
            finished.error_message,
            "No se pudo confirmar el envío",
        )

        self.assertEqual(
            finished.metadata,
            {
                "uncertain": True,
            },
        )

        self.assertIsNotNone(
            finished.finished_at
        )

        with self.assertRaisesRegex(
            ValueError,
            "otro estado",
        ):
            self.repo.finish_attempt(
                attempt.id,
                status="SENT",
            )



if __name__ == "__main__":
    unittest.main()
