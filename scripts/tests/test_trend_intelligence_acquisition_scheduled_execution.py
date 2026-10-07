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
from backend.trend_intelligence.acquisition.models import ERROR_NETWORK, ERROR_UNKNOWN
from backend.trend_intelligence.acquisition.orchestrator import (
    RegisteredSource,
    SourceAcquisitionOrchestrator,
)
from backend.trend_intelligence.acquisition.readiness import (
    build_acquisition_readiness_plan,
)
from backend.trend_intelligence.acquisition.scheduled_execution import (
    EXECUTION_EXECUTED,
    EXECUTION_SKIPPED,
    SKIP_REASON_NOT_DUE,
    SKIP_REASON_UNRESOLVABLE_PLAN_ENTRY,
    execute_scheduled_batch,
)
from backend.trend_intelligence.acquisition.scheduling import (
    REASON_INTERVAL_ELAPSED,
    REASON_INTERVAL_NOT_ELAPSED,
    REASON_NEVER_RUN,
    REASON_RETRY_EXHAUSTED,
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

    def __init__(self, batches_by_cursor):
        self._batches_by_cursor = dict(batches_by_cursor)

    def collect(self, *, cursor=None):
        return self._batches_by_cursor[cursor]


class _AlwaysFailingCollector:
    collector_key = "FAILING_COLLECTOR"
    collector_version = "1.0.0"
    provider = "FAILING"

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


class TrendIntelligenceAcquisitionScheduledExecutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "scheduled_execution.db"
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

    def _good_adapter_factory(self, source_code, item_id):
        def factory():
            return CollectorSourceAdapter(
                source_code=source_code,
                collector=_ScriptedCollector(
                    {
                        None: CollectorBatch(
                            items=(RawCollectedItem(raw_payload={"id": item_id}),),
                            next_cursor="cursor-1",
                        )
                    }
                ),
                normalizer=_PassthroughNormalizer(),
                trend_service=self.service,
            )

        return factory

    def _failing_adapter_factory(self, source_code):
        return lambda: CollectorSourceAdapter(
            source_code=source_code,
            collector=_AlwaysFailingCollector(),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
        )

    def _register_good(self, source_code, item_id=None):
        self.orchestrator.register(
            RegisteredSource(
                source_code=source_code,
                adapter_factory=self._good_adapter_factory(
                    source_code, item_id or f"{source_code}-1"
                ),
            )
        )

    def _register_failing(self, source_code):
        self.orchestrator.register(
            RegisteredSource(
                source_code=source_code,
                adapter_factory=self._failing_adapter_factory(source_code),
            )
        )

    def _mark_fresh(self, source_code, *, at):
        adapter = CollectorSourceAdapter(
            source_code=source_code,
            collector=_ScriptedCollector(
                {
                    None: CollectorBatch(
                        items=(RawCollectedItem(raw_payload={"id": "warmup"}),),
                        next_cursor="cursor-warmup",
                    )
                }
            ),
            normalizer=_PassthroughNormalizer(),
            trend_service=self.service,
            clock=_fixed_clock(at),
        )
        list(adapter.collect())

    def test_never_run_source_executes_and_persists(self):
        self._register_good("SOURCE_A")

        plan = build_acquisition_readiness_plan(self.orchestrator, self.service)
        report = execute_scheduled_batch(self.orchestrator, plan)

        self.assertEqual(len(report.outcomes), 1)
        outcome = report.outcomes[0]
        self.assertEqual(outcome.source_code, "SOURCE_A")
        self.assertEqual(outcome.execution_state, EXECUTION_EXECUTED)
        self.assertTrue(outcome.executed)
        self.assertTrue(outcome.ok)
        self.assertIsNotNone(outcome.acquisition_outcome)
        self.assertEqual(outcome.acquisition_outcome.report.created, 1)

        runs = self.service.list_collector_runs("SOURCE_A")
        self.assertEqual(len(runs), 1)

    def test_not_due_source_is_skipped_without_executing(self):
        self._register_good("SOURCE_A")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._mark_fresh("SOURCE_A", at=started_at)

        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(seconds=30),
            policy=SchedulePolicy(normal_interval_seconds=3600),
        )
        report = execute_scheduled_batch(self.orchestrator, plan)

        self.assertEqual(len(report.outcomes), 1)
        outcome = report.outcomes[0]
        self.assertEqual(outcome.execution_state, EXECUTION_SKIPPED)
        self.assertFalse(outcome.executed)
        self.assertIsNone(outcome.ok)
        self.assertEqual(outcome.plan_reason, REASON_INTERVAL_NOT_ELAPSED)
        self.assertIsNone(outcome.acquisition_outcome)

        runs = self.service.list_collector_runs("SOURCE_A")
        self.assertEqual(len(runs), 1)

    def test_retry_exhausted_blocked_source_is_skipped(self):
        self._register_failing("SOURCE_A")
        base = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)

        for offset in range(3):
            adapter = CollectorSourceAdapter(
                source_code="SOURCE_A",
                collector=_AlwaysFailingCollector(),
                normalizer=_PassthroughNormalizer(),
                trend_service=self.service,
                clock=_fixed_clock(base + timedelta(minutes=offset)),
            )
            with self.assertRaises(CollectorError):
                list(adapter.collect())

        policy = SchedulePolicy(max_consecutive_failures=3)
        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=base + timedelta(days=30),
            policy=policy,
        )
        report = execute_scheduled_batch(self.orchestrator, plan)

        outcome = report.outcomes[0]
        self.assertEqual(outcome.execution_state, EXECUTION_SKIPPED)
        self.assertEqual(outcome.plan_reason, REASON_RETRY_EXHAUSTED)

        runs_before = self.service.list_collector_runs("SOURCE_A")
        self.assertEqual(len(runs_before), 3)

    def test_partial_success_isolates_failing_source_from_succeeding_one(self):
        self._register_failing("SOURCE_A")
        self._register_good("SOURCE_B")

        plan = build_acquisition_readiness_plan(self.orchestrator, self.service)
        report = execute_scheduled_batch(self.orchestrator, plan)

        self.assertEqual(len(report.outcomes), 2)
        self.assertEqual(len(report.executed), 2)
        self.assertEqual(len(report.succeeded), 1)
        self.assertEqual(len(report.failed), 1)

        failed = report.failed[0]
        self.assertEqual(failed.source_code, "SOURCE_A")
        self.assertEqual(failed.acquisition_outcome.error_classification, ERROR_NETWORK)

        succeeded = report.succeeded[0]
        self.assertEqual(succeeded.source_code, "SOURCE_B")
        self.assertEqual(succeeded.acquisition_outcome.report.created, 1)

        runs_b = self.service.list_collector_runs("SOURCE_B")
        self.assertEqual(len(runs_b), 1)

    def test_source_not_registered_in_orchestrator_is_isolated_not_fatal(self):
        class _PlanEntryStub:
            source_code = "GHOST_SOURCE"
            is_due = True
            reason = REASON_NEVER_RUN

        class _PlanStub:
            entries = (_PlanEntryStub(),)

        report = execute_scheduled_batch(self.orchestrator, _PlanStub())

        self.assertEqual(len(report.outcomes), 1)
        outcome = report.outcomes[0]
        self.assertEqual(outcome.execution_state, EXECUTION_EXECUTED)
        self.assertFalse(outcome.ok)
        self.assertIsNotNone(outcome.error_message)
        self.assertIsNone(outcome.acquisition_outcome)

    def test_source_absent_from_plan_is_never_executed(self):
        self._register_good("SOURCE_A")
        self._register_good("SOURCE_B")

        plan = build_acquisition_readiness_plan(
            self.orchestrator, self.service, source_code="SOURCE_A"
        )
        report = execute_scheduled_batch(self.orchestrator, plan)

        self.assertEqual(len(report.outcomes), 1)
        self.assertEqual(report.outcomes[0].source_code, "SOURCE_A")

        runs_b = self.service.list_collector_runs("SOURCE_B")
        self.assertEqual(list(runs_b), [])

    def test_unresolvable_plan_entry_is_skipped_explicitly(self):
        class _OpaqueEntry:
            source_code = "SOURCE_A"
            reason = "N/A"

        class _PlanStub:
            entries = (_OpaqueEntry(),)

        self._register_good("SOURCE_A")

        report = execute_scheduled_batch(self.orchestrator, _PlanStub())

        outcome = report.outcomes[0]
        self.assertEqual(outcome.execution_state, EXECUTION_SKIPPED)
        self.assertEqual(outcome.plan_reason, SKIP_REASON_UNRESOLVABLE_PLAN_ENTRY)
        self.assertIsNotNone(outcome.error_message)

        runs = self.service.list_collector_runs("SOURCE_A")
        self.assertEqual(list(runs), [])

    def test_plan_is_required(self):
        with self.assertRaises(ValueError):
            execute_scheduled_batch(self.orchestrator, None)

    def test_execution_order_is_deterministic_regardless_of_plan_entry_order(self):
        self._register_good("SOURCE_C")
        self._register_good("SOURCE_A")
        self._register_good("SOURCE_B")

        plan = build_acquisition_readiness_plan(self.orchestrator, self.service)
        # Entries already come back sorted; reverse them to prove the
        # executor re-sorts rather than trusting plan entry order.
        reversed_entries = tuple(reversed(plan.entries))

        class _ReversedPlanStub:
            entries = reversed_entries

        report = execute_scheduled_batch(self.orchestrator, _ReversedPlanStub())

        self.assertEqual(
            [outcome.source_code for outcome in report.outcomes],
            ["SOURCE_A", "SOURCE_B", "SOURCE_C"],
        )

    def test_evidence_object_exists_for_every_source_considered(self):
        self._register_good("SOURCE_A")
        self._register_failing("SOURCE_B")
        started_at = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
        self._mark_fresh("SOURCE_A", at=started_at)
        self._register_good("SOURCE_C")

        plan = build_acquisition_schedule_plan(
            self.orchestrator,
            self.service,
            now=started_at + timedelta(seconds=5),
            policy=SchedulePolicy(normal_interval_seconds=3600),
        )
        self.assertEqual(len(plan.entries), 3)

        report = execute_scheduled_batch(self.orchestrator, plan)

        self.assertEqual(len(report.outcomes), 3)
        by_code = {outcome.source_code: outcome for outcome in report.outcomes}
        self.assertEqual(by_code["SOURCE_A"].execution_state, EXECUTION_SKIPPED)
        self.assertEqual(by_code["SOURCE_B"].execution_state, EXECUTION_EXECUTED)
        self.assertFalse(by_code["SOURCE_B"].ok)
        self.assertEqual(by_code["SOURCE_C"].execution_state, EXECUTION_EXECUTED)
        self.assertTrue(by_code["SOURCE_C"].ok)

    def test_run_all_outcomes_do_not_mutate_schema(self):
        self._register_good("SOURCE_A")

        before_codes = self.orchestrator.registered_source_codes()
        plan = build_acquisition_readiness_plan(self.orchestrator, self.service)
        execute_scheduled_batch(self.orchestrator, plan)
        after_codes = self.orchestrator.registered_source_codes()

        self.assertEqual(before_codes, after_codes)


if __name__ == "__main__":
    unittest.main()
