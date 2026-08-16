import ast
from pathlib import Path
import unittest


PANEL_PATH = Path(
    "frontend/components/dehu_inbox_panel.py"
)

NOTIFICATIONS_PATH = Path(
    "frontend/views/notifications_view.py"
)

MAIN_PATH = Path(
    "app/main.py"
)


def parse(
    path,
):
    return ast.parse(
        path.read_text(
            encoding="utf-8"
        )
    )


def function_node(
    tree,
    name,
):
    for node in ast.walk(
        tree
    ):
        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == name
        ):
            return node

    raise AssertionError(
        f"No se encontró función {name}"
    )


def arg_names(
    function,
):
    return [
        arg.arg
        for arg in (
            function.args.args
            + function.args.kwonlyargs
        )
    ]


class DehuFletRuntimeContractTest(
    unittest.TestCase
):
    def test_panel_accepts_open_portal_callback(
        self,
    ):
        tree = parse(
            PANEL_PATH
        )

        function = function_node(
            tree,
            "build_dehu_inbox_panel",
        )

        self.assertIn(
            "on_open_portal",
            arg_names(
                function
            ),
        )

    def test_panel_exposes_safe_root_portal_action(
        self,
    ):
        tree = parse(
            PANEL_PATH
        )

        function = function_node(
            tree,
            "open_portal_root",
        )

        calls = []

        for node in ast.walk(
            function
        ):
            if not (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "request_portal_open"
            ):
                continue

            calls.append(
                node
            )

        self.assertEqual(
            len(
                calls
            ),
            1,
        )

        self.assertEqual(
            len(
                calls[0].args
            ),
            1,
        )

        self.assertIsInstance(
            calls[0].args[0],
            ast.Constant,
        )

        self.assertIsNone(
            calls[0].args[0].value
        )

        text = (
            PANEL_PATH.read_text(
                encoding="utf-8"
            )
        )

        self.assertIn(
            '"Abrir portal DEHú"',
            text,
        )

    def test_panel_no_longer_launches_system_browser(
        self,
    ):
        tree = parse(
            PANEL_PATH
        )

        hits = []

        for node in ast.walk(
            tree
        ):
            if not (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Attribute,
                )
                and node.func.attr
                == "launch_url"
            ):
                continue

            hits.append(
                node.lineno
            )

        self.assertEqual(
            hits,
            [],
        )

    def test_notifications_accepts_dehu_callback(
        self,
    ):
        tree = parse(
            NOTIFICATIONS_PATH
        )

        function = function_node(
            tree,
            "notifications_view",
        )

        self.assertIn(
            "on_open_dehu_portal",
            arg_names(
                function
            ),
        )

    def test_notifications_panel_receives_bridge_callback(
        self,
    ):
        text = (
            NOTIFICATIONS_PATH
            .read_text(
                encoding="utf-8"
            )
        )

        self.assertIn(
            "on_open_portal=(",
            text,
        )

        self.assertIn(
            "open_dehu_portal",
            text,
        )

        self.assertIn(
            "start_background_worker(",
            text,
        )

    def test_main_owns_single_dehu_runtime(
        self,
    ):
        tree = parse(
            MAIN_PATH
        )

        constructor_calls = []

        for node in ast.walk(
            tree
        ):
            if not (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "DehuRuntimeService"
            ):
                continue

            constructor_calls.append(
                node.lineno
            )

        self.assertEqual(
            len(
                constructor_calls
            ),
            1,
        )

    def test_main_injects_runtime_into_notifications(
        self,
    ):
        text = (
            MAIN_PATH.read_text(
                encoding="utf-8"
            )
        )

        self.assertIn(
            "on_open_dehu_portal=(",
            text,
        )

        self.assertIn(
            "dehu_runtime.open_portal(",
            text,
        )

    def test_page_close_attempts_both_runtimes(
        self,
    ):
        tree = parse(
            MAIN_PATH
        )

        function = function_node(
            tree,
            "on_page_close",
        )

        called = []

        for node in ast.walk(
            function
        ):
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Name,
                )
            ):
                called.append(
                    node.func.id
                )

        self.assertIn(
            "close_whatsapp_session_services",
            called,
        )

        self.assertIn(
            "close_dehu_session_services",
            called,
        )

    def test_frontend_has_no_browser_infrastructure_imports(
        self,
    ):
        for path in (
            PANEL_PATH,
            NOTIFICATIONS_PATH,
        ):
            tree = parse(
                path
            )

            imported = []

            for node in ast.walk(
                tree
            ):
                if isinstance(
                    node,
                    ast.Import,
                ):
                    imported.extend(
                        alias.name
                        for alias in node.names
                    )

                elif isinstance(
                    node,
                    ast.ImportFrom,
                ):
                    imported.append(
                        node.module
                        or ""
                    )

            forbidden = [
                name
                for name in imported
                if (
                    "seleniumbase"
                    in name.lower()
                    or "browser_session"
                    in name.lower()
                    or "dehu_runtime_service"
                    in name.lower()
                )
            ]

            self.assertEqual(
                forbidden,
                [],
                msg=(
                    f"Infraestructura navegador "
                    f"filtrada a frontend: {path}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
