import unittest

from backend.trend_intelligence.advanced_detection import (
    CrossSourceRecurrenceDetector,
)
from backend.trend_intelligence.models import (
    SIGNAL_CROSS_SOURCE,
    SIGNAL_RECURRENCE,
    TrendTemporalMetric,
)


def metric(
    *,
    day,
    observations,
    sources,
):
    return TrendTemporalMetric(
        id=None,
        domain_id=1,
        topic_id=1,
        window_start=(
            f"{day}T00:00:00+00:00"
        ),
        window_end=(
            f"{day}T23:59:59+00:00"
        ),
        observation_count=observations,
        source_count=sources,
        signal_count=0,
    )


class AdvancedDetectionTest(
    unittest.TestCase
):
    def test_cross_source_and_recurrence(
        self,
    ):
        detector = (
            CrossSourceRecurrenceDetector()
        )

        result = detector.detect(
            current_metric=metric(
                day="2026-09-21",
                observations=10,
                sources=4,
            ),
            historical_metrics=[
                metric(
                    day="2026-09-20",
                    observations=4,
                    sources=2,
                ),
                metric(
                    day="2026-09-19",
                    observations=3,
                    sources=2,
                ),
            ],
        )

        types = {
            item.signal_type
            for item
            in result.signals
        }

        self.assertIn(
            SIGNAL_CROSS_SOURCE,
            types,
        )

        self.assertIn(
            SIGNAL_RECURRENCE,
            types,
        )

    def test_single_source_not_cross_source(
        self,
    ):
        result = (
            CrossSourceRecurrenceDetector()
            .detect(
                current_metric=metric(
                    day="2026-09-21",
                    observations=10,
                    sources=1,
                ),
                historical_metrics=[],
            )
        )

        types = {
            item.signal_type
            for item
            in result.signals
        }

        self.assertNotIn(
            SIGNAL_CROSS_SOURCE,
            types,
        )


if __name__ == "__main__":
    unittest.main()
