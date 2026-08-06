import importlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


class ReagrupacionAuthorizationTransitionTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "test.db"
        )

        self._create_base_schema()

        self.db_patch = patch(
            "backend.services."
            "client_authorization_transition_service."
            "DB_PATH",
            self.db_path,
        )

        self.admin_db_patch = patch(
            "backend.services."
            "client_administrative_status_service."
            "DB_PATH",
            self.db_path,
        )

        self.db_patch.start()
        self.admin_db_patch.start()

        from backend.services import (
            client_authorization_transition_service,
        )

        from backend.services import (
            client_administrative_status_service,
        )

        self.transition_service = (
            importlib.reload(
                client_authorization_transition_service
            )
        )

        self.admin_service = (
            importlib.reload(
                client_administrative_status_service
            )
        )

        self.transition_service.DB_PATH = (
            self.db_path
        )

        self.admin_service.DB_PATH = (
            self.db_path
        )

        self.transition_service.MIGRATION_PATH = (
            Path(
                "database/migrations/"
                "20260806_seed_reagrupacion_"
                "authorization_transitions.sql"
            )
        )

        self._apply_admin_schema()

    def tearDown(self):
        self.db_patch.stop()
        self.admin_db_patch.stop()
        self.temp_dir.cleanup()

    def _create_base_schema(self):
        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    activo INTEGER DEFAULT 1,
                    situacion_administrativa_id INTEGER,
                    autorizacion_actual_id INTEGER,
                    fecha_caducidad_residencia TEXT,
                    fecha_caducidad_origen TEXT,
                    fecha_caducidad_expediente_id INTEGER,
                    fecha_caducidad_actualizada_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE config_familias_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT UNIQUE,
                    nombre TEXT,
                    activo INTEGER DEFAULT 1
                );

                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    familia_id INTEGER,
                    codigo TEXT UNIQUE,
                    nombre TEXT,
                    activo INTEGER DEFAULT 1
                );

                CREATE TABLE config_subtipos_expediente (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER,
                    codigo TEXT,
                    nombre TEXT,
                    activo INTEGER DEFAULT 1
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER NOT NULL,
                    numero_expediente TEXT,
                    tipo_expediente_id INTEGER,
                    subtipo_expediente_id INTEGER,
                    fecha_presentacion TEXT,
                    fecha_resolucion TEXT,
                    provincia TEXT,
                    activo INTEGER DEFAULT 1
                );

                INSERT INTO clientes (
                    id,
                    nombre
                )
                VALUES (
                    1,
                    'CLIENTE PRUEBA'
                );

                INSERT INTO config_familias_expediente (
                    id,
                    codigo,
                    nombre
                )
                VALUES (
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERÍA'
                );

                INSERT INTO config_tipos_expediente (
                    id,
                    familia_id,
                    codigo,
                    nombre
                )
                VALUES (
                    14,
                    1,
                    'REAGRUPACION_FAMILIAR',
                    'REAGRUPACIÓN FAMILIAR'
                );

                INSERT INTO config_subtipos_expediente (
                    id,
                    tipo_expediente_id,
                    codigo,
                    nombre
                )
                VALUES
                    (
                        8,
                        14,
                        'INICIAL',
                        'INICIAL'
                    ),
                    (
                        10,
                        14,
                        'RENOVACION',
                        'RENOVACIÓN'
                    );

                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    numero_expediente,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    fecha_presentacion,
                    fecha_resolucion,
                    provincia
                )
                VALUES
                    (
                        100,
                        1,
                        'EX-100',
                        14,
                        8,
                        '2026-01-10',
                        '2026-02-10',
                        'ASTURIAS'
                    ),
                    (
                        101,
                        1,
                        'EX-101',
                        14,
                        10,
                        '2027-01-10',
                        '2027-02-10',
                        'ASTURIAS'
                    );
                """
            )

            conn.commit()

    def _apply_admin_schema(self):
        administrative_migration = Path(
            "database/migrations/"
            "20260805_create_client_"
            "administrative_trajectory.sql"
        )

        evolution_migration = Path(
            "database/migrations/"
            "20260805_create_expedient_"
            "evolution_schema.sql"
        )

        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.executescript(
                administrative_migration.read_text(
                    encoding="utf-8"
                )
            )

            conn.executescript(
                evolution_migration.read_text(
                    encoding="utf-8"
                )
            )

            conn.execute(
                """
                INSERT OR IGNORE INTO
                config_tipos_autorizacion (
                    id,
                    codigo,
                    nombre,
                    familia_codigo,
                    categoria,
                    modalidad,
                    admite_inicial,
                    admite_renovacion,
                    activo
                )
                VALUES (
                    8,
                    'RESIDENCIA_TEMPORAL_REAGRUPACION_FAMILIAR',
                    'AUTORIZACIÓN DE RESIDENCIA TEMPORAL POR REAGRUPACIÓN FAMILIAR',
                    'EXTRANJERIA',
                    'RESIDENCIA_TEMPORAL',
                    'REAGRUPACION_FAMILIAR',
                    1,
                    1,
                    1
                )
                """
            )

            conn.commit()

    def test_seeds_two_transitions(self):
        (
            self.transition_service
            .ensure_authorization_transition_seed()
        )

        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_transiciones_autorizacion
                """
            ).fetchone()[0]

        self.assertEqual(total, 2)

    def test_resolves_initial_transition(self):
        transition = (
            self.transition_service
            .resolve_transition_for_expedient(
                expediente_id=100,
                event_code=(
                    "RESOLUCION_FAVORABLE"
                ),
                result_code="CONCEDIDO",
            )
        )

        self.assertIsNotNone(transition)

        self.assertEqual(
            transition["tipo_transicion"],
            "INICIAL",
        )

        self.assertEqual(
            transition["autorizacion_codigo"],
            "RESIDENCIA_TEMPORAL_"
            "REAGRUPACION_FAMILIAR",
        )

    def test_rejects_non_favorable_event(self):
        transition = (
            self.transition_service
            .resolve_transition_for_expedient(
                expediente_id=100,
                event_code="REQUERIMIENTO",
                result_code="PENDIENTE",
            )
        )

        self.assertIsNone(transition)

    def test_creates_initial_authorization(self):
        result = (
            self.transition_service
            .apply_favorable_resolution_to_client(
                expediente_id=100,
                documento_id=500,
                resolution_data={
                    "fecha_concesion":
                        "2026-02-10",
                    "fecha_vigencia_desde":
                        "2026-03-01",
                    "fecha_vigencia_hasta":
                        "2027-03-01",
                    "numero_expediente_"
                    "administrativo":
                        "EXTRANJERIA-100",
                    "organismo_concedente":
                        "OFICINA DE EXTRANJERÍA",
                },
                usuario="TEST",
            )
        )

        self.assertTrue(result["applied"])

        current = (
            self.admin_service
            .get_current_authorization(1)
        )

        self.assertEqual(
            current["autorizacion_codigo"],
            "RESIDENCIA_TEMPORAL_"
            "REAGRUPACION_FAMILIAR",
        )

        self.assertEqual(
            current["expediente_origen_id"],
            100,
        )

        self.assertEqual(
            current["documento_origen_id"],
            500,
        )

        self.assertEqual(
            current["fecha_vigencia_hasta"],
            "2027-03-01",
        )

    def test_renewal_creates_new_history_row(self):
        (
            self.transition_service
            .apply_favorable_resolution_to_client(
                expediente_id=100,
                documento_id=500,
                resolution_data={
                    "fecha_vigencia_desde":
                        "2026-03-01",
                    "fecha_vigencia_hasta":
                        "2027-03-01",
                },
                usuario="TEST",
            )
        )

        (
            self.transition_service
            .apply_favorable_resolution_to_client(
                expediente_id=101,
                documento_id=501,
                resolution_data={
                    "fecha_vigencia_desde":
                        "2027-03-02",
                    "fecha_vigencia_hasta":
                        "2031-03-02",
                },
                usuario="TEST",
            )
        )

        rows = (
            self.admin_service
            .list_client_authorizations(
                1,
            )
        )

        self.assertEqual(len(rows), 2)

        current = [
            row
            for row in rows
            if row["es_actual"] == 1
        ]

        previous = [
            row
            for row in rows
            if row["es_actual"] == 0
        ]

        self.assertEqual(len(current), 1)
        self.assertEqual(len(previous), 1)

        self.assertEqual(
            current[0]["documento_origen_id"],
            501,
        )

        self.assertEqual(
            previous[0]["documento_origen_id"],
            500,
        )

    def test_same_resolution_is_idempotent(self):
        first = (
            self.transition_service
            .apply_favorable_resolution_to_client(
                expediente_id=100,
                documento_id=500,
                resolution_data={
                    "fecha_concesion":
                        "2026-02-10",
                    "fecha_vigencia_desde":
                        "2026-03-01",
                    "fecha_vigencia_hasta":
                        "2027-03-01",
                },
                usuario="TEST",
            )
        )

        second = (
            self.transition_service
            .apply_favorable_resolution_to_client(
                expediente_id=100,
                documento_id=500,
                resolution_data={
                    "fecha_concesion":
                        "2026-02-10",
                    "fecha_vigencia_desde":
                        "2026-03-01",
                    "fecha_vigencia_hasta":
                        "2027-03-01",
                },
                usuario="TEST",
            )
        )

        self.assertTrue(first["applied"])

        self.assertFalse(
            second["applied"]
        )

        self.assertTrue(
            second["already_applied"]
        )

        self.assertEqual(
            second["reason"],
            "RESOLUCION_YA_APLICADA",
        )

        rows = (
            self.admin_service
            .list_client_authorizations(
                1,
            )
        )

        self.assertEqual(
            len(rows),
            1,
        )

        self.assertEqual(
            rows[0]["documento_origen_id"],
            500,
        )


    def test_no_transition_returns_not_applied(self):
        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.execute(
                """
                UPDATE expedientes
                SET tipo_expediente_id = 999
                WHERE id = 100
                """
            )
            conn.commit()

        result = (
            self.transition_service
            .apply_favorable_resolution_to_client(
                expediente_id=100,
                documento_id=500,
            )
        )

        self.assertFalse(result["applied"])

        self.assertEqual(
            result["reason"],
            "SIN_TRANSICION_CONFIGURADA",
        )


if __name__ == "__main__":
    unittest.main()
