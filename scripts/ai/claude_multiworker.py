"""Governed Claude Runner V2A: exactly-two-worker multiworker coordinator.

RUNNER-V2A-MULTIWORKER-CORE adds a separate, additive coordinator on top of
the durable V1.5/V1.5.1 single-worker queue (`scripts/ai/claude_queue.py`),
capable of executing up to exactly two independently queued Work Orders
concurrently, while reusing every existing V1.5 governance primitive
unchanged: `QueueLock`, the QUEUED->RUNNING attempt state machine
(`start_attempt`/`finalize_attempt`), checkpoint capture/reconciliation,
quota classification/global barrier, and the fail-closed recovery
primitives. This module never weakens, reimplements or bypasses any of
those contracts - it only adds a scheduling layer able to claim and run up
to two of them at once.

Why V1.5's own `run_next()`/`supervisor_once()` cannot simply be called
twice concurrently (the "existing V1.5 locking limitation"): V1.5's
`_run_next_locked()` deliberately holds ONE exclusive `QueueLock` across
selection, attempt creation, the full (potentially many-minutes) Claude
subprocess invocation, and finalization. That is correct and required for
single-worker durability, but it structurally serializes everything - a
second concurrent call simply blocks on the same lock for the entire
duration of the first Claude invocation, so no two Claude subprocesses can
ever overlap. V2A does not change that method or its lock-holds-through-
invocation contract; V1.5's public API and every V1.5 test keep behaving
exactly as before.

V2A per-job lifecycle:

    QUEUED
      -> ATOMIC CLAIM        (short-held QueueLock: barrier check, target-
                               exclusivity check, QUEUED->RUNNING transition
                               via the existing `start_attempt`, durable
                               claim-file write - all before any executor
                               call)
      -> RUNNING WITH LEASE   (a durable claim file under a sibling
                               metadata root, never a child of `queue_root`
                               itself - see `_multiworker_meta_root()` -
                               records worker_id, attempt_id, coordinator_run_id,
                               target_key, pid, hostname, claimed_at_utc,
                               heartbeat_at_utc, lease_seconds, status)
      -> EXECUTOR             (the claimed job's fresh `claude_runner.
                               WorkOrderRequest` is executed by exactly one
                               worker thread calling `claude_runner.
                               execute_work_order()` - a fresh, non-resumed
                               Claude CLI subprocess invocation, identical to
                               V1.5 - with NO lock held during this step)
      -> GOVERNED FINALIZATION (short-held QueueLock again: the exact same
                               result-mapping/checkpoint/quota primitives
                               V1.5's `_run_next_locked()` uses -
                               `_map_runner_result_to_queue_state`,
                               `capture_or_reuse_checkpoint`,
                               `finalize_attempt` - plus a claim-file update)

Lock model / ordering: there is exactly ONE lock type in this module - the
existing V1.5 `claude_queue.QueueLock` for the queue root - acquired and
released for two short, bounded critical sections per job cycle: CLAIM and
FINALIZE. It is NEVER held across a Claude subprocess invocation (that
always happens in a worker thread, lock-free, between one CLAIM and its
matching FINALIZE). There is deliberately no second, independent "target
lock" primitive to order against: target exclusivity is not a physical
lock at all, but a value *derived*, under that same single short-held
QueueLock, from already-durable item state - any item whose canonical
target currently has another item in RUNNING, BLOCKED_ON_CHECKPOINT or
WAITING_QUOTA excludes a new claim at that same target. Because there is
only one lock type and it is always acquired/released within one call
frame (never nested, never held while waiting on another lock or on a
subprocess), no lock-ordering deadlock is reachable by construction; the
"REQUIRED TESTS" in `scripts/tests/test_claude_multiworker.py` exercise
this directly (two distinct targets overlap; two items at the same target
never overlap; a claim-vs-claim race cannot double-claim one item).

Global barrier semantics are reused, generalized to multiple concurrent
in-flight jobs, from V1.5's `supervisor_once()`: a RUNNING item this
coordinator does not itself own (i.e. not one of its own in-flight claims)
is either a live/unverifiable foreign claim (OPERATOR_REQUIRED - safety
cannot be established, so no dispatch happens anywhere, though this
coordinator's OWN already in-flight jobs are still allowed to finish and
finalize normally) or a demonstrably dead foreign claim (safely recovered
via the exact same checkpoint-governed
`claude_queue.recover_single_running_item_locked()` V1.5 uses for orphan
recovery, RUNNER-V2A's only addition to claude_queue.py). Any
BLOCKED_ON_CHECKPOINT item anywhere is a global operator barrier
preventing new claims, exactly like V1.5. Any WAITING_QUOTA item is a
global provider-quota barrier preventing new claims everywhere (never per
target only), reusing V1.5's own trusted-reset-time/auto-resume primitives
verbatim under the same held lock.

Deliberately out of scope for V2A (see the Work Order's DELIBERATELY
DEFERRED section for the full list): more than two workers, dynamic
autoscaling, Git worktree creation/allocation, priority scheduling beyond
existing deterministic queue order, cross-item dependencies, distributed/
cross-machine workers, multiple Claude provider accounts, any automatic
Git mutation (commit/push/merge/rebase/reset/restore/clean/branch/worktree),
and in-process WAITING_QUOTA sleeping (V1.5's `run_supervisor_loop` can
sleep for a trusted, bounded quota delay; this coordinator instead returns
a `QUOTA_WAIT` outcome with `next_wake_utc` immediately and expects an
external caller/operator to re-invoke `supervise`, keeping this module's
own runtime bound simple and avoiding a second independent sleep policy).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import claude_queue as queue
    from scripts.ai import claude_runner
except ImportError:  # pragma: no cover - exercised only via direct-script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_queue as queue  # type: ignore[no-redef]
    import claude_runner  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_WORKERS = 2
MAX_ALLOWED_WORKERS = 2  # RUNNER-V2A hard ceiling: no third worker this generation.

# RUNNER-V2A-MULTIWORKER-CORE-FIX1: V1.5's `claude_queue.list_items()` fails
# closed on every published direct child directory of `queue_root` that is
# not a valid queue item (see claude_queue.py's own docstring/contract) -
# any V2A metadata living under `queue_root` itself is therefore
# indistinguishable from a corrupt queue item and previously broke
# `list_items()` with QueueError("MISSING_ITEM"). Claim metadata instead
# lives under a deterministic SIBLING of `queue_root` (never a descendant),
# so it is structurally invisible to `list_items()`'s iteration of
# `queue_root.iterdir()` and can never be mistaken for a queue item. The
# sibling name is derived from `queue_root.name` (not a fixed literal), so
# two distinct queue roots sharing one parent directory - which necessarily
# have distinct names - always get distinct, non-colliding metadata roots.
MULTIWORKER_META_SUFFIX = ".multiworker"
CLAIMS_DIRNAME = "claims"
CLAIM_SCHEMA_VERSION = 1

# RUNNER-V2B-FIX2: a second deterministic sibling of `queue_root`, same
# rationale as `MULTIWORKER_META_SUFFIX` above (structurally invisible to
# `claude_queue.list_items()`, collision-free between two queue roots
# sharing a parent), hosting every claimed job's Claude Runner execution
# evidence (`claude_runner.execute_work_order()`'s prompt/stdout/stderr/
# metadata/result.json). A real productive dual-target write-mode run
# exposed that `queue_root` being placed outside a target repository (the
# recommended deployment) did NOT, on its own, keep this coordinator's own
# Claude evidence out of that target repository's working tree too:
# `_build_work_order_request()` was never told a `run_root`, so
# `execute_work_order()`'s own target-local default silently applied
# regardless. `claude_queue.py`'s RUNNER-V2B-FIX0 governance-path exclusion
# already keeps that target-local evidence out of checkpoint CONTENT (a
# regression test proves this explicitly for this exact "external
# queue_root" topology too) - but it stays live Runner-owned churn inside
# every target repository this coordinator writes to, which checkpoint
# capture's own several sequential `git` subprocess calls must then
# needlessly race against. RUNNER-V2B-FIX2 removes the target repository
# from that picture entirely: every claimed job now gets an explicit
# `run_root` under this evidence sidecar, so V2 Claude evidence is never
# part of any target repository's own working tree at all.
MULTIWORKER_EVIDENCE_SUFFIX = ".evidence"

# Conservative defaults suitable for long (many-minutes) Claude executions:
# a lease only becomes even eligible for orphan reconsideration after this
# many seconds without a heartbeat, and heartbeats are cheap/atomic and
# infrequent relative to typical Claude CLI run durations.
DEFAULT_LEASE_SECONDS = 1800.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0

_TARGET_EXCLUSIVE_STATES = {
    queue.QueueState.RUNNING,
    queue.QueueState.BLOCKED_ON_CHECKPOINT,
    queue.QueueState.WAITING_QUOTA,
}


class MultiworkerError(Exception):
    """Raised for V2A coordinator validation/integrity failures with a
    known reason, mirroring `claude_queue.QueueError`."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


class MultiworkerOutcome(str, Enum):
    NO_WORK = "NO_WORK"
    PROGRESSED = "PROGRESSED"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
    QUOTA_WAIT = "QUOTA_WAIT"
    SAFETY_STOP = "SAFETY_STOP"
    RUNTIME_BUDGET_EXHAUSTED = "RUNTIME_BUDGET_EXHAUSTED"


class MultiworkerReason(str, Enum):
    NO_QUEUED_WORK = "NO_QUEUED_WORK"
    QUEUE_DRAINED_PROGRESSED = "QUEUE_DRAINED_PROGRESSED"
    CHECKPOINT_PENDING_RECONCILIATION = "CHECKPOINT_PENDING_RECONCILIATION"
    QUOTA_MANUAL_RESUME_REQUIRED = "QUOTA_MANUAL_RESUME_REQUIRED"
    QUOTA_BARRIER_NOT_DUE = "QUOTA_BARRIER_NOT_DUE"
    QUOTA_AUTO_RESUME_SAFETY_STOP = "QUOTA_AUTO_RESUME_SAFETY_STOP"
    LIVE_OR_UNVERIFIABLE_FOREIGN_CLAIM = "LIVE_OR_UNVERIFIABLE_FOREIGN_CLAIM"
    MAX_CYCLES_REACHED = "MAX_CYCLES_REACHED"
    MAX_RUNTIME_REACHED = "MAX_RUNTIME_REACHED"


# ---------------------------------------------------------------------------
# Canonical target identity (worktree/target exclusivity)
# ---------------------------------------------------------------------------

def canonical_target_key(repository_path) -> str:
    """Resolves `repository_path` to a stable, OS-normalized comparison key
    (case-insensitive/separator-insensitive on Windows via
    `os.path.normcase`), used only to GROUP already-durable queue items by
    target - never to construct a filesystem path itself, so this carries
    no path-traversal risk. Fails closed (`MultiworkerError`) for anything
    empty/unresolvable, matching "reject ambiguous or invalid target
    identities fail-closed"."""
    if not isinstance(repository_path, str) or not repository_path.strip():
        raise MultiworkerError(
            "INVALID_TARGET_IDENTITY", "repository_path must be a non-empty string"
        )
    try:
        resolved = Path(repository_path).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise MultiworkerError(
            "INVALID_TARGET_IDENTITY",
            f"cannot resolve repository_path {repository_path!r}: {exc}",
        )
    return os.path.normcase(str(resolved))


def _held_target_keys(items: list) -> set:
    held = set()
    for it in items:
        if queue.QueueState(it.state) not in _TARGET_EXCLUSIVE_STATES:
            continue
        try:
            held.add(canonical_target_key(it.repository_path))
        except MultiworkerError:
            continue
    return held


# ---------------------------------------------------------------------------
# Durable per-item worker claim (lease) records
# ---------------------------------------------------------------------------

def _multiworker_meta_root(queue_root: Path) -> Path:
    """Deterministic sibling of `queue_root` (same parent directory, never a
    descendant): `<parent>/<queue_root.name>.multiworker`. Deterministic
    across coordinator restarts (pure function of `queue_root`'s own path),
    collision-free between two distinct queue roots sharing a parent
    (their names differ, so their derived siblings differ too), and safe on
    Windows/Git-Bash (`.multiworker` is a plain ASCII suffix, no reserved
    characters, no trailing dot/space on the resulting directory name)."""
    queue_root = Path(queue_root)
    return queue_root.parent / f"{queue_root.name}{MULTIWORKER_META_SUFFIX}"


def _claims_dir(queue_root: Path) -> Path:
    return _multiworker_meta_root(queue_root) / CLAIMS_DIRNAME


def _multiworker_evidence_root(queue_root: Path) -> Path:
    """Deterministic sibling of `queue_root` (never a descendant): `<parent>/
    <queue_root.name>.evidence`. See `MULTIWORKER_EVIDENCE_SUFFIX` above."""
    queue_root = Path(queue_root)
    return queue_root.parent / f"{queue_root.name}{MULTIWORKER_EVIDENCE_SUFFIX}"


def _evidence_run_root(queue_root: Path, item_id: str) -> str:
    """One durable evidence sub-root per queue item (never per-attempt -
    `claude_runner.create_run_dir()` already disambiguates individual
    attempts within it via its own timestamp+uuid run-directory naming), so
    every attempt of the same item stays correlated under one directory for
    audit while two DIFFERENT items - even concurrently claimed, even for
    the same target repository - can never collide."""
    return str(_multiworker_evidence_root(queue_root) / item_id)


def _claim_path(queue_root: Path, item_id: str) -> Path:
    # item_id is only ever an already-validated QueueItem.item_id (safe
    # single path segment, enforced by claude_queue._validate_item_id at
    # enqueue/load time) - never raw operator/external input here.
    return _claims_dir(queue_root) / f"{item_id}.json"


def _write_claim(queue_root: Path, item_id: str, payload: dict) -> None:
    queue._atomic_write_json(_claim_path(queue_root, item_id), payload)


def _load_claim(queue_root: Path, item_id: str) -> Optional[dict]:
    path = _claim_path(queue_root, item_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _build_claim_payload(job: "_ClaimedJob", coordinator_run_id: str, hostname: str, pid: int, lease_seconds: float) -> dict:
    now_iso = queue._now_iso()
    return {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "item_id": job.item_id,
        "attempt_id": job.attempt_id,
        "worker_id": job.worker_id,
        "coordinator_run_id": coordinator_run_id,
        "target_key": job.target_key,
        "provider": job.request.provider or "claude",
        "repository_path": job.request.repo,
        "pid": pid,
        "hostname": hostname,
        "claimed_at_utc": now_iso,
        "heartbeat_at_utc": now_iso,
        "lease_seconds": lease_seconds,
        "status": "ACTIVE",
        "finalized_at_utc": None,
        "final_queue_state": None,
    }


def _mark_claim_orphan_recovered(queue_root: Path, item_id: str, claim: Optional[dict]) -> None:
    if not isinstance(claim, dict):
        return
    updated = dict(claim)
    updated["status"] = "ORPHAN_RECOVERED"
    updated["finalized_at_utc"] = queue._now_iso()
    try:
        _write_claim(queue_root, item_id, updated)
    except OSError:
        pass


def _finalize_claim_record(queue_root: Path, job: "_ClaimedJob", final_state: str) -> None:
    claim = _load_claim(queue_root, job.item_id)
    if not isinstance(claim, dict):
        claim = {"item_id": job.item_id, "attempt_id": job.attempt_id}
    claim = dict(claim)
    claim["status"] = "FINALIZED"
    claim["finalized_at_utc"] = queue._now_iso()
    claim["final_queue_state"] = final_state
    try:
        _write_claim(queue_root, job.item_id, claim)
    except OSError:
        pass


class _HeartbeatThread(threading.Thread):
    """Best-effort, cheap, atomic periodic heartbeat for one active claim.
    Never blocks CLAIM/FINALIZE and is never itself consulted as
    authoritative proof of life - only PID/hostname liveness
    (`_pid_alive`) is ever treated as proof a claim owner is gone; the
    heartbeat only bounds how soon a genuinely dead owner's claim even
    becomes ELIGIBLE for that liveness check (`_is_lease_stale`)."""

    def __init__(self, queue_root: Path, item_id: str, base_claim: dict, interval_seconds: float):
        super().__init__(daemon=True)
        self._queue_root = queue_root
        self._item_id = item_id
        self._base_claim = base_claim
        self._interval = interval_seconds
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            claim = dict(self._base_claim)
            claim["heartbeat_at_utc"] = queue._now_iso()
            try:
                _write_claim(self._queue_root, self._item_id, claim)
            except OSError:
                pass

    def stop(self) -> None:
        self._stop_event.set()


# ---------------------------------------------------------------------------
# PID/host liveness (crash detection)
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> Optional[bool]:
    """Best-effort, local-only liveness check. Returns True (alive), False
    (demonstrably not running), or None (inconclusive - callers must treat
    this exactly like True: never sufficient grounds for recovery)."""
    if platform.system() == "Windows":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_INVALID_PARAMETER = 87
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        err = ctypes.get_last_error()
        if err == ERROR_INVALID_PARAMETER:
            return False
        if err == ERROR_ACCESS_DENIED:
            return True
        return None
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None
        return True


def _is_lease_stale(heartbeat_raw, lease_seconds, now: datetime) -> Optional[bool]:
    if not isinstance(heartbeat_raw, str) or not heartbeat_raw:
        return None
    try:
        heartbeat = datetime.fromisoformat(heartbeat_raw)
    except ValueError:
        return None
    if heartbeat.tzinfo is None or heartbeat.utcoffset() is None:
        return None
    heartbeat = heartbeat.astimezone(timezone.utc)
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) or lease_seconds <= 0:
        return None
    return now >= heartbeat + timedelta(seconds=lease_seconds)


def _classify_foreign_claim(
    claim: Optional[dict], coordinator_run_id: str, current_hostname: str, now: datetime, pid_alive,
) -> str:
    """Returns one of SAME_COORDINATOR_RUN, DEAD_FOREIGN, ALIVE_FOREIGN,
    UNKNOWN. Only DEAD_FOREIGN is ever safe to auto-recover; every other
    outcome (including UNKNOWN) must block new dispatch fail-closed."""
    if not isinstance(claim, dict):
        return "UNKNOWN"
    if claim.get("coordinator_run_id") == coordinator_run_id:
        return "SAME_COORDINATOR_RUN"
    stale = _is_lease_stale(
        claim.get("heartbeat_at_utc") or claim.get("claimed_at_utc"), claim.get("lease_seconds"), now,
    )
    if stale is not True:
        return "UNKNOWN"
    claim_host = claim.get("hostname")
    claim_pid = claim.get("pid")
    if claim_host != current_hostname or isinstance(claim_pid, bool) or not isinstance(claim_pid, int):
        return "UNKNOWN"
    alive = pid_alive(claim_pid)
    if alive is False:
        return "DEAD_FOREIGN"
    if alive is True:
        return "ALIVE_FOREIGN"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Claim/dispatch cycle (short-held QueueLock)
# ---------------------------------------------------------------------------

@dataclass
class _ClaimedJob:
    slot_index: int
    item_id: str
    attempt_id: str
    worker_id: str
    target_key: str
    request: "claude_runner.WorkOrderRequest"


@dataclass
class _Barrier:
    outcome: str
    reason: str
    item_id: Optional[str] = None
    next_wake_utc: Optional[str] = None


@dataclass
class _ClaimCycleResult:
    claimed: list
    barrier: Optional[_Barrier]


def _dispatch_cycle_locked(
    queue_root: Path,
    *,
    lock: "queue.QueueLock",
    free_slot_indices: list,
    in_flight_item_ids: set,
    coordinator_run_id: str,
    hostname: str,
    lease_seconds: float,
    now: datetime,
    pid_alive,
) -> _ClaimCycleResult:
    """One short critical section: barrier evaluation (foreign-RUNNING
    liveness, BLOCKED_ON_CHECKPOINT, WAITING_QUOTA - in that order,
    mirroring `claude_queue.supervisor_once()`'s precedence) followed by
    at most `len(free_slot_indices)` atomic claims of distinct-target
    QUEUED items. Requires the caller's already-held `lock`; never
    acquires/releases one itself."""
    queue._require_held_lock(queue_root, lock)
    items = queue.list_items(queue_root)

    orphan_recovered_any = False
    for it in items:
        if queue.QueueState(it.state) != queue.QueueState.RUNNING:
            continue
        if it.item_id in in_flight_item_ids:
            continue
        claim = _load_claim(queue_root, it.item_id)
        status = _classify_foreign_claim(claim, coordinator_run_id, hostname, now, pid_alive)
        if status == "DEAD_FOREIGN":
            detail = (
                "multiworker orphan recovery: durable claim owner "
                f"(pid={claim.get('pid')} host={claim.get('hostname')} "
                f"coordinator_run_id={claim.get('coordinator_run_id')} "
                f"worker_id={claim.get('worker_id')}) is demonstrably not "
                "running on this host and its lease had expired; recovered "
                "fail-closed via the existing checkpoint-governed orphan path"
            )
            queue.recover_single_running_item_locked(queue_root, it, lock=lock, detail=detail)
            _mark_claim_orphan_recovered(queue_root, it.item_id, claim)
            orphan_recovered_any = True
            continue
        return _ClaimCycleResult(
            claimed=[],
            barrier=_Barrier(
                outcome=MultiworkerOutcome.OPERATOR_REQUIRED.value,
                reason=MultiworkerReason.LIVE_OR_UNVERIFIABLE_FOREIGN_CLAIM.value,
                item_id=it.item_id,
            ),
        )

    if orphan_recovered_any:
        items = queue.list_items(queue_root)

    blocked = [it for it in items if queue.QueueState(it.state) == queue.QueueState.BLOCKED_ON_CHECKPOINT]
    if blocked:
        return _ClaimCycleResult(
            claimed=[],
            barrier=_Barrier(
                outcome=MultiworkerOutcome.OPERATOR_REQUIRED.value,
                reason=MultiworkerReason.CHECKPOINT_PENDING_RECONCILIATION.value,
                item_id=blocked[0].item_id,
            ),
        )

    waiting_quota = [it for it in items if queue.QueueState(it.state) == queue.QueueState.WAITING_QUOTA]
    if waiting_quota:
        trusted = [(it, queue._parse_trusted_retry_not_before(it)) for it in waiting_quota]
        untrusted = [it for it, rnb in trusted if rnb is None]
        if untrusted:
            return _ClaimCycleResult(
                claimed=[],
                barrier=_Barrier(
                    outcome=MultiworkerOutcome.OPERATOR_REQUIRED.value,
                    reason=MultiworkerReason.QUOTA_MANUAL_RESUME_REQUIRED.value,
                    item_id=untrusted[0].item_id,
                ),
            )
        latest_instant = max(rnb for _, rnb in trusted)
        if any(now < rnb for _, rnb in trusted) or not free_slot_indices:
            return _ClaimCycleResult(
                claimed=[],
                barrier=_Barrier(
                    outcome=MultiworkerOutcome.QUOTA_WAIT.value,
                    reason=MultiworkerReason.QUOTA_BARRIER_NOT_DUE.value,
                    next_wake_utc=latest_instant.isoformat(),
                ),
            )
        chosen = waiting_quota[0]
        try:
            queue._auto_resume_one_waiting_quota_item_locked(
                queue_root, chosen.item_id, lock=lock, now_utc=now,
            )
        except queue.QueueError as exc:
            return _ClaimCycleResult(
                claimed=[],
                barrier=_Barrier(
                    outcome=MultiworkerOutcome.SAFETY_STOP.value,
                    reason=f"{MultiworkerReason.QUOTA_AUTO_RESUME_SAFETY_STOP.value}:{exc.reason}",
                    item_id=chosen.item_id,
                ),
            )
        items = queue.list_items(queue_root)

    held_targets = _held_target_keys(items)
    queued = [it for it in items if queue.QueueState(it.state) == queue.QueueState.QUEUED]

    claimed: list = []
    remaining_slots = list(free_slot_indices)
    pid = os.getpid()
    for it in queued:
        if not remaining_slots:
            break
        try:
            target_key = canonical_target_key(it.repository_path)
        except MultiworkerError:
            continue
        if target_key in held_targets:
            continue

        slot_index = remaining_slots.pop(0)
        attempt_id = queue.generate_attempt_id()
        attempt = queue.QueueAttempt(
            attempt_id=attempt_id, started_at_utc=queue._now_iso(), ended_at_utc=None,
            status="RUNNING", runner_state=None, runner_exit_code=None,
            runner_run_id=None, runner_evidence_dir=None, final_queue_state=None,
        )
        updated_item = queue.start_attempt(queue_root, it.item_id, attempt)
        worker_id = f"{coordinator_run_id}:w{slot_index}"
        # RUNNER-V2B-FIX2: an explicit, coordinator-owned, externalized
        # run_root - never the Runner's own target-local default - so this
        # job's Claude evidence is never part of the target repository's
        # own working tree.
        request = queue._build_work_order_request(
            queue_root, updated_item, run_root=_evidence_run_root(queue_root, it.item_id),
        )
        job = _ClaimedJob(
            slot_index=slot_index, item_id=it.item_id, attempt_id=attempt_id,
            worker_id=worker_id, target_key=target_key, request=request,
        )
        claim_payload = _build_claim_payload(job, coordinator_run_id, hostname, pid, lease_seconds)
        _write_claim(queue_root, it.item_id, claim_payload)
        claimed.append(job)
        held_targets.add(target_key)

    return _ClaimCycleResult(claimed=claimed, barrier=None)


def _finalize_claimed_job_locked(
    queue_root: Path, job: _ClaimedJob, outcome_pair: tuple, *, lock: "queue.QueueLock", quota_classifier,
):
    """Finalizes one completed job under the caller's already-held `lock`,
    reusing the identical result-mapping/checkpoint/quota primitives
    `claude_queue._run_next_locked()` uses for its own single dispatch -
    never a reimplementation of that governance, only its orchestration
    split across CLAIM and FINALIZE instead of one inline call."""
    queue._require_held_lock(queue_root, lock)
    item = queue.load_item(queue_root, job.item_id)
    kind, payload = outcome_pair

    if kind == "EXCEPTION":
        exc = payload
        checkpoint_record = queue.capture_or_reuse_checkpoint(queue_root, item, attempt_id=job.attempt_id)
        item = queue.finalize_attempt(
            queue_root, job.item_id, job.attempt_id,
            to_state=queue.QueueState.BLOCKED_ON_CHECKPOINT,
            status="EXCEPTION",
            ended_at_utc=queue._now_iso(),
            runner_state=None, runner_exit_code=None, runner_run_id=None, runner_evidence_dir=None,
            detail=queue._with_checkpoint_note(
                f"executor raised {type(exc).__name__}: {exc}; execution outcome "
                "is uncertain, recovered fail-closed without an automatic retry",
                checkpoint_record,
            ),
            checkpoint_record=checkpoint_record,
        )
        _finalize_claim_record(queue_root, job, item.state)
        return item.state, None

    result = payload
    to_state, quota_record = queue._map_runner_result_to_queue_state(
        item, result, quota_classifier=quota_classifier, expected_run_root=job.request.run_root,
    )
    checkpoint_record = None
    detail = result.error_message
    if to_state == queue.QueueState.BLOCKED_ON_CHECKPOINT:
        checkpoint_record = queue.capture_or_reuse_checkpoint(queue_root, item, attempt_id=job.attempt_id)
        detail = queue._with_checkpoint_note(detail or "write-mode mutation detected", checkpoint_record)
    elif to_state == queue.QueueState.WAITING_QUOTA:
        detail = queue._with_quota_note(detail, quota_record)
    item = queue.finalize_attempt(
        queue_root, job.item_id, job.attempt_id,
        to_state=to_state, status="COMPLETED", ended_at_utc=queue._now_iso(),
        runner_state=result.state.value, runner_exit_code=result.exit_code,
        runner_run_id=result.run_id,
        runner_evidence_dir=str(result.evidence_dir) if result.evidence_dir else None,
        detail=detail, checkpoint_record=checkpoint_record, quota_record=quota_record,
    )
    _finalize_claim_record(queue_root, job, item.state)
    return item.state, result.state.value


def _run_job(job: _ClaimedJob, executor_fn) -> tuple:
    """Executed in a worker thread: exactly one fresh, non-resumed
    `claude_runner.execute_work_order()` call (or the injected fake
    executor in tests) per claimed job, with NO queue lock held."""
    try:
        result = executor_fn(job.request)
    except Exception as exc:  # noqa: BLE001 - an executor exception is an
        # expected, governed outcome (mirrors _run_next_locked); it is
        # finalized fail-closed, never re-raised into the coordinator loop.
        return job, ("EXCEPTION", exc)
    return job, ("RESULT", result)


# ---------------------------------------------------------------------------
# Coordinator result model
# ---------------------------------------------------------------------------

@dataclass
class DispatchRecord:
    item_id: str
    attempt_id: str
    worker_id: str
    queue_state: Optional[str]
    runner_state: Optional[str]
    provider: Optional[str] = None


@dataclass
class MultiworkerResult:
    outcome: str
    reason: str
    cycles: int = 0
    dispatched: list = field(default_factory=list)
    max_observed_concurrency: int = 0
    elapsed_seconds: float = 0.0
    next_wake_utc: Optional[str] = None
    blocking_item_id: Optional[str] = None


@dataclass
class _InFlight:
    job: _ClaimedJob
    heartbeat: Optional[_HeartbeatThread]


def _resolve_now(clock) -> datetime:
    if clock is None:
        return datetime.now(timezone.utc)
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise MultiworkerError("INVALID_CLOCK", "clock() must return a timezone-aware datetime")
    return now.astimezone(timezone.utc)


def _result_from_barrier(barrier: _Barrier, *, cycles, dispatched, max_observed_concurrency, elapsed_seconds) -> MultiworkerResult:
    return MultiworkerResult(
        outcome=barrier.outcome, reason=barrier.reason, cycles=cycles,
        dispatched=list(dispatched), max_observed_concurrency=max_observed_concurrency,
        elapsed_seconds=elapsed_seconds, next_wake_utc=barrier.next_wake_utc,
        blocking_item_id=barrier.item_id,
    )


# ---------------------------------------------------------------------------
# Coordinator main loop
# ---------------------------------------------------------------------------

def supervise_multiworker(
    queue_root: Path,
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    executor=None,
    quota_classifier=None,
    max_runtime_seconds: Optional[float] = None,
    max_cycles: Optional[int] = None,
    clock=None,
    monotonic_clock=None,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    heartbeat_interval_seconds: Optional[float] = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    pid_alive_fn=None,
    coordinator_run_id: Optional[str] = None,
    wait_for_lock: bool = False,
) -> MultiworkerResult:
    """Finite, governed V2A coordinator run over `queue_root`.

    Claims and runs up to `max_workers` (<=2) queued items concurrently,
    one fresh `claude_runner`-style executor invocation per attempt, never
    holding the queue lock across an invocation. Returns exactly one
    `MultiworkerResult` once the queue is drained, a global barrier stops
    all new dispatch (with nothing left in flight), or a configured
    `max_cycles`/`max_runtime_seconds` bound is reached (after draining
    every already-claimed job - a claim is never abandoned mid-flight).
    """
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise MultiworkerError("INVALID_MAX_WORKERS", "max_workers must be a positive integer")
    if max_workers > MAX_ALLOWED_WORKERS:
        raise MultiworkerError(
            "MAX_WORKERS_EXCEEDS_LIMIT",
            f"RUNNER-V2A supports at most {MAX_ALLOWED_WORKERS} concurrent "
            f"workers; got {max_workers}",
        )

    queue_root = Path(queue_root)
    executor_fn = executor or claude_runner.execute_work_order
    monotonic_fn = monotonic_clock or time.monotonic
    pid_alive = pid_alive_fn or _pid_alive
    run_id = coordinator_run_id or uuid.uuid4().hex
    hostname = socket.gethostname()

    max_cycles_v = queue._validate_positive_int(max_cycles, "max_cycles")
    max_runtime_v = queue._validate_positive_number(max_runtime_seconds, "max_runtime_seconds")

    start_monotonic = monotonic_fn()

    def elapsed() -> float:
        return monotonic_fn() - start_monotonic

    def remaining_budget() -> Optional[float]:
        if max_runtime_v is None:
            return None
        return max_runtime_v - elapsed()

    pool = ThreadPoolExecutor(max_workers=max_workers)
    futures: dict = {}
    dispatched: list = []
    max_observed_concurrency = 0
    cycles = 0

    try:
        while True:
            budget_exhausted = max_runtime_v is not None and remaining_budget() <= 0
            cycles_exhausted = max_cycles_v is not None and cycles >= max_cycles_v
            stop_new_dispatch = budget_exhausted or cycles_exhausted

            barrier: Optional[_Barrier] = None
            if not stop_new_dispatch:
                busy_indices = {inf.job.slot_index for inf in futures.values()}
                free_indices = sorted(set(range(max_workers)) - busy_indices)
                if free_indices:
                    cycles += 1
                    lock = queue.QueueLock(queue_root)
                    lock.acquire(blocking=wait_for_lock)
                    try:
                        claim_result = _dispatch_cycle_locked(
                            queue_root, lock=lock,
                            free_slot_indices=free_indices,
                            in_flight_item_ids={inf.job.item_id for inf in futures.values()},
                            coordinator_run_id=run_id, hostname=hostname,
                            lease_seconds=lease_seconds,
                            now=_resolve_now(clock), pid_alive=pid_alive,
                        )
                    finally:
                        lock.release()
                    barrier = claim_result.barrier
                    for job in claim_result.claimed:
                        heartbeat = None
                        if heartbeat_interval_seconds:
                            base_claim = _build_claim_payload(job, run_id, hostname, os.getpid(), lease_seconds)
                            heartbeat = _HeartbeatThread(
                                queue_root, job.item_id, base_claim, heartbeat_interval_seconds,
                            )
                            heartbeat.start()
                        future = pool.submit(_run_job, job, executor_fn)
                        futures[future] = _InFlight(job=job, heartbeat=heartbeat)
                    max_observed_concurrency = max(max_observed_concurrency, len(futures))

            if not futures:
                if barrier is not None:
                    return _result_from_barrier(
                        barrier, cycles=cycles, dispatched=dispatched,
                        max_observed_concurrency=max_observed_concurrency, elapsed_seconds=elapsed(),
                    )
                if stop_new_dispatch:
                    reason = (
                        MultiworkerReason.MAX_RUNTIME_REACHED.value if budget_exhausted
                        else MultiworkerReason.MAX_CYCLES_REACHED.value
                    )
                    return MultiworkerResult(
                        outcome=MultiworkerOutcome.RUNTIME_BUDGET_EXHAUSTED.value, reason=reason,
                        cycles=cycles, dispatched=list(dispatched),
                        max_observed_concurrency=max_observed_concurrency, elapsed_seconds=elapsed(),
                    )
                outcome = MultiworkerOutcome.PROGRESSED if dispatched else MultiworkerOutcome.NO_WORK
                reason = (
                    MultiworkerReason.QUEUE_DRAINED_PROGRESSED if dispatched
                    else MultiworkerReason.NO_QUEUED_WORK
                )
                return MultiworkerResult(
                    outcome=outcome.value, reason=reason.value, cycles=cycles,
                    dispatched=list(dispatched), max_observed_concurrency=max_observed_concurrency,
                    elapsed_seconds=elapsed(),
                )

            wait_timeout = None
            if not stop_new_dispatch and max_runtime_v is not None:
                rb = remaining_budget()
                wait_timeout = rb if rb > 0 else 0.0
            done, _pending = futures_wait(list(futures.keys()), timeout=wait_timeout, return_when=FIRST_COMPLETED)
            if not done:
                # Runtime budget elapsed while jobs were still in flight:
                # new dispatch is already suppressed above; keep draining
                # unboundedly here. This is safe/bounded in practice
                # because every in-flight attempt is itself bounded by its
                # own claude_runner subprocess timeout_seconds - a claim is
                # never abandoned with a dangling RUNNING item.
                done, _pending = futures_wait(list(futures.keys()), return_when=FIRST_COMPLETED)

            for future in done:
                in_flight = futures.pop(future)
                if in_flight.heartbeat is not None:
                    in_flight.heartbeat.stop()
                job, outcome_pair = future.result()
                lock = queue.QueueLock(queue_root)
                lock.acquire(blocking=wait_for_lock)
                try:
                    final_state, runner_state = _finalize_claimed_job_locked(
                        queue_root, job, outcome_pair, lock=lock, quota_classifier=quota_classifier,
                    )
                finally:
                    lock.release()
                dispatched.append(DispatchRecord(
                    item_id=job.item_id, attempt_id=job.attempt_id, worker_id=job.worker_id,
                    queue_state=final_state, runner_state=runner_state,
                    provider=job.request.provider,
                ))
    finally:
        for in_flight in futures.values():
            if in_flight.heartbeat is not None:
                in_flight.heartbeat.stop()
        pool.shutdown(wait=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_MULTIWORKER_EXIT_CODES = {
    MultiworkerOutcome.NO_WORK.value: 0,
    MultiworkerOutcome.PROGRESSED.value: 0,
    MultiworkerOutcome.RUNTIME_BUDGET_EXHAUSTED.value: 0,
    MultiworkerOutcome.QUOTA_WAIT.value: 2,
    MultiworkerOutcome.OPERATOR_REQUIRED.value: 3,
    MultiworkerOutcome.SAFETY_STOP.value: 5,
}


def _default_repo_path() -> str:
    return str(Path.cwd())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude_multiworker",
        description=(
            "Governed Claude Runner V2A: up to exactly two concurrent "
            "worker slots over the existing durable V1.5 queue. Never "
            "creates/removes worktrees, never commits/pushes/merges, "
            "never resumes a Claude session. A clearly separate module "
            "from claude_queue's single-worker `supervise`."
        ),
    )
    parser.add_argument(
        "--queue-root", default=None,
        help="Queue root directory (default: <repo>/runtime/claude_runner/queue).",
    )
    parser.add_argument(
        "--repo", default=None,
        help="Repository path associated with the queue root default (default: cwd).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="List all queue items with any active V2A claim.")

    supervise_p = subparsers.add_parser(
        "supervise",
        help=(
            "Finite V2A coordinator run: claims and runs up to --max-workers "
            "(<=2) queued items concurrently, one fresh Claude Runner "
            "invocation per attempt, draining before returning."
        ),
    )
    supervise_p.add_argument(
        "--max-workers", type=int, default=DEFAULT_MAX_WORKERS,
        help=f"Maximum concurrent worker slots (1-{MAX_ALLOWED_WORKERS}; default: %(default)s).",
    )
    supervise_p.add_argument("--max-cycles", type=int, default=None)
    supervise_p.add_argument("--max-runtime-seconds", type=float, default=None)
    supervise_p.add_argument(
        "--wait", action="store_true", help="Block on lock contention within each short critical section.",
    )
    return parser


def _resolve_queue_root_from_args(args: argparse.Namespace) -> Path:
    repo = Path(args.repo).resolve() if args.repo else Path(_default_repo_path()).resolve()
    return queue.resolve_queue_root(repo, args.queue_root)


def _cmd_status(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        items = queue.list_items(queue_root)
    except queue.QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    for item in items:
        claim = _load_claim(queue_root, item.item_id)
        worker_id = claim.get("worker_id") if isinstance(claim, dict) else None
        claim_status = claim.get("status") if isinstance(claim, dict) else None
        print(
            f"{item.item_id}\t{item.state}\t{item.created_at_utc}\t{item.repository_path}"
            f"\tworker_id={worker_id}\tclaim_status={claim_status}"
        )
    return 0


def _cmd_supervise(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        result = supervise_multiworker(
            queue_root, max_workers=args.max_workers, max_cycles=args.max_cycles,
            max_runtime_seconds=args.max_runtime_seconds, wait_for_lock=args.wait,
        )
    except MultiworkerError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    except queue.QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except queue.QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1

    fields = [
        f"outcome={result.outcome}", f"reason={result.reason}", f"cycles={result.cycles}",
        f"dispatched_count={len(result.dispatched)}",
        f"max_observed_concurrency={result.max_observed_concurrency}",
        f"elapsed_seconds={result.elapsed_seconds:.3f}",
    ]
    if result.next_wake_utc is not None:
        fields.append(f"next_wake_utc={result.next_wake_utc}")
    if result.blocking_item_id is not None:
        fields.append(f"blocking_item_id={result.blocking_item_id}")
    print(" ".join(fields))
    for rec in result.dispatched:
        print(
            f"dispatched item_id={rec.item_id} attempt_id={rec.attempt_id} "
            f"worker_id={rec.worker_id} provider={rec.provider or 'claude'} "
            f"queue_state={rec.queue_state} runner_state={rec.runner_state}"
        )
    return _MULTIWORKER_EXIT_CODES.get(result.outcome, 1)


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "supervise":
        if args.max_workers < 1 or args.max_workers > MAX_ALLOWED_WORKERS:
            print(
                f"error: MAX_WORKERS_EXCEEDS_LIMIT: --max-workers must be between 1 "
                f"and {MAX_ALLOWED_WORKERS} in RUNNER-V2A (got {args.max_workers})",
                file=sys.stderr,
            )
            return 1
        return _cmd_supervise(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
