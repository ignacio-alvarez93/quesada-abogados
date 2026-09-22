import pytest

from backend.automation.site_architecture.expected_observed_graph import (
    GRAPH_CLASSIFICATION_DIVERGENT_TARGET,
    GRAPH_CLASSIFICATION_INSUFFICIENT_EVIDENCE,
    GRAPH_CLASSIFICATION_MATCH,
    GRAPH_CLASSIFICATION_MISSING_EXPECTED_STATE,
    GRAPH_CLASSIFICATION_MISSING_EXPECTED_TRANSITION,
    GRAPH_CLASSIFICATION_NEW_STATE,
    GRAPH_CLASSIFICATION_NEW_TRANSITION,
    ExpectedGraph,
    ExpectedGraphState,
    ExpectedGraphTransition,
    compare_expected_to_observed_graph,
)
from backend.automation.site_architecture.navigation_graph import (
    build_navigation_graph,
)
from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
    STATE_TRANSITION_UNCHANGED,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def _action(selector, kind="LINK"):
    return {
        "kind": kind,
        "policy": "NAVIGATION_CANDIDATE",
        "selector": selector,
        "frame_path": "main",
    }


def _changed(before, after, selector, confidence=STATE_TRANSITION_CONFIDENCE_HIGH):
    return {
        "schema_version": STATE_TRANSITION_SCHEMA_VERSION,
        "transition_type": STATE_TRANSITION_TYPE,
        "changed": True,
        "status": STATE_TRANSITION_CHANGED,
        "before_fingerprint": before,
        "after_fingerprint": after,
        "action": _action(selector),
        "confidence": confidence,
        "contract_changed": False,
        "inconclusive": False,
    }


def _unchanged(fingerprint):
    return {
        "schema_version": STATE_TRANSITION_SCHEMA_VERSION,
        "transition_type": STATE_TRANSITION_TYPE,
        "changed": False,
        "status": STATE_TRANSITION_UNCHANGED,
        "before_fingerprint": fingerprint,
        "after_fingerprint": fingerprint,
        "action": None,
        "confidence": STATE_TRANSITION_CONFIDENCE_HIGH,
        "contract_changed": False,
        "inconclusive": False,
    }


def _expected_ab():
    return ExpectedGraph(
        states=(
            ExpectedGraphState(state_id="STATE_A", fingerprint=FP_A),
            ExpectedGraphState(state_id="STATE_B", fingerprint=FP_B),
        ),
        transitions=(
            ExpectedGraphTransition(
                from_state_id="STATE_A",
                to_state_id="STATE_B",
                action_kind="LINK",
                action_selector="#continuar",
            ),
        ),
    )


def _entry_map(entries):
    return {
        (
            (e.expected or {}).get("state_id")
            or (e.expected or {}).get("from_state_id"),
            (e.observed or {}).get("fingerprint")
            or (e.observed or {}).get("source_fingerprint"),
        ): e
        for e in entries
    }


def test_match_when_observed_graph_equals_expected():
    expected = _expected_ab()

    observed = build_navigation_graph([
        _changed(FP_A, FP_B, "#continuar"),
    ])

    report = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    state_classes = {e.classification for e in report["state_entries"]}
    transition_classes = {
        e.classification for e in report["transition_entries"]
    }

    assert state_classes == {GRAPH_CLASSIFICATION_MATCH}
    assert transition_classes == {GRAPH_CLASSIFICATION_MATCH}


def test_missing_expected_state_when_never_observed():
    expected = _expected_ab()

    observed = build_navigation_graph([])

    report = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    classes = [e.classification for e in report["state_entries"]]

    assert classes.count(
        GRAPH_CLASSIFICATION_MISSING_EXPECTED_STATE
    ) == 2


def test_insufficient_evidence_when_source_state_unobserved():
    expected = _expected_ab()

    # STATE_A observed as an isolated appearance elsewhere (never as a
    # transition source): the expected A -> B action itself was never
    # tried, but state A also never appeared, so we still can't tell.
    observed = build_navigation_graph([])

    report = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    transition = report["transition_entries"][0]

    assert (
        transition.classification
        == GRAPH_CLASSIFICATION_INSUFFICIENT_EVIDENCE
    )


def test_missing_expected_transition_when_source_observed_without_action():
    expected = _expected_ab()

    # STATE_A appears (via an unrelated unchanged self-loop) but the
    # expected A -> B action was never observed.
    observed = build_navigation_graph([
        _unchanged(FP_A),
    ])

    report = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    transition = report["transition_entries"][0]

    assert (
        transition.classification
        == GRAPH_CLASSIFICATION_MISSING_EXPECTED_TRANSITION
    )


def test_divergent_target_when_action_leads_elsewhere():
    expected = _expected_ab()

    observed = build_navigation_graph([
        _changed(FP_A, FP_C, "#continuar"),
    ])

    report = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    transition = next(
        e
        for e in report["transition_entries"]
        if e.expected is not None
    )

    assert (
        transition.classification
        == GRAPH_CLASSIFICATION_DIVERGENT_TARGET
    )


def test_new_state_and_new_transition_are_reported():
    expected = ExpectedGraph(
        states=(
            ExpectedGraphState(state_id="STATE_A", fingerprint=FP_A),
        ),
        transitions=(),
    )

    observed = build_navigation_graph([
        _changed(FP_A, FP_C, "#nuevo"),
    ])

    report = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    state_classes = {e.classification for e in report["state_entries"]}
    transition_classes = {
        e.classification for e in report["transition_entries"]
    }

    assert GRAPH_CLASSIFICATION_NEW_STATE in state_classes
    assert GRAPH_CLASSIFICATION_NEW_TRANSITION in transition_classes


def test_human_only_edges_are_valid_graph_knowledge():
    # The comparator carries action kind/selector/frame_path only,
    # never policy: HUMAN_ONLY transitions compare exactly like any
    # other transition.
    expected = ExpectedGraph(
        states=(
            ExpectedGraphState(state_id="STATE_A", fingerprint=FP_A),
            ExpectedGraphState(state_id="STATE_B", fingerprint=FP_B),
        ),
        transitions=(
            ExpectedGraphTransition(
                from_state_id="STATE_A",
                to_state_id="STATE_B",
                action_kind="BUTTON",
                action_selector="#firmar",
            ),
        ),
    )

    observed = build_navigation_graph([
        _changed(FP_A, FP_B, "#firmar", ),
    ])

    # Overwrite the action's kind to BUTTON to match expected.
    observed["edges"][0]["action"]["kind"] = "BUTTON"

    report = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    transition = report["transition_entries"][0]

    assert transition.classification == GRAPH_CLASSIFICATION_MATCH
    assert "policy" not in transition.expected["action"]


def test_contextual_route_identity_is_respected():
    transition_a = ExpectedGraphTransition(
        from_state_id="STATE_A",
        to_state_id="STATE_B",
        action_kind="BUTTON",
        action_selector="#opcion",
        contextual=True,
        context_signature="ctx-1",
    )

    transition_b = ExpectedGraphTransition(
        from_state_id="STATE_A",
        to_state_id="STATE_B",
        action_kind="BUTTON",
        action_selector="#opcion",
        contextual=True,
        context_signature="ctx-2",
    )

    assert transition_a.route_identity() != transition_b.route_identity()


def test_expected_graph_rejects_unknown_state_reference():
    with pytest.raises(ValueError):
        ExpectedGraph(
            states=(
                ExpectedGraphState(
                    state_id="STATE_A", fingerprint=FP_A
                ),
            ),
            transitions=(
                ExpectedGraphTransition(
                    from_state_id="STATE_A",
                    to_state_id="STATE_UNKNOWN",
                    action_kind="LINK",
                    action_selector="#x",
                ),
            ),
        )


def test_comparator_is_deterministic_across_runs():
    expected = _expected_ab()

    observed = build_navigation_graph([
        _changed(FP_A, FP_B, "#continuar"),
        _changed(FP_A, FP_B, "#continuar"),
    ])

    first = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    second = compare_expected_to_observed_graph(
        expected=expected,
        observed_graph=observed,
    )

    assert first == second


def test_comparator_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        compare_expected_to_observed_graph(
            expected={"not": "expected"},
            observed_graph={},
        )

    with pytest.raises(TypeError):
        compare_expected_to_observed_graph(
            expected=_expected_ab(),
            observed_graph=None,
        )
