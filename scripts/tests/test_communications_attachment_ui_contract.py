import unittest
from pathlib import Path


SOURCE = Path(
    "frontend/views/communications_view.py"
).read_text(
    encoding="utf-8"
)


class CommunicationsAttachmentUIContractTests(
    unittest.TestCase
):
    def test_pending_attachment_state_is_ephemeral(
        self,
    ):
        self.assertIn(
            '"pending_attachments": []',
            SOURCE,
        )
        self.assertIn(
            '"attachment_target_thread_id": None',
            SOURCE,
        )

    def test_thread_change_clears_pending_files(
        self,
    ):
        start = SOURCE.index(
            "    def select_thread("
        )
        end = SOURCE.index(
            "    def load_data(",
            start,
        )

        block = SOURCE[start:end]

        self.assertIn(
            'state["pending_attachments"] = []',
            block,
        )
        self.assertIn(
            'state["attachment_target_thread_id"] = None',
            block,
        )

    def test_general_picker_supports_multiple_files(
        self,
    ):
        start = SOURCE.index(
            "    async def _pick_attachments("
        )
        end = SOURCE.index(
            "    def _run_background(",
            start,
        )

        block = SOURCE[start:end]

        self.assertIn(
            "await ft.FilePicker().pick_files(",
            block,
        )
        self.assertIn(
            "allow_multiple=True",
            block,
        )
        self.assertIn(
            'source="EXPLORER"',
            block,
        )

    def test_expedient_picker_uses_box_folder(
        self,
    ):
        start = SOURCE.index(
            "    async def pick_expedient_attachments("
        )
        end = SOURCE.index(
            "    def _expedient_attachment_handler(",
            start,
        )

        block = SOURCE[start:end]

        self.assertIn(
            "box_folder_path",
            block,
        )
        self.assertIn(
            "initial_directory=(",
            block,
        )
        self.assertIn(
            'source="EXPEDIENT"',
            block,
        )

    def test_picker_rejects_thread_change(
        self,
    ):
        start = SOURCE.index(
            "    async def _pick_attachments("
        )
        end = SOURCE.index(
            "    async def pick_general_attachments(",
            start,
        )

        block = SOURCE[start:end]

        self.assertIn(
            "captured_thread_id",
            block,
        )
        self.assertIn(
            "La conversación cambió mientras",
            block,
        )

    def test_composer_has_attachment_button_and_preview(
        self,
    ):
        self.assertIn(
            "attachment_button = ft.IconButton(",
            SOURCE,
        )
        self.assertIn(
            "_build_pending_attachments()",
            SOURCE,
        )
        self.assertIn(
            "composer_input,\n"
            "                                        "
            "attachment_button,\n"
            "                                        "
            "send_button,",
            SOURCE,
        )

    def test_expedient_card_exposes_route_and_attachment(
        self,
    ):
        self.assertIn(
            "_expedient_attachment_handler(",
            SOURCE,
        )
        self.assertIn(
            "expedient\n"
            "                                                "
            ".box_folder_path",
            SOURCE,
        )
        self.assertIn(
            '"Ruta: "',
            SOURCE,
        )

    def test_file_selection_does_not_transport(
        self,
    ):
        start = SOURCE.index(
            "    async def _pick_attachments("
        )
        end = SOURCE.index(
            "    def _run_background(",
            start,
        )

        block = SOURCE[start:end]

        self.assertNotIn(
            "send_file_message(",
            block,
        )
        self.assertNotIn(
            ".connector",
            block,
        )

    def test_pending_files_no_longer_block_send(
        self,
    ):
        start = SOURCE.index(
            "    def _refresh_composer_controls("
        )

        end = SOURCE.index(
            "    def _clear_composer(",
            start,
        )

        block = SOURCE[
            start:
            end
        ]

        self.assertNotIn(
            "or has_pending_attachments",
            block,
        )

        self.assertNotIn(
            "12C2 todavía no activa transporte físico",
            block,
        )



if __name__ == "__main__":
    unittest.main()
