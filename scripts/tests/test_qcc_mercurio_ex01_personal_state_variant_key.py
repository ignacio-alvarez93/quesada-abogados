from backend.automation.site_architecture.models import (
    SiteArchitectureSnapshot,
    SiteArchitectureSource,
)
from backend.automation.site_recognizers.mercurio import (
    apply_mercurio_functional_fingerprint_capability,
    resolve_mercurio_state_variant_key,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_SITE_CODE,
)


GENERIC_FINGERPRINT = "f" * 64

# The real, already-recorded REAL EX01_PERSONAL generic fingerprint
# (2D-20I), shared by both the 130/TITULAR and 131/FAMILIAR branches
# before this augmentation runs.
REAL_EX01_PERSONAL_GENERIC_FINGERPRINT = (
    "d0af84caa02f93f585f9df7f3e2ef82b487348a"
    "64550e07c54f481e58e84e2f4"
)

EXPECTED_TITULAR_FINGERPRINT = (
    "52efb715d5688ad10cb2945d862847868ce25b4"
    "208f6ca84dcf57aa8a4032311"
)

EXPECTED_FAMILIAR_FINGERPRINT = (
    "88c730539a17c84d7c3ac6fb753c7ba40a748928"
    "9f7d0c950d815f3aa568ae38"
)


def _snapshot(
    *,
    pest_familiar_style=None,
    include_pest_familiar=True,
    extra_elements=(),
):
    element = {
        "id":
            "pestFamiliar",

        "class":
            "r-tabs-tab r-tabs-state-disabled",
    }

    if pest_familiar_style is not None:
        element["style"] = pest_familiar_style

    elements = (
        [element]
        if include_pest_familiar
        else []
    )

    return {
        "elements":
            list(elements)
            + list(extra_elements),
    }


def test_titular_variant_key():
    result = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=_snapshot(
                pest_familiar_style="display: none;",
            ),
        )
    )

    assert result == "NO_FAMILIAR_TAB"


def test_familiar_variant_key():
    result = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=_snapshot(
                pest_familiar_style="",
            ),
        )
    )

    assert result == "FAMILIAR_TAB_AVAILABLE"


def test_branch_codes_alone_do_not_change_the_variant_key():
    # 130-shaped and 131-shaped evidence sharing the SAME observable
    # capability (pestFamiliar hidden) must resolve to the SAME
    # state_variant_key -- the branch code itself is never consulted.
    snapshot_130 = _snapshot(
        pest_familiar_style="display: none;",
        extra_elements=[
            {
                "id":
                    "idOpcionAutorizacion",

                "value":
                    "130",
            },
        ],
    )

    snapshot_131_same_capability = _snapshot(
        pest_familiar_style="display: none;",
        extra_elements=[
            {
                "id":
                    "idOpcionAutorizacion",

                "value":
                    "131",
            },
        ],
    )

    variant_130 = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=snapshot_130,
        )
    )

    variant_131 = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=snapshot_131_same_capability,
        )
    )

    assert variant_130 == variant_131
    assert variant_130 == "NO_FAMILIAR_TAB"


def test_differing_capability_produces_differing_variant_keys():
    titular_variant = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=_snapshot(
                pest_familiar_style="display: none;",
            ),
        )
    )

    familiar_variant = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=_snapshot(
                pest_familiar_style="",
            ),
        )
    )

    assert titular_variant != familiar_variant


def test_non_mercurio_site_is_untouched():
    result = (
        resolve_mercurio_state_variant_key(
            site_code="some_other_site",
            functional_state="EX01_PERSONAL",
            snapshot=_snapshot(
                pest_familiar_style="",
            ),
        )
    )

    assert result is None


def test_non_ex01_personal_state_is_untouched():
    result = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_AUTHORIZATION",
            snapshot=_snapshot(
                pest_familiar_style="",
            ),
        )
    )

    assert result is None


def test_missing_capability_signal_resolves_no_variant():
    # No pestFamiliar element observable at all: fail-open, never guess
    # -- absent/empty must preserve pre-2D-20J behavior (no variant).
    result = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=_snapshot(
                include_pest_familiar=False,
            ),
        )
    )

    assert result is None


def test_expected_current_fingerprints_for_real_ex01_personal_branches():
    # 2D-20I verified these exact values against the real, already
    # -recorded REAL captures (130 -> TITULAR_ONLY, 131 ->
    # FAMILIAR_CAPABLE). This locks the still-refreshable *fingerprint*
    # algorithm; it is intentionally independent of state_variant_key,
    # which instead carries the *stable* identity signal.
    titular_fingerprint = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=(
                REAL_EX01_PERSONAL_GENERIC_FINGERPRINT
            ),
            snapshot=_snapshot(
                pest_familiar_style="display: none;",
            ),
        )
    )

    familiar_fingerprint = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=(
                REAL_EX01_PERSONAL_GENERIC_FINGERPRINT
            ),
            snapshot=_snapshot(
                pest_familiar_style="",
            ),
        )
    )

    assert (
        titular_fingerprint
        == EXPECTED_TITULAR_FINGERPRINT
    )

    assert (
        familiar_fingerprint
        == EXPECTED_FAMILIAR_FINGERPRINT
    )


def test_real_site_architecture_snapshot_dataclass_is_supported():
    # Regression (found and fixed under 2D-20K): ingestor.py's real
    # ingestion path calls these functions with the actual
    # SiteArchitectureSnapshot produced by normalize_dom_capture(), not
    # a plain dict -- both must accept it, not just test fixtures.
    snapshot = (
        SiteArchitectureSnapshot(
            source=(
                SiteArchitectureSource(
                    kind="DOM_CAPTURE",
                    schema_version=1,
                )
            ),
            elements=(
                {
                    "id":
                        "pestFamiliar",

                    "style":
                        "display: none;",
                },
            ),
        )
    )

    variant_key = (
        resolve_mercurio_state_variant_key(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            snapshot=snapshot,
        )
    )

    fingerprint = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=snapshot,
        )
    )

    assert variant_key == "NO_FAMILIAR_TAB"
    assert fingerprint != GENERIC_FINGERPRINT
