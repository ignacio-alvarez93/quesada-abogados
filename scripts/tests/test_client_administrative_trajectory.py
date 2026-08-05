import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import client_administrative_status_service


class ClientAdministrativeTrajectoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "client_administrative.db"
        )

        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                fecha_caducidad_residencia TEXT,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                numero_expediente TEXT NOT NULL
            );

            INSERT INTO clientes (
                id,
                nombre,
                fecha_caducidad_residencia
            )
            VALUES (
                1,
                'CLIENTE PRUEBA',
                '2027-05-10'
            );

            INSERT INTO expedientes (
                id,
                cliente_id,
                numero_expediente
            )
            VALUES (
                100,
                1,
                'EXP-2026-0100'
            );
            """
        )
        conn.commit()
        conn.close()

        self.db_patch = patch.object(
            client_administrative_status_service,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_schema_is_created_without_losing_existing_expiry(self):
        client_administrative_status_service.ensure_client_administrative_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(clientes)"
                ).fetchall()
            }

            expiry = conn.execute(
                """
                SELECT fecha_caducidad_residencia
                FROM clientes
                WHERE id = 1
                """
            ).fetchone()[0]

        self.assertIn("numero_soporte_nie", columns)
        self.assertIn("localizacion_actual", columns)
        self.assertIn("situacion_administrativa_id", columns)
        self.assertIn("autorizacion_actual_id", columns)
        self.assertEqual(expiry, "2027-05-10")

    def test_initialization_is_idempotent(self):
        client_administrative_status_service.ensure_client_administrative_schema()
        client_administrative_status_service.ensure_client_administrative_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            situations = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_situaciones_administrativas
                """
            ).fetchone()[0]

        self.assertEqual(situations, 16)

    def test_only_one_current_authorization_per_client(self):
        client_administrative_status_service.ensure_client_administrative_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            situation_id = conn.execute(
                """
                SELECT id
                FROM config_situaciones_administrativas
                WHERE codigo = 'RESIDENCIA_TEMPORAL'
                """
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO config_tipos_autorizacion (
                    codigo,
                    nombre,
                    familia_codigo
                )
                VALUES (
                    'TEST_AUTORIZACION',
                    'AUTORIZACIÓN DE PRUEBA',
                    'EXTRANJERIA'
                )
                """
            )

            authorization_type_id = conn.execute(
                """
                SELECT id
                FROM config_tipos_autorizacion
                WHERE codigo = 'TEST_AUTORIZACION'
                """
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO cliente_autorizaciones (
                    cliente_id,
                    situacion_administrativa_id,
                    tipo_autorizacion_id,
                    es_actual
                )
                VALUES (?, ?, ?, 1)
                """,
                (
                    1,
                    situation_id,
                    authorization_type_id,
                ),
            )

            conn.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO cliente_autorizaciones (
                        cliente_id,
                        situacion_administrativa_id,
                        tipo_autorizacion_id,
                        es_actual
                    )
                    VALUES (?, ?, ?, 1)
                    """,
                    (
                        1,
                        situation_id,
                        authorization_type_id,
                    ),
                )

    def test_get_current_authorization(self):
        client_administrative_status_service.ensure_client_administrative_schema()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            situation_id = conn.execute(
                """
                SELECT id
                FROM config_situaciones_administrativas
                WHERE codigo = 'RESIDENCIA_TEMPORAL'
                """
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO config_tipos_autorizacion (
                    codigo,
                    nombre,
                    familia_codigo
                )
                VALUES (
                    'ARRAIGO_SOCIAL',
                    'ARRAIGO SOCIAL',
                    'EXTRANJERIA'
                )
                """
            )

            authorization_type_id = conn.execute(
                """
                SELECT id
                FROM config_tipos_autorizacion
                WHERE codigo = 'ARRAIGO_SOCIAL'
                """
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO cliente_autorizaciones (
                    cliente_id,
                    situacion_administrativa_id,
                    tipo_autorizacion_id,
                    estado_autorizacion,
                    fecha_vigencia_desde,
                    fecha_vigencia_hasta,
                    expediente_origen_id,
                    es_actual
                )
                VALUES (
                    1,
                    ?,
                    ?,
                    'VIGENTE',
                    '2026-05-10',
                    '2027-05-10',
                    100,
                    1
                )
                """,
                (
                    situation_id,
                    authorization_type_id,
                ),
            )
            conn.commit()

        current = (
            client_administrative_status_service
            .get_current_authorization(1)
        )

        self.assertIsNotNone(current)
        self.assertEqual(
            current["autorizacion_codigo"],
            "ARRAIGO_SOCIAL",
        )
        self.assertEqual(
            current["situacion_codigo"],
            "RESIDENCIA_TEMPORAL",
        )


if __name__ == "__main__":
    unittest.main()
