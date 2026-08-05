import gc
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_evolution_service
from backend.services import expedient_service
from backend.services import expedient_traceability_service
from backend.services import notification_tracking_service


ROOT = Path(__file__).resolve().parents[2]

TRACEABILITY_SCHEMA = (
    ROOT
    / "database"
    / "expedient_traceability_schema.sql"
)

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


class ReagrupacionToVisaEndToEndTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "reagrupacion_to_visa.db"
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

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
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

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

            CREATE TABLE config_estados_documentales (
                id INTEGER PRIMARY KEY,
                codigo TEXT UNIQUE,
                nombre TEXT,
                color TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_estados_administrativos (
                id INTEGER PRIMARY KEY,
                codigo TEXT UNIQUE,
                nombre TEXT,
                color TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_prioridades (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                color TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1
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
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id),
                FOREIGN KEY (tipo_expediente_id)
                    REFERENCES config_tipos_expediente(id),
                FOREIGN KEY (subtipo_expediente_id)
                    REFERENCES config_subtipos_expediente(id)
            );

            INSERT INTO clientes (
                id,
                nombre,
                primer_apellido,
                activo
            )
            VALUES (
                1,
                'CLIENTE',
                'PRUEBA',
                1
            );

            INSERT INTO config_familias_expediente (
                id,
                codigo,
                nombre,
                notification_workflow_code,
                orden,
                activo
            )
            VALUES
                (
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERÍA',
                    'EXTRANJERIA_STANDARD',
                    10,
                    1
                ),
                (
                    3,
                    'VISADOS',
                    'VISADOS',
                    'RESOLUCION_DIRECTA',
                    30,
                    1
                );

            INSERT INTO config_tipos_expediente (
                id,
                codigo,
                nombre,
                activo,
                workflow_code,
                familia_id
            )
            VALUES (
                14,
                'REAGRUPACION_FAMILIAR',
                'REAGRUPACIÓN FAMILIAR',
                1,
                'EXTRANJERIA',
                1
            );

            INSERT INTO config_subtipos_expediente (
                id,
                tipo_expediente_id,
                codigo,
                nombre,
                activo
            )
            VALUES (
                8,
                14,
                'INICIAL',
                'INICIAL',
                1
            );

            INSERT INTO config_estados_documentales (
                id,
                codigo,
                nombre,
                activo
            )
            VALUES (
                1,
                'PENDIENTE_DOCUMENTACION',
                'PENDIENTE DE DOCUMENTACIÓN',
                1
            );

            INSERT INTO config_estados_administrativos (
                id,
                codigo,
                nombre,
                orden,
                activo
            )
            VALUES
                (
                    1,
                    'NO_PRESENTADO',
                    'NO PRESENTADO',
                    10,
                    1
                ),
                (
                    7,
                    'RESUELTO_FAVORABLE',
                    'RESUELTO FAVORABLE',
                    70,
                    1
                );

            INSERT INTO config_prioridades (
                id,
                nombre,
                activo
            )
            VALUES (
                1,
                'NORMAL',
                1
            );

            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente,
                tipo_expediente_id,
                subtipo_expediente_id,
                subtipo_expediente,
                estado_documental_id,
                estado_administrativo_id,
                estado_presentacion,
                prioridad_id,
                responsable,
                fecha_apertura,
                provincia,
                activo
            )
            VALUES (
                1000,
                1,
                'EXP-2026-1000',
                14,
                8,
                'INICIAL',
                1,
                1,
                'NO PRESENTADO',
                1,
                'NACHO',
                '2026-08-05',
                'ASTURIAS',
                1
            );
            """
        )

        conn.executescript(
            TRACEABILITY_SCHEMA.read_text(
                encoding="utf-8"
            )
        )

        conn.executescript(
            EVOLUTION_MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        conn.executescript(
            CONSULAR_SEED.read_text(
                encoding="utf-8"
            )
        )

        conn.commit()
        conn.close()

        self.patches = [
            patch.object(
                expedient_traceability_service,
                "DB_PATH",
                self.db_path,
            ),
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
            patch.object(
                notification_tracking_service,
                "reconcile_expedient",
                return_value={
                    "ok": True,
                    "changed": False,
                },
            ),
        ]

        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

        # sqlite3.Connection como context manager confirma o
        # revierte la transacción, pero no siempre libera
        # inmediatamente el descriptor en Windows.
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

    def test_reagrupacion_favorable_creates_and_accepts_visa_proposal(
        self,
    ):
        event_result = (
            expedient_traceability_service
            .create_admin_document_event(
                {
                    "expediente_id": 1000,
                    "file_name": (
                        "resolucion_favorable_prueba.pdf"
                    ),
                    "event_code": (
                        "RESOLUCION_FAVORABLE"
                    ),
                    "favorable_resolution_extraction": {
                        "fecha_resolucion": (
                            "2026-08-05"
                        ),
                        "csv_resolucion": (
                            "CSV-RESOLUCION-TEST"
                        ),
                        "unidad_tramitacion_codigo": (
                            "EA0000001"
                        ),
                        "unidad_tramitacion_nombre": (
                            "OFICINA DE EXTRANJERÍA"
                        ),
                        "numero_expediente_extranjeria": (
                            "EX-TEST-2026"
                        ),
                    },
                    "usuario": "TEST",
                }
            )
        )

        self.assertTrue(
            event_result["transition_applied"]
        )
        self.assertEqual(
            event_result["estado_nuevo"],
            "RESUELTO FAVORABLE",
        )

        evaluation = event_result[
            "derivation_evaluation"
        ]

        self.assertTrue(evaluation["ok"])
        self.assertEqual(
            evaluation["rules_evaluated"],
            1,
        )
        self.assertEqual(
            len(evaluation["proposals"]),
            1,
        )

        proposal_id = evaluation[
            "proposals"
        ][0]["proposal"]["id"]

        with closing(
            sqlite3.connect(self.db_path)
        ) as conn:
            conn.row_factory = sqlite3.Row

            source = conn.execute(
                """
                SELECT
                    e.*,
                    a.nombre AS estado_nombre
                FROM expedientes e
                LEFT JOIN config_estados_administrativos a
                  ON a.id = e.estado_administrativo_id
                WHERE e.id = 1000
                """
            ).fetchone()

            proposal = conn.execute(
                """
                SELECT
                    p.*,
                    f.codigo AS familia_destino_codigo,
                    t.codigo AS tipo_destino_codigo
                FROM expediente_derivacion_propuestas p
                JOIN config_familias_expediente f
                  ON f.id = p.familia_destino_id
                JOIN config_tipos_expediente t
                  ON t.id =
                     p.tipo_expediente_destino_id
                WHERE p.id = ?
                """,
                (proposal_id,),
            ).fetchone()

            justificantes = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_justificantes
                WHERE expediente_id = 1000
                  AND tipo_justificante =
                      'RESOLUCION_FAVORABLE'
                  AND activo = 1
                """
            ).fetchone()[0]

        self.assertEqual(
            source["estado_nombre"],
            "RESUELTO FAVORABLE",
        )
        self.assertEqual(justificantes, 1)
        self.assertEqual(
            proposal["estado"],
            "PENDIENTE",
        )
        self.assertEqual(
            proposal["familia_destino_codigo"],
            "TRAMITES_CONSULARES",
        )
        self.assertEqual(
            proposal["tipo_destino_codigo"],
            "VISADO_REAGRUPACION_FAMILIAR",
        )

        acceptance = (
            expedient_evolution_service
            .accept_derivation_proposal(
                proposal_id=proposal_id,
                usuario="TEST",
            )
        )

        self.assertTrue(acceptance["created"])
        self.assertFalse(
            acceptance["already_created"]
        )

        destination_id = acceptance[
            "expediente_destino"
        ]["id"]

        second_evaluation = (
            expedient_evolution_service
            .evaluate_derivation_rules_for_event(
                expediente_id=1000,
                event_code="RESOLUCION_FAVORABLE",
                resultado="CONCEDIDO",
                usuario="TEST",
            )
        )

        second_acceptance = (
            expedient_evolution_service
            .accept_derivation_proposal(
                proposal_id=proposal_id,
                usuario="TEST",
            )
        )

        self.assertEqual(
            len(second_evaluation["proposals"]),
            1,
        )
        self.assertTrue(
            second_evaluation[
                "proposals"
            ][0]["already_existed"]
        )
        self.assertTrue(
            second_acceptance["already_created"]
        )
        self.assertFalse(
            second_acceptance["created"]
        )
        self.assertEqual(
            second_acceptance[
                "expediente_destino"
            ]["id"],
            destination_id,
        )

        with closing(
            sqlite3.connect(self.db_path)
        ) as conn:
            conn.row_factory = sqlite3.Row

            destination = conn.execute(
                """
                SELECT
                    e.*,
                    t.codigo AS tipo_codigo,
                    f.codigo AS familia_codigo
                FROM expedientes e
                JOIN config_tipos_expediente t
                  ON t.id = e.tipo_expediente_id
                JOIN config_familias_expediente f
                  ON f.id = t.familia_id
                WHERE e.id = ?
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

            final_proposal = conn.execute(
                """
                SELECT *
                FROM expediente_derivacion_propuestas
                WHERE id = ?
                """,
                (proposal_id,),
            ).fetchone()

            destination_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expedientes
                WHERE id <> 1000
                """
            ).fetchone()[0]

            relation_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_relaciones
                WHERE expediente_origen_id = 1000
                """
            ).fetchone()[0]

            proposal_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_derivacion_propuestas
                WHERE expediente_origen_id = 1000
                """
            ).fetchone()[0]

            origin_events = conn.execute(
                """
                SELECT tipo_evento
                FROM expediente_eventos
                WHERE expediente_id = 1000
                """
            ).fetchall()

            destination_events = conn.execute(
                """
                SELECT tipo_evento
                FROM expediente_eventos
                WHERE expediente_id = ?
                """,
                (destination_id,),
            ).fetchall()

        self.assertEqual(
            destination["cliente_id"],
            1,
        )
        self.assertEqual(
            destination["tipo_codigo"],
            "VISADO_REAGRUPACION_FAMILIAR",
        )
        self.assertEqual(
            destination["familia_codigo"],
            "TRAMITES_CONSULARES",
        )
        self.assertEqual(
            destination["responsable"],
            "NACHO",
        )
        self.assertEqual(
            destination["provincia"],
            "ASTURIAS",
        )

        self.assertEqual(
            relation["tipo_relacion"],
            "ACTUACION_POSTERIOR",
        )
        self.assertEqual(
            final_proposal["estado"],
            "CREADA",
        )
        self.assertEqual(
            final_proposal[
                "expediente_destino_id"
            ],
            destination_id,
        )

        self.assertEqual(destination_count, 1)
        self.assertEqual(relation_count, 1)
        self.assertEqual(proposal_count, 1)

        origin_event_codes = {
            row["tipo_evento"]
            for row in origin_events
        }

        destination_event_codes = {
            row["tipo_evento"]
            for row in destination_events
        }

        self.assertIn(
            "DOCUMENTO_ADMINISTRATIVO",
            origin_event_codes,
        )
        self.assertIn(
            "PROPUESTA_DERIVACION_GENERADA",
            origin_event_codes,
        )
        self.assertIn(
            "EXPEDIENTE_DERIVADO_CREADO",
            origin_event_codes,
        )
        self.assertIn(
            "EXPEDIENTE_CREADO_DESDE_DERIVACION",
            destination_event_codes,
        )


if __name__ == "__main__":
    unittest.main()
