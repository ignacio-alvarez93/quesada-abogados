import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppConnector,
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


class _FakeImageBatchConnector:
    def __init__(
        self,
    ):
        self.calls = []
        self.thread_ids = []
        self.result = {
            "scope": "MEDIA_HUB",
            "date_scope": "TODAY",
            "direction_scope": "ALL",
            "media_type_scope": "IMAGE",
            "scanned": 0,
            "matched": 0,
            "downloaded": 0,
            "skipped": [],
            "errors": [],
            "items": [],
        }

    def download_today_images_from_media_hub(
        self,
        *,
        download_dir,
        timeout,
        max_images,
    ):
        self.thread_ids.append(
            threading.get_ident()
        )

        self.calls.append(
            {
                "download_dir":
                    str(
                        Path(
                            download_dir
                        ).resolve()
                    ),

                "timeout":
                    timeout,

                "max_images":
                    max_images,
            }
        )

        return dict(
            self.result
        )


class WhatsAppImageBatchDownloadTests(
    unittest.TestCase
):
    def _runtime(
        self,
        connector,
    ):
        runtime = WhatsAppRuntimeService(
            profile_key="test_profile",
            headless=True,
            communication_service=object(),
        )

        runtime._ensure_ready_impl = (
            lambda **kwargs:
                connector
        )

        return runtime


    def test_runtime_uses_default_watched_folder(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            connector = (
                _FakeImageBatchConnector()
            )

            runtime = self._runtime(
                connector
            )

            watch = {
                "id": 1,
                "name": "Descargas",
                "folder_path": temp,
                "is_active": 1,
            }

            try:
                with patch(
                    "backend.services."
                    "whatsapp_runtime_service."
                    "document_inbox_watch_service."
                    "ensure_default_downloads_watch_folder",
                    return_value=watch,
                ) as ensure_watch:
                    result = (
                        runtime
                        .download_today_images(
                            download_timeout=13,
                            max_images=17,
                        )
                    )

                ensure_watch.assert_called_once_with()

                self.assertEqual(
                    len(
                        connector.calls
                    ),
                    1,
                )

                self.assertEqual(
                    Path(
                        connector.calls[
                            0
                        ][
                            "download_dir"
                        ]
                    ).resolve(),
                    Path(temp).resolve(),
                )

                self.assertEqual(
                    connector.calls[
                        0
                    ][
                        "timeout"
                    ],
                    13,
                )

                self.assertEqual(
                    connector.calls[
                        0
                    ][
                        "max_images"
                    ],
                    17,
                )

                self.assertNotEqual(
                    connector.thread_ids[
                        0
                    ],
                    threading.get_ident(),
                )

                self.assertEqual(
                    result[
                        "scope"
                    ],
                    "MEDIA_HUB",
                )

                self.assertEqual(
                    result[
                        "date_scope"
                    ],
                    "TODAY",
                )

                self.assertEqual(
                    result[
                        "direction_scope"
                    ],
                    "ALL",
                )

                self.assertEqual(
                    result[
                        "media_type_scope"
                    ],
                    "IMAGE",
                )

                self.assertEqual(
                    result[
                        "watch_folder_id"
                    ],
                    1,
                )

                self.assertTrue(
                    result[
                        "document_inbox_watch"
                    ]
                )

            finally:
                runtime.close()


    def test_runtime_accepts_active_selected_folder(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            connector = (
                _FakeImageBatchConnector()
            )

            runtime = self._runtime(
                connector
            )

            watch = {
                "id": 8,
                "name": "WhatsApp",
                "folder_path": temp,
                "is_active": 1,
            }

            try:
                with patch(
                    "backend.services."
                    "whatsapp_runtime_service."
                    "document_inbox_watch_service."
                    "get_watch_folder",
                    return_value=watch,
                ) as get_watch:
                    result = (
                        runtime
                        .download_today_images(
                            watch_folder_id=8,
                        )
                    )

                get_watch.assert_called_once_with(
                    8
                )

                self.assertEqual(
                    result[
                        "watch_folder_id"
                    ],
                    8,
                )

                self.assertEqual(
                    result[
                        "watch_folder_name"
                    ],
                    "WhatsApp",
                )

            finally:
                runtime.close()


    def test_runtime_rejects_inactive_folder(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            connector = (
                _FakeImageBatchConnector()
            )

            runtime = self._runtime(
                connector
            )

            watch = {
                "id": 9,
                "name": "Inactiva",
                "folder_path": temp,
                "is_active": 0,
            }

            try:
                with patch(
                    "backend.services."
                    "whatsapp_runtime_service."
                    "document_inbox_watch_service."
                    "get_watch_folder",
                    return_value=watch,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "inactiva",
                    ):
                        runtime.download_today_images(
                            watch_folder_id=9,
                        )

                self.assertEqual(
                    connector.calls,
                    [],
                )

            finally:
                runtime.close()


    def test_connector_source_freezes_today_image_contract(
        self,
    ):
        source = inspect.getsource(
            WhatsAppConnector
            .download_today_images_from_media_hub
        )

        for token in (
            '"TODAY"',
            '"ALL"',
            '"IMAGE"',
            'tab-media',
            'media-canvas',
            'media-canvas-img',
            'media-url-provider',
            'Imagen de',
            'Video de',
            'GIF de',
            'msg-gif',
            'Ayer',
            'La semana pasada',
            'MEDIA_CANVAS_IMG',
        ):
            self.assertIn(
                token,
                source,
            )

        self.assertNotIn(
            "sent_by_me",
            source,
        )

        self.assertNotIn(
            "TODAY_NOT_SENT_BY_ME",
            source,
        )


    def test_image_viewer_close_is_scoped_to_media_viewer(
        self,
    ):
        source = inspect.getsource(
            WhatsAppConnector
            .download_today_images_from_media_hub
        )

        self.assertIn(
            '[data-testid="media-viewer-modal"]',
            source,
        )

        self.assertIn(
            "viewer.querySelectorAll(",
            source,
        )

        self.assertNotIn(
            """Array.from(
                                    document.querySelectorAll(
                                        'button'
                                        + '[aria-label="Cerrar"]'
                                    )
                                )
                                .find(""",
            source,
        )


    def test_image_detection_does_not_require_media_url_provider(
        self,
    ):
        source = inspect.getsource(
            WhatsAppConnector
            .download_today_images_from_media_hub
        )

        self.assertIn(
            "/Imagen de/i.test(",
            source,
        )

        self.assertIn(
            "&& hasImage",
            source,
        )

        self.assertNotIn(
            "&& hasProvider",
            source,
        )

        self.assertNotIn(
            "|| !provider",
            source,
        )


    def test_image_batch_never_scans_or_imports_inbox(
        self,
    ):
        connector_source = inspect.getsource(
            WhatsAppConnector
            .download_today_images_from_media_hub
        )

        runtime_source = inspect.getsource(
            WhatsAppRuntimeService
            ._download_today_images_impl
        )

        combined = (
            connector_source
            + "\n"
            + runtime_source
        )

        for forbidden in (
            "scan_watch_folder(",
            "scan_active_watch_folders(",
            "import_file_to_inbox(",
        ):
            self.assertNotIn(
                forbidden,
                combined,
            )

        self.assertIn(
            "ensure_default_downloads_watch_folder",
            runtime_source,
        )

        self.assertIn(
            "get_watch_folder",
            runtime_source,
        )


if __name__ == "__main__":
    unittest.main()
