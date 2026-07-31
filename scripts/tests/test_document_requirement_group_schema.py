import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    document_requirement_group_service as requirement_service,
)


class DocumentRequirementGroupSchemaTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = (
            Path(self.temp_dir.name)
            / "document_requirements.db"
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
                """
            )
            conn.commit()

        self.db_patch = patch.object(
            requirement_service,
            "DB_PATH",
            self.db_path,
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_create_any_group_with_alternative_documents(self):
        marriage_id = requirement_service.create_document_catalog(
            {
                "codigo": "CERTIFICADO_MATRIMONIO",
                "nombre": "Certificado de matrimonio",
                "categoria": "VINCULO",
            }
        )
        birth_id = requirement_service.create_document_catalog(
            {
                "codigo": "CERTIFICADO_NACIMIENTO",
                "nombre": "Certificado de nacimiento",
                "categoria": "VINCULO",
            }
        )

        group_id = requirement_service.create_requirement_group(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "codigo": "ACREDITACION_VINCULO",
                "nombre": "Acreditación del vínculo",
                "regla_cumplimiento": "ANY",
                "minimo_documentos": 99,
            }
        )

        requirement_service.add_document_to_group(
            group_id,
            marriage_id,
            orden=10,
        )
        requirement_service.add_document_to_group(
            group_id,
            birth_id,
            orden=20,
        )

        group = requirement_service.get_requirement_group(group_id)

        self.assertEqual(
            group["regla_cumplimiento"],
            "ANY",
        )
        self.assertEqual(group["minimo_documentos"], 1)
        self.assertEqual(len(group["documentos"]), 2)

    def test_rejects_subtype_from_another_type(self):
        with self.assertRaisesRegex(ValueError, "no pertenece"):
            requirement_service.create_requirement_group(
                {
                    "tipo_expediente_id": 10,
                    "subtipo_expediente_id": 200,
                    "codigo": "INVALIDO",
                    "nombre": "Grupo inválido",
                    "regla_cumplimiento": "ALL",
                }
            )

    def test_at_least_requires_positive_minimum(self):
        with self.assertRaisesRegex(ValueError, "mínimo"):
            requirement_service.create_requirement_group(
                {
                    "tipo_expediente_id": 10,
                    "subtipo_expediente_id": 100,
                    "codigo": "PRUEBAS",
                    "nombre": "Pruebas",
                    "regla_cumplimiento": "AT_LEAST",
                    "minimo_documentos": 0,
                }
            )

    def test_general_and_subtype_groups_can_share_code(self):
        requirement_service.create_requirement_group(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": None,
                "codigo": "IDENTIDAD",
                "nombre": "Identidad general",
                "regla_cumplimiento": "ALL",
            }
        )

        requirement_service.create_requirement_group(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "codigo": "IDENTIDAD",
                "nombre": "Identidad inicial",
                "regla_cumplimiento": "ALL",
            }
        )

        groups = requirement_service.list_requirement_groups(
            tipo_expediente_id=10
        )

        self.assertEqual(len(groups), 2)

    def test_any_group_without_options_is_not_ready(self):
        group_id = requirement_service.create_requirement_group(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "codigo": "VINCULO",
                "nombre": "Vínculo",
                "regla_cumplimiento": "ANY",
            }
        )

        validation = (
            requirement_service
            .validate_requirement_group_readiness(group_id)
        )

        self.assertFalse(validation["valido"])
        self.assertEqual(validation["documentos_activos"], 0)
        self.assertTrue(validation["errores"])

    def test_at_least_cannot_require_more_than_options(self):
        document_id = requirement_service.create_document_catalog(
            {
                "codigo": "PRUEBA_1",
                "nombre": "Prueba 1",
            }
        )

        group_id = requirement_service.create_requirement_group(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "codigo": "PRUEBAS_PERMANENCIA",
                "nombre": "Pruebas de permanencia",
                "regla_cumplimiento": "AT_LEAST",
                "minimo_documentos": 2,
            }
        )

        requirement_service.add_document_to_group(
            group_id,
            document_id,
        )

        validation = (
            requirement_service
            .validate_requirement_group_readiness(group_id)
        )

        self.assertFalse(validation["valido"])
        self.assertEqual(validation["documentos_activos"], 1)
        self.assertIn(
            "supera",
            validation["errores"][0],
        )

    def test_ready_group_passes_validation(self):
        marriage_id = requirement_service.create_document_catalog(
            {
                "codigo": "MATRIMONIO",
                "nombre": "Certificado de matrimonio",
            }
        )
        birth_id = requirement_service.create_document_catalog(
            {
                "codigo": "NACIMIENTO",
                "nombre": "Certificado de nacimiento",
            }
        )

        group_id = requirement_service.create_requirement_group(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "codigo": "VINCULO",
                "nombre": "Vínculo",
                "regla_cumplimiento": "ANY",
            }
        )

        requirement_service.add_document_to_group(
            group_id,
            marriage_id,
        )
        requirement_service.add_document_to_group(
            group_id,
            birth_id,
        )

        validation = (
            requirement_service
            .validate_requirement_group_readiness(group_id)
        )

        self.assertTrue(validation["valido"])
        self.assertEqual(validation["documentos_activos"], 2)
        self.assertEqual(validation["errores"], [])

    def test_duplicate_document_in_group_is_rejected(self):
        document_id = requirement_service.create_document_catalog(
            {
                "codigo": "PASAPORTE",
                "nombre": "Pasaporte",
            }
        )

        group_id = requirement_service.create_requirement_group(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "codigo": "IDENTIDAD",
                "nombre": "Identidad",
                "regla_cumplimiento": "ALL",
            }
        )

        requirement_service.add_document_to_group(
            group_id,
            document_id,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            requirement_service.add_document_to_group(
                group_id,
                document_id,
            )


if __name__ == "__main__":
    unittest.main()
