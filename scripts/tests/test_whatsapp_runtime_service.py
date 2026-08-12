import unittest

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_READY,
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
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
        self.close_calls = 0
        self.dismiss_calls = 0

        self.status = (
            SESSION_STATUS_READY
        )

        self.sent = []
        self.sync_snapshots = []

        self.__class__.instances.append(
            self
        )

    def start(
        self,
    ):
        self.start_calls += 1
        self.browser = object()
        return self.browser

    def detect_session_status(
        self,
    ):
        return self.status

    def dismiss_known_overlays(
        self,
    ):
        self.dismiss_calls += 1

        return {
            "known_closed": 0,
            "unknown": [],
        }

    def close(
        self,
    ):
        self.close_calls += 1
        self.browser = None
        return True

    def send_text_message(
        self,
        text,
        *,
        timeout=10,
    ):
        self.sent.append(
            (
                text,
                timeout,
            )
        )

        raise RuntimeError(
            "No debe probarse transporte real aquí"
        )

    def list_visible_message_snapshots(
        self,
        *,
        limit=200,
    ):
        return list(
            self.sync_snapshots[
                -int(limit):
            ]
        )


class FakeCommunicationService:
    pass


class WhatsAppRuntimeServiceTest(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        FakeConnector.instances = []

    def _runtime(
        self,
    ):
        return WhatsAppRuntimeService(
            profile_key="test_profile",
            headless=True,
            communication_service=(
                FakeCommunicationService()
            ),
            connector_factory=(
                FakeConnector
            ),
        )

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
            len(
                FakeConnector.instances
            ),
            0,
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

    def test_ensure_ready_reuses_runtime(
        self,
    ):
        runtime = self._runtime()

        first = runtime.ensure_ready(
            wait_timeout=1,
        )

        second = runtime.ensure_ready(
            wait_timeout=1,
        )

        self.assertIs(
            first,
            second,
        )

        self.assertEqual(
            first.start_calls,
            1,
        )

        self.assertEqual(
            first.dismiss_calls,
            2,
        )

    def test_status_before_start(
        self,
    ):
        runtime = self._runtime()

        self.assertEqual(
            runtime.get_status(),
            "NOT_STARTED",
        )

    def test_close_resets_runtime(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        self.assertTrue(
            runtime.close()
        )

        self.assertEqual(
            connector.close_calls,
            1,
        )

        self.assertIsNone(
            runtime.connector
        )

        self.assertFalse(
            runtime.started
        )

        replacement = runtime.start()

        self.assertIsNot(
            replacement,
            connector,
        )

        self.assertEqual(
            len(
                FakeConnector.instances
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
