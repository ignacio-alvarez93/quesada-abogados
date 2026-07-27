import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_traceability_service as trace_service


class JustificantePresentacionPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "presentation.db"

        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                numero_expediente TEXT,
                numero_expediente_mercurio TEXT,
                fecha_presentacion TEXT,
                numero_registro TEXT,
                organo_presentacion TEXT,
                updated_at TEXT
            );

            INSERT INTO expedientes (
                id,
                numero_expediente,
                numero_expediente_mercurio,
                fecha_presentacion,
                numero_registro,
                organo_presentacion
            )
            VALUES (
                1,
                'EXP-INTERNO-1',
                NULL,
                NULL,
                NULL,
                NULL
            );
            """
        )
        conn.commit()
        conn.close()

        def test_connection():
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        self.connect_patch = patch.object(
            trace_service,
            "_connect",
            test_connection,
        )
        self.connect_patch.start()

    def tearDown(self):
        self.connect_patch.stop()
        self.temp_dir.cleanup()

    def test_persist_registry_data(self):
        extraction = {
            "format": "GEISER_REGAGE",
            "numero_presentacion_registro": "I33202604692498",
            "fecha_hora_presentacion": "2026-07-21 16:59:03",
            "fecha_hora_registro": "2026-07-21 16:59:05",
            "numero_registro_regage": "REGAGE26e00067195547",
            "oficina_registro_nombre":
                "Oficina de Asistencia en Materia de Registros (Oviedo)",
            "oficina_registro_codigo": "O00001605",
            "unidad_tramitacion_nombre":
                "Delegación del Gobierno en Asturias",
            "unidad_tramitacion_codigo": "EA0040281",
            "organismo_tramitacion":
                "Ministerio de Política Territorial y Memoria Democrática",
            "registro_ambito_prefijo": "GEISER",
            "registro_csv_geiser":
                "GEISER-efc6-814c-c393-4ca4-87ac-fd5a-de22-c3ab",
            "sha256": "abc123",
            "warnings": [],
            "confidence": 1.0,
        }

        trace_service.persist_presentation_registry_data(
            1,
            extraction,
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            row = conn.execute(
                """
                SELECT *
                FROM expedientes
                WHERE id = 1
                """
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(
            row["numero_presentacion_registro"],
            "I33202604692498",
        )
        self.assertEqual(
            row["numero_expediente_mercurio"],
            "I33202604692498",
        )
        self.assertEqual(
            row["numero_registro_regage"],
            "REGAGE26e00067195547",
        )
        self.assertEqual(
            row["numero_registro"],
            "REGAGE26e00067195547",
        )
        self.assertEqual(
            row["fecha_hora_presentacion"],
            "2026-07-21 16:59:03",
        )
        self.assertEqual(
            row["fecha_presentacion"],
            "2026-07-21",
        )
        self.assertEqual(
            row["organo_presentacion"],
            "Delegación del Gobierno en Asturias",
        )
        self.assertEqual(
            row["justificante_extraction_status"],
            "CONFIRMADA",
        )
        self.assertIsNone(
            row["numero_expediente_extranjeria"]
        )

        stored_json = json.loads(
            row["justificante_extraction_json"]
        )
        self.assertEqual(
            stored_json["registro_csv_geiser"],
            extraction["registro_csv_geiser"],
        )

    def test_runtime_schema_is_idempotent(self):
        connection = trace_service._connect()

        try:
            trace_service.ensure_presentation_registry_runtime_schema(
                connection
            )
            trace_service.ensure_presentation_registry_runtime_schema(
                connection
            )
            connection.commit()
        finally:
            connection.close()

        connection = sqlite3.connect(self.db_path)

        try:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(expedientes)"
                ).fetchall()
            }
        finally:
            connection.close()

        self.assertIn(
            "numero_presentacion_registro",
            columns,
        )
        self.assertIn(
            "numero_expediente_extranjeria",
            columns,
        )
        self.assertIn(
            "registro_csv_geiser",
            columns,
        )


if __name__ == "__main__":
    unittest.main()
