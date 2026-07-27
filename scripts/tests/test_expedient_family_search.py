import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_service


class ExpedientFamilySearchTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "family_search.db"

        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT,
                nie TEXT,
                pasaporte TEXT,
                dni TEXT
            );

            CREATE TABLE config_familias_expediente (
                id INTEGER PRIMARY KEY,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                notification_workflow_code TEXT
            );

            CREATE TABLE config_tipos_expediente (
                id INTEGER PRIMARY KEY,
                familia_id INTEGER,
                codigo TEXT,
                nombre TEXT
            );

            CREATE TABLE config_subtipos_expediente (
                id INTEGER PRIMARY KEY,
                tipo_expediente_id INTEGER,
                codigo TEXT,
                nombre TEXT
            );

            CREATE TABLE config_estados_documentales (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                color TEXT
            );

            CREATE TABLE config_estados_administrativos (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                color TEXT
            );

            CREATE TABLE config_prioridades (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                color TEXT
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                numero_expediente TEXT,
                numero_expediente_mercurio TEXT,
                tipo_expediente_id INTEGER,
                subtipo_expediente_id INTEGER,
                subtipo_expediente TEXT,
                estado_documental_id INTEGER,
                estado_administrativo_id INTEGER,
                prioridad_id INTEGER,
                responsable TEXT,
                numero_registro TEXT,
                box_folder_path TEXT,
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO clientes
                (id, nombre, primer_apellido)
            VALUES
                (1, 'ANA', 'EXTRANJERIA'),
                (2, 'LUIS', 'NACIONALIDAD');

            INSERT INTO config_familias_expediente
                (id, codigo, nombre, notification_workflow_code)
            VALUES
                (1, 'EXTRANJERIA', 'EXTRANJERÍA', 'EXTRANJERIA_STANDARD'),
                (2, 'NACIONALIDAD', 'NACIONALIDAD', 'RESOLUCION_DIRECTA');

            INSERT INTO config_tipos_expediente
                (id, familia_id, codigo, nombre)
            VALUES
                (10, 1, 'ARRAIGO', 'ARRAIGO'),
                (20, 2, 'NACIONALIDAD_RESIDENCIA', 'NACIONALIDAD POR RESIDENCIA');

            INSERT INTO expedientes
                (
                    id,
                    cliente_id,
                    numero_expediente,
                    tipo_expediente_id,
                    activo,
                    created_at
                )
            VALUES
                (100, 1, 'EXP-EXT', 10, 1, '2026-07-24 10:00:00'),
                (200, 2, 'EXP-NAC', 20, 1, '2026-07-24 11:00:00');
            """
        )
        conn.commit()
        conn.close()

        self.db_patch = patch.object(
            expedient_service,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

        @contextmanager
        def closed_connection():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        self.connect_patch = patch.object(
            expedient_service,
            "_connect",
            closed_connection,
        )
        self.connect_patch.start()

    def tearDown(self):
        self.connect_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_search_filters_by_family(self):
        rows = expedient_service.search_expedientes(
            {
                "familia_id": 2,
                "active_only": True,
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numero_expediente"], "EXP-NAC")
        self.assertEqual(
            rows[0]["familia_expediente_codigo"],
            "NACIONALIDAD",
        )
        self.assertEqual(
            rows[0]["notification_workflow_code"],
            "RESOLUCION_DIRECTA",
        )

    def test_family_and_type_filters_are_compatible(self):
        rows = expedient_service.search_expedientes(
            {
                "familia_id": 1,
                "tipo_expediente_id": 10,
                "active_only": True,
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numero_expediente"], "EXP-EXT")

        mismatch = expedient_service.search_expedientes(
            {
                "familia_id": 2,
                "tipo_expediente_id": 10,
                "active_only": True,
            }
        )

        self.assertEqual(mismatch, [])

    def test_expedientes_table_does_not_duplicate_family(self):
        conn = sqlite3.connect(self.db_path)
        try:
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(expedientes)"
                ).fetchall()
            }
        finally:
            conn.close()

        self.assertNotIn("familia_id", columns)
        self.assertNotIn("familia_expediente_id", columns)


if __name__ == "__main__":
    unittest.main()
