"""IT Instagram Collector v1: ingestion, dedupe/idempotency and pipeline reuse.

No network, no Chrome: Instagram observations are injected as
InstagramRawObservation fixtures through the existing, unmodified
TrendIngestionService / TrendIntelligenceService contracts.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.ingestion import TrendIngestionService
from backend.trend_intelligence.service import TrendIntelligenceService
from backend.trend_intelligence.sources.instagram_browser import (
    InstagramAccessBlockedError,
    InstagramCollectionConfig,
    InstagramCollectionTarget,
    run_instagram_collection,
)
from backend.trend_intelligence.sources import (
    InstagramRawObservation,
    InstagramTrendSourceAdapter,
    ManualTrendSourceAdapter,
    TrendObservationInput,
)


def _raw(**overrides):
    defaults = dict(
        source_account="example_account",
        external_id="ABC123",
        canonical_url="https://www.instagram.com/p/ABC123/",
        content_type="POST",
        observed_at="2026-10-11T10:00:00+00:00",
        caption="Hello #trend",
    )
    defaults.update(overrides)
    return InstagramRawObservation(**defaults)


class InstagramIngestionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

        self.repository = SQLiteTrendIntelligenceRepository(
            Path(self.tmp.name) / "instagram.db"
        )

        self.service = TrendIntelligenceService(repository=self.repository)
        self.service.ensure_schema()

        self.service.create_domain(
            code="MARKETING_TEST",
            name="Marketing Test",
        )

        self.service.create_source(
            code="INSTAGRAM_TEST",
            name="Instagram Test",
            source_type="SOCIAL",
            collection_mode="SELENIUM",
        )

        self.ingestion = TrendIngestionService(self.service)

    def tearDown(self):
        self.tmp.cleanup()

    def _adapter(self, raws):
        return InstagramTrendSourceAdapter("INSTAGRAM_TEST", raws)

    def test_ingestion_creates_observation_through_existing_contract(self):
        report = self.ingestion.ingest(
            self._adapter([_raw()]),
            domain_code="MARKETING_TEST",
        )

        self.assertEqual(report.total, 1)
        self.assertEqual(report.created, 1)
        self.assertEqual(report.duplicates, 0)

        observation = self.repository.get_observation(report.observation_ids[0])
        self.assertEqual(observation.external_id, "ABC123")
        self.assertEqual(observation.author, "example_account")

    def test_collection_failure_never_enters_ingestion(self):
        config = InstagramCollectionConfig(source_code="INSTAGRAM_TEST", targets=(
            InstagramCollectionTarget("first", 2),
            InstagramCollectionTarget("failed", 3),
            InstagramCollectionTarget("unvisited", 1),
        ))
        for error_type in (InstagramAccessBlockedError, RuntimeError, TimeoutError):
            with self.subTest(error_type=error_type):
                error = error_type("collection failed")
                collector = Mock()
                collector.collect_account.side_effect = [[_raw()], error]
                ingestion = Mock(wraps=self.ingestion)
                with self.assertRaises(error_type) as caught:
                    run_instagram_collection(collector=collector, config=config,
                                             ingestion_service=ingestion)
                self.assertIs(caught.exception, error)
                self.assertEqual(collector.collect_account.call_args_list, [
                    call("first", limit=2), call("failed", limit=3),
                ])
                ingestion.ingest.assert_not_called()
                collector.start.assert_not_called()
                collector.shutdown.assert_not_called()

    def test_empty_collection_is_a_successful_zero_report(self):
        collector = Mock()
        collector.collect_account.return_value = []
        config = InstagramCollectionConfig(source_code="INSTAGRAM_TEST", targets=(
            InstagramCollectionTarget("empty"),
        ))
        report = run_instagram_collection(collector=collector, config=config,
                                          ingestion_service=self.ingestion)
        self.assertEqual(report.source_code, "INSTAGRAM_TEST")
        self.assertEqual((report.total, report.created, report.duplicates),
                         (0, 0, 0))
        self.assertEqual(report.observation_ids, ())
        collector.start.assert_not_called()
        collector.shutdown.assert_not_called()

    def test_repeated_observation_of_same_post_is_idempotent(self):
        first = self.ingestion.ingest(
            self._adapter([_raw()]),
            domain_code="MARKETING_TEST",
        )

        second = self.ingestion.ingest(
            self._adapter([_raw()]),
            domain_code="MARKETING_TEST",
        )

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.duplicates, 1)
        self.assertEqual(first.observation_ids, second.observation_ids)

    def test_two_different_posts_remain_distinct_after_ingestion(self):
        report = self.ingestion.ingest(
            self._adapter(
                [
                    _raw(external_id="POST-1"),
                    _raw(
                        external_id="POST-2",
                        canonical_url="https://www.instagram.com/p/POST-2/",
                    ),
                ]
            ),
            domain_code="MARKETING_TEST",
        )

        self.assertEqual(report.created, 2)
        self.assertEqual(len(set(report.observation_ids)), 2)

    def test_bad_observation_preserves_crm_fail_fast_contract(self):
        # Marketing's partial rejection report is deliberately not ported.
        with self.assertRaises(ValueError):
            self.ingestion.ingest(
                self._adapter([_raw(observed_at="not-a-timestamp")]),
                domain_code="MARKETING_TEST",
            )
        report = self.ingestion.ingest(self._adapter([_raw()]))
        self.assertEqual(report.created, 1)
        # Preserve positional construction and the existing public report shape.
        self.assertEqual(type(report)("INSTAGRAM_TEST", 1, 1, 0, report.observation_ids), report)

    def test_existing_pipeline_consumes_instagram_observations(self):
        report = self.ingestion.ingest(
            self._adapter([_raw()]),
            domain_code="MARKETING_TEST",
        )

        observation_id = report.observation_ids[0]

        self.service.create_topic(
            topic_key="TOPIC_TEST",
            name="Topic Test",
            domain_codes=("MARKETING_TEST",),
        )

        self.service.classify_observation(
            observation_id,
            domain_code="MARKETING_TEST",
            topic_key="TOPIC_TEST",
        )

        self.service.create_signal(
            observation_id=observation_id,
            domain_code="MARKETING_TEST",
            topic_key="TOPIC_TEST",
            signal_type="MENTION",
            strength=70,
            detected_at="2026-10-11T10:00:00+00:00",
        )

        result = self.service.recalculate_trend(
            domain_code="MARKETING_TEST",
            topic_key="TOPIC_TEST",
            window_start="2026-10-11T00:00:00+00:00",
            window_end="2026-10-12T00:00:00+00:00",
        )

        self.assertEqual(result["trend"].observation_count, 1)
        self.assertEqual(result["trend"].signal_count, 1)

        # Raw Instagram metadata (hashtags/metrics) never leaks into the
        # explainable scoring contract, same guarantee already proven for
        # other sources.
        trend_metadata = result["trend"].metadata or {}
        self.assertNotIn("hashtags", trend_metadata)

    def test_manual_source_remains_compatible_alongside_instagram(self):
        self.service.create_source(
            code="MANUAL_TEST",
            name="Manual Test",
            source_type="MANUAL",
            collection_mode="MANUAL",
        )

        manual_adapter = ManualTrendSourceAdapter(
            "MANUAL_TEST",
            [
                TrendObservationInput(
                    observation_type="ARTICLE",
                    external_id="MANUAL-1",
                    title="Manual item",
                    observed_at="2026-10-11T09:00:00+00:00",
                ),
            ],
        )

        manual_report = self.ingestion.ingest(
            manual_adapter,
            domain_code="MARKETING_TEST",
        )

        instagram_report = self.ingestion.ingest(
            self._adapter([_raw()]),
            domain_code="MARKETING_TEST",
        )

        self.assertEqual(manual_report.created, 1)
        self.assertEqual(instagram_report.created, 1)
        self.assertNotEqual(
            manual_report.observation_ids,
            instagram_report.observation_ids,
        )


if __name__ == "__main__":
    unittest.main()
