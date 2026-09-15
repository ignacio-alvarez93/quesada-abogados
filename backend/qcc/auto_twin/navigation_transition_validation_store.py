"""Persistent audit store for AUTO TWIN causal transition validation.

Materialized revisions remain immutable.

This store records that one exact TWIN_ELIGIBLE causal transition from
one exact materialized revision was physically replayed inside the
governed local Twin and reached its expected target.

TWIN_VALIDATED never grants authority over REAL.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading


AUTO_TWIN_NAVIGATION_VALIDATION_STORE_SCHEMA_VERSION = 1

AUTO_TWIN_NAVIGATION_VALIDATION_STORE_TYPE = (
    "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_STORE"
)

AUTO_TWIN_NAVIGATION_VALIDATION_STATUS = (
    "TWIN_VALIDATED"
)

DEFAULT_AUTO_TWIN_NAVIGATION_VALIDATION_STORE_PATH = (
    Path("data")
    / "qcc"
    / "auto_twin"
    / "navigation_transition_validation.json"
)


def _text(
    value,
):
    return str(
        value
        or ""
    ).strip()


def _utc_now():
    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def _validation_identity(
    record,
):
    payload = {
        "twin_key":
            record[
                "twin_key"
            ],

        "revision_id":
            record[
                "revision_id"
            ],

        "candidate_id":
            record[
                "candidate_id"
            ],

        "before_state_id":
            record[
                "before_state_id"
            ],

        "after_state_id":
            record[
                "after_state_id"
            ],

        "selector":
            record[
                "selector"
            ],

        "expected_runtime_entry":
            record[
                "expected_runtime_entry"
            ],

        "status":
            AUTO_TWIN_NAVIGATION_VALIDATION_STATUS,
    }

    canonical = json.dumps(
        payload,
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


def _normalize_validation(
    validation,
):
    if not isinstance(
        validation,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_RECORD_INVALID"
        )

    if (
        _text(
            validation.get(
                "status"
            )
        )
        != AUTO_TWIN_NAVIGATION_VALIDATION_STATUS
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_STATUS_INVALID"
        )

    required = (
        "twin_key",
        "revision_id",
        "candidate_id",
        "before_state_id",
        "after_state_id",
        "selector",
        "expected_runtime_entry",
    )

    normalized = {
        key:
            _text(
                validation.get(
                    key
                )
            )
        for key in required
    }

    missing = [
        key
        for key, value
        in normalized.items()
        if not value
    ]

    if missing:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_FIELDS_REQUIRED:"
            + ",".join(
                missing
            )
        )

    location = (
        validation.get(
            "location"
        )
        or {}
    )

    normalized[
        "status"
    ] = (
        AUTO_TWIN_NAVIGATION_VALIDATION_STATUS
    )

    normalized[
        "reason"
    ] = _text(
        validation.get(
            "reason"
        )
    )

    normalized[
        "observed_href"
    ] = _text(
        location.get(
            "href"
        )
        if isinstance(
            location,
            dict,
        )
        else None
    )

    normalized[
        "observed_pathname"
    ] = _text(
        location.get(
            "pathname"
        )
        if isinstance(
            location,
            dict,
        )
        else None
    )

    return normalized


class AutoTwinNavigationTransitionValidationStore:
    def __init__(
        self,
        *,
        path=(
            DEFAULT_AUTO_TWIN_NAVIGATION_VALIDATION_STORE_PATH
        ),
    ):
        self._path = Path(
            path
        )

        self._lock = (
            threading.RLock()
        )

        self._revision = 0
        self._records = {}

        self._load()

    @property
    def path(
        self,
    ):
        return self._path

    @property
    def revision(
        self,
    ):
        with self._lock:
            return self._revision

    def _load(
        self,
    ):
        if not self._path.is_file():
            return

        payload = json.loads(
            self._path.read_text(
                encoding="utf-8"
            )
        )

        if (
            payload.get(
                "schema_version"
            )
            != AUTO_TWIN_NAVIGATION_VALIDATION_STORE_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_STORE_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "record_type"
            )
            != AUTO_TWIN_NAVIGATION_VALIDATION_STORE_TYPE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_STORE_TYPE_INVALID"
            )

        records = payload.get(
            "records"
        )

        if not isinstance(
            records,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_STORE_RECORDS_INVALID"
            )

        self._revision = int(
            payload.get(
                "revision"
            )
            or 0
        )

        self._records = deepcopy(
            records
        )

    def _persist(
        self,
    ):
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "schema_version":
                AUTO_TWIN_NAVIGATION_VALIDATION_STORE_SCHEMA_VERSION,

            "record_type":
                AUTO_TWIN_NAVIGATION_VALIDATION_STORE_TYPE,

            "revision":
                self._revision,

            "record_count":
                len(
                    self._records
                ),

            "records":
                self._records,
        }

        temporary = self._path.with_suffix(
            self._path.suffix
            + ".tmp"
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
            self._path
        )

    def record_twin_validated(
        self,
        validation,
    ):
        normalized = (
            _normalize_validation(
                validation
            )
        )

        evidence_id = (
            _validation_identity(
                normalized
            )
        )

        with self._lock:
            existing = self._records.get(
                evidence_id
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

                    "evidence_id":
                        evidence_id,

                    "record":
                        deepcopy(
                            existing
                        ),
                }

            record = {
                "evidence_id":
                    evidence_id,

                "validated_at":
                    _utc_now(),

                **normalized,
            }

            self._records[
                evidence_id
            ] = record

            self._revision += 1

            self._persist()

            return {
                "created":
                    True,

                "store_revision":
                    self._revision,

                "evidence_id":
                    evidence_id,

                "record":
                    deepcopy(
                        record
                    ),
            }

    def latest_for_candidate(
        self,
        twin_key,
        candidate_id,
    ):
        twin_key = _text(
            twin_key
        )

        candidate_id = _text(
            candidate_id
        )

        matches = [
            record
            for record
            in self._records.values()
            if (
                record.get(
                    "twin_key"
                )
                == twin_key
                and record.get(
                    "candidate_id"
                )
                == candidate_id
            )
        ]

        if not matches:
            return None

        matches.sort(
            key=lambda record: (
                _text(
                    record.get(
                        "validated_at"
                    )
                ),
                _text(
                    record.get(
                        "evidence_id"
                    )
                ),
            )
        )

        return deepcopy(
            matches[-1]
        )

    def latest_for_revision_candidate(
        self,
        twin_key,
        revision_id,
        candidate_id,
    ):
        twin_key = _text(
            twin_key
        )

        revision_id = _text(
            revision_id
        )

        candidate_id = _text(
            candidate_id
        )

        matches = [
            record
            for record
            in self._records.values()
            if (
                record.get(
                    "twin_key"
                )
                == twin_key
                and record.get(
                    "revision_id"
                )
                == revision_id
                and record.get(
                    "candidate_id"
                )
                == candidate_id
                and record.get(
                    "status"
                )
                == AUTO_TWIN_NAVIGATION_VALIDATION_STATUS
            )
        ]

        if not matches:
            return None

        matches.sort(
            key=lambda record: (
                _text(
                    record.get(
                        "validated_at"
                    )
                ),
                _text(
                    record.get(
                        "evidence_id"
                    )
                ),
            )
        )

        return deepcopy(
            matches[-1]
        )

    def snapshot(
        self,
    ):
        with self._lock:
            records = list(
                deepcopy(
                    self._records
                ).values()
            )

            records.sort(
                key=lambda record: (
                    _text(
                        record.get(
                            "validated_at"
                        )
                    ),
                    _text(
                        record.get(
                            "evidence_id"
                        )
                    ),
                )
            )

            return {
                "schema_version":
                    AUTO_TWIN_NAVIGATION_VALIDATION_STORE_SCHEMA_VERSION,

                "record_type":
                    AUTO_TWIN_NAVIGATION_VALIDATION_STORE_TYPE,

                "revision":
                    self._revision,

                "record_count":
                    len(
                        records
                    ),

                "records":
                    records,
            }


_DEFAULT_STORE = (
    AutoTwinNavigationTransitionValidationStore()
)


def get_default_navigation_transition_validation_store():
    return _DEFAULT_STORE
