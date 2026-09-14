"""WO 2D-20R: contextual one-to-many navigation target rebind.

Covers resolve_contextual_supersession_navigation_target() and
rebind_contextual_supersession_navigation_targets() in
backend/qcc/auto_twin/navigation_transition_materialization.py.

These fixtures are synthetic/provider-neutral -- they exercise the
generic 1->N resolution contract, never the real Mercurio 130/131
branch codes, and never hardcode a 130/131 mapping.
"""

from backend.qcc.auto_twin.navigation_transition_materialization import (
    resolve_contextual_supersession_navigation_target,
    rebind_contextual_supersession_navigation_targets,
)


STALE_FP = "d0" + "0" * 62
BEFORE_FP = "0f" + "0" * 62
REPLACEMENT_A_FP = "aa" + "0" * 62
REPLACEMENT_B_FP = "bb" + "0" * 62
UNRELATED_FP = "cc" + "0" * 62

OLD_STATE_KEY = "old-collided-state-key"
REPLACEMENT_A_KEY = "replacement-a-state-key"
REPLACEMENT_B_KEY = "replacement-b-state-key"
UNRELATED_KEY = "unrelated-state-key"

SIGNATURE_A = "sig-a"
SIGNATURE_B = "sig-b"


def _historical_states():
    return {
        OLD_STATE_KEY: {
            "last_fingerprint": STALE_FP,
        },
        REPLACEMENT_A_KEY: {
            "last_fingerprint": REPLACEMENT_A_FP,
        },
        REPLACEMENT_B_KEY: {
            "last_fingerprint": REPLACEMENT_B_FP,
        },
        UNRELATED_KEY: {
            "last_fingerprint": UNRELATED_FP,
        },
    }


def _current_states():
    return {
        REPLACEMENT_A_KEY: {
            "last_fingerprint": REPLACEMENT_A_FP,
        },
        REPLACEMENT_B_KEY: {
            "last_fingerprint": REPLACEMENT_B_FP,
        },
        UNRELATED_KEY: {
            "last_fingerprint": UNRELATED_FP,
        },
    }


def _supersession(
    *,
    replacement_keys,
    corroboration=None,
):
    record = {
        "old_state_key": OLD_STATE_KEY,
        "replacement_state_keys": list(replacement_keys),
    }

    if corroboration is not None:
        record["provenance"] = {
            "replacement_navigation_context_signatures": corroboration,
        }

    return {
        OLD_STATE_KEY: record,
    }


def _candidate(
    *,
    after_fingerprint=STALE_FP,
    context_signature=None,
    candidate_id="candidate-1",
):
    return {
        "candidate_id": candidate_id,
        "before_fingerprint": BEFORE_FP,
        "after_fingerprint": after_fingerprint,
        "context_signature": context_signature,
    }


def _resolve(
    *,
    context_signature,
    twin_supersessions,
    current_states=None,
):
    fingerprint_owners = {
        STALE_FP: {OLD_STATE_KEY},
    }

    return resolve_contextual_supersession_navigation_target(
        after_fingerprint=STALE_FP,
        context_signature=context_signature,
        twin_supersessions=twin_supersessions,
        fingerprint_owners=fingerprint_owners,
        current_states=(
            current_states
            if current_states is not None
            else _current_states()
        ),
    )


def test_unique_contextual_one_to_many_resolves():
    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration={
            REPLACEMENT_A_KEY: {
                "context_signature": SIGNATURE_A,
                "fingerprint": REPLACEMENT_A_FP,
            },
        },
    )

    resolved = _resolve(
        context_signature=SIGNATURE_A,
        twin_supersessions=twin_supersessions,
    )

    assert resolved == REPLACEMENT_A_FP


def test_two_branch_shaped_candidates_resolve_to_distinct_replacements():
    """130/131-shaped fixture: two contexts, two independent branches."""

    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration={
            REPLACEMENT_A_KEY: {
                "context_signature": SIGNATURE_A,
                "fingerprint": REPLACEMENT_A_FP,
            },
            REPLACEMENT_B_KEY: {
                "context_signature": SIGNATURE_B,
                "fingerprint": REPLACEMENT_B_FP,
            },
        },
    )

    candidates = (
        _candidate(
            candidate_id="branch-a",
            context_signature=SIGNATURE_A,
        ),
        _candidate(
            candidate_id="branch-b",
            context_signature=SIGNATURE_B,
        ),
    )

    rebound = rebind_contextual_supersession_navigation_targets(
        candidates,
        twin_supersessions=twin_supersessions,
        historical_states=_historical_states(),
        current_states=_current_states(),
    )

    by_id = {item["candidate_id"]: item for item in rebound}

    assert by_id["branch-a"]["after_fingerprint"] == REPLACEMENT_A_FP
    assert by_id["branch-b"]["after_fingerprint"] == REPLACEMENT_B_FP

    # Historical evidence identity (before_fingerprint) is untouched.
    assert by_id["branch-a"]["before_fingerprint"] == BEFORE_FP
    assert by_id["branch-b"]["before_fingerprint"] == BEFORE_FP

    # The input candidate dicts themselves are never mutated.
    assert candidates[0]["after_fingerprint"] == STALE_FP
    assert candidates[1]["after_fingerprint"] == STALE_FP


def test_context_without_corroboration_fails_closed():
    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration=None,
    )

    resolved = _resolve(
        context_signature=SIGNATURE_A,
        twin_supersessions=twin_supersessions,
    )

    assert resolved is None


def test_missing_context_signature_fails_closed():
    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration={
            REPLACEMENT_A_KEY: {
                "context_signature": SIGNATURE_A,
                "fingerprint": REPLACEMENT_A_FP,
            },
        },
    )

    resolved = _resolve(
        context_signature=None,
        twin_supersessions=twin_supersessions,
    )

    assert resolved is None


def test_ambiguous_competing_match_fails_closed():
    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration={
            REPLACEMENT_A_KEY: {
                "context_signature": SIGNATURE_A,
                "fingerprint": REPLACEMENT_A_FP,
            },
            REPLACEMENT_B_KEY: {
                # Same signature corroborates two replacements at
                # once -- never a unique match.
                "context_signature": SIGNATURE_A,
                "fingerprint": REPLACEMENT_B_FP,
            },
        },
    )

    resolved = _resolve(
        context_signature=SIGNATURE_A,
        twin_supersessions=twin_supersessions,
    )

    assert resolved is None


def test_corroboration_outside_supersession_set_is_ignored():
    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY],
        corroboration={
            # UNRELATED_KEY is not a declared replacement of this
            # supersession -- must never be treated as a match, even
            # though it exists as a real CURRENT state elsewhere.
            UNRELATED_KEY: {
                "context_signature": SIGNATURE_A,
                "fingerprint": UNRELATED_FP,
            },
        },
    )

    resolved = _resolve(
        context_signature=SIGNATURE_A,
        twin_supersessions=twin_supersessions,
    )

    assert resolved is None


def test_single_replacement_supersession_is_out_of_scope():
    """1->1 stays owned by the existing causal-refresh rebind path."""

    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY],
        corroboration={
            REPLACEMENT_A_KEY: {
                "context_signature": SIGNATURE_A,
                "fingerprint": REPLACEMENT_A_FP,
            },
        },
    )

    resolved = _resolve(
        context_signature=SIGNATURE_A,
        twin_supersessions=twin_supersessions,
    )

    assert resolved is None


def test_capability_drift_between_provenance_and_current_fails_closed():
    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration={
            REPLACEMENT_A_KEY: {
                "context_signature": SIGNATURE_A,
                # Recorded fingerprint no longer matches what is
                # CURRENTLY observed for this replacement.
                "fingerprint": UNRELATED_FP,
            },
        },
    )

    resolved = _resolve(
        context_signature=SIGNATURE_A,
        twin_supersessions=twin_supersessions,
    )

    assert resolved is None


def test_non_qualifying_candidate_is_returned_unchanged_by_rebind():
    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration=None,
    )

    candidate = _candidate(context_signature=SIGNATURE_A)

    rebound = rebind_contextual_supersession_navigation_targets(
        (candidate,),
        twin_supersessions=twin_supersessions,
        historical_states=_historical_states(),
        current_states=_current_states(),
    )

    assert rebound == (candidate,)


def test_unrelated_current_fingerprint_candidate_is_untouched():
    """A candidate whose target is not superseded at all is a no-op."""

    twin_supersessions = _supersession(
        replacement_keys=[REPLACEMENT_A_KEY, REPLACEMENT_B_KEY],
        corroboration={
            REPLACEMENT_A_KEY: {
                "context_signature": SIGNATURE_A,
                "fingerprint": REPLACEMENT_A_FP,
            },
        },
    )

    candidate = _candidate(
        after_fingerprint=UNRELATED_FP,
        context_signature=SIGNATURE_A,
    )

    rebound = rebind_contextual_supersession_navigation_targets(
        (candidate,),
        twin_supersessions=twin_supersessions,
        historical_states=_historical_states(),
        current_states=_current_states(),
    )

    assert rebound[0]["after_fingerprint"] == UNRELATED_FP
