import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT,
    AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    build_auto_twin_behavior_trace,
)


def _action():
    return {
        "kind":
            "SELECT",

        "selector":
            "#province",

        "frame_path":
            "main",
    }


def _transition():
    return {
        "before_state":
            "FORM",

        "after_state":
            "FORM",

        "changed":
            True,
    }


def _effects():
    return (
        {
            "kind":
                "SOURCE_SELECTION_CHANGED",

            "source":
                "province",

            "target":
                "province",

            "before_value":
                "28",

            "after_value":
                "33",
        },
        {
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

            "before_selected_value":
                "",

            "after_selected_value":
                "",
        },
    )


def _relations():
    return (
        {
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
        },
        {
            "relation":
                "DEPENDS_ON",

            "source":
                "municipality",

            "target":
                "province",

            "evidence_kind":
                "OBSERVED_CATALOG_MUTATION",

            "before_options_count":
                179,

            "after_options_count":
                78,
        },
    )


def _build(
    *,
    source,
    policy,
    restoration_status=None,
    references=None,
    effects=None,
    relations=None,
):
    kwargs = {
        "twin_key":
            "mercurio",

        "candidate_id":
            "candidate-1",

        "source":
            source,

        "action":
            _action(),

        "transition":
            _transition(),

        "effects":
            (
                _effects()
                if effects is None
                else effects
            ),

        "causal_relations":
            (
                _relations()
                if relations is None
                else relations
            ),

        "policy":
            policy,

        "references":
            references,
    }

    if restoration_status is not None:
        kwargs[
            "restoration_status"
        ] = restoration_status

    return (
        build_auto_twin_behavior_trace(
            **kwargs
        )
    )


def test_real_observed_trace_defaults_to_not_applicable_restore():
    trace = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
    )

    assert (
        trace[
            "restoration_status"
        ]
        == AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE
    )


def test_twin_controlled_trace_requires_exact_restore():
    trace = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        ),
        policy="AUTOMATION_ALLOWED",
    )

    assert (
        trace[
            "restoration_status"
        ]
        == AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
    )


def test_twin_non_exact_restore_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_TWIN_RESTORATION_REQUIRED"
        ),
    ):
        _build(
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
            ),
            policy="AUTOMATION_ALLOWED",
            restoration_status="FAILED",
        )


def test_real_cannot_claim_controlled_restore():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_REAL_RESTORATION_INVALID"
        ),
    ):
        _build(
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
            ),
            policy="HUMAN_ONLY",
            restoration_status="EXACT",
        )


def test_policy_does_not_change_functional_signature():
    real = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
    )

    twin = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        ),
        policy="AUTOMATION_ALLOWED",
    )

    assert (
        real[
            "functional_signature"
        ]
        == twin[
            "functional_signature"
        ]
    )

    assert (
        real[
            "behavior_trace_id"
        ]
        != twin[
            "behavior_trace_id"
        ]
    )


def test_physical_fingerprints_do_not_change_functional_signature():
    first = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
        references={
            "before_fingerprint":
                "real-before",

            "after_fingerprint":
                "real-after",
        },
    )

    second = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
        references={
            "before_fingerprint":
                "other-before",

            "after_fingerprint":
                "other-after",
        },
    )

    assert (
        first[
            "functional_signature"
        ]
        == second[
            "functional_signature"
        ]
    )


def test_effect_order_does_not_change_signature():
    effects = list(
        _effects()
    )

    first = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
        effects=effects,
    )

    second = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
        effects=list(
            reversed(
                effects
            )
        ),
    )

    assert (
        first[
            "functional_signature"
        ]
        == second[
            "functional_signature"
        ]
    )


def test_relation_order_does_not_change_signature():
    relations = list(
        _relations()
    )

    first = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
        relations=relations,
    )

    second = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
        relations=list(
            reversed(
                relations
            )
        ),
    )

    assert (
        first[
            "functional_signature"
        ]
        == second[
            "functional_signature"
        ]
    )


def test_duplicate_effects_are_deduplicated():
    effect = _effects()[0]

    trace = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
        effects=(
            effect,
            effect,
        ),
        relations=(),
    )

    assert (
        len(
            trace[
                "effects"
            ]
        )
        == 1
    )


def test_functional_difference_changes_signature():
    real = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
    )

    changed_effects = list(
        _effects()
    )

    changed_effects[
        1
    ] = {
        **changed_effects[
            1
        ],
        "after_options_count":
            79,
    }

    twin = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        ),
        policy="AUTOMATION_ALLOWED",
        effects=changed_effects,
    )

    assert (
        real[
            "functional_signature"
        ]
        != twin[
            "functional_signature"
        ]
    )


def test_action_identity_is_required():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_ACTION_IDENTITY_REQUIRED"
        ),
    ):
        build_auto_twin_behavior_trace(
            twin_key="mercurio",
            candidate_id="candidate-1",
            source="REAL_OBSERVED",
            action={
                "kind":
                    "SELECT",
            },
            transition=_transition(),
        )


def test_changed_must_be_boolean():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_CHANGED_INVALID"
        ),
    ):
        build_auto_twin_behavior_trace(
            twin_key="mercurio",
            candidate_id="candidate-1",
            source="REAL_OBSERVED",
            action=_action(),
            transition={
                "before_state":
                    "FORM",

                "after_state":
                    "FORM",

                "changed":
                    "yes",
            },
        )


def test_nested_heavy_references_are_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_REFERENCES_INVALID"
        ),
    ):
        _build(
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
            ),
            policy="HUMAN_ONLY",
            references={
                "raw_capture": {
                    "forbidden":
                        True,
                },
            },
        )


def test_trace_is_lightweight():
    trace = _build(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        policy="HUMAN_ONLY",
    )

    assert (
        "before_capture"
        not in trace
    )

    assert (
        "after_capture"
        not in trace
    )

    assert (
        "html"
        not in trace
    )

    assert (
        "screenshot"
        not in trace
    )


def test_action_code_can_replace_selector():
    trace = build_auto_twin_behavior_trace(
        twin_key="mercurio",
        candidate_id="candidate-1",
        source="REAL_OBSERVED",
        action={
            "kind":
                "NAVIGATION",

            "action_code":
                "CONTINUE",
        },
        transition={
            "before_state":
                "FORM",

            "after_state":
                "NEXT",

            "changed":
                True,
        },
        policy="HUMAN_ONLY",
    )

    assert (
        trace[
            "action"
        ][
            "action_code"
        ]
        == "CONTINUE"
    )
