"""Comparación unificada de fidelidad REAL ↔ TWIN.

Integra las cinco dimensiones requeridas:

- STRUCTURE
- GEOMETRY
- VISUAL
- CATALOGS
- BEHAVIOR

Distingue deliberadamente entre:

    catálogo explícitamente vacío
        -> evidencia disponible

    clave ``catalogs`` ausente
        -> evidencia NOT_AVAILABLE

El resultado puede declarar ``ready_for_validation=True`` cuando
las cinco dimensiones requeridas son PASS.

Eso NO modifica el lifecycle del candidato.
No valida automáticamente.
No promociona ACTIVE.
"""

from __future__ import annotations

from copy import deepcopy

from backend.automation.site_architecture.contract_diff import (
    DEFAULT_GEOMETRY_TOLERANCE_PX,
)

from .behavior_comparator import (
    compare_auto_twin_behavior,
)

from .catalog_comparator import (
    compare_auto_twin_catalogs,
)

from .structural_comparator import (
    compare_auto_twin_structure_geometry,
)

from .validation_evidence import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    AUTO_TWIN_VALIDATION_DIMENSIONS,
    build_auto_twin_validation_evidence,
)

from .visual_comparator import (
    DEFAULT_VISUAL_CHANNEL_TOLERANCE,
    DEFAULT_VISUAL_MAX_CHANGED_PIXEL_RATIO,
    compare_auto_twin_visual,
)


AUTO_TWIN_UNIFIED_COMPARATOR_SCHEMA_VERSION = 1

AUTO_TWIN_UNIFIED_COMPARATOR_TYPE = (
    "QCC_AUTO_TWIN_UNIFIED_FIDELITY_COMPARISON"
)


# Compatibilidad: "core" continúa significando
# las tres dimensiones originalmente implementadas.
AUTO_TWIN_CORE_FIDELITY_DIMENSIONS = (
    "STRUCTURE",
    "GEOMETRY",
    "VISUAL",
)


def _core_verdict(
    checks,
) -> str:
    statuses = tuple(
        checks[
            dimension
        ][
            "status"
        ]
        for dimension
        in AUTO_TWIN_CORE_FIDELITY_DIMENSIONS
    )

    if (
        AUTO_TWIN_VALIDATION_CHECK_FAIL
        in statuses
    ):
        return (
            AUTO_TWIN_VALIDATION_CHECK_FAIL
        )

    if all(
        status
        == AUTO_TWIN_VALIDATION_CHECK_PASS
        for status
        in statuses
    ):
        return (
            AUTO_TWIN_VALIDATION_CHECK_PASS
        )

    return (
        AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
    )


def _catalog_check(
    *,
    capture_pair,
    real_snapshot,
    twin_snapshot,
) -> dict:
    """Obtiene CATALOGS sin convertir ausencia en inventario vacío."""

    real_available = (
        isinstance(
            real_snapshot,
            dict,
        )
        and "catalogs"
        in real_snapshot
    )

    twin_available = (
        isinstance(
            twin_snapshot,
            dict,
        )
        and "catalogs"
        in twin_snapshot
    )

    if (
        not real_available
        or not twin_available
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

        return {
            "status":
                AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,

            "summary":
                "Catalog inventory evidence unavailable.",

            "metrics": {
                "real_available":
                    real_available,

                "twin_available":
                    twin_available,
            },

            "references": {
                "real_capture_id":
                    real_capture.get(
                        "capture_id"
                    ),

                "twin_capture_id":
                    twin_capture.get(
                        "capture_id"
                    ),
            },
        }

    comparison = (
        compare_auto_twin_catalogs(
            capture_pair=(
                capture_pair
            ),
            real_snapshot=(
                real_snapshot
            ),
            twin_snapshot=(
                twin_snapshot
            ),
        )
    )

    return deepcopy(
        comparison[
            "checks"
        ][
            "CATALOGS"
        ]
    )


def _assert_behavior_scope(
    *,
    capture_pair,
    trace,
    side,
):
    """Impide mezclar una traza de otro candidate/TWIN."""

    if trace is None:
        return

    if not isinstance(
        trace,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_UNIFIED_BEHAVIOR_TRACE_INVALID"
        )

    pair_twin_key = str(
        capture_pair.get(
            "twin_key"
        )
        or ""
    ).strip()

    pair_candidate_id = str(
        capture_pair.get(
            "candidate_id"
        )
        or ""
    ).strip()

    trace_twin_key = str(
        trace.get(
            "twin_key"
        )
        or ""
    ).strip()

    trace_candidate_id = str(
        trace.get(
            "candidate_id"
        )
        or ""
    ).strip()

    if (
        trace_twin_key
        != pair_twin_key
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_UNIFIED_BEHAVIOR_TWIN_KEY_MISMATCH"
        )

    if (
        trace_candidate_id
        != pair_candidate_id
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_UNIFIED_BEHAVIOR_CANDIDATE_MISMATCH"
        )

    if side not in {
        "REAL",
        "TWIN",
    }:
        raise ValueError(
            "QCC_AUTO_TWIN_UNIFIED_BEHAVIOR_SIDE_INVALID"
        )


def _behavior_check(
    *,
    capture_pair,
    real_behavior_trace,
    twin_behavior_trace,
) -> dict:
    _assert_behavior_scope(
        capture_pair=(
            capture_pair
        ),
        trace=(
            real_behavior_trace
        ),
        side="REAL",
    )

    _assert_behavior_scope(
        capture_pair=(
            capture_pair
        ),
        trace=(
            twin_behavior_trace
        ),
        side="TWIN",
    )

    comparison = (
        compare_auto_twin_behavior(
            real_trace=(
                real_behavior_trace
            ),
            twin_trace=(
                twin_behavior_trace
            ),
        )
    )

    return deepcopy(
        comparison[
            "checks"
        ][
            "BEHAVIOR"
        ]
    )


def compare_auto_twin_fidelity(
    *,
    capture_pair,
    real_snapshot,
    twin_snapshot,
    real_image_path,
    twin_image_path,
    real_behavior_trace=None,
    twin_behavior_trace=None,
    geometry_tolerance_px=(
        DEFAULT_GEOMETRY_TOLERANCE_PX
    ),
    visual_channel_tolerance=(
        DEFAULT_VISUAL_CHANNEL_TOLERANCE
    ),
    visual_max_changed_pixel_ratio=(
        DEFAULT_VISUAL_MAX_CHANGED_PIXEL_RATIO
    ),
) -> dict:
    """Genera evidencia unificada sin modificar lifecycle."""

    structural = (
        compare_auto_twin_structure_geometry(
            capture_pair=(
                capture_pair
            ),
            real_snapshot=(
                real_snapshot
            ),
            twin_snapshot=(
                twin_snapshot
            ),
            geometry_tolerance_px=(
                geometry_tolerance_px
            ),
        )
    )

    visual = (
        compare_auto_twin_visual(
            capture_pair=(
                capture_pair
            ),
            real_image_path=(
                real_image_path
            ),
            twin_image_path=(
                twin_image_path
            ),
            channel_tolerance=(
                visual_channel_tolerance
            ),
            max_changed_pixel_ratio=(
                visual_max_changed_pixel_ratio
            ),
        )
    )

    checks = {
        "STRUCTURE":
            deepcopy(
                structural[
                    "checks"
                ][
                    "STRUCTURE"
                ]
            ),

        "GEOMETRY":
            deepcopy(
                structural[
                    "checks"
                ][
                    "GEOMETRY"
                ]
            ),

        "VISUAL":
            deepcopy(
                visual[
                    "checks"
                ][
                    "VISUAL"
                ]
            ),

        "CATALOGS":
            _catalog_check(
                capture_pair=(
                    capture_pair
                ),
                real_snapshot=(
                    real_snapshot
                ),
                twin_snapshot=(
                    twin_snapshot
                ),
            ),

        "BEHAVIOR":
            _behavior_check(
                capture_pair=(
                    capture_pair
                ),
                real_behavior_trace=(
                    real_behavior_trace
                ),
                twin_behavior_trace=(
                    twin_behavior_trace
                ),
            ),
    }

    if (
        tuple(
            checks
        )
        != AUTO_TWIN_VALIDATION_DIMENSIONS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_UNIFIED_DIMENSIONS_INVALID"
        )

    core_verdict = (
        _core_verdict(
            checks
        )
    )

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

    state_identity = (
        capture_pair.get(
            "state_identity"
        )
        or {}
    )

    rendering_profile = (
        capture_pair.get(
            "rendering_profile"
        )
        or {}
    )

    evidence = (
        build_auto_twin_validation_evidence(
            twin_key=(
                capture_pair.get(
                    "twin_key"
                )
            ),
            candidate_id=(
                capture_pair.get(
                    "candidate_id"
                )
            ),
            candidate_revision=(
                capture_pair.get(
                    "candidate_revision"
                )
            ),
            real_capture_id=(
                real_capture.get(
                    "capture_id"
                )
            ),
            twin_capture_id=(
                twin_capture.get(
                    "capture_id"
                )
            ),
            pathname=(
                state_identity.get(
                    "pathname"
                )
            ),
            functional_state=(
                state_identity.get(
                    "functional_state"
                )
            ),
            rendering_profile_id=(
                rendering_profile.get(
                    "rendering_profile_id"
                )
            ),

            # Deliberadamente no reducimos required_dimensions.
            # Las cinco dimensiones siguen siendo obligatorias.
            checks=(
                checks
            ),
        )
    )

    # Contrato defensivo:
    # la evidencia debe conservar exactamente el mismo
    # resultado ligero de cada comparador.
    for dimension in (
        AUTO_TWIN_VALIDATION_DIMENSIONS
    ):
        if (
            evidence[
                "checks"
            ][
                dimension
            ][
                "status"
            ]
            != checks[
                dimension
            ][
                "status"
            ]
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_UNIFIED_CHECK_PROJECTION_INVALID"
            )

    return {
        "schema_version":
            AUTO_TWIN_UNIFIED_COMPARATOR_SCHEMA_VERSION,

        "comparison_type":
            AUTO_TWIN_UNIFIED_COMPARATOR_TYPE,

        "capture_pair_id":
            capture_pair.get(
                "capture_pair_id"
            ),

        "core_dimensions":
            AUTO_TWIN_CORE_FIDELITY_DIMENSIONS,

        "core_fidelity_verdict":
            core_verdict,

        "core_fidelity_pass":
            (
                core_verdict
                == AUTO_TWIN_VALIDATION_CHECK_PASS
            ),

        "checks":
            deepcopy(
                checks
            ),

        "validation_evidence":
            evidence,
    }
