import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_start_uses_governed_persistent_session(
        self,
    ):
        class FakeGovernedSession:
            instances = []

            def __init__(
                self,
                *,
                config,
                profile_resolver,
            ):
                self.config = config
                self.profile_resolver = (
                    profile_resolver
                )

                self.browser = object()
                self.start_calls = 0
                self.shutdown_modes = []

                self.__class__.instances.append(
                    self
                )

            def start(
                self,
            ):
                self.start_calls += 1

                return self.browser

            def shutdown(
                self,
                mode,
            ):
                self.shutdown_modes.append(
                    mode
                )

                return SimpleNamespace(
                    has_error=False,
                    control_released=True,
                    browser_closed=True,
                )

        with patch.object(
            whatsapp_connector,
            "open_url",
        ) as open_url_mock:
            connector = (
                whatsapp_connector
                .WhatsAppConnector(
                    profile_key="whatsapp_dev",
                    headless=True,
                    browser_session_factory=(
                        FakeGovernedSession
                    ),
                )
            )

            browser = connector.start()

        self.assertEqual(
            len(
                FakeGovernedSession.instances
            ),
            1,
        )

        session = (
            FakeGovernedSession.instances[0]
        )

        self.assertIs(
            browser,
            session.browser,
        )

        self.assertIs(
            connector.browser,
            session.browser,
        )

        self.assertEqual(
            session.config.consumer,
            "whatsapp",
        )

        self.assertEqual(
            session.config.mode.value,
            "PERSISTENT",
        )

        self.assertEqual(
            session.config.profile_key,
            "whatsapp_dev",
        )

        self.assertTrue(
            session.config.headless
        )

        self.assertIs(
            session.profile_resolver,
            whatsapp_connector
            .get_whatsapp_profile_dir,
        )

        self.assertEqual(
            session.start_calls,
            1,
        )

        open_url_mock.assert_called_once_with(
            browser,
            whatsapp_connector.WHATSAPP_WEB_URL,
        )

    def test_close_delegates_to_governed_session(
        self,
    ):
        class FakeGovernedSession:
            instances = []

            def __init__(
                self,
                *,
                config,
                profile_resolver,
            ):
                self.config = config
                self.profile_resolver = (
                    profile_resolver
                )

                self.browser = object()
                self.shutdown_modes = []

                self.__class__.instances.append(
                    self
                )

            def start(
                self,
            ):
                return self.browser

            def shutdown(
                self,
                mode,
            ):
                self.shutdown_modes.append(
                    mode
                )

                return SimpleNamespace(
                    has_error=False,
                    control_released=True,
                    browser_closed=True,
                )

        with patch.object(
            whatsapp_connector,
            "open_url",
        ):
            connector = (
                whatsapp_connector
                .WhatsAppConnector(
                    browser_session_factory=(
                        FakeGovernedSession
                    )
                )
            )

            connector.start()

        session = (
            FakeGovernedSession.instances[0]
        )

        result = connector.close()

        self.assertTrue(
            result
        )

        self.assertEqual(
            len(
                session.shutdown_modes
            ),
            1,
        )

        self.assertEqual(
            session.shutdown_modes[0].value,
            "CLOSE",
        )

        self.assertIsNone(
            connector.browser
        )

        self.assertIsNone(
            connector._browser_session
        )

    def test_close_never_stops_unmanaged_browser(
        self,
    ):
        connector = (
            whatsapp_connector
            .WhatsAppConnector()
        )

        class FakeDriver:
            def __init__(
                self,
            ):
                self.stopped = False

            def stop(
                self,
            ):
                self.stopped = True

                raise AssertionError(
                    "driver.stop() no debe ejecutarse"
                )

        class FakeChrome:
            def __init__(
                self,
            ):
                self.driver = FakeDriver()

        fake_browser = FakeChrome()

        connector.browser = (
            fake_browser
        )

        result = connector.close()

        self.assertFalse(
            result
        )

        self.assertFalse(
            fake_browser.driver.stopped
        )

        self.assertIs(
            connector.browser,
            fake_browser,
        )

    def test_connector_has_no_direct_browser_factory_dependency(
        self,
    ):
        source_path = (
            Path(
                whatsapp_connector.__file__
            )
            .resolve()
        )

        tree = ast.parse(
            source_path.read_text(
                encoding="utf-8",
            )
        )

        imported_names = []

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.ImportFrom,
            ):
                imported_names.extend(
                    alias.name
                    for alias in node.names
                )

            elif isinstance(
                node,
                ast.Import,
            ):
                imported_names.extend(
                    alias.name
                    for alias in node.names
                )

        self.assertNotIn(
            "start_seleniumbase_chrome",
            imported_names,
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
