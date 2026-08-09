import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.services import (
    calendar_alert_service,
    calendar_alert_recurrence_service
    as recurrence_service,
)


class CalendarAlertRecurrenceServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.tmpdir.name)
            / "recurrence.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                numero_expediente TEXT
            )
            """
        )

        conn.commit()
        conn.close()

        (
            calendar_alert_service
            .ensure_calendar_alert_schema(
                db_path=self.db_path
            )
        )

        (
            recurrence_service
            .ensure_schema(
                db_path=self.db_path
            )
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _alert(self):
        return (
            calendar_alert_service
            .create_alert(
                titulo="Aviso recurrente",
                fecha_evento=(
                    "2026-08-09 09:00:00"
                ),
                db_path=self.db_path,
            )["alert"]
        )

    def test_daily_recurrence(self):
        values = (
            recurrence_service
            .preview_occurrences(
                "2026-08-09 09:00:00",
                frequency_unit="DAY",
                interval_value=2,
                limit=3,
            )
        )

        self.assertEqual(
            values,
            [
                datetime(
                    2026, 8, 9, 9, 0
                ),
                datetime(
                    2026, 8, 11, 9, 0
                ),
                datetime(
                    2026, 8, 13, 9, 0
                ),
            ],
        )

    def test_weekly_recurrence(self):
        values = (
            recurrence_service
            .preview_occurrences(
                "2026-08-09 09:00:00",
                frequency_unit="WEEK",
                interval_value=1,
                limit=3,
            )
        )

        self.assertEqual(
            values[1],
            datetime(
                2026,
                8,
                16,
                9,
                0,
            ),
        )

    def test_month_end_preserves_anchor_day(
        self,
    ):
        values = (
            recurrence_service
            .preview_occurrences(
                "2027-01-31 09:00:00",
                frequency_unit="MONTH",
                interval_value=1,
                limit=3,
            )
        )

        self.assertEqual(
            values[0],
            datetime(
                2027, 1, 31, 9, 0
            ),
        )

        self.assertEqual(
            values[1],
            datetime(
                2027, 2, 28, 9, 0
            ),
        )

        self.assertEqual(
            values[2],
            datetime(
                2027, 3, 31, 9, 0
            ),
        )

    def test_leap_year_yearly_recurrence(
        self,
    ):
        values = (
            recurrence_service
            .preview_occurrences(
                "2024-02-29 10:30:00",
                frequency_unit="YEAR",
                interval_value=1,
                limit=3,
            )
        )

        self.assertEqual(
            values[1],
            datetime(
                2025,
                2,
                28,
                10,
                30,
            ),
        )

        self.assertEqual(
            values[2],
            datetime(
                2026,
                2,
                28,
                10,
                30,
            ),
        )

    def test_count_end(self):
        values = (
            recurrence_service
            .preview_occurrences(
                "2026-08-09 09:00:00",
                frequency_unit="MONTH",
                interval_value=1,
                end_type="COUNT",
                max_occurrences=3,
                limit=10,
            )
        )

        self.assertEqual(
            len(values),
            3,
        )

    def test_date_end(self):
        values = (
            recurrence_service
            .preview_occurrences(
                "2026-08-09 09:00:00",
                frequency_unit="MONTH",
                interval_value=1,
                end_type="DATE",
                end_date=(
                    "2026-10-09 09:00:00"
                ),
                limit=10,
            )
        )

        self.assertEqual(
            len(values),
            3,
        )

    def test_create_recurrence(self):
        alert = self._alert()

        recurrence = (
            recurrence_service
            .create_recurrence(
                root_alert_id=alert["id"],
                anchor_at=(
                    alert["fecha_evento"]
                ),
                frequency_unit="MONTH",
                interval_value=3,
                end_type="NEVER",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence[
                "root_alert_id"
            ],
            alert["id"],
        )

        self.assertEqual(
            recurrence[
                "frequency_unit"
            ],
            "MONTH",
        )

        self.assertEqual(
            recurrence[
                "interval_value"
            ],
            3,
        )

        self.assertTrue(
            recurrence[
                "next_occurrence_at"
            ].startswith(
                "2026-11-09"
            )
        )

    def test_root_alert_is_registered_as_occurrence(
        self,
    ):
        alert = self._alert()

        recurrence = (
            recurrence_service
            .create_recurrence(
                root_alert_id=alert["id"],
                anchor_at=(
                    alert["fecha_evento"]
                ),
                frequency_unit="MONTH",
                interval_value=1,
                db_path=self.db_path,
            )
        )

        conn = sqlite3.connect(
            self.db_path
        )

        row = conn.execute(
            """
            SELECT
                alert_id,
                occurrence_index
            FROM
                calendar_alert_recurrence_occurrences
            WHERE recurrence_id = ?
            """,
            (
                recurrence["id"],
            ),
        ).fetchone()

        conn.close()

        self.assertEqual(
            row,
            (
                alert["id"],
                1,
            ),
        )

    def test_recurrence_can_be_found_from_alert(
        self,
    ):
        alert = self._alert()

        created = (
            recurrence_service
            .create_recurrence(
                root_alert_id=alert["id"],
                anchor_at=(
                    alert["fecha_evento"]
                ),
                frequency_unit="YEAR",
                interval_value=1,
                db_path=self.db_path,
            )
        )

        found = (
            recurrence_service
            .get_recurrence_for_alert(
                alert["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            found["id"],
            created["id"],
        )


if __name__ == "__main__":
    unittest.main()
