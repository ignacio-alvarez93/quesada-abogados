from backend.qcc.auto_twin import (
    AUTO_TWIN_OBSERVATION_CHANGED,
    AUTO_TWIN_OBSERVATION_KNOWN,
    AUTO_TWIN_OBSERVATION_UNKNOWN,
    AutoTwinManagedSite,
    AutoTwinObservationStore,
)
from backend.qcc.auto_twin import (
    observation_store as observation_store_module,
)


URL = (
    "https://mercurio.delegaciondelgobierno.gob.es"
    "/mercurio/finalizacionSolicitud.html"
)


def _twin(
    *,
    discover_unknown_states=True,
):
    return AutoTwinManagedSite(
        twin_key="mercurio",
        site_code="MERCURIO",
        origins=(
            "https://mercurio.delegaciondelgobierno.gob.es",
        ),
        path_prefixes=(
            "/mercurio",
        ),
        discover_unknown_states=(
            discover_unknown_states
        ),
    )


def _state(
    fingerprint,
    *,
    state=None,
    state_variant_key=None,
):
    return {
        "state":
            state,

        "fingerprint":
            fingerprint,

        "state_variant_key":
            state_variant_key,
    }


def _observe(
    store,
    twin,
    *,
    capture_id,
    fingerprint,
    url=URL,
    state=None,
    state_variant_key=None,
):
    return store.observe(
        twin,
        capture_id=capture_id,
        observed_at=(
            "2026-09-05T08:00:00+00:00"
        ),
        browser_profile_key=(
            "mercurio_assisted"
        ),
        url=url,
        site_code="MERCURIO",
        state_observation=_state(
            fingerprint,
            state=state,
            state_variant_key=(
                state_variant_key
            ),
        ),
    )


def test_first_state_is_unknown_and_becomes_baseline(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    result = _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
    )

    assert (
        result["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )

    assert result[
        "state_registered"
    ] is True

    assert (
        result["baseline_fingerprint"]
        == "fp-1"
    )

    assert (
        result["baseline_capture_id"]
        == "capture-1"
    )


def test_same_state_and_fingerprint_becomes_known(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-1",
    )

    result = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-1",
    )

    assert (
        result["classification"]
        == AUTO_TWIN_OBSERVATION_KNOWN
    )

    assert (
        result["baseline_capture_id"]
        == "capture-1"
    )


def test_changed_fingerprint_does_not_replace_baseline(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-baseline",
    )

    changed = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-changed",
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
        == "capture-1"
    )

    assert (
        changed["fingerprint"]
        == "fp-changed"
    )


def test_new_path_is_unknown_state(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-1",
    )

    result = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-2",
        url=(
            "https://mercurio.delegaciondelgobierno.gob.es"
            "/mercurio/datosSolicitud.html"
        ),
    )

    assert (
        result["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )


def test_functional_state_participates_in_identity(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    first = _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-a",
        state="STATE_A",
    )

    second = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-b",
        state="STATE_B",
    )

    assert (
        first["state_key"]
        != second["state_key"]
    )

    assert (
        second["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )


def test_unknown_discovery_can_be_disabled(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin(
        discover_unknown_states=False
    )

    first = _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-1",
    )

    second = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-1",
    )

    assert (
        first["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )

    assert (
        second["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )

    assert (
        first["state_registered"]
        is False
    )

    assert (
        second["state_registered"]
        is False
    )


def test_observation_state_survives_restart(
    tmp_path,
):
    path = (
        tmp_path
        / "observation_state.json"
    )

    first = AutoTwinObservationStore(
        path=path
    )

    twin = _twin()

    _observe(
        first,
        twin,
        capture_id="capture-1",
        fingerprint="fp-1",
    )

    second = AutoTwinObservationStore(
        path=path
    )

    result = _observe(
        second,
        twin,
        capture_id="capture-2",
        fingerprint="fp-1",
    )

    assert (
        result["classification"]
        == AUTO_TWIN_OBSERVATION_KNOWN
    )

    assert (
        result["baseline_capture_id"]
        == "capture-1"
    )


def test_observation_store_is_lightweight(
    tmp_path,
):
    path = (
        tmp_path
        / "observation_state.json"
    )

    store = AutoTwinObservationStore(
        path=path
    )

    _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
    )

    text = path.read_text(
        encoding="utf-8"
    )

    assert "capture-1" in text
    assert "fp-1" in text

    for forbidden in (
        "outerHTML",
        "qcc_capture",
        "page.mhtml",
        "screenshot_viewport",
    ):
        assert forbidden not in text


def test_out_of_scope_url_is_rejected(
    tmp_path,
):
    import pytest

    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_URL_OUT_OF_SCOPE",
    ):
        _observe(
            store,
            _twin(),
            capture_id="capture-1",
            fingerprint="fp-1",
            url="https://example.com/",
        )


# --- WO 2D-20J: optional state_variant_key identity extension -------


def test_absent_state_variant_key_preserves_legacy_state_key(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    result = _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
    )

    legacy_identity = {
        "pathname":
            "/mercurio/finalizacionSolicitud.html",

        "functional_state":
            "EX01_PERSONAL",
    }

    expected_state_key = (
        observation_store_module
        ._state_key(
            legacy_identity
        )
    )

    assert (
        result["state_key"]
        == expected_state_key
    )

    assert (
        result["state_variant_key"]
        is None
    )


def test_same_variant_with_differing_branch_context_shares_state_key(
    tmp_path,
):
    # Mirrors the real 130 (TITULAR) vs 131 (FAMILIAR) situation: two
    # observations sharing the same observable capability variant must
    # collide on the same state_key even though nothing else about the
    # caller-supplied branch/context differs.
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    first = _observe(
        store,
        twin,
        capture_id="capture-130",
        fingerprint="fp-130",
        state="EX01_PERSONAL",
        state_variant_key="NO_FAMILIAR_TAB",
    )

    second = _observe(
        store,
        twin,
        capture_id="capture-131-same-capability",
        fingerprint="fp-130",
        state="EX01_PERSONAL",
        state_variant_key="NO_FAMILIAR_TAB",
    )

    assert (
        first["state_key"]
        == second["state_key"]
    )

    assert (
        second["classification"]
        == AUTO_TWIN_OBSERVATION_KNOWN
    )


def test_differing_capability_variant_produces_differing_state_keys(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    titular = _observe(
        store,
        twin,
        capture_id="capture-130",
        fingerprint="fp-shared",
        state="EX01_PERSONAL",
        state_variant_key="NO_FAMILIAR_TAB",
    )

    familiar = _observe(
        store,
        twin,
        capture_id="capture-131",
        fingerprint="fp-shared",
        state="EX01_PERSONAL",
        state_variant_key="FAMILIAR_TAB_AVAILABLE",
    )

    assert (
        titular["state_key"]
        != familiar["state_key"]
    )

    # Both are first-seen under their own distinct identity.
    assert (
        titular["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )

    assert (
        familiar["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )


def test_fingerprint_refresh_within_variant_preserves_state_identity(
    tmp_path,
):
    # Causal-refresh semantics: the fingerprint may change freely
    # inside a variant without moving state_key/state_id.
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    baseline = _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-familiar-old",
        state="EX01_PERSONAL",
        state_variant_key="FAMILIAR_TAB_AVAILABLE",
    )

    refreshed = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-familiar-new",
        state="EX01_PERSONAL",
        state_variant_key="FAMILIAR_TAB_AVAILABLE",
    )

    assert (
        refreshed["state_key"]
        == baseline["state_key"]
    )

    assert (
        refreshed["classification"]
        == AUTO_TWIN_OBSERVATION_CHANGED
    )

    assert (
        refreshed["baseline_fingerprint"]
        == "fp-familiar-old"
    )

    assert (
        refreshed["fingerprint"]
        == "fp-familiar-new"
    )


def test_variant_key_has_no_impact_on_unrelated_states(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    variant_result = _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        state_variant_key="NO_FAMILIAR_TAB",
    )

    plain_result = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-2",
        state="EX01_AUTHORIZATION",
    )

    assert (
        variant_result["state_key"]
        != plain_result["state_key"]
    )

    legacy_identity = {
        "pathname":
            "/mercurio/finalizacionSolicitud.html",

        "functional_state":
            "EX01_AUTHORIZATION",
    }

    expected_plain_state_key = (
        observation_store_module
        ._state_key(
            legacy_identity
        )
    )

    assert (
        plain_result["state_key"]
        == expected_plain_state_key
    )

    assert (
        plain_result["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )
