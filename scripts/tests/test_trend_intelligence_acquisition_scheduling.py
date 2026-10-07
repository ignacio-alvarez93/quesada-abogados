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
from backend.trend_intelligence.acquisition.health import HEALTH_FAILED, HEALTH_NEVER_RUN
from backend.trend_intelligence.acquisition.models import ERROR_NETWORK
from backend.trend_intelligence.acquisition.orchestrator import (
    RegisteredSource,
    SourceAcquisitionOrchestrator,
)
from backend.trend_intelligence.acquisition.scheduling import (
    REASON_FAILURE_BACKOFF_ELAPSED,
    REASON_FAILURE_BACKOFF_PENDING,
    REASON_INTERVAL_ELAPSED,
    REASON_INTERVAL_NOT_ELAPSED,
    REASON_INVALID_POLICY,
    REASON_NEVER_RUN,
    REASON_RETRY_EXHAUSTED,
    SCHEDULE_BLOCKED,
    SCHEDULE_DUE,
    SCHEDULE_NOT_DUE,
    SchedulePolicy,
    build_acquisition_schedule_plan,
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


class TrendIntelligenceAcquisitionSchedulingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "scheduling.db"
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

    def test_now_is_required_for_determinism(self):
        self._register("SOURCE_A")

        with self.assertRaises(ValueError):
            build_acquisition_schedule_plan(
                self.orchestrator, self.service, now=None
            )

    def test_never_run_source_is_due(self):
        self._register("SOURCE_A")

        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(plan.entries), 1)
        entry = plan.entries[0]
        self.assertEqual(entry.schedule_state, SCHEDULE_DUE)
        self.assertTrue(entry.is_due)
        self.assertEqual(entry.reason, REASON_NEVER_RUN)
        self.assertEqual(entry.health_state, HEALTH_NEVER_RUN)
        self.assertIsNone(entry.next_eligible_at)

    def test_source_within_normal_interval_is_not_due(self):
        self._register("SOURCE_A")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        policy = SchedulePolicy(normal_interval_seconds=3600)
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(seconds=30),
            policy=policy,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.schedule_state, SCHEDULE_NOT_DUE)
        self.assertFalse(entry.is_due)
        self.assertEqual(entry.reason, REASON_INTERVAL_NOT_ELAPSED)
        self.assertEqual(
            entry.next_eligible_at, "2026-10-01T09:00:00+00:00"
        )

    def test_source_past_normal_interval_is_due(self):
        self._register("SOURCE_A")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        policy = SchedulePolicy(normal_interval_seconds=3600)
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(hours=2),
            policy=policy,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.schedule_state, SCHEDULE_DUE)
        self.assertTrue(entry.is_due)
        self.assertEqual(entry.reason, REASON_INTERVAL_ELAPSED)

    def test_failed_source_pending_backoff_is_not_due_with_next_eligible(self):
        self._register("SOURCE_A")
        failure_at = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
        self._run_failure("SOURCE_A", at=failure_at)

        policy = SchedulePolicy(
            failure_backoff_seconds=300,
            failure_backoff_multiplier=2.0,
            max_failure_backoff_seconds=3600,
            max_consecutive_failures=5,
        )
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=failure_at + timedelta(seconds=60),
            policy=policy,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.health_state, HEALTH_FAILED)
        self.assertEqual(entry.schedule_state, SCHEDULE_NOT_DUE)
        self.assertFalse(entry.is_due)
        self.assertEqual(entry.reason, REASON_FAILURE_BACKOFF_PENDING)
        self.assertEqual(entry.next_eligible_at, "2026-10-01T09:05:00+00:00")

    def test_failed_source_past_backoff_is_due(self):
        self._register("SOURCE_A")
        failure_at = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
        self._run_failure("SOURCE_A", at=failure_at)

        policy = SchedulePolicy(
            failure_backoff_seconds=300,
            failure_backoff_multiplier=2.0,
            max_failure_backoff_seconds=3600,
            max_consecutive_failures=5,
        )
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=failure_at + timedelta(minutes=10),
            policy=policy,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.schedule_state, SCHEDULE_DUE)
        self.assertTrue(entry.is_due)
        self.assertEqual(entry.reason, REASON_FAILURE_BACKOFF_ELAPSED)

    def test_failure_backoff_grows_with_consecutive_failures(self):
        self._register("SOURCE_A")
        base = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)

        self._run_failure("SOURCE_A", at=base)
        self._run_failure("SOURCE_A", at=base + timedelta(minutes=1))

        policy = SchedulePolicy(
            failure_backoff_seconds=300,
            failure_backoff_multiplier=2.0,
            max_failure_backoff_seconds=3600,
            max_consecutive_failures=5,
        )

        second_failure_at = base + timedelta(minutes=1)
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=second_failure_at + timedelta(seconds=350),
            policy=policy,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.consecutive_failures, 2)
        self.assertEqual(entry.schedule_state, SCHEDULE_NOT_DUE)
        self.assertEqual(entry.reason, REASON_FAILURE_BACKOFF_PENDING)
        self.assertEqual(
            entry.next_eligible_at,
            (second_failure_at + timedelta(seconds=600)).isoformat(),
        )

    def test_failure_backoff_is_capped(self):
        self._register("SOURCE_A")
        base = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)

        for offset in range(4):
            self._run_failure("SOURCE_A", at=base + timedelta(minutes=offset))

        policy = SchedulePolicy(
            failure_backoff_seconds=300,
            failure_backoff_multiplier=10.0,
            max_failure_backoff_seconds=600,
            max_consecutive_failures=10,
        )

        last_failure_at = base + timedelta(minutes=3)
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=last_failure_at + timedelta(seconds=601),
            policy=policy,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.schedule_state, SCHEDULE_DUE)
        self.assertEqual(entry.reason, REASON_FAILURE_BACKOFF_ELAPSED)

    def test_failed_source_over_threshold_is_blocked(self):
        self._register("SOURCE_A")
        base = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)

        for offset in range(3):
            self._run_failure("SOURCE_A", at=base + timedelta(minutes=offset))

        policy = SchedulePolicy(max_consecutive_failures=3)
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=base + timedelta(days=30),
            policy=policy,
        )

        entry = plan.entries[0]
        self.assertEqual(entry.consecutive_failures, 3)
        self.assertEqual(entry.schedule_state, SCHEDULE_BLOCKED)
        self.assertFalse(entry.is_due)
        self.assertEqual(entry.reason, REASON_RETRY_EXHAUSTED)
        self.assertIsNone(entry.next_eligible_at)
        self.assertEqual(len(plan.blocked), 1)

    def test_invalid_policy_fails_closed_without_crashing_plan(self):
        self._register("SOURCE_A")
        self._register("SOURCE_B")

        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
            policy_overrides={
                "SOURCE_A": SchedulePolicy(normal_interval_seconds=0),
            },
        )

        self.assertEqual(len(plan.entries), 2)
        a_entry = next(e for e in plan.entries if e.source_code == "SOURCE_A")
        b_entry = next(e for e in plan.entries if e.source_code == "SOURCE_B")

        self.assertEqual(a_entry.schedule_state, SCHEDULE_BLOCKED)
        self.assertFalse(a_entry.is_due)
        self.assertEqual(a_entry.reason, REASON_INVALID_POLICY)
        self.assertIsNotNone(a_entry.error_message)

        self.assertEqual(b_entry.schedule_state, SCHEDULE_DUE)
        self.assertTrue(b_entry.is_due)

    def test_per_source_policy_override_is_explicit(self):
        self._register("SOURCE_A")
        self._register("SOURCE_B")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)
        self._run_success("SOURCE_B", at=started_at)

        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(minutes=30),
            policy=SchedulePolicy(normal_interval_seconds=3600),
            policy_overrides={
                "source_b": SchedulePolicy(normal_interval_seconds=60),
            },
        )

        a_entry = next(e for e in plan.entries if e.source_code == "SOURCE_A")
        b_entry = next(e for e in plan.entries if e.source_code == "SOURCE_B")

        self.assertEqual(a_entry.schedule_state, SCHEDULE_NOT_DUE)
        self.assertEqual(b_entry.schedule_state, SCHEDULE_DUE)
        self.assertEqual(b_entry.reason, REASON_INTERVAL_ELAPSED)

    def test_source_isolation_on_lookup_error(self):
        self._register("SOURCE_A")
        self._register("SOURCE_B")

        class _ExplodingService:
            def __getattr__(self, name):
                def _boom(*args, **kwargs):
                    raise RuntimeError("boom")

                return _boom

        class _PartialProxy:
            def __init__(self, real, broken_source):
                self._real = real
                self._broken_source = broken_source

            def get_source_health(self, source_code):
                if source_code == self._broken_source:
                    raise RuntimeError("boom")
                return self._real.get_source_health(source_code)

            def list_collector_runs(self, source_code):
                if source_code == self._broken_source:
                    raise RuntimeError("boom")
                return self._real.list_collector_runs(source_code)

        proxy = _PartialProxy(self.service, "SOURCE_A")

        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            proxy,
            now=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
        )

        a_entry = next(e for e in plan.entries if e.source_code == "SOURCE_A")
        b_entry = next(e for e in plan.entries if e.source_code == "SOURCE_B")

        self.assertEqual(a_entry.schedule_state, SCHEDULE_BLOCKED)
        self.assertIsNotNone(a_entry.error_message)
        self.assertEqual(b_entry.schedule_state, SCHEDULE_DUE)

    def test_multi_source_ordering_is_deterministic(self):
        self._register("SOURCE_C")
        self._register("SOURCE_A")
        self._register("SOURCE_B")

        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(
            [entry.source_code for entry in plan.entries],
            ["SOURCE_A", "SOURCE_B", "SOURCE_C"],
        )

    def test_domain_neutral_filtering(self):
        self._register("SOURCE_A", domain_code="LEGAL")
        self._register("SOURCE_B", domain_code="OTHER")
        self._register("SOURCE_C")

        now = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)

        legal_plan = build_acquisition_schedule_plan(
            self.orchestrator, self.service, now=now, domain_code="legal"
        )
        self.assertEqual(len(legal_plan.entries), 1)
        self.assertEqual(legal_plan.entries[0].source_code, "SOURCE_A")

        all_plan = build_acquisition_schedule_plan(
            self.orchestrator, self.service, now=now
        )
        self.assertEqual(
            {entry.source_code for entry in all_plan.entries},
            {"SOURCE_A", "SOURCE_B", "SOURCE_C"},
        )

        no_match_plan = build_acquisition_schedule_plan(
            self.orchestrator, self.service, now=now, domain_code="NEVER_REGISTERED"
        )
        self.assertEqual(no_match_plan.entries, ())

    def test_plan_is_read_only_and_does_not_call_collector(self):
        self._register("SOURCE_A")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._run_success("SOURCE_A", at=started_at)

        before = self.service.list_collector_runs("SOURCE_A")
        build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(hours=1),
        )
        build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(hours=1),
        )
        after = self.service.list_collector_runs("SOURCE_A")

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
