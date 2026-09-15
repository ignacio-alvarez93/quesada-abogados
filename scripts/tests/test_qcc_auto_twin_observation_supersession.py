import pytest

from backend.qcc.auto_twin import (
    AutoTwinManagedSite,
    AutoTwinObservationStore,
)
from backend.qcc.auto_twin.automatic_materialization import (
    _all_observed_twins,
)


URL = (
    "https://mercurio.delegaciondelgobierno.gob.es"
    "/mercurio/nuevaSolicitud-EX01.html"
)

OTHER_TWIN_URL = (
    "https://otro-sitio.example.gob.es"
    "/otro/pagina.html"
)


def _twin(
    *,
    twin_key="mercurio",
    origin=(
        "https://mercurio.delegaciondelgobierno.gob.es"
    ),
    path_prefix="/mercurio",
):
    return AutoTwinManagedSite(
        twin_key=twin_key,
        site_code="MERCURIO",
        origins=(
            origin,
        ),
        path_prefixes=(
            path_prefix,
        ),
        discover_unknown_states=True,
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
    state="EX01_PERSONAL",
    state_variant_key=None,
):
    return store.observe(
        twin,
        capture_id=capture_id,
        observed_at=(
            "2026-09-12T06:00:00+00:00"
        ),
        browser_profile_key=(
            "twin_discovery"
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


def _seed_collided_and_replacements(
    store,
    twin,
):
    """Reproduces the real 2D-20I/2D-20J scenario in miniature.

    One legacy collided EX01_PERSONAL observation (no variant), then
    the two capability-aware replacements.
    """

    old = _observe(
        store,
        twin,
        capture_id="20260912_060228_192874_aa602bac",
        fingerprint=(
            "d0af84caa02f93f585f9df7f3e2ef82"
            "b487348a64550e07c54f481e58e84e2f4"
        ),
    )

    titular = _observe(
        store,
        twin,
        capture_id="20260912_060218_754542_25a0d363",
        fingerprint=(
            "52efb715d5688ad10cb2945d862847868"
            "ce25b4208f6ca84dcf57aa8a4032311"
        ),
        state_variant_key="NO_FAMILIAR_TAB",
    )

    familiar = _observe(
        store,
        twin,
        capture_id="20260912_060631_109928_94d6a6ca",
        fingerprint=(
            "88c730539a17c84d7c3ac6fb753c7ba4"
            "0a7489289f7d0c950d815f3aa568ae38"
        ),
        state_variant_key="FAMILIAR_TAB_AVAILABLE",
    )

    return old, titular, familiar


def test_historical_old_projection_remains_readable_after_supersession(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason=(
            "2D-20K: capability-aware"
            " EX01_PERSONAL split"
        ),
        recorded_at=(
            "2026-09-12T12:00:00+00:00"
        ),
        provenance={
            "work_order":
                "2D-20K",
        },
    )

    historical = store.snapshot(
        twin.twin_key,
    )

    assert (
        old["state_key"]
        in historical["twin"]["states"]
    )

    assert (
        historical["twin"]["states"][
            old["state_key"]
        ]["last_fingerprint"]
        == old["fingerprint"]
    )


def test_current_snapshot_excludes_superseded_state_after_success(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason="EX01_PERSONAL capability split",
    )

    current = store.snapshot(
        twin.twin_key,
        current_only=True,
    )

    current_states = current[
        "twin"
    ]["states"]

    assert (
        old["state_key"]
        not in current_states
    )

    assert (
        titular["state_key"]
        in current_states
    )

    assert (
        familiar["state_key"]
        in current_states
    )

    assert len(
        current_states
    ) == 2


def test_failed_replacement_validation_leaves_old_projection_active(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old = _observe(
        store,
        twin,
        capture_id="capture-old",
        fingerprint="fp-collided",
    )

    titular = _observe(
        store,
        twin,
        capture_id="capture-130",
        fingerprint="fp-titular",
        state_variant_key="NO_FAMILIAR_TAB",
    )

    # familiar replacement was never actually observed/validated --
    # e.g. the second half of a partial reprojection failed.
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_SUPERSESSION_REPLACEMENT_UNKNOWN"
        ),
    ):
        store.supersede(
            twin,
            old_state_key=(
                old["state_key"]
            ),
            replacement_state_keys=(
                titular["state_key"],
                "never-observed-familiar-key",
            ),
            reason="partial reprojection",
        )

    current = store.snapshot(
        twin.twin_key,
        current_only=True,
    )

    assert (
        old["state_key"]
        in current["twin"]["states"]
    )


def test_repeated_supersession_is_idempotent(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    first = store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason="EX01_PERSONAL capability split",
    )

    revision_after_first = (
        store.revision
    )

    second = store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason=(
            "EX01_PERSONAL capability"
            " split (re-run)"
        ),
    )

    assert (
        second["replacement_state_keys"]
        == first["replacement_state_keys"]
    )

    # Idempotent: no new write on an identical target.
    assert (
        store.revision
        == revision_after_first
    )


def test_conflicting_supersession_target_is_rejected(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
        ),
        reason="first supersession",
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_SUPERSESSION_IMMUTABLE_CONFLICT"
        ),
    ):
        store.supersede(
            twin,
            old_state_key=(
                old["state_key"]
            ),
            replacement_state_keys=(
                familiar["state_key"],
            ),
            reason="different target",
        )


def test_unrelated_states_and_sites_unaffected_by_supersession(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()
    other_twin = _twin(
        twin_key="otro_sitio",
        origin=(
            "https://otro-sitio.example.gob.es"
        ),
        path_prefix="/otro",
    )

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    unrelated_mercurio_state = _observe(
        store,
        twin,
        capture_id="capture-authorization",
        fingerprint="fp-authorization",
        state="EX01_AUTHORIZATION",
    )

    other_site_state = _observe(
        store,
        other_twin,
        capture_id="capture-other-site",
        fingerprint="fp-other-site",
        state="SOME_OTHER_STATE",
        url=OTHER_TWIN_URL,
    )

    store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason="EX01_PERSONAL capability split",
    )

    current_mercurio = store.snapshot(
        twin.twin_key,
        current_only=True,
    )["twin"]["states"]

    assert (
        unrelated_mercurio_state[
            "state_key"
        ]
        in current_mercurio
    )

    current_other = store.snapshot(
        other_twin.twin_key,
        current_only=True,
    )["twin"]["states"]

    assert (
        other_site_state["state_key"]
        in current_other
    )

    assert (
        len(
            current_other
        )
        == 1
    )


def test_causal_refresh_within_new_variant_preserves_state_identity_after_supersession(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason="EX01_PERSONAL capability split",
    )

    refreshed_familiar = _observe(
        store,
        twin,
        capture_id="capture-familiar-refresh",
        fingerprint="fp-familiar-refreshed",
        state_variant_key="FAMILIAR_TAB_AVAILABLE",
    )

    assert (
        refreshed_familiar["state_key"]
        == familiar["state_key"]
    )

    current = store.snapshot(
        twin.twin_key,
        current_only=True,
    )["twin"]["states"]

    assert (
        current[
            familiar["state_key"]
        ]["last_fingerprint"]
        == "fp-familiar-refreshed"
    )

    assert len(
        current
    ) == 2


def test_materializer_sees_exactly_the_two_new_variants(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason="EX01_PERSONAL capability split",
    )

    twins = _all_observed_twins(
        store
    )

    states = twins[
        twin.twin_key
    ]["states"]

    assert (
        old["state_key"]
        not in states
    )

    assert set(
        states.keys()
    ) >= {
        titular["state_key"],
        familiar["state_key"],
    }

    ex01_personal_states = [
        state
        for state in states.values()
        if (
            state.get(
                "functional_state"
            )
            == "EX01_PERSONAL"
        )
    ]

    assert (
        len(
            ex01_personal_states
        )
        == 2
    )


# WO 2D-20S: governed corroboration enrichment on an EXISTING
# supersession record (AutoTwinObservationStore.
# enrich_supersession_provenance()).


def _superseded_store(tmp_path):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    store.supersede(
        twin,
        old_state_key=(
            old["state_key"]
        ),
        replacement_state_keys=(
            titular["state_key"],
            familiar["state_key"],
        ),
        reason="EX01_PERSONAL capability split",
        recorded_at=(
            "2026-09-12T12:00:00+00:00"
        ),
        provenance={
            "work_order":
                "2D-20K",
        },
    )

    return store, twin, old, titular, familiar


def test_enrich_adds_corroboration_to_existing_supersession(
    tmp_path,
):
    store, twin, old, titular, familiar = (
        _superseded_store(tmp_path)
    )

    record = store.enrich_supersession_provenance(
        twin,
        old_state_key=old["state_key"],
        replacement_navigation_context_signatures={
            titular["state_key"]: {
                "context_signature": "sig-titular",
                "fingerprint": titular["fingerprint"],
            },
            familiar["state_key"]: {
                "context_signature": "sig-familiar",
                "fingerprint": familiar["fingerprint"],
            },
        },
    )

    corroboration = record["provenance"][
        "replacement_navigation_context_signatures"
    ]

    assert corroboration == {
        titular["state_key"]: {
            "context_signature": "sig-titular",
            "fingerprint": titular["fingerprint"],
        },
        familiar["state_key"]: {
            "context_signature": "sig-familiar",
            "fingerprint": familiar["fingerprint"],
        },
    }

    # Pre-existing provenance from 2D-20K survives untouched.
    assert record["provenance"]["work_order"] == "2D-20K"


def test_enrich_preserves_core_supersession_fields(
    tmp_path,
):
    store, twin, old, titular, familiar = (
        _superseded_store(tmp_path)
    )

    before = store.snapshot(
        twin.twin_key,
    )["twin"]["supersessions"][
        old["state_key"]
    ]

    record = store.enrich_supersession_provenance(
        twin,
        old_state_key=old["state_key"],
        replacement_navigation_context_signatures={
            titular["state_key"]: {
                "context_signature": "sig-titular",
                "fingerprint": titular["fingerprint"],
            },
        },
    )

    assert (
        record["old_state_key"]
        == before["old_state_key"]
    )

    assert (
        record["replacement_state_keys"]
        == before["replacement_state_keys"]
    )

    assert record["reason"] == before["reason"]
    assert (
        record["recorded_at"]
        == before["recorded_at"]
    )


def test_enrich_is_idempotent_on_repeat(
    tmp_path,
):
    store, twin, old, titular, familiar = (
        _superseded_store(tmp_path)
    )

    mapping = {
        titular["state_key"]: {
            "context_signature": "sig-titular",
            "fingerprint": titular["fingerprint"],
        },
        familiar["state_key"]: {
            "context_signature": "sig-familiar",
            "fingerprint": familiar["fingerprint"],
        },
    }

    store.enrich_supersession_provenance(
        twin,
        old_state_key=old["state_key"],
        replacement_navigation_context_signatures=mapping,
    )

    revision_after_first = store.revision

    second = store.enrich_supersession_provenance(
        twin,
        old_state_key=old["state_key"],
        replacement_navigation_context_signatures=mapping,
    )

    assert store.revision == revision_after_first

    assert (
        second["provenance"][
            "replacement_navigation_context_signatures"
        ]
        == mapping
    )


def test_enrich_rejects_conflicting_corroboration(
    tmp_path,
):
    store, twin, old, titular, familiar = (
        _superseded_store(tmp_path)
    )

    store.enrich_supersession_provenance(
        twin,
        old_state_key=old["state_key"],
        replacement_navigation_context_signatures={
            titular["state_key"]: {
                "context_signature": "sig-titular",
                "fingerprint": titular["fingerprint"],
            },
        },
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_"
            "CORROBORATION_CONFLICT"
        ),
    ):
        store.enrich_supersession_provenance(
            twin,
            old_state_key=old["state_key"],
            replacement_navigation_context_signatures={
                titular["state_key"]: {
                    "context_signature": "sig-titular-DIFFERENT",
                    "fingerprint": titular["fingerprint"],
                },
            },
        )


def test_enrich_rejects_replacement_outside_declared_set(
    tmp_path,
):
    store, twin, old, titular, familiar = (
        _superseded_store(tmp_path)
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_"
            "CORROBORATION_REPLACEMENT_UNKNOWN"
        ),
    ):
        store.enrich_supersession_provenance(
            twin,
            old_state_key=old["state_key"],
            replacement_navigation_context_signatures={
                "never-declared-replacement-key": {
                    "context_signature": "sig-x",
                    "fingerprint": "fp-x",
                },
            },
        )


def test_enrich_requires_an_existing_supersession(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    old, titular, familiar = (
        _seed_collided_and_replacements(
            store,
            twin,
        )
    )

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_SUPERSESSION_NOT_FOUND",
    ):
        store.enrich_supersession_provenance(
            twin,
            old_state_key=old["state_key"],
            replacement_navigation_context_signatures={
                titular["state_key"]: {
                    "context_signature": "sig-titular",
                    "fingerprint": titular["fingerprint"],
                },
            },
        )


def test_enrich_does_not_touch_unrelated_twin_or_states(
    tmp_path,
):
    store, twin, old, titular, familiar = (
        _superseded_store(tmp_path)
    )

    other_twin = _twin(
        twin_key="otro_sitio",
        origin=(
            "https://otro-sitio.example.gob.es"
        ),
        path_prefix="/otro",
    )

    other_site_state = _observe(
        store,
        other_twin,
        capture_id="capture-other-site",
        fingerprint="fp-other-site",
        state="SOME_OTHER_STATE",
        url=OTHER_TWIN_URL,
    )

    store.enrich_supersession_provenance(
        twin,
        old_state_key=old["state_key"],
        replacement_navigation_context_signatures={
            titular["state_key"]: {
                "context_signature": "sig-titular",
                "fingerprint": titular["fingerprint"],
            },
        },
    )

    current_other = store.snapshot(
        other_twin.twin_key,
        current_only=True,
    )["twin"]["states"]

    assert (
        other_site_state["state_key"]
        in current_other
    )

    current_mercurio = store.snapshot(
        twin.twin_key,
        current_only=True,
    )["twin"]["states"]

    assert (
        titular["state_key"]
        in current_mercurio
    )

    assert (
        familiar["state_key"]
        in current_mercurio
    )

    # Historical old state is still fully readable, unmodified.
    historical = store.snapshot(
        twin.twin_key,
    )["twin"]["states"][old["state_key"]]

    assert (
        historical["last_fingerprint"]
        == old["fingerprint"]
    )
