import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_family_service


class ExpedientFamiliesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_families.db"

        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE config_tipos_expediente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                activo INTEGER NOT NULL DEFAULT 1,
                workflow_code TEXT
            );

            INSERT INTO config_tipos_expediente
                (codigo, nombre, workflow_code)
            VALUES
                ('ARRAIGO', 'ARRAIGO', 'EXTRANJERIA'),
                ('NACIONALIDAD', 'NACIONALIDAD', 'NACIONALIDAD'),
                ('FUTURO_VISADO', 'FUTURO VISADO', NULL);
            """
        )
        conn.commit()
        conn.close()

        self.db_patch = patch.object(
            expedient_family_service,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_create_default_families(self):
        expedient_family_service.initialize_expedient_families()

        with closing(sqlite3.connect(self.db_path)) as conn:
            codes = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT codigo
                    FROM config_familias_expediente
                    """
                ).fetchall()
            }

        self.assertEqual(
            codes,
            {
                "EXTRANJERIA",
                "NACIONALIDAD",
                "VISADOS",
                "UGE",
                "CANCELACION_ANTECEDENTES",
                "ASILO",
                "OTROS",
            },
        )

    def test_assign_types_conservatively(self):
        expedient_family_service.initialize_expedient_families()

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT
                    t.codigo,
                    f.codigo
                FROM config_tipos_expediente t
                JOIN config_familias_expediente f
                  ON f.id = t.familia_id
                ORDER BY t.codigo
                """
            ).fetchall()

        assigned = dict(rows)

        self.assertEqual(assigned["ARRAIGO"], "EXTRANJERIA")
        self.assertEqual(assigned["NACIONALIDAD"], "NACIONALIDAD")
        self.assertEqual(assigned["FUTURO_VISADO"], "OTROS")

    def test_initialization_is_idempotent(self):
        expedient_family_service.initialize_expedient_families()
        expedient_family_service.initialize_expedient_families()

        with closing(sqlite3.connect(self.db_path)) as conn:
            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_familias_expediente
                """
            ).fetchone()[0]

        self.assertEqual(total, 7)


if __name__ == "__main__":
    unittest.main()
