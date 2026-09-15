import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION,
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
)


def _twin():
    return AutoTwinManagedSite(
        twin_key="mercurio",
        site_code="MERCURIO",
        origins=(
            "https://mercurio.delegaciondelgobierno.gob.es",
        ),
        path_prefixes=(
            "/mercurio",
        ),
    )


def _changed(
    *,
    capture_id,
    fingerprint,
    baseline="fp-baseline",
):
    return {
        "classification":
            "CHANGED",

        "capture_id":
            capture_id,

        "observed_at":
            "2026-09-05T08:00:00+00:00",

        "browser_profile_key":
            "mercurio_assisted",

        "pathname":
            "/mercurio/finalizacionSolicitud.html",

        "functional_state":
            None,

        "state_key":
            "state-key-1",

        "fingerprint":
            fingerprint,

        "baseline_fingerprint":
            baseline,

        "baseline_capture_id":
            "capture-baseline",
    }


def test_first_change_creates_pending_candidate(
    tmp_path,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    result = (
        store.record_changed_observation(
            _twin(),
            _changed(
                capture_id="capture-2",
                fingerprint="fp-new",
            ),
        )
    )

    assert result["created"] is True
    assert result["updated"] is False

    candidate = result[
        "candidate"
    ]

    assert (
        candidate["candidate_revision"]
        == 1
    )

    assert (
        candidate["status"]
        == AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION
    )

    assert (
        candidate["baseline_fingerprint"]
        == "fp-baseline"
    )

    assert (
        candidate["fingerprint"]
        == "fp-new"
    )


def test_same_change_is_deduplicated(
    tmp_path,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    twin = _twin()

    first = (
        store.record_changed_observation(
            twin,
            _changed(
                capture_id="capture-2",
                fingerprint="fp-new",
            ),
        )
    )

    second = (
        store.record_changed_observation(
            twin,
            _changed(
                capture_id="capture-3",
                fingerprint="fp-new",
            ),
        )
    )

    assert (
        first[
            "candidate"
        ]["candidate_id"]
        == second[
            "candidate"
        ]["candidate_id"]
    )

    assert second["created"] is False
    assert second["updated"] is True

    assert (
        second[
            "candidate"
        ]["candidate_revision"]
        == 1
    )

    assert (
        second[
            "candidate"
        ]["observation_count"]
        == 2
    )

    assert (
        second[
            "candidate"
        ]["evidence_capture_ids"]
        == [
            "capture-2",
            "capture-3",
        ]
    )

    assert (
        store.snapshot(
            "mercurio"
        )["candidate_count"]
        == 1
    )


def test_exact_capture_is_idempotent(
    tmp_path,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    twin = _twin()

    first = (
        store.record_changed_observation(
            twin,
            _changed(
                capture_id="capture-2",
                fingerprint="fp-new",
            ),
        )
    )

    revision_before = (
        store.revision
    )

    second = (
        store.record_changed_observation(
            twin,
            _changed(
                capture_id="capture-2",
                fingerprint="fp-new",
            ),
        )
    )

    assert first["created"] is True

    assert second["created"] is False
    assert second["updated"] is False

    assert (
        store.revision
        == revision_before
    )


def test_different_change_creates_next_candidate_revision(
    tmp_path,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    twin = _twin()

    store.record_changed_observation(
        twin,
        _changed(
            capture_id="capture-2",
            fingerprint="fp-change-a",
        ),
    )

    second = (
        store.record_changed_observation(
            twin,
            _changed(
                capture_id="capture-3",
                fingerprint="fp-change-b",
            ),
        )
    )

    assert (
        second[
            "candidate"
        ]["candidate_revision"]
        == 2
    )

    assert (
        store.snapshot(
            "mercurio"
        )["candidate_count"]
        == 2
    )


@pytest.mark.parametrize(
    "classification",
    [
        "KNOWN",
        "UNKNOWN",
        "",
    ],
)
def test_only_changed_can_create_candidate(
    tmp_path,
    classification,
):
    store = AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )

    observation = _changed(
        capture_id="capture-2",
        fingerprint="fp-new",
    )

    observation[
        "classification"
    ] = classification

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_CANDIDATE_REQUIRES_CHANGED",
    ):
        store.record_changed_observation(
            _twin(),
            observation,
        )


def test_equal_baseline_is_not_candidate(
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
        match="QCC_AUTO_TWIN_CANDIDATE_NOT_CHANGED",
    ):
        store.record_changed_observation(
            _twin(),
            _changed(
                capture_id="capture-2",
                fingerprint="same",
                baseline="same",
            ),
        )


def test_candidate_survives_restart(
    tmp_path,
):
    path = (
        tmp_path
        / "candidates.json"
    )

    first = AutoTwinCandidateRevisionStore(
        path=path
    )

    first.record_changed_observation(
        _twin(),
        _changed(
            capture_id="capture-2",
            fingerprint="fp-new",
        ),
    )

    second = AutoTwinCandidateRevisionStore(
        path=path
    )

    snapshot = second.snapshot(
        "mercurio"
    )

    assert snapshot["candidate_count"] == 1

    candidate = snapshot[
        "candidates"
    ][0]

    assert (
        candidate["candidate_revision"]
        == 1
    )

    assert (
        candidate["status"]
        == "PENDING_VALIDATION"
    )

    assert (
        candidate["baseline_capture_id"]
        == "capture-baseline"
    )


def test_candidate_store_contains_references_not_heavy_evidence(
    tmp_path,
):
    path = (
        tmp_path
        / "candidates.json"
    )

    store = AutoTwinCandidateRevisionStore(
        path=path
    )

    store.record_changed_observation(
        _twin(),
        _changed(
            capture_id="capture-2",
            fingerprint="fp-new",
        ),
    )

    text = path.read_text(
        encoding="utf-8"
    )

    assert "capture-2" in text
    assert "fp-new" in text

    for forbidden in (
        "outerHTML",
        "page.mhtml",
        "qcc_capture",
        "screenshot_viewport",
    ):
        assert forbidden not in text
