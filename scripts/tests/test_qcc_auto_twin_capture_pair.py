import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_CAPTURE_PAIR_INCOMPATIBLE,
    AUTO_TWIN_CAPTURE_PAIR_INCOMPLETE,
    AUTO_TWIN_CAPTURE_PAIR_READY,
    build_auto_twin_capture_pair,
    build_auto_twin_rendering_profile,
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
    **overrides,
):
    payload = {
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

    for key, value in overrides.items():
        if key.startswith(
            "viewport_"
        ):
            viewport_key = key[
                len(
                    "viewport_"
                ):
            ]

            payload[
                "viewport"
            ][
                viewport_key
            ] = value

        else:
            payload[
                key
            ] = value

    return payload


def _pair(
    **overrides,
):
    payload = {
        "twin_key":
            "mercurio",

        "candidate_id":
            "candidate-1",

        "candidate_revision":
            1,

        "pathname":
            "/mercurio/page.html",

        "functional_state":
            "FORM",

        "rendering_profile":
            _profile(),

        "real_capture":
            _capture(
                "capture-real"
            ),

        "twin_capture":
            _capture(
                "capture-twin"
            ),
    }

    payload.update(
        overrides
    )

    return (
        build_auto_twin_capture_pair(
            **payload
        )
    )


def test_matching_capture_pair_is_ready():
    result = _pair()

    assert (
        result["status"]
        == AUTO_TWIN_CAPTURE_PAIR_READY
    )

    assert (
        result[
            "ready_for_comparison"
        ]
        is True
    )

    assert (
        result["reasons"]
        == ()
    )


def test_missing_twin_capture_is_incomplete():
    result = _pair(
        twin_capture=None
    )

    assert (
        result["status"]
        == AUTO_TWIN_CAPTURE_PAIR_INCOMPLETE
    )

    assert (
        result[
            "ready_for_comparison"
        ]
        is False
    )

    assert (
        result["reasons"]
        == (
            "TWIN_CAPTURE_MISSING",
        )
    )


def test_real_viewport_must_match_rendering_profile():
    result = _pair(
        real_capture=_capture(
            "capture-real",
            viewport_inner_width=1279,
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_CAPTURE_PAIR_INCOMPATIBLE
    )

    assert (
        "REAL_INNER_WIDTH_MISMATCH"
        in result["reasons"]
    )


def test_twin_viewport_must_match_rendering_profile():
    result = _pair(
        twin_capture=_capture(
            "capture-twin",
            viewport_inner_height=719,
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_CAPTURE_PAIR_INCOMPATIBLE
    )

    assert (
        "TWIN_INNER_HEIGHT_MISMATCH"
        in result["reasons"]
    )


def test_dpr_must_match():
    result = _pair(
        twin_capture=_capture(
            "capture-twin",
            viewport_device_pixel_ratio=1.25,
        )
    )

    assert (
        "TWIN_DPR_MISMATCH"
        in result["reasons"]
    )

    assert (
        result[
            "ready_for_comparison"
        ]
        is False
    )


def test_scroll_y_must_match_exactly():
    result = _pair(
        twin_capture=_capture(
            "capture-twin",
            viewport_scroll_y=1,
        )
    )

    assert (
        "SCROLL_Y_MISMATCH"
        in result["reasons"]
    )


def test_scroll_x_must_match_exactly():
    result = _pair(
        twin_capture=_capture(
            "capture-twin",
            viewport_scroll_x=4,
        )
    )

    assert (
        "SCROLL_X_MISMATCH"
        in result["reasons"]
    )


def test_pathname_must_match_functional_identity():
    result = _pair(
        twin_capture=_capture(
            "capture-twin",
            pathname="/other/page.html",
        )
    )

    assert (
        "TWIN_PATHNAME_MISMATCH"
        in result["reasons"]
    )


def test_functional_state_must_match():
    result = _pair(
        twin_capture=_capture(
            "capture-twin",
            functional_state="OTHER",
        )
    )

    assert (
        "TWIN_FUNCTIONAL_STATE_MISMATCH"
        in result["reasons"]
    )


def test_capture_pair_identity_has_no_origin_or_url():
    result = _pair()

    identity = result[
        "state_identity"
    ]

    assert (
        identity
        == {
            "pathname":
                "/mercurio/page.html",

            "functional_state":
                "FORM",
        }
    )

    assert "origin" not in identity
    assert "url" not in identity


def test_real_and_twin_profiles_may_differ():
    result = _pair(
        real_capture=_capture(
            "capture-real",
            browser_profile_key=(
                "mercurio_assisted"
            ),
        ),

        twin_capture=_capture(
            "capture-twin",
            browser_profile_key=(
                "twin_discovery"
            ),
        ),
    )

    assert (
        result["status"]
        == AUTO_TWIN_CAPTURE_PAIR_READY
    )


def test_heavy_capture_payload_is_rejected():
    capture = _capture(
        "capture-real"
    )

    capture[
        "screenshot"
    ] = b"forbidden"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CAPTURE_REFERENCE_FIELDS_INVALID"
        ),
    ):
        _pair(
            real_capture=capture
        )


def test_capture_pair_id_is_deterministic():
    first = _pair()
    second = _pair()

    assert (
        first[
            "capture_pair_id"
        ]
        == second[
            "capture_pair_id"
        ]
    )


def test_different_capture_produces_different_pair_id():
    first = _pair()

    second = _pair(
        twin_capture=_capture(
            "capture-twin-2"
        )
    )

    assert (
        first[
            "capture_pair_id"
        ]
        != second[
            "capture_pair_id"
        ]
    )


def test_real_capture_is_required():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_REAL_CAPTURE_REQUIRED"
        ),
    ):
        _pair(
            real_capture=None
        )
