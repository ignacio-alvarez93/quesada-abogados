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


    def test_form_situations_exclude_location_codes(
        self,
    ):
        situations = (
            client_administrative_status_service
            .list_administrative_situations()
        )

        codes = {
            item["codigo"]
            for item in situations
        }

        self.assertNotIn(
            "EN_ORIGEN",
            codes,
        )

        self.assertNotIn(
            "NO_HA_ENTRADO_EN_ESPANA",
            codes,
        )

        self.assertIn(
            "RESIDENCIA_TEMPORAL",
            codes,
        )

    def test_updates_client_administrative_snapshot(
        self,
    ):
        result = (
            client_administrative_status_service
            .update_client_administrative_snapshot(
                client_id=1,
                data={
                    "numero_soporte_nie":
                        "C01234567",
                    "localizacion_actual":
                        "EN_ESPANA",
                    "pais_localizacion_actual":
                        "España",
                    "fecha_entrada_espana":
                        "2024-02-15",
                    "fecha_entrada_espana_aproximada":
                        True,
                },
            )
        )

        self.assertEqual(
            result["numero_soporte_nie"],
            "C01234567",
        )

        self.assertEqual(
            result["localizacion_actual"],
            "EN_ESPANA",
        )

        self.assertEqual(
            result[
                "fecha_entrada_espana_aproximada"
            ],
            1,
        )

    def test_sets_current_authorization_and_syncs_client(
        self,
    ):
        client_administrative_status_service.ensure_client_administrative_schema()

        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.row_factory = sqlite3.Row

            situation_id = conn.execute(
                """
                SELECT id
                FROM config_situaciones_administrativas
                WHERE codigo =
                      'RESIDENCIA_TEMPORAL'
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
                    'REAGRUPACION_FAMILIAR',
                    'REAGRUPACIÓN FAMILIAR',
                    'EXTRANJERIA'
                )
                """
            )

            authorization_type_id = (
                conn.execute(
                    """
                    SELECT id
                    FROM config_tipos_autorizacion
                    WHERE codigo =
                          'REAGRUPACION_FAMILIAR'
                    """
                ).fetchone()["id"]
            )

            conn.commit()

        current = (
            client_administrative_status_service
            .set_current_authorization(
                client_id=1,
                authorization_data={
                    "situacion_administrativa_id":
                        situation_id,
                    "tipo_autorizacion_id":
                        authorization_type_id,
                    "fecha_vigencia_desde":
                        "2026-08-05",
                    "fecha_vigencia_hasta":
                        "2027-08-04",
                    "expediente_origen_id":
                        100,
                },
                usuario="TEST",
            )
        )

        self.assertEqual(
            current["autorizacion_codigo"],
            "REAGRUPACION_FAMILIAR",
        )

        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.row_factory = sqlite3.Row

            client = conn.execute(
                """
                SELECT
                    situacion_administrativa_id,
                    autorizacion_actual_id,
                    fecha_caducidad_residencia,
                    fecha_caducidad_origen,
                    fecha_caducidad_expediente_id
                FROM clientes
                WHERE id = 1
                """
            ).fetchone()

        self.assertEqual(
            client["situacion_administrativa_id"],
            situation_id,
        )

        self.assertEqual(
            client["autorizacion_actual_id"],
            current["id"],
        )

        self.assertEqual(
            client["fecha_caducidad_residencia"],
            "2027-08-04",
        )

        self.assertEqual(
            client["fecha_caducidad_origen"],
            "AUTORIZACION_CLIENTE",
        )

        self.assertEqual(
            client[
                "fecha_caducidad_expediente_id"
            ],
            100,
        )

    def test_new_current_authorization_preserves_history(
        self,
    ):
        client_administrative_status_service.ensure_client_administrative_schema()

        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.row_factory = sqlite3.Row

            situation_id = conn.execute(
                """
                SELECT id
                FROM config_situaciones_administrativas
                WHERE codigo =
                      'RESIDENCIA_TEMPORAL'
                """
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO config_tipos_autorizacion (
                    codigo,
                    nombre,
                    familia_codigo
                )
                VALUES
                    (
                        'AUTORIZACION_UNO',
                        'AUTORIZACIÓN UNO',
                        'EXTRANJERIA'
                    ),
                    (
                        'AUTORIZACION_DOS',
                        'AUTORIZACIÓN DOS',
                        'EXTRANJERIA'
                    )
                """
            )

            type_ids = {
                row["codigo"]: row["id"]
                for row in conn.execute(
                    """
                    SELECT id, codigo
                    FROM config_tipos_autorizacion
                    """
                ).fetchall()
            }

            conn.commit()

        first = (
            client_administrative_status_service
            .set_current_authorization(
                client_id=1,
                authorization_data={
                    "situacion_administrativa_id":
                        situation_id,
                    "tipo_autorizacion_id":
                        type_ids[
                            "AUTORIZACION_UNO"
                        ],
                },
            )
        )

        second = (
            client_administrative_status_service
            .set_current_authorization(
                client_id=1,
                authorization_data={
                    "situacion_administrativa_id":
                        situation_id,
                    "tipo_autorizacion_id":
                        type_ids[
                            "AUTORIZACION_DOS"
                        ],
                },
            )
        )

        history = (
            client_administrative_status_service
            .list_client_authorizations(1)
        )

        self.assertEqual(
            len(history),
            2,
        )

        self.assertEqual(
            sum(
                int(item["es_actual"])
                for item in history
            ),
            1,
        )

        self.assertEqual(
            second["es_actual"],
            1,
        )

        previous = next(
            item
            for item in history
            if item["id"] == first["id"]
        )

        self.assertEqual(
            previous["es_actual"],
            0,
        )

        self.assertTrue(
            previous["motivo_fin"]
        )


if __name__ == "__main__":
    unittest.main()
