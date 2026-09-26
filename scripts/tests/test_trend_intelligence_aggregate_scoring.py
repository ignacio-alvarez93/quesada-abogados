import unittest

from backend.trend_intelligence.aggregate_scoring import (
    AggregateTrendScorer,
)
from backend.trend_intelligence.models import (
    TrendAggregateSignal,
)


def signal(
    signal_type,
    strength,
    confidence=0.95,
):
    return TrendAggregateSignal(
        id=None,
        domain_id=1,
        topic_id=1,
        signal_type=signal_type,
        window_start=(
            "2026-09-21T00:00:00+00:00"
        ),
        window_end=(
            "2026-09-21T23:59:59+00:00"
        ),
        strength=strength,
        confidence=confidence,
        detector_key="TEST",
        detector_version="1",
        reason="TEST",
    )


class AggregateScoringTest(
    unittest.TestCase
):
    def test_strong_multi_signal_window_is_hot(
        self,
    ):
        result = (
            AggregateTrendScorer()
            .calculate(
                [
                    signal(
                        "VOLUME_SPIKE",
                        100,
                    ),
                    signal(
                        "GROWTH",
                        95,
                    ),
                    signal(
                        "CROSS_SOURCE",
                        90,
                    ),
                    signal(
                        "RECURRENCE",
                        85,
                    ),
                ]
            )
        )

        self.assertGreaterEqual(
            result.score,
            80.0,
        )

        self.assertEqual(
            result.status,
            "HOT",
        )

        self.assertEqual(
            result.signal_type_count,
            4,
        )

    def test_declining_window_uses_velocity(
        self,
    ):
        result = (
            AggregateTrendScorer()
            .calculate(
                [
                    signal(
                        "MENTION",
                        40,
                        0.8,
                    ),
                ],
                prior_score=85.0,
            )
        )

        self.assertLessEqual(
            result.velocity,
            -15.0,
        )

        self.assertEqual(
            result.status,
            "DECLINING",
        )

    def test_empty_window_is_dormant(
        self,
    ):
        result = (
            AggregateTrendScorer()
            .calculate(
                [],
                prior_score=60.0,
            )
        )

        self.assertEqual(
            result.score,
            0.0,
        )

        self.assertEqual(
            result.status,
            "DORMANT",
        )


if __name__ == "__main__":
    unittest.main()
