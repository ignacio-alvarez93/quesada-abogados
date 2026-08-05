import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    expedient_document_state_service
    as document_state_service,
)


class PresentationTargetDiagnosisTests(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "presentation_target.db"
        )

        with closing(
            sqlite3.connect(self.db_path)
        ) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL
                );

                CREATE TABLE config_subtipos_expediente (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER NOT NULL,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER,
                    subtipo_expediente_id INTEGER,
                    box_folder_path TEXT,
                    activo INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT
                );

                CREATE TABLE box_watch_folders (
                    id INTEGER PRIMARY KEY,
                    ruta TEXT NOT NULL,
                    nombre_carpeta TEXT,
                    tipo_detectado TEXT,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE box_watch_items (
                    id INTEGER PRIMARY KEY,
                    ruta TEXT NOT NULL,
                    nombre_archivo TEXT,
                    extension TEXT,
                    tipo_detectado TEXT,
                    estado TEXT,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE config_documentos_requeridos (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER NOT NULL,
                    subtipo_expediente_id INTEGER,
                    codigo_documento TEXT NOT NULL,
                    nombre_documento TEXT NOT NULL,
                    obligatorio INTEGER NOT NULL DEFAULT 1,
                    orden INTEGER NOT NULL DEFAULT 0,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE expedient_document_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expediente_id INTEGER NOT NULL,
                    purpose TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                );

                INSERT INTO config_tipos_expediente (
                    id,
                    codigo,
                    nombre
                )
                VALUES (
                    14,
                    'REAGRUPACION_FAMILIAR',
                    'REAGRUPACION FAMILIAR'
                );

                INSERT INTO config_subtipos_expediente (
                    id,
                    tipo_expediente_id,
                    codigo,
                    nombre
                )
                VALUES (
                    8,
                    14,
                    'INICIAL',
                    'INICIAL'
                );

                INSERT INTO expedientes (
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    box_folder_path,
                    activo,
                    updated_at
                )
                VALUES (
                    100,
                    14,
                    8,
                    'CLIENTES/EXPEDIENTE_100',
                    1,
                    CURRENT_TIMESTAMP
                );

                INSERT INTO config_documentos_requeridos (
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    codigo_documento,
                    nombre_documento,
                    obligatorio,
                    orden,
                    activo
                )
                VALUES (
                    1,
                    14,
                    8,
                    'PASAPORTE',
                    'PASAPORTE',
                    1,
                    10,
                    1
                );

                INSERT INTO box_watch_folders (
                    id,
                    ruta,
                    nombre_carpeta,
                    tipo_detectado,
                    activo
                )
                VALUES
                    (
                        1,
                        'CLIENTES/EXPEDIENTE_100/PRESENTACION',
                        'PRESENTACION',
                        'OTROS',
                        1
                    ),
                    (
                        2,
                        'CLIENTES/EXPEDIENTE_100/ARCHIVO',
                        'ARCHIVO',
                        'OTROS',
                        1
                    );

                INSERT INTO box_watch_items (
                    id,
                    ruta,
                    nombre_archivo,
                    extension,
                    tipo_detectado,
                    estado,
                    activo
                )
                VALUES
                    (
                        1,
                        'CLIENTES/EXPEDIENTE_100/PRESENTACION/NIE.pdf',
                        'NIE.pdf',
                        'pdf',
                        'NIE',
                        'OK',
                        1
                    ),
                    (
                        2,
                        'CLIENTES/EXPEDIENTE_100/ARCHIVO/PASAPORTE.pdf',
                        'PASAPORTE.pdf',
                        'pdf',
                        'PASAPORTE',
                        'OK',
                        1
                    ),
                    (
                        3,
                        'CLIENTES/EXPEDIENTE_100/ARCHIVO/RESOLUCION_CONCESION.pdf',
                        'RESOLUCION_CONCESION.pdf',
                        'pdf',
                        'RESOLUCION_FAVORABLE',
                        'OK',
                        1
                    );

                INSERT INTO expedient_document_targets (
                    expediente_id,
                    purpose,
                    relative_path,
                    active,
                    created_at,
                    updated_at
                )
                VALUES (
                    100,
                    'PRESENTACION',
                    'PRESENTACION',
                    1,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                );
                """
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_only_presentation_target_is_diagnosed(
        self,
    ):
        with patch.object(
            document_state_service,
            "DB_PATH",
            self.db_path,
        ):
            result = (
                document_state_service
                .diagnose_expediente_document_state(
                    100
                )
            )

        self.assertTrue(
            result["target_disponible"]
        )
        self.assertEqual(
            result["diagnostic_scope"],
            "PRESENTACION_TARGET",
        )
        self.assertEqual(
            result["target_relative_path"],
            "PRESENTACION",
        )
        self.assertEqual(
            result["resumen"]["total_archivos"],
            1,
        )

        detected_codes = set(
            result.get(
                "detectados",
                {},
            ).get(
                "codigos_documento",
                [],
            )
        )

        self.assertIn(
            "NIE",
            detected_codes,
        )
        self.assertNotIn(
            "PASAPORTE",
            detected_codes,
        )

        missing_codes = {
            item.get("codigo")
            or item.get("codigo_documento")
            for item in result.get(
                "faltantes",
                []
            )
        }

        self.assertIn(
            "PASAPORTE",
            missing_codes,
        )

        self.assertEqual(
            result["fuente_completitud"],
            "LEGACY",
        )

        # El diagnóstico semántico continúa disponible
        # en paralelo, pero no bloquea expedientes legacy.
        self.assertEqual(
            result[
                "semantic_readiness"
            ][
                "modo"
            ],
            "PARALELO_NO_VINCULANTE",
        )

        # La concesión está fuera del target documental,
        # pero debe detectarse como estado procesal global.
        self.assertEqual(
            result[
                "estado_procesal_detectado"
            ][
                "estado_procesal"
            ],
            "CONCEDIDO",
        )
        self.assertTrue(
            result[
                "estado_procesal_detectado"
            ][
                "detectado"
            ]
        )

    def test_without_target_returns_no_diagnosis(
        self,
    ):
        with closing(
            sqlite3.connect(self.db_path)
        ) as conn:
            conn.execute(
                """
                UPDATE expedient_document_targets
                SET active = 0
                """
            )
            conn.commit()

        with patch.object(
            document_state_service,
            "DB_PATH",
            self.db_path,
        ):
            result = (
                document_state_service
                .diagnose_expediente_document_state(
                    100
                )
            )

        self.assertFalse(
            result["target_disponible"]
        )
        self.assertEqual(
            result["diagnostic_scope"],
            "PRESENTACION_TARGET",
        )
        self.assertEqual(
            result["estado_sugerido_legacy"],
            "SIN_DIAGNOSTICO",
        )
        self.assertEqual(
            result["resumen"]["total_archivos"],
            0,
        )
        self.assertTrue(
            any(
                "target" in str(signal).casefold()
                for signal in result.get(
                    "senales",
                    []
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
