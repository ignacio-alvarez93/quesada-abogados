"""
Generic collector contract for Trend Intelligence source acquisition.

A Collector fetches provider-specific raw payloads. It never normalizes,
never persists and never classifies topics.

A Normalizer turns a single raw payload into the existing V1
TrendObservationInput contract. It never performs network I/O.

The pairing (Collector, Normalizer) is composed by
backend.trend_intelligence.acquisition.adapter.CollectorSourceAdapter,
which implements the existing TrendSourceAdapter protocol so the
unchanged V1 ingestion pipeline can consume it.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from backend.trend_intelligence.acquisition.models import (
    ERROR_UNKNOWN,
    VALID_ERROR_CLASSIFICATIONS,
)
from backend.trend_intelligence.sources.base import TrendObservationInput


class CollectorError(Exception):
    """Raised by a Collector when acquisition fails.

    classification must be one of VALID_ERROR_CLASSIFICATIONS so run
    lifecycle/health reporting stays deterministic across providers.
    """

    def __init__(self, message, *, classification=ERROR_UNKNOWN):
        super().__init__(message)

        classification = str(classification or ERROR_UNKNOWN).strip().upper()

        if classification not in VALID_ERROR_CLASSIFICATIONS:
            classification = ERROR_UNKNOWN

        self.classification = classification


class NormalizationError(Exception):
    """Raised by a Normalizer when a raw payload cannot be normalized.

    Never raised for network/auth failures: those belong to CollectorError.
    """


@dataclass(frozen=True, slots=True)
class RawCollectedItem:
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CollectorBatch:
    items: tuple[RawCollectedItem, ...]
    next_cursor: str | None = None


class Collector(Protocol):
    @property
    def collector_key(self) -> str:
        ...

    @property
    def collector_version(self) -> str:
        ...

    @property
    def provider(self) -> str:
        ...

    def collect(self, *, cursor: str | None = None) -> CollectorBatch:
        ...


class Normalizer(Protocol):
    def normalize(self, raw_item: RawCollectedItem) -> TrendObservationInput:
        ...
