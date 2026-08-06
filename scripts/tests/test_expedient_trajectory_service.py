import gc
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_evolution_service
from backend.services import expedient_service
from backend.services import expedient_trajectory_service


ROOT = Path(__file__).resolve().parents[2]

EVOLUTION_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_create_expedient_evolution_schema.sql"
)

TRAJECTORY_MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_create_flexible_trajectory_schema.sql"
)


class ExpedientTrajectoryServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "trajectory_service.db"
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

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
                numero_expediente TEXT NOT NULL UNIQUE,
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

            INSERT INTO clientes (
                id,
                nombre
            )
            VALUES
                (1, 'CLIENTE UNO'),
                (2, 'CLIENTE DOS');

            INSERT INTO config_familias_expediente (
                id,
                codigo,
                nombre
            )
            VALUES
                (
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERÍA'
                ),
                (
                    2,
                    'TRAMITES_CONSULARES',
                    'TRÁMITES CONSULARES'
                ),
                (
                    3,
                    'DOCUMENTACION_EXTRANJEROS',
                    'DOCUMENTACIÓN DE EXTRANJEROS'
                );

            INSERT INTO config_tipos_expediente (
                id,
                codigo,
                nombre,
                familia_id
            )
            VALUES
                (
                    10,
                    'REAGRUPACION_FAMILIAR',
                    'REAGRUPACIÓN FAMILIAR',
                    1
                ),
                (
                    20,
                    'VISADO_REAGRUPACION_FAMILIAR',
                    'VISADO DE REAGRUPACIÓN FAMILIAR',
                    2
                ),
                (
                    30,
                    'TOMA_HUELLAS',
                    'TOMA DE HUELLAS',
                    3
                );

            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente,
                tipo_expediente_id,
                responsable,
                provincia,
                activo
            )
            VALUES
                (
                    100,
                    1,
                    'EXP-2026-0100',
                    10,
                    'NACHO',
                    'ASTURIAS',
                    1
                ),
                (
                    200,
                    2,
                    'EXP-2026-0200',
                    10,
                    'OTRO',
                    'MADRID',
                    1
                );
            """
        )

        conn.executescript(
            EVOLUTION_MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        conn.executescript(
            TRAJECTORY_MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        conn.commit()
        conn.close()

        self.patches = [
            patch.object(
                expedient_service,
                "DB_PATH",
                self.db_path,
            ),
            patch.object(
                expedient_evolution_service,
                "DB_PATH",
                self.db_path,
            ),
            patch.object(
                expedient_trajectory_service,
                "DB_PATH",
                self.db_path,
            ),
        ]

        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

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

    def _new_data(
        self,
        cliente_id=1,
        tipo_id=30,
    ):
        return {
            "cliente_id": cliente_id,
            "numero_expediente": "",
            "tipo_expediente_id": tipo_id,
            "subtipo_expediente_id": None,
            "estado_documental_id": None,
            "estado_administrativo_id": None,
            "estado_presentacion":
                "NO PRESENTADO",
            "prioridad_id": None,
            "responsable": "NACHO",
            "fecha_apertura": "2026-08-05",
            "fecha_presentacion": None,
            "fecha_resolucion": None,
            "numero_registro": "",
            "organo_presentacion": "",
            "provincia": "ASTURIAS",
            "observaciones": "",
            "observaciones_internas": "",
            "box_folder_path": "",
            "activo": 1,
        }

    def test_creates_independent_expedient(self):
        result = (
            expedient_trajectory_service
            .create_expedient_with_continuity(
                expediente_data=self._new_data(),
                continuity={
                    "mode": "INDEPENDENT",
                },
                usuario="TEST",
            )
        )

        expediente_id = result["expediente"]["id"]

        self.assertEqual(
            result["mode"],
            "INDEPENDENT",
        )
        self.assertIsNone(result["relation"])
        self.assertIsNone(result["milestone"])
        self.assertEqual(
            result["creation_origin"][
                "origen_creacion"
            ],
            "APERTURA_MANUAL",
        )

        with sqlite3.connect(self.db_path) as conn:
            relation_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_relaciones
                """
            ).fetchone()[0]

            event_codes = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT tipo_evento
                    FROM expediente_eventos
                    WHERE expediente_id = ?
                    """,
                    (expediente_id,),
                ).fetchall()
            }

        self.assertEqual(relation_count, 0)
        self.assertEqual(
            event_codes,
            {
                "EXPEDIENTE_CREADO_MANUALMENTE",
            },
        )

    def test_creates_direct_manual_continuity(self):
        result = (
            expedient_trajectory_service
            .create_expedient_with_continuity(
                expediente_data=self._new_data(),
                continuity={
                    "mode": "DIRECT_RELATION",
                    "previous_expedient_id": 100,
                    "relation_type":
                        "ACTUACION_POSTERIOR",
                    "reason":
                        "Continuidad contratada.",
                },
                usuario="TEST",
            )
        )

        new_id = result["expediente"]["id"]

        self.assertEqual(
            result["creation_origin"][
                "origen_creacion"
            ],
            "CONTINUIDAD_MANUAL",
        )

        self.assertEqual(
            result["relation"][
                "relation"
            ]["expediente_origen_id"],
            100,
        )

        self.assertEqual(
            result["relation"][
                "relation"
            ]["expediente_destino_id"],
            new_id,
        )

        self.assertEqual(
            result["relation"][
                "relation_origin"
            ]["origen_relacion"],
            "VINCULACION_MANUAL",
        )

        with sqlite3.connect(self.db_path) as conn:
            relation_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_relaciones
                """
            ).fetchone()[0]

            new_events = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT tipo_evento
                    FROM expediente_eventos
                    WHERE expediente_id = ?
                    """,
                    (new_id,),
                ).fetchall()
            }

            previous_events = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT tipo_evento
                    FROM expediente_eventos
                    WHERE expediente_id = 100
                    """
                ).fetchall()
            }

        self.assertEqual(relation_count, 1)

        self.assertIn(
            "EXPEDIENTE_VINCULADO_MANUALMENTE",
            new_events,
        )

        self.assertIn(
            "EXPEDIENTE_POSTERIOR_VINCULADO",
            previous_events,
        )

    def test_creates_external_milestone_continuity(
        self,
    ):
        result = (
            expedient_trajectory_service
            .create_expedient_with_continuity(
                expediente_data=self._new_data(),
                continuity={
                    "mode":
                        "EXTERNAL_MILESTONE",
                    "previous_expedient_id": 100,
                    "milestone": {
                        "codigo":
                            "VISADO_REAGRUPACION_EXTERNO",
                        "nombre":
                            "Visado de Reagrupación Familiar",
                        "familia_referencia_codigo":
                            "TRAMITES_CONSULARES",
                        "tipo_referencia_codigo":
                            "VISADO_REAGRUPACION_FAMILIAR",
                        "fecha_fin":
                            "2026-08-01",
                        "estado":
                            "FINALIZADO",
                        "resultado":
                            "CONCEDIDO",
                        "observaciones":
                            (
                                "El cliente lo tramitó "
                                "por su cuenta."
                            ),
                    },
                },
                usuario="TEST",
            )
        )

        new_id = result["expediente"]["id"]
        milestone = result["milestone"]

        self.assertEqual(
            result["creation_origin"][
                "origen_creacion"
            ],
            "CONTINUIDAD_CON_HITO_EXTERNO",
        )

        self.assertIsNone(result["relation"])
        self.assertEqual(
            milestone["expediente_anterior_id"],
            100,
        )
        self.assertEqual(
            milestone["expediente_posterior_id"],
            new_id,
        )
        self.assertEqual(
            milestone["resultado"],
            "CONCEDIDO",
        )

        with sqlite3.connect(self.db_path) as conn:
            relation_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_relaciones
                """
            ).fetchone()[0]

            milestone_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_hitos_externos
                """
            ).fetchone()[0]

        self.assertEqual(relation_count, 0)
        self.assertEqual(milestone_count, 1)

    def test_external_milestone_can_have_only_posterior(
        self,
    ):
        result = (
            expedient_trajectory_service
            .create_expedient_with_continuity(
                expediente_data=self._new_data(),
                continuity={
                    "mode":
                        "EXTERNAL_MILESTONE",
                    "milestone": {
                        "codigo":
                            "VISADO_REAGRUPACION_EXTERNO",
                        "nombre":
                            "Visado externo",
                        "estado":
                            "FINALIZADO",
                        "resultado":
                            "CONCEDIDO",
                    },
                },
                usuario="TEST",
            )
        )

        self.assertIsNone(
            result["milestone"][
                "expediente_anterior_id"
            ]
        )

        self.assertEqual(
            result["milestone"][
                "expediente_posterior_id"
            ],
            result["expediente"]["id"],
        )

    def test_rolls_back_when_clients_do_not_match(
        self,
    ):
        with self.assertRaises(ValueError):
            (
                expedient_trajectory_service
                .create_expedient_with_continuity(
                    expediente_data=self._new_data(
                        cliente_id=1
                    ),
                    continuity={
                        "mode":
                            "DIRECT_RELATION",
                        "previous_expedient_id": 200,
                    },
                    usuario="TEST",
                )
            )

        with sqlite3.connect(self.db_path) as conn:
            expediente_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expedientes
                """
            ).fetchone()[0]

            origin_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_origenes_creacion
                """
            ).fetchone()[0]

            relation_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_relaciones
                """
            ).fetchone()[0]

        self.assertEqual(expediente_count, 2)
        self.assertEqual(origin_count, 0)
        self.assertEqual(relation_count, 0)

    def test_manual_relation_rejects_cycle(self):
        first = (
            expedient_trajectory_service
            .create_expedient_with_continuity(
                expediente_data=self._new_data(),
                continuity={
                    "mode": "DIRECT_RELATION",
                    "previous_expedient_id": 100,
                },
                usuario="TEST",
            )
        )

        new_id = first["expediente"]["id"]

        with self.assertRaisesRegex(
            ValueError,
            "ciclo",
        ):
            (
                expedient_trajectory_service
                .create_manual_expedient_relation(
                    expediente_origen_id=new_id,
                    expediente_destino_id=100,
                    usuario="TEST",
                )
            )

    def test_lists_external_milestones(self):
        created = (
            expedient_trajectory_service
            .create_expedient_with_continuity(
                expediente_data=self._new_data(),
                continuity={
                    "mode":
                        "EXTERNAL_MILESTONE",
                    "previous_expedient_id": 100,
                    "milestone": {
                        "codigo":
                            "VISADO_REAGRUPACION_EXTERNO",
                        "nombre":
                            "Visado externo",
                        "estado":
                            "FINALIZADO",
                    },
                },
                usuario="TEST",
            )
        )

        items = (
            expedient_trajectory_service
            .list_external_milestones(
                expediente_id=(
                    created["expediente"]["id"]
                )
            )
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["codigo"],
            "VISADO_REAGRUPACION_EXTERNO",
        )
        self.assertEqual(
            items[0]["expediente_anterior_numero"],
            "EXP-2026-0100",
        )


    def _create_test_milestone(self):
        return (
            expedient_trajectory_service
            .create_external_milestone(
                cliente_id=1,
                milestone={
                    "codigo":
                        "VISADO_EXTERNO",
                    "nombre":
                        "Visado externo",
                    "fecha_inicio":
                        "2026-07-01",
                    "estado":
                        "EN_TRAMITE",
                    "observaciones":
                        "Pendiente de resolución.",
                },
                expediente_anterior_id=100,
                usuario="TEST",
            )
        )

    def test_gets_external_milestone(self):
        created = self._create_test_milestone()

        item = (
            expedient_trajectory_service
            .get_external_milestone(
                created["id"]
            )
        )

        self.assertEqual(
            item["codigo"],
            "VISADO_EXTERNO",
        )

        self.assertEqual(
            item["expediente_anterior_numero"],
            "EXP-2026-0100",
        )

    def test_updates_external_milestone(self):
        created = self._create_test_milestone()

        updated = (
            expedient_trajectory_service
            .update_external_milestone(
                created["id"],
                {
                    "nombre":
                        "Visado de reagrupación",
                    "estado":
                        "EN_TRAMITE",
                    "observaciones":
                        "Documentación presentada.",
                    "documento_referencia":
                        "BOX/VISADO.pdf",
                },
                usuario="TEST",
            )
        )

        self.assertEqual(
            updated["nombre"],
            "Visado de reagrupación",
        )

        self.assertEqual(
            updated["documento_referencia"],
            "BOX/VISADO.pdf",
        )

        with sqlite3.connect(
            self.db_path
        ) as conn:
            event_types = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT tipo_evento
                    FROM expediente_eventos
                    WHERE expediente_id = 100
                    """
                ).fetchall()
            }

        self.assertIn(
            "HITO_EXTERNO_ACTUALIZADO",
            event_types,
        )

    def test_rejects_editing_trajectory_edges(self):
        created = self._create_test_milestone()

        with self.assertRaisesRegex(
            ValueError,
            "extremos de la trayectoria",
        ):
            (
                expedient_trajectory_service
                .update_external_milestone(
                    created["id"],
                    {
                        "expediente_posterior_id":
                            200,
                    },
                    usuario="TEST",
                )
            )

    def test_rejects_invalid_date_range(self):
        created = self._create_test_milestone()

        with self.assertRaisesRegex(
            ValueError,
            "fecha final",
        ):
            (
                expedient_trajectory_service
                .update_external_milestone(
                    created["id"],
                    {
                        "fecha_fin":
                            "2026-06-01",
                    },
                    usuario="TEST",
                )
            )

    def test_completes_external_milestone(self):
        created = self._create_test_milestone()

        completed = (
            expedient_trajectory_service
            .complete_external_milestone(
                created["id"],
                resultado="CONCEDIDO",
                fecha_fin="2026-08-05",
                observaciones=(
                    "Visado concedido."
                ),
                usuario="TEST",
            )
        )

        self.assertEqual(
            completed["estado"],
            "FINALIZADO",
        )

        self.assertEqual(
            completed["resultado"],
            "CONCEDIDO",
        )

        self.assertEqual(
            completed["fecha_fin"],
            "2026-08-05",
        )

        with sqlite3.connect(
            self.db_path
        ) as conn:
            event_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_eventos
                WHERE expediente_id = 100
                  AND tipo_evento =
                      'HITO_EXTERNO_FINALIZADO'
                """
            ).fetchone()[0]

        self.assertEqual(
            event_count,
            1,
        )

    def test_deactivates_external_milestone(self):
        created = self._create_test_milestone()

        result = (
            expedient_trajectory_service
            .deactivate_external_milestone(
                created["id"],
                usuario="TEST",
                motivo="Registro duplicado.",
            )
        )

        self.assertEqual(
            result["activo"],
            0,
        )

        active_items = (
            expedient_trajectory_service
            .list_external_milestones(
                expediente_id=100,
                active_only=True,
            )
        )

        all_items = (
            expedient_trajectory_service
            .list_external_milestones(
                expediente_id=100,
                active_only=False,
            )
        )

        self.assertEqual(
            active_items,
            [],
        )

        self.assertEqual(
            len(all_items),
            1,
        )

        with sqlite3.connect(
            self.db_path
        ) as conn:
            event_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_eventos
                WHERE expediente_id = 100
                  AND tipo_evento =
                      'HITO_EXTERNO_DESACTIVADO'
                """
            ).fetchone()[0]

        self.assertEqual(
            event_count,
            1,
        )


if __name__ == "__main__":
    unittest.main()
