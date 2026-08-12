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


    def test_view_can_open_persistent_whatsapp_runtime(
        self,
    ):
        self.assertIn(
            'def open_whatsapp(',
            self.view_text,
        )

        self.assertIn(
            '"Abrir WhatsApp"',
            self.view_text,
        )

        self.assertIn(
            'whatsapp_runtime.start()',
            self.view_text,
        )

        self.assertIn(
            'whatsapp_runtime.started',
            self.view_text,
        )

        self.assertIn(
            '"run_thread"',
            self.view_text,
        )


    def test_composer_refreshes_after_initial_thread_load(
        self,
    ):
        self.assertIn(
            "_refresh_composer_controls()",
            self.view_text,
        )

        initial_load_marker = (
            "load_data(\n"
            "        preserve_selection=True,\n"
            "    )\n\n"
            "    _refresh_composer_controls()"
        )

        self.assertIn(
            initial_load_marker,
            self.view_text,
        )


    def test_selecting_thread_routes_persistent_whatsapp(
        self,
    ):
        self.assertIn(
            "def _route_whatsapp_thread(",
            self.view_text,
        )

        self.assertIn(
            "verify_and_open_thread(",
            self.view_text,
        )

        self.assertIn(
            "_route_whatsapp_thread(\n"
            "                    new_thread_id",
            self.view_text,
        )

        self.assertNotIn(
            "and whatsapp_runtime.started",
            self.view_text,
        )

        self.assertIn(
            "if whatsapp_runtime is not None:",
            self.view_text,
        )

        self.assertIn(
            "if not whatsapp_runtime.started:",
            self.view_text,
        )

        self.assertIn(
            "whatsapp_runtime.start()",
            self.view_text,
        )


    def test_open_whatsapp_does_not_route_implicitly(
        self,
    ):
        start = self.view_text.index(
            "    def open_whatsapp("
        )

        end = self.view_text.index(
            "\n    def ",
            start + 10,
        )

        block = self.view_text[
            start:end
        ]

        self.assertNotIn(
            "verify_and_open_thread(",
            block,
        )

        self.assertIn(
            "Selecciona una conversación ",
            block,
        )


if __name__ == "__main__":
    unittest.main()
