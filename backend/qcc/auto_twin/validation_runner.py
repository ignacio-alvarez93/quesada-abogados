"""Runner gobernado de validación técnica AUTO TWIN.

Cadena:

    TWIN capture_id explícito
        ↓
    PersistedCaptureBundle(TWIN)
        ↓
    ValidationTrigger resolver
        ↓
      READY
        ↓
    PersistedCaptureBundle(REAL exacto del candidato)
        ↓
    ValidationEvaluator
        ↓
    ValidationEvidenceStore

No:
- descubre capturas;
- enumera directorios;
- ejecuta navegador;
- crea comportamiento;
- cambia CandidateRevision;
- valida automáticamente;
- materializa;
- promociona.
"""

from __future__ import annotations

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
)

from .persisted_capture_bundle import (
    load_auto_twin_persisted_capture_bundle,
)

from .validation_evaluator import (
    evaluate_auto_twin_candidate_fidelity,
)

from .validation_trigger import (
    AUTO_TWIN_VALIDATION_TRIGGER_AMBIGUOUS,
    AUTO_TWIN_VALIDATION_TRIGGER_READY,
    resolve_auto_twin_validation_trigger,
)


AUTO_TWIN_VALIDATION_RUNNER_SCHEMA_VERSION = 1

AUTO_TWIN_VALIDATION_RUNNER_TYPE = (
    "QCC_AUTO_TWIN_VALIDATION_RUN"
)

AUTO_TWIN_VALIDATION_RUNNER_EVALUATED = (
    "EVALUATED"
)

AUTO_TWIN_VALIDATION_RUNNER_SKIPPED = (
    "SKIPPED"
)

AUTO_TWIN_VALIDATION_RUNNER_AMBIGUOUS = (
    "AMBIGUOUS"
)


def _result(
    *,
    status,
    twin_capture_id,
    decision,
    evaluation=None,
):
    return {
        "schema_version":
            AUTO_TWIN_VALIDATION_RUNNER_SCHEMA_VERSION,

        "run_type":
            AUTO_TWIN_VALIDATION_RUNNER_TYPE,

        "status":
            status,

        "twin_capture_id":
            twin_capture_id,

        "decision":
            decision,

        "evaluated":
            evaluation is not None,

        "evaluation":
            evaluation,
    }


def run_auto_twin_validation_evaluation(
    *,
    managed_twin,
    profile_policy,
    candidate_store,
    evidence_store,
    twin_capture_id,
    capture_root=(
        DEFAULT_QCC_SITE_ARCHITECTURE_ROOT
    ),
    real_behavior_trace=None,
    twin_behavior_trace=None,
    geometry_tolerance_px=None,
    visual_channel_tolerance=None,
    visual_max_changed_pixel_ratio=None,
) -> dict:
    """Ejecuta validación solo desde referencias explícitas.

    La captura TWIN se carga primero por el ``capture_id``
    suministrado por el runtime que acaba de producirla.

    La captura REAL solo puede proceder de la decisión del
    resolver y, por tanto, del propio CandidateRevision.
    """

    twin_bundle = (
        load_auto_twin_persisted_capture_bundle(
            capture_id=(
                twin_capture_id
            ),
            root=(
                capture_root
            ),
            require_viewport_image=True,
        )
    )

    decision = (
        resolve_auto_twin_validation_trigger(
            managed_twin=(
                managed_twin
            ),
            profile_policy=(
                profile_policy
            ),
            candidate_store=(
                candidate_store
            ),
            twin_capture=(
                twin_bundle[
                    "capture"
                ]
            ),
        )
    )

    decision_status = (
        decision.get(
            "status"
        )
    )

    if (
        decision_status
        == AUTO_TWIN_VALIDATION_TRIGGER_AMBIGUOUS
    ):
        return _result(
            status=(
                AUTO_TWIN_VALIDATION_RUNNER_AMBIGUOUS
            ),
            twin_capture_id=(
                twin_bundle[
                    "capture_id"
                ]
            ),
            decision=(
                decision
            ),
        )

    if (
        decision_status
        != AUTO_TWIN_VALIDATION_TRIGGER_READY
    ):
        return _result(
            status=(
                AUTO_TWIN_VALIDATION_RUNNER_SKIPPED
            ),
            twin_capture_id=(
                twin_bundle[
                    "capture_id"
                ]
            ),
            decision=(
                decision
            ),
        )

    real_capture_id = (
        decision.get(
            "real_capture_id"
        )
    )

    real_bundle = (
        load_auto_twin_persisted_capture_bundle(
            capture_id=(
                real_capture_id
            ),
            root=(
                capture_root
            ),
            require_viewport_image=True,
        )
    )

    # Defensa adicional:
    # el loader debe devolver exactamente el locator decidido.
    if (
        real_bundle.get(
            "capture_id"
        )
        != real_capture_id
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_RUNNER_"
            "REAL_CAPTURE_ID_MISMATCH"
        )

    if (
        twin_bundle.get(
            "capture_id"
        )
        != decision.get(
            "twin_capture_id"
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_RUNNER_"
            "TWIN_CAPTURE_ID_MISMATCH"
        )

    evaluator_kwargs = {
        "candidate_store":
            candidate_store,

        "evidence_store":
            evidence_store,

        "twin_key":
            decision[
                "twin_key"
            ],

        "candidate_id":
            decision[
                "candidate_id"
            ],

        # El perfil representa el entorno físico
        # esperado para la comparación.
        #
        # CapturePair volverá a comprobar que REAL
        # y TWIN son compatibles con él.
        "rendering_profile":
            twin_bundle[
                "rendering_profile"
            ],

        "real_capture":
            real_bundle[
                "capture"
            ],

        "twin_capture":
            twin_bundle[
                "capture"
            ],

        "real_snapshot":
            real_bundle[
                "snapshot"
            ],

        "twin_snapshot":
            twin_bundle[
                "snapshot"
            ],

        "real_image_path":
            real_bundle[
                "image_path"
            ],

        "twin_image_path":
            twin_bundle[
                "image_path"
            ],

        "real_behavior_trace":
            real_behavior_trace,

        "twin_behavior_trace":
            twin_behavior_trace,
    }

    if (
        geometry_tolerance_px
        is not None
    ):
        evaluator_kwargs[
            "geometry_tolerance_px"
        ] = (
            geometry_tolerance_px
        )

    if (
        visual_channel_tolerance
        is not None
    ):
        evaluator_kwargs[
            "visual_channel_tolerance"
        ] = (
            visual_channel_tolerance
        )

    if (
        visual_max_changed_pixel_ratio
        is not None
    ):
        evaluator_kwargs[
            "visual_max_changed_pixel_ratio"
        ] = (
            visual_max_changed_pixel_ratio
        )

    evaluation = (
        evaluate_auto_twin_candidate_fidelity(
            **evaluator_kwargs
        )
    )

    return _result(
        status=(
            AUTO_TWIN_VALIDATION_RUNNER_EVALUATED
        ),
        twin_capture_id=(
            twin_bundle[
                "capture_id"
            ]
        ),
        decision=(
            decision
        ),
        evaluation=(
            evaluation
        ),
    )
