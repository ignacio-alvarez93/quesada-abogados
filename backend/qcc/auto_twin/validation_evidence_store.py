"""Persistencia auditable de ValidationEvidence AUTO TWIN.

Responsabilidad exclusiva:

    ValidationEvidence
        -> memoria ligera persistente

No modifica:
- candidate lifecycle;
- status VALIDATED / REJECTED;
- baselines;
- materialización;
- ACTIVE.

La evidencia permanece separada del CandidateRevisionStore.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading

from .validation_evidence import (
    AUTO_TWIN_VALIDATION_EVIDENCE_SCHEMA_VERSION,
    AUTO_TWIN_VALIDATION_EVIDENCE_TYPE,
    build_auto_twin_validation_evidence,
)


AUTO_TWIN_VALIDATION_EVIDENCE_STORE_SCHEMA_VERSION = 1

AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE = (
    "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STORE"
)

DEFAULT_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_PATH = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "validation_evidence.json"
)


def _text(
    value,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _json_value(
    value,
):
    """Normaliza tuple/list y otros valores JSON equivalentes."""

    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _canonical_json(
    value,
) -> str:
    return json.dumps(
        _json_value(
            value
        ),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalize_validation_evidence(
    value,
) -> dict:
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_INVALID"
        )

    if (
        value.get(
            "schema_version"
        )
        != AUTO_TWIN_VALIDATION_EVIDENCE_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_SCHEMA_INVALID"
        )

    if (
        value.get(
            "evidence_type"
        )
        != AUTO_TWIN_VALIDATION_EVIDENCE_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TYPE_INVALID"
        )

    state_identity = (
        value.get(
            "state_identity"
        )
        or {}
    )

    capture_pair = (
        value.get(
            "capture_pair"
        )
        or {}
    )

    if not isinstance(
        state_identity,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STATE_INVALID"
        )

    if not isinstance(
        capture_pair,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CAPTURE_PAIR_INVALID"
        )

    rebuilt = (
        build_auto_twin_validation_evidence(
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
            candidate_revision=(
                value.get(
                    "candidate_revision"
                )
            ),
            real_capture_id=(
                capture_pair.get(
                    "real_capture_id"
                )
            ),
            twin_capture_id=(
                capture_pair.get(
                    "twin_capture_id"
                )
            ),
            pathname=(
                state_identity.get(
                    "pathname"
                )
            ),
            functional_state=(
                state_identity.get(
                    "functional_state"
                )
            ),
            checks=(
                value.get(
                    "checks"
                )
            ),
            required_dimensions=(
                value.get(
                    "required_dimensions"
                )
            ),
            rendering_profile_id=(
                value.get(
                    "rendering_profile_id"
                )
            ),
        )
    )

    supplied_json = (
        _json_value(
            value
        )
    )

    rebuilt_json = (
        _json_value(
            rebuilt
        )
    )

    if (
        supplied_json
        != rebuilt_json
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TAMPERED"
        )

    return rebuilt_json


def _evidence_id(
    evidence,
) -> str:
    canonical = (
        _canonical_json(
            evidence
        )
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def _record_sort_key(
    record,
):
    return (
        _text(
            record.get(
                "recorded_at"
            )
        ),
        _text(
            record.get(
                "evidence_id"
            )
        ),
    )


class AutoTwinValidationEvidenceStore:
    """Store persistente de evidencias de fidelidad."""

    def __init__(
        self,
        *,
        path=(
            DEFAULT_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_PATH
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

    @staticmethod
    def _counts(
        twins,
    ):
        candidate_count = 0
        evidence_count = 0

        for twin in twins.values():
            if not isinstance(
                twin,
                dict,
            ):
                continue

            candidates = (
                twin.get(
                    "candidates"
                )
                or {}
            )

            if not isinstance(
                candidates,
                dict,
            ):
                continue

            candidate_count += len(
                candidates
            )

            for candidate in (
                candidates.values()
            ):
                if not isinstance(
                    candidate,
                    dict,
                ):
                    continue

                evidence = (
                    candidate.get(
                        "evidence"
                    )
                    or {}
                )

                if isinstance(
                    evidence,
                    dict,
                ):
                    evidence_count += len(
                        evidence
                    )

        return (
            candidate_count,
            evidence_count,
        )

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

        (
            candidate_count,
            evidence_count,
        ) = self._counts(
            effective_twins
        )

        return {
            "schema_version":
                AUTO_TWIN_VALIDATION_EVIDENCE_STORE_SCHEMA_VERSION,

            "store_type":
                AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE,

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

            "evidence_count":
                evidence_count,

            "twins":
                deepcopy(
                    effective_twins
                ),
        }

    @staticmethod
    def _validate_loaded_twins(
        twins,
    ) -> dict:
        if not isinstance(
            twins,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TWINS_INVALID"
            )

        normalized_twins = {}

        for raw_twin_key, raw_twin in (
            twins.items()
        ):
            twin_key = _text(
                raw_twin_key
            )

            if (
                not twin_key
                or twin_key
                != raw_twin_key
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TWIN_KEY_INVALID"
                )

            if not isinstance(
                raw_twin,
                dict,
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TWIN_INVALID"
                )

            raw_candidates = (
                raw_twin.get(
                    "candidates"
                )
            )

            if not isinstance(
                raw_candidates,
                dict,
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CANDIDATES_INVALID"
                )

            normalized_candidates = {}

            for (
                raw_candidate_id,
                raw_candidate,
            ) in raw_candidates.items():
                candidate_id = _text(
                    raw_candidate_id
                )

                if (
                    not candidate_id
                    or candidate_id
                    != raw_candidate_id
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CANDIDATE_ID_INVALID"
                    )

                if not isinstance(
                    raw_candidate,
                    dict,
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CANDIDATE_INVALID"
                    )

                candidate_revision = (
                    raw_candidate.get(
                        "candidate_revision"
                    )
                )

                if (
                    not isinstance(
                        candidate_revision,
                        int,
                    )
                    or candidate_revision <= 0
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CANDIDATE_REVISION_INVALID"
                    )

                raw_evidence = (
                    raw_candidate.get(
                        "evidence"
                    )
                )

                if not isinstance(
                    raw_evidence,
                    dict,
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_RECORDS_INVALID"
                    )

                normalized_evidence = {}

                for (
                    raw_evidence_id,
                    raw_record,
                ) in raw_evidence.items():
                    if not isinstance(
                        raw_record,
                        dict,
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_RECORD_INVALID"
                        )

                    evidence_id = _text(
                        raw_evidence_id
                    )

                    recorded_at = _text(
                        raw_record.get(
                            "recorded_at"
                        )
                    )

                    nested = (
                        raw_record.get(
                            "validation_evidence"
                        )
                    )

                    if not evidence_id:
                        raise ValueError(
                            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_ID_INVALID"
                        )

                    if not recorded_at:
                        raise ValueError(
                            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_RECORDED_AT_REQUIRED"
                        )

                    normalized = (
                        _normalize_validation_evidence(
                            nested
                        )
                    )

                    if (
                        normalized[
                            "twin_key"
                        ]
                        != twin_key
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_TWIN_KEY_MISMATCH"
                        )

                    if (
                        normalized[
                            "candidate_id"
                        ]
                        != candidate_id
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CANDIDATE_MISMATCH"
                        )

                    if (
                        normalized[
                            "candidate_revision"
                        ]
                        != candidate_revision
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CANDIDATE_REVISION_MISMATCH"
                        )

                    expected_id = (
                        _evidence_id(
                            normalized
                        )
                    )

                    if (
                        evidence_id
                        != expected_id
                        or _text(
                            raw_record.get(
                                "evidence_id"
                            )
                        )
                        != expected_id
                    ):
                        raise ValueError(
                            "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_ID_MISMATCH"
                        )

                    normalized_evidence[
                        expected_id
                    ] = {
                        "evidence_id":
                            expected_id,

                        "recorded_at":
                            recorded_at,

                        "validation_evidence":
                            normalized,
                    }

                normalized_candidates[
                    candidate_id
                ] = {
                    "candidate_revision":
                        candidate_revision,

                    "evidence":
                        normalized_evidence,
                }

            normalized_twins[
                twin_key
            ] = {
                "candidates":
                    normalized_candidates,
            }

        return normalized_twins

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
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_READ_INVALID"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_INVALID"
            )

        if (
            payload.get(
                "schema_version"
            )
            != AUTO_TWIN_VALIDATION_EVIDENCE_STORE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "store_type"
            )
            != AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE_INVALID"
            )

        revision = payload.get(
            "revision"
        )

        if (
            not isinstance(
                revision,
                int,
            )
            or revision < 0
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_REVISION_INVALID"
            )

        twins = (
            self._validate_loaded_twins(
                payload.get(
                    "twins"
                )
            )
        )

        (
            candidate_count,
            evidence_count,
        ) = self._counts(
            twins
        )

        if (
            payload.get(
                "twin_count"
            )
            != len(
                twins
            )
            or payload.get(
                "candidate_count"
            )
            != candidate_count
            or payload.get(
                "evidence_count"
            )
            != evidence_count
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_STORE_COUNTS_INVALID"
            )

        self._revision = revision

        self._twins = twins

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

    def record_validation_evidence(
        self,
        evidence,
    ) -> dict:
        normalized = (
            _normalize_validation_evidence(
                evidence
            )
        )

        twin_key = normalized[
            "twin_key"
        ]

        candidate_id = normalized[
            "candidate_id"
        ]

        candidate_revision = normalized[
            "candidate_revision"
        ]

        evidence_id = (
            _evidence_id(
                normalized
            )
        )

        with self._lock:
            current_twin = (
                self._twins.get(
                    twin_key
                )
                or {}
            )

            current_candidates = (
                current_twin.get(
                    "candidates"
                )
                or {}
            )

            current_candidate = (
                current_candidates.get(
                    candidate_id
                )
            )

            if isinstance(
                current_candidate,
                dict,
            ):
                stored_revision = (
                    current_candidate.get(
                        "candidate_revision"
                    )
                )

                if (
                    stored_revision
                    != candidate_revision
                ):
                    raise ValueError(
                        "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_CANDIDATE_REVISION_CONFLICT"
                    )

                existing = (
                    current_candidate.get(
                        "evidence",
                        {},
                    ).get(
                        evidence_id
                    )
                )

                if isinstance(
                    existing,
                    dict,
                ):
                    return {
                        "created":
                            False,

                        "store_revision":
                            self._revision,

                        "record":
                            deepcopy(
                                existing
                            ),
                    }

            candidate_twins = deepcopy(
                self._twins
            )

            twin_state = (
                candidate_twins.setdefault(
                    twin_key,
                    {
                        "candidates": {},
                    },
                )
            )

            candidates = (
                twin_state.setdefault(
                    "candidates",
                    {},
                )
            )

            candidate = (
                candidates.get(
                    candidate_id
                )
            )

            if candidate is None:
                candidate = {
                    "candidate_revision":
                        candidate_revision,

                    "evidence":
                        {},
                }

                candidates[
                    candidate_id
                ] = candidate

            record = {
                "evidence_id":
                    evidence_id,

                "recorded_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "validation_evidence":
                    deepcopy(
                        normalized
                    ),
            }

            candidate[
                "evidence"
            ][
                evidence_id
            ] = record

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
                    True,

                "store_revision":
                    self._revision,

                "record":
                    deepcopy(
                        record
                    ),
            }

    def get_evidence(
        self,
        twin_key,
        candidate_id,
        evidence_id,
    ) -> dict | None:
        key = _text(
            twin_key
        )

        candidate_key = _text(
            candidate_id
        )

        evidence_key = _text(
            evidence_id
        )

        if not key:
            raise ValueError(
                "QCC_AUTO_TWIN_KEY_REQUIRED"
            )

        if not candidate_key:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
            )

        if not evidence_key:
            raise ValueError(
                "QCC_AUTO_TWIN_VALIDATION_EVIDENCE_ID_REQUIRED"
            )

        with self._lock:
            record = (
                self._twins
                .get(
                    key,
                    {},
                )
                .get(
                    "candidates",
                    {},
                )
                .get(
                    candidate_key,
                    {},
                )
                .get(
                    "evidence",
                    {},
                )
                .get(
                    evidence_key
                )
            )

            return (
                deepcopy(
                    record
                )
                if isinstance(
                    record,
                    dict,
                )
                else None
            )

    def latest_for_candidate(
        self,
        twin_key,
        candidate_id,
    ) -> dict | None:
        key = _text(
            twin_key
        )

        candidate_key = _text(
            candidate_id
        )

        if not key:
            raise ValueError(
                "QCC_AUTO_TWIN_KEY_REQUIRED"
            )

        if not candidate_key:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
            )

        with self._lock:
            evidence = (
                self._twins
                .get(
                    key,
                    {},
                )
                .get(
                    "candidates",
                    {},
                )
                .get(
                    candidate_key,
                    {},
                )
                .get(
                    "evidence",
                    {},
                )
            )

            records = [
                record
                for record
                in evidence.values()
                if isinstance(
                    record,
                    dict,
                )
            ]

            if not records:
                return None

            return deepcopy(
                max(
                    records,
                    key=_record_sort_key,
                )
            )

    @staticmethod
    def _candidate_projection(
        candidate_id,
        candidate,
    ) -> dict:
        evidence = (
            candidate.get(
                "evidence"
            )
            or {}
        )

        records = [
            deepcopy(
                record
            )
            for record
            in evidence.values()
            if isinstance(
                record,
                dict,
            )
        ]

        records.sort(
            key=_record_sort_key
        )

        return {
            "candidate_id":
                candidate_id,

            "candidate_revision":
                candidate.get(
                    "candidate_revision"
                ),

            "evidence_count":
                len(
                    records
                ),

            "latest_evidence":
                (
                    deepcopy(
                        records[-1]
                    )
                    if records
                    else None
                ),

            "evidence":
                records,
        }

    def candidate_snapshot(
        self,
        twin_key,
        candidate_id,
    ) -> dict:
        key = _text(
            twin_key
        )

        candidate_key = _text(
            candidate_id
        )

        if not key:
            raise ValueError(
                "QCC_AUTO_TWIN_KEY_REQUIRED"
            )

        if not candidate_key:
            raise ValueError(
                "QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED"
            )

        with self._lock:
            candidate = (
                self._twins
                .get(
                    key,
                    {},
                )
                .get(
                    "candidates",
                    {},
                )
                .get(
                    candidate_key
                )
            )

            return {
                "schema_version":
                    AUTO_TWIN_VALIDATION_EVIDENCE_STORE_SCHEMA_VERSION,

                "store_type":
                    AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE,

                "revision":
                    self._revision,

                "twin_key":
                    key,

                "candidate_id":
                    candidate_key,

                "found":
                    isinstance(
                        candidate,
                        dict,
                    ),

                "candidate":
                    (
                        self._candidate_projection(
                            candidate_key,
                            candidate,
                        )
                        if isinstance(
                            candidate,
                            dict,
                        )
                        else None
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
                raw_candidates = (
                    twin.get(
                        "candidates"
                    )
                    or {}
                )

                if isinstance(
                    raw_candidates,
                    dict,
                ):
                    candidates = [
                        self._candidate_projection(
                            candidate_id,
                            candidate,
                        )
                        for (
                            candidate_id,
                            candidate,
                        )
                        in raw_candidates.items()
                        if isinstance(
                            candidate,
                            dict,
                        )
                    ]

            candidates.sort(
                key=lambda item: (
                    int(
                        item.get(
                            "candidate_revision"
                        )
                        or 0
                    ),
                    str(
                        item.get(
                            "candidate_id"
                        )
                        or ""
                    ),
                )
            )

            evidence_count = sum(
                int(
                    candidate.get(
                        "evidence_count"
                    )
                    or 0
                )
                for candidate
                in candidates
            )

            return {
                "schema_version":
                    AUTO_TWIN_VALIDATION_EVIDENCE_STORE_SCHEMA_VERSION,

                "store_type":
                    AUTO_TWIN_VALIDATION_EVIDENCE_STORE_TYPE,

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

                "evidence_count":
                    evidence_count,

                "candidates":
                    candidates,
            }
