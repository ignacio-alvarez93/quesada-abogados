import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.batch import (
    TrendBatchService,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)


class TrendIntelligenceBatchTest(
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
                / "batch.db"
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

        self.batch = (
            TrendBatchService(
                self.service
            )
        )

        self.service.create_domain(
            code="DOMAIN_BATCH",
            name="Domain Batch",
        )

        self.service.create_source(
            code="SOURCE_BATCH",
            name="Source Batch",
            source_type="WEB",
            collection_mode="HTTP",
        )

        for key in (
            "TOPIC_ONE",
            "TOPIC_TWO",
            "TOPIC_EMPTY",
        ):
            self.service.create_topic(
                topic_key=key,
                name=key,
                domain_codes=(
                    "DOMAIN_BATCH",
                ),
            )

    def tearDown(self):
        self.tmp.cleanup()

    def _signal(
        self,
        *,
        topic_key,
        external_id,
        strength,
    ):
        observation, created = (
            self.service
            .record_observation(
                source_code=(
                    "SOURCE_BATCH"
                ),
                observation_type=(
                    "ARTICLE"
                ),
                external_id=(
                    external_id
                ),
                title=topic_key,
                observed_at=(
                    "2026-09-21T09:00:00+00:00"
                ),
            )
        )

        self.assertTrue(
            created
        )

        self.service.classify_observation(
            observation.id,
            domain_code=(
                "DOMAIN_BATCH"
            ),
            topic_key=(
                topic_key
            ),
        )

        self.service.create_signal(
            observation_id=(
                observation.id
            ),
            domain_code=(
                "DOMAIN_BATCH"
            ),
            topic_key=(
                topic_key
            ),
            signal_type="GROWTH",
            strength=strength,
            detected_at=(
                "2026-09-21T09:00:00+00:00"
            ),
        )

    def test_batch_recalculates_all_domain_topics(
        self,
    ):
        self._signal(
            topic_key="TOPIC_ONE",
            external_id="ONE",
            strength=90,
        )

        self._signal(
            topic_key="TOPIC_TWO",
            external_id="TWO",
            strength=50,
        )

        result = (
            self.batch
            .recalculate_domain(
                "DOMAIN_BATCH",
                window_start=(
                    "2026-09-21T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-21T23:59:59+00:00"
                ),
            )
        )

        self.assertEqual(
            result.topic_count,
            3,
        )

        self.assertEqual(
            result.calculated_count,
            3,
        )

        indexed = {
            item.topic_key:
                item
            for item
            in result.items
        }

        self.assertEqual(
            indexed[
                "TOPIC_ONE"
            ].signal_count,
            1,
        )

        self.assertEqual(
            indexed[
                "TOPIC_TWO"
            ].signal_count,
            1,
        )

        self.assertEqual(
            indexed[
                "TOPIC_EMPTY"
            ].signal_count,
            0,
        )

        self.assertGreater(
            indexed[
                "TOPIC_ONE"
            ].score,
            indexed[
                "TOPIC_TWO"
            ].score,
        )

    def test_batch_can_skip_empty_topics(
        self,
    ):
        self._signal(
            topic_key="TOPIC_ONE",
            external_id="ONE-2",
            strength=90,
        )

        result = (
            self.batch
            .recalculate_domain(
                "DOMAIN_BATCH",
                window_start=(
                    "2026-09-21T00:00:00+00:00"
                ),
                window_end=(
                    "2026-09-21T23:59:59+00:00"
                ),
                include_empty=False,
            )
        )

        self.assertEqual(
            result.topic_count,
            3,
        )

        self.assertEqual(
            result.calculated_count,
            1,
        )

        self.assertEqual(
            result.items[
                0
            ].topic_key,
            "TOPIC_ONE",
        )


if __name__ == "__main__":
    unittest.main()
