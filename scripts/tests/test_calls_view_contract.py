import ast
import unittest
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[2]

CALLS_VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "calls_view.py"
)

WHATSAPP_VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "communications_view.py"
)

MAIN = (
    ROOT
    / "app"
    / "main.py"
)

SIDEBAR = (
    ROOT
    / "frontend"
    / "layouts"
    / "sidebar.py"
)


class CallsViewContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(
        cls,
    ):
        cls.calls_text = (
            CALLS_VIEW.read_text(
                encoding="utf-8"
            )
        )

        cls.calls_tree = ast.parse(
            cls.calls_text
        )

        cls.whatsapp_text = (
            WHATSAPP_VIEW.read_text(
                encoding="utf-8"
            )
        )

        cls.main_text = (
            MAIN.read_text(
                encoding="utf-8"
            )
        )

        cls.sidebar_text = (
            SIDEBAR.read_text(
                encoding="utf-8"
            )
        )

    def test_calls_is_dedicated_view(
        self,
    ):
        functions = [
            node
            for node in self.calls_tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "calls_view"
            )
        ]

        self.assertEqual(
            len(functions),
            1,
        )

        self.assertIn(
            'elif view_name == "Llamadas":',
            self.main_text,
        )

        self.assertIn(
            "calls_view(",
            self.main_text,
        )

    def test_whatsapp_does_not_host_calls_register(
        self,
    ):
        self.assertNotIn(
            "def build_calls_content(",
            self.whatsapp_text,
        )

        self.assertNotIn(
            "build_communications_mode_switch",
            self.whatsapp_text,
        )

        self.assertNotIn(
            "call_service=None",
            self.whatsapp_text,
        )

    def test_sidebar_calls_entry_is_active(
        self,
    ):
        start = self.sidebar_text.index(
            "KNOWN_ACTIVE_VIEWS"
        )

        block = self.sidebar_text[
            start:
            start + 1000
        ]

        self.assertIn(
            '"Llamadas"',
            block,
        )

    def test_calls_view_uses_governed_read_api(
        self,
    ):
        calls = [
            node
            for node in ast.walk(
                self.calls_tree
            )
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Attribute,
                )
                and node.func.attr
                == "list_call_overviews"
            )
        ]

        self.assertEqual(
            len(calls),
            1,
        )

    def test_calls_view_uses_reusable_ui_components(
        self,
    ):
        for token in (
            "app_table",
            "filter_bar",
            "metric_card",
            "status_chip",
            "select_input",
            "text_input",
            "empty_state",
        ):
            self.assertIn(
                token,
                self.calls_text,
            )

    def test_no_sql_repository_or_browser_coupling(
        self,
    ):
        forbidden_imports = []

        for node in ast.walk(
            self.calls_tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                modules = [
                    alias.name
                    for alias in node.names
                ]

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                modules = [
                    node.module
                    or ""
                ]

            else:
                continue

            for module in modules:
                normalized = (
                    module.lower()
                )

                if (
                    "sqlite" in normalized
                    or "repository" in normalized
                    or "selenium" in normalized
                    or "whatsapp_connector"
                    in normalized
                ):
                    forbidden_imports.append(
                        module
                    )

        self.assertEqual(
            forbidden_imports,
            [],
        )

        for token in (
            "SELECT ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "CREATE TABLE",
            "ALTER TABLE",
            "find_element",
            "browser.evaluate",
        ):
            self.assertNotIn(
                token,
                self.calls_text,
            )


if __name__ == "__main__":
    unittest.main()
