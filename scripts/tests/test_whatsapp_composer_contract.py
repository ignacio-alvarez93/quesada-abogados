import asyncio
import unittest
from unittest.mock import patch

from backend.automation.connectors.whatsapp_connector import (
    MESSAGE_COMPOSER_SELECTOR,
    MESSAGE_DIRECTION_INBOUND,
    MESSAGE_DIRECTION_OUTBOUND,
    MESSAGE_SEND_SELECTOR,
    MESSAGE_STATUS_RECEIVED,
    MESSAGE_STATUS_SENT,
    MESSAGE_TYPE_TEXT,
    WhatsAppMessageSnapshot,
    WhatsAppConnector,
)


class FakeLoop:
    def run_until_complete(
        self,
        awaitable,
    ):
        return asyncio.run(
            awaitable
        )


class FakeTab:
    def __init__(
        self,
    ):
        self.commands = []

    async def send(
        self,
        command,
    ):
        self.commands.append(
            command
        )


class FakeElement:
    def __init__(
        self,
    ):
        self._tab = FakeTab()
        self.focused = False
        self.mouse_click_count = 0

    async def focus_async(
        self,
    ):
        self.focused = True

    def mouse_click(
        self,
    ):
        self.mouse_click_count += 1


class FakeBrowser:
    def __init__(
        self,
        *,
        states=None,
    ):
        self.states = list(
            states
            or []
        )
        self.send_keys_calls = []
        self.element = FakeElement()
        self.loop = FakeLoop()

    def evaluate(
        self,
        _script,
    ):
        if not self.states:
            raise AssertionError(
                "No hay estado evaluate preparado"
            )

        return self.states.pop(
            0
        )

    def send_keys(
        self,
        selector,
        text,
    ):
        self.send_keys_calls.append(
            (
                selector,
                text,
            )
        )

    def find_element(
        self,
        selector,
    ):
        if selector not in (
            MESSAGE_COMPOSER_SELECTOR,
            MESSAGE_SEND_SELECTOR,
        ):
            raise AssertionError(
                selector
            )

        return self.element


class WhatsAppComposerContractTest(
    unittest.TestCase
):
    def test_composer_state_is_normalized(
        self,
    ):
        connector = (
            WhatsAppConnector()
        )

        connector.browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "Hola",
                    "send_found": True,
                }
            ]
        )

        state = (
            connector
            .get_message_composer_state()
        )

        self.assertEqual(
            state,
            {
                "found": True,
                "text": "Hola",
                "send_found": True,
            },
        )

    def test_set_message_composer_text_uses_cdp_send_keys(
        self,
    ):
        connector = (
            WhatsAppConnector()
        )

        browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "",
                    "send_found": False,
                },
                {
                    "found": True,
                    "text": "Mensaje prueba",
                    "send_found": True,
                },
            ]
        )

        connector.browser = browser

        result = (
            connector
            .set_message_composer_text(
                "Mensaje prueba"
            )
        )

        self.assertEqual(
            browser.send_keys_calls,
            [
                (
                    MESSAGE_COMPOSER_SELECTOR,
                    "Mensaje prueba",
                )
            ],
        )

        self.assertTrue(
            result["send_found"]
        )

    def test_set_message_composer_text_refuses_existing_draft(
        self,
    ):
        connector = (
            WhatsAppConnector()
        )

        connector.browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "BORRADOR",
                    "send_found": True,
                }
            ]
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "borrador previo",
        ):
            connector.set_message_composer_text(
                "Nuevo"
            )

    def test_clear_empty_composer_is_noop(
        self,
    ):
        connector = (
            WhatsAppConnector()
        )

        browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "",
                    "send_found": False,
                }
            ]
        )

        connector.browser = browser

        state = (
            connector
            .clear_message_composer()
        )

        self.assertEqual(
            state["text"],
            "",
        )

        self.assertEqual(
            browser.element._tab.commands,
            [],
        )

    @patch(
        "backend.automation.connectors."
        "whatsapp_connector."
        "cdp_input.dispatch_key_event"
    )
    def test_clear_composer_dispatches_ctrl_a_and_backspace(
        self,
        dispatch,
    ):
        sequence = []

        def fake_dispatch(
            event_type,
            **kwargs,
        ):
            event = {
                "event_type": event_type,
                **kwargs,
            }

            sequence.append(
                event
            )

            return event

        dispatch.side_effect = (
            fake_dispatch
        )

        connector = (
            WhatsAppConnector()
        )

        browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "Mensaje prueba",
                    "send_found": True,
                },
                {
                    "found": True,
                    "text": "",
                    "send_found": False,
                },
            ]
        )

        connector.browser = browser

        result = (
            connector
            .clear_message_composer()
        )

        self.assertTrue(
            browser.element.focused
        )

        self.assertEqual(
            len(sequence),
            6,
        )

        self.assertEqual(
            sequence[0][
                "key"
            ],
            "Control",
        )

        self.assertEqual(
            sequence[1][
                "key"
            ],
            "a",
        )

        self.assertEqual(
            sequence[1][
                "modifiers"
            ],
            2,
        )

        self.assertEqual(
            sequence[4][
                "key"
            ],
            "Backspace",
        )

        self.assertEqual(
            result["text"],
            "",
        )

        self.assertFalse(
            result["send_found"]
        )

    @staticmethod
    def _message(
        provider_message_id,
        *,
        direction,
        body_text,
        status=MESSAGE_STATUS_SENT,
    ):
        return WhatsAppMessageSnapshot(
            provider_message_id=(
                provider_message_id
            ),
            direction=direction,
            body_text=body_text,
            provider_timestamp=(
                "2026-08-12T12:12:00"
            ),
            message_type=(
                MESSAGE_TYPE_TEXT
            ),
            provider_status=status,
            sender=None,
            metadata={},
        )

    def test_send_text_message_returns_new_outbound_snapshot(
        self,
    ):
        connector = (
            WhatsAppConnector()
        )

        browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "",
                    "send_found": False,
                },
                {
                    "found": True,
                    "text": "Hola",
                    "send_found": True,
                },
            ]
        )

        connector.browser = browser

        old_message = self._message(
            "OLD-1",
            direction=(
                MESSAGE_DIRECTION_INBOUND
            ),
            body_text="Anterior",
            status=(
                MESSAGE_STATUS_RECEIVED
            ),
        )

        sent_message = self._message(
            "NEW-1",
            direction=(
                MESSAGE_DIRECTION_OUTBOUND
            ),
            body_text="Hola",
        )

        snapshot_batches = iter(
            [
                [
                    old_message,
                ],
                [
                    old_message,
                    sent_message,
                ],
            ]
        )

        connector.list_visible_message_snapshots = (
            lambda limit=200:
                next(
                    snapshot_batches
                )
        )

        result = (
            connector
            .send_text_message(
                "Hola"
            )
        )

        self.assertEqual(
            result.provider_message_id,
            "NEW-1",
        )

        self.assertEqual(
            result.direction,
            MESSAGE_DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            result.body_text,
            "Hola",
        )

        self.assertEqual(
            browser.element.mouse_click_count,
            1,
        )

        self.assertEqual(
            browser.send_keys_calls,
            [
                (
                    MESSAGE_COMPOSER_SELECTOR,
                    "Hola",
                )
            ],
        )

    def test_send_text_message_ignores_concurrent_inbound(
        self,
    ):
        connector = (
            WhatsAppConnector()
        )

        browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "",
                    "send_found": False,
                },
                {
                    "found": True,
                    "text": "Respuesta CRM",
                    "send_found": True,
                },
            ]
        )

        connector.browser = browser

        old_message = self._message(
            "OLD-1",
            direction=(
                MESSAGE_DIRECTION_INBOUND
            ),
            body_text="Anterior",
            status=(
                MESSAGE_STATUS_RECEIVED
            ),
        )

        concurrent_inbound = self._message(
            "NEW-IN-1",
            direction=(
                MESSAGE_DIRECTION_INBOUND
            ),
            body_text="Mensaje simultáneo",
            status=(
                MESSAGE_STATUS_RECEIVED
            ),
        )

        sent_message = self._message(
            "NEW-OUT-1",
            direction=(
                MESSAGE_DIRECTION_OUTBOUND
            ),
            body_text="Respuesta CRM",
        )

        snapshot_batches = iter(
            [
                [
                    old_message,
                ],
                [
                    old_message,
                    concurrent_inbound,
                    sent_message,
                ],
            ]
        )

        connector.list_visible_message_snapshots = (
            lambda limit=200:
                next(
                    snapshot_batches
                )
        )

        result = (
            connector
            .send_text_message(
                "Respuesta CRM"
            )
        )

        self.assertEqual(
            result.provider_message_id,
            "NEW-OUT-1",
        )

    def test_send_text_message_rejects_ambiguous_confirmation(
        self,
    ):
        connector = (
            WhatsAppConnector()
        )

        browser = FakeBrowser(
            states=[
                {
                    "found": True,
                    "text": "",
                    "send_found": False,
                },
                {
                    "found": True,
                    "text": "Duplicado",
                    "send_found": True,
                },
            ]
        )

        connector.browser = browser

        first = self._message(
            "NEW-1",
            direction=(
                MESSAGE_DIRECTION_OUTBOUND
            ),
            body_text="Duplicado",
        )

        second = self._message(
            "NEW-2",
            direction=(
                MESSAGE_DIRECTION_OUTBOUND
            ),
            body_text="Duplicado",
        )

        snapshot_batches = iter(
            [
                [],
                [
                    first,
                    second,
                ],
            ]
        )

        connector.list_visible_message_snapshots = (
            lambda limit=200:
                next(
                    snapshot_batches
                )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Confirmación ambigua",
        ):
            connector.send_text_message(
                "Duplicado"
            )

        self.assertEqual(
            browser.element.mouse_click_count,
            1,
        )

    def test_send_text_message_uses_send_selector(
        self,
    ):
        class SelectorBrowser(
            FakeBrowser
        ):
            def __init__(
                self,
            ):
                super().__init__(
                    states=[
                        {
                            "found": True,
                            "text": "",
                            "send_found": False,
                        },
                        {
                            "found": True,
                            "text": "Hola",
                            "send_found": True,
                        },
                    ]
                )

                self.find_selectors = []

            def find_element(
                self,
                selector,
            ):
                self.find_selectors.append(
                    selector
                )

                return self.element

        connector = (
            WhatsAppConnector()
        )

        browser = SelectorBrowser()

        connector.browser = browser

        sent_message = self._message(
            "NEW-1",
            direction=(
                MESSAGE_DIRECTION_OUTBOUND
            ),
            body_text="Hola",
        )

        snapshot_batches = iter(
            [
                [],
                [
                    sent_message,
                ],
            ]
        )

        connector.list_visible_message_snapshots = (
            lambda limit=200:
                next(
                    snapshot_batches
                )
        )

        connector.send_text_message(
            "Hola"
        )

        self.assertIn(
            MESSAGE_SEND_SELECTOR,
            browser.find_selectors,
        )



if __name__ == "__main__":
    unittest.main()
