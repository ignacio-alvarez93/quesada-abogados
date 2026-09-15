"""Comparador visual REAL ↔ TWIN para screenshots de viewport.

Opera exclusivamente sobre evidencia ya capturada.

No redimensiona imágenes.
No corrige diferencias.
No modifica candidates.
No cambia lifecycle.
No promociona ACTIVE.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageStat,
)

from .capture_pair import (
    AUTO_TWIN_CAPTURE_PAIR_READY,
)

from .validation_evidence import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
)


AUTO_TWIN_VISUAL_COMPARATOR_SCHEMA_VERSION = 1

AUTO_TWIN_VISUAL_COMPARATOR_TYPE = (
    "QCC_AUTO_TWIN_VISUAL_COMPARISON"
)


DEFAULT_VISUAL_CHANNEL_TOLERANCE = 0

DEFAULT_VISUAL_MAX_CHANGED_PIXEL_RATIO = 0.0


def _channel_tolerance(
    value,
) -> int:
    if isinstance(
        value,
        bool,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VISUAL_CHANNEL_TOLERANCE_INVALID"
        )

    try:
        normalized = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_VISUAL_CHANNEL_TOLERANCE_INVALID"
        ) from exc

    if (
        normalized < 0
        or normalized > 255
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VISUAL_CHANNEL_TOLERANCE_INVALID"
        )

    return normalized


def _pixel_ratio(
    value,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VISUAL_PIXEL_RATIO_INVALID"
        )

    try:
        normalized = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_VISUAL_PIXEL_RATIO_INVALID"
        ) from exc

    if (
        not math.isfinite(
            normalized
        )
        or normalized < 0
        or normalized > 1
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VISUAL_PIXEL_RATIO_INVALID"
        )

    return normalized


def _artifact_path(
    value,
) -> Path | None:
    if value is None:
        return None

    text = str(
        value
    ).strip()

    if not text:
        return None

    return Path(
        text
    )


def _load_rgb(
    path,
):
    try:
        with Image.open(
            path
        ) as image:
            image.load()

            return image.convert(
                "RGB"
            )

    except (
        OSError,
        ValueError,
    ):
        return None


def _expected_pixel_size(
    capture_pair,
):
    profile = capture_pair.get(
        "rendering_profile"
    )

    if not isinstance(
        profile,
        dict,
    ):
        return None

    try:
        width = int(
            profile[
                "inner_width"
            ]
        )

        height = int(
            profile[
                "inner_height"
            ]
        )

        dpr = float(
            profile[
                "device_pixel_ratio"
            ]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None

    if (
        width <= 0
        or height <= 0
        or not math.isfinite(
            dpr
        )
        or dpr <= 0
    ):
        return None

    return (
        int(
            round(
                width
                * dpr
            )
        ),
        int(
            round(
                height
                * dpr
            )
        ),
    )


def _threshold_mask(
    difference,
    *,
    tolerance,
):
    channels = (
        difference.split()
    )

    masks = [
        channel.point(
            lambda value: (
                255
                if value > tolerance
                else 0
            )
        )
        for channel
        in channels
    ]

    combined = masks[0]

    for mask in masks[1:]:
        combined = (
            ImageChops.lighter(
                combined,
                mask,
            )
        )

    return combined


def _difference_metrics(
    real,
    twin,
    *,
    channel_tolerance,
):
    difference = (
        ImageChops.difference(
            real,
            twin,
        )
    )

    stat = ImageStat.Stat(
        difference
    )

    mean_absolute_error = (
        sum(
            float(
                value
            )
            for value
            in stat.mean
        )
        / len(
            stat.mean
        )
    )

    root_mean_square_error = math.sqrt(
        sum(
            float(
                value
            )
            ** 2
            for value
            in stat.rms
        )
        / len(
            stat.rms
        )
    )

    extrema = (
        difference.getextrema()
    )

    max_channel_error = max(
        upper
        for _lower, upper
        in extrema
    )

    mask = _threshold_mask(
        difference,
        tolerance=(
            channel_tolerance
        ),
    )

    histogram = (
        mask.histogram()
    )

    changed_pixels = int(
        histogram[
            255
        ]
    )

    total_pixels = (
        real.width
        * real.height
    )

    changed_pixel_ratio = (
        (
            changed_pixels
            / total_pixels
        )
        if total_pixels
        else 0.0
    )

    return {
        "total_pixels":
            total_pixels,

        "changed_pixels":
            changed_pixels,

        "changed_pixel_ratio":
            changed_pixel_ratio,

        "mean_absolute_error":
            mean_absolute_error,

        "root_mean_square_error":
            root_mean_square_error,

        "max_channel_error":
            int(
                max_channel_error
            ),
    }


def _result(
    *,
    capture_pair,
    status,
    summary,
    real_path,
    twin_path,
    metrics=None,
    reason=None,
    channel_tolerance,
    max_changed_pixel_ratio,
):
    real_capture = (
        capture_pair.get(
            "real_capture"
        )
        or {}
    )

    twin_capture = (
        capture_pair.get(
            "twin_capture"
        )
        or {}
    )

    normalized_metrics = {
        "channel_tolerance":
            channel_tolerance,

        "max_changed_pixel_ratio":
            max_changed_pixel_ratio,
    }

    if isinstance(
        metrics,
        dict,
    ):
        normalized_metrics.update(
            metrics
        )

    references = {
        "capture_pair_id":
            capture_pair.get(
                "capture_pair_id"
            ),

        "real_capture_id":
            real_capture.get(
                "capture_id"
            ),

        "twin_capture_id":
            twin_capture.get(
                "capture_id"
            ),

        "real_visual_artifact":
            (
                str(
                    real_path
                )
                if real_path
                else None
            ),

        "twin_visual_artifact":
            (
                str(
                    twin_path
                )
                if twin_path
                else None
            ),
    }

    if reason:
        references[
            "reason"
        ] = reason

    return {
        "schema_version":
            AUTO_TWIN_VISUAL_COMPARATOR_SCHEMA_VERSION,

        "comparison_type":
            AUTO_TWIN_VISUAL_COMPARATOR_TYPE,

        "capture_pair_id":
            capture_pair.get(
                "capture_pair_id"
            ),

        "checks": {
            "VISUAL": {
                "status":
                    status,

                "summary":
                    summary,

                "metrics":
                    normalized_metrics,

                "references":
                    references,
            },
        },
    }


def compare_auto_twin_visual(
    *,
    capture_pair,
    real_image_path,
    twin_image_path,
    channel_tolerance=(
        DEFAULT_VISUAL_CHANNEL_TOLERANCE
    ),
    max_changed_pixel_ratio=(
        DEFAULT_VISUAL_MAX_CHANGED_PIXEL_RATIO
    ),
) -> dict:
    """Compara dos screenshots de viewport sin transformarlos.

    channel_tolerance:
        diferencia máxima permitida por canal RGB antes de
        considerar que un píxel ha cambiado.

    max_changed_pixel_ratio:
        proporción máxima de píxeles modificados permitida.

    Los defaults son deliberadamente estrictos:
        tolerance = 0
        ratio = 0.0

    La calibración visual futura podrá relajar estos parámetros
    de forma explícita, nunca silenciosa.
    """

    if not isinstance(
        capture_pair,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CAPTURE_PAIR_INVALID"
        )

    if (
        capture_pair.get(
            "status"
        )
        != AUTO_TWIN_CAPTURE_PAIR_READY
        or capture_pair.get(
            "ready_for_comparison"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CAPTURE_PAIR_NOT_READY"
        )

    normalized_tolerance = (
        _channel_tolerance(
            channel_tolerance
        )
    )

    normalized_ratio = (
        _pixel_ratio(
            max_changed_pixel_ratio
        )
    )

    real_path = (
        _artifact_path(
            real_image_path
        )
    )

    twin_path = (
        _artifact_path(
            twin_image_path
        )
    )

    if (
        real_path is None
        or twin_path is None
        or not real_path.is_file()
        or not twin_path.is_file()
    ):
        return _result(
            capture_pair=(
                capture_pair
            ),
            status=(
                AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
            ),
            summary=(
                "Visual evidence unavailable."
            ),
            real_path=(
                real_path
            ),
            twin_path=(
                twin_path
            ),
            reason=(
                "VISUAL_ARTIFACT_MISSING"
            ),
            channel_tolerance=(
                normalized_tolerance
            ),
            max_changed_pixel_ratio=(
                normalized_ratio
            ),
        )

    real = _load_rgb(
        real_path
    )

    twin = _load_rgb(
        twin_path
    )

    if (
        real is None
        or twin is None
    ):
        return _result(
            capture_pair=(
                capture_pair
            ),
            status=(
                AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
            ),
            summary=(
                "Visual evidence cannot be decoded."
            ),
            real_path=(
                real_path
            ),
            twin_path=(
                twin_path
            ),
            reason=(
                "VISUAL_ARTIFACT_INVALID"
            ),
            channel_tolerance=(
                normalized_tolerance
            ),
            max_changed_pixel_ratio=(
                normalized_ratio
            ),
        )

    expected_size = (
        _expected_pixel_size(
            capture_pair
        )
    )

    if expected_size is None:
        return _result(
            capture_pair=(
                capture_pair
            ),
            status=(
                AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
            ),
            summary=(
                "Rendering profile cannot determine image size."
            ),
            real_path=(
                real_path
            ),
            twin_path=(
                twin_path
            ),
            reason=(
                "RENDERING_PROFILE_IMAGE_SIZE_UNKNOWN"
            ),
            channel_tolerance=(
                normalized_tolerance
            ),
            max_changed_pixel_ratio=(
                normalized_ratio
            ),
        )

    if (
        real.size
        != expected_size
    ):
        return _result(
            capture_pair=(
                capture_pair
            ),
            status=(
                AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
            ),
            summary=(
                "REAL screenshot does not match rendering profile."
            ),
            real_path=(
                real_path
            ),
            twin_path=(
                twin_path
            ),
            metrics={
                "expected_width_px":
                    expected_size[
                        0
                    ],

                "expected_height_px":
                    expected_size[
                        1
                    ],

                "real_width_px":
                    real.width,

                "real_height_px":
                    real.height,
            },
            reason=(
                "REAL_IMAGE_RENDERING_PROFILE_MISMATCH"
            ),
            channel_tolerance=(
                normalized_tolerance
            ),
            max_changed_pixel_ratio=(
                normalized_ratio
            ),
        )

    if (
        twin.size
        != expected_size
    ):
        return _result(
            capture_pair=(
                capture_pair
            ),
            status=(
                AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
            ),
            summary=(
                "TWIN screenshot does not match rendering profile."
            ),
            real_path=(
                real_path
            ),
            twin_path=(
                twin_path
            ),
            metrics={
                "expected_width_px":
                    expected_size[
                        0
                    ],

                "expected_height_px":
                    expected_size[
                        1
                    ],

                "twin_width_px":
                    twin.width,

                "twin_height_px":
                    twin.height,
            },
            reason=(
                "TWIN_IMAGE_RENDERING_PROFILE_MISMATCH"
            ),
            channel_tolerance=(
                normalized_tolerance
            ),
            max_changed_pixel_ratio=(
                normalized_ratio
            ),
        )

    if (
        real.size
        != twin.size
    ):
        return _result(
            capture_pair=(
                capture_pair
            ),
            status=(
                AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
            ),
            summary=(
                "REAL and TWIN image dimensions differ."
            ),
            real_path=(
                real_path
            ),
            twin_path=(
                twin_path
            ),
            reason=(
                "VISUAL_DIMENSIONS_MISMATCH"
            ),
            channel_tolerance=(
                normalized_tolerance
            ),
            max_changed_pixel_ratio=(
                normalized_ratio
            ),
        )

    metrics = (
        _difference_metrics(
            real,
            twin,
            channel_tolerance=(
                normalized_tolerance
            ),
        )
    )

    visual_pass = (
        metrics[
            "changed_pixel_ratio"
        ]
        <= normalized_ratio
    )

    status = (
        AUTO_TWIN_VALIDATION_CHECK_PASS
        if visual_pass
        else AUTO_TWIN_VALIDATION_CHECK_FAIL
    )

    summary = (
        "Visual fidelity within configured tolerance."
        if visual_pass
        else
        "Visual fidelity exceeds configured tolerance."
    )

    return _result(
        capture_pair=(
            capture_pair
        ),
        status=(
            status
        ),
        summary=(
            summary
        ),
        real_path=(
            real_path
        ),
        twin_path=(
            twin_path
        ),
        metrics=(
            metrics
        ),
        channel_tolerance=(
            normalized_tolerance
        ),
        max_changed_pixel_ratio=(
            normalized_ratio
        ),
    )
