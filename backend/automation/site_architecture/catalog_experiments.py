"""Análisis canónico de experimentos activos de catálogos QCC."""

from __future__ import annotations

from .catalog_dynamics import (
    build_catalog_causal_relations,
    build_catalog_dynamic_evidence,
)
from .normalizer import (
    normalize_dom_capture,
)
from .qcc_capture_adapter import (
    adapt_qcc_extension_capture,
)


QCC_CATALOG_EXPERIMENT_TYPE = (
    "QCC_CATALOG_EXPERIMENT"
)

QCC_CATALOG_EXPERIMENT_SAFETY_TWIN_ONLY = (
    "TWIN_ONLY"
)

QCC_CATALOG_EXPERIMENT_TWIN_ORIGIN = (
    "http://127.0.0.1:8767"
)


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _snapshot_from_qcc_capture(
    capture,
):
    raw = adapt_qcc_extension_capture(
        capture
    )

    return normalize_dom_capture(
        raw
    )


def _resolve_source_catalog_key(
    catalogs,
    selector,
):
    selector = _text(
        selector
    )

    matches = [
        catalog
        for catalog in catalogs
        if (
            _text(
                catalog.get(
                    "frame_path"
                )
            ) == "main"
            and _text(
                catalog.get(
                    "selector"
                )
            ) == selector
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_SOURCE_AMBIGUOUS"
        )

    key = _text(
        matches[0].get(
            "catalog_key"
        )
    )

    if not key:
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_SOURCE_KEY_MISSING"
        )

    return key


def _capture_main_origin(
    capture,
):
    if not isinstance(
        capture,
        dict,
    ):
        return ""

    frames = (
        capture.get("frames")
        or ()
    )

    for frame in frames:
        if (
            isinstance(frame, dict)
            and frame.get("frame_id") == 0
        ):
            result = (
                frame.get("result")
                or {}
            )

            if isinstance(
                result,
                dict,
            ):
                return _text(
                    result.get("origin")
                )

    return ""


def _catalog_restore_signature(
    catalog,
):
    state = (
        catalog.get("state")
        or {}
    )

    selected_values = (
        state.get("selected_values")
        or ()
    )

    options = []

    for option in (
        catalog.get("options")
        or ()
    ):
        if not isinstance(
            option,
            dict,
        ):
            continue

        options.append((
            _text(
                option.get("value")
            ),
            _text(
                option.get("label")
            ),
            bool(
                option.get("disabled")
            ),
        ))

    return (
        _text(
            state.get(
                "selected_value"
            )
        ),
        tuple(
            _text(value)
            for value
            in selected_values
        ),
        tuple(options),
    )


def _assert_restored_exact(
    before_catalogs,
    restored_catalogs,
):
    before = {
        _text(
            catalog.get(
                "catalog_key"
            )
        ):
            catalog
        for catalog
        in before_catalogs
        if isinstance(
            catalog,
            dict,
        )
        and _text(
            catalog.get(
                "catalog_key"
            )
        )
    }

    restored = {
        _text(
            catalog.get(
                "catalog_key"
            )
        ):
            catalog
        for catalog
        in restored_catalogs
        if isinstance(
            catalog,
            dict,
        )
        and _text(
            catalog.get(
                "catalog_key"
            )
        )
    }

    if set(before) != set(restored):
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_RESTORE_CATALOG_SET_MISMATCH"
        )

    for key in before:
        if (
            _catalog_restore_signature(
                before[key]
            )
            != _catalog_restore_signature(
                restored[key]
            )
        ):
            raise ValueError(
                "QCC_CATALOG_EXPERIMENT_RESTORE_STATE_MISMATCH"
            )


def analyze_qcc_catalog_experiment(
    experiment,
):
    """Convierte un experimento QCC validado en evidencia dinámica."""

    if not isinstance(
        experiment,
        dict,
    ):
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_INVALID"
        )

    if (
        experiment.get(
            "experiment_type"
        )
        != QCC_CATALOG_EXPERIMENT_TYPE
    ):
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_TYPE_INVALID"
        )

    if (
        experiment.get(
            "safety_mode"
        )
        != QCC_CATALOG_EXPERIMENT_SAFETY_TWIN_ONLY
    ):
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_SAFETY_INVALID"
        )

    verification = (
        experiment.get(
            "restoration_verification"
        )
        or {}
    )

    if (
        verification.get(
            "exact"
        )
        is not True
    ):
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_NOT_RESTORED"
        )

    before_capture = (
        experiment.get(
            "before"
        )
    )

    after_capture = (
        experiment.get(
            "after"
        )
    )

    restored_capture = (
        experiment.get(
            "restored"
        )
    )

    if (
        not isinstance(
            before_capture,
            dict,
        )
        or not isinstance(
            after_capture,
            dict,
        )
        or not isinstance(
            restored_capture,
            dict,
        )
    ):
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_CAPTURE_MISSING"
        )

    declared_origin = _text(
        experiment.get(
            "origin"
        )
    )

    capture_origins = {
        _capture_main_origin(
            before_capture
        ),
        _capture_main_origin(
            after_capture
        ),
        _capture_main_origin(
            restored_capture
        ),
    }

    if (
        declared_origin
        != QCC_CATALOG_EXPERIMENT_TWIN_ORIGIN
        or capture_origins
        != {
            QCC_CATALOG_EXPERIMENT_TWIN_ORIGIN
        }
    ):
        raise ValueError(
            "QCC_CATALOG_EXPERIMENT_ORIGIN_INVALID"
        )

    before = _snapshot_from_qcc_capture(
        before_capture
    )

    after = _snapshot_from_qcc_capture(
        after_capture
    )

    restored = _snapshot_from_qcc_capture(
        restored_capture
    )

    _assert_restored_exact(
        before.catalogs,
        restored.catalogs,
    )

    selector = _text(
        experiment.get(
            "selector"
        )
    )

    source_catalog_key = (
        _resolve_source_catalog_key(
            before.catalogs,
            selector,
        )
    )

    evidence = (
        build_catalog_dynamic_evidence(
            before.catalogs,
            after.catalogs,
            source_catalog_key=(
                source_catalog_key
            ),
        )
    )

    causal_relations = (
        build_catalog_causal_relations(
            evidence
        )
    )

    return {
        "source_catalog_key":
            source_catalog_key,

        "selector":
            selector,

        "evidence":
            evidence,

        "evidence_count":
            len(evidence),

        "causal_relations":
            causal_relations,

        "causal_relation_count":
            len(
                causal_relations
            ),

        "restoration_exact":
            True,

        "compared_catalogs":
            int(
                verification.get(
                    "compared_catalogs"
                )
                or 0
            ),
    }
