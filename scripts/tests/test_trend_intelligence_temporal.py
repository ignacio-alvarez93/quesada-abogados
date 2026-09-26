import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)
from backend.trend_intelligence.temporal import (
    TrendTemporalIntelligenceService,
)


class TrendIntelligenceTemporalTest(
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
                / "temporal.db"
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

        self.core.create_domain(
            code="DOMAIN_A",
            name="Domain A",
        )

        self.core.create_domain(
            code="DOMAIN_B",
            name="Domain B",
        )

        self.core.create_source(
            code="SOURCE_ONE",
            name="Source One",
            source_type="WEB",
            collection_mode="HTTP",
            country="ES",
            language="es",
        )

        self.core.create_source(
            code="SOURCE_TWO",
            name="Source Two",
            source_type="WEB",
            collection_mode="HTTP",
            country="ES",
            language="es",
        )

        self.core.create_topic(
            topic_key="TOPIC_SHARED",
            name="Topic Shared",
            domain_codes=(
                "DOMAIN_A",
                "DOMAIN_B",
            ),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _observation(
        self,
        *,
        source,
        domain,
        external_id,
        observed_at,
        with_signal=False,
    ):
        observation, created = (
            self.core
            .record_observation(
                source_code=source,
                observation_type="ARTICLE",
                external_id=external_id,
                title=external_id,
                observed_at=(
                    observed_at
                ),
                country="ES",
                language="es",
            )
        )

        self.assertTrue(
            created
        )

        self.core.classify_observation(
            observation.id,
            domain_code=domain,
            topic_key="TOPIC_SHARED",
            confidence=1.0,
            detection_method="TEST",
        )

        if with_signal:
            self.core.create_signal(
                observation_id=(
                    observation.id
                ),
                domain_code=domain,
                topic_key=(
                    "TOPIC_SHARED"
                ),
                signal_type="MENTION",
                strength=50,
                confidence=1.0,
                detected_at=(
                    observed_at
                ),
            )

        return observation

    def test_materialize_window_counts_observations_without_signals(
        self,
    ):
        self._observation(
            source="SOURCE_ONE",
            domain="DOMAIN_A",
            external_id="A-1",
            observed_at=(
                "2026-09-20T10:00:00+00:00"
            ),
        )

        self._observation(
            source="SOURCE_TWO",
            domain="DOMAIN_A",
            external_id="A-2",
            observed_at=(
                "2026-09-20T11:00:00+00:00"
            ),
        )

        metric = (
            self.temporal
            .materialize_window(
                domain_code=(
                    "DOMAIN_A"
                ),
                topic_key=(
                    "TOPIC_SHARED"
                ),
                window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                country="ES",
                language="es",
            )
        )

        self.assertEqual(
            metric.observation_count,
            2,
        )

        self.assertEqual(
            metric.source_count,
            2,
        )

        self.assertEqual(
            metric.signal_count,
            0,
        )

    def test_temporal_metrics_are_domain_isolated(
        self,
    ):
        self._observation(
            source="SOURCE_ONE",
            domain="DOMAIN_A",
            external_id="A-ISO",
            observed_at=(
                "2026-09-20T10:00:00+00:00"
            ),
            with_signal=True,
        )

        self._observation(
            source="SOURCE_ONE",
            domain="DOMAIN_B",
            external_id="B-ISO",
            observed_at=(
                "2026-09-20T10:00:00+00:00"
            ),
        )

        alpha = (
            self.temporal
            .materialize_window(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                country="ES",
                language="es",
            )
        )

        beta = (
            self.temporal
            .materialize_window(
                domain_code="DOMAIN_B",
                topic_key="TOPIC_SHARED",
                window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                country="ES",
                language="es",
            )
        )

        self.assertEqual(
            alpha.observation_count,
            1,
        )

        self.assertEqual(
            beta.observation_count,
            1,
        )

        self.assertEqual(
            alpha.signal_count,
            1,
        )

        self.assertEqual(
            beta.signal_count,
            0,
        )

    def test_metric_upsert_is_idempotent(
        self,
    ):
        self._observation(
            source="SOURCE_ONE",
            domain="DOMAIN_A",
            external_id="IDEMPOTENT",
            observed_at=(
                "2026-09-20T10:00:00+00:00"
            ),
        )

        first = (
            self.temporal
            .materialize_window(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                country="ES",
                language="es",
            )
        )

        second = (
            self.temporal
            .materialize_window(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                country="ES",
                language="es",
            )
        )

        self.assertEqual(
            first.id,
            second.id,
        )

    def test_baseline_uses_only_previous_windows(
        self,
    ):
        counts = (
            2,
            4,
            6,
        )

        dates = (
            "2026-09-17",
            "2026-09-18",
            "2026-09-19",
        )

        sequence = 0

        for date, count in zip(
            dates,
            counts,
        ):
            for index in range(
                count
            ):
                sequence += 1

                self._observation(
                    source="SOURCE_ONE",
                    domain="DOMAIN_A",
                    external_id=(
                        f"HIST-{sequence}"
                    ),
                    observed_at=(
                        f"{date}T10:00:00+00:00"
                    ),
                )

            self.temporal.materialize_window(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                window_start=(
                    f"{date}T00:00:00+00:00"
                ),
                window_end=(
                    f"{date}T23:59:59+00:00"
                ),
                country="ES",
                language="es",
            )

        baseline = (
            self.temporal
            .calculate_baseline(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                reference_window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                reference_window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                lookback_windows=3,
                country="ES",
                language="es",
            )
        )

        self.assertEqual(
            baseline.sample_count,
            3,
        )

        self.assertEqual(
            baseline.observation_mean,
            4.0,
        )

        self.assertGreater(
            baseline.observation_stddev,
            0.0,
        )

    def test_analysis_detects_growth_against_baseline(
        self,
    ):
        history = (
            (
                "2026-09-17",
                2,
            ),
            (
                "2026-09-18",
                2,
            ),
            (
                "2026-09-19",
                2,
            ),
        )

        sequence = 0

        for date, count in history:
            for _ in range(
                count
            ):
                sequence += 1

                self._observation(
                    source="SOURCE_ONE",
                    domain="DOMAIN_A",
                    external_id=(
                        f"BASE-{sequence}"
                    ),
                    observed_at=(
                        f"{date}T10:00:00+00:00"
                    ),
                )

            self.temporal.materialize_window(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                window_start=(
                    f"{date}T00:00:00+00:00"
                ),
                window_end=(
                    f"{date}T23:59:59+00:00"
                ),
                country="ES",
                language="es",
            )

        for index in range(
            8
        ):
            self._observation(
                source=(
                    "SOURCE_ONE"
                    if index % 2 == 0
                    else "SOURCE_TWO"
                ),
                domain="DOMAIN_A",
                external_id=(
                    f"CURRENT-{index}"
                ),
                observed_at=(
                    "2026-09-20T10:00:00+00:00"
                ),
            )

        analysis = (
            self.temporal
            .analyze_window(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                lookback_windows=3,
                country="ES",
                language="es",
            )
        )

        self.assertEqual(
            analysis.metric.observation_count,
            8,
        )

        self.assertEqual(
            analysis.baseline.observation_mean,
            2.0,
        )

        self.assertEqual(
            analysis.observation_growth_percent,
            300.0,
        )

        self.assertGreater(
            analysis.observation_z_score,
            0.0,
        )

    def test_empty_history_baseline_is_safe(
        self,
    ):
        baseline = (
            self.temporal
            .calculate_baseline(
                domain_code="DOMAIN_A",
                topic_key="TOPIC_SHARED",
                reference_window_start=(
                    "2026-09-20T00:00:00+00:00"
                ),
                reference_window_end=(
                    "2026-09-20T23:59:59+00:00"
                ),
                lookback_windows=7,
                country="ES",
                language="es",
            )
        )

        self.assertEqual(
            baseline.sample_count,
            0,
        )

        self.assertEqual(
            baseline.observation_mean,
            0.0,
        )

        self.assertEqual(
            baseline.observation_stddev,
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
