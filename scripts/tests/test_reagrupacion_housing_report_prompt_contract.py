import ast
import unittest
from pathlib import Path


class ReagrupacionHousingReportPromptContractTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(
            "frontend/views/expedients_view.py"
        )
        cls.source = cls.path.read_text(
            encoding="utf-8"
        )
        cls.tree = ast.parse(
            cls.source
        )

    def function_source(self, name):
        node = next(
            item
            for item in ast.walk(self.tree)
            if isinstance(item, ast.FunctionDef)
            and item.name == name
        )

        return (
            ast.get_source_segment(
                self.source,
                node,
            )
            or ""
        )

    def test_detects_exact_initial_reunification(self):
        source = self.function_source(
            "_is_initial_family_reunification"
        )

        self.assertIn(
            "REAGRUPACION_FAMILIAR",
            source,
        )
        self.assertIn(
            "INICIAL",
            source,
        )
        self.assertIn(
            "EXTRANJERIA",
            source,
        )

    def test_searches_same_client_housing_reports(self):
        source = self.function_source(
            "_list_client_housing_reports"
        )

        self.assertIn(
            "e.cliente_id = ?",
            source,
        )
        self.assertIn(
            "INFORME_VIVIENDA_ADECUADA",
            source,
        )

    def test_relation_direction_is_report_to_reunification(
        self,
    ):
        source = self.function_source(
            "_link_housing_report_to_reagrupacion"
        )

        self.assertIn(
            (
                "expediente_origen_id=int("
                "\n                        "
                "housing_report_id"
            ),
            source,
        )

        self.assertIn(
            (
                "expediente_destino_id=int("
                "\n                        "
                "reagrupacion_id"
            ),
            source,
        )

    def test_uses_existing_relation_service(self):
        source = self.function_source(
            "_link_housing_report_to_reagrupacion"
        )

        self.assertIn(
            "create_manual_expedient_relation",
            source,
        )
        self.assertIn(
            "ACTUACION_POSTERIOR",
            source,
        )

    def test_prompt_is_only_called_after_creation(self):
        source = self.function_source(
            "save_expediente"
        )

        creation_position = source.index(
            "create_expedient_with_continuity"
        )

        prompt_position = source.index(
            "_open_housing_report_prompt"
        )

        self.assertGreater(
            prompt_position,
            creation_position,
        )

    def test_existing_link_prevents_duplicate_prompt(self):
        source = self.function_source(
            "_open_housing_report_prompt"
        )

        self.assertIn(
            "_has_linked_housing_report",
            source,
        )

    def test_can_create_housing_report_from_prompt(
        self,
    ):
        source = self.function_source(
            "_open_housing_report_prompt"
        )

        self.assertIn(
            "Crear informe de vivienda",
            source,
        )

        self.assertIn(
            "_start_housing_report_creation",
            source,
        )

    def test_creation_inherits_client(self):
        source = self.function_source(
            "_start_housing_report_creation"
        )

        self.assertIn(
            "cliente_id=int(cliente_id)",
            source,
        )

    def test_creation_inherits_box_root(self):
        source = self.function_source(
            "_start_housing_report_creation"
        )

        self.assertIn(
            "box_folder_path",
            source,
        )

        self.assertIn(
            "pending_housing_report_box_root",
            source,
        )

    def test_created_report_is_linked_automatically(
        self,
    ):
        source = self.function_source(
            "_complete_pending_housing_report_relation"
        )

        self.assertIn(
            "create_manual_expedient_relation",
            source,
        )

        self.assertIn(
            "expediente_origen_id=int",
            source,
        )

        self.assertIn(
            "expediente_destino_id=int",
            source,
        )

    def test_user_can_continue_without_report(self):
        source = self.function_source(
            "_open_housing_report_prompt"
        )

        self.assertIn(
            "No crear informe",
            source,
        )

        self.assertIn(
            "_cancel_housing_report_creation",
            source,
        )

    def test_box_is_not_modified(self):
        sources = "\n".join(
            [
                self.function_source(
                    "_open_housing_report_prompt"
                ),
                self.function_source(
                    "_link_housing_report_to_reagrupacion"
                ),
            ]
        )

        self.assertNotIn(
            "link_box_folder_to_expediente",
            sources,
        )
        self.assertNotIn(
            "mkdir",
            sources,
        )


if __name__ == "__main__":
    unittest.main()
