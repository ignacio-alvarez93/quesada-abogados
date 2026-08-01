import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import expedient_dynamic_form_service
from backend.services import form_mapper_service
from backend.services import mercurio_mapper_service
from backend.services import presentation_config_service


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DB = PROJECT_ROOT / "database" / "quesada.db"


class ImmigrationProcedureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True
        )
        cls.db_path = Path(cls.temp_dir.name) / "quesada_test.db"
        shutil.copy2(SOURCE_DB, cls.db_path)

        cls.patchers = [
            patch.object(
                expedient_dynamic_form_service,
                "DB_PATH",
                cls.db_path,
            ),
            patch.object(
                form_mapper_service,
                "DB_PATH",
                cls.db_path,
            ),
            patch.object(
                mercurio_mapper_service,
                "DB_PATH",
                cls.db_path,
            ),
            patch.object(
                presentation_config_service,
                "DB_PATH",
                cls.db_path,
            ),
        ]

        for patcher in cls.patchers:
            patcher.start()

    @classmethod
    def tearDownClass(cls):
        for patcher in reversed(cls.patchers):
            patcher.stop()

        cls.temp_dir.cleanup()

    def _get_type_and_subtype(self, type_code, subtype_code):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            row = conn.execute(
                """
                SELECT
                    t.id AS tipo_id,
                    t.codigo AS tipo_codigo,
                    t.familia_id,
                    f.codigo AS familia_codigo,
                    s.id AS subtipo_id,
                    s.codigo AS subtipo_codigo
                FROM config_tipos_expediente t
                JOIN config_familias_expediente f
                  ON f.id = t.familia_id
                JOIN config_subtipos_expediente s
                  ON s.tipo_expediente_id = t.id
                WHERE t.codigo = ?
                  AND s.codigo = ?
                  AND t.activo = 1
                  AND s.activo = 1
                """,
                (type_code, subtype_code),
            ).fetchone()

        self.assertIsNotNone(
            row,
            msg=(
                f"No existe contrato activo para "
                f"{type_code}/{subtype_code}"
            ),
        )

        return dict(row)

    def _get_pdf_mapper(self, type_id, subtype_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            row = conn.execute(
                """
                SELECT *
                FROM form_mapper_templates
                WHERE activo = 1
                  AND tipo_expediente_id = ?
                  AND (
                      subtipo_expediente_id = ?
                      OR subtipo_expediente_id IS NULL
                  )
                ORDER BY
                    CASE
                        WHEN subtipo_expediente_id = ? THEN 0
                        ELSE 1
                    END,
                    id DESC
                LIMIT 1
                """,
                (
                    int(type_id),
                    int(subtype_id),
                    int(subtype_id),
                ),
            ).fetchone()

        return dict(row) if row else None

    def _assert_contract(
        self,
        *,
        type_code,
        subtype_code,
        expected_dynamic_form,
        expected_pdf_mapper,
        expected_mercurio_form,
        expected_mercurio_mapper,
    ):
        context = self._get_type_and_subtype(
            type_code,
            subtype_code,
        )

        self.assertEqual(
            context["familia_codigo"],
            "EXTRANJERIA",
        )

        dynamic_form = (
            expedient_dynamic_form_service
            .get_formulario_for_context(
                context["tipo_id"],
                context["subtipo_id"],
            )
        )

        self.assertIsNotNone(dynamic_form["formulario"])
        self.assertEqual(
            dynamic_form["formulario"]["codigo"],
            expected_dynamic_form,
        )

        pdf_mapper = self._get_pdf_mapper(
            context["tipo_id"],
            context["subtipo_id"],
        )

        self.assertIsNotNone(pdf_mapper)
        self.assertEqual(
            pdf_mapper["codigo"],
            expected_pdf_mapper,
        )

        config = presentation_config_service.get_presentacion_config(
            context["tipo_id"],
            context["subtipo_id"],
        )

        self.assertIsNotNone(config)
        self.assertEqual(
            config["portal"],
            "MERCURIO",
        )
        self.assertEqual(
            config["flujo"],
            "BI_PRESENTAR_NUEVA_SOLICITUD",
        )

        reglas = presentation_config_service.get_presentacion_reglas(
            context["tipo_id"],
            context["subtipo_id"],
        )

        self.assertEqual(
            reglas.get("tipo_formulario_objetivo"),
            expected_mercurio_form,
        )
        self.assertEqual(
            reglas.get("mapper_codigo"),
            expected_mercurio_mapper,
        )

        expediente_json = {
            "tipo_expediente_id": context["tipo_id"],
            "tipo_expediente_codigo": context["tipo_codigo"],
            "subtipo_expediente_id": context["subtipo_id"],
            "subtipo_expediente_codigo": context["subtipo_codigo"],
        }

        self.assertEqual(
            mercurio_mapper_service
            .resolve_tipo_formulario_objetivo(
                expediente_json
            ),
            expected_mercurio_form,
        )

        self.assertEqual(
            mercurio_mapper_service.resolve_mapper_codigo(
                expediente_json,
                expected_mercurio_form,
            ),
            expected_mercurio_mapper,
        )

    def test_no_lucrativa_renovacion_titular_contract(self):
        self._assert_contract(
            type_code="RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
            subtype_code="RENOVACION_TITULAR",
            expected_dynamic_form="EX01",
            expected_pdf_mapper="EX01",
            expected_mercurio_form="EX01",
            expected_mercurio_mapper="MERCURIO_EX01",
        )

    def test_no_lucrativa_renovacion_familiar_contract(self):
        self._assert_contract(
            type_code="RESIDENCIA_TEMPORAL_NO_LUCRATIVA",
            subtype_code="RENOVACION_FAMILIAR",
            expected_dynamic_form="EX01",
            expected_pdf_mapper="EX01_FAMILIAR",
            expected_mercurio_form="EX01",
            expected_mercurio_mapper="MERCURIO_EX01_FAMILIAR",
        )

    def test_reagrupacion_familiar_inicial_contract(self):
        self._assert_contract(
            type_code="REAGRUPACION_FAMILIAR",
            subtype_code="INICIAL",
            expected_dynamic_form="EX02",
            expected_pdf_mapper="EX02",
            expected_mercurio_form="EX02",
            expected_mercurio_mapper="MERCURIO_EX02",
        )

    def test_wrong_subtype_does_not_resolve_presentation(self):
        context = self._get_type_and_subtype(
            "REAGRUPACION_FAMILIAR",
            "INICIAL",
        )

        config = presentation_config_service.get_presentacion_config(
            context["tipo_id"],
            999999,
        )

        self.assertIsNone(config)

    def test_mapper_json_is_valid_for_protected_contracts(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                """
                SELECT codigo, mapper_json, required_fields_json
                FROM form_mapper_templates
                WHERE codigo IN (
                    'EX01',
                    'EX01_FAMILIAR',
                    'EX02'
                )
                """
            ).fetchall()

        self.assertEqual(len(rows), 3)

        for row in rows:
            mapper = json.loads(row["mapper_json"])
            required = json.loads(
                row["required_fields_json"] or "[]"
            )

            self.assertIsInstance(mapper, dict)
            self.assertGreater(
                len(mapper),
                0,
                msg=f"Mapper vacío: {row['codigo']}",
            )
            self.assertIsInstance(required, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
