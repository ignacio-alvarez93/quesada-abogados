import pytest

from backend.automation.site_architecture.safe_recovery import (
    RECOVERY_LEVEL_BOUNDED_SAFE_RETRY,
    RECOVERY_LEVEL_RECOGNIZE,
    RECOVERY_LEVEL_RE_RESOLVE,
    RecoveryBudget,
    budget_allows,
    build_recovery_attempt,
)


def test_default_budget_is_finite_and_positive():
    budget = RecoveryBudget()

    assert budget.total_bound() > 0
    assert budget.max_recognize_attempts >= 0
    assert budget.max_reresolve_attempts >= 0
    assert budget.max_bounded_safe_retries >= 0


def test_negative_budget_is_rejected():
    with pytest.raises(ValueError):
        RecoveryBudget(max_recognize_attempts=-1)


def test_budget_allows_respects_independent_counters():
    budget = RecoveryBudget(
        max_recognize_attempts=1,
        max_reresolve_attempts=0,
        max_bounded_safe_retries=2,
    )

    counters = {"recognize": 0, "reresolve": 0, "bounded_retry": 0}

    assert budget_allows(
        counters, budget, RECOVERY_LEVEL_RECOGNIZE
    )
    assert not budget_allows(
        counters, budget, RECOVERY_LEVEL_RE_RESOLVE
    )
    assert budget_allows(
        counters, budget, RECOVERY_LEVEL_BOUNDED_SAFE_RETRY
    )

    counters["recognize"] = 1
    counters["bounded_retry"] = 2

    assert not budget_allows(
        counters, budget, RECOVERY_LEVEL_RECOGNIZE
    )
    assert not budget_allows(
        counters, budget, RECOVERY_LEVEL_BOUNDED_SAFE_RETRY
    )


def test_recovery_attempt_requires_a_reason():
    with pytest.raises(ValueError):
        build_recovery_attempt(
            RECOVERY_LEVEL_RECOGNIZE, "", retried=True
        )


def test_recovery_attempt_to_public_dict():
    attempt = build_recovery_attempt(
        RECOVERY_LEVEL_RECOGNIZE, "SNAPSHOT_UNAVAILABLE", retried=True
    )

    assert attempt.to_public_dict() == {
        "schema_version": 1,
        "level": RECOVERY_LEVEL_RECOGNIZE,
        "reason": "SNAPSHOT_UNAVAILABLE",
        "retried": True,
    }
