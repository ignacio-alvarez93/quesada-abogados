import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.acquisition.adapter import CollectorSourceAdapter
from backend.trend_intelligence.acquisition.contracts import (
    CollectorBatch,
    CollectorError,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_NETWORK,
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCESS,
)
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources.base import TrendObservationInput


class _FakeCollector:
    collector_key = "FAKE_COLLECTOR"
    collector_version = "1.0.0"
    provider = "FAKE"

    def __init__(self, batches):
        self._batches = list(batches)
        self.seen_cursors = []

    def collect(self, *, cursor=None):
        self.seen_cursors.append(cursor)
        return self._batches.pop(0)


class _FailingCollector:
    collector_key = "FAKE_COLLECTOR"
    collector_version = "1.0.0"
    provider = "FAKE"

    def collect(self, *, cursor=None):
        raise CollectorError("network down", classification=ERROR_NETWORK)


class _PassthroughNormalizer:
    def normalize(self, raw_item):
        payload = raw_item.raw_payload
        return TrendObservationInput(
            observation_type="ARTICLE",
            external_id=payload["id"],
            title=payload["id"],
            observed_at="2026-09-21T08:00:00+00:00",
        )


class TrendIntelligenceAcquisitionLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "lifecycle.db"
        self.repository = SQLiteTrendIntelligenceRepository(self.db)
        self.service = TrendIntelligenceService(repository=self.repository)
        self.service.ensure_schema()

        self.service.create_source(
            code="FAKE_SOURCE",
            name="Fake Source",
            source_type="RSS",
            collection_mode="HTTP",
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _clock_sequence(moments):
        moments = iter(moments)
        return lambda: next(moments)

    def test_successful_run_persists_lifecycle_and_cursor(self):
        batch = CollectorBatch(
            items=(RawCollectedItem(raw_payload={"id": "A"}),),
            next_cursor="cursor-1",
        )
        collector = _FakeCollector([batch])
        adapter = CollectorSourceAdapter(
            source_code="FAKE_SOURCE",
            collector=collector,
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
            clock=self._clock_sequence(
                [
                    datetime(2026, 9, 22, 8, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 9, 22, 8, 0, 1, tzinfo=timezone.utc),
                ]
            ),
        )

        items = list(adapter.collect())
        self.assertEqual(len(items), 1)

        runs = self.service.list_collector_runs("FAKE_SOURCE")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, RUN_STATUS_SUCCESS)
        self.assertEqual(runs[0].items_seen, 1)
        self.assertEqual(runs[0].items_accepted, 1)
        self.assertEqual(runs[0].items_rejected, 0)
        self.assertEqual(runs[0].cursor, "cursor-1")

        health = self.service.get_source_health("FAKE_SOURCE")
        self.assertEqual(health.last_run_status, RUN_STATUS_SUCCESS)
        self.assertIsNotNone(health.last_success_at)
        self.assertEqual(health.consecutive_failures, 0)
        self.assertEqual(health.last_cursor, "cursor-1")

    def test_second_run_reuses_persisted_cursor(self):
        batch_one = CollectorBatch(items=(), next_cursor="cursor-1")
        batch_two = CollectorBatch(items=(), next_cursor="cursor-2")
        collector = _FakeCollector([batch_one, batch_two])
        adapter = CollectorSourceAdapter(
            source_code="FAKE_SOURCE",
            collector=collector,
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
        )

        list(adapter.collect())
        list(adapter.collect())

        self.assertEqual(collector.seen_cursors, [None, "cursor-1"])

    def test_collector_error_marks_run_failed_and_propagates(self):
        adapter = CollectorSourceAdapter(
            source_code="FAKE_SOURCE",
            collector=_FailingCollector(),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
        )

        with self.assertRaises(CollectorError):
            list(adapter.collect())

        runs = self.service.list_collector_runs("FAKE_SOURCE")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, RUN_STATUS_FAILED)
        self.assertEqual(runs[0].error_classification, ERROR_NETWORK)

        health = self.service.get_source_health("FAKE_SOURCE")
        self.assertEqual(health.consecutive_failures, 1)
        self.assertIsNotNone(health.last_failure_at)

    def test_consecutive_failures_reset_by_success(self):
        adapter_fail = CollectorSourceAdapter(
            source_code="FAKE_SOURCE",
            collector=_FailingCollector(),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
        )

        for _ in range(2):
            with self.assertRaises(CollectorError):
                list(adapter_fail.collect())

        health = self.service.get_source_health("FAKE_SOURCE")
        self.assertEqual(health.consecutive_failures, 2)

        adapter_ok = CollectorSourceAdapter(
            source_code="FAKE_SOURCE",
            collector=_FakeCollector([CollectorBatch(items=())]),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
        )
        list(adapter_ok.collect())

        health = self.service.get_source_health("FAKE_SOURCE")
        self.assertEqual(health.consecutive_failures, 0)
        self.assertEqual(health.last_run_status, RUN_STATUS_SUCCESS)

    def test_unknown_source_code_is_rejected(self):
        adapter = CollectorSourceAdapter(
            source_code="MISSING_SOURCE",
            collector=_FakeCollector([CollectorBatch(items=())]),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
        )

        with self.assertRaises(ValueError):
            list(adapter.collect())


if __name__ == "__main__":
    unittest.main()
