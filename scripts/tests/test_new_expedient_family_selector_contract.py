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


class NewExpedientFamilySelectorContractTest(
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

    def test_has_family_selector_dialog(self):
        self.assertIn(
            "new_expedient_family_dialog",
            self.source,
        )

        self.assertIn(
            "page.overlay.append",
            self.source,
        )

    def test_new_action_opens_family_selector(self):
        open_new = next(
            node
            for node in ast.walk(self.tree)
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name == "open_new"
            )
        )

        segment = ast.get_source_segment(
            self.source,
            open_new,
        )

        self.assertIn(
            "new_expedient_family_dialog",
            segment,
        )

        self.assertNotIn(
            "expediente_dialog.open = True",
            segment,
        )

    def test_opens_form_for_selected_family(self):
        self.assertIn(
            "open_new_for_family",
            self.function_names,
        )

        self.assertIn(
            "familia_expediente.set_value",
            self.source,
        )

        self.assertIn(
            "refresh_tipo_options_for_familia",
            self.source,
        )

    def test_family_is_selected_before_form(self):
        function = next(
            node
            for node in ast.walk(self.tree)
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "open_new_for_family"
            )
        )

        segment = ast.get_source_segment(
            self.source,
            function,
        )

        family_position = segment.index(
            "familia_expediente.set_value"
        )

        dialog_position = segment.index(
            "expediente_dialog.open = True"
        )

        self.assertLess(
            family_position,
            dialog_position,
        )

    def test_preserves_client_navigation(self):
        self.assertIn(
            "pending_new_expedient_client_id",
            self.source,
        )

        self.assertIn(
            "cliente_id=cliente_id",
            self.source,
        )

    def test_has_family_cards(self):
        self.assertIn(
            "_build_new_expedient_family_card",
            self.function_names,
        )

        self.assertIn(
            "_family_type_count",
            self.function_names,
        )

        self.assertIn(
            "_family_selector_style",
            self.function_names,
        )

    def test_uses_active_catalog_families(self):
        self.assertIn(
            "active_families",
            self.source,
        )

        self.assertIn(
            "for family in (familias or [])",
            self.source,
        )

    def test_stores_selected_family_context(self):
        for identifier in (
            "new_expedient_family_id",
            "new_expedient_family_code",
            "new_expedient_family_name",
        ):
            self.assertIn(
                identifier,
                self.source,
            )


if __name__ == "__main__":
    unittest.main()
