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
from backend.trend_intelligence.acquisition.health import (
    HEALTH_FAILED,
    HEALTH_FRESH,
    HEALTH_NEVER_RUN,
    HEALTH_STALE,
    build_source_freshness_report,
    list_source_freshness_reports,
)
from backend.trend_intelligence.acquisition.models import ERROR_NETWORK
from backend.trend_intelligence.acquisition.orchestrator import (
    RegisteredSource,
    SourceAcquisitionOrchestrator,
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


class TrendIntelligenceAcquisitionHealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "health.db"
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

    def tearDown(self):
        self.tmp.cleanup()

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

    def test_source_with_no_runs_is_never_run(self):
        report = build_source_freshness_report(self.service, "SOURCE_A")

        self.assertEqual(report.health_state, HEALTH_NEVER_RUN)
        self.assertIsNone(report.latest_run)
        self.assertIsNone(report.freshness_age_seconds)
        self.assertFalse(report.has_cursor)
        self.assertIsNone(report.last_cursor)
        self.assertIsNone(report.last_failure_reason)

    def test_recent_success_is_fresh(self):
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at, cursor="cursor-1")

        report = build_source_freshness_report(
            self.service,
            "SOURCE_A",
            now=started_at + timedelta(seconds=30),
            stale_after_seconds=3600,
        )

        self.assertEqual(report.health_state, HEALTH_FRESH)
        self.assertAlmostEqual(report.freshness_age_seconds, 30, delta=1)
        self.assertTrue(report.has_cursor)
        self.assertEqual(report.last_cursor, "cursor-1")
        self.assertIsNotNone(report.latest_run)

    def test_old_success_beyond_threshold_is_stale(self):
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        report = build_source_freshness_report(
            self.service,
            "SOURCE_A",
            now=started_at + timedelta(hours=2),
            stale_after_seconds=3600,
        )

        self.assertEqual(report.health_state, HEALTH_STALE)

    def test_latest_failure_overrides_prior_success_and_reports_reason(self):
        success_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        failure_at = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)

        self._run_success("SOURCE_A", at=success_at)
        self._run_failure("SOURCE_A", at=failure_at)

        report = build_source_freshness_report(
            self.service,
            "SOURCE_A",
            now=failure_at + timedelta(seconds=5),
        )

        self.assertEqual(report.health_state, HEALTH_FAILED)
        self.assertEqual(report.last_run_status, "FAILED")
        self.assertIsNotNone(report.last_success_at)
        self.assertIn("upstream unreachable", report.last_failure_reason)
        self.assertEqual(report.last_error_classification, ERROR_NETWORK)

    def test_build_report_does_not_mutate_persisted_state(self):
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        before = self.service.list_collector_runs("SOURCE_A")
        build_source_freshness_report(self.service, "SOURCE_A")
        build_source_freshness_report(self.service, "SOURCE_A")
        after = self.service.list_collector_runs("SOURCE_A")

        self.assertEqual(before, after)

    def test_list_reports_filters_by_domain_code(self):
        orchestrator = SourceAcquisitionOrchestrator(ingestion_service=self.ingestion)
        orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_A",
                adapter_factory=lambda: None,
                domain_code="LEGAL",
            )
        )
        orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_B",
                adapter_factory=lambda: None,
                domain_code="OTHER",
            )
        )
        orchestrator.register(
            RegisteredSource(
                source_code="SOURCE_C",
                adapter_factory=lambda: None,
            )
        )

        legal_reports = list_source_freshness_reports(
            orchestrator,
            self.service,
            domain_code="legal",
        )

        self.assertEqual(len(legal_reports), 1)
        self.assertEqual(legal_reports[0].source_code, "SOURCE_A")
        self.assertEqual(legal_reports[0].domain_code, "LEGAL")

        all_reports = list_source_freshness_reports(orchestrator, self.service)
        self.assertEqual(
            {report.source_code for report in all_reports},
            {"SOURCE_A", "SOURCE_B", "SOURCE_C"},
        )

        no_domain_match = list_source_freshness_reports(
            orchestrator,
            self.service,
            domain_code="NEVER_REGISTERED",
        )
        self.assertEqual(no_domain_match, ())

    def test_list_reports_filters_by_source_code(self):
        orchestrator = SourceAcquisitionOrchestrator(ingestion_service=self.ingestion)
        orchestrator.register(
            RegisteredSource(source_code="SOURCE_A", adapter_factory=lambda: None)
        )
        orchestrator.register(
            RegisteredSource(source_code="SOURCE_B", adapter_factory=lambda: None)
        )

        reports = list_source_freshness_reports(
            orchestrator,
            self.service,
            source_code="source_b",
        )

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].source_code, "SOURCE_B")


if __name__ == "__main__":
    unittest.main()
