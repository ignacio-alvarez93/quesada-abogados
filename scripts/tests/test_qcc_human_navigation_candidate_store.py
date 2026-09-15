from pathlib import Path

from backend.qcc.navigation_learning import (
    HUMAN_NAVIGATION_CANDIDATE_STATUS_CANDIDATE,
    HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED,
    HUMAN_NAVIGATION_CANDIDATE_STATUS_CORROBORATED,
    HumanNavigationCandidateStore,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def _transition(
    event_id,
    *,
    environment="LAB",
    after_state="STATE_B",
    after_fingerprint=FP_B,
):
    return {
        "event_id":
            event_id,

        "session_id":
            "session-secret-runtime-only",

        "site_code":
            "MERCURIO",

        "environment":
            environment,

        "before_state":
            "STATE_A",

        "before_fingerprint":
            FP_A,

        "kind":
            "LINK",

        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            "#continue",

        "frame_path":
            "main",

        "after_state":
            after_state,

        "after_fingerprint":
            after_fingerprint,

        "action_observed_at":
            "2026-08-31T09:00:00+00:00",

        "after_observed_at":
            "2026-08-31T09:00:01+00:00",

        "changed":
            True,

        # Deliberately unsafe/unrelated fields:
        "client_id":
            "must-not-persist",

        "url":
            "https://example.invalid/private",

        "text":
            "must-not-persist",
    }


def _store(
    tmp_path,
):
    return HumanNavigationCandidateStore(
        root=(
            tmp_path
            / "human-navigation-learning"
        )
    )


def test_first_distinct_observation_is_candidate(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    result = (
        store.record_observed_transition(
            _transition(
                "event-1"
            )
        )
    )

    candidate = result[
        "candidate"
    ]

    assert (
        result[
            "recorded"
        ]
        is True
    )

    assert (
        result[
            "became_confirmed"
        ]
        is False
    )

    assert (
        candidate[
            "observation_count"
        ]
        == 1
    )

    assert (
        candidate[
            "status"
        ]
        == HUMAN_NAVIGATION_CANDIDATE_STATUS_CANDIDATE
    )


def test_second_distinct_observation_is_corroborated(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_observed_transition(
        _transition(
            "event-1"
        )
    )

    result = (
        store.record_observed_transition(
            _transition(
                "event-2"
            )
        )
    )

    assert (
        result[
            "candidate"
        ][
            "observation_count"
        ]
        == 2
    )

    assert (
        result[
            "candidate"
        ][
            "status"
        ]
        == HUMAN_NAVIGATION_CANDIDATE_STATUS_CORROBORATED
    )


def test_third_distinct_observation_confirms_candidate(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    for event_id in (
        "event-1",
        "event-2",
    ):
        store.record_observed_transition(
            _transition(
                event_id
            )
        )

    result = (
        store.record_observed_transition(
            _transition(
                "event-3"
            )
        )
    )

    assert (
        result[
            "became_confirmed"
        ]
        is True
    )

    assert (
        result[
            "candidate"
        ][
            "observation_count"
        ]
        == 3
    )

    assert (
        result[
            "candidate"
        ][
            "status"
        ]
        == HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
    )


def test_same_event_id_is_idempotent(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    first = (
        store.record_observed_transition(
            _transition(
                "event-1"
            )
        )
    )

    second = (
        store.record_observed_transition(
            _transition(
                "event-1"
            )
        )
    )

    assert (
        first[
            "candidate"
        ][
            "observation_count"
        ]
        == 1
    )

    assert (
        second[
            "recorded"
        ]
        is False
    )

    assert (
        second[
            "duplicate_event"
        ]
        is True
    )

    assert (
        second[
            "candidate"
        ][
            "observation_count"
        ]
        == 1
    )


def test_different_after_transition_is_separate_candidate(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_observed_transition(
        _transition(
            "event-1"
        )
    )

    store.record_observed_transition(
        _transition(
            "event-2",
            after_state="STATE_C",
            after_fingerprint=FP_C,
        )
    )

    snapshot = store.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    assert (
        snapshot[
            "candidate_count"
        ]
        == 2
    )


def test_environment_evidence_is_strictly_separated(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_observed_transition(
        _transition(
            "lab-event",
            environment="LAB",
        )
    )

    store.record_observed_transition(
        _transition(
            "real-event",
            environment="REAL",
        )
    )

    lab = store.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    real = store.snapshot(
        "MERCURIO",
        environment="REAL",
    )

    assert (
        lab[
            "candidate_count"
        ]
        == 1
    )

    assert (
        real[
            "candidate_count"
        ]
        == 1
    )

    assert (
        lab[
            "candidates"
        ][0][
            "event_ids"
        ]
        == [
            "lab-event"
        ]
    )

    assert (
        real[
            "candidates"
        ][0][
            "event_ids"
        ]
        == [
            "real-event"
        ]
    )


def test_candidate_persistence_is_pii_safe(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    store.record_observed_transition(
        _transition(
            "event-1"
        )
    )

    snapshot = store.snapshot(
        "MERCURIO",
        environment="LAB",
    )

    serialized = str(
        snapshot
    )

    assert (
        "session-secret-runtime-only"
        not in serialized
    )

    assert (
        "must-not-persist"
        not in serialized
    )

    assert (
        "example.invalid"
        not in serialized
    )


def test_confirmed_candidate_can_be_marked_promoted(
    tmp_path,
):
    store = _store(
        tmp_path
    )

    candidate_id = None

    for index in range(
        1,
        4,
    ):
        result = (
            store.record_observed_transition(
                _transition(
                    f"event-{index}"
                )
            )
        )

        candidate_id = (
            result[
                "candidate"
            ][
                "candidate_id"
            ]
        )

    pending = (
        store.confirmed_unpromoted(
            "MERCURIO",
            environment="LAB",
        )
    )

    assert len(
        pending
    ) == 1

    promoted = (
        store.mark_promoted(
            "MERCURIO",
            candidate_id,
            environment="LAB",
            promoted_at=(
                "2026-08-31T10:00:00+00:00"
            ),
        )
    )

    assert (
        promoted[
            "promoted_at"
        ]
        == "2026-08-31T10:00:00+00:00"
    )

    assert (
        store.confirmed_unpromoted(
            "MERCURIO",
            environment="LAB",
        )
        == ()
    )


def test_candidate_store_does_not_write_navigation_knowledge():
    source = (
        Path(
            "backend/qcc/navigation_learning/"
            "human_candidate_store.py"
        )
        .read_text(
            encoding="utf-8"
        )
    )

    assert (
        "from backend.qcc.navigation_knowledge"
        not in source
    )

    assert (
        "import backend.qcc.navigation_knowledge"
        not in source
    )

    assert (
        ".record_transition("
        not in source
    )
