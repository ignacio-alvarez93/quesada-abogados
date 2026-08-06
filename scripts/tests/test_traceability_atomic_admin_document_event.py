import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    expedient_traceability_service,
)


class AtomicAdminDocumentEventTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "atomic.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )

        conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT,
                nie TEXT,
                dni TEXT,
                pasaporte TEXT,
                fecha_caducidad_residencia TEXT,
                fecha_caducidad_origen TEXT,
                fecha_caducidad_expediente_id INTEGER,
                fecha_caducidad_documento_id INTEGER,
                fecha_caducidad_actualizada_at TEXT,
                situacion_administrativa_id INTEGER,
                autorizacion_actual_id INTEGER,
                activo INTEGER DEFAULT 1,
                updated_at TEXT
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                estado_administrativo_id INTEGER,
                estado_presentacion TEXT,
                unidad_tramitacion_nombre TEXT,
                unidad_tramitacion_codigo TEXT,
                organismo_tramitacion TEXT,
                organo_presentacion TEXT,
                activo INTEGER DEFAULT 1,
                updated_at TEXT
            );

            CREATE TABLE expediente_justificantes (
                id INTEGER PRIMARY KEY,
                expediente_id INTEGER NOT NULL,
                cliente_id INTEGER NOT NULL,
                archivo_nombre TEXT,
                archivo_ruta TEXT,
                tipo_justificante TEXT,
                fecha_presentacion TEXT,
                numero_registro TEXT,
                organo_presentacion TEXT,
                fecha_documento TEXT,
                csv_documento TEXT,
                dir3_documento TEXT,
                organo_documento TEXT,
                nie_documento TEXT,
                numero_expediente_documento TEXT,
                metadata_documento_json TEXT,
                procedimiento_detectado TEXT,
                estado_conciliacion TEXT,
                observaciones TEXT,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE expediente_eventos (
                id INTEGER PRIMARY KEY,
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

            INSERT INTO clientes (
                id,
                nombre,
                fecha_caducidad_residencia
            )
            VALUES (
                1,
                'CLIENTE TEST',
                '2026-01-01'
            );

            INSERT INTO expedientes (
                id,
                cliente_id,
                estado_administrativo_id,
                unidad_tramitacion_nombre
            )
            VALUES (
                100,
                1,
                1,
                'OFICINA DE EXTRANJERÍA'
            );
            """
        )

        conn.commit()
        conn.close()

        self.db_patch = patch.object(
            expedient_traceability_service,
            "DB_PATH",
            self.db_path,
        )

        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _data(self):
        return {
            "expediente_id": 100,
            "archivo_nombre":
                "resolucion.pdf",
            "archivo_ruta":
                "C:/TEST/resolucion.pdf",
            "event_code":
                "RESOLUCION_FAVORABLE",
            "usuario":
                "TEST",
            "favorable_resolution_extraction": {
                "fecha_resolucion":
                    "2026-02-10",
                "fecha_caducidad":
                    "2027-03-01",
                "numero_expediente_extranjeria":
                    "EX-100",
                "unidad_tramitacion_nombre":
                    "OFICINA DE EXTRANJERÍA",
            },
        }

    def _counts(self):
        conn = sqlite3.connect(
            self.db_path
        )

        try:
            justificantes = (
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM expediente_justificantes
                    """
                ).fetchone()[0]
            )

            eventos = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_eventos
                """
            ).fetchone()[0]

            cliente = conn.execute(
                """
                SELECT
                    fecha_caducidad_residencia,
                    fecha_caducidad_documento_id
                FROM clientes
                WHERE id = 1
                """
            ).fetchone()

            return {
                "justificantes":
                    justificantes,
                "eventos":
                    eventos,
                "fecha_caducidad":
                    cliente[0],
                "documento_id":
                    cliente[1],
            }

        finally:
            conn.close()

    def test_authorization_failure_rolls_back_core(
        self,
    ):
        with (
            patch.object(
                expedient_traceability_service,
                "ensure_admin_document_metadata_schema",
                return_value=None,
            ),
            patch.object(
                expedient_traceability_service,
                "_ensure_client_residence_expiry_schema",
                return_value=None,
            ),
            patch.object(
                expedient_traceability_service,
                "_apply_admin_document_transition",
                return_value={
                    "changed": True,
                    "workflow_code":
                        "EXTRANJERIA",
                    "estado_anterior":
                        "EN TRÁMITE",
                    "estado_nuevo":
                        "RESUELTO FAVORABLE",
                    "estado_nuevo_id": 9,
                },
            ),
            patch(
                "backend.services."
                "client_authorization_transition_service."
                "apply_favorable_resolution_to_client",
                side_effect=ValueError(
                    "Fallo forzado"
                ),
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Fallo forzado",
            ):
                (
                    expedient_traceability_service
                    .create_admin_document_event(
                        self._data()
                    )
                )

        state = self._counts()

        self.assertEqual(
            state["justificantes"],
            0,
        )

        self.assertEqual(
            state["eventos"],
            0,
        )

        self.assertEqual(
            state["fecha_caducidad"],
            "2026-01-01",
        )

        self.assertIsNone(
            state["documento_id"]
        )


if __name__ == "__main__":
    unittest.main()
