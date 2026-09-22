"""
Deterministic collector run lifecycle and source health models.

Domain-neutral, provider-neutral. No secrets are represented here:
credentials/tokens belong to collector configuration, never to run state.
"""

from dataclasses import dataclass
from typing import Any


RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_SUCCESS = "SUCCESS"
RUN_STATUS_PARTIAL = "PARTIAL"
RUN_STATUS_FAILED = "FAILED"

VALID_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_RUNNING,
        RUN_STATUS_SUCCESS,
        RUN_STATUS_PARTIAL,
        RUN_STATUS_FAILED,
    }
)


ERROR_NONE = "NONE"
ERROR_NETWORK = "NETWORK"
ERROR_AUTH = "AUTH"
ERROR_RATE_LIMIT = "RATE_LIMIT"
ERROR_PARSE = "PARSE"
ERROR_UNKNOWN = "UNKNOWN"

VALID_ERROR_CLASSIFICATIONS = frozenset(
    {
        ERROR_NONE,
        ERROR_NETWORK,
        ERROR_AUTH,
        ERROR_RATE_LIMIT,
        ERROR_PARSE,
        ERROR_UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class CollectorRun:
    id: int | None
    source_id: int

    collector_key: str
    collector_version: str
    provider: str | None = None

    started_at: str | None = None
    completed_at: str | None = None

    status: str = RUN_STATUS_RUNNING

    items_seen: int = 0
    items_accepted: int = 0
    items_rejected: int = 0

    error_classification: str = ERROR_NONE
    error_message: str | None = None

    cursor: str | None = None

    metadata: dict[str, Any] | None = None

    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: int

    last_run_status: str | None = None
    last_run_at: str | None = None

    last_success_at: str | None = None
    last_failure_at: str | None = None

    consecutive_failures: int = 0
    last_error_classification: str | None = None
    last_cursor: str | None = None
