"""
Normalizes raw YouTube search#list items into the unchanged V1
TrendObservationInput contract.

Provider-specific payload shapes (search result envelope, snippet
structure) never cross this boundary.
"""

from datetime import datetime, timezone

from backend.trend_intelligence.acquisition.contracts import NormalizationError
from backend.trend_intelligence.acquisition.provenance import (
    build_provenance,
    with_provenance,
)
from backend.trend_intelligence.models import canonical_time
from backend.trend_intelligence.sources.base import TrendObservationInput


class YouTubeNormalizer:
    def __init__(
        self,
        *,
        collector_key,
        collector_version,
        provider="YOUTUBE",
        language=None,
        country=None,
        clock=None,
    ):
        self.collector_key = collector_key
        self.collector_version = collector_version
        self.provider = provider
        self.language = language
        self.country = country
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def normalize(self, raw_item):
        payload = raw_item.raw_payload

        video_id = (payload.get("id") or {}).get("videoId")
        if not video_id:
            raise NormalizationError("YouTube search result missing videoId")

        snippet = payload.get("snippet") or {}

        title = snippet.get("title")
        if not title:
            raise NormalizationError("YouTube search result missing title")

        published_at = snippet.get("publishedAt")
        if not published_at:
            raise NormalizationError("YouTube search result missing publishedAt")

        try:
            canonical_published_at = canonical_time(published_at)
        except ValueError as exc:
            raise NormalizationError(
                f"YouTube search result has unparsable publishedAt: {exc}"
            ) from exc

        provenance = build_provenance(
            collector_key=self.collector_key,
            collector_version=self.collector_version,
            provider=self.provider,
            source_identity=video_id,
        )

        return TrendObservationInput(
            observation_type="VIDEO",
            external_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=title,
            body_text=snippet.get("description"),
            author=snippet.get("channelTitle"),
            published_at=canonical_published_at,
            observed_at=canonical_time(self._clock()),
            language=self.language,
            country=self.country,
            metadata=with_provenance(None, provenance),
        )
