"""
Read-only source health + freshness reporting.

Built entirely on top of the existing collector run lifecycle
(CollectorRun / SourceHealth, see acquisition.models) and the existing
SourceAcquisitionOrchestrator registry. This module never starts or
completes a run, never writes to ti_sources / ti_collector_runs, and
never introduces a new source/domain persistence link: a source's
domain_code is only known where the orchestrator already models it
(RegisteredSource.domain_code), which is the sole place domain and
source are currently associated.

Domain-neutral and provider-neutral: no vertical-specific assumptions
about which sources exist, no Selenium dependency.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from backend.trend_intelligence.acquisition.models import RUN_STATUS_FAILED
from backend.trend_intelligence.models import canonical_time


HEALTH_NEVER_RUN = "NEVER_RUN"
HEALTH_FRESH = "FRESH"
HEALTH_STALE = "STALE"
HEALTH_FAILED = "FAILED"

VALID_SOURCE_HEALTH_STATES = frozenset(
    {
        HEALTH_NEVER_RUN,
        HEALTH_FRESH,
        HEALTH_STALE,
        HEALTH_FAILED,
    }
)

DEFAULT_STALE_AFTER_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class SourceFreshnessReport:
    source_code: str
    source_id: int | None
    domain_code: str | None

    health_state: str

    latest_run: object | None

    last_run_status: str | None
    last_run_at: str | None

    last_success_at: str | None
    last_failure_at: str | None

    last_error_classification: str | None
    last_failure_reason: str | None

    consecutive_failures: int

    has_cursor: bool
    last_cursor: str | None

    freshness_age_seconds: float | None


def _coerce_now(now):
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _seconds_since(reference, *, now):
    if not reference:
        return None
    reference_dt = datetime.fromisoformat(canonical_time(reference))
    return max(0.0, (now - reference_dt).total_seconds())


def compute_health_state(health, *, freshness_age_seconds, stale_after_seconds):
    if not health.last_run_at:
        return HEALTH_NEVER_RUN

    if health.last_run_status == RUN_STATUS_FAILED:
        return HEALTH_FAILED

    if (
        freshness_age_seconds is not None
        and freshness_age_seconds <= stale_after_seconds
    ):
        return HEALTH_FRESH

    return HEALTH_STALE


def build_source_freshness_report(
    trend_service,
    source_code,
    *,
    domain_code=None,
    now=None,
    stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
):
    """Read-only freshness/health snapshot for a single source.

    domain_code is purely descriptive here (typically the caller's
    orchestrator registration for that source): it is never resolved
    or validated against persistence, since current source models
    carry no domain linkage of their own.
    """
    source_code = str(source_code or "").strip().upper()
    now = _coerce_now(now)
    stale_after_seconds = float(stale_after_seconds)

    health = trend_service.get_source_health(source_code)
    runs = trend_service.list_collector_runs(source_code)

    latest_run = runs[0] if runs else None
    last_failure_reason = next(
        (run.error_message for run in runs if run.status == RUN_STATUS_FAILED),
        None,
    )

    freshness_age_seconds = _seconds_since(health.last_success_at, now=now)

    return SourceFreshnessReport(
        source_code=source_code,
        source_id=health.source_id,
        domain_code=domain_code,
        health_state=compute_health_state(
            health,
            freshness_age_seconds=freshness_age_seconds,
            stale_after_seconds=stale_after_seconds,
        ),
        latest_run=latest_run,
        last_run_status=health.last_run_status,
        last_run_at=health.last_run_at,
        last_success_at=health.last_success_at,
        last_failure_at=health.last_failure_at,
        last_error_classification=health.last_error_classification,
        last_failure_reason=last_failure_reason,
        consecutive_failures=health.consecutive_failures,
        has_cursor=health.last_cursor is not None,
        last_cursor=health.last_cursor,
        freshness_age_seconds=freshness_age_seconds,
    )


def list_source_freshness_reports(
    orchestrator,
    trend_service,
    *,
    domain_code=None,
    source_code=None,
    now=None,
    stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
):
    """Freshness/health snapshots for every source registered on
    orchestrator, optionally filtered by domain_code and/or
    source_code.

    domain_code filtering only matches sources registered with that
    exact domain_code: it is the only place current models associate
    a source with a domain, so a source never registered with a
    domain_code cannot match any domain_code filter.
    """
    domain_filter = str(domain_code or "").strip().upper() or None
    source_filter = str(source_code or "").strip().upper() or None
    now = _coerce_now(now)

    reports = []

    for registered in orchestrator.registered_sources():
        code = str(registered.source_code or "").strip().upper()
        registered_domain = (
            str(registered.domain_code or "").strip().upper() or None
        )

        if source_filter and code != source_filter:
            continue

        if domain_filter and registered_domain != domain_filter:
            continue

        reports.append(
            build_source_freshness_report(
                trend_service,
                code,
                domain_code=registered.domain_code,
                now=now,
                stale_after_seconds=stale_after_seconds,
            )
        )

    return tuple(reports)
