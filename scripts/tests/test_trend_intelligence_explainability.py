import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.acquisition.health import HEALTH_FAILED, HEALTH_NEVER_RUN
from backend.trend_intelligence.acquisition.models import ERROR_NETWORK, RUN_STATUS_FAILED, RUN_STATUS_SUCCESS
from backend.trend_intelligence.acquisition.provenance import build_provenance, with_provenance
from backend.trend_intelligence.models import TrendAggregateSignal
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.temporal import TrendTemporalIntelligenceService
from backend.trend_intelligence.trend_history import TrendSnapshotService


class TrendExplainabilityTestBase(unittest.TestCase):
    db_name = "explainability.db"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / self.db_name
        self.repository = SQLiteTrendIntelligenceRepository(self.db)
        self.service = TrendIntelligenceService(repository=self.repository)
        self.service.ensure_schema()

        self.service.create_domain(code="GENERIC_DOMAIN", name="Generic Domain")

        self.service.create_source(
            code="SOURCE_X",
            name="Source X",
            source_type="RSS",
            provider="FEEDLY",
            collection_mode="HTTP",
        )
        self.service.create_source(
            code="SOURCE_Y",
            name="Source Y",
            source_type="WEB",
            collection_mode="MANUAL",
        )

        self.service.create_topic(
            topic_key="GENERIC_TOPIC",
            name="Generic Topic",
            domain_codes=("GENERIC_DOMAIN",),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _row_counts(self):
        conn = sqlite3.connect(str(self.db))
        try:
            tables = (
                "ti_observations",
                "ti_signals",
                "ti_trends",
                "ti_trend_evidence",
                "ti_trend_snapshots",
                "ti_aggregate_signals",
                "ti_collector_runs",
            )
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
        finally:
            conn.close()

    def _observe_and_signal(
        self,
        *,
        source_code,
        external_id,
        signal_type,
        strength,
        detected_at,
        provenance=None,
    ):
        metadata = with_provenance(None, provenance) if provenance else None

        observation, _ = self.service.record_observation(
            source_code=source_code,
            observation_type="ARTICLE",
            external_id=external_id,
            title=external_id,
            observed_at=detected_at,
            metadata=metadata,
        )

        self.service.classify_observation(
            observation.id,
            domain_code="GENERIC_DOMAIN",
            topic_key="GENERIC_TOPIC",
        )

        self.service.create_signal(
            observation_id=observation.id,
            domain_code="GENERIC_DOMAIN",
            topic_key="GENERIC_TOPIC",
            signal_type=signal_type,
            strength=strength,
            detected_at=detected_at,
        )

        return observation

    def _fail_collector_run(self, source_code):
        run = self.service.start_collector_run(
            source_code=source_code,
            collector_key="RSS_COLLECTOR",
            collector_version="1.0",
            started_at="2026-09-21T07:00:00+00:00",
        )
        self.service.complete_collector_run(
            run,
            status=RUN_STATUS_FAILED,
            items_seen=1,
            items_accepted=0,
            items_rejected=1,
            error_classification=ERROR_NETWORK,
            error_message="upstream unreachable",
            completed_at="2026-09-21T07:00:05+00:00",
        )

    def _succeed_collector_run(self, source_code, *, cursor="cursor-1"):
        run = self.service.start_collector_run(
            source_code=source_code,
            collector_key="RSS_COLLECTOR",
            collector_version="1.0",
            started_at="2026-09-21T07:00:00+00:00",
        )
        self.service.complete_collector_run(
            run,
            status=RUN_STATUS_SUCCESS,
            items_seen=1,
            items_accepted=1,
            cursor=cursor,
            completed_at="2026-09-21T07:00:05+00:00",
        )


class TrendExplainabilityTrendTest(TrendExplainabilityTestBase):
    db_name = "explainability_trend.db"

    def setUp(self):
        super().setUp()

        provenance_x = build_provenance(
            collector_key="RSS_COLLECTOR",
            collector_version="1.0",
            provider="FEEDLY",
            source_identity="feedly:source-x",
        )

        self._observe_and_signal(
            source_code="SOURCE_X",
            external_id="X-1",
            signal_type="MENTION",
            strength=60,
            detected_at="2026-09-21T08:00:00+00:00",
            provenance=provenance_x,
        )

        self._observe_and_signal(
            source_code="SOURCE_X",
            external_id="X-2",
            signal_type="CROSS_SOURCE",
            strength=80,
            detected_at="2026-09-21T09:00:00+00:00",
            provenance=provenance_x,
        )

        self._observe_and_signal(
            source_code="SOURCE_Y",
            external_id="Y-1",
            signal_type="QUESTION",
            strength=70,
            detected_at="2026-09-21T10:00:00+00:00",
        )

        self._fail_collector_run("SOURCE_X")

        self.first_result = self.service.recalculate_trend(
            domain_code="GENERIC_DOMAIN",
            topic_key="GENERIC_TOPIC",
            window_start="2026-09-21T00:00:00+00:00",
            window_end="2026-09-21T23:59:59+00:00",
        )

        self._observe_and_signal(
            source_code="SOURCE_X",
            external_id="X-3",
            signal_type="GROWTH",
            strength=90,
            detected_at="2026-09-22T08:00:00+00:00",
            provenance=provenance_x,
        )

        self.second_result = self.service.recalculate_trend(
            domain_code="GENERIC_DOMAIN",
            topic_key="GENERIC_TOPIC",
            window_start="2026-09-22T00:00:00+00:00",
            window_end="2026-09-22T23:59:59+00:00",
        )

    def test_contributing_sources_and_signal_type_counts(self):
        explanation = self.service.explain_trend(self.first_result["trend"].id)

        self.assertEqual(
            [item.source_code for item in explanation.contributing_sources],
            ["SOURCE_X", "SOURCE_Y"],
        )

        source_x = explanation.contributing_sources[0]
        self.assertEqual(source_x.observation_count, 2)
        self.assertEqual(source_x.signal_count, 2)
        self.assertEqual(source_x.signal_types, ("CROSS_SOURCE", "MENTION"))

        source_y = explanation.contributing_sources[1]
        self.assertEqual(source_y.observation_count, 1)
        self.assertEqual(source_y.signal_types, ("QUESTION",))

        self.assertEqual(
            [(item.signal_type, item.signal_count, item.source_count) for item in explanation.signal_type_counts],
            [
                ("CROSS_SOURCE", 1, 1),
                ("MENTION", 1, 1),
                ("QUESTION", 1, 1),
            ],
        )

    def test_window_and_already_computed_score_are_not_recomputed(self):
        trend = self.first_result["trend"]
        explanation = self.service.explain_trend(trend.id)

        self.assertEqual(explanation.window_start, trend.window_start)
        self.assertEqual(explanation.window_end, trend.window_end)
        self.assertEqual(explanation.status, trend.status)
        self.assertEqual(explanation.score, trend.score)
        self.assertEqual(explanation.velocity, trend.velocity)
        self.assertEqual(explanation.signal_count, trend.signal_count)
        self.assertEqual(explanation.source_count, trend.source_count)

    def test_scoring_components_reuse_persisted_evidence(self):
        trend = self.first_result["trend"]
        explanation = self.service.explain_trend(trend.id)
        persisted_evidence = self.service.get_trend_evidence(trend.id)

        self.assertEqual(len(explanation.scoring_components), len(persisted_evidence))

        reasons = {item.reason for item in persisted_evidence}
        self.assertEqual(
            {item["reason"] for item in explanation.scoring_components},
            reasons,
        )

        signal_types = {item["signal_type"] for item in explanation.scoring_components}
        self.assertEqual(signal_types, {"MENTION", "CROSS_SOURCE", "QUESTION"})

    def test_provenance_references(self):
        explanation = self.service.explain_trend(self.first_result["trend"].id)

        self.assertEqual(len(explanation.provenance), 1)
        reference = explanation.provenance[0]
        self.assertEqual(reference.collector_key, "RSS_COLLECTOR")
        self.assertEqual(reference.provider, "FEEDLY")
        self.assertEqual(reference.source_identity, "feedly:source-x")
        self.assertEqual(reference.observation_count, 2)

    def test_partial_sources_flags_failed_collector(self):
        explanation = self.service.explain_trend(self.first_result["trend"].id)

        self.assertIn("SOURCE_X", explanation.partial_sources)
        self.assertNotIn("SOURCE_Y", explanation.partial_sources)

        source_x = next(
            item for item in explanation.contributing_sources if item.source_code == "SOURCE_X"
        )
        self.assertEqual(source_x.health_state, HEALTH_FAILED)

        source_y = next(
            item for item in explanation.contributing_sources if item.source_code == "SOURCE_Y"
        )
        self.assertEqual(source_y.health_state, HEALTH_NEVER_RUN)

    def test_recurrence_reuses_previous_trend(self):
        explanation = self.service.explain_trend(self.second_result["trend"].id)

        self.assertEqual(len(explanation.recurrence), 1)
        self.assertEqual(
            explanation.recurrence[0].window_start,
            self.first_result["trend"].window_start,
        )
        self.assertEqual(explanation.previous_score, self.first_result["trend"].score)
        self.assertEqual(explanation.previous_status, self.first_result["trend"].status)

    def test_first_window_has_no_recurrence(self):
        explanation = self.service.explain_trend(self.first_result["trend"].id)

        self.assertEqual(explanation.recurrence, ())
        self.assertIsNone(explanation.previous_score)
        self.assertIsNone(explanation.previous_velocity)
        self.assertIsNone(explanation.previous_status)

    def test_deterministic_ordering_across_repeated_calls(self):
        trend = self.first_result["trend"]
        first_call = self.service.explain_trend(trend.id)
        second_call = self.service.explain_trend(trend.id)

        self.assertEqual(first_call, second_call)

    def test_explain_does_not_mutate_persistence(self):
        trend = self.first_result["trend"]
        before = self._row_counts()

        self.service.explain_trend(trend.id)
        self.service.explain_trend(trend.id)

        after = self._row_counts()
        self.assertEqual(before, after)

    def test_unknown_trend_raises(self):
        with self.assertRaises(ValueError):
            self.service.explain_trend(999999)


class TrendExplainabilitySnapshotTest(TrendExplainabilityTestBase):
    db_name = "explainability_snapshot.db"

    def setUp(self):
        super().setUp()

        self.temporal_service = TrendTemporalIntelligenceService(self.repository)
        self.snapshot_service = TrendSnapshotService(
            repository=self.repository,
            temporal_service=self.temporal_service,
        )

        self.domain = self.repository.get_domain_by_code("GENERIC_DOMAIN")
        self.topic = self.repository.get_topic_by_key("GENERIC_TOPIC")

        self._succeed_collector_run("SOURCE_X")

        self._observe_and_signal(
            source_code="SOURCE_X",
            external_id="SNAP-X-1",
            signal_type="VOLUME_SPIKE",
            strength=75,
            detected_at="2026-09-21T08:00:00+00:00",
        )

        self._observe_and_signal(
            source_code="SOURCE_Y",
            external_id="SNAP-Y-1",
            signal_type="MENTION",
            strength=55,
            detected_at="2026-09-21T09:00:00+00:00",
        )

        self.first_snapshot = self._materialize_window(
            day="2026-09-21",
            detector_key="TEMPORAL_CROSS_SOURCE",
            signal_type="CROSS_SOURCE",
        )

        self._observe_and_signal(
            source_code="SOURCE_X",
            external_id="SNAP-X-2",
            signal_type="GROWTH",
            strength=65,
            detected_at="2026-09-22T08:00:00+00:00",
        )

        self.second_snapshot = self._materialize_window(
            day="2026-09-22",
            detector_key="TEMPORAL_RECURRENCE",
            signal_type="RECURRENCE",
        )

    def _materialize_window(self, *, day, detector_key, signal_type):
        window_start = f"{day}T00:00:00+00:00"
        window_end = f"{day}T23:59:59+00:00"

        self.temporal_service.materialize_window(
            domain_code="GENERIC_DOMAIN",
            topic_key="GENERIC_TOPIC",
            window_start=window_start,
            window_end=window_end,
        )

        self.temporal_service.calculate_baseline(
            domain_code="GENERIC_DOMAIN",
            topic_key="GENERIC_TOPIC",
            reference_window_start=window_start,
            reference_window_end=window_end,
            lookback_windows=3,
        )

        self.repository.save_aggregate_signal(
            TrendAggregateSignal(
                id=None,
                domain_id=self.domain.id,
                topic_id=self.topic.id,
                signal_type=signal_type,
                window_start=window_start,
                window_end=window_end,
                strength=80.0,
                confidence=0.9,
                detector_key=detector_key,
                detector_version="1",
                reason="deterministic fixture",
            )
        )

        return self.snapshot_service.materialize(
            domain_code="GENERIC_DOMAIN",
            topic_key="GENERIC_TOPIC",
            window_start=window_start,
            window_end=window_end,
        )

    def test_scoring_components_reuse_snapshot_metadata(self):
        explanation = self.service.explain_snapshot(self.first_snapshot)

        expected = tuple(self.first_snapshot.metadata["components"])
        self.assertEqual(explanation.scoring_components, expected)

    def test_window_and_already_computed_score_are_not_recomputed(self):
        explanation = self.service.explain_snapshot(self.first_snapshot)

        self.assertEqual(explanation.status, self.first_snapshot.status)
        self.assertEqual(explanation.score, self.first_snapshot.score)
        self.assertEqual(explanation.velocity, self.first_snapshot.velocity)
        self.assertEqual(explanation.source_count, self.first_snapshot.source_count)

    def test_contributing_sources_from_raw_signals(self):
        explanation = self.service.explain_snapshot(self.first_snapshot)

        self.assertEqual(
            [item.source_code for item in explanation.contributing_sources],
            ["SOURCE_X", "SOURCE_Y"],
        )

        source_x = explanation.contributing_sources[0]
        self.assertEqual(source_x.signal_types, ("VOLUME_SPIKE",))
        # A SUCCESS run recorded against a fixed historical timestamp is
        # necessarily stale relative to wall-clock "now"; health_state is
        # reused as-is from the existing freshness infrastructure, not
        # recomputed here.
        self.assertEqual(source_x.health_state, "STALE")

    def test_recurrence_reuses_previous_snapshot_history(self):
        explanation = self.service.explain_snapshot(self.second_snapshot)

        self.assertEqual(len(explanation.recurrence), 1)
        self.assertEqual(
            explanation.recurrence[0].window_start,
            self.first_snapshot.window_start,
        )
        self.assertEqual(explanation.previous_score, self.first_snapshot.score)
        self.assertEqual(explanation.previous_status, self.first_snapshot.status)

    def test_first_window_has_no_recurrence(self):
        explanation = self.service.explain_snapshot(self.first_snapshot)

        self.assertEqual(explanation.recurrence, ())
        self.assertIsNone(explanation.previous_score)

    def test_history_limit_is_respected(self):
        explanation = self.service.explain_snapshot(self.second_snapshot, history_limit=0)

        self.assertEqual(explanation.recurrence, ())

    def test_deterministic_ordering_across_repeated_calls(self):
        first_call = self.service.explain_snapshot(self.first_snapshot)
        second_call = self.service.explain_snapshot(self.first_snapshot)

        self.assertEqual(first_call, second_call)

    def test_explain_does_not_mutate_persistence(self):
        before = self._row_counts()

        self.service.explain_snapshot(self.first_snapshot)
        self.service.explain_snapshot(self.second_snapshot)

        after = self._row_counts()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
