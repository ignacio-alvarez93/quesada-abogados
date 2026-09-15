"""Comparador funcional de BehaviorTrace REAL ↔ TWIN.

Compara trazas ya normalizadas.

No ejecuta acciones.
No analiza experimentos.
No modifica candidates.
No modifica lifecycle.

La policy queda deliberadamente fuera de la fidelidad
funcional.
"""

from __future__ import annotations

from .behavior_trace import (
    AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION,
    AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT,
    AUTO_TWIN_BEHAVIOR_REAL_SOURCES,
    AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED,
    AUTO_TWIN_BEHAVIOR_TRACE_SCHEMA_VERSION,
    AUTO_TWIN_BEHAVIOR_TRACE_TYPE,
    build_auto_twin_behavior_trace,
)

from .validation_evidence import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
)


AUTO_TWIN_BEHAVIOR_COMPARATOR_SCHEMA_VERSION = 1

AUTO_TWIN_BEHAVIOR_COMPARATOR_TYPE = (
    "QCC_AUTO_TWIN_BEHAVIOR_FIDELITY_COMPARISON"
)


def _validate_trace(
    value,
    *,
    expected_sources,
):
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_BEHAVIOR_TRACE_INVALID"
        )

    if (
        value.get(
            "schema_version"
        )
        != AUTO_TWIN_BEHAVIOR_TRACE_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_TRACE_SCHEMA_INVALID"
        )

    if (
        value.get(
            "trace_type"
        )
        != AUTO_TWIN_BEHAVIOR_TRACE_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_TRACE_TYPE_INVALID"
        )

    if (
        value.get(
            "source"
        )
        not in expected_sources
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_TRACE_SOURCE_INVALID"
        )

    rebuilt = (
        build_auto_twin_behavior_trace(
            twin_key=(
                value.get(
                    "twin_key"
                )
            ),
            candidate_id=(
                value.get(
                    "candidate_id"
                )
            ),
            source=(
                value.get(
                    "source"
                )
            ),
            action=(
                value.get(
                    "action"
                )
            ),
            transition=(
                value.get(
                    "transition"
                )
            ),
            behavior_kind=(
                value.get(
                    "behavior_kind"
                )
            ),
            effects=(
                value.get(
                    "effects"
                )
                or ()
            ),
            causal_relations=(
                value.get(
                    "causal_relations"
                )
                or ()
            ),
            policy=(
                value.get(
                    "policy"
                )
            ),
            restoration_status=(
                value.get(
                    "restoration_status"
                )
            ),
            references=(
                value.get(
                    "references"
                )
                or {}
            ),
        )
    )

    if (
        value.get(
            "functional_signature"
        )
        != rebuilt[
            "functional_signature"
        ]
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_SIGNATURE_INVALID"
        )

    return rebuilt


def _transition_complete(
    trace,
) -> bool:
    transition = (
        trace.get(
            "transition"
        )
        or {}
    )

    if (
        transition.get(
            "changed"
        )
        is not True
    ):
        return True

    return bool(
        transition.get(
            "before_state"
        )
        and transition.get(
            "after_state"
        )
    )


def _catalog_option_identity_complete(
    trace,
) -> bool:
    """Evita PASS por conteos cuando falta identidad de opciones."""

    if (
        trace.get(
            "behavior_kind"
        )
        != AUTO_TWIN_BEHAVIOR_KIND_CATALOG_MUTATION
    ):
        return True

    for effect in (
        trace.get(
            "effects"
        )
        or ()
    ):
        if (
            effect.get(
                "kind"
            )
            != "CATALOG_OPTIONS_CHANGED"
        ):
            continue

        if (
            not effect.get(
                "before_options_signature"
            )
            or not effect.get(
                "after_options_signature"
            )
        ):
            return False

    return True


def _check(
    *,
    status,
    summary,
    real_trace,
    twin_trace,
    metrics,
):
    references = {
        "real_behavior_trace_id":
            (
                real_trace.get(
                    "behavior_trace_id"
                )
                if real_trace
                else None
            ),

        "twin_behavior_trace_id":
            (
                twin_trace.get(
                    "behavior_trace_id"
                )
                if twin_trace
                else None
            ),
    }

    return {
        "status":
            status,

        "summary":
            summary,

        "metrics":
            metrics,

        "references":
            references,
    }


def compare_auto_twin_behavior(
    *,
    real_trace,
    twin_trace,
) -> dict:
    """Compara una traza REAL observada con una TWIN controlada."""

    if (
        real_trace is None
        or twin_trace is None
    ):
        check = _check(
            status=(
                AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE
            ),
            summary=(
                "Behavior evidence pair unavailable."
            ),
            real_trace=(
                real_trace
                if isinstance(
                    real_trace,
                    dict,
                )
                else None
            ),
            twin_trace=(
                twin_trace
                if isinstance(
                    twin_trace,
                    dict,
                )
                else None
            ),
            metrics={
                "real_available":
                    real_trace is not None,

                "twin_available":
                    twin_trace is not None,
            },
        )

        return {
            "schema_version":
                AUTO_TWIN_BEHAVIOR_COMPARATOR_SCHEMA_VERSION,

            "comparison_type":
                AUTO_TWIN_BEHAVIOR_COMPARATOR_TYPE,

            "checks": {
                "BEHAVIOR":
                    check,
            },

            "behavior_fidelity_pass":
                False,
        }

    real = _validate_trace(
        real_trace,
        expected_sources=(
            AUTO_TWIN_BEHAVIOR_REAL_SOURCES
        ),
    )

    twin = _validate_trace(
        twin_trace,
        expected_sources={
            AUTO_TWIN_BEHAVIOR_SOURCE_TWIN_CONTROLLED
        },
    )

    if (
        real[
            "twin_key"
        ]
        != twin[
            "twin_key"
        ]
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_TWIN_KEY_MISMATCH"
        )

    if (
        real[
            "candidate_id"
        ]
        != twin[
            "candidate_id"
        ]
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_CANDIDATE_MISMATCH"
        )

    if (
        twin[
            "restoration_status"
        ]
        != AUTO_TWIN_BEHAVIOR_RESTORATION_EXACT
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BEHAVIOR_TWIN_RESTORATION_REQUIRED"
        )

    behavior_kind_equal = (
        real[
            "behavior_kind"
        ]
        == twin[
            "behavior_kind"
        ]
    )

    action_equal = (
        real[
            "action"
        ]
        == twin[
            "action"
        ]
    )

    transition_equal = (
        real[
            "transition"
        ]
        == twin[
            "transition"
        ]
    )

    effects_equal = (
        real[
            "effects"
        ]
        == twin[
            "effects"
        ]
    )

    causal_relations_equal = (
        real[
            "causal_relations"
        ]
        == twin[
            "causal_relations"
        ]
    )

    signature_equal = (
        real[
            "functional_signature"
        ]
        == twin[
            "functional_signature"
        ]
    )

    real_complete = (
        _transition_complete(
            real
        )
    )

    twin_complete = (
        _transition_complete(
            twin
        )
    )

    real_catalog_option_identity_complete = (
        _catalog_option_identity_complete(
            real
        )
    )

    twin_catalog_option_identity_complete = (
        _catalog_option_identity_complete(
            twin
        )
    )

    metrics = {
        "behavior_kind_equal":
            behavior_kind_equal,

        "action_equal":
            action_equal,

        "transition_equal":
            transition_equal,

        "effects_equal":
            effects_equal,

        "causal_relations_equal":
            causal_relations_equal,

        "functional_signature_equal":
            signature_equal,

        "real_transition_complete":
            real_complete,

        "twin_transition_complete":
            twin_complete,

        "real_catalog_option_identity_complete":
            real_catalog_option_identity_complete,

        "twin_catalog_option_identity_complete":
            twin_catalog_option_identity_complete,

        # Auditamos que la policy pueda ser distinta
        # sin participar en el veredicto funcional.
        "policy_equal":
            (
                real.get(
                    "policy"
                )
                == twin.get(
                    "policy"
                )
            ),
    }

    if not behavior_kind_equal:
        status = (
            AUTO_TWIN_VALIDATION_CHECK_FAIL
        )

        summary = (
            "Behavior kind differs."
        )

    elif not action_equal:
        status = (
            AUTO_TWIN_VALIDATION_CHECK_FAIL
        )

        summary = (
            "Behavior action identity differs."
        )

    elif (
        not real_complete
        or not twin_complete
    ):
        status = (
            AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
        )

        summary = (
            "Behavior transition evidence incomplete."
        )

    elif (
        not real_catalog_option_identity_complete
        or not twin_catalog_option_identity_complete
    ):
        status = (
            AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE
        )

        summary = (
            "Catalog option identity evidence incomplete."
        )

    elif signature_equal:
        status = (
            AUTO_TWIN_VALIDATION_CHECK_PASS
        )

        summary = (
            "REAL and TWIN functional behavior equivalent."
        )

    else:
        status = (
            AUTO_TWIN_VALIDATION_CHECK_FAIL
        )

        summary = (
            "REAL and TWIN functional behavior differs."
        )

    check = _check(
        status=status,
        summary=summary,
        real_trace=real,
        twin_trace=twin,
        metrics=metrics,
    )

    return {
        "schema_version":
            AUTO_TWIN_BEHAVIOR_COMPARATOR_SCHEMA_VERSION,

        "comparison_type":
            AUTO_TWIN_BEHAVIOR_COMPARATOR_TYPE,

        "twin_key":
            real[
                "twin_key"
            ],

        "candidate_id":
            real[
                "candidate_id"
            ],

        "checks": {
            "BEHAVIOR":
                check,
        },

        "behavior_fidelity_pass":
            (
                status
                == AUTO_TWIN_VALIDATION_CHECK_PASS
            ),
    }
