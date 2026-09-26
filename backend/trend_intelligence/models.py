"""
Trend Intelligence.

Motor transversal de detección de tendencias.

No depende de ningún vertical concreto.

Los dominios funcionales se representan como datos
configurables y nunca como lógica hardcoded del core.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Any


COLLECTION_MODE_API = "API"
COLLECTION_MODE_HTTP = "HTTP"
COLLECTION_MODE_MANUAL = "MANUAL"
COLLECTION_MODE_IMPORT = "IMPORT"
COLLECTION_MODE_QCC = "QCC"
COLLECTION_MODE_SELENIUM = "SELENIUM"

VALID_COLLECTION_MODES = frozenset(
    {
        COLLECTION_MODE_API,
        COLLECTION_MODE_HTTP,
        COLLECTION_MODE_MANUAL,
        COLLECTION_MODE_IMPORT,
        COLLECTION_MODE_QCC,
        COLLECTION_MODE_SELENIUM,
    }
)


SIGNAL_MENTION = "MENTION"
SIGNAL_QUESTION = "QUESTION"
SIGNAL_HIGH_ENGAGEMENT = "HIGH_ENGAGEMENT"
SIGNAL_GROWTH = "GROWTH"
SIGNAL_RECURRENCE = "RECURRENCE"
SIGNAL_NEW_TOPIC = "NEW_TOPIC"
SIGNAL_CROSS_SOURCE = "CROSS_SOURCE"
SIGNAL_VOLUME_SPIKE = "VOLUME_SPIKE"
SIGNAL_SEARCH_GROWTH = "SEARCH_GROWTH"
SIGNAL_SENTIMENT_SHIFT = "SENTIMENT_SHIFT"

VALID_SIGNAL_TYPES = frozenset(
    {
        SIGNAL_MENTION,
        SIGNAL_QUESTION,
        SIGNAL_HIGH_ENGAGEMENT,
        SIGNAL_GROWTH,
        SIGNAL_RECURRENCE,
        SIGNAL_NEW_TOPIC,
        SIGNAL_CROSS_SOURCE,
        SIGNAL_VOLUME_SPIKE,
        SIGNAL_SEARCH_GROWTH,
        SIGNAL_SENTIMENT_SHIFT,
    }
)


TREND_EMERGING = "EMERGING"
TREND_RISING = "RISING"
TREND_HOT = "HOT"
TREND_STABLE = "STABLE"
TREND_DECLINING = "DECLINING"
TREND_DORMANT = "DORMANT"

VALID_TREND_STATUSES = frozenset(
    {
        TREND_EMERGING,
        TREND_RISING,
        TREND_HOT,
        TREND_STABLE,
        TREND_DECLINING,
        TREND_DORMANT,
    }
)


@dataclass(frozen=True, slots=True)
class TrendDomain:
    id: int | None
    code: str
    name: str
    description: str | None = None
    is_active: bool = True
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendSource:
    id: int | None
    code: str
    name: str
    source_type: str
    provider: str | None = None
    base_url: str | None = None
    collection_mode: str = COLLECTION_MODE_MANUAL
    country: str | None = None
    language: str | None = None
    is_active: bool = True
    configuration: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendTopic:
    id: int | None
    topic_key: str
    name: str
    description: str | None = None
    category: str | None = None
    parent_topic_id: int | None = None
    is_active: bool = True
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TopicDomain:
    topic_id: int
    domain_id: int
    relevance: float = 1.0
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendTopicAlias:
    id: int | None
    topic_id: int
    alias_key: str
    alias_text: str
    language: str = ""
    country: str = ""
    confidence: float = 1.0
    is_active: bool = True
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationDomain:
    observation_id: int
    domain_id: int
    confidence: float = 1.0
    detection_method: str = "MANUAL"
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendObservation:
    id: int | None
    source_id: int
    observation_type: str
    external_id: str | None = None
    url: str | None = None
    title: str | None = None
    body_text: str | None = None
    author: str | None = None
    published_at: str | None = None
    observed_at: str | None = None
    language: str | None = None
    country: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationTopic:
    observation_id: int
    topic_id: int
    confidence: float = 1.0
    detection_method: str = "MANUAL"
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendSignal:
    id: int | None
    observation_id: int
    topic_id: int
    signal_type: str
    strength: float
    confidence: float = 1.0
    numeric_value: float | None = None
    text_value: str | None = None
    detected_at: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class Trend:
    id: int | None
    domain_id: int
    topic_id: int
    status: str
    score: float
    velocity: float
    observation_count: int
    source_count: int
    signal_count: int
    window_start: str
    window_end: str
    country: str = ""
    language: str = ""
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendAggregateSignal:
    id: int | None
    domain_id: int
    topic_id: int

    signal_type: str

    window_start: str
    window_end: str

    country: str = ""
    language: str = ""

    strength: float = 0.0
    confidence: float = 1.0

    numeric_value: float | None = None
    text_value: str | None = None

    detector_key: str = ""
    detector_version: str = ""

    reason: str = ""
    metadata: dict[str, Any] | None = None

    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendTemporalMetric:
    id: int | None
    domain_id: int
    topic_id: int

    window_start: str
    window_end: str

    country: str = ""
    language: str = ""

    observation_count: int = 0
    source_count: int = 0
    signal_count: int = 0

    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendTemporalBaseline:
    id: int | None
    domain_id: int
    topic_id: int

    reference_window_start: str
    reference_window_end: str

    lookback_windows: int
    sample_count: int

    country: str = ""
    language: str = ""

    observation_mean: float = 0.0
    observation_stddev: float = 0.0

    source_mean: float = 0.0
    source_stddev: float = 0.0

    signal_mean: float = 0.0
    signal_stddev: float = 0.0

    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendSnapshot:
    id: int | None

    domain_id: int
    topic_id: int

    window_start: str
    window_end: str

    country: str = ""
    language: str = ""

    status: str = TREND_DORMANT

    score: float = 0.0
    velocity: float = 0.0

    aggregate_signal_count: int = 0
    observation_count: int = 0
    source_count: int = 0

    baseline_observation_mean: float = 0.0

    metadata: dict[str, Any] | None = None

    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TrendEvidence:
    id: int | None
    trend_id: int | None
    signal_id: int
    weight: float
    reason: str
    created_at: str | None = None


# TI time contract: naive input means UTC; precision beyond microseconds is
# rejected rather than silently rounded. SQL uses TI_TIME for legacy offsets.
def canonical_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if re.search(r"[.,]\d{7,}", raw):
            raise ValueError("Timestamp precision exceeds microseconds")
        if not raw:
            raise ValueError("Timestamp required")
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def time_key(value):
    return datetime.fromisoformat(canonical_time(value))


def canonical_window(start, end):
    if time_key(start) >= time_key(end):
        raise ValueError("Window requires start < end")
    return canonical_time(start), canonical_time(end)


def canonical_country(value):
    return str(value or "").strip().upper()


def canonical_language(value):
    return str(value or "").strip().lower()


def finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("TI numerical value required") from exc
    if not math.isfinite(number):
        raise ValueError("TI numerical values must be finite")
    return number
