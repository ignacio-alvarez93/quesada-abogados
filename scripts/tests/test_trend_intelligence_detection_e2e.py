import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.detection import (
    AutomaticVolumeGrowthDetector,
)
from backend.trend_intelligence.models import (
    SIGNAL_GROWTH,
    SIGNAL_VOLUME_SPIKE,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)
from backend.trend_intelligence.temporal import (
    TrendTemporalIntelligenceService,
)


class TrendIntelligenceDetectionE2ETest(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile
            .TemporaryDirectory()
        )

        self.repository = (
            SQLiteTrendIntelligenceRepository(
                Path(
                    self.tmp.name
                )
                / "detection_e2e.db"
            )
        )

        self.core = (
            TrendIntelligenceService(
                repository=(
                    self.repository
                )
            )
        )

        self.core.ensure_schema()

        self.temporal = (
            TrendTemporalIntelligenceService(
                self.repository
            )
        )

        self.detector = (
            AutomaticVolumeGrowthDetector()
        )

        self.core.create_domain(
            code="DOMAIN_X",
            name="Domain X",
        )

        for source in (
            "SOURCE_A",
            "SOURCE_B",
            "SOURCE_C",
        ):
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

    def _create_observations(
        self,
        *,
        date,
        count,
        prefix,
    ):
        sources = (
            "SOURCE_A",
            "SOURCE_B",
            "SOURCE_C",
        )

        for index in range(
            count
        ):
            observation, created = (
                self.core
                .record_observation(
                    source_code=(
                        sources[
                            index
                            % len(
                                sources
                            )
                        ]
                    ),
                    observation_type=(
                        "ARTICLE"
                    ),
                    external_id=(
                        f"{prefix}-{index}"
                    ),
                    title=(
                        f"{prefix}-{index}"
                    ),
                    observed_at=(
                        f"{date}T10:00:00+00:00"
                    ),
                )
            )

            self.assertTrue(
                created
            )

            self.core.classify_observation(
                observation.id,
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
            )

    def test_temporal_growth_creates_detection_candidates(
        self,
    ):
        for date, count in (
            (
                "2026-09-17",
                2,
            ),
            (
                "2026-09-18",
                3,
            ),
            (
                "2026-09-19",
                2,
            ),
        ):
            self._create_observations(
                date=date,
                count=count,
                prefix=date,
            )

            self.temporal.materialize_window(
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
                window_start=(
                    f"{date}T00:00:00+00:00"
                ),
                window_end=(
                    f"{date}T23:59:59+00:00"
                ),
            )

        self._create_observations(
            date="2026-09-20",
            count=15,
            prefix="CURRENT",
        )

        analysis = (
            self.temporal
            .analyze_window(
                domain_code="DOMAIN_X",
                topic_key="TOPIC_X",
                window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                lookback_windows=3,
            )
        )

        detection = (
            self.detector.detect(
                analysis
            )
        )

        signal_types = {
            signal.signal_type
            for signal
            in detection.signals
        }

        self.assertTrue(
            detection.baseline_ready
        )

        self.assertIn(
            SIGNAL_VOLUME_SPIKE,
            signal_types,
        )

        self.assertIn(
            SIGNAL_GROWTH,
            signal_types,
        )

        self.assertEqual(
            detection.current_observation_count,
            15,
        )

        self.assertEqual(
            detection.baseline_sample_count,
            3,
        )


if __name__ == "__main__":
    unittest.main()
