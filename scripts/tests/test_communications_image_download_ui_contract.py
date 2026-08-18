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


class CommunicationsImageDownloadUiContractTest(
    unittest.TestCase
):
    def test_image_has_ephemeral_double_click_guard(
        self,
    ):
        self.assertIn(
            '"downloading_image_provider_ids": set()',
            SOURCE,
        )

        handler = function_source(
            "_image_download_handler"
        )

        self.assertIn(
            '"downloading_image_provider_ids"',
            handler,
        )

        self.assertIn(
            "active_downloads.add(",
            handler,
        )

        self.assertIn(
            "active_downloads.discard(",
            handler,
        )


    def test_image_download_runs_outside_flet_ui_thread(
        self,
    ):
        handler = function_source(
            "_image_download_handler"
        )

        self.assertIn(
            ".download_image(",
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


    def test_image_download_returns_with_page_run_task(
        self,
    ):
        scheduler = function_source(
            "_schedule_image_download_finish"
        )

        self.assertIn(
            '"run_task"',
            scheduler,
        )

        self.assertIn(
            "_finish_image_download_ui",
            scheduler,
        )


    def test_image_finish_reports_watched_folder(
        self,
    ):
        finish = function_source(
            "_finish_image_download_ui"
        )

        self.assertIn(
            '"watch_folder_name"',
            finish,
        )

        self.assertIn(
            '"filename"',
            finish,
        )

        self.assertIn(
            "descargada en",
            finish,
        )


    def test_image_bubble_uses_download_contract(
        self,
    ):
        bubble = function_source(
            "_build_message_bubble"
        )

        self.assertIn(
            'message_type == "IMAGE"',
            bubble,
        )

        self.assertIn(
            "_image_download_handler(",
            bubble,
        )

        self.assertIn(
            "Descargar imagen en carpeta",
            bubble,
        )

        self.assertIn(
            "vigilada por Bandeja Documental",
            bubble,
        )

        self.assertIn(
            "ft.Icons.IMAGE",
            bubble,
        )


    def test_image_ui_never_imports_or_scans_inbox_directly(
        self,
    ):
        source = (
            function_source(
                "_image_download_handler"
            )
            + "\n"
            + function_source(
                "_finish_image_download_ui"
            )
        )

        self.assertNotIn(
            "scan_watch_folder(",
            source,
        )

        self.assertNotIn(
            "scan_active_watch_folders(",
            source,
        )

        self.assertNotIn(
            "import_file_to_inbox(",
            source,
        )


if __name__ == "__main__":
    unittest.main()
