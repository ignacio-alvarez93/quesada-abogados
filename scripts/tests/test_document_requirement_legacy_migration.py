import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    document_requirement_legacy_migration_service as migration,
)


class LegacyDocumentRequirementMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "legacy_document_migration.db"
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
                    (10, 'REAGRUPACION', 'REAGRUPACIÓN', 1),
                    (20, 'NACIONALIDAD', 'NACIONALIDAD', 1);

                INSERT INTO config_subtipos_expediente
                    (
                        id,
                        tipo_expediente_id,
                        codigo,
                        nombre,
                        activo
                    )
                VALUES
                    (100, 10, 'INICIAL', 'INICIAL', 1),
                    (200, 20, 'GENERAL', 'GENERAL', 1);

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
                        1,
                        10,
                        100,
                        'PASAPORTE_REAGRUPANTE',
                        'PASAPORTE REAGRUPANTE',
                        1,
                        10,
                        1
                    ),
                    (
                        2,
                        10,
                        100,
                        'PASAPORTE_REAGRUPADO',
                        'PASAPORTE REAGRUPADO',
                        1,
                        20,
                        1
                    ),
                    (
                        3,
                        20,
                        200,
                        'PASAPORTE',
                        'PASAPORTE',
                        1,
                        10,
                        1
                    ),
                    (
                        4,
                        20,
                        200,
                        'MEDIOS_ECONOMICOS',
                        'MEDIOS ECONÓMICOS',
                        0,
                        30,
                        1
                    );
                """
            )
            conn.commit()

        self.db_patch = patch.object(
            migration,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_preview_does_not_write(self):
        preview = (
            migration
            .preview_legacy_document_requirement_migration()
        )

        self.assertEqual(len(preview), 4)
        self.assertEqual(
            preview[0]["documento_codigo"],
            "PASAPORTE",
        )
        self.assertEqual(
            preview[0]["rol_documental"],
            "REAGRUPANTE",
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'config_documentos_catalogo'
                """
            ).fetchone()

        self.assertIsNone(table)

    def test_migration_deduplicates_canonical_documents(self):
        summary = (
            migration
            .migrate_legacy_document_requirements()
        )

        self.assertEqual(summary["legacy_rows"], 4)

        with closing(sqlite3.connect(self.db_path)) as conn:
            passport_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_documentos_catalogo
                WHERE codigo = 'PASAPORTE'
                """
            ).fetchone()[0]

            total_catalog = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_documentos_catalogo
                """
            ).fetchone()[0]

        self.assertEqual(passport_count, 1)
        self.assertEqual(total_catalog, 2)

    def test_migration_preserves_distinct_roles(self):
        migration.migrate_legacy_document_requirements()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            roles = {
                row["rol_documental"]
                for row in conn.execute(
                    """
                    SELECT o.rol_documental
                    FROM config_grupo_requisito_documentos o
                    JOIN config_documentos_catalogo d
                      ON d.id = o.documento_catalogo_id
                    WHERE d.codigo = 'PASAPORTE'
                    """
                ).fetchall()
            }

        self.assertEqual(
            roles,
            {
                "REAGRUPANTE",
                "REAGRUPADO",
                "TITULAR",
            },
        )

    def test_optional_legacy_requirement_becomes_optional_group(self):
        migration.migrate_legacy_document_requirements()

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT
                    regla_cumplimiento,
                    minimo_documentos
                FROM config_grupos_requisitos_documentales
                WHERE codigo =
                    'LEGACY_REQ_4_MEDIOS_ECONOMICOS'
                """
            ).fetchone()

        self.assertEqual(row[0], "OPTIONAL")
        self.assertEqual(row[1], 0)

    def test_migration_is_idempotent(self):
        first = migration.migrate_legacy_document_requirements()
        second = migration.migrate_legacy_document_requirements()

        self.assertEqual(first["legacy_rows"], 4)
        self.assertEqual(second["legacy_rows"], 4)
        self.assertEqual(second["catalog_created"], 0)
        self.assertEqual(second["groups_created"], 0)
        self.assertEqual(second["options_created"], 0)

        with closing(sqlite3.connect(self.db_path)) as conn:
            counts = {
                "catalog": conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM config_documentos_catalogo
                    """
                ).fetchone()[0],
                "groups": conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM config_grupos_requisitos_documentales
                    """
                ).fetchone()[0],
                "options": conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM config_grupo_requisito_documentos
                    """
                ).fetchone()[0],
                "legacy": conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM config_documentos_requeridos
                    """
                ).fetchone()[0],
            }

        self.assertEqual(
            counts,
            {
                "catalog": 2,
                "groups": 4,
                "options": 4,
                "legacy": 4,
            },
        )


if __name__ == "__main__":
    unittest.main()
