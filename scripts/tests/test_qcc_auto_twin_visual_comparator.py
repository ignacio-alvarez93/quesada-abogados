from pathlib import Path

import pytest

from PIL import Image

from backend.qcc.auto_twin import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    build_auto_twin_capture_pair,
    build_auto_twin_rendering_profile,
    compare_auto_twin_visual,
)


WIDTH = 40
HEIGHT = 30


def _profile(
    *,
    width=WIDTH,
    height=HEIGHT,
    dpr=1,
):
    return (
        build_auto_twin_rendering_profile(
            inner_width=width,
            inner_height=height,
            device_pixel_ratio=dpr,
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


def _png(
    path,
    *,
    size=(WIDTH, HEIGHT),
    color=(255, 255, 255),
):
    image = Image.new(
        "RGB",
        size,
        color,
    )

    image.save(
        path,
        format="PNG",
    )

    return path


def _status(
    result,
):
    return (
        result[
            "checks"
        ][
            "VISUAL"
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
            "VISUAL"
        ][
            "metrics"
        ]
    )


def test_identical_images_pass_exact_comparison(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )

    metrics = _metrics(
        result
    )

    assert (
        metrics[
            "changed_pixels"
        ]
        == 0
    )

    assert (
        metrics[
            "changed_pixel_ratio"
        ]
        == 0
    )

    assert (
        metrics[
            "mean_absolute_error"
        ]
        == 0
    )

    assert (
        metrics[
            "root_mean_square_error"
        ]
        == 0
    )


def test_single_changed_pixel_fails_exact_mode(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    image = Image.open(
        twin
    )

    image.putpixel(
        (0, 0),
        (0, 0, 0),
    )

    image.save(
        twin
    )

    image.close()

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
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
            "changed_pixels"
        ]
        == 1
    )


def test_channel_tolerance_can_ignore_small_difference(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png",
        color=(
            100,
            100,
            100,
        ),
    )

    twin = _png(
        tmp_path
        / "twin.png",
        color=(
            104,
            104,
            104,
        ),
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
        channel_tolerance=4,
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
            "changed_pixels"
        ]
        == 0
    )

    # Aunque la tolerancia permite el PASS,
    # conservamos la métrica física de diferencia.
    assert (
        _metrics(
            result
        )[
            "mean_absolute_error"
        ]
        == 4
    )


def test_difference_above_channel_tolerance_fails(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png",
        color=(
            100,
            100,
            100,
        ),
    )

    twin = _png(
        tmp_path
        / "twin.png",
        color=(
            105,
            100,
            100,
        ),
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
        channel_tolerance=4,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_FAIL
    )


def test_changed_pixel_ratio_can_allow_small_region(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    with Image.open(
        twin
    ) as image:
        image = image.convert(
            "RGB"
        )

        image.putpixel(
            (0, 0),
            (0, 0, 0),
        )

        image.save(
            twin
        )

    total = (
        WIDTH
        * HEIGHT
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
        max_changed_pixel_ratio=(
            1
            / total
        ),
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
    )


def test_missing_image_is_not_available(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=(
            tmp_path
            / "missing.png"
        ),
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
    )


def test_invalid_png_is_inconclusive(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = (
        tmp_path
        / "twin.png"
    )

    twin.write_text(
        "not an image",
        encoding="utf-8",
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )


def test_real_image_must_match_rendering_profile(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png",
        size=(
            WIDTH + 1,
            HEIGHT,
        ),
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )

    references = (
        result[
            "checks"
        ][
            "VISUAL"
        ][
            "references"
        ]
    )

    assert (
        references[
            "reason"
        ]
        == "REAL_IMAGE_RENDERING_PROFILE_MISMATCH"
    )


def test_twin_image_must_match_rendering_profile(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png",
        size=(
            WIDTH,
            HEIGHT + 1,
        ),
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )


def test_dpr_controls_expected_physical_image_size(
    tmp_path,
):
    profile = _profile(
        width=20,
        height=15,
        dpr=2,
    )

    def capture(
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
                    20,

                "inner_height":
                    15,

                "device_pixel_ratio":
                    2,

                "scroll_x":
                    0,

                "scroll_y":
                    0,
            },
        }

    pair = build_auto_twin_capture_pair(
        twin_key="mercurio",
        candidate_id="candidate-1",
        candidate_revision=1,
        pathname="/mercurio/page.html",
        functional_state="FORM",
        rendering_profile=profile,
        real_capture=capture(
            "real"
        ),
        twin_capture=capture(
            "twin"
        ),
    )

    real = _png(
        tmp_path
        / "real.png",
        size=(
            40,
            30,
        ),
    )

    twin = _png(
        tmp_path
        / "twin.png",
        size=(
            40,
            30,
        ),
    )

    result = compare_auto_twin_visual(
        capture_pair=pair,
        real_image_path=real,
        twin_image_path=twin,
    )

    assert (
        _status(
            result
        )
        == AUTO_TWIN_VALIDATION_CHECK_PASS
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

    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CAPTURE_PAIR_NOT_READY"
        ),
    ):
        compare_auto_twin_visual(
            capture_pair=pair,
            real_image_path=real,
            twin_image_path=twin,
        )


@pytest.mark.parametrize(
    "value",
    [
        -1,
        256,
        True,
    ],
)
def test_invalid_channel_tolerance_is_rejected(
    tmp_path,
    value,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VISUAL_CHANNEL_TOLERANCE_INVALID"
        ),
    ):
        compare_auto_twin_visual(
            capture_pair=_pair(),
            real_image_path=real,
            twin_image_path=twin,
            channel_tolerance=value,
        )


@pytest.mark.parametrize(
    "value",
    [
        -0.01,
        1.01,
        True,
    ],
)
def test_invalid_changed_pixel_ratio_is_rejected(
    tmp_path,
    value,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_VISUAL_PIXEL_RATIO_INVALID"
        ),
    ):
        compare_auto_twin_visual(
            capture_pair=_pair(),
            real_image_path=real,
            twin_image_path=twin,
            max_changed_pixel_ratio=value,
        )


def test_result_is_lightweight(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
    )

    visual = (
        result[
            "checks"
        ][
            "VISUAL"
        ]
    )

    assert (
        "image"
        not in visual
    )

    assert (
        "pixels"
        not in visual
    )

    assert (
        isinstance(
            visual[
                "metrics"
            ][
                "changed_pixels"
            ],
            int,
        )
    )


def test_references_capture_identity(
    tmp_path,
):
    real = _png(
        tmp_path
        / "real.png"
    )

    twin = _png(
        tmp_path
        / "twin.png"
    )

    result = compare_auto_twin_visual(
        capture_pair=_pair(),
        real_image_path=real,
        twin_image_path=twin,
    )

    references = (
        result[
            "checks"
        ][
            "VISUAL"
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
