"""Contrato inmutable de una revisión materializada AUTO TWIN.

Una MaterializedRevision representa contenido generado a partir de
evidencia REAL gobernada.

La revisión materializada NO es el lifecycle del candidate.

Dos modos de procedencia:

BOOTSTRAP_REAL
    Construcción inicial desde captures REAL exactos.
    No requiere candidates previos.

CANDIDATE_UPDATE
    Construcción posterior asociada a uno o varios candidates
    state-scoped.

Límites deliberados:

- materializar NO significa validar;
- no requiere VALIDATED antes de existir;
- no contiene ValidationEvidence;
- no modifica CandidateRevisionStore;
- no introduce ACTIVE;
- no promociona;
- no ejecuta navegador;
- no usa el Golden manual como input.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re


AUTO_TWIN_MATERIALIZED_REVISION_SCHEMA_VERSION = 2

AUTO_TWIN_MATERIALIZED_REVISION_TYPE = (
    "QCC_AUTO_TWIN_MATERIALIZED_REVISION"
)

AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL = (
    "BOOTSTRAP_REAL"
)

AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION = (
    "DISCOVERY_EXTENSION"
)

AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH = (
    "CATALOG_REFRESH"
)


AUTO_TWIN_MATERIALIZATION_MODE_CANDIDATE_UPDATE = (
    "CANDIDATE_UPDATE"
)

AUTO_TWIN_MATERIALIZATION_MODES = frozenset({
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION,
    AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH,
    AUTO_TWIN_MATERIALIZATION_MODE_CANDIDATE_UPDATE,
})

AUTO_TWIN_MATERIALIZATION_SOURCE_REAL_EVIDENCE = (
    "REAL_EVIDENCE_ONLY"
)

AUTO_TWIN_MATERIALIZATION_IMMUTABLE = True


_SHA256_RE = re.compile(
    r"^[0-9a-f]{64}$"
)


def _text(value) -> str:
    return str(
        value
        or ""
    ).strip()


def _required_text(
    value,
    *,
    error,
) -> str:
    result = _text(
        value
    )

    if not result:
        raise ValueError(
            error
        )

    return result


def _positive_int(
    value,
    *,
    error,
) -> int:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
        or value <= 0
    ):
        raise ValueError(
            error
        )

    return value


def _non_negative_int(
    value,
    *,
    error,
) -> int:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
        or value < 0
    ):
        raise ValueError(
            error
        )

    return value


def _sha256(
    value,
    *,
    error,
) -> str:
    result = _text(
        value
    ).lower()

    if not _SHA256_RE.fullmatch(
        result
    ):
        raise ValueError(
            error
        )

    return result


def _utc_timestamp(
    value=None,
) -> str:
    if value is None:
        return (
            datetime.now(
                timezone.utc
            )
            .isoformat(
                timespec="microseconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        )

    result = _required_text(
        value,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZED_CREATED_AT_INVALID"
        ),
    )

    candidate = result

    if candidate.endswith(
        "Z"
    ):
        candidate = (
            candidate[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            candidate
        )

    except ValueError as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_CREATED_AT_INVALID"
        ) from exc

    if parsed.tzinfo is None:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_CREATED_AT_TIMEZONE_REQUIRED"
        )

    return result


def _unique_text_tuple(
    values,
    *,
    empty_error,
    duplicate_error,
    allow_empty=False,
) -> tuple[str, ...]:
    if values is None:
        values = ()

    if not isinstance(
        values,
        (list, tuple),
    ):
        raise TypeError(
            empty_error
        )

    normalized = tuple(
        _required_text(
            value,
            error=empty_error,
        )
        for value
        in values
    )

    if (
        not normalized
        and not allow_empty
    ):
        raise ValueError(
            empty_error
        )

    if len(
        set(
            normalized
        )
    ) != len(
        normalized
    ):
        raise ValueError(
            duplicate_error
        )

    return normalized


def _relative_artifact_path(
    value,
) -> str:
    result = _required_text(
        value,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_PATH_INVALID"
        ),
    ).replace(
        "\\",
        "/",
    )

    path = PurePosixPath(
        result
    )

    if (
        path.is_absolute()
        or ".." in path.parts
        or result.startswith(
            "/"
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_PATH_UNSAFE"
        )

    return path.as_posix()


def _normalize_state_manifest(
    values,
    *,
    source_capture_ids,
) -> tuple[dict, ...]:
    if not isinstance(
        values,
        (list, tuple),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MATERIALIZED_STATE_MANIFEST_INVALID"
        )

    if not values:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_STATE_MANIFEST_EMPTY"
        )

    result = []
    state_ids = set()

    source_ids = set(
        source_capture_ids
    )

    for value in values:
        if not isinstance(
            value,
            dict,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_INVALID"
            )

        state_id = _required_text(
            value.get(
                "state_id"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_ID_INVALID"
            ),
        )

        if state_id in state_ids:
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_ID_DUPLICATE"
            )

        state_ids.add(
            state_id
        )

        capture_id = _required_text(
            value.get(
                "source_capture_id"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_CAPTURE_INVALID"
            ),
        )

        if capture_id not in source_ids:
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_CAPTURE_OUT_OF_SCOPE"
            )

        pathname = _required_text(
            value.get(
                "pathname"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_PATHNAME_INVALID"
            ),
        )

        if not pathname.startswith(
            "/"
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_PATHNAME_INVALID"
            )

        functional_state = (
            _text(
                value.get(
                    "functional_state"
                )
            )
            or None
        )

        result.append({
            "state_id":
                state_id,

            "source_capture_id":
                capture_id,

            "pathname":
                pathname,

            "functional_state":
                functional_state,
        })

    return tuple(
        result
    )


def _normalize_candidate_refs(
    values,
    *,
    state_ids,
) -> tuple[dict, ...]:
    if values is None:
        values = ()

    if not isinstance(
        values,
        (list, tuple),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_REFS_INVALID"
        )

    result = []
    candidate_ids = set()

    for value in values:
        if not isinstance(
            value,
            dict,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_REF_INVALID"
            )

        candidate_id = _required_text(
            value.get(
                "candidate_id"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_ID_INVALID"
            ),
        )

        if candidate_id in candidate_ids:
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_ID_DUPLICATE"
            )

        candidate_ids.add(
            candidate_id
        )

        candidate_revision = _positive_int(
            value.get(
                "candidate_revision"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_REVISION_INVALID"
            ),
        )

        referenced_states = (
            _unique_text_tuple(
                value.get(
                    "state_ids"
                ),
                empty_error=(
                    "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_STATES_REQUIRED"
                ),
                duplicate_error=(
                    "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_STATE_DUPLICATE"
                ),
            )
        )

        if not set(
            referenced_states
        ).issubset(
            state_ids
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_CANDIDATE_STATE_OUT_OF_SCOPE"
            )

        result.append({
            "candidate_id":
                candidate_id,

            "candidate_revision":
                candidate_revision,

            "state_ids":
                list(
                    referenced_states
                ),
        })

    return tuple(
        result
    )


def _normalize_artifact_manifest(
    values,
) -> tuple[dict, ...]:
    if not isinstance(
        values,
        (list, tuple),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_MANIFEST_INVALID"
        )

    if not values:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_MANIFEST_EMPTY"
        )

    result = []
    paths = set()

    for value in values:
        if not isinstance(
            value,
            dict,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_INVALID"
            )

        path = _relative_artifact_path(
            value.get(
                "path"
            )
        )

        if path in paths:
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_PATH_DUPLICATE"
            )

        paths.add(
            path
        )

        result.append({
            "path":
                path,

            "kind":
                _required_text(
                    value.get(
                        "kind"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_KIND_INVALID"
                    ),
                ),

            "sha256":
                _sha256(
                    value.get(
                        "sha256"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_SHA256_INVALID"
                    ),
                ),

            "size_bytes":
                _non_negative_int(
                    value.get(
                        "size_bytes"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_MATERIALIZED_ARTIFACT_SIZE_INVALID"
                    ),
                ),
        })

    return tuple(
        result
    )


def _identity_payload(
    *,
    twin_key,
    materialization_mode,
    source_capture_ids,
    candidate_refs,
    state_manifest,
    artifact_manifest,
    content_sha256,
) -> dict:
    return {
        "twin_key":
            twin_key,

        "materialization_mode":
            materialization_mode,

        "source_capture_ids":
            list(
                source_capture_ids
            ),

        "candidate_refs":
            list(
                candidate_refs
            ),

        "state_manifest":
            list(
                state_manifest
            ),

        "artifact_manifest":
            list(
                artifact_manifest
            ),

        "content_sha256":
            content_sha256,
    }


def _materialized_revision_id(
    payload,
) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8"
    )

    digest = hashlib.sha256(
        encoded
    ).hexdigest()

    return (
        "matrev-"
        + digest[:24]
    )


def build_auto_twin_materialized_revision(
    *,
    twin_key,
    materialization_mode,
    source_capture_ids,
    state_manifest,
    artifact_manifest,
    content_sha256,
    candidate_refs=None,
    created_at=None,
) -> dict:
    """Construye una revisión materializada sin persistirla."""

    normalized_twin_key = _required_text(
        twin_key,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZED_TWIN_KEY_INVALID"
        ),
    )

    normalized_mode = _required_text(
        materialization_mode,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZED_MODE_INVALID"
        ),
    ).upper()

    if normalized_mode not in (
        AUTO_TWIN_MATERIALIZATION_MODES
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_MODE_INVALID"
        )

    normalized_source_capture_ids = (
        _unique_text_tuple(
            source_capture_ids,
            empty_error=(
                "QCC_AUTO_TWIN_MATERIALIZED_SOURCE_CAPTURES_REQUIRED"
            ),
            duplicate_error=(
                "QCC_AUTO_TWIN_MATERIALIZED_SOURCE_CAPTURE_DUPLICATE"
            ),
        )
    )

    normalized_states = (
        _normalize_state_manifest(
            state_manifest,
            source_capture_ids=(
                normalized_source_capture_ids
            ),
        )
    )

    state_capture_ids = {
        state[
            "source_capture_id"
        ]
        for state
        in normalized_states
    }

    if state_capture_ids != set(
        normalized_source_capture_ids
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_SOURCE_CAPTURE_COVERAGE_INVALID"
        )

    state_ids = {
        state[
            "state_id"
        ]
        for state
        in normalized_states
    }

    normalized_candidate_refs = (
        _normalize_candidate_refs(
            candidate_refs,
            state_ids=state_ids,
        )
    )

    if (
        normalized_mode
        == AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
        and normalized_candidate_refs
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_BOOTSTRAP_CANDIDATE_REFS_FORBIDDEN"
        )

    if (
        normalized_mode
        == AUTO_TWIN_MATERIALIZATION_MODE_CANDIDATE_UPDATE
        and not normalized_candidate_refs
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CANDIDATE_UPDATE_REFS_REQUIRED"
        )

    normalized_artifacts = (
        _normalize_artifact_manifest(
            artifact_manifest
        )
    )

    normalized_content_sha256 = _sha256(
        content_sha256,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZED_CONTENT_SHA256_INVALID"
        ),
    )

    identity = _identity_payload(
        twin_key=(
            normalized_twin_key
        ),
        materialization_mode=(
            normalized_mode
        ),
        source_capture_ids=(
            normalized_source_capture_ids
        ),
        candidate_refs=(
            normalized_candidate_refs
        ),
        state_manifest=(
            normalized_states
        ),
        artifact_manifest=(
            normalized_artifacts
        ),
        content_sha256=(
            normalized_content_sha256
        ),
    )

    revision_id = _materialized_revision_id(
        identity
    )

    return {
        "schema_version":
            AUTO_TWIN_MATERIALIZED_REVISION_SCHEMA_VERSION,

        "record_type":
            AUTO_TWIN_MATERIALIZED_REVISION_TYPE,

        "materialized_revision_id":
            revision_id,

        "twin_key":
            normalized_twin_key,

        "materialization_mode":
            normalized_mode,

        "generation_source":
            AUTO_TWIN_MATERIALIZATION_SOURCE_REAL_EVIDENCE,

        "immutable":
            AUTO_TWIN_MATERIALIZATION_IMMUTABLE,

        "created_at":
            _utc_timestamp(
                created_at
            ),

        "source_capture_ids":
            list(
                normalized_source_capture_ids
            ),

        "candidate_refs":
            deepcopy(
                list(
                    normalized_candidate_refs
                )
            ),

        "state_manifest":
            deepcopy(
                list(
                    normalized_states
                )
            ),

        "artifact_manifest":
            deepcopy(
                list(
                    normalized_artifacts
                )
            ),

        "content_sha256":
            normalized_content_sha256,
    }


def validate_auto_twin_materialized_revision(
    record,
) -> dict:
    """Valida integridad contractual y determinismo."""

    if not isinstance(
        record,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MATERIALIZED_REVISION_INVALID"
        )

    if (
        record.get(
            "schema_version"
        )
        != AUTO_TWIN_MATERIALIZED_REVISION_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_SCHEMA_VERSION_INVALID"
        )

    if (
        record.get(
            "record_type"
        )
        != AUTO_TWIN_MATERIALIZED_REVISION_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_RECORD_TYPE_INVALID"
        )

    if (
        record.get(
            "immutable"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_IMMUTABLE_REQUIRED"
        )

    if (
        record.get(
            "generation_source"
        )
        != AUTO_TWIN_MATERIALIZATION_SOURCE_REAL_EVIDENCE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_GENERATION_SOURCE_INVALID"
        )

    rebuilt = build_auto_twin_materialized_revision(
        twin_key=(
            record.get(
                "twin_key"
            )
        ),
        materialization_mode=(
            record.get(
                "materialization_mode"
            )
        ),
        source_capture_ids=(
            record.get(
                "source_capture_ids"
            )
        ),
        candidate_refs=(
            record.get(
                "candidate_refs"
            )
        ),
        state_manifest=(
            record.get(
                "state_manifest"
            )
        ),
        artifact_manifest=(
            record.get(
                "artifact_manifest"
            )
        ),
        content_sha256=(
            record.get(
                "content_sha256"
            )
        ),
        created_at=(
            record.get(
                "created_at"
            )
        ),
    )

    if (
        record.get(
            "materialized_revision_id"
        )
        != rebuilt[
            "materialized_revision_id"
        ]
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_REVISION_ID_MISMATCH"
        )

    if record != rebuilt:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_REVISION_NON_CANONICAL"
        )

    return deepcopy(
        rebuilt
    )
