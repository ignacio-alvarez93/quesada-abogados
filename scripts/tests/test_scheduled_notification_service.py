import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.services import task_service
from backend.services import calendar_alert_service
from backend.services import scheduled_notification_service


class ScheduledNotificationServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "scheduled.db"
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
            INSERT INTO clientes
            VALUES (
                1,
                'MOHAMED',
                'PRUEBA',
                ''
            )
            """
        )

        conn.execute(
            """
            INSERT INTO expedientes
            VALUES (
                10,
                1,
                'EXP-TEST-001'
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

    def tearDown(self):
        self.tmpdir.cleanup()

    def _task(self):
        return task_service.create_task(
            titulo="Presentar expediente",
            cliente_id=1,
            expediente_id=10,
            prioridad="ALTA",
            fecha_vencimiento=(
                "2026-01-13 12:00"
            ),
            db_path=self.db_path,
        )["task"]

    def _alert(self):
        return (
            calendar_alert_service
            .create_alert(
                titulo=(
                    "Caducan los penales"
                ),
                cliente_id=1,
                expediente_id=10,
                tipo=(
                    "CADUCIDAD_DOCUMENTO"
                ),
                fecha_evento=(
                    "2026-01-14 00:00"
                ),
                fecha_inicio_aviso=(
                    "2026-01-13 09:00"
                ),
                db_path=self.db_path,
            )["alert"]
        )

    def test_task_and_alert_share_outbox(
        self,
    ):
        task = self._task()
        alert = self._alert()

        scheduled_notification_service \
            .schedule_task_notifications(
                task,
                db_path=self.db_path,
            )

        scheduled_notification_service \
            .schedule_alert_notification(
                alert,
                db_path=self.db_path,
            )

        conn = sqlite3.connect(
            self.db_path
        )

        rows = conn.execute(
            """
            SELECT
                source_type,
                COUNT(*)
            FROM scheduled_notifications
            GROUP BY source_type
            ORDER BY source_type
            """
        ).fetchall()

        conn.close()

        counts = dict(rows)

        self.assertEqual(
            counts["TASK"],
            2,
        )

        self.assertEqual(
            counts["ALERT"],
            1,
        )

    def test_alert_notification_is_idempotent(
        self,
    ):
        alert = self._alert()

        first = (
            scheduled_notification_service
            .schedule_alert_notification(
                alert,
                db_path=self.db_path,
            )
        )

        second = (
            scheduled_notification_service
            .schedule_alert_notification(
                alert,
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            first["created"]
        )

        self.assertFalse(
            second["created"]
        )

        self.assertEqual(
            first["notification"]["id"],
            second["notification"]["id"],
        )

    def test_alert_uses_warning_start_date(
        self,
    ):
        alert = self._alert()

        result = (
            scheduled_notification_service
            .schedule_alert_notification(
                alert,
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["notification"][
                "scheduled_at"
            ].startswith(
                "2026-01-13 09:00"
            )
        )

    def test_due_returns_task_context(
        self,
    ):
        task = self._task()

        scheduled_notification_service \
            .schedule_task_notifications(
                task,
                db_path=self.db_path,
            )

        due = (
            scheduled_notification_service
            .list_due_notifications(
                now=datetime(
                    2026,
                    1,
                    13,
                    13,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        task_items = [
            item
            for item in due
            if item["source_type"]
            == "TASK"
        ]

        self.assertTrue(
            task_items
        )

        source = (
            task_items[0]
            ["delivery_context"]
            ["source"]
        )

        self.assertEqual(
            source["numero_expediente"],
            "EXP-TEST-001",
        )

    def test_due_returns_alert_context(
        self,
    ):
        alert = self._alert()

        scheduled_notification_service \
            .schedule_alert_notification(
                alert,
                db_path=self.db_path,
            )

        due = (
            scheduled_notification_service
            .list_due_notifications(
                now=datetime(
                    2026,
                    1,
                    13,
                    10,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(due),
            1,
        )

        self.assertEqual(
            due[0]["source_type"],
            "ALERT",
        )

        source = (
            due[0]
            ["delivery_context"]
            ["source"]
        )

        self.assertEqual(
            source["titulo"],
            "Caducan los penales",
        )

    def test_resolved_alert_is_not_delivered(
        self,
    ):
        alert = self._alert()

        scheduled_notification_service \
            .schedule_alert_notification(
                alert,
                db_path=self.db_path,
            )

        calendar_alert_service \
            .resolve_alert(
                alert["id"],
                db_path=self.db_path,
            )

        due = (
            scheduled_notification_service
            .list_due_notifications(
                now=datetime(
                    2026,
                    1,
                    14,
                    12,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            due,
            [],
        )

    def test_completed_task_is_not_delivered(
        self,
    ):
        task = self._task()

        scheduled_notification_service \
            .schedule_task_notifications(
                task,
                db_path=self.db_path,
            )

        task_service.complete_task(
            task["id"],
            db_path=self.db_path,
        )

        due = (
            scheduled_notification_service
            .list_due_notifications(
                now=datetime(
                    2026,
                    1,
                    14,
                    12,
                    0,
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            due,
            [],
        )

    def test_delivery_states(self):
        alert = self._alert()

        notification = (
            scheduled_notification_service
            .schedule_alert_notification(
                alert,
                db_path=self.db_path,
            )["notification"]
        )

        processing = (
            scheduled_notification_service
            .mark_processing(
                notification["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            processing["estado"],
            "PROCESANDO",
        )

        self.assertEqual(
            processing["attempt_count"],
            1,
        )

        error = (
            scheduled_notification_service
            .mark_error(
                notification["id"],
                "Sin conexión",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            error["estado"],
            "ERROR",
        )

        sent = (
            scheduled_notification_service
            .mark_sent(
                notification["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            sent["estado"],
            "ENVIADA",
        )

        self.assertIsNotNone(
            sent["sent_at"]
        )


if __name__ == "__main__":
    unittest.main()
