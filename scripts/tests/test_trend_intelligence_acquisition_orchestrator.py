import tempfile
import unittest
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
    ERROR_UNKNOWN,
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCESS,
)
from backend.trend_intelligence.acquisition.orchestrator import (
    RegisteredSource,
    SourceAcquisitionOrchestrator,
)
from backend.trend_intelligence.acquisition.provenance import (
    build_provenance,
    with_provenance,
)
from backend.trend_intelligence.ingestion import TrendIngestionService
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources.base import TrendObservationInput


class _ScriptedCollector:
    collector_key = "SCRIPTED_COLLECTOR"
    collector_version = "1.0.0"
    provider = "SCRIPTED"

    def __init__(self, batches_by_cursor):
        self._batches_by_cursor = dict(batches_by_cursor)
        self.seen_cursors = []

    def collect(self, *, cursor=None):
        self.seen_cursors.append(cursor)
        return self._batches_by_cursor[cursor]


class _AlwaysFailingCollector:
    collector_key = "FAILING_COLLECTOR"
    collector_version = "1.0.0"
    provider = "FAILING"

    def collect(self, *, cursor=None):
        raise CollectorError("upstream unreachable", classification=ERROR_NETWORK)


class _ExplodingCollector:
    collector_key = "EXPLODING_COLLECTOR"
    collector_version = "1.0.0"
    provider = "EXPLODING"

    def collect(self, *, cursor=None):
        raise RuntimeError("unexpected bug")


class _PassthroughNormalizer:
    def normalize(self, raw_item):
        payload = raw_item.raw_payload
        provenance = build_provenance(
            collector_key="SCRIPTED_COLLECTOR",
            collector_version="1.0.0",
            provider="SCRIPTED",
            source_identity=payload["id"],
        )
        return TrendObservationInput(
            observation_type="ARTICLE",
            external_id=payload["id"],
            title=payload["id"],
            observed_at="2026-09-21T08:00:00+00:00",
            metadata=with_provenance(None, provenance),
        )


class TrendIntelligenceAcquisitionOrchestratorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "orchestrator.db"
        self.repository = SQLiteTrendIntelligenceRepository(self.db)
        self.service = TrendIntelligenceService(repository=self.repository)
        self.service.ensure_schema()
        self.ingestion = TrendIngestionService(self.service)

        for code in ("SOURCE_A", "SOURCE_B"):
            self.service.create_source(
                code=code,
                name=code,
                source_type="RSS",
                collection_mode="HTTP",
            )

        self.orchestrator = SourceAcquisitionOrchestrator(
            ingestion_service=self.ingestion
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _good_adapter_factory(self, source_code, item_id):
        def factory():
            collector = _ScriptedCollector(
                {
                    None: CollectorBatch(
                        items=(RawCollectedItem(raw_payload={"id": item_id}),),
                        next_cursor="cursor-1",
                    )
                }
            )
            return CollectorSourceAdapter(
                source_code=source_code,
                collector=collector,
                normalizer=_PassthroughNormalizer(),
                trend_service=self.service,
            )

        return factory

    def test_run_all_isolates_one_failing_source_from_a_succeeding_one(self):
        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_A",
                adapter_factory=lambda: CollectorSourceAdapter(
                    source_code="SOURCE_A",
                    collector=_AlwaysFailingCollector(),
                    normalizer=_PassthroughNormalizer(),
                    trend_service=self.service,
                ),
            )
        )
        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_B",
                adapter_factory=self._good_adapter_factory("SOURCE_B", "B-1"),
            )
        )

        report = self.orchestrator.run_all()

        self.assertEqual(len(report.failed), 1)
        self.assertEqual(report.failed[0].source_code, "SOURCE_A")
        self.assertEqual(report.failed[0].error_classification, ERROR_NETWORK)

        self.assertEqual(len(report.succeeded), 1)
        self.assertEqual(report.succeeded[0].source_code, "SOURCE_B")
        self.assertEqual(report.succeeded[0].report.created, 1)

        health_a = self.service.get_source_health("SOURCE_A")
        self.assertEqual(health_a.last_run_status, RUN_STATUS_FAILED)

        health_b = self.service.get_source_health("SOURCE_B")
        self.assertEqual(health_b.last_run_status, RUN_STATUS_SUCCESS)

        runs_b = self.service.list_collector_runs("SOURCE_B")
        self.assertEqual(len(runs_b), 1)
        self.assertEqual(runs_b[0].items_accepted, 1)

    def test_unexpected_collector_exception_is_isolated_as_unknown(self):
        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_A",
                adapter_factory=lambda: CollectorSourceAdapter(
                    source_code="SOURCE_A",
                    collector=_ExplodingCollector(),
                    normalizer=_PassthroughNormalizer(),
                    trend_service=self.service,
                ),
            )
        )
        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_B",
                adapter_factory=self._good_adapter_factory("SOURCE_B", "B-1"),
            )
        )

        report = self.orchestrator.run_all()

        failed = report.failed[0]
        self.assertEqual(failed.source_code, "SOURCE_A")
        self.assertEqual(failed.error_classification, ERROR_UNKNOWN)

        self.assertEqual(report.succeeded[0].report.created, 1)

    def test_repeated_source_runs_are_idempotent_and_resume_cursor(self):
        collector = _ScriptedCollector(
            {
                None: CollectorBatch(items=(), next_cursor="cursor-1"),
                "cursor-1": CollectorBatch(
                    items=(RawCollectedItem(raw_payload={"id": "A-1"}),),
                    next_cursor="cursor-2",
                ),
                "cursor-2": CollectorBatch(items=(), next_cursor="cursor-2"),
            }
        )

        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_A",
                adapter_factory=lambda: CollectorSourceAdapter(
                    source_code="SOURCE_A",
                    collector=collector,
                    normalizer=_PassthroughNormalizer(),
                    trend_service=self.service,
                ),
            )
        )

        first = self.orchestrator.run_source("SOURCE_A")
        self.assertTrue(first.ok)
        self.assertEqual(first.report.created, 0)

        second = self.orchestrator.run_source("SOURCE_A")
        self.assertTrue(second.ok)
        self.assertEqual(second.report.created, 1)

        third = self.orchestrator.run_source("SOURCE_A")
        self.assertTrue(third.ok)
        self.assertEqual(third.report.total, 0)

        self.assertEqual(collector.seen_cursors, [None, "cursor-1", "cursor-2"])

        runs = self.service.list_collector_runs("SOURCE_A")
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(run.status == RUN_STATUS_SUCCESS for run in runs))

    def test_retry_after_transient_failure_resumes_without_duplicating(self):
        class _FlakyCollector:
            collector_key = "FLAKY_COLLECTOR"
            collector_version = "1.0.0"
            provider = "FLAKY"

            def __init__(self):
                self.attempts = 0

            def collect(self, *, cursor=None):
                self.attempts += 1
                if self.attempts == 1:
                    raise CollectorError(
                        "timeout", classification=ERROR_NETWORK
                    )
                return CollectorBatch(
                    items=(RawCollectedItem(raw_payload={"id": "A-1"}),),
                    next_cursor="cursor-1",
                )

        flaky = _FlakyCollector()
        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_A",
                adapter_factory=lambda: CollectorSourceAdapter(
                    source_code="SOURCE_A",
                    collector=flaky,
                    normalizer=_PassthroughNormalizer(),
                    trend_service=self.service,
                ),
            )
        )

        first = self.orchestrator.run_source("SOURCE_A")
        self.assertFalse(first.ok)
        self.assertEqual(first.error_classification, ERROR_NETWORK)

        retry = self.orchestrator.run_source("SOURCE_A")
        self.assertTrue(retry.ok)
        self.assertEqual(retry.report.created, 1)

        retry_again = self.orchestrator.run_source("SOURCE_A")
        self.assertTrue(retry_again.ok)
        self.assertEqual(retry_again.report.created, 0)
        self.assertEqual(retry_again.report.duplicates, 1)

        health = self.service.get_source_health("SOURCE_A")
        self.assertEqual(health.last_run_status, RUN_STATUS_SUCCESS)
        self.assertEqual(health.consecutive_failures, 0)

    def test_run_source_rejects_unregistered_code(self):
        with self.assertRaises(ValueError):
            self.orchestrator.run_source("MISSING_SOURCE")

    def test_registered_source_codes_lists_in_sorted_order(self):
        self.orchestrator.register(
            RegisteredSource(
                source_code="source_b",
                adapter_factory=self._good_adapter_factory("SOURCE_B", "B-1"),
            )
        )
        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_A",
                adapter_factory=self._good_adapter_factory("SOURCE_A", "A-1"),
            )
        )

        self.assertEqual(
            self.orchestrator.registered_source_codes(),
            ("SOURCE_A", "SOURCE_B"),
        )

    def test_provenance_is_preserved_through_orchestrated_run(self):
        self.orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_A",
                adapter_factory=self._good_adapter_factory("SOURCE_A", "A-1"),
            )
        )

        outcome = self.orchestrator.run_source("SOURCE_A")
        observation = self.repository.get_observation(
            outcome.report.observation_ids[0]
        )

        provenance = observation.metadata["acquisition"]
        self.assertEqual(provenance["collector_key"], "SCRIPTED_COLLECTOR")
        self.assertEqual(provenance["provider"], "SCRIPTED")


if __name__ == "__main__":
    unittest.main()
