"""
Deterministic per-source acquisition scheduling policy.

Built entirely on top of the existing Source Health + Freshness engine
(acquisition.health) and the existing SourceAcquisitionOrchestrator
registry: this module computes no health or freshness state of its
own, it only applies an explicit, configurable scheduling policy
(normal cadence interval + failed-source retry backoff) on top of the
facts ``build_source_freshness_report`` already produces
(``last_success_at``, ``last_failure_at``, ``consecutive_failures``,
``health_state``).

This is a deterministic planning layer, not a daemon: ``now`` is
always caller-supplied, there is no background process, no sleep or
timer, no network/collector call and no UI. It never starts/completes
a collector run and never writes to persistence. Callers decide what,
if anything, to do with the plan.

Domain-neutral and provider-neutral: no vertical-specific assumptions
about which sources exist.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.trend_intelligence.acquisition.health import (
    HEALTH_FAILED,
    HEALTH_NEVER_RUN,
    build_source_freshness_report,
)
from backend.trend_intelligence.models import canonical_time


SCHEDULE_DUE = "DUE"
SCHEDULE_NOT_DUE = "NOT_DUE"
SCHEDULE_BLOCKED = "BLOCKED"

VALID_SCHEDULE_STATES = frozenset(
    {
        SCHEDULE_DUE,
        SCHEDULE_NOT_DUE,
        SCHEDULE_BLOCKED,
    }
)

REASON_NEVER_RUN = "NEVER_RUN"
REASON_INTERVAL_ELAPSED = "INTERVAL_ELAPSED"
REASON_INTERVAL_NOT_ELAPSED = "INTERVAL_NOT_ELAPSED"
REASON_FAILURE_BACKOFF_ELAPSED = "FAILURE_BACKOFF_ELAPSED"
REASON_FAILURE_BACKOFF_PENDING = "FAILURE_BACKOFF_PENDING"
REASON_RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
REASON_INVALID_POLICY = "INVALID_POLICY"
REASON_SCHEDULING_LOOKUP_ERROR = "SCHEDULING_LOOKUP_ERROR"

DEFAULT_NORMAL_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_FAILURE_BACKOFF_SECONDS = 5 * 60
DEFAULT_FAILURE_BACKOFF_MULTIPLIER = 2.0
DEFAULT_MAX_FAILURE_BACKOFF_SECONDS = 6 * 60 * 60
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True, slots=True)
class SchedulePolicy:
    """Explicit, per-source-assignable scheduling policy.

    ``failure_backoff_seconds`` is the backoff applied after the first
    consecutive failure; it grows by ``failure_backoff_multiplier`` for
    each additional consecutive failure, capped at
    ``max_failure_backoff_seconds``, until ``max_consecutive_failures``
    is reached, at which point the source is retry-exhausted.
    """

    normal_interval_seconds: float = DEFAULT_NORMAL_INTERVAL_SECONDS
    failure_backoff_seconds: float = DEFAULT_FAILURE_BACKOFF_SECONDS
    failure_backoff_multiplier: float = DEFAULT_FAILURE_BACKOFF_MULTIPLIER
    max_failure_backoff_seconds: float = DEFAULT_MAX_FAILURE_BACKOFF_SECONDS
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES

    def validate(self):
        if not (float(self.normal_interval_seconds) > 0):
            raise ValueError("normal_interval_seconds debe ser > 0")
        if not (float(self.failure_backoff_seconds) > 0):
            raise ValueError("failure_backoff_seconds debe ser > 0")
        if not (float(self.failure_backoff_multiplier) >= 1):
            raise ValueError("failure_backoff_multiplier debe ser >= 1")
        if float(self.max_failure_backoff_seconds) < float(self.failure_backoff_seconds):
            raise ValueError(
                "max_failure_backoff_seconds debe ser >= failure_backoff_seconds"
            )
        if int(self.max_consecutive_failures) < 1:
            raise ValueError("max_consecutive_failures debe ser >= 1")


DEFAULT_SCHEDULE_POLICY = SchedulePolicy()


@dataclass(frozen=True, slots=True)
class SourceSchedule:
    source_code: str
    domain_code: str | None

    schedule_state: str
    is_due: bool
    reason: str

    health_state: str | None
    consecutive_failures: int

    last_success_at: str | None
    last_failure_at: str | None

    next_eligible_at: str | None

    freshness: object | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionSchedulePlan:
    entries: tuple[SourceSchedule, ...]

    @property
    def due(self):
        return tuple(entry for entry in self.entries if entry.is_due)

    @property
    def not_due(self):
        return tuple(
            entry for entry in self.entries if entry.schedule_state == SCHEDULE_NOT_DUE
        )

    @property
    def blocked(self):
        return tuple(
            entry for entry in self.entries if entry.schedule_state == SCHEDULE_BLOCKED
        )


def _coerce_now(now):
    if now is None:
        raise ValueError("now es obligatorio: la planificación debe ser determinista")
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_timestamp(value):
    return datetime.fromisoformat(canonical_time(value))


def _failure_backoff_seconds(policy, consecutive_failures):
    exponent = max(0, consecutive_failures - 1)
    backoff = policy.failure_backoff_seconds * (
        policy.failure_backoff_multiplier**exponent
    )
    return min(backoff, policy.max_failure_backoff_seconds)


def _compute_schedule(report, *, policy, now):
    """Pure decision step: (schedule_state, is_due, reason, next_eligible_at).

    Takes only the facts already computed by the health engine
    (``report``) plus the caller-supplied policy and ``now``; it never
    re-derives health/freshness itself.
    """
    if report.health_state == HEALTH_NEVER_RUN:
        return SCHEDULE_DUE, True, REASON_NEVER_RUN, None

    if report.health_state == HEALTH_FAILED:
        if report.consecutive_failures >= policy.max_consecutive_failures:
            return SCHEDULE_BLOCKED, False, REASON_RETRY_EXHAUSTED, None

        if not report.last_failure_at:
            return SCHEDULE_DUE, True, REASON_FAILURE_BACKOFF_ELAPSED, None

        backoff_seconds = _failure_backoff_seconds(
            policy, report.consecutive_failures
        )
        next_eligible = _parse_timestamp(report.last_failure_at) + timedelta(
            seconds=backoff_seconds
        )

        if now >= next_eligible:
            return SCHEDULE_DUE, True, REASON_FAILURE_BACKOFF_ELAPSED, None
        return (
            SCHEDULE_NOT_DUE,
            False,
            REASON_FAILURE_BACKOFF_PENDING,
            next_eligible,
        )

    # Last run succeeded (health engine's FRESH/STALE labels are not
    # reused here: scheduling cadence is governed by this policy's own
    # normal_interval_seconds, not by the health engine's
    # stale_after_seconds threshold).
    if not report.last_success_at:
        return SCHEDULE_DUE, True, REASON_INTERVAL_ELAPSED, None

    next_eligible = _parse_timestamp(report.last_success_at) + timedelta(
        seconds=float(policy.normal_interval_seconds)
    )

    if now >= next_eligible:
        return SCHEDULE_DUE, True, REASON_INTERVAL_ELAPSED, None
    return SCHEDULE_NOT_DUE, False, REASON_INTERVAL_NOT_ELAPSED, next_eligible


def build_acquisition_schedule_plan(
    orchestrator,
    trend_service,
    *,
    now,
    policy=DEFAULT_SCHEDULE_POLICY,
    policy_overrides=None,
    domain_code=None,
    source_code=None,
):
    """Deterministic, read-only acquisition scheduling plan.

    Iterates ``orchestrator.registered_sources()`` (already returned in
    stable source_code order) and, for every registered source, reuses
    ``build_source_freshness_report`` for the underlying health facts,
    then applies an explicit per-source ``SchedulePolicy`` (``policy``,
    optionally overridden per source_code via ``policy_overrides``) to
    decide due/not-due/blocked with an explicit reason and, where
    calculable, a deterministic next eligible time.

    ``now`` is a required, caller-supplied timestamp: there is no
    fallback to the wall clock, keeping this planning step fully
    deterministic.

    One source's policy being invalid, or its health lookup failing,
    is isolated to that source (fails closed: BLOCKED / not due) and
    never prevents sibling sources from being scheduled.
    """
    now = _coerce_now(now)
    policy_overrides = policy_overrides or {}
    overrides_by_code = {
        str(code or "").strip().upper(): source_policy
        for code, source_policy in policy_overrides.items()
    }

    domain_filter = str(domain_code or "").strip().upper() or None
    source_filter = str(source_code or "").strip().upper() or None

    entries = []

    for registered in orchestrator.registered_sources():
        code = str(registered.source_code or "").strip().upper()
        registered_domain = str(registered.domain_code or "").strip().upper() or None

        if source_filter and code != source_filter:
            continue

        if domain_filter and registered_domain != domain_filter:
            continue

        source_policy = overrides_by_code.get(code, policy)

        try:
            source_policy.validate()
        except ValueError as exc:
            entries.append(
                SourceSchedule(
                    source_code=code,
                    domain_code=registered_domain,
                    schedule_state=SCHEDULE_BLOCKED,
                    is_due=False,
                    reason=REASON_INVALID_POLICY,
                    health_state=None,
                    consecutive_failures=0,
                    last_success_at=None,
                    last_failure_at=None,
                    next_eligible_at=None,
                    error_message=str(exc)[:500],
                )
            )
            continue

        try:
            report = build_source_freshness_report(
                trend_service,
                code,
                domain_code=registered.domain_code,
                now=now,
                stale_after_seconds=source_policy.normal_interval_seconds,
            )
        except Exception as exc:
            # Isolation boundary: a lookup failure for one source must
            # never prevent sibling sources from being scheduled.
            entries.append(
                SourceSchedule(
                    source_code=code,
                    domain_code=registered_domain,
                    schedule_state=SCHEDULE_BLOCKED,
                    is_due=False,
                    reason=REASON_SCHEDULING_LOOKUP_ERROR,
                    health_state=None,
                    consecutive_failures=0,
                    last_success_at=None,
                    last_failure_at=None,
                    next_eligible_at=None,
                    error_message=str(exc)[:500],
                )
            )
            continue

        schedule_state, is_due, reason, next_eligible = _compute_schedule(
            report, policy=source_policy, now=now
        )

        entries.append(
            SourceSchedule(
                source_code=code,
                domain_code=registered_domain,
                schedule_state=schedule_state,
                is_due=is_due,
                reason=reason,
                health_state=report.health_state,
                consecutive_failures=report.consecutive_failures,
                last_success_at=report.last_success_at,
                last_failure_at=report.last_failure_at,
                next_eligible_at=(
                    canonical_time(next_eligible) if next_eligible is not None else None
                ),
                freshness=report,
            )
        )

    return AcquisitionSchedulePlan(entries=tuple(entries))
