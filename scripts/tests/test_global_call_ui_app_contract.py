import ast
import unittest
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[2]

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


class GlobalCallUIAppContractTest(
    unittest.TestCase
):
    def test_app_owns_global_coordinator(
        self,
    ):
        text = MAIN.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "GlobalCallUICoordinator(",
            text,
        )

        self.assertIn(
            "on_whatsapp_call_watch_change",
            text,
        )

        self.assertIn(
            "QUESADA_CALL_UI_SMOKE",
            text,
        )


    def test_frontend_coordinator_has_no_infrastructure_imports(
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
            module = None

            if isinstance(
                node,
                ast.ImportFrom,
            ):
                module = (
                    node.module
                    or ""
                )

            elif isinstance(
                node,
                ast.Import,
            ):
                for alias in node.names:
                    value = (
                        alias.name.lower()
                    )

                    if any(
                        token in value
                        for token in (
                            "sqlite",
                            "repository",
                            "selenium",
                            "whatsapp_connector",
                        )
                    ):
                        forbidden.append(
                            alias.name
                        )

                continue

            if module:
                value = module.lower()

                if any(
                    token in value
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
