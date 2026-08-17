import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


def history_item():
    return {
        "provider_call_id":
            "CALL1",

        "external_call_key":
            "false_23244480487535@lid_CALL1",

        "peer_lid":
            "23244480487535@lid",

        "peer_phone_id":
            "34639156371@c.us",

        "peer_display_name":
            "Mama",

        "provider_timestamp":
            1786892997,

        "call_duration_seconds":
            18,

        "raw_outcome":
            "Completed",

        "raw_final_outcome":
            "Completed",

        "row_state":
            "Entrante",

        "is_video":
            False,
    }


class FakeCallService:
    def __init__(self):
        self.snapshots = []

    def reconcile_provider_call(
        self,
        snapshot,
    ):
        self.snapshots.append(
            snapshot
        )

        return snapshot


class FakeConnector:
    def __init__(
        self,
        *,
        active_tab="CHATS",
        call_present=False,
        fail_history=False,
    ):
        self.active_tab = (
            active_tab
        )

        self.call_present = (
            call_present
        )

        self.fail_history = (
            fail_history
        )

        self.open_calls_count = 0
        self.open_chats_count = 0
        self.read_history_count = 0

    def read_call_snapshot(self):
        return SimpleNamespace(
            present=self.call_present
        )

    def read_primary_navigation_state(
        self,
    ):
        return {
            "chats_present":
                True,

            "calls_present":
                True,

            "chats_pressed":
                (
                    "true"
                    if self.active_tab
                    == "CHATS"
                    else "false"
                ),

            "calls_pressed":
                (
                    "true"
                    if self.active_tab
                    == "CALLS"
                    else "false"
                ),
        }

    def open_calls_tab(
        self,
        *,
        timeout=5,
    ):
        self.open_calls_count += 1
        self.active_tab = "CALLS"

        return {
            "tab": "CALLS",
            "clicked": True,
        }

    def open_chats_tab(
        self,
        *,
        timeout=5,
    ):
        self.open_chats_count += 1
        self.active_tab = "CHATS"

        return {
            "tab": "CHATS",
            "clicked": True,
        }

    def read_visible_call_history(
        self,
    ):
        self.read_history_count += 1

        if self.fail_history:
            raise RuntimeError(
                "forced history failure"
            )

        return {
            "version":
                "CALL-SYNC-4A",

            "read_only":
                True,

            "rows_scanned":
                1,

            "items": [
                history_item()
            ],

            "skipped_rows":
                [],
        }


class RuntimeProbe:
    _sync_call_history_impl = (
        WhatsAppRuntimeService
        ._sync_call_history_impl
    )

    def __init__(
        self,
        connector,
    ):
        self.connector_probe = (
            connector
        )

        self.call_service = (
            FakeCallService()
        )

        self.serialized_calls = []
        self.executor = (
            ThreadPoolExecutor(
                max_workers=1
            )
        )

    def _get_executor(
        self,
    ):
        return self.executor

    def _execute_on_worker(
        self,
        callable_,
        *args,
        **kwargs,
    ):
        return callable_(
            *args,
            **kwargs,
        )

    def _ensure_ready_impl(
        self,
        *,
        wait_timeout=60,
    ):
        return self.connector_probe

    def _run_serialized(
        self,
        callable_,
        *args,
        **kwargs,
    ):
        self.serialized_calls.append(
            callable_.__name__
        )

        return callable_(
            *args,
            **kwargs,
        )


class WhatsAppCallHistoryNavigationTest(
    unittest.TestCase
):
    def test_chats_roundtrip_and_reconcile(
        self,
    ):
        connector = FakeConnector(
            active_tab="CHATS"
        )

        runtime = RuntimeProbe(
            connector
        )

        result = (
            WhatsAppRuntimeService
            .sync_call_history(
                runtime,
                wait_timeout=9,
                navigation_timeout=3,
                dry_run=False,
            )
        )

        self.assertFalse(
            result["skipped"]
        )

        self.assertEqual(
            connector.open_calls_count,
            1,
        )

        self.assertEqual(
            connector.open_chats_count,
            1,
        )

        self.assertEqual(
            connector.active_tab,
            "CHATS",
        )

        self.assertEqual(
            len(
                runtime
                .call_service
                .snapshots
            ),
            1,
        )

        self.assertEqual(
            result["execution"][
                "reconciled"
            ],
            1,
        )

    def test_calls_tab_is_not_needlessly_restored(
        self,
    ):
        connector = FakeConnector(
            active_tab="CALLS"
        )

        runtime = RuntimeProbe(
            connector
        )

        result = (
            WhatsAppRuntimeService
            .sync_call_history(
                runtime,
                dry_run=True,
            )
        )

        self.assertFalse(
            result["skipped"]
        )

        self.assertEqual(
            connector.open_calls_count,
            0,
        )

        self.assertEqual(
            connector.open_chats_count,
            0,
        )

        self.assertEqual(
            connector.active_tab,
            "CALLS",
        )

        self.assertEqual(
            runtime.call_service.snapshots,
            [],
        )

    def test_active_call_skips_navigation(
        self,
    ):
        connector = FakeConnector(
            active_tab="CHATS",
            call_present=True,
        )

        runtime = RuntimeProbe(
            connector
        )

        result = (
            WhatsAppRuntimeService
            .sync_call_history(
                runtime,
            )
        )

        self.assertTrue(
            result["skipped"]
        )

        self.assertEqual(
            result["reason"],
            "ACTIVE_CALL",
        )

        self.assertEqual(
            connector.open_calls_count,
            0,
        )

        self.assertEqual(
            connector.read_history_count,
            0,
        )

    def test_chats_restored_even_when_history_fails(
        self,
    ):
        connector = FakeConnector(
            active_tab="CHATS",
            fail_history=True,
        )

        runtime = RuntimeProbe(
            connector
        )

        with self.assertRaises(
            RuntimeError
        ):
            (
                WhatsAppRuntimeService
                .sync_call_history(
                    runtime,
                )
            )

        self.assertEqual(
            connector.open_calls_count,
            1,
        )

        self.assertEqual(
            connector.open_chats_count,
            1,
        )

        self.assertEqual(
            connector.active_tab,
            "CHATS",
        )

    def test_public_api_is_one_serialized_operation(
        self,
    ):
        connector = FakeConnector(
            active_tab="CHATS"
        )

        runtime = RuntimeProbe(
            connector
        )

        (
            WhatsAppRuntimeService
            .sync_call_history(
                runtime,
                dry_run=True,
            )
        )

        self.assertEqual(
            runtime.serialized_calls,
            [
                "_sync_call_history_impl"
            ],
        )




class DelayedHistoryConnector(
    FakeConnector
):
    def __init__(
        self,
        *,
        empty_reads,
    ):
        super().__init__(
            active_tab="CHATS"
        )

        self.empty_reads = int(
            empty_reads
        )

    def read_visible_call_history(
        self,
    ):
        self.read_history_count += 1

        if (
            self.read_history_count
            <= self.empty_reads
        ):
            return {
                "version":
                    "CALL-SYNC-4A",

                "read_only":
                    True,

                "rows_scanned":
                    0,

                "items":
                    [],

                "skipped_rows":
                    [],
            }

        return {
            "version":
                "CALL-SYNC-4A",

            "read_only":
                True,

            "rows_scanned":
                1,

            "items": [
                history_item()
            ],

            "skipped_rows":
                [],
        }


class WhatsAppCallHistoryMaterializationTest(
    unittest.TestCase
):
    def test_waits_until_rows_are_materialized(
        self,
    ):
        connector = (
            DelayedHistoryConnector(
                empty_reads=2
            )
        )

        runtime = RuntimeProbe(
            connector
        )

        result = (
            WhatsAppRuntimeService
            .sync_call_history(
                runtime,
                navigation_timeout=1,
                dry_run=False,
            )
        )

        self.assertFalse(
            result["skipped"]
        )

        self.assertEqual(
            connector.read_history_count,
            3,
        )

        self.assertEqual(
            result["navigation"][
                "materialization_attempts"
            ],
            3,
        )

        self.assertEqual(
            result["execution"][
                "reconciled"
            ],
            1,
        )

        self.assertEqual(
            connector.active_tab,
            "CHATS",
        )


    def test_materialization_timeout_restores_chats(
        self,
    ):
        connector = (
            DelayedHistoryConnector(
                empty_reads=1000
            )
        )

        runtime = RuntimeProbe(
            connector
        )

        with self.assertRaises(
            TimeoutError
        ):
            (
                WhatsAppRuntimeService
                .sync_call_history(
                    runtime,
                    navigation_timeout=0.2,
                    dry_run=False,
                )
            )

        self.assertEqual(
            connector.open_calls_count,
            1,
        )

        self.assertEqual(
            connector.open_chats_count,
            1,
        )

        self.assertEqual(
            connector.active_tab,
            "CHATS",
        )




class WhatsAppCallHistoryAsyncSubmissionTest(
    unittest.TestCase
):
    def test_submit_uses_governed_executor(
        self,
    ):
        connector = FakeConnector(
            active_tab="CALLS"
        )

        runtime = RuntimeProbe(
            connector
        )

        try:
            future = (
                WhatsAppRuntimeService
                .submit_call_history_sync(
                    runtime,
                    dry_run=True,
                )
            )

            result = future.result(
                timeout=2
            )

        finally:
            runtime.executor.shutdown(
                wait=True
            )

        self.assertFalse(
            result["skipped"]
        )

        self.assertEqual(
            result["execution"][
                "planned"
            ],
            1,
        )

        self.assertEqual(
            result["execution"][
                "reconciled"
            ],
            0,
        )

        self.assertEqual(
            connector.open_calls_count,
            0,
        )


if __name__ == "__main__":
    unittest.main()
