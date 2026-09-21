import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)


class TrendIntelligenceQueryApiTest(
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
            / "query.db"
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
            code="GENERIC_DOMAIN",
            name="Generic Domain",
        )

        self.service.create_source(
            code="GENERIC_SOURCE",
            name="Generic Source",
            source_type="WEB",
            collection_mode="HTTP",
        )

        self.service.create_topic(
            topic_key="GENERIC_TOPIC",
            name="Generic Topic",
            domain_codes=(
                "GENERIC_DOMAIN",
            ),
        )

        observation, _ = (
            self.service
            .record_observation(
                source_code=(
                    "GENERIC_SOURCE"
                ),
                observation_type=(
                    "ARTICLE"
                ),
                external_id="QUERY-1",
                title="Query test",
                observed_at=(
                    "2026-09-21T08:00:00+00:00"
                ),
            )
        )

        self.service.classify_observation(
            observation.id,
            domain_code=(
                "GENERIC_DOMAIN"
            ),
            topic_key=(
                "GENERIC_TOPIC"
            ),
        )

        self.service.create_signal(
            observation_id=(
                observation.id
            ),
            domain_code=(
                "GENERIC_DOMAIN"
            ),
            topic_key=(
                "GENERIC_TOPIC"
            ),
            signal_type=(
                "VOLUME_SPIKE"
            ),
            strength=95,
            detected_at=(
                "2026-09-21T08:00:00+00:00"
            ),
        )

        self.result = (
            self.service
            .recalculate_trend(
                domain_code=(
                    "GENERIC_DOMAIN"
                ),
                topic_key=(
                    "GENERIC_TOPIC"
                ),
                window_start=(
                    "2026-09-21T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-21T23:59:59+00:00"
                ),
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_domain_trends(
        self,
    ):
        items = (
            self.service
            .list_domain_trends(
                "GENERIC_DOMAIN"
            )
        )

        self.assertEqual(
            len(
                items
            ),
            1,
        )

        self.assertEqual(
            items[0].id,
            self.result[
                "trend"
            ].id,
        )

    def test_evidence_query(
        self,
    ):
        evidence = (
            self.service
            .get_trend_evidence(
                self.result[
                    "trend"
                ].id
            )
        )

        self.assertEqual(
            len(
                evidence
            ),
            1,
        )

        self.assertIn(
            "VOLUME_SPIKE",
            evidence[0].reason,
        )


if __name__ == "__main__":
    unittest.main()
