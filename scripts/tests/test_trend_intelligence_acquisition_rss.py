import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from backend.trend_intelligence.acquisition.collectors.rss import (
    RssCollector,
    _default_fetcher,
    parse_feed,
)
from backend.trend_intelligence.acquisition.contracts import (
    CollectorError,
    NormalizationError,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_PARSE,
    ERROR_RATE_LIMIT,
)
from backend.trend_intelligence.acquisition.normalizers.rss import RssNormalizer


RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Titulo</title>
      <link>https://example.com/a</link>
      <guid>guid-a</guid>
      <pubDate>Mon, 21 Sep 2026 08:00:00 GMT</pubDate>
      <description>Resumen</description>
      <author>autor@example.com</author>
    </item>
  </channel>
</rss>
"""

ATOM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Titulo Atom</title>
    <id>urn:uuid:entry-1</id>
    <link href="https://example.com/atom-1" />
    <updated>2026-09-21T08:00:00Z</updated>
    <summary>Resumen Atom</summary>
    <author><name>Autor Atom</name></author>
  </entry>
</feed>
"""

MALFORMED_XML = b"<rss><channel><item><title>Unclosed"

UNSUPPORTED_ROOT_XML = b"<html></html>"


class TrendIntelligenceAcquisitionRssParsingTest(unittest.TestCase):
    def test_parses_rss2_items(self):
        entries = parse_feed(RSS_XML)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Titulo")
        self.assertEqual(entries[0]["guid"], "guid-a")
        self.assertEqual(entries[0]["link"], "https://example.com/a")
        self.assertEqual(
            entries[0]["published_at"], "Mon, 21 Sep 2026 08:00:00 GMT"
        )
        self.assertEqual(entries[0]["summary"], "Resumen")
        self.assertEqual(entries[0]["author"], "autor@example.com")

    def test_parses_atom_entries(self):
        entries = parse_feed(ATOM_XML)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Titulo Atom")
        self.assertEqual(entries[0]["guid"], "urn:uuid:entry-1")
        self.assertEqual(entries[0]["link"], "https://example.com/atom-1")
        self.assertEqual(entries[0]["published_at"], "2026-09-21T08:00:00Z")
        self.assertEqual(entries[0]["author"], "Autor Atom")

    def test_malformed_xml_raises_parse_classified_error(self):
        with self.assertRaises(CollectorError) as ctx:
            parse_feed(MALFORMED_XML)
        self.assertEqual(ctx.exception.classification, ERROR_PARSE)

    def test_unsupported_root_raises_parse_classified_error(self):
        with self.assertRaises(CollectorError) as ctx:
            parse_feed(UNSUPPORTED_ROOT_XML)
        self.assertEqual(ctx.exception.classification, ERROR_PARSE)

    def test_default_fetcher_rejects_non_http_scheme(self):
        with self.assertRaises(CollectorError) as ctx:
            _default_fetcher("file:///etc/passwd")
        self.assertEqual(ctx.exception.classification, ERROR_NETWORK)

    @patch("backend.trend_intelligence.acquisition.collectors.rss.urlopen")
    def test_default_fetcher_classifies_auth_errors(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "https://example.com/feed", 403, "Forbidden", {}, None
        )
        with self.assertRaises(CollectorError) as ctx:
            _default_fetcher("https://example.com/feed")
        self.assertEqual(ctx.exception.classification, ERROR_AUTH)

    @patch("backend.trend_intelligence.acquisition.collectors.rss.urlopen")
    def test_default_fetcher_classifies_rate_limit_errors(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "https://example.com/feed", 429, "Too Many Requests", {}, None
        )
        with self.assertRaises(CollectorError) as ctx:
            _default_fetcher("https://example.com/feed")
        self.assertEqual(ctx.exception.classification, ERROR_RATE_LIMIT)

    @patch("backend.trend_intelligence.acquisition.collectors.rss.urlopen")
    def test_default_fetcher_classifies_url_errors_as_network(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("connection refused")
        with self.assertRaises(CollectorError) as ctx:
            _default_fetcher("https://example.com/feed")
        self.assertEqual(ctx.exception.classification, ERROR_NETWORK)

    def test_collector_wraps_fetcher_and_parses_batch(self):
        collector = RssCollector(
            feed_url="https://example.com/feed",
            fetcher=lambda url: RSS_XML,
        )
        batch = collector.collect()

        self.assertEqual(len(batch.items), 1)
        self.assertIsInstance(batch.items[0], RawCollectedItem)


class TrendIntelligenceAcquisitionRssNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = RssNormalizer(
            collector_key="RSS_FEED",
            collector_version="1.0.0",
            provider="RSS",
        )

    def test_normalizes_rfc822_pub_date(self):
        item = RawCollectedItem(
            raw_payload={
                "title": "Titulo",
                "link": "https://example.com/a",
                "guid": "guid-a",
                "published_at": "Mon, 21 Sep 2026 08:00:00 GMT",
                "summary": "Resumen",
                "author": "autor@example.com",
            }
        )
        observation = self.normalizer.normalize(item)

        self.assertEqual(observation.external_id, "guid-a")
        self.assertEqual(observation.published_at, "2026-09-21T08:00:00+00:00")
        self.assertEqual(
            observation.metadata["acquisition"]["source_identity"], "guid-a"
        )

    def test_normalizes_iso8601_published_date(self):
        item = RawCollectedItem(
            raw_payload={
                "title": "Titulo Atom",
                "link": "https://example.com/atom-1",
                "guid": "urn:uuid:entry-1",
                "published_at": "2026-09-21T08:00:00Z",
                "summary": "Resumen",
                "author": "Autor Atom",
            }
        )
        observation = self.normalizer.normalize(item)

        self.assertEqual(observation.published_at, "2026-09-21T08:00:00+00:00")

    def test_missing_guid_and_link_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={
                "title": "Titulo",
                "published_at": "Mon, 21 Sep 2026 08:00:00 GMT",
            }
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)

    def test_missing_title_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={
                "guid": "guid-a",
                "published_at": "Mon, 21 Sep 2026 08:00:00 GMT",
            }
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)

    def test_missing_published_date_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={"title": "Titulo", "guid": "guid-a"}
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)

    def test_unparsable_published_date_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={
                "title": "Titulo",
                "guid": "guid-a",
                "published_at": "not-a-date",
            }
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)


if __name__ == "__main__":
    unittest.main()
