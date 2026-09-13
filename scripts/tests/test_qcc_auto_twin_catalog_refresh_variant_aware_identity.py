"""WO 2D-20W: variant-aware catalog-refresh CURRENT identity.

Covers _current_state_metadata() and _matches_state_discriminator() in
backend/qcc/auto_twin/catalog_refresh.py.

These fixtures are synthetic/provider-neutral -- they never hardcode
Mercurio/EX01/TITULAR/FAMILIAR/specific fingerprints, and never derive
identity from a raw branch code or navigation_context.
"""

import json

import pytest

from backend.qcc.auto_twin.catalog_refresh import (
    _current_state_metadata,
)


PATHNAME = "/some/family/route.html"
FUNCTIONAL_STATE = "SOME_FAMILY_STATE"

FP_A = "a" * 64
FP_B = "b" * 64


def _build_revision(tmp_path, states):
    """``states``: list of dicts with state_id, fingerprint, pathname,
    functional_state, and optionally state_variant_key/extra fields
    (e.g. a branch_code, to prove it is never a usable discriminator).
    """

    revision = tmp_path / "matrev-test"

    registry_states = []

    for index, spec in enumerate(states, start=1):
        state_id = spec["state_id"]

        runtime = (
            revision
            / "states"
            / f"{index:02d}-{state_id}"
            / "runtime"
        )
        runtime.mkdir(parents=True)

        state_json = {
            "state_id": state_id,
            "pathname": spec["pathname"],
            "functional_state": spec["functional_state"],
            "fingerprint": spec.get("fingerprint"),
        }

        if "state_variant_key" in spec:
            state_json["state_variant_key"] = spec["state_variant_key"]

        if "branch_code" in spec:
            state_json["branch_code"] = spec["branch_code"]

        (runtime / "state.json").write_text(
            json.dumps(state_json),
            encoding="utf-8",
        )

        registry_states.append({
            **state_json,
            "runtime_entry": (
                f"states/{index:02d}-{state_id}/runtime/index.html"
            ),
        })

    registry_dir = revision / "runtime"
    registry_dir.mkdir(parents=True)

    (registry_dir / "registry.json").write_text(
        json.dumps({"states": registry_states}),
        encoding="utf-8",
    )

    return revision


def _resolve(revision, **kwargs):
    return _current_state_metadata(
        revision_dir=revision,
        pathname=PATHNAME,
        functional_state=FUNCTIONAL_STATE,
        **kwargs,
    )


# ---------------------------------------------------------------
# Legacy single-state family: byte-compatible, discriminators never
# even consulted.
# ---------------------------------------------------------------


def test_legacy_single_state_lookup_unchanged(tmp_path):
    revision = _build_revision(
        tmp_path,
        [
            {
                "state_id": "STATE_ONLY",
                "fingerprint": FP_A,
                "pathname": PATHNAME,
                "functional_state": FUNCTIONAL_STATE,
            },
        ],
    )

    result = _resolve(revision)

    assert result["state_id"] == "STATE_ONLY"
    assert result["fingerprint"] == FP_A


def test_unrelated_single_state_family_unaffected(tmp_path):
    """A completely different, unrelated provider/site family with a
    single CURRENT state behaves exactly as before -- no discriminator
    logic engages at all."""

    revision = _build_revision(
        tmp_path,
        [
            {
                "state_id": "OTHER_PROVIDER_STATE",
                "fingerprint": FP_B,
                "pathname": "/unrelated/other-provider.html",
                "functional_state": "OTHER_FAMILY_STATE",
            },
        ],
    )

    result = _current_state_metadata(
        revision_dir=revision,
        pathname="/unrelated/other-provider.html",
        functional_state="OTHER_FAMILY_STATE",
    )

    assert result["state_id"] == "OTHER_PROVIDER_STATE"


# ---------------------------------------------------------------
# Governed 1->N family: multiple CURRENT variants coexist; resolution
# requires an exact discriminator.
# ---------------------------------------------------------------


def _two_variant_states():
    return [
        {
            "state_id": "VARIANT_A",
            "fingerprint": FP_A,
            "pathname": PATHNAME,
            "functional_state": FUNCTIONAL_STATE,
            "state_variant_key": "VARIANT_A_KEY",
            "branch_code": "130",
        },
        {
            "state_id": "VARIANT_B",
            "fingerprint": FP_B,
            "pathname": PATHNAME,
            "functional_state": FUNCTIONAL_STATE,
            "state_variant_key": "VARIANT_B_KEY",
            "branch_code": "131",
        },
    ]


def test_two_current_variants_coexist_without_global_ambiguity(tmp_path):
    """Their mere coexistence in the registry is never itself an
    error -- only an unresolved lookup is."""

    revision = _build_revision(tmp_path, _two_variant_states())

    result = _resolve(revision, fingerprint=FP_A)

    assert result["state_id"] == "VARIANT_A"


def test_exact_state_variant_key_resolves_exactly_one(tmp_path):
    revision = _build_revision(tmp_path, _two_variant_states())

    result = _resolve(
        revision,
        state_variant_key="VARIANT_B_KEY",
    )

    assert result["state_id"] == "VARIANT_B"


def test_exact_state_id_resolves_exactly_one(tmp_path):
    revision = _build_revision(tmp_path, _two_variant_states())

    result = _resolve(revision, state_id="VARIANT_A")

    assert result["state_id"] == "VARIANT_A"


def test_exact_fingerprint_resolves_only_matching_variant(tmp_path):
    revision = _build_revision(tmp_path, _two_variant_states())

    result_a = _resolve(revision, fingerprint=FP_A)
    result_b = _resolve(revision, fingerprint=FP_B)

    assert result_a["state_id"] == "VARIANT_A"
    assert result_b["state_id"] == "VARIANT_B"
    assert result_a["state_id"] != result_b["state_id"]


def test_fingerprint_discriminator_is_case_insensitive_hex(tmp_path):
    revision = _build_revision(tmp_path, _two_variant_states())

    result = _resolve(revision, fingerprint=FP_A.upper())

    assert result["state_id"] == "VARIANT_A"


def test_missing_discriminator_with_multiple_variants_fails_closed(
    tmp_path,
):
    revision = _build_revision(tmp_path, _two_variant_states())

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS",
    ):
        _resolve(revision)


def test_unknown_discriminator_fails_closed(tmp_path):
    revision = _build_revision(tmp_path, _two_variant_states())

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS",
    ):
        _resolve(revision, state_id="NEVER_REGISTERED_STATE_ID")

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS",
    ):
        _resolve(revision, fingerprint="c" * 64)


def test_branch_code_alone_cannot_select_a_variant(tmp_path):
    """branch_code is present on both variants' persisted evidence but
    _current_state_metadata() has no parameter for it at all -- it can
    never be used to disambiguate, regardless of its value."""

    revision = _build_revision(tmp_path, _two_variant_states())

    with pytest.raises(TypeError):
        _current_state_metadata(
            revision_dir=revision,
            pathname=PATHNAME,
            functional_state=FUNCTIONAL_STATE,
            branch_code="130",
        )

    # Without a governed discriminator, ambiguity is not resolved by
    # the mere presence of distinguishing branch data on disk.
    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS",
    ):
        _resolve(revision)


def test_duplicate_same_variant_identity_remains_an_error(tmp_path):
    """Two registry entries sharing the SAME state_id (a data
    corruption / governance violation) must never be silently
    resolved by picking one -- even when a discriminator matches
    both."""

    states = [
        {
            "state_id": "DUPLICATE_ID",
            "fingerprint": FP_A,
            "pathname": PATHNAME,
            "functional_state": FUNCTIONAL_STATE,
        },
        {
            "state_id": "DUPLICATE_ID",
            "fingerprint": FP_B,
            "pathname": PATHNAME,
            "functional_state": FUNCTIONAL_STATE,
        },
    ]

    revision = _build_revision(tmp_path, states)

    with pytest.raises(
        ValueError,
        match="QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS",
    ):
        _resolve(revision, state_id="DUPLICATE_ID")
