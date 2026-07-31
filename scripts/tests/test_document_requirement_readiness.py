import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    document_requirement_readiness_service as readiness,
)


class DocumentRequirementReadinessTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "document_readiness.db"
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

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

                INSERT INTO config_documentos_catalogo
                    (id, codigo, nombre, categoria, activo)
                VALUES
                    (1, 'PASAPORTE', 'PASAPORTE', 'IDENTIDAD', 1),
                    (2, 'NIE', 'NIE', 'IDENTIDAD', 1),
                    (
                        3,
                        'CERTIFICADO_MATRIMONIO',
                        'CERTIFICADO DE MATRIMONIO',
                        'ESTADO_CIVIL',
                        1
                    ),
                    (
                        4,
                        'ACTA_NACIMIENTO',
                        'ACTA DE NACIMIENTO',
                        'ESTADO_CIVIL',
                        1
                    ),
                    (5, 'DELE', 'DELE', 'NACIONALIDAD', 1);

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
                        10,
                        14,
                        8,
                        'IDENTIDAD_PARTES',
                        'IDENTIDAD DE LAS PARTES',
                        'ALL',
                        0,
                        10,
                        1
                    ),
                    (
                        20,
                        14,
                        8,
                        'VINCULO',
                        'VÍNCULO',
                        'ANY',
                        1,
                        20,
                        1
                    ),
                    (
                        30,
                        14,
                        8,
                        'PRUEBAS',
                        'PRUEBAS',
                        'AT_LEAST',
                        2,
                        30,
                        1
                    ),
                    (
                        40,
                        14,
                        8,
                        'IDIOMA',
                        'IDIOMA',
                        'OPTIONAL',
                        0,
                        40,
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
                        101,
                        10,
                        1,
                        'REAGRUPANTE',
                        'Pasaporte del reagrupante',
                        10,
                        1
                    ),
                    (
                        102,
                        10,
                        1,
                        'REAGRUPADO',
                        'Pasaporte del reagrupado',
                        20,
                        1
                    ),
                    (
                        103,
                        10,
                        2,
                        'REAGRUPANTE',
                        'NIE del reagrupante',
                        30,
                        1
                    ),
                    (
                        201,
                        20,
                        3,
                        NULL,
                        'Certificado de matrimonio',
                        10,
                        1
                    ),
                    (
                        202,
                        20,
                        4,
                        NULL,
                        'Acta de nacimiento',
                        20,
                        1
                    ),
                    (
                        301,
                        30,
                        1,
                        NULL,
                        'Pasaporte',
                        10,
                        1
                    ),
                    (
                        302,
                        30,
                        2,
                        NULL,
                        'NIE',
                        20,
                        1
                    ),
                    (
                        303,
                        30,
                        4,
                        NULL,
                        'Nacimiento',
                        30,
                        1
                    ),
                    (
                        401,
                        40,
                        5,
                        NULL,
                        'DELE',
                        10,
                        1
                    );
                """
            )
            conn.commit()

        self.db_patch = patch.object(
            readiness,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_all_group_requires_every_role(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    {
                        "codigo": "PASAPORTE",
                        "rol_documental": "REAGRUPANTE",
                    },
                    {
                        "codigo": "PASAPORTE",
                        "rol_documental": "REAGRUPADO",
                    },
                    {
                        "codigo": "NIE",
                        "rol_documental": "REAGRUPANTE",
                    },
                ],
            )
        )

        identity = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "IDENTIDAD_PARTES"
        )

        self.assertTrue(identity["cumplido"])
        self.assertEqual(identity["documentos_detectados"], 3)

    def test_code_without_role_does_not_satisfy_role_option(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                ["PASAPORTE", "NIE"],
            )
        )

        identity = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "IDENTIDAD_PARTES"
        )

        self.assertFalse(identity["cumplido"])
        self.assertEqual(
            identity["opciones_ambiguas_por_rol"],
            3,
        )

    def test_any_group_accepts_one_alternative(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                ["ACTA_NAC"],
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VINCULO"
        )

        self.assertTrue(group["cumplido"])
        self.assertEqual(group["documentos_detectados"], 1)

    def test_at_least_group_requires_minimum(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                ["PASAPORTE", "NIE"],
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "PRUEBAS"
        )

        self.assertTrue(group["cumplido"])
        self.assertEqual(group["documentos_requeridos"], 2)

    def test_optional_group_never_blocks_completion(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    {
                        "codigo": "PASAPORTE",
                        "rol_documental": "REAGRUPANTE",
                    },
                    {
                        "codigo": "PASAPORTE",
                        "rol_documental": "REAGRUPADO",
                    },
                    {
                        "codigo": "NIE",
                        "rol_documental": "REAGRUPANTE",
                    },
                    "CERTIFICADO_MATRIMONIO",
                    "PASAPORTE",
                    "NIE",
                ],
            )
        )

        optional = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "IDIOMA"
        )

        self.assertTrue(optional["cumplido"])
        self.assertFalse(optional["bloquea_completitud"])
        self.assertEqual(
            optional["estado"],
            "OPCIONAL_NO_APORTADO",
        )
        self.assertTrue(result["completo"])

    def test_inactive_and_legacy_groups_are_ignored(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO config_grupos_requisitos_documentales (
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    codigo,
                    nombre,
                    regla_cumplimiento,
                    minimo_documentos,
                    activo
                )
                VALUES
                    (
                        50,
                        14,
                        8,
                        'LEGACY_REQ_1_PASAPORTE',
                        'LEGACY',
                        'ALL',
                        1,
                        1
                    ),
                    (
                        60,
                        14,
                        8,
                        'INACTIVO',
                        'INACTIVO',
                        'ALL',
                        1,
                        0
                    )
                """
            )
            conn.commit()

        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [],
            )
        )

        codes = {
            group["codigo"]
            for group in result["grupos"]
        }

        self.assertNotIn("LEGACY_REQ_1_PASAPORTE", codes)
        self.assertNotIn("INACTIVO", codes)


if __name__ == "__main__":
    unittest.main()
