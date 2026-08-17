import unittest
from types import SimpleNamespace

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppConnector,
)
from backend.automation.connectors.whatsapp_call_observer import (
    WHATSAPP_CALL_DIRECTION_INBOUND,
    WHATSAPP_CALL_PHASE_ABSENT,
    WHATSAPP_CALL_PHASE_CONNECTING,
    WHATSAPP_CALL_PHASE_INCOMING_RINGING,
    WhatsAppCallSnapshot,
)


class FakeElement:
    def __init__(
        self,
        *,
        error=None,
    ):
        self.click_count = 0
        self.error = error

    def mouse_click(
        self,
    ):
        self.click_count += 1

        if self.error:
            raise self.error


class FakeBrowser:
    def __init__(
        self,
        *,
        control=None,
        element=None,
    ):
        self.control = (
            control
            or {
                "found": True,
                "aria_label": "Aceptar",
                "aria_disabled": "false",
                "disabled": False,
            }
        )

        self.element = (
            element
            or FakeElement()
        )

        self.find_calls = []

    def evaluate(
        self,
        script,
    ):
        return dict(
            self.control
        )

    def find_element(
        self,
        selector,
    ):
        self.find_calls.append(
            selector
        )

        return self.element


def ringing_snapshot():
    return WhatsAppCallSnapshot(
        present=True,
        phase=(
            WHATSAPP_CALL_PHASE_INCOMING_RINGING
        ),
        direction=(
            WHATSAPP_CALL_DIRECTION_INBOUND
        ),
        provider_call_id="CALL-REAL-1",
        external_call_key="false_CALL-REAL-1",
        participant_phone="+34639156371",
        can_accept=True,
        can_reject=True,
        can_hangup=False,
        identity_complete=True,
    )


def connecting_snapshot():
    return WhatsAppCallSnapshot(
        present=True,
        phase=(
            WHATSAPP_CALL_PHASE_CONNECTING
        ),
        direction=(
            WHATSAPP_CALL_DIRECTION_INBOUND
        ),
        provider_call_id="CALL-REAL-1",
        external_call_key="false_CALL-REAL-1",
        participant_phone="+34639156371",
        can_accept=False,
        can_reject=False,
        can_hangup=True,
        identity_complete=True,
    )


def absent_snapshot():
    return WhatsAppCallSnapshot(
        present=False,
        phase=(
            WHATSAPP_CALL_PHASE_ABSENT
        ),
        direction=None,
    )


class IncomingCallConnectorActionTest(
    unittest.TestCase
):
    def connector_with_snapshots(
        self,
        snapshots,
        *,
        aria_label,
    ):
        connector = object.__new__(
            WhatsAppConnector
        )

        browser = FakeBrowser(
            control={
                "found": True,
                "aria_label":
                    aria_label,
                "aria_disabled":
                    "false",
                "disabled": False,
            }
        )

        connector.browser = browser

        queue = list(
            snapshots
        )

        connector.read_call_snapshot = (
            lambda:
                queue.pop(0)
                if len(queue) > 1
                else queue[0]
        )

        return (
            connector,
            browser,
        )


    def test_accept_clicks_once_and_confirms_connecting(
        self,
    ):
        connector, browser = (
            self.connector_with_snapshots(
                [
                    ringing_snapshot(),
                    connecting_snapshot(),
                ],
                aria_label="Aceptar",
            )
        )

        result = (
            connector.accept_incoming_call(
                expected_provider_call_id=(
                    "CALL-REAL-1"
                ),
                expected_external_call_key=(
                    "false_CALL-REAL-1"
                ),
                confirm_timeout=0,
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            result["reason"],
            "CALL_ACCEPTED",
        )

        self.assertEqual(
            browser.element.click_count,
            1,
        )


    def test_reject_clicks_once_and_confirms_absence(
        self,
    ):
        connector, browser = (
            self.connector_with_snapshots(
                [
                    ringing_snapshot(),
                    absent_snapshot(),
                ],
                aria_label="Rechazar",
            )
        )

        result = (
            connector.reject_incoming_call(
                expected_provider_call_id=(
                    "CALL-REAL-1"
                ),
                expected_external_call_key=(
                    "false_CALL-REAL-1"
                ),
                confirm_timeout=0,
            )
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            result["reason"],
            "CALL_REJECTED",
        )

        self.assertEqual(
            browser.element.click_count,
            1,
        )


    def test_stale_provider_identity_never_clicks(
        self,
    ):
        connector, browser = (
            self.connector_with_snapshots(
                [
                    ringing_snapshot(),
                ],
                aria_label="Aceptar",
            )
        )

        result = (
            connector.accept_incoming_call(
                expected_provider_call_id=(
                    "OTHER-CALL"
                ),
                confirm_timeout=0,
            )
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertFalse(
            result["clicked"]
        )

        self.assertEqual(
            browser.element.click_count,
            0,
        )

        self.assertEqual(
            result["reason"],
            "CALL_ACCEPT_IDENTITY_MISMATCH",
        )


    def test_disabled_control_never_clicks(
        self,
    ):
        connector, browser = (
            self.connector_with_snapshots(
                [
                    ringing_snapshot(),
                ],
                aria_label="Aceptar",
            )
        )

        browser.control[
            "aria_disabled"
        ] = "true"

        result = (
            connector.accept_incoming_call(
                confirm_timeout=0,
            )
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertFalse(
            result["clicked"]
        )

        self.assertEqual(
            browser.element.click_count,
            0,
        )


    def test_click_exception_is_uncertain_and_not_retried(
        self,
    ):
        connector, browser = (
            self.connector_with_snapshots(
                [
                    ringing_snapshot(),
                ],
                aria_label="Aceptar",
            )
        )

        browser.element.error = (
            RuntimeError(
                "click transport error"
            )
        )

        result = (
            connector.accept_incoming_call(
                confirm_timeout=0,
            )
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertTrue(
            result["uncertain"]
        )

        self.assertTrue(
            result["clicked"]
        )

        self.assertEqual(
            browser.element.click_count,
            1,
        )


if __name__ == "__main__":
    unittest.main()
