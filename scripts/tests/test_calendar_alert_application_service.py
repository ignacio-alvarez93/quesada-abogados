import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend.services import calendar_alert_service
from backend.services import calendar_alert_application_service
from backend.services import scheduled_notification_service


class CalendarAlertApplicationServiceTestCase(
    unittest.TestCase
):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "calendar-alert-app.db"
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

    def tearDown(self):
        self.tmpdir.cleanup()

    def _future(
        self,
        *,
        days=3,
        hours=0,
    ):
        return (
            datetime.now()
            + timedelta(
                days=days,
                hours=hours,
            )
        ).replace(
            microsecond=0
        )

    def _create(self):
        event_at = self._future(
            days=5
        )

        warning_at = self._future(
            days=3
        )

        return (
            calendar_alert_application_service
            .create_calendar_alert(
                titulo="Caducidad antecedentes",
                cliente_id=1,
                expediente_id=10,
                prioridad="ALTA",
                fecha_evento=event_at,
                fecha_inicio_aviso=warning_at,
                db_path=self.db_path,
            )
        )

    def test_create_alert_schedules_notification(
        self,
    ):
        result = self._create()

        self.assertTrue(
            result["created"]
        )

        self.assertEqual(
            result["alert"]["estado"],
            "ACTIVO",
        )

        self.assertIsNotNone(
            result["notification"]
        )

        rows = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                result["alert"]["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(rows),
            1,
        )

        self.assertEqual(
            rows[0]["estado"],
            "PENDIENTE",
        )

    def test_update_without_schedule_change_keeps_notification(
        self,
    ):
        result = self._create()

        alert_id = result["alert"]["id"]

        before = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )

        updated = (
            calendar_alert_application_service
            .update_calendar_alert(
                alert_id,
                titulo=(
                    "Caducidad antecedentes editada"
                ),
                db_path=self.db_path,
            )
        )

        after = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertFalse(
            updated["schedule_changed"]
        )

        self.assertIsNone(
            updated["notification"]
        )

        self.assertEqual(
            before[0]["id"],
            after[0]["id"],
        )

    def test_update_warning_date_creates_new_revision(
        self,
    ):
        result = self._create()

        alert_id = result["alert"]["id"]

        old = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )[0]

        new_warning = self._future(
            days=2
        )

        updated = (
            calendar_alert_application_service
            .update_calendar_alert(
                alert_id,
                fecha_inicio_aviso=(
                    new_warning
                ),
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            updated["schedule_changed"]
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )

        history = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(active),
            1,
        )

        self.assertNotEqual(
            active[0]["id"],
            old["id"],
        )

        old_row = next(
            row
            for row in history
            if row["id"] == old["id"]
        )

        self.assertEqual(
            old_row["estado"],
            "CANCELADA",
        )

        self.assertEqual(
            old_row["activo"],
            0,
        )

    def test_update_event_date_replans_when_no_warning_date(
        self,
    ):
        event_at = self._future(
            days=4
        )

        result = (
            calendar_alert_application_service
            .create_calendar_alert(
                titulo="Evento",
                fecha_evento=event_at,
                db_path=self.db_path,
            )
        )

        alert_id = result["alert"]["id"]

        old = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )[0]

        new_event = self._future(
            days=6
        )

        updated = (
            calendar_alert_application_service
            .update_calendar_alert(
                alert_id,
                fecha_evento=new_event,
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            updated["schedule_changed"]
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(active),
            1,
        )

        self.assertNotEqual(
            old["id"],
            active[0]["id"],
        )

    def test_resolve_cancels_pending_notification(
        self,
    ):
        result = self._create()

        alert_id = result["alert"]["id"]

        resolved = (
            calendar_alert_application_service
            .resolve_calendar_alert(
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            resolved["estado"],
            "RESUELTO",
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            active,
            [],
        )

    def test_cancel_cancels_pending_notification(
        self,
    ):
        result = self._create()

        alert_id = result["alert"]["id"]

        cancelled = (
            calendar_alert_application_service
            .cancel_calendar_alert(
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            cancelled["estado"],
            "CANCELADO",
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            active,
            [],
        )

    def test_reopen_creates_new_notification_revision(
        self,
    ):
        result = self._create()

        alert_id = result["alert"]["id"]

        original = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )[0]

        (
            calendar_alert_application_service
            .resolve_calendar_alert(
                alert_id,
                db_path=self.db_path,
            )
        )

        reopened = (
            calendar_alert_application_service
            .reopen_calendar_alert(
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            reopened["alert"]["estado"],
            "ACTIVO",
        )

        self.assertIsNotNone(
            reopened["notification"]
        )

        active = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                alert_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(active),
            1,
        )

        self.assertNotEqual(
            active[0]["id"],
            original["id"],
        )

    def test_source_key_remains_idempotent_on_create(
        self,
    ):
        event_at = self._future(
            days=5
        )

        kwargs = {
            "titulo":
                "Caducidad automática",
            "fecha_evento":
                event_at,
            "source_key":
                "DOC:20:CADUCIDAD",
            "origen_tipo":
                "DOCUMENTO",
            "origen_id":
                "20",
            "db_path":
                self.db_path,
        }

        first = (
            calendar_alert_application_service
            .create_calendar_alert(
                **kwargs
            )
        )

        second = (
            calendar_alert_application_service
            .create_calendar_alert(
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
            first["alert"]["id"],
            second["alert"]["id"],
        )

        history = (
            scheduled_notification_service
            .list_for_source(
                "ALERT",
                first["alert"]["id"],
                include_inactive=True,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(history),
            1,
        )


if __name__ == "__main__":
    unittest.main()
