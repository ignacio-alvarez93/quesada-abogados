import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION,
    AUTO_TWIN_BEHAVIOR_KIND_GENERIC,
    AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION,
    AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT,
    AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    build_auto_twin_behavior_trace,
    compare_auto_twin_behavior,
)


def _trace(
    *,
    source,
    behavior_kind=AUTO_TWIN_BEHAVIOR_KIND_GENERIC,
    policy=None,
    restoration_status=None,
):
    kwargs = {
        "twin_key":
            "mercurio",

        "candidate_id":
            "candidate-1",

        "source":
            source,

        "behavior_kind":
            behavior_kind,

        "action": {
            "kind":
                "SELECT",

            "selector":
                "#province",

            "frame_path":
                "main",
        },

        "transition": {
            "before_state":
                None,

            "after_state":
                None,

            "changed":
                False,
        },

        "policy":
            policy,
    }

    if restoration_status is not None:
        kwargs[
            "restoration_status"
        ] = restoration_status

    return build_auto_twin_behavior_trace(
        **kwargs
    )


def test_real_observed_remains_non_controlled():
    trace = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
        ),
    )

    assert (
        trace[
            "restoration_status"
        ]
        == AUTO_TWIN_BEHAVIOR_RESTORATION_NOT_APPLICABLE
    )


def test_real_controlled_harvest_requires_exact_restoration():
    trace = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
        ),
    )

    assert (
        trace[
            "restoration_status"
        ]
        == AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
    )


def test_real_controlled_harvest_rejects_non_exact_restore():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_CONTROLLED_RESTORATION_REQUIRED"
        ),
    ):
        _trace(
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST
            ),
            behavior_kind=(
                AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
            ),
            restoration_status="FAILED",
        )


def test_twin_controlled_still_requires_exact_restoration():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_TWIN_RESTORATION_REQUIRED"
        ),
    ):
        _trace(
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
            ),
            behavior_kind=(
                AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
            ),
            restoration_status="FAILED",
        )


def test_behavior_kind_enters_functional_identity():
    navigation = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
        ),
    )

    catalog = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
        ),
    )

    assert (
        navigation[
            "functional_signature"
        ]
        != catalog[
            "functional_signature"
        ]
    )


def test_comparator_rejects_cross_kind_pair():
    real = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
        ),
    )

    twin = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
        ),
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    check = (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ]
    )

    assert (
        check[
            "status"
        ]
        == "FAIL"
    )

    assert (
        check[
            "metrics"
        ][
            "behavior_kind_equal"
        ]
        is False
    )


def test_comparator_accepts_real_controlled_harvest_side():
    real = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_REAL_CONTROLLED_HARVEST
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
        ),
        policy="REAL_GOVERNED_HARVEST",
    )

    twin = _trace(
        source=(
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        ),
        behavior_kind=(
            AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
        ),
        policy="TWIN_ONLY",
    )

    result = compare_auto_twin_behavior(
        real_trace=real,
        twin_trace=twin,
    )

    assert (
        result[
            "behavior_fidelity_pass"
        ]
        is True
    )


def test_unknown_behavior_kind_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_BEHAVIOR_KIND_INVALID"
        ),
    ):
        _trace(
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
            ),
            behavior_kind="UNKNOWN_KIND",
        )
