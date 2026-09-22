import pytest

from backend.automation.site_architecture.automation_readiness import (
    AutomationReadinessInputs,
    DimensionCounts,
    assess_automation_readiness,
    is_interaction_policy_known,
)


def test_human_only_is_a_known_policy():
    assert is_interaction_policy_known("HUMAN_ONLY") is True
    assert is_interaction_policy_known("AUTOMATION_ALLOWED") is True
    assert is_interaction_policy_known("DENY") is True
    assert is_interaction_policy_known("") is False
    assert is_interaction_policy_known(None) is False
    assert is_interaction_policy_known("SOMETHING_ELSE") is False


def test_full_coverage_yields_perfect_score_and_no_blockers():
    inputs = AutomationReadinessInputs(
        state_coverage=DimensionCounts(covered=4, total=4),
        transition_coverage=DimensionCounts(covered=6, total=6),
        selector_confidence=DimensionCounts(covered=6, total=6),
        policy_coverage=DimensionCounts(covered=6, total=6),
        evidence_coverage=DimensionCounts(covered=6, total=6),
        contract_watcher_stability=DimensionCounts(covered=1, total=1),
        twin_fidelity=DimensionCounts(covered=6, total=6),
        recovery_coverage=DimensionCounts(covered=2, total=2),
        runtime_health_available=True,
    )

    report = assess_automation_readiness(inputs)

    assert report.score == 1.0
    assert report.blockers == ()
    assert report.unknowns == ()


def test_human_only_known_actions_do_not_reduce_policy_coverage():
    # All 6 actions have a KNOWN policy: 4 AUTOMATION_ALLOWED, 2
    # HUMAN_ONLY. Both count as covered.
    inputs = AutomationReadinessInputs(
        policy_coverage=DimensionCounts(covered=6, total=6),
    )

    report = assess_automation_readiness(inputs)

    assert report.dimension_scores["policy_coverage"] == 1.0
    assert "UNKNOWN_INTERACTION_POLICY_PRESENT" not in report.blockers


def test_unknown_policy_reduces_readiness_and_is_a_blocker():
    inputs = AutomationReadinessInputs(
        policy_coverage=DimensionCounts(covered=4, total=6),
    )

    report = assess_automation_readiness(inputs)

    assert report.dimension_scores["policy_coverage"] < 1.0
    assert "UNKNOWN_INTERACTION_POLICY_PRESENT" in report.blockers


def test_missing_dimension_is_unknown_not_zero_or_perfect():
    inputs = AutomationReadinessInputs(
        state_coverage=DimensionCounts(covered=2, total=2),
    )

    report = assess_automation_readiness(inputs)

    assert report.dimension_scores["contract_watcher_stability"] is None
    assert "CONTRACT_WATCHER_STABILITY_UNAVAILABLE" in report.unknowns
    # A perfect single dimension still yields a perfect overall score:
    # unavailable dimensions are excluded, not penalized as zero.
    assert report.score == 1.0


def test_dimension_with_zero_total_is_reported_as_no_data():
    inputs = AutomationReadinessInputs(
        transition_coverage=DimensionCounts(covered=0, total=0),
    )

    report = assess_automation_readiness(inputs)

    assert report.dimension_scores["transition_coverage"] is None
    assert "TRANSITION_COVERAGE_NO_DATA" in report.unknowns


def test_runtime_health_unavailable_is_reported_but_not_scored():
    inputs = AutomationReadinessInputs(
        runtime_health_available=False,
    )

    report = assess_automation_readiness(inputs)

    assert "RUNTIME_HEALTH_UNAVAILABLE" in report.unknowns
    assert "runtime_health_available" not in report.dimension_scores


def test_no_data_anywhere_yields_none_score():
    inputs = AutomationReadinessInputs()

    report = assess_automation_readiness(inputs)

    assert report.score is None
    # 8 unavailable dimensions + runtime health unavailable.
    assert len(report.unknowns) == 9
    assert all(value is None for value in report.dimension_scores.values())


def test_readiness_report_has_no_execution_authority():
    report = assess_automation_readiness(
        AutomationReadinessInputs(
            state_coverage=DimensionCounts(covered=1, total=1),
        )
    )

    assert not hasattr(report, "execute")
    assert not hasattr(report, "authorize")
    assert not hasattr(report, "grant")


def test_dimension_counts_rejects_covered_exceeding_total():
    with pytest.raises(ValueError):
        DimensionCounts(covered=3, total=2)


def test_dimension_counts_rejects_negative_values():
    with pytest.raises(ValueError):
        DimensionCounts(covered=-1, total=2)


def test_inputs_reject_wrong_dimension_type():
    with pytest.raises(TypeError):
        AutomationReadinessInputs(state_coverage="not a DimensionCounts")


def test_assess_rejects_invalid_inputs_type():
    with pytest.raises(TypeError):
        assess_automation_readiness({"not": "inputs"})
