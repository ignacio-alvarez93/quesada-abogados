"""Pareja ligera de capturas REAL ↔ TWIN para validación."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from .rendering_profile import (
    validate_auto_twin_rendering_profile,
)


AUTO_TWIN_CAPTURE_PAIR_SCHEMA_VERSION = 1

AUTO_TWIN_CAPTURE_PAIR_TYPE = (
    "QCC_AUTO_TWIN_CAPTURE_PAIR"
)

AUTO_TWIN_CAPTURE_PAIR_READY = "READY"

AUTO_TWIN_CAPTURE_PAIR_INCOMPLETE = (
    "INCOMPLETE"
)

AUTO_TWIN_CAPTURE_PAIR_INCOMPATIBLE = (
    "INCOMPATIBLE"
)


_ALLOWED_CAPTURE_FIELDS = frozenset({
    "capture_id",
    "pathname",
    "functional_state",
    "browser_profile_key",
    "viewport",
})

_ALLOWED_VIEWPORT_FIELDS = frozenset({
    "inner_width",
    "inner_height",
    "device_pixel_ratio",
    "scroll_x",
    "scroll_y",
})


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _number(
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

    if not math.isfinite(
        normalized
    ):
        raise ValueError(
            error
        )

    return normalized


def _positive_dimension(
    value,
    *,
    error,
) -> int:
    normalized = _number(
        value,
        error=error,
    )

    if (
        normalized <= 0
        or not normalized.is_integer()
    ):
        raise ValueError(
            error
        )

    return int(
        normalized
    )


def _normalize_viewport(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CAPTURE_VIEWPORT_INVALID"
        )

    if (
        set(value)
        - _ALLOWED_VIEWPORT_FIELDS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CAPTURE_VIEWPORT_FIELDS_INVALID"
        )

    return {
        "inner_width":
            _positive_dimension(
                value.get(
                    "inner_width"
                ),
                error=(
                    "QCC_AUTO_TWIN_CAPTURE_INNER_WIDTH_INVALID"
                ),
            ),

        "inner_height":
            _positive_dimension(
                value.get(
                    "inner_height"
                ),
                error=(
                    "QCC_AUTO_TWIN_CAPTURE_INNER_HEIGHT_INVALID"
                ),
            ),

        "device_pixel_ratio":
            _number(
                value.get(
                    "device_pixel_ratio"
                ),
                error=(
                    "QCC_AUTO_TWIN_CAPTURE_DPR_INVALID"
                ),
            ),

        "scroll_x":
            _number(
                value.get(
                    "scroll_x",
                    0,
                ),
                error=(
                    "QCC_AUTO_TWIN_CAPTURE_SCROLL_INVALID"
                ),
            ),

        "scroll_y":
            _number(
                value.get(
                    "scroll_y",
                    0,
                ),
                error=(
                    "QCC_AUTO_TWIN_CAPTURE_SCROLL_INVALID"
                ),
            ),
    }


def _normalize_capture(
    value,
    *,
    required,
) -> dict | None:
    if value is None:
        if required:
            raise ValueError(
                "QCC_AUTO_TWIN_REAL_CAPTURE_REQUIRED"
            )

        return None

    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CAPTURE_REFERENCE_INVALID"
        )

    if (
        set(value)
        - _ALLOWED_CAPTURE_FIELDS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CAPTURE_REFERENCE_FIELDS_INVALID"
        )

    capture_id = _text(
        value.get(
            "capture_id"
        )
    )

    if not capture_id:
        raise ValueError(
            "QCC_AUTO_TWIN_CAPTURE_ID_REQUIRED"
        )

    return {
        "capture_id":
            capture_id,

        "pathname":
            _text(
                value.get(
                    "pathname"
                )
            )
            or None,

        "functional_state":
            _text(
                value.get(
                    "functional_state"
                )
            )
            or None,

        "browser_profile_key":
            _text(
                value.get(
                    "browser_profile_key"
                )
            )
            or None,

        "viewport":
            _normalize_viewport(
                value.get(
                    "viewport"
                )
            ),
    }


def _pair_id(
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


def _profile_mismatches(
    capture,
    profile,
    *,
    prefix,
) -> list[str]:
    viewport = capture[
        "viewport"
    ]

    mismatches = []

    if (
        viewport[
            "inner_width"
        ]
        != profile[
            "inner_width"
        ]
    ):
        mismatches.append(
            f"{prefix}_INNER_WIDTH_MISMATCH"
        )

    if (
        viewport[
            "inner_height"
        ]
        != profile[
            "inner_height"
        ]
    ):
        mismatches.append(
            f"{prefix}_INNER_HEIGHT_MISMATCH"
        )

    if (
        viewport[
            "device_pixel_ratio"
        ]
        != profile[
            "device_pixel_ratio"
        ]
    ):
        mismatches.append(
            f"{prefix}_DPR_MISMATCH"
        )

    return mismatches


def build_auto_twin_capture_pair(
    *,
    twin_key,
    candidate_id,
    candidate_revision,
    pathname,
    functional_state=None,
    rendering_profile,
    real_capture,
    twin_capture=None,
) -> dict:
    normalized_twin_key = _text(
        twin_key
    )

    normalized_candidate_id = _text(
        candidate_id
    )

    normalized_pathname = _text(
        pathname
    )

    normalized_state = _text(
        functional_state
    ) or None

    if not normalized_twin_key:
        raise ValueError(
            "QCC_AUTO_TWIN_KEY_REQUIRED"
        )

    if not normalized_candidate_id:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
        )

    if not normalized_pathname:
        raise ValueError(
            "QCC_AUTO_TWIN_PATHNAME_REQUIRED"
        )

    try:
        normalized_revision = int(
            candidate_revision
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_REVISION_INVALID"
        ) from exc

    if normalized_revision <= 0:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_REVISION_INVALID"
        )

    profile = (
        validate_auto_twin_rendering_profile(
            rendering_profile
        )
    )

    real = _normalize_capture(
        real_capture,
        required=True,
    )

    twin = _normalize_capture(
        twin_capture,
        required=False,
    )

    mismatches = []

    if (
        real.get(
            "pathname"
        )
        != normalized_pathname
    ):
        mismatches.append(
            "REAL_PATHNAME_MISMATCH"
        )

    if (
        real.get(
            "functional_state"
        )
        != normalized_state
    ):
        mismatches.append(
            "REAL_FUNCTIONAL_STATE_MISMATCH"
        )

    mismatches.extend(
        _profile_mismatches(
            real,
            profile,
            prefix="REAL",
        )
    )

    if twin is None:
        status = (
            AUTO_TWIN_CAPTURE_PAIR_INCOMPLETE
        )

        reasons = (
            "TWIN_CAPTURE_MISSING",
        )

    else:
        if (
            twin.get(
                "pathname"
            )
            != normalized_pathname
        ):
            mismatches.append(
                "TWIN_PATHNAME_MISMATCH"
            )

        if (
            twin.get(
                "functional_state"
            )
            != normalized_state
        ):
            mismatches.append(
                "TWIN_FUNCTIONAL_STATE_MISMATCH"
            )

        mismatches.extend(
            _profile_mismatches(
                twin,
                profile,
                prefix="TWIN",
            )
        )

        if (
            real[
                "viewport"
            ][
                "scroll_x"
            ]
            != twin[
                "viewport"
            ][
                "scroll_x"
            ]
        ):
            mismatches.append(
                "SCROLL_X_MISMATCH"
            )

        if (
            real[
                "viewport"
            ][
                "scroll_y"
            ]
            != twin[
                "viewport"
            ][
                "scroll_y"
            ]
        ):
            mismatches.append(
                "SCROLL_Y_MISMATCH"
            )

        if mismatches:
            status = (
                AUTO_TWIN_CAPTURE_PAIR_INCOMPATIBLE
            )

            reasons = tuple(
                mismatches
            )

        else:
            status = (
                AUTO_TWIN_CAPTURE_PAIR_READY
            )

            reasons = ()

    if (
        twin is None
        and mismatches
    ):
        status = (
            AUTO_TWIN_CAPTURE_PAIR_INCOMPATIBLE
        )

        reasons = tuple(
            mismatches
        ) + (
            "TWIN_CAPTURE_MISSING",
        )

    identity = {
        "twin_key":
            normalized_twin_key,

        "candidate_id":
            normalized_candidate_id,

        "candidate_revision":
            normalized_revision,

        "pathname":
            normalized_pathname,

        "functional_state":
            normalized_state,

        "rendering_profile_id":
            profile[
                "rendering_profile_id"
            ],

        "real_capture_id":
            real[
                "capture_id"
            ],

        "twin_capture_id":
            (
                twin[
                    "capture_id"
                ]
                if twin is not None
                else None
            ),
    }

    return {
        "schema_version":
            AUTO_TWIN_CAPTURE_PAIR_SCHEMA_VERSION,

        "pair_type":
            AUTO_TWIN_CAPTURE_PAIR_TYPE,

        "capture_pair_id":
            _pair_id(
                identity
            ),

        "twin_key":
            normalized_twin_key,

        "candidate_id":
            normalized_candidate_id,

        "candidate_revision":
            normalized_revision,

        # Deliberadamente sin URL/origin.
        "state_identity": {
            "pathname":
                normalized_pathname,

            "functional_state":
                normalized_state,
        },

        "rendering_profile":
            deepcopy(
                profile
            ),

        "real_capture":
            deepcopy(
                real
            ),

        "twin_capture":
            deepcopy(
                twin
            ),

        "status":
            status,

        "reasons":
            reasons,

        "ready_for_comparison":
            (
                status
                == AUTO_TWIN_CAPTURE_PAIR_READY
            ),
    }
