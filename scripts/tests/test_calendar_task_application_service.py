import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import task_service
from backend.services import scheduled_notification_service
from backend.services import calendar_task_application_service as app_service


class CalendarTaskApplicationServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "calendar_task_app.db"
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

        scheduled_notification_service \
            .ensure_schema(
                db_path=self.db_path
            )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create(self, priority="ALTA"):
        return (
            app_service
            .create_calendar_task(
                titulo="Presentar expediente",
                fecha_vencimiento=(
                    "2026-08-20 10:00:00"
                ),
                cliente_id=1,
                expediente_id=10,
                prioridad=priority,
                responsable="Nacho",
                db_path=self.db_path,
            )
        )

    def _notifications(self, task_id):
        return (
            scheduled_notification_service
            .list_for_source(
                "TASK",
                task_id,
                include_inactive=True,
                db_path=self.db_path,
            )
        )

    def test_create_generates_notifications(
        self,
    ):
        result = self._create()

        task = result["task"]

        self.assertTrue(
            result["created"]
        )

        self.assertEqual(
            len(result["notifications"]),
            2,
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "TASK",
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(active),
            2,
        )

    def test_normal_priority_generates_one(
        self,
    ):
        result = self._create(
            priority="NORMAL"
        )

        self.assertEqual(
            len(result["notifications"]),
            1,
        )

    def test_update_title_does_not_reschedule(
        self,
    ):
        task = self._create()["task"]

        before = self._notifications(
            task["id"]
        )

        result = (
            app_service
            .update_calendar_task(
                task["id"],
                titulo="Presentar EX-02",
                db_path=self.db_path,
            )
        )

        after = self._notifications(
            task["id"]
        )

        self.assertFalse(
            result["schedule_changed"]
        )

        self.assertEqual(
            len(before),
            len(after),
        )

    def test_update_due_date_reschedules(
        self,
    ):
        task = self._create()["task"]

        result = (
            app_service
            .update_calendar_task(
                task["id"],
                fecha_vencimiento=(
                    "2026-08-21 12:00:00"
                ),
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["schedule_changed"]
        )

        rows = self._notifications(
            task["id"]
        )

        old_cancelled = [
            row
            for row in rows
            if row["estado"]
            == "CANCELADA"
        ]

        active = [
            row
            for row in rows
            if row["activo"] == 1
        ]

        self.assertEqual(
            len(old_cancelled),
            2,
        )

        self.assertEqual(
            len(active),
            2,
        )

        self.assertTrue(
            all(
                "2026-08-21"
                in row["scheduled_at"]
                or "2026-08-20"
                in row["scheduled_at"]
                for row in active
            )
        )

    def test_complete_cancels_pending(
        self,
    ):
        task = self._create()["task"]

        completed = (
            app_service
            .complete_calendar_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            completed["estado"],
            "COMPLETADA",
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "TASK",
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            active,
            [],
        )

    def test_cancel_cancels_pending(
        self,
    ):
        task = self._create()["task"]

        cancelled = (
            app_service
            .cancel_calendar_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            cancelled["estado"],
            "CANCELADA",
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "TASK",
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            active,
            [],
        )

    def test_reopen_creates_new_revision(
        self,
    ):
        task = self._create()["task"]

        (
            app_service
            .complete_calendar_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        result = (
            app_service
            .reopen_calendar_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            result["task"]["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            len(result["notifications"]),
            2,
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "TASK",
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(active),
            2,
        )

    def test_start_preserves_notifications(
        self,
    ):
        task = self._create()["task"]

        before = (
            scheduled_notification_service
            .list_for_source(
                "TASK",
                task["id"],
                db_path=self.db_path,
            )
        )

        started = (
            app_service
            .start_calendar_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        after = (
            scheduled_notification_service
            .list_for_source(
                "TASK",
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            started["estado"],
            "EN_CURSO",
        )

        self.assertEqual(
            len(before),
            len(after),
        )


if __name__ == "__main__":
    unittest.main()
