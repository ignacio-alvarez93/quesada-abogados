"""Conocimiento persistente de navegación observado por QCC.

Persiste exclusivamente identidad funcional PII-safe:

- fingerprints;
- identidad segura de acción;
- evidencia/confianza;
- aliases semánticos de estado.

No persiste DOM, HTML, valores, texto ni payloads.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import json
from pathlib import Path
import re
import threading

from backend.automation.site_architecture.navigation_graph import (
    build_navigation_graph,
)
from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_CONFIDENCE_LOW,
    STATE_TRANSITION_CONFIDENCE_MEDIUM,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
    STATE_TRANSITION_UNCHANGED,
)


NAVIGATION_KNOWLEDGE_SCHEMA_VERSION = 2

NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT = (
    "GENERIC"
)
NAVIGATION_KNOWLEDGE_TYPE = (
    "QCC_NAVIGATION_KNOWLEDGE"
)

DEFAULT_NAVIGATION_KNOWLEDGE_ROOT = Path(
    "data/qcc/navigation_knowledge"
)

_SITE_CODE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_.-]{0,127}$"
)

_ENVIRONMENT_CODE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_.-]{0,63}$"
)

_STATE_CODE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_.:/-]{0,127}$"
)

_CONFIDENCE_VALUES = {
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_CONFIDENCE_MEDIUM,
    STATE_TRANSITION_CONFIDENCE_LOW,
}


def _site_code(
    value,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    if not _SITE_CODE_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_SITE_CODE_INVALID"
        )

    return normalized


def _environment_code(
    value,
):
    normalized = str(
        getattr(
            value,
            "value",
            value,
        )
        or ""
    ).strip().upper()

    if not _ENVIRONMENT_CODE_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_ENVIRONMENT_INVALID"
        )

    return normalized


def _state_code(
    value,
):
    if value is None:
        return None

    normalized = str(
        getattr(
            value,
            "value",
            value,
        )
        or ""
    ).strip().upper()

    if not normalized:
        return None

    if not _STATE_CODE_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_STATE_CODE_INVALID"
        )

    return normalized


def _text(
    value,
):
    normalized = str(
        value
        or ""
    ).strip()

    return normalized or None


def _fingerprint(
    value,
):
    normalized = _text(
        value
    )

    if (
        normalized is None
        or len(normalized) != 64
        or any(
            character
            not in "0123456789abcdefABCDEF"
            for character
            in normalized
        )
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_FINGERPRINT_INVALID"
        )

    return normalized.lower()


def _safe_action(
    action,
):
    if action is None:
        return None

    if not isinstance(
        action,
        dict,
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_ACTION_INVALID"
        )

    return {
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
            str(
                action.get(
                    "frame_path"
                )
                or "main"
            ),
    }


def _safe_transition(
    transition,
):
    if not isinstance(
        transition,
        dict,
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_TRANSITION_INVALID"
        )

    if (
        transition.get(
            "schema_version"
        )
        != STATE_TRANSITION_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_TRANSITION_SCHEMA_INVALID"
        )

    if (
        transition.get(
            "transition_type"
        )
        != STATE_TRANSITION_TYPE
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_TRANSITION_TYPE_INVALID"
        )

    changed = transition.get(
        "changed"
    )

    if not isinstance(
        changed,
        bool,
    ):
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_CHANGED_INVALID"
        )

    status = _text(
        transition.get(
            "status"
        )
    )

    expected_status = (
        STATE_TRANSITION_CHANGED
        if changed
        else STATE_TRANSITION_UNCHANGED
    )

    if status != expected_status:
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_STATUS_INVALID"
        )

    confidence = _text(
        transition.get(
            "confidence"
        )
    )

    if confidence not in _CONFIDENCE_VALUES:
        raise ValueError(
            "QCC_NAVIGATION_KNOWLEDGE_CONFIDENCE_INVALID"
        )

    return {
        "schema_version":
            STATE_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            STATE_TRANSITION_TYPE,

        "changed":
            changed,

        "status":
            status,

        "before_fingerprint":
            _fingerprint(
                transition.get(
                    "before_fingerprint"
                )
            ),

        "after_fingerprint":
            _fingerprint(
                transition.get(
                    "after_fingerprint"
                )
            ),

        "action":
            _safe_action(
                transition.get(
                    "action"
                )
            ),

        "confidence":
            confidence,

        "contract_changed":
            bool(
                transition.get(
                    "contract_changed"
                )
            ),

        "inconclusive":
            bool(
                transition.get(
                    "inconclusive"
                )
            ),
    }


def _utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


class NavigationKnowledgeStore:
    """Store JSON aislado por site_code + environment."""

    def __init__(
        self,
        *,
        root=DEFAULT_NAVIGATION_KNOWLEDGE_ROOT,
    ):
        self._root = Path(
            root
        )

        self._lock = (
            threading.RLock()
        )

    def _site_dir(
        self,
        site_code,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        return (
            self._root
            / _site_code(
                site_code
            )
            / _environment_code(
                environment
            )
        )

    def _path(
        self,
        site_code,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        return (
            self._site_dir(
                site_code,
                environment,
            )
            / "navigation_knowledge.json"
        )

    def _empty(
        self,
        site_code,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        normalized = _site_code(
            site_code
        )

        normalized_environment = (
            _environment_code(
                environment
            )
        )

        return {
            "schema_version":
                NAVIGATION_KNOWLEDGE_SCHEMA_VERSION,

            "knowledge_type":
                NAVIGATION_KNOWLEDGE_TYPE,

            "site_code":
                normalized,

            "environment":
                normalized_environment,

            "revision":
                0,

            "updated_at":
                None,

            "transition_observation_count":
                0,

            "transition_observation_ids":
                [],

            "transitions":
                [],

            # fingerprint -> state_code -> count
            "state_aliases":
                {},
        }

    def _load(
        self,
        site_code,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        normalized = _site_code(
            site_code
        )

        normalized_environment = (
            _environment_code(
                environment
            )
        )

        path = self._path(
            normalized,
            normalized_environment,
        )

        if not path.exists():
            return self._empty(
                normalized,
                normalized_environment,
            )

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_PAYLOAD_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != NAVIGATION_KNOWLEDGE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "knowledge_type"
            )
            != NAVIGATION_KNOWLEDGE_TYPE
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_TYPE_INVALID"
            )

        if (
            payload.get(
                "site_code"
            )
            != normalized
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_SITE_MISMATCH"
            )

        if (
            payload.get(
                "environment"
            )
            != normalized_environment
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_ENVIRONMENT_MISMATCH"
            )

        if not isinstance(
            payload.get(
                "transitions"
            ),
            list,
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_TRANSITIONS_INVALID"
            )

        observation_ids = payload.get(
            "transition_observation_ids"
        )

        if observation_ids is None:
            # Backward compatibility with existing
            # Navigation Knowledge payloads.
            observation_ids = []

            payload[
                "transition_observation_ids"
            ] = observation_ids

        if not isinstance(
            observation_ids,
            list,
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_OBSERVATION_IDS_INVALID"
            )

        if any(
            not str(
                value
                or ""
            ).strip()
            for value in observation_ids
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_OBSERVATION_ID_INVALID"
            )


        if not isinstance(
            payload.get(
                "state_aliases"
            ),
            dict,
        ):
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_ALIASES_INVALID"
            )

        return payload

    def _write(
        self,
        site_code,
        payload,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        site_dir = self._site_dir(
            site_code,
            environment,
        )

        site_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = self._path(
            site_code,
            environment,
        )

        temporary = (
            path.with_suffix(
                ".json.tmp"
            )
        )

        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(
            path
        )

    @staticmethod
    def _record_alias(
        payload,
        *,
        fingerprint,
        state,
    ):
        state = _state_code(
            state
        )

        if state is None:
            return

        aliases = payload[
            "state_aliases"
        ]

        fingerprint_aliases = (
            aliases.setdefault(
                fingerprint,
                {},
            )
        )

        fingerprint_aliases[
            state
        ] = (
            int(
                fingerprint_aliases.get(
                    state,
                    0,
                )
                or 0
            )
            + 1
        )

    def record_transition(
        self,
        site_code,
        transition,
        *,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
        before_state=None,
        after_state=None,
    ):
        """Añade una observación PII-safe al conocimiento."""

        normalized_site = (
            _site_code(
                site_code
            )
        )

        normalized_environment = (
            _environment_code(
                environment
            )
        )

        safe_transition = (
            _safe_transition(
                transition
            )
        )

        with self._lock:
            payload = self._load(
                normalized_site,
                normalized_environment,
            )

            payload[
                "transitions"
            ].append(
                safe_transition
            )

            payload[
                "transition_observation_count"
            ] = (
                len(
                    payload[
                        "transitions"
                    ]
                )
            )

            self._record_alias(
                payload,
                fingerprint=(
                    safe_transition[
                        "before_fingerprint"
                    ]
                ),
                state=before_state,
            )

            self._record_alias(
                payload,
                fingerprint=(
                    safe_transition[
                        "after_fingerprint"
                    ]
                ),
                state=after_state,
            )

            payload[
                "revision"
            ] = (
                int(
                    payload.get(
                        "revision",
                        0,
                    )
                    or 0
                )
                + 1
            )

            payload[
                "updated_at"
            ] = _utc_now()

            self._write(
                normalized_site,
                payload,
                normalized_environment,
            )

            return int(
                payload[
                    "revision"
                ]
            )

    def record_transition_once(
        self,
        site_code,
        transition,
        *,
        observation_id,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
        before_state=None,
        after_state=None,
    ):
        """Registra una observación como máximo una vez.

        Diseñado para promociones/reintentos donde una caída entre
        escrituras no debe inflar artificialmente la evidencia.

        observation_id es técnico y PII-safe.
        """

        normalized_observation_id = (
            _text(
                observation_id
            )
        )

        if normalized_observation_id is None:
            raise ValueError(
                "QCC_NAVIGATION_KNOWLEDGE_OBSERVATION_ID_REQUIRED"
            )

        normalized_site = (
            _site_code(
                site_code
            )
        )

        normalized_environment = (
            _environment_code(
                environment
            )
        )

        safe_transition = (
            _safe_transition(
                transition
            )
        )

        with self._lock:
            payload = self._load(
                normalized_site,
                normalized_environment,
            )

            observation_ids = payload.setdefault(
                "transition_observation_ids",
                [],
            )

            if (
                normalized_observation_id
                in observation_ids
            ):
                return {
                    "recorded":
                        False,

                    "duplicate_observation":
                        True,

                    "revision":
                        int(
                            payload.get(
                                "revision",
                                0,
                            )
                            or 0
                        ),
                }

            payload[
                "transitions"
            ].append(
                safe_transition
            )

            observation_ids.append(
                normalized_observation_id
            )

            payload[
                "transition_observation_count"
            ] = len(
                payload[
                    "transitions"
                ]
            )

            self._record_alias(
                payload,
                fingerprint=(
                    safe_transition[
                        "before_fingerprint"
                    ]
                ),
                state=before_state,
            )

            self._record_alias(
                payload,
                fingerprint=(
                    safe_transition[
                        "after_fingerprint"
                    ]
                ),
                state=after_state,
            )

            payload[
                "revision"
            ] = (
                int(
                    payload.get(
                        "revision",
                        0,
                    )
                    or 0
                )
                + 1
            )

            payload[
                "updated_at"
            ] = _utc_now()

            self._write(
                normalized_site,
                payload,
                normalized_environment,
            )

            return {
                "recorded":
                    True,

                "duplicate_observation":
                    False,

                "revision":
                    int(
                        payload[
                            "revision"
                        ]
                    ),
            }


    def snapshot(
        self,
        site_code,
        *,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        with self._lock:
            payload = self._load(
                site_code,
                environment,
            )

            # Copia mediante roundtrip JSON:
            # payload contiene solo tipos JSON-safe.
            public_payload = json.loads(
                json.dumps(
                    payload
                )
            )

            # Metadata técnica de exactly-once.
            #
            # Debe persistir en disco para soportar retries,
            # pero no forma parte del contrato público de
            # Navigation Knowledge.
            public_payload.pop(
                "transition_observation_ids",
                None,
            )

            return public_payload

    def build_graph(
        self,
        site_code,
        *,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        """Reconstruye el grafo del environment solicitado."""

        snapshot = self.snapshot(
            site_code,
            environment=environment,
        )

        return build_navigation_graph(
            snapshot[
                "transitions"
            ]
        )

    def resolve_state_fingerprints(
        self,
        site_code,
        state_code,
        *,
        environment=(
            NAVIGATION_KNOWLEDGE_GENERIC_ENVIRONMENT
        ),
    ):
        """Devuelve fingerprints observados para un estado semántico.

        Orden:
        - más observaciones primero;
        - desempate determinista por fingerprint.
        """

        normalized_state = (
            _state_code(
                state_code
            )
        )

        if normalized_state is None:
            return ()

        snapshot = self.snapshot(
            site_code,
            environment=environment,
        )

        candidates = []

        for (
            fingerprint,
            aliases,
        ) in snapshot[
            "state_aliases"
        ].items():
            count = int(
                aliases.get(
                    normalized_state,
                    0,
                )
                or 0
            )

            if count <= 0:
                continue

            candidates.append({
                "fingerprint":
                    fingerprint,

                "observation_count":
                    count,
            })

        return tuple(
            sorted(
                candidates,
                key=lambda item: (
                    -item[
                        "observation_count"
                    ],
                    item[
                        "fingerprint"
                    ],
                ),
            )
        )
