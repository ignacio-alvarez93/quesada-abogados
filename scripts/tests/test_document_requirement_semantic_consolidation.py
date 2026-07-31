import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    document_requirement_legacy_migration_service as legacy_migration,
)
from backend.services import (
    document_requirement_semantic_consolidation_service as consolidation,
)


class SemanticDocumentRequirementConsolidationTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "semantic_consolidation.db"
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT NOT NULL UNIQUE,
                    nombre TEXT NOT NULL,
                    activo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE config_subtipos_expediente (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER NOT NULL,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL,
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

                INSERT INTO config_tipos_expediente
                    (id, codigo, nombre, activo)
                VALUES
                    (3, 'NACIONALIDAD', 'NACIONALIDAD', 1),
                    (
                        10,
                        'REGULARIZACION_MASIVA_TRANS_21',
                        'REGULARIZACION',
                        1
                    ),
                    (
                        13,
                        'RESIDENCIA_TEMPORAL_NO_LUCRATIVA',
                        'NO LUCRATIVA',
                        1
                    ),
                    (
                        14,
                        'REAGRUPACION_FAMILIAR',
                        'REAGRUPACION',
                        1
                    );

                INSERT INTO config_subtipos_expediente (
                    id,
                    tipo_expediente_id,
                    codigo,
                    nombre,
                    activo
                )
                VALUES
                    (1, 3, 'CASO_GENERAL', 'CASO GENERAL', 1),
                    (2, 10, 'INDIVIDUALES', 'INDIVIDUALES', 1),
                    (
                        6,
                        13,
                        'RENOVACION_TITULAR',
                        'RENOVACION TITULAR',
                        1
                    ),
                    (8, 14, 'INICIAL', 'INICIAL', 1);
                """
            )

            legacy_rows = [
                (
                    1,
                    3,
                    1,
                    "AAPP",
                    "AAPP",
                    1,
                ),
                (
                    2,
                    3,
                    1,
                    "ACTA_DE_NACIMIENTO_DEL_PAIS_DE_ORIGEN",
                    "ACTA DE NACIMIENTO DEL PAIS DE ORIGEN",
                    1,
                ),
                (3, 3, 1, "PASAPORTE", "PASAPORTE", 1),
                (4, 3, 1, "NIE", "NIE", 1),
                (5, 3, 1, "CCSE", "CCSE", 1),
                (6, 3, 1, "DELE", "DELE", 0),
                (7, 3, 1, "TASA_790016", "TASA 790016", 1),
                (
                    8,
                    3,
                    1,
                    "EMPADRONAMIENTO",
                    "EMPADRONAMIENTO",
                    1,
                ),
                (
                    9,
                    3,
                    1,
                    "ACTA_DE_NACIMIENTO_DE_LOS_HIJOS_MENORES_DE_EDAD",
                    "ACTA DE NACIMIENTO DE HIJOS MENORES",
                    0,
                ),
                (
                    10,
                    3,
                    1,
                    "PODER_O_MANDATO_ACREDITATIVO_DE_REPRESENTACION",
                    "PODER",
                    1,
                ),
                (
                    11,
                    3,
                    1,
                    "DNI_DE_REPRESENTANTE",
                    "DNI DE REPRESENTANTE",
                    0,
                ),
                (12, 10, 2, "AAPP", "AAPP", 1),
                (
                    13,
                    10,
                    2,
                    "EMPADRONAMIENTO",
                    "EMPADRONAMIENTO",
                    1,
                ),
                (14, 10, 2, "PASAPORTE", "PASAPORTE", 1),
                (
                    15,
                    10,
                    2,
                    "PRUEBAS_DE_PERMANENCIA",
                    "PRUEBAS DE PERMANENCIA",
                    1,
                ),
                (16, 10, 2, "PODER", "PODER", 1),
                (17, 10, 2, "CONTRATO", "CONTRATO", 0),
                (
                    18,
                    10,
                    None,
                    "INFORME_DE_VULNERABILIDAD",
                    "INFORME DE VULNERABILIDAD",
                    0,
                ),
                (
                    19,
                    10,
                    2,
                    "ACTA_DE_NACIMIENTO",
                    "ACTA DE NACIMIENTO",
                    1,
                ),
                (20, 13, 6, "PASAPORTE", "PASAPORTE", 1),
                (21, 13, 6, "NIE", "NIE", 1),
                (
                    22,
                    13,
                    6,
                    "EMPADRONAMIENTO",
                    "EMPADRONAMIENTO",
                    1,
                ),
                (
                    23,
                    13,
                    6,
                    "SEGURO_DE_SALUD",
                    "SEGURO DE SALUD",
                    1,
                ),
                (
                    24,
                    13,
                    6,
                    "MEDIOS_ECONOMICOS",
                    "MEDIOS ECONOMICOS",
                    1,
                ),
                (
                    25,
                    14,
                    8,
                    "PASAPORTE_REAGRUPANTE",
                    "PASAPORTE REAGRUPANTE",
                    1,
                ),
                (
                    26,
                    14,
                    8,
                    "PASAPORTE_REAGRUPADO",
                    "PASAPORTE REAGRUPADO",
                    1,
                ),
                (
                    27,
                    14,
                    8,
                    "NIE_REAGRUPANTE",
                    "NIE REAGRUPANTE",
                    1,
                ),
                (
                    28,
                    14,
                    8,
                    "EMPADRONAMIENTO_CONJUNTO",
                    "EMPADRONAMIENTO CONJUNTO",
                    1,
                ),
                (
                    29,
                    14,
                    8,
                    "INFORME_DE_VIVIENDA",
                    "INFORME DE VIVIENDA",
                    0,
                ),
                (
                    30,
                    14,
                    8,
                    "CERTIFICADO_MATRIMONIO",
                    "CERTIFICADO MATRIMONIO",
                    1,
                ),
                (
                    31,
                    14,
                    8,
                    "MEDIOS_ECONOMICOS",
                    "MEDIOS ECONOMICOS",
                    1,
                ),
            ]

            conn.executemany(
                """
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
                VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                """,
                legacy_rows,
            )
            conn.commit()

        self.legacy_patch = patch.object(
            legacy_migration,
            "DB_PATH",
            self.db_path,
        )
        self.semantic_patch = patch.object(
            consolidation,
            "DB_PATH",
            self.db_path,
        )

        self.legacy_patch.start()
        self.semantic_patch.start()

        legacy_migration.migrate_legacy_document_requirements()

    def tearDown(self):
        self.semantic_patch.stop()
        self.legacy_patch.stop()
        self.temp_dir.cleanup()

    def test_preview_contains_27_semantic_groups(self):
        preview = consolidation.preview_semantic_consolidation()

        self.assertEqual(len(preview), 27)

    def test_identity_groups_are_consolidated(self):
        consolidation.consolidate_semantic_groups()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            nationality = conn.execute(
                """
                SELECT id
                FROM config_grupos_requisitos_documentales
                WHERE codigo = 'IDENTIDAD_TITULAR'
                  AND tipo_expediente_id = 3
                """
            ).fetchone()

            nationality_options = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_grupo_requisito_documentos
                WHERE grupo_id = ?
                """,
                (nationality["id"],),
            ).fetchone()[0]

            regrouping = conn.execute(
                """
                SELECT id
                FROM config_grupos_requisitos_documentales
                WHERE codigo = 'IDENTIDAD_PARTES'
                  AND tipo_expediente_id = 14
                """
            ).fetchone()

            regrouping_options = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_grupo_requisito_documentos
                WHERE grupo_id = ?
                """,
                (regrouping["id"],),
            ).fetchone()[0]

        self.assertEqual(nationality_options, 2)
        self.assertEqual(regrouping_options, 3)

    def test_optional_requirements_remain_separate(self):
        consolidation.consolidate_semantic_groups()

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT codigo, regla_cumplimiento
                FROM config_grupos_requisitos_documentales
                WHERE codigo IN (
                    'INTEGRACION_DELE',
                    'NACIMIENTO_HIJOS_MENORES',
                    'IDENTIDAD_REPRESENTANTE',
                    'RELACION_LABORAL',
                    'VIVIENDA'
                )
                """
            ).fetchall()

        self.assertEqual(len(rows), 5)
        self.assertTrue(
            all(row[1] == "OPTIONAL" for row in rows)
        )

    def test_legacy_groups_are_deactivated_and_traced(self):
        summary = consolidation.consolidate_semantic_groups()

        self.assertEqual(
            summary["legacy_groups_deactivated"],
            31,
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            active_legacy = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_grupos_requisitos_documentales
                WHERE codigo LIKE 'LEGACY_REQ_%'
                  AND activo = 1
                """
            ).fetchone()[0]

            provenance = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_grupos_requisitos_origen_legacy
                """
            ).fetchone()[0]

        self.assertEqual(active_legacy, 0)
        self.assertEqual(provenance, 31)

    def test_consolidation_is_idempotent(self):
        first = consolidation.consolidate_semantic_groups()
        second = consolidation.consolidate_semantic_groups()

        self.assertEqual(first["semantic_groups_created"], 27)
        self.assertEqual(second["semantic_groups_created"], 0)
        self.assertEqual(second["options_created"], 0)
        self.assertEqual(second["provenance_created"], 0)
        self.assertEqual(
            second["legacy_groups_deactivated"],
            0,
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            semantic_groups = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_grupos_requisitos_documentales
                WHERE codigo NOT LIKE 'LEGACY_REQ_%'
                """
            ).fetchone()[0]

            semantic_options = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_grupo_requisito_documentos o
                JOIN config_grupos_requisitos_documentales g
                  ON g.id = o.grupo_id
                WHERE g.codigo NOT LIKE 'LEGACY_REQ_%'
                """
            ).fetchone()[0]

        self.assertEqual(semantic_groups, 27)
        self.assertEqual(semantic_options, 31)


if __name__ == "__main__":
    unittest.main()
