import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.services import (
    document_classification_catalog_service
    as catalog_service,
)


class DocumentClassificationCatalogTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = (
            Path(self.temp_dir.name)
            / "classification_catalog.db"
        )

        with closing(
            sqlite3.connect(
                str(self.db_path)
            )
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
                    subtipo_expediente_id INTEGER
                );

                CREATE TABLE config_documentos_catalogo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT NOT NULL UNIQUE,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    categoria TEXT,
                    activo INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
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
                    (8, 14, 'INICIAL', 'INICIAL'),
                    (10, 14, 'RENOVACION', 'RENOVACION');

                INSERT INTO expedientes
                    (
                        id,
                        tipo_expediente_id,
                        subtipo_expediente_id
                    )
                VALUES
                    (100, 14, 8);

                INSERT INTO config_documentos_catalogo (
                    id,
                    codigo,
                    nombre,
                    descripcion,
                    categoria,
                    activo
                )
                VALUES
                    (
                        1,
                        'PASAPORTE',
                        'PASAPORTE',
                        'Pasaporte',
                        'IDENTIDAD',
                        1
                    ),
                    (
                        2,
                        'INFORME_DE_VIVIENDA',
                        'INFORME DE VIVIENDA',
                        'Informe de vivienda',
                        'VIVIENDA',
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
                    activo
                )
                VALUES
                    (
                        1,
                        1,
                        14,
                        8,
                        'REAGRUPANTE',
                        'PASAPORTE REAGRUPANTE',
                        'pdf',
                        10,
                        1
                    ),
                    (
                        2,
                        1,
                        14,
                        8,
                        'REAGRUPADO',
                        'PASAPORTE REAGRUPADO',
                        'pdf',
                        10,
                        1
                    ),
                    (
                        3,
                        2,
                        14,
                        8,
                        NULL,
                        'INFORME DE VIVIENDA',
                        'pdf',
                        10,
                        1
                    ),
                    (
                        4,
                        2,
                        14,
                        8,
                        NULL,
                        'INFORME ADECUACION VIVIENDA',
                        'pdf',
                        20,
                        1
                    ),
                    (
                        5,
                        2,
                        14,
                        10,
                        NULL,
                        'INFORME RENOVACION',
                        'pdf',
                        10,
                        1
                    );
                """
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_deduplicates_patterns_and_preserves_roles(
        self,
    ):
        result = (
            catalog_service
            .list_options_for_expedient(
                100,
                db_path=self.db_path,
            )
        )

        labels = [
            item["label"]
            for item in result["specific"]
        ]

        self.assertIn(
            "PASAPORTE · REAGRUPANTE",
            labels,
        )

        self.assertIn(
            "PASAPORTE · REAGRUPADO",
            labels,
        )

        self.assertEqual(
            labels.count(
                "INFORME DE VIVIENDA"
            ),
            1,
        )

    def test_does_not_include_other_subtype(
        self,
    ):
        result = (
            catalog_service
            .list_options_for_expedient(
                100,
                db_path=self.db_path,
            )
        )

        labels = [
            item["label"]
            for item in result["specific"]
        ]

        self.assertNotIn(
            "INFORME RENOVACION",
            labels,
        )

    def test_adds_procedural_documents(
        self,
    ):
        result = (
            catalog_service
            .list_options_for_expedient(
                100,
                db_path=self.db_path,
            )
        )

        codes = {
            item["codigo"]
            for item in result["procedural"]
        }

        expected = {
            "ADMISION_TRAMITE",
            "ADMISION_TRAMITE_TASA",
            "TRAMITE_AUDIENCIA",
            "RESOLUCION_CONCESION",
            "RESOLUCION_DENEGACION",
            "INADMISION",
            "ARCHIVO",
        }

        self.assertEqual(
            expected,
            codes,
        )

    def test_returns_scope_context(
        self,
    ):
        result = (
            catalog_service
            .list_options_for_expedient(
                100,
                db_path=self.db_path,
            )
        )

        expediente = result["expediente"]

        self.assertEqual(
            expediente["tipo_codigo"],
            "REAGRUPACION_FAMILIAR",
        )

        self.assertEqual(
            expediente["subtipo_codigo"],
            "INICIAL",
        )


if __name__ == "__main__":
    unittest.main()
