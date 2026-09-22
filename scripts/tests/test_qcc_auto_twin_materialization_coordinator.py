"""AUTO TWIN post-learning materialization coordinator.

Pure coordinator semantics: per-twin coalescing, single worker,
exception isolation and safe observable state. The processor is always
injected, so no materializer is involved.
"""

import json
import threading

import pytest

from backend.qcc.auto_twin.materialization_coordinator import (
    AutoTwinMaterializationCoordinator,
)


TIMEOUT = 5.0


class _Processor:
    """Records calls; optionally blocks each call until released."""

    def __init__(self, *, block=False):
        self.calls = []
        self.block = block
        self.started = threading.Semaphore(0)
        self.release = threading.Semaphore(0)

    def __call__(self, *, twin_key, trigger_capture_id):
        self.calls.append((twin_key, trigger_capture_id))
        self.started.release()

        if self.block:
            assert self.release.acquire(timeout=TIMEOUT)

        return {"status": "MATERIALIZED"}


def _enqueue(coordinator, twin_key, capture_id):
    return coordinator.enqueue(
        twin_key=twin_key,
        trigger_capture_id=capture_id,
    )


def test_first_job_is_queued_and_processed():
    processor = _Processor()
    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    result = _enqueue(coordinator, "mercurio", "cap-1")

    assert result["status"] == "QUEUED"
    assert result["twin_key"] == "mercurio"
    assert result["trigger_capture_id"] == "cap-1"

    assert coordinator.wait_until_idle(timeout=TIMEOUT)
    assert processor.calls == [("mercurio", "cap-1")]


def test_same_twin_pending_job_is_coalesced_with_one_queue_entry():
    processor = _Processor(block=True)
    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    # Occupy the single worker with another twin so "mercurio" stays
    # queued-but-not-running.
    _enqueue(coordinator, "blocker", "cap-blocker")
    assert processor.started.acquire(timeout=TIMEOUT)

    first = _enqueue(coordinator, "mercurio", "cap-A")
    second = _enqueue(coordinator, "mercurio", "cap-B")

    assert first["status"] == "QUEUED"
    assert second["status"] == "COALESCED"

    # Exactly one pending entry and one queue token for mercurio.
    assert coordinator.snapshot()["pending_count"] == 1
    assert coordinator._queue.qsize() == 1

    processor.release.release(2)
    assert coordinator.wait_until_idle(timeout=TIMEOUT)


def test_replacement_uses_replacement_trusted_capture():
    processor = _Processor(block=True)
    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    _enqueue(coordinator, "blocker", "cap-blocker")
    assert processor.started.acquire(timeout=TIMEOUT)

    _enqueue(coordinator, "mercurio", "cap-A")
    _enqueue(coordinator, "mercurio", "cap-B")

    processor.release.release(2)
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    assert processor.calls == [
        ("blocker", "cap-blocker"),
        ("mercurio", "cap-B"),
    ]
    assert ("mercurio", "cap-A") not in processor.calls


def test_enqueues_during_running_job_yield_current_plus_one_follow_up():
    processor = _Processor(block=True)
    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    assert _enqueue(coordinator, "mercurio", "cap-A")["status"] == "QUEUED"
    assert processor.started.acquire(timeout=TIMEOUT)

    # A is running now.
    assert coordinator.snapshot()["running_count"] == 1
    assert coordinator.snapshot()["pending_count"] == 0

    b = _enqueue(coordinator, "mercurio", "cap-B")
    c = _enqueue(coordinator, "mercurio", "cap-C")
    d = _enqueue(coordinator, "mercurio", "cap-D")

    assert [b["status"], c["status"], d["status"]] == [
        "QUEUED",
        "COALESCED",
        "COALESCED",
    ]

    # The running job is untouched.
    assert processor.calls == [("mercurio", "cap-A")]

    processor.release.release(3)
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    # Current + exactly ONE follow-up carrying the last payload.
    assert processor.calls == [
        ("mercurio", "cap-A"),
        ("mercurio", "cap-D"),
    ]


def test_different_twins_are_not_coalesced():
    processor = _Processor(block=True)
    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    _enqueue(coordinator, "blocker", "cap-blocker")
    assert processor.started.acquire(timeout=TIMEOUT)

    one = _enqueue(coordinator, "twin_one", "cap-1")
    two = _enqueue(coordinator, "twin_two", "cap-2")

    assert one["status"] == "QUEUED"
    assert two["status"] == "QUEUED"
    assert coordinator.snapshot()["pending_count"] == 2

    processor.release.release(3)
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    assert sorted(processor.calls) == [
        ("blocker", "cap-blocker"),
        ("twin_one", "cap-1"),
        ("twin_two", "cap-2"),
    ]


def test_processor_exception_does_not_kill_worker():
    calls = []

    def processor(*, twin_key, trigger_capture_id):
        calls.append((twin_key, trigger_capture_id))

        if trigger_capture_id == "cap-bad":
            raise RuntimeError("SECRET-onclick-continuar('INI')")

        return {"status": "NO_CHANGE"}

    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    _enqueue(coordinator, "mercurio", "cap-bad")
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    failed = coordinator.snapshot()

    assert failed["worker_alive"] is True
    assert failed["last_result"]["status"] == "ERROR"
    assert failed["last_result"]["reason"] == "RuntimeError"

    # Only the exception type is observable, never its message.
    assert "SECRET" not in json.dumps(failed)

    _enqueue(coordinator, "mercurio", "cap-good")
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    assert calls == [
        ("mercurio", "cap-bad"),
        ("mercurio", "cap-good"),
    ]
    assert coordinator.snapshot()["last_result"]["status"] == "NO_CHANGE"


def test_wait_until_idle_reflects_running_work():
    processor = _Processor(block=True)
    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    # Idle before any work.
    assert coordinator.wait_until_idle(timeout=0.1) is True

    _enqueue(coordinator, "mercurio", "cap-1")
    assert processor.started.acquire(timeout=TIMEOUT)

    assert coordinator.wait_until_idle(timeout=0.1) is False

    processor.release.release()

    assert coordinator.wait_until_idle(timeout=TIMEOUT) is True


def test_snapshot_exposes_safe_state_only():
    def processor(*, twin_key, trigger_capture_id):
        return {
            "status": "MATERIALIZED",
            "materialized_revision_id": "matrev-1",
            "capture_root": "C:/private/root",
            "human_navigation_candidate_store": object(),
            "transitions": [{"selector": "a[onclick=\"continuar('INI');\"]"}],
        }

    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    _enqueue(coordinator, "mercurio", "cap-1")
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    snapshot = coordinator.snapshot()

    assert set(snapshot) == {
        "schema_version",
        "pending_count",
        "running_count",
        "worker_alive",
        "last_result",
    }

    assert snapshot["last_result"] == {
        "status": "MATERIALIZED",
        "materialized_revision_id": "matrev-1",
        "twin_key": "mercurio",
        "trigger_capture_id": "cap-1",
    }

    serialized = json.dumps(snapshot)
    assert "private" not in serialized
    assert "continuar" not in serialized


@pytest.mark.parametrize(
    "twin_key, capture_id",
    [
        ("", "cap-1"),
        ("mercurio", ""),
        ("mercurio", None),
        ("../x", "cap-1"),
        ("mercurio", "a/b"),
    ],
)
def test_invalid_jobs_are_rejected_and_never_queued(twin_key, capture_id):
    processor = _Processor()
    coordinator = AutoTwinMaterializationCoordinator(processor=processor)

    with pytest.raises(ValueError):
        _enqueue(coordinator, twin_key, capture_id)

    assert coordinator.snapshot()["pending_count"] == 0
    assert processor.calls == []
