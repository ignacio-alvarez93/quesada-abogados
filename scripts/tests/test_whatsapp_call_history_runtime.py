import unittest

from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


class FakeConnector:
    def __init__(self):
        self.read_count = 0

    def read_visible_call_history(self):
        self.read_count += 1

        return {
            "version": "CALL-SYNC-4A",
            "read_only": True,
            "rows_scanned": 2,
            "items": [],
            "skipped_rows": [],
        }


class RuntimeProbe:
    _read_visible_call_history_impl = (
        WhatsAppRuntimeService
        ._read_visible_call_history_impl
    )

    def __init__(self):
        self.connector = FakeConnector()
        self.ready_timeouts = []
        self.serialized_calls = []

    def _ensure_ready_impl(
        self,
        *,
        wait_timeout=60,
    ):
        self.ready_timeouts.append(
            wait_timeout
        )

        return self.connector

    def _run_serialized(
        self,
        callable_,
        *args,
        **kwargs,
    ):
        self.serialized_calls.append({
            "callable":
                callable_.__name__,
            "args":
                args,
            "kwargs":
                kwargs,
        })

        return callable_(
            *args,
            **kwargs,
        )


class WhatsAppCallHistoryRuntimeTest(
    unittest.TestCase
):
    def test_impl_ensures_ready_and_delegates(
        self,
    ):
        runtime = RuntimeProbe()

        result = (
            WhatsAppRuntimeService
            ._read_visible_call_history_impl(
                runtime,
                wait_timeout=7,
            )
        )

        self.assertEqual(
            runtime.ready_timeouts,
            [7],
        )

        self.assertEqual(
            runtime.connector.read_count,
            1,
        )

        self.assertTrue(
            result["read_only"]
        )

    def test_public_api_uses_serialized_worker(
        self,
    ):
        runtime = RuntimeProbe()

        result = (
            WhatsAppRuntimeService
            .read_visible_call_history(
                runtime,
                wait_timeout=9,
            )
        )

        self.assertEqual(
            len(
                runtime.serialized_calls
            ),
            1,
        )

        call = (
            runtime.serialized_calls[0]
        )

        self.assertEqual(
            call["callable"],
            "_read_visible_call_history_impl",
        )

        self.assertEqual(
            call["kwargs"],
            {
                "wait_timeout": 9,
            },
        )

        self.assertEqual(
            runtime.ready_timeouts,
            [9],
        )

        self.assertEqual(
            runtime.connector.read_count,
            1,
        )

        self.assertEqual(
            result["version"],
            "CALL-SYNC-4A",
        )


if __name__ == "__main__":
    unittest.main()
