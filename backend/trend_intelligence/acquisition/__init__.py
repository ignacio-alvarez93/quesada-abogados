"""
Trend Intelligence · Source Acquisition V2.

Provider-neutral layer that gets raw source data into the existing
V1 canonical ingestion pipeline (TrendObservationInput -> record_observation).

This package does not change V1 scoring, ingestion or repository
contracts. It only adds acquisition-side contracts (collector, run
lifecycle, normalization, provenance, source health) that produce
TrendObservationInput instances consumed unchanged by
backend.trend_intelligence.ingestion.TrendIngestionService, plus a
SourceAcquisitionOrchestrator that sequences any number of registered
sources through those same contracts with per-source failure isolation.
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
from backend.trend_intelligence.acquisition.orchestrator import (
    AcquisitionRunReport,
    RegisteredSource,
    SourceAcquisitionOrchestrator,
    SourceAcquisitionOutcome,
)
from backend.trend_intelligence.acquisition.health import (
    DEFAULT_STALE_AFTER_SECONDS,
    HEALTH_FAILED,
    HEALTH_FRESH,
    HEALTH_NEVER_RUN,
    HEALTH_STALE,
    SourceFreshnessReport,
    VALID_SOURCE_HEALTH_STATES,
    build_source_freshness_report,
    list_source_freshness_reports,
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
    "RegisteredSource",
    "SourceAcquisitionOrchestrator",
    "SourceAcquisitionOutcome",
    "AcquisitionRunReport",
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
    "SourceFreshnessReport",
    "build_source_freshness_report",
    "list_source_freshness_reports",
    "HEALTH_NEVER_RUN",
    "HEALTH_FRESH",
    "HEALTH_STALE",
    "HEALTH_FAILED",
    "VALID_SOURCE_HEALTH_STATES",
    "DEFAULT_STALE_AFTER_SECONDS",
]
