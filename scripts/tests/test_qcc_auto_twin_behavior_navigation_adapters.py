from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
)

from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)

from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
)

from backend.qcc.auto_twin import (
    AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT,
    AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    behavior_trace_from_observed_human_transition,
    behavior_trace_from_twin_state_transition,
    compare_auto_twin_behavior,
)


FP_REAL_A = "a" * 64
FP_REAL_B = "b" * 64

FP_TWIN_A = "c" * 64
FP_TWIN_B = "d" * 64


def _human_transition(
    *,
    policy="HUMAN_ONLY",
):
    observed_at = datetime.now(
        timezone.utc
    )

    action = QccObservedHumanAction(
        event_id="event-1",
        session_id="session-1",
        site_code="MERCURIO",
        environment="REAL",
        before_state="STATE_A",
        before_fingerprint=(
            FP_REAL_A
        ),
        kind="LINK",
        policy=policy,
        selector="#btncont",
        frame_path="main",
        observed_at=observed_at,
    )

    return (
        QccObservedHumanTransition
        .from_action(
            action,
            after_state="STATE_B",
            after_fingerprint=(
                FP_REAL_B
            ),
            after_observed_at=(
                observed_at
                + timedelta(
                    seconds=1
                )
            ),
        )
    )


def _twin_transition(
    *,
    policy="AUTOMATION_ALLOWED",
    selector="#btncont",
    kind="LINK",
):
    return {
        "schema_version":
            STATE_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            STATE_TRANSITION_TYPE,

        "status":
            STATE_TRANSITION_CHANGED,

        "changed":
            True,

        "before_fingerprint":
            FP_TWIN_A,

        "after_fingerprint":
            FP_TWIN_B,

        "action": {
            "kind":
                kind,

            "policy":
                policy,

            "selector":
                selector,

            "frame_path":
                "main",
        },

        "confidence":
            STATE_TRANSITION_CONFIDENCE_HIGH,

        "contract_changed":
            True,

        "inconclusive":
            False,
    }


def _real():
    return (
        behavior_trace_from_observed_human_transition(
            _human_transition(),
            twin_key="mercurio",
            candidate_id="candidate-1",
        )
    )


def _twin():
    return (
        behavior_trace_from_twin_state_transition(
            _twin_transition(),
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=True,
        )
    )


def test_real_adapter_builds_real_observed_trace():
    trace = _real()

    assert (
        trace[
            "source"
        ]
        == AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
    )

    assert (
        trace[
            "restoration_status"
        ]
        == AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE
    )

    assert (
        trace[
            "transition"
        ][
            "before_state"
        ]
        == "STATE_A"
    )

    assert (
        trace[
            "transition"
        ][
            "after_state"
        ]
        == "STATE_B"
    )


def test_real_adapter_preserves_only_safe_action_identity():
    trace = _real()

    assert trace[
        "action"
    ] == {
        "kind":
            "LINK",

        "selector":
            "#btncont",

        "frame_path":
            "main",

        "action_code":
            None,
    }


def test_real_adapter_keeps_fingerprints_as_references_only():
    trace = _real()

    assert (
        trace[
            "references"
        ][
            "before_fingerprint"
        ]
        == FP_REAL_A
    )

    assert (
        trace[
            "references"
        ][
            "after_fingerprint"
        ]
        == FP_REAL_B
    )

    assert (
        "before_fingerprint"
        not in trace[
            "transition"
        ]
    )


def test_twin_adapter_builds_controlled_trace():
    trace = _twin()

    assert (
        trace[
            "source"
        ]
        == AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
    )

    assert (
        trace[
            "restoration_status"
        ]
        == AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
    )


def test_twin_adapter_requires_external_exact_restore_proof():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_TWIN_RESTORATION_REQUIRED"
        ),
    ):
        behavior_trace_from_twin_state_transition(
            _twin_transition(),
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=False,
        )


def test_twin_adapter_does_not_invent_state_names():
    trace = (
        behavior_trace_from_twin_state_transition(
            _twin_transition(),
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state=None,
            after_state=None,
            restoration_exact=True,
        )
    )

    assert (
        trace[
            "transition"
        ][
            "before_state"
        ]
        is None
    )

    assert (
        trace[
            "transition"
        ][
            "after_state"
        ]
        is None
    )


def test_navigation_pair_is_functionally_equivalent():
    real = _real()
    twin = _twin()

    assert (
        real[
            "policy"
        ]
        == "HUMAN_ONLY"
    )

    assert (
        twin[
            "policy"
        ]
        == "AUTOMATION_ALLOWED"
    )

    assert (
        real[
            "functional_signature"
        ]
        == twin[
            "functional_signature"
        ]
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        result[
            "behavior_fidelity_pass"
        ]
        is True
    )


def test_physical_fingerprint_difference_does_not_break_navigation_fidelity():
    real = _real()
    twin = _twin()

    assert (
        real[
            "references"
        ][
            "before_fingerprint"
        ]
        != twin[
            "references"
        ][
            "before_fingerprint"
        ]
    )

    assert (
        real[
            "functional_signature"
        ]
        == twin[
            "functional_signature"
        ]
    )


def test_selector_difference_produces_real_behavior_failure():
    twin = (
        behavior_trace_from_twin_state_transition(
            _twin_transition(
                selector="#other"
            ),
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=True,
        )
    )

    result = compare_auto_twin_behavior(
        real_trace=_real(),
        twin_trace=twin,
    )

    assert (
        result[
            "behavior_fidelity_pass"
        ]
        is False
    )


def test_wrong_real_source_type_is_rejected():
    with pytest.raises(
        TypeError,
        match=(
            "QCC_AUTO_TWIN_REAL_HUMAN_TRANSITION_INVALID"
        ),
    ):
        behavior_trace_from_observed_human_transition(
            {},
            twin_key="mercurio",
            candidate_id="candidate-1",
        )


def test_twin_transition_schema_is_validated():
    transition = _twin_transition()

    transition[
        "schema_version"
    ] = 999

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_INVALID"
        ),
    ):
        behavior_trace_from_twin_state_transition(
            transition,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=True,
        )


def test_twin_transition_type_is_validated():
    transition = _twin_transition()

    transition[
        "transition_type"
    ] = "OTHER"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_TRANSITION_TYPE_INVALID"
        ),
    ):
        behavior_trace_from_twin_state_transition(
            transition,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=True,
        )


def test_twin_transition_status_is_validated():
    transition = _twin_transition()

    transition[
        "status"
    ] = "FUNCTIONAL_STATE_UNCHANGED"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_STATUS_INVALID"
        ),
    ):
        behavior_trace_from_twin_state_transition(
            transition,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=True,
        )


def test_twin_transition_requires_action_evidence():
    transition = _twin_transition()

    transition[
        "action"
    ] = None

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_TWIN_ACTION_REQUIRED"
        ),
    ):
        behavior_trace_from_twin_state_transition(
            transition,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=True,
        )


def test_twin_diagnostic_fields_are_references_not_functional_identity():
    first = _twin()

    changed = _twin_transition()

    changed[
        "confidence"
    ] = "MEDIUM"

    changed[
        "contract_changed"
    ] = False

    changed[
        "inconclusive"
    ] = True

    second = (
        behavior_trace_from_twin_state_transition(
            changed,
            twin_key="mercurio",
            candidate_id="candidate-1",
            before_state="STATE_A",
            after_state="STATE_B",
            restoration_exact=True,
        )
    )

    assert (
        first[
            "functional_signature"
        ]
        == second[
            "functional_signature"
        ]
    )
