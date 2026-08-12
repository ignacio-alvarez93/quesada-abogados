import unittest
from pathlib import Path

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppConnector,
)


class RoutingConnector(
    WhatsAppConnector
):
    def __init__(
        self,
    ):
        self.profile_key = "test"
        self.profile_dir = None
        self.headless = True

        # started=True contract
        self.browser = object()

        self.current_result = {
            "opened": True,
            "verified": False,
            "reason":
                "PHONE_MISMATCH",
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600999888",
        }

        self.search_result = {
            "opened": True,
            "reason": None,
        }

        self.after_search_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        self.verify_calls = []
        self.search_calls = []

    def _verify_active_chat_phone(
        self,
        phone,
        *,
        timeout=10,
    ):
        self.verify_calls.append(
            (
                phone,
                timeout,
            )
        )

        if len(
            self.verify_calls
        ) == 1:
            return dict(
                self.current_result
            )

        return dict(
            self.after_search_result
        )

    def search_and_open_chat_by_phone(
        self,
        phone,
        *,
        expected_display_name=None,
        timeout=10,
    ):
        self.search_calls.append(
            (
                phone,
                timeout,
            )
        )

        return dict(
            self.search_result
        )


class WhatsAppRecipientRoutingTest(
    unittest.TestCase
):
    def test_current_matching_chat_is_reused(
        self,
    ):
        connector = RoutingConnector()

        connector.current_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600111222",
        }

        result = (
            connector.open_chat_by_phone(
                "+34 600 111 222",
                timeout=9,
            )
        )

        self.assertTrue(
            result["verified"]
        )

        self.assertEqual(
            result["navigation"],
            "CURRENT_CHAT",
        )

        self.assertEqual(
            connector.search_calls,
            [],
        )

    def test_mismatch_uses_internal_search_then_verifies(
        self,
    ):
        connector = RoutingConnector()

        result = (
            connector.open_chat_by_phone(
                "+34 600 111 222",
                timeout=9,
            )
        )

        self.assertTrue(
            result["verified"]
        )

        self.assertEqual(
            result["navigation"],
            "CHAT_SEARCH",
        )

        self.assertEqual(
            len(
                connector.search_calls
            ),
            1,
        )

        self.assertEqual(
            len(
                connector.verify_calls
            ),
            2,
        )

    def test_search_failure_never_verifies_success(
        self,
    ):
        connector = RoutingConnector()

        connector.search_result = {
            "opened": False,
            "reason":
                "CHAT_SEARCH_NO_RESULT",
        }

        result = (
            connector.open_chat_by_phone(
                "+34 600 111 222",
                timeout=9,
            )
        )

        self.assertFalse(
            result["verified"]
        )

        self.assertEqual(
            result["reason"],
            "CHAT_SEARCH_NO_RESULT",
        )

        self.assertEqual(
            len(
                connector.verify_calls
            ),
            1,
        )

    def test_post_search_phone_mismatch_is_rejected(
        self,
    ):
        connector = RoutingConnector()

        connector.after_search_result = {
            "opened": True,
            "verified": False,
            "reason":
                "PHONE_MISMATCH",
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600999888",
        }

        result = (
            connector.open_chat_by_phone(
                "+34 600 111 222",
                timeout=9,
            )
        )

        self.assertFalse(
            result["verified"]
        )

        self.assertEqual(
            result["reason"],
            "PHONE_MISMATCH",
        )

    def test_invalid_phone_never_searches(
        self,
    ):
        connector = RoutingConnector()

        with self.assertRaises(
            ValueError
        ):
            connector.open_chat_by_phone(
                "abc",
                timeout=9,
            )

        self.assertEqual(
            connector.search_calls,
            [],
        )


    def test_connector_contract_allows_verified_self_chat(
        self,
    ):
        from pathlib import Path

        connector_text = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "CHAT_KIND_INDIVIDUAL,",
            connector_text,
        )

        self.assertIn(
            "CHAT_KIND_SELF,",
            connector_text,
        )

        self.assertIn(
            "observed.digits",
            connector_text,
        )

        self.assertIn(
            "expected.digits",
            connector_text,
        )


    def test_chat_search_selector_uses_safe_js_serialization(
        self,
    ):
        from pathlib import Path

        connector_text = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "selector_js = json.dumps(",
            connector_text,
        )

        self.assertIn(
            "{selector_js}",
            connector_text,
        )

        # selector!r puede aparecer legítimamente en
        # trazas de diagnóstico. Lo prohibido es usarlo
        # directamente como argumento JavaScript.
        self.assertNotIn(
            "document.querySelector(\n"
            "                            {selector!r}",
            connector_text,
        )


    def test_open_chat_supports_search_result_row_shapes(
        self,
    ):
        from pathlib import Path

        connector_text = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "candidate_selectors = (",
            connector_text,
        )

        self.assertIn(
            "' [role=\"gridcell\"]'",
            connector_text,
        )

        self.assertIn(
            "row_selector,",
            connector_text,
        )

        self.assertIn(
            '"CHAT_ROW_NOT_FOUND"',
            connector_text,
        )


    def test_phone_search_always_clears_before_routing(
        self,
    ):
        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        clear_start = source.index(
            "    def clear_chat_search("
        )

        clear_end = source.index(
            "\n    def search_and_open_chat_by_phone(",
            clear_start,
        )

        clear_block = source[
            clear_start:clear_end
        ]

        self.assertNotIn(
            'if not state["text"]:\n'
            "            return True",
            clear_block,
        )

        search_start = source.index(
            "    def search_and_open_chat_by_phone("
        )

        search_end = source.index(
            "\n    def _verify_active_chat_phone(",
            search_start,
        )

        search_block = source[
            search_start:search_end
        ]

        pre_clear_position = search_block.index(
            "pre_clear = ("
        )

        prepare_position = search_block.index(
            "self.prepare_chat_interface()"
        )

        self.assertLess(
            pre_clear_position,
            prepare_position,
        )

        self.assertIn(
            "[WA-SEARCH] B9 search cleared",
            search_block,
        )


if __name__ == "__main__":
    unittest.main()
