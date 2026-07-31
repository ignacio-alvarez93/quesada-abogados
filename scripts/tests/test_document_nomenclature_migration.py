import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    document_nomenclature_migration_service
    as migration,
)


class DocumentNomenclatureMigrationTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "nomenclature_migration.db"
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT NOT NULL UNIQUE,
                    nombre TEXT NOT NULL
                );

                CREATE TABLE config_subtipos_expediente (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER NOT NULL,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL
                );

                CREATE TABLE config_documentos_requeridos (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER NOT NULL,
                    subtipo_expediente_id INTEGER,
                    codigo_documento TEXT NOT NULL,
                    nombre_documento TEXT NOT NULL,
                    obligatorio INTEGER NOT NULL DEFAULT 1,
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

                INSERT INTO config_tipos_expediente
                    (id, codigo, nombre)
                VALUES
                    (3, 'NACIONALIDAD', 'NACIONALIDAD');

                INSERT INTO config_subtipos_expediente
                    (
                        id,
                        tipo_expediente_id,
                        codigo,
                        nombre
                    )
                VALUES
                    (
                        1,
                        3,
                        'CASO_GENERAL',
                        'CASO GENERAL'
                    );

                INSERT INTO config_documentos_requeridos (
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    codigo_documento,
                    nombre_documento,
                    obligatorio,
                    activo
                )
                VALUES
                    (
                        1,
                        3,
                        1,
                        'AAPP',
                        'AAPP',
                        1,
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
                        1,
                        3,
                        1,
                        'PENALES',
                        '.PDF;pdf',
                        1,
                        NULL
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
                        50,
                        'ANTECEDENTES_PENALES',
                        'ANTECEDENTES PENALES',
                        'ANTECEDENTES',
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

    def test_preview_preserves_general_subtype_scope(self):
        preview = (
            migration
            .preview_nomenclature_migration()
        )

        self.assertEqual(len(preview), 1)
        self.assertEqual(
            preview[0]["codigo_canonico"],
            "ANTECEDENTES_PENALES",
        )
        self.assertIsNone(
            preview[0]["subtipo_expediente_id"]
        )
        self.assertIsNone(
            preview[0]["rol_documental"]
        )

    def test_preview_does_not_create_table(self):
        migration.preview_nomenclature_migration()

        with closing(sqlite3.connect(self.db_path)) as conn:
            table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name =
                    'config_nomenclaturas_catalogo'
                """
            ).fetchone()

        self.assertIsNone(table)

    def test_migration_creates_canonical_nomenclature(self):
        summary = (
            migration
            .migrate_document_nomenclatures()
        )

        self.assertEqual(summary["legacy_rows"], 1)
        self.assertEqual(summary["created"], 1)

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row

            row = conn.execute(
                """
                SELECT *
                FROM config_nomenclaturas_catalogo
                """
            ).fetchone()

        self.assertEqual(
            row["documento_catalogo_id"],
            50,
        )
        self.assertEqual(
            row["tipo_expediente_id"],
            3,
        )
        self.assertIsNone(
            row["subtipo_expediente_id"]
        )
        self.assertEqual(
            row["patron_nombre"],
            "PENALES",
        )
        self.assertEqual(
            row["extension_permitida"],
            "pdf",
        )
        self.assertEqual(
            row["origen_legacy_id"],
            1,
        )

    def test_migration_is_idempotent(self):
        first = (
            migration
            .migrate_document_nomenclatures()
        )
        second = (
            migration
            .migrate_document_nomenclatures()
        )

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["reused"], 1)
        self.assertEqual(second["updated"], 0)

        with closing(sqlite3.connect(self.db_path)) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM config_nomenclaturas_catalogo
                """
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_legacy_change_updates_canonical_record(self):
        migration.migrate_document_nomenclatures()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                UPDATE config_nomenclaturas_documentales
                SET patron_nombre = 'PENALES*'
                WHERE id = 1
                """
            )
            conn.commit()

        summary = (
            migration
            .migrate_document_nomenclatures()
        )

        self.assertEqual(summary["updated"], 1)

        with closing(sqlite3.connect(self.db_path)) as conn:
            pattern = conn.execute(
                """
                SELECT patron_nombre
                FROM config_nomenclaturas_catalogo
                WHERE origen_legacy_id = 1
                """
            ).fetchone()[0]

        self.assertEqual(pattern, "PENALES*")

    def test_legacy_table_remains_untouched(self):
        migration.migrate_document_nomenclatures()

        with closing(sqlite3.connect(self.db_path)) as conn:
            legacy = conn.execute(
                """
                SELECT
                    documento_id,
                    patron_nombre,
                    subtipo_expediente_id,
                    activo
                FROM config_nomenclaturas_documentales
                WHERE id = 1
                """
            ).fetchone()

        self.assertEqual(
            legacy,
            (
                1,
                "PENALES",
                None,
                1,
            ),
        )


if __name__ == "__main__":
    unittest.main()
