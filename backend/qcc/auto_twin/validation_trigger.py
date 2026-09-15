"""Resolución pura del trigger de validación AUTO TWIN.

Decide si una captura TWIN ya identificada puede asociarse
de forma inequívoca con una revisión candidata pendiente.

Este módulo no:
- carga artefactos;
- busca capturas en disco;
- ejecuta navegador;
- ejecuta comparadores;
- persiste evidencia;
- modifica estados de revisión.
"""

from __future__ import annotations

from typing import Any

from .profile_policy import (
    AUTO_TWIN_DISCOVERY_PROFILE_KEY,
)


AUTO_TWIN_VALIDATION_TRIGGER_SCHEMA_VERSION = 1

AUTO_TWIN_VALIDATION_TRIGGER_TYPE = (
    "QCC_AUTO_TWIN_VALIDATION_TRIGGER_DECISION"
)

AUTO_TWIN_VALIDATION_TRIGGER_READY = "READY"
AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED = "SKIPPED"
AUTO_TWIN_VALIDATION_TRIGGER_AMBIGUOUS = "AMBIGUOUS"

AUTO_TWIN_VALIDATION_TRIGGER_REASON_READY = "READY"
AUTO_TWIN_VALIDATION_TRIGGER_REASON_TWIN_DISABLED = (
    "MANAGED_TWIN_DISABLED"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_PROFILE_NOT_ALLOWED = (
    "PROFILE_NOT_VALIDATION"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_CAPTURE_INVALID = (
    "TWIN_CAPTURE_INVALID"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_CAPTURE_PROFILE_MISMATCH = (
    "TWIN_CAPTURE_PROFILE_MISMATCH"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_NO_PENDING = (
    "NO_PENDING_CANDIDATE"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_NO_MATCH = (
    "NO_MATCHING_CANDIDATE"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_AMBIGUOUS = (
    "AMBIGUOUS_CANDIDATE"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_CANDIDATE_INVALID = (
    "CANDIDATE_INVALID"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_REAL_CAPTURE_UNAVAILABLE = (
    "REAL_CAPTURE_UNAVAILABLE"
)
AUTO_TWIN_VALIDATION_TRIGGER_REASON_CAPTURE_COLLISION = (
    "REAL_TWIN_CAPTURE_COLLISION"
)

_PENDING_VALIDATION = "PENDING_VALIDATION"


def _value(
    source: Any,
    key: str,
    default=None,
):
    if isinstance(source, dict):
        return source.get(
            key,
            default,
        )

    return getattr(
        source,
        key,
        default,
    )


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _functional_state(
    value,
):
    normalized = _text(
        value
    )

    return (
        normalized
        or None
    )


def _base_decision(
    *,
    status,
    reason,
    twin_key=None,
    twin_capture_id=None,
    pathname=None,
    functional_state=None,
    profile_key=None,
):
    return {
        "schema_version":
            AUTO_TWIN_VALIDATION_TRIGGER_SCHEMA_VERSION,

        "decision_type":
            AUTO_TWIN_VALIDATION_TRIGGER_TYPE,

        "status":
            status,

        "reason":
            reason,

        "twin_key":
            twin_key,

        "twin_capture_id":
            twin_capture_id,

        "pathname":
            pathname,

        "functional_state":
            functional_state,

        "profile_key":
            profile_key,

        "candidate_id":
            None,

        "candidate_revision":
            None,

        "real_capture_id":
            None,

        "matching_candidate_ids":
            [],
    }


def resolve_auto_twin_validation_trigger(
    *,
    managed_twin,
    profile_policy,
    candidate_store,
    twin_capture,
):
    """Resuelve una asociación candidata para una captura TWIN.

    La selección es deliberadamente estricta:

    - solo perfil ``twin_discovery``;
    - ``validate_twin`` debe estar concedido por policy;
    - solo revisiones PENDING_VALIDATION;
    - pathname y functional_state deben coincidir;
    - cero coincidencias => SKIPPED;
    - más de una => AMBIGUOUS;
    - la captura REAL procede exclusivamente de
      latest_capture_id ya registrado en evidence_capture_ids.
    """

    twin_key = _text(
        _value(
            managed_twin,
            "twin_key",
        )
    )

    enabled = (
        _value(
            managed_twin,
            "enabled",
            False,
        )
        is True
    )

    profile_key = _text(
        _value(
            profile_policy,
            "profile_key",
        )
    )

    validate_twin = (
        _value(
            profile_policy,
            "validate_twin",
            False,
        )
        is True
    )

    if not enabled:
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_TWIN_DISABLED
            ),
            twin_key=twin_key or None,
            profile_key=profile_key or None,
        )

    if (
        profile_key
        != AUTO_TWIN_DISCOVERY_PROFILE_KEY
        or not validate_twin
    ):
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_PROFILE_NOT_ALLOWED
            ),
            twin_key=twin_key or None,
            profile_key=profile_key or None,
        )

    if not isinstance(
        twin_capture,
        dict,
    ):
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_CAPTURE_INVALID
            ),
            twin_key=twin_key or None,
            profile_key=profile_key or None,
        )

    twin_capture_id = _text(
        twin_capture.get(
            "capture_id"
        )
    )

    capture_profile_key = _text(
        twin_capture.get(
            "browser_profile_key"
        )
    )

    pathname = _text(
        twin_capture.get(
            "pathname"
        )
    )

    functional_state = _functional_state(
        twin_capture.get(
            "functional_state"
        )
    )

    if (
        not twin_key
        or not twin_capture_id
        or not pathname
    ):
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_CAPTURE_INVALID
            ),
            twin_key=twin_key or None,
            twin_capture_id=(
                twin_capture_id
                or None
            ),
            pathname=(
                pathname
                or None
            ),
            functional_state=functional_state,
            profile_key=profile_key,
        )

    if (
        capture_profile_key
        != profile_key
    ):
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_CAPTURE_PROFILE_MISMATCH
            ),
            twin_key=twin_key,
            twin_capture_id=twin_capture_id,
            pathname=pathname,
            functional_state=functional_state,
            profile_key=profile_key,
        )

    snapshot = candidate_store.snapshot(
        twin_key
    )

    candidates = (
        snapshot.get(
            "candidates"
        )
        if isinstance(
            snapshot,
            dict,
        )
        else None
    )

    if not isinstance(
        candidates,
        list,
    ):
        candidates = []

    pending = [
        candidate
        for candidate
        in candidates
        if (
            isinstance(
                candidate,
                dict,
            )
            and _text(
                candidate.get(
                    "status"
                )
            ).upper()
            == _PENDING_VALIDATION
        )
    ]

    if not pending:
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_NO_PENDING
            ),
            twin_key=twin_key,
            twin_capture_id=twin_capture_id,
            pathname=pathname,
            functional_state=functional_state,
            profile_key=profile_key,
        )

    matching = [
        candidate
        for candidate
        in pending
        if (
            _text(
                candidate.get(
                    "pathname"
                )
            )
            == pathname
            and _functional_state(
                candidate.get(
                    "functional_state"
                )
            )
            == functional_state
        )
    ]

    if not matching:
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_NO_MATCH
            ),
            twin_key=twin_key,
            twin_capture_id=twin_capture_id,
            pathname=pathname,
            functional_state=functional_state,
            profile_key=profile_key,
        )

    matching_candidate_ids = [
        _text(
            candidate.get(
                "candidate_id"
            )
        )
        for candidate
        in matching
        if _text(
            candidate.get(
                "candidate_id"
            )
        )
    ]

    if len(
        matching
    ) != 1:
        result = _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_AMBIGUOUS
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_AMBIGUOUS
            ),
            twin_key=twin_key,
            twin_capture_id=twin_capture_id,
            pathname=pathname,
            functional_state=functional_state,
            profile_key=profile_key,
        )

        result[
            "matching_candidate_ids"
        ] = sorted(
            set(
                matching_candidate_ids
            )
        )

        return result

    candidate = matching[0]

    candidate_id = _text(
        candidate.get(
            "candidate_id"
        )
    )

    try:
        candidate_revision = int(
            candidate.get(
                "candidate_revision"
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        candidate_revision = 0

    if (
        not candidate_id
        or candidate_revision <= 0
    ):
        return _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_CANDIDATE_INVALID
            ),
            twin_key=twin_key,
            twin_capture_id=twin_capture_id,
            pathname=pathname,
            functional_state=functional_state,
            profile_key=profile_key,
        )

    evidence_capture_ids = (
        candidate.get(
            "evidence_capture_ids"
        )
    )

    if not isinstance(
        evidence_capture_ids,
        list,
    ):
        evidence_capture_ids = []

    evidence_capture_ids = [
        capture_id
        for capture_id
        in (
            _text(
                item
            )
            for item
            in evidence_capture_ids
        )
        if capture_id
    ]

    real_capture_id = _text(
        candidate.get(
            "latest_capture_id"
        )
    )

    if (
        not real_capture_id
        or real_capture_id
        not in evidence_capture_ids
    ):
        result = _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_REAL_CAPTURE_UNAVAILABLE
            ),
            twin_key=twin_key,
            twin_capture_id=twin_capture_id,
            pathname=pathname,
            functional_state=functional_state,
            profile_key=profile_key,
        )

        result[
            "candidate_id"
        ] = candidate_id

        result[
            "candidate_revision"
        ] = candidate_revision

        return result

    if (
        real_capture_id
        == twin_capture_id
    ):
        result = _base_decision(
            status=(
                AUTO_TWIN_VALIDATION_TRIGGER_SKIPPED
            ),
            reason=(
                AUTO_TWIN_VALIDATION_TRIGGER_REASON_CAPTURE_COLLISION
            ),
            twin_key=twin_key,
            twin_capture_id=twin_capture_id,
            pathname=pathname,
            functional_state=functional_state,
            profile_key=profile_key,
        )

        result[
            "candidate_id"
        ] = candidate_id

        result[
            "candidate_revision"
        ] = candidate_revision

        return result

    result = _base_decision(
        status=(
            AUTO_TWIN_VALIDATION_TRIGGER_READY
        ),
        reason=(
            AUTO_TWIN_VALIDATION_TRIGGER_REASON_READY
        ),
        twin_key=twin_key,
        twin_capture_id=twin_capture_id,
        pathname=pathname,
        functional_state=functional_state,
        profile_key=profile_key,
    )

    result[
        "candidate_id"
    ] = candidate_id

    result[
        "candidate_revision"
    ] = candidate_revision

    result[
        "real_capture_id"
    ] = real_capture_id

    result[
        "matching_candidate_ids"
    ] = [
        candidate_id
    ]

    return result
