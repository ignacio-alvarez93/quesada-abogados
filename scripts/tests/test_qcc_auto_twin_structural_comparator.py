from copy import deepcopy

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    build_auto_twin_capture_pair,
    build_auto_twin_rendering_profile,
    compare_auto_twin_structure_geometry,
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


def _element(
    selector="#field",
    *,
    x=10,
    y=20,
    width=100,
    height=30,
):
    return {
        "semantics": (
            "INPUT",
        ),

        "selectors": {
            "frame_path":
                "main",

            "candidates": (
                {
                    "selector":
                        selector,

                    "unique":
                        True,
                },
            ),

            "primary": {
                "strategy":
                    "CSS",

                "selector":
                    selector,

                "confidence":
                    1.0,

                "unique":
                    True,
            },

            "fallbacks":
                (),
        },

        "interaction": {
            "visible":
                True,

            "disabled":
                False,

            "aria_disabled":
                False,

            "readonly":
                False,

            "hidden":
                False,

            "aria_hidden":
                False,

            "pointer_events":
                "auto",
        },

        "geometry": {
            "viewport_rect": {
                "x":
                    x,

                "y":
                    y,

                "width":
                    width,

                "height":
                    height,
            },
        },
    }


def _snapshot(
    *,
    origin,
    url,
):
    return {
        "schema_version":
            1,

        "page": {
            "url":
                url,

            "origin":
                origin,

            "pathname":
                "/mercurio/page.html",

            "query":
                "",

            "title":
                "Mercurio",

            "signature":
                "page-signature",
        },

        "elements": (
            _element(),
        ),
    }


def _real():
    return _snapshot(
        origin=(
            "https://mercurio."
            "delegaciondelgobierno.gob.es"
        ),
        url=(
            "https://mercurio."
            "delegaciondelgobierno.gob.es"
            "/mercurio/page.html"
        ),
    )


def _twin():
    return _snapshot(
        origin=(
            "http://127.0.0.1:8767"
        ),
        url=(
            "http://127.0.0.1:8767"
            "/mercurio/page.html"
        ),
    )


def _compare(
    real=None,
    twin=None,
    *,
    pair=None,
    tolerance=8,
):
    return (
        compare_auto_twin_structure_geometry(
            capture_pair=(
                pair
                if pair is not None
                else _pair()
            ),

            real_snapshot=(
                real
                if real is not None
                else _real()
            ),

            twin_snapshot=(
                twin
                if twin is not None
                else _twin()
            ),

            geometry_tolerance_px=(
                tolerance
            ),
        )
    )


def test_origin_and_url_differences_are_ignored():
    result = _compare()

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    assert (
        result[
            "checks"
        ][
            "GEOMETRY"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )


def test_title_change_is_structural_failure():
    twin = _twin()

    twin[
        "page"
    ][
        "title"
    ] = "Different title"

    result = _compare(
        twin=twin
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "metrics"
        ][
            "page_changed"
        ]
        is True
    )


def test_selector_change_is_structural_failure():
    twin = _twin()

    twin[
        "elements"
    ] = (
        _element(
            selector="#other"
        ),
    )

    result = _compare(
        twin=twin
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "metrics"
        ][
            "removed_elements"
        ]
        == 1
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "metrics"
        ][
            "added_elements"
        ]
        == 1
    )


def test_semantics_change_is_structural_failure():
    twin = _twin()

    element = deepcopy(
        twin[
            "elements"
        ][0]
    )

    element[
        "semantics"
    ] = (
        "BUTTON",
    )

    twin[
        "elements"
    ] = (
        element,
    )

    result = _compare(
        twin=twin
    )

    metrics = (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "metrics"
        ]
    )

    assert (
        metrics[
            "semantic_changes"
        ]
        == 1
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_interaction_change_is_structural_failure():
    twin = _twin()

    element = deepcopy(
        twin[
            "elements"
        ][0]
    )

    element[
        "interaction"
    ][
        "disabled"
    ] = True

    twin[
        "elements"
    ] = (
        element,
    )

    result = _compare(
        twin=twin
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "metrics"
        ][
            "interaction_changes"
        ]
        == 1
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_geometry_within_tolerance_passes():
    twin = _twin()

    twin[
        "elements"
    ] = (
        _element(
            x=18,
        ),
    )

    result = _compare(
        twin=twin,
        tolerance=8,
    )

    assert (
        result[
            "checks"
        ][
            "GEOMETRY"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )


def test_geometry_above_tolerance_fails_only_geometry():
    twin = _twin()

    twin[
        "elements"
    ] = (
        _element(
            x=19,
        ),
    )

    result = _compare(
        twin=twin,
        tolerance=8,
    )

    assert (
        result[
            "checks"
        ][
            "GEOMETRY"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    assert (
        result[
            "checks"
        ][
            "GEOMETRY"
        ][
            "metrics"
        ][
            "changed_elements"
        ]
        == 1
    )


def test_added_element_fails_structure():
    twin = _twin()

    twin[
        "elements"
    ] = (
        _element(),
        _element(
            selector="#extra",
        ),
    )

    result = _compare(
        twin=twin
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "metrics"
        ][
            "added_elements"
        ]
        == 1
    )


def test_unaddressable_element_makes_comparison_inconclusive():
    real = _real()
    twin = _twin()

    anonymous = {
        "semantics":
            ("DIV",),

        "selectors":
            {
                "candidates":
                    (),
            },

        "interaction":
            {},

        "geometry": {
            "viewport_rect": {
                "x": 1,
                "y": 1,
                "width": 10,
                "height": 10,
            },
        },
    }

    real[
        "elements"
    ] = (
        *real[
            "elements"
        ],
        anonymous,
    )

    twin[
        "elements"
    ] = (
        *twin[
            "elements"
        ],
        deepcopy(
            anonymous
        ),
    )

    result = _compare(
        real=real,
        twin=twin,
    )

    assert (
        result[
            "inconclusive"
        ]
        is True
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )

    assert (
        result[
            "checks"
        ][
            "GEOMETRY"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )


def test_failed_difference_takes_precedence_over_inconclusive():
    real = _real()
    twin = _twin()

    anonymous = {
        "semantics":
            ("DIV",),

        "selectors": {
            "candidates":
                (),
        },

        "interaction":
            {},

        "geometry": {
            "viewport_rect": None,
        },
    }

    real[
        "elements"
    ] = (
        *real[
            "elements"
        ],
        anonymous,
    )

    twin[
        "page"
    ][
        "title"
    ] = "Different"

    result = _compare(
        real=real,
        twin=twin,
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
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
            pair=pair
        )


def test_comparison_references_capture_pair():
    result = _compare()

    structure = (
        result[
            "checks"
        ][
            "STRUCTURE"
        ]
    )

    assert (
        structure[
            "references"
        ][
            "capture_pair_id"
        ]
        == _pair()[
            "capture_pair_id"
        ]
    )

    assert (
        structure[
            "references"
        ][
            "real_capture_id"
        ]
        == "capture-real"
    )

    assert (
        structure[
            "references"
        ][
            "twin_capture_id"
        ]
        == "capture-twin"
    )


def test_comparison_result_is_lightweight():
    result = _compare()

    assert "elements" not in result
    assert "real_snapshot" not in result
    assert "twin_snapshot" not in result
    assert "html" not in result
    assert "screenshot" not in result


def test_page_signature_is_still_meaningful():
    twin = _twin()

    twin[
        "page"
    ][
        "signature"
    ] = "different-signature"

    result = _compare(
        twin=twin
    )

    assert (
        result[
            "checks"
        ][
            "STRUCTURE"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )
