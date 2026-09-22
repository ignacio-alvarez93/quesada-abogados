"""
YouTube metadata collector.

Uses googleapiclient (already a project dependency for Gmail/Calendar
integrations). The API client/resource is injected so tests never
perform real network calls; no browser automation is involved.
"""

from googleapiclient.errors import HttpError

from backend.trend_intelligence.acquisition.contracts import (
    CollectorBatch,
    CollectorError,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_RATE_LIMIT,
    ERROR_UNKNOWN,
)


def _classify_youtube_error(exc):
    status = getattr(getattr(exc, "resp", None), "status", None)

    if status in (401, 403):
        return ERROR_AUTH

    if status == 429:
        return ERROR_RATE_LIMIT

    if status is not None and 500 <= status < 600:
        return ERROR_NETWORK

    return ERROR_UNKNOWN


class YouTubeSearchCollector:
    collector_key = "YOUTUBE_SEARCH"
    collector_version = "1.0.0"
    provider = "YOUTUBE"

    def __init__(self, *, client, channel_id=None, query=None, max_results=25):
        self.client = client
        self.channel_id = str(channel_id or "").strip() or None
        self.query = str(query or "").strip() or None
        self.max_results = int(max_results)

        if not self.channel_id and not self.query:
            raise ValueError("channel_id o query obligatorio")

    def collect(self, *, cursor=None):
        request_kwargs = {
            "part": "snippet",
            "type": "video",
            "order": "date",
            "maxResults": self.max_results,
        }

        if self.channel_id:
            request_kwargs["channelId"] = self.channel_id

        if self.query:
            request_kwargs["q"] = self.query

        if cursor:
            request_kwargs["pageToken"] = cursor

        try:
            response = self.client.search().list(**request_kwargs).execute()
        except HttpError as exc:
            raise CollectorError(
                str(exc),
                classification=_classify_youtube_error(exc),
            ) from exc

        items = tuple(
            RawCollectedItem(raw_payload=item)
            for item in response.get("items", [])
        )

        return CollectorBatch(
            items=items,
            next_cursor=response.get("nextPageToken"),
        )
