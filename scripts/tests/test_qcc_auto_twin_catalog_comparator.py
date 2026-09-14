from copy import deepcopy

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    build_auto_twin_capture_pair,
    build_auto_twin_rendering_profile,
    compare_auto_twin_catalogs,
)


def _profile():
    return (
        build_auto_twin_rendering_profile(
            inner_width=1280,
            inner_height=720,
            device_pixel_ratio=1,
        )
    )


def _capture(
    capture_id,
):
    return {
        "capture_id":
            capture_id,

        "pathname":
            "/mercurio/page.html",

        "functional_state":
            "FORM",

        "browser_profile_key":
            "profile",

        "viewport": {
            "inner_width":
                1280,

            "inner_height":
                720,

            "device_pixel_ratio":
                1,

            "scroll_x":
                0,

            "scroll_y":
                0,
        },
    }


def _pair():
    return (
        build_auto_twin_capture_pair(
            twin_key="mercurio",
            candidate_id="candidate-1",
            candidate_revision=1,
            pathname="/mercurio/page.html",
            functional_state="FORM",
            rendering_profile=_profile(),
            real_capture=_capture(
                "capture-real"
            ),
            twin_capture=_capture(
                "capture-twin"
            ),
        )
    )


def _catalog(
    element_id,
    *,
    selected_value="33",
    selected_label="ASTURIAS",
    options=None,
    hints=None,
    catalog_type="native_select",
    frame_path="main",
):
    if options is None:
        options = [
            {
                "value":
                    "",

                "label":
                    "--",

                "disabled":
                    False,
            },
            {
                "value":
                    "33",

                "label":
                    "ASTURIAS",

                "disabled":
                    False,
            },
        ]

    return {
        "catalog_type":
            catalog_type,

        "selector":
            f"#{element_id}",

        "frame_path":
            frame_path,

        "element": {
            "tag":
                "select",

            "id":
                element_id,

            "name":
                element_id,

            "type":
                "",

            "role":
                "",
        },

        "state": {
            "selected_value":
                selected_value,

            "selected_label":
                selected_label,

            "selected_values":
                (
                    [selected_value]
                    if selected_value
                    else []
                ),

            "selected_index":
                1,
        },

        "options":
            deepcopy(
                options
            ),

        "options_count":
            len(
                options
            ),

        "dependency_hints":
            deepcopy(
                hints
                or {}
            ),
    }


def _snapshot(
    catalogs,
):
    return {
        "schema_version":
            1,

        "catalogs":
            deepcopy(
                catalogs
            ),
    }


def _compare(
    real,
    twin,
    *,
    pair=None,
):
    return compare_auto_twin_catalogs(
        capture_pair=(
            pair
            if pair is not None
            else _pair()
        ),
        real_snapshot=(
            _snapshot(
                real
            )
        ),
        twin_snapshot=(
            _snapshot(
                twin
            )
        ),
    )


def _status(
    result,
):
    return (
        result[
            "checks"
        ][
            "CATALOGS"
        ][
            "status"
        ]
    )


def _metrics(
    result,
):
    return (
        result[
            "checks"
        ][
            "CATALOGS"
        ][
            "metrics"
        ]
    )


def test_identical_catalogs_pass():
    catalogs = [
        _catalog(
            "province"
        ),
    ]

    result = _compare(
        catalogs,
        catalogs,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    assert (
        result[
            "catalog_fidelity_pass"
        ]
        is True
    )


def test_empty_catalog_inventories_are_equivalent():
    result = _compare(
        [],
        [],
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    assert (
        _metrics(
            result
        )[
            "real_catalog_count"
        ]
        == 0
    )


def test_catalog_order_does_not_matter_when_keys_are_stable():
    first = [
        _catalog(
            "province"
        ),
        _catalog(
            "municipality"
        ),
    ]

    second = list(
        reversed(
            deepcopy(
                first
            )
        )
    )

    result = _compare(
        first,
        second,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )


def test_added_catalog_fails():
    real = [
        _catalog(
            "province"
        ),
    ]

    twin = [
        *deepcopy(
            real
        ),
        _catalog(
            "municipality"
        ),
    ]

    result = _compare(
        real,
        twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        _metrics(
            result
        )[
            "added_catalogs"
        ]
        == 1
    )


def test_removed_catalog_fails():
    real = [
        _catalog(
            "province"
        ),
        _catalog(
            "municipality"
        ),
    ]

    twin = [
        _catalog(
            "province"
        ),
    ]

    result = _compare(
        real,
        twin,
    )

    assert (
        _metrics(
            result
        )[
            "removed_catalogs"
        ]
        == 1
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_selected_state_change_fails():
    real = [
        _catalog(
            "province",
            selected_value="33",
            selected_label="ASTURIAS",
        ),
    ]

    twin = [
        _catalog(
            "province",
            selected_value="28",
            selected_label="MADRID",
        ),
    ]

    result = _compare(
        real,
        twin,
    )

    assert (
        _metrics(
            result
        )[
            "state_changes"
        ]
        == 1
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_option_label_change_fails():
    real = [
        _catalog(
            "province"
        ),
    ]

    twin = deepcopy(
        real
    )

    twin[
        0
    ][
        "options"
    ][
        1
    ][
        "label"
    ] = "ASTURIAS MODIFICADO"

    result = _compare(
        real,
        twin,
    )

    assert (
        _metrics(
            result
        )[
            "option_changes"
        ]
        == 1
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_option_order_is_part_of_fidelity():
    real = [
        _catalog(
            "province"
        ),
    ]

    twin = deepcopy(
        real
    )

    twin[
        0
    ][
        "options"
    ] = list(
        reversed(
            twin[
                0
            ][
                "options"
            ]
        )
    )

    result = _compare(
        real,
        twin,
    )

    assert (
        _metrics(
            result
        )[
            "option_changes"
        ]
        == 1
    )


def test_disabled_option_change_fails():
    real = [
        _catalog(
            "province"
        ),
    ]

    twin = deepcopy(
        real
    )

    twin[
        0
    ][
        "options"
    ][
        1
    ][
        "disabled"
    ] = True

    result = _compare(
        real,
        twin,
    )

    assert (
        _metrics(
            result
        )[
            "option_changes"
        ]
        == 1
    )


def test_catalog_type_change_fails():
    real = [
        _catalog(
            "province"
        ),
    ]

    twin = [
        _catalog(
            "province",
            catalog_type="custom_catalog",
        ),
    ]

    result = _compare(
        real,
        twin,
    )

    assert (
        _metrics(
            result
        )[
            "identity_changes"
        ]
        == 1
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_dependency_hint_change_fails():
    real = [
        _catalog(
            "province",
            hints={
                "data-target":
                    "municipality",
            },
        ),
        _catalog(
            "municipality"
        ),
    ]

    twin = [
        _catalog(
            "province",
            hints={},
        ),
        _catalog(
            "municipality"
        ),
    ]

    result = _compare(
        real,
        twin,
    )

    metrics = _metrics(
        result
    )

    assert (
        metrics[
            "dependency_changes"
        ]
        == 1
    )

    assert (
        metrics[
            "removed_relations"
        ]
        == 1
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_static_dom_reference_graph_must_match():
    real = [
        _catalog(
            "province",
            hints={
                "aria-controls":
                    "municipality",
            },
        ),
        _catalog(
            "municipality"
        ),
    ]

    twin = deepcopy(
        real
    )

    twin[
        0
    ][
        "dependency_hints"
    ][
        "aria-controls"
    ] = "locality"

    twin.append(
        _catalog(
            "locality"
        )
    )

    result = _compare(
        real,
        twin,
    )

    assert (
        _metrics(
            result
        )[
            "added_relations"
        ]
        >= 1
    )

    assert (
        _metrics(
            result
        )[
            "removed_relations"
        ]
        >= 1
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_anonymous_catalog_is_inconclusive():
    anonymous = {
        "catalog_type":
            "native_select",

        "frame_path":
            "main",

        "element": {
            "tag":
                "select",
        },

        "options":
            [],

        "options_count":
            0,

        "dependency_hints":
            {},
    }

    result = _compare(
        [
            anonymous,
        ],
        [
            deepcopy(
                anonymous
            ),
        ],
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )

    assert (
        result[
            "inconclusive"
        ]
        is True
    )


def test_failure_precedes_inconclusive():
    anonymous = {
        "catalog_type":
            "native_select",

        "frame_path":
            "main",

        "element": {
            "tag":
                "select",
        },

        "options":
            [],

        "dependency_hints":
            {},
    }

    real = [
        _catalog(
            "province"
        ),
        anonymous,
    ]

    twin = [
        anonymous,
    ]

    result = _compare(
        real,
        twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_not_ready_capture_pair_is_rejected():
    pair = _pair()

    pair[
        "status"
    ] = "INCOMPATIBLE"

    pair[
        "ready_for_comparison"
    ] = False

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CAPTURE_PAIR_NOT_READY"
        ),
    ):
        _compare(
            [],
            [],
            pair=pair,
        )


def test_result_references_capture_pair():
    result = _compare(
        [],
        [],
    )

    references = (
        result[
            "checks"
        ][
            "CATALOGS"
        ][
            "references"
        ]
    )

    assert (
        references[
            "real_capture_id"
        ]
        == "capture-real"
    )

    assert (
        references[
            "twin_capture_id"
        ]
        == "capture-twin"
    )


def test_result_is_lightweight():
    result = _compare(
        [
            _catalog(
                "province"
            ),
        ],
        [
            _catalog(
                "province"
            ),
        ],
    )

    assert (
        "catalogs"
        not in result
    )

    assert (
        "relations"
        not in result
    )

    assert (
        "options"
        not in result
    )

    assert (
        "real_snapshot"
        not in result
    )

    assert (
        "twin_snapshot"
        not in result
    )
