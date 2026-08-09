import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.services import (
    calendar_alert_service,
    scheduled_notification_service,
    calendar_alert_recurrence_service,
    calendar_alert_recurrence_application_service
    as recurrence_app,
)


class CalendarAlertRecurrenceApplicationServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "recurrence-app.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
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

        conn.execute(
            """
            INSERT INTO clientes (
                id,
                nombre,
                primer_apellido,
                segundo_apellido
            )
            VALUES (
                31,
                'WENDY VANESSA',
                'RAMIREZ',
                'VELASQUEZ'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente
            )
            VALUES (
                43,
                31,
                'EXP-2026-0026'
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
            scheduled_notification_service
            .ensure_schema(
                db_path=self.db_path
            )
        )

        (
            calendar_alert_recurrence_service
            .ensure_schema(
                db_path=self.db_path
            )
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _event_at(self):
        return datetime(
            2026,
            8,
            15,
            9,
            0,
        )

    def _warning_at(self):
        return datetime(
            2026,
            8,
            9,
            9,
            0,
        )

    def _create_series(
        self,
        *,
        end_type="NEVER",
        end_date=None,
        max_occurrences=None,
    ):
        return (
            recurrence_app
            .create_recurring_alert(
                titulo=(
                    "Renovar documentación"
                ),
                descripcion=(
                    "Aviso recurrente"
                ),
                cliente_id=31,
                expediente_id=43,
                prioridad="ALTA",
                fecha_evento=(
                    self._event_at()
                ),
                fecha_inicio_aviso=(
                    self._warning_at()
                ),
                frequency_unit="DAY",
                interval_value=1,
                end_type=end_type,
                end_date=end_date,
                max_occurrences=(
                    max_occurrences
                ),
                db_path=self.db_path,
            )
        )

    def test_create_series_creates_one_alert_and_rule(
        self,
    ):
        result = self._create_series()

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

        alert = result["alert"]

        self.assertEqual(
            alert["cliente_id"],
            31,
        )

        self.assertEqual(
            alert["numero_expediente"],
            "EXP-2026-0026",
        )

        self.assertEqual(
            result["recurrence"][
                "root_alert_id"
            ],
            alert["id"],
        )

        self.assertEqual(
            result["recurrence"][
                "anchor_at"
            ],
            "2026-08-09 09:00:00",
        )

    def test_root_notification_is_first_occurrence(
        self,
    ):
        result = self._create_series()

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(notifications),
            1,
        )

        self.assertEqual(
            notifications[0][
                "scheduled_at"
            ],
            "2026-08-09 09:00:00",
        )

        self.assertEqual(
            len(mappings),
            1,
        )

        self.assertEqual(
            mappings[0][
                "occurrence_index"
            ],
            1,
        )

        legacy_occurrences = (
            calendar_alert_recurrence_service
            .list_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            legacy_occurrences,
            [],
        )


    def test_next_occurrence_reuses_same_alert(
        self,
    ):
        result = self._create_series()

        occurrence = (
            recurrence_app
            .materialize_next_occurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertIsNotNone(
            occurrence
        )

        self.assertEqual(
            occurrence["alert"]["id"],
            result["alert"]["id"],
        )

        self.assertEqual(
            occurrence["scheduled_at"],
            "2026-08-10 09:00:00",
        )

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

    def test_recurrent_notifications_use_root_alert(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=3,
                db_path=self.db_path,
            )
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(notifications),
            4,
        )

        self.assertTrue(
            all(
                item["source_id"]
                == result["alert"]["id"]
                for item in notifications
            )
        )

    def test_materialize_three_creates_notifications_not_alerts(
        self,
    ):
        result = self._create_series()

        created = (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=3,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(created),
            3,
        )

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["scheduled_at"]
                for item in notifications
            ],
            [
                "2026-08-09 09:00:00",
                "2026-08-10 09:00:00",
                "2026-08-11 09:00:00",
                "2026-08-12 09:00:00",
            ],
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["occurrence_index"]
                for item in mappings
            ],
            [1, 2, 3, 4],
        )

    def test_event_date_is_natural_limit(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=20,
                db_path=self.db_path,
            )
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["scheduled_at"]
                for item in notifications
            ],
            [
                "2026-08-09 09:00:00",
                "2026-08-10 09:00:00",
                "2026-08-11 09:00:00",
                "2026-08-12 09:00:00",
                "2026-08-13 09:00:00",
                "2026-08-14 09:00:00",
                "2026-08-15 09:00:00",
            ],
        )

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence[
                "occurrences_generated"
            ],
            7,
        )

        self.assertEqual(
            recurrence["estado"],
            "FINALIZADA",
        )

        self.assertEqual(
            recurrence["activo"],
            0,
        )

        self.assertIsNone(
            recurrence[
                "next_occurrence_at"
            ]
        )

    def test_count_series_stops_exactly(
        self,
    ):
        result = self._create_series(
            end_type="COUNT",
            max_occurrences=3,
        )

        created = (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=20,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(created),
            2,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(notifications),
            3,
        )

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence[
                "occurrences_generated"
            ],
            3,
        )

        self.assertEqual(
            recurrence["estado"],
            "FINALIZADA",
        )

        self.assertEqual(
            recurrence["activo"],
            0,
        )

    def test_recurrent_notification_source_keys_are_unique(
        self,
    ):
        result = self._create_series()

        (
            recurrence_app
            .materialize_occurrences(
                result["recurrence"]["id"],
                count=3,
                db_path=self.db_path,
            )
        )

        mappings = (
            calendar_alert_recurrence_service
            .list_notification_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(mappings),
            4,
        )

        generated = mappings[1:]

        self.assertEqual(
            [
                item["source_key"]
                for item in generated
            ],
            [
                (
                    "ALERT_RECURRENCE:"
                    f"{result['recurrence']['id']}:2"
                ),
                (
                    "ALERT_RECURRENCE:"
                    f"{result['recurrence']['id']}:3"
                ),
                (
                    "ALERT_RECURRENCE:"
                    f"{result['recurrence']['id']}:4"
                ),
            ],
        )


    def test_materialize_until_event_limit(
        self,
    ):
        result = self._create_series()

        created = (
            recurrence_app
            .materialize_until_limit(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        # El 09/08 ya existe como primer aviso.
        # Se generan 10, 11, 12, 13, 14 y 15.
        self.assertEqual(
            len(created),
            6,
        )

        alerts = (
            calendar_alert_service
            .list_alerts(
                include_archived=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(alerts),
            1,
        )

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            [
                item["scheduled_at"]
                for item in notifications
            ],
            [
                "2026-08-09 09:00:00",
                "2026-08-10 09:00:00",
                "2026-08-11 09:00:00",
                "2026-08-12 09:00:00",
                "2026-08-13 09:00:00",
                "2026-08-14 09:00:00",
                "2026-08-15 09:00:00",
            ],
        )

        recurrence = (
            calendar_alert_recurrence_service
            .get_recurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            recurrence[
                "occurrences_generated"
            ],
            7,
        )

        self.assertEqual(
            recurrence["estado"],
            "FINALIZADA",
        )

        self.assertEqual(
            recurrence["activo"],
            0,
        )

        self.assertIsNone(
            recurrence[
                "next_occurrence_at"
            ]
        )



if __name__ == "__main__":
    unittest.main()
