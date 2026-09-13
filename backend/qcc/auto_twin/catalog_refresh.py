"""Decisión de refresco catalogal para AUTO TWIN.

Compara:

    evidencia catalogal candidata REAL
        vs
    catálogo actualmente materializado en la MISMA identidad Twin

No navega, no interactúa con REAL y no crea revisiones.

La identidad del estado sigue siendo:

    pathname + functional_state

La captura visual NO cambia por esta decisión.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.qcc.auto_twin.catalog_materialization import (
    build_catalog_runtime_payload,
)


AUTO_TWIN_CATALOG_REFRESH_SCHEMA_VERSION = 1

AUTO_TWIN_CATALOG_REFRESH_NO_EVIDENCE = (
    "NO_CATALOG_EVIDENCE"
)

AUTO_TWIN_CATALOG_REFRESH_NO_CHANGE = (
    "NO_CHANGE"
)

AUTO_TWIN_CATALOG_REFRESH_REQUIRED = (
    "REFRESH_REQUIRED"
)


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _result(
    *,
    status,
    reason,
    trigger_capture_id,
    pathname,
    functional_state,
    candidate_fingerprint=None,
    current_fingerprint=None,
    catalog_count=None,
    option_count=None,
):
    return {
        "schema_version":
            AUTO_TWIN_CATALOG_REFRESH_SCHEMA_VERSION,

        "status":
            status,

        "reason":
            reason,

        "trigger_capture_id":
            _text(
                trigger_capture_id
            ),

        "pathname":
            _text(
                pathname
            ),

        "functional_state":
            _text(
                functional_state
            ),

        "candidate_catalog_fingerprint":
            _text(
                candidate_fingerprint
            )
            or None,

        "current_catalog_fingerprint":
            _text(
                current_fingerprint
            )
            or None,

        "catalog_count":
            (
                int(
                    catalog_count
                )
                if catalog_count is not None
                else None
            ),

        "option_count":
            (
                int(
                    option_count
                )
                if option_count is not None
                else None
            ),
    }


def _load_json(
    path,
    *,
    error_code,
):
    path = Path(
        path
    )

    if not path.is_file():
        raise FileNotFoundError(
            error_code
            + ":"
            + str(
                path
            )
        )

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            error_code
            + ":"
            + str(
                path
            )
        ) from exc


# QCC_AUTO_TWIN_CATALOG_REFRESH_VARIANT_AWARE_IDENTITY_V1 (2D-20W)
#
# (pathname, functional_state) remains the FAMILY lookup, exactly as
# before -- but a governed 1->N supersession (2D-20J/K/O) means a
# family may legitimately contain more than one CURRENT physical
# variant at once. Their mere coexistence is never itself an error.
#
# When the family lookup alone already narrows to exactly one match,
# behavior is untouched byte-for-byte (no discriminator is even
# consulted) -- this is the overwhelming common case for every site/
# state that never splits.
#
# When it does not, resolution proceeds ONLY via an exact match on a
# caller-supplied, already-governed stable discriminator -- whichever
# of state_id / fingerprint / state_variant_key the caller can supply
# for its specific evidence (never a raw branch code, never
# navigation_context, never a first-match/ranking heuristic). Missing,
# unrecognized, or still-ambiguous-after-filtering discriminators fail
# closed with the exact same error this function has always raised.
#
# A caller may supply more than one discriminator at once even though
# only some of them are actually populated on this revision's
# materialized states (e.g. state_variant_key is not yet a persisted
# registry field anywhere). A discriminator field the caller supplied
# is only REQUIRED to match when at least one state in the family
# actually carries a non-empty value for that field -- otherwise the
# field carries no information in this dataset and is silently
# skipped, never silently treated as a false non-match. Every ACTIVE,
# caller-supplied field must still agree on the exact same single
# state; disagreement between two active discriminators is treated
# exactly like an unknown discriminator -- fail closed.
def _active_discriminator_fields(states, field_names):
    active = set()

    for field in field_names:
        for state in states:
            if _text(state.get(field)):
                active.add(field)
                break

    return active


def _discriminator_field_value(state, field):
    value = _text(
        state.get(field)
    )

    if field == "fingerprint":
        value = value.lower()

    return value or None


def _matches_state_discriminator(
    state,
    fields,
):
    for field, value in fields.items():
        if (
            _discriminator_field_value(
                state,
                field,
            )
            != value
        ):
            return False

    return True


def _current_state_metadata(
    *,
    revision_dir,
    pathname,
    functional_state,
    state_id=None,
    fingerprint=None,
    state_variant_key=None,
):
    """Resuelve exactamente un estado del runtime materializado."""

    revision_dir = Path(
        revision_dir
    )

    registry_path = (
        revision_dir
        / "runtime"
        / "registry.json"
    )

    registry = _load_json(
        registry_path,
        error_code=(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_REGISTRY_INVALID"
        ),
    )

    states = (
        registry.get(
            "states"
        )
        or []
    )

    if not isinstance(
        states,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_STATES_INVALID"
        )

    pathname = _text(
        pathname
    )

    functional_state = _text(
        functional_state
    )

    family_matches = [
        state
        for state in states
        if (
            isinstance(
                state,
                dict,
            )
            and _text(
                state.get(
                    "pathname"
                )
            )
            == pathname
            and _text(
                state.get(
                    "functional_state"
                )
            )
            == functional_state
        )
    ]

    matches = family_matches

    if len(matches) != 1:
        supplied = {
            "state_id": (
                _text(state_id)
                or None
            ),

            "fingerprint": (
                _text(fingerprint).lower()
                or None
            ),

            "state_variant_key": (
                _text(state_variant_key)
                or None
            ),
        }

        supplied = {
            field: value
            for field, value in supplied.items()
            if value is not None
        }

        if not supplied:
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS"
            )

        active_fields = _active_discriminator_fields(
            family_matches,
            supplied.keys(),
        )

        usable = {
            field: value
            for field, value in supplied.items()
            if field in active_fields
        }

        if not usable:
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS"
            )

        matches = [
            state
            for state in family_matches
            if _matches_state_discriminator(
                state,
                usable,
            )
        ]

        if len(matches) != 1:
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_IDENTITY_AMBIGUOUS"
            )

    registry_state = (
        matches[0]
    )

    runtime_entry = _text(
        registry_state.get(
            "runtime_entry"
        )
    )

    if not runtime_entry:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_RUNTIME_ENTRY_REQUIRED"
        )

    runtime_entry_path = (
        revision_dir
        / Path(
            runtime_entry
        )
    )

    state_json = (
        runtime_entry_path.parent
        / "state.json"
    )

    persisted = _load_json(
        state_json,
        error_code=(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_METADATA_INVALID"
        ),
    )

    if (
        _text(
            persisted.get(
                "pathname"
            )
        )
        != pathname
        or _text(
            persisted.get(
                "functional_state"
            )
        )
        != functional_state
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_METADATA_IDENTITY_MISMATCH"
        )

    return persisted


def decide_catalog_refresh(
    *,
    qcc_capture_payload,
    trigger_capture_id,
    revision_dir,
    pathname,
    functional_state,
    required_profile_key=None,
    state_id=None,
    fingerprint=None,
    state_variant_key=None,
):
    """Determina si un catálogo nuevo merece nueva revisión."""

    trigger_capture_id = _text(
        trigger_capture_id
    )

    pathname = _text(
        pathname
    )

    functional_state = _text(
        functional_state
    )

    if not trigger_capture_id:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_CAPTURE_REQUIRED"
        )

    if not pathname:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_PATHNAME_REQUIRED"
        )


    candidate = (
        build_catalog_runtime_payload(
            qcc_capture_payload=(
                qcc_capture_payload
            ),
            source_capture_id=(
                trigger_capture_id
            ),
            expected_pathname=(
                pathname
            ),
            required_profile_key=(
                required_profile_key
            ),
        )
    )

    catalog_count = int(
        candidate.get(
            "catalog_count"
        )
        or 0
    )

    option_count = int(
        candidate.get(
            "option_count"
        )
        or 0
    )

    if catalog_count <= 0:
        return _result(
            status=(
                AUTO_TWIN_CATALOG_REFRESH_NO_EVIDENCE
            ),
            reason="CATALOG_PROBE_EMPTY",
            trigger_capture_id=(
                trigger_capture_id
            ),
            pathname=pathname,
            functional_state=(
                functional_state
            ),
            catalog_count=0,
            option_count=0,
        )

    candidate_fingerprint = _text(
        candidate.get(
            "catalog_fingerprint"
        )
    )

    if not candidate_fingerprint:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_CANDIDATE_FINGERPRINT_REQUIRED"
        )

    current = (
        _current_state_metadata(
            revision_dir=(
                revision_dir
            ),
            pathname=pathname,
            functional_state=(
                functional_state
            ),
            state_id=state_id,
            fingerprint=fingerprint,
            state_variant_key=(
                state_variant_key
            ),
        )
    )

    current_fingerprint = _text(
        current.get(
            "catalog_fingerprint"
        )
    )

    if (
        current_fingerprint
        == candidate_fingerprint
    ):
        return _result(
            status=(
                AUTO_TWIN_CATALOG_REFRESH_NO_CHANGE
            ),
            reason=(
                "CATALOG_FINGERPRINT_UNCHANGED"
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
            pathname=pathname,
            functional_state=(
                functional_state
            ),
            candidate_fingerprint=(
                candidate_fingerprint
            ),
            current_fingerprint=(
                current_fingerprint
            ),
            catalog_count=(
                catalog_count
            ),
            option_count=(
                option_count
            ),
        )

    reason = (
        "CATALOG_NOT_MATERIALIZED"
        if not current_fingerprint
        else "CATALOG_FINGERPRINT_CHANGED"
    )

    return _result(
        status=(
            AUTO_TWIN_CATALOG_REFRESH_REQUIRED
        ),
        reason=reason,
        trigger_capture_id=(
            trigger_capture_id
        ),
        pathname=pathname,
        functional_state=(
            functional_state
        ),
        candidate_fingerprint=(
            candidate_fingerprint
        ),
        current_fingerprint=(
            current_fingerprint
        ),
        catalog_count=(
            catalog_count
        ),
        option_count=(
            option_count
        ),
    )


def materialized_catalog_provenance(
    *,
    revision_dir,
    pathname,
    functional_state=None,
):
    """Lee procedencia catalogal de una revisión existente.

    Backward compatible:
    revisiones anteriores a catálogos devuelven {}.
    """

    if revision_dir is None:
        return {}

    revision_dir = Path(
        revision_dir
    )

    if not revision_dir.is_dir():
        return {}

    try:
        metadata = (
            _current_state_metadata(
                revision_dir=(
                    revision_dir
                ),
                pathname=(
                    pathname
                ),
                functional_state=(
                    functional_state
                ),
            )
        )

    except (
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
    ):
        return {}

    if not isinstance(
        metadata,
        dict,
    ):
        return {}

    result = {}

    for key in (
        "catalog_source_capture_id",
        "catalog_fingerprint",
        "catalog_count",
        "catalog_option_count",
    ):
        value = metadata.get(
            key
        )

        if value is not None:
            result[
                key
            ] = value

    return result
