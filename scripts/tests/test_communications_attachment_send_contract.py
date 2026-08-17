from __future__ import annotations

import ast
import unittest
from pathlib import Path


SOURCE = Path(
    "frontend/views/communications_view.py"
).read_text(
    encoding="utf-8"
)


def function_source(
    name,
):
    tree = ast.parse(
        SOURCE
    )

    matches = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == name
        )
    ]

    if len(matches) != 1:
        raise AssertionError(
            f"{name}: {len(matches)} matches"
        )

    node = matches[0]

    lines = SOURCE.splitlines(
        keepends=True
    )

    return "".join(
        lines[
            node.lineno - 1:
            node.end_lineno
        ]
    )


class CommunicationsAttachmentSendContractTests(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        self.send = function_source(
            "send_message"
        )

        self.finish = function_source(
            "_finish_send_ui"
        )

        self.refresh = function_source(
            "_refresh_composer_controls"
        )

    def test_pending_attachments_do_not_disable_send(
        self,
    ):
        self.assertNotIn(
            "or has_pending_attachments",
            self.refresh,
        )

    def test_attachments_only_are_valid_payload(
        self,
    ):
        self.assertIn(
            "not text_to_send",
            self.send,
        )

        self.assertIn(
            "not pending_attachments",
            self.send,
        )

    def test_attachment_target_is_frozen_to_thread(
        self,
    ):
        self.assertIn(
            "attachment_target_thread_id",
            self.send,
        )

        self.assertIn(
            "Los archivos pendientes pertenecen",
            self.send,
        )

    def test_text_is_sent_before_documents(
        self,
    ):
        self.assertLess(
            self.send.index(
                ".send_text_message("
            ),
            self.send.index(
                ".send_document_message("
            ),
        )

    def test_documents_use_runtime_only(
        self,
    ):
        self.assertIn(
            ".send_document_message(",
            self.send,
        )

        self.assertNotIn(
            ".connector",
            self.send,
        )

        self.assertNotIn(
            "WhatsAppConnector(",
            self.send,
        )

    def test_documents_are_sequential(
        self,
    ):
        self.assertIn(
            "for attachment in (",
            self.send,
        )

        self.assertIn(
            "pending_attachments",
            self.send,
        )

    def test_expedient_context_is_propagated(
        self,
    ):
        self.assertIn(
            "expedient_id=(",
            self.send,
        )

        self.assertIn(
            '"attachment_source"',
            self.send,
        )

    def test_queue_stops_on_uncertain_or_failure(
        self,
    ):
        self.assertIn(
            '"UNCERTAIN"',
            self.send,
        )

        self.assertIn(
            '"SEND_FAILED"',
            self.send,
        )

        self.assertIn(
            "return False",
            self.send,
        )

    def test_queue_stops_if_selection_changes(
        self,
    ):
        self.assertIn(
            '"SELECTION_CHANGED"',
            self.send,
        )

        self.assertIn(
            "current_thread_id",
            self.send,
        )

    def test_only_confirmed_attachments_are_removed(
        self,
    ):
        self.assertIn(
            "completed_attachment_keys",
            self.finish,
        )

        self.assertIn(
            "not in completed_attachment_keys",
            self.finish,
        )

    def test_successful_text_is_cleared_even_if_later_file_fails(
        self,
    ):
        self.assertIn(
            "text_sent",
            self.finish,
        )

        self.assertIn(
            "_clear_composer()",
            self.finish,
        )

    def test_uncertain_still_blocks_thread(
        self,
    ):
        self.assertIn(
            "send_blocked_thread_ids",
            self.finish,
        )

        self.assertIn(
            "No reenvíes este mensaje o archivo",
            self.finish,
        )

    def test_attachment_finish_refreshes_central_panel(
        self,
    ):
        self.assertIn(
            "_refresh_chat_panel_control()",
            self.finish,
        )

        self.assertIn(
            "_force_message_history_bottom()",
            self.finish,
        )


if __name__ == "__main__":
    unittest.main()
