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


class CanonicalNomenclatureDetectionTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "canonical_nomenclature_detection.db"
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
                    tipo_expediente_id INTEGER NOT NULL,
                    documento_id INTEGER NOT NULL,
                    patron_nombre TEXT NOT NULL,
                    extension_permitida TEXT,
                    activo INTEGER NOT NULL DEFAULT 1,
                    subtipo_expediente_id INTEGER
                );

                CREATE TABLE config_documentos_catalogo (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT NOT NULL UNIQUE,
                    nombre TEXT NOT NULL,
                    categoria TEXT,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE config_nomenclaturas_catalogo (
                    id INTEGER PRIMARY KEY,
                    documento_catalogo_id INTEGER NOT NULL,
                    tipo_expediente_id INTEGER NOT NULL,
                    subtipo_expediente_id INTEGER,
                    rol_documental TEXT,
                    patron_nombre TEXT NOT NULL,
                    extension_permitida TEXT NOT NULL,
                    prioridad INTEGER NOT NULL DEFAULT 100,
                    activo INTEGER NOT NULL DEFAULT 1,
                    origen_legacy_id INTEGER
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
                        'CLIENTES/EXPEDIENTE_100/PASAPORTE_REAGRUPANTE.pdf',
                        'PASAPORTE_REAGRUPANTE.pdf',
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
                        'PASAPORTE_REAGRUPANTE',
                        'PASAPORTE REAGRUPANTE',
                        1,
                        10,
                        1
                    );

                INSERT INTO config_nomenclaturas_documentales (
                    id,
                    tipo_expediente_id,
                    documento_id,
                    patron_nombre,
                    extension_permitida,
                    activo,
                    subtipo_expediente_id
                )
                VALUES
                    (
                        50,
                        14,
                        10,
                        'PASAPORTE_REAGRUPANTE',
                        'pdf',
                        1,
                        8
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
                    );

                INSERT INTO config_nomenclaturas_catalogo (
                    id,
                    documento_catalogo_id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    rol_documental,
                    patron_nombre,
                    extension_permitida,
                    prioridad,
                    activo,
                    origen_legacy_id
                )
                VALUES
                    (
                        60,
                        1,
                        14,
                        8,
                        'REAGRUPANTE',
                        'PASAPORTE_REAGRUPANTE',
                        'pdf',
                        10,
                        1,
                        50
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
                        70,
                        14,
                        8,
                        'IDENTIDAD_REAGRUPANTE',
                        'IDENTIDAD DEL REAGRUPANTE',
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
                        80,
                        70,
                        1,
                        'REAGRUPANTE',
                        'Pasaporte del reagrupante',
                        10,
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

    def test_canonical_nomenclature_has_priority(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            expediente = {
                "tipo_expediente_id": 14,
                "subtipo_expediente_id": 8,
            }

            rules = doc_state._get_nomenclatures(
                conn,
                expediente,
            )

        self.assertEqual(len(rules), 1)
        self.assertEqual(
            rules[0]["fuente_nomenclatura"],
            "CANONICAL",
        )
        self.assertEqual(
            rules[0]["codigo_documento"],
            "PASAPORTE",
        )
        self.assertEqual(
            rules[0]["rol_documental"],
            "REAGRUPANTE",
        )

    def test_migrated_legacy_rule_is_not_duplicated(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            rules = doc_state._get_nomenclatures(
                conn,
                {
                    "tipo_expediente_id": 14,
                    "subtipo_expediente_id": 8,
                },
            )

        sources = [
            rule["fuente_nomenclatura"]
            for rule in rules
        ]

        self.assertEqual(sources, ["CANONICAL"])

    def test_canonical_detection_preserves_role(self):
        result = (
            doc_state
            .diagnose_expediente_document_state(100)
        )

        semantic = result["semantic_readiness"]

        self.assertTrue(semantic["disponible"])
        self.assertTrue(semantic["completo"])
        self.assertEqual(
            semantic["grupos_bloqueantes"],
            0,
        )

        detections = semantic["detecciones"]

        self.assertEqual(len(detections), 1)
        self.assertEqual(
            detections[0]["codigo"],
            "PASAPORTE",
        )
        self.assertEqual(
            detections[0]["rol_documental"],
            "REAGRUPANTE",
        )
        self.assertEqual(
            detections[0]["origen"],
            "nomenclatura_canónica",
        )

    def test_legacy_is_used_when_canonical_table_is_absent(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                DROP TABLE config_nomenclaturas_catalogo
                """
            )
            conn.commit()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            rules = doc_state._get_nomenclatures(
                conn,
                {
                    "tipo_expediente_id": 14,
                    "subtipo_expediente_id": 8,
                },
            )

        self.assertEqual(len(rules), 1)
        self.assertEqual(
            rules[0]["fuente_nomenclatura"],
            "LEGACY",
        )
        self.assertEqual(
            rules[0]["codigo_documento"],
            "PASAPORTE_REAGRUPANTE",
        )


    def test_inferred_role_can_complete_semantic_group(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE config_nomenclaturas_catalogo
                SET
                    rol_documental = NULL,
                    patron_nombre = 'PASAPORTE'
                WHERE id = 60
                """
            )
            conn.commit()

        result = (
            doc_state
            .diagnose_expediente_document_state(100)
        )

        semantic = result["semantic_readiness"]
        summary = result[
            "resumen_inferencia_roles"
        ]

        self.assertTrue(semantic["disponible"])
        self.assertTrue(semantic["completo"])
        self.assertEqual(
            semantic["grupos_bloqueantes"],
            0,
        )

        self.assertEqual(
            summary["roles_inferidos"],
            1,
        )
        self.assertEqual(
            summary["roles_explicitos"],
            0,
        )
        self.assertEqual(
            summary["por_rol"],
            {
                "REAGRUPANTE": 1,
            },
        )

        detection = semantic["detecciones"][0]

        self.assertEqual(
            detection["rol_documental"],
            "REAGRUPANTE",
        )
        self.assertEqual(
            detection[
                "estado_inferencia_rol"
            ],
            "INFERIDO",
        )


if __name__ == "__main__":
    unittest.main()
