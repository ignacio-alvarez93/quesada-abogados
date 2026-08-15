import ast
from pathlib import Path
import threading
import unittest

from backend.automation.connectors.dehu_connector import (
    DEHU_URL,
    normalize_dehu_portal_url,
)
from backend.services.dehu_runtime_service import (
    DehuRuntimeService,
)


RUNTIME_PATH = Path(
    "backend/services/dehu_runtime_service.py"
)


class FakeConnector:
    instances = []

    def __init__(
        self,
        *,
        profile_key,
        headless,
    ):
        self.profile_key = profile_key
        self.headless = headless

        self.browser = None

        self.start_calls = 0
        self.open_calls = []
        self.capture_calls = []
        self.close_calls = 0

        self.thread_ids = []

        self.close_result = True
        self.start_error = None

        self.__class__.instances.append(
            self
        )

    def _remember_thread(
        self,
    ):
        self.thread_ids.append(
            threading.get_ident()
        )

    def start(
        self,
    ):
        self._remember_thread()

        self.start_calls += 1
        self.browser = object()

        if self.start_error is not None:
            raise self.start_error

        return self.browser

    def open_portal(
        self,
        url=None,
    ):
        self._remember_thread()

        target = (
            url
            or DEHU_URL
        )

        self.open_calls.append(
            target
        )

        return target

    def capture(
        self,
        label,
    ):
        self._remember_thread()

        self.capture_calls.append(
            label
        )

        return {
            "label": label,
        }

    def close(
        self,
    ):
        self._remember_thread()

        self.close_calls += 1

        if not self.close_result:
            return False

        self.browser = None

        return True


class DehuRuntimeServiceTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        FakeConnector.instances = []

        self.runtimes = []

    def tearDown(
        self,
    ):
        # Evita dejar executors vivos cuando un test falle.
        for runtime in self.runtimes:
            connector = runtime.connector

            if connector is not None:
                connector.close_result = True

                try:
                    runtime.close()
                except Exception:
                    pass

    def _runtime(
        self,
    ):
        runtime = DehuRuntimeService(
            profile_key="dehu_test",
            headless=True,
            connector_factory=(
                FakeConnector
            ),
        )

        self.runtimes.append(
            runtime
        )

        return runtime

    def test_connector_is_lazy(
        self,
    ):
        runtime = self._runtime()

        self.assertIsNone(
            runtime.connector
        )

        self.assertFalse(
            runtime.started
        )

        self.assertEqual(
            FakeConnector.instances,
            [],
        )

    def test_start_reuses_single_connector(
        self,
    ):
        runtime = self._runtime()

        first = runtime.start()
        second = runtime.start()

        self.assertIs(
            first,
            second,
        )

        self.assertEqual(
            len(
                FakeConnector.instances
            ),
            1,
        )

        self.assertEqual(
            first.start_calls,
            1,
        )

        self.assertEqual(
            first.profile_key,
            "dehu_test",
        )

        self.assertTrue(
            first.headless
        )

    def test_all_browser_operations_share_worker_thread(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        worker_id = (
            runtime._worker_thread_id
        )

        runtime.open_portal(
            "https://dehu.redsara.es/test"
        )

        runtime.capture(
            "probe"
        )

        self.assertTrue(
            connector.thread_ids
        )

        self.assertEqual(
            set(
                connector.thread_ids
            ),
            {
                worker_id,
            },
        )

        self.assertNotEqual(
            worker_id,
            threading.get_ident(),
        )

    def test_open_portal_starts_runtime_lazily(
        self,
    ):
        runtime = self._runtime()

        result = runtime.open_portal(
            "https://dehu.redsara.es/test/1"
        )

        connector = runtime.connector

        self.assertTrue(
            runtime.started
        )

        self.assertEqual(
            connector.start_calls,
            1,
        )

        self.assertEqual(
            connector.open_calls,
            [
                "https://dehu.redsara.es/test/1"
            ],
        )

        self.assertEqual(
            result,
            "https://dehu.redsara.es/test/1",
        )

    def test_capture_requires_started_runtime(
        self,
    ):
        runtime = self._runtime()

        with self.assertRaises(
            RuntimeError
        ):
            runtime.capture(
                "before_start"
            )

        # capture() creó el worker, pero no un connector.
        self.assertIsNone(
            runtime.connector
        )

    def test_close_resets_runtime_and_executor(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        worker_id = (
            runtime._worker_thread_id
        )

        self.assertTrue(
            runtime.close()
        )

        self.assertEqual(
            connector.close_calls,
            1,
        )

        self.assertEqual(
            connector.thread_ids[-1],
            worker_id,
        )

        self.assertIsNone(
            runtime.connector
        )

        self.assertIsNone(
            runtime._executor
        )

        self.assertIsNone(
            runtime._worker_thread_id
        )

        self.assertFalse(
            runtime.started
        )

    def test_close_failure_preserves_owner_and_executor(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()
        executor = runtime._executor

        connector.close_result = False

        self.assertFalse(
            runtime.close()
        )

        self.assertIs(
            runtime.connector,
            connector,
        )

        self.assertIs(
            runtime._executor,
            executor,
        )

        self.assertTrue(
            runtime.started
        )

        connector.close_result = True

        self.assertTrue(
            runtime.close()
        )

        self.assertIsNone(
            runtime.connector
        )

        self.assertIsNone(
            runtime._executor
        )

    def test_start_failure_preserves_connector_for_governed_close(
        self,
    ):
        runtime = self._runtime()

        connector = (
            runtime._build_connector()
        )

        connector.start_error = (
            RuntimeError(
                "forced-start-error"
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "forced-start-error",
        ):
            runtime.start()

        # El fake representa el caso:
        # BrowserSession arrancó pero una operación posterior
        # de navegación falló.
        self.assertIs(
            runtime.connector,
            connector,
        )

        self.assertIsNotNone(
            runtime._executor
        )

        self.assertIsNotNone(
            connector.browser
        )

        connector.start_error = None

        self.assertTrue(
            runtime.close()
        )

    def test_dehu_url_allowlist(
        self,
    ):
        accepted = [
            "https://dehu.redsara.es/",
            "https://dehu.redsara.es/test/1",
            (
                "https://DEHU.REDSARA.ES/"
                "communications?id=123"
            ),
            "https://dehu.redsara.es:443/test",
        ]

        for url in accepted:
            with self.subTest(
                url=url
            ):
                self.assertEqual(
                    normalize_dehu_portal_url(
                        url
                    ),
                    url,
                )

        rejected = [
            "http://dehu.redsara.es/",
            "https://example.com/",
            (
                "https://dehu.redsara.es."
                "example.com/"
            ),
            "javascript:alert(1)",
            "file:///C:/temp/test",
            (
                "https://user:password@"
                "dehu.redsara.es/"
            ),
            "https://dehu.redsara.es:444/",
        ]

        for url in rejected:
            with self.subTest(
                url=url
            ):
                with self.assertRaises(
                    ValueError
                ):
                    normalize_dehu_portal_url(
                        url
                    )

    def test_runtime_has_no_seleniumbase_dependency(
        self,
    ):
        tree = ast.parse(
            RUNTIME_PATH.read_text(
                encoding="utf-8"
            )
        )

        imported = []

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                imported.extend(
                    alias.name
                    for alias in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                imported.append(
                    node.module
                    or ""
                )

        self.assertFalse(
            any(
                "seleniumbase"
                in name.lower()
                for name in imported
            )
        )


if __name__ == "__main__":
    unittest.main()
