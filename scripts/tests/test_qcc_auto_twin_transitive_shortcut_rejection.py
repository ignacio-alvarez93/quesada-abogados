from backend.qcc.auto_twin.navigation_transition_runtime import (
    _contextual_default_transition,
)


def test_contextual_runtime_rejects_transitive_shortcut():
    """
    Learned graph:

        A -> B
        A -> C
        B -> C

    A -> C must not be selected as the interactive successor when
    B is a learned intermediate state leading to C.

    This protects AUTO TWIN against skipping screens in previously
    observed REAL navigation.
    """

    a = (
        "5cea7645e1b5d3ff95a4b18265c7af52"
        "47e2fde2b52bcc1043eb460241a7169e"
    )
    b = (
        "200be7a4e3f397ac0c1bd5b2aede58c"
        "c4ec3449569876339ce06862dd875f19a"
    )
    c = (
        "ef13dbfba40c051c8d941d7cb5c236e3"
        "36dd0e35f5bef6a57b3fafc5a8a8b0b4"
    )

    a_to_b = {
        "candidate_id": "A_TO_B",
        "before_fingerprint": a,
        "after_fingerprint": b,
        "real_observation_count": 1,
    }

    # Deliberately give the wrong shortcut far more observations.
    # Graph causality must still win.
    a_to_c = {
        "candidate_id": "A_TO_C",
        "before_fingerprint": a,
        "after_fingerprint": c,
        "real_observation_count": 99,
    }

    b_to_c = {
        "candidate_id": "B_TO_C",
        "before_fingerprint": b,
        "after_fingerprint": c,
        "real_observation_count": 1,
    }

    group = {
        "action_group_id": "TEST_CONTEXTUAL_ACTION",
        "outcomes": [
            {
                "candidate_ids": [
                    "A_TO_B",
                ],
            },
            {
                "candidate_ids": [
                    "A_TO_C",
                ],
            },
        ],
    }

    selected = _contextual_default_transition(
        group,
        {
            "A_TO_B": a_to_b,
            "A_TO_C": a_to_c,
            "B_TO_C": b_to_c,
        },
        [
            a_to_b,
            a_to_c,
            b_to_c,
        ],
    )

    assert selected["candidate_id"] == "A_TO_B"
    assert selected["after_fingerprint"] == b


def test_contextual_runtime_keeps_stable_fallback_when_graph_cannot_order_outcomes():
    """
    If A -> B and A -> C exist but neither B nor C is known to lead
    to the other, the graph must not invent an ordering.
    """

    a = "a" * 64
    b = "b" * 64
    c = "c" * 64

    a_to_b = {
        "candidate_id": "A_TO_B",
        "before_fingerprint": a,
        "after_fingerprint": b,
        "real_observation_count": 5,
    }

    a_to_c = {
        "candidate_id": "A_TO_C",
        "before_fingerprint": a,
        "after_fingerprint": c,
        "real_observation_count": 1,
    }

    group = {
        "action_group_id": "TEST_UNORDERED_CONTEXTUAL_ACTION",
        "outcomes": [
            {"candidate_ids": ["A_TO_B"]},
            {"candidate_ids": ["A_TO_C"]},
        ],
    }

    selected = _contextual_default_transition(
        group,
        {
            "A_TO_B": a_to_b,
            "A_TO_C": a_to_c,
        },
        [
            a_to_b,
            a_to_c,
        ],
    )

    assert selected["candidate_id"] == "A_TO_B"
