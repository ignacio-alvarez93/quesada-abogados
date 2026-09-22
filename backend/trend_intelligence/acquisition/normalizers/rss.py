"""
Normalizes raw RSS/Atom entries into the unchanged V1
TrendObservationInput contract.

Provider-specific payload shapes never cross this boundary: only the
whitelisted TrendObservationInput fields plus structured provenance
metadata leave this module.
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from backend.trend_intelligence.acquisition.contracts import NormalizationError
from backend.trend_intelligence.acquisition.provenance import (
    build_provenance,
    with_provenance,
)
from backend.trend_intelligence.models import canonical_time
from backend.trend_intelligence.sources.base import TrendObservationInput


def _parse_flexible_datetime(value):
    # RSS uses RFC 822 (pubDate); Atom uses ISO 8601 (updated/published).
    errors = []

    try:
        parsed = parsedate_to_datetime(value)
        if parsed is not None:
            return canonical_time(parsed)
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))

    try:
        return canonical_time(value)
    except ValueError as exc:
        errors.append(str(exc))

    raise ValueError("; ".join(errors) or "unparsable datetime")


class RssNormalizer:
    def __init__(
        self,
        *,
        collector_key,
        collector_version,
        provider="RSS",
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

        guid = payload.get("guid") or payload.get("link")
        if not guid:
            raise NormalizationError("RSS entry missing guid/link")

        title = payload.get("title")
        if not title:
            raise NormalizationError("RSS entry missing title")

        published_at = payload.get("published_at")
        if not published_at:
            raise NormalizationError("RSS entry missing published date")

        try:
            canonical_published_at = _parse_flexible_datetime(published_at)
        except ValueError as exc:
            raise NormalizationError(
                f"RSS entry has unparsable published date: {exc}"
            ) from exc

        provenance = build_provenance(
            collector_key=self.collector_key,
            collector_version=self.collector_version,
            provider=self.provider,
            source_identity=guid,
        )

        return TrendObservationInput(
            observation_type="ARTICLE",
            external_id=str(guid),
            url=payload.get("link"),
            title=title,
            body_text=payload.get("summary"),
            author=payload.get("author"),
            published_at=canonical_published_at,
            observed_at=canonical_time(self._clock()),
            language=self.language,
            country=self.country,
            metadata=with_provenance(None, provenance),
        )
