import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend.services import task_service
from backend.services import (
    task_notification_service,
)


class TaskNotificationServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "task_notifications.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )

        conn.execute(
            """
            PRAGMA foreign_keys = ON
            """
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
                1,
                'CLIENTE',
                'PRUEBA',
                ''
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

        task_notification_service \
            .ensure_notification_schema(
                db_path=self.db_path
            )

    def tearDown(self):
        self.tmpdir.cleanup()

    def create_task(
        self,
        *,
        prioridad="NORMAL",
        due="2030-08-10 12:00",
    ):
        return task_service.create_task(
            titulo="Tarea de prueba",
            cliente_id=1,
            expediente_id=10,
            prioridad=prioridad,
            fecha_vencimiento=due,
            db_path=self.db_path,
        )["task"]

    def test_create_notification(self):
        task = self.create_task()

        result = (
            task_notification_service
            .create_notification(
                task_id=task["id"],
                scheduled_at=(
                    "2030-08-10 12:00"
                ),
                notification_type=(
                    "VENCIMIENTO"
                ),
                source_key=(
                    f"TASK:{task['id']}:"
                    "TELEGRAM:VENCIMIENTO"
                ),
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["created"]
        )

        self.assertEqual(
            result["notification"][
                "estado"
            ],
            "PENDIENTE",
        )

    def test_notification_is_idempotent(
        self,
    ):
        task = self.create_task()

        kwargs = {
            "task_id": task["id"],
            "scheduled_at":
                "2030-08-10 12:00",
            "notification_type":
                "VENCIMIENTO",
            "source_key":
                f"TASK:{task['id']}:"
                "TELEGRAM:VENCIMIENTO",
            "db_path":
                self.db_path,
        }

        first = (
            task_notification_service
            .create_notification(
                **kwargs
            )
        )

        second = (
            task_notification_service
            .create_notification(
                **kwargs
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

    def test_normal_priority_creates_one(
        self,
    ):
        task = self.create_task(
            prioridad="NORMAL"
        )

        task_notification_service \
            .schedule_default_telegram_notifications(
                task,
                db_path=self.db_path,
            )

        items = (
            task_notification_service
            .get_notifications_for_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            1,
        )

        self.assertEqual(
            items[0]["notification_type"],
            "VENCIMIENTO",
        )

    def test_high_priority_creates_two(
        self,
    ):
        task = self.create_task(
            prioridad="ALTA"
        )

        task_notification_service \
            .schedule_default_telegram_notifications(
                task,
                db_path=self.db_path,
            )

        items = (
            task_notification_service
            .get_notifications_for_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            2,
        )

    def test_urgent_priority_creates_three(
        self,
    ):
        task = self.create_task(
            prioridad="URGENTE"
        )

        task_notification_service \
            .schedule_default_telegram_notifications(
                task,
                db_path=self.db_path,
            )

        items = (
            task_notification_service
            .get_notifications_for_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            3,
        )

    def test_policy_is_idempotent(self):
        task = self.create_task(
            prioridad="URGENTE"
        )

        for _ in range(3):
            task_notification_service \
                .schedule_default_telegram_notifications(
                    task,
                    db_path=self.db_path,
                )

        items = (
            task_notification_service
            .get_notifications_for_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            3,
        )

    def test_due_notifications(self):
        reference_now = datetime.now().replace(
            microsecond=0
        )

        due_at = (
            reference_now
            + timedelta(minutes=5)
        )

        task = self.create_task(
            due=due_at.isoformat(
                sep=" "
            )
        )

        task_notification_service \
            .schedule_default_telegram_notifications(
                task,
                db_path=self.db_path,
            )

        due = (
            task_notification_service
            .list_due_notifications(
                now=(
                    due_at
                    + timedelta(hours=1)
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(due),
            1,
        )

        self.assertEqual(
            due[0]["numero_expediente"],
            "EXP-TEST-001",
        )

    def test_delivery_state_transitions(
        self,
    ):
        task = self.create_task(
            due="2026-08-07 10:00"
        )

        result = (
            task_notification_service
            .schedule_default_telegram_notifications(
                task,
                db_path=self.db_path,
            )[0]
        )

        notification_id = (
            result[
                "notification"
            ]["id"]
        )

        processing = (
            task_notification_service
            .mark_processing(
                notification_id,
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
            task_notification_service
            .mark_error(
                notification_id,
                "Telegram no disponible",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            error["estado"],
            "ERROR",
        )

        sent = (
            task_notification_service
            .mark_sent(
                notification_id,
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

        self.assertIsNone(
            sent["last_error"]
        )

    def test_cancel_pending_for_task(self):
        task = self.create_task(
            prioridad="URGENTE"
        )

        task_notification_service \
            .schedule_default_telegram_notifications(
                task,
                db_path=self.db_path,
            )

        cancelled = (
            task_notification_service
            .cancel_pending_for_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            cancelled,
            3,
        )

        active = (
            task_notification_service
            .get_notifications_for_task(
                task["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            active,
            [],
        )


if __name__ == "__main__":
    unittest.main()
