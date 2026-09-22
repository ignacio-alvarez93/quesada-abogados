"""Materialización automática gobernada de conocimiento Discovery.

Pipeline:

    QCC REAL capture
        ↓
    AutoTwinObservationStore
        ↓
    baseline de nuevo estado
        ↓
    HTML + MHTML + viewport + arquitectura completos
        ↓
    MaterializationPlan
        ↓
    MaterializedRevision

Semántica:

- primera revisión:
      BOOTSTRAP_REAL

- estados nuevos posteriores:
      DISCOVERY_EXTENSION

- KNOWN sin cambio:
      no crea revisión

- CHANGED:
      no se procesa como Discovery Extension;
      pertenece a CandidateRevision / Validation

- no usa Golden;
- no promociona ACTIVE;
- no modifica CandidateRevisionStore;
- no ejecuta navegador;
- no hace interacción REAL.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import threading

from backend.qcc.site_architecture.ingestor import (
    QccSiteArchitectureIngestor,
)


from .catalog_refresh import (
    decide_catalog_refresh,
    materialized_catalog_provenance,
)

from .materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    materialize_auto_twin_plan,
)

from .navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,
    AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,
    AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,
    project_twin_eligible_navigation_candidates,
    rebind_contextual_supersession_navigation_targets,
)

from backend.qcc.context.navigation_context import (
    navigation_context_signature,
)

from .navigation_transition_runtime import (
    AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
    AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME,
)


from .materialization_plan import (
    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
    AUTO_TWIN_STATE_SOURCE_REAL_CAPTURE,
    build_auto_twin_materialization_plan,
)

from .materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION,
    AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH,
)

from .materialized_revision_store import (
    AutoTwinMaterializedRevisionStore,
)

from .profile_policy import (
    AUTO_TWIN_DISCOVERY_PROFILE_KEY,
)


AUTO_TWIN_AUTO_MATERIALIZATION_SCHEMA_VERSION = 1

AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED = (
    "MATERIALIZED"
)

AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE = (
    "NO_CHANGE"
)

AUTO_TWIN_AUTO_MATERIALIZATION_WAITING = (
    "WAITING_EVIDENCE"
)

AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED = (
    "SKIPPED"
)


DEFAULT_MATERIALIZED_ROOT = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "materialized"
)


REQUIRED_ARTIFACTS = (
    "metadata.json",
    "page.html",
    "page.mhtml",
    "qcc_capture.json",
    "screenshot_viewport.png",
    "site_architecture.json",
    "state_observation.json",
)


_LOCKS_GUARD = threading.RLock()
_LOCKS = {}


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _value(
    value,
    key,
    default=None,
):
    if isinstance(
        value,
        dict,
    ):
        return value.get(
            key,
            default,
        )

    return getattr(
        value,
        key,
        default,
    )


def _result(
    *,
    status,
    reason,
    twin_key=None,
    trigger_capture_id=None,
    revision_id=None,
    materialization_mode=None,
    state_count=None,
    added_state_count=None,
    plan_id=None,
    previous_revision_selection_mode=None,
    base_revision_id=None,
):
    return {
        "schema_version":
            AUTO_TWIN_AUTO_MATERIALIZATION_SCHEMA_VERSION,

        "status":
            status,

        "reason":
            reason,

        "twin_key":
            twin_key,

        "trigger_capture_id":
            trigger_capture_id,

        "materialized_revision_id":
            revision_id,

        "materialization_mode":
            materialization_mode,

        "state_count":
            state_count,

        "added_state_count":
            added_state_count,

        "plan_id":
            plan_id,

        # QCC_AUTO_TWIN_PREVIOUS_REVISION_PINNING_V1 (2D-20P)
        #
        # Proves which base/previous revision this reconciliation
        # actually used, and whether that selection was an explicit
        # governed pin or the default latest-revision lookup.
        "previous_revision_selection_mode":
            previous_revision_selection_mode,

        "base_revision_id":
            base_revision_id,
    }


def _lock_for(
    twin_key,
):
    with _LOCKS_GUARD:
        lock = _LOCKS.get(
            twin_key
        )

        if lock is None:
            lock = threading.RLock()

            _LOCKS[
                twin_key
            ] = lock

        return lock


def _same_path(
    left,
    right,
):
    try:
        return (
            Path(left).resolve()
            == Path(right).resolve()
        )

    except Exception:
        return (
            Path(left)
            == Path(right)
        )


def _materialized_root_for(
    capture_root,
):
    capture_root = Path(
        capture_root
    )

    normal_root = (
        Path("data")
        / "qcc"
        / "site_architecture"
    )

    if _same_path(
        capture_root,
        normal_root,
    ):
        return DEFAULT_MATERIALIZED_ROOT

    # Tests/temp environments nunca escriben
    # accidentalmente en data/qcc/auto_twin.
    return (
        capture_root.parent
        / "auto_twin_materialized"
    )


def _capture_dir(
    root,
    capture_id,
):
    return (
        Path(root)
        / capture_id
    )


def _missing_artifacts(
    root,
    capture_id,
):
    capture_dir = _capture_dir(
        root,
        capture_id,
    )

    return [
        filename
        for filename
        in REQUIRED_ARTIFACTS
        if not (
            capture_dir
            / filename
        ).is_file()
    ]


def _capture_profile_key(
    root,
    capture_id,
):
    path = (
        _capture_dir(
            root,
            capture_id,
        )
        / "qcc_capture.json"
    )

    if not path.is_file():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return None

    if not isinstance(
        payload,
        dict,
    ):
        return None

    # Contrato actual.
    profile_key = _text(
        payload.get(
            "browser_profile_key"
        )
    )

    # Compatibilidad defensiva.
    if (
        not profile_key
        and isinstance(
            payload.get(
                "capture"
            ),
            dict,
        )
    ):
        profile_key = _text(
            payload[
                "capture"
            ].get(
                "browser_profile_key"
            )
        )

    return (
        profile_key
        or None
    )


# QCC_AUTO_TWIN_VOLATILE_PATH_IDENTITY_V1
#
# Los parámetros de sesión del servidor no forman parte
# de la identidad funcional persistente de una superficie.
#
# Este contrato replica deliberadamente la normalización
# ya aplicada por state_fingerprint.py:
#
#   /path;jsessionid=SESSION_A
#   /path;jsessionid=SESSION_B
#   /path
#
# representan el mismo pathname funcional.
#
# No se eliminan otros path parameters.
_VOLATILE_PATH_SESSION_PARAMETER = re.compile(
    r";jsessionid=[^/?#;]*",
    re.IGNORECASE,
)


def _canonical_identity_pathname(
    pathname,
):
    normalized = (
        _text(
            pathname
        )
        or "/"
    )

    normalized = (
        _VOLATILE_PATH_SESSION_PARAMETER.sub(
            "",
            normalized,
        )
    )

    return (
        normalized
        or "/"
    )


def _identity(
    pathname,
    functional_state,
):
    return (
        _canonical_identity_pathname(
            pathname
        ),
        (
            _text(
                functional_state
            )
            or None
        ),
    )


def _state_id(
    state_key,
):
    normalized = _text(
        state_key
    ).upper()

    safe = "".join(
        character
        for character
        in normalized
        if (
            character.isalnum()
            or character == "_"
        )
    )

    if not safe:
        raise ValueError(
            "QCC_AUTO_TWIN_DISCOVERY_STATE_KEY_INVALID"
        )

    return (
        "AUTO_"
        + safe[:24]
    )


def _all_observed_twins(
    observation_store,
):
    # QCC_AUTO_TWIN_OBSERVATION_CURRENT_VIEW_V1
    #
    # Materialization must only ever see CURRENT/ACTIVE observation
    # state -- a state_key superseded via
    # AutoTwinObservationStore.supersede() (2D-20K) must never be
    # eligible here, even though it remains fully readable through the
    # store's default (historical) snapshot for audit purposes.
    snapshot = (
        observation_store
        .snapshot(
            current_only=True,
        )
    )

    if not isinstance(
        snapshot,
        dict,
    ):
        return {}

    twins = snapshot.get(
        "twins"
    )

    return (
        twins
        if isinstance(
            twins,
            dict,
        )
        else {}
    )


def _resolve_trigger_twin(
    *,
    twins,
    trigger_capture_id,
):
    capture_id = _text(
        trigger_capture_id
    )

    if not capture_id:
        return None

    matches = []

    for (
        twin_key,
        twin,
    ) in twins.items():
        if not isinstance(
            twin,
            dict,
        ):
            continue

        states = twin.get(
            "states",
            {},
        )

        if not isinstance(
            states,
            dict,
        ):
            continue

        for state in states.values():
            if not isinstance(
                state,
                dict,
            ):
                continue

            if capture_id in {
                _text(
                    state.get(
                        "baseline_capture_id"
                    )
                ),
                _text(
                    state.get(
                        "last_capture_id"
                    )
                ),
            }:
                matches.append(
                    _text(
                        twin_key
                    )
                )

                break

    matches = sorted(
        set(
            value
            for value
            in matches
            if value
        )
    )

    if len(matches) != 1:
        return None

    return matches[0]


def _renderer_refresh_capture_for_identity(
    *,
    renderer_refresh,
    observed_states,
    identity,
    trigger_capture_id,
):
    """Selecciona evidencia fresca sólo durante migración de renderer.

    No altera baseline_capture_id del Observation Store.

    Requisitos:
    - debe existir renderer refresh;
    - la identidad funcional debe ser exactamente la misma;
    - el trigger actual debe ser last_capture_id de esa identidad.

    De esta forma una observación KNOWN normal nunca genera una
    revisión por sí misma.
    """

    if not renderer_refresh:
        return None

    if not isinstance(
        observed_states,
        dict,
    ):
        return None

    trigger_capture_id = _text(
        trigger_capture_id
    )

    if not trigger_capture_id:
        return None

    matches = []

    for state in observed_states.values():
        if not isinstance(
            state,
            dict,
        ):
            continue

        current_identity = _identity(
            state.get(
                "pathname"
            ),
            state.get(
                "functional_state"
            ),
        )

        if current_identity != identity:
            continue

        last_capture_id = _text(
            state.get(
                "last_capture_id"
            )
        )

        if (
            last_capture_id
            == trigger_capture_id
        ):
            matches.append(
                last_capture_id
            )

    if len(matches) > 1:
        raise ValueError(
            "QCC_AUTO_TWIN_RENDERER_REFRESH_IDENTITY_AMBIGUOUS"
        )

    return (
        matches[0]
        if matches
        else None
    )



def _visual_main_frame_result(
    payload,
):
    if not isinstance(
        payload,
        dict,
    ):
        return {}

    frames = (
        payload.get(
            "frames"
        )
        or []
    )

    if not isinstance(
        frames,
        list,
    ):
        return {}

    for frame in frames:
        if (
            isinstance(
                frame,
                dict,
            )
            and frame.get(
                "frame_id"
            ) == 0
        ):
            result = frame.get(
                "result"
            )

            return (
                result
                if isinstance(
                    result,
                    dict,
                )
                else {}
            )

    return {}


def _visual_adopted_stylesheet_stats(
    payload,
):
    result = _visual_main_frame_result(
        payload
    )

    sheets = (
        result.get(
            "shadow_adopted_stylesheets"
        )
        or []
    )

    if not isinstance(
        sheets,
        list,
    ):
        sheets = []

    readable = [
        sheet
        for sheet in sheets
        if (
            isinstance(
                sheet,
                dict,
            )
            and sheet.get(
                "readable"
            )
            is True
            and _text(
                sheet.get(
                    "css_text"
                )
            )
        )
    ]

    return {
        "stylesheet_count":
            len(
                sheets
            ),

        "readable_count":
            len(
                readable
            ),

        "css_chars":
            sum(
                len(
                    str(
                        sheet.get(
                            "css_text"
                        )
                        or ""
                    )
                )
                for sheet
                in readable
            ),
    }


def _materialized_state_dir_by_id(
    *,
    revision_dir,
    state_id,
):
    revision_dir = Path(
        revision_dir
    )

    states_root = (
        revision_dir
        / "states"
    )

    if not states_root.is_dir():
        return None

    state_id = _text(
        state_id
    )

    matches = [
        path
        for path in states_root.glob(
            "*-" + state_id
        )
        if path.is_dir()
    ]

    if len(matches) > 1:
        raise ValueError(
            "QCC_AUTO_TWIN_MATERIALIZED_STATE_AMBIGUOUS:"
            + state_id
        )

    return (
        matches[0]
        if matches
        else None
    )




def _materialized_runtime_registry(
    revision_dir,
):
    if revision_dir is None:
        return None

    path = (
        Path(
            revision_dir
        )
        / "runtime"
        / "registry.json"
    )

    if not path.is_file():
        return None

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
    ):
        return None

    if not isinstance(
        payload,
        dict,
    ):
        return None

    return payload


def _materialized_state_fingerprints(
    revision_dir,
):
    registry = _materialized_runtime_registry(
        revision_dir
    )

    if registry is None:
        return frozenset()

    states = registry.get(
        "states"
    )

    if not isinstance(
        states,
        list,
    ):
        return frozenset()

    fingerprints = set()

    for state in states:
        if not isinstance(
            state,
            dict,
        ):
            continue

        fingerprint = _text(
            state.get(
                "fingerprint"
            )
        )

        if (
            fingerprint
            and len(
                fingerprint
            )
            == 64
            and all(
                character
                in "0123456789abcdefABCDEF"
                for character in fingerprint
            )
        ):
            fingerprints.add(
                fingerprint.lower()
            )

    return frozenset(
        fingerprints
    )



# QCC_AUTO_TWIN_FUNCTIONAL_FINGERPRINT_CANONICALIZATION_V1
#
# Site observation identity and physical Twin identity are deliberately
# different concepts:
#
# - pathname + functional_state remain useful observation metadata;
# - functional fingerprint is the authority for physical Twin state
#   uniqueness.
#
# A V2 fingerprint must therefore have exactly one physical
# representative inside a newly materialized revision.
def _normalized_materialized_fingerprint(
    value,
):
    fingerprint = _text(
        value
    )

    if (
        not fingerprint
        or len(
            fingerprint
        ) != 64
        or not all(
            character
            in "0123456789abcdefABCDEF"
            for character in fingerprint
        )
    ):
        return None

    return fingerprint.lower()


def _materialized_state_fingerprint_index(
    revision_dir,
):
    registry = _materialized_runtime_registry(
        revision_dir
    )

    if registry is None:
        return {}

    states = registry.get(
        "states"
    )

    if not isinstance(
        states,
        list,
    ):
        return {}

    result = {}

    for state in states:
        if not isinstance(
            state,
            dict,
        ):
            continue

        state_id = _text(
            state.get(
                "state_id"
            )
        )

        fingerprint = (
            _normalized_materialized_fingerprint(
                state.get(
                    "fingerprint"
                )
            )
        )

        if (
            not state_id
            or fingerprint is None
        ):
            continue

        previous = result.get(
            state_id
        )

        if (
            previous is not None
            and previous != fingerprint
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_MATERIALIZED_STATE_FINGERPRINT_AMBIGUOUS:"
                + state_id
            )

        result[
            state_id
        ] = fingerprint

    return result


def _physical_state_representative_rank(
    state,
):
    pathname = (
        _text(
            state.get(
                "pathname"
            )
        )
        or "/"
    )

    functional_state = _text(
        state.get(
            "functional_state"
        )
    )

    # Prefer:
    #
    # 1. richer recognized functional identity;
    # 2. pathname without volatile server session parameter;
    # 3. newest QCC capture (capture ids are chronological);
    # 4. deterministic state id tie-breaker.
    return (
        1 if functional_state else 0,
        (
            1
            if ";jsessionid=" not in pathname.lower()
            else 0
        ),
        _text(
            state.get(
                "source_capture_id"
            )
        ),
        _text(
            state.get(
                "state_id"
            )
        ),
    )


def _canonical_previous_states_by_fingerprint(
    previous_states,
    revision_dir,
):
    if not isinstance(
        previous_states,
        list,
    ):
        return tuple()

    fingerprint_by_state_id = (
        _materialized_state_fingerprint_index(
            revision_dir
        )
    )

    # Fail-open for revisions without runtime fingerprint authority.
    if not fingerprint_by_state_id:
        return tuple(
            previous_states
        )

    passthrough = []
    grouped = {}

    for index, state in enumerate(
        previous_states
    ):
        if not isinstance(
            state,
            dict,
        ):
            passthrough.append(
                (
                    index,
                    state,
                )
            )
            continue

        state_id = _text(
            state.get(
                "state_id"
            )
        )

        fingerprint = (
            fingerprint_by_state_id.get(
                state_id
            )
        )

        if fingerprint is None:
            passthrough.append(
                (
                    index,
                    state,
                )
            )
            continue

        grouped.setdefault(
            fingerprint,
            [],
        ).append(
            (
                index,
                state,
            )
        )

    selected = list(
        passthrough
    )

    for group in grouped.values():
        winner = max(
            group,
            key=lambda pair: (
                _physical_state_representative_rank(
                    pair[1]
                )
            ),
        )

        selected.append(
            winner
        )

    # Preserve physical ordering of the selected representatives.
    selected.sort(
        key=lambda pair: pair[0]
    )

    return tuple(
        state
        for _, state in selected
    )


def _observed_state_fingerprint(
    state_key,
    state,
):
    if not isinstance(
        state,
        dict,
    ):
        return None

    for value in (
        state.get(
            "last_fingerprint"
        ),
        state.get(
            "baseline_fingerprint"
        ),
        state_key,
    ):
        fingerprint = (
            _normalized_materialized_fingerprint(
                value
            )
        )

        if fingerprint is not None:
            return fingerprint

    return None


def _navigation_transition_signature(
    transition,
):
    if not isinstance(
        transition,
        dict,
    ):
        return None

    action = transition.get(
        "action"
    )

    if not isinstance(
        action,
        dict,
    ):
        return None

    identity = {
        "candidate_id":
            _text(
                transition.get(
                    "candidate_id"
                )
            ),

        "eligibility":
            _text(
                transition.get(
                    "eligibility"
                )
            ),

        "evidence_source":
            _text(
                transition.get(
                    "evidence_source"
                )
            ),

        "real_observation_count":
            int(
                transition.get(
                    "real_observation_count"
                )
                or 0
            ),

        "candidate_status":
            _text(
                transition.get(
                    "candidate_status"
                )
            ),

        "navigation_context":
            transition.get(
                "navigation_context"
            )
            or [],

        "context_signature":
            _text(
                transition.get(
                    "context_signature"
                )
            ),

        "before_fingerprint":
            (
                _text(
                    transition.get(
                        "before_fingerprint"
                    )
                )
                or ""
            ).lower(),

        "after_fingerprint":
            (
                _text(
                    transition.get(
                        "after_fingerprint"
                    )
                )
                or ""
            ).lower(),

        "action": {
            "kind":
                _text(
                    action.get(
                        "kind"
                    )
                ),

            "policy":
                _text(
                    action.get(
                        "policy"
                    )
                ),

            "selector":
                _text(
                    action.get(
                        "selector"
                    )
                ),

            "frame_path":
                (
                    _text(
                        action.get(
                            "frame_path"
                        )
                    )
                    or "main"
                ),
        },
    }

    return json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


def _materialized_navigation_signatures(
    revision_dir,
):
    if revision_dir is None:
        return frozenset()

    path = (
        Path(
            revision_dir
        )
        / "runtime"
        / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME
    )

    if not path.is_file():
        return frozenset()

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
    ):
        return frozenset()

    transitions = payload.get(
        "transitions"
    )

    if not isinstance(
        transitions,
        list,
    ):
        return frozenset()

    return frozenset(
        signature
        for signature in (
            _navigation_transition_signature(
                transition
            )
            for transition in transitions
        )
        if signature is not None
    )




# QCC_AUTO_TWIN_CAUSAL_EQUIVALENT_DISCOVERY_V1
#
# CAUSAL_LAST sigue siendo la autoridad causal primaria.
#
# Si esa captura concreta ha perdido evidencia pesada por
# retención, no degradamos el contrato a pathname/frecuencia.
#
# Únicamente podemos sustituir su representación física por
# otra captura:
#
# - TWIN_DISCOVERY;
# - físicamente completa;
# - con el MISMO fingerprint funcional backend-authoritative;
# - y, cuando existe estado semántico reconocido, con el
#   MISMO functional_state.
#
# Si no existe una equivalente válida, devolvemos CAUSAL_LAST
# original y la guarda existente *_EVIDENCE_INCOMPLETE sigue
# cerrando el pipeline.
def _capture_functional_fingerprint(
    capture_root,
    capture_id,
):
    path = (
        _capture_dir(
            capture_root,
            capture_id,
        )
        / "state_observation.json"
    )

    if not path.is_file():
        return None

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
    ):
        return None

    if not isinstance(
        payload,
        dict,
    ):
        return None

    fingerprint = _text(
        payload.get(
            "fingerprint"
        )
    ).lower()

    if (
        len(fingerprint) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in fingerprint
        )
    ):
        return None

    return fingerprint


def _capture_functional_state(
    capture_root,
    capture_id,
):
    path = (
        _capture_dir(
            capture_root,
            capture_id,
        )
        / "state_observation.json"
    )

    if not path.is_file():
        return None

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
    ):
        return None

    if not isinstance(
        payload,
        dict,
    ):
        return None

    return (
        _text(
            payload.get(
                "state"
            )
            or payload.get(
                "functional_state"
            )
        )
        or None
    )


def _complete_discovery_capture_for_fingerprint(
    *,
    capture_root,
    fingerprint,
    functional_state=None,
    exclude_capture_id=None,
):
    fingerprint = _text(
        fingerprint
    ).lower()

    if (
        len(fingerprint) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in fingerprint
        )
    ):
        return None

    functional_state = (
        _text(
            functional_state
        )
        or None
    )

    exclude_capture_id = _text(
        exclude_capture_id
    )

    root = Path(
        capture_root
    )

    if not root.is_dir():
        return None

    candidates = []

    for directory in root.iterdir():

        if not directory.is_dir():
            continue

        candidate_id = _text(
            directory.name
        )

        if (
            not candidate_id
            or candidate_id
            == exclude_capture_id
        ):
            continue

        if _missing_artifacts(
            root,
            candidate_id,
        ):
            continue

        if (
            _capture_profile_key(
                root,
                candidate_id,
            )
            != AUTO_TWIN_DISCOVERY_PROFILE_KEY
        ):
            continue

        candidate_fingerprint = (
            _capture_functional_fingerprint(
                root,
                candidate_id,
            )
        )

        if (
            candidate_fingerprint
            != fingerprint
        ):
            continue

        if functional_state is not None:

            candidate_state = (
                _capture_functional_state(
                    root,
                    candidate_id,
                )
            )

            if (
                candidate_state
                != functional_state
            ):
                continue

        candidates.append(
            candidate_id
        )

    # Los capture_id QCC comienzan por timestamp UTC:
    #
    # YYYYMMDD_HHMMSS_microseconds_...
    #
    # por lo que max() selecciona de forma determinista
    # la evidencia completa más reciente.
    return (
        max(
            candidates
        )
        if candidates
        else None
    )


# QCC_AUTO_TWIN_CAUSAL_BASELINE_FALLBACK_V1 (2D-20U)
#
# _complete_discovery_capture_for_fingerprint() above is indexed by
# each capture's own cached state_observation.json fingerprint -- the
# pre-2D-20H generic value. For a site/state whose physical identity
# is only disambiguated by a narrow, provider-specific capability
# augmentation applied later at re-ingestion time (2D-20H's
# apply_mercurio_functional_fingerprint_capability), that cached value
# can never distinguish two governed replacements (e.g. EX01_PERSONAL
# TITULAR vs FAMILIAR) -- CAUSAL_EQUIVALENT then legitimately finds
# nothing, exactly as designed.
#
# This is a narrower, LAST-resort fallback for exactly that gap: the
# state's own already-recorded baseline_capture_id (set once, on the
# state's first observe(), and never rewritten) may be used instead --
# but ONLY after an INDEPENDENT re-validation, never by trusting any
# cached/recorded value. Re-validation runs the same in-memory
# adapt+normalize+recognize pipeline used everywhere else in this
# codebase (QccSiteArchitectureIngestor.observe_candidate(), the
# canonical read-only observe gate) directly against the baseline
# capture's raw bytes, and requires ALL of:
#
# - readable required artifacts;
# - the EXACT same recomputed CURRENT functional fingerprint;
# - the same functional_state family;
# - the same state_variant_key/capability identity, when the state
#   being materialized declares one;
# - the same site_code, when the caller supplies one to check against.
#
# Being older, already recorded on the state, or sharing route/context
# is never, by itself, sufficient -- any missing/ambiguous/mismatched
# signal fails closed (returns None), leaving the caller's existing
# CAUSAL_LAST fail-closed behavior completely unchanged.
def _recompute_capture_identity(
    capture_root,
    capture_id,
):
    """Independently recompute one capture's CURRENT identity.

    Never reads a capture's cached state_observation.json, and never
    reads anything already recorded on an observation-store state.
    Read-only: adapts + normalizes + recognizes entirely in memory: no
    directory is created, no artifact is persisted, no context/live
    navigation is touched. Returns None on any read/parse/pipeline
    failure -- provider-neutral, fail-closed.
    """

    path = (
        _capture_dir(
            capture_root,
            capture_id,
        )
        / "qcc_capture.json"
    )

    if not path.is_file():
        return None

    try:
        raw_capture = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None

    try:
        # QccSiteArchitectureIngestor.observe_candidate() is the
        # canonical read-only gate: it adapts + normalizes + observes
        # the RAW capture payload entirely in memory itself -- it must
        # never be handed an already-adapted/normalized snapshot.
        observed = (
            QccSiteArchitectureIngestor()
            .observe_candidate(
                raw_capture
            )
        )

    except Exception:
        return None

    if not isinstance(
        observed,
        dict,
    ):
        return None

    fingerprint = _text(
        observed.get(
            "fingerprint"
        )
    ).lower()

    if not fingerprint:
        return None

    state_observation = (
        observed.get(
            "state_observation"
        )
        or {}
    )

    return {
        "site_code":
            observed.get(
                "site_code"
            ),

        "functional_state":
            observed.get(
                "functional_state"
            ),

        "fingerprint":
            fingerprint,

        "state_variant_key":
            (
                state_observation.get(
                    "state_variant_key"
                )
                if isinstance(
                    state_observation,
                    dict,
                )
                else None
            ),
    }


def _causal_baseline_fallback_capture(
    state,
    *,
    capture_root,
    last_fingerprint,
    baseline_capture_id,
    last_capture_id,
    expected_site_code=None,
):
    """Governed last-resort baseline fallback -- see the module note
    QCC_AUTO_TWIN_CAUSAL_BASELINE_FALLBACK_V1 above for the exact
    fail-closed contract. Returns baseline_capture_id only when every
    invariant holds; otherwise None.
    """

    if (
        not baseline_capture_id
        or baseline_capture_id
        == last_capture_id
    ):
        return None

    if not last_fingerprint:
        return None

    if capture_root is None:
        return None

    if _missing_artifacts(
        capture_root,
        baseline_capture_id,
    ):
        return None

    identity = _recompute_capture_identity(
        capture_root,
        baseline_capture_id,
    )

    if identity is None:
        return None

    if (
        identity.get(
            "fingerprint"
        )
        != last_fingerprint
    ):
        return None

    expected_functional_state = _text(
        state.get(
            "functional_state"
        )
    )

    if (
        expected_functional_state
        and _text(
            identity.get(
                "functional_state"
            )
        )
        != expected_functional_state
    ):
        return None

    expected_state_variant_key = _text(
        state.get(
            "state_variant_key"
        )
    )

    if (
        expected_state_variant_key
        and _text(
            identity.get(
                "state_variant_key"
            )
        )
        != expected_state_variant_key
    ):
        return None

    expected_site_code = _text(
        expected_site_code
    )

    if (
        expected_site_code
        and _text(
            identity.get(
                "site_code"
            )
        ).upper()
        != expected_site_code.upper()
    ):
        return None

    return baseline_capture_id


def _new_state_navigation_source(
    state,
    navigation_candidates,
    *,
    capture_root=None,
    expected_site_code=None,
):
    """Choose source evidence for one not-yet-materialized state.

    Default remains the immutable baseline capture.

    Only when the state's current fingerprint is explicitly referenced
    by trusted TWIN_ELIGIBLE causal evidence may its last capture become
    the physical source used for Twin validation.

    CAUSAL_LAST remains primary. A physically incomplete CAUSAL_LAST
    may use an exact-fingerprint complete TWIN_DISCOVERY equivalent
    (CAUSAL_EQUIVALENT), or -- only when that also finds nothing -- the
    state's own independently re-validated baseline_capture_id
    (CAUSAL_BASELINE_FALLBACK, 2D-20U). Existing fail-closed behavior
    is unchanged when none of these apply.
    """

    if not isinstance(
        state,
        dict,
    ):
        return (
            None,
            "BASELINE",
        )

    baseline_capture_id = _text(
        state.get(
            "baseline_capture_id"
        )
    )

    endpoint_fingerprints = set()

    for candidate in (
        navigation_candidates
        or ()
    ):
        if not isinstance(
            candidate,
            dict,
        ):
            continue

        for key in (
            "before_fingerprint",
            "after_fingerprint",
        ):
            fingerprint = _text(
                candidate.get(
                    key
                )
            )

            if fingerprint:
                endpoint_fingerprints.add(
                    fingerprint.lower()
                )

    last_fingerprint = _text(
        state.get(
            "last_fingerprint"
        )
    ).lower()

    if (
        last_fingerprint
        and last_fingerprint
        in endpoint_fingerprints
    ):
        last_capture_id = _text(
            state.get(
                "last_capture_id"
            )
        )

        if (
            capture_root is not None
            and last_capture_id
            and _missing_artifacts(
                capture_root,
                last_capture_id,
            )
        ):
            equivalent_capture_id = (
                _complete_discovery_capture_for_fingerprint(
                    capture_root=(
                        capture_root
                    ),
                    fingerprint=(
                        last_fingerprint
                    ),
                    functional_state=(
                        state.get(
                            "functional_state"
                        )
                    ),
                    exclude_capture_id=(
                        last_capture_id
                    ),
                )
            )

            if equivalent_capture_id:
                return (
                    equivalent_capture_id,
                    "CAUSAL_EQUIVALENT",
                )

            baseline_fallback_capture_id = (
                _causal_baseline_fallback_capture(
                    state,
                    capture_root=(
                        capture_root
                    ),
                    last_fingerprint=(
                        last_fingerprint
                    ),
                    baseline_capture_id=(
                        baseline_capture_id
                    ),
                    last_capture_id=(
                        last_capture_id
                    ),
                    expected_site_code=(
                        expected_site_code
                    ),
                )
            )

            if baseline_fallback_capture_id:
                return (
                    baseline_fallback_capture_id,
                    "CAUSAL_BASELINE_FALLBACK",
                )

        return (
            last_capture_id,
            "CAUSAL_LAST",
        )

    return (
        baseline_capture_id,
        "BASELINE",
    )


# QCC_AUTO_TWIN_NAVIGATION_CARRY_FORWARD_V1
#
# projected_navigation_candidates reflects whatever the CURRENT
# HumanNavigationCandidateStore snapshot happens to contain for this
# one materialization pass. That snapshot store is an isolated
# evidence source: it may legitimately be empty, partial, or simply
# not passed at all (human_navigation_candidate_store=None) without
# that meaning any previously materialized navigation capability has
# become physically invalid.
#
# A previously materialized revision's own navigation_transitions.json
# is itself durable proof that those candidate_ids were, at the time,
# validated against physically resolvable endpoints. This reconstructs
# an equivalent candidate for any candidate_id the live snapshot does
# not currently carry, so it gets a chance to pass through the exact
# same fingerprint-existence gate
# (_navigation_refresh_for_latest_revision) as any live candidate --
# never bypassing it, never aliasing fingerprints, never inventing
# evidence. A transition whose physical endpoint has genuinely stopped
# existing there, or whose action route has become ambiguous, is
# dropped by that same unchanged gate exactly as it already was.
def _materialized_navigation_transitions(
    revision_dir,
):
    if revision_dir is None:
        return ()

    path = (
        Path(
            revision_dir
        )
        / "runtime"
        / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME
    )

    if not path.is_file():
        return ()

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
    ):
        return ()

    transitions = payload.get(
        "transitions"
    )

    if not isinstance(
        transitions,
        list,
    ):
        return ()

    return tuple(
        transition
        for transition in transitions
        if isinstance(
            transition,
            dict,
        )
    )


def _reconstruct_navigation_candidate(
    runtime_transition,
):
    action = runtime_transition.get(
        "action"
    )

    if not isinstance(
        action,
        dict,
    ):
        return None

    candidate_id = _text(
        runtime_transition.get(
            "candidate_id"
        )
    )

    before_fingerprint = _text(
        runtime_transition.get(
            "before_fingerprint"
        )
    )

    after_fingerprint = _text(
        runtime_transition.get(
            "after_fingerprint"
        )
    )

    selector = _text(
        action.get(
            "selector"
        )
    )

    kind = _text(
        action.get(
            "kind"
        )
    )

    policy = _text(
        action.get(
            "policy"
        )
    )

    observation_count = int(
        runtime_transition.get(
            "real_observation_count"
        )
        or 0
    )

    if (
        not candidate_id
        or not before_fingerprint
        or not after_fingerprint
        or not selector
        or not kind
        or not policy
        or observation_count < 1
    ):
        return None

    return {
        "schema_version":
            AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,

        "candidate_id":
            candidate_id,

        "eligibility":
            AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,

        "evidence_source":
            AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

        "real_observation_count":
            observation_count,

        # Preserved from the already-materialized record (rather than
        # a synthetic marker) so an unchanged carried-forward
        # candidate reproduces the exact same signature and this pass
        # stays idempotent when nothing physically changed.
        "candidate_status":
            _text(
                runtime_transition.get(
                    "candidate_status"
                )
            )
            or "UNKNOWN",

        "navigation_context":
            runtime_transition.get(
                "navigation_context"
            )
            or (),

        # Recomputed from the carried-forward navigation_context
        # (same derivation as the original materialization) rather
        # than copied, so a contextual transition keeps the identical
        # context_signature every reconcile pass instead of losing it.
        "context_signature":
            navigation_context_signature(
                runtime_transition.get(
                    "navigation_context"
                )
                or ()
            ),

        "before_fingerprint":
            before_fingerprint,

        "after_fingerprint":
            after_fingerprint,

        "action": {
            "kind":
                kind,

            "policy":
                policy,

            "selector":
                selector,

            "frame_path":
                _text(
                    action.get(
                        "frame_path"
                    )
                )
                or "main",
        },
    }


def _carry_forward_navigation_candidates(
    revision_dir,
    candidates,
):
    """Union live candidates with still-unclaimed materialized ones.

    Never overrides a live candidate: a candidate_id present in the
    live snapshot always wins over its carried-forward reconstruction.
    """

    live = tuple(
        candidate
        for candidate in (
            candidates
            or ()
        )
        if isinstance(
            candidate,
            dict,
        )
    )

    claimed_candidate_ids = {
        _text(
            candidate.get(
                "candidate_id"
            )
        )
        for candidate in live
    }

    carried = []

    for runtime_transition in (
        _materialized_navigation_transitions(
            revision_dir
        )
    ):
        candidate_id = _text(
            runtime_transition.get(
                "candidate_id"
            )
        )

        if (
            not candidate_id
            or candidate_id
            in claimed_candidate_ids
        ):
            continue

        reconstructed = (
            _reconstruct_navigation_candidate(
                runtime_transition
            )
        )

        if reconstructed is None:
            continue

        carried.append(
            reconstructed
        )

        claimed_candidate_ids.add(
            candidate_id
        )

    return (
        live
        + tuple(
            carried
        )
    )


def _navigation_refresh_for_latest_revision(
    *,
    revision_dir,
    candidates,
):
    """Select navigation evidence whose A/B states physically exist.

    Conservative rule:
    a transition becomes materializable only after both fingerprints
    already exist in the latest immutable Twin revision.

    Therefore a state discovered in the same capture is materialized
    first; its transition becomes eligible on the next reconcile.
    """

    fingerprints = (
        _materialized_state_fingerprints(
            revision_dir
        )
    )

    materializable = tuple(
        candidate
        for candidate in candidates
        if (
            candidate[
                "before_fingerprint"
            ]
            in fingerprints
            and candidate[
                "after_fingerprint"
            ]
            in fingerprints
        )
    )

    desired_signatures = frozenset(
        _navigation_transition_signature(
            candidate
        )
        for candidate in materializable
    )

    current_signatures = (
        _materialized_navigation_signatures(
            revision_dir
        )
    )

    return (
        materializable,
        desired_signatures
        != current_signatures,
    )


# QCC_AUTO_TWIN_CAUSAL_REFRESH_NAVIGATION_REBIND_V1
#
# Materialized navigation capability belongs to the stable physical
# state identity (state_id), not permanently to one historical
# fingerprint value.
#
# When QCC_AUTO_TWIN_EXISTING_STATE_CAUSAL_REFRESH_V1 replaces a
# state's physical fingerprint OLD with NEW while explicitly
# preserving the same state_id, an already-selected navigation
# transition that still references OLD as a physical endpoint is
# rebound to NEW for this materialization pass only.
#
# This never mutates historical evidence: the human navigation
# candidate store keeps recording OLD, unchanged. Only this pass's
# local, in-memory transition list (already frozen/selected earlier
# by _navigation_refresh_for_latest_revision) is rewritten.
#
# Not a generic fingerprint-aliasing mechanism: a transition whose
# endpoint was refreshed this pass but failed the governed
# uniqueness/no-ambiguity checks in the causal-refresh loop is
# dropped (deferred) rather than guessed or left to crash the
# navigation runtime downstream.
def _rebind_causal_refresh_navigation_endpoints(
    transitions,
    rebind_map,
    unresolved_old_fingerprints,
):
    rebound = []

    for transition in transitions:
        before = transition.get(
            "before_fingerprint"
        )

        after = transition.get(
            "after_fingerprint"
        )

        if (
            before in unresolved_old_fingerprints
            or after in unresolved_old_fingerprints
        ):
            continue

        if (
            before in rebind_map
            or after in rebind_map
        ):
            transition = dict(
                transition
            )

            if before in rebind_map:
                transition[
                    "before_fingerprint"
                ] = rebind_map[
                    before
                ]

            if after in rebind_map:
                transition[
                    "after_fingerprint"
                ] = rebind_map[
                    after
                ]

        rebound.append(
            transition
        )

    return tuple(
        rebound
    )


def _visual_enrichment_for_previous_state(
    *,
    renderer_refresh,
    capture_root,
    revision_dir,
    previous_state_id,
    identity,
    observed_states,
    trigger_capture_id,
):
    """Detecta enriquecimiento de evidencia, no cambio de sede.

    Requisitos estrictos:
    - renderer ya actual;
    - misma identidad funcional;
    - trigger == last_capture_id;
    - clasificación KNOWN;
    - fingerprint baseline == last;
    - la revisión materializada carecía de CSS adoptado legible;
    - el trigger añade esa capability.
    """

    if (
        renderer_refresh
        or revision_dir is None
    ):
        return None

    matches = []

    for state in (
        observed_states.values()
        if isinstance(
            observed_states,
            dict,
        )
        else ()
    ):
        if not isinstance(
            state,
            dict,
        ):
            continue

        if (
            _identity(
                state.get(
                    "pathname"
                ),
                state.get(
                    "functional_state"
                ),
            )
            != identity
        ):
            continue

        if (
            _text(
                state.get(
                    "last_capture_id"
                )
            )
            != _text(
                trigger_capture_id
            )
        ):
            continue

        matches.append(
            state
        )

    if len(matches) != 1:
        return None

    observed = matches[0]

    if (
        _text(
            observed.get(
                "last_classification"
            )
        ).upper()
        != "KNOWN"
    ):
        return None

    baseline_fingerprint = _text(
        observed.get(
            "baseline_fingerprint"
        )
    )

    last_fingerprint = _text(
        observed.get(
            "last_fingerprint"
        )
    )

    if (
        baseline_fingerprint
        and last_fingerprint
        and baseline_fingerprint
        != last_fingerprint
    ):
        return None

    state_dir = (
        _materialized_state_dir_by_id(
            revision_dir=(
                revision_dir
            ),
            state_id=(
                previous_state_id
            ),
        )
    )

    if state_dir is None:
        return None

    old_capture_path = (
        state_dir
        / "evidence"
        / "qcc_capture.json"
    )

    if not old_capture_path.is_file():
        return None

    try:
        old_payload = json.loads(
            old_capture_path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return None

    new_payload = _load_qcc_capture(
        capture_root,
        trigger_capture_id,
    )

    if not isinstance(
        new_payload,
        dict,
    ):
        return None

    old_stats = (
        _visual_adopted_stylesheet_stats(
            old_payload
        )
    )

    new_stats = (
        _visual_adopted_stylesheet_stats(
            new_payload
        )
    )

    # Dominancia de capability, no comparación arbitraria
    # de cantidades entre dos capturas que ya poseen la capability.
    if (
        old_stats[
            "readable_count"
        ] == 0
        and new_stats[
            "readable_count"
        ] > 0
        and new_stats[
            "css_chars"
        ] > 0
    ):
        return {
            "identity":
                identity,

            "capture_id":
                _text(
                    trigger_capture_id
                ),

            "previous_state_id":
                _text(
                    previous_state_id
                ),

            "old_stats":
                old_stats,

            "new_stats":
                new_stats,
        }

    return None


def _materialized_revision_dir(
    *,
    materialized_root,
    twin_key,
    revision,
):
    if not isinstance(
        revision,
        dict,
    ):
        return None

    revision_id = _text(
        revision.get(
            "materialized_revision_id"
        )
    )

    if not revision_id:
        return None

    return (
        Path(
            materialized_root
        )
        / twin_key
        / revision_id
    )


def _load_qcc_capture(
    capture_root,
    capture_id,
):
    path = (
        _capture_dir(
            capture_root,
            capture_id,
        )
        / "qcc_capture.json"
    )

    if not path.is_file():
        return None

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
    ):
        return None

    return (
        payload
        if isinstance(
            payload,
            dict,
        )
        else None
    )


def _catalog_refresh_identity_for_trigger(
    *,
    observed_states,
    known_identities,
    trigger_capture_id,
):
    """Busca una identidad ya materializada cuyo last_capture sea trigger.

    Returns (identity, discriminator) -- discriminator carries the
    matching state's own governed state_id/fingerprint/
    state_variant_key (2D-20W), so a caller can resolve
    _current_state_metadata() against the exact governed variant this
    trigger belongs to when its (pathname, functional_state) family
    now legitimately holds more than one CURRENT state. (None, None)
    when no state matches.
    """

    if not isinstance(
        observed_states,
        dict,
    ):
        return None, None

    trigger_capture_id = _text(
        trigger_capture_id
    )

    if not trigger_capture_id:
        return None, None

    matches = []

    for state in observed_states.values():
        if not isinstance(
            state,
            dict,
        ):
            continue

        if (
            _text(
                state.get(
                    "last_capture_id"
                )
            )
            != trigger_capture_id
        ):
            continue

        current_identity = _identity(
            state.get(
                "pathname"
            ),
            state.get(
                "functional_state"
            ),
        )

        if (
            current_identity
            not in known_identities
        ):
            # Estado nuevo → Discovery Extension.
            continue

        # QCC_AUTO_TWIN_CATALOG_REFRESH_ORTHOGONAL_TO_VISUAL_CHANGE
        #
        # No filtramos por last_classification.
        #
        # CHANGED gobierna la adopción de evidencia visual/DOM mediante
        # CandidateRevision, pero el catálogo es evidencia suplementaria
        # independiente:
        #
        # - la identidad debe existir ya en la revisión materializada;
        # - el trigger debe ser exactamente last_capture_id;
        # - el perfil debe ser twin_discovery;
        # - Catalog Refresh NO rebindea source_capture_id visual.
        #
        # Por tanto un KNOWN identity marcado CHANGED puede aportar
        # conocimiento catalogal sin adoptar el cambio visual.
        matches.append(
            (current_identity, state)
        )

    unique = []

    for identity, _state in matches:
        if identity not in unique:
            unique.append(
                identity
            )

    if len(unique) > 1:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_REFRESH_TRIGGER_IDENTITY_AMBIGUOUS"
        )

    if not matches:
        return None, None

    resolved_identity, resolved_state = matches[0]

    discriminator = {
        "state_id": (
            _state_id(
                resolved_state.get(
                    "state_key"
                )
            )
            if resolved_state.get(
                "state_key"
            )
            else None
        ),

        "fingerprint": (
            _text(
                resolved_state.get(
                    "last_fingerprint"
                )
            )
            or None
        ),

        "state_variant_key": (
            _text(
                resolved_state.get(
                    "state_variant_key"
                )
            )
            or None
        ),
    }

    return resolved_identity, discriminator


def _catalog_refresh_decision_for_trigger(
    *,
    revision_dir,
    capture_root,
    trigger_capture_id,
    identity,
    discriminator=None,
):
    """Compara REAL catalog evidence contra el Twin actual.

    ``discriminator`` (2D-20W) carries the trigger's own governed
    state_id/fingerprint/state_variant_key -- consulted by
    decide_catalog_refresh()/_current_state_metadata() ONLY when the
    (pathname, functional_state) family it belongs to now holds more
    than one legitimate CURRENT variant. A family with a single
    CURRENT state ignores it entirely, preserving prior behavior.
    """

    if (
        revision_dir is None
        or not Path(
            revision_dir
        ).is_dir()
    ):
        return None

    profile_key = (
        _capture_profile_key(
            capture_root,
            trigger_capture_id,
        )
    )

    if (
        profile_key
        != AUTO_TWIN_DISCOVERY_PROFILE_KEY
    ):
        return None

    qcc_capture = (
        _load_qcc_capture(
            capture_root,
            trigger_capture_id,
        )
    )

    if not isinstance(
        qcc_capture,
        dict,
    ):
        return None

    # QCC_AUTO_TWIN_CATALOG_LEGACY_CAPTURE_FAIL_OPEN
    #
    # Catalog evidence is supplemental.
    #
    # Capturas históricas/pre-catalog y fixtures antiguos pueden
    # tener qcc_capture.json válido para el pipeline original pero
    # no contener todavía frames/result/catalog_probe.
    #
    # Esa ausencia NO convierte un KNOWN normal en error y NO debe
    # bloquear Discovery/Renderer/Candidate semantics.
    frames = (
        qcc_capture.get(
            "frames"
        )
        or []
    )

    if not isinstance(
        frames,
        list,
    ):
        return None

    main_frame = next(
        (
            frame
            for frame in frames
            if (
                isinstance(
                    frame,
                    dict,
                )
                and frame.get(
                    "frame_id"
                ) == 0
            )
        ),
        None,
    )

    if main_frame is None:
        main_frame = next(
            (
                frame
                for frame in frames
                if isinstance(
                    frame,
                    dict,
                )
            ),
            None,
        )

    if main_frame is None:
        return None

    main_result = (
        main_frame.get(
            "result"
        )
        or {}
    )

    if not isinstance(
        main_result,
        dict,
    ):
        return None

    catalog_probe = (
        main_result.get(
            "catalog_probe"
        )
    )

    if not isinstance(
        catalog_probe,
        dict,
    ):
        return None

    decision = (
        decide_catalog_refresh(
            qcc_capture_payload=(
                qcc_capture
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
            revision_dir=(
                revision_dir
            ),
            pathname=(
                identity[0]
            ),
            functional_state=(
                identity[1]
            ),
            required_profile_key=(
                AUTO_TWIN_DISCOVERY_PROFILE_KEY
            ),
            state_id=(
                (discriminator or {}).get(
                    "state_id"
                )
            ),
            fingerprint=(
                (discriminator or {}).get(
                    "fingerprint"
                )
            ),
            state_variant_key=(
                (discriminator or {}).get(
                    "state_variant_key"
                )
            ),
        )
    )

    return (
        decision
        if isinstance(
            decision,
            dict,
        )
        else None
    )


def _managed_origin(
    managed,
):
    origins = _value(
        managed,
        "origins",
        None,
    )

    if isinstance(
        origins,
        (list, tuple),
    ):
        values = [
            _text(value).rstrip("/")
            for value
            in origins
            if _text(value)
        ]

        if len(values) == 1:
            return values[0]

        if len(values) > 1:
            return None

    origin = _text(
        _value(
            managed,
            "origin",
            None,
        )
    ).rstrip("/")

    return (
        origin
        or None
    )


def _latest_revision(
    store,
    twin_key,
):
    revisions = list(
        store.list(
            twin_key=twin_key
        )
        or []
    )

    if not revisions:
        return None

    return revisions[-1]


# QCC_AUTO_TWIN_PREVIOUS_REVISION_PINNING_V1 (2D-20P)
AUTO_TWIN_PREVIOUS_REVISION_SELECTION_PINNED = (
    "PINNED"
)

AUTO_TWIN_PREVIOUS_REVISION_SELECTION_DEFAULT_LATEST = (
    "DEFAULT_LATEST"
)


def _select_previous_revision(
    store,
    twin_key,
    *,
    previous_revision_id=None,
):
    """Resolve the previous/base revision for reconciliation.

    Backward compatible by construction: with no explicit
    ``previous_revision_id``, this is byte-for-byte the same lookup
    ``_latest_revision`` always performed (DEFAULT_LATEST).

    With an explicit ``previous_revision_id``, it is validated against
    exactly this twin's own revisions (``store.list(twin_key=...)`` is
    already twin-scoped, so a revision id belonging to another
    twin/site can never match here) and used exactly as found --
    regardless of any newer revision that may exist. If it is not
    found, this returns ``(None, PINNED)``: the caller must fail
    closed and must NEVER reinterpret that as "no previous revision"
    (which would silently fall back to bootstrap/latest semantics).
    """

    normalized_pin = (
        _text(
            previous_revision_id
        )
        or None
    )

    if normalized_pin is None:
        return (
            _latest_revision(
                store,
                twin_key,
            ),
            AUTO_TWIN_PREVIOUS_REVISION_SELECTION_DEFAULT_LATEST,
        )

    revisions = list(
        store.list(
            twin_key=twin_key
        )
        or []
    )

    for revision in revisions:
        if (
            isinstance(
                revision,
                dict,
            )
            and _text(
                revision.get(
                    "materialized_revision_id"
                )
            )
            == normalized_pin
        ):
            return (
                revision,
                AUTO_TWIN_PREVIOUS_REVISION_SELECTION_PINNED,
            )

    return (
        None,
        AUTO_TWIN_PREVIOUS_REVISION_SELECTION_PINNED,
    )



# QCC_AUTO_TWIN_REFRESH_DIMENSIONS_V1
#
# Renderer físico y runtime de navegación tienen ciclos
# de invalidación independientes.
#
# Un cambio únicamente del adapter de navegación NO exige
# reconstruir HTML/MHTML/screenshots de todos los estados.
def _physical_renderer_refresh_required(
#
# Un cambio físico del renderer SÍ conserva el contrato
# estricto de evidencia Discovery fresca.
    *,
    materialized_root,
    twin_key,
    revision,
):
    if not isinstance(
        revision,
        dict,
    ):
        return False

    revision_id = _text(
        revision.get(
            "materialized_revision_id"
        )
    )

    if not revision_id:
        return False

    revision_dir = (
        Path(
            materialized_root
        )
        / twin_key
        / revision_id
    )

    # Synthetic/unit-test revision metadata may not have
    # a physical materialized directory.
    if not revision_dir.is_dir():
        return False

    marker_path = (
        revision_dir
        / "runtime"
        / "renderer.json"
    )

    if not marker_path.is_file():
        return True

    try:
        payload = json.loads(
            marker_path.read_text(
                encoding="utf-8"
            )
        )

        version = int(
            payload.get(
                "renderer_version"
            )
        )

    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return True

    return (
        version
        != AUTO_TWIN_RUNTIME_RENDERER_VERSION
    )


def _navigation_runtime_refresh_required(
    *,
    materialized_root,
    twin_key,
    revision,
):
    if not isinstance(
        revision,
        dict,
    ):
        return False

    revision_id = _text(
        revision.get(
            "materialized_revision_id"
        )
    )

    if not revision_id:
        return False

    revision_dir = (
        Path(
            materialized_root
        )
        / twin_key
        / revision_id
    )

    if not revision_dir.is_dir():
        return False

    navigation_path = (
        revision_dir
        / "runtime"
        / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME
    )

    if not navigation_path.is_file():
        return True

    try:
        payload = json.loads(
            navigation_path.read_text(
                encoding="utf-8"
            )
        )

        adapter_version = int(
            payload.get(
                "adapter_version"
            )
        )

    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return True

    return (
        adapter_version
        != AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
    )


def _renderer_refresh_required(
    *,
    materialized_root,
    twin_key,
    revision,
):
    """Compatibilidad: cualquier runtime físico obsoleto."""

    return (
        _physical_renderer_refresh_required(
            materialized_root=materialized_root,
            twin_key=twin_key,
            revision=revision,
        )
        or
        _navigation_runtime_refresh_required(
            materialized_root=materialized_root,
            twin_key=twin_key,
            revision=revision,
        )
    )


def reconcile_auto_twin_discovery_materialization(
    *,
    managed_site_store,
    observation_store,
    capture_root,
    trigger_capture_id,
    twin_key=None,
    materialized_root=None,
    revision_store=None,
    plan_builder=None,
    materializer=None,
    human_navigation_candidate_store=None,
    previous_revision_id=None,
):
    """Materializa automáticamente conocimiento Discovery completo.

    Puede llamarse después de MHTML y después de viewport.
    El primer hook que vea el bundle completo gana.
    La segunda llamada será idempotente/no-op.
    """

    capture_root = Path(
        capture_root
    )

    trigger_capture_id = _text(
        trigger_capture_id
    )

    if not trigger_capture_id:
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
            ),
            reason="CAPTURE_ID_EMPTY",
        )

    twins = _all_observed_twins(
        observation_store
    )

    resolved_twin_key = (
        _text(
            twin_key
        )
        or _resolve_trigger_twin(
            twins=twins,
            trigger_capture_id=(
                trigger_capture_id
            ),
        )
    )

    if not resolved_twin_key:
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
            ),
            reason=(
                "TRIGGER_NOT_LINKED_TO_OBSERVED_TWIN"
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
        )

    managed = (
        managed_site_store.get(
            resolved_twin_key
        )
    )

    if managed is None:
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
            ),
            reason=(
                "MANAGED_TWIN_NOT_FOUND"
            ),
            twin_key=(
                resolved_twin_key
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
        )

    if (
        _value(
            managed,
            "enabled",
            False,
        )
        is not True
    ):
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
            ),
            reason="MANAGED_TWIN_DISABLED",
            twin_key=(
                resolved_twin_key
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
        )

    if (
        _value(
            managed,
            "auto_update",
            False,
        )
        is not True
    ):
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
            ),
            reason="AUTO_UPDATE_DISABLED",
            twin_key=(
                resolved_twin_key
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
        )

    if (
        _value(
            managed,
            "discover_unknown_states",
            False,
        )
        is not True
    ):
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
            ),
            reason=(
                "DISCOVER_UNKNOWN_STATES_DISABLED"
            ),
            twin_key=(
                resolved_twin_key
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
        )

    required_origin = _managed_origin(
        managed
    )

    if not required_origin:
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
            ),
            reason=(
                "MANAGED_TWIN_ORIGIN_AMBIGUOUS"
            ),
            twin_key=(
                resolved_twin_key
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
        )

    twin_snapshot = twins.get(
        resolved_twin_key
    )

    if not isinstance(
        twin_snapshot,
        dict,
    ):
        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
            ),
            reason="OBSERVATION_STATE_EMPTY",
            twin_key=(
                resolved_twin_key
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
        )

    observed_states = (
        twin_snapshot.get(
            "states",
            {}
        )
    )

    if not isinstance(
        observed_states,
        dict,
    ):
        observed_states = {}

    if materialized_root is None:
        materialized_root = (
            _materialized_root_for(
                capture_root
            )
        )

    materialized_root = Path(
        materialized_root
    )

    if revision_store is None:
        revision_store = (
            AutoTwinMaterializedRevisionStore(
                root=(
                    materialized_root
                )
            )
        )

    if plan_builder is None:
        plan_builder = (
            build_auto_twin_materialization_plan
        )

    if materializer is None:
        materializer = (
            materialize_auto_twin_plan
        )

    site_code = (
        _text(
            _value(
                managed,
                "site_code",
                None,
            )
        )
        or resolved_twin_key.upper()
    )

    with _lock_for(
        resolved_twin_key
    ):
        (
            latest,
            previous_revision_selection_mode,
        ) = _select_previous_revision(
            revision_store,
            resolved_twin_key,
            previous_revision_id=(
                previous_revision_id
            ),
        )

        if (
            latest is None
            and previous_revision_selection_mode
            == AUTO_TWIN_PREVIOUS_REVISION_SELECTION_PINNED
        ):
            # QCC_AUTO_TWIN_PREVIOUS_REVISION_PINNING_V1 (2D-20P)
            #
            # Fail closed. Never reinterpret a validation failure as
            # "no previous revision" -- that would silently fall back
            # to bootstrap/latest semantics instead of honoring the
            # explicit pin.
            return _result(
                status=(
                    AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                ),
                reason=(
                    "PREVIOUS_REVISION_PIN_NOT_FOUND:"
                    + _text(
                        previous_revision_id
                    )
                ),
                twin_key=(
                    resolved_twin_key
                ),
                trigger_capture_id=(
                    trigger_capture_id
                ),
                previous_revision_selection_mode=(
                    previous_revision_selection_mode
                ),
                base_revision_id=(
                    _text(
                        previous_revision_id
                    )
                    or None
                ),
            )

        renderer_refresh = (
            latest is not None
            and _renderer_refresh_required(
                materialized_root=(
                    materialized_root
                ),
                twin_key=(
                    resolved_twin_key
                ),
                revision=(
                    latest
                ),
            )
        )

        physical_renderer_refresh = (
            _physical_renderer_refresh_required(
                materialized_root=materialized_root,
                twin_key=resolved_twin_key,
                revision=latest,
            )
        )

        navigation_runtime_refresh = (
            _navigation_runtime_refresh_required(
                materialized_root=materialized_root,
                twin_key=resolved_twin_key,
                revision=latest,
            )
        )

        # QCC_AUTO_TWIN_CATALOG_REFRESH_CONTEXT
        latest_revision_dir = (
            _materialized_revision_dir(
                materialized_root=(
                    materialized_root
                ),
                twin_key=(
                    resolved_twin_key
                ),
                revision=(
                    latest
                ),
            )
        )

        catalog_refresh = None
        visual_enrichment = None

        # QCC_AUTO_TWIN_CAUSAL_NAVIGATION_REFRESH_V1
        #
        # CandidateStore is deliberately pre-Knowledge.
        # >= 1 trusted REAL causal observation may be replayed in the
        # controlled Twin, but grants no REAL execution authority.
        projected_navigation_candidates = ()

        if (
            human_navigation_candidate_store
            is not None
        ):
            candidate_snapshot = (
                human_navigation_candidate_store
                .snapshot(
                    site_code,
                    environment="REAL",
                )
            )

            projected_navigation_candidates = (
                project_twin_eligible_navigation_candidates(
                    candidate_snapshot
                )
            )

            # QCC_AUTO_TWIN_CONTEXTUAL_SUPERSESSION_TARGET_REBIND_V1
            # (2D-20R)
            #
            # A historical candidate may still target a content
            # fingerprint that a governed 1->N observation supersession
            # (2D-20K) has since replaced. Rebind only the qualifying
            # candidates' target to the corroborated replacement's
            # CURRENT fingerprint -- see
            # navigation_transition_materialization.py for the exact
            # fail-closed contract. This never changes which
            # candidates are selected as materializable below (that
            # gate is untouched); it only lets an already-selected
            # candidate's stale target resolve against the CURRENT
            # revision instead of being silently excluded.
            historical_twin_snapshot = (
                observation_store.snapshot(
                    resolved_twin_key
                ).get(
                    "twin"
                )
                or {}
            )

            historical_states = (
                historical_twin_snapshot.get(
                    "states"
                )
                or {}
            )

            projected_navigation_candidates = (
                rebind_contextual_supersession_navigation_targets(
                    projected_navigation_candidates,
                    twin_supersessions=(
                        twin_snapshot.get(
                            "supersessions"
                        )
                        or {}
                    ),
                    historical_states=(
                        historical_states
                    ),
                    current_states=(
                        observed_states
                    ),
                )
            )

        # QCC_AUTO_TWIN_NAVIGATION_CARRY_FORWARD_V1
        #
        # Applied unconditionally -- including when
        # human_navigation_candidate_store is None or its snapshot is
        # empty -- so an isolated/partial candidate-store view can
        # never by itself make previously materialized, still
        # physically valid navigation silently disappear.
        projected_navigation_candidates = (
            _carry_forward_navigation_candidates(
                latest_revision_dir,
                projected_navigation_candidates,
            )
        )

        (
            materializable_navigation_transitions,
            navigation_refresh,
        ) = (
            _navigation_refresh_for_latest_revision(
                revision_dir=(
                    latest_revision_dir
                ),
                candidates=(
                    projected_navigation_candidates
                ),
            )
        )

        state_sources = []
        identities = set()
        state_ids = set()

        # QCC_AUTO_TWIN_CARRY_FORWARD_SUPERSESSION_ELIGIBILITY_V1 (2D-20O)
        #
        # A new revision represents CURRENT Twin state only. Any
        # previous physical state whose observation state_key has been
        # governed-superseded (AutoTwinObservationStore.supersede(),
        # 2D-20K) must never be carried forward -- consulted here,
        # BEFORE any previous identity/state_id/fingerprint is
        # inserted into the carry-forward sets below. Historical
        # revisions remain the immutable, readable home for its
        # legacy runtime artifacts; this only governs what counts as
        # CURRENT in the revision about to be built.
        #
        # Absent/empty supersessions is a no-op: preserves prior
        # behavior exactly.
        twin_supersessions = (
            twin_snapshot.get(
                "supersessions"
            )
            or {}
        )

        superseded_state_ids = {
            _state_id(
                old_state_key
            )
            for old_state_key in (
                twin_supersessions
            )
            if _text(
                old_state_key
            )
        }

        # A one-to-many split (2D-20J/K) means two or more governed
        # replacement state_keys legitimately share the SAME coarse
        # (pathname, functional_state) identity. That coarse identity
        # is otherwise used below to dedupe "already covered" states;
        # a declared replacement must never be blocked by -- or block
        # -- its own sibling replacement through that dedupe. This
        # reads only the already-recorded supersession record; it
        # does not compute, weaken, or reinterpret state_variant_key.
        governed_replacement_state_keys = {
            _text(
                replacement_key
            )
            for record in (
                twin_supersessions.values()
                if isinstance(
                    twin_supersessions,
                    dict,
                )
                else ()
            )
            if isinstance(
                record,
                dict,
            )
            for replacement_key in (
                record.get(
                    "replacement_state_keys"
                )
                or ()
            )
            if _text(
                replacement_key
            )
        }

        # Physical Twin state uniqueness is fingerprint-first.
        #
        # The set is also used below to prevent an observed legacy
        # identity from re-introducing a second physical representative
        # after duplicate previous states have been collapsed.
        physical_fingerprints = set(
            _materialized_state_fingerprints(
                latest_revision_dir
            )
            if latest_revision_dir is not None
            else ()
        )

        if (
            superseded_state_ids
            and latest_revision_dir is not None
        ):
            superseded_registry_fingerprints = {
                _text(
                    entry.get(
                        "fingerprint"
                    )
                )
                for entry in (
                    (
                        _materialized_runtime_registry(
                            latest_revision_dir
                        )
                        or {}
                    ).get(
                        "states"
                    )
                    or ()
                )
                if (
                    isinstance(
                        entry,
                        dict,
                    )
                    and _text(
                        entry.get(
                            "state_id"
                        )
                    )
                    in superseded_state_ids
                )
            }

            physical_fingerprints -= (
                superseded_registry_fingerprints
            )

        # --------------------------------------------------
        # Conservar todos los estados de la revisión previa.
        # --------------------------------------------------

        if latest is not None:
            previous_states = latest.get(
                "state_manifest",
                [],
            )

            if not isinstance(
                previous_states,
                list,
            ):
                return _result(
                    status=(
                        AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                    ),
                    reason=(
                        "PREVIOUS_STATE_MANIFEST_INVALID"
                    ),
                    twin_key=(
                        resolved_twin_key
                    ),
                    trigger_capture_id=(
                        trigger_capture_id
                    ),
                )

            # QCC_AUTO_TWIN_FUNCTIONAL_FINGERPRINT_CANONICALIZATION_V1
            #
            # A previous revision may contain several historical
            # pathname/recognizer identities that V2 now proves to be
            # the same functional state. The new immutable revision
            # carries forward exactly one physical representative.
            if latest_revision_dir is not None:
                previous_states = list(
                    _canonical_previous_states_by_fingerprint(
                        previous_states,
                        latest_revision_dir,
                    )
                )

            # QCC_AUTO_TWIN_VISUAL_EVIDENCE_ENRICHMENT
            #
            # Precalculamos antes de recorrer los estados para que un
            # source histórico podado de OTRO estado no bloquee el
            # carry-forward antes de llegar a la identidad trigger.
            if (
                not renderer_refresh
                and latest_revision_dir is not None
            ):
                for candidate_previous in previous_states:
                    if not isinstance(
                        candidate_previous,
                        dict,
                    ):
                        continue

                    candidate = (
                        _visual_enrichment_for_previous_state(
                            renderer_refresh=(
                                renderer_refresh
                            ),
                            capture_root=(
                                capture_root
                            ),
                            revision_dir=(
                                latest_revision_dir
                            ),
                            previous_state_id=(
                                candidate_previous.get(
                                    "state_id"
                                )
                            ),
                            identity=(
                                _identity(
                                    candidate_previous.get(
                                        "pathname"
                                    ),
                                    candidate_previous.get(
                                        "functional_state"
                                    ),
                                )
                            ),
                            observed_states=(
                                observed_states
                            ),
                            trigger_capture_id=(
                                trigger_capture_id
                            ),
                        )
                    )

                    if candidate is None:
                        continue

                    if (
                        visual_enrichment is not None
                        and visual_enrichment[
                            "identity"
                        ]
                        != candidate[
                            "identity"
                        ]
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_VISUAL_ENRICHMENT_AMBIGUOUS"
                        )

                    visual_enrichment = candidate

            for previous in previous_states:
                if not isinstance(
                    previous,
                    dict,
                ):
                    continue

                previous_capture_id = _text(
                    previous.get(
                        "source_capture_id"
                    )
                )

                previous_state_id = _text(
                    previous.get(
                        "state_id"
                    )
                )

                previous_identity = _identity(
                    previous.get(
                        "pathname"
                    ),
                    previous.get(
                        "functional_state"
                    ),
                )

                if (
                    not previous_capture_id
                    or not previous_state_id
                ):
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                        ),
                        reason=(
                            "PREVIOUS_STATE_SOURCE_INVALID"
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                # QCC_AUTO_TWIN_CARRY_FORWARD_SUPERSESSION_ELIGIBILITY_V1
                #
                # Governed-superseded: excluded from the new revision
                # entirely -- never added to identities/state_ids, so
                # it can never block a replacement's identity or
                # fingerprint below. Its evidence remains fully
                # readable in the immutable previous revision.
                if (
                    previous_state_id
                    in superseded_state_ids
                ):
                    continue

                selected_capture_id = (
                    previous_capture_id
                )

                source_mode = (
                    AUTO_TWIN_STATE_SOURCE_REAL_CAPTURE
                )

                if (
                    visual_enrichment is not None
                    and previous_identity
                    == visual_enrichment[
                        "identity"
                    ]
                ):
                    selected_capture_id = (
                        visual_enrichment[
                            "capture_id"
                        ]
                    )

                    enrichment_missing = (
                        _missing_artifacts(
                            capture_root,
                            selected_capture_id,
                        )
                    )

                    if enrichment_missing:
                        return _result(
                            status=(
                                AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                            ),
                            reason=(
                                "VISUAL_ENRICHMENT_EVIDENCE_INCOMPLETE:"
                                + selected_capture_id
                                + ":"
                                + ",".join(
                                    enrichment_missing
                                )
                            ),
                            twin_key=(
                                resolved_twin_key
                            ),
                            trigger_capture_id=(
                                trigger_capture_id
                            ),
                        )

                    enrichment_profile = (
                        _capture_profile_key(
                            capture_root,
                            selected_capture_id,
                        )
                    )

                    if (
                        enrichment_profile
                        != AUTO_TWIN_DISCOVERY_PROFILE_KEY
                    ):
                        return _result(
                            status=(
                                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                            ),
                            reason=(
                                "VISUAL_ENRICHMENT_PROFILE_NOT_AUTHORIZED:"
                                + str(
                                    enrichment_profile
                                    or "UNKNOWN"
                                )
                            ),
                            twin_key=(
                                resolved_twin_key
                            ),
                            trigger_capture_id=(
                                trigger_capture_id
                            ),
                        )

                elif (
                    visual_enrichment is not None
                    or (
                        navigation_refresh
                        and not renderer_refresh
                        and catalog_refresh is None
                    )
                ):
                    # Copy-on-write:
                    #
                    # visual enrichment or navigation-only refresh must
                    # preserve all unaffected physical states exactly
                    # from the previous immutable revision.
                    source_mode = (
                        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                    )

                else:
                    previous_profile = (
                        _capture_profile_key(
                            capture_root,
                            previous_capture_id,
                        )
                    )

                    # QCC_AUTO_TWIN_LEGACY_PHYSICAL_CARRY_FORWARD_V1
                    #
                    # Una revisión materializada previa es autoridad
                    # física suficiente para conservar un estado legacy.
                    #
                    # No reconstruimos un estado ya validado desde una
                    # captura qcc_assisted únicamente para extender el
                    # Twin con nuevos estados Discovery.
                    #
                    # Renderer refresh queda expresamente fuera: en una
                    # migración de renderer sí necesitamos nueva evidencia.
                    materialized_state_dir = (
                        _materialized_state_dir_by_id(
                            revision_dir=(
                                latest_revision_dir
                            ),
                            state_id=(
                                previous_state_id
                            ),
                        )
                        if latest_revision_dir is not None
                        else None
                    )

                    if (
                        previous_profile
                        != AUTO_TWIN_DISCOVERY_PROFILE_KEY
                        and materialized_state_dir is not None
                        and not physical_renderer_refresh
                    ):
                        source_mode = (
                            AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                        )

                    else:
                        missing = _missing_artifacts(
                            capture_root,
                            previous_capture_id,
                        )

                        if missing:
                            return _result(
                                status=(
                                    AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                                ),
                                reason=(
                                    "PREVIOUS_SOURCE_EVIDENCE_INCOMPLETE:"
                                    + ",".join(
                                        missing
                                    )
                                ),
                                twin_key=(
                                    resolved_twin_key
                                ),
                                trigger_capture_id=(
                                    trigger_capture_id
                                ),
                            )

                        if (
                            previous_profile
                            != AUTO_TWIN_DISCOVERY_PROFILE_KEY
                        ):
                            return _result(
                                status=(
                                    AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                                ),
                                reason=(
                                    "LEGACY_BASELINE_PROFILE_MIGRATION_REQUIRED:"
                                    + str(
                                        previous_profile
                                        or "UNKNOWN"
                                    )
                                ),
                                twin_key=(
                                    resolved_twin_key
                                ),
                                trigger_capture_id=(
                                    trigger_capture_id
                                ),
                                revision_id=(
                                    latest.get(
                                        "materialized_revision_id"
                                    )
                                ),
                                state_count=(
                                    len(
                                        previous_states
                                    )
                                ),
                            )

                # QCC_AUTO_TWIN_RENDERER_REFRESH_SOURCE_REBINDING
                #
                # Durante una migración de renderer podemos necesitar
                # evidencia capturada después del baseline histórico.
                #
                # Sólo se permite para la identidad del trigger actual
                # y sólo cuando ese trigger es exactamente last_capture_id
                # del estado observado.
                refresh_capture_id = (
                    _renderer_refresh_capture_for_identity(
                        renderer_refresh=(
                            physical_renderer_refresh
                        ),
                        observed_states=(
                            observed_states
                        ),
                        identity=(
                            previous_identity
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )
                )

                if (
                    refresh_capture_id
                    and refresh_capture_id
                    != previous_capture_id
                ):
                    refresh_missing = (
                        _missing_artifacts(
                            capture_root,
                            refresh_capture_id,
                        )
                    )

                    if refresh_missing:
                        return _result(
                            status=(
                                AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                            ),
                            reason=(
                                "RENDERER_REFRESH_EVIDENCE_INCOMPLETE:"
                                + refresh_capture_id
                                + ":"
                                + ",".join(
                                    refresh_missing
                                )
                            ),
                            twin_key=(
                                resolved_twin_key
                            ),
                            trigger_capture_id=(
                                trigger_capture_id
                            ),
                            revision_id=(
                                latest.get(
                                    "materialized_revision_id"
                                )
                            ),
                        )

                    refresh_profile = (
                        _capture_profile_key(
                            capture_root,
                            refresh_capture_id,
                        )
                    )

                    if (
                        refresh_profile
                        != AUTO_TWIN_DISCOVERY_PROFILE_KEY
                    ):
                        return _result(
                            status=(
                                AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                            ),
                            reason=(
                                "RENDERER_REFRESH_PROFILE_NOT_AUTHORIZED:"
                                + str(
                                    refresh_profile
                                    or "UNKNOWN"
                                )
                            ),
                            twin_key=(
                                resolved_twin_key
                            ),
                            trigger_capture_id=(
                                trigger_capture_id
                            ),
                            revision_id=(
                                latest.get(
                                    "materialized_revision_id"
                                )
                            ),
                        )

                    selected_capture_id = (
                        refresh_capture_id
                    )

                identities.add(
                    previous_identity
                )

                state_ids.add(
                    previous_state_id
                )

                state_sources.append({
                    "state_id":
                        previous_state_id,

                    "capture_id":
                        selected_capture_id,

                    "pathname":
                        previous_identity[0],

                    "functional_state":
                        previous_identity[1],

                    "source_mode":
                        source_mode,
                })
                # QCC_AUTO_TWIN_CATALOG_PROVENANCE_CARRY_FORWARD
                previous_catalog = (
                    materialized_catalog_provenance(
                        revision_dir=(
                            latest_revision_dir
                        ),
                        pathname=(
                            previous_identity[0]
                        ),
                        functional_state=(
                            previous_identity[1]
                        ),
                    )
                )

                previous_catalog_capture = _text(
                    previous_catalog.get(
                        "catalog_source_capture_id"
                    )
                )

                if previous_catalog_capture:
                    state_sources[
                        -1
                    ][
                        "catalog_capture_id"
                    ] = (
                        previous_catalog_capture
                    )


        # --------------------------------------------------
        # Incorporar sólo identidades Discovery nuevas.
        # --------------------------------------------------

        ordered_states = sorted(
            (
                (
                    _text(
                        key
                    ),
                    state,
                )
                for (
                    key,
                    state,
                )
                in observed_states.items()
                if isinstance(
                    state,
                    dict,
                )
            ),
            key=lambda item: (
                _text(
                    item[1].get(
                        "first_seen_at"
                    )
                ),
                item[0],
            ),
        )

        # QCC_AUTO_TWIN_CATALOG_REFRESH_DECISION
        #
        # Renderer migration has precedence.
        if (
            latest is not None
            and not renderer_refresh
        ):
            (
                catalog_refresh_identity,
                catalog_refresh_discriminator,
            ) = (
                _catalog_refresh_identity_for_trigger(
                    observed_states=(
                        observed_states
                    ),
                    known_identities=(
                        identities
                    ),
                    trigger_capture_id=(
                        trigger_capture_id
                    ),
                )
            )

            if (
                catalog_refresh_identity
                is not None
            ):
                catalog_decision = (
                    _catalog_refresh_decision_for_trigger(
                        revision_dir=(
                            latest_revision_dir
                        ),
                        capture_root=(
                            capture_root
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                        identity=(
                            catalog_refresh_identity
                        ),
                        discriminator=(
                            catalog_refresh_discriminator
                        ),
                    )
                )

                if (
                    isinstance(
                        catalog_decision,
                        dict,
                    )
                    and catalog_decision.get(
                        "status"
                    )
                    == "REFRESH_REQUIRED"
                ):
                    catalog_refresh = {
                        "identity":
                            catalog_refresh_identity,

                        "catalog_capture_id":
                            trigger_capture_id,

                        "decision":
                            catalog_decision,
                    }

                    matching_sources = [
                        source
                        for source in state_sources
                        if _identity(
                            source.get(
                                "pathname"
                            ),
                            source.get(
                                "functional_state"
                            ),
                        )
                        == catalog_refresh_identity
                    ]

                    # QCC_AUTO_TWIN_CATALOG_REFRESH_VARIANT_AWARE_IDENTITY_V1
                    # (2D-20W)
                    #
                    # A governed 1->N family may legitimately carry
                    # more than one state_source sharing this
                    # (pathname, functional_state) identity. Narrow via
                    # the trigger's own already-governed discriminator
                    # (the same one threaded into
                    # decide_catalog_refresh() above) -- never a
                    # first-match/ranking heuristic. Still fails closed
                    # exactly as before when no unique source results.
                    if len(matching_sources) != 1:
                        discriminator_state_id = (
                            (
                                catalog_refresh_discriminator
                                or {}
                            ).get(
                                "state_id"
                            )
                        )

                        if discriminator_state_id:
                            matching_sources = [
                                source
                                for source in matching_sources
                                if source.get(
                                    "state_id"
                                )
                                == discriminator_state_id
                            ]

                    if len(matching_sources) != 1:
                        raise ValueError(
                            "QCC_AUTO_TWIN_CATALOG_REFRESH_STATE_SOURCE_AMBIGUOUS"
                        )

                    matching_sources[0][
                        "catalog_capture_id"
                    ] = (
                        trigger_capture_id
                    )

        added = 0

        # QCC_AUTO_TWIN_EXISTING_STATE_CAUSAL_REFRESH_V1
        #
        # Un estado ya materializado puede conservar identidad semántica
        # y state_id mientras su fingerprint funcional REAL evoluciona.
        #
        # Nunca adoptamos CHANGED de forma general.
        #
        # Sólo se permite sustituir su evidencia física cuando:
        #
        # - la identidad ya existe;
        # - el nuevo fingerprint no está físicamente materializado;
        # - dicho fingerprint participa como endpoint en evidencia
        #   causal TWIN_ELIGIBLE;
        # - _new_state_navigation_source() devuelve CAUSAL_LAST o
        #   CAUSAL_EQUIVALENT;
        # - la captura es twin_discovery;
        # - la captura está completa;
        # - fingerprint y functional_state de la captura coinciden
        #   exactamente con Observation Store.
        #
        # El state_id materializado se conserva. Esto crea una nueva
        # revisión inmutable, nunca modifica la revisión anterior.
        causal_existing_state_refreshes = 0

        # QCC_AUTO_TWIN_CAUSAL_REFRESH_NAVIGATION_REBIND_V1
        #
        # OLD fingerprint -> NEW fingerprint, only for refreshes that
        # pass the governed uniqueness/no-ambiguity checks below.
        causal_fingerprint_rebinds = {}

        # OLD fingerprints that were refreshed this pass but did NOT
        # pass those checks: any transition still referencing one of
        # these must be dropped, never guessed.
        causally_refreshed_fingerprints_unresolved = set()

        causal_refresh_fingerprint_by_state_id = (
            _materialized_state_fingerprint_index(
                latest_revision_dir
            )
        )

        causal_refresh_fingerprint_owner_counts = {}

        for fingerprint in (
            causal_refresh_fingerprint_by_state_id.values()
        ):
            causal_refresh_fingerprint_owner_counts[
                fingerprint
            ] = (
                causal_refresh_fingerprint_owner_counts.get(
                    fingerprint,
                    0,
                )
                + 1
            )

        for (
            state_key,
            state,
        ) in ordered_states:
            current_identity = _identity(
                state.get(
                    "pathname"
                ),
                state.get(
                    "functional_state"
                ),
            )

            current_fingerprint = (
                _observed_state_fingerprint(
                    state_key,
                    state,
                )
            )

            # Ya materializado:
            #
            # KNOWN continúa siendo no-op.
            #
            # CHANGED tampoco se adopta de forma general. Únicamente
            # puede sustituir la representación física existente cuando
            # el fingerprint actual forma parte de evidencia causal
            # TWIN_ELIGIBLE y la evidencia Discovery correspondiente
            # supera todas las guardas.
            #
            # A state_key already declared as a governed one-to-many
            # replacement (2D-20O) never enters this identity-collision
            # gate -- it always proceeds to the new-identity path below,
            # which mints its own distinct state_id.
            if (
                current_identity in identities
                and state_key
                not in governed_replacement_state_keys
            ):
                if (
                    current_fingerprint is None
                    or current_fingerprint
                    in physical_fingerprints
                ):
                    continue

                (
                    causal_capture_id,
                    causal_evidence_kind,
                ) = _new_state_navigation_source(
                    state,
                    projected_navigation_candidates,
                    capture_root=(
                        capture_root
                    ),
                )

                if causal_evidence_kind not in {
                    "CAUSAL_LAST",
                    "CAUSAL_EQUIVALENT",
                }:
                    continue

                if not causal_capture_id:
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                        ),
                        reason=(
                            "CAUSAL_EXISTING_STATE_CAPTURE_ID_MISSING"
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                causal_missing = _missing_artifacts(
                    capture_root,
                    causal_capture_id,
                )

                if causal_missing:
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                        ),
                        reason=(
                            "CAUSAL_EXISTING_STATE_EVIDENCE_INCOMPLETE:"
                            + causal_capture_id
                            + ":"
                            + ",".join(
                                causal_missing
                            )
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                causal_profile = (
                    _capture_profile_key(
                        capture_root,
                        causal_capture_id,
                    )
                )

                if (
                    causal_profile
                    != AUTO_TWIN_DISCOVERY_PROFILE_KEY
                ):
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                        ),
                        reason=(
                            "CAUSAL_EXISTING_STATE_PROFILE_NOT_AUTHORIZED:"
                            + str(
                                causal_profile
                                or "UNKNOWN"
                            )
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                causal_capture_fingerprint = (
                    _capture_functional_fingerprint(
                        capture_root,
                        causal_capture_id,
                    )
                )

                if (
                    causal_capture_fingerprint
                    != current_fingerprint
                ):
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                        ),
                        reason=(
                            "CAUSAL_EXISTING_STATE_FINGERPRINT_MISMATCH:"
                            + causal_capture_id
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                causal_capture_state = (
                    _capture_functional_state(
                        capture_root,
                        causal_capture_id,
                    )
                )

                if (
                    causal_capture_state
                    != current_identity[1]
                ):
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                        ),
                        reason=(
                            "CAUSAL_EXISTING_STATE_FUNCTIONAL_STATE_MISMATCH:"
                            + causal_capture_id
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                matching_source_indexes = [
                    index
                    for (
                        index,
                        source,
                    )
                    in enumerate(
                        state_sources
                    )
                    if (
                        isinstance(
                            source,
                            dict,
                        )
                        and _identity(
                            source.get(
                                "pathname"
                            ),
                            source.get(
                                "functional_state"
                            ),
                        )
                        == current_identity
                    )
                ]

                if (
                    len(
                        matching_source_indexes
                    )
                    != 1
                ):
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                        ),
                        reason=(
                            "CAUSAL_EXISTING_STATE_SOURCE_AMBIGUOUS:"
                            + str(
                                len(
                                    matching_source_indexes
                                )
                            )
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                source_index = (
                    matching_source_indexes[
                        0
                    ]
                )

                previous_source = (
                    state_sources[
                        source_index
                    ]
                )

                preserved_state_id = _text(
                    previous_source.get(
                        "state_id"
                    )
                )

                if not preserved_state_id:
                    return _result(
                        status=(
                            AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                        ),
                        reason=(
                            "CAUSAL_EXISTING_STATE_ID_MISSING"
                        ),
                        twin_key=(
                            resolved_twin_key
                        ),
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                refreshed_source = dict(
                    previous_source
                )

                refreshed_source[
                    "state_id"
                ] = preserved_state_id

                refreshed_source[
                    "capture_id"
                ] = causal_capture_id

                refreshed_source[
                    "pathname"
                ] = current_identity[0]

                refreshed_source[
                    "functional_state"
                ] = current_identity[1]

                # Al eliminar MATERIALIZED_CARRY_FORWARD obligamos
                # al plan/materializer a reconstruir exclusivamente
                # este estado desde evidencia REAL Discovery fresca.
                refreshed_source.pop(
                    "source_mode",
                    None,
                )

                state_sources[
                    source_index
                ] = refreshed_source

                physical_fingerprints.add(
                    current_fingerprint
                )

                # QCC_AUTO_TWIN_CAUSAL_REFRESH_NAVIGATION_REBIND_V1
                #
                # Governed rebind only when the OLD fingerprint being
                # displaced belonged to exactly one prior materialized
                # physical state (state_id + functional-state identity
                # compatibility are already guaranteed above: this
                # branch only runs for an identity already present in
                # `identities`, matched to exactly one previous_source).
                old_fingerprint = (
                    causal_refresh_fingerprint_by_state_id.get(
                        preserved_state_id
                    )
                )

                if (
                    old_fingerprint is not None
                    and causal_refresh_fingerprint_owner_counts.get(
                        old_fingerprint,
                        0,
                    )
                    == 1
                ):
                    causal_fingerprint_rebinds[
                        old_fingerprint
                    ] = current_fingerprint

                elif old_fingerprint is not None:
                    causally_refreshed_fingerprints_unresolved.add(
                        old_fingerprint
                    )

                causal_existing_state_refreshes += 1

                continue

            if (
                current_fingerprint is not None
                and current_fingerprint
                in physical_fingerprints
            ):
                continue

            baseline_capture_id = _text(
                state.get(
                    "baseline_capture_id"
                )
            )

            if not baseline_capture_id:
                return _result(
                    status=(
                        AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                    ),
                    reason=(
                        "BASELINE_CAPTURE_ID_MISSING"
                    ),
                    twin_key=(
                        resolved_twin_key
                    ),
                    trigger_capture_id=(
                        trigger_capture_id
                    ),
                )

            (
                selected_capture_id,
                selected_evidence_kind,
            ) = _new_state_navigation_source(
                state,
                projected_navigation_candidates,
                capture_root=(
                    capture_root
                ),
                expected_site_code=(
                    site_code
                ),
            )


            if not selected_capture_id:
                return _result(
                    status=(
                        AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                    ),
                    reason=(
                        selected_evidence_kind
                        + "_CAPTURE_ID_MISSING"
                    ),
                    twin_key=(
                        resolved_twin_key
                    ),
                    trigger_capture_id=(
                        trigger_capture_id
                    ),
                )

            missing = _missing_artifacts(
                capture_root,
                selected_capture_id,
            )

            if missing:
                return _result(
                    status=(
                        AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                    ),
                    reason=(
                        selected_evidence_kind
                        + "_EVIDENCE_INCOMPLETE:"
                        + selected_capture_id
                        + ":"
                        + ",".join(
                            missing
                        )
                    ),
                    twin_key=(
                        resolved_twin_key
                    ),
                    trigger_capture_id=(
                        trigger_capture_id
                    ),
                )

            profile_key = (
                _capture_profile_key(
                    capture_root,
                    selected_capture_id,
                )
            )

            if (
                profile_key
                != AUTO_TWIN_DISCOVERY_PROFILE_KEY
            ):
                return _result(
                    status=(
                        AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
                    ),
                    reason=(
                        selected_evidence_kind
                        + "_PROFILE_NOT_AUTHORIZED:"
                        + str(
                            profile_key
                            or "UNKNOWN"
                        )
                    ),
                    twin_key=(
                        resolved_twin_key
                    ),
                    trigger_capture_id=(
                        trigger_capture_id
                    ),
                )

            generated_state_id = (
                _state_id(
                    state_key
                )
            )

            if generated_state_id in state_ids:
                raise ValueError(
                    "QCC_AUTO_TWIN_DISCOVERY_STATE_ID_COLLISION"
                )

            state_ids.add(
                generated_state_id
            )

            identities.add(
                current_identity
            )

            state_sources.append({
                "state_id":
                    generated_state_id,

                "capture_id":
                    selected_capture_id,

                "pathname":
                    current_identity[0],

                "functional_state":
                    current_identity[1],
            })

            if current_fingerprint is not None:
                physical_fingerprints.add(
                    current_fingerprint
                )

            added += 1

        # QCC_AUTO_TWIN_CAUSAL_REFRESH_NAVIGATION_REBIND_V1
        #
        # Applied once, after the causal-refresh loop has finished
        # populating causal_fingerprint_rebinds/
        # causally_refreshed_fingerprints_unresolved, and before the
        # plan is built. This never changes which transitions were
        # selected as materializable by _navigation_refresh_for_latest_
        # revision() above (TWO_PASS_REQUIRED gating for genuinely new
        # endpoints is untouched); it only rebinds or drops endpoints
        # of already-selected transitions affected by this pass's own
        # existing-state causal refresh.
        navigation_transitions_for_plan = (
            _rebind_causal_refresh_navigation_endpoints(
                materializable_navigation_transitions,
                causal_fingerprint_rebinds,
                causally_refreshed_fingerprints_unresolved,
            )
        )

        # --------------------------------------------------
        # No existe conocimiento nuevo.
        # --------------------------------------------------

        if (
            latest is not None
            and added == 0
            and causal_existing_state_refreshes == 0
            and not renderer_refresh
            and visual_enrichment is None
            and catalog_refresh is None
            and not navigation_refresh
        ):
            return _result(
                status=(
                    AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
                ),
                reason=(
                    "NO_NEW_DISCOVERY_STATE"
                ),
                twin_key=(
                    resolved_twin_key
                ),
                trigger_capture_id=(
                    trigger_capture_id
                ),
                revision_id=(
                    latest.get(
                        "materialized_revision_id"
                    )
                ),
                materialization_mode=(
                    latest.get(
                        "materialization_mode"
                    )
                ),
                state_count=(
                    len(
                        latest.get(
                            "state_manifest",
                            [],
                        )
                    )
                ),
                added_state_count=0,
                previous_revision_selection_mode=(
                    previous_revision_selection_mode
                ),
                base_revision_id=(
                    latest.get(
                        "materialized_revision_id"
                    )
                ),
            )

        if not state_sources:
            return _result(
                status=(
                    AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
                ),
                reason=(
                    "NO_COMPLETE_DISCOVERY_STATE"
                ),
                twin_key=(
                    resolved_twin_key
                ),
                trigger_capture_id=(
                    trigger_capture_id
                ),
            )

        if (
            (
                navigation_refresh
                or causal_existing_state_refreshes > 0
            )
            and latest is not None
            and added == 0
        ):
            mode = (
                latest.get(
                    "materialization_mode"
                )
                or (
                    AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION
                )
            )

        elif (
            visual_enrichment is not None
            and latest is not None
            and added == 0
        ):
            mode = (
                latest.get(
                    "materialization_mode"
                )
                or (
                    AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION
                )
            )

        elif (
            renderer_refresh
            and latest is not None
            and added == 0
        ):
            mode = (
                latest.get(
                    "materialization_mode"
                )
                or (
                    AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION
                )
            )

        elif (
            catalog_refresh is not None
            and latest is not None
            and added == 0
        ):
            mode = (
                AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH
            )

        else:
            mode = (
                AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
                if latest is None
                else (
                    AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION
                )
            )

        uses_materialized_carry_forward = any(
            source.get(
                "source_mode"
            )
            == AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
            for source in state_sources
        )

        plan = plan_builder(
            twin_key=(
                resolved_twin_key
            ),
            materialization_mode=(
                mode
            ),
            state_sources=(
                state_sources
            ),
            required_origin=(
                required_origin
            ),
            required_profile_key=(
                AUTO_TWIN_DISCOVERY_PROFILE_KEY
            ),
            base_materialized_revision_id=(
                latest.get(
                    "materialized_revision_id"
                )
                if (
                    latest is not None
                    and uses_materialized_carry_forward
                )
                else None
            ),
            navigation_transitions=(
                navigation_transitions_for_plan
            ),
            root=(
                capture_root
            ),
        )

        built = materializer(
            plan=(
                plan
            ),
            source_root=(
                capture_root
            ),
            materialized_root=(
                materialized_root
            ),
            # Metadata runtime legacy:
            # NO representa procedure identity.
            procedure_code=(
                site_code
            ),
            flow_variant=(
                "SITE_LEVEL"
            ),
        )

        revision = (
            built.get(
                "revision"
            )
            if isinstance(
                built,
                dict,
            )
            else None
        )

        if not isinstance(
            revision,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_AUTO_MATERIALIZATION_RESULT_INVALID"
            )

        return _result(
            status=(
                AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
            ),
            reason=(
                (
                    "VISUAL_EVIDENCE_ENRICHED"
                    if visual_enrichment is not None
                    else (
                        "CATALOG_KNOWLEDGE_MATERIALIZED"
                        if (
                            mode
                            == AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH
                        )
                        else (
                            "DISCOVERY_KNOWLEDGE_MATERIALIZED"
                        )
                    )
                )
            ),
            twin_key=(
                resolved_twin_key
            ),
            trigger_capture_id=(
                trigger_capture_id
            ),
            revision_id=(
                revision.get(
                    "materialized_revision_id"
                )
            ),
            materialization_mode=(
                revision.get(
                    "materialization_mode"
                )
            ),
            state_count=(
                len(
                    revision.get(
                        "state_manifest",
                        [],
                    )
                )
            ),
            added_state_count=(
                added
            ),
            plan_id=(
                plan.get(
                    "plan_id"
                )
            ),
            previous_revision_selection_mode=(
                previous_revision_selection_mode
            ),
            base_revision_id=(
                latest.get(
                    "materialized_revision_id"
                )
                if latest is not None
                else None
            ),
        )
