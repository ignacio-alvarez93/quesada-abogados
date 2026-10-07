import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
from backend.trend_intelligence.acquisition.health import HEALTH_FAILED
from backend.trend_intelligence.acquisition.models import ERROR_NETWORK
from backend.trend_intelligence.acquisition.orchestrator import (
    RegisteredSource,
    SourceAcquisitionOrchestrator,
)
from backend.trend_intelligence.acquisition.readiness import (
    READINESS_NOT_DUE,
    READINESS_READY,
    READINESS_UNHEALTHY,
    REASON_FAILED_RETRY_ELIGIBLE,
    REASON_FAILED_RETRY_EXHAUSTED,
    REASON_FRESH_NOT_DUE,
    REASON_NEVER_RUN,
    REASON_STALE_PAST_THRESHOLD,
    build_acquisition_readiness_plan,
)
from backend.trend_intelligence.ingestion import TrendIngestionService
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources.base import TrendObservationInput


class _ScriptedCollector:
    collector_key = "SCRIPTED_COLLECTOR"
    collector_version = "1.0.0"
    provider = "SCRIPTED"

    def __init__(self, batch):
        self._batch = batch

    def collect(self, *, cursor=None):
        return self._batch


class _FailingCollector:
    collector_key = "SCRIPTED_COLLECTOR"
    collector_version = "1.0.0"
    provider = "SCRIPTED"

    def collect(self, *, cursor=None):
        raise CollectorError("upstream unreachable", classification=ERROR_NETWORK)


class _PassthroughNormalizer:
    def normalize(self, raw_item):
        payload = raw_item.raw_payload
        return TrendObservationInput(
            observation_type="ARTICLE",
            external_id=payload["id"],
            title=payload["id"],
            observed_at="2026-09-21T08:00:00+00:00",
        )


def _fixed_clock(moment):
    return lambda: moment


class TrendIntelligenceAcquisitionReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "readiness.db"
        self.repository = SQLiteTrendIntelligenceRepository(self.db)
        self.service = TrendIntelligenceService(repository=self.repository)
        self.service.ensure_schema()
        self.ingestion = TrendIngestionService(self.service)

        for code in ("SOURCE_A", "SOURCE_B", "SOURCE_C"):
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

    def _register(self, source_code, *, domain_code=None):
        self.orchestrator.register(
            RegisteredSource(
                source_code=source_code,
                adapter_factory=lambda: None,
                domain_code=domain_code,
            )
        )

    def _run_success(self, source_code, *, at, cursor="cursor-1"):
        adapter = CollectorSourceAdapter(
            source_code=source_code,
            collector=_ScriptedCollector(
                CollectorBatch(
                    items=(RawCollectedItem(raw_payload={"id": "A"}),),
                    next_cursor=cursor,
                )
            ),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
            clock=_fixed_clock(at),
        )
        list(adapter.collect())

    def _run_failure(self, source_code, *, at):
        adapter = CollectorSourceAdapter(
            source_code=source_code,
            collector=_FailingCollector(),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
            clock=_fixed_clock(at),
        )
        with self.assertRaises(CollectorError):
            list(adapter.collect())

    def test_never_run_source_is_ready(self):
        self._register("SOURCE_A")

        plan = build_acquisition_readiness_plan(self.orchestrator, self.service)

        self.assertEqual(len(plan.entries), 1)
        entry = plan.entries[0]
        self.assertEqual(entry.readiness_state, READINESS_READY)
        self.assertTrue(entry.is_ready)
        self.assertEqual(entry.reason, REASON_NEVER_RUN)
        self.assertIsNone(entry.retry_eligible)

    def test_fresh_source_is_not_due(self):
        self._register("SOURCE_A")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        plan = build_acquisition_readiness_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(seconds=30),
            stale_after_seconds=3600,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.readiness_state, READINESS_NOT_DUE)
        self.assertFalse(entry.is_ready)
        self.assertEqual(entry.reason, REASON_FRESH_NOT_DUE)
        self.assertIsNone(entry.retry_eligible)
        self.assertEqual(plan.stale, ())
        self.assertEqual(plan.unhealthy, ())

    def test_stale_source_is_ready(self):
        self._register("SOURCE_A")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        plan = build_acquisition_readiness_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(hours=2),
            stale_after_seconds=3600,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.readiness_state, READINESS_READY)
        self.assertTrue(entry.is_ready)
        self.assertEqual(entry.reason, REASON_STALE_PAST_THRESHOLD)
        self.assertIsNone(entry.retry_eligible)
        self.assertEqual(len(plan.stale), 1)
        self.assertEqual(plan.stale[0].source_code, "SOURCE_A")

    def test_failed_source_under_threshold_is_retry_eligible(self):
        self._register("SOURCE_A")
        failure_at = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
        self._run_failure("SOURCE_A", at=failure_at)

        plan = build_acquisition_readiness_plan(
            self.orchestrator,
            self.service,
            now=failure_at + timedelta(seconds=5),
            max_consecutive_failures=3,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.health_state, HEALTH_FAILED)
        self.assertEqual(entry.readiness_state, READINESS_READY)
        self.assertTrue(entry.is_ready)
        self.assertTrue(entry.retry_eligible)
        self.assertEqual(entry.reason, REASON_FAILED_RETRY_ELIGIBLE)
        self.assertEqual(len(plan.unhealthy), 1)

    def test_failed_source_over_threshold_is_retry_ineligible(self):
        self._register("SOURCE_A")
        base = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)

        for offset in range(3):
            self._run_failure("SOURCE_A", at=base + timedelta(minutes=offset))

        plan = build_acquisition_readiness_plan(
            self.orchestrator,
            self.service,
            now=base + timedelta(minutes=10),
            max_consecutive_failures=3,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.consecutive_failures, 3)
        self.assertEqual(entry.readiness_state, READINESS_UNHEALTHY)
        self.assertFalse(entry.is_ready)
        self.assertFalse(entry.retry_eligible)
        self.assertEqual(entry.reason, REASON_FAILED_RETRY_EXHAUSTED)

    def test_multi_source_ordering_is_deterministic(self):
        self._register("SOURCE_C")
        self._register("SOURCE_A")
        self._register("SOURCE_B")

        plan = build_acquisition_readiness_plan(self.orchestrator, self.service)

        self.assertEqual(
            [entry.source_code for entry in plan.entries],
            ["SOURCE_A", "SOURCE_B", "SOURCE_C"],
        )

    def test_domain_neutral_filtering(self):
        self._register("SOURCE_A", domain_code="LEGAL")
        self._register("SOURCE_B", domain_code="OTHER")
        self._register("SOURCE_C")

        legal_plan = build_acquisition_readiness_plan(
            self.orchestrator, self.service, domain_code="legal"
        )
        self.assertEqual(len(legal_plan.entries), 1)
        self.assertEqual(legal_plan.entries[0].source_code, "SOURCE_A")

        all_plan = build_acquisition_readiness_plan(self.orchestrator, self.service)
        self.assertEqual(
            {entry.source_code for entry in all_plan.entries},
            {"SOURCE_A", "SOURCE_B", "SOURCE_C"},
        )

        no_match_plan = build_acquisition_readiness_plan(
            self.orchestrator, self.service, domain_code="NEVER_REGISTERED"
        )
        self.assertEqual(no_match_plan.entries, ())

    def test_plan_is_read_only(self):
        self._register("SOURCE_A")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        before = self.service.list_collector_runs("SOURCE_A")
        build_acquisition_readiness_plan(self.orchestrator, self.service)
        build_acquisition_readiness_plan(self.orchestrator, self.service)
        after = self.service.list_collector_runs("SOURCE_A")

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
