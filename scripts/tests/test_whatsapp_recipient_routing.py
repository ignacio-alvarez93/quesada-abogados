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


    def test_phone_search_uses_fast_route_with_safe_fallback(
        self,
    ):
        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
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

        self.assertIn(
            "self._get_fast_chat_routing_state()",
            search_block,
        )

        # La ruta conservadora sigue presente como fallback.
        self.assertIn(
            "self.clear_chat_search()",
            search_block,
        )

        self.assertIn(
            "self.prepare_chat_interface()",
            search_block,
        )

        # La escritura DOM rápida nunca elimina el fallback
        # probado mediante SeleniumBase.
        self.assertIn(
            "self._set_chat_search_value_fast(",
            search_block,
        )

        self.assertIn(
            "self.browser.send_keys(",
            search_block,
        )

        # La limpieza final sigue siendo obligatoria.
        self.assertIn(
            "self._request_chat_search_clear_fast(",
            search_block,
        )

        self.assertIn(
            "if not cleared:",
            search_block,
        )

        self.assertIn(
            "self.clear_chat_search()",
            search_block,
        )


    def test_phone_search_avoids_fixed_layout_wait_before_mouse_click(
        self,
    ):
        from pathlib import Path

        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        search_start = source.index(
            "    def search_and_open_chat_by_phone("
        )

        search_end = source.index(
            "\n    def _verify_active_chat_phone(",
            search_start,
        )

        search_block = source[
            search_start:
            search_end
        ]

        # No debemos pagar 150 ms preventivos en
        # cada selección.
        self.assertNotIn(
            "search_layout_wait_ms=",
            search_block,
        )

        self.assertNotIn(
            "time.sleep(\n"
            "            0.15\n"
            "        )",
            search_block,
        )

        # El elemento se intenta recuperar inmediatamente.
        first_find_pos = search_block.index(
            "self.browser.find_element(\n"
            "                    target_selector"
        )

        retry_guard_pos = search_block.index(
            "if not result_element:",
            first_find_pos,
        )

        retry_sleep_pos = search_block.index(
            "time.sleep(\n"
            "                0.05\n"
            "            )",
            retry_guard_pos,
        )

        second_find_pos = search_block.index(
            "self.browser.find_element(\n"
            "                        target_selector",
            retry_sleep_pos,
        )

        self.assertLess(
            first_find_pos,
            retry_guard_pos,
        )

        self.assertLess(
            retry_guard_pos,
            retry_sleep_pos,
        )

        self.assertLess(
            retry_sleep_pos,
            second_find_pos,
        )

        # La interacción probada no cambia.
        self.assertIn(
            "mouse_click()",
            search_block,
        )

        # Tampoco desaparece el retry físico posterior.
        self.assertIn(
            "retry_click()",
            search_block,
        )


    def test_phone_search_defers_marker_cleanup_until_after_confirmation(
        self,
    ):
        from pathlib import Path

        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        search_start = source.index(
            "    def search_and_open_chat_by_phone("
        )

        search_end = source.index(
            "\n    def _verify_active_chat_phone(",
            search_start,
        )

        search_block = source[
            search_start:
            search_end
        ]

        click_pos = search_block.index(
            "mouse_click()"
        )

        confirm_pos = search_block.index(
            "# Confirmamos que el chat REALMENTE cambió."
        )

        final_cleanup_pos = search_block.index(
            "# Cleanup único: se realiza DESPUÉS "
            "de confirmar o"
        )

        # La confirmación de identidad ocurre antes del
        # cleanup final del marcador.
        self.assertLess(
            click_pos,
            confirm_pos,
        )

        self.assertLess(
            confirm_pos,
            final_cleanup_pos,
        )

        # El retry sigue limpiando cualquier marcador viejo
        # antes de volver a localizar la fila.
        retry_pos = search_block.index(
            "retry_marked = ("
        )

        retry_block = search_block[
            retry_pos:
            final_cleanup_pos
        ]

        self.assertIn(
            "removeAttribute(",
            retry_block,
        )

        # Y existe un cleanup final real tras confirmación/retry.
        final_cleanup_block = search_block[
            final_cleanup_pos:
        ]

        self.assertIn(
            "removeAttribute(",
            final_cleanup_block,
        )

        self.assertIn(
            "'data-qa-whatsapp-routing-target'",
            final_cleanup_block,
        )

        # Interacción y verificación permanecen intactas.
        self.assertIn(
            "retry_click()",
            search_block,
        )

        self.assertIn(
            "conversation-info-header-chat-title",
            search_block,
        )


    def test_phone_search_uses_sequential_cdp_click_with_historical_fallback(
        self,
    ):
        from pathlib import Path

        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "def _dispatch_element_mouse_click_sequential(",
            source,
        )

        helper_start = source.index(
            "    def _dispatch_element_mouse_click_sequential("
        )

        helper_end = source.index(
            "\n    def _dispatch_composer_key_event(",
            helper_start,
        )

        helper = source[
            helper_start:
            helper_end
        ]

        self.assertIn(
            "element.get_position_async()",
            helper,
        )

        self.assertIn(
            'cdp_input.dispatch_mouse_event(\n'
            '                "mousePressed"',
            helper,
        )

        self.assertIn(
            'cdp_input.dispatch_mouse_event(\n'
            '                "mouseReleased"',
            helper,
        )

        self.assertIn(
            "element._tab.send(",
            helper,
        )

        # No debe degradar a GUI/PyAutoGUI.
        self.assertNotIn(
            "gui_click",
            helper,
        )

        self.assertNotIn(
            "pyautogui",
            helper,
        )

        search_start = source.index(
            "    def search_and_open_chat_by_phone("
        )

        search_end = source.index(
            "\n    def _verify_active_chat_phone(",
            search_start,
        )

        search_block = source[
            search_start:
            search_end
        ]

        self.assertIn(
            "_dispatch_element_mouse_click_sequential(",
            search_block,
        )

        # La identidad sigue siendo autoritativa.
        self.assertIn(
            "conversation-info-header-chat-title",
            search_block,
        )

        # El fallback histórico sigue intacto.
        self.assertIn(
            "retry_click()",
            search_block,
        )



    def test_fast_final_clear_has_safe_fallback(
        self,
    ):
        source = Path(
            "backend/automation/connectors/"
            "whatsapp_connector.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "def _request_chat_search_clear_fast(",
            source,
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

        fast_clear_pos = search_block.index(
            "self._request_chat_search_clear_fast("
        )

        fallback_guard_pos = search_block.index(
            "if not cleared:",
            fast_clear_pos,
        )

        safe_clear_pos = search_block.index(
            "self.clear_chat_search()",
            fallback_guard_pos,
        )

        self.assertLess(
            fast_clear_pos,
            fallback_guard_pos,
        )

        self.assertLess(
            fallback_guard_pos,
            safe_clear_pos,
        )
