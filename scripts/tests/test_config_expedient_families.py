import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.services import config_service
from backend.services import expedient_family_service


class ConfigExpedientFamiliesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_config_families.db"

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT NOT NULL UNIQUE,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    activo INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    url_presentacion TEXT,
                    workflow_code TEXT
                );

                CREATE TABLE config_documentos_requeridos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo_expediente_id INTEGER NOT NULL,
                    codigo_documento TEXT NOT NULL,
                    nombre_documento TEXT NOT NULL,
                    obligatorio INTEGER NOT NULL DEFAULT 1,
                    orden INTEGER NOT NULL DEFAULT 0,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE config_nomenclaturas_documentales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo_expediente_id INTEGER NOT NULL,
                    documento_id INTEGER NOT NULL,
                    patron_nombre TEXT NOT NULL,
                    extension_permitida TEXT,
                    activo INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            conn.commit()

        self.config_db_patch = patch.object(
            config_service,
            "DB_PATH",
            self.db_path,
        )
        self.family_db_patch = patch.object(
            expedient_family_service,
            "DB_PATH",
            self.db_path,
        )

        self.config_db_patch.start()
        self.family_db_patch.start()

        @contextmanager
        def test_config_connection():
            """
            Conexión transaccional cerrada expresamente.

            sqlite3.Connection como context manager confirma o revierte,
            pero no garantiza el cierre físico del archivo en Windows.
            """
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
            config_service,
            "_connect",
            test_config_connection,
        )
        self.connect_patch.start()

        # Evitar cargar schemas del repositorio sobre la base mínima del test.
        self.dynamic_patch = patch.object(
            config_service,
            "_initialize_dynamic_forms_runtime_schema",
            lambda: None,
        )
        self.dynamic_patch.start()

        config_service.ensure_config_runtime_schema()

    def tearDown(self):
        self.dynamic_patch.stop()
        self.connect_patch.stop()
        self.family_db_patch.stop()
        self.config_db_patch.stop()
        self.temp_dir.cleanup()

    def _family_id(self, code):
        families = config_service.get_familias_expediente(active_only=True)
        return next(
            int(item["id"])
            for item in families
            if item["codigo"] == code
        )

    def test_create_type_requires_family(self):
        with self.assertRaisesRegex(ValueError, "familia"):
            config_service.create_tipo_expediente(
                {
                    "nombre": "TIPO SIN FAMILIA",
                    "activo": 1,
                }
            )

    def test_create_type_with_uge_family(self):
        uge_id = self._family_id("UGE")

        tipo_id = config_service.create_tipo_expediente(
            {
                "familia_id": uge_id,
                "codigo": "TELETRABAJADOR_INTERNACIONAL",
                "nombre": "TELETRABAJADOR INTERNACIONAL",
                "descripcion": "Procedimiento UGE",
                "url_presentacion": "",
                "activo": 1,
            }
        )

        tipos = config_service.get_tipos_expediente(active_only=True)
        created = next(item for item in tipos if item["id"] == tipo_id)

        self.assertEqual(created["familia_codigo"], "UGE")
        self.assertEqual(created["workflow_code"], "UGE")

    def test_update_type_changes_family(self):
        otros_id = self._family_id("OTROS")
        visados_id = self._family_id("VISADOS")

        tipo_id = config_service.create_tipo_expediente(
            {
                "familia_id": otros_id,
                "codigo": "TIPO_TEMPORAL",
                "nombre": "TIPO TEMPORAL",
                "activo": 1,
            }
        )

        config_service.update_tipo_expediente(
            tipo_id,
            {
                "familia_id": visados_id,
                "codigo": "VISADO_ESTUDIOS",
                "nombre": "VISADO DE ESTUDIOS",
                "activo": 1,
            },
        )

        tipos = config_service.get_tipos_expediente(active_only=True)
        updated = next(item for item in tipos if item["id"] == tipo_id)

        self.assertEqual(updated["familia_codigo"], "VISADOS")
        self.assertEqual(updated["workflow_code"], "VISADOS")


if __name__ == "__main__":
    unittest.main()
