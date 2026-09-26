import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)


class TrendIntelligenceTopicAliasesTest(
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
            / "aliases.db"
        )

        self.repository = (
            SQLiteTrendIntelligenceRepository(
                self.db
            )
        )

        self.service = (
            TrendIntelligenceService(
                repository=(
                    self.repository
                )
            )
        )

        self.service.ensure_schema()

        self.service.create_domain(
            code="DOMAIN_TEST",
            name="Domain Test",
        )

        self.topic = (
            self.service
            .create_topic(
                topic_key=(
                    "CANONICAL_TOPIC"
                ),
                name=(
                    "Canonical Topic"
                ),
                domain_codes=(
                    "DOMAIN_TEST",
                ),
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_direct_topic_key_resolves(
        self,
    ):
        resolved = (
            self.service
            .resolve_topic(
                "CANONICAL_TOPIC"
            )
        )

        self.assertEqual(
            resolved.id,
            self.topic.id,
        )

    def test_alias_resolves_to_canonical_topic(
        self,
    ):
        self.service.register_topic_alias(
            "CANONICAL_TOPIC",
            "Alternative wording",
            language="en",
        )

        resolved = (
            self.service
            .resolve_topic(
                "Alternative wording",
                language="en",
            )
        )

        self.assertIsNotNone(
            resolved
        )

        self.assertEqual(
            resolved.id,
            self.topic.id,
        )

    def test_alias_normalization_is_stable(
        self,
    ):
        first = (
            self.service
            .register_topic_alias(
                "CANONICAL_TOPIC",
                "some topic wording",
                language="en",
                country="US",
                confidence=0.7,
            )
        )

        second = (
            self.service
            .register_topic_alias(
                "CANONICAL_TOPIC",
                "Some Topic Wording",
                language="en",
                country="US",
                confidence=0.95,
            )
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        aliases = (
            self.repository
            .list_topic_aliases(
                self.topic.id
            )
        )

        self.assertEqual(
            len(
                aliases
            ),
            1,
        )

        self.assertEqual(
            aliases[0].confidence,
            0.95,
        )

    def test_country_specific_alias_has_priority(
        self,
    ):
        self.service.register_topic_alias(
            "CANONICAL_TOPIC",
            "Shared label",
            language="en",
            country="",
        )

        other = (
            self.service
            .create_topic(
                topic_key=(
                    "OTHER_TOPIC"
                ),
                name=(
                    "Other Topic"
                ),
                domain_codes=(
                    "DOMAIN_TEST",
                ),
            )
        )

        self.service.register_topic_alias(
            "OTHER_TOPIC",
            "Shared label",
            language="en",
            country="GB",
        )

        resolved = (
            self.service
            .resolve_topic(
                "Shared label",
                language="en",
                country="GB",
            )
        )

        self.assertEqual(
            resolved.id,
            other.id,
        )


if __name__ == "__main__":
    unittest.main()
