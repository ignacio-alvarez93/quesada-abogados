"""Bounded safe recovery primitives (V1).

QCC_SAFE_RECOVERY_V1

Recovery exists to regain trustworthy state, never as an excuse to
blindly repeat a mutating action. This module only defines the levels,
the deterministic/testable budget and the attempt record shape used by
the state-aware execution orchestrator
(``backend.automation.site_architecture.state_aware_execution``).

It never executes anything and never decides by itself whether a
specific outcome is retry-eligible: that decision belongs to
``outcome_classification.classify_post_action_outcome`` (post-action)
and to the orchestrator's own governance-aware routing (pre-action).

Levels:

    0 RECOGNIZE         re-read route/state/fingerprint. No mutation.
    1 RE_RESOLVE         re-resolve the selector against current state.
    2 REVALIDATE          re-run policy/evidence/state/selector gates.
    3 BOUNDED_SAFE_RETRY  retry only a demonstrably safe/idempotent
                          action.
    4 HUMAN_HANDOFF       fail closed with structured evidence.
"""

from __future__ import annotations

from dataclasses import dataclass


SAFE_RECOVERY_SCHEMA_VERSION = 1

RECOVERY_LEVEL_RECOGNIZE = 0
RECOVERY_LEVEL_RE_RESOLVE = 1
RECOVERY_LEVEL_REVALIDATE = 2
RECOVERY_LEVEL_BOUNDED_SAFE_RETRY = 3
RECOVERY_LEVEL_HUMAN_HANDOFF = 4

_VALID_LEVELS = frozenset({
    RECOVERY_LEVEL_RECOGNIZE,
    RECOVERY_LEVEL_RE_RESOLVE,
    RECOVERY_LEVEL_REVALIDATE,
    RECOVERY_LEVEL_BOUNDED_SAFE_RETRY,
    RECOVERY_LEVEL_HUMAN_HANDOFF,
})


def _non_negative_int(value, *, error):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(error)

    if value < 0:
        raise ValueError(error)

    return value


@dataclass(
    frozen=True,
    slots=True,
)
class RecoveryBudget:
    """Explicit, deterministic bound on recovery attempts.

    Each counter bounds one recovery level independently. There is no
    implicit/global retry: exhausting any single counter routes the
    caller into HUMAN_HANDOFF for that level's concern.
    """

    max_recognize_attempts: int = 2
    max_reresolve_attempts: int = 2
    max_bounded_safe_retries: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_recognize_attempts",
            _non_negative_int(
                self.max_recognize_attempts,
                error="QCC_RECOVERY_BUDGET_RECOGNIZE_INVALID",
            ),
        )

        object.__setattr__(
            self,
            "max_reresolve_attempts",
            _non_negative_int(
                self.max_reresolve_attempts,
                error="QCC_RECOVERY_BUDGET_RERESOLVE_INVALID",
            ),
        )

        object.__setattr__(
            self,
            "max_bounded_safe_retries",
            _non_negative_int(
                self.max_bounded_safe_retries,
                error="QCC_RECOVERY_BUDGET_BOUNDED_RETRY_INVALID",
            ),
        )

    def total_bound(self) -> int:
        """Deterministic upper bound on total recovery attempts.

        Used by the orchestrator as a defensive hard cap so a latent
        logic error can never produce an unbounded loop.
        """

        return (
            self.max_recognize_attempts
            + self.max_reresolve_attempts
            + self.max_bounded_safe_retries
        )


@dataclass(
    frozen=True,
    slots=True,
)
class RecoveryAttempt:
    schema_version: int
    level: int
    reason: str
    retried: bool

    def __post_init__(self) -> None:
        if self.level not in _VALID_LEVELS:
            raise ValueError(
                "QCC_RECOVERY_ATTEMPT_LEVEL_INVALID"
            )

        reason = str(self.reason or "").strip()

        if not reason:
            raise ValueError(
                "QCC_RECOVERY_ATTEMPT_REASON_REQUIRED"
            )

        object.__setattr__(self, "reason", reason)

        if not isinstance(self.retried, bool):
            raise TypeError(
                "QCC_RECOVERY_ATTEMPT_RETRIED_INVALID"
            )

    def to_public_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "level": self.level,
            "reason": self.reason,
            "retried": self.retried,
        }


def build_recovery_attempt(
    level: int,
    reason: str,
    *,
    retried: bool,
) -> RecoveryAttempt:
    return RecoveryAttempt(
        schema_version=SAFE_RECOVERY_SCHEMA_VERSION,
        level=level,
        reason=reason,
        retried=retried,
    )


def budget_allows(
    counters: dict,
    budget: RecoveryBudget,
    level: int,
) -> bool:
    """Whether one more attempt is allowed at ``level`` right now."""

    if level == RECOVERY_LEVEL_RECOGNIZE:
        return (
            counters.get("recognize", 0)
            < budget.max_recognize_attempts
        )

    if level == RECOVERY_LEVEL_RE_RESOLVE:
        return (
            counters.get("reresolve", 0)
            < budget.max_reresolve_attempts
        )

    if level == RECOVERY_LEVEL_BOUNDED_SAFE_RETRY:
        return (
            counters.get("bounded_retry", 0)
            < budget.max_bounded_safe_retries
        )

    return False
