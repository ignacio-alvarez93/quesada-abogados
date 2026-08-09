import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.services import task_service


class TaskServiceTestCase(
    unittest.TestCase
):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.tmpdir.name)
            / "tasks.db"
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

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_create_manual_task(self):
        result = task_service.create_task(
            titulo="Llamar al cliente",
            descripcion="Confirmar documentación.",
            cliente_id=1,
            expediente_id=10,
            fecha_vencimiento=(
                "2030-08-10 12:00"
            ),
            prioridad="ALTA",
            responsable="NACHO",
            db_path=self.db_path,
        )

        self.assertTrue(
            result["created"]
        )

        task = result["task"]

        self.assertEqual(
            task["titulo"],
            "Llamar al cliente",
        )

        self.assertEqual(
            task["prioridad"],
            "ALTA",
        )

        self.assertEqual(
            task["estado"],
            "PENDIENTE",
        )

        self.assertEqual(
            task["numero_expediente"],
            "EXP-TEST-001",
        )

    def test_due_date_is_required(self):
        with self.assertRaises(
            ValueError
        ):
            task_service.create_task(
                titulo="Sin fecha",
                fecha_vencimiento="",
                db_path=self.db_path,
            )

    def test_invalid_priority_is_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            task_service.create_task(
                titulo="Prioridad inválida",
                fecha_vencimiento=(
                    "2030-08-10"
                ),
                prioridad="CRITICA",
                db_path=self.db_path,
            )

    def test_source_key_is_idempotent(self):
        first = task_service.create_task(
            titulo=(
                "Contestar requerimiento"
            ),
            expediente_id=10,
            fecha_vencimiento=(
                "2030-08-20"
            ),
            origen_tipo="TRAZABILIDAD",
            origen_id="500",
            source_key=(
                "REQUERIMIENTO:10:500"
            ),
            db_path=self.db_path,
        )

        second = task_service.create_task(
            titulo=(
                "Contestar requerimiento"
            ),
            expediente_id=10,
            fecha_vencimiento=(
                "2030-08-20"
            ),
            origen_tipo="TRAZABILIDAD",
            origen_id="500",
            source_key=(
                "REQUERIMIENTO:10:500"
            ),
            db_path=self.db_path,
        )

        self.assertTrue(
            first["created"]
        )

        self.assertFalse(
            second["created"]
        )

        self.assertEqual(
            first["task"]["id"],
            second["task"]["id"],
        )

        tasks = task_service.list_tasks(
            db_path=self.db_path
        )

        self.assertEqual(
            len(tasks),
            1,
        )

    def test_complete_task(self):
        created = task_service.create_task(
            titulo="Completar prueba",
            fecha_vencimiento=(
                "2030-08-10"
            ),
            db_path=self.db_path,
        )

        task_id = (
            created["task"]["id"]
        )

        completed = (
            task_service.complete_task(
                task_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            completed["estado"],
            "COMPLETADA",
        )

        self.assertIsNotNone(
            completed["completada_at"]
        )

        self.assertFalse(
            completed["abierta"]
        )

    def test_cancel_and_reopen_task(self):
        created = task_service.create_task(
            titulo="Cancelar prueba",
            fecha_vencimiento=(
                "2030-08-10"
            ),
            db_path=self.db_path,
        )

        task_id = (
            created["task"]["id"]
        )

        cancelled = (
            task_service.cancel_task(
                task_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            cancelled["estado"],
            "CANCELADA",
        )

        self.assertIsNotNone(
            cancelled["cancelada_at"]
        )

        reopened = (
            task_service.reopen_task(
                task_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            reopened["estado"],
            "PENDIENTE",
        )

        self.assertIsNone(
            reopened["cancelada_at"]
        )

    def test_overdue_is_calculated_not_stored(self):
        result = task_service.create_task(
            titulo="Tarea vencida",
            fecha_vencimiento=(
                "2020-01-01 10:00"
            ),
            db_path=self.db_path,
        )

        task = result["task"]

        decorated = (
            task_service._decorate_task(
                task,
                now=datetime(
                    2026,
                    8,
                    7,
                    10,
                    0,
                ),
            )
        )

        self.assertTrue(
            decorated["vencida"]
        )

        self.assertEqual(
            decorated["estado"],
            "PENDIENTE",
        )

    def test_list_order_priority_then_due_date(
        self,
    ):
        task_service.create_task(
            titulo="Normal",
            fecha_vencimiento=(
                "2030-08-01"
            ),
            prioridad="NORMAL",
            db_path=self.db_path,
        )

        task_service.create_task(
            titulo="Urgente",
            fecha_vencimiento=(
                "2030-09-01"
            ),
            prioridad="URGENTE",
            db_path=self.db_path,
        )

        tasks = task_service.list_tasks(
            db_path=self.db_path
        )

        self.assertEqual(
            tasks[0]["titulo"],
            "Urgente",
        )

    def test_archive_task(self):
        created = task_service.create_task(
            titulo="Archivar",
            fecha_vencimiento=(
                "2030-08-10"
            ),
            db_path=self.db_path,
        )

        task_id = (
            created["task"]["id"]
        )

        archived = (
            task_service.archive_task(
                task_id,
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            archived["activo"],
            0,
        )

        visible = task_service.list_tasks(
            db_path=self.db_path
        )

        self.assertEqual(
            visible,
            [],
        )


if __name__ == "__main__":
    unittest.main()
