import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_RENDERING_PROFILE_TYPE,
    build_auto_twin_rendering_profile,
    validate_auto_twin_rendering_profile,
)


def test_rendering_profile_is_deterministic():
    first = (
        build_auto_twin_rendering_profile(
            inner_width=1280,
            inner_height=720,
            device_pixel_ratio=1,
        )
    )

    second = (
        build_auto_twin_rendering_profile(
            inner_width=1280.0,
            inner_height=720.0,
            device_pixel_ratio=1.0,
        )
    )

    assert (
        first
        == second
    )

    assert (
        first[
            "profile_type"
        ]
        == AUTO_TWIN_RENDERING_PROFILE_TYPE
    )


def test_rendering_profile_changes_with_viewport():
    first = (
        build_auto_twin_rendering_profile(
            inner_width=1280,
            inner_height=720,
            device_pixel_ratio=1,
        )
    )

    second = (
        build_auto_twin_rendering_profile(
            inner_width=1281,
            inner_height=720,
            device_pixel_ratio=1,
        )
    )

    assert (
        first[
            "rendering_profile_id"
        ]
        != second[
            "rendering_profile_id"
        ]
    )


def test_rendering_profile_changes_with_dpr():
    first = (
        build_auto_twin_rendering_profile(
            inner_width=1280,
            inner_height=720,
            device_pixel_ratio=1,
        )
    )

    second = (
        build_auto_twin_rendering_profile(
            inner_width=1280,
            inner_height=720,
            device_pixel_ratio=1.25,
        )
    )

    assert (
        first[
            "rendering_profile_id"
        ]
        != second[
            "rendering_profile_id"
        ]
    )


@pytest.mark.parametrize(
    "field,value,error",
    [
        (
            "inner_width",
            0,
            "QCC_AUTO_TWIN_RENDERING_INNER_WIDTH_INVALID",
        ),
        (
            "inner_height",
            -1,
            "QCC_AUTO_TWIN_RENDERING_INNER_HEIGHT_INVALID",
        ),
        (
            "device_pixel_ratio",
            0,
            "QCC_AUTO_TWIN_RENDERING_DPR_INVALID",
        ),
    ],
)
def test_invalid_rendering_geometry_is_rejected(
    field,
    value,
    error,
):
    payload = {
        "inner_width":
            1280,

        "inner_height":
            720,

        "device_pixel_ratio":
            1,
    }

    payload[
        field
    ] = value

    with pytest.raises(
        ValueError,
        match=error,
    ):
        build_auto_twin_rendering_profile(
            **payload
        )


def test_tampered_profile_id_is_rejected():
    profile = (
        build_auto_twin_rendering_profile(
            inner_width=1280,
            inner_height=720,
            device_pixel_ratio=1,
        )
    )

    profile[
        "rendering_profile_id"
    ] = "tampered"

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_RENDERING_PROFILE_ID_INVALID"
        ),
    ):
        validate_auto_twin_rendering_profile(
            profile
        )
