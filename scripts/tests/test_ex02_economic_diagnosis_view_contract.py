import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEW_PATH = (
    ROOT
    / "frontend"
    / "views"
    / "expedients_view.py"
)


class Ex02EconomicDiagnosisViewContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = VIEW_PATH.read_text(
            encoding="utf-8"
        )
        cls.tree = ast.parse(cls.source)

        cls.string_constants = {
            node.value
            for node in ast.walk(cls.tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        }

        cls.names = {
            node.id
            for node in ast.walk(cls.tree)
            if isinstance(node, ast.Name)
        }

        cls.attributes = {
            node.attr
            for node in ast.walk(cls.tree)
            if isinstance(node, ast.Attribute)
        }

    def test_view_is_valid_python(self):
        self.assertIsInstance(
            self.tree,
            ast.Module,
        )

    def test_economic_service_is_imported(self):
        self.assertIn(
            (
                "family_reunification_"
                "economic_diagnosis_service"
            ),
            self.source,
        )
        self.assertIn(
            "reunification_economic_diagnosis",
            self.names,
        )

    def test_ex02_has_economic_step(self):
        self.assertIn(
            "Medios económicos",
            self.string_constants,
        )
        self.assertIn(
            "Diagnóstico orientativo",
            self.string_constants,
        )

    def test_stepper_uses_dynamic_step_count(self):
        self.assertIn(
            "specific_steps_count",
            self.string_constants,
        )

        assignments = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Assign)
        ]

        has_len_steps_assignment = False

        for assignment in assignments:
            value = assignment.value

            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "len"
                and len(value.args) == 1
                and isinstance(value.args[0], ast.Name)
                and value.args[0].id == "steps"
            ):
                continue

            for target in assignment.targets:
                if not isinstance(
                    target,
                    ast.Subscript,
                ):
                    continue

                slice_node = target.slice

                if (
                    isinstance(
                        slice_node,
                        ast.Constant,
                    )
                    and slice_node.value
                    == "specific_steps_count"
                ):
                    has_len_steps_assignment = True

        self.assertTrue(
            has_len_steps_assignment,
            (
                "La vista debe registrar "
                "specific_steps_count = len(steps)"
            ),
        )

    def test_ex02_economic_input_codes_exist(self):
        expected_codes = {
            "numero_personas_reagrupadas",
            "numero_reagrupados_menores",
            "iprem_mensual_referencia_euros",
            "iprem_mensual_referencia_centimos",
            (
                "ingresos_mensuales_"
                "computables_euros"
            ),
            (
                "ingresos_mensuales_"
                "computables_centimos"
            ),
            "criterio_economico",
            (
                "valoracion_profesional_"
                "economica"
            ),
            (
                "observaciones_valoracion_"
                "economica"
            ),
        }

        for code in expected_codes:
            with self.subTest(code=code):
                self.assertIn(
                    code,
                    self.string_constants,
                )

    def test_diagnosis_snapshot_codes_exist(self):
        expected_codes = {
            "diagnostico_economico_estado",
            (
                "diagnostico_economico_"
                "porcentaje_iprem"
            ),
            (
                "diagnostico_economico_"
                "importe_referencia_centimos"
            ),
            (
                "diagnostico_economico_"
                "diferencia_centimos"
            ),
            (
                "diagnostico_economico_"
                "porcentaje_cobertura"
            ),
            (
                "diagnostico_economico_"
                "nivel_advertencia"
            ),
            (
                "diagnostico_economico_"
                "requiere_revision"
            ),
            (
                "diagnostico_economico_"
                "bloquea_presentacion"
            ),
        }

        for code in expected_codes:
            with self.subTest(code=code):
                self.assertIn(
                    code,
                    self.string_constants,
                )

    def test_diagnosis_calls_pure_service(self):
        matching_calls = []

        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue

            function = node.func

            if (
                isinstance(function, ast.Attribute)
                and function.attr
                == (
                    "evaluate_family_reunification_"
                    "economic_diagnosis"
                )
            ):
                matching_calls.append(node)

        self.assertTrue(
            matching_calls,
            (
                "EX02 debe invocar el servicio "
                "puro de diagnóstico económico"
            ),
        )

    def test_diagnosis_is_explicitly_non_blocking(self):
        code = (
            "diagnostico_economico_"
            "bloquea_presentacion"
        )

        self.assertIn(
            code,
            self.string_constants,
        )
        self.assertIn(
            "No",
            self.string_constants,
        )

    def test_professional_assessment_is_independent(self):
        expected_options = {
            "PENDIENTE",
            "VIABLE",
            "VIABLE_CON_ADVERTENCIAS",
            "NO_RECOMENDADO",
        }

        for option in expected_options:
            with self.subTest(option=option):
                self.assertIn(
                    option,
                    self.string_constants,
                )

    def test_economic_card_is_part_of_ex02_steps(self):
        self.assertIn(
            "economic_card",
            self.names,
        )
        self.assertIn(
            (
                "Diagnóstico de medios "
                "económicos"
            ),
            self.string_constants,
        )


if __name__ == "__main__":
    unittest.main()
