from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,
    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED,
    AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,
    AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,
    classify_twin_navigation_transition_outcomes,
)
from backend.qcc.auto_twin.navigation_transition_runtime import (
    build_navigation_runtime_payload,
    inject_navigation_runtime_adapter,
    outgoing_navigation_transitions,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64

SELECTOR = "#continuar"


def _context(value):
    return [
        {
            "key":
                "EX_MODEL",

            "selector":
                'input[name="ex_model"]',

            "kind":
                "RADIO",

            "selected_values":
                [value],
        }
    ]


def _transition(
    candidate_id,
    after_fingerprint,
    value=None,
):
    result = {
        "schema_version":
            AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,

        "candidate_id":
            candidate_id,

        "eligibility":
            AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,

        "evidence_source":
            AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

        "real_observation_count":
            1,

        "candidate_status":
            "CANDIDATE",

        "before_fingerprint":
            FP_A,

        "after_fingerprint":
            after_fingerprint,

        "action": {
            "kind":
                "BUTTON",

            "policy":
                "HUMAN_ONLY",

            "selector":
                SELECTOR,

            "frame_path":
                "main",
        },
    }

    if value is not None:
        result[
            "navigation_context"
        ] = _context(
            value
        )

    return result


def _states():
    return [
        {
            "state_id":
                "SELECT_EX",

            "fingerprint":
                FP_A,

            "runtime_entry":
                "states/01/runtime/index.html",
        },
        {
            "state_id":
                "EX01",

            "fingerprint":
                FP_B,

            "runtime_entry":
                "states/02/runtime/index.html",
        },
        {
            "state_id":
                "EX02",

            "fingerprint":
                FP_C,

            "runtime_entry":
                "states/03/runtime/index.html",
        },
    ]


def test_contextual_branch_is_resolved_by_selection():
    transitions = [
        _transition(
            "candidate-ex01",
            FP_B,
            "EX01",
        ),
        _transition(
            "candidate-ex02",
            FP_C,
            "EX02",
        ),
    ]

    groups = (
        classify_twin_navigation_transition_outcomes(
            transitions
        )
    )

    assert len(groups) == 1

    group = groups[0]

    assert (
        group[
            "outcome_mode"
        ]
        == AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED
    )

    assert (
        group[
            "discriminator_keys"
        ]
        == ["EX_MODEL"]
    )

    assert len(
        group[
            "branches"
        ]
    ) == 2


def test_contextual_resolved_routes_are_all_materialized():
    payload = (
        build_navigation_runtime_payload(
            [
                _transition(
                    "candidate-ex01",
                    FP_B,
                    "EX01",
                ),
                _transition(
                    "candidate-ex02",
                    FP_C,
                    "EX02",
                ),
            ],
            _states(),
        )
    )

    assert payload[
        "contextual_resolved_count"
    ] == 2

    assert payload[
        "contextual_unresolved_count"
    ] == 0

    assert payload[
        "contextual_default_count"
    ] == 0

    outgoing = (
        outgoing_navigation_transitions(
            payload,
            "SELECT_EX",
        )
    )

    assert len(
        outgoing
    ) == 2

    assert {
        item[
            "after_state_id"
        ]
        for item in outgoing
    } == {
        "EX01",
        "EX02",
    }


def test_contextual_opaque_branch_fails_closed():
    payload = (
        build_navigation_runtime_payload(
            [
                _transition(
                    "candidate-b",
                    FP_B,
                ),
                _transition(
                    "candidate-c",
                    FP_C,
                ),
            ],
            _states(),
        )
    )

    assert payload[
        "contextual_unresolved_count"
    ] == 1

    assert payload[
        "interactive_transition_count"
    ] == 0

    assert payload[
        "contextual_default_count"
    ] == 0

    assert (
        outgoing_navigation_transitions(
            payload,
            "SELECT_EX",
        )
        == ()
    )


def test_runtime_adapter_resolves_branch_from_live_dom():
    payload = (
        build_navigation_runtime_payload(
            [
                _transition(
                    "candidate-ex01",
                    FP_B,
                    "EX01",
                ),
                _transition(
                    "candidate-ex02",
                    FP_C,
                    "EX02",
                ),
            ],
            _states(),
        )
    )

    outgoing = (
        outgoing_navigation_transitions(
            payload,
            "SELECT_EX",
        )
    )

    html = """<!doctype html>
<html>
<head></head>
<body>
<input type="radio" name="ex_model" value="EX01" checked>
<input type="radio" name="ex_model" value="EX02">
<button id="continuar">Continuar</button>
</body>
</html>
"""

    result = (
        inject_navigation_runtime_adapter(
            html,
            state_id="SELECT_EX",
            transitions=outgoing,
        )
    )

    assert (
        'data-qcc-auto-twin-navigation="1"'
        in result
    )

    assert (
        "contextMatches"
        in result
    )

    assert (
        "document.querySelectorAll(selector)"
        in result
    )

    assert (
        "states/02/runtime/index.html"
        in result
    )

    assert (
        "states/03/runtime/index.html"
        in result
    )
