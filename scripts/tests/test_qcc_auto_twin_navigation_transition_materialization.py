import pytest

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,
    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE,
    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED,
    AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC,
    classify_twin_navigation_transition_outcomes,
    project_twin_eligible_navigation_candidates,
)


FP_A = "a" * 64
FP_B = "b" * 64


def _candidate(
    *,
    observation_count=1,
    status="CANDIDATE",
):
    return {
        "candidate_id":
            "candidate-1",

        "evidence_source":
            AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

        "observation_count":
            observation_count,

        "status":
            status,

        "before_fingerprint":
            FP_A,

        "after_fingerprint":
            FP_B,

        "action": {
            "kind":
                "LINK",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                'a[onclick="continuar(\'INI\');"]',

            "frame_path":
                "main",
        },

        # Must never leak into materialized transition contract.
        "event_ids": [
            "event-1",
            "event-2",
        ],
    }


def test_one_real_causal_observation_is_twin_eligible():
    transitions = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                _candidate(
                    observation_count=1,
                    status="CANDIDATE",
                )
            ]
        })
    )

    assert len(
        transitions
    ) == 1

    transition = transitions[0]

    assert (
        transition[
            "eligibility"
        ]
        == AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE
    )

    assert (
        transition[
            "real_observation_count"
        ]
        == 1
    )

    assert (
        transition[
            "candidate_status"
        ]
        == "CANDIDATE"
    )

    assert (
        transition[
            "before_fingerprint"
        ]
        == FP_A
    )

    assert (
        transition[
            "after_fingerprint"
        ]
        == FP_B
    )

    assert (
        transition[
            "action"
        ][
            "selector"
        ]
        == 'a[onclick="continuar(\'INI\');"]'
    )

    assert "event_ids" not in transition


def test_corroborated_candidate_is_also_twin_eligible():
    transitions = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                _candidate(
                    observation_count=2,
                    status="CORROBORATED",
                )
            ]
        })
    )

    assert len(
        transitions
    ) == 1

    assert (
        transitions[0][
            "real_observation_count"
        ]
        == 2
    )

    assert (
        transitions[0][
            "candidate_status"
        ]
        == "CORROBORATED"
    )


def test_zero_observation_candidate_is_not_twin_eligible():
    transitions = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                _candidate(
                    observation_count=0,
                )
            ]
        })
    )

    assert transitions == ()


def test_untrusted_evidence_source_is_not_materialized():
    candidate = _candidate()
    candidate[
        "evidence_source"
    ] = "SOMETHING_ELSE"

    transitions = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                candidate
            ]
        })
    )

    assert transitions == ()


def test_selector_is_mandatory():
    candidate = _candidate()
    candidate[
        "action"
    ][
        "selector"
    ] = None

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_ACTION_SELECTOR_REQUIRED"
        ),
    ):
        project_twin_eligible_navigation_candidates({
            "candidates": [
                candidate
            ]
        })


def test_fingerprint_is_mandatory_and_strict():
    candidate = _candidate()
    candidate[
        "after_fingerprint"
    ] = "not-a-fingerprint"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_AFTER_FINGERPRINT_INVALID"
        ),
    ):
        project_twin_eligible_navigation_candidates({
            "candidates": [
                candidate
            ]
        })


def test_projection_is_deterministic():
    first = _candidate()
    first[
        "candidate_id"
    ] = "z"

    second = _candidate()
    second[
        "candidate_id"
    ] = "a"

    transitions = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                first,
                second,
            ]
        })
    )

    assert [
        item[
            "candidate_id"
        ]
        for item in transitions
    ] == [
        "a",
        "z",
    ]


def test_normalization_preserves_only_safe_transition_contract():
    from backend.qcc.auto_twin.navigation_transition_materialization import (
        normalize_twin_navigation_transitions,
    )

    projected = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                _candidate(
                    observation_count=2,
                    status="CORROBORATED",
                )
            ]
        })
    )

    normalized = normalize_twin_navigation_transitions(
        projected
    )

    assert len(normalized) == 1
    assert normalized[0]["candidate_id"] == "candidate-1"
    assert normalized[0]["before_fingerprint"] == FP_A
    assert normalized[0]["after_fingerprint"] == FP_B
    assert normalized[0]["real_observation_count"] == 2
    assert "event_ids" not in normalized[0]


def test_normalization_rejects_non_twin_eligible_transition():
    from backend.qcc.auto_twin.navigation_transition_materialization import (
        normalize_twin_navigation_transitions,
    )

    projected = list(
        project_twin_eligible_navigation_candidates({
            "candidates": [
                _candidate()
            ]
        })
    )

    projected[0]["eligibility"] = "REAL_AUTOMATION_ELIGIBLE"

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_NAVIGATION_NOT_TWIN_ELIGIBLE",
    ):
        normalize_twin_navigation_transitions(
            projected
        )


def test_single_outcome_action_group_is_deterministic():
    projected = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                _candidate(
                    observation_count=2,
                    status="CORROBORATED",
                )
            ]
        })
    )

    groups = (
        classify_twin_navigation_transition_outcomes(
            projected
        )
    )

    assert len(groups) == 1

    group = groups[0]

    assert (
        group["outcome_mode"]
        == AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC
    )

    assert group["outcome_count"] == 1
    assert len(group["outcomes"]) == 1

    assert (
        group["outcomes"][0][
            "after_fingerprint"
        ]
        == FP_B
    )

    assert (
        group["outcomes"][0][
            "real_observation_count"
        ]
        == 2
    )

    assert (
        group["outcomes"][0][
            "candidate_ids"
        ]
        == ["candidate-1"]
    )


def test_same_action_same_outcome_remains_deterministic():
    first = _candidate(
        observation_count=2,
        status="CORROBORATED",
    )

    first["candidate_id"] = "candidate-a"

    second = _candidate(
        observation_count=1,
        status="CANDIDATE",
    )

    second["candidate_id"] = "candidate-b"

    projected = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                first,
                second,
            ]
        })
    )

    groups = (
        classify_twin_navigation_transition_outcomes(
            projected
        )
    )

    assert len(groups) == 1

    group = groups[0]

    assert (
        group["outcome_mode"]
        == AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC
    )

    assert group["outcome_count"] == 1

    outcome = group["outcomes"][0]

    assert (
        outcome["candidate_ids"]
        == [
            "candidate-a",
            "candidate-b",
        ]
    )

    assert (
        outcome["real_observation_count"]
        == 3
    )


def test_same_before_different_after_different_context_is_contextual_resolved():
    # Mirrors the real Mercurio EX01_AUTHORIZATION 130/131 scenario
    # (2D-20D/2D-20G): same source action, genuinely different physical
    # targets, discriminated by a RADIO navigation_context selection.
    # This must resolve as CONTEXTUAL_RESOLVED, never DETERMINISTIC,
    # and never silently collapse to one transition.
    first = _candidate(
        observation_count=1,
        status="CANDIDATE",
    )

    first["candidate_id"] = "candidate-130"
    first["after_fingerprint"] = FP_B
    first["navigation_context"] = [
        {
            "key":
                "name:datosForAut:RADIO",

            "selector":
                'input[type="radio"][name="datosForAut"]',

            "frame_path":
                "main",

            "kind":
                "RADIO",

            "selected_values":
                ["130"],
        },
    ]

    second = _candidate(
        observation_count=1,
        status="CANDIDATE",
    )

    second["candidate_id"] = "candidate-131"
    second["after_fingerprint"] = "c" * 64
    second["navigation_context"] = [
        {
            "key":
                "name:datosForAut:RADIO",

            "selector":
                'input[type="radio"][name="datosForAut"]',

            "frame_path":
                "main",

            "kind":
                "RADIO",

            "selected_values":
                ["131"],
        },
    ]

    projected = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                first,
                second,
            ]
        })
    )

    groups = (
        classify_twin_navigation_transition_outcomes(
            projected
        )
    )

    assert len(groups) == 1

    group = groups[0]

    assert (
        group["outcome_mode"]
        == AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED
    )

    assert group["outcome_count"] == 2

    assert {
        item["after_fingerprint"]
        for item in group["outcomes"]
    } == {
        FP_B,
        "c" * 64,
    }

    # No single winner: both physical targets are preserved distinctly.
    assert "after_fingerprint" not in group


def test_multiple_outcomes_are_contextual_opaque():
    first = _candidate(
        observation_count=4,
        status="CORROBORATED",
    )

    first["candidate_id"] = "candidate-b"
    first["after_fingerprint"] = FP_B

    second = _candidate(
        observation_count=1,
        status="CANDIDATE",
    )

    second["candidate_id"] = "candidate-c"
    second["after_fingerprint"] = "c" * 64

    projected = (
        project_twin_eligible_navigation_candidates({
            "candidates": [
                first,
                second,
            ]
        })
    )

    groups = (
        classify_twin_navigation_transition_outcomes(
            projected
        )
    )

    assert len(groups) == 1

    group = groups[0]

    assert (
        group["outcome_mode"]
        == AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE
    )

    assert group["outcome_count"] == 2

    assert {
        item["after_fingerprint"]
        for item in group["outcomes"]
    } == {
        FP_B,
        "c" * 64,
    }

    # No arbitrary winner is selected.
    assert "after_fingerprint" not in group


def test_action_group_identity_is_order_independent():
    first = _candidate()
    first["candidate_id"] = "candidate-b"

    second = _candidate()
    second["candidate_id"] = "candidate-a"

    one = (
        classify_twin_navigation_transition_outcomes(
            project_twin_eligible_navigation_candidates({
                "candidates": [
                    first,
                    second,
                ]
            })
        )
    )

    two = (
        classify_twin_navigation_transition_outcomes(
            project_twin_eligible_navigation_candidates({
                "candidates": [
                    second,
                    first,
                ]
            })
        )
    )

    assert one == two
    assert (
        one[0]["action_group_id"]
        == two[0]["action_group_id"]
    )
