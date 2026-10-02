import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_OBSERVATION_KNOWN,
    AUTO_TWIN_OBSERVATION_UNKNOWN,
    AutoTwinManagedSite,
    AutoTwinObservationStore,
)
from backend.qcc.auto_twin import (
    observation_store as observation_store_module,
)

from backend.qcc.universal_web.branch_context import (
    build_branch_context,
)
from backend.qcc.universal_web.branch_discriminators import (
    build_branch_discriminator,
)


URL = (
    "https://mercurio.delegaciondelgobierno.gob.es"
    "/mercurio/finalizacionSolicitud.html"
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
        discover_unknown_states=True,
    )


def _state_observation(
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
    state=None,
    state_variant_key=None,
    branch_context=None,
    url=URL,
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
        state_observation=_state_observation(
            fingerprint,
            state=state,
            state_variant_key=(
                state_variant_key
            ),
        ),
        branch_context=branch_context,
    )


def _radio_context(
    control_id,
    active_value,
):
    return build_branch_context([
        build_branch_discriminator(
            kind="RADIO",
            control_id=control_id,
            active_value=active_value,
        ),
    ])


def _legacy_state_key(
    *,
    pathname,
    functional_state,
):
    return (
        observation_store_module
        ._state_key(
            {
                "pathname":
                    pathname,

                "functional_state":
                    functional_state,
            }
        )
    )


# --- 1/2: None/empty BranchContext preserve legacy state_key --------


def test_none_branch_context_preserves_legacy_state_key(
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
        branch_context=None,
    )

    expected = _legacy_state_key(
        pathname=(
            "/mercurio/finalizacionSolicitud.html"
        ),
        functional_state=(
            "EX01_PERSONAL"
        ),
    )

    assert (
        result["state_key"]
        == expected
    )

    assert (
        "branch_context_id"
        not in result
    )


def test_empty_branch_context_preserves_legacy_state_key(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    empty_context = build_branch_context(
        []
    )

    result = _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        branch_context=empty_context,
    )

    expected = _legacy_state_key(
        pathname=(
            "/mercurio/finalizacionSolicitud.html"
        ),
        functional_state=(
            "EX01_PERSONAL"
        ),
    )

    assert (
        result["state_key"]
        == expected
    )

    assert (
        "branch_context_id"
        not in result
    )


# --- 3: non-empty BranchContext changes state_key deterministically -


def test_non_empty_branch_context_changes_state_key(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    context = _radio_context(
        "modalidad",
        "TITULAR",
    )

    result = _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        branch_context=context,
    )

    legacy = _legacy_state_key(
        pathname=(
            "/mercurio/finalizacionSolicitud.html"
        ),
        functional_state=(
            "EX01_PERSONAL"
        ),
    )

    assert (
        result["state_key"]
        != legacy
    )

    assert (
        result["branch_context_id"]
        == context.context_id
    )


# --- 4: discriminator order independence ----------------------------


def test_same_context_different_discriminator_order_same_state_key(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    context_one = build_branch_context([
        build_branch_discriminator(
            kind="RADIO",
            control_id="modalidad",
            active_value="TITULAR",
        ),
        build_branch_discriminator(
            kind="CHECKBOX",
            control_id="acepto",
            active_value="CHECKED",
        ),
    ])

    context_two = build_branch_context([
        build_branch_discriminator(
            kind="CHECKBOX",
            control_id="acepto",
            active_value="CHECKED",
        ),
        build_branch_discriminator(
            kind="RADIO",
            control_id="modalidad",
            active_value="TITULAR",
        ),
    ])

    assert (
        context_one.context_id
        == context_two.context_id
    )

    first = _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        branch_context=context_one,
    )

    second = _observe(
        store,
        _twin(),
        capture_id="capture-2",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        branch_context=context_two,
    )

    assert (
        first["state_key"]
        == second["state_key"]
    )

    assert (
        second["classification"]
        == AUTO_TWIN_OBSERVATION_KNOWN
    )


# --- 5/6: different vs same branch contexts -------------------------


def test_different_branch_contexts_give_different_state_keys(
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
        branch_context=(
            _radio_context(
                "modalidad",
                "TITULAR",
            )
        ),
    )

    familiar = _observe(
        store,
        twin,
        capture_id="capture-131",
        fingerprint="fp-shared",
        state="EX01_PERSONAL",
        branch_context=(
            _radio_context(
                "modalidad",
                "FAMILIAR",
            )
        ),
    )

    assert (
        titular["state_key"]
        != familiar["state_key"]
    )

    assert (
        titular["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )

    assert (
        familiar["classification"]
        == AUTO_TWIN_OBSERVATION_UNKNOWN
    )


def test_same_branch_context_gives_same_state_key(
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
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        branch_context=(
            _radio_context(
                "modalidad",
                "TITULAR",
            )
        ),
    )

    second = _observe(
        store,
        twin,
        capture_id="capture-2",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        branch_context=(
            _radio_context(
                "modalidad",
                "TITULAR",
            )
        ),
    )

    assert (
        first["state_key"]
        == second["state_key"]
    )

    assert (
        second["classification"]
        == AUTO_TWIN_OBSERVATION_KNOWN
    )


# --- 7/8: state_variant_key compatibility -----------------------------


def test_state_variant_key_still_participates_exactly_as_before(
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

    assert (
        "branch_context_id"
        not in titular
    )

    assert (
        "branch_context_id"
        not in familiar
    )


def test_state_variant_key_and_branch_context_id_coexist(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    context = _radio_context(
        "modalidad",
        "TITULAR",
    )

    plain_variant = _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        state_variant_key="NO_FAMILIAR_TAB",
    )

    variant_plus_branch = _observe(
        store,
        _twin(),
        capture_id="capture-2",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        state_variant_key="NO_FAMILIAR_TAB",
        branch_context=context,
    )

    assert (
        plain_variant["state_key"]
        != variant_plus_branch["state_key"]
    )

    assert (
        variant_plus_branch[
            "state_variant_key"
        ]
        == "NO_FAMILIAR_TAB"
    )

    assert (
        variant_plus_branch[
            "branch_context_id"
        ]
        == context.context_id
    )


# --- 9: invalid branch_context type fails closed ---------------------


def test_invalid_branch_context_type_fails_closed(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    with pytest.raises(
        TypeError,
    ):
        _observe(
            store,
            _twin(),
            capture_id="capture-1",
            fingerprint="fp-1",
            state="EX01_PERSONAL",
            branch_context="TITULAR",
        )


# --- 10: raw control value alone never creates branch scope ----------


def test_raw_control_value_alone_does_not_create_branch_scope(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    state_observation = _state_observation(
        "fp-1",
        state="EX01_PERSONAL",
    )

    # A raw, caller-supplied control value sitting unused inside the
    # state_observation payload must never be interpreted as branch
    # scope by itself -- only an explicit, already-governed
    # BranchContext argument may ever contribute a context_id.
    state_observation["selected_radio"] = "TITULAR"

    result = store.observe(
        _twin(),
        capture_id="capture-1",
        observed_at=(
            "2026-09-05T08:00:00+00:00"
        ),
        browser_profile_key=(
            "mercurio_assisted"
        ),
        url=URL,
        site_code="MERCURIO",
        state_observation=state_observation,
    )

    expected = _legacy_state_key(
        pathname=(
            "/mercurio/finalizacionSolicitud.html"
        ),
        functional_state=(
            "EX01_PERSONAL"
        ),
    )

    assert (
        result["state_key"]
        == expected
    )

    assert (
        "branch_context_id"
        not in result
    )


# --- 11/12: persisted shape -------------------------------------------


def test_persisted_observation_exposes_branch_context_id_only_when_scoped(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    twin = _twin()

    context = _radio_context(
        "modalidad",
        "TITULAR",
    )

    _observe(
        store,
        twin,
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
        branch_context=context,
    )

    snapshot = store.snapshot(
        "mercurio"
    )

    states = snapshot["twin"][
        "states"
    ]

    assert len(
        states
    ) == 1

    persisted_state = next(
        iter(
            states.values()
        )
    )

    assert (
        persisted_state[
            "branch_context_id"
        ]
        == context.context_id
    )

    last_observation = snapshot[
        "twin"
    ][
        "last_observation"
    ]

    assert (
        last_observation[
            "branch_context_id"
        ]
        == context.context_id
    )


def test_legacy_persisted_observation_shape_remains_valid(
    tmp_path,
):
    store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        )
    )

    _observe(
        store,
        _twin(),
        capture_id="capture-1",
        fingerprint="fp-1",
        state="EX01_PERSONAL",
    )

    snapshot = store.snapshot(
        "mercurio"
    )

    states = snapshot["twin"][
        "states"
    ]

    persisted_state = next(
        iter(
            states.values()
        )
    )

    assert (
        "branch_context_id"
        not in persisted_state
    )

    last_observation = snapshot[
        "twin"
    ][
        "last_observation"
    ]

    assert (
        "branch_context_id"
        not in last_observation
    )
