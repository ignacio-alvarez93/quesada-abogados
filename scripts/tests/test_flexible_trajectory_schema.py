import gc
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260805_create_flexible_trajectory_schema.sql"
)


class FlexibleTrajectorySchemaTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "flexible_trajectory.db"
        )

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

        self.conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER NOT NULL,
                numero_expediente TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,

                FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE expediente_relaciones (
                id INTEGER PRIMARY KEY,
                expediente_origen_id INTEGER NOT NULL,
                expediente_destino_id INTEGER NOT NULL,
                tipo_relacion TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,

                FOREIGN KEY (expediente_origen_id)
                    REFERENCES expedientes(id)
                    ON DELETE CASCADE,

                FOREIGN KEY (expediente_destino_id)
                    REFERENCES expedientes(id)
                    ON DELETE CASCADE
            );

            INSERT INTO clientes (
                id,
                nombre
            )
            VALUES
                (1, 'CLIENTE UNO'),
                (2, 'CLIENTE DOS');

            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente
            )
            VALUES
                (100, 1, 'EXP-100'),
                (101, 1, 'EXP-101'),
                (200, 2, 'EXP-200');

            INSERT INTO expediente_relaciones (
                id,
                expediente_origen_id,
                expediente_destino_id,
                tipo_relacion
            )
            VALUES (
                500,
                100,
                101,
                'ACTUACION_POSTERIOR'
            );
            """
        )

        self.conn.executescript(
            MIGRATION.read_text(
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

    def test_schema_is_idempotent(self):
        self.conn.executescript(
            MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        self.conn.executescript(
            MIGRATION.read_text(
                encoding="utf-8"
            )
        )

        tables = {
            row["name"]
            for row in self.conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        self.assertIn(
            "expediente_origenes_creacion",
            tables,
        )
        self.assertIn(
            "expediente_relacion_origenes",
            tables,
        )
        self.assertIn(
            "expediente_hitos_externos",
            tables,
        )

    def test_registers_manual_and_derived_origins(self):
        self.conn.execute(
            """
            INSERT INTO expediente_origenes_creacion (
                expediente_id,
                origen_creacion,
                descripcion,
                created_by
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                100,
                "APERTURA_MANUAL",
                "Servicio contratado directamente.",
                "TEST",
            ),
        )

        self.conn.execute(
            """
            INSERT INTO expediente_origenes_creacion (
                expediente_id,
                origen_creacion,
                descripcion,
                created_by
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                101,
                "DERIVACION_INTERNA",
                "Creado desde otro expediente.",
                "TEST",
            ),
        )

        self.conn.execute(
            """
            INSERT INTO expediente_relacion_origenes (
                relacion_id,
                origen_relacion,
                descripcion,
                created_by
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                500,
                "DERIVACION_AUTOMATICA",
                "Relación creada por una regla.",
                "TEST",
            ),
        )

        origins = self.conn.execute(
            """
            SELECT
                expediente_id,
                origen_creacion
            FROM expediente_origenes_creacion
            ORDER BY expediente_id
            """
        ).fetchall()

        relation_origin = self.conn.execute(
            """
            SELECT
                relacion_id,
                origen_relacion
            FROM expediente_relacion_origenes
            WHERE relacion_id = 500
            """
        ).fetchone()

        self.assertEqual(
            [
                (
                    row["expediente_id"],
                    row["origen_creacion"],
                )
                for row in origins
            ],
            [
                (100, "APERTURA_MANUAL"),
                (101, "DERIVACION_INTERNA"),
            ],
        )

        self.assertEqual(
            relation_origin["origen_relacion"],
            "DERIVACION_AUTOMATICA",
        )

    def test_registers_external_milestone_between_expedients(
        self,
    ):
        cursor = self.conn.execute(
            """
            INSERT INTO expediente_hitos_externos (
                cliente_id,
                codigo,
                nombre,
                familia_referencia_codigo,
                tipo_referencia_codigo,
                fecha_fin,
                estado,
                resultado,
                observaciones,
                expediente_anterior_id,
                expediente_posterior_id,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "VISADO_REAGRUPACION_EXTERNO",
                (
                    "Visado de Reagrupación Familiar "
                    "tramitado externamente"
                ),
                "TRAMITES_CONSULARES",
                "VISADO_REAGRUPACION_FAMILIAR",
                "2026-08-01",
                "FINALIZADO",
                "CONCEDIDO",
                (
                    "El cliente gestionó el visado "
                    "por su cuenta."
                ),
                100,
                101,
                "TEST",
            ),
        )

        milestone = self.conn.execute(
            """
            SELECT *
            FROM expediente_hitos_externos
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

        self.assertEqual(
            milestone["cliente_id"],
            1,
        )
        self.assertEqual(
            milestone["codigo"],
            "VISADO_REAGRUPACION_EXTERNO",
        )
        self.assertEqual(
            milestone["resultado"],
            "CONCEDIDO",
        )
        self.assertEqual(
            milestone["expediente_anterior_id"],
            100,
        )
        self.assertEqual(
            milestone["expediente_posterior_id"],
            101,
        )

    def test_external_milestone_requires_a_link(self):
        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.conn.execute(
                """
                INSERT INTO expediente_hitos_externos (
                    cliente_id,
                    codigo,
                    nombre
                )
                VALUES (?, ?, ?)
                """,
                (
                    1,
                    "VISADO_EXTERNO",
                    "Visado externo",
                ),
            )

    def test_duplicate_active_milestone_is_rejected(self):
        values = (
            1,
            "VISADO_REAGRUPACION_EXTERNO",
            "Visado externo",
            100,
            101,
        )

        self.conn.execute(
            """
            INSERT INTO expediente_hitos_externos (
                cliente_id,
                codigo,
                nombre,
                expediente_anterior_id,
                expediente_posterior_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            values,
        )

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.conn.execute(
                """
                INSERT INTO expediente_hitos_externos (
                    cliente_id,
                    codigo,
                    nombre,
                    expediente_anterior_id,
                    expediente_posterior_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                values,
            )

    def test_invalid_origin_codes_are_rejected(self):
        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.conn.execute(
                """
                INSERT INTO expediente_origenes_creacion (
                    expediente_id,
                    origen_creacion
                )
                VALUES (?, ?)
                """,
                (
                    100,
                    "ORIGEN_INVENTADO",
                ),
            )

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            self.conn.execute(
                """
                INSERT INTO expediente_relacion_origenes (
                    relacion_id,
                    origen_relacion
                )
                VALUES (?, ?)
                """,
                (
                    500,
                    "RELACION_INVENTADA",
                ),
            )


if __name__ == "__main__":
    unittest.main()
