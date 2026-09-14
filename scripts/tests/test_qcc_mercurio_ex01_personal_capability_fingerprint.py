from backend.automation.site_recognizers.mercurio import (
    apply_mercurio_functional_fingerprint_capability,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_SITE_CODE,
)


GENERIC_FINGERPRINT = "f" * 64


def _snapshot(
    *,
    pest_familiar_style=None,
    include_pest_familiar=True,
):
    element = {
        "id":
            "pestFamiliar",

        "class":
            "r-tabs-tab r-tabs-state-disabled",
    }

    if pest_familiar_style is not None:
        element["style"] = pest_familiar_style

    return {
        "elements": (
            [element]
            if include_pest_familiar
            else []
        ),
    }


def test_titular_and_familiar_variants_get_distinct_fingerprints():
    titular_snapshot = _snapshot(
        pest_familiar_style="display: none;",
    )

    familiar_snapshot = _snapshot(
        pest_familiar_style="",
    )

    titular_fingerprint = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=titular_snapshot,
        )
    )

    familiar_fingerprint = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=familiar_snapshot,
        )
    )

    assert titular_fingerprint != familiar_fingerprint
    assert titular_fingerprint != GENERIC_FINGERPRINT
    assert familiar_fingerprint != GENERIC_FINGERPRINT
    assert len(titular_fingerprint) == 64
    assert len(familiar_fingerprint) == 64


def test_same_capability_state_is_deterministic():
    first = apply_mercurio_functional_fingerprint_capability(
        site_code=MERCURIO_SITE_CODE,
        functional_state="EX01_PERSONAL",
        fingerprint=GENERIC_FINGERPRINT,
        snapshot=_snapshot(
            pest_familiar_style="",
        ),
    )

    second = apply_mercurio_functional_fingerprint_capability(
        site_code=MERCURIO_SITE_CODE,
        functional_state="EX01_PERSONAL",
        fingerprint=GENERIC_FINGERPRINT,
        snapshot=_snapshot(
            pest_familiar_style="",
        ),
    )

    assert first == second


def test_non_mercurio_site_is_untouched():
    result = (
        apply_mercurio_functional_fingerprint_capability(
            site_code="some_other_site",
            functional_state="EX01_PERSONAL",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=_snapshot(
                pest_familiar_style="",
            ),
        )
    )

    assert result == GENERIC_FINGERPRINT


def test_non_ex01_personal_state_is_untouched():
    result = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_AUTHORIZATION",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=_snapshot(
                pest_familiar_style="",
            ),
        )
    )

    assert result == GENERIC_FINGERPRINT


def test_missing_capability_signal_leaves_fingerprint_unchanged():
    # No pestFamiliar element observable at all: fail-open, never guess.
    result = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=_snapshot(
                include_pest_familiar=False,
            ),
        )
    )

    assert result == GENERIC_FINGERPRINT


def test_branch_codes_alone_do_not_create_a_new_physical_state():
    # Two snapshots differing ONLY in branch-code-like fields (not the
    # observable pestFamiliar capability itself) must not be
    # distinguished by this function -- it never even looks at them.
    snapshot_130 = {
        "elements": [
            {
                "id":
                    "pestFamiliar",

                "style":
                    "display: none;",
            },
            {
                "id":
                    "idOpcionAutorizacion",

                "value":
                    "130",
            },
        ],
    }

    snapshot_131_same_capability = {
        "elements": [
            {
                "id":
                    "pestFamiliar",

                "style":
                    "display: none;",
            },
            {
                "id":
                    "idOpcionAutorizacion",

                "value":
                    "131",
            },
        ],
    }

    result_130 = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=snapshot_130,
        )
    )

    result_131 = (
        apply_mercurio_functional_fingerprint_capability(
            site_code=MERCURIO_SITE_CODE,
            functional_state="EX01_PERSONAL",
            fingerprint=GENERIC_FINGERPRINT,
            snapshot=snapshot_131_same_capability,
        )
    )

    assert result_130 == result_131
