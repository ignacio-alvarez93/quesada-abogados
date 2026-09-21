import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)


class TrendIntelligenceGenericDomainsTest(
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
            / "generic.db"
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

        self.service.create_source(
            code="WEB_GENERAL",
            name="Web General",
            source_type="WEB",
            collection_mode="HTTP",
            country="ES",
            language="es",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _build_trend(
        self,
        *,
        domain,
        topic,
        external_id,
        title,
        signal_type,
    ):
        self.service.create_domain(
            code=domain,
            name=domain,
        )

        self.service.create_topic(
            topic_key=topic,
            name=title,
            domain_codes=[
                domain
            ],
        )

        observation, created = (
            self.service
            .record_observation(
                source_code=(
                    "WEB_GENERAL"
                ),
                observation_type=(
                    "ARTICLE"
                ),
                external_id=(
                    external_id
                ),
                title=title,
                observed_at=(
                    "2026-09-20T10:00:00+00:00"
                ),
            )
        )

        self.assertTrue(
            created
        )

        self.service.classify_observation(
            observation.id,
            domain_code=domain,
            topic_key=topic,
            confidence=1.0,
        )

        self.service.create_signal(
            observation_id=(
                observation.id
            ),
            domain_code=domain,
            topic_key=topic,
            signal_type=(
                signal_type
            ),
            strength=85,
            confidence=0.95,
            detected_at=(
                "2026-09-20T10:00:00+00:00"
            ),
        )

        return (
            self.service
            .recalculate_trend(
                domain_code=domain,
                topic_key=topic,
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

    def test_engine_supports_unrelated_verticals(
        self,
    ):
        vertical_a = (
            self._build_trend(
                domain="VERTICAL_A",
                topic=(
                    "VERTICAL_A_TOPIC_1"
                ),
                external_id="A-1",
                title="Tema A",
                signal_type="GROWTH",
            )
        )

        vertical_b = (
            self._build_trend(
                domain="VERTICAL_B",
                topic=(
                    "VERTICAL_B_TOPIC_1"
                ),
                external_id="B-1",
                title="Tema B",
                signal_type=(
                    "SEARCH_GROWTH"
                ),
            )
        )

        self.assertNotEqual(
            vertical_a[
                "trend"
            ].domain_id,
            vertical_b[
                "trend"
            ].domain_id,
        )

        self.assertNotEqual(
            vertical_a[
                "trend"
            ].topic_id,
            vertical_b[
                "trend"
            ].topic_id,
        )

        self.assertEqual(
            len(
                vertical_a[
                    "evidence"
                ]
            ),
            1,
        )

        self.assertEqual(
            len(
                vertical_b[
                    "evidence"
                ]
            ),
            1,
        )

    def test_same_source_can_feed_multiple_domains(
        self,
    ):
        self._build_trend(
            domain="DOMAIN_ONE",
            topic="DOMAIN_ONE_TOPIC",
            external_id="ONE",
            title="One",
            signal_type="MENTION",
        )

        self._build_trend(
            domain="DOMAIN_TWO",
            topic="DOMAIN_TWO_TOPIC",
            external_id="TWO",
            title="Two",
            signal_type="QUESTION",
        )

        source = (
            self.service
            .repository
            .get_source_by_code(
                "WEB_GENERAL"
            )
        )

        self.assertIsNotNone(
            source
        )


if __name__ == "__main__":
    unittest.main()
