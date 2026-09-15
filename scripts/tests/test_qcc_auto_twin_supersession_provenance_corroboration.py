"""WO 2D-20S: governed corroboration of supersession provenance.

Covers correlate_supersession_replacement_navigation_context_signatures()
in backend/qcc/auto_twin/navigation_transition_materialization.py.

These fixtures are synthetic/provider-neutral -- they exercise the
generic evidence-correlation contract, never the real Mercurio 130/131
branch codes, and never hardcode a 130/131 mapping. Correlation is
derived exclusively from timestamps, fingerprints and opaque
context_signature hashes -- never from navigation_context content.
"""

from backend.qcc.auto_twin.navigation_transition_materialization import (
    correlate_supersession_replacement_navigation_context_signatures,
)


STALE_FP = "d0" + "0" * 62
REPLACEMENT_A_FP = "aa" + "0" * 62
REPLACEMENT_B_FP = "bb" + "0" * 62
UNRELATED_FP = "cc" + "0" * 62

REPLACEMENT_A_KEY = "replacement-a-state-key"
REPLACEMENT_B_KEY = "replacement-b-state-key"

ANCHOR_A = "2026-09-12T06:02:28.192874+00:00"
ANCHOR_B = "2026-09-12T06:06:35.832343+00:00"

SIGNATURE_A = "sig-a"
SIGNATURE_B = "sig-b"


def _anchors():
    return {
        REPLACEMENT_A_KEY: ANCHOR_A,
        REPLACEMENT_B_KEY: ANCHOR_B,
    }


def _current_states():
    return {
        REPLACEMENT_A_KEY: {
            "last_fingerprint": REPLACEMENT_A_FP,
        },
        REPLACEMENT_B_KEY: {
            "last_fingerprint": REPLACEMENT_B_FP,
        },
    }


def _candidate(
    *,
    after_fingerprint=STALE_FP,
    context_signature,
    observed_at,
):
    return {
        "after_fingerprint": after_fingerprint,
        "context_signature": context_signature,
        "observed_at": observed_at,
    }


def _correlate(
    *,
    candidates,
    anchors=None,
    current_states=None,
    max_gap_seconds=120,
):
    return (
        correlate_supersession_replacement_navigation_context_signatures(
            stale_fingerprint=STALE_FP,
            replacement_anchors=(
                anchors if anchors is not None else _anchors()
            ),
            candidates=candidates,
            current_states=(
                current_states
                if current_states is not None
                else _current_states()
            ),
        )
    )


def test_independent_evidence_correlates_to_exact_2d_20r_schema():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    corroboration = _correlate(candidates=candidates)

    assert corroboration == {
        REPLACEMENT_A_KEY: {
            "context_signature": SIGNATURE_A,
            "fingerprint": REPLACEMENT_A_FP,
        },
        REPLACEMENT_B_KEY: {
            "context_signature": SIGNATURE_B,
            "fingerprint": REPLACEMENT_B_FP,
        },
    }


def test_two_replacements_receive_distinct_context_signatures():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    corroboration = _correlate(candidates=candidates)

    signatures = {
        entry["context_signature"]
        for entry in corroboration.values()
    }

    assert signatures == {SIGNATURE_A, SIGNATURE_B}


def test_signature_without_capture_event_correlation_cannot_corroborate():
    """A candidate carrying a context_signature but observed at a time

    with no anchor at-or-before it (never preceded by any recorded
    capture evidence) cannot corroborate anything -- the literal
    signature alone is insufficient.
    """

    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-01-01T00:00:00+00:00",
        ),
    )

    assert _correlate(candidates=candidates) == {}


def test_missing_correlation_for_one_replacement_fails_closed():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        # No candidate ever corroborates REPLACEMENT_B_KEY.
    )

    assert _correlate(candidates=candidates) == {}


def test_ambiguous_multiple_candidates_for_same_replacement_fails_closed():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        _candidate(
            context_signature="sig-a-2",
            observed_at="2026-09-12T06:02:35.000000+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    assert _correlate(candidates=candidates) == {}


def test_conflicting_duplicate_signature_across_replacements_fails_closed():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        # Same signature corroborates the OTHER replacement too --
        # could never uniquely resolve either one.
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    assert _correlate(candidates=candidates) == {}


def test_candidate_targeting_unrelated_fingerprint_is_ignored():
    candidates = (
        _candidate(
            after_fingerprint=UNRELATED_FP,
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    # REPLACEMENT_A_KEY never gets a qualifying candidate -- the
    # unrelated-fingerprint candidate must not be recruited for it.
    assert _correlate(candidates=candidates) == {}


def test_candidate_without_context_signature_is_ignored():
    candidates = (
        _candidate(
            context_signature=None,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    assert _correlate(candidates=candidates) == {}


def test_gap_beyond_bound_is_treated_as_uncorrelated():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            # Far later than ANCHOR_A -- too stale a gap to trust as
            # the same physical navigation event.
            observed_at="2026-09-12T08:00:00+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    assert _correlate(candidates=candidates) == {}


def test_missing_current_fingerprint_fails_closed():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    current_states = {
        REPLACEMENT_A_KEY: {
            "last_fingerprint": REPLACEMENT_A_FP,
        },
        # REPLACEMENT_B_KEY has no CURRENT observation at all.
    }

    assert _correlate(
        candidates=candidates,
        current_states=current_states,
    ) == {}


def test_correlation_is_pure_and_deterministic():
    candidates = (
        _candidate(
            context_signature=SIGNATURE_A,
            observed_at="2026-09-12T06:02:31.639000+00:00",
        ),
        _candidate(
            context_signature=SIGNATURE_B,
            observed_at="2026-09-12T06:06:39.729000+00:00",
        ),
    )

    first = _correlate(candidates=candidates)
    second = _correlate(candidates=candidates)

    assert first == second
