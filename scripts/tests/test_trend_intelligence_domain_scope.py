import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)


class TrendIntelligenceDomainScopeTest(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile
            .TemporaryDirectory()
        )

        self.db = (
            Path(
                self.tmp.name
            )
            / "domain_scope.db"
        )

        self.service = (
            TrendIntelligenceService(
                repository=(
                    SQLiteTrendIntelligenceRepository(
                        self.db
                    )
                )
            )
        )

        self.service.ensure_schema()

        self.service.create_domain(
            code="DOMAIN_ALPHA",
            name="Domain Alpha",
        )

        self.service.create_domain(
            code="DOMAIN_BETA",
            name="Domain Beta",
        )

        self.service.create_source(
            code="GENERIC_WEB",
            name="Generic Web",
            source_type="WEB",
            collection_mode="HTTP",
        )

        self.service.create_topic(
            topic_key="SHARED_TOPIC",
            name="Shared Topic",
            domain_codes=(
                "DOMAIN_ALPHA",
                "DOMAIN_BETA",
            ),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _observation(
        self,
        *,
        external_id,
        domain,
        strength,
    ):
        observation, created = (
            self.service
            .record_observation(
                source_code=(
                    "GENERIC_WEB"
                ),
                observation_type="ARTICLE",
                external_id=external_id,
                title=external_id,
                observed_at=(
                    "2026-09-21T08:00:00+00:00"
                ),
            )
        )

        self.assertTrue(
            created
        )

        self.service.classify_observation(
            observation.id,
            domain_code=domain,
            topic_key="SHARED_TOPIC",
            confidence=1.0,
            detection_method="TEST",
        )

        self.service.create_signal(
            observation_id=(
                observation.id
            ),
            domain_code=domain,
            topic_key="SHARED_TOPIC",
            signal_type="GROWTH",
            strength=strength,
            confidence=1.0,
            detected_at=(
                "2026-09-21T08:00:00+00:00"
            ),
        )

        return observation

    def test_domain_scoping_prevents_signal_leakage(
        self,
    ):
        self._observation(
            external_id="ALPHA-1",
            domain="DOMAIN_ALPHA",
            strength=95,
        )

        self._observation(
            external_id="BETA-1",
            domain="DOMAIN_BETA",
            strength=25,
        )

        alpha = (
            self.service
            .recalculate_trend(
                domain_code=(
                    "DOMAIN_ALPHA"
                ),
                topic_key=(
                    "SHARED_TOPIC"
                ),
                window_start=(
                    "2026-09-21T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-21T23:59:59+00:00"
                ),
            )
        )

        beta = (
            self.service
            .recalculate_trend(
                domain_code=(
                    "DOMAIN_BETA"
                ),
                topic_key=(
                    "SHARED_TOPIC"
                ),
                window_start=(
                    "2026-09-21T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-21T23:59:59+00:00"
                ),
            )
        )

        self.assertEqual(
            alpha[
                "trend"
            ].signal_count,
            1,
        )

        self.assertEqual(
            beta[
                "trend"
            ].signal_count,
            1,
        )

        self.assertEqual(
            alpha[
                "trend"
            ].observation_count,
            1,
        )

        self.assertEqual(
            beta[
                "trend"
            ].observation_count,
            1,
        )

        self.assertGreater(
            alpha[
                "trend"
            ].score,
            beta[
                "trend"
            ].score,
        )

    def test_signal_requires_observation_domain(
        self,
    ):
        observation, _ = (
            self.service
            .record_observation(
                source_code=(
                    "GENERIC_WEB"
                ),
                observation_type=(
                    "ARTICLE"
                ),
                external_id=(
                    "UNSCOPED"
                ),
                title="Unscoped",
                observed_at=(
                    "2026-09-21T09:00:00+00:00"
                ),
            )
        )

        with self.assertRaises(
            ValueError
        ):
            self.service.create_signal(
                observation_id=(
                    observation.id
                ),
                domain_code=(
                    "DOMAIN_ALPHA"
                ),
                topic_key=(
                    "SHARED_TOPIC"
                ),
                signal_type="MENTION",
                strength=50,
                detected_at=(
                    "2026-09-21T09:00:00+00:00"
                ),
            )


if __name__ == "__main__":
    unittest.main()
