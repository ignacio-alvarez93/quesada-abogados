from backend.qcc.auto_twin.automatic_materialization import (
    _rebind_causal_refresh_navigation_endpoints,
)


FP_OLD = "a" * 64
FP_NEW = "c" * 64
FP_TARGET = "b" * 64
FP_UNRELATED_BEFORE = "d" * 64
FP_UNRELATED_AFTER = "e" * 64
FP_UNRESOLVED_OLD = "f" * 64


def _transition(
    candidate_id,
    before,
    after,
):
    return {
        "candidate_id":
            candidate_id,

        "before_fingerprint":
            before,

        "after_fingerprint":
            after,
    }


def test_governed_refresh_rebinds_old_endpoint_to_new():
    transitions = (
        _transition(
            "cand-1",
            FP_OLD,
            FP_TARGET,
        ),
    )

    result = (
        _rebind_causal_refresh_navigation_endpoints(
            transitions,
            {FP_OLD: FP_NEW},
            set(),
        )
    )

    assert len(result) == 1

    assert result[0]["before_fingerprint"] == FP_NEW
    assert result[0]["after_fingerprint"] == FP_TARGET
    assert result[0]["candidate_id"] == "cand-1"


def test_rebind_never_mutates_the_historical_candidate_object():
    original = _transition(
        "cand-1",
        FP_OLD,
        FP_TARGET,
    )

    _rebind_causal_refresh_navigation_endpoints(
        (original,),
        {FP_OLD: FP_NEW},
        set(),
    )

    # Historical evidence/provenance (the caller's own object, standing
    # in for the human navigation candidate store's record) must never
    # be rewritten in place.
    assert original["before_fingerprint"] == FP_OLD


def test_both_endpoints_rebind_when_both_were_refreshed():
    transitions = (
        _transition(
            "cand-1",
            FP_OLD,
            FP_TARGET,
        ),
    )

    result = (
        _rebind_causal_refresh_navigation_endpoints(
            transitions,
            {
                FP_OLD: FP_NEW,
                FP_TARGET: "9" * 64,
            },
            set(),
        )
    )

    assert result[0]["before_fingerprint"] == FP_NEW
    assert result[0]["after_fingerprint"] == "9" * 64


def test_ambiguous_refresh_drops_transition_instead_of_guessing():
    transitions = (
        _transition(
            "cand-1",
            FP_UNRESOLVED_OLD,
            FP_TARGET,
        ),
    )

    result = (
        _rebind_causal_refresh_navigation_endpoints(
            transitions,
            {},
            {FP_UNRESOLVED_OLD},
        )
    )

    assert result == ()


def test_unrelated_missing_fingerprint_is_left_unchanged():
    transitions = (
        _transition(
            "cand-1",
            FP_UNRELATED_BEFORE,
            FP_UNRELATED_AFTER,
        ),
    )

    result = (
        _rebind_causal_refresh_navigation_endpoints(
            transitions,
            {FP_OLD: FP_NEW},
            {FP_UNRESOLVED_OLD},
        )
    )

    assert result[0]["before_fingerprint"] == FP_UNRELATED_BEFORE
    assert result[0]["after_fingerprint"] == FP_UNRELATED_AFTER


def test_rebind_never_adds_or_duplicates_transitions():
    transitions = (
        _transition(
            "cand-1",
            FP_OLD,
            FP_TARGET,
        ),
        _transition(
            "cand-2",
            FP_TARGET,
            FP_UNRELATED_AFTER,
        ),
    )

    result = (
        _rebind_causal_refresh_navigation_endpoints(
            transitions,
            {FP_OLD: FP_NEW},
            set(),
        )
    )

    assert len(result) == len(transitions)

    assert {
        item["candidate_id"]
        for item in result
    } == {
        "cand-1",
        "cand-2",
    }


def test_rebind_output_is_always_a_subset_of_its_input_by_candidate_id():
    # This is the property that keeps this mechanism from being able
    # to widen which edges materialize beyond what the existing
    # two-pass eligibility gate (_navigation_refresh_for_latest_
    # revision) already selected: rebinding can only rewrite or drop
    # entries already present in `transitions`, never introduce new
    # ones sourced elsewhere.
    transitions = (
        _transition(
            "cand-1",
            FP_OLD,
            FP_TARGET,
        ),
    )

    result = (
        _rebind_causal_refresh_navigation_endpoints(
            transitions,
            {
                FP_OLD: FP_NEW,
                # An unrelated rebind entry that happens to match no
                # transition in the input at all must not fabricate
                # a new transition.
                FP_UNRELATED_BEFORE: FP_UNRELATED_AFTER,
            },
            set(),
        )
    )

    input_ids = {
        item["candidate_id"]
        for item in transitions
    }

    result_ids = {
        item["candidate_id"]
        for item in result
    }

    assert result_ids <= input_ids
