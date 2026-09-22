import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.acquisition.adapter import CollectorSourceAdapter
from backend.trend_intelligence.acquisition.collectors.rss import RssCollector
from backend.trend_intelligence.acquisition.normalizers.rss import RssNormalizer
from backend.trend_intelligence.ingestion import TrendIngestionService
from backend.trend_intelligence.service import TrendIntelligenceService


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Fixture Feed</title>
    <item>
      <title>Primera noticia</title>
      <link>https://example.com/1</link>
      <guid>https://example.com/1</guid>
      <pubDate>Mon, 21 Sep 2026 08:00:00 GMT</pubDate>
      <description>Cuerpo 1</description>
      <author>redaccion@example.com</author>
    </item>
    <item>
      <title>Segunda noticia</title>
      <link>https://example.com/2</link>
      <guid>https://example.com/2</guid>
      <pubDate>Mon, 21 Sep 2026 09:00:00 GMT</pubDate>
      <description>Cuerpo 2</description>
      <author>redaccion@example.com</author>
    </item>
  </channel>
</rss>
"""


def _fixed_fetcher(url):
    return RSS_FIXTURE


class TrendIntelligenceAcquisitionIdempotencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "idempotency.db"
        self.repository = SQLiteTrendIntelligenceRepository(self.db)
        self.service = TrendIntelligenceService(repository=self.repository)
        self.service.ensure_schema()

        self.service.create_domain(code="DOMAIN_TEST", name="Domain Test")
        self.service.create_source(
            code="RSS_FIXTURE",
            name="RSS Fixture",
            source_type="RSS",
            collection_mode="HTTP",
        )

        self.ingestion = TrendIngestionService(self.service)

    def tearDown(self):
        self.tmp.cleanup()

    def _adapter(self):
        collector = RssCollector(
            feed_url="https://feeds.example.com/rss",
            fetcher=_fixed_fetcher,
        )
        normalizer = RssNormalizer(
            collector_key=collector.collector_key,
            collector_version=collector.collector_version,
            provider=collector.provider,
            clock=lambda: datetime(2026, 9, 22, 8, 0, 0, tzinfo=timezone.utc),
        )
        return CollectorSourceAdapter(
            source_code="RSS_FIXTURE",
            collector=collector,
            normalizer=normalizer,
            trend_service=self.service,
        )

    def test_repeated_collection_is_idempotent(self):
        first = self.ingestion.ingest(self._adapter(), domain_code="DOMAIN_TEST")
        second = self.ingestion.ingest(self._adapter(), domain_code="DOMAIN_TEST")

        self.assertEqual(first.total, 2)
        self.assertEqual(first.created, 2)
        self.assertEqual(first.duplicates, 0)

        self.assertEqual(second.total, 2)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.duplicates, 2)

        self.assertEqual(first.observation_ids, second.observation_ids)

    def test_deterministic_replay_produces_same_run_counters(self):
        self.ingestion.ingest(self._adapter(), domain_code="DOMAIN_TEST")
        run_one = self.service.list_collector_runs("RSS_FIXTURE")[0]

        self.ingestion.ingest(self._adapter(), domain_code="DOMAIN_TEST")
        run_two = self.service.list_collector_runs("RSS_FIXTURE")[0]

        self.assertEqual(
            (run_one.items_seen, run_one.items_accepted, run_one.items_rejected),
            (run_two.items_seen, run_two.items_accepted, run_two.items_rejected),
        )
        self.assertEqual(run_one.status, run_two.status)

    def test_provenance_is_attached_to_stored_observation(self):
        report = self.ingestion.ingest(self._adapter(), domain_code="DOMAIN_TEST")
        observation = self.repository.get_observation(report.observation_ids[0])

        provenance = observation.metadata["acquisition"]
        self.assertEqual(provenance["collector_key"], "RSS_FEED")
        self.assertEqual(provenance["collector_version"], "1.0.0")
        self.assertEqual(provenance["provider"], "RSS")
        self.assertEqual(provenance["source_identity"], "https://example.com/1")


if __name__ == "__main__":
    unittest.main()
