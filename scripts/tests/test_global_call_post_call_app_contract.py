import ast
import unittest
from pathlib import Path


ROOT = (
    Path(
        __file__
    ).resolve().parents[2]
)

MAIN = (
    ROOT
    / "app"
    / "main.py"
)

COORDINATOR = (
    ROOT
    / "frontend"
    / "components"
    / "global_call_ui_coordinator.py"
)


class GlobalPostCallAppContractTest(
    unittest.TestCase
):
    def test_composition_root_wires_service_callback(
        self,
    ):
        text = MAIN.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "save_global_post_call",
            text,
        )

        self.assertIn(
            ".save_post_call_details(",
            text,
        )

        self.assertIn(
            "on_save_post_call=(",
            text,
        )

        self.assertIn(
            "list_reason_options()",
            text,
        )


    def test_frontend_has_no_repository_or_sql_imports(
        self,
    ):
        tree = ast.parse(
            COORDINATOR.read_text(
                encoding="utf-8"
            )
        )

        forbidden = []

        for node in ast.walk(
            tree
        ):
            modules = []

            if isinstance(
                node,
                ast.Import,
            ):
                modules.extend(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                modules.append(
                    node.module
                    or ""
                )

            for module in modules:
                normalized = (
                    module.lower()
                )

                if any(
                    token in normalized
                    for token in (
                        "sqlite",
                        "repository",
                        "selenium",
                        "whatsapp_connector",
                    )
                ):
                    forbidden.append(
                        module
                    )

        self.assertEqual(
            forbidden,
            [],
        )


if __name__ == "__main__":
    unittest.main()
