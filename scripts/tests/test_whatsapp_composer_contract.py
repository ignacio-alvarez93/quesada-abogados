import asyncio
import unittest
from unittest.mock import patch

from backend.automation.connectors.whatsapp_connector import (
    MESSAGE_COMPOSER_SELECTOR,
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

    async def focus_async(
        self,
    ):
        self.focused = True


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
        if (
            selector
            != MESSAGE_COMPOSER_SELECTOR
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


if __name__ == "__main__":
    unittest.main()
