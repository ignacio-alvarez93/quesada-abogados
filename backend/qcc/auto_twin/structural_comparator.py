"""Comparador estructural/geométrico REAL ↔ TWIN.

Reutiliza el contrato canónico Site Architecture, pero neutraliza
la infraestructura de origen porque REAL y TWIN viven necesariamente
en origins distintos.

No modifica candidates.
No materializa TWINs.
No promociona ACTIVE.
"""

from __future__ import annotations

from copy import deepcopy

from backend.automation.site_architecture.contract_diff import (
    DEFAULT_GEOMETRY_TOLERANCE_PX,
    GEOMETRY_CHANGED,
    INTERACTION_CHANGED,
    SELECTOR_CHANGED,
    SEMANTICS_CHANGED,
    diff_site_architecture,
)

from .capture_pair import (
    AUTO_TWIN_CAPTURE_PAIR_READY,
)

from .validation_evidence import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
)


AUTO_TWIN_STRUCTURAL_COMPARATOR_SCHEMA_VERSION = 1

AUTO_TWIN_STRUCTURAL_COMPARATOR_TYPE = (
    "QCC_AUTO_TWIN_STRUCTURAL_GEOMETRY_COMPARISON"
)


def _canonical_snapshot(
    value,
):
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_SNAPSHOT_INVALID"
        )

    result = deepcopy(
        value
    )

    page = result.get(
        "page"
    )

    if isinstance(
        page,
        dict,
    ):
        pathname = str(
            page.get(
                "pathname"
            )
            or ""
        ).strip()

        # REAL y TWIN nunca compartirán origin/url.
        # Los hacemos equivalentes sin ocultar pathname,
        # query, title ni signature.
        page[
            "origin"
        ] = "qcc://auto-twin-comparison"

        page[
            "url"
        ] = (
            "qcc://auto-twin-comparison"
            + (
                pathname
                if pathname.startswith("/")
                else (
                    "/"
                    + pathname
                    if pathname
                    else "/"
                )
            )
        )

    return result


def _status(
    *,
    failed,
    inconclusive,
):
    if failed:
        return (
            AUTO_TWIN_VALIDATION_CHECK_FAIL
        )

    if inconclusive:
        return (
            AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
        )

    return (
        AUTO_TWIN_VALIDATION_CHECK_PASS
    )


def compare_auto_twin_structure_geometry(
    *,
    capture_pair,
    real_snapshot,
    twin_snapshot,
    geometry_tolerance_px=(
        DEFAULT_GEOMETRY_TOLERANCE_PX
    ),
) -> dict:
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

    real = _canonical_snapshot(
        real_snapshot
    )

    twin = _canonical_snapshot(
        twin_snapshot
    )

    diff = diff_site_architecture(
        real,
        twin,
        geometry_tolerance_px=(
            geometry_tolerance_px
        ),
    )

    counts = diff.get(
        "counts"
    )

    if not isinstance(
        counts,
        dict,
    ):
        counts = {}

    added_count = int(
        counts.get(
            "ADDED"
        )
        or 0
    )

    removed_count = int(
        counts.get(
            "REMOVED"
        )
        or 0
    )

    semantic_changes = 0
    selector_changes = 0
    interaction_changes = 0
    geometry_changes = 0

    structural_changed_elements = 0

    for element in (
        diff.get(
            "elements"
        )
        or ()
    ):
        if not isinstance(
            element,
            dict,
        ):
            continue

        reasons = tuple(
            element.get(
                "changes"
            )
            or ()
        )

        structural_reasons = tuple(
            reason
            for reason in reasons
            if reason != GEOMETRY_CHANGED
        )

        if structural_reasons:
            structural_changed_elements += 1

        if (
            SEMANTICS_CHANGED
            in reasons
        ):
            semantic_changes += 1

        if (
            SELECTOR_CHANGED
            in reasons
        ):
            selector_changes += 1

        if (
            INTERACTION_CHANGED
            in reasons
        ):
            interaction_changes += 1

        if (
            GEOMETRY_CHANGED
            in reasons
        ):
            geometry_changes += 1

    page = diff.get(
        "page"
    )

    page_changed = (
        isinstance(
            page,
            dict,
        )
        and page.get(
            "changed"
        )
        is True
    )

    unmatched_before_count = len(
        tuple(
            diff.get(
                "unmatched_before"
            )
            or ()
        )
    )

    unmatched_after_count = len(
        tuple(
            diff.get(
                "unmatched_after"
            )
            or ()
        )
    )

    inconclusive = (
        diff.get(
            "inconclusive"
        )
        is True
    )

    structure_failed = (
        page_changed
        or added_count > 0
        or removed_count > 0
        or structural_changed_elements > 0
    )

    geometry_failed = (
        geometry_changes > 0
    )

    structure_status = _status(
        failed=structure_failed,
        inconclusive=inconclusive,
    )

    geometry_status = _status(
        failed=geometry_failed,
        inconclusive=inconclusive,
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
    }

    structure_summary = (
        "Structural contract equivalent."
        if (
            structure_status
            == AUTO_TWIN_VALIDATION_CHECK_PASS
        )
        else (
            "Structural comparison inconclusive."
            if (
                structure_status
                == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
            )
            else
            "Structural differences detected."
        )
    )

    geometry_summary = (
        "Geometry within tolerance."
        if (
            geometry_status
            == AUTO_TWIN_VALIDATION_CHECK_PASS
        )
        else (
            "Geometry comparison inconclusive."
            if (
                geometry_status
                == AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
            )
            else
            "Geometry exceeds tolerance."
        )
    )

    return {
        "schema_version":
            AUTO_TWIN_STRUCTURAL_COMPARATOR_SCHEMA_VERSION,

        "comparison_type":
            AUTO_TWIN_STRUCTURAL_COMPARATOR_TYPE,

        "capture_pair_id":
            capture_pair.get(
                "capture_pair_id"
            ),

        "geometry_tolerance_px":
            diff.get(
                "geometry_tolerance_px"
            ),

        "checks": {
            "STRUCTURE": {
                "status":
                    structure_status,

                "summary":
                    structure_summary,

                "metrics": {
                    "page_changed":
                        page_changed,

                    "added_elements":
                        added_count,

                    "removed_elements":
                        removed_count,

                    "changed_elements":
                        structural_changed_elements,

                    "semantic_changes":
                        semantic_changes,

                    "selector_changes":
                        selector_changes,

                    "interaction_changes":
                        interaction_changes,

                    "unmatched_before":
                        unmatched_before_count,

                    "unmatched_after":
                        unmatched_after_count,
                },

                "references":
                    deepcopy(
                        references
                    ),
            },

            "GEOMETRY": {
                "status":
                    geometry_status,

                "summary":
                    geometry_summary,

                "metrics": {
                    "changed_elements":
                        geometry_changes,

                    "tolerance_px":
                        diff.get(
                            "geometry_tolerance_px"
                        ),

                    "unmatched_before":
                        unmatched_before_count,

                    "unmatched_after":
                        unmatched_after_count,
                },

                "references":
                    deepcopy(
                        references
                    ),
            },
        },

        "inconclusive":
            inconclusive,

        # Resumen ligero. Nunca devolvemos el diff completo
        # ni snapshots pesados desde este contrato.
        "summary": {
            "structure_status":
                structure_status,

            "geometry_status":
                geometry_status,

            "page_changed":
                page_changed,

            "added_elements":
                added_count,

            "removed_elements":
                removed_count,

            "structural_changed_elements":
                structural_changed_elements,

            "geometry_changed_elements":
                geometry_changes,

            "unmatched_before":
                unmatched_before_count,

            "unmatched_after":
                unmatched_after_count,
        },
    }
