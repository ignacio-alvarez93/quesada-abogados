"""Orquestación gobernada de evaluación AUTO TWIN.

Cadena:

    CandidateRevision
        +
    captura REAL explícita
        +
    captura TWIN explícita
        +
    snapshots / imágenes / behavior traces
        ↓
    CapturePair
        ↓
    Unified Five-Dimension Fidelity
        ↓
    ValidationEvidence
        ↓
    ValidationEvidenceStore

Este módulo NO:

- descubre capturas;
- busca "la última captura";
- ejecuta navegador;
- ejecuta experimentos;
- cambia lifecycle;
- valida candidatos automáticamente;
- materializa TWIN;
- promociona ACTIVE.
"""

from __future__ import annotations

from copy import deepcopy

from .candidate_revision_store import (
    AutoTwinCandidateRevisionStore,
)

from .capture_pair import (
    AUTO_TWIN_CAPTURE_PAIR_READY,
    build_auto_twin_capture_pair,
)

from .unified_comparator import (
    compare_auto_twin_fidelity,
)

from .validation_evidence_store import (
    AutoTwinValidationEvidenceStore,
)


AUTO_TWIN_VALIDATION_EVALUATOR_SCHEMA_VERSION = 1

AUTO_TWIN_VALIDATION_EVALUATOR_TYPE = (
    "QCC_AUTO_TWIN_VALIDATION_EVALUATION"
)


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _capture_id(
    capture,
    *,
    error,
) -> str:
    if not isinstance(
        capture,
        dict,
    ):
        raise TypeError(
            error
        )

    capture_id = _text(
        capture.get(
            "capture_id"
        )
    )

    if not capture_id:
        raise ValueError(
            error
        )

    return capture_id


def _candidate_revision(
    candidate,
) -> int:
    try:
        revision = int(
            candidate.get(
                "candidate_revision"
            )
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CANDIDATE_REVISION_INVALID"
        ) from exc

    if revision <= 0:
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CANDIDATE_REVISION_INVALID"
        )

    return revision


def evaluate_auto_twin_candidate_fidelity(
    *,
    candidate_store,
    evidence_store,
    twin_key,
    candidate_id,
    rendering_profile,
    real_capture,
    twin_capture,
    real_snapshot,
    twin_snapshot,
    real_image_path,
    twin_image_path,
    real_behavior_trace=None,
    twin_behavior_trace=None,
    geometry_tolerance_px=None,
    visual_channel_tolerance=None,
    visual_max_changed_pixel_ratio=None,
) -> dict:
    """Evalúa y persiste evidencia técnica de un candidato.

    La asociación de capturas es explícita.

    ``real_capture.capture_id`` debe pertenecer al conjunto
    ``evidence_capture_ids`` del CandidateRevision.

    La captura TWIN nunca se infiere desde disco ni desde
    otro browser/profile.
    """

    if not isinstance(
        candidate_store,
        AutoTwinCandidateRevisionStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CANDIDATE_STORE_INVALID"
        )

    if not isinstance(
        evidence_store,
        AutoTwinValidationEvidenceStore,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "EVIDENCE_STORE_INVALID"
        )

    normalized_twin_key = _text(
        twin_key
    )

    normalized_candidate_id = _text(
        candidate_id
    )

    if not normalized_twin_key:
        raise ValueError(
            "QCC_AUTO_TWIN_KEY_REQUIRED"
        )

    if not normalized_candidate_id:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
        )

    candidate = (
        candidate_store.get_candidate(
            normalized_twin_key,
            normalized_candidate_id,
        )
    )

    if candidate is None:
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND"
        )

    candidate_revision = (
        _candidate_revision(
            candidate
        )
    )

    pathname = _text(
        candidate.get(
            "pathname"
        )
    )

    if not pathname:
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CANDIDATE_PATHNAME_REQUIRED"
        )

    functional_state = (
        _text(
            candidate.get(
                "functional_state"
            )
        )
        or None
    )

    real_capture_id = (
        _capture_id(
            real_capture,
            error=(
                "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
                "REAL_CAPTURE_INVALID"
            ),
        )
    )

    twin_capture_id = (
        _capture_id(
            twin_capture,
            error=(
                "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
                "TWIN_CAPTURE_INVALID"
            ),
        )
    )

    evidence_capture_ids = {
        _text(
            item
        )
        for item
        in (
            candidate.get(
                "evidence_capture_ids"
            )
            or ()
        )
        if _text(
            item
        )
    }

    if (
        real_capture_id
        not in evidence_capture_ids
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "REAL_CAPTURE_NOT_CANDIDATE_EVIDENCE"
        )

    if (
        real_capture_id
        == twin_capture_id
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CAPTURE_ID_COLLISION"
        )

    capture_pair = (
        build_auto_twin_capture_pair(
            twin_key=(
                normalized_twin_key
            ),
            candidate_id=(
                normalized_candidate_id
            ),
            candidate_revision=(
                candidate_revision
            ),
            pathname=(
                pathname
            ),
            functional_state=(
                functional_state
            ),
            rendering_profile=(
                rendering_profile
            ),
            real_capture=(
                real_capture
            ),
            twin_capture=(
                twin_capture
            ),
        )
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
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "CAPTURE_PAIR_NOT_READY"
        )

    comparator_kwargs = {
        "capture_pair":
            capture_pair,

        "real_snapshot":
            real_snapshot,

        "twin_snapshot":
            twin_snapshot,

        "real_image_path":
            real_image_path,

        "twin_image_path":
            twin_image_path,

        "real_behavior_trace":
            real_behavior_trace,

        "twin_behavior_trace":
            twin_behavior_trace,
    }

    if geometry_tolerance_px is not None:
        comparator_kwargs[
            "geometry_tolerance_px"
        ] = geometry_tolerance_px

    if visual_channel_tolerance is not None:
        comparator_kwargs[
            "visual_channel_tolerance"
        ] = visual_channel_tolerance

    if (
        visual_max_changed_pixel_ratio
        is not None
    ):
        comparator_kwargs[
            "visual_max_changed_pixel_ratio"
        ] = (
            visual_max_changed_pixel_ratio
        )

    comparison = (
        compare_auto_twin_fidelity(
            **comparator_kwargs
        )
    )

    validation_evidence = (
        comparison.get(
            "validation_evidence"
        )
    )

    if not isinstance(
        validation_evidence,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "EVIDENCE_MISSING"
        )

    # Defensa de scope antes de persistir.
    if (
        validation_evidence.get(
            "twin_key"
        )
        != normalized_twin_key
        or validation_evidence.get(
            "candidate_id"
        )
        != normalized_candidate_id
        or validation_evidence.get(
            "candidate_revision"
        )
        != candidate_revision
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVALUATOR_"
            "EVIDENCE_SCOPE_MISMATCH"
        )

    persisted = (
        evidence_store
        .record_validation_evidence(
            validation_evidence
        )
    )

    record = (
        persisted.get(
            "record"
        )
        or {}
    )

    return {
        "schema_version":
            AUTO_TWIN_VALIDATION_EVALUATOR_SCHEMA_VERSION,

        "evaluation_type":
            AUTO_TWIN_VALIDATION_EVALUATOR_TYPE,

        "evaluated":
            True,

        "twin_key":
            normalized_twin_key,

        "candidate_id":
            normalized_candidate_id,

        "candidate_revision":
            candidate_revision,

        "candidate_status":
            candidate.get(
                "status"
            ),

        "capture_pair_id":
            capture_pair.get(
                "capture_pair_id"
            ),

        "real_capture_id":
            real_capture_id,

        "twin_capture_id":
            twin_capture_id,

        "verdict":
            validation_evidence.get(
                "verdict"
            ),

        "ready_for_validation":
            (
                validation_evidence.get(
                    "ready_for_validation"
                )
                is True
            ),

        "evidence_created":
            persisted.get(
                "created"
            )
            is True,

        "evidence_store_revision":
            persisted.get(
                "store_revision"
            ),

        "evidence_id":
            record.get(
                "evidence_id"
            ),

        # Ligera por contrato.
        "validation_evidence":
            deepcopy(
                validation_evidence
            ),
    }
