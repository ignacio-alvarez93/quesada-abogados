"""Revisiones candidatas AUTO TWIN.

Una observación CHANGED nunca sustituye automáticamente
el baseline validado.

Se transforma en evidencia candidata:

    CHANGED
        ->
    PENDING_VALIDATION

La revisión ACTIVE permanece intacta.

Este store no:
- materializa HTML/CSS/assets;
- modifica Site Architecture;
- promociona candidatos;
- ejecuta navegación;
- acepta UNKNOWN/KNOWN como cambios.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading

from .managed_site_registry import (
    AutoTwinManagedSite,
)
from .observation_store import (
    AUTO_TWIN_OBSERVATION_CHANGED,
)


AUTO_TWIN_CANDIDATE_STORE_SCHEMA_VERSION = 1

AUTO_TWIN_CANDIDATE_STORE_TYPE = (
    "QCC_AUTO_TWIN_CANDIDATE_REVISION_STORE"
)

AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION = (
    "PENDING_VALIDATION"
)

AUTO_TWIN_CANDIDATE_STATUS_VALIDATED = (
    "VALIDATED"
)

AUTO_TWIN_CANDIDATE_STATUS_REJECTED = (
    "REJECTED"
)

AUTO_TWIN_CANDIDATE_TERMINAL_STATUSES = frozenset({
    AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
    AUTO_TWIN_CANDIDATE_STATUS_REJECTED,
})

DEFAULT_AUTO_TWIN_CANDIDATE_STORE_PATH = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "candidate_revisions.json"
)


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _candidate_identity(
    *,
    twin_key,
    state_key,
    fingerprint,
    baseline_fingerprint,
) -> dict:
    return {
        "twin_key":
            twin_key,

        "state_key":
            state_key,

        "fingerprint":
            fingerprint,

        "baseline_fingerprint":
            baseline_fingerprint,
    }


def _candidate_id(
    identity,
) -> str:
    canonical = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


class AutoTwinCandidateRevisionStore:
    """Store persistente y thread-safe de revisiones candidatas."""

    def __init__(
        self,
        *,
        path=(
            DEFAULT_AUTO_TWIN_CANDIDATE_STORE_PATH
        ),
    ) -> None:
        self._path = Path(
            path
        )

        self._lock = (
            threading.RLock()
        )

        self._revision = 0

        self._twins: dict[
            str,
            dict,
        ] = {}

        self._load()

    @property
    def path(
        self,
    ) -> Path:
        return self._path

    @property
    def revision(
        self,
    ) -> int:
        with self._lock:
            return self._revision

    def _payload(
        self,
        *,
        twins=None,
        revision=None,
    ) -> dict:
        effective_twins = (
            self._twins
            if twins is None
            else twins
        )

        effective_revision = (
            self._revision
            if revision is None
            else revision
        )

        candidate_count = sum(
            len(
                twin.get(
                    "candidates",
                    {},
                )
            )
            for twin
            in effective_twins.values()
            if isinstance(
                twin,
                dict,
            )
        )

        return {
            "schema_version":
                AUTO_TWIN_CANDIDATE_STORE_SCHEMA_VERSION,

            "store_type":
                AUTO_TWIN_CANDIDATE_STORE_TYPE,

            "revision":
                int(
                    effective_revision
                ),

            "twin_count":
                len(
                    effective_twins
                ),

            "candidate_count":
                candidate_count,

            "twins":
                deepcopy(
                    effective_twins
                ),
        }

    def _load(
        self,
    ) -> None:
        if not self._path.is_file():
            return

        try:
            payload = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_STORE_READ_INVALID"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_STORE_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != AUTO_TWIN_CANDIDATE_STORE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_STORE_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "store_type"
            )
            != AUTO_TWIN_CANDIDATE_STORE_TYPE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_STORE_TYPE_INVALID"
            )

        revision = payload.get(
            "revision"
        )

        twins = payload.get(
            "twins"
        )

        if (
            not isinstance(
                revision,
                int,
            )
            or revision < 0
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_REVISION_INVALID"
            )

        if not isinstance(
            twins,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_TWINS_INVALID"
            )

        self._revision = revision

        self._twins = deepcopy(
            twins
        )

    def _persist(
        self,
        *,
        twins,
        revision,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = (
            self._path.with_suffix(
                self._path.suffix
                + ".tmp"
            )
        )

        temporary.write_text(
            json.dumps(
                self._payload(
                    twins=twins,
                    revision=revision,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary.replace(
            self._path
        )

    @staticmethod
    def _next_candidate_revision(
        twin_state,
    ) -> int:
        candidates = twin_state.get(
            "candidates",
            {},
        )

        revisions = [
            int(
                candidate.get(
                    "candidate_revision"
                )
                or 0
            )
            for candidate
            in candidates.values()
            if isinstance(
                candidate,
                dict,
            )
        ]

        return (
            max(
                revisions,
                default=0,
            )
            + 1
        )

    def record_changed_observation(
        self,
        managed_twin,
        observation,
    ) -> dict:
        if not isinstance(
            managed_twin,
            AutoTwinManagedSite,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MANAGED_SITE_INVALID"
            )

        if not isinstance(
            observation,
            dict,
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_CHANGED_OBSERVATION_INVALID"
            )

        classification = _text(
            observation.get(
                "classification"
            )
        ).upper()

        if (
            classification
            != AUTO_TWIN_OBSERVATION_CHANGED
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_REQUIRES_CHANGED"
            )

        capture_id = _text(
            observation.get(
                "capture_id"
            )
        )

        state_key = _text(
            observation.get(
                "state_key"
            )
        )

        fingerprint = _text(
            observation.get(
                "fingerprint"
            )
        )

        baseline_fingerprint = _text(
            observation.get(
                "baseline_fingerprint"
            )
        )

        baseline_capture_id = _text(
            observation.get(
                "baseline_capture_id"
            )
        )

        if not capture_id:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_CAPTURE_ID_REQUIRED"
            )

        if not state_key:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_STATE_KEY_REQUIRED"
            )

        if not fingerprint:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_FINGERPRINT_REQUIRED"
            )

        if not baseline_fingerprint:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_BASELINE_REQUIRED"
            )

        if (
            fingerprint
            == baseline_fingerprint
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_NOT_CHANGED"
            )

        identity = _candidate_identity(
            twin_key=(
                managed_twin.twin_key
            ),
            state_key=state_key,
            fingerprint=fingerprint,
            baseline_fingerprint=(
                baseline_fingerprint
            ),
        )

        candidate_id = (
            _candidate_id(
                identity
            )
        )

        observed_at = (
            _text(
                observation.get(
                    "observed_at"
                )
            )
            or None
        )

        with self._lock:
            candidate_twins = deepcopy(
                self._twins
            )

            twin_state = (
                candidate_twins.setdefault(
                    managed_twin.twin_key,
                    {
                        "twin_key":
                            managed_twin.twin_key,

                        "site_code":
                            managed_twin.site_code,

                        "candidates":
                            {},
                    },
                )
            )

            candidates = twin_state[
                "candidates"
            ]

            existing = candidates.get(
                candidate_id
            )

            if existing is not None:
                evidence_capture_ids = (
                    existing.setdefault(
                        "evidence_capture_ids",
                        [],
                    )
                )

                # Idempotencia exacta.
                if (
                    capture_id
                    in evidence_capture_ids
                ):
                    return {
                        "created":
                            False,

                        "updated":
                            False,

                        "store_revision":
                            self._revision,

                        "candidate":
                            deepcopy(
                                existing
                            ),
                    }

                evidence_capture_ids.append(
                    capture_id
                )

                existing[
                    "latest_capture_id"
                ] = capture_id

                existing[
                    "last_seen_at"
                ] = observed_at

                existing[
                    "observation_count"
                ] = (
                    int(
                        existing.get(
                            "observation_count"
                        )
                        or 0
                    )
                    + 1
                )

                candidate = existing
                created = False
                updated = True

            else:
                candidate_revision = (
                    self._next_candidate_revision(
                        twin_state
                    )
                )

                candidate = {
                    "candidate_id":
                        candidate_id,

                    "candidate_revision":
                        candidate_revision,

                    "status":
                        AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION,

                    **identity,

                    "baseline_capture_id":
                        (
                            baseline_capture_id
                            or None
                        ),

                    "first_capture_id":
                        capture_id,

                    "latest_capture_id":
                        capture_id,

                    "evidence_capture_ids": [
                        capture_id,
                    ],

                    "first_seen_at":
                        observed_at,

                    "last_seen_at":
                        observed_at,

                    "observation_count":
                        1,

                    "pathname":
                        observation.get(
                            "pathname"
                        ),

                    "functional_state":
                        observation.get(
                            "functional_state"
                        ),

                    "browser_profile_key":
                        observation.get(
                            "browser_profile_key"
                        ),
                }

                candidates[
                    candidate_id
                ] = candidate

                created = True
                updated = False

            next_revision = (
                self._revision
                + 1
            )

            self._persist(
                twins=candidate_twins,
                revision=next_revision,
            )

            self._twins = (
                candidate_twins
            )

            self._revision = (
                next_revision
            )

            return {
                "created":
                    created,

                "updated":
                    updated,

                "store_revision":
                    self._revision,

                "candidate":
                    deepcopy(
                        candidate
                    ),
            }

    def get_candidate(
        self,
        twin_key,
        candidate_id,
    ) -> dict | None:
        key = _text(
            twin_key
        )

        normalized_candidate_id = _text(
            candidate_id
        )

        if not key:
            raise ValueError(
                "QCC_AUTO_TWIN_KEY_REQUIRED"
            )

        if not normalized_candidate_id:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
            )

        with self._lock:
            twin = self._twins.get(
                key
            )

            if not isinstance(
                twin,
                dict,
            ):
                return None

            candidates = twin.get(
                "candidates"
            )

            if not isinstance(
                candidates,
                dict,
            ):
                return None

            candidate = candidates.get(
                normalized_candidate_id
            )

            return (
                deepcopy(
                    candidate
                )
                if isinstance(
                    candidate,
                    dict,
                )
                else None
            )

    def transition_candidate_status(
        self,
        twin_key,
        candidate_id,
        *,
        target_status,
    ) -> dict:
        """Aplica únicamente una decisión de validación.

        Transiciones permitidas:

            PENDING_VALIDATION -> VALIDATED
            PENDING_VALIDATION -> REJECTED

        VALIDATED y REJECTED son terminales en esta fase.

        IMPORTANTE:
        VALIDATED no significa ACTIVE.
        Este método nunca modifica baselines ni materialización.
        """

        key = _text(
            twin_key
        )

        normalized_candidate_id = _text(
            candidate_id
        )

        normalized_target = _text(
            target_status
        ).upper()

        if not key:
            raise ValueError(
                "QCC_AUTO_TWIN_KEY_REQUIRED"
            )

        if not normalized_candidate_id:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
            )

        if normalized_target not in {
            AUTO_TWIN_CANDIDATE_STATUS_VALIDATED,
            AUTO_TWIN_CANDIDATE_STATUS_REJECTED,
        }:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_TARGET_STATUS_INVALID"
            )

        with self._lock:
            twin = self._twins.get(
                key
            )

            if not isinstance(
                twin,
                dict,
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND"
                )

            candidates = twin.get(
                "candidates"
            )

            if not isinstance(
                candidates,
                dict,
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND"
                )

            current = candidates.get(
                normalized_candidate_id
            )

            if not isinstance(
                current,
                dict,
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_CANDIDATE_NOT_FOUND"
                )

            current_status = _text(
                current.get(
                    "status"
                )
            ).upper()

            # Idempotencia.
            if (
                current_status
                == normalized_target
            ):
                return {
                    "changed":
                        False,

                    "store_revision":
                        self._revision,

                    "candidate":
                        deepcopy(
                            current
                        ),
                }

            if (
                current_status
                != AUTO_TWIN_CANDIDATE_STATUS_PENDING_VALIDATION
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_CANDIDATE_STATUS_TRANSITION_INVALID"
                )

            candidate_twins = deepcopy(
                self._twins
            )

            candidate = (
                candidate_twins[
                    key
                ][
                    "candidates"
                ][
                    normalized_candidate_id
                ]
            )

            decided_at = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            candidate[
                "status"
            ] = normalized_target

            candidate[
                "status_changed_at"
            ] = decided_at

            if (
                normalized_target
                == AUTO_TWIN_CANDIDATE_STATUS_VALIDATED
            ):
                candidate[
                    "validated_at"
                ] = decided_at

            elif (
                normalized_target
                == AUTO_TWIN_CANDIDATE_STATUS_REJECTED
            ):
                candidate[
                    "rejected_at"
                ] = decided_at

            next_revision = (
                self._revision
                + 1
            )

            self._persist(
                twins=candidate_twins,
                revision=next_revision,
            )

            self._twins = (
                candidate_twins
            )

            self._revision = (
                next_revision
            )

            return {
                "changed":
                    True,

                "store_revision":
                    self._revision,

                "candidate":
                    deepcopy(
                        candidate
                    ),
            }

    def snapshot(
        self,
        twin_key=None,
    ) -> dict:
        with self._lock:
            if twin_key is None:
                return self._payload()

            key = _text(
                twin_key
            )

            if not key:
                raise ValueError(
                    "QCC_AUTO_TWIN_KEY_REQUIRED"
                )

            twin = self._twins.get(
                key
            )

            candidates = []

            if isinstance(
                twin,
                dict,
            ):
                raw_candidates = twin.get(
                    "candidates",
                    {},
                )

                if isinstance(
                    raw_candidates,
                    dict,
                ):
                    candidates = [
                        deepcopy(
                            value
                        )
                        for value
                        in raw_candidates.values()
                        if isinstance(
                            value,
                            dict,
                        )
                    ]

                    candidates.sort(
                        key=lambda item: int(
                            item.get(
                                "candidate_revision"
                            )
                            or 0
                        )
                    )

            return {
                "schema_version":
                    AUTO_TWIN_CANDIDATE_STORE_SCHEMA_VERSION,

                "store_type":
                    AUTO_TWIN_CANDIDATE_STORE_TYPE,

                "revision":
                    self._revision,

                "twin_key":
                    key,

                "found":
                    twin is not None,

                "candidate_count":
                    len(
                        candidates
                    ),

                "candidates":
                    candidates,
            }
