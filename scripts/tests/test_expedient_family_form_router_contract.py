import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "expedients_view.py"
)


class ExpedientFamilyFormRouterContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = VIEW.read_text(
            encoding="utf-8"
        )

        cls.tree = ast.parse(cls.source)

        cls.function_names = {
            node.name
            for node in ast.walk(cls.tree)
            if isinstance(
                node,
                ast.FunctionDef,
            )
        }

    def _function_source(self, name):
        function = next(
            node
            for node in ast.walk(self.tree)
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name == name
            )
        )

        return ast.get_source_segment(
            self.source,
            function,
        )

    def test_resolves_current_family(self):
        self.assertIn(
            "current_expedient_family",
            self.function_names,
        )

        self.assertIn(
            "current_expedient_family_code",
            self.function_names,
        )

        self.assertIn(
            "new_expedient_family_code",
            self.source,
        )

    def test_has_family_section_router(self):
        self.assertIn(
            "get_family_dialog_sections",
            self.function_names,
        )

        source = self._function_source(
            "get_family_dialog_sections"
        )

        self.assertIn(
            "is_immigration_expedient",
            source,
        )

        self.assertIn(
            "Trazabilidad",
            source,
        )

    def test_immigration_keeps_special_sections(self):
        source = self._function_source(
            "get_family_dialog_sections"
        )

        for label in (
            "Plantillas y formularios",
            "Diagnóstico",
            "Automatización",
        ):
            self.assertIn(
                label,
                source,
            )

    def test_has_generic_family_form(self):
        self.assertIn(
            "build_generic_expedient_edit_content",
            self.function_names,
        )

        source = self._function_source(
            "build_generic_expedient_edit_content"
        )

        self.assertIn(
            "numero_expediente",
            source,
        )

        self.assertIn(
            "familia_expediente.control",
            source,
        )

        self.assertIn(
            "continuity_form_wrapper",
            source,
        )

    def test_generic_form_excludes_immigration_ids(self):
        source = self._function_source(
            "build_generic_expedient_edit_content"
        )

        self.assertNotIn(
            "id_presentacion",
            source,
        )

        self.assertNotIn(
            "numero_expediente_extranjeria",
            source,
        )

        self.assertNotIn(
            "MERCURIO",
            source.upper(),
        )

    def test_family_form_routes_immigration(self):
        source = self._function_source(
            "build_family_edit_content"
        )

        self.assertIn(
            "is_immigration_expedient",
            source,
        )

        self.assertIn(
            "build_edit_content",
            source,
        )

        self.assertIn(
            "build_generic_expedient_edit_content",
            source,
        )

    def test_dialog_uses_family_sections(self):
        source = self._function_source(
            "build_expediente_dialog_content"
        )

        self.assertIn(
            "get_family_dialog_sections",
            source,
        )

        self.assertIn(
            "allowed_sections",
            source,
        )

    def test_dialog_section_uses_family_form(self):
        source = self._function_source(
            "build_dialog_section_content"
        )

        self.assertIn(
            "build_family_edit_content",
            source,
        )

    def test_specific_data_remains_available(self):
        source = self._function_source(
            "get_family_dialog_sections"
        )

        self.assertIn(
            "Datos específicos",
            source,
        )

        self.assertIn(
            "Documentación",
            source,
        )

    def test_has_family_specific_header(self):
        self.assertIn(
            "_family_form_header",
            self.function_names,
        )

        source = self._function_source(
            "_family_form_header"
        )

        for code in (
            "EXTRANJERIA",
            "NACIONALIDAD",
            "UGE",
            "DOCUMENTACION_EXTRANJEROS",
            "TRAMITES_CONSULARES",
            "REGISTRO_CIVIL",
        ):
            self.assertIn(
                code,
                source,
            )


if __name__ == "__main__":
    unittest.main()
