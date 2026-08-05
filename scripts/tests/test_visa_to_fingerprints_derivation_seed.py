import gc
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EVOLUTION_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_create_expedient_evolution_schema.sql"
)

CONSULAR_SEED = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_seed_reagrupacion_to_consular_visa_rule.sql"
)

FINGERPRINTS_SEED = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_seed_visa_to_fingerprints_rule.sql"
)


class VisaToFingerprintsDerivationSeedTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "visa_to_fingerprints_seed.db"
        )

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

        self.conn.executescript(
            """
            CREATE TABLE config_familias_expediente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                notification_workflow_code TEXT
                    NOT NULL DEFAULT 'RESOLUCION_DIRECTA',
                orden INTEGER NOT NULL DEFAULT 0,
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE config_tipos_expediente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                url_presentacion TEXT,
                workflow_code TEXT,
                familia_id INTEGER,
                FOREIGN KEY (familia_id)
                    REFERENCES config_familias_expediente(id)
            );

            CREATE TABLE config_subtipos_expediente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_expediente_id INTEGER NOT NULL,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tipo_expediente_id)
                    REFERENCES config_tipos_expediente(id)
            );

            CREATE TABLE config_tipos_autorizacion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL
            );

            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id)
            );

            INSERT INTO config_familias_expediente (
                id,
                codigo,
                nombre,
                orden
            )
            VALUES (
                1,
                'EXTRANJERIA',
                'EXTRANJERÍA',
                10
            );

            INSERT INTO config_tipos_expediente (
                id,
                codigo,
                nombre,
                familia_id,
                workflow_code
            )
            VALUES (
                14,
                'REAGRUPACION_FAMILIAR',
                'REAGRUPACIÓN FAMILIAR',
                1,
                'EXTRANJERIA'
            );

            INSERT INTO config_subtipos_expediente (
                id,
                tipo_expediente_id,
                codigo,
                nombre
            )
            VALUES (
                8,
                14,
                'INICIAL',
                'INICIAL'
            );
            """
        )

        self.conn.executescript(
            EVOLUTION_MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        self.conn.executescript(
            CONSULAR_SEED.read_text(
                encoding="utf-8"
            )
        )

        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        gc.collect()

        cleanup_error = None

        for _ in range(5):
            try:
                self.temp_dir.cleanup()
                cleanup_error = None
                break
            except PermissionError as exc:
                cleanup_error = exc
                gc.collect()
                time.sleep(0.05)

        if cleanup_error is not None:
            raise cleanup_error

    def apply_seed(self):
        self.conn.executescript(
            FINGERPRINTS_SEED.read_text(
                encoding="utf-8"
            )
        )
        self.conn.commit()

    def test_seed_creates_police_catalog_and_rule(self):
        self.apply_seed()

        family = self.conn.execute(
            """
            SELECT *
            FROM config_familias_expediente
            WHERE codigo = 'POLICIA_NACIONAL'
            """
        ).fetchone()

        expedient_type = self.conn.execute(
            """
            SELECT *
            FROM config_tipos_expediente
            WHERE codigo = 'TOMA_HUELLAS'
            """
        ).fetchone()

        rule = self.conn.execute(
            """
            SELECT *
            FROM config_reglas_expediente_derivado
            WHERE codigo =
                'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'
            """
        ).fetchone()

        origin_type = self.conn.execute(
            """
            SELECT id, familia_id
            FROM config_tipos_expediente
            WHERE codigo =
                'VISADO_REAGRUPACION_FAMILIAR'
            """
        ).fetchone()

        self.assertIsNotNone(family)
        self.assertIsNotNone(expedient_type)
        self.assertIsNotNone(rule)
        self.assertIsNotNone(origin_type)

        self.assertEqual(
            expedient_type["familia_id"],
            family["id"],
        )
        self.assertEqual(
            rule["familia_origen_id"],
            origin_type["familia_id"],
        )
        self.assertEqual(
            rule["tipo_expediente_origen_id"],
            origin_type["id"],
        )
        self.assertIsNone(
            rule["subtipo_expediente_origen_id"]
        )
        self.assertEqual(
            rule["familia_destino_id"],
            family["id"],
        )
        self.assertEqual(
            rule["tipo_expediente_destino_id"],
            expedient_type["id"],
        )
        self.assertIsNone(
            rule["subtipo_expediente_destino_id"]
        )
        self.assertEqual(
            rule["evento_disparador"],
            "RESOLUCION_FAVORABLE",
        )
        self.assertEqual(
            rule["resultado_requerido"],
            "CONCEDIDO",
        )
        self.assertEqual(
            rule["tipo_relacion"],
            "ACTUACION_POSTERIOR",
        )
        self.assertEqual(
            rule["creacion_automatica"],
            0,
        )
        self.assertEqual(
            rule["requiere_revision_humana"],
            1,
        )

    def test_seed_is_idempotent(self):
        self.apply_seed()
        self.apply_seed()

        family_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM config_familias_expediente
            WHERE codigo = 'POLICIA_NACIONAL'
            """
        ).fetchone()[0]

        type_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM config_tipos_expediente
            WHERE codigo = 'TOMA_HUELLAS'
            """
        ).fetchone()[0]

        rule_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM config_reglas_expediente_derivado
            WHERE codigo =
                'VISADO_REAGRUPACION_CONCEDIDO_A_HUELLAS'
            """
        ).fetchone()[0]

        self.assertEqual(family_count, 1)
        self.assertEqual(type_count, 1)
        self.assertEqual(rule_count, 1)

    def test_existing_consular_catalog_is_preserved(self):
        self.apply_seed()

        family = self.conn.execute(
            """
            SELECT codigo, nombre, activo
            FROM config_familias_expediente
            WHERE codigo = 'TRAMITES_CONSULARES'
            """
        ).fetchone()

        expedient_type = self.conn.execute(
            """
            SELECT codigo, nombre, activo
            FROM config_tipos_expediente
            WHERE codigo =
                'VISADO_REAGRUPACION_FAMILIAR'
            """
        ).fetchone()

        self.assertIsNotNone(family)
        self.assertIsNotNone(expedient_type)
        self.assertEqual(family["activo"], 1)
        self.assertEqual(expedient_type["activo"], 1)


if __name__ == "__main__":
    unittest.main()
