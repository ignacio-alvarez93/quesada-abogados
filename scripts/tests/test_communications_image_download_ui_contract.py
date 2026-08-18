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


class CommunicationsTodayImagesBatchUiContractTest(
    unittest.TestCase
):
    def test_batch_images_has_double_click_guard(
        self,
    ):
        self.assertIn(
            '"downloading_today_images": False',
            SOURCE,
        )

        handler = function_source(
            "_download_today_images"
        )

        self.assertIn(
            '"downloading_today_images"',
            handler,
        )

        self.assertIn(
            "] = True",
            handler,
        )


    def test_batch_images_runs_runtime_in_background(
        self,
    ):
        handler = function_source(
            "_download_today_images"
        )

        self.assertIn(
            ".download_today_images()",
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


    def test_batch_images_returns_with_run_task(
        self,
    ):
        scheduler = function_source(
            "_schedule_today_images_download_finish"
        )

        self.assertIn(
            '"run_task"',
            scheduler,
        )

        self.assertIn(
            "_finish_today_images_download_ui",
            scheduler,
        )


    def test_batch_images_reports_results(
        self,
    ):
        finish = function_source(
            "_finish_today_images_download_ui"
        )

        self.assertIn(
            "No hay imágenes de hoy.",
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


    def test_batch_images_header_button_contract(
        self,
    ):
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
            "Descargar imágenes de hoy de todos los chats",
            string_constants,
        )

        self.assertIn(
            "_download_today_images",
            SOURCE,
        )

        self.assertIn(
            "icon=ft.Icons.IMAGE",
            SOURCE,
        )


    def test_batch_images_never_scans_or_imports_inbox(
        self,
    ):
        source = (
            function_source(
                "_download_today_images"
            )
            + "\n"
            + function_source(
                "_finish_today_images_download_ui"
            )
        )

        for forbidden in (
            "scan_watch_folder(",
            "scan_active_watch_folders(",
            "import_file_to_inbox(",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )


if __name__ == "__main__":
    unittest.main()
