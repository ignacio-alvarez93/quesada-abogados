import ast
import unittest
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "views"
    / "communications_view.py"
)

SOURCE = SOURCE_PATH.read_text(
    encoding="utf-8"
)


def function_source(name):
    tree = ast.parse(
        SOURCE
    )

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
            lines = SOURCE.splitlines()

            return "\n".join(
                lines[
                    node.lineno - 1:
                    node.end_lineno
                ]
            )

    raise AssertionError(
        f"Función no encontrada: {name}"
    )


class CommunicationsDocumentDownloadUiContractTest(
    unittest.TestCase
):
    def test_batch_has_ephemeral_double_click_guard(
        self,
    ):
        self.assertIn(
            '"downloading_today_documents": False',
            SOURCE,
        )

        handler = function_source(
            "_download_today_documents"
        )

        self.assertIn(
            'state.get(\n            "downloading_today_documents"',
            handler,
        )

        self.assertIn(
            '"downloading_today_documents"\n        ] = True',
            handler,
        )

    def test_batch_runs_runtime_outside_flet_ui_thread(
        self,
    ):
        handler = function_source(
            "_download_today_documents"
        )

        self.assertIn(
            ".download_today_documents()",
            handler,
        )

        self.assertIn(
            "_run_background(",
            handler,
        )

        self.assertNotIn(
            "WhatsAppConnector(",
            handler,
        )

        self.assertNotIn(
            "download_today_documents_from_media_hub",
            handler,
        )

    def test_batch_returns_to_flet_loop_with_run_task(
        self,
    ):
        scheduler = function_source(
            "_schedule_today_documents_download_finish"
        )

        self.assertIn(
            'getattr(\n            page,\n            "run_task"',
            scheduler,
        )

        self.assertIn(
            "_finish_today_documents_download_ui",
            scheduler,
        )

    def test_batch_ui_reports_empty_success_and_partial_error(
        self,
    ):
        finish = function_source(
            "_finish_today_documents_download_ui"
        )

        self.assertIn(
            "No hay documentos de hoy.",
            finish,
        )

        self.assertIn(
            '"watch_folder_name"',
            finish,
        )

        self.assertIn(
            '"downloaded"',
            finish,
        )

        self.assertIn(
            '"errors"',
            finish,
        )

        self.assertIn(
            "no se pudieron",
            finish,
        )

    def test_batch_ui_does_not_scan_or_import_inbox_directly(
        self,
    ):
        handler = function_source(
            "_download_today_documents"
        )

        finish = function_source(
            "_finish_today_documents_download_ui"
        )

        batch_source = (
            handler
            + "\n"
            + finish
        )

        self.assertNotIn(
            "scan_watch_folder(",
            batch_source,
        )

        self.assertNotIn(
            "scan_active_watch_folders(",
            batch_source,
        )

        self.assertNotIn(
            "import_file_to_inbox(",
            batch_source,
        )

        tree = ast.parse(
            SOURCE
        )

        string_constants = {
            node.value
            for node in ast.walk(
                tree
            )
            if (
                isinstance(
                    node,
                    ast.Constant,
                )
                and isinstance(
                    node.value,
                    str,
                )
            )
        }

        self.assertIn(
            "Descargar documentos de hoy de todos los chats",
            string_constants,
        )

        self.assertIn(
            "ft.Icons.DOWNLOAD",
            SOURCE,
        )


if __name__ == "__main__":
    unittest.main()
