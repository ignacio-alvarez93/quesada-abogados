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
    mercurio_connector as connector_module,
)
from backend.automation.connectors.mercurio_connector import (
    MercurioConnector,
)


CONNECTOR_PATH = Path(
    "backend/automation/connectors/mercurio_connector.py"
)

RUNNER_PATH = Path(
    "app/run_presentacion_asistida.py"
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


class MercurioSessionContractTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        FakeGovernedSession.instances = []

        self.temp_dir = tempfile.TemporaryDirectory()

        self.addCleanup(
            self.temp_dir.cleanup
        )

    def _connector(
        self,
    ):
        return MercurioConnector(
            session_dir=self.temp_dir.name,
            expediente_id="TEST-1",
            headless=False,
            browser_session_factory=(
                FakeGovernedSession
            ),
        )

    def test_start_uses_assisted_governed_session(
        self,
    ):
        connector = self._connector()

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
            browser = connector.start_browser(
                "about:blank"
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
            "mercurio",
        )

        self.assertEqual(
            session.config.mode,
            BrowserSessionMode.ASSISTED,
        )

        self.assertFalse(
            session.config.headless
        )

        self.assertEqual(
            opened,
            [
                (
                    session.browser,
                    "about:blank",
                )
            ],
        )

    def test_optional_profile_is_forwarded_generically(
        self,
    ):
        connector = MercurioConnector(
            session_dir=self.temp_dir.name,
            expediente_id="TEST-PROFILE",
            profile_key=" assisted_test ",
            headless=False,
            browser_session_factory=(
                FakeGovernedSession
            ),
        )

        session = (
            connector._build_browser_session()
        )

        self.assertEqual(
            connector.profile_key,
            "assisted_test",
        )

        self.assertEqual(
            session.config.profile_key,
            "assisted_test",
        )

        self.assertIs(
            session.profile_resolver,
            connector_module
            .get_browser_profile_dir,
        )

    def test_close_delegates_to_governed_close(
        self,
    ):
        connector = self._connector()

        original = (
            connector_module.open_url
        )

        connector_module.open_url = (
            lambda browser, url: None
        )

        try:
            connector.start_browser(
                "about:blank"
            )

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
            connector.close_browser()
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
        connector = self._connector()

        unmanaged = object()

        connector.browser = unmanaged

        self.assertFalse(
            connector.close_browser()
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

    def test_connector_has_no_direct_quit_close_stop_calls(
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
            if (
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

    def test_runner_delegates_exit_to_connector(
        self,
    ):
        source = RUNNER_PATH.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "connector.close_browser()",
            source,
        )

        tree = ast.parse(
            source
        )

        raw_browser_shutdowns = []

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
                    ast.Name,
                )
                and owner.id
                == "browser"
            ):
                raw_browser_shutdowns.append(
                    (
                        node.func.attr,
                        node.lineno,
                    )
                )

        self.assertEqual(
            raw_browser_shutdowns,
            [],
        )


if __name__ == "__main__":
    unittest.main()
