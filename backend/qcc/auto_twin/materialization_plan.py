"""Plan puro y determinista de materialización AUTO TWIN.

Transforma referencias explícitas a captures REAL ya persistidos en un
plan de operaciones de artefactos.

Este módulo:

- carga únicamente capture_ids explícitos;
- valida cada capture mediante PersistedCaptureBundle;
- valida origin/profile/pathname/functional_state esperados;
- exige las materias primas de materialización;
- calcula tamaños y SHA256;
- produce destinos relativos deterministas;
- no escribe ningún fichero;
- no construye runtime;
- no valida fidelidad;
- no modifica candidates;
- no promociona revisiones.
"""

from __future__ import annotations

from backend.qcc.auto_twin.catalog_materialization import (
    build_catalog_runtime_payload,
)

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
)

from .materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODES,
    AUTO_TWIN_MATERIALIZATION_SOURCE_REAL_EVIDENCE,
)

from .persisted_capture_bundle import (
    load_auto_twin_persisted_capture_bundle,
)


AUTO_TWIN_MATERIALIZATION_PLAN_SCHEMA_VERSION = 1

AUTO_TWIN_MATERIALIZATION_PLAN_TYPE = (
    "QCC_AUTO_TWIN_MATERIALIZATION_PLAN"
)


AUTO_TWIN_STATE_SOURCE_REAL_CAPTURE = (
    "REAL_CAPTURE"
)

AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD = (
    "MATERIALIZED_CARRY_FORWARD"
)


AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS = (
    (
        "RAW_CAPTURE",
        "qcc_capture.json",
        "evidence/qcc_capture.json",
    ),
    (
        "SITE_ARCHITECTURE",
        "site_architecture.json",
        "evidence/site_architecture.json",
    ),
    (
        "STATE_OBSERVATION",
        "state_observation.json",
        "evidence/state_observation.json",
    ),
    (
        "METADATA",
        "metadata.json",
        "evidence/metadata.json",
    ),
    (
        "PAGE_HTML",
        "page.html",
        "source/page.html",
    ),
    (
        "PAGE_MHTML",
        "page.mhtml",
        "source/page.mhtml",
    ),
    (
        "SCREENSHOT_VIEWPORT",
        "screenshot_viewport.png",
        "evidence/screenshot_viewport.png",
    ),
)


_SAFE_STATE_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
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


def _canonical_json(
    value,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8"
    )


def _sha256_bytes(
    value,
) -> str:
    return hashlib.sha256(
        value
    ).hexdigest()


def _safe_state_id(
    value,
) -> str:
    result = _required_text(
        value,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_STATE_ID_REQUIRED"
        ),
    )

    if not _SAFE_STATE_ID_RE.fullmatch(
        result
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_STATE_ID_INVALID"
        )

    return result


def _snapshot_origin(
    snapshot,
) -> str:
    if not isinstance(
        snapshot,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_SNAPSHOT_INVALID"
        )

    page = snapshot.get(
        "page"
    )

    if not isinstance(
        page,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PAGE_INVALID"
        )

    origin = _text(
        page.get(
            "origin"
        )
    )

    if not origin:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_ORIGIN_REQUIRED"
        )

    return origin.rstrip(
        "/"
    )


def _artifact_operation(
    *,
    root,
    capture_id,
    state_index,
    state_id,
    kind,
    source_filename,
    destination_suffix,
) -> dict:
    source = (
        Path(
            root
        )
        / capture_id
        / source_filename
    )

    if not source.is_file():
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_SOURCE_ARTIFACT_MISSING:"
            + capture_id
            + ":"
            + source_filename
        )

    try:
        content = source.read_bytes()

    except OSError as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_SOURCE_ARTIFACT_INVALID:"
            + capture_id
            + ":"
            + source_filename
        ) from exc

    state_root = PurePosixPath(
        "states"
    ) / (
        f"{state_index:02d}-"
        + state_id
    )

    destination = (
        state_root
        / PurePosixPath(
            destination_suffix
        )
    ).as_posix()

    return {
        "state_id":
            state_id,

        "source_capture_id":
            capture_id,

        "kind":
            kind,

        "source_filename":
            source_filename,

        # Referencia portable: nunca contiene el root absoluto local.
        "source_reference":
            PurePosixPath(
                capture_id,
                source_filename,
            ).as_posix(),

        "destination_path":
            destination,

        "sha256":
            _sha256_bytes(
                content
            ),

        "size_bytes":
            len(
                content
            ),
    }


def _plan_identity(
    *,
    twin_key,
    materialization_mode,
    required_origin,
    required_profile_key,
    source_capture_ids,
    state_manifest,
    artifact_operations,
    source_evidence_sha256,
) -> dict:
    return {
        "twin_key":
            twin_key,

        "materialization_mode":
            materialization_mode,

        "generation_source":
            AUTO_TWIN_MATERIALIZATION_SOURCE_REAL_EVIDENCE,

        "required_origin":
            required_origin,

        "required_profile_key":
            required_profile_key,

        "source_capture_ids":
            list(
                source_capture_ids
            ),

        "state_manifest":
            deepcopy(
                list(
                    state_manifest
                )
            ),

        "artifact_operations":
            deepcopy(
                list(
                    artifact_operations
                )
            ),

        "source_evidence_sha256":
            source_evidence_sha256,
    }


def _load_supplemental_catalog_evidence(
    *,
    root,
    capture_id,
    expected_pathname,
    required_profile_key,
):
    """Valida evidencia catalogal suplementaria sin materializarla."""

    capture_id = _text(
        capture_id
    )

    if not capture_id:
        return {}

    path = (
        Path(root)
        / capture_id
        / "qcc_capture.json"
    )

    if not path.is_file():
        # QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_FAIL_OPEN_V1
        #
        # Catalog evidence is supplemental (see module docstring).
        # A historical supplemental capture that no longer exists on
        # disk must never crash reconciliation of the core physical
        # state; it is treated exactly like an absent catalog_capture_id.
        print(
            "[QCC-AUTO-TWIN-CATALOG] "
            "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_CAPTURE_MISSING:"
            + capture_id,
            flush=True,
        )

        return {}

    try:
        payload = json.loads(
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
            "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_CAPTURE_INVALID:"
            + capture_id
        ) from exc

    artifact = (
        build_catalog_runtime_payload(
            qcc_capture_payload=payload,
            source_capture_id=capture_id,
            expected_pathname=(
                expected_pathname
            ),
            required_profile_key=(
                required_profile_key
            ),
        )
    )

    catalog_count = int(
        artifact.get(
            "catalog_count"
        )
        or 0
    )

    if catalog_count <= 0:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_SUPPLEMENT_EMPTY:"
            + capture_id
        )

    return {
        "catalog_source_capture_id":
            capture_id,

        "catalog_fingerprint":
            str(
                artifact.get(
                    "catalog_fingerprint"
                )
                or ""
            ),

        "catalog_count":
            catalog_count,

        "catalog_option_count":
            int(
                artifact.get(
                    "option_count"
                )
                or 0
            ),
    }


from .navigation_transition_materialization import (
    normalize_twin_navigation_transitions,
)


def build_auto_twin_materialization_plan(
    *,
    twin_key,
    materialization_mode,
    state_sources,
    required_origin,
    required_profile_key,
    base_materialized_revision_id=None,
    navigation_transitions=(),
    root=(
        DEFAULT_QCC_SITE_ARCHITECTURE_ROOT
    ),
) -> dict:
    """Construye un plan sin efectuar ninguna escritura."""

    normalized_twin_key = _required_text(
        twin_key,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_TWIN_KEY_REQUIRED"
        ),
    )

    normalized_mode = _required_text(
        materialization_mode,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_MODE_REQUIRED"
        ),
    ).upper()

    if normalized_mode not in (
        AUTO_TWIN_MATERIALIZATION_MODES
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_MODE_INVALID"
        )

    normalized_origin = _required_text(
        required_origin,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_ORIGIN_REQUIRED"
        ),
    ).rstrip(
        "/"
    )

    normalized_profile = _required_text(
        required_profile_key,
        error=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PROFILE_REQUIRED"
        ),
    )

    if not isinstance(
        state_sources,
        (list, tuple),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_STATE_SOURCES_INVALID"
        )

    if not state_sources:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_STATE_SOURCES_EMPTY"
        )

    normalized_base_revision_id = (
        _text(
            base_materialized_revision_id
        )
        or None
    )

    normalized_navigation_transitions = (
        normalize_twin_navigation_transitions(
            navigation_transitions
        )
    )

    root_path = Path(
        root
    )

    state_ids = set()
    capture_ids = set()

    normalized_states = []
    artifact_operations = []

    for (
        state_index,
        raw_state,
    ) in enumerate(
        state_sources,
        start=1,
    ):
        if not isinstance(
            raw_state,
            dict,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_STATE_SOURCE_INVALID"
            )

        state_id = _safe_state_id(
            raw_state.get(
                "state_id"
            )
        )

        if state_id in state_ids:
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_STATE_ID_DUPLICATE"
            )

        state_ids.add(
            state_id
        )

        capture_id = _required_text(
            raw_state.get(
                "capture_id"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_CAPTURE_ID_REQUIRED"
            ),
        )

        if capture_id in capture_ids:
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_CAPTURE_ID_DUPLICATE"
            )

        capture_ids.add(
            capture_id
        )

        source_mode = (
            _text(
                raw_state.get(
                    "source_mode"
                )
            ).upper()
            or AUTO_TWIN_STATE_SOURCE_REAL_CAPTURE
        )

        if (
            source_mode
            == AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
        ):
            if not normalized_base_revision_id:
                raise ValueError(
                    "QCC_AUTO_TWIN_CARRY_FORWARD_BASE_REVISION_REQUIRED"
                )

            expected_pathname = _required_text(
                raw_state.get(
                    "pathname"
                ),
                error=(
                    "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PATHNAME_REQUIRED"
                ),
            )

            if not expected_pathname.startswith(
                "/"
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PATHNAME_INVALID"
                )

            expected_functional_state = (
                _text(
                    raw_state.get(
                        "functional_state"
                    )
                )
                or None
            )

            normalized_states.append({
                "state_index":
                    state_index,

                "state_id":
                    state_id,

                "source_capture_id":
                    capture_id,

                "pathname":
                    expected_pathname,

                "functional_state":
                    expected_functional_state,

                "fingerprint":
                    None,

                "rendering_profile_id":
                    "MATERIALIZED_CARRY_FORWARD",

                "source_mode":
                    (
                        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                    ),
            })

            continue

        if (
            source_mode
            != AUTO_TWIN_STATE_SOURCE_REAL_CAPTURE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_SOURCE_MODE_INVALID:"
                + source_mode
            )

        expected_pathname = _required_text(
            raw_state.get(
                "pathname"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PATHNAME_REQUIRED"
            ),
        )

        if not expected_pathname.startswith(
            "/"
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PATHNAME_INVALID"
            )

        expected_functional_state = (
            _text(
                raw_state.get(
                    "functional_state"
                )
            )
            or None
        )

        catalog_capture_id = (
            _text(
                raw_state.get(
                    "catalog_capture_id"
                )
            )
            or None
        )

        catalog_evidence = {}

        if catalog_capture_id:
            catalog_evidence = (
                _load_supplemental_catalog_evidence(
                    root=root_path,
                    capture_id=(
                        catalog_capture_id
                    ),
                    expected_pathname=(
                        expected_pathname
                    ),
                    required_profile_key=(
                        normalized_profile
                    ),
                )
            )

        bundle = (
            load_auto_twin_persisted_capture_bundle(
                capture_id=(
                    capture_id
                ),
                root=(
                    root_path
                ),
                require_viewport_image=True,
            )
        )

        capture = bundle.get(
            "capture"
        )

        if not isinstance(
            capture,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_BUNDLE_CAPTURE_INVALID"
            )

        if (
            _text(
                bundle.get(
                    "capture_id"
                )
            )
            != capture_id
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_CAPTURE_ID_MISMATCH"
            )

        if (
            _text(
                capture.get(
                    "browser_profile_key"
                )
            )
            != normalized_profile
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PROFILE_MISMATCH"
            )

        if (
            _text(
                capture.get(
                    "pathname"
                )
            )
            != expected_pathname
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PATHNAME_MISMATCH"
            )

        actual_functional_state = (
            _text(
                capture.get(
                    "functional_state"
                )
            )
            or None
        )

        if (
            actual_functional_state
            != expected_functional_state
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_FUNCTIONAL_STATE_MISMATCH"
            )

        actual_origin = _snapshot_origin(
            bundle.get(
                "snapshot"
            )
        )

        if (
            actual_origin
            != normalized_origin
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_ORIGIN_MISMATCH"
            )

        rendering_profile = bundle.get(
            "rendering_profile"
        )

        if not isinstance(
            rendering_profile,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_RENDERING_PROFILE_INVALID"
            )

        rendering_profile_id = _required_text(
            rendering_profile.get(
                "rendering_profile_id"
            ),
            error=(
                "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_RENDERING_PROFILE_ID_REQUIRED"
            ),
        )

        normalized_states.append({
            "state_index":
                state_index,

            "state_id":
                state_id,

            "source_capture_id":
                capture_id,

            "pathname":
                expected_pathname,

            "functional_state":
                expected_functional_state,

            "fingerprint":
                (
                    _text(
                        bundle.get(
                            "fingerprint"
                        )
                    )
                    or None
                ),

            "rendering_profile_id":
                rendering_profile_id,
        })

        if catalog_evidence:
            normalized_states[
                -1
            ].update(
                catalog_evidence
            )

        for (
            kind,
            source_filename,
            destination_suffix,
        ) in (
            AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS
        ):
            artifact_operations.append(
                _artifact_operation(
                    root=(
                        root_path
                    ),
                    capture_id=(
                        capture_id
                    ),
                    state_index=(
                        state_index
                    ),
                    state_id=(
                        state_id
                    ),
                    kind=kind,
                    source_filename=(
                        source_filename
                    ),
                    destination_suffix=(
                        destination_suffix
                    ),
                )
            )

    source_capture_ids = tuple(
        state[
            "source_capture_id"
        ]
        for state
        in normalized_states
    )

    # Hash de la evidencia fuente exacta. Incluye orden, estado,
    # capture identity y hashes de cada artefacto, pero nunca paths
    # absolutos del PC.
    source_evidence_identity = {
        "states":
            normalized_states,

        "artifacts":
            artifact_operations,

        "navigation_transitions":
            normalized_navigation_transitions,
    }

    if normalized_base_revision_id:
        source_evidence_identity[
            "base_materialized_revision_id"
        ] = normalized_base_revision_id

    source_evidence_sha256 = (
        _sha256_bytes(
            _canonical_json(
                source_evidence_identity
            )
        )
    )

    identity = _plan_identity(
        twin_key=(
            normalized_twin_key
        ),
        materialization_mode=(
            normalized_mode
        ),
        required_origin=(
            normalized_origin
        ),
        required_profile_key=(
            normalized_profile
        ),
        source_capture_ids=(
            source_capture_ids
        ),
        state_manifest=(
            normalized_states
        ),
        artifact_operations=(
            artifact_operations
        ),
        source_evidence_sha256=(
            source_evidence_sha256
        ),
    )

    if normalized_base_revision_id:
        identity[
            "base_materialized_revision_id"
        ] = normalized_base_revision_id

    identity[
        "navigation_transitions"
    ] = json.loads(
        json.dumps(
            normalized_navigation_transitions
        )
    )

    plan_id = (
        "matplan-"
        + _sha256_bytes(
            _canonical_json(
                identity
            )
        )[:24]
    )

    return {
        "schema_version":
            AUTO_TWIN_MATERIALIZATION_PLAN_SCHEMA_VERSION,

        "plan_type":
            AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,

        "plan_id":
            plan_id,

        **deepcopy(
            identity
        ),
    }
