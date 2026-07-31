import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    document_requirement_readiness_service as readiness,
)
from backend.services import (
    expedient_document_state_service as doc_state,
)


class ExpedientDocumentStateSemanticBridgeTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "semantic_bridge.db"
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
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

                CREATE TABLE config_nomenclaturas_documentales (
                    id INTEGER PRIMARY KEY,
                    documento_id INTEGER NOT NULL,
                    tipo_expediente_id INTEGER NOT NULL,
                    subtipo_expediente_id INTEGER,
                    patron_nombre TEXT NOT NULL,
                    extension_permitida TEXT,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE config_documentos_catalogo (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT NOT NULL UNIQUE,
                    nombre TEXT NOT NULL,
                    categoria TEXT,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE config_grupos_requisitos_documentales (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER NOT NULL,
                    subtipo_expediente_id INTEGER,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    regla_cumplimiento TEXT NOT NULL,
                    minimo_documentos INTEGER NOT NULL DEFAULT 0,
                    orden INTEGER NOT NULL DEFAULT 0,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE config_grupo_requisito_documentos (
                    id INTEGER PRIMARY KEY,
                    grupo_id INTEGER NOT NULL,
                    documento_catalogo_id INTEGER NOT NULL,
                    rol_documental TEXT,
                    etiqueta_requisito TEXT,
                    descripcion_requisito TEXT,
                    orden INTEGER NOT NULL DEFAULT 0,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                INSERT INTO config_tipos_expediente
                    (id, codigo, nombre)
                VALUES
                    (
                        14,
                        'REAGRUPACION_FAMILIAR',
                        'REAGRUPACION FAMILIAR'
                    );

                INSERT INTO config_subtipos_expediente
                    (
                        id,
                        tipo_expediente_id,
                        codigo,
                        nombre
                    )
                VALUES
                    (8, 14, 'INICIAL', 'INICIAL');

                INSERT INTO expedientes (
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    box_folder_path,
                    activo,
                    updated_at
                )
                VALUES
                    (
                        100,
                        14,
                        8,
                        'CLIENTES/EXPEDIENTE_100',
                        1,
                        CURRENT_TIMESTAMP
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
                        'CLIENTES/EXPEDIENTE_100',
                        'EXPEDIENTE_100',
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
                        'CLIENTES/EXPEDIENTE_100/PASAPORTE.pdf',
                        'PASAPORTE.pdf',
                        'pdf',
                        'PASAPORTE',
                        'OK',
                        1
                    ),
                    (
                        2,
                        'CLIENTES/EXPEDIENTE_100/NIE_CLIENTE.pdf',
                        'NIE_CLIENTE.pdf',
                        'pdf',
                        'SIN CLASIFICAR',
                        'OK',
                        1
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
                VALUES
                    (
                        10,
                        14,
                        8,
                        'PASAPORTE',
                        'PASAPORTE',
                        1,
                        10,
                        1
                    ),
                    (
                        20,
                        14,
                        8,
                        'NIE',
                        'NIE',
                        1,
                        20,
                        1
                    );

                INSERT INTO config_nomenclaturas_documentales (
                    id,
                    documento_id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    patron_nombre,
                    extension_permitida,
                    activo
                )
                VALUES
                    (
                        1,
                        20,
                        14,
                        8,
                        'NIE',
                        'pdf',
                        1
                    );

                INSERT INTO config_documentos_catalogo (
                    id,
                    codigo,
                    nombre,
                    categoria,
                    activo
                )
                VALUES
                    (
                        1,
                        'PASAPORTE',
                        'PASAPORTE',
                        'IDENTIDAD',
                        1
                    ),
                    (
                        2,
                        'NIE',
                        'NIE',
                        'IDENTIDAD',
                        1
                    );

                INSERT INTO config_grupos_requisitos_documentales (
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    codigo,
                    nombre,
                    regla_cumplimiento,
                    minimo_documentos,
                    orden,
                    activo
                )
                VALUES
                    (
                        30,
                        14,
                        8,
                        'IDENTIDAD_PARTES',
                        'IDENTIDAD DE LAS PARTES',
                        'ALL',
                        1,
                        10,
                        1
                    );

                INSERT INTO config_grupo_requisito_documentos (
                    id,
                    grupo_id,
                    documento_catalogo_id,
                    rol_documental,
                    etiqueta_requisito,
                    orden,
                    activo
                )
                VALUES
                    (
                        31,
                        30,
                        1,
                        'REAGRUPANTE',
                        'Pasaporte del reagrupante',
                        10,
                        1
                    ),
                    (
                        32,
                        30,
                        2,
                        NULL,
                        'NIE',
                        20,
                        1
                    );
                """
            )
            conn.commit()

        self.doc_state_patch = patch.object(
            doc_state,
            "DB_PATH",
            self.db_path,
        )
        self.readiness_patch = patch.object(
            readiness,
            "DB_PATH",
            self.db_path,
        )

        self.doc_state_patch.start()
        self.readiness_patch.start()

    def tearDown(self):
        self.readiness_patch.stop()
        self.doc_state_patch.stop()
        self.temp_dir.cleanup()

    def test_bridge_preserves_detection_origins(self):
        detections = doc_state._build_semantic_detections(
            [
                {
                    "codigo": "PASAPORTE",
                    "archivo": "PASAPORTE.pdf",
                    "ruta": "A/PASAPORTE.pdf",
                    "estado": "OK",
                },
                {
                    "codigo": "NIE",
                    "archivo": "NIE.pdf",
                    "ruta": "A/NIE.pdf",
                    "patron": "NIE",
                    "origen": "nomenclatura_configurada",
                },
            ]
        )

        self.assertEqual(len(detections), 2)
        self.assertEqual(
            detections[0]["origen"],
            "box_classifier",
        )
        self.assertEqual(
            detections[1]["origen"],
            "nomenclatura_configurada",
        )

    def test_semantic_result_is_parallel_and_non_binding(self):
        result = (
            doc_state
            .diagnose_expediente_document_state(100)
        )

        self.assertEqual(
            result["estado_sugerido"],
            doc_state.ESTADO_COMPLETO_SIN_PRESENTAR,
        )
        self.assertEqual(result["faltantes"], [])

        semantic = result["semantic_readiness"]

        self.assertTrue(semantic["disponible"])
        self.assertEqual(
            semantic["modo"],
            "PARALELO_NO_VINCULANTE",
        )
        self.assertFalse(semantic["completo"])
        self.assertEqual(
            semantic["grupos_bloqueantes"],
            1,
        )
        self.assertEqual(
            len(
                semantic[
                    "opciones_ambiguas_por_rol"
                ]
            ),
            1,
        )

        origins = {
            detection["origen"]
            for detection in semantic["detecciones"]
        }

        self.assertEqual(
            origins,
            {
                "box_classifier",
                "nomenclatura_configurada",
            },
        )

    def test_semantic_failure_does_not_break_legacy(self):
        with patch.object(
            readiness,
            "evaluate_semantic_requirement_readiness",
            side_effect=RuntimeError(
                "fallo semántico controlado"
            ),
        ):
            result = (
                doc_state
                .diagnose_expediente_document_state(100)
            )

        self.assertEqual(
            result["estado_sugerido"],
            doc_state.ESTADO_COMPLETO_SIN_PRESENTAR,
        )
        self.assertFalse(
            result["semantic_readiness"]["disponible"]
        )
        self.assertIn(
            "fallo semántico controlado",
            result["semantic_readiness"]["error"],
        )


    def test_repeated_diagnosis_releases_connections(self):
        first = (
            doc_state
            .diagnose_expediente_document_state(100)
        )
        second = (
            doc_state
            .diagnose_expediente_document_state(100)
        )

        self.assertEqual(
            first["estado_sugerido"],
            second["estado_sugerido"],
        )
        self.assertEqual(
            first["semantic_readiness"]["completo"],
            second["semantic_readiness"]["completo"],
        )


if __name__ == "__main__":
    unittest.main()
