"""
Read-only acquisition readiness planning.

Built entirely on top of the existing Source Health + Freshness engine
(acquisition.health) and the existing SourceAcquisitionOrchestrator
registry: this module computes no health state of its own, it only
classifies the health state already produced by
``build_source_freshness_report`` into a deterministic readiness plan.

This is a planning layer only: it never starts/completes a collector
run, never calls a collector/network, never writes to persistence, and
never schedules or runs anything in the background. Callers decide
what, if anything, to do with the plan.

Domain-neutral and provider-neutral: no vertical-specific assumptions
about which sources exist.
"""

from dataclasses import dataclass

from backend.trend_intelligence.acquisition.health import (
    HEALTH_FAILED,
    HEALTH_FRESH,
    HEALTH_NEVER_RUN,
    HEALTH_STALE,
    DEFAULT_STALE_AFTER_SECONDS,
    build_source_freshness_report,
)


READINESS_READY = "READY"
READINESS_NOT_DUE = "NOT_DUE"
READINESS_UNHEALTHY = "UNHEALTHY"

VALID_READINESS_STATES = frozenset(
    {
        READINESS_READY,
        READINESS_NOT_DUE,
        READINESS_UNHEALTHY,
    }
)

REASON_NEVER_RUN = "NEVER_RUN"
REASON_STALE_PAST_THRESHOLD = "STALE_PAST_THRESHOLD"
REASON_FRESH_NOT_DUE = "FRESH_NOT_DUE"
REASON_FAILED_RETRY_ELIGIBLE = "FAILED_RETRY_ELIGIBLE"
REASON_FAILED_RETRY_EXHAUSTED = "FAILED_RETRY_EXHAUSTED"
REASON_READINESS_LOOKUP_ERROR = "READINESS_LOOKUP_ERROR"

DEFAULT_MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True, slots=True)
class SourceReadiness:
    source_code: str
    domain_code: str | None

    readiness_state: str
    health_state: str | None
    is_ready: bool

    retry_eligible: bool | None
    reason: str

    consecutive_failures: int

    freshness: object | None

    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionReadinessPlan:
    entries: tuple[SourceReadiness, ...]

    @property
    def ready(self):
        return tuple(entry for entry in self.entries if entry.is_ready)

    @property
    def stale(self):
        return tuple(
            entry for entry in self.entries if entry.health_state == HEALTH_STALE
        )

    @property
    def unhealthy(self):
        return tuple(
            entry for entry in self.entries if entry.health_state == HEALTH_FAILED
        )


def _classify(report, *, max_consecutive_failures):
    if report.health_state == HEALTH_NEVER_RUN:
        return READINESS_READY, None, REASON_NEVER_RUN

    if report.health_state == HEALTH_FRESH:
        return READINESS_NOT_DUE, None, REASON_FRESH_NOT_DUE

    if report.health_state == HEALTH_STALE:
        return READINESS_READY, None, REASON_STALE_PAST_THRESHOLD

    # HEALTH_FAILED
    eligible = report.consecutive_failures < max_consecutive_failures
    if eligible:
        return READINESS_READY, True, REASON_FAILED_RETRY_ELIGIBLE
    return READINESS_UNHEALTHY, False, REASON_FAILED_RETRY_EXHAUSTED


def build_acquisition_readiness_plan(
    orchestrator,
    trend_service,
    *,
    domain_code=None,
    source_code=None,
    now=None,
    stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
    max_consecutive_failures=DEFAULT_MAX_CONSECUTIVE_FAILURES,
):
    """Deterministic, read-only acquisition readiness plan.

    Iterates ``orchestrator.registered_sources()`` (already returned in
    stable source_code order) and, for every registered source, reuses
    ``build_source_freshness_report`` to classify it as ready to run,
    stale, fresh (not due) or temporarily unhealthy, with an explicit
    retry-eligibility flag and readiness reason. One source's health
    lookup failing is isolated: it never prevents other sources from
    being classified.
    """
    domain_filter = str(domain_code or "").strip().upper() or None
    source_filter = str(source_code or "").strip().upper() or None
    max_consecutive_failures = int(max_consecutive_failures)

    entries = []

    for registered in orchestrator.registered_sources():
        code = str(registered.source_code or "").strip().upper()
        registered_domain = str(registered.domain_code or "").strip().upper() or None

        if source_filter and code != source_filter:
            continue

        if domain_filter and registered_domain != domain_filter:
            continue

        try:
            report = build_source_freshness_report(
                trend_service,
                code,
                domain_code=registered.domain_code,
                now=now,
                stale_after_seconds=stale_after_seconds,
            )
        except Exception as exc:
            # Isolation boundary: a lookup failure for one source must
            # never prevent sibling sources from being classified.
            entries.append(
                SourceReadiness(
                    source_code=code,
                    domain_code=registered_domain,
                    readiness_state=READINESS_UNHEALTHY,
                    health_state=None,
                    is_ready=False,
                    retry_eligible=False,
                    reason=REASON_READINESS_LOOKUP_ERROR,
                    consecutive_failures=0,
                    freshness=None,
                    error_message=str(exc)[:500],
                )
            )
            continue

        readiness_state, retry_eligible, reason = _classify(
            report, max_consecutive_failures=max_consecutive_failures
        )

        entries.append(
            SourceReadiness(
                source_code=code,
                domain_code=registered_domain,
                readiness_state=readiness_state,
                health_state=report.health_state,
                is_ready=readiness_state == READINESS_READY,
                retry_eligible=retry_eligible,
                reason=reason,
                consecutive_failures=report.consecutive_failures,
                freshness=report,
            )
        )

    return AcquisitionReadinessPlan(entries=tuple(entries))
