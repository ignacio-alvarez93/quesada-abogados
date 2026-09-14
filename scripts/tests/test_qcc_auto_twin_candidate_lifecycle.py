import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION,
    AUTO_TWIN_CANDIDATE_STATUS_REJECTED,
    AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
)


def _twin():
    return AutoTwinManagedSite(
        twin_key="mercurio",
        site_code="MERCURIO",
        origins=(
            "https://example.test",
        ),
        path_prefixes=(
            "/mercurio",
        ),
    )


def _changed():
    return {
        "classification":
            "CHANGED",

        "capture_id":
            "capture-new",

        "observed_at":
            "2026-09-05T08:00:00+00:00",

        "browser_profile_key":
            "mercurio_assisted",

        "pathname":
            "/mercurio/page.html",

        "functional_state":
            None,

        "state_key":
            "state-key",

        "fingerprint":
            "fp-new",

        "baseline_fingerprint":
            "fp-baseline",

        "baseline_capture_id":
            "capture-baseline",
    }


def _prepared_store(
    tmp_path,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    created = (
        store.record_changed_observation(
            _twin(),
            _changed(),
        )
    )

    return (
        store,
        created[
            "candidate"
        ][
            "candidate_id"
        ],
    )


def test_candidate_starts_pending_validation(
    tmp_path,
):
    store, candidate_id = (
        _prepared_store(
            tmp_path
        )
    )

    candidate = store.get_candidate(
        "mercurio",
        candidate_id,
    )

    assert (
        candidate["status"]
        == AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION
    )


def test_pending_can_be_validated(
    tmp_path,
):
    store, candidate_id = (
        _prepared_store(
            tmp_path
        )
    )

    result = (
        store.transition_candidate_status(
            "mercurio",
            candidate_id,
            target_status=(
                AUTO_TWIN_CANDIDATE_STATUS_VALIDATED
            ),
        )
    )

    assert result["changed"] is True

    candidate = result[
        "candidate"
    ]

    assert (
        candidate["status"]
        == AUTO_TWIN_CANDIDATE_STATUS_VALIDATED
    )

    assert candidate[
        "validated_at"
    ]

    # Validar no modifica identidad del baseline.
    assert (
        candidate["baseline_fingerprint"]
        == "fp-baseline"
    )

    assert (
        candidate["baseline_capture_id"]
        == "capture-baseline"
    )


def test_pending_can_be_rejected(
    tmp_path,
):
    store, candidate_id = (
        _prepared_store(
            tmp_path
        )
    )

    result = (
        store.transition_candidate_status(
            "mercurio",
            candidate_id,
            target_status=(
                AUTO_TWIN_CANDIDATE_STATUS_REJECTED
            ),
        )
    )

    assert result["changed"] is True

    candidate = result[
        "candidate"
    ]

    assert (
        candidate["status"]
        == AUTO_TWIN_CANDIDATE_STATUS_REJECTED
    )

    assert candidate[
        "rejected_at"
    ]


def test_same_transition_is_idempotent(
    tmp_path,
):
    store, candidate_id = (
        _prepared_store(
            tmp_path
        )
    )

    first = (
        store.transition_candidate_status(
            "mercurio",
            candidate_id,
            target_status="VALIDATED",
        )
    )

    revision = (
        store.revision
    )

    second = (
        store.transition_candidate_status(
            "mercurio",
            candidate_id,
            target_status="VALIDATED",
        )
    )

    assert first["changed"] is True
    assert second["changed"] is False

    assert (
        store.revision
        == revision
    )


@pytest.mark.parametrize(
    "initial,target",
    [
        ("VALIDATED", "REJECTED"),
        ("REJECTED", "VALIDATED"),
    ],
)
def test_terminal_decision_cannot_be_reversed(
    tmp_path,
    initial,
    target,
):
    store, candidate_id = (
        _prepared_store(
            tmp_path
        )
    )

    store.transition_candidate_status(
        "mercurio",
        candidate_id,
        target_status=initial,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CANDIDATE_STATUS_TRANSITION_INVALID"
        ),
    ):
        store.transition_candidate_status(
            "mercurio",
            candidate_id,
            target_status=target,
        )


def test_unknown_candidate_is_rejected(
    tmp_path,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND",
    ):
        store.transition_candidate_status(
            "mercurio",
            "missing",
            target_status="VALIDATED",
        )


def test_invalid_target_status_is_rejected(
    tmp_path,
):
    store, candidate_id = (
        _prepared_store(
            tmp_path
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CANDIDATE_TARGET_STATUS_INVALID"
        ),
    ):
        store.transition_candidate_status(
            "mercurio",
            candidate_id,
            target_status="ACTIVE",
        )


def test_decision_survives_restart(
    tmp_path,
):
    path = (
        tmp_path
        / "candidates.json"
    )

    first = AutoTwinCandidateRevisionStore(
        path=path
    )

    created = (
        first.record_changed_observation(
            _twin(),
            _changed(),
        )
    )

    candidate_id = (
        created[
            "candidate"
        ][
            "candidate_id"
        ]
    )

    first.transition_candidate_status(
        "mercurio",
        candidate_id,
        target_status="VALIDATED",
    )

    second = AutoTwinCandidateRevisionStore(
        path=path
    )

    candidate = second.get_candidate(
        "mercurio",
        candidate_id,
    )

    assert (
        candidate["status"]
        == "VALIDATED"
    )

    assert candidate[
        "validated_at"
    ]


def test_lifecycle_has_no_active_status(
    tmp_path,
):
    store, candidate_id = (
        _prepared_store(
            tmp_path
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CANDIDATE_TARGET_STATUS_INVALID"
        ),
    ):
        store.transition_candidate_status(
            "mercurio",
            candidate_id,
            target_status="ACTIVE",
        )
