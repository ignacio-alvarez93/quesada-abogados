import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.automation.connectors import (
    whatsapp_connector,
)


class FakeBrowser:
    def __init__(self, body_text):
        self.body_text = body_text

    def get_text(self, selector):
        if selector != "body":
            raise ValueError(selector)

        return self.body_text


class WhatsAppSessionContractTest(
    unittest.TestCase
):
    def test_detects_login_state(self):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser(
            "Scan this QR code "
            "to use WhatsApp on your computer"
        )

        self.assertEqual(
            connector.detect_session_status(),
            whatsapp_connector
            .SESSION_STATUS_NEEDS_LOGIN,
        )

    def test_detects_ready_state(self):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser(
            "Search or start new chat"
        )

        self.assertEqual(
            connector.detect_session_status(),
            whatsapp_connector
            .SESSION_STATUS_READY,
        )

    def test_empty_page_is_loading(self):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        connector.browser = FakeBrowser("")

        self.assertEqual(
            connector.detect_session_status(),
            whatsapp_connector
            .SESSION_STATUS_LOADING,
        )

    def test_close_uses_internal_driver_stop(self):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        class FakeDriver:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        class FakeChrome:
            def __init__(self):
                self.driver = FakeDriver()

        fake_browser = FakeChrome()
        connector.browser = fake_browser

        result = connector.close()

        self.assertTrue(result)
        self.assertTrue(
            fake_browser.driver.stopped
        )

    def test_profile_directory_is_local_runtime(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            fake_root = Path(temp)

            with patch(
                "backend.automation.connectors."
                "whatsapp_connector."
                "get_project_root",
                return_value=fake_root,
            ):
                profile = (
                    whatsapp_connector
                    .get_whatsapp_profile_dir(
                        "whatsapp_dev"
                    )
                )

            self.assertEqual(
                profile,
                fake_root
                / "data"
                / "browser_profiles"
                / "whatsapp_dev",
            )

            self.assertTrue(
                profile.exists()
            )


if __name__ == "__main__":
    unittest.main()
