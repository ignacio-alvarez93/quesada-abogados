import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_evolution_service


class ExpedientEvolutionSchemaTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "expedient_evolution.db"
        )

        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT NOT NULL,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_familias_expediente (
                id INTEGER PRIMARY KEY,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL
            );

            CREATE TABLE config_tipos_expediente (
                id INTEGER PRIMARY KEY,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                familia_id INTEGER,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_subtipos_expediente (
                id INTEGER PRIMARY KEY,
                tipo_expediente_id INTEGER NOT NULL,
                codigo TEXT NOT NULL,
                nombre TEXT NOT NULL,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_tipos_autorizacion (
                id INTEGER PRIMARY KEY,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                familia_codigo TEXT NOT NULL
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                numero_expediente TEXT NOT NULL,
                tipo_expediente_id INTEGER,
                subtipo_expediente_id INTEGER,
                activo INTEGER DEFAULT 1
            );

            INSERT INTO clientes
                (id, nombre)
            VALUES
                (1, 'CLIENTE UNO'),
                (2, 'CLIENTE DOS');

            INSERT INTO config_familias_expediente
                (id, codigo, nombre)
            VALUES
                (1, 'EXTRANJERIA', 'EXTRANJERÍA'),
                (3, 'VISADOS', 'VISADOS'),
                (4, 'UGE', 'UGE');

            INSERT INTO config_tipos_expediente
                (id, codigo, nombre, familia_id)
            VALUES
                (10, 'REAGRUPACION_FAMILIAR',
                    'REAGRUPACIÓN FAMILIAR', 1),
                (20, 'VISADO_REAGRUPACION',
                    'VISADO DE REAGRUPACIÓN', 3),
                (30, 'TOMA_HUELLAS',
                    'TOMA DE HUELLAS', 1);

            INSERT INTO config_subtipos_expediente
                (id, tipo_expediente_id, codigo, nombre)
            VALUES
                (100, 10, 'INICIAL', 'INICIAL'),
                (200, 20, 'INICIAL', 'INICIAL');

            INSERT INTO expedientes
                (
                    id,
                    cliente_id,
                    numero_expediente,
                    tipo_expediente_id,
                    subtipo_expediente_id
                )
            VALUES
                (1000, 1, 'EXP-2026-1000', 10, 100),
                (1001, 1, 'EXP-2026-1001', 20, 200),
                (2000, 2, 'EXP-2026-2000', 20, 200);
            """
        )
        conn.commit()
        conn.close()

        self.db_patch = patch.object(
            expedient_evolution_service,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_schema_is_idempotent(self):
        expedient_evolution_service.ensure_expedient_evolution_schema()
        expedient_evolution_service.ensure_expedient_evolution_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                )
            }

        self.assertIn("expediente_relaciones", tables)
        self.assertIn(
            "config_transiciones_autorizacion",
            tables,
        )
        self.assertIn(
            "config_reglas_expediente_derivado",
            tables,
        )
        self.assertIn(
            "expediente_derivacion_propuestas",
            tables,
        )

    def test_relation_requires_same_client(self):
        expedient_evolution_service.ensure_expedient_evolution_schema()

        with self.assertRaises(ValueError):
            expedient_evolution_service.create_expedient_relation(
                1000,
                2000,
                "ACTUACION_POSTERIOR",
            )

    def test_create_and_list_relation(self):
        relation = (
            expedient_evolution_service
            .create_expedient_relation(
                1000,
                1001,
                "ACTUACION_POSTERIOR",
                motivo="Visado derivado de reagrupación",
            )
        )

        self.assertEqual(
            relation["tipo_relacion"],
            "ACTUACION_POSTERIOR",
        )

        relations = (
            expedient_evolution_service
            .list_expedient_relations(1000)
        )

        self.assertEqual(len(relations), 1)
        self.assertEqual(
            relations[0]["expediente_destino_id"],
            1001,
        )

    def test_derivation_proposal_is_idempotent(self):
        expedient_evolution_service.ensure_expedient_evolution_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO config_reglas_expediente_derivado (
                    id,
                    codigo,
                    nombre,
                    familia_origen_id,
                    tipo_expediente_origen_id,
                    subtipo_expediente_origen_id,
                    evento_disparador,
                    resultado_requerido,
                    familia_destino_id,
                    tipo_expediente_destino_id,
                    subtipo_expediente_destino_id
                )
                VALUES (
                    1,
                    'REAGRUPACION_A_VISADO',
                    'Reagrupación concedida a visado',
                    1,
                    10,
                    100,
                    'RESOLUCION_FAVORABLE',
                    'CONCEDIDO',
                    3,
                    20,
                    200
                )
                """
            )
            conn.commit()

        first = (
            expedient_evolution_service
            .create_derivation_proposal(
                1000,
                1,
                "RESOLUCION_FAVORABLE",
            )
        )

        second = (
            expedient_evolution_service
            .create_derivation_proposal(
                1000,
                1,
                "RESOLUCION_FAVORABLE",
            )
        )

        self.assertEqual(first["id"], second["id"])

        proposals = (
            expedient_evolution_service
            .list_derivation_proposals(
                expediente_origen_id=1000,
                estado="PENDIENTE",
            )
        )

        self.assertEqual(len(proposals), 1)
        self.assertEqual(
            proposals[0]["regla_codigo"],
            "REAGRUPACION_A_VISADO",
        )


if __name__ == "__main__":
    unittest.main()
