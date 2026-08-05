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


class NewExpedientTypeCatalogContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = VIEW.read_text(
            encoding="utf-8"
        )

        cls.tree = ast.parse(cls.source)

        cls.functions = {
            node.name: node
            for node in ast.walk(cls.tree)
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
        }

    def function_source(self, name):
        node = self.functions[name]

        return ast.get_source_segment(
            self.source,
            node,
        )

    def test_catalog_reuses_expedient_dialog(self):
        catalog_source = self.function_source(
            "open_new_expedient_type_catalog"
        )

        selection_source = self.function_source(
            "_open_new_expedient_form_after_type"
        )

        self.assertIn(
            "expediente_dialog.content",
            catalog_source,
        )

        self.assertIn(
            "expediente_dialog.content",
            selection_source,
        )

        self.assertNotIn(
            "new_expedient_type_dialog",
            self.source,
        )

    def test_catalog_open_function_exists(self):
        self.assertIn(
            "open_new_expedient_type_catalog",
            self.functions,
        )

    def test_templates_support_unsaved_expedient(
        self,
    ):
        source = self.function_source(
            "build_expedient_templates_content"
        )

        guard_position = source.index(
            "if not expediente_id:"
        )

        conversion_position = source.index(
            "expediente_id = int(expediente_id)"
        )

        self.assertLess(
            guard_position,
            conversion_position,
        )

        self.assertIn(
            "Guarda primero el expediente",
            source,
        )

    def test_types_use_vertical_layout(
        self,
    ):
        family_source = self.function_source(
            "_build_new_expedient_family_card"
        )

        card_source = self.function_source(
            "_build_new_expedient_type_card"
        )

        catalog_source = self.function_source(
            "open_new_expedient_type_catalog"
        )

        def geometry(function_source):
            tree = ast.parse(
                function_source
            )

            function = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
            )

            container = next(
                statement.value
                for statement in function.body
                if isinstance(statement, ast.Return)
                and isinstance(statement.value, ast.Call)
                and isinstance(
                    statement.value.func,
                    ast.Attribute,
                )
                and statement.value.func.attr
                == "Container"
            )

            return {
                keyword.arg: ast.dump(
                    keyword.value,
                    include_attributes=False,
                )
                for keyword in container.keywords
                if keyword.arg in {
                    "width",
                    "height",
                    "padding",
                    "border_radius",
                }
            }

        self.assertEqual(
            geometry(card_source),
            geometry(family_source),
        )

        self.assertIn(
            "content=ft.Row(",
            card_source,
        )

        self.assertIn(
            "for expedient_type in filtered_types",
            catalog_source,
        )

        self.assertNotIn(
            "filtered_types[index:index + 2]",
            catalog_source,
        )


    def test_catalog_and_form_use_same_dialog(
        self,
    ):
        catalog_source = self.function_source(
            "open_new_expedient_type_catalog"
        )

        selection_source = self.function_source(
            "_open_new_expedient_form_after_type"
        )

        self.assertIn(
            "expediente_dialog.open = True",
            catalog_source,
        )

        self.assertIn(
            "expediente_dialog.open = True",
            selection_source,
        )

        self.assertNotIn(
            "page.run_task(",
            selection_source,
        )

        self.assertNotIn(
            "_show_new_expedient_dialog_deferred",
            self.source,
        )

    def test_type_card_builder_exists(self):
        self.assertIn(
            "_build_new_expedient_type_card",
            self.functions,
        )

    def test_catalog_groups_exist(self):
        source = self.function_source(
            "_expedient_type_catalog_group"
        )

        expected = (
            "Situaciones de estancia",
            "Residencia temporal",
            "Familiares de",
            "Circunstancias",
            "Régimen comunitario",
            "larga duración",
            "Modificaciones",
        )

        for label in expected:
            self.assertIn(
                label,
                source,
            )

    def test_only_active_family_types_are_loaded(self):
        source = self.function_source(
            "_active_types_for_family"
        )

        self.assertIn(
            "active_only=True",
            source,
        )

        self.assertIn(
            "familia_id=family_id",
            source,
        )

    def test_family_selection_opens_catalog(self):
        source = self.function_source(
            "open_new_for_family"
        )

        self.assertIn(
            "open_new_expedient_type_catalog",
            source,
        )

        self.assertNotIn(
            "expediente_dialog.open = True",
            source,
        )

    def test_type_selection_sets_state(self):
        source = self.function_source(
            "_open_new_expedient_form_after_type"
        )

        for key in (
            "new_expedient_type_id",
            "new_expedient_type_code",
            "new_expedient_type_name",
        ):
            self.assertIn(
                key,
                source,
            )

    def test_type_selection_refreshes_subtypes(self):
        source = self.function_source(
            "_open_new_expedient_form_after_type"
        )

        self.assertIn(
            "refresh_subtipo_options_for_tipo",
            source,
        )






    def test_type_cards_use_supported_container_height(
        self,
    ):
        source = self.function_source(
            "_build_new_expedient_type_card"
        )

        self.assertNotIn(
            "min_height=",
            source,
        )



    def test_empty_search_result_uses_supported_signature(
        self,
    ):
        source = self.function_source(
            "_build_expedient_type_catalog_content"
        )

        tree = ast.parse(source)

        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "empty_state"
        ]

        self.assertTrue(calls)

        for call in calls:
            self.assertEqual(
                len(call.args),
                1,
            )

    def test_catalog_has_search(self):
        source = self.function_source(
            "open_new_expedient_type_catalog"
        )

        self.assertIn(
            "Buscar por nombre, código o descripción",
            source,
        )

        self.assertIn(
            "search_control.on_change",
            source,
        )

    def test_legacy_types_are_not_hardcoded(self):
        source = self.function_source(
            "_build_expedient_type_catalog_content"
        )

        self.assertNotIn(
            "REGULARIZACION_MASIVA_TRANS_20",
            source,
        )

        self.assertNotIn(
            "REGULARIZACION_MASIVA_TRANS_21",
            source,
        )


if __name__ == "__main__":
    unittest.main()
