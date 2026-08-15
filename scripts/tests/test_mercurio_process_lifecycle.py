import ast
from pathlib import Path
import unittest

from backend.services import (
    presentation_assistant_service,
)


SERVICE_PATH = Path(
    "backend/services/presentation_assistant_service.py"
)

RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
)


class FakeProcess:
    def __init__(
        self,
        *,
        returncode=None,
    ):
        self.returncode = returncode
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(
        self,
    ):
        return self.returncode

    def terminate(
        self,
    ):
        self.terminate_calls += 1

        raise AssertionError(
            "terminate() no debe ejecutarse"
        )

    def kill(
        self,
    ):
        self.kill_calls += 1

        raise AssertionError(
            "kill() no debe ejecutarse"
        )


class MercurioProcessLifecycleTest(
    unittest.TestCase
):
    def test_parent_service_never_force_terminates_runner(
        self,
    ):
        tree = ast.parse(
            SERVICE_PATH.read_text(
                encoding="utf-8"
            )
        )

        forbidden = []

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
                in {
                    "terminate",
                    "kill",
                }
            ):
                continue

            forbidden.append(
                (
                    node.func.attr,
                    node.lineno,
                )
            )

        self.assertEqual(
            forbidden,
            [],
        )

    def test_close_presentation_does_not_kill_live_runner(
        self,
    ):
        process = FakeProcess(
            returncode=None
        )

        result = (
            presentation_assistant_service
            .close_presentation(
                {
                    "process": process,
                }
            )
        )

        self.assertFalse(
            result
        )

        self.assertEqual(
            process.terminate_calls,
            0,
        )

        self.assertEqual(
            process.kill_calls,
            0,
        )

    def test_close_presentation_reports_finished_runner(
        self,
    ):
        process = FakeProcess(
            returncode=0
        )

        result = (
            presentation_assistant_service
            .close_presentation(
                {
                    "process": process,
                }
            )
        )

        self.assertTrue(
            result
        )

        self.assertEqual(
            process.terminate_calls,
            0,
        )

    def test_runner_registers_connector_before_browser_start(
        self,
    ):
        tree = ast.parse(
            RUNNER_PATH.read_text(
                encoding="utf-8"
            )
        )

        main = next(
            node
            for node in ast.walk(
                tree
            )
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "main"
            )
        )

        lifecycle_assignments = []

        start_calls = []

        for node in ast.walk(
            main
        ):
            if isinstance(
                node,
                ast.Assign,
            ):
                for target in node.targets:
                    if not isinstance(
                        target,
                        ast.Subscript,
                    ):
                        continue

                    if not (
                        isinstance(
                            target.value,
                            ast.Name,
                        )
                        and target.value.id
                        == "lifecycle"
                    ):
                        continue

                    lifecycle_assignments.append(
                        node.lineno
                    )

            if not isinstance(
                node,
                ast.Call,
            ):
                continue

            function = node.func

            if (
                isinstance(
                    function,
                    ast.Attribute,
                )
                and function.attr
                == "start_browser"
                and isinstance(
                    function.value,
                    ast.Name,
                )
                and function.value.id
                == "connector"
            ):
                start_calls.append(
                    node.lineno
                )

        self.assertTrue(
            lifecycle_assignments
        )

        self.assertEqual(
            len(
                start_calls
            ),
            1,
        )

        self.assertLess(
            min(
                lifecycle_assignments
            ),
            start_calls[
                0
            ],
        )

    def test_entrypoint_has_finally_governed_cleanup(
        self,
    ):
        tree = ast.parse(
            RUNNER_PATH.read_text(
                encoding="utf-8"
            )
        )

        module_if = None

        for node in tree.body:
            if not isinstance(
                node,
                ast.If,
            ):
                continue

            if "__name__" not in ast.dump(
                node.test
            ):
                continue

            module_if = node
            break

        self.assertIsNotNone(
            module_if
        )

        finally_blocks = []

        for node in ast.walk(
            module_if
        ):
            if (
                isinstance(
                    node,
                    ast.Try,
                )
                and node.finalbody
            ):
                finally_blocks.append(
                    node
                )

        self.assertEqual(
            len(
                finally_blocks
            ),
            1,
        )

        close_calls = []

        for node in ast.walk(
            finally_blocks[
                0
            ]
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
                == "close_browser"
            ):
                continue

            close_calls.append(
                node.lineno
            )

        self.assertEqual(
            len(
                close_calls
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
