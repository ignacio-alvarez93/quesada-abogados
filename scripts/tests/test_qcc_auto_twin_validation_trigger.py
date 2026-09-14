from types import SimpleNamespace

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_TRIGGER_AMBIGUOUS,
    AUTO_TWIN_VALIDATION_TRIGGER_READY,
    AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED,
    build_auto_twin_profile_policy,
    resolve_auto_twin_validation_trigger,
)


class CandidateStore:
    def __init__(
        self,
        candidates,
    ):
        self.candidates = list(
            candidates
        )

        self.snapshot_calls = []

    def snapshot(
        self,
        twin_key,
    ):
        self.snapshot_calls.append(
            twin_key
        )

        return {
            "revision": 1,
            "candidates":
                list(
                    self.candidates
                ),
        }


def managed(
    *,
    enabled=True,
):
    return SimpleNamespace(
        twin_key="mercurio",
        enabled=enabled,
    )


def capture(
    *,
    capture_id="twin-capture-1",
    profile_key="twin_discovery",
    pathname="/mercurio/page.html",
    functional_state="STATE_A",
):
    return {
        "capture_id":
            capture_id,

        "browser_profile_key":
            profile_key,

        "pathname":
            pathname,

        "functional_state":
            functional_state,
    }


def candidate(
    *,
    candidate_id="candidate-1",
    revision=1,
    status="PENDING_VALIDATION",
    pathname="/mercurio/page.html",
    functional_state="STATE_A",
    latest_capture_id="real-capture-1",
    evidence_capture_ids=None,
):
    if evidence_capture_ids is None:
        evidence_capture_ids = [
            latest_capture_id
        ]

    return {
        "candidate_id":
            candidate_id,

        "candidate_revision":
            revision,

        "status":
            status,

        "pathname":
            pathname,

        "functional_state":
            functional_state,

        "latest_capture_id":
            latest_capture_id,

        "evidence_capture_ids":
            list(
                evidence_capture_ids
            ),
    }


def resolve(
    candidates,
    *,
    managed_twin=None,
    profile_key="twin_discovery",
    twin_capture=None,
):
    return resolve_auto_twin_validation_trigger(
        managed_twin=(
            managed_twin
            or managed()
        ),
        profile_policy=(
            build_auto_twin_profile_policy(
                profile_key
            )
        ),
        candidate_store=(
            CandidateStore(
                candidates
            )
        ),
        twin_capture=(
            twin_capture
            or capture(
                profile_key=profile_key
            )
        ),
    )


def test_unique_pending_candidate_is_ready():
    result = resolve(
        [
            candidate()
        ]
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_READY
    )

    assert (
        result["reason"]
        == "READY"
    )

    assert (
        result["candidate_id"]
        == "candidate-1"
    )

    assert (
        result["real_capture_id"]
        == "real-capture-1"
    )

    assert (
        result["twin_capture_id"]
        == "twin-capture-1"
    )


def test_observer_profile_never_becomes_ready():
    result = resolve(
        [
            candidate()
        ],
        profile_key="office_profile",
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "PROFILE_NOT_VALIDATION"
    )


def test_disabled_managed_twin_is_skipped():
    result = resolve(
        [
            candidate()
        ],
        managed_twin=managed(
            enabled=False
        ),
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "MANAGED_TWIN_DISABLED"
    )


def test_capture_profile_must_match_policy_profile():
    result = resolve_auto_twin_validation_trigger(
        managed_twin=managed(),
        profile_policy=(
            build_auto_twin_profile_policy(
                "twin_discovery"
            )
        ),
        candidate_store=CandidateStore(
            [
                candidate()
            ]
        ),
        twin_capture=capture(
            profile_key="other_profile"
        ),
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "TWIN_CAPTURE_PROFILE_MISMATCH"
    )


def test_no_pending_candidate_is_skipped():
    result = resolve(
        []
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "NO_PENDING_CANDIDATE"
    )


def test_pending_candidate_must_match_pathname():
    result = resolve(
        [
            candidate(
                pathname="/other.html"
            )
        ]
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "NO_MATCHING_CANDIDATE"
    )


def test_pending_candidate_must_match_functional_state():
    result = resolve(
        [
            candidate(
                functional_state="STATE_B"
            )
        ]
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "NO_MATCHING_CANDIDATE"
    )


def test_terminal_candidates_are_not_eligible():
    result = resolve(
        [
            candidate(
                status="VALIDATED"
            ),
            candidate(
                candidate_id="candidate-2",
                status="REJECTED",
            ),
        ]
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "NO_PENDING_CANDIDATE"
    )


def test_two_matching_pending_candidates_fail_closed():
    result = resolve(
        [
            candidate(
                candidate_id="candidate-1",
                revision=1,
                latest_capture_id="real-1",
            ),
            candidate(
                candidate_id="candidate-2",
                revision=2,
                latest_capture_id="real-2",
            ),
        ]
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_AMBIGUOUS
    )

    assert (
        result["reason"]
        == "AMBIGUOUS_CANDIDATE"
    )

    assert (
        result["candidate_id"]
        is None
    )

    assert (
        result["real_capture_id"]
        is None
    )

    assert (
        result["matching_candidate_ids"]
        == [
            "candidate-1",
            "candidate-2",
        ]
    )


def test_latest_real_capture_must_be_candidate_evidence():
    result = resolve(
        [
            candidate(
                latest_capture_id="real-latest",
                evidence_capture_ids=[
                    "real-old"
                ],
            )
        ]
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "REAL_CAPTURE_UNAVAILABLE"
    )

    assert (
        result["real_capture_id"]
        is None
    )


def test_real_and_twin_capture_ids_cannot_collide():
    result = resolve(
        [
            candidate(
                latest_capture_id="same-capture"
            )
        ],
        twin_capture=capture(
            capture_id="same-capture"
        ),
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
    )

    assert (
        result["reason"]
        == "REAL_TWIN_CAPTURE_COLLISION"
    )


def test_none_functional_state_matches_none_only():
    result = resolve(
        [
            candidate(
                functional_state=None
            )
        ],
        twin_capture=capture(
            functional_state=None
        ),
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_READY
    )


def test_ambiguity_is_checked_before_evidence_quality():
    result = resolve(
        [
            candidate(
                candidate_id="candidate-valid",
                revision=1,
                latest_capture_id="real-1",
            ),
            candidate(
                candidate_id="candidate-bad-evidence",
                revision=2,
                latest_capture_id="real-2",
                evidence_capture_ids=[
                    "different-real"
                ],
            ),
        ]
    )

    assert (
        result["status"]
        == AUTO_TWIN_VALIDATION_TRIGGER_AMBIGUOUS
    )

    assert (
        result["candidate_id"]
        is None
    )
