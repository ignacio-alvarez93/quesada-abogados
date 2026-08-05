import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_evolution_service
from backend.services import expedient_service


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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                numero_expediente TEXT NOT NULL,
                numero_expediente_mercurio TEXT,
                numero_presentacion_registro TEXT,
                numero_expediente_extranjeria TEXT,
                tipo_expediente_id INTEGER,
                subtipo_expediente_id INTEGER,
                subtipo_expediente TEXT,
                estado_documental_id INTEGER,
                estado_administrativo_id INTEGER,
                estado_presentacion TEXT,
                prioridad_id INTEGER,
                responsable TEXT,
                fecha_apertura TEXT,
                fecha_presentacion TEXT,
                fecha_resolucion TEXT,
                numero_registro TEXT,
                organo_presentacion TEXT,
                provincia TEXT,
                observaciones TEXT,
                observaciones_internas TEXT,
                box_folder_path TEXT,
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                    subtipo_expediente_id,
                    subtipo_expediente,
                    prioridad_id,
                    responsable,
                    provincia,
                    activo
                )
            VALUES
                (
                    1000,
                    1,
                    'EXP-2026-1000',
                    10,
                    100,
                    'INICIAL',
                    NULL,
                    'NACHO',
                    'ASTURIAS',
                    1
                ),
                (
                    1001,
                    1,
                    'EXP-2026-1001',
                    20,
                    200,
                    'INICIAL',
                    NULL,
                    'NACHO',
                    'ASTURIAS',
                    1
                ),
                (
                    2000,
                    2,
                    'EXP-2026-2000',
                    20,
                    200,
                    'INICIAL',
                    NULL,
                    'OTRO',
                    'MADRID',
                    1
                );
            """
        )
        conn.commit()
        conn.close()

        self.db_patches = [
            patch.object(
                expedient_evolution_service,
                "DB_PATH",
                self.db_path,
            ),
            patch.object(
                expedient_service,
                "DB_PATH",
                self.db_path,
            ),
        ]

        for item in self.db_patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.db_patches):
            item.stop()
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

    def _create_derivation_rule_and_proposal(self):
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
                    subtipo_expediente_destino_id,
                    tipo_relacion
                )
                VALUES (
                    10,
                    'REAGRUPACION_A_VISADO_ACEPTACION',
                    'Reagrupación a visado',
                    1,
                    10,
                    100,
                    'RESOLUCION_FAVORABLE',
                    'CONCEDIDO',
                    3,
                    20,
                    200,
                    'ACTUACION_POSTERIOR'
                )
                """
            )
            conn.commit()

        return (
            expedient_evolution_service
            .create_derivation_proposal(
                expediente_origen_id=1000,
                regla_derivacion_id=10,
                detectada_por_evento=(
                    "RESOLUCION_FAVORABLE"
                ),
            )
        )

    def test_accept_proposal_creates_full_chain(self):
        proposal = self._create_derivation_rule_and_proposal()

        result = (
            expedient_evolution_service
            .accept_derivation_proposal(
                proposal["id"],
                usuario="NACHO",
            )
        )

        self.assertTrue(result["created"])
        self.assertFalse(result["already_created"])

        destination_id = result[
            "expediente_destino"
        ]["id"]

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            destination = conn.execute(
                """
                SELECT *
                FROM expedientes
                WHERE id = ?
                """,
                (destination_id,),
            ).fetchone()

            relation = conn.execute(
                """
                SELECT *
                FROM expediente_relaciones
                WHERE expediente_origen_id = 1000
                  AND expediente_destino_id = ?
                """,
                (destination_id,),
            ).fetchone()

            updated_proposal = conn.execute(
                """
                SELECT *
                FROM expediente_derivacion_propuestas
                WHERE id = ?
                """,
                (proposal["id"],),
            ).fetchone()

            events = conn.execute(
                """
                SELECT tipo_evento
                FROM expediente_eventos
                WHERE expediente_id IN (1000, ?)
                ORDER BY id
                """,
                (destination_id,),
            ).fetchall()

        self.assertEqual(destination["cliente_id"], 1)
        self.assertEqual(
            destination["tipo_expediente_id"],
            20,
        )
        self.assertEqual(
            destination["subtipo_expediente_id"],
            200,
        )
        self.assertEqual(
            destination["subtipo_expediente"],
            "INICIAL",
        )
        self.assertEqual(
            destination["responsable"],
            "NACHO",
        )
        self.assertEqual(
            destination["provincia"],
            "ASTURIAS",
        )
        self.assertIsNotNone(relation)
        self.assertEqual(
            relation["tipo_relacion"],
            "ACTUACION_POSTERIOR",
        )
        self.assertEqual(
            updated_proposal["estado"],
            "CREADA",
        )
        self.assertEqual(
            updated_proposal["expediente_destino_id"],
            destination_id,
        )
        self.assertEqual(
            [row["tipo_evento"] for row in events],
            [
                "EXPEDIENTE_DERIVADO_CREADO",
                (
                    "EXPEDIENTE_CREADO_"
                    "DESDE_DERIVACION"
                ),
            ],
        )

    def test_accept_proposal_is_idempotent(self):
        proposal = self._create_derivation_rule_and_proposal()

        first = (
            expedient_evolution_service
            .accept_derivation_proposal(
                proposal["id"],
                usuario="NACHO",
            )
        )

        second = (
            expedient_evolution_service
            .accept_derivation_proposal(
                proposal["id"],
                usuario="NACHO",
            )
        )

        self.assertTrue(first["created"])
        self.assertTrue(second["already_created"])
        self.assertFalse(second["created"])

        self.assertEqual(
            first["expediente_destino"]["id"],
            second["expediente_destino"]["id"],
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            total_destinations = conn.execute(
                """
                SELECT COUNT(*)
                FROM expedientes
                WHERE id NOT IN (1000, 1001, 2000)
                """
            ).fetchone()[0]

            total_relations = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_relaciones
                WHERE expediente_origen_id = 1000
                """
            ).fetchone()[0]

        self.assertEqual(total_destinations, 1)
        self.assertEqual(total_relations, 1)

    def test_accept_proposal_rolls_back_on_event_failure(self):
        proposal = self._create_derivation_rule_and_proposal()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("DROP TABLE expediente_eventos")
            conn.commit()

        with self.assertRaisesRegex(
            RuntimeError,
            "expediente_eventos",
        ):
            (
                expedient_evolution_service
                .accept_derivation_proposal(
                    proposal["id"],
                    usuario="NACHO",
                )
            )

        with closing(sqlite3.connect(self.db_path)) as conn:
            derived_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expedientes
                WHERE id NOT IN (1000, 1001, 2000)
                """
            ).fetchone()[0]

            relation_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_relaciones
                """
            ).fetchone()[0]

            proposal_state = conn.execute(
                """
                SELECT estado, expediente_destino_id
                FROM expediente_derivacion_propuestas
                WHERE id = ?
                """,
                (proposal["id"],),
            ).fetchone()

        self.assertEqual(derived_count, 0)
        self.assertEqual(relation_count, 0)
        self.assertEqual(
            proposal_state[0],
            "PENDIENTE",
        )
        self.assertIsNone(proposal_state[1])

    def test_evaluate_rules_creates_matching_proposals(self):
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
                    subtipo_expediente_destino_id,
                    tipo_relacion
                )
                VALUES
                    (
                        20,
                        'REGLA_EXACTA',
                        'Regla exacta',
                        1,
                        10,
                        100,
                        'RESOLUCION_FAVORABLE',
                        'CONCEDIDO',
                        3,
                        20,
                        200,
                        'ACTUACION_POSTERIOR'
                    ),
                    (
                        21,
                        'REGLA_TIPO',
                        'Regla genérica de tipo',
                        NULL,
                        10,
                        NULL,
                        'RESOLUCION_FAVORABLE',
                        'CONCEDIDO',
                        3,
                        20,
                        200,
                        'ACTUACION_POSTERIOR'
                    ),
                    (
                        22,
                        'REGLA_OTRO_TIPO',
                        'Regla de otro tipo',
                        NULL,
                        30,
                        NULL,
                        'RESOLUCION_FAVORABLE',
                        'CONCEDIDO',
                        3,
                        20,
                        200,
                        'ACTUACION_POSTERIOR'
                    )
                """
            )
            conn.commit()

        result = (
            expedient_evolution_service
            .evaluate_derivation_rules_for_event(
                expediente_id=1000,
                event_code="RESOLUCION_FAVORABLE",
                resultado="CONCEDIDO",
                usuario="NACHO",
            )
        )

        self.assertEqual(
            result["rules_evaluated"],
            2,
        )
        self.assertEqual(
            len(result["proposals"]),
            2,
        )

        codes = {
            item["regla_codigo"]
            for item in result["proposals"]
        }

        self.assertEqual(
            codes,
            {
                "REGLA_EXACTA",
                "REGLA_TIPO",
            },
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            proposal_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_derivacion_propuestas
                WHERE expediente_origen_id = 1000
                """
            ).fetchone()[0]

            event_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_eventos
                WHERE expediente_id = 1000
                  AND tipo_evento =
                      'PROPUESTA_DERIVACION_GENERADA'
                """
            ).fetchone()[0]

        self.assertEqual(proposal_count, 2)
        self.assertEqual(event_count, 2)

    def test_evaluate_rules_respects_required_result(self):
        expedient_evolution_service.ensure_expedient_evolution_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO config_reglas_expediente_derivado (
                    id,
                    codigo,
                    nombre,
                    tipo_expediente_origen_id,
                    evento_disparador,
                    resultado_requerido,
                    familia_destino_id,
                    tipo_expediente_destino_id,
                    subtipo_expediente_destino_id
                )
                VALUES (
                    30,
                    'SOLO_CONCEDIDO',
                    'Solo si es concedido',
                    10,
                    'RESOLUCION_FAVORABLE',
                    'CONCEDIDO',
                    3,
                    20,
                    200
                )
                """
            )
            conn.commit()

        result = (
            expedient_evolution_service
            .evaluate_derivation_rules_for_event(
                expediente_id=1000,
                event_code="RESOLUCION_FAVORABLE",
                resultado="DENEGADO",
            )
        )

        self.assertEqual(
            len(result["proposals"]),
            0,
        )
        self.assertEqual(
            len(result["skipped"]),
            1,
        )
        self.assertEqual(
            result["skipped"][0]["reason"],
            "RESULTADO_NO_COINCIDE",
        )

    def test_evaluate_rules_is_idempotent(self):
        expedient_evolution_service.ensure_expedient_evolution_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO config_reglas_expediente_derivado (
                    id,
                    codigo,
                    nombre,
                    tipo_expediente_origen_id,
                    evento_disparador,
                    familia_destino_id,
                    tipo_expediente_destino_id,
                    subtipo_expediente_destino_id
                )
                VALUES (
                    40,
                    'REGLA_IDEMPOTENTE',
                    'Regla idempotente',
                    10,
                    'RESOLUCION_FAVORABLE',
                    3,
                    20,
                    200
                )
                """
            )
            conn.commit()

        first = (
            expedient_evolution_service
            .evaluate_derivation_rules_for_event(
                expediente_id=1000,
                event_code="RESOLUCION_FAVORABLE",
            )
        )

        second = (
            expedient_evolution_service
            .evaluate_derivation_rules_for_event(
                expediente_id=1000,
                event_code="RESOLUCION_FAVORABLE",
            )
        )

        self.assertTrue(
            first["proposals"][0]["created"]
        )
        self.assertTrue(
            second["proposals"][0][
                "already_existed"
            ]
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            proposals = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_derivacion_propuestas
                WHERE expediente_origen_id = 1000
                  AND regla_derivacion_id = 40
                """
            ).fetchone()[0]

            events = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_eventos
                WHERE expediente_id = 1000
                  AND tipo_evento =
                      'PROPUESTA_DERIVACION_GENERADA'
                """
            ).fetchone()[0]

        self.assertEqual(proposals, 1)
        self.assertEqual(events, 1)

    def test_evaluate_rules_rolls_back_with_external_connection(self):
        expedient_evolution_service.ensure_expedient_evolution_schema()

        with closing(sqlite3.connect(self.db_path)) as setup_conn:
            setup_conn.execute(
                """
                INSERT INTO config_reglas_expediente_derivado (
                    id,
                    codigo,
                    nombre,
                    tipo_expediente_origen_id,
                    evento_disparador,
                    familia_destino_id,
                    tipo_expediente_destino_id
                )
                VALUES (
                    50,
                    'REGLA_TRANSACCIONAL',
                    'Regla transaccional',
                    10,
                    'RESOLUCION_FAVORABLE',
                    3,
                    20
                )
                """
            )
            setup_conn.commit()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            conn.execute("BEGIN IMMEDIATE")

            result = (
                expedient_evolution_service
                .evaluate_derivation_rules_for_event(
                    expediente_id=1000,
                    event_code=(
                        "RESOLUCION_FAVORABLE"
                    ),
                    conn=conn,
                )
            )

            self.assertEqual(
                len(result["proposals"]),
                1,
            )

            conn.rollback()
        finally:
            conn.close()

        with closing(sqlite3.connect(self.db_path)) as check_conn:
            proposal_count = check_conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_derivacion_propuestas
                WHERE expediente_origen_id = 1000
                  AND regla_derivacion_id = 50
                """
            ).fetchone()[0]

        self.assertEqual(proposal_count, 0)

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
