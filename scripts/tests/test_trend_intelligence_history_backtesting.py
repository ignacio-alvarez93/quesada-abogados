import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.models import (
    TrendAggregateSignal,
    TrendTemporalMetric,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)
from backend.trend_intelligence.temporal import (
    TrendTemporalIntelligenceService,
)
from backend.trend_intelligence.trend_history import (
    TrendBacktestingService,
    TrendSnapshotService,
)


class HistoryBacktestingTest(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile
            .TemporaryDirectory()
        )

        self.repo = (
            SQLiteTrendIntelligenceRepository(
                Path(
                    self.tmp.name
                )
                / "history.db"
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

        self.core.create_domain(
            code="DOMAIN_X",
            name="Domain X",
        )

        self.core.create_topic(
            topic_key="TOPIC_X",
            name="Topic X",
            domain_codes=(
                "DOMAIN_X",
            ),
        )

        self.domain = (
            self.repo.get_domain_by_code(
                "DOMAIN_X"
            )
        )

        self.topic = (
            self.repo.get_topic_by_key(
                "TOPIC_X"
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def add_window(
        self,
        *,
        day,
        observations,
        sources,
        signal_specs,
    ):
        metric = (
            self.repo
            .save_temporal_metric(
                TrendTemporalMetric(
                    id=None,
                    domain_id=(
                        self.domain.id
                    ),
                    topic_id=(
                        self.topic.id
                    ),
                    window_start=(
                        f"{day}T00:00:00+00:00"
                    ),
                    window_end=(
                        f"{day}T23:59:59+00:00"
                    ),
                    observation_count=(
                        observations
                    ),
                    source_count=(
                        sources
                    ),
                    signal_count=0,
                )
            )
        )

        for (
            signal_type,
            strength,
        ) in signal_specs:

            self.repo.save_aggregate_signal(
                TrendAggregateSignal(
                    id=None,
                    domain_id=(
                        self.domain.id
                    ),
                    topic_id=(
                        self.topic.id
                    ),
                    signal_type=(
                        signal_type
                    ),
                    window_start=(
                        metric.window_start
                    ),
                    window_end=(
                        metric.window_end
                    ),
                    strength=(
                        strength
                    ),
                    confidence=0.95,
                    detector_key=(
                        f"TEST_{signal_type}"
                    ),
                    detector_version="1",
                    reason="TEST",
                )
            )

        return metric

    def test_snapshot_upsert_is_idempotent(
        self,
    ):
        metric = self.add_window(
            day="2026-09-21",
            observations=20,
            sources=4,
            signal_specs=(
                (
                    "VOLUME_SPIKE",
                    100,
                ),
                (
                    "GROWTH",
                    95,
                ),
                (
                    "CROSS_SOURCE",
                    90,
                ),
            ),
        )

        service = (
            TrendSnapshotService(
                repository=self.repo,
                temporal_service=(
                    self.temporal
                ),
            )
        )

        first = service.materialize(
            domain_code="DOMAIN_X",
            topic_key="TOPIC_X",
            window_start=(
                metric.window_start
            ),
            window_end=(
                metric.window_end
            ),
        )

        second = service.materialize(
            domain_code="DOMAIN_X",
            topic_key="TOPIC_X",
            window_start=(
                metric.window_start
            ),
            window_end=(
                metric.window_end
            ),
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        history = (
            self.repo.list_trend_snapshots(
                self.domain.id,
                self.topic.id,
            )
        )

        self.assertEqual(
            len(history),
            1,
        )

        self.assertGreater(
            second.score,
            60.0,
        )

    def test_backtest_is_historical_and_non_mutating(
        self,
    ):
        self.add_window(
            day="2026-09-19",
            observations=3,
            sources=1,
            signal_specs=(
                (
                    "RECURRENCE",
                    45,
                ),
            ),
        )

        self.add_window(
            day="2026-09-20",
            observations=8,
            sources=3,
            signal_specs=(
                (
                    "GROWTH",
                    75,
                ),
                (
                    "CROSS_SOURCE",
                    75,
                ),
            ),
        )

        self.add_window(
            day="2026-09-21",
            observations=20,
            sources=4,
            signal_specs=(
                (
                    "VOLUME_SPIKE",
                    100,
                ),
                (
                    "GROWTH",
                    95,
                ),
                (
                    "CROSS_SOURCE",
                    90,
                ),
                (
                    "RECURRENCE",
                    85,
                ),
            ),
        )

        result = (
            TrendBacktestingService(
                repository=self.repo,
                temporal_service=(
                    self.temporal
                ),
            )
            .run(
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
            )
        )

        self.assertEqual(
            result.window_count,
            3,
        )

        self.assertGreater(
            result.final_score,
            result.windows[0].score,
        )

        self.assertGreaterEqual(
            result.peak_score,
            result.final_score,
        )

        snapshots = (
            self.repo.list_trend_snapshots(
                self.domain.id,
                self.topic.id,
            )
        )

        self.assertEqual(
            snapshots,
            [],
        )


if __name__ == "__main__":
    unittest.main()
