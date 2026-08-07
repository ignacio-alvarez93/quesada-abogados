import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    calendar_alert_service,
)


class CalendarAlertServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.tmpdir.name)
            / "alerts.db"
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
                1,
                'MOHAMED',
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

        calendar_alert_service \
            .ensure_calendar_alert_schema(
                db_path=self.db_path
            )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_create_alert(self):
        result = (
            calendar_alert_service
            .create_alert(
                titulo=(
                    "Caducidad antecedentes"
                ),
                descripcion=(
                    "Los penales caducan."
                ),
                cliente_id=1,
                expediente_id=10,
                documento_id=20,
                tipo="CADUCIDAD_DOCUMENTO",
                prioridad="ALTA",
                fecha_evento=(
                    "2026-01-14"
                ),
                fecha_inicio_aviso=(
                    "2026-01-13"
                ),
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            result["created"]
        )

        alert = result["alert"]

        self.assertEqual(
            alert["estado"],
            "ACTIVO",
        )

        self.assertEqual(
            alert["numero_expediente"],
            "EXP-TEST-001",
        )

        self.assertTrue(
            alert["abierto"]
        )

    def test_title_is_required(self):
        with self.assertRaises(
            ValueError
        ):
            calendar_alert_service \
                .create_alert(
                    titulo="",
                    fecha_evento=(
                        "2026-01-14"
                    ),
                    db_path=self.db_path,
                )

    def test_event_date_is_required(self):
        with self.assertRaises(
            ValueError
        ):
            calendar_alert_service \
                .create_alert(
                    titulo="Aviso",
                    fecha_evento="",
                    db_path=self.db_path,
                )

    def test_invalid_priority_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            calendar_alert_service \
                .create_alert(
                    titulo="Aviso",
                    fecha_evento=(
                        "2026-01-14"
                    ),
                    prioridad="CRITICA",
                    db_path=self.db_path,
                )

    def test_source_key_is_idempotent(
        self,
    ):
        kwargs = {
            "titulo":
                "Caducidad penales",
            "cliente_id":
                1,
            "expediente_id":
                10,
            "documento_id":
                20,
            "fecha_evento":
                "2026-01-14",
            "source_key":
                "CADUCIDAD_PENALES:"
                "EXP10:DOC20",
            "db_path":
                self.db_path,
        }

        first = (
            calendar_alert_service
            .create_alert(
                **kwargs
            )
        )

        second = (
            calendar_alert_service
            .create_alert(
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

        self.assertEqual(
            len(
                calendar_alert_service
                .list_alerts(
                    db_path=self.db_path
                )
            ),
            1,
        )

    def test_update_alert(self):
        alert = (
            calendar_alert_service
            .create_alert(
                titulo="Caducidad penales",
                fecha_evento=(
                    "2026-01-14"
                ),
                prioridad="NORMAL",
                db_path=self.db_path,
            )["alert"]
        )

        updated = (
            calendar_alert_service
            .update_alert(
                alert["id"],
                titulo=(
                    "Caducidad penales renovada"
                ),
                prioridad="URGENTE",
                fecha_evento=(
                    "2026-01-15"
                ),
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            updated["titulo"],
            "Caducidad penales renovada",
        )

        self.assertEqual(
            updated["prioridad"],
            "URGENTE",
        )

        self.assertTrue(
            updated["fecha_evento"]
            .startswith(
                "2026-01-15"
            )
        )

    def test_resolve_and_reopen(self):
        alert = (
            calendar_alert_service
            .create_alert(
                titulo="Aviso",
                fecha_evento=(
                    "2026-01-14"
                ),
                db_path=self.db_path,
            )["alert"]
        )

        resolved = (
            calendar_alert_service
            .resolve_alert(
                alert["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            resolved["estado"],
            "RESUELTO",
        )

        self.assertIsNotNone(
            resolved["resolved_at"]
        )

        reopened = (
            calendar_alert_service
            .reopen_alert(
                alert["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            reopened["estado"],
            "ACTIVO",
        )

        self.assertIsNone(
            reopened["resolved_at"]
        )

    def test_cancel_alert(self):
        alert = (
            calendar_alert_service
            .create_alert(
                titulo="Cancelar",
                fecha_evento=(
                    "2026-01-14"
                ),
                db_path=self.db_path,
            )["alert"]
        )

        cancelled = (
            calendar_alert_service
            .cancel_alert(
                alert["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            cancelled["estado"],
            "CANCELADO",
        )

        self.assertIsNotNone(
            cancelled["cancelled_at"]
        )

    def test_filters_by_expedient(self):
        calendar_alert_service \
            .create_alert(
                titulo="Aviso expediente",
                cliente_id=1,
                expediente_id=10,
                fecha_evento=(
                    "2026-01-14"
                ),
                db_path=self.db_path,
            )

        calendar_alert_service \
            .create_alert(
                titulo="Aviso general",
                fecha_evento=(
                    "2026-01-15"
                ),
                db_path=self.db_path,
            )

        items = (
            calendar_alert_service
            .list_alerts(
                expediente_id=10,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            len(items),
            1,
        )

        self.assertEqual(
            items[0]["titulo"],
            "Aviso expediente",
        )

    def test_archive_alert(self):
        alert = (
            calendar_alert_service
            .create_alert(
                titulo="Archivar",
                fecha_evento=(
                    "2026-01-14"
                ),
                db_path=self.db_path,
            )["alert"]
        )

        archived = (
            calendar_alert_service
            .archive_alert(
                alert["id"],
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            archived["activo"],
            0,
        )

        visible = (
            calendar_alert_service
            .list_alerts(
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            visible,
            [],
        )


if __name__ == "__main__":
    unittest.main()
