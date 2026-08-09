import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

MIGRATIONS = [
    ROOT
    / "database/migrations/"
    "20260807_01_create_task_system.sql",

    ROOT
    / "database/migrations/"
    "20260807_02_create_calendar_alerts.sql",

    ROOT
    / "database/migrations/"
    "20260807_03_create_scheduled_notifications.sql",

    ROOT
    / "database/migrations/"
    "20260809_01_create_calendar_alert_recurrences.sql",

    ROOT
    / "database/migrations/"
    "20260809_02_create_calendar_alert_recurrence_notifications.sql",
]


class CalendarMigrationsCleanInstallTestCase(
    unittest.TestCase
):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "calendar_clean_install.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )

        try:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            conn.executescript(
                """
                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY
                );

                INSERT INTO clientes (id)
                VALUES (1);

                INSERT INTO expedientes (id)
                VALUES (1);
                """
            )

            conn.commit()

        finally:
            conn.close()

    def tearDown(self):
        self.tmpdir.cleanup()

    def apply_migrations(self):
        conn = sqlite3.connect(
            self.db_path
        )

        try:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            for path in MIGRATIONS:
                self.assertTrue(
                    path.exists(),
                    str(path),
                )

                conn.executescript(
                    path.read_text(
                        encoding="utf-8"
                    )
                )

            conn.commit()

        finally:
            conn.close()

    def table_names(self):
        conn = sqlite3.connect(
            self.db_path
        )

        try:
            return {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }

        finally:
            conn.close()

    def test_clean_install_creates_calendar_schema(
        self,
    ):
        self.apply_migrations()

        names = self.table_names()

        expected = {
            "tasks",
            "calendar_alerts",
            "scheduled_notifications",
            "calendar_alert_recurrences",
            (
                "calendar_alert_"
                "recurrence_occurrences"
            ),
            (
                "calendar_alert_"
                "recurrence_notifications"
            ),
        }

        self.assertTrue(
            expected.issubset(names)
        )

        self.assertNotIn(
            "task_notifications",
            names,
        )

    def test_notification_schema_accepts_lifecycle_states(
        self,
    ):
        self.apply_migrations()

        conn = sqlite3.connect(
            self.db_path
        )

        try:
            conn.execute(
                """
                INSERT INTO tasks (
                    id,
                    titulo,
                    fecha_vencimiento
                )
                VALUES (
                    1,
                    'Prueba',
                    '2030-01-01 12:00:00'
                )
                """
            )

            for index, state in enumerate(
                (
                    "PAUSADA",
                    "OMITIDA",
                ),
                start=1,
            ):
                conn.execute(
                    """
                    INSERT INTO scheduled_notifications (
                        source_type,
                        source_id,
                        notification_type,
                        scheduled_at,
                        estado,
                        source_key
                    )
                    VALUES (
                        'TASK',
                        1,
                        'TEST',
                        '2030-01-01 12:00:00',
                        ?,
                        ?
                    )
                    """,
                    (
                        state,
                        f"TEST:{state}:{index}",
                    ),
                )

            conn.commit()

            states = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT estado
                    FROM scheduled_notifications
                    """
                ).fetchall()
            }

            self.assertEqual(
                states,
                {
                    "PAUSADA",
                    "OMITIDA",
                },
            )

        finally:
            conn.close()

    def test_recurrence_schema_contains_lifecycle(
        self,
    ):
        self.apply_migrations()

        conn = sqlite3.connect(
            self.db_path
        )

        try:
            columns = {
                row[1]
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        calendar_alert_recurrences
                    )
                    """
                ).fetchall()
            }

            self.assertIn(
                "estado",
                columns,
            )

        finally:
            conn.close()

    def test_migrations_are_idempotent(
        self,
    ):
        self.apply_migrations()
        self.apply_migrations()

        self.assertIn(
            "scheduled_notifications",
            self.table_names(),
        )

    def test_integrity_is_clean(
        self,
    ):
        self.apply_migrations()

        conn = sqlite3.connect(
            self.db_path
        )

        try:
            self.assertEqual(
                conn.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0],
                "ok",
            )

            self.assertEqual(
                conn.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall(),
                [],
            )

        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
