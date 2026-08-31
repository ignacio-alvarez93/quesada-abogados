"""Candidate evidence for trusted human navigation.

This store sits deliberately BEFORE NavigationKnowledgeStore.

One physical observation must never become navigation knowledge by
itself. Repeated, distinct trusted human causal observations first
accumulate here.

Learning a route never grants permission to execute its action.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path


HUMAN_NAVIGATION_CANDIDATE_SCHEMA_VERSION = 1

HUMAN_NAVIGATION_CANDIDATE_TYPE = (
    "QCC_HUMAN_NAVIGATION_CANDIDATES"
)

HUMAN_NAVIGATION_CANDIDATE_STATUS_CANDIDATE = (
    "CANDIDATE"
)

HUMAN_NAVIGATION_CANDIDATE_STATUS_CORROBORATED = (
    "CORROBORATED"
)

HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED = (
    "CONFIRMED"
)

HUMAN_NAVIGATION_CANDIDATE_CONFIRMATION_COUNT = 3

HUMAN_NAVIGATION_EVIDENCE_SOURCE = (
    "TRUSTED_DOM_HUMAN_CAUSAL_JOIN"
)

_FINGERPRINT_RE = re.compile(
    r"^[0-9a-fA-F]{64}$"
)

_PATH_CODE_RE = re.compile(
    r"^[A-Za-z0-9_.-]+$"
)


def _utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def _value(
    source,
    name,
):
    if isinstance(
        source,
        dict,
    ):
        return source.get(
            name
        )

    return getattr(
        source,
        name,
        None,
    )


def _required_text(
    value,
    error,
):
    text = str(
        value
        or ""
    ).strip()

    if not text:
        raise ValueError(
            error
        )

    return text


def _code(
    value,
    error,
):
    text = _required_text(
        value,
        error,
    ).upper()

    if (
        text in {".", ".."}
        or not _PATH_CODE_RE.fullmatch(
            text
        )
    ):
        raise ValueError(
            error
        )

    return text


def _fingerprint(
    value,
    error,
):
    text = _required_text(
        value,
        error,
    ).lower()

    if not _FINGERPRINT_RE.fullmatch(
        text
    ):
        raise ValueError(
            error
        )

    return text


def _status_for_count(
    observation_count,
):
    count = int(
        observation_count
    )

    if (
        count
        >= HUMAN_NAVIGATION_CANDIDATE_CONFIRMATION_COUNT
    ):
        return (
            HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
        )

    if count >= 2:
        return (
            HUMAN_NAVIGATION_CANDIDATE_STATUS_CORROBORATED
        )

    return (
        HUMAN_NAVIGATION_CANDIDATE_STATUS_CANDIDATE
    )


def _safe_identity(
    transition,
):
    if (
        _value(
            transition,
            "changed",
        )
        is not True
    ):
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_CANDIDATE_REQUIRES_CHANGED_TRANSITION"
        )

    return {
        "site_code":
            _code(
                _value(
                    transition,
                    "site_code",
                ),
                "QCC_HUMAN_NAVIGATION_CANDIDATE_SITE_REQUIRED",
            ),

        "environment":
            _code(
                _value(
                    transition,
                    "environment",
                ),
                "QCC_HUMAN_NAVIGATION_CANDIDATE_ENVIRONMENT_REQUIRED",
            ),

        "before_state":
            _required_text(
                _value(
                    transition,
                    "before_state",
                ),
                "QCC_HUMAN_NAVIGATION_CANDIDATE_BEFORE_STATE_REQUIRED",
            ),

        "before_fingerprint":
            _fingerprint(
                _value(
                    transition,
                    "before_fingerprint",
                ),
                "QCC_HUMAN_NAVIGATION_CANDIDATE_BEFORE_FINGERPRINT_INVALID",
            ),

        "action": {
            "kind":
                _required_text(
                    _value(
                        transition,
                        "kind",
                    ),
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_KIND_REQUIRED",
                ),

            "policy":
                _required_text(
                    _value(
                        transition,
                        "policy",
                    ),
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_POLICY_REQUIRED",
                ),

            "selector":
                _required_text(
                    _value(
                        transition,
                        "selector",
                    ),
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_SELECTOR_REQUIRED",
                ),

            "frame_path":
                _required_text(
                    _value(
                        transition,
                        "frame_path",
                    ),
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_FRAME_PATH_REQUIRED",
                ),
        },

        "after_state":
            _required_text(
                _value(
                    transition,
                    "after_state",
                ),
                "QCC_HUMAN_NAVIGATION_CANDIDATE_AFTER_STATE_REQUIRED",
            ),

        "after_fingerprint":
            _fingerprint(
                _value(
                    transition,
                    "after_fingerprint",
                ),
                "QCC_HUMAN_NAVIGATION_CANDIDATE_AFTER_FINGERPRINT_INVALID",
            ),
    }


def _candidate_id(
    identity,
):
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


class HumanNavigationCandidateStore:
    """Persistent pre-knowledge store.

    Persistence is isolated by:
        site_code / environment

    The store never imports or writes NavigationKnowledgeStore.
    """

    def __init__(
        self,
        *,
        root,
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
        environment,
    ):
        return (
            self._root
            / _code(
                site_code,
                "QCC_HUMAN_NAVIGATION_CANDIDATE_SITE_INVALID",
            )
            / _code(
                environment,
                "QCC_HUMAN_NAVIGATION_CANDIDATE_ENVIRONMENT_INVALID",
            )
        )

    def _path(
        self,
        site_code,
        environment,
    ):
        return (
            self._site_dir(
                site_code,
                environment,
            )
            / "human_navigation_candidates.json"
        )

    def _empty(
        self,
        site_code,
        environment,
    ):
        return {
            "schema_version":
                HUMAN_NAVIGATION_CANDIDATE_SCHEMA_VERSION,

            "candidate_type":
                HUMAN_NAVIGATION_CANDIDATE_TYPE,

            "site_code":
                _code(
                    site_code,
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_SITE_INVALID",
                ),

            "environment":
                _code(
                    environment,
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_ENVIRONMENT_INVALID",
                ),

            "revision":
                0,

            "updated_at":
                None,

            "candidate_count":
                0,

            "candidates":
                [],
        }

    def _load(
        self,
        site_code,
        environment,
    ):
        normalized_site = _code(
            site_code,
            "QCC_HUMAN_NAVIGATION_CANDIDATE_SITE_INVALID",
        )

        normalized_environment = _code(
            environment,
            "QCC_HUMAN_NAVIGATION_CANDIDATE_ENVIRONMENT_INVALID",
        )

        path = self._path(
            normalized_site,
            normalized_environment,
        )

        if not path.exists():
            return self._empty(
                normalized_site,
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
                "QCC_HUMAN_NAVIGATION_CANDIDATE_PAYLOAD_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != HUMAN_NAVIGATION_CANDIDATE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_HUMAN_NAVIGATION_CANDIDATE_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "candidate_type"
            )
            != HUMAN_NAVIGATION_CANDIDATE_TYPE
        ):
            raise ValueError(
                "QCC_HUMAN_NAVIGATION_CANDIDATE_TYPE_INVALID"
            )

        if (
            payload.get(
                "site_code"
            )
            != normalized_site
        ):
            raise ValueError(
                "QCC_HUMAN_NAVIGATION_CANDIDATE_SITE_MISMATCH"
            )

        if (
            payload.get(
                "environment"
            )
            != normalized_environment
        ):
            raise ValueError(
                "QCC_HUMAN_NAVIGATION_CANDIDATE_ENVIRONMENT_MISMATCH"
            )

        if not isinstance(
            payload.get(
                "candidates"
            ),
            list,
        ):
            raise ValueError(
                "QCC_HUMAN_NAVIGATION_CANDIDATES_INVALID"
            )

        return payload

    def _write(
        self,
        site_code,
        environment,
        payload,
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

        temporary = path.with_suffix(
            ".json.tmp"
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

    def record_observed_transition(
        self,
        transition,
    ):
        """Record one distinct trusted causal observation.

        event_id provides delivery idempotency.

        Replaying the same event cannot increase confidence.
        """

        identity = _safe_identity(
            transition
        )

        event_id = _required_text(
            _value(
                transition,
                "event_id",
            ),
            "QCC_HUMAN_NAVIGATION_CANDIDATE_EVENT_ID_REQUIRED",
        )

        observed_at = _required_text(
            _value(
                transition,
                "after_observed_at",
            ),
            "QCC_HUMAN_NAVIGATION_CANDIDATE_OBSERVED_AT_REQUIRED",
        )

        candidate_id = _candidate_id(
            identity
        )

        site_code = identity[
            "site_code"
        ]

        environment = identity[
            "environment"
        ]

        with self._lock:
            payload = self._load(
                site_code,
                environment,
            )

            candidate = next(
                (
                    item
                    for item
                    in payload[
                        "candidates"
                    ]
                    if item.get(
                        "candidate_id"
                    )
                    == candidate_id
                ),
                None,
            )

            if candidate is None:
                candidate = {
                    "candidate_id":
                        candidate_id,

                    "evidence_source":
                        HUMAN_NAVIGATION_EVIDENCE_SOURCE,

                    **identity,

                    "observation_count":
                        0,

                    "event_ids":
                        [],

                    "first_observed_at":
                        observed_at,

                    "last_observed_at":
                        observed_at,

                    "status":
                        HUMAN_NAVIGATION_CANDIDATE_STATUS_CANDIDATE,

                    "promoted_at":
                        None,
                }

                payload[
                    "candidates"
                ].append(
                    candidate
                )

            if (
                event_id
                in candidate[
                    "event_ids"
                ]
            ):
                return {
                    "recorded":
                        False,

                    "duplicate_event":
                        True,

                    "became_confirmed":
                        False,

                    "candidate":
                        json.loads(
                            json.dumps(
                                candidate
                            )
                        ),
                }

            previous_count = int(
                candidate[
                    "observation_count"
                ]
            )

            candidate[
                "event_ids"
            ].append(
                event_id
            )

            candidate[
                "observation_count"
            ] = (
                previous_count
                + 1
            )

            candidate[
                "last_observed_at"
            ] = observed_at

            candidate[
                "status"
            ] = _status_for_count(
                candidate[
                    "observation_count"
                ]
            )

            payload[
                "candidates"
            ] = sorted(
                payload[
                    "candidates"
                ],
                key=lambda item: (
                    item[
                        "candidate_id"
                    ]
                ),
            )

            payload[
                "candidate_count"
            ] = len(
                payload[
                    "candidates"
                ]
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
                site_code,
                environment,
                payload,
            )

            became_confirmed = (
                previous_count
                < HUMAN_NAVIGATION_CANDIDATE_CONFIRMATION_COUNT
                <= candidate[
                    "observation_count"
                ]
            )

            return {
                "recorded":
                    True,

                "duplicate_event":
                    False,

                "became_confirmed":
                    became_confirmed,

                "candidate":
                    json.loads(
                        json.dumps(
                            candidate
                        )
                    ),
            }

    def snapshot(
        self,
        site_code,
        *,
        environment,
    ):
        with self._lock:
            return json.loads(
                json.dumps(
                    self._load(
                        site_code,
                        environment,
                    )
                )
            )

    def confirmed_unpromoted(
        self,
        site_code,
        *,
        environment,
    ):
        payload = self.snapshot(
            site_code,
            environment=environment,
        )

        return tuple(
            item
            for item
            in payload[
                "candidates"
            ]
            if (
                item[
                    "status"
                ]
                == HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
                and item.get(
                    "promoted_at"
                )
                is None
            )
        )

    def mark_promoted(
        self,
        site_code,
        candidate_id,
        *,
        environment,
        promoted_at=None,
    ):
        with self._lock:
            payload = self._load(
                site_code,
                environment,
            )

            candidate = next(
                (
                    item
                    for item
                    in payload[
                        "candidates"
                    ]
                    if item.get(
                        "candidate_id"
                    )
                    == candidate_id
                ),
                None,
            )

            if candidate is None:
                raise ValueError(
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_NOT_FOUND"
                )

            if (
                candidate[
                    "status"
                ]
                != HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
            ):
                raise ValueError(
                    "QCC_HUMAN_NAVIGATION_CANDIDATE_NOT_CONFIRMED"
                )

            if candidate.get(
                "promoted_at"
            ) is not None:
                return json.loads(
                    json.dumps(
                        candidate
                    )
                )

            candidate[
                "promoted_at"
            ] = (
                promoted_at
                or _utc_now()
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
                site_code,
                environment,
                payload,
            )

            return json.loads(
                json.dumps(
                    candidate
                )
            )
