from copy import deepcopy

from PIL import Image

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
    AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION,
    AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    AUTO_TWIN_VALIDATION_VERDICT_FAIL,
    AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_VERDICT_PASS,
    build_auto_twin_behavior_trace,
    build_auto_twin_capture_pair,
    build_auto_twin_rendering_profile,
    compare_auto_twin_fidelity,
)


WIDTH = 40
HEIGHT = 30


def _profile():
    return (
        build_auto_twin_rendering_profile(
            inner_width=WIDTH,
            inner_height=HEIGHT,
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
                WIDTH,

            "inner_height":
                HEIGHT,

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
    *,
    x=10,
    selector="#field",
):
    return {
        "semantics":
            ("INPUT",),

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
                    20,

                "width":
                    100,

                "height":
                    30,
            },
        },
    }


def _snapshot(
    *,
    real,
):
    origin = (
        "https://real.example"
        if real
        else "http://127.0.0.1:8767"
    )

    return {
        "schema_version":
            1,

        "page": {
            "url":
                (
                    origin
                    + "/mercurio/page.html"
                ),

            "origin":
                origin,

            "pathname":
                "/mercurio/page.html",

            "query":
                "",

            "title":
                "Mercurio",

            "signature":
                "same-signature",
        },

        "elements": (
            _element(),
        ),
    }


def _png(
    path,
    *,
    color=(255, 255, 255),
):
    image = Image.new(
        "RGB",
        (
            WIDTH,
            HEIGHT,
        ),
        color,
    )

    image.save(
        path,
        format="PNG",
    )

    return path


def _compare(
    tmp_path,
    *,
    real_snapshot=None,
    twin_snapshot=None,
    real_image=None,
    twin_image=None,
    pair=None,
    real_behavior_trace=None,
    twin_behavior_trace=None,
):
    if real_image is None:
        real_image = _png(
            tmp_path
            / "real.png"
        )

    if twin_image is None:
        twin_image = _png(
            tmp_path
            / "twin.png"
        )

    return compare_auto_twin_fidelity(
        capture_pair=(
            pair
            if pair is not None
            else _pair()
        ),
        real_snapshot=(
            real_snapshot
            if real_snapshot is not None
            else _snapshot(
                real=True
            )
        ),
        twin_snapshot=(
            twin_snapshot
            if twin_snapshot is not None
            else _snapshot(
                real=False
            )
        ),
        real_image_path=(
            real_image
        ),
        twin_image_path=(
            twin_image
        ),
        real_behavior_trace=(
            real_behavior_trace
        ),
        twin_behavior_trace=(
            twin_behavior_trace
        ),
    )


def test_perfect_core_fidelity_passes(
    tmp_path,
):
    result = _compare(
        tmp_path
    )

    assert (
        result[
            "core_fidelity_verdict"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    assert (
        result[
            "core_fidelity_pass"
        ]
        is True
    )

    assert all(
        result[
            "checks"
        ][
            dimension
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
        for dimension
        in (
            "STRUCTURE",
            "GEOMETRY",
            "VISUAL",
        )
    )


def test_perfect_core_is_not_complete_validation(
    tmp_path,
):
    result = _compare(
        tmp_path
    )

    evidence = (
        result[
            "validation_evidence"
        ]
    )

    assert (
        evidence[
            "checks"
        ][
            "CATALOGS"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )

    assert (
        evidence[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )

    assert (
        evidence[
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE
    )

    assert (
        evidence[
            "ready_for_validation"
        ]
        is False
    )


def test_visual_failure_fails_core_and_global(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png",
        color=(
            255,
            255,
            255,
        ),
    )

    twin = _png(
        tmp_path
        / "twin.png",
        color=(
            0,
            0,
            0,
        ),
    )

    result = _compare(
        tmp_path,
        real_image=real,
        twin_image=twin,
    )

    assert (
        result[
            "checks"
        ][
            "VISUAL"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "core_fidelity_verdict"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "validation_evidence"
        ][
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_FAIL
    )


def test_geometry_failure_is_separate(
    tmp_path,
):
    twin = _snapshot(
        real=False
    )

    twin[
        "elements"
    ] = (
        _element(
            x=19
        ),
    )

    result = _compare(
        tmp_path,
        twin_snapshot=twin,
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
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "core_fidelity_verdict"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_structure_failure_fails_core(
    tmp_path,
):
    twin = _snapshot(
        real=False
    )

    twin[
        "page"
    ][
        "title"
    ] = "Other"

    result = _compare(
        tmp_path,
        twin_snapshot=twin,
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
            "core_fidelity_verdict"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_missing_visual_is_core_inconclusive(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    result = _compare(
        tmp_path,
        real_image=real,
        twin_image=(
            tmp_path
            / "missing.png"
        ),
    )

    assert (
        result[
            "checks"
        ][
            "VISUAL"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )

    assert (
        result[
            "core_fidelity_verdict"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )

    assert (
        result[
            "core_fidelity_pass"
        ]
        is False
    )


def test_unaddressable_structure_is_core_inconclusive(
    tmp_path,
):
    real = _snapshot(
        real=True
    )

    twin = _snapshot(
        real=False
    )

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
            "viewport_rect":
                None,
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
        tmp_path,
        real_snapshot=real,
        twin_snapshot=twin,
    )

    assert (
        result[
            "core_fidelity_verdict"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )


def test_capture_pair_identity_is_preserved(
    tmp_path,
):
    pair = _pair()

    result = _compare(
        tmp_path,
        pair=pair,
    )

    assert (
        result[
            "capture_pair_id"
        ]
        == pair[
            "capture_pair_id"
        ]
    )

    evidence = (
        result[
            "validation_evidence"
        ]
    )

    assert (
        evidence[
            "capture_pair"
        ][
            "real_capture_id"
        ]
        == "capture-real"
    )

    assert (
        evidence[
            "capture_pair"
        ][
            "twin_capture_id"
        ]
        == "capture-twin"
    )


def test_all_five_dimensions_remain_required(
    tmp_path,
):
    result = _compare(
        tmp_path
    )

    required = (
        result[
            "validation_evidence"
        ][
            "required_dimensions"
        ]
    )

    assert (
        required
        == (
            "STRUCTURE",
            "GEOMETRY",
            "VISUAL",
            "CATALOGS",
            "BEHAVIOR",
        )
    )


def test_result_is_lightweight(
    tmp_path,
):
    result = _compare(
        tmp_path
    )

    assert (
        "real_snapshot"
        not in result
    )

    assert (
        "twin_snapshot"
        not in result
    )

    assert (
        "image"
        not in result
    )

    assert (
        "html"
        not in result
    )


def test_not_ready_pair_is_rejected(
    tmp_path,
):
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
            tmp_path,
            pair=pair,
        )


def _unified_catalog(
    element_id="province",
    *,
    selected_value="33",
):
    return {
        "catalog_type":
            "native_select",

        "selector":
            f"#{element_id}",

        "frame_path":
            "main",

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
                "ASTURIAS"
                if selected_value == "33"
                else "MADRID",

            "selected_values": [
                selected_value
            ],

            "selected_index":
                1,
        },

        "options": [
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
        ],

        "options_count":
            2,

        "dependency_hints":
            {},
    }


def _snapshot_with_catalogs(
    *,
    real,
    catalogs=None,
):
    snapshot = _snapshot(
        real=real
    )

    snapshot[
        "catalogs"
    ] = (
        deepcopy(
            catalogs
        )
        if catalogs is not None
        else []
    )

    return snapshot


def _behavior_pair(
    *,
    candidate_id="candidate-1",
    twin_action_code="CONTINUE",
):
    real = (
        build_auto_twin_behavior_trace(
            twin_key="mercurio",
            candidate_id=(
                candidate_id
            ),
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_REAL_OBSERVED
            ),
            behavior_kind=(
                AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
            ),
            action={
                "kind":
                    "NAVIGATION",

                "action_code":
                    "CONTINUE",
            },
            transition={
                "before_state":
                    "FORM",

                "after_state":
                    "NEXT",

                "changed":
                    True,
            },
            policy="HUMAN_ONLY",
        )
    )

    twin = (
        build_auto_twin_behavior_trace(
            twin_key="mercurio",
            candidate_id=(
                candidate_id
            ),
            source=(
                AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
            ),
            behavior_kind=(
                AUTO_TWIN_BEHAVIOR_KIND_NAVIGATION
            ),
            action={
                "kind":
                    "NAVIGATION",

                "action_code":
                    twin_action_code,
            },
            transition={
                "before_state":
                    "FORM",

                "after_state":
                    "NEXT",

                "changed":
                    True,
            },
            policy="AUTOMATION_ALLOWED",
        )
    )

    return (
        real,
        twin,
    )


def test_missing_catalog_key_means_not_available(
    tmp_path,
):
    real = _snapshot(
        real=True
    )

    twin = _snapshot(
        real=False
    )

    real[
        "catalogs"
    ] = []

    result = _compare(
        tmp_path,
        real_snapshot=real,
        twin_snapshot=twin,
    )

    assert (
        result[
            "checks"
        ][
            "CATALOGS"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )


def test_explicit_empty_catalog_inventories_pass(
    tmp_path,
):
    result = _compare(
        tmp_path,
        real_snapshot=(
            _snapshot_with_catalogs(
                real=True
            )
        ),
        twin_snapshot=(
            _snapshot_with_catalogs(
                real=False
            )
        ),
    )

    assert (
        result[
            "checks"
        ][
            "CATALOGS"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    assert (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )

    assert (
        result[
            "validation_evidence"
        ][
            "ready_for_validation"
        ]
        is False
    )


def test_all_five_dimensions_pass_and_are_ready(
    tmp_path,
):
    catalogs = [
        _unified_catalog()
    ]

    real_behavior, twin_behavior = (
        _behavior_pair()
    )

    result = _compare(
        tmp_path,
        real_snapshot=(
            _snapshot_with_catalogs(
                real=True,
                catalogs=catalogs,
            )
        ),
        twin_snapshot=(
            _snapshot_with_catalogs(
                real=False,
                catalogs=catalogs,
            )
        ),
        real_behavior_trace=(
            real_behavior
        ),
        twin_behavior_trace=(
            twin_behavior
        ),
    )

    assert all(
        result[
            "checks"
        ][
            dimension
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_PASS
        for dimension
        in (
            "STRUCTURE",
            "GEOMETRY",
            "VISUAL",
            "CATALOGS",
            "BEHAVIOR",
        )
    )

    evidence = (
        result[
            "validation_evidence"
        ]
    )

    assert (
        evidence[
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_PASS
    )

    assert (
        evidence[
            "ready_for_validation"
        ]
        is True
    )

    assert (
        evidence[
            "summary"
        ][
            "incomplete_dimensions"
        ]
        == ()
    )


def test_behavior_failure_fails_global_evidence(
    tmp_path,
):
    catalogs = [
        _unified_catalog()
    ]

    real_behavior, twin_behavior = (
        _behavior_pair(
            twin_action_code="BACK"
        )
    )

    result = _compare(
        tmp_path,
        real_snapshot=(
            _snapshot_with_catalogs(
                real=True,
                catalogs=catalogs,
            )
        ),
        twin_snapshot=(
            _snapshot_with_catalogs(
                real=False,
                catalogs=catalogs,
            )
        ),
        real_behavior_trace=(
            real_behavior
        ),
        twin_behavior_trace=(
            twin_behavior
        ),
    )

    assert (
        result[
            "core_fidelity_pass"
        ]
        is True
    )

    assert (
        result[
            "checks"
        ][
            "BEHAVIOR"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "validation_evidence"
        ][
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_FAIL
    )

    assert (
        result[
            "validation_evidence"
        ][
            "ready_for_validation"
        ]
        is False
    )


def test_catalog_failure_fails_global_evidence(
    tmp_path,
):
    real_catalogs = [
        _unified_catalog(
            selected_value="33"
        )
    ]

    twin_catalogs = [
        _unified_catalog(
            selected_value="28"
        )
    ]

    real_behavior, twin_behavior = (
        _behavior_pair()
    )

    result = _compare(
        tmp_path,
        real_snapshot=(
            _snapshot_with_catalogs(
                real=True,
                catalogs=real_catalogs,
            )
        ),
        twin_snapshot=(
            _snapshot_with_catalogs(
                real=False,
                catalogs=twin_catalogs,
            )
        ),
        real_behavior_trace=(
            real_behavior
        ),
        twin_behavior_trace=(
            twin_behavior
        ),
    )

    assert (
        result[
            "checks"
        ][
            "CATALOGS"
        ][
            "status"
        ]
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    assert (
        result[
            "validation_evidence"
        ][
            "verdict"
        ]
        == AUTO_TWIN_VALIDATION_VERDICT_FAIL
    )


def test_behavior_scope_must_match_capture_pair(
    tmp_path,
):
    catalogs = [
        _unified_catalog()
    ]

    real_behavior, twin_behavior = (
        _behavior_pair(
            candidate_id="candidate-OTHER"
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_UNIFIED_BEHAVIOR_CANDIDATE_MISMATCH"
        ),
    ):
        _compare(
            tmp_path,
            real_snapshot=(
                _snapshot_with_catalogs(
                    real=True,
                    catalogs=catalogs,
                )
            ),
            twin_snapshot=(
                _snapshot_with_catalogs(
                    real=False,
                    catalogs=catalogs,
                )
            ),
            real_behavior_trace=(
                real_behavior
            ),
            twin_behavior_trace=(
                twin_behavior
            ),
        )


def test_all_five_checks_are_returned(
    tmp_path,
):
    result = _compare(
        tmp_path
    )

    assert (
        tuple(
            result[
                "checks"
            ]
        )
        == (
            "STRUCTURE",
            "GEOMETRY",
            "VISUAL",
            "CATALOGS",
            "BEHAVIOR",
        )
    )
