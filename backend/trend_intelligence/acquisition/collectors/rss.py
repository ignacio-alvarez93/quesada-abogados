"""
RSS 2.0 / Atom collector.

Stdlib only: no new dependency, no browser automation. Network fetch is
injectable so tests never perform real HTTP calls.
"""

import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from backend.trend_intelligence.acquisition.contracts import (
    CollectorBatch,
    CollectorError,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_PARSE,
    ERROR_RATE_LIMIT,
)


ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _default_fetcher(url, *, timeout=15):
    parsed = urlsplit(url)

    if parsed.scheme not in ("http", "https"):
        raise CollectorError(
            f"Unsupported feed scheme: {parsed.scheme or '<empty>'}",
            classification=ERROR_NETWORK,
        )

    request = Request(
        url,
        headers={"User-Agent": "TrendIntelligenceCollector/1.0"},
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code in (401, 403):
            classification = ERROR_AUTH
        elif exc.code == 429:
            classification = ERROR_RATE_LIMIT
        else:
            classification = ERROR_NETWORK
        raise CollectorError(
            f"HTTP {exc.code} fetching feed",
            classification=classification,
        ) from exc
    except URLError as exc:
        raise CollectorError(str(exc.reason), classification=ERROR_NETWORK) from exc


def _text_of(element, tag):
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _parse_rss_item(item):
    guid = _text_of(item, "guid") or _text_of(item, "link")
    return {
        "title": _text_of(item, "title"),
        "link": _text_of(item, "link"),
        "guid": guid,
        "published_at": _text_of(item, "pubDate"),
        "summary": _text_of(item, "description"),
        "author": _text_of(item, "author"),
    }


def _parse_atom_entry(entry):
    link_el = entry.find(f"{ATOM_NS}link")
    link = link_el.get("href") if link_el is not None else None

    author_el = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")
    author = author_el.text.strip() if (author_el is not None and author_el.text) else None

    return {
        "title": _text_of(entry, f"{ATOM_NS}title"),
        "link": link,
        "guid": _text_of(entry, f"{ATOM_NS}id") or link,
        "published_at": (
            _text_of(entry, f"{ATOM_NS}updated")
            or _text_of(entry, f"{ATOM_NS}published")
        ),
        "summary": (
            _text_of(entry, f"{ATOM_NS}summary")
            or _text_of(entry, f"{ATOM_NS}content")
        ),
        "author": author,
    }


def parse_feed(raw_bytes):
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError as exc:
        raise CollectorError(
            f"Malformed feed XML: {exc}",
            classification=ERROR_PARSE,
        ) from exc

    if root.tag == "rss":
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []
        return [_parse_rss_item(item) for item in items]

    if root.tag in (f"{ATOM_NS}feed", "feed"):
        entries = root.findall(f"{ATOM_NS}entry") or root.findall("entry")
        return [_parse_atom_entry(entry) for entry in entries]

    raise CollectorError(
        f"Unsupported feed root element: {root.tag}",
        classification=ERROR_PARSE,
    )


class RssCollector:
    collector_key = "RSS_FEED"
    collector_version = "1.0.0"
    provider = "RSS"

    def __init__(self, *, feed_url, fetcher=None):
        self.feed_url = str(feed_url or "").strip()

        if not self.feed_url:
            raise ValueError("feed_url obligatorio")

        self._fetcher = fetcher or _default_fetcher

    def collect(self, *, cursor=None):
        raw_bytes = self._fetcher(self.feed_url)
        entries = parse_feed(raw_bytes)

        items = tuple(
            RawCollectedItem(raw_payload=entry)
            for entry in entries
        )

        # RSS/Atom feeds are not naturally paginated; idempotency is
        # delegated to the existing external_id/content_hash dedup at the
        # ingestion layer, so the cursor simply passes through unchanged.
        return CollectorBatch(items=items, next_cursor=cursor)
