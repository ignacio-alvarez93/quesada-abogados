from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.automation.connectors.whatsapp_connector import (
    WHATSAPP_ATTACH_BUTTON_SELECTOR,
    WHATSAPP_DOCUMENT_ATTACH_SELECTOR,
    WHATSAPP_DOCUMENT_CAPTURE_SELECTOR,
    WhatsAppActiveChatFingerprint,
    WhatsAppConnector,
)


class _FakeElement:
    def __init__(
        self,
        *,
        send_file_error=None,
    ):
        self.click_count = 0
        self.sent_paths = []
        self.send_file_error = (
            send_file_error
        )

    def mouse_click(
        self,
    ):
        self.click_count += 1

    def send_file(
        self,
        path,
    ):
        self.sent_paths.append(
            path
        )

        if (
            self.send_file_error
            is not None
        ):
            raise self.send_file_error


class _FakeBrowser:
    def __init__(
        self,
        *,
        send_file_error=None,
        captured_count=1,
    ):
        self.attach = _FakeElement()
        self.document = _FakeElement()

        self.file_input = (
            _FakeElement(
                send_file_error=(
                    send_file_error
                )
            )
        )

        self.captured_count = int(
            captured_count
        )

        self.restore_count = 0
        self.install_count = 0

    def find_element(
        self,
        selector,
    ):
        if (
            selector
            == WHATSAPP_ATTACH_BUTTON_SELECTOR
        ):
            return self.attach

        if (
            selector
            == WHATSAPP_DOCUMENT_ATTACH_SELECTOR
        ):
            return self.document

        if (
            selector
            == WHATSAPP_DOCUMENT_CAPTURE_SELECTOR
        ):
            return self.file_input

        return None

    def evaluate(
        self,
        script,
    ):
        source = str(
            script
            or ""
        )

        if (
            "QA_WA_ATTACHMENT_INSTALL"
            in source
        ):
            self.install_count += 1

            return {
                "installed": True,
                "reason": None,
            }

        if (
            "QA_WA_ATTACHMENT_COUNT"
            in source
        ):
            return self.captured_count

        if (
            "QA_WA_ATTACHMENT_RESTORE"
            in source
        ):
            self.restore_count += 1
            return True

        return {}


class WhatsAppAttachmentTransportTest(
    unittest.TestCase
):
    def _build_connector(
        self,
        *,
        send_file_error=None,
        captured_count=1,
    ):
        connector = WhatsAppConnector()

        browser = _FakeBrowser(
            send_file_error=(
                send_file_error
            ),
            captured_count=(
                captured_count
            ),
        )

        connector.browser = browser

        connector.get_active_chat_fingerprint = (
            lambda: WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name="Cliente prueba",
                active_identity="cliente prueba",
                visible_message_count=5,
                last_provider_message_id="BEFORE",
            )
        )

        return connector, browser

    def _temporary_file(
        self,
    ):
        temp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".txt",
        )

        temp.write(
            b"attachment-test"
        )

        temp.close()

        self.addCleanup(
            lambda: Path(
                temp.name
            ).unlink(
                missing_ok=True
            )
        )

        return Path(
            temp.name
        )

    def test_stage_document_attachment_happy_path(
        self,
    ):
        connector, browser = (
            self._build_connector()
        )

        file_path = (
            self._temporary_file()
        )

        states = iter(
            [
                {
                    "preview_found": False,
                    "filename_present": False,
                    "send_found": False,
                },
                {
                    "preview_found": True,
                    "filename_present": True,
                    "send_found": True,
                    "selected_count": 1,
                    "document_labels": [
                        file_path.name
                    ],
                    "caption_found": True,
                    "remove_found": True,
                    "add_found": True,
                    "send_aria_label":
                        "Enviar 1 seleccionado",
                },
            ]
        )

        connector.get_document_attachment_preview_state = (
            lambda **kwargs: next(
                states
            )
        )

        result = (
            connector.stage_document_attachment(
                file_path,
                timeout=1,
            )
        )

        self.assertTrue(
            result["staged"]
        )

        self.assertEqual(
            result["filename"],
            file_path.name,
        )

        self.assertEqual(
            browser.attach.click_count,
            1,
        )

        self.assertEqual(
            browser.document.click_count,
            1,
        )

        self.assertEqual(
            len(
                browser.file_input.sent_paths
            ),
            1,
        )

        self.assertEqual(
            browser.install_count,
            1,
        )

        self.assertEqual(
            browser.restore_count,
            1,
        )

    def test_stage_rejects_missing_file(
        self,
    ):
        connector, browser = (
            self._build_connector()
        )

        with self.assertRaises(
            FileNotFoundError
        ):
            connector.stage_document_attachment(
                "definitely_missing_qa_file.txt",
                timeout=1,
            )

        self.assertEqual(
            browser.attach.click_count,
            0,
        )

    def test_stage_rejects_existing_preview(
        self,
    ):
        connector, browser = (
            self._build_connector()
        )

        file_path = (
            self._temporary_file()
        )

        connector.get_document_attachment_preview_state = (
            lambda **kwargs: {
                "preview_found": True,
                "filename_present": True,
                "send_found": True,
            }
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Ya existe un preview",
        ):
            connector.stage_document_attachment(
                file_path,
                timeout=1,
            )

        self.assertEqual(
            browser.attach.click_count,
            0,
        )

    def test_stage_fails_closed_on_ambiguous_input_count(
        self,
    ):
        connector, browser = (
            self._build_connector(
                captured_count=2,
            )
        )

        file_path = (
            self._temporary_file()
        )

        connector.get_document_attachment_preview_state = (
            lambda **kwargs: {
                "preview_found": False,
                "filename_present": False,
                "send_found": False,
            }
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Número ambiguo",
        ):
            connector.stage_document_attachment(
                file_path,
                timeout=1,
            )

        self.assertEqual(
            browser.file_input.sent_paths,
            [],
        )

        self.assertEqual(
            browser.restore_count,
            1,
        )

    def test_send_file_exception_is_reconciled_when_preview_exists(
        self,
    ):
        connector, browser = (
            self._build_connector(
                send_file_error=RuntimeError(
                    "simulated transport error"
                )
            )
        )

        file_path = (
            self._temporary_file()
        )

        states = iter(
            [
                {
                    "preview_found": False,
                    "filename_present": False,
                    "send_found": False,
                },
                {
                    "preview_found": True,
                    "filename_present": True,
                    "send_found": True,
                    "selected_count": 1,
                    "document_labels": [
                        file_path.name
                    ],
                    "caption_found": True,
                    "remove_found": True,
                    "add_found": True,
                    "send_aria_label":
                        "Enviar 1 seleccionado",
                },
            ]
        )

        connector.get_document_attachment_preview_state = (
            lambda **kwargs: next(
                states
            )
        )

        result = (
            connector.stage_document_attachment(
                file_path,
                timeout=1,
            )
        )

        self.assertTrue(
            result[
                "load_error_reconciled"
            ]
        )

        self.assertEqual(
            len(
                browser.file_input.sent_paths
            ),
            1,
        )

    def test_source_contract_never_sends_attachment(
        self,
    ):
        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    def stage_document_attachment("
        )

        end = source.index(
            "\n    def send_text_message(",
            start,
        )

        block = source[
            start:
            end
        ]

        self.assertIn(
            "send_file(",
            block,
        )

        self.assertNotIn(
            "_dispatch_send_button_fast(",
            block,
        )

        self.assertNotIn(
            "send_text_message(",
            block,
        )

        self.assertNotIn(
            "pyautogui",
            block.casefold(),
        )

        self.assertIn(
            "captured_count != 1",
            block,
        )

        self.assertIn(
            "WhatsAppAttachmentStageStateUncertainError",
            block,
        )


if __name__ == "__main__":
    unittest.main()
