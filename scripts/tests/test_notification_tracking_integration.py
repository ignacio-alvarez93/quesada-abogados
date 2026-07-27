import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    notification_tracking_service as service,
)


class NotificationTrackingIntegrationTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "notification_tracking_test.db"
        )

        self.db_patch = patch.object(
            service,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

        self._create_base_schema()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _create_base_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    primer_apellido TEXT,
                    segundo_apellido TEXT,
                    nie TEXT
                );

                CREATE TABLE config_familias_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    notification_workflow_code TEXT NOT NULL
                );

                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    familia_id INTEGER,
                    codigo TEXT,
                    nombre TEXT,
                    FOREIGN KEY (familia_id)
                        REFERENCES config_familias_expediente(id)
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER NOT NULL,
                    numero_expediente TEXT,
                    numero_presentacion_registro TEXT,
                    numero_expediente_mercurio TEXT,
                    numero_expediente_extranjeria TEXT,
                    numero_registro_regage TEXT,
                    registro_csv_geiser TEXT,
                    estado_presentacion TEXT,
                    tipo_expediente_id INTEGER,
                    activo INTEGER DEFAULT 1,
                    FOREIGN KEY (cliente_id)
                        REFERENCES clientes(id),
                    FOREIGN KEY (tipo_expediente_id)
                        REFERENCES config_tipos_expediente(id)
                );

                CREATE TABLE expediente_justificantes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expediente_id INTEGER NOT NULL,
                    cliente_id INTEGER NOT NULL,
                    tipo_justificante TEXT,
                    numero_expediente_documento TEXT,
                    metadata_documento_json TEXT,
                    fecha_documento TEXT,
                    fecha_presentacion TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    activo INTEGER DEFAULT 1,
                    FOREIGN KEY (expediente_id)
                        REFERENCES expedientes(id),
                    FOREIGN KEY (cliente_id)
                        REFERENCES clientes(id)
                );

                CREATE TABLE expediente_eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expediente_id INTEGER NOT NULL,
                    cliente_id INTEGER NOT NULL,
                    tipo_evento TEXT NOT NULL,
                    titulo TEXT NOT NULL,
                    descripcion TEXT,
                    estado_anterior TEXT,
                    estado_nuevo TEXT,
                    entidad_relacionada TEXT,
                    entidad_relacionada_id INTEGER,
                    usuario TEXT,
                    fecha_evento TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            conn.execute(
                """
                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido
                )
                VALUES (1, 'CLIENTE', 'PRUEBA')
                """
            )

            conn.execute(
                """
                INSERT INTO config_familias_expediente (
                    id,
                    codigo,
                    nombre,
                    notification_workflow_code
                )
                VALUES (
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERÍA',
                    'EXTRANJERIA_STANDARD'
                )
                """
            )

            conn.execute(
                """
                INSERT INTO config_tipos_expediente (
                    id,
                    familia_id,
                    codigo,
                    nombre
                )
                VALUES (
                    1,
                    1,
                    'ARRAIGO',
                    'ARRAIGO SOCIOLABORAL'
                )
                """
            )

            conn.execute(
                """
                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    numero_expediente,
                    numero_presentacion_registro,
                    numero_expediente_mercurio,
                    numero_expediente_extranjeria,
                    numero_registro_regage,
                    registro_csv_geiser,
                    estado_presentacion,
                    tipo_expediente_id,
                    activo
                )
                VALUES (
                    1,
                    1,
                    'EXP-TEST-0001',
                    '',
                    '',
                    '',
                    '',
                    '',
                    'NO PRESENTADO',
                    1,
                    1
                )
                """
            )

    def _insert_document(
        self,
        event_code,
        *,
        official_number="",
        active=1,
    ):
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO expediente_justificantes (
                    expediente_id,
                    cliente_id,
                    tipo_justificante,
                    numero_expediente_documento,
                    activo
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    1,
                    1,
                    event_code,
                    official_number,
                    active,
                ),
            )
            return cursor.lastrowid

    def _update_expedient_number(self, value):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE expedientes
                SET numero_expediente_extranjeria = ?
                WHERE id = 1
                """,
                (value,),
            )

    def _archive_document(self, document_id):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE expediente_justificantes
                SET activo = 0
                WHERE id = ?
                """,
                (document_id,),
            )

    def test_never_presented_does_not_create_tracking(self):
        result = service.reconcile_expedient(
            1,
            source="TEST",
        )

        self.assertFalse(result["created"])
        self.assertIsNone(result["tracking_id"])

        self.assertIsNone(
            service.get_tracking_by_expedient(1)
        )

    def test_full_notification_workflow(self):
        presentation_id = self._insert_document(
            "JUSTIFICANTE_PRESENTACION"
        )

        result = service.reconcile_expedient(
            1,
            source="TEST_PRESENTATION",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_ESPERA_NUMERO,
        )
        self.assertEqual(result["activo"], 1)

        tracking_id = result["tracking_id"]

        self._update_expedient_number(
            "330020260001234"
        )

        result = service.reconcile_expedient(
            1,
            source="TEST_OFFICIAL_NUMBER",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_ESPERA_ADMISION,
        )
        self.assertEqual(
            result["tracking_id"],
            tracking_id,
        )

        admission_id = self._insert_document(
            "ADMISION_TRAMITE"
        )

        result = service.reconcile_expedient(
            1,
            source="TEST_ADMISSION",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_ESPERA_RESOLUCION,
        )

        tracking = (
            service.get_tracking_by_expedient(1)
        )

        self.assertEqual(
            tracking["justificante_presentacion_id"],
            presentation_id,
        )
        self.assertEqual(
            tracking["justificante_admision_id"],
            admission_id,
        )

        resolution_id = self._insert_document(
            "RESOLUCION_FAVORABLE"
        )

        result = service.reconcile_expedient(
            1,
            source="TEST_RESOLUTION",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_CERRADO_FAVORABLE,
        )
        self.assertEqual(result["activo"], 0)

        tracking = (
            service.get_tracking_by_expedient(1)
        )

        self.assertEqual(
            tracking["justificante_resolucion_id"],
            resolution_id,
        )
        self.assertEqual(
            tracking["resultado_resolucion"],
            "FAVORABLE",
        )

        self.assertEqual(
            service.list_active_tracking(),
            [],
        )

    def test_admission_with_tax_waits_resolution(self):
        self._insert_document(
            "JUSTIFICANTE_PRESENTACION"
        )
        self._update_expedient_number(
            "330020260005555"
        )
        admission_id = self._insert_document(
            "ADMISION_TRAMITE_TASA"
        )

        result = service.reconcile_expedient(
            1,
            source="TEST_ADMISSION_WITH_TAX",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_ESPERA_RESOLUCION,
        )

        tracking = (
            service.get_tracking_by_expedient(1)
        )

        self.assertEqual(
            tracking["tipo_admision"],
            "ADMISION_TRAMITE_TASA",
        )
        self.assertEqual(
            tracking["justificante_admision_id"],
            admission_id,
        )

    def test_denial_closes_tracking(self):
        self._insert_document(
            "JUSTIFICANTE_PRESENTACION"
        )
        self._update_expedient_number(
            "330020260006666"
        )
        self._insert_document(
            "ADMISION_TRAMITE"
        )
        self._insert_document(
            "RESOLUCION_DENEGATORIA"
        )

        result = service.reconcile_expedient(
            1,
            source="TEST_DENIAL",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_CERRADO_DENEGATORIO,
        )
        self.assertEqual(result["activo"], 0)
        self.assertEqual(
            result["resultado_resolucion"],
            "DENEGATORIA",
        )

    def test_resolution_archive_reopens_waiting_resolution(
        self,
    ):
        self._insert_document(
            "JUSTIFICANTE_PRESENTACION"
        )
        self._update_expedient_number(
            "330020260007777"
        )
        self._insert_document(
            "ADMISION_TRAMITE"
        )
        resolution_id = self._insert_document(
            "RESOLUCION_FAVORABLE"
        )

        service.reconcile_expedient(
            1,
            source="TEST_CLOSE",
        )

        self._archive_document(resolution_id)

        result = service.reconcile_expedient(
            1,
            source="TEST_REOPEN",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_ESPERA_RESOLUCION,
        )
        self.assertEqual(result["activo"], 1)

    def test_admission_archive_returns_to_waiting_admission(
        self,
    ):
        self._insert_document(
            "JUSTIFICANTE_PRESENTACION"
        )
        self._update_expedient_number(
            "330020260008888"
        )
        admission_id = self._insert_document(
            "ADMISION_TRAMITE_TASA"
        )

        service.reconcile_expedient(
            1,
            source="TEST_ADMISSION",
        )

        self._archive_document(admission_id)

        result = service.reconcile_expedient(
            1,
            source="TEST_ARCHIVE_ADMISSION",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service.ESTADO_ESPERA_ADMISION,
        )
        self.assertEqual(result["activo"], 1)

    def test_presentation_archive_cancels_existing_tracking(
        self,
    ):
        presentation_id = self._insert_document(
            "JUSTIFICANTE_PRESENTACION"
        )

        created = service.reconcile_expedient(
            1,
            source="TEST_PRESENTATION",
        )

        self.assertTrue(created["created"])

        self._archive_document(presentation_id)

        result = service.reconcile_expedient(
            1,
            source="TEST_ARCHIVE_PRESENTATION",
        )

        self.assertEqual(
            result["estado_nuevo"],
            service
            .ESTADO_CANCELADO_SIN_PRESENTACION,
        )
        self.assertEqual(result["activo"], 0)

    def test_reconciliation_is_idempotent(self):
        self._insert_document(
            "JUSTIFICANTE_PRESENTACION"
        )

        first = service.reconcile_expedient(
            1,
            source="TEST_FIRST",
        )

        second = service.reconcile_expedient(
            1,
            source="TEST_SECOND",
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertFalse(second["changed"])
        self.assertEqual(
            first["tracking_id"],
            second["tracking_id"],
        )

        with self._connect() as conn:
            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM notification_tracking
                WHERE expediente_id = 1
                """
            ).fetchone()[0]

        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main()
