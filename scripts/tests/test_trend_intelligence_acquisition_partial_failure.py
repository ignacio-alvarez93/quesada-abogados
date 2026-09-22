import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.acquisition.adapter import CollectorSourceAdapter
from backend.trend_intelligence.acquisition.contracts import (
    CollectorBatch,
    NormalizationError,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_NONE,
    ERROR_PARSE,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_SUCCESS,
)
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources.base import TrendObservationInput


class _FixedBatchCollector:
    collector_key = "FAKE_COLLECTOR"
    collector_version = "1.0.0"
    provider = "FAKE"

    def __init__(self, batch):
        self._batch = batch

    def collect(self, *, cursor=None):
        return self._batch


class _SelectiveNormalizer:
    def normalize(self, raw_item):
        payload = raw_item.raw_payload

        if not payload.get("valid"):
            raise NormalizationError("missing required field")

        return TrendObservationInput(
            observation_type="ARTICLE",
            external_id=payload["id"],
            title=payload["id"],
            observed_at="2026-09-21T08:00:00+00:00",
        )


class TrendIntelligenceAcquisitionPartialFailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "partial.db"
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

    def _adapter(self, batch):
        return CollectorSourceAdapter(
            source_code="FAKE_SOURCE",
            collector=_FixedBatchCollector(batch),
            normalizer=_SelectiveNormalizer(),
            trend_service=self.service,
        )

    def test_mixed_batch_yields_partial_status(self):
        batch = CollectorBatch(
            items=(
                RawCollectedItem(raw_payload={"id": "A", "valid": True}),
                RawCollectedItem(raw_payload={"id": "B", "valid": False}),
                RawCollectedItem(raw_payload={"id": "C", "valid": True}),
            ),
        )

        items = list(self._adapter(batch).collect())
        self.assertEqual(len(items), 2)

        run = self.service.list_collector_runs("FAKE_SOURCE")[0]
        self.assertEqual(run.status, RUN_STATUS_PARTIAL)
        self.assertEqual(run.items_seen, 3)
        self.assertEqual(run.items_accepted, 2)
        self.assertEqual(run.items_rejected, 1)
        self.assertEqual(run.error_classification, ERROR_PARSE)

    def test_fully_malformed_batch_yields_failed_status(self):
        batch = CollectorBatch(
            items=(RawCollectedItem(raw_payload={"id": "A", "valid": False}),),
        )

        items = list(self._adapter(batch).collect())
        self.assertEqual(items, [])

        run = self.service.list_collector_runs("FAKE_SOURCE")[0]
        self.assertEqual(run.status, RUN_STATUS_FAILED)
        self.assertEqual(run.items_accepted, 0)
        self.assertEqual(run.items_rejected, 1)

    def test_empty_batch_is_a_successful_no_op_run(self):
        items = list(self._adapter(CollectorBatch(items=())).collect())
        self.assertEqual(items, [])

        run = self.service.list_collector_runs("FAKE_SOURCE")[0]
        self.assertEqual(run.status, RUN_STATUS_SUCCESS)
        self.assertEqual(run.error_classification, ERROR_NONE)
        self.assertEqual(run.items_seen, 0)


if __name__ == "__main__":
    unittest.main()
