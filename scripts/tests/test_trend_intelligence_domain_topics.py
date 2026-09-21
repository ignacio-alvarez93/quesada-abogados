import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)


class TrendIntelligenceDomainTopicsTest(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile
            .TemporaryDirectory()
        )

        self.service = (
            TrendIntelligenceService(
                repository=(
                    SQLiteTrendIntelligenceRepository(
                        Path(
                            self.tmp.name
                        )
                        / "domain_topics.db"
                    )
                )
            )
        )

        self.service.ensure_schema()

        self.service.create_domain(
            code="DOMAIN_A",
            name="Domain A",
        )

        self.service.create_domain(
            code="DOMAIN_B",
            name="Domain B",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_topics_are_filtered_by_domain(
        self,
    ):
        self.service.create_topic(
            topic_key="TOPIC_A",
            name="Topic A",
            domain_codes=(
                "DOMAIN_A",
            ),
        )

        self.service.create_topic(
            topic_key="TOPIC_B",
            name="Topic B",
            domain_codes=(
                "DOMAIN_B",
            ),
        )

        domain_a = (
            self.service
            .list_domain_topics(
                "DOMAIN_A"
            )
        )

        domain_b = (
            self.service
            .list_domain_topics(
                "DOMAIN_B"
            )
        )

        self.assertEqual(
            [
                item.topic_key
                for item
                in domain_a
            ],
            [
                "TOPIC_A",
            ],
        )

        self.assertEqual(
            [
                item.topic_key
                for item
                in domain_b
            ],
            [
                "TOPIC_B",
            ],
        )


if __name__ == "__main__":
    unittest.main()
