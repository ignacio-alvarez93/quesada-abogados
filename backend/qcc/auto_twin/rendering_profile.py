"""Perfil controlado de renderizado para comparación AUTO TWIN."""

from __future__ import annotations

import hashlib
import json
import math


AUTO_TWIN_RENDERING_PROFILE_SCHEMA_VERSION = 1

AUTO_TWIN_RENDERING_PROFILE_TYPE = (
    "QCC_AUTO_TWIN_RENDERING_PROFILE"
)


def _positive_number(
    value,
    *,
    error,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise ValueError(
            error
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
            error
        ) from exc

    if (
        not math.isfinite(
            normalized
        )
        or normalized <= 0
    ):
        raise ValueError(
            error
        )

    return normalized


def _dimension(
    value,
    *,
    error,
) -> int:
    normalized = (
        _positive_number(
            value,
            error=error,
        )
    )

    if not normalized.is_integer():
        raise ValueError(
            error
        )

    return int(
        normalized
    )


def _profile_identity(
    *,
    inner_width,
    inner_height,
    device_pixel_ratio,
) -> dict:
    return {
        "inner_width":
            inner_width,

        "inner_height":
            inner_height,

        "device_pixel_ratio":
            device_pixel_ratio,
    }


def _rendering_profile_id(
    identity,
) -> str:
    canonical = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def build_auto_twin_rendering_profile(
    *,
    inner_width,
    inner_height,
    device_pixel_ratio,
) -> dict:
    """Construye perfil mínimo que afecta al viewport renderizado.

    outerWidth/outerHeight y coordenadas de pantalla se excluyen
    deliberadamente: la evidencia visual AUTO TWIN actual es una
    captura del viewport, no de la ventana Chrome completa.
    """

    normalized_width = _dimension(
        inner_width,
        error=(
            "QCC_AUTO_TWIN_RENDERING_INNER_WIDTH_INVALID"
        ),
    )

    normalized_height = _dimension(
        inner_height,
        error=(
            "QCC_AUTO_TWIN_RENDERING_INNER_HEIGHT_INVALID"
        ),
    )

    normalized_dpr = (
        _positive_number(
            device_pixel_ratio,
            error=(
                "QCC_AUTO_TWIN_RENDERING_DPR_INVALID"
            ),
        )
    )

    identity = (
        _profile_identity(
            inner_width=(
                normalized_width
            ),
            inner_height=(
                normalized_height
            ),
            device_pixel_ratio=(
                normalized_dpr
            ),
        )
    )

    return {
        "schema_version":
            AUTO_TWIN_RENDERING_PROFILE_SCHEMA_VERSION,

        "profile_type":
            AUTO_TWIN_RENDERING_PROFILE_TYPE,

        "rendering_profile_id":
            _rendering_profile_id(
                identity
            ),

        **identity,
    }


def validate_auto_twin_rendering_profile(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_RENDERING_PROFILE_INVALID"
        )

    if (
        value.get(
            "schema_version"
        )
        != AUTO_TWIN_RENDERING_PROFILE_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_RENDERING_PROFILE_SCHEMA_INVALID"
        )

    if (
        value.get(
            "profile_type"
        )
        != AUTO_TWIN_RENDERING_PROFILE_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_RENDERING_PROFILE_TYPE_INVALID"
        )

    rebuilt = (
        build_auto_twin_rendering_profile(
            inner_width=value.get(
                "inner_width"
            ),
            inner_height=value.get(
                "inner_height"
            ),
            device_pixel_ratio=value.get(
                "device_pixel_ratio"
            ),
        )
    )

    if (
        value.get(
            "rendering_profile_id"
        )
        != rebuilt[
            "rendering_profile_id"
        ]
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_RENDERING_PROFILE_ID_INVALID"
        )

    return rebuilt
