import pytest

from backend.automation.site_architecture.execution_gate import (
    EXECUTION_GATE_BLOCKED_AMBIGUOUS,
    EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT,
    EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
    EXECUTION_GATE_BLOCKED_POLICY,
    EXECUTION_GATE_BLOCKED_STALE_EVIDENCE,
    EXECUTION_GATE_BLOCKED_UNKNOWN_STATE,
    EXECUTION_GATE_EXECUTE_ALLOWED,
    EXECUTION_GATE_WAIT_FOR_HUMAN,
    ExecutionGateContext,
    evaluate_execution_gate,
)


def _context(**overrides):
    base = dict(
        site_gate_authorized=True,
        functional_state="STATE_A",
        interaction_policy="AUTOMATION_ALLOWED",
        action_kind="LINK",
        action_selector="#continuar",
        action_frame_path="main",
        selector_resolution="PRIMARY_OK",
    )
    base.update(overrides)
    return ExecutionGateContext(**base)


def test_execute_allowed_with_fully_confirmed_evidence():
    context = _context(
        expected_graph_classification="MATCH",
        contract_watcher_health="STABLE",
        twin_validation_status="TWIN_VALIDATED",
        transition_confidence="HIGH",
        observation_count=5,
    )

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_EXECUTE_ALLOWED


def test_execute_allowed_when_optional_signals_are_unavailable():
    # No expected-graph/contract-watcher/twin-validation/confidence
    # signals supplied: they must never count against execution.
    context = _context()

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_EXECUTE_ALLOWED


def test_human_only_always_waits_for_human():
    context = _context(interaction_policy="HUMAN_ONLY")

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_WAIT_FOR_HUMAN


def test_human_only_wins_even_with_perfect_evidence():
    context = _context(
        interaction_policy="HUMAN_ONLY",
        expected_graph_classification="MATCH",
        contract_watcher_health="STABLE",
        twin_validation_status="TWIN_VALIDATED",
        transition_confidence="HIGH",
        observation_count=100,
    )

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_WAIT_FOR_HUMAN


def test_unknown_policy_never_defaults_to_automation():
    context = _context(interaction_policy="SOMETHING_UNDEFINED")

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_POLICY


def test_deny_policy_is_blocked():
    context = _context(interaction_policy="DENY")

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_POLICY
    assert decision.reason == "INTERACTION_POLICY_DENY"


def test_site_gate_not_authorized_blocks_before_anything_else():
    context = _context(
        site_gate_authorized=False,
        interaction_policy="HUMAN_ONLY",
    )

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_POLICY
    assert decision.reason == "SITE_GATE_NOT_AUTHORIZED"


def test_unknown_functional_state_blocks():
    context = _context(functional_state=None)

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_UNKNOWN_STATE


def test_stale_evidence_never_passes():
    context = _context(evidence_stale=True)

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_STALE_EVIDENCE


def test_ambiguous_selector_never_passes():
    context = _context(selector_resolution="AMBIGUOUS")

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_AMBIGUOUS


def test_unresolved_selector_is_insufficient_evidence():
    context = _context(selector_resolution="UNRESOLVED")

    decision = evaluate_execution_gate(context)

    assert (
        decision.decision
        == EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE
    )


def test_healed_selector_requires_high_confidence():
    medium = _context(
        selector_resolution="HEALED",
        selector_confidence="MEDIUM",
    )

    assert (
        evaluate_execution_gate(medium).decision
        == EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE
    )

    high = _context(
        selector_resolution="HEALED",
        selector_confidence="HIGH",
    )

    assert (
        evaluate_execution_gate(high).decision
        == EXECUTION_GATE_EXECUTE_ALLOWED
    )


def test_contract_drift_blocks_via_divergent_target():
    context = _context(
        expected_graph_classification="DIVERGENT_TARGET",
    )

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT


def test_contract_watcher_unstable_blocks():
    context = _context(contract_watcher_health="UNSTABLE")

    decision = evaluate_execution_gate(context)

    assert decision.decision == EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT


def test_new_transition_is_insufficient_evidence_not_execute():
    context = _context(
        expected_graph_classification="NEW_TRANSITION",
    )

    decision = evaluate_execution_gate(context)

    assert (
        decision.decision
        == EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE
    )


def test_twin_not_validated_blocks():
    context = _context(twin_validation_status="NOT_VALIDATED")

    decision = evaluate_execution_gate(context)

    assert (
        decision.decision
        == EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE
    )


def test_low_transition_confidence_blocks():
    context = _context(transition_confidence="LOW")

    decision = evaluate_execution_gate(context)

    assert (
        decision.decision
        == EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE
    )


def test_zero_observation_count_blocks():
    context = _context(observation_count=0)

    decision = evaluate_execution_gate(context)

    assert (
        decision.decision
        == EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE
    )


def test_gate_rejects_invalid_context_type():
    with pytest.raises(TypeError):
        evaluate_execution_gate({"not": "a context"})


def test_context_rejects_missing_action_identity():
    with pytest.raises(ValueError):
        ExecutionGateContext(
            site_gate_authorized=True,
            functional_state="STATE_A",
            interaction_policy="AUTOMATION_ALLOWED",
            action_kind="",
            action_selector="",
            action_frame_path="main",
            selector_resolution="PRIMARY_OK",
        )


def test_context_rejects_invalid_selector_resolution():
    with pytest.raises(ValueError):
        _context(selector_resolution="NOT_A_REAL_STATUS")


def test_gate_output_never_carries_execution_authority_itself():
    # The decision object is an inert value: nothing about it can be
    # invoked to actually run the action.
    decision = evaluate_execution_gate(_context())

    assert not hasattr(decision, "execute")
    assert not hasattr(decision, "run")
