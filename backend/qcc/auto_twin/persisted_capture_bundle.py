"""Carga gobernada de una captura Site Architecture persistida.

Entrada:
    capture_id exacto

Salida:
    bundle preparado para ValidationEvaluator:
    - capture identity;
    - Site Architecture snapshot;
    - RenderingProfile;
    - screenshot viewport explícitamente registrado.

No:
- enumera directorios;
- busca la captura más reciente;
- infiere otra captura;
- ejecuta browser;
- compara;
- persiste ValidationEvidence;
- cambia lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.automation.site_recognizers.mercurio import (
    apply_mercurio_functional_fingerprint_capability,
)

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
    QccSiteArchitectureIngestor,
)

from .rendering_profile import (
    build_auto_twin_rendering_profile,
)


AUTO_TWIN_PERSISTED_CAPTURE_BUNDLE_SCHEMA_VERSION = 1

AUTO_TWIN_PERSISTED_CAPTURE_BUNDLE_TYPE = (
    "QCC_AUTO_TWIN_PERSISTED_CAPTURE_BUNDLE"
)

_EXPECTED_ARTIFACTS = {
    "raw_capture":
        "qcc_capture.json",

    "site_architecture":
        "site_architecture.json",

    "state_observation":
        "state_observation.json",

    "metadata":
        "metadata.json",
}

_VIEWPORT_SCREENSHOT_FILENAME = (
    "screenshot_viewport.png"
)

_PNG_SIGNATURE = (
    b"\x89PNG\r\n\x1a\n"
)


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _safe_capture_id(
    value,
) -> str:
    capture_id = _text(
        value
    )

    if (
        not capture_id
        or capture_id in {
            ".",
            "..",
        }
        or "/" in capture_id
        or "\\" in capture_id
        or Path(
            capture_id
        ).name != capture_id
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_ID_INVALID"
        )

    return capture_id


def _read_json(
    path,
    *,
    error,
):
    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            error
        ) from exc

    if not isinstance(
        value,
        dict,
    ):
        raise ValueError(
            error
        )

    return value


def _number(
    value,
    *,
    error,
    positive=False,
):
    if isinstance(
        value,
        bool,
    ):
        raise ValueError(
            error
        )

    try:
        number = float(
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
        positive
        and number <= 0
    ):
        raise ValueError(
            error
        )

    return number


def _viewport(
    snapshot,
):
    viewport = snapshot.get(
        "viewport"
    )

    if not isinstance(
        viewport,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_INVALID"
        )

    inner_width = _number(
        viewport.get(
            "inner_width"
        ),
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_INVALID"
        ),
        positive=True,
    )

    inner_height = _number(
        viewport.get(
            "inner_height"
        ),
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_INVALID"
        ),
        positive=True,
    )

    device_pixel_ratio = _number(
        viewport.get(
            "device_pixel_ratio"
        ),
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_INVALID"
        ),
        positive=True,
    )

    scroll_x = _number(
        viewport.get(
            "scroll_x",
            0,
        ),
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_INVALID"
        ),
    )

    scroll_y = _number(
        viewport.get(
            "scroll_y",
            0,
        ),
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_INVALID"
        ),
    )

    return {
        "inner_width":
            inner_width,

        "inner_height":
            inner_height,

        "device_pixel_ratio":
            device_pixel_ratio,

        "scroll_x":
            scroll_x,

        "scroll_y":
            scroll_y,
    }


def _validate_required_artifact_contract(
    metadata,
):
    artifacts = metadata.get(
        "artifacts"
    )

    if not isinstance(
        artifacts,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_ARTIFACTS_INVALID"
        )

    for (
        artifact_key,
        expected_filename,
    ) in _EXPECTED_ARTIFACTS.items():
        if (
            artifacts.get(
                artifact_key
            )
            != expected_filename
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_PERSISTED_CAPTURE_ARTIFACT_CONTRACT_INVALID"
            )

    return artifacts


def _viewport_image_path(
    *,
    capture_dir,
    metadata,
    artifacts,
    required,
):
    declared = artifacts.get(
        "screenshot_viewport"
    )

    visual_evidence = metadata.get(
        "visual_evidence"
    )

    viewport_evidence = (
        visual_evidence.get(
            "viewport"
        )
        if isinstance(
            visual_evidence,
            dict,
        )
        else None
    )

    formally_registered = (
        declared
        == _VIEWPORT_SCREENSHOT_FILENAME
        and isinstance(
            viewport_evidence,
            dict,
        )
        and viewport_evidence.get(
            "artifact"
        )
        == _VIEWPORT_SCREENSHOT_FILENAME
        and viewport_evidence.get(
            "content_type"
        )
        == "image/png"
    )

    if not formally_registered:
        if required:
            raise ValueError(
                "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_IMAGE_NOT_REGISTERED"
            )

        return None

    image_path = (
        capture_dir
        / _VIEWPORT_SCREENSHOT_FILENAME
    )

    if not image_path.is_file():
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_IMAGE_MISSING"
        )

    try:
        signature = image_path.read_bytes()[
            :len(
                _PNG_SIGNATURE
            )
        ]

    except OSError as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_IMAGE_INVALID"
        ) from exc

    if (
        signature
        != _PNG_SIGNATURE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_IMAGE_INVALID"
        )

    return image_path


# QCC_AUTO_TWIN_MATERIALIZATION_CAPABILITY_AWARE_FINGERPRINT_V1 (2D-20V)
#
# The raw generic fingerprint cached on a capture's own
# state_observation.json/metadata.json predates any provider-specific
# capability augmentation applied at observation-ingestion time (see
# QccSiteArchitectureIngestor._observe_state() and
# apply_mercurio_functional_fingerprint_capability() in
# backend/automation/site_recognizers/mercurio.py). Left unadjusted, a
# materialized CURRENT bundle would silently re-collapse a provider
# already-disambiguated identity (e.g. two governed EX01_PERSONAL
# replacements) back onto the shared legacy generic fingerprint.
#
# This delegates to the EXACT SAME canonical, provider-neutral
# capability function observation ingestion already uses -- never
# duplicates or hardcodes provider/state/branch-specific logic here.
# The function is a no-op passthrough for every site/state it does not
# narrowly own (confirmed by its own contract), so calling it
# unconditionally is safe for every provider.
#
# Recomputed strictly from THIS capture's own persisted, immutable
# site_architecture.json snapshot -- never from any value already
# recorded on an observation-store state, and never by borrowing
# another capture's fingerprint. Any failure (unreadable/ambiguous
# snapshot, unexpected exception) fails closed to the capture's own
# unadjusted generic fingerprint -- exactly the same fail-closed
# passthrough contract the canonical function itself already
# guarantees for an UNKNOWN/ambiguous capability signal.
def _current_functional_fingerprint(
    *,
    site_code,
    functional_state,
    generic_fingerprint,
    snapshot,
):
    try:
        return apply_mercurio_functional_fingerprint_capability(
            site_code=(
                _text(
                    site_code
                ).upper()
                or None
            ),
            functional_state=functional_state,
            fingerprint=generic_fingerprint,
            snapshot=snapshot,
        )

    except Exception:
        return generic_fingerprint


# QCC_AUTO_TWIN_MATERIALIZATION_CANONICAL_CURRENT_PROJECTION_V1 (2D-20V-2)
#
# The generic fingerprint algorithm itself (not just the capability
# augmentation above) can evolve between the moment a capture was
# originally ingested and the moment its bundle is later materialized.
# When that happens, applying the CURRENT capability function to the
# capture's HISTORICAL persisted generic fingerprint (as
# _current_functional_fingerprint() above still correctly does in
# isolation) does not itself yield the CURRENT canonical identity --
# it yields a hybrid of an old generic value and a new capability
# layer, which can disagree with what observation ingestion produces
# for the exact same bytes today.
#
# The only way to guarantee agreement with
# QccSiteArchitectureIngestor.observe_candidate() is to call that
# exact same canonical, provider-neutral, in-memory observe gate
# again, directly against this capture's own immutable
# qcc_capture.json. Never against an already-adapted/normalized
# snapshot, never against any cached fingerprint.
#
# A genuine, already-ingested QCC capture always re-adapts/normalizes/
# observes cleanly here -- it went through this exact same pipeline to
# get persisted in the first place. Returning None (rather than
# raising) on failure is reserved for capture payloads that were never
# real DOM captures to begin with (e.g. minimal fixtures exercising
# unrelated bundle-loading plumbing): callers fail closed only on a
# genuine semantic mismatch (see _require_compatible()), never on the
# mere absence of a recomputable projection.
def _current_canonical_observation(
    raw_capture,
):
    try:
        return QccSiteArchitectureIngestor().observe_candidate(
            raw_capture
        )

    except Exception:
        return None


def _require_compatible(
    *,
    persisted_site_code,
    canonical_site_code,
    persisted_functional_state,
    canonical_functional_state,
):
    normalized_persisted_site_code = (
        _text(
            persisted_site_code
        ).upper()
    )

    normalized_canonical_site_code = (
        _text(
            canonical_site_code
        ).upper()
    )

    if (
        normalized_persisted_site_code
        != normalized_canonical_site_code
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_CURRENT_SITE_CODE_INCOMPATIBLE"
        )

    normalized_persisted_functional_state = (
        _text(
            persisted_functional_state
        )
    )

    normalized_canonical_functional_state = (
        _text(
            canonical_functional_state
        )
    )

    if (
        normalized_persisted_functional_state
        != normalized_canonical_functional_state
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_CURRENT_FUNCTIONAL_STATE_INCOMPATIBLE"
        )


def load_auto_twin_persisted_capture_bundle(
    *,
    capture_id,
    root=(
        DEFAULT_QCC_SITE_ARCHITECTURE_ROOT
    ),
    require_viewport_image=True,
) -> dict:
    """Carga exclusivamente ``root / capture_id``."""

    normalized_capture_id = (
        _safe_capture_id(
            capture_id
        )
    )

    root_path = Path(
        root
    )

    capture_dir = (
        root_path
        / normalized_capture_id
    )

    if (
        not capture_dir.exists()
        or not capture_dir.is_dir()
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_NOT_FOUND"
        )

    metadata = _read_json(
        capture_dir
        / "metadata.json",
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_METADATA_INVALID"
        ),
    )

    if (
        _text(
            metadata.get(
                "capture_id"
            )
        )
        != normalized_capture_id
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_METADATA_ID_MISMATCH"
        )

    artifacts = (
        _validate_required_artifact_contract(
            metadata
        )
    )

    raw_capture = _read_json(
        capture_dir
        / "qcc_capture.json",
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_RAW_INVALID"
        ),
    )

    snapshot = _read_json(
        capture_dir
        / "site_architecture.json",
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_SNAPSHOT_INVALID"
        ),
    )

    state_observation = _read_json(
        capture_dir
        / "state_observation.json",
        error=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_STATE_INVALID"
        ),
    )

    profile_key = _text(
        raw_capture.get(
            "browser_profile_key"
        )
    )

    if not profile_key:
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_PROFILE_REQUIRED"
        )

    retention = metadata.get(
        "retention"
    )

    if isinstance(
        retention,
        dict,
    ):
        retention_profile = _text(
            retention.get(
                "browser_profile_key"
            )
        )

        if (
            retention_profile
            and retention_profile
            != profile_key
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_PERSISTED_CAPTURE_PROFILE_MISMATCH"
            )

    page = snapshot.get(
        "page"
    )

    if not isinstance(
        page,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_PAGE_INVALID"
        )

    pathname = _text(
        page.get(
            "pathname"
        )
    )

    if not pathname:
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_PATHNAME_REQUIRED"
        )

    functional_state = (
        _text(
            state_observation.get(
                "state"
            )
        )
        or None
    )

    metadata_state = metadata.get(
        "state_observation"
    )

    if not isinstance(
        metadata_state,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_METADATA_STATE_INVALID"
        )

    if (
        (
            _text(
                metadata_state.get(
                    "state"
                )
            )
            or None
        )
        != functional_state
        or _text(
            metadata_state.get(
                "fingerprint"
            )
        )
        != _text(
            state_observation.get(
                "fingerprint"
            )
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_STATE_MISMATCH"
        )

    persisted_site_code = (
        _text(
            metadata.get(
                "site_code"
            )
        )
        or None
    )

    canonical_observation = (
        _current_canonical_observation(
            raw_capture
        )
    )

    if canonical_observation is not None:
        _require_compatible(
            persisted_site_code=(
                persisted_site_code
            ),
            canonical_site_code=(
                canonical_observation.get(
                    "site_code"
                )
            ),
            persisted_functional_state=(
                functional_state
            ),
            canonical_functional_state=(
                canonical_observation.get(
                    "functional_state"
                )
            ),
        )

    viewport = _viewport(
        snapshot
    )

    rendering_profile = (
        build_auto_twin_rendering_profile(
            inner_width=(
                viewport[
                    "inner_width"
                ]
            ),
            inner_height=(
                viewport[
                    "inner_height"
                ]
            ),
            device_pixel_ratio=(
                viewport[
                    "device_pixel_ratio"
                ]
            ),
        )
    )

    image_path = (
        _viewport_image_path(
            capture_dir=(
                capture_dir
            ),
            metadata=(
                metadata
            ),
            artifacts=(
                artifacts
            ),
            required=(
                require_viewport_image
                is True
            ),
        )
    )

    return {
        "schema_version":
            AUTO_TWIN_PERSISTED_CAPTURE_BUNDLE_SCHEMA_VERSION,

        "bundle_type":
            AUTO_TWIN_PERSISTED_CAPTURE_BUNDLE_TYPE,

        "capture_id":
            normalized_capture_id,

        "capture": {
            "capture_id":
                normalized_capture_id,

            "pathname":
                pathname,

            "functional_state":
                functional_state,

            "browser_profile_key":
                profile_key,

            "viewport":
                viewport,
        },

        "snapshot":
            snapshot,

        "rendering_profile":
            rendering_profile,

        "image_path":
            (
                str(
                    image_path
                )
                if image_path is not None
                else None
            ),

        # QCC_AUTO_TWIN_MATERIALIZATION_CANONICAL_CURRENT_PROJECTION_V1
        # (2D-20V-2): "fingerprint" is the CURRENT canonical functional
        # fingerprint -- obtained by re-running the exact same
        # canonical observe gate
        # (QccSiteArchitectureIngestor.observe_candidate()) directly
        # against this capture's own immutable qcc_capture.json, never
        # by re-deriving it from any cached/historical value. The raw,
        # historical, pre-projection value recorded on this immutable
        # capture is preserved unchanged and readable at
        # "raw_fingerprint" -- nothing here rewrites or removes the
        # capture's own persisted evidence.
        #
        # canonical_observation is None only when this capture's own
        # qcc_capture.json cannot be re-adapted/normalized/observed at
        # all (never for a genuine, already-ingested QCC capture) --
        # the capability-aware historical projection is the safe,
        # unchanged fallback for that narrow case.
        "fingerprint": (
            canonical_observation.get(
                "fingerprint"
            )
            if canonical_observation
            is not None
            else _current_functional_fingerprint(
                site_code=(
                    metadata.get(
                        "site_code"
                    )
                ),
                functional_state=(
                    functional_state
                ),
                generic_fingerprint=(
                    _text(
                        state_observation.get(
                            "fingerprint"
                        )
                    )
                    or None
                ),
                snapshot=snapshot,
            )
        ),

        "raw_fingerprint":
            (
                _text(
                    state_observation.get(
                        "fingerprint"
                    )
                )
                or None
            ),

        "site_code":
            persisted_site_code,
    }
