import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    notification_tracking_service,
)


class NotificationTrackingDateFiltersTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "tracking_dates.db"
        )

        self.db_patch = patch.object(
            notification_tracking_service,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

        self.conn = sqlite3.connect(
            self.db_path
        )
        self.conn.row_factory = sqlite3.Row

        self._create_schema()
        self._insert_data()

    def tearDown(self):
        self.conn.close()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _create_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT,
                nie TEXT
            );

            CREATE TABLE config_tipos_expediente (
                id INTEGER PRIMARY KEY,
                nombre TEXT
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY,
                cliente_id INTEGER,
                tipo_expediente_id INTEGER
            );

            CREATE TABLE notification_tracking (
                id INTEGER PRIMARY KEY,
                expediente_id INTEGER,
                cliente_id INTEGER,
                familia_codigo TEXT,
                notification_workflow_code TEXT,
                estado TEXT,
                activo INTEGER,
                numero_expediente_interno TEXT,
                numero_presentacion_registro TEXT,
                numero_expediente_extranjeria TEXT,
                numero_registro_regage TEXT,
                registro_csv_geiser TEXT,
                justificante_presentacion_id INTEGER,
                justificante_admision_id INTEGER,
                justificante_resolucion_id INTEGER,
                tipo_admision TEXT,
                resultado_resolucion TEXT,
                fecha_inicio_espera_numero TEXT,
                fecha_inicio_espera_admision TEXT,
                fecha_inicio_espera_resolucion TEXT,
                closed_at TEXT,
                origen_ultima_sincronizacion TEXT,
                usuario_ultima_sincronizacion TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )

    def _insert_data(self):
        self.conn.execute(
            """
            INSERT INTO clientes
            VALUES (
                1,
                'ANA',
                'QUESADA',
                'SOLER',
                'X0000001A'
            )
            """
        )

        self.conn.execute(
            """
            INSERT INTO config_tipos_expediente
            VALUES (
                1,
                'Residencia'
            )
            """
        )

        for expediente_id in (1, 2, 3):
            self.conn.execute(
                """
                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    tipo_expediente_id
                )
                VALUES (?, 1, 1)
                """,
                (expediente_id,),
            )

        rows = [
            (
                1,
                "ESPERA_NUMERO_EXPEDIENTE",
                "2026-07-01 09:00:00",
                None,
                None,
            ),
            (
                2,
                "ESPERA_ADMISION_TRAMITE",
                "2026-06-01 09:00:00",
                "2026-07-15 09:00:00",
                None,
            ),
            (
                3,
                "ESPERA_RESOLUCION",
                "2026-05-01 09:00:00",
                "2026-06-01 09:00:00",
                "2026-07-30 09:00:00",
            ),
        ]

        for (
            item_id,
            estado,
            fecha_numero,
            fecha_admision,
            fecha_resolucion,
        ) in rows:
            self.conn.execute(
                """
                INSERT INTO notification_tracking (
                    id,
                    expediente_id,
                    cliente_id,
                    familia_codigo,
                    notification_workflow_code,
                    estado,
                    activo,
                    numero_expediente_interno,
                    fecha_inicio_espera_numero,
                    fecha_inicio_espera_admision,
                    fecha_inicio_espera_resolucion,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERIA_STANDARD',
                    ?,
                    1,
                    ?,
                    ?,
                    ?,
                    ?,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    item_id,
                    item_id,
                    estado,
                    f"EXP-{item_id}",
                    fecha_numero,
                    fecha_admision,
                    fecha_resolucion,
                ),
            )

        self.conn.commit()

    def test_filters_current_state_start_date(
        self,
    ):
        result = (
            notification_tracking_service
            .list_active_tracking(
                started_from=(
                    "2026-07-10 00:00:00"
                ),
                started_to=(
                    "2026-07-20 23:59:59"
                ),
            )
        )

        self.assertEqual(
            len(result),
            1,
        )
        self.assertEqual(
            result[0]["expediente_id"],
            2,
        )
        self.assertEqual(
            result[0][
                "current_wait_started_at"
            ],
            "2026-07-15 09:00:00",
        )

    def test_filters_today(
        self,
    ):
        result = (
            notification_tracking_service
            .list_active_tracking(
                started_from=(
                    "2026-07-30 00:00:00"
                ),
                started_to=(
                    "2026-07-30 23:59:59"
                ),
            )
        )

        self.assertEqual(
            len(result),
            1,
        )
        self.assertEqual(
            result[0]["expediente_id"],
            3,
        )


if __name__ == "__main__":
    unittest.main()
