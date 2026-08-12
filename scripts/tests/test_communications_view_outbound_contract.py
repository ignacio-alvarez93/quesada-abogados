from pathlib import Path
import re
import unittest


ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "communications_view.py"
)

APP = (
    ROOT
    / "app"
    / "main.py"
)


class CommunicationsViewOutboundContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(
        cls,
    ):
        cls.view_text = VIEW.read_text(
            encoding="utf-8"
        )

        cls.app_text = APP.read_text(
            encoding="utf-8"
        )

    def test_view_accepts_runtime_and_username(
        self,
    ):
        self.assertIn(
            "whatsapp_runtime=None,",
            self.view_text,
        )

        self.assertIn(
            "current_username=None,",
            self.view_text,
        )

    def test_app_injects_runtime_and_username(
        self,
    ):
        self.assertIn(
            "whatsapp_runtime=(",
            self.app_text,
        )

        self.assertIn(
            "current_username=(",
            self.app_text,
        )

    def test_view_sends_only_through_runtime(
        self,
    ):
        self.assertIn(
            "whatsapp_runtime",
            self.view_text,
        )

        self.assertIn(
            ".send_text_message(",
            self.view_text,
        )

        self.assertNotIn(
            "WhatsAppConnector(",
            self.view_text,
        )

    def test_double_send_guard_exists(
        self,
    ):
        self.assertIn(
            '"sending": False',
            self.view_text,
        )

        self.assertRegex(
            self.view_text,
            (
                r'if\s+state\.get\(\s*'
                r'"sending"\s*'
                r'\)\s*:\s*'
                r'return'
            ),
        )

        self.assertIn(
            'state["sending"] = True',
            self.view_text,
        )

    def test_uncertain_send_is_blocked(
        self,
    ):
        self.assertIn(
            '"send_blocked_thread_ids": set()',
            self.view_text,
        )

        self.assertIn(
            "if uncertain:",
            self.view_text,
        )

        self.assertIn(
            "No reenvíes este mensaje",
            self.view_text,
        )

    def test_draft_is_cleared_on_thread_change(
        self,
    ):
        self.assertIn(
            "previous_thread_id",
            self.view_text,
        )

        self.assertIn(
            "_clear_composer()",
            self.view_text,
        )


if __name__ == "__main__":
    unittest.main()
