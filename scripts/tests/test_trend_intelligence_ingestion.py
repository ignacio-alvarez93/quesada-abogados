import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.ingestion import (
    TrendIngestionService,
)
from backend.trend_intelligence.service import (
    TrendIntelligenceService,
)
from backend.trend_intelligence.sources import (
    ManualTrendSourceAdapter,
    TrendObservationInput,
)


class TrendIntelligenceIngestionTest(
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
            / "ingestion.db"
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

        self.service.create_source(
            code="MANUAL_TEST",
            name="Manual Test",
            source_type="MANUAL",
            collection_mode="MANUAL",
        )

        self.ingestion = (
            TrendIngestionService(
                self.service
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _adapter(
        self,
    ):
        return ManualTrendSourceAdapter(
            "MANUAL_TEST",
            [
                TrendObservationInput(
                    observation_type=(
                        "ARTICLE"
                    ),
                    external_id="ROW-1",
                    title="Primera",
                    observed_at=(
                        "2026-09-21T08:00:00+00:00"
                    ),
                ),
                TrendObservationInput(
                    observation_type=(
                        "ARTICLE"
                    ),
                    external_id="ROW-2",
                    title="Segunda",
                    observed_at=(
                        "2026-09-21T08:01:00+00:00"
                    ),
                ),
            ],
        )

    def test_ingestion_creates_observations(
        self,
    ):
        report = (
            self.ingestion
            .ingest(
                self._adapter(),
                domain_code=(
                    "DOMAIN_TEST"
                ),
            )
        )

        self.assertEqual(
            report.total,
            2,
        )

        self.assertEqual(
            report.created,
            2,
        )

        self.assertEqual(
            report.duplicates,
            0,
        )

        self.assertEqual(
            len(
                report.observation_ids
            ),
            2,
        )

        for observation_id in (
            report.observation_ids
        ):
            links = (
                self.repository
                .list_observation_domains(
                    observation_id
                )
            )

            self.assertEqual(
                len(
                    links
                ),
                1,
            )

    def test_repeated_ingestion_is_idempotent(
        self,
    ):
        first = (
            self.ingestion
            .ingest(
                self._adapter(),
                domain_code=(
                    "DOMAIN_TEST"
                ),
            )
        )

        second = (
            self.ingestion
            .ingest(
                self._adapter(),
                domain_code=(
                    "DOMAIN_TEST"
                ),
            )
        )

        self.assertEqual(
            first.created,
            2,
        )

        self.assertEqual(
            second.created,
            0,
        )

        self.assertEqual(
            second.duplicates,
            2,
        )

        self.assertEqual(
            first.observation_ids,
            second.observation_ids,
        )


if __name__ == "__main__":
    unittest.main()
