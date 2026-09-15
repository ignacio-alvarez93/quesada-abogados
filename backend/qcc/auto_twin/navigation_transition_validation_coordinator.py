"""Background coordinator for governed AUTO TWIN transition validation.

The Bridge only enqueues immutable materialized revisions.

The worker:
- serializes Twin browser validation;
- skips exact revision/candidate pairs already TWIN_VALIDATED;
- never touches REAL;
- never blocks the QCC ingestion request;
- keeps materialized revisions immutable.
"""

from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import time

from backend.services.twin_browser_runtime_service import (
    DEFAULT_MATERIALIZED_ROOT,
)

from .navigation_transition_validation import (
    validate_and_record_materialized_navigation_transition,
)

from .navigation_transition_validation_store import (
    get_default_navigation_transition_validation_store,
)


AUTO_TWIN_NAVIGATION_VALIDATION_COORDINATOR_SCHEMA_VERSION = 1


def _text(
    value,
):
    return str(
        value
        or ""
    ).strip()


def _segment(
    value,
    *,
    error,
):
    value = _text(
        value
    )

    if (
        not value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise ValueError(
            error
        )

    return value


class AutoTwinNavigationTransitionValidationCoordinator:
    def __init__(
        self,
        *,
        materialized_root=DEFAULT_MATERIALIZED_ROOT,
        validation_store=None,
        validator=None,
    ):
        self.materialized_root = Path(
            materialized_root
        )

        self.validation_store = (
            validation_store
            or get_default_navigation_transition_validation_store()
        )

        self._validator = (
            validator
            or validate_and_record_materialized_navigation_transition
        )

        self._lock = threading.RLock()
        self._queue = queue.Queue()

        self._pending = set()
        self._worker = None

        self._last_result = None

    def _job_key(
        self,
        *,
        twin_key,
        revision_id,
    ):
        return (
            _segment(
                twin_key,
                error=(
                    "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
                    "COORDINATOR_TWIN_KEY_INVALID"
                ),
            ),
            _segment(
                revision_id,
                error=(
                    "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
                    "COORDINATOR_REVISION_ID_INVALID"
                ),
            ),
        )

    def _ensure_worker_locked(
        self,
    ):
        if (
            self._worker is not None
            and self._worker.is_alive()
        ):
            return

        self._worker = threading.Thread(
            target=self._worker_loop,
            name=(
                "qcc-auto-twin-navigation-validation"
            ),
            daemon=True,
        )

        self._worker.start()

    def enqueue(
        self,
        *,
        twin_key,
        revision_id,
    ):
        key = self._job_key(
            twin_key=twin_key,
            revision_id=revision_id,
        )

        with self._lock:
            if key in self._pending:
                return {
                    "schema_version":
                        AUTO_TWIN_NAVIGATION_VALIDATION_COORDINATOR_SCHEMA_VERSION,

                    "status":
                        "DEDUPED",

                    "twin_key":
                        key[0],

                    "revision_id":
                        key[1],
                }

            self._pending.add(
                key
            )

            self._ensure_worker_locked()

            self._queue.put({
                "twin_key":
                    key[0],

                "revision_id":
                    key[1],
            })

        return {
            "schema_version":
                AUTO_TWIN_NAVIGATION_VALIDATION_COORDINATOR_SCHEMA_VERSION,

            "status":
                "QUEUED",

            "twin_key":
                key[0],

            "revision_id":
                key[1],
        }

    def _load_transitions(
        self,
        *,
        twin_key,
        revision_id,
    ):
        path = (
            self.materialized_root
            / twin_key
            / revision_id
            / "runtime"
            / "navigation_transitions.json"
        )

        if not path.is_file():
            return ()

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        transitions = payload.get(
            "transitions"
        )

        if not isinstance(
            transitions,
            list,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_VALIDATION_"
                "COORDINATOR_TRANSITIONS_INVALID"
            )

        return tuple(
            transition
            for transition
            in transitions
            if isinstance(
                transition,
                dict,
            )
        )

    def process_revision(
        self,
        *,
        twin_key,
        revision_id,
    ):
        twin_key, revision_id = (
            self._job_key(
                twin_key=twin_key,
                revision_id=revision_id,
            )
        )

        transitions = self._load_transitions(
            twin_key=twin_key,
            revision_id=revision_id,
        )

        validated = 0
        skipped = 0
        failed = 0
        results = []

        for transition in transitions:
            candidate_id = _text(
                transition.get(
                    "candidate_id"
                )
            )

            if not candidate_id:
                failed += 1

                results.append({
                    "status":
                        "FAILED",

                    "reason":
                        "CANDIDATE_ID_REQUIRED",
                })

                continue

            existing = (
                self.validation_store
                .latest_for_revision_candidate(
                    twin_key,
                    revision_id,
                    candidate_id,
                )
            )

            if existing is not None:
                skipped += 1

                results.append({
                    "status":
                        "SKIPPED",

                    "reason":
                        "ALREADY_TWIN_VALIDATED",

                    "candidate_id":
                        candidate_id,
                })

                continue

            try:
                result = self._validator(
                    twin_key=twin_key,
                    revision_id=revision_id,
                    candidate_id=candidate_id,
                    validation_store=(
                        self.validation_store
                    ),
                    materialized_root=(
                        self.materialized_root
                    ),
                )

                results.append(
                    result
                )

                if (
                    result.get(
                        "status"
                    )
                    == "TWIN_VALIDATED"
                    and result.get(
                        "recorded"
                    )
                    is True
                ):
                    validated += 1
                else:
                    failed += 1

            except Exception as exc:
                failed += 1

                results.append({
                    "status":
                        "FAILED",

                    "candidate_id":
                        candidate_id,

                    "reason":
                        (
                            type(exc).__name__
                            + ":"
                            + str(exc)
                        ),
                })

        result = {
            "schema_version":
                AUTO_TWIN_NAVIGATION_VALIDATION_COORDINATOR_SCHEMA_VERSION,

            "status":
                (
                    "COMPLETE"
                    if failed == 0
                    else "PARTIAL"
                ),

            "twin_key":
                twin_key,

            "revision_id":
                revision_id,

            "transition_count":
                len(
                    transitions
                ),

            "validated_count":
                validated,

            "skipped_count":
                skipped,

            "failed_count":
                failed,

            "results":
                results,
        }

        with self._lock:
            self._last_result = result

        return result

    def _worker_loop(
        self,
    ):
        while True:
            job = self._queue.get()

            key = (
                job[
                    "twin_key"
                ],
                job[
                    "revision_id"
                ],
            )

            try:
                self.process_revision(
                    twin_key=key[0],
                    revision_id=key[1],
                )

            finally:
                with self._lock:
                    self._pending.discard(
                        key
                    )

                self._queue.task_done()

    def wait_until_idle(
        self,
        *,
        timeout=10.0,
    ):
        deadline = (
            time.monotonic()
            + float(
                timeout
            )
        )

        while True:
            with self._lock:
                pending = len(
                    self._pending
                )

            if pending == 0:
                return True

            if (
                time.monotonic()
                >= deadline
            ):
                return False

            time.sleep(
                0.01
            )

    def snapshot(
        self,
    ):
        with self._lock:
            return {
                "schema_version":
                    AUTO_TWIN_NAVIGATION_VALIDATION_COORDINATOR_SCHEMA_VERSION,

                "pending_count":
                    len(
                        self._pending
                    ),

                "worker_alive":
                    (
                        self._worker is not None
                        and self._worker.is_alive()
                    ),

                "last_result":
                    self._last_result,
            }


_DEFAULT_COORDINATOR = (
    AutoTwinNavigationTransitionValidationCoordinator()
)


def get_default_navigation_transition_validation_coordinator():
    return _DEFAULT_COORDINATOR
