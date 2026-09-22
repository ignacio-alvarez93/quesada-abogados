"""Background coordinator for governed AUTO TWIN post-learning materialization.

The Bridge resolves Twin authority BEFORE enqueue and only publishes a
trusted (twin_key, trigger_capture_id) job.

The worker:
- runs the injected processor (the existing synchronous materialization
  helper) outside the human-dom-action request thread;
- coalesces per twin_key (latest pending payload wins);
- never runs two jobs concurrently (single worker);
- isolates processor exceptions.

Pending state is transient execution state only. It is never persisted
and is never an authority source: every job carries the exact trusted
trigger_capture_id resolved by the caller.
"""

from __future__ import annotations

import queue
import threading
import time


AUTO_TWIN_MATERIALIZATION_COORDINATOR_SCHEMA_VERSION = 1


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


def _safe_result(
    result,
):
    """Whitelist scalar, non-sensitive fields of a processor result."""

    if not isinstance(
        result,
        dict,
    ):
        return None

    return {
        key: result[key]
        for key
        in (
            "status",
            "reason",
            "materialized_revision_id",
        )
        if isinstance(
            result.get(
                key
            ),
            str,
        )
    }


class AutoTwinMaterializationCoordinator:
    def __init__(
        self,
        *,
        processor,
    ):
        if not callable(
            processor
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_MATERIALIZATION_"
                "COORDINATOR_PROCESSOR_REQUIRED"
            )

        self._processor = processor

        self._lock = threading.RLock()
        self._queue = queue.Queue()

        # twin_key -> trigger_capture_id, queued and not yet running.
        self._pending = {}

        # twin_key currently owned by the worker.
        self._running = set()

        self._worker = None

        self._last_result = None

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
                "qcc-auto-twin-materialization"
            ),
            daemon=True,
        )

        self._worker.start()

    def enqueue(
        self,
        *,
        twin_key,
        trigger_capture_id,
    ):
        twin_key = _segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_MATERIALIZATION_"
                "COORDINATOR_TWIN_KEY_INVALID"
            ),
        )

        trigger_capture_id = _segment(
            trigger_capture_id,
            error=(
                "QCC_AUTO_TWIN_MATERIALIZATION_"
                "COORDINATOR_TRIGGER_CAPTURE_ID_INVALID"
            ),
        )

        with self._lock:
            coalesced = (
                twin_key
                in self._pending
            )

            # Replace the payload in place: the single queue token
            # for this twin already exists.
            self._pending[
                twin_key
            ] = trigger_capture_id

            if not coalesced:
                self._ensure_worker_locked()

                self._queue.put(
                    twin_key
                )

        return {
            "schema_version":
                AUTO_TWIN_MATERIALIZATION_COORDINATOR_SCHEMA_VERSION,

            "status":
                (
                    "COALESCED"
                    if coalesced
                    else "QUEUED"
                ),

            "twin_key":
                twin_key,

            "trigger_capture_id":
                trigger_capture_id,
        }

    def _process(
        self,
        *,
        twin_key,
        trigger_capture_id,
    ):
        try:
            result = _safe_result(
                self._processor(
                    twin_key=twin_key,
                    trigger_capture_id=(
                        trigger_capture_id
                    ),
                )
            )

            status = (
                (
                    result
                    or {}
                ).get(
                    "status"
                )
                or "COMPLETE"
            )

            record = {
                "status":
                    status,

                **{
                    key: value
                    for key, value
                    in (
                        result
                        or {}
                    ).items()
                    if key != "status"
                },
            }

        except Exception as exc:
            record = {
                "status":
                    "ERROR",

                "reason":
                    type(exc).__name__,
            }

        record.update({
            "twin_key":
                twin_key,

            "trigger_capture_id":
                trigger_capture_id,
        })

        with self._lock:
            self._last_result = record

    def _worker_loop(
        self,
    ):
        while True:
            twin_key = self._queue.get()

            try:
                # Atomically move pending -> running so that
                # wait_until_idle() never observes a gap.
                with self._lock:
                    trigger_capture_id = (
                        self._pending.pop(
                            twin_key
                        )
                    )

                    self._running.add(
                        twin_key
                    )

                try:
                    self._process(
                        twin_key=twin_key,
                        trigger_capture_id=(
                            trigger_capture_id
                        ),
                    )

                finally:
                    with self._lock:
                        self._running.discard(
                            twin_key
                        )

            finally:
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
                busy = bool(
                    self._pending
                    or self._running
                )

            if not busy:
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
                    AUTO_TWIN_MATERIALIZATION_COORDINATOR_SCHEMA_VERSION,

                "pending_count":
                    len(
                        self._pending
                    ),

                "running_count":
                    len(
                        self._running
                    ),

                "worker_alive":
                    (
                        self._worker is not None
                        and self._worker.is_alive()
                    ),

                "last_result":
                    (
                        dict(
                            self._last_result
                        )
                        if self._last_result
                        is not None
                        else None
                    ),
            }
