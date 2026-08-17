import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppActiveChatFingerprint,
    WhatsAppConnector,
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


class _FakePage:
    def __init__(self):
        self.commands = []

    def send(self, command):
        self.commands.append(command)
        return command


class _FakeLoop:
    def __init__(self):
        self.calls = []

    def run_until_complete(self, value):
        self.calls.append(value)
        return value


class _FakeDownloadBrowser:
    def __init__(
        self,
        *,
        target_dir,
        open_result=None,
    ):
        self.target_dir = Path(target_dir)

        self.open_result = (
            open_result
            or {
                "opened": True,
                "reason": None,
                "filename": "documento.pdf",
            }
        )

        self.page = _FakePage()
        self.loop = _FakeLoop()

        self.download_clicks = 0
        self.close_clicks = 0

    def evaluate(self, script):
        source = str(script or "")

        if "MESSAGE_NOT_VISIBLE" in source:
            return dict(self.open_result)

        if (
            'aria-label="Descargar"'
            in source
            and "Boolean(" in source
        ):
            return True

        if (
            'aria-label="Descargar"'
            in source
            and "button.click()" in source
        ):
            self.download_clicks += 1

            # Chrome puede exponer primero un temporal.
            (
                self.target_dir
                / "descarga.tmp"
            ).write_bytes(
                b"temporary"
            )

            (
                self.target_dir
                / "documento.pdf"
            ).write_bytes(
                b"final-document"
            )

            return True

        if (
            'aria-label="Cerrar"'
            in source
        ):
            self.close_clicks += 1
            return True

        return {}


class _RuntimeConnector:
    instances = []

    def __init__(
        self,
        *,
        profile_key,
        headless,
    ):
        self.profile_key = profile_key
        self.headless = headless
        self.browser = object()

        self.download_calls = []
        self.download_thread_ids = []

        self.__class__.instances.append(
            self
        )

    def download_visible_document(
        self,
        provider_message_id,
        *,
        download_dir,
        timeout,
    ):
        self.download_thread_ids.append(
            threading.get_ident()
        )

        self.download_calls.append(
            {
                "provider_message_id":
                    provider_message_id,
                "download_dir":
                    str(
                        Path(
                            download_dir
                        ).resolve()
                    ),
                "timeout":
                    timeout,
            }
        )

        return {
            "provider_message_id":
                provider_message_id,
            "expected_filename":
                "documento.pdf",
            "filename":
                "documento.pdf",
            "file_path":
                str(
                    Path(
                        download_dir
                    )
                    / "documento.pdf"
                ),
            "size_bytes":
                123,
        }

    def close(self):
        self.browser = None
        return True


class WhatsAppDocumentDownloadTest(
    unittest.TestCase
):
    def _connector(
        self,
        *,
        target_dir,
        open_result=None,
    ):
        connector = WhatsAppConnector()

        browser = _FakeDownloadBrowser(
            target_dir=target_dir,
            open_result=open_result,
        )

        connector.browser = browser

        connector.get_active_chat_fingerprint = (
            lambda:
                WhatsAppActiveChatFingerprint(
                    chat_open=True,
                    active_display_name=(
                        "Cliente prueba"
                    ),
                    active_identity=(
                        "cliente prueba"
                    ),
                    visible_message_count=5,
                    last_provider_message_id=(
                        "MSG-5"
                    ),
                )
        )

        return connector, browser

    def _runtime(self):
        _RuntimeConnector.instances = []

        runtime = WhatsAppRuntimeService(
            profile_key="test_profile",
            headless=True,
            communication_service=object(),
            connector_factory=(
                _RuntimeConnector
            ),
        )

        runtime._prepare_verified_outbound_impl = (
            lambda **kwargs:
                SimpleNamespace(
                    id=7,
                    client_id=30,
                )
        )

        return runtime

    def test_connector_rejects_empty_provider_id(
        self,
    ):
        connector = WhatsAppConnector()
        connector.browser = object()

        with self.assertRaisesRegex(
            ValueError,
            "provider_message_id",
        ):
            connector.download_visible_document(
                "",
                download_dir=".",
            )

    def test_connector_rejects_failed_and_loading_documents(
        self,
    ):
        for reason in (
            "DOCUMENT_FAILED",
            "DOCUMENT_LOADING",
        ):
            with self.subTest(
                reason=reason
            ):
                with tempfile.TemporaryDirectory() as temp:
                    connector, _ = (
                        self._connector(
                            target_dir=temp,
                            open_result={
                                "opened": False,
                                "reason": reason,
                            },
                        )
                    )

                    with patch(
                        "backend.automation.connectors."
                        "whatsapp_connector."
                        "cdp_browser."
                        "set_download_behavior",
                        side_effect=(
                            lambda **kwargs:
                                dict(kwargs)
                        ),
                    ):
                        with self.assertRaisesRegex(
                            RuntimeError,
                            reason,
                        ):
                            connector.download_visible_document(
                                "MSG-DOC-1",
                                download_dir=temp,
                                timeout=1,
                            )

    def test_connector_downloads_final_file_and_restores_cdp_behavior(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            connector, browser = (
                self._connector(
                    target_dir=temp,
                )
            )

            calls = []

            def fake_behavior(**kwargs):
                calls.append(
                    dict(kwargs)
                )
                return dict(kwargs)

            with patch(
                "backend.automation.connectors."
                "whatsapp_connector."
                "cdp_browser."
                "set_download_behavior",
                side_effect=fake_behavior,
            ):
                result = (
                    connector
                    .download_visible_document(
                        "MSG-DOC-2",
                        download_dir=temp,
                        timeout=1,
                    )
                )

            self.assertEqual(
                result["filename"],
                "documento.pdf",
            )

            self.assertEqual(
                Path(
                    result["file_path"]
                ).suffix.lower(),
                ".pdf",
            )

            self.assertNotEqual(
                Path(
                    result["file_path"]
                ).suffix.lower(),
                ".tmp",
            )

            self.assertEqual(
                browser.download_clicks,
                1,
            )

            self.assertGreaterEqual(
                browser.close_clicks,
                1,
            )

            self.assertEqual(
                calls[0]["behavior"],
                "allow",
            )

            self.assertEqual(
                Path(
                    calls[0]["download_path"]
                ).resolve(),
                Path(temp).resolve(),
            )

            self.assertTrue(
                calls[0]["events_enabled"]
            )

            self.assertEqual(
                calls[-1]["behavior"],
                "default",
            )

    def test_runtime_uses_default_watched_downloads_folder(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            runtime = self._runtime()

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
                ):
                    result = (
                        runtime.download_document(
                            thread_id=7,
                            provider_message_id=(
                                "MSG-DOC-3"
                            ),
                            download_timeout=11,
                        )
                    )

                connector = (
                    _RuntimeConnector
                    .instances[0]
                )

                self.assertEqual(
                    len(
                        connector.download_calls
                    ),
                    1,
                )

                self.assertEqual(
                    Path(
                        connector.download_calls[
                            0
                        ][
                            "download_dir"
                        ]
                    ).resolve(),
                    Path(temp).resolve(),
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

                self.assertNotEqual(
                    connector
                    .download_thread_ids[0],
                    threading.get_ident(),
                )

            finally:
                runtime.close()

    def test_runtime_accepts_only_active_selected_watch_folder(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            runtime = self._runtime()

            active = {
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
                    return_value=active,
                ) as get_watch:
                    result = (
                        runtime.download_document(
                            thread_id=7,
                            provider_message_id=(
                                "MSG-DOC-4"
                            ),
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

                connector = (
                    _RuntimeConnector
                    .instances[0]
                )

                self.assertEqual(
                    Path(
                        connector.download_calls[
                            0
                        ][
                            "download_dir"
                        ]
                    ).resolve(),
                    Path(temp).resolve(),
                )

            finally:
                runtime.close()

        with tempfile.TemporaryDirectory() as temp:
            runtime = self._runtime()

            inactive = {
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
                    return_value=inactive,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "no está activa",
                    ):
                        runtime.download_document(
                            thread_id=7,
                            provider_message_id=(
                                "MSG-DOC-5"
                            ),
                            watch_folder_id=9,
                        )

                self.assertEqual(
                    _RuntimeConnector.instances,
                    [],
                )

            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
