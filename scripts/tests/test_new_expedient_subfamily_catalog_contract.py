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


class NewExpedientSubfamilyCatalogContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = VIEW.read_text(
            encoding="utf-8"
        )
        cls.tree = ast.parse(cls.source)

    def function_source(self, name):
        node = next(
            item
            for item in ast.walk(self.tree)
            if isinstance(
                item,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and item.name == name
        )

        return ast.get_source_segment(
            self.source,
            node,
        )

    def test_subfamily_catalog_exists(self):
        self.function_source(
            "open_new_expedient_subfamily_catalog"
        )

    def test_groups_come_from_active_types(self):
        source = self.function_source(
            "_active_type_groups_for_family"
        )

        self.assertIn(
            "_active_types_for_family",
            source,
        )

        self.assertIn(
            "_expedient_type_catalog_group",
            source,
        )

    def test_subfamily_card_opens_filtered_catalog(
        self,
    ):
        source = self.function_source(
            "_build_new_expedient_subfamily_card"
        )

        self.assertIn(
            "open_new_expedient_type_catalog",
            source,
        )

        self.assertIn(
            "group_order=selected_order",
            source,
        )

    def test_immigration_routes_to_subfamilies(
        self,
    ):
        source = self.function_source(
            "open_new_for_family"
        )

        self.assertIn(
            '"EXTRANJERIA"',
            source,
        )

        self.assertIn(
            "open_new_expedient_subfamily_catalog",
            source,
        )

        parsed = ast.parse(
            source
        )

        routed = False

        for node in ast.walk(parsed):
            if not isinstance(node, ast.If):
                continue

            condition = (
                ast.get_source_segment(
                    source,
                    node.test,
                )
                or ""
            )

            body = "\n".join(
                (
                    ast.get_source_segment(
                        source,
                        statement,
                    )
                    or ""
                )
                for statement in node.body
            )

            if (
                '"EXTRANJERIA"' in condition
                and
                "open_new_expedient_subfamily_catalog"
                in body
            ):
                routed = True
                break

        self.assertTrue(
            routed,
            (
                "Extranjería debe continuar "
                "enrutándose al catálogo "
                "de subfamilias"
            ),
        )

    def test_type_catalog_accepts_group_filter(
        self,
    ):
        source = self.function_source(
            "open_new_expedient_type_catalog"
        )

        self.assertIn(
            "group_order=None",
            source,
        )

        self.assertIn(
            "_expedient_type_catalog_group",
            source,
        )

        self.assertIn(
            "Volver a subfamilias",
            source,
        )

    def test_subfamilies_use_vertical_layout(
        self,
    ):
        family_source = self.function_source(
            "_build_new_expedient_family_card"
        )

        card_source = self.function_source(
            "_build_new_expedient_subfamily_card"
        )

        catalog_source = self.function_source(
            "open_new_expedient_subfamily_catalog"
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
            "controls=cards",
            catalog_source,
        )

        self.assertNotIn(
            "cards[index:index + 2]",
            catalog_source,
        )


    def test_subfamily_catalog_reuses_dialog(
        self,
    ):
        source = self.function_source(
            "open_new_expedient_subfamily_catalog"
        )

        self.assertIn(
            "expediente_dialog.content",
            source,
        )

        self.assertIn(
            "expediente_dialog.open = True",
            source,
        )

    def test_subfamilies_are_visual_only(self):
        self.assertNotIn(
            "subfamilia_id",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
