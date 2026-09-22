import unittest

import httplib2
from googleapiclient.errors import HttpError

from backend.trend_intelligence.acquisition.collectors.youtube import (
    YouTubeSearchCollector,
    _classify_youtube_error,
)
from backend.trend_intelligence.acquisition.contracts import (
    CollectorError,
    NormalizationError,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_RATE_LIMIT,
    ERROR_UNKNOWN,
)
from backend.trend_intelligence.acquisition.normalizers.youtube import (
    YouTubeNormalizer,
)


class _FakeSearchRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeSearchResource:
    def __init__(self, response, captured_calls):
        self._response = response
        self._captured_calls = captured_calls

    def list(self, **kwargs):
        self._captured_calls.append(kwargs)
        return _FakeSearchRequest(self._response)


class _FakeYouTubeClient:
    def __init__(self, response):
        self._response = response
        self.captured_calls = []

    def search(self):
        return _FakeSearchResource(self._response, self.captured_calls)


class _FailingSearchRequest:
    def __init__(self, error):
        self._error = error

    def execute(self):
        raise self._error


class _FailingYouTubeClient:
    def __init__(self, error):
        self._error = error

    def search(self):
        return self

    def list(self, **kwargs):
        return _FailingSearchRequest(self._error)


def _http_error(status):
    return HttpError(
        httplib2.Response({"status": status}),
        b'{"error": {"message": "boom"}}',
    )


class TrendIntelligenceAcquisitionYouTubeCollectorTest(unittest.TestCase):
    def test_collects_items_and_next_cursor(self):
        response = {
            "items": [
                {"id": {"videoId": "abc"}, "snippet": {"title": "A"}},
                {"id": {"videoId": "def"}, "snippet": {"title": "B"}},
            ],
            "nextPageToken": "page-2",
        }
        client = _FakeYouTubeClient(response)
        collector = YouTubeSearchCollector(client=client, channel_id="UC123")

        batch = collector.collect()

        self.assertEqual(len(batch.items), 2)
        self.assertEqual(batch.next_cursor, "page-2")

    def test_cursor_is_forwarded_as_page_token(self):
        client = _FakeYouTubeClient({"items": []})
        collector = YouTubeSearchCollector(client=client, query="ley")

        collector.collect(cursor="page-5")

        self.assertEqual(client.captured_calls[0]["pageToken"], "page-5")
        self.assertEqual(client.captured_calls[0]["q"], "ley")

    def test_requires_channel_id_or_query(self):
        with self.assertRaises(ValueError):
            YouTubeSearchCollector(client=_FakeYouTubeClient({"items": []}))

    def test_http_error_is_wrapped_as_collector_error(self):
        client = _FailingYouTubeClient(_http_error(403))
        collector = YouTubeSearchCollector(client=client, channel_id="UC123")

        with self.assertRaises(CollectorError) as ctx:
            collector.collect()

        self.assertEqual(ctx.exception.classification, ERROR_AUTH)

    def test_classify_youtube_error_maps_status_codes(self):
        self.assertEqual(_classify_youtube_error(_http_error(401)), ERROR_AUTH)
        self.assertEqual(_classify_youtube_error(_http_error(429)), ERROR_RATE_LIMIT)
        self.assertEqual(_classify_youtube_error(_http_error(503)), ERROR_NETWORK)
        self.assertEqual(_classify_youtube_error(_http_error(418)), ERROR_UNKNOWN)


class TrendIntelligenceAcquisitionYouTubeNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = YouTubeNormalizer(
            collector_key="YOUTUBE_SEARCH",
            collector_version="1.0.0",
            provider="YOUTUBE",
        )

    def test_normalizes_valid_search_result(self):
        item = RawCollectedItem(
            raw_payload={
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "Video Title",
                    "description": "Description",
                    "channelTitle": "Channel",
                    "publishedAt": "2026-09-21T08:00:00Z",
                },
            }
        )
        observation = self.normalizer.normalize(item)

        self.assertEqual(observation.external_id, "abc123")
        self.assertEqual(
            observation.url, "https://www.youtube.com/watch?v=abc123"
        )
        self.assertEqual(observation.published_at, "2026-09-21T08:00:00+00:00")
        self.assertEqual(
            observation.metadata["acquisition"]["source_identity"], "abc123"
        )

    def test_missing_video_id_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={
                "id": {},
                "snippet": {
                    "title": "X",
                    "publishedAt": "2026-09-21T08:00:00Z",
                },
            }
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)

    def test_missing_title_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={
                "id": {"videoId": "abc"},
                "snippet": {"publishedAt": "2026-09-21T08:00:00Z"},
            }
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)

    def test_missing_published_at_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={
                "id": {"videoId": "abc"},
                "snippet": {"title": "X"},
            }
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)

    def test_unparsable_published_at_is_rejected(self):
        item = RawCollectedItem(
            raw_payload={
                "id": {"videoId": "abc"},
                "snippet": {"title": "X", "publishedAt": "not-a-date"},
            }
        )
        with self.assertRaises(NormalizationError):
            self.normalizer.normalize(item)


if __name__ == "__main__":
    unittest.main()
