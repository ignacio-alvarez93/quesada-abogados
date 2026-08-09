import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.services import (
    task_service,
    calendar_alert_service,
    scheduled_notification_service,
    calendar_service,
)


class CalendarServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "calendar.db"
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

        conn.execute(
            """
            INSERT INTO clientes
            VALUES (
                1,
                'ANA',
                'GUILHERME',
                'BORGES'
            )
            """
        )

        conn.execute(
            """
            INSERT INTO expedientes
            VALUES (
                10,
                1,
                'EXP-2026-0022'
            )
            """
        )

        conn.commit()
        conn.close()

        task_service.ensure_task_schema(
            db_path=self.db_path
        )

        calendar_alert_service \
            .ensure_calendar_alert_schema(
                db_path=self.db_path
            )

        scheduled_notification_service \
            .ensure_schema(
                db_path=self.db_path
            )

        self.task = (
            task_service.create_task(
                titulo="Presentar EX-02",
                descripcion="Solicitud inicial",
                cliente_id=1,
                expediente_id=10,
                prioridad="ALTA",
                responsable="Nacho",
                fecha_vencimiento=(
                    "2026-08-10 09:00:00"
                ),
                db_path=self.db_path,
            )["task"]
        )

        self.alert = (
            calendar_alert_service
            .create_alert(
                titulo="Caducan penales",
                descripcion=(
                    "Renovar certificado"
                ),
                cliente_id=1,
                expediente_id=10,
                prioridad="URGENTE",
                fecha_evento=(
                    "2026-08-11 10:30:00"
                ),
                fecha_inicio_aviso=(
                    "2026-08-10 10:30:00"
                ),
                db_path=self.db_path,
            )["alert"]
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_projection_returns_both_domains(
        self,
    ):
        items = (
            calendar_service
            .list_calendar_items(
                db_path=self.db_path
            )
        )

        self.assertEqual(
            len(items),
            2,
        )

        self.assertEqual(
            {
                item["item_type"]
                for item in items
            },
            {
                "TASK",
                "ALERT",
            },
        )

    def test_projection_contract(
        self,
    ):
        items = (
            calendar_service
            .list_calendar_items(
                db_path=self.db_path
            )
        )

        task = items[0]

        self.assertEqual(
            task["item_type"],
            "TASK",
        )

        self.assertEqual(
            task["client_name"],
            "ANA GUILHERME BORGES",
        )

        self.assertEqual(
            task["expedient_number"],
            "EXP-2026-0022",
        )

        self.assertEqual(
            task["responsible"],
            "Nacho",
        )

    def test_range_filter(
        self,
    ):
        items = (
            calendar_service
            .list_calendar_items(
                start_at=(
                    "2026-08-10 00:00:00"
                ),
                end_at=(
                    "2026-08-10 23:59:59"
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            1,
        )

        self.assertEqual(
            items[0]["title"],
            "Presentar EX-02",
        )

    def test_type_filter(
        self,
    ):
        items = (
            calendar_service
            .list_calendar_items(
                item_type="ALERT",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            1,
        )

        self.assertEqual(
            items[0]["title"],
            "Caducan penales",
        )

    def test_search(
        self,
    ):
        items = (
            calendar_service
            .list_calendar_items(
                search="GUILHERME",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            2,
        )

    def test_upcoming(
        self,
    ):
        items = (
            calendar_service
            .get_upcoming_items(
                now=datetime(
                    2026,
                    8,
                    10,
                    8,
                    0,
                ),
                days=7,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            2,
        )

    def test_summary(
        self,
    ):
        scheduled_notification_service \
            .schedule_task_notifications(
                self.task,
                db_path=self.db_path,
            )

        summary = (
            calendar_service
            .get_calendar_summary(
                now=datetime(
                    2026,
                    8,
                    10,
                    8,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            summary["pending_tasks"],
            1,
        )

        self.assertEqual(
            summary["due_today"],
            1,
        )

        self.assertEqual(
            summary["next_7_days"],
            2,
        )

        self.assertEqual(
            summary["critical_alerts"],
            1,
        )

        self.assertGreaterEqual(
            summary["pending_telegram"],
            1,
        )

    def test_day_summary(
        self,
    ):
        summary = (
            calendar_service
            .get_day_summary(
                "2026-08-11",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            summary["alerts"],
            1,
        )

        self.assertEqual(
            summary["tasks"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
