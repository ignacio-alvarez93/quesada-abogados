import unittest
from unittest.mock import patch

from backend.automation.connectors.whatsapp_connector import (
    CHAT_KIND_GROUP,
    CHAT_KIND_INDIVIDUAL,
    WhatsAppConnector,
)


class FakeBrowser:
    def __init__(
        self,
    ):
        self.composer_found = True

    def evaluate(
        self,
        script,
    ):
        return self.composer_found


class RoutingConnector(
    WhatsAppConnector
):
    def __init__(
        self,
    ):
        # Evita crear perfil real para este test.
        self.profile_key = "test"
        self.profile_dir = None
        self.headless = True
        self.browser = FakeBrowser()

        self.profile_open = True
        self.kind = (
            CHAT_KIND_INDIVIDUAL
        )
        self.observed_phone = (
            "+34 600 111 222"
        )
        self.close_calls = 0

    def open_contact_profile(
        self,
        *,
        expected_display_name=None,
        timeout=10,
    ):
        return self.profile_open

    def classify_open_profile(
        self,
    ):
        return {
            "kind": self.kind,
            "drawer_text": "",
        }

    def get_open_contact_phone(
        self,
    ):
        return self.observed_phone

    def close_contact_profile(
        self,
        *,
        timeout=5,
    ):
        self.close_calls += 1
        return True


class WhatsAppRecipientRoutingTest(
    unittest.TestCase
):
    @patch(
        "backend.automation.connectors."
        "whatsapp_connector.open_url"
    )
    def test_matching_phone_is_verified(
        self,
        open_url_mock,
    ):
        connector = RoutingConnector()

        result = (
            connector
            .open_chat_by_phone(
                "+34 600 111 222",
                timeout=1,
            )
        )

        self.assertTrue(
            result["opened"]
        )

        self.assertTrue(
            result["verified"]
        )

        self.assertIsNone(
            result["reason"]
        )

        self.assertEqual(
            result[
                "expected_phone"
            ],
            "+34600111222",
        )

        self.assertEqual(
            result[
                "observed_phone"
            ],
            "+34600111222",
        )

        self.assertEqual(
            connector.close_calls,
            1,
        )

        url = (
            open_url_mock
            .call_args
            .args[1]
        )

        self.assertEqual(
            url,
            (
                "https://web.whatsapp.com/"
                "send?phone=34600111222"
            ),
        )

    @patch(
        "backend.automation.connectors."
        "whatsapp_connector.open_url"
    )
    def test_mismatching_phone_is_rejected(
        self,
        open_url_mock,
    ):
        connector = RoutingConnector()

        connector.observed_phone = (
            "+34 600 999 888"
        )

        result = (
            connector
            .open_chat_by_phone(
                "+34 600 111 222",
                timeout=1,
            )
        )

        self.assertTrue(
            result["opened"]
        )

        self.assertFalse(
            result["verified"]
        )

        self.assertEqual(
            result["reason"],
            "PHONE_MISMATCH",
        )

        self.assertEqual(
            connector.close_calls,
            1,
        )

    @patch(
        "backend.automation.connectors."
        "whatsapp_connector.open_url"
    )
    def test_group_identity_is_rejected(
        self,
        open_url_mock,
    ):
        connector = RoutingConnector()

        connector.kind = (
            CHAT_KIND_GROUP
        )

        result = (
            connector
            .open_chat_by_phone(
                "+34 600 111 222",
                timeout=1,
            )
        )

        self.assertFalse(
            result["verified"]
        )

        self.assertEqual(
            result["reason"],
            "NOT_INDIVIDUAL_CHAT",
        )

        self.assertEqual(
            connector.close_calls,
            1,
        )

    @patch(
        "backend.automation.connectors."
        "whatsapp_connector.open_url"
    )
    def test_unverifiable_phone_is_rejected(
        self,
        open_url_mock,
    ):
        connector = RoutingConnector()

        connector.observed_phone = None

        result = (
            connector
            .open_chat_by_phone(
                "+34 600 111 222",
                timeout=1,
            )
        )

        self.assertFalse(
            result["verified"]
        )

        self.assertEqual(
            result["reason"],
            "PHONE_UNVERIFIABLE",
        )

    @patch(
        "backend.automation.connectors."
        "whatsapp_connector.open_url"
    )
    def test_invalid_expected_phone_never_navigates(
        self,
        open_url_mock,
    ):
        connector = RoutingConnector()

        with self.assertRaises(
            ValueError
        ):
            connector.open_chat_by_phone(
                "abc",
                timeout=1,
            )

        open_url_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
