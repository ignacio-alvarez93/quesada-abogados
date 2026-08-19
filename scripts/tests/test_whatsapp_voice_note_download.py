import tempfile
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
    def send(self, command):
        return command


class _FakeLoop:
    def run_until_complete(self, value):
        return value


class _FakeVoiceBrowser:
    def __init__(self, target_dir):
        self.target_dir = Path(target_dir)
        self.page = _FakePage()
        self.loop = _FakeLoop()
        self.download_clicks = 0

    def evaluate(self, script):
        source = str(script or "")

        if (
            "VOICE_NOTE_NOT_FOUND"
            in source
            and "downloadButton.click()"
            in source
        ):
            self.download_clicks += 1

            (
                self.target_dir
                / "voice.tmp"
            ).write_bytes(
                b"temporary"
            )

            (
                self.target_dir
                / "voice-note.ogg"
            ).write_bytes(
                b"voice-note-data"
            )

            return {
                "clicked": True,
                "reason": None,
            }

        return {}


class _RuntimeVoiceConnector:
    def __init__(self):
        self.calls = []

    def download_visible_voice_note(
        self,
        provider_message_id,
        *,
        download_dir,
        timeout,
    ):
        self.calls.append(
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
            "media_type":
                "VOICE_NOTE",
            "expected_filename":
                None,
            "filename":
                "voice-note.ogg",
            "file_path":
                str(
                    Path(download_dir)
                    / "voice-note.ogg"
                ),
            "size_bytes":
                15,
        }


class WhatsAppVoiceNoteDownloadTest(
    unittest.TestCase
):

    def test_connector_downloads_voice_note(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            connector = WhatsAppConnector()

            browser = _FakeVoiceBrowser(
                temp
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
                        visible_message_count=1,
                        last_provider_message_id=(
                            "VOICE-1"
                        ),
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
                    .download_visible_voice_note(
                        "VOICE-1",
                        download_dir=temp,
                        timeout=1,
                    )
                )

            self.assertEqual(
                result["media_type"],
                "VOICE_NOTE",
            )

            self.assertEqual(
                result["filename"],
                "voice-note.ogg",
            )

            self.assertEqual(
                browser.download_clicks,
                1,
            )

            self.assertEqual(
                calls[0]["behavior"],
                "allow",
            )

            self.assertEqual(
                calls[-1]["behavior"],
                "default",
            )


    def test_runtime_routes_voice_note_download(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            runtime = (
                WhatsAppRuntimeService
                .__new__(
                    WhatsAppRuntimeService
                )
            )

            connector = (
                _RuntimeVoiceConnector()
            )

            runtime._prepare_verified_outbound_impl = (
                lambda **kwargs:
                    SimpleNamespace(
                        id=7,
                        client_id=9,
                    )
            )

            runtime._build_connector = (
                lambda:
                    connector
            )

            watch_folder = {
                "id": 3,
                "name": "Descargas",
                "folder_path": temp,
                "is_active": 1,
            }

            with patch(
                "backend.services."
                "whatsapp_runtime_service."
                "document_inbox_watch_service."
                "ensure_default_downloads_watch_folder",
                return_value=(
                    watch_folder
                ),
            ):
                result = (
                    runtime
                    ._download_voice_note_impl(
                        thread_id=7,
                        provider_message_id=(
                            "VOICE-2"
                        ),
                        download_timeout=4,
                    )
                )

            self.assertEqual(
                result["media_type"],
                "VOICE_NOTE",
            )

            self.assertEqual(
                result["thread_id"],
                7,
            )

            self.assertEqual(
                result["client_id"],
                9,
            )

            self.assertEqual(
                len(connector.calls),
                1,
            )

            self.assertEqual(
                connector.calls[0][
                    "provider_message_id"
                ],
                "VOICE-2",
            )


if __name__ == "__main__":
    unittest.main()
