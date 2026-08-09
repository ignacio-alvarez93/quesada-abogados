import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
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
        self.tmpdir = (
            tempfile.TemporaryDirectory()
        )

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

    def _future_anchor(self):
        return (
            datetime.now()
            + timedelta(days=10)
        ).replace(
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )

    def _create_series(
        self,
        *,
        end_type="NEVER",
        max_occurrences=None,
    ):
        event_at = self._future_anchor()

        warning_at = (
            event_at
            - timedelta(
                days=2,
                hours=3,
            )
        )

        return (
            recurrence_app
            .create_recurring_alert(
                titulo="Renovar documentación",
                descripcion="Aviso recurrente",
                cliente_id=31,
                expediente_id=43,
                prioridad="ALTA",
                fecha_evento=event_at,
                fecha_inicio_aviso=warning_at,
                frequency_unit="MONTH",
                interval_value=1,
                end_type=end_type,
                max_occurrences=max_occurrences,
                db_path=self.db_path,
            )
        )

    def test_create_series_creates_root_alert_and_rule(
        self,
    ):
        result = self._create_series()

        self.assertEqual(
            result["alert"]["cliente_id"],
            31,
        )

        self.assertEqual(
            result["alert"][
                "numero_expediente"
            ],
            "EXP-2026-0026",
        )

        self.assertEqual(
            result["recurrence"][
                "root_alert_id"
            ],
            result["alert"]["id"],
        )

        self.assertEqual(
            result["recurrence"][
                "occurrences_generated"
            ],
            1,
        )

    def test_root_alert_schedules_telegram(
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

        self.assertEqual(
            len(notifications),
            1,
        )

        self.assertEqual(
            notifications[0]["estado"],
            "PENDIENTE",
        )

    def test_materialize_next_creates_real_alert(
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

        alert = occurrence[
            "alert"
        ]

        self.assertNotEqual(
            alert["id"],
            result["alert"]["id"],
        )

        self.assertEqual(
            alert["cliente_id"],
            31,
        )

        self.assertEqual(
            alert["numero_expediente"],
            "EXP-2026-0026",
        )

        self.assertEqual(
            alert["titulo"],
            "Renovar documentación",
        )

        self.assertEqual(
            occurrence[
                "occurrence_index"
            ],
            2,
        )

    def test_materialized_alert_schedules_telegram(
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

        notifications = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                occurrence["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(notifications),
            1,
        )

        self.assertEqual(
            notifications[0]["estado"],
            "PENDIENTE",
        )

    def test_warning_offset_is_preserved(
        self,
    ):
        result = self._create_series()

        root = result[
            "alert"
        ]

        occurrence = (
            recurrence_app
            .materialize_next_occurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        child = occurrence[
            "alert"
        ]

        root_event = datetime.fromisoformat(
            root["fecha_evento"]
        )

        root_warning = datetime.fromisoformat(
            root["fecha_inicio_aviso"]
        )

        child_event = datetime.fromisoformat(
            child["fecha_evento"]
        )

        child_warning = datetime.fromisoformat(
            child["fecha_inicio_aviso"]
        )

        self.assertEqual(
            root_event - root_warning,
            child_event - child_warning,
        )

    def test_materialize_three_occurrences(
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
            4,
        )

        occurrences = (
            calendar_alert_recurrence_service
            .list_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(occurrences),
            4,
        )

        self.assertEqual(
            [
                item["occurrence_index"]
                for item in occurrences
            ],
            [1, 2, 3, 4],
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
                count=10,
                db_path=self.db_path,
            )
        )

        # El aviso raíz cuenta como ocurrencia 1,
        # por tanto solamente se crean 2 adicionales.
        self.assertEqual(
            len(created),
            2,
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
            recurrence["activo"],
            0,
        )

        self.assertIsNone(
            recurrence[
                "next_occurrence_at"
            ]
        )

    def test_occurrence_source_key_is_idempotent(
        self,
    ):
        result = self._create_series()

        first = (
            recurrence_app
            .materialize_next_occurrence(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            first["alert"][
                "source_key"
            ].startswith(
                "CALENDAR_RECURRENCE:"
            )
        )

        occurrences = (
            calendar_alert_recurrence_service
            .list_occurrences(
                result["recurrence"]["id"],
                db_path=self.db_path,
            )
        )

        keys = {
            item["occurrence_index"]
            for item in occurrences
        }

        self.assertEqual(
            keys,
            {1, 2},
        )


if __name__ == "__main__":
    unittest.main()
