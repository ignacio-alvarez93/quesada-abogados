from types import SimpleNamespace
import threading
import time
import unittest

from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


class WatchRuntime(
    WhatsAppRuntimeService
):
    def __init__(
        self,
    ):
        super().__init__(
            communication_service=object(),
            call_service=None,
            connector_factory=object,
        )

        self.watch_calls = 0
        self.watch_failures_remaining = 0
        self.watch_changed = False
        self.watch_called = (
            threading.Event()
        )

    def observe_and_sync_call(
        self,
        *,
        wait_timeout=60,
    ):
        self.watch_calls += 1

        self.watch_called.set()

        if (
            self.watch_failures_remaining
            > 0
        ):
            self.watch_failures_remaining -= 1

            raise RuntimeError(
                "temporary call watch failure"
            )

        return SimpleNamespace(
            action="NOT_ACTIONABLE",
            observation=(
                SimpleNamespace(
                    changed=(
                        self.watch_changed
                    )
                )
            ),
        )


def wait_until(
    predicate,
    *,
    timeout=2.0,
):
    deadline = (
        time.time()
        + timeout
    )

    while time.time() < deadline:
        if predicate():
            return True

        time.sleep(
            0.01
        )

    return bool(
        predicate()
    )


class WhatsAppCallWatchTest(
    unittest.TestCase
):
    def test_start_is_idempotent_and_stop_is_safe(
        self,
    ):
        runtime = WatchRuntime()

        first = (
            runtime.start_call_watch(
                interval_seconds=0.05,
                wait_timeout=1,
            )
        )

        second = (
            runtime.start_call_watch(
                interval_seconds=0.05,
                wait_timeout=1,
            )
        )

        self.assertIs(
            first,
            second,
        )

        self.assertTrue(
            runtime.watch_called.wait(
                timeout=1
            )
        )

        self.assertTrue(
            runtime.call_watch_running
        )

        self.assertTrue(
            runtime.stop_call_watch()
        )

        self.assertFalse(
            runtime.call_watch_running
        )


    def test_watcher_stores_last_result(
        self,
    ):
        runtime = WatchRuntime()

        runtime.start_call_watch(
            interval_seconds=0.05,
            wait_timeout=1,
        )

        self.assertTrue(
            runtime.watch_called.wait(
                timeout=1
            )
        )

        self.assertTrue(
            wait_until(
                lambda: (
                    runtime
                    .call_watch_last_result
                    is not None
                )
            )
        )

        result = (
            runtime
            .call_watch_last_result
        )

        self.assertEqual(
            result.action,
            "NOT_ACTIONABLE",
        )

        runtime.stop_call_watch()


    def test_changed_observation_dispatches_callback(
        self,
    ):
        runtime = WatchRuntime()
        runtime.watch_changed = True

        callback_called = (
            threading.Event()
        )

        received = []

        def on_change(
            result,
        ):
            received.append(
                result
            )

            callback_called.set()

        runtime.start_call_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=on_change,
        )

        self.assertTrue(
            callback_called.wait(
                timeout=1
            )
        )

        self.assertGreaterEqual(
            len(
                received
            ),
            1,
        )

        runtime.stop_call_watch()


    def test_transient_failure_does_not_kill_watcher(
        self,
    ):
        runtime = WatchRuntime()
        runtime.watch_failures_remaining = 1

        runtime.start_call_watch(
            interval_seconds=0.05,
            wait_timeout=1,
        )

        self.assertTrue(
            wait_until(
                lambda: (
                    runtime.watch_calls
                    >= 2
                )
            )
        )

        self.assertTrue(
            runtime.call_watch_running
        )

        error = (
            runtime
            .call_watch_last_error
        )

        self.assertIsNotNone(
            error
        )

        self.assertEqual(
            error[
                "stage"
            ],
            "WATCH",
        )

        runtime.stop_call_watch()


    def test_callback_failure_is_diagnostic_and_watcher_survives(
        self,
    ):
        runtime = WatchRuntime()
        runtime.watch_changed = True

        callback_calls = []

        def broken_callback(
            result,
        ):
            callback_calls.append(
                result
            )

            raise RuntimeError(
                "consumer failed"
            )

        runtime.start_call_watch(
            interval_seconds=0.05,
            wait_timeout=1,
            on_change=broken_callback,
        )

        self.assertTrue(
            wait_until(
                lambda: (
                    len(
                        callback_calls
                    )
                    >= 1
                )
            )
        )

        self.assertTrue(
            runtime.call_watch_running
        )

        self.assertTrue(
            wait_until(
                lambda: (
                    runtime
                    .call_watch_last_error
                    is not None
                )
            )
        )

        self.assertEqual(
            runtime
            .call_watch_last_error[
                "stage"
            ],
            "CALLBACK",
        )

        runtime.stop_call_watch()


    def test_close_stops_call_watcher(
        self,
    ):
        runtime = WatchRuntime()

        runtime.start_call_watch(
            interval_seconds=0.05,
            wait_timeout=1,
        )

        self.assertTrue(
            runtime.watch_called.wait(
                timeout=1
            )
        )

        self.assertTrue(
            runtime.call_watch_running
        )

        runtime.close()

        self.assertFalse(
            runtime.call_watch_running
        )


if __name__ == "__main__":
    unittest.main()
