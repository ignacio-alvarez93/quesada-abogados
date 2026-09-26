import unittest

from backend.trend_intelligence.detection import (
    AutomaticSignalDetectionConfig,
    AutomaticVolumeGrowthDetector,
)
from backend.trend_intelligence.models import (
    SIGNAL_GROWTH,
    SIGNAL_VOLUME_SPIKE,
    TrendTemporalBaseline,
    TrendTemporalMetric,
)
from backend.trend_intelligence.temporal import (
    TemporalWindowAnalysis,
)


def analysis(
    *,
    current,
    sources,
    baseline_mean,
    baseline_stddev,
    samples,
    growth,
    z_score,
):
    metric = TrendTemporalMetric(
        id=1,
        domain_id=1,
        topic_id=1,
        window_start=(
            "2026-09-21T00:00:00+00:00"
        ),
        window_end=(
            "2026-09-21T23:59:59+00:00"
        ),
        observation_count=current,
        source_count=sources,
        signal_count=0,
    )

    baseline = TrendTemporalBaseline(
        id=1,
        domain_id=1,
        topic_id=1,
        reference_window_start=(
            metric.window_start
        ),
        reference_window_end=(
            metric.window_end
        ),
        lookback_windows=7,
        sample_count=samples,
        observation_mean=(
            baseline_mean
        ),
        observation_stddev=(
            baseline_stddev
        ),
    )

    return TemporalWindowAnalysis(
        metric=metric,
        baseline=baseline,
        observation_growth_percent=(
            growth
        ),
        source_growth_percent=None,
        signal_growth_percent=None,
        observation_z_score=(
            z_score
        ),
        source_z_score=0.0,
        signal_z_score=0.0,
    )


class TrendIntelligenceDetectionTest(
    unittest.TestCase
):
    def setUp(self):
        self.detector = (
            AutomaticVolumeGrowthDetector()
        )

    def test_insufficient_baseline_produces_no_signal(
        self,
    ):
        result = (
            self.detector.detect(
                analysis(
                    current=50,
                    sources=5,
                    baseline_mean=2,
                    baseline_stddev=1,
                    samples=2,
                    growth=2400.0,
                    z_score=48.0,
                )
            )
        )

        self.assertFalse(
            result.baseline_ready
        )

        self.assertEqual(
            result.signals,
            (),
        )

    def test_low_volume_produces_no_signal(
        self,
    ):
        result = (
            self.detector.detect(
                analysis(
                    current=2,
                    sources=1,
                    baseline_mean=1,
                    baseline_stddev=0.1,
                    samples=7,
                    growth=100.0,
                    z_score=10.0,
                )
            )
        )

        self.assertTrue(
            result.baseline_ready
        )

        self.assertEqual(
            result.signals,
            (),
        )

    def test_volume_spike_is_detected(
        self,
    ):
        result = (
            self.detector.detect(
                analysis(
                    current=12,
                    sources=4,
                    baseline_mean=3,
                    baseline_stddev=1,
                    samples=7,
                    growth=300.0,
                    z_score=9.0,
                )
            )
        )

        types = {
            item.signal_type
            for item
            in result.signals
        }

        self.assertIn(
            SIGNAL_VOLUME_SPIKE,
            types,
        )

        volume = next(
            item
            for item
            in result.signals
            if (
                item.signal_type
                == SIGNAL_VOLUME_SPIKE
            )
        )

        self.assertGreater(
            volume.strength,
            80.0,
        )

        self.assertGreater(
            volume.confidence,
            0.8,
        )

        self.assertEqual(
            volume.detector_key,
            "TEMPORAL_VOLUME_SPIKE",
        )

    def test_growth_is_detected(
        self,
    ):
        result = (
            self.detector.detect(
                analysis(
                    current=8,
                    sources=3,
                    baseline_mean=4,
                    baseline_stddev=2,
                    samples=7,
                    growth=100.0,
                    z_score=2.0,
                )
            )
        )

        types = {
            item.signal_type
            for item
            in result.signals
        }

        self.assertIn(
            SIGNAL_GROWTH,
            types,
        )

        growth = next(
            item
            for item
            in result.signals
            if (
                item.signal_type
                == SIGNAL_GROWTH
            )
        )

        self.assertEqual(
            growth.numeric_value,
            100.0,
        )

        self.assertEqual(
            growth.detector_version,
            "1",
        )

    def test_stable_window_produces_no_signal(
        self,
    ):
        result = (
            self.detector.detect(
                analysis(
                    current=10,
                    sources=3,
                    baseline_mean=9,
                    baseline_stddev=3,
                    samples=7,
                    growth=11.11,
                    z_score=0.33,
                )
            )
        )

        self.assertEqual(
            result.signals,
            (),
        )

    def test_negative_growth_produces_no_signal(
        self,
    ):
        result = (
            self.detector.detect(
                analysis(
                    current=5,
                    sources=3,
                    baseline_mean=10,
                    baseline_stddev=2,
                    samples=7,
                    growth=-50.0,
                    z_score=-2.5,
                )
            )
        )

        self.assertEqual(
            result.signals,
            (),
        )

    def test_detection_is_deterministic(
        self,
    ):
        candidate = analysis(
            current=15,
            sources=5,
            baseline_mean=3,
            baseline_stddev=1,
            samples=7,
            growth=400.0,
            z_score=12.0,
        )

        first = (
            self.detector.detect(
                candidate
            )
        )

        second = (
            self.detector.detect(
                candidate
            )
        )

        self.assertEqual(
            first,
            second,
        )

    def test_custom_thresholds_are_supported(
        self,
    ):
        detector = (
            AutomaticVolumeGrowthDetector(
                AutomaticSignalDetectionConfig(
                    min_baseline_samples=5,
                    min_current_observations=10,
                    volume_spike_growth_percent=300,
                    volume_spike_z_score=5,
                    growth_growth_percent=200,
                    growth_z_score=4,
                )
            )
        )

        result = detector.detect(
            analysis(
                current=8,
                sources=3,
                baseline_mean=4,
                baseline_stddev=2,
                samples=7,
                growth=100.0,
                z_score=2.0,
            )
        )

        self.assertEqual(
            result.signals,
            (),
        )


if __name__ == "__main__":
    unittest.main()
