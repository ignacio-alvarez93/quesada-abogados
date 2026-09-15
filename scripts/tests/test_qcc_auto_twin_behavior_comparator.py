from copy import deepcopy

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    build_auto_twin_behavior_trace,
    compare_auto_twin_behavior,
)


def _action():
    return {
        "kind":
            "NAVIGATION",

        "action_code":
            "CONTINUE",
    }


def _transition():
    return {
        "before_state":
            "FORM",

        "after_state":
            "NEXT",

        "changed":
            True,
    }


def _trace(
    source,
    *,
    policy,
    action=None,
    transition=None,
    effects=(),
    causal_relations=(),
    twin_key="mercurio",
    candidate_id="candidate-1",
):
    return build_auto_twin_behavior_trace(
        twin_key=twin_key,
        candidate_id=candidate_id,
        source=source,
        action=(
            action
            if action is not None
            else _action()
        ),
        transition=(
            transition
            if transition is not None
            else _transition()
        ),
        effects=effects,
        causal_relations=causal_relations,
        policy=policy,
    )


def _real(**kwargs):
    return _trace(
        AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
        policy="HUMAN_ONLY",
        **kwargs,
    )


def _twin(**kwargs):
    return _trace(
        AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
        policy="AUTOMATION_ALLOWED",
        **kwargs,
    )


def _status(result):
    return (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
    )


def _metrics(result):
    return (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "metrics"
        ]
    )


def test_equivalent_behavior_passes_despite_policy_difference():
    result = compare_auto_twin_behavior(
        real_trace=_real(),
        twin_trace=_twin(),
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    assert (
        result[
            "behavior_fidelity_pass"
        ]
        is True
    )

    assert (
        _metrics(
            result
        )[
            "policy_equal"
        ]
        is False
    )


def test_different_transition_fails():
    twin = _twin(
        transition={
            "before_state":
                "FORM",

            "after_state":
                "OTHER",

            "changed":
                True,
        }
    )

    result = compare_auto_twin_behavior(
        real_trace=_real(),
        twin_trace=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        _metrics(
            result
        )[
            "transition_equal"
        ]
        is False
    )


def test_different_action_fails():
    twin = _twin(
        action={
            "kind":
                "NAVIGATION",

            "action_code":
                "BACK",
        }
    )

    result = compare_auto_twin_behavior(
        real_trace=_real(),
        twin_trace=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        _metrics(
            result
        )[
            "action_equal"
        ]
        is False
    )


def test_different_effects_fail():
    effect = {
        "kind":
            "CATALOG_OPTIONS_CHANGED",

        "source":
            "province",

        "target":
            "municipality",

        "before_options_count":
            179,

        "after_options_count":
            78,
    }

    real = _real(
        effects=(
            effect,
        )
    )

    changed = {
        **effect,
        "after_options_count":
            79,
    }

    twin = _twin(
        effects=(
            changed,
        )
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        _metrics(
            result
        )[
            "effects_equal"
        ]
        is False
    )


def test_different_causal_relations_fail():
    relation = {
        "relation":
            "INFLUENCES",

        "source":
            "province",

        "target":
            "municipality",

        "evidence_kind":
            "OBSERVED_CATALOG_MUTATION",

        "before_options_count":
            179,

        "after_options_count":
            78,
    }

    real = _real(
        causal_relations=(
            relation,
        )
    )

    twin = _twin(
        causal_relations=(
            {
                **relation,
                "after_options_count":
                    79,
            },
        )
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        _metrics(
            result
        )[
            "causal_relations_equal"
        ]
        is False
    )


def test_missing_real_trace_is_not_available():
    result = compare_auto_twin_behavior(
        real_trace=None,
        twin_trace=_twin(),
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )


def test_missing_twin_trace_is_not_available():
    result = compare_auto_twin_behavior(
        real_trace=_real(),
        twin_trace=None,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )


def test_changed_transition_without_states_is_inconclusive():
    transition = {
        "before_state":
            None,

        "after_state":
            None,

        "changed":
            True,
    }

    result = compare_auto_twin_behavior(
        real_trace=_real(
            transition=transition,
        ),
        twin_trace=_twin(
            transition=transition,
        ),
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )


def test_unchanged_transition_without_states_can_be_complete():
    transition = {
        "before_state":
            None,

        "after_state":
            None,

        "changed":
            False,
    }

    result = compare_auto_twin_behavior(
        real_trace=_real(
            transition=transition,
        ),
        twin_trace=_twin(
            transition=transition,
        ),
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )


def test_wrong_source_pair_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_TRACE_SOURCE_INVALID"
        ),
    ):
        compare_auto_twin_behavior(
            real_trace=_twin(),
            twin_trace=_real(),
        )


def test_candidate_mismatch_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_CANDIDATE_MISMATCH"
        ),
    ):
        compare_auto_twin_behavior(
            real_trace=_real(),
            twin_trace=_twin(
                candidate_id="candidate-2",
            ),
        )


def test_twin_key_mismatch_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_TWIN_KEY_MISMATCH"
        ),
    ):
        compare_auto_twin_behavior(
            real_trace=_real(),
            twin_trace=_twin(
                twin_key="other",
            ),
        )


def test_tampered_functional_signature_is_rejected():
    real = _real()

    real[
        "functional_signature"
    ] = "tampered"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_SIGNATURE_INVALID"
        ),
    ):
        compare_auto_twin_behavior(
            real_trace=real,
            twin_trace=_twin(),
        )


def test_policy_change_alone_never_breaks_fidelity():
    real = _real()
    twin = _twin()

    twin[
        "policy"
    ] = "SOME_OTHER_TWIN_POLICY"

    # Rebuild required because policy does not enter
    # functional_signature but does enter trace provenance.
    twin = build_auto_twin_behavior_trace(
        twin_key=twin[
            "twin_key"
        ],
        candidate_id=twin[
            "candidate_id"
        ],
        source=twin[
            "source"
        ],
        action=twin[
            "action"
        ],
        transition=twin[
            "transition"
        ],
        effects=twin[
            "effects"
        ],
        causal_relations=twin[
            "causal_relations"
        ],
        policy="SOME_OTHER_TWIN_POLICY",
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )


def test_result_is_lightweight():
    result = compare_auto_twin_behavior(
        real_trace=_real(),
        twin_trace=_twin(),
    )

    assert (
        "real_trace"
        not in result
    )

    assert (
        "twin_trace"
        not in result
    )

    assert (
        "raw_capture"
        not in result
    )

    assert (
        "html"
        not in result
    )
