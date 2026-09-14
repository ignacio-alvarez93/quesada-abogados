from backend.qcc.auto_twin import (
    AUTO_TWIN_OBSERVATION_CHANGED,
    AUTO_TWIN_OBSERVATION_KNOWN,
    AUTO_TWIN_OBSERVATION_UNKNOWN,
    AutoTwinManagedSite,
    AutoTwinManagedSiteStore,
    AutoTwinObservationStore,
    project_ingested_auto_twin_observation,
)


REAL_ORIGIN = (
    "https://mercurio.delegaciondelgobierno.gob.es"
)

REAL_URL = (
    REAL_ORIGIN
    + "/mercurio/finalizacionSolicitud.html"
)


def _managed_store(
    tmp_path,
):
    store = AutoTwinManagedSiteStore(
        path=(
            tmp_path
            / "managed_sites.json"
        )
    )

    store.register(
        AutoTwinManagedSite(
            twin_key="mercurio",
            site_code="MERCURIO",
            origins=(
                REAL_ORIGIN,
            ),
            path_prefixes=(
                "/mercurio",
            ),
        )
    )

    return store


def _observation_store(
    tmp_path,
):
    return AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )


def _result(
    capture_id,
    fingerprint,
    *,
    url=REAL_URL,
    state=None,
):
    return {
        "capture_id":
            capture_id,

        "received_at":
            "2026-09-05T08:00:00+00:00",

        "site_code":
            "MERCURIO",

        "page": {
            "url":
                url,
        },

        "state_observation": {
            "state":
                state,

            "fingerprint":
                fingerprint,
        },
    }


def test_unbound_profile_is_not_projected(
    tmp_path,
):
    result = (
        project_ingested_auto_twin_observation(
            _managed_store(
                tmp_path
            ),
            _observation_store(
                tmp_path
            ),
            browser_profile_key="",
            ingest_result=_result(
                "capture-1",
                "fp-1",
            ),
        )
    )

    assert result["processed"] is False

    assert (
        result["reason"]
        == "PROFILE_UNBOUND"
    )


def test_unmanaged_url_is_skipped(
    tmp_path,
):
    result = (
        project_ingested_auto_twin_observation(
            _managed_store(
                tmp_path
            ),
            _observation_store(
                tmp_path
            ),
            browser_profile_key=(
                "mercurio_assisted"
            ),
            ingest_result=_result(
                "capture-1",
                "fp-1",
                url="https://example.com/",
            ),
        )
    )

    assert result["processed"] is False

    assert (
        result["reason"]
        == "UNMANAGED_URL"
    )


def test_first_managed_capture_is_unknown(
    tmp_path,
):
    result = (
        project_ingested_auto_twin_observation(
            _managed_store(
                tmp_path
            ),
            _observation_store(
                tmp_path
            ),
            browser_profile_key=(
                "mercurio_assisted"
            ),
            ingest_result=_result(
                "capture-1",
                "fp-1",
            ),
        )
    )

    assert result["processed"] is True

    assert (
        result["twin_key"]
        == "mercurio"
    )

    assert (
        result["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )


def test_second_equal_capture_is_known(
    tmp_path,
):
    managed = _managed_store(
        tmp_path
    )

    observations = (
        _observation_store(
            tmp_path
        )
    )

    project_ingested_auto_twin_observation(
        managed,
        observations,
        browser_profile_key=(
            "mercurio_assisted"
        ),
        ingest_result=_result(
            "capture-1",
            "fp-1",
        ),
    )

    second = (
        project_ingested_auto_twin_observation(
            managed,
            observations,
            browser_profile_key=(
                "mercurio_assisted"
            ),
            ingest_result=_result(
                "capture-2",
                "fp-1",
            ),
        )
    )

    assert (
        second["classification"]
        == AUTO_TWIN_OBSERVATION_KNOWN
    )


def test_changed_capture_preserves_baseline(
    tmp_path,
):
    managed = _managed_store(
        tmp_path
    )

    observations = (
        _observation_store(
            tmp_path
        )
    )

    project_ingested_auto_twin_observation(
        managed,
        observations,
        browser_profile_key=(
            "mercurio_assisted"
        ),
        ingest_result=_result(
            "capture-baseline",
            "fp-baseline",
        ),
    )

    changed = (
        project_ingested_auto_twin_observation(
            managed,
            observations,
            browser_profile_key=(
                "mercurio_assisted"
            ),
            ingest_result=_result(
                "capture-new",
                "fp-new",
            ),
        )
    )

    assert (
        changed["classification"]
        == AUTO_TWIN_OBSERVATION_CHANGED
    )

    assert (
        changed["baseline_fingerprint"]
        == "fp-baseline"
    )

    assert (
        changed["baseline_capture_id"]
        == "capture-baseline"
    )


def test_discovery_profile_uses_same_passive_projection(
    tmp_path,
):
    result = (
        project_ingested_auto_twin_observation(
            _managed_store(
                tmp_path
            ),
            _observation_store(
                tmp_path
            ),
            browser_profile_key=(
                "twin_discovery"
            ),
            ingest_result=_result(
                "capture-1",
                "fp-1",
            ),
        )
    )

    assert result["processed"] is True

    assert (
        result[
            "profile_policy"
        ]["active_discovery"]
        is True
    )

    # Esta proyección concreta sigue siendo pasiva.
    assert (
        result["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )
