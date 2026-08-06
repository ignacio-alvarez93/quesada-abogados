import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    client_administrative_status_service
)


class ClientAuthorizationCatalogTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "client_authorization_catalog.db"
        )

        conn = sqlite3.connect(
            self.db_path
        )

        conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                fecha_caducidad_residencia TEXT,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER,
                numero_expediente TEXT
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

    def test_catalog_is_seeded(
        self,
    ):
        (
            client_administrative_status_service
            .ensure_client_administrative_schema()
        )

        catalog = (
            client_administrative_status_service
            .list_authorization_types()
        )

        self.assertGreaterEqual(
            len(catalog),
            30,
        )

    def test_reagrupacion_uses_full_title(
        self,
    ):
        (
            client_administrative_status_service
            .ensure_client_administrative_schema()
        )

        catalog = (
            client_administrative_status_service
            .list_authorization_types()
        )

        item = next(
            entry
            for entry in catalog
            if entry["codigo"]
            == (
                "RESIDENCIA_TEMPORAL_"
                "REAGRUPACION_FAMILIAR"
            )
        )

        self.assertEqual(
            item["nombre"],
            (
                "AUTORIZACIÓN DE RESIDENCIA "
                "TEMPORAL POR REAGRUPACIÓN FAMILIAR"
            ),
        )

        self.assertEqual(
            item["categoria"],
            "RESIDENCIA_TEMPORAL",
        )

        self.assertEqual(
            item["modalidad"],
            "REAGRUPACION_FAMILIAR",
        )

    def test_catalog_is_idempotent(
        self,
    ):
        (
            client_administrative_status_service
            .ensure_client_administrative_schema()
        )

        (
            client_administrative_status_service
            .ensure_client_administrative_schema()
        )

        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_tipos_autorizacion
                """
            ).fetchone()[0]

            distinct_codes = conn.execute(
                """
                SELECT COUNT(
                    DISTINCT codigo
                )
                FROM config_tipos_autorizacion
                """
            ).fetchone()[0]

        self.assertEqual(
            total,
            distinct_codes,
        )

    def test_catalog_contains_core_trajectories(
        self,
    ):
        (
            client_administrative_status_service
            .ensure_client_administrative_schema()
        )

        codes = {
            item["codigo"]
            for item in (
                client_administrative_status_service
                .list_authorization_types()
            )
        }

        expected = {
            (
                "ESTANCIA_ESTUDIOS_"
                "SUPERIORES"
            ),
            (
                "RESIDENCIA_TEMPORAL_"
                "REAGRUPACION_FAMILIAR"
            ),
            (
                "RESIDENCIA_TEMPORAL_"
                "TRABAJO_CUENTA_AJENA"
            ),
            (
                "RESIDENCIA_TEMPORAL_"
                "ARRAIGO_SOCIAL"
            ),
            "RESIDENCIA_LARGA_DURACION",
            (
                "TARJETA_RESIDENCIA_FAMILIAR_"
                "CIUDADANO_UE"
            ),
            "PROTECCION_TEMPORAL",
            (
                "RESIDENCIA_TELETRABAJADOR_"
                "INTERNACIONAL"
            ),
        }

        self.assertTrue(
            expected.issubset(codes)
        )


if __name__ == "__main__":
    unittest.main()
