import ast
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from backend.automation.browser_contracts import (
    BrowserSessionMode,
    BrowserShutdownMode,
)
from backend.automation.connectors import (
    dehu_connector as connector_module,
)
from backend.automation.connectors.dehu_connector import (
    DEHU_URL,
    DehuConnector,
    get_dehu_profile_dir,
)


CONNECTOR_PATH = Path(
    "backend/automation/connectors/dehu_connector.py"
)


class FakeGovernedSession:
    instances = []

    def __init__(
        self,
        *,
        config,
        profile_resolver=None,
    ):
        self.config = config
        self.profile_resolver = (
            profile_resolver
        )

        self.browser = object()
        self.start_calls = 0
        self.shutdown_calls = []

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
        self.shutdown_calls.append(
            mode
        )

        return SimpleNamespace(
            has_error=False,
            control_released=True,
            browser_closed=True,
        )


class DehuSessionContractTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        FakeGovernedSession.instances = []

        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.addCleanup(
            self.temp_dir.cleanup
        )

    def _connector(
        self,
        *,
        profile_key="dehu",
    ):
        return DehuConnector(
            session_dir=(
                self.temp_dir.name
            ),
            profile_key=profile_key,
            headless=False,
            browser_session_factory=(
                FakeGovernedSession
            ),
        )

    def test_start_uses_persistent_governed_session(
        self,
    ):
        connector = (
            self._connector()
        )

        opened = []

        original = (
            connector_module.open_url
        )

        connector_module.open_url = (
            lambda browser, url:
                opened.append(
                    (
                        browser,
                        url,
                    )
                )
        )

        try:
            browser = (
                connector.start()
            )

        finally:
            connector_module.open_url = (
                original
            )

        self.assertEqual(
            len(
                FakeGovernedSession.instances
            ),
            1,
        )

        session = (
            FakeGovernedSession.instances[
                0
            ]
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
            session.start_calls,
            1,
        )

        self.assertEqual(
            session.config.consumer,
            "dehu",
        )

        self.assertEqual(
            session.config.mode,
            BrowserSessionMode.PERSISTENT,
        )

        self.assertEqual(
            session.config.profile_key,
            "dehu",
        )

        self.assertFalse(
            session.config.headless
        )

        self.assertIs(
            session.profile_resolver,
            get_dehu_profile_dir,
        )

        self.assertEqual(
            opened,
            [
                (
                    session.browser,
                    DEHU_URL,
                )
            ],
        )

    def test_profile_resolver_uses_logical_profile_key(
        self,
    ):
        path = (
            get_dehu_profile_dir(
                "dehu_contract_test"
            )
        )

        try:
            self.assertEqual(
                path.name,
                "dehu_contract_test",
            )

            self.assertEqual(
                path.parent.name,
                "browser_profiles",
            )

            self.assertTrue(
                path.exists()
            )

        finally:
            try:
                path.rmdir()
            except OSError:
                pass

    def test_close_delegates_to_governed_close(
        self,
    ):
        connector = (
            self._connector()
        )

        original = (
            connector_module.open_url
        )

        connector_module.open_url = (
            lambda browser, url: None
        )

        try:
            connector.start()

        finally:
            connector_module.open_url = (
                original
            )

        session = (
            FakeGovernedSession.instances[
                0
            ]
        )

        self.assertTrue(
            connector.close()
        )

        self.assertEqual(
            session.shutdown_calls,
            [
                BrowserShutdownMode.CLOSE
            ],
        )

        self.assertIsNone(
            connector.browser
        )

        self.assertIsNone(
            connector._browser_session
        )

    def test_unmanaged_browser_is_not_destroyed(
        self,
    ):
        connector = (
            self._connector()
        )

        unmanaged = object()

        connector.browser = (
            unmanaged
        )

        self.assertFalse(
            connector.close()
        )

        self.assertIs(
            connector.browser,
            unmanaged,
        )

    def test_connector_has_no_direct_common_factory_dependency(
        self,
    ):
        tree = ast.parse(
            CONNECTOR_PATH.read_text(
                encoding="utf-8"
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

        self.assertNotIn(
            "start_seleniumbase_chrome",
            imported_names,
        )

    def test_connector_has_no_direct_raw_shutdown_calls(
        self,
    ):
        tree = ast.parse(
            CONNECTOR_PATH.read_text(
                encoding="utf-8"
            )
        )

        forbidden = []

        for node in ast.walk(
            tree
        ):
            if not (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Attribute,
                )
                and node.func.attr
                in {
                    "quit",
                    "close",
                    "stop",
                }
            ):
                continue

            owner = (
                node.func.value
            )

            if (
                isinstance(
                    owner,
                    ast.Attribute,
                )
                and owner.attr
                == "browser"
            ):
                forbidden.append(
                    (
                        node.func.attr,
                        node.lineno,
                    )
                )

        self.assertEqual(
            forbidden,
            [],
        )


if __name__ == "__main__":
    unittest.main()
