from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.automation.connectors.whatsapp_connector import (
    WHATSAPP_ATTACH_BUTTON_SELECTOR,
    WHATSAPP_DOCUMENT_ATTACH_SELECTOR,
    WHATSAPP_DOCUMENT_CAPTURE_SELECTOR,
    WHATSAPP_ATTACHMENT_SEND_ONE_SELECTOR,
    MESSAGE_DIRECTION_OUTBOUND,
    MESSAGE_STATUS_UNKNOWN,
    MESSAGE_TYPE_DOCUMENT,
    MESSAGE_TYPE_TEXT,
    WhatsAppMessageSnapshot,
    WhatsAppSendStateUncertainError,
    WhatsAppActiveChatFingerprint,
    WhatsAppConnector,
)


class _FakeElement:
    def __init__(
        self,
        *,
        send_file_error=None,
        mouse_click_error=None,
    ):
        self.click_count = 0
        self.sent_paths = []
        self.send_file_error = (
            send_file_error
        )
        self.mouse_click_error = (
            mouse_click_error
        )

    def mouse_click(
        self,
    ):
        self.click_count += 1

        if (
            self.mouse_click_error
            is not None
        ):
            raise self.mouse_click_error

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
        send_click_error=None,
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

        self.preview_send = (
            _FakeElement(
                mouse_click_error=(
                    send_click_error
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

        if (
            selector
            == WHATSAPP_ATTACHMENT_SEND_ONE_SELECTOR
        ):
            return self.preview_send

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

    def _message_snapshot(
        self,
        *,
        provider_message_id,
        direction=MESSAGE_DIRECTION_OUTBOUND,
        message_type=MESSAGE_TYPE_TEXT,
        filename=None,
    ):
        metadata = {
            "transport":
                "WHATSAPP_WEB",
        }

        if filename is not None:
            metadata[
                "filename"
            ] = filename

        return WhatsAppMessageSnapshot(
            provider_message_id=(
                provider_message_id
            ),
            direction=direction,
            body_text="",
            provider_timestamp=None,
            message_type=message_type,
            provider_status=(
                MESSAGE_STATUS_UNKNOWN
            ),
            sender=None,
            metadata=metadata,
        )

    def _configure_document_send(
        self,
        file_path,
        *,
        identities=(
            "cliente prueba",
            "cliente prueba",
        ),
        snapshot_batches=None,
        selected_count=1,
        filename_present=True,
        send_found=True,
        send_click_error=None,
    ):
        connector = WhatsAppConnector()

        browser = _FakeBrowser(
            send_click_error=(
                send_click_error
            )
        )

        connector.browser = browser

        fingerprints = [
            WhatsAppActiveChatFingerprint(
                chat_open=True,
                active_display_name=identity,
                active_identity=identity,
                visible_message_count=5,
                last_provider_message_id="BEFORE",
            )
            for identity
            in identities
        ]

        fingerprint_state = {
            "index": 0,
        }

        def fingerprint():
            index = min(
                fingerprint_state[
                    "index"
                ],
                len(
                    fingerprints
                )
                - 1,
            )

            fingerprint_state[
                "index"
            ] += 1

            return fingerprints[
                index
            ]

        connector.get_active_chat_fingerprint = (
            fingerprint
        )

        filename = Path(
            file_path
        ).name

        connector.stage_document_attachment = (
            lambda *args, **kwargs: {
                "staged": True,
                "filename":
                    filename,
                "size":
                    Path(
                        file_path
                    ).stat().st_size,
                "active_display_name":
                    identities[0],
                "preview": {
                    "preview_found": True,
                    "filename_present":
                        filename_present,
                    "send_found":
                        send_found,
                    "selected_count":
                        selected_count,
                    "send_aria_label":
                        (
                            "Enviar 1 seleccionado"
                            if selected_count == 1
                            else (
                                f"Enviar "
                                f"{selected_count} "
                                f"seleccionados"
                            )
                        ),
                },
                "load_error_reconciled":
                    False,
            }
        )

        batches = list(
            snapshot_batches
            or []
        )

        if not batches:
            batches = [
                [],
            ]

        snapshot_state = {
            "index": 0,
        }

        def snapshots(
            *,
            limit=200,
        ):
            index = min(
                snapshot_state[
                    "index"
                ],
                len(
                    batches
                )
                - 1,
            )

            snapshot_state[
                "index"
            ] += 1

            return batches[
                index
            ]

        connector.list_visible_message_snapshots = (
            snapshots
        )

        return connector, browser

    def test_send_document_attachment_confirms_exact_outbound(
        self,
    ):
        file_path = (
            self._temporary_file()
        )

        before = (
            self._message_snapshot(
                provider_message_id="BEFORE",
            )
        )

        confirmed = (
            self._message_snapshot(
                provider_message_id="AFTER",
                message_type=(
                    MESSAGE_TYPE_DOCUMENT
                ),
                filename=file_path.name,
            )
        )

        connector, browser = (
            self._configure_document_send(
                file_path,
                snapshot_batches=[
                    [
                        before,
                    ],
                    [
                        before,
                        confirmed,
                    ],
                ],
            )
        )

        result = (
            connector.send_document_attachment(
                file_path,
                timeout=0.1,
            )
        )

        self.assertEqual(
            result.provider_message_id,
            "AFTER",
        )

        self.assertEqual(
            result.message_type,
            MESSAGE_TYPE_DOCUMENT,
        )

        self.assertEqual(
            result.metadata[
                "filename"
            ],
            file_path.name,
        )

        self.assertEqual(
            browser.preview_send.click_count,
            1,
        )

    def test_send_document_attachment_cancels_if_recipient_changes(
        self,
    ):
        file_path = (
            self._temporary_file()
        )

        connector, browser = (
            self._configure_document_send(
                file_path,
                identities=(
                    "cliente uno",
                    "cliente dos",
                ),
                snapshot_batches=[
                    [],
                ],
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "destinatario cambió",
        ):
            connector.send_document_attachment(
                file_path,
                timeout=0.05,
            )

        self.assertEqual(
            browser.preview_send.click_count,
            0,
        )

    def test_send_document_attachment_rejects_ambiguous_preview(
        self,
    ):
        file_path = (
            self._temporary_file()
        )

        connector, browser = (
            self._configure_document_send(
                file_path,
                snapshot_batches=[
                    [],
                ],
                selected_count=2,
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "exactamente un documento",
        ):
            connector.send_document_attachment(
                file_path,
                timeout=0.05,
            )

        self.assertEqual(
            browser.preview_send.click_count,
            0,
        )

    def test_send_document_click_error_is_reconciled_if_outbound_exists(
        self,
    ):
        file_path = (
            self._temporary_file()
        )

        confirmed = (
            self._message_snapshot(
                provider_message_id="AFTER",
                message_type=(
                    MESSAGE_TYPE_DOCUMENT
                ),
                filename=file_path.name,
            )
        )

        connector, browser = (
            self._configure_document_send(
                file_path,
                snapshot_batches=[
                    [],
                    [
                        confirmed,
                    ],
                ],
                send_click_error=RuntimeError(
                    "simulated click error"
                ),
            )
        )

        result = (
            connector.send_document_attachment(
                file_path,
                timeout=0.1,
            )
        )

        self.assertEqual(
            result.provider_message_id,
            "AFTER",
        )

        self.assertEqual(
            browser.preview_send.click_count,
            1,
        )

    def test_send_document_click_error_never_retries(
        self,
    ):
        file_path = (
            self._temporary_file()
        )

        connector, browser = (
            self._configure_document_send(
                file_path,
                snapshot_batches=[
                    [],
                    [],
                ],
                send_click_error=RuntimeError(
                    "simulated click error"
                ),
            )
        )

        with self.assertRaises(
            WhatsAppSendStateUncertainError
        ):
            connector.send_document_attachment(
                file_path,
                timeout=0.06,
            )

        self.assertEqual(
            browser.preview_send.click_count,
            1,
        )

    def test_send_document_successful_click_without_confirmation_is_uncertain(
        self,
    ):
        file_path = (
            self._temporary_file()
        )

        connector, browser = (
            self._configure_document_send(
                file_path,
                snapshot_batches=[
                    [],
                    [],
                ],
            )
        )

        with self.assertRaises(
            WhatsAppSendStateUncertainError
        ):
            connector.send_document_attachment(
                file_path,
                timeout=0.06,
            )

        self.assertEqual(
            browser.preview_send.click_count,
            1,
        )

    def test_send_document_multiple_exact_matches_is_uncertain(
        self,
    ):
        file_path = (
            self._temporary_file()
        )

        first = (
            self._message_snapshot(
                provider_message_id="AFTER-1",
                message_type=(
                    MESSAGE_TYPE_DOCUMENT
                ),
                filename=file_path.name,
            )
        )

        second = (
            self._message_snapshot(
                provider_message_id="AFTER-2",
                message_type=(
                    MESSAGE_TYPE_DOCUMENT
                ),
                filename=file_path.name,
            )
        )

        connector, browser = (
            self._configure_document_send(
                file_path,
                snapshot_batches=[
                    [],
                    [
                        first,
                        second,
                    ],
                ],
            )
        )

        with self.assertRaises(
            WhatsAppSendStateUncertainError
        ):
            connector.send_document_attachment(
                file_path,
                timeout=0.1,
            )

        self.assertEqual(
            browser.preview_send.click_count,
            1,
        )

    def test_send_document_source_contract_has_single_click_site(
        self,
    ):
        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        start = source.index(
            "    def send_document_attachment("
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
            "stage_document_attachment(",
            block,
        )

        self.assertEqual(
            block.count(
                "send_click()"
            ),
            1,
        )

        self.assertIn(
            "MESSAGE_DIRECTION_OUTBOUND",
            block,
        )

        self.assertIn(
            "MESSAGE_TYPE_DOCUMENT",
            block,
        )

        self.assertIn(
            '"filename"',
            block,
        )

        self.assertIn(
            "WhatsAppSendStateUncertainError",
            block,
        )

        self.assertNotIn(
            "_dispatch_send_button_fast(",
            block,
        )

    def test_stage_document_attachment_can_repeat_in_same_session(
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
                # First operation: no preview initially.
                {
                    "preview_found": False,
                    "filename_present": False,
                    "send_found": False,
                },

                # First operation: staged.
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

                # Simulate preview already closed/sent
                # before the second attachment.
                {
                    "preview_found": False,
                    "filename_present": False,
                    "send_found": False,
                },

                # Second operation: staged.
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

        first = (
            connector.stage_document_attachment(
                file_path,
                timeout=1,
            )
        )

        second = (
            connector.stage_document_attachment(
                file_path,
                timeout=1,
            )
        )

        self.assertTrue(
            first[
                "staged"
            ]
        )

        self.assertTrue(
            second[
                "staged"
            ]
        )

        self.assertEqual(
            browser.install_count,
            2,
        )

        self.assertEqual(
            browser.restore_count,
            2,
        )

        self.assertEqual(
            len(
                browser.file_input.sent_paths
            ),
            2,
        )

    def test_document_capture_source_uses_only_current_operation(
        self,
    ):
        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        install_start = source.index(
            "    def _install_document_input_click_interceptor("
        )

        restore_start = source.index(
            "\n    def _restore_document_input_click_interceptor(",
            install_start,
        )

        count_start = source.index(
            "\n    def _get_captured_document_input_count(",
            restore_start,
        )

        stage_start = source.index(
            "\n    def stage_document_attachment(",
            count_start,
        )

        install = source[
            install_start:
            restore_start
        ]

        restore = source[
            restore_start:
            count_start
        ]

        count = source[
            count_start:
            stage_start
        ]

        self.assertIn(
            "removeAttribute(",
            install,
        )

        self.assertIn(
            "data-qa-wa-document-input",
            install,
        )

        self.assertIn(
            ".includes(",
            install,
        )

        self.assertIn(
            "__qaWaDocumentCaptured",
            count,
        )

        self.assertIn(
            "node.isConnected",
            count,
        )

        self.assertNotIn(
            "document.querySelectorAll(",
            count,
        )

        self.assertIn(
            "removeAttribute(",
            restore,
        )

        self.assertIn(
            "__qaWaDocumentCaptured",
            restore,
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
            "\n    def send_document_attachment(",
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
