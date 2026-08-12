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

        self.open_phone_calls = []
        self.routing_result = {
            "opened": True,
            "verified": True,
            "reason": None,
            "expected_phone": (
                "+34600111222"
            ),
            "observed_phone": (
                "+34600111222"
            ),
        }

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

    def open_chat_by_phone(
        self,
        phone,
        *,
        timeout=15,
    ):
        self.open_phone_calls.append(
            (
                phone,
                timeout,
            )
        )

        return dict(
            self.routing_result
        )

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


class FakeThread:
    def __init__(
        self,
        *,
        thread_id=7,
        external_address=(
            "+34 600 111 222"
        ),
    ):
        self.id = thread_id
        self.external_address = (
            external_address
        )


class FakeCommunicationService:
    def __init__(
        self,
    ):
        self.thread = FakeThread()

    def get_thread(
        self,
        thread_id,
    ):
        if (
            self.thread
            and int(thread_id)
            == int(self.thread.id)
        ):
            return self.thread

        return None


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


    def test_verify_and_open_thread_routes_by_persisted_phone(
        self,
    ):
        runtime = self._runtime()

        result = (
            runtime
            .verify_and_open_thread(
                7,
                wait_timeout=1,
                routing_timeout=9,
            )
        )

        connector = runtime.connector

        self.assertEqual(
            connector.open_phone_calls,
            [
                (
                    "+34 600 111 222",
                    9,
                )
            ],
        )

        self.assertTrue(
            result[
                "routing"
            ][
                "verified"
            ]
        )

        self.assertEqual(
            result[
                "thread"
            ].id,
            7,
        )

    def test_verify_and_open_thread_rejects_identity_mismatch(
        self,
    ):
        runtime = self._runtime()

        connector = runtime.start()

        connector.routing_result = {
            "opened": True,
            "verified": False,
            "reason":
                "PHONE_MISMATCH",
            "expected_phone":
                "+34600111222",
            "observed_phone":
                "+34600999888",
        }

        with self.assertRaises(
            RuntimeError
        ) as raised:
            runtime.verify_and_open_thread(
                7,
                wait_timeout=1,
            )

        self.assertIn(
            "PHONE_MISMATCH",
            str(
                raised.exception
            ),
        )

    def test_verify_and_open_thread_rejects_missing_phone(
        self,
    ):
        runtime = self._runtime()

        runtime.communication_service.thread = (
            FakeThread(
                external_address=None,
            )
        )

        with self.assertRaises(
            ValueError
        ):
            runtime.verify_and_open_thread(
                7,
                wait_timeout=1,
            )

        self.assertEqual(
            runtime.connector.open_phone_calls,
            [],
        )


if __name__ == "__main__":
    unittest.main()
