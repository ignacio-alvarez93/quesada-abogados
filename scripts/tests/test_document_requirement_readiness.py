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
                    (5, 'DELE', 'DELE', 'NACIONALIDAD', 1),
                    (
                        6,
                        'INFORME_DE_VIVIENDA',
                        'INFORME DE VIVIENDA',
                        'VIVIENDA',
                        1
                    ),
                    (
                        7,
                        'JUSTIFICANTE_SOLICITUD_INFORME_VIVIENDA',
                        'JUSTIFICANTE DE SOLICITUD DEL INFORME DE VIVIENDA',
                        'VIVIENDA',
                        1
                    ),
                    (
                        8,
                        'ACREDITACION_MEDIOS_ECONOMICOS',
                        'ACREDITACIÓN DE MEDIOS ECONÓMICOS',
                        'LEGACY_AGGREGATE',
                        1
                    ),
                    (
                        9,
                        'NOMINAS',
                        'NÓMINAS',
                        'MEDIOS_ECONOMICOS',
                        1
                    ),
                    (
                        10,
                        'CONTRATO_TRABAJO',
                        'CONTRATO DE TRABAJO',
                        'MEDIOS_ECONOMICOS',
                        1
                    ),
                    (
                        11,
                        'VIDA_LABORAL',
                        'VIDA LABORAL',
                        'MEDIOS_ECONOMICOS',
                        1
                    ),
                    (
                        12,
                        'DECLARACION_IRPF',
                        'DECLARACIÓN DEL IRPF',
                        'MEDIOS_ECONOMICOS',
                        1
                    ),
                    (
                        13,
                        'EXTRACTOS_BANCARIOS',
                        'EXTRACTOS BANCARIOS',
                        'MEDIOS_ECONOMICOS',
                        1
                    ),
                    (
                        14,
                        'CERTIFICADO_BANCARIO',
                        'CERTIFICADO BANCARIO',
                        'MEDIOS_ECONOMICOS',
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
                    ),
                    (
                        45,
                        14,
                        8,
                        'VIVIENDA',
                        'ADECUACIÓN DE LA VIVIENDA',
                        'ANY',
                        1,
                        45,
                        1
                    ),
                    (
                        50,
                        14,
                        8,
                        'MEDIOS_ECONOMICOS',
                        'ACREDITACIÓN DE MEDIOS ECONÓMICOS',
                        'ANY',
                        1,
                        50,
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
                    ),
                    (
                        451,
                        45,
                        6,
                        NULL,
                        'Informe de vivienda',
                        10,
                        1
                    ),
                    (
                        452,
                        45,
                        7,
                        NULL,
                        'Justificante de solicitud del informe',
                        20,
                        1
                    ),
                    (
                        501,
                        50,
                        8,
                        NULL,
                        'Acreditación agregada legacy',
                        0,
                        1
                    ),
                    (
                        502,
                        50,
                        9,
                        'REAGRUPANTE',
                        'Nóminas del reagrupante',
                        10,
                        1
                    ),
                    (
                        503,
                        50,
                        10,
                        'REAGRUPANTE',
                        'Contrato de trabajo del reagrupante',
                        20,
                        1
                    ),
                    (
                        504,
                        50,
                        11,
                        'REAGRUPANTE',
                        'Vida laboral del reagrupante',
                        30,
                        1
                    ),
                    (
                        505,
                        50,
                        12,
                        'REAGRUPANTE',
                        'Declaración del IRPF',
                        40,
                        1
                    ),
                    (
                        506,
                        50,
                        13,
                        'REAGRUPANTE',
                        'Extractos bancarios',
                        50,
                        1
                    ),
                    (
                        507,
                        50,
                        14,
                        'REAGRUPANTE',
                        'Certificado bancario',
                        60,
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
                    "INFORME_DE_VIVIENDA",
                    {
                        "codigo": "NOMINAS",
                        "rol_documental": (
                            "REAGRUPANTE"
                        ),
                    },
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

    def test_housing_group_blocks_without_document(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [],
            )
        )

        housing = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VIVIENDA"
        )

        self.assertEqual(housing["estado"], "PENDIENTE")
        self.assertFalse(housing["cumplido"])
        self.assertTrue(housing["bloquea_completitud"])
        self.assertEqual(housing["documentos_detectados"], 0)
        self.assertEqual(housing["documentos_requeridos"], 1)

    def test_housing_group_accepts_housing_report(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    {
                        "codigo": "INFORME_DE_VIVIENDA",
                        "archivo": "informe_vivienda.pdf",
                    },
                ],
            )
        )

        housing = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VIVIENDA"
        )

        self.assertEqual(housing["estado"], "CUMPLIDO")
        self.assertTrue(housing["cumplido"])
        self.assertFalse(housing["bloquea_completitud"])
        self.assertEqual(housing["documentos_detectados"], 1)
        self.assertEqual(housing["documentos_requeridos"], 1)

    def test_housing_group_accepts_request_receipt(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    {
                        "codigo": (
                            "JUSTIFICANTE_SOLICITUD_"
                            "INFORME_VIVIENDA"
                        ),
                        "archivo": (
                            "justificante_solicitud_"
                            "informe_vivienda.pdf"
                        ),
                    },
                ],
            )
        )

        housing = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VIVIENDA"
        )

        self.assertEqual(housing["estado"], "CUMPLIDO")
        self.assertTrue(housing["cumplido"])
        self.assertFalse(housing["bloquea_completitud"])
        self.assertEqual(housing["documentos_detectados"], 1)
        self.assertEqual(housing["documentos_requeridos"], 1)

    def test_spouse_requires_marriage_certificate(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    {
                        "codigo": (
                            "CERTIFICADO_MATRIMONIO"
                        ),
                    },
                ],
                context={
                    (
                        "vinculo_reagrupado_"
                        "reagrupante"
                    ): "CÓNYUGE",
                },
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VINCULO"
        )

        self.assertTrue(group["cumplido"])
        self.assertTrue(
            group[
                "filtro_contextual_aplicado"
            ]
        )
        self.assertEqual(
            [
                option["documento_codigo"]
                for option in group["opciones"]
            ],
            ["CERTIFICADO_MATRIMONIO"],
        )

    def test_spouse_does_not_accept_birth_certificate(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                ["ACTA_NACIMIENTO"],
                context={
                    (
                        "vinculo_reagrupado_"
                        "reagrupante"
                    ): "CÓNYUGE",
                },
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VINCULO"
        )

        self.assertFalse(group["cumplido"])
        self.assertEqual(
            [
                option["documento_codigo"]
                for option in group["opciones"]
            ],
            ["CERTIFICADO_MATRIMONIO"],
        )

    def test_minor_child_requires_birth_certificate(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                ["ACTA_NACIMIENTO"],
                context={
                    (
                        "vinculo_reagrupado_"
                        "reagrupante"
                    ): "HIJO/A MENOR 18 AÑOS",
                },
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VINCULO"
        )

        self.assertTrue(group["cumplido"])
        self.assertEqual(
            [
                option["documento_codigo"]
                for option in group["opciones"]
            ],
            ["ACTA_NACIMIENTO"],
        )

    def test_minor_child_does_not_accept_marriage_certificate(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                ["CERTIFICADO_MATRIMONIO"],
                context={
                    (
                        "vinculo_reagrupado_"
                        "reagrupante"
                    ): "HIJO/A MENOR 18 AÑOS",
                },
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"] == "VINCULO"
        )

        self.assertFalse(group["cumplido"])
        self.assertEqual(
            [
                option["documento_codigo"]
                for option in group["opciones"]
            ],
            ["ACTA_NACIMIENTO"],
        )

    def test_economic_group_blocks_without_evidence(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [],
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"]
            == "MEDIOS_ECONOMICOS"
        )

        self.assertFalse(group["cumplido"])
        self.assertTrue(
            group["bloquea_completitud"]
        )
        self.assertEqual(
            group["documentos_requeridos"],
            1,
        )

    def test_economic_group_accepts_payroll_evidence(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    {
                        "codigo": "NOMINAS",
                        "rol_documental": (
                            "REAGRUPANTE"
                        ),
                    },
                ],
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"]
            == "MEDIOS_ECONOMICOS"
        )

        self.assertTrue(group["cumplido"])
        self.assertEqual(
            group["documentos_detectados"],
            1,
        )

    def test_economic_role_must_be_reagrupante(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    {
                        "codigo": "NOMINAS",
                        "rol_documental": (
                            "REAGRUPADO"
                        ),
                    },
                ],
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"]
            == "MEDIOS_ECONOMICOS"
        )

        self.assertFalse(group["cumplido"])
        self.assertEqual(
            group[
                "opciones_ambiguas_por_rol"
            ],
            1,
        )

    def test_economic_legacy_aggregate_remains_valid(self):
        result = (
            readiness
            .evaluate_semantic_requirement_readiness(
                14,
                8,
                [
                    "ACREDITACION_MEDIOS_ECONOMICOS",
                ],
            )
        )

        group = next(
            group
            for group in result["grupos"]
            if group["codigo"]
            == "MEDIOS_ECONOMICOS"
        )

        self.assertTrue(group["cumplido"])
        self.assertEqual(
            group["documentos_detectados"],
            1,
        )

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
                        60,
                        14,
                        8,
                        'LEGACY_REQ_1_PASAPORTE',
                        'LEGACY',
                        'ALL',
                        1,
                        1
                    ),
                    (
                        70,
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
