import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.pipeline import (
    TrendAutomaticPipelineService,
)
from backend.trend_intelligence.regression import (
    TrendRegressionGateService,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)
from backend.trend_intelligence.temporal import (
    TrendTemporalIntelligenceService,
    _datetime,
)


class TrendIntelligenceHandoffPipelineTest(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile
            .TemporaryDirectory()
        )

        self.repo = (
            SQLiteTrendIntelligenceRepository(
                Path(self.tmp.name)
                / "handoff.db"
            )
        )

        self.core = (
            TrendIntelligenceService(
                repository=self.repo
            )
        )

        self.core.ensure_schema()

        self.temporal = (
            TrendTemporalIntelligenceService(
                self.repo
            )
        )

        self.pipeline = (
            TrendAutomaticPipelineService(
                repository=self.repo,
                temporal_service=(
                    self.temporal
                ),
            )
        )

        self.core.create_domain(
            code="DOMAIN_X",
            name="Domain X",
        )

        self.sources = (
            "SOURCE_A",
            "SOURCE_B",
            "SOURCE_C",
            "SOURCE_D",
        )

        for source in self.sources:
            self.core.create_source(
                code=source,
                name=source,
                source_type="WEB",
                collection_mode="HTTP",
            )

        self.core.create_topic(
            topic_key="TOPIC_X",
            name="Topic X",
            domain_codes=(
                "DOMAIN_X",
            ),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def add_observations(
        self,
        *,
        day,
        count,
    ):
        for index in range(count):
            observation, created = (
                self.core.record_observation(
                    source_code=(
                        self.sources[
                            index
                            % len(self.sources)
                        ]
                    ),
                    observation_type="ARTICLE",
                    external_id=(
                        f"{day}-{index}"
                    ),
                    title=(
                        f"{day}-{index}"
                    ),
                    observed_at=(
                        f"{day}T10:00:00+00:00"
                    ),
                )
            )

            self.assertTrue(created)

            self.core.classify_observation(
                observation.id,
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
            )

    def test_canonical_utc(self):
        self.assertEqual(
            _datetime(
                "2026-09-21T12:00:00+02:00"
            ),
            "2026-09-21T10:00:00+00:00",
        )

        self.assertEqual(
            _datetime(
                "2026-09-21T10:00:00Z"
            ),
            "2026-09-21T10:00:00+00:00",
        )

    def test_pipeline_replay_and_regression_gate(
        self,
    ):
        data = (
            ("2026-09-17", 2),
            ("2026-09-18", 2),
            ("2026-09-19", 2),
            ("2026-09-20", 20),
        )

        results = []

        for day, count in data:
            self.add_observations(
                day=day,
                count=count,
            )

            results.append(
                self.pipeline.process_window(
                    domain_code="DOMAIN_X",
                    topic_key="TOPIC_X",
                    window_start=(
                        f"{day}T00:00:00+00:00"
                    ),
                    window_end=(
                        f"{day}T23:59:59+00:00"
                    ),
                    lookback_windows=3,
                )
            )

        final = results[-1]

        self.assertEqual(
            set(final.signal_types),
            {
                "VOLUME_SPIKE",
                "GROWTH",
                "CROSS_SOURCE",
                "RECURRENCE",
            },
        )

        self.assertEqual(
            final.status,
            "HOT",
        )

        replay_1 = (
            self.pipeline
            .replay_existing_windows(
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
                lookback_windows=3,
            )
        )

        replay_2 = (
            self.pipeline
            .replay_existing_windows(
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
                lookback_windows=3,
            )
        )

        self.assertEqual(
            replay_1.processed_windows,
            4,
        )

        self.assertEqual(
            replay_1.signature,
            replay_2.signature,
        )

        domain = (
            self.repo.get_domain_by_code(
                "DOMAIN_X"
            )
        )

        topic = (
            self.repo.get_topic_by_key(
                "TOPIC_X"
            )
        )

        snapshots = (
            self.repo.list_trend_snapshots(
                domain.id,
                topic.id,
                ascending=True,
            )
        )

        self.assertEqual(
            len(snapshots),
            4,
        )

        self.assertEqual(
            snapshots[0]
            .baseline_observation_mean,
            0.0,
        )

        self.assertGreater(
            snapshots[-1]
            .baseline_observation_mean,
            0.0,
        )

        gate = (
            TrendRegressionGateService(
                repository=self.repo,
                temporal_service=self.temporal,
            )
            .run_scope(
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
            )
        )

        self.assertTrue(
            gate.passed,
            gate.violations,
        )


if __name__ == "__main__":
    unittest.main()
