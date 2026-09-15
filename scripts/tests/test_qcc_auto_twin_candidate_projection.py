from backend.qcc.auto_twin import (
    AutoTwinCandidateRevisionStore,
    AutoTwinManagedSite,
    AutoTwinManagedSiteStore,
    project_auto_twin_candidate_revision,
)


def _managed(
    tmp_path,
    *,
    auto_update=True,
):
    store = AutoTwinManagedSiteStore(
        path=(
            tmp_path
            / "managed.json"
        )
    )

    store.register(
        AutoTwinManagedSite(
            twin_key="mercurio",
            site_code="MERCURIO",
            origins=(
                "https://example.test",
            ),
            path_prefixes=(
                "/mercurio",
            ),
            auto_update=auto_update,
        )
    )

    return store


def _candidates(
    tmp_path,
):
    return AutoTwinCandidateRevisionStore(
        path=(
            tmp_path
            / "candidates.json"
        )
    )


def _observation(
    classification,
    *,
    auto_update=True,
    capture_id="capture-2",
    fingerprint="fp-new",
):
    return {
        "processed":
            True,

        "classification":
            classification,

        "twin_key":
            "mercurio",

        "browser_profile_key":
            "mercurio_assisted",

        "capture_id":
            capture_id,

        "observed_at":
            "2026-09-05T08:00:00+00:00",

        "pathname":
            "/mercurio/page.html",

        "functional_state":
            None,

        "state_key":
            "state-key",

        "fingerprint":
            fingerprint,

        "baseline_fingerprint":
            "fp-baseline",

        "baseline_capture_id":
            "capture-baseline",

        "auto_update":
            auto_update,
    }


def test_changed_creates_candidate(
    tmp_path,
):
    result = (
        project_auto_twin_candidate_revision(
            _managed(
                tmp_path
            ),
            _candidates(
                tmp_path
            ),
            _observation(
                "CHANGED"
            ),
        )
    )

    assert result["processed"] is True
    assert result["created"] is True

    assert (
        result["status"]
        == "PENDING_VALIDATION"
    )

    assert (
        result["candidate_revision"]
        == 1
    )


def test_known_does_not_create_candidate(
    tmp_path,
):
    candidates = _candidates(
        tmp_path
    )

    result = (
        project_auto_twin_candidate_revision(
            _managed(
                tmp_path
            ),
            candidates,
            _observation(
                "KNOWN"
            ),
        )
    )

    assert result["processed"] is False

    assert (
        result["reason"]
        == "OBSERVATION_NOT_CHANGED"
    )

    assert (
        candidates.snapshot(
            "mercurio"
        )["candidate_count"]
        == 0
    )


def test_unknown_does_not_create_candidate(
    tmp_path,
):
    candidates = _candidates(
        tmp_path
    )

    result = (
        project_auto_twin_candidate_revision(
            _managed(
                tmp_path
            ),
            candidates,
            _observation(
                "UNKNOWN"
            ),
        )
    )

    assert result["processed"] is False

    assert (
        result["reason"]
        == "OBSERVATION_NOT_CHANGED"
    )

    assert (
        candidates.snapshot(
            "mercurio"
        )["candidate_count"]
        == 0
    )


def test_auto_update_disabled_blocks_candidate(
    tmp_path,
):
    candidates = _candidates(
        tmp_path
    )

    result = (
        project_auto_twin_candidate_revision(
            _managed(
                tmp_path,
                auto_update=False,
            ),
            candidates,
            _observation(
                "CHANGED",
                auto_update=False,
            ),
        )
    )

    assert result["processed"] is False

    assert (
        result["reason"]
        == "AUTO_UPDATE_DISABLED"
    )

    assert (
        candidates.snapshot(
            "mercurio"
        )["candidate_count"]
        == 0
    )


def test_same_changed_fingerprint_is_deduplicated(
    tmp_path,
):
    managed = _managed(
        tmp_path
    )

    candidates = _candidates(
        tmp_path
    )

    first = (
        project_auto_twin_candidate_revision(
            managed,
            candidates,
            _observation(
                "CHANGED",
                capture_id="capture-2",
            ),
        )
    )

    second = (
        project_auto_twin_candidate_revision(
            managed,
            candidates,
            _observation(
                "CHANGED",
                capture_id="capture-3",
            ),
        )
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["updated"] is True

    assert (
        first["candidate_id"]
        == second["candidate_id"]
    )

    assert (
        candidates.snapshot(
            "mercurio"
        )["candidate_count"]
        == 1
    )
