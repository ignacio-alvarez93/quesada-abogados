"""
Trend Intelligence · Source Acquisition V1.

Provider-neutral layer that gets raw source data into the existing
V1 canonical ingestion pipeline (TrendObservationInput -> record_observation).

This package does not change V1 scoring, ingestion or repository
contracts. It only adds acquisition-side contracts (collector, run
lifecycle, normalization, provenance, source health) that produce
TrendObservationInput instances consumed unchanged by
backend.trend_intelligence.ingestion.TrendIngestionService.
"""

from backend.trend_intelligence.acquisition.contracts import (
    Collector,
    CollectorBatch,
    CollectorError,
    NormalizationError,
    Normalizer,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    CollectorRun,
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_NONE,
    ERROR_PARSE,
    ERROR_RATE_LIMIT,
    ERROR_UNKNOWN,
    RUN_STATUS_FAILED,
    RUN_STATUS_PARTIAL,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    SourceHealth,
    VALID_ERROR_CLASSIFICATIONS,
    VALID_RUN_STATUSES,
)
from backend.trend_intelligence.acquisition.adapter import (
    CollectorSourceAdapter,
)

__all__ = [
    "Collector",
    "CollectorBatch",
    "CollectorError",
    "NormalizationError",
    "Normalizer",
    "RawCollectedItem",
    "CollectorRun",
    "SourceHealth",
    "CollectorSourceAdapter",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SUCCESS",
    "RUN_STATUS_PARTIAL",
    "RUN_STATUS_FAILED",
    "VALID_RUN_STATUSES",
    "ERROR_NONE",
    "ERROR_NETWORK",
    "ERROR_AUTH",
    "ERROR_RATE_LIMIT",
    "ERROR_PARSE",
    "ERROR_UNKNOWN",
    "VALID_ERROR_CLASSIFICATIONS",
]
