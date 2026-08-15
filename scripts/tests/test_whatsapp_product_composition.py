import ast
from pathlib import Path
import unittest


APP_MAIN_PATH = Path(
    "app/main.py"
)

VIEW_PATH = Path(
    "frontend/views/communications_view.py"
)


class WhatsAppProductCompositionTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(
        cls,
    ):
        cls.app_source = (
            APP_MAIN_PATH.read_text(
                encoding="utf-8"
            )
        )

        cls.view_source = (
            VIEW_PATH.read_text(
                encoding="utf-8"
            )
        )

    def test_product_root_builds_shared_communication_repository(
        self,
    ):
        self.assertIn(
            "communication_repository = (",
            self.app_source,
        )

        self.assertIn(
            "SQLiteCommunicationRepository()",
            self.app_source,
        )

    def test_message_and_call_services_share_repository(
        self,
    ):
        self.assertIn(
            """CommunicationService(
            repository=(
                communication_repository
            )""",
            self.app_source,
        )

        self.assertIn(
            """CommunicationCallService(
            repository=(
                communication_repository
            )""",
            self.app_source,
        )

    def test_runtime_receives_both_application_services(
        self,
    ):
        self.assertIn(
            """WhatsAppRuntimeService(
        communication_service=(
            communication_service
        ),
        call_service=(
            communication_call_service
        ),""",
            self.app_source,
        )

    def test_communications_view_receives_same_message_service(
        self,
    ):
        self.assertIn(
            """content = communications_view(
                page,
                service=(
                    communication_service
                ),
                whatsapp_runtime=(
                    whatsapp_runtime
                ),""",
            self.app_source,
        )

    def test_call_watch_starts_only_after_successful_login(
        self,
    ):
        login_pos = self.app_source.index(
            "def on_login_success(user):"
        )

        watch_start_pos = self.app_source.index(
            "start_whatsapp_session_services()",
            login_pos,
        )

        initial_start_pos = self.app_source.index(
            "def start():"
        )

        self.assertGreater(
            watch_start_pos,
            login_pos,
        )

        # La pantalla de login no arranca WhatsApp.
        initial_start_block = (
            self.app_source[
                initial_start_pos:
            ]
        )

        initial_start_block = (
            initial_start_block.split(
                "page.add(main_container)",
                1,
            )[0]
        )

        self.assertNotIn(
            "start_whatsapp_session_services()",
            initial_start_block,
        )


    def test_authenticated_ui_is_rendered_before_call_watch_start(
        self,
    ):
        start = self.app_source.index(
            "def on_login_success(user):"
        )

        end = self.app_source.index(
            "    def start():",
            start,
        )

        login_block = (
            self.app_source[
                start:end
            ]
        )

        self.assertLess(
            login_block.index(
                'navigate("Clientes")'
            ),
            login_block.index(
                "start_whatsapp_session_services()"
            ),
        )


    def test_page_close_closes_whatsapp_runtime(
        self,
    ):
        self.assertNotIn(
            "import atexit",
            self.app_source,
        )

        self.assertNotIn(
            "atexit.register(",
            self.app_source,
        )

        self.assertIn(
            "def on_page_close(",
            self.app_source,
        )

        self.assertIn(
            "page.on_close = on_page_close",
            self.app_source,
        )

        self.assertIn(
            "close_whatsapp_session_services()",
            self.app_source,
        )

        self.assertIn(
            "whatsapp_runtime.close()",
            self.app_source,
        )


    def test_close_latch_tracks_runtime_ownership(
        self,
    ):
        """
        El composition root no puede declarar cerrado el
        runtime antes de conocer el resultado del shutdown.

        El latch definitivo depende de que el Runtime ya no
        conserve connector.
        """

        tree = ast.parse(
            self.app_source
        )

        helper = None

        for node in ast.walk(
            tree
        ):
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "close_whatsapp_session_services"
            ):
                helper = node
                break

        self.assertIsNotNone(
            helper
        )

        close_calls = []

        for node in ast.walk(
            helper
        ):
            if not isinstance(
                node,
                ast.Call,
            ):
                continue

            function = node.func

            if not isinstance(
                function,
                ast.Attribute,
            ):
                continue

            if (
                function.attr == "close"
                and isinstance(
                    function.value,
                    ast.Name,
                )
                and function.value.id
                == "whatsapp_runtime"
            ):
                close_calls.append(
                    node
                )

        self.assertEqual(
            len(
                close_calls
            ),
            1,
        )

        close_line = (
            close_calls[0].lineno
        )

        def is_closed_flag_target(
            target,
        ):
            return (
                isinstance(
                    target,
                    ast.Subscript,
                )
                and isinstance(
                    target.value,
                    ast.Name,
                )
                and target.value.id
                == "whatsapp_runtime_closed"
                and isinstance(
                    target.slice,
                    ast.Constant,
                )
                and target.slice.value
                == "value"
            )

        assignments = []

        for node in ast.walk(
            helper
        ):
            if not isinstance(
                node,
                ast.Assign,
            ):
                continue

            if any(
                is_closed_flag_target(
                    target
                )
                for target in node.targets
            ):
                assignments.append(
                    node
                )

        self.assertGreaterEqual(
            len(
                assignments
            ),
            2,
        )

        # Nunca puede existir un latch=True previo al
        # shutdown físico.
        self.assertFalse(
            any(
                assignment.lineno
                < close_line
                for assignment
                in assignments
            )
        )

        ownership_assignments = []

        for assignment in assignments:
            value = assignment.value

            if not isinstance(
                value,
                ast.Compare,
            ):
                continue

            if (
                len(
                    value.ops
                )
                != 1
                or not isinstance(
                    value.ops[0],
                    ast.Is,
                )
            ):
                continue

            left = value.left

            if not (
                isinstance(
                    left,
                    ast.Attribute,
                )
                and left.attr
                == "connector"
                and isinstance(
                    left.value,
                    ast.Name,
                )
                and left.value.id
                == "whatsapp_runtime"
            ):
                continue

            if (
                len(
                    value.comparators
                )
                == 1
                and isinstance(
                    value.comparators[0],
                    ast.Constant,
                )
                and value.comparators[0].value
                is None
            ):
                ownership_assignments.append(
                    assignment
                )

        self.assertEqual(
            len(
                ownership_assignments
            ),
            1,
        )

        self.assertGreater(
            ownership_assignments[
                0
            ].lineno,
            close_line,
        )

        # El camino excepcional debe dejar explícitamente
        # abierto el latch para permitir retry.
        exception_resets = []

        for handler in [
            node
            for node in ast.walk(
                helper
            )
            if isinstance(
                node,
                ast.ExceptHandler,
            )
        ]:
            for node in ast.walk(
                handler
            ):
                if not isinstance(
                    node,
                    ast.Assign,
                ):
                    continue

                if not any(
                    is_closed_flag_target(
                        target
                    )
                    for target
                    in node.targets
                ):
                    continue

                if (
                    isinstance(
                        node.value,
                        ast.Constant,
                    )
                    and node.value.value
                    is False
                ):
                    exception_resets.append(
                        node
                    )

        self.assertEqual(
            len(
                exception_resets
            ),
            1,
        )


    def test_page_disconnect_does_not_close_runtime_implicitly(
        self,
    ):
        self.assertNotIn(
            "page.on_disconnect =",
            self.app_source,
        )


    def test_frontend_still_does_not_import_sqlite_repository(
        self,
    ):
        self.assertNotIn(
            "SQLiteCommunicationRepository",
            self.view_source,
        )

        self.assertNotIn(
            "sqlite3",
            self.view_source,
        )


if __name__ == "__main__":
    unittest.main()
