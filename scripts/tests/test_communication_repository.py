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
from backend.communications.call_followups import (
    CALL_FOLLOW_UP_IN_PROGRESS,
    CALL_FOLLOW_UP_RESOLVED,
    transition_call_follow_up,
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

    def test_call_follow_up_schema_is_idempotent(
        self,
    ):
        self.repo.ensure_schema()
        self.repo.ensure_schema()

        conn = sqlite3.connect(
            str(self.db_path)
        )

        try:
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }

            self.assertIn(
                "communication_call_followups",
                tables,
            )

            self.assertIn(
                "communication_call_callbacks",
                tables,
            )

        finally:
            conn.close()

    def test_call_follow_up_schema_supports_multiple_callbacks(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600111111",
                status=CALL_STATUS_MISSED,
            )
        )

        first_callback = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600111111",
            )
        )

        second_callback = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600111111",
            )
        )

        conn = sqlite3.connect(
            str(self.db_path)
        )

        try:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            conn.execute(
                """
                INSERT INTO
                    communication_call_followups (
                        source_call_id,
                        status
                    )
                VALUES (?, 'PENDING')
                """,
                (
                    source.id,
                ),
            )

            conn.execute(
                """
                INSERT INTO
                    communication_call_callbacks (
                        source_call_id,
                        callback_call_id
                    )
                VALUES (?, ?)
                """,
                (
                    source.id,
                    first_callback.id,
                ),
            )

            conn.execute(
                """
                INSERT INTO
                    communication_call_callbacks (
                        source_call_id,
                        callback_call_id
                    )
                VALUES (?, ?)
                """,
                (
                    source.id,
                    second_callback.id,
                ),
            )

            conn.commit()

            callback_count = (
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM communication_call_callbacks
                    WHERE source_call_id = ?
                    """,
                    (
                        source.id,
                    ),
                ).fetchone()[0]
            )

            self.assertEqual(
                callback_count,
                2,
            )

            with self.assertRaises(
                sqlite3.IntegrityError
            ):
                conn.execute(
                    """
                    INSERT INTO
                        communication_call_followups (
                            source_call_id,
                            status
                        )
                    VALUES (?, 'PENDING')
                    """,
                    (
                        source.id,
                    ),
                )

        finally:
            conn.close()

    def test_call_callback_requires_follow_up(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600222222",
                status=CALL_STATUS_MISSED,
            )
        )

        callback = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600222222",
            )
        )

        conn = sqlite3.connect(
            str(self.db_path)
        )

        try:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            with self.assertRaises(
                sqlite3.IntegrityError
            ):
                conn.execute(
                    """
                    INSERT INTO
                        communication_call_callbacks (
                            source_call_id,
                            callback_call_id
                        )
                    VALUES (?, ?)
                    """,
                    (
                        source.id,
                        callback.id,
                    ),
                )

        finally:
            conn.close()

    def test_callback_call_cannot_belong_to_two_follow_ups(
        self,
    ):
        first_source = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600333331",
                    status=CALL_STATUS_MISSED,
                )
            )
        )

        second_source = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600333332",
                    status=CALL_STATUS_MISSED,
                )
            )
        )

        callback = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600333331",
            )
        )

        conn = sqlite3.connect(
            str(self.db_path)
        )

        try:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            for source in (
                first_source,
                second_source,
            ):
                conn.execute(
                    """
                    INSERT INTO
                        communication_call_followups (
                            source_call_id,
                            status
                        )
                    VALUES (?, 'PENDING')
                    """,
                    (
                        source.id,
                    ),
                )

            conn.execute(
                """
                INSERT INTO
                    communication_call_callbacks (
                        source_call_id,
                        callback_call_id
                    )
                VALUES (?, ?)
                """,
                (
                    first_source.id,
                    callback.id,
                ),
            )

            with self.assertRaises(
                sqlite3.IntegrityError
            ):
                conn.execute(
                    """
                    INSERT INTO
                        communication_call_callbacks (
                            source_call_id,
                            callback_call_id
                        )
                    VALUES (?, ?)
                    """,
                    (
                        second_source.id,
                        callback.id,
                    ),
                )

        finally:
            conn.close()

    def test_resolved_follow_up_requires_resolved_at(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600444444",
                status=CALL_STATUS_MISSED,
            )
        )

        conn = sqlite3.connect(
            str(self.db_path)
        )

        try:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            with self.assertRaises(
                sqlite3.IntegrityError
            ):
                conn.execute(
                    """
                    INSERT INTO
                        communication_call_followups (
                            source_call_id,
                            status,
                            resolved_at
                        )
                    VALUES (
                        ?,
                        'RESOLVED',
                        NULL
                    )
                    """,
                    (
                        source.id,
                    ),
                )

            conn.execute(
                """
                INSERT INTO
                    communication_call_followups (
                        source_call_id,
                        status,
                        resolved_at
                    )
                VALUES (
                    ?,
                    'RESOLVED',
                    ?
                )
                """,
                (
                    source.id,
                    "2026-08-14T15:30:00+02:00",
                ),
            )

            conn.commit()

        finally:
            conn.close()

    def test_call_follow_up_repository_is_idempotent(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600500001",
                status=CALL_STATUS_MISSED,
            )
        )

        first = (
            self.repo
            .get_or_create_call_follow_up(
                source.id
            )
        )

        second = (
            self.repo
            .get_or_create_call_follow_up(
                source.id
            )
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        self.assertEqual(
            first.source_call_id,
            source.id,
        )

        self.assertEqual(
            first.status,
            "PENDING",
        )

        by_id = (
            self.repo
            .get_call_follow_up(
                first.id
            )
        )

        by_source = (
            self.repo
            .get_call_follow_up_by_source_call(
                source.id
            )
        )

        self.assertEqual(
            by_id,
            first,
        )

        self.assertEqual(
            by_source,
            first,
        )

    def test_call_follow_up_repository_persists_lifecycle(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600500002",
                status=CALL_STATUS_MISSED,
            )
        )

        pending = (
            self.repo
            .get_or_create_call_follow_up(
                source.id
            )
        )

        active = (
            transition_call_follow_up(
                pending,
                CALL_FOLLOW_UP_IN_PROGRESS,
            )
        )

        stored_active = (
            self.repo
            .update_call_follow_up(
                active
            )
        )

        self.assertEqual(
            stored_active.status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

        resolved = (
            transition_call_follow_up(
                stored_active,
                CALL_FOLLOW_UP_RESOLVED,
                resolved_at=(
                    "2026-08-14T16:10:00+02:00"
                ),
            )
        )

        stored_resolved = (
            self.repo
            .update_call_follow_up(
                resolved
            )
        )

        self.assertEqual(
            stored_resolved.status,
            CALL_FOLLOW_UP_RESOLVED,
        )

        self.assertEqual(
            stored_resolved.resolved_at,
            "2026-08-14T16:10:00+02:00",
        )

    def test_callback_repository_is_idempotent_and_lists_calls(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600500003",
                status=CALL_STATUS_MISSED,
            )
        )

        self.repo.get_or_create_call_follow_up(
            source.id
        )

        first_callback = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_OUTBOUND,
                    phone_number="+34600500003",
                )
            )
        )

        second_callback = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_OUTBOUND,
                    phone_number="+34600500003",
                )
            )
        )

        first_link = (
            self.repo.link_callback_call(
                source_call_id=source.id,
                callback_call_id=(
                    first_callback.id
                ),
            )
        )

        repeated_link = (
            self.repo.link_callback_call(
                source_call_id=source.id,
                callback_call_id=(
                    first_callback.id
                ),
            )
        )

        self.repo.link_callback_call(
            source_call_id=source.id,
            callback_call_id=(
                second_callback.id
            ),
        )

        self.assertEqual(
            first_link.id,
            repeated_link.id,
        )

        callbacks = (
            self.repo
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
                first_callback.id,
                second_callback.id,
            ],
        )

    def test_callback_call_cannot_be_reused_for_another_follow_up_repository(
        self,
    ):
        first_source = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600500004",
                    status=CALL_STATUS_MISSED,
                )
            )
        )

        second_source = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600500005",
                    status=CALL_STATUS_MISSED,
                )
            )
        )

        self.repo.get_or_create_call_follow_up(
            first_source.id
        )

        self.repo.get_or_create_call_follow_up(
            second_source.id
        )

        callback = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600500004",
            )
        )

        self.repo.link_callback_call(
            source_call_id=first_source.id,
            callback_call_id=callback.id,
        )

        with self.assertRaisesRegex(
            ValueError,
            "ya está vinculada",
        ):
            self.repo.link_callback_call(
                source_call_id=second_source.id,
                callback_call_id=callback.id,
            )

    def test_pending_call_inventory_projects_context_and_callbacks(
        self,
    ):
        first_source = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600500006",
                    display_name_snapshot=(
                        "CLIENTE TEST"
                    ),
                    client_id=10,
                    expedient_id=20,
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T15:00:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T15:00:10+02:00"
                    ),
                )
            )
        )

        second_source = (
            self.repo.create_call(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600500007",
                    display_name_snapshot=(
                        "Número no identificado"
                    ),
                    status=CALL_STATUS_MISSED,
                    ringing_at=(
                        "2026-08-14T15:10:00+02:00"
                    ),
                    ended_at=(
                        "2026-08-14T15:10:05+02:00"
                    ),
                )
            )
        )

        first_follow_up = (
            self.repo
            .get_or_create_call_follow_up(
                first_source.id
            )
        )

        self.repo.get_or_create_call_follow_up(
            second_source.id
        )

        callback = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600500006",
            )
        )

        self.repo.link_callback_call(
            source_call_id=first_source.id,
            callback_call_id=callback.id,
        )

        active = (
            transition_call_follow_up(
                first_follow_up,
                CALL_FOLLOW_UP_IN_PROGRESS,
            )
        )

        self.repo.update_call_follow_up(
            active
        )

        inventory = (
            self.repo
            .list_pending_call_follow_ups()
        )

        self.assertEqual(
            len(inventory),
            2,
        )

        first = inventory[0]

        self.assertEqual(
            first.source_call_id,
            first_source.id,
        )

        self.assertEqual(
            first.follow_up_status,
            CALL_FOLLOW_UP_IN_PROGRESS,
        )

        self.assertEqual(
            first.phone_number,
            "+34600500006",
        )

        self.assertEqual(
            first.display_name_snapshot,
            "CLIENTE TEST",
        )

        self.assertEqual(
            first.client_id,
            10,
        )

        self.assertEqual(
            first.expedient_id,
            20,
        )

        self.assertEqual(
            first.source_call_status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            first.callback_count,
            1,
        )

        self.assertIsNotNone(
            first.latest_callback_at
        )

        self.assertEqual(
            inventory[1].source_call_id,
            second_source.id,
        )

        self.assertEqual(
            inventory[1].callback_count,
            0,
        )

    def test_resolved_follow_up_is_excluded_from_pending_inventory(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600500008",
                status=CALL_STATUS_MISSED,
            )
        )

        pending = (
            self.repo
            .get_or_create_call_follow_up(
                source.id
            )
        )

        resolved = (
            transition_call_follow_up(
                pending,
                CALL_FOLLOW_UP_RESOLVED,
                resolved_at=(
                    "2026-08-14T16:20:00+02:00"
                ),
            )
        )

        self.repo.update_call_follow_up(
            resolved
        )

        inventory = (
            self.repo
            .list_pending_call_follow_ups()
        )

        self.assertNotIn(
            source.id,
            {
                item.source_call_id
                for item in inventory
            },
        )

    def test_callback_reverse_lookup(
        self,
    ):
        source = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600600001",
                status=CALL_STATUS_MISSED,
            )
        )

        self.repo.get_or_create_call_follow_up(
            source.id
        )

        callback = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_OUTBOUND,
                phone_number="+34600600001",
            )
        )

        linked = self.repo.link_callback_call(
            source_call_id=source.id,
            callback_call_id=callback.id,
        )

        found = (
            self.repo
            .get_call_callback_by_callback_call(
                callback.id
            )
        )

        self.assertEqual(
            found,
            linked,
        )

        self.assertEqual(
            found.source_call_id,
            source.id,
        )

    def test_provider_call_identity_is_idempotent(
        self,
    ):
        first_candidate = CommunicationCall(
            id=None,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600710001",
            provider=" mobile_link ",
            provider_call_id=" raw-001 ",
            external_call_key=" stable-001 ",
        )

        second_candidate = CommunicationCall(
            id=None,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600710001",
            provider="MOBILE_LINK",
            provider_call_id="raw-001",
            external_call_key="stable-001",
        )

        first, first_created = (
            self.repo
            .get_or_create_call_with_identity(
                first_candidate
            )
        )

        second, second_created = (
            self.repo
            .get_or_create_call_with_identity(
                second_candidate
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
            first.provider,
            "MOBILE_LINK",
        )

        self.assertEqual(
            first.provider_call_id,
            "raw-001",
        )

        self.assertEqual(
            first.external_call_key,
            "stable-001",
        )

        found = (
            self.repo
            .get_call_by_provider_identity(
                provider=" mobile_link ",
                external_call_key=" stable-001 ",
            )
        )

        self.assertEqual(
            found.id,
            first.id,
        )

    def test_provider_call_identity_is_scoped_by_provider(
        self,
    ):
        mobile, mobile_created = (
            self.repo
            .get_or_create_call_with_identity(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_PHONE,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600710002",
                    provider="MOBILE_LINK",
                    external_call_key="shared-key",
                )
            )
        )

        whatsapp, whatsapp_created = (
            self.repo
            .get_or_create_call_with_identity(
                CommunicationCall(
                    id=None,
                    channel=CHANNEL_WHATSAPP,
                    direction=DIRECTION_INBOUND,
                    phone_number="+34600710002",
                    provider="WHATSAPP_WEB",
                    external_call_key="shared-key",
                )
            )
        )

        self.assertTrue(
            mobile_created
        )

        self.assertTrue(
            whatsapp_created
        )

        self.assertNotEqual(
            mobile.id,
            whatsapp.id,
        )

    def test_provider_call_unique_index_rejects_raw_duplicate(
        self,
    ):
        candidate = CommunicationCall(
            id=None,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600710003",
            provider="MOBILE_LINK",
            external_call_key="unique-001",
        )

        self.repo.create_call(
            candidate
        )

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.repo.create_call(
                candidate
            )

    def test_external_call_key_requires_provider(
        self,
    ):
        candidate = CommunicationCall(
            id=None,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600710004",
            external_call_key="orphan-key",
        )

        with self.assertRaisesRegex(
            ValueError,
            "requiere provider",
        ):
            (
                self.repo
                .get_or_create_call_with_identity(
                    candidate
                )
            )

    def test_provider_reconciliation_update_preserves_crm_context(
        self,
    ):
        from dataclasses import replace

        stored = self.repo.create_call(
            CommunicationCall(
                id=None,
                channel=CHANNEL_PHONE,
                direction=DIRECTION_INBOUND,
                phone_number="+34600820001",
                client_id=10,
                expedient_id=20,
                display_name_snapshot="CRM NAME",
                reason_code="EXPEDIENT_STATUS",
                notes="CRM NOTE",
                status=CALL_STATUS_RINGING,
                provider="MOBILE_LINK",
                external_call_key="repo-reconcile-001",
                ringing_at=(
                    "2026-08-14T18:10:00+02:00"
                ),
                metadata={
                    "source": "crm",
                },
            )
        )

        candidate = replace(
            stored,
            provider_call_id="raw-repo-001",
            status=CALL_STATUS_MISSED,
            ended_at=(
                "2026-08-14T18:10:09+02:00"
            ),
            ring_duration_seconds=9,
            talk_duration_seconds=0,
            total_duration_seconds=9,
            metadata={
                "source": "crm",
                "history": True,
            },
        )

        updated = (
            self.repo
            .update_call_provider_reconciliation(
                candidate
            )
        )

        self.assertEqual(
            updated.provider_call_id,
            "raw-repo-001",
        )

        self.assertEqual(
            updated.status,
            CALL_STATUS_MISSED,
        )

        self.assertEqual(
            updated.client_id,
            10,
        )

        self.assertEqual(
            updated.expedient_id,
            20,
        )

        self.assertEqual(
            updated.phone_number,
            "+34600820001",
        )

        self.assertEqual(
            updated.display_name_snapshot,
            "CRM NAME",
        )

        self.assertEqual(
            updated.reason_code,
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            updated.notes,
            "CRM NOTE",
        )

        self.assertTrue(
            updated.metadata["history"]
        )

    def test_provider_reconciliation_requires_external_identity(
        self,
    ):
        call = CommunicationCall(
            id=999,
            channel=CHANNEL_PHONE,
            direction=DIRECTION_INBOUND,
            phone_number="+34600820002",
            status=CALL_STATUS_MISSED,
        )

        with self.assertRaisesRegex(
            ValueError,
            "identidad externa",
        ):
            (
                self.repo
                .update_call_provider_reconciliation(
                    call
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
