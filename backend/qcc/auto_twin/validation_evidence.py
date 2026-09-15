"""Contrato ligero de evidencia de validación AUTO TWIN.

No materializa TWINs.
No modifica candidates.
No promociona ACTIVE.
No almacena DOM, HTML, MHTML ni imágenes.

Únicamente normaliza resultados ligeros de comparadores.
"""

from __future__ import annotations

from copy import deepcopy


AUTO_TWIN_VALIDATION_EVIDENCE_SCHEMA_VERSION = 1

AUTO_TWIN_VALIDATION_EVIDENCE_TYPE = (
    "QCC_AUTO_TWIN_VALIDATION_EVIDENCE"
)


AUTO_TWIN_VALIDATION_CHECK_PASS = "PASS"
AUTO_TWIN_VALIDATION_CHECK_FAIL = "FAIL"
AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE = (
    "INCONCLUSIVE"
)
AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE = (
    "NOT_AVAILABLE"
)


AUTO_TWIN_VALIDATION_VERDICT_PASS = "PASS"
AUTO_TWIN_VALIDATION_VERDICT_FAIL = "FAIL"
AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE = (
    "INCONCLUSIVE"
)


AUTO_TWIN_VALIDATION_DIMENSION_STRUCTURE = (
    "STRUCTURE"
)
AUTO_TWIN_VALIDATION_DIMENSION_GEOMETRY = (
    "GEOMETRY"
)
AUTO_TWIN_VALIDATION_DIMENSION_VISUAL = (
    "VISUAL"
)
AUTO_TWIN_VALIDATION_DIMENSION_CATALOGS = (
    "CATALOGS"
)
AUTO_TWIN_VALIDATION_DIMENSION_BEHAVIOR = (
    "BEHAVIOR"
)


AUTO_TWIN_VALIDATION_DIMENSIONS = (
    AUTO_TWIN_VALIDATION_DIMENSION_STRUCTURE,
    AUTO_TWIN_VALIDATION_DIMENSION_GEOMETRY,
    AUTO_TWIN_VALIDATION_DIMENSION_VISUAL,
    AUTO_TWIN_VALIDATION_DIMENSION_CATALOGS,
    AUTO_TWIN_VALIDATION_DIMENSION_BEHAVIOR,
)


AUTO_TWIN_VALIDATION_CHECK_STATUSES = frozenset({
    AUTO_TWIN_VALIDATION_CHECK_PASS,
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
    AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
})


_ALLOWED_CHECK_FIELDS = frozenset({
    "status",
    "summary",
    "metrics",
    "references",
})


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _normalize_dimension(
    value,
) -> str:
    dimension = _text(
        value
    ).upper()

    if (
        dimension
        not in AUTO_TWIN_VALIDATION_DIMENSIONS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_DIMENSION_INVALID"
        )

    return dimension


def _normalize_required_dimensions(
    value,
) -> tuple[str, ...]:
    if value is None:
        return (
            AUTO_TWIN_VALIDATION_DIMENSIONS
        )

    if not isinstance(
        value,
        (list, tuple, set, frozenset),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_REQUIRED_DIMENSIONS_INVALID"
        )

    result = []

    for item in value:
        dimension = (
            _normalize_dimension(
                item
            )
        )

        if dimension not in result:
            result.append(
                dimension
            )

    if not result:
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_REQUIRED_DIMENSIONS_EMPTY"
        )

    return tuple(
        result
    )


def _normalize_scalar_mapping(
    value,
    *,
    error,
) -> dict:
    if value is None:
        return {}

    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            error
        )

    result = {}

    for raw_key, raw_value in value.items():
        key = _text(
            raw_key
        )

        if not key:
            raise ValueError(
                error
            )

        if isinstance(
            raw_value,
            (dict, list, tuple, set),
        ):
            raise ValueError(
                error
            )

        result[
            key
        ] = raw_value

    return result


def _normalize_check(
    value,
) -> dict:
    if value is None:
        value = {
            "status":
                AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
        }

    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_CHECK_INVALID"
        )

    if (
        set(value)
        - _ALLOWED_CHECK_FIELDS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_CHECK_FIELDS_INVALID"
        )

    status = _text(
        value.get(
            "status"
        )
    ).upper()

    if (
        status
        not in AUTO_TWIN_VALIDATION_CHECK_STATUSES
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_CHECK_STATUS_INVALID"
        )

    summary = _text(
        value.get(
            "summary"
        )
    )

    metrics = (
        _normalize_scalar_mapping(
            value.get(
                "metrics"
            ),
            error=(
                "QCC_AUTO_TWIN_VALIDATION_METRICS_INVALID"
            ),
        )
    )

    references = (
        _normalize_scalar_mapping(
            value.get(
                "references"
            ),
            error=(
                "QCC_AUTO_TWIN_VALIDATION_REFERENCES_INVALID"
            ),
        )
    )

    return {
        "status":
            status,

        "summary":
            summary
            or None,

        "metrics":
            metrics,

        "references":
            references,
    }


def _validation_verdict(
    checks,
    required_dimensions,
) -> str:
    required_statuses = tuple(
        checks[
            dimension
        ][
            "status"
        ]
        for dimension
        in required_dimensions
    )

    if (
        AUTO_TWIN_VALIDATION_CHECK_FAIL
        in required_statuses
    ):
        return (
            AUTO_TWIN_VALIDATION_VERDICT_FAIL
        )

    if all(
        status
        == AUTO_TWIN_VALIDATION_CHECK_PASS
        for status
        in required_statuses
    ):
        return (
            AUTO_TWIN_VALIDATION_VERDICT_PASS
        )

    return (
        AUTO_TWIN_VALIDATION_VERDICT_INCONCLUSIVE
    )


def build_auto_twin_validation_evidence(
    *,
    twin_key,
    candidate_id,
    candidate_revision,
    real_capture_id=None,
    twin_capture_id=None,
    pathname=None,
    functional_state=None,
    checks=None,
    required_dimensions=None,
    rendering_profile_id=None,
) -> dict:
    """Construye evidencia ligera REAL ↔ TWIN.

    El contrato deliberadamente NO exige que exista ya
    twin_capture_id. Mientras falte evidencia requerida,
    el veredicto permanecerá INCONCLUSIVE.

    El origen REAL/TWIN no forma parte de state_identity:
    REAL y TWIN necesariamente viven en origins distintos.
    """

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

    required = (
        _normalize_required_dimensions(
            required_dimensions
        )
    )

    if checks is None:
        checks = {}

    if not isinstance(
        checks,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_CHECKS_INVALID"
        )

    normalized_input_checks = {}

    for raw_dimension, raw_check in checks.items():
        dimension = (
            _normalize_dimension(
                raw_dimension
            )
        )

        normalized_input_checks[
            dimension
        ] = _normalize_check(
            raw_check
        )

    normalized_checks = {}

    for dimension in (
        AUTO_TWIN_VALIDATION_DIMENSIONS
    ):
        normalized_checks[
            dimension
        ] = (
            normalized_input_checks.get(
                dimension
            )
            or _normalize_check(
                None
            )
        )

    verdict = (
        _validation_verdict(
            normalized_checks,
            required,
        )
    )

    passed_dimensions = tuple(
        dimension
        for dimension
        in AUTO_TWIN_VALIDATION_DIMENSIONS
        if (
            normalized_checks[
                dimension
            ][
                "status"
            ]
            == AUTO_TWIN_VALIDATION_CHECK_PASS
        )
    )

    failed_dimensions = tuple(
        dimension
        for dimension
        in AUTO_TWIN_VALIDATION_DIMENSIONS
        if (
            normalized_checks[
                dimension
            ][
                "status"
            ]
            == AUTO_TWIN_VALIDATION_CHECK_FAIL
        )
    )

    incomplete_dimensions = tuple(
        dimension
        for dimension
        in required
        if (
            normalized_checks[
                dimension
            ][
                "status"
            ]
            in {
                AUTO_TWIN_VALIDATION_CHECK_INCONCLUSIVE,
                AUTO_TWIN_VALIDATION_CHECK_NOT_AVAILABLE,
            }
        )
    )

    return {
        "schema_version":
            AUTO_TWIN_VALIDATION_EVIDENCE_SCHEMA_VERSION,

        "evidence_type":
            AUTO_TWIN_VALIDATION_EVIDENCE_TYPE,

        "twin_key":
            normalized_twin_key,

        "candidate_id":
            normalized_candidate_id,

        "candidate_revision":
            normalized_revision,

        "state_identity": {
            # Deliberadamente sin origin/url.
            "pathname":
                _text(
                    pathname
                )
                or None,

            "functional_state":
                _text(
                    functional_state
                )
                or None,
        },

        "capture_pair": {
            "real_capture_id":
                _text(
                    real_capture_id
                )
                or None,

            "twin_capture_id":
                _text(
                    twin_capture_id
                )
                or None,
        },

        "rendering_profile_id":
            _text(
                rendering_profile_id
            )
            or None,

        "required_dimensions":
            required,

        "checks":
            deepcopy(
                normalized_checks
            ),

        "summary": {
            "passed_dimensions":
                passed_dimensions,

            "failed_dimensions":
                failed_dimensions,

            "incomplete_dimensions":
                incomplete_dimensions,
        },

        "verdict":
            verdict,

        "ready_for_validation":
            (
                verdict
                == AUTO_TWIN_VALIDATION_VERDICT_PASS
            ),
    }
