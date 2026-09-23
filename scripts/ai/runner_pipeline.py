"""Runner V2 pipeline orchestrator: durable multiworker + multiprovider
"night shift" execution over declarative manifests.

Architecture (why this is a layer, not a second engine)
-------------------------------------------------------
The V1.5 queue (`claude_queue`) and the V2A coordinator (`claude_multiworker`)
are checkpoint-governed, single-provider-era contracts: a closed
`QueueState` machine without dependency/retry states, a global quota barrier
and a hard two-worker ceiling. They are left byte-compatible (this work only
adds the persisted `provider`/`required_capabilities` item fields and passes
them through to the Runner). The pipeline layer sits ABOVE the provider-
neutral execution core and reuses, unchanged:

* `claude_runner.execute_work_order` - the single governed execution path
  (provider resolution, preflight, worktree binding, write guards, evidence);
* `claude_queue.QueueLock` - the OS advisory lock (released by the kernel on
  process death, so "the lock is acquirable" IS proof its previous owner is
  dead) for both the pipeline lock and the per-worktree write lease;
* `claude_queue._atomic_write_json` - atomic durable writes;
* `runner_providers` - registry, capability model, transient classification.

The core never branches on a provider id: provider-specific knowledge lives
in adapters (`Provider.probe/capabilities/is_transient_failure`).

Durable layout (per pipeline, under `<state_root>/<pipeline_id>/`)::

    pipeline.json          manifest snapshot, run settings, status, deadline
    pipeline_result.json   machine-readable aggregate (rewritten on every save)
    lock/                  pipeline OS lock + identity (one orchestrator only)
    workers/<id>/worker.json      spec + state + attempt history (main thread only)
    workers/<id>/heartbeat.json   liveness, written by a heartbeat thread
    workers/<id>/preflight.json   provider/capability preflight for this worker
    workers/<id>/result.json      final per-worker result
    workers/<id>/evidence/        Runner evidence (stdout/stderr/metadata/...)

Worker states: QUEUED, WAITING_DEPENDENCY, READY, RUNNING, RETRY_WAIT,
WAITING_PROVIDER_QUOTA, BLOCKED_PROVIDER_AUTH,
SUCCESS, PARTIAL, BLOCKED, FAILED, CANCELLED, INTERRUPTED. SUCCESS/PARTIAL/
BLOCKED/FAILED/CANCELLED are terminal. INTERRUPTED (a worker that was RUNNING
when its orchestrator died) is a governed recoverable state: it is never
re-executed automatically, because a WRITE worker may have partially mutated
its worktree; the operator re-queues it explicitly (`--requeue-interrupted`
or `--rerun <id>`), and the Runner's own dirty-tree guard still applies.

Work-product preservation + governed resume (Runner V2.1 R21-B): each
attempt is tagged with `pipeline_id`/`worker_id`/`attempt` (provenance only,
never a safety input) so a write-mode attempt's `work_product.json` (written
by `claude_runner` next to its other evidence whenever it left authorized,
safety-clean changes behind, including an INTERRUPTED/quota-exhausted one)
can be traced back to exactly the attempt that produced it. This pipeline
never sets `WorkOrderRequest.resume_from` on its own re-queued attempts -
`--requeue-interrupted`/`--rerun <id>` still hits the SAME dirty-tree guard
as any other write-mode attempt (see module docstring above). Resuming into
that dirty tree is an operator decision made outside this orchestrator, by
invoking `claude_runner` directly with an explicit, validated
`--resume-from <worker>/evidence/.../work_product.json`.

Deliberate limits: no hard-stop kill (`execute_work_order` exposes no
cancellation handle; forcing it would risk orphaned provider processes), no
git mutation, no worktree creation, no provider installation.

Evidence finalization vs. work result (Runner V2.1 R21-A): a provider's WORK
result (`WorkOrderResult.state`/`work_status`) and the completeness of its
persisted evidence artifacts (`WorkOrderResult.evidence_complete`/
`evidence_error`) are independent axes. A provider that completed
successfully but whose evidence could not be fully persisted (e.g. a missing
`git_before.txt`, per the disk/permission/race classes `claude_runner` now
absorbs instead of raising) is never reported as FAILED: it lands on PARTIAL
with `state_reason="EVIDENCE_FINALIZATION_FAILED"`, and the attempt record
still carries the provider's actual `work_status` (e.g. "SUCCESS").
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

try:
    from scripts.ai import claude_multiworker as mw
    from scripts.ai import claude_queue as queue
    from scripts.ai import claude_runner
    from scripts.ai import runner_process_supervision as supervision
    from scripts.ai import runner_provider_availability as availability
    from scripts.ai import runner_providers as providers
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_multiworker as mw  # type: ignore[no-redef]
    import claude_queue as queue  # type: ignore[no-redef]
    import claude_runner  # type: ignore[no-redef]
    import runner_process_supervision as supervision  # type: ignore[no-redef]
    import runner_provider_availability as availability  # type: ignore[no-redef]
    import runner_providers as providers  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Constants / enums
# ---------------------------------------------------------------------------

PIPELINE_SCHEMA_VERSION = 1
MAX_PIPELINE_WORKERS = 16
DEFAULT_MAX_WORKERS = 2
DEFAULT_LEASE_SECONDS = 1800.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_LEASE_WAIT_SECONDS = 600.0
MAX_BACKOFF_SECONDS = 3600.0
# Provider quota waiting. A derived reset time gets a small margin so the first
# post-reset probe does not land on the boundary; with no usable reset hint the
# worker is probed at exponentially growing, bounded intervals (never a tight
# loop). Waiting is bounded only by the pipeline deadline/shutdown, never by
# the work attempt budget.
QUOTA_RESET_MARGIN_SECONDS = 60.0
QUOTA_PROBE_BASE_SECONDS = 300.0
QUOTA_PROBE_MAX_SECONDS = 3600.0
# A reset hint further away than this is not trusted (bad clock/parse): probe instead.
QUOTA_MAX_HINT_HORIZON_SECONDS = 36 * 3600.0
BUDGET_WORK = "WORK"
BUDGET_PROVIDER_AVAILABILITY = "PROVIDER_AVAILABILITY"
WRITE_LEASE_DIRNAME = "quesada_runner_write_lease"
STDERR_TAIL_CHARS = 4000
# Forced shutdown waits this long (per pass) for supervised providers to be
# terminated and confirmed dead: graceful phase + forced phase + margin.
DEFAULT_FORCED_TERMINATION_WAIT_SECONDS = (
    supervision.DEFAULT_GRACE_SECONDS + supervision.DEFAULT_FORCE_WAIT_SECONDS + 5.0
)
# Process-evidence statuses that prove the provider process is finished.
_PROCESS_FINISHED_STATUSES = frozenset({
    supervision.STATUS_EXITED, supervision.STATUS_TERMINATED, supervision.STATUS_LAUNCH_FAILED, "NOT_STARTED",
})


class WorkerState(str, Enum):
    QUEUED = "QUEUED"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    READY = "READY"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    # Provider quota/session exhausted: NOT a failure. Worktree/DAG preserved,
    # no execution slot or lease held, eligible again at provider recovery.
    WAITING_PROVIDER_QUOTA = "WAITING_PROVIDER_QUOTA"
    # Provider credentials rejected: recoverable only by an operator (like
    # INTERRUPTED, not terminal, never releases dependents, never retried).
    BLOCKED_PROVIDER_AUTH = "BLOCKED_PROVIDER_AUTH"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


TERMINAL_STATES = frozenset({
    WorkerState.SUCCESS, WorkerState.PARTIAL, WorkerState.BLOCKED,
    WorkerState.FAILED, WorkerState.CANCELLED,
})
_PENDING_STATES = frozenset({WorkerState.QUEUED, WorkerState.WAITING_DEPENDENCY, WorkerState.READY})

_W = WorkerState
_ALLOWED_TRANSITIONS = {
    _W.QUEUED: {_W.WAITING_DEPENDENCY, _W.READY, _W.BLOCKED, _W.CANCELLED},
    _W.WAITING_DEPENDENCY: {_W.READY, _W.CANCELLED, _W.BLOCKED},
    _W.READY: {_W.RUNNING, _W.BLOCKED, _W.CANCELLED, _W.WAITING_DEPENDENCY},
    _W.RUNNING: {
        _W.SUCCESS, _W.PARTIAL, _W.BLOCKED, _W.FAILED, _W.RETRY_WAIT, _W.INTERRUPTED, _W.READY,
        _W.WAITING_PROVIDER_QUOTA, _W.BLOCKED_PROVIDER_AUTH,
    },
    _W.RETRY_WAIT: {_W.READY, _W.CANCELLED},
    _W.WAITING_PROVIDER_QUOTA: {_W.READY, _W.CANCELLED},
    _W.BLOCKED_PROVIDER_AUTH: {_W.CANCELLED},
    _W.INTERRUPTED: {_W.CANCELLED},
    _W.SUCCESS: set(), _W.PARTIAL: set(), _W.BLOCKED: set(), _W.FAILED: set(), _W.CANCELLED: set(),
}

DEPENDENCY_POLICIES = {
    "success": frozenset({_W.SUCCESS}),
    "success_or_partial": frozenset({_W.SUCCESS, _W.PARTIAL}),
    "completed": frozenset({_W.SUCCESS, _W.PARTIAL, _W.BLOCKED, _W.FAILED}),
}


class PipelineStatus(str, Enum):
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INCOMPLETE = "INCOMPLETE"


PIPELINE_EXIT_CODES = {
    PipelineStatus.SUCCESS.value: 0,
    PipelineStatus.BLOCKED.value: 6,
    PipelineStatus.PARTIAL.value: 7,
    PipelineStatus.FAILED.value: 8,
    PipelineStatus.CANCELLED.value: 9,
    PipelineStatus.INCOMPLETE.value: 30,
}
EXIT_MANIFEST_INVALID = 40
EXIT_PIPELINE_REFUSED = 41

# Runner states that, WITHOUT an evidence dir, mean the provider process never
# ran (nothing mutated), so an explicitly configured fallback is still safe.
_FALLBACK_TRIGGER_STATES = frozenset({
    claude_runner.RunState.PROVIDER_UNAVAILABLE.value,
    claude_runner.RunState.PROVIDER_UNKNOWN.value,
    claude_runner.RunState.CLAUDE_ERROR.value,
})

# Runner state -> normalized worker state + reason for non-success outcomes.
_RS = claude_runner.RunState
_BLOCKING_REFUSALS = frozenset({
    _RS.PROVIDER_UNAVAILABLE, _RS.PROVIDER_UNKNOWN, _RS.CAPABILITY_MISMATCH,
    _RS.WORKTREE_BINDING_FAILED, _RS.INVALID_REPOSITORY, _RS.INVALID_WORK_ORDER,
    _RS.WRITE_SCOPE_REQUIRED, _RS.WRITE_SCOPE_INVALID, _RS.BRANCH_GUARD_REFUSED,
    _RS.DIRTY_TREE_REFUSED, _RS.RESUME_REFUSED,
})


class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ManifestError(Exception):
    """Aggregated manifest validation failure; nothing has executed."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__("; ".join(f"{e['code']}: {e['message']}" for e in errors))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(raw) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_segment(value) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 64
        and all(c.isalnum() or c in "-_." for c in value)
        and value not in (".", "..") and not value.startswith(".")
    )


def _git(path: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_toplevel(path) -> Optional[Path]:
    path = Path(path)
    if not path.is_dir():
        return None
    top = _git(path, "rev-parse", "--show-toplevel")
    if not top:
        return None
    try:
        return Path(top).resolve()
    except OSError:
        return None


def default_self_worktree() -> Optional[Path]:
    """The worktree this orchestrator process's own source lives in."""
    return git_toplevel(Path(__file__).resolve().parent)


def _paths_overlap(a: Path, b: Path) -> bool:
    ka, kb = Path(os.path.normcase(str(a))), Path(os.path.normcase(str(b)))
    return ka == kb or ka in kb.parents or kb in ka.parents


def is_unsafe_self_target(worktree_top: Path, self_worktree: Optional[Path]) -> bool:
    """A WRITE worker must never target the worktree (or anything nested in /
    enclosing it) that the running orchestrator executes from."""
    return self_worktree is not None and _paths_overlap(Path(worktree_top), Path(self_worktree))


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class WorkerSpec:
    id: str
    worktree: str
    work_order: str
    provider: str = providers.DEFAULT_PROVIDER_ID
    model: Optional[str] = None
    mode: str = providers.MODE_READ_ONLY
    required_capabilities: list = field(default_factory=list)
    priority: int = 0
    depends_on: list = field(default_factory=list)
    dependency_policy: str = "success"
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    timeout_seconds: Optional[int] = None
    authorize_path: list = field(default_factory=list)
    fallback_providers: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # Derived by the parser (never taken from the manifest): the resolved git
    # toplevel of `worktree`, used for leases and self-hosting checks.
    worktree_top: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkerSpec":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Manifest:
    pipeline_id: str
    workers: list
    max_workers: Optional[int] = None
    provider_limits: dict = field(default_factory=dict)
    not_before_utc: Optional[str] = None
    deadline_utc: Optional[str] = None
    sha256: str = ""
    raw: dict = field(default_factory=dict)


_MANIFEST_KEYS = {"pipeline_id", "workers", "max_workers", "provider_limits", "not_before_utc", "deadline_utc"}
_WORKER_KEYS = {
    "id", "provider", "model", "worktree", "work_order", "mode", "required_capabilities", "priority",
    "depends_on", "dependencies", "dependency_policy", "max_attempts", "backoff_seconds",
    "timeout_seconds", "authorize_path", "fallback_providers", "metadata",
}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _find_cycle(graph: dict) -> Optional[list]:
    """Iterative DFS cycle finder; returns one cycle as a node list or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    for root in graph:
        if color[root] != WHITE:
            continue
        stack = [(root, iter(graph[root]))]
        path = [root]
        color[root] = GREY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if nxt not in graph:
                    continue
                if color[nxt] == GREY:
                    return path[path.index(nxt):] + [nxt]
                if color[nxt] == WHITE:
                    color[nxt] = GREY
                    path.append(nxt)
                    stack.append((nxt, iter(graph[nxt])))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return None


def parse_manifest(
    data, base_dir: Path, *, self_worktree: Optional[Path] = None, registered_providers: Optional[list] = None,
) -> Manifest:
    """Validates the WHOLE manifest and either returns a `Manifest` or raises
    `ManifestError` carrying every problem found. Pure validation: touches
    nothing, starts nothing."""
    errors: list = []

    def err(code: str, message: str, worker: Optional[str] = None) -> None:
        errors.append({"code": code, "worker": worker, "message": message})

    if not isinstance(data, dict):
        raise ManifestError([{"code": "MANIFEST_NOT_OBJECT", "worker": None, "message": "manifest must be a JSON object"}])
    for key in sorted(set(data) - _MANIFEST_KEYS):
        err("UNKNOWN_MANIFEST_KEY", f"unknown manifest key {key!r}")

    known = registered_providers if registered_providers is not None else providers.registered_provider_ids()
    pipeline_id = data.get("pipeline_id")
    if not _safe_segment(pipeline_id):
        err("INVALID_PIPELINE_ID", "pipeline_id must be a safe single path segment (letters, digits, '-', '_', '.')")

    raw_workers = data.get("workers")
    if not isinstance(raw_workers, list) or not raw_workers:
        err("NO_WORKERS", "workers must be a non-empty list")
        raw_workers = []

    max_workers = data.get("max_workers")
    if max_workers is not None and (not _is_int(max_workers) or not 1 <= max_workers <= MAX_PIPELINE_WORKERS):
        err("INVALID_MAX_WORKERS", f"max_workers must be an integer in 1..{MAX_PIPELINE_WORKERS}")

    provider_limits = data.get("provider_limits") or {}
    if not isinstance(provider_limits, dict):
        err("INVALID_PROVIDER_LIMITS", "provider_limits must be an object of provider id -> positive integer")
        provider_limits = {}
    for pid, limit in provider_limits.items():
        if pid not in known:
            err("INVALID_PROVIDER_LIMITS", f"provider_limits names unknown provider {pid!r}")
        if not _is_int(limit) or limit < 1:
            err("INVALID_PROVIDER_LIMITS", f"provider_limits[{pid!r}] must be a positive integer")

    for key in ("not_before_utc", "deadline_utc"):
        if data.get(key) is not None and _parse_iso(data[key]) is None:
            err("INVALID_TIME", f"{key} must be a timezone-aware ISO-8601 timestamp")

    specs: list = []
    seen: set = set()
    for index, raw in enumerate(raw_workers):
        wid = raw.get("id") if isinstance(raw, dict) else None
        label = wid if isinstance(wid, str) else f"#{index}"
        if not isinstance(raw, dict):
            err("INVALID_WORKER", "worker entry must be an object", label)
            continue
        for key in sorted(set(raw) - _WORKER_KEYS):
            err("UNKNOWN_WORKER_KEY", f"unknown worker key {key!r}", label)
        if not _safe_segment(wid):
            err("INVALID_WORKER_ID", "worker id must be a safe single path segment", label)
            continue
        if wid in seen:
            err("DUPLICATE_WORKER_ID", f"duplicate worker id {wid!r}", label)
            continue
        seen.add(wid)

        provider = raw.get("provider", providers.DEFAULT_PROVIDER_ID)
        provider = provider.strip().lower() if isinstance(provider, str) else provider
        if provider not in known:
            err("UNKNOWN_PROVIDER", f"unknown provider {provider!r}; registered: {', '.join(known)}", label)
        fallbacks = raw.get("fallback_providers") or []
        if not isinstance(fallbacks, list) or any(f not in known for f in fallbacks):
            err("INVALID_FALLBACK_PROVIDERS", f"fallback_providers must list registered providers ({', '.join(known)})", label)
            fallbacks = []

        try:
            mode = queue.normalize_execution_mode(raw.get("mode", providers.MODE_READ_ONLY))
        except queue.QueueError as exc:
            err("INVALID_MODE", exc.message, label)
            mode = providers.MODE_READ_ONLY

        worktree_raw = raw.get("worktree")
        top = None
        if not isinstance(worktree_raw, str) or not worktree_raw.strip():
            err("INVALID_WORKTREE", "worktree must be a non-empty path", label)
        else:
            wt = Path(worktree_raw)
            wt = wt if wt.is_absolute() else Path(base_dir) / wt
            top = git_toplevel(wt)
            if top is None:
                err("INVALID_WORKTREE", f"worktree is not an existing git worktree: {wt}", label)
            elif mode == providers.MODE_WRITE and is_unsafe_self_target(top, self_worktree):
                err(
                    "SELF_MODIFICATION_REFUSED",
                    f"WRITE worker targets the orchestrator's own worktree ({self_worktree}); "
                    "target a different worktree", label,
                )

        wo_raw = raw.get("work_order")
        wo_path = None
        if not isinstance(wo_raw, str) or not wo_raw.strip():
            err("INVALID_WORK_ORDER", "work_order must be a non-empty path", label)
        else:
            wo_path = Path(wo_raw)
            wo_path = wo_path if wo_path.is_absolute() else Path(base_dir) / wo_path
            try:
                claude_runner.validate_work_order(str(wo_path))
            except claude_runner.RunnerError as exc:
                err("INVALID_WORK_ORDER", exc.message, label)

        deps = raw.get("depends_on", raw.get("dependencies")) or []
        if "depends_on" in raw and "dependencies" in raw:
            err("AMBIGUOUS_DEPENDENCIES", "use only one of depends_on / dependencies", label)
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            err("INVALID_DEPENDENCIES", "depends_on must be a list of worker ids", label)
            deps = []
        policy = raw.get("dependency_policy", "success")
        if policy not in DEPENDENCY_POLICIES:
            err("INVALID_DEPENDENCY_POLICY", f"dependency_policy must be one of {sorted(DEPENDENCY_POLICIES)}", label)

        max_attempts = raw.get("max_attempts", 1)
        if not _is_int(max_attempts) or not 1 <= max_attempts <= 20:
            err("INVALID_MAX_ATTEMPTS", "max_attempts must be an integer in 1..20", label)
            max_attempts = 1
        backoff = raw.get("backoff_seconds", 0.0)
        if isinstance(backoff, bool) or not isinstance(backoff, (int, float)) or backoff < 0:
            err("INVALID_BACKOFF", "backoff_seconds must be a non-negative number", label)
            backoff = 0.0
        timeout = raw.get("timeout_seconds")
        if timeout is not None and (not _is_int(timeout) or timeout < 1):
            err("INVALID_TIMEOUT", "timeout_seconds must be a positive integer", label)
            timeout = None
        priority = raw.get("priority", 0)
        if not _is_int(priority):
            err("INVALID_PRIORITY", "priority must be an integer", label)
            priority = 0
        caps = raw.get("required_capabilities") or []
        if not isinstance(caps, list) or any(not isinstance(c, str) for c in caps):
            err("INVALID_CAPABILITIES", "required_capabilities must be a list of capability names", label)
            caps = []
        authorize = raw.get("authorize_path") or []
        if not isinstance(authorize, list) or any(not isinstance(a, str) for a in authorize):
            err("INVALID_AUTHORIZE_PATH", "authorize_path must be a list of strings", label)
            authorize = []
        metadata = raw.get("metadata") or {}
        if not isinstance(metadata, dict):
            err("INVALID_METADATA", "metadata must be an object", label)
            metadata = {}
        model = raw.get("model")
        if model is not None and not isinstance(model, str):
            err("INVALID_MODEL", "model must be a string", label)
            model = None

        specs.append(WorkerSpec(
            id=wid, worktree=str(worktree_raw), work_order=str(wo_path) if wo_path else str(wo_raw),
            provider=provider if isinstance(provider, str) else "", model=model, mode=mode,
            required_capabilities=list(caps), priority=priority, depends_on=list(deps),
            dependency_policy=policy if policy in DEPENDENCY_POLICIES else "success",
            max_attempts=max_attempts, backoff_seconds=float(backoff), timeout_seconds=timeout,
            authorize_path=list(authorize), fallback_providers=list(fallbacks), metadata=dict(metadata),
            worktree_top=str(top) if top else "",
        ))

    ids = {s.id for s in specs}
    for spec in specs:
        for dep in spec.depends_on:
            if dep == spec.id:
                err("SELF_DEPENDENCY", "worker depends on itself", spec.id)
            elif dep not in ids:
                err("UNKNOWN_DEPENDENCY", f"depends_on references unknown worker {dep!r}", spec.id)
    cycle = _find_cycle({s.id: [d for d in s.depends_on if d != s.id] for s in specs})
    if cycle:
        err("DEPENDENCY_CYCLE", "dependency cycle: " + " -> ".join(cycle))

    if errors:
        raise ManifestError(errors)

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return Manifest(
        pipeline_id=pipeline_id, workers=specs, max_workers=max_workers,
        provider_limits={k: int(v) for k, v in provider_limits.items()},
        not_before_utc=data.get("not_before_utc"), deadline_utc=data.get("deadline_utc"),
        sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(), raw=data,
    )


def load_manifest(path, *, self_worktree: Optional[Path] = None, registered_providers: Optional[list] = None) -> Manifest:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError([{"code": "MANIFEST_UNREADABLE", "worker": None, "message": str(exc)}])
    except json.JSONDecodeError as exc:
        raise ManifestError([{"code": "MANIFEST_MALFORMED_JSON", "worker": None, "message": str(exc)}])
    return parse_manifest(
        data, path.resolve().parent, self_worktree=self_worktree, registered_providers=registered_providers,
    )


# ---------------------------------------------------------------------------
# Leases (OS-lock based: kernel release on death = proof of a dead owner)
# ---------------------------------------------------------------------------

def assess_owner(owner: Optional[dict], now: datetime, hostname: str, pid_alive, lease_seconds: float) -> str:
    """Read-only liveness verdict for a recorded owner: ALIVE, STALE or
    UNVERIFIABLE. Only a dead PID on this host proves staleness; a fresh
    heartbeat keeps an owner ALIVE even when the PID probe is inconclusive
    (heartbeats are independent of provider output)."""
    if not isinstance(owner, dict):
        return "UNVERIFIABLE"
    if owner.get("hostname") != hostname:
        return "UNVERIFIABLE"
    pid = owner.get("pid")
    if not _is_int(pid):
        return "UNVERIFIABLE"
    alive = pid_alive(pid)
    if alive is False:
        return "STALE"
    if alive is True:
        return "ALIVE"
    heartbeat = _parse_iso(owner.get("last_heartbeat_utc") or owner.get("heartbeat_at_utc"))
    if heartbeat is not None and now < heartbeat + timedelta(seconds=lease_seconds):
        return "ALIVE"
    return "UNVERIFIABLE"


class DirLease:
    """Exclusive lease over a directory using the queue's OS advisory lock.
    The identity file (pipeline/worker/pid/host/started_at/worktree/heartbeat)
    is diagnostic: only the OS lock decides ownership. A previous owner's
    identity left behind by a crash is reported as `recovered_from` when the
    lock is (provably) free again."""

    IDENTITY = "lease.json"

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock: Optional["queue.QueueLock"] = None
        self.identity: dict = {}
        self.recovered_from: Optional[dict] = None

    @property
    def held(self) -> bool:
        return self._lock is not None

    def holder(self) -> Optional[dict]:
        try:
            data = json.loads((self.directory / self.IDENTITY).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def try_acquire(self, identity: dict) -> bool:
        lock = queue.QueueLock(self.directory)
        try:
            lock.acquire(blocking=False)
        except queue.QueueLockError:
            return False
        previous = self.holder()
        self.recovered_from = previous if previous and previous.get("pid") != os.getpid() else None
        self._lock = lock
        self.identity = dict(identity)
        self.identity["recovered_from"] = self.recovered_from
        self._write()
        return True

    def _write(self) -> None:
        queue._atomic_write_json(self.directory / self.IDENTITY, self.identity)

    def touch(self) -> None:
        if self._lock is None:
            return
        self.identity["last_heartbeat_utc"] = queue._now_iso()
        try:
            self._write()
        except OSError:
            pass

    def release(self) -> None:
        if self._lock is None:
            return
        try:
            (self.directory / self.IDENTITY).unlink()
        except OSError:
            pass
        self._lock.release()
        self._lock = None


def worktree_lease_dir(worktree_top: Path, lease_root: Optional[Path] = None) -> Path:
    """Lease directory shared by EVERY orchestrator process for this
    worktree: inside the worktree's own (per-worktree) git dir, so it is
    never part of the working tree/diff, survives across pipelines and is
    not tied to any state root."""
    if lease_root is not None:
        digest = hashlib.sha1(mw.canonical_target_key(str(worktree_top)).encode("utf-8")).hexdigest()[:20]
        return Path(lease_root) / digest
    git_dir = _git(Path(worktree_top), "rev-parse", "--absolute-git-dir")
    if not git_dir:
        raise PipelineError("LEASE_LOCATION_UNRESOLVED", f"cannot resolve git dir for {worktree_top}")
    return Path(git_dir) / WRITE_LEASE_DIRNAME


class _Heartbeat(threading.Thread):
    """Periodic liveness beat, independent of provider stdout activity."""

    def __init__(self, interval: float, beat: Callable[[], None]):
        super().__init__(daemon=True)
        self._interval = interval
        self._beat = beat
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                self._beat()
            except Exception:  # noqa: BLE001 - a failed beat must never kill a worker
                pass

    def stop(self) -> None:
        self._stop_event.set()


# ---------------------------------------------------------------------------
# Keep-awake (opt-in, Windows only; degrades cleanly elsewhere)
# ---------------------------------------------------------------------------

class KeepAwake:
    """Abstraction over a "prevent sleep" assertion. `acquire`/`release` are
    idempotent. SetThreadExecutionState is per-thread on Windows, so the
    orchestrator calls both from its own (scheduler) thread."""

    supported = False

    def __init__(self):
        self.active = False

    def acquire(self) -> None:
        if not self.active:
            self._apply(True)
            self.active = True

    def release(self) -> None:
        if self.active:
            self._apply(False)
            self.active = False

    def _apply(self, on: bool) -> None:  # pragma: no cover - overridden
        pass


class NullKeepAwake(KeepAwake):
    """Unsupported OS: accepts the request, changes nothing."""


class WindowsKeepAwake(KeepAwake):
    supported = True
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001

    def __init__(self, api=None):
        super().__init__()
        self._api = api  # injectable `SetThreadExecutionState`-like callable (tests)

    def _apply(self, on: bool) -> None:
        api = self._api
        if api is None:
            import ctypes

            api = ctypes.windll.kernel32.SetThreadExecutionState  # type: ignore[attr-defined]
        # ES_CONTINUOUS alone clears the assertion; it never touches the
        # user's power plan. Nothing persists beyond this thread/process.
        api(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED if on else self.ES_CONTINUOUS)


def default_keep_awake() -> KeepAwake:
    return WindowsKeepAwake() if platform.system() == "Windows" else NullKeepAwake()


# ---------------------------------------------------------------------------
# Runtime worker record
# ---------------------------------------------------------------------------

@dataclass
class WorkerRuntime:
    spec: WorkerSpec
    order: int
    state: str = WorkerState.QUEUED.value
    state_reason: Optional[str] = None
    active_provider: str = ""
    # True once a provider process may have started for this worker; from then
    # on the provider is fixed (no fallback) until the operator re-runs it.
    provider_locked: bool = False
    fallbacks_used: list = field(default_factory=list)
    attempts: list = field(default_factory=list)
    attempt_base: int = 0
    retry_not_before_utc: Optional[str] = None
    # Durable provider-availability wait (quota/auth): classification, reset
    # evidence, next eligibility and consecutive-hit count. Separate from the
    # work attempt budget; cleared once an attempt ends without a hold.
    provider_wait: Optional[dict] = None
    owner: Optional[dict] = None
    updated_at_utc: str = ""
    result_path: Optional[str] = None

    def __post_init__(self):
        if not self.active_provider:
            self.active_provider = self.spec.provider

    @property
    def worker_state(self) -> WorkerState:
        return WorkerState(self.state)

    @property
    def attempts_used(self) -> int:
        """Executed WORK attempts since the last operator (re)queue. Attempts
        that never reached a provider (fallback hops) and attempts that ended
        on provider availability (quota/auth) do not consume the budget: the
        provider being unavailable is not the implementation failing."""
        return sum(
            1 for a in self.attempts[self.attempt_base:]
            if a.get("executed") and a.get("budget_class", BUDGET_WORK) == BUDGET_WORK
        )

    @property
    def availability_attempts(self) -> int:
        return sum(
            1 for a in self.attempts[self.attempt_base:]
            if a.get("executed") and a.get("budget_class") == BUDGET_PROVIDER_AVAILABILITY
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": PIPELINE_SCHEMA_VERSION, "spec": self.spec.to_dict(), "order": self.order,
            "state": self.state, "state_reason": self.state_reason, "active_provider": self.active_provider,
            "provider_locked": self.provider_locked, "fallbacks_used": list(self.fallbacks_used),
            "attempts": self.attempts, "attempt_base": self.attempt_base,
            "retry_not_before_utc": self.retry_not_before_utc, "provider_wait": self.provider_wait,
            "work_attempts_used": self.attempts_used, "availability_attempts": self.availability_attempts,
            "owner": self.owner, "updated_at_utc": self.updated_at_utc, "result_path": self.result_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkerRuntime":
        return cls(
            spec=WorkerSpec.from_dict(data["spec"]), order=data.get("order", 0), state=data["state"],
            state_reason=data.get("state_reason"), active_provider=data.get("active_provider", ""),
            provider_locked=bool(data.get("provider_locked")), fallbacks_used=list(data.get("fallbacks_used") or []),
            attempts=list(data.get("attempts") or []), attempt_base=int(data.get("attempt_base") or 0),
            retry_not_before_utc=data.get("retry_not_before_utc"),
            provider_wait=data.get("provider_wait") if isinstance(data.get("provider_wait"), dict) else None,
            owner=data.get("owner"),
            updated_at_utc=data.get("updated_at_utc", ""), result_path=data.get("result_path"),
        )


@dataclass
class PipelineResult:
    pipeline_id: str
    status: str
    stop_reason: Optional[str]
    path: Path
    summary: dict

    @property
    def exit_code(self) -> int:
        return PIPELINE_EXIT_CODES.get(self.status, 1)


class _ForcedStop(Exception):
    pass


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class PipelineRunner:
    def __init__(
        self,
        manifest: Manifest,
        state_root,
        *,
        max_workers: Optional[int] = None,
        provider_limits: Optional[dict] = None,
        max_runtime_seconds: Optional[float] = None,
        executor: Optional[Callable] = None,
        provider_resolver: Optional[Callable] = None,
        clock: Optional[Callable] = None,
        sleep_fn: Optional[Callable] = None,
        keep_awake: Optional[KeepAwake] = None,
        self_worktree: Optional[Path] = None,
        lease_root: Optional[Path] = None,
        heartbeat_interval_seconds: Optional[float] = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        lease_wait_seconds: float = DEFAULT_LEASE_WAIT_SECONDS,
        pid_alive_fn: Optional[Callable] = None,
        group_probe_fn: Optional[Callable] = None,
        requeue_interrupted: bool = False,
        rerun: Optional[list] = None,
        forced_termination_wait_seconds: float = DEFAULT_FORCED_TERMINATION_WAIT_SECONDS,
        tz_lookup: Optional[Callable] = None,
    ):
        self.manifest = manifest
        # IANA zone resolver for provider reset hints (default: zoneinfo).
        self.tz_lookup = tz_lookup
        self.state_root = Path(state_root)
        self.dir = self.state_root / manifest.pipeline_id
        self.max_workers = max_workers or manifest.max_workers or DEFAULT_MAX_WORKERS
        if not 1 <= self.max_workers <= MAX_PIPELINE_WORKERS:
            raise PipelineError("INVALID_MAX_WORKERS", f"max_workers must be in 1..{MAX_PIPELINE_WORKERS}")
        self.provider_limits = {**manifest.provider_limits, **(provider_limits or {})}
        for pid, limit in self.provider_limits.items():
            if not _is_int(limit) or limit < 1:
                raise PipelineError("INVALID_PROVIDER_LIMIT", f"provider limit for {pid!r} must be a positive integer")
        self.max_runtime_seconds = max_runtime_seconds
        self.executor = executor or claude_runner.execute_work_order
        self.resolver = provider_resolver or providers.resolve_provider
        self._clock = clock
        self._shutdown = threading.Event()
        self._sleep = sleep_fn or (lambda seconds: self._shutdown.wait(seconds))
        self.keep_awake = keep_awake
        self.self_worktree = self_worktree if self_worktree is not None else default_self_worktree()
        self.lease_root = Path(lease_root) if lease_root else None
        self.heartbeat_interval = heartbeat_interval_seconds
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.lease_wait_seconds = lease_wait_seconds
        self.pid_alive = pid_alive_fn or mw._pid_alive
        self.group_probe = group_probe_fn or supervision.probe_posix_group
        self.requeue_interrupted = requeue_interrupted
        self.rerun = list(rerun or [])

        self.hostname = socket.gethostname()
        self.run_id = f"{os.getpid()}-{int(time.time() * 1000)}"
        self.workers: dict = {}
        self._futures: dict = {}
        self._leases: dict = {}
        # One ExecutionControl per running worker attempt (never shared).
        self._controls: dict = {}
        # Leases whose provider process could not be confirmed dead: they are
        # deliberately NOT released (the OS lock frees them when this
        # orchestrator exits), so no new WRITE execution can assume the
        # previous one is gone.
        self._unresolved_leases: dict = {}
        self.forced_termination_wait_seconds = forced_termination_wait_seconds
        self._heartbeats: dict = {}
        self._pipeline_lock = DirLease(self.dir / "lock")
        self._status = PipelineStatus.RUNNING.value
        self._stop_reason: Optional[str] = None
        self._draining = False
        self._deadline: Optional[datetime] = None
        self._started_at: Optional[datetime] = None
        self._ended_at: Optional[datetime] = None
        self._lease_blocked_since: Optional[datetime] = None
        self._pool: Optional[ThreadPoolExecutor] = None
        self.observed_max_concurrency = 0
        self._initialized = False

    # -- time / persistence -------------------------------------------------

    def _now(self) -> datetime:
        return mw._resolve_now(self._clock)

    def _worker_dir(self, wid: str) -> Path:
        return self.dir / "workers" / wid

    def _save_worker(self, rt: WorkerRuntime) -> None:
        rt.updated_at_utc = _iso(self._now())
        queue._atomic_write_json(self._worker_dir(rt.spec.id) / "worker.json", rt.to_dict())

    def _transition(self, rt: WorkerRuntime, new: WorkerState, reason: Optional[str] = None) -> None:
        if new not in _ALLOWED_TRANSITIONS[rt.worker_state]:
            raise PipelineError("ILLEGAL_WORKER_TRANSITION", f"{rt.spec.id}: {rt.state} -> {new.value}")
        rt.state = new.value
        rt.state_reason = reason
        self._save_worker(rt)
        self._save_pipeline()

    def _force_state(self, rt: WorkerRuntime, new: WorkerState, reason: Optional[str]) -> None:
        """Explicit operator re-queue / recovery path outside the automatic table."""
        rt.state = new.value
        rt.state_reason = reason
        self._save_worker(rt)

    def _save_pipeline(self) -> None:
        settings = {
            "max_workers": self.max_workers, "provider_limits": self.provider_limits,
            "max_runtime_seconds": self.max_runtime_seconds, "lease_seconds": self.lease_seconds,
        }
        payload = {
            "schema_version": PIPELINE_SCHEMA_VERSION, "pipeline_id": self.manifest.pipeline_id,
            "manifest_sha256": self.manifest.sha256, "manifest": self.manifest.raw, "settings": settings,
            "status": self._status, "stop_reason": self._stop_reason,
            "started_at_utc": _iso(self._started_at) if self._started_at else None,
            "deadline_utc": _iso(self._deadline) if self._deadline else None,
            "updated_at_utc": _iso(self._now()),
            "orchestrator": {"pid": os.getpid(), "hostname": self.hostname, "run_id": self.run_id},
        }
        queue._atomic_write_json(self.dir / "pipeline.json", payload)
        queue._atomic_write_json(self.dir / "pipeline_result.json", self.build_result())

    # -- aggregate ----------------------------------------------------------

    def _overall_status(self) -> str:
        states = [w.worker_state for w in self.workers.values()]
        if any(s not in TERMINAL_STATES for s in states):
            return PipelineStatus.INCOMPLETE.value
        if all(s == WorkerState.SUCCESS for s in states):
            return PipelineStatus.SUCCESS.value
        for sev, name in (
            (WorkerState.FAILED, PipelineStatus.FAILED), (WorkerState.BLOCKED, PipelineStatus.BLOCKED),
            (WorkerState.CANCELLED, PipelineStatus.CANCELLED), (WorkerState.PARTIAL, PipelineStatus.PARTIAL),
        ):
            if sev in states:
                return name.value
        return PipelineStatus.INCOMPLETE.value  # pragma: no cover

    def build_result(self) -> dict:
        counts = {s.value: 0 for s in WorkerState}
        breakdown: dict = {}
        workers = []
        for rt in sorted(self.workers.values(), key=lambda r: r.order):
            counts[rt.state] += 1
            slot = breakdown.setdefault(rt.active_provider, {"total": 0})
            slot["total"] += 1
            slot[rt.state] = slot.get(rt.state, 0) + 1
            workers.append({
                "id": rt.spec.id, "provider": rt.active_provider, "requested_provider": rt.spec.provider,
                "state": rt.state, "state_reason": rt.state_reason, "attempts": len(rt.attempts),
                "work_attempts_used": rt.attempts_used, "availability_attempts": rt.availability_attempts,
                "provider_condition": (rt.provider_wait or {}).get("condition"),
                "next_eligible_utc": (rt.provider_wait or {}).get("next_eligible_utc"),
                "result_path": rt.result_path,
                "worker_path": str(self._worker_dir(rt.spec.id) / "worker.json"),
            })
        started, ended = self._started_at, self._ended_at or (self._now() if self._started_at else None)
        overall = self._status if self._status in (PipelineStatus.RUNNING.value, PipelineStatus.DRAINING.value) \
            else self._overall_status()
        return {
            "schema_version": PIPELINE_SCHEMA_VERSION, "pipeline_id": self.manifest.pipeline_id,
            "status": overall, "stop_reason": self._stop_reason,
            "started_at_utc": _iso(started) if started else None,
            "ended_at_utc": _iso(self._ended_at) if self._ended_at else None,
            "duration_seconds": (ended - started).total_seconds() if started and ended else None,
            "workers_total": len(self.workers), "success": counts["SUCCESS"], "partial": counts["PARTIAL"],
            "blocked": counts["BLOCKED"], "failed": counts["FAILED"], "cancelled": counts["CANCELLED"],
            "interrupted": counts["INTERRUPTED"], "waiting_provider_quota": counts["WAITING_PROVIDER_QUOTA"],
            "blocked_provider_auth": counts["BLOCKED_PROVIDER_AUTH"], "state_counts": counts, "provider_breakdown": breakdown,
            "max_observed_concurrency": self.observed_max_concurrency, "workers": workers,
        }

    # -- lifecycle ----------------------------------------------------------

    def request_shutdown(self) -> None:
        """Graceful shutdown: stop scheduling, persist DRAINING, let active
        workers finish. Safe to call from any thread."""
        self._shutdown.set()

    def run(self) -> PipelineResult:
        self._check_state_root()
        self.dir.mkdir(parents=True, exist_ok=True)
        identity = {
            "pipeline_id": self.manifest.pipeline_id, "pid": os.getpid(), "hostname": self.hostname,
            "run_id": self.run_id, "started_at_utc": queue._now_iso(), "last_heartbeat_utc": queue._now_iso(),
        }
        if not self._pipeline_lock.try_acquire(identity):
            holder = self._pipeline_lock.holder() or {}
            raise PipelineError(
                "PIPELINE_LOCKED",
                f"pipeline {self.manifest.pipeline_id!r} is being run by another orchestrator "
                f"(pid={holder.get('pid')} host={holder.get('hostname')} "
                f"last_heartbeat={holder.get('last_heartbeat_utc')}); nothing was started",
            )
        forced = False
        try:
            self._started_at = self._now()
            self._init_state()
            self._initialized = True
            self._compute_deadline()
            if self.keep_awake is None:
                self.keep_awake = NullKeepAwake()
            self._pool = ThreadPoolExecutor(max_workers=self.max_workers)
            self._preflight_pending()
            self._status = PipelineStatus.RUNNING.value
            self._save_pipeline()
            self._wait_not_before()
            self._loop()
        except _ForcedStop:
            forced = True
        finally:
            self._finalize(forced)
        return PipelineResult(
            pipeline_id=self.manifest.pipeline_id, status=self._status, stop_reason=self._stop_reason,
            path=self.dir / "pipeline_result.json", summary=self.build_result(),
        )

    def _record_process(self, attempt: dict, control) -> None:
        """Compact, secret-free process summary on the attempt (the full
        record lives in `process_evidence_path`)."""
        process = control.process if control is not None else None
        if process is None:
            return
        ev = process.evidence
        attempt["process"] = {
            key: ev.get(key) for key in (
                "status", "containment_mode", "graceful_outcome", "forced_outcome", "exit_code",
                "confirmed_dead", "termination_reason",
            )
        }
        attempt["process"]["pid"] = (ev.get("identity") or {}).get("pid")

    def _terminate_active_executions(self) -> dict:
        """Second-interrupt path: ask every active supervised execution to
        terminate (its own worker thread runs the graceful -> forced
        sequence), wait a bounded time, then terminate directly whatever is
        still not confirmed. Only Runner-owned attempts are touched: each
        control references exactly one worker's process. Returns
        {worker_id: (resolved, detail)}."""
        controls = dict(self._controls)
        for control in controls.values():
            control.request_cancel("FORCED_SHUTDOWN")
        by_worker = {rt.spec.id: f for f, rt in self._futures.items()}

        def _pending() -> list:
            return [by_worker[w] for w, c in controls.items() if w in by_worker and c.needs_wait() and not by_worker[w].done()]

        try:
            futures_wait(_pending(), timeout=self.forced_termination_wait_seconds)
        except KeyboardInterrupt:
            pass  # a further interrupt: go straight to direct termination
        for wid, control in controls.items():
            if control.needs_wait():
                control.terminate_now("FORCED_SHUTDOWN")
        return {wid: control.resolution() for wid, control in controls.items()}

    def _finalize(self, forced: bool) -> None:
        resolutions: dict = {}
        if forced:
            resolutions = self._terminate_active_executions()
        for hb in self._heartbeats.values():
            hb.stop()
        if forced:
            for rt in self.workers.values():
                if rt.worker_state == WorkerState.RUNNING:
                    attempt = rt.attempts[-1]
                    attempt.update(status="INTERRUPTED", ended_at_utc=_iso(self._now()))
                    control = self._controls.pop(rt.spec.id, None)
                    resolved, detail = resolutions.get(rt.spec.id, (True, "NO_EXECUTION_CONTROL"))
                    self._record_process(attempt, control)
                    attempt["process_confirmed_stopped"] = resolved
                    attempt["process_termination_detail"] = detail
                    if not resolved:
                        attempt["process_termination_unresolved"] = True
                    self._force_state(rt, WorkerState.INTERRUPTED, "FORCED_SHUTDOWN")
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
            self._stop_reason = "FORCED_SHUTDOWN"
        elif self._pool is not None:
            self._pool.shutdown(wait=True)
        if self.keep_awake is not None:
            self.keep_awake.release()
        for wid, lease in list(self._leases.items()):
            # Forced: a lease is released only once its provider process is
            # confirmed gone; an unresolved one stays held (fail closed).
            if not forced or resolutions.get(wid, (True, ""))[0]:
                lease.release()
                self._leases.pop(wid, None)
        self._ended_at = self._now()
        if self._initialized:
            self._status = self._overall_status()
            if self._status == PipelineStatus.INCOMPLETE.value and self._stop_reason is None:
                held = {rt.worker_state for rt in self.workers.values()}
                if WorkerState.BLOCKED_PROVIDER_AUTH in held:
                    self._stop_reason = "PROVIDER_AUTH_BLOCKED"
                elif WorkerState.WAITING_PROVIDER_QUOTA in held:
                    self._stop_reason = "WAITING_PROVIDER_QUOTA"
                else:
                    self._stop_reason = "NO_PROGRESSABLE_WORK"
            self._save_pipeline()
        self._pipeline_lock.release()

    # -- state initialisation / recovery ------------------------------------

    def _init_state(self) -> None:
        state_file = self.dir / "pipeline.json"
        stored = None
        if state_file.exists():
            try:
                stored = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise PipelineError("PIPELINE_STATE_CORRUPT", f"cannot read {state_file}: {exc}")
            if stored.get("manifest_sha256") != self.manifest.sha256:
                raise PipelineError(
                    "MANIFEST_CHANGED",
                    "the manifest differs from the one this pipeline_id was started with; "
                    "use a new pipeline_id (or restore the original manifest) - nothing was started",
                )
        for order, spec in enumerate(self.manifest.workers):
            path = self._worker_dir(spec.id) / "worker.json"
            if path.exists():
                try:
                    rt = WorkerRuntime.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise PipelineError("WORKER_STATE_CORRUPT", f"cannot read {path}: {exc}")
                rt.spec, rt.order = spec, order
            else:
                rt = WorkerRuntime(spec=spec, order=order)
            self.workers[spec.id] = rt
        self._recover_running()
        self._apply_operator_requests()
        for rt in self.workers.values():
            self._save_worker(rt)

    def _recover_running(self) -> None:
        """Holding the pipeline OS lock proves the previous orchestrator is
        dead. Any worker it left RUNNING is therefore stale: it becomes
        INTERRUPTED (recoverable), never SUCCESS and never auto re-executed."""
        for rt in self.workers.values():
            if rt.worker_state != WorkerState.RUNNING:
                continue
            owner = rt.owner or {}
            if owner.get("hostname") not in (None, self.hostname):
                raise PipelineError(
                    "FOREIGN_HOST_RUNNING_WORKER",
                    f"worker {rt.spec.id!r} was running on host {owner.get('hostname')!r}; "
                    "liveness cannot be verified from this host - nothing was started",
                )
            if rt.attempts and rt.attempts[-1].get("status") == "RUNNING":
                rt.attempts[-1].update(status="INTERRUPTED", ended_at_utc=_iso(self._now()))
                rt.attempts[-1]["process_recovery"] = self._assess_process_evidence(rt.attempts[-1])
            self._force_state(rt, WorkerState.INTERRUPTED, "ORCHESTRATOR_DIED_WHILE_RUNNING")
            rt.owner = None
            self._save_worker(rt)

    def _assess_process_evidence(self, attempt: dict) -> dict:
        """Conservative reading of a dead orchestrator's process evidence.
        Nothing is ever killed here: after a restart a bare pid is not
        ownership evidence (pids are reused). The result only decides whether
        an operator re-run is safe.

        RESOLVED   - no provider process was recorded, it is recorded as
                     finished, or the provider AND its recorded containment
                     are demonstrably gone (a dead direct leader alone is
                     never enough: descendants may remain in its group).
        UNRESOLVED - a provider process may still be running (pid alive or
                     liveness inconclusive, launch intent without a pid, or
                     containment that cannot be shown empty)."""
        # Known uncertainty is never erased by missing evidence: an attempt
        # that explicitly recorded "process not confirmed stopped" or
        # "termination unresolved" can only become RESOLVED through evidence
        # that positively shows the process gone, never through its absence.
        known_unresolved = (
            attempt.get("process_termination_unresolved") is True
            or ("process_confirmed_stopped" in attempt and attempt.get("process_confirmed_stopped") is not True)
        )
        raw_path = attempt.get("process_evidence_path")
        if not raw_path:
            if known_unresolved:
                return {"resolution": "UNRESOLVED", "detail": "UNRESOLVED_FLAG_WITHOUT_PROCESS_EVIDENCE"}
            return {"resolution": "RESOLVED", "detail": "NO_PROCESS_EVIDENCE_PATH"}
        try:
            evidence = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            if known_unresolved:
                return {"resolution": "UNRESOLVED", "detail": "UNRESOLVED_MARKER_WITH_MISSING_PROCESS_EVIDENCE"}
            return {"resolution": "RESOLVED", "detail": "NO_PROCESS_EVIDENCE_WRITTEN"}
        except (OSError, ValueError) as exc:
            return {"resolution": "UNRESOLVED", "detail": f"PROCESS_EVIDENCE_UNREADABLE:{type(exc).__name__}"}
        if not isinstance(evidence, dict):
            return {"resolution": "UNRESOLVED", "detail": "PROCESS_EVIDENCE_MALFORMED"}
        status = evidence.get("status")
        identity = evidence.get("identity") or {}
        report = {
            "evidence_status": status, "pid": identity.get("pid"),
            "containment_mode": identity.get("containment_mode") or evidence.get("containment_mode"),
        }
        if status in _PROCESS_FINISHED_STATUSES and evidence.get("confirmed_dead"):
            return {**report, "resolution": "RESOLVED", "detail": "PROCESS_RECORDED_DEAD"}
        pid = identity.get("pid")
        if pid is None:
            return {**report, "resolution": "UNRESOLVED", "detail": "LAUNCH_INTENT_WITHOUT_PID"}
        alive = self.pid_alive(pid)
        report["pid_alive_at_recovery"] = alive
        if alive is not False:
            return {**report, "resolution": "UNRESOLVED", "detail": "PROVIDER_PID_MAY_STILL_BE_RUNNING"}
        # Direct leader death != containment death. Assessment only: nothing
        # is signalled from persisted numeric ids.
        contained_gone, detail = supervision.assess_recorded_containment(
            identity, pid_alive=self.pid_alive, group_probe=self.group_probe,
        )
        if not contained_gone:
            return {**report, "resolution": "UNRESOLVED", "detail": detail}
        return {**report, "resolution": "RESOLVED", "detail": detail}

    def _apply_operator_requests(self) -> None:
        wanted = list(self.rerun)
        if self.requeue_interrupted:
            wanted += [r.spec.id for r in self.workers.values() if r.worker_state == WorkerState.INTERRUPTED]
        for wid in wanted:
            rt = self.workers.get(wid)
            if rt is None:
                raise PipelineError("UNKNOWN_WORKER", f"cannot re-run unknown worker {wid!r}")
            if rt.worker_state in (WorkerState.SUCCESS, WorkerState.RUNNING):
                raise PipelineError("RERUN_REFUSED", f"worker {wid!r} is {rt.state}; only unfinished/failed workers can be re-run")
            # The latest EXECUTED attempt decides, whatever markers it carries:
            # an attempt flagged process_confirmed_stopped != True or
            # process_termination_unresolved may never have gotten a
            # process_recovery record, so that record cannot gate the requeue.
            latest = next((a for a in reversed(rt.attempts) if a.get("executed")), None)
            if latest is not None:
                recovery = latest.get("process_recovery") or {}
                if (
                    recovery.get("resolution") == "UNRESOLVED"
                    or latest.get("process_confirmed_stopped") is not True
                    or latest.get("process_termination_unresolved") is True
                ):
                    # Re-assess now: the process may have exited (or the
                    # operator resolved it) since the interruption was recorded.
                    recovery = latest["process_recovery"] = self._assess_process_evidence(latest)
                if recovery.get("resolution") == "UNRESOLVED":
                    raise PipelineError(
                        "PROVIDER_PROCESS_UNRESOLVED",
                        f"worker {wid!r}: a provider process from its latest executed attempt may still be running "
                        f"({recovery.get('detail')}, pid={recovery.get('pid')}); re-running could overlap a WRITE. "
                        "Stop that process yourself, then record its confirmed death in "
                        f"{latest.get('process_evidence_path')} (status TERMINATED, confirmed_dead=true); an attempt "
                        "never explicitly marked unresolved may instead have that file removed "
                        "- nothing was started",
                    )
            self._requeue(rt, "OPERATOR_REQUEUE")
            self._requeue_cancelled_dependents(wid)

    def _requeue(self, rt: WorkerRuntime, reason: str) -> None:
        rt.attempt_base = len(rt.attempts)
        rt.provider_locked = False
        rt.active_provider = rt.spec.provider
        rt.fallbacks_used = []
        rt.retry_not_before_utc = None
        rt.provider_wait = None
        rt.result_path = None
        self._force_state(rt, WorkerState.QUEUED, reason)

    def _requeue_cancelled_dependents(self, wid: str) -> None:
        changed = True
        targets = {wid}
        while changed:
            changed = False
            for rt in self.workers.values():
                if (
                    rt.spec.id not in targets and set(rt.spec.depends_on) & targets
                    and rt.worker_state == WorkerState.CANCELLED
                    and str(rt.state_reason or "").startswith("DEPENDENCY_UNSATISFIED")
                ):
                    self._requeue(rt, "OPERATOR_REQUEUE_DEPENDENT")
                    targets.add(rt.spec.id)
                    changed = True

    def _compute_deadline(self) -> None:
        candidates = []
        if self.max_runtime_seconds is not None:
            candidates.append(self._started_at + timedelta(seconds=self.max_runtime_seconds))
        manifest_deadline = _parse_iso(self.manifest.deadline_utc)
        if manifest_deadline is not None:
            candidates.append(manifest_deadline)
        self._deadline = min(candidates) if candidates else None

    def _check_state_root(self) -> None:
        """Runner evidence/state written inside a target worktree would look
        like repository mutation to the Runner's own safety guards."""
        here = Path(os.path.normcase(str(self.dir.resolve())))
        for spec in self.manifest.workers:
            top = Path(os.path.normcase(str(spec.worktree_top))) if spec.worktree_top else None
            if top is not None and (here == top or top in here.parents):
                raise PipelineError(
                    "STATE_ROOT_INSIDE_TARGET_WORKTREE",
                    f"state root {self.dir} lies inside worker {spec.id!r}'s worktree {spec.worktree_top}; "
                    "choose --state-root outside every target worktree",
                )

    # -- preflight / provider selection -------------------------------------

    def _candidate_report(self, rt: WorkerRuntime, provider_id: str) -> dict:
        mode = rt.spec.mode
        report = {"provider": provider_id, "verdict": "PASS", "reason": None}
        try:
            provider = self.resolver(provider_id)
        except providers.ProviderError as exc:
            return {**report, "verdict": "PROVIDER_UNKNOWN", "reason": exc.message}
        probe = provider.probe()
        report.update(provider_status=probe.label, provider_version=probe.version)
        if not probe.available:
            return {**report, "verdict": "PROVIDER_UNAVAILABLE", "reason": probe.reason or "provider unavailable"}
        policy = providers.ExecutionPolicy(mode=mode)
        needed = providers.required_capabilities(policy, tuple(rt.spec.required_capabilities))
        missing = sorted(providers._cap_name(c) for c in needed - provider.capabilities(policy))
        if missing:
            return {**report, "verdict": "CAPABILITY_MISMATCH", "missing_capabilities": missing,
                    "reason": f"provider {provider_id!r} cannot supply: {', '.join(missing)}"}
        return report

    def _preflight_pending(self) -> None:
        """Per-worker provider/capability preflight for every not-yet-started
        worker. A worker whose provider is unavailable is BLOCKED (or moved to
        an explicitly configured fallback that is available) without
        affecting any independent worker."""
        for rt in self.workers.values():
            if rt.worker_state not in _PENDING_STATES or rt.provider_locked:
                continue
            candidates = [rt.spec.provider] + [p for p in rt.spec.fallback_providers if p != rt.spec.provider]
            reports = [self._candidate_report(rt, pid) for pid in candidates]
            queue._atomic_write_json(self._worker_dir(rt.spec.id) / "preflight.json", {
                "worker_id": rt.spec.id, "mode": rt.spec.mode, "checked_at_utc": _iso(self._now()),
                "candidates": reports,
            })
            chosen = next((r for r in reports if r["verdict"] == "PASS"), None)
            if chosen is None:
                self._block(rt, reports[0]["verdict"], reports[0]["reason"])
                continue
            if chosen["provider"] != rt.active_provider:
                rt.fallbacks_used.append({
                    "from": rt.active_provider, "to": chosen["provider"], "at_utc": _iso(self._now()),
                    "reason": f"preflight: {reports[0]['verdict']}", "phase": "PRE_EXECUTION",
                })
                rt.active_provider = chosen["provider"]
                self._save_worker(rt)

    def _block(self, rt: WorkerRuntime, code: str, message: Optional[str]) -> None:
        self._transition(rt, WorkerState.BLOCKED, code)
        self._write_result(rt, {"outcome": "BLOCKED", "code": code, "message": message})

    def _write_result(self, rt: WorkerRuntime, extra: dict) -> None:
        last = rt.attempts[-1] if rt.attempts else {}
        evidence = last.get("evidence_dir")
        artifacts = []
        if evidence:
            for name in (
                "prompt.txt", "stdout.txt", "stderr.txt", "metadata.json", "preflight.json", "result.json",
                "work_product.json",
            ):
                if (Path(evidence) / name).exists():
                    artifacts.append(str(Path(evidence) / name))
        payload = {
            "worker_id": rt.spec.id, "pipeline_id": self.manifest.pipeline_id, "state": rt.state,
            "state_reason": rt.state_reason, "provider": rt.active_provider,
            "requested_provider": rt.spec.provider, "mode": rt.spec.mode, "worktree": rt.spec.worktree_top,
            "runner_state": last.get("runner_state"), "work_status": last.get("work_status"),
            "attempts": rt.attempts, "fallbacks_used": rt.fallbacks_used, "evidence_dir": evidence,
            "artifacts": artifacts, "preflight": str(self._worker_dir(rt.spec.id) / "preflight.json"),
            "metadata": rt.spec.metadata, "written_at_utc": _iso(self._now()), **extra,
        }
        path = self._worker_dir(rt.spec.id) / "result.json"
        queue._atomic_write_json(path, payload)
        rt.result_path = str(path)
        self._save_worker(rt)

    # -- scheduling ---------------------------------------------------------

    def _wait_not_before(self) -> None:
        not_before = _parse_iso(self.manifest.not_before_utc)
        while not_before is not None and self._now() < not_before and not self._shutdown.is_set():
            if self._deadline is not None and self._now() >= self._deadline:
                return
            self._sleep(min(self.poll_seconds, max((not_before - self._now()).total_seconds(), 0.0)))

    def _refresh(self, now: datetime) -> None:
        for rt in sorted(self.workers.values(), key=lambda r: r.order):
            state = rt.worker_state
            if state == WorkerState.RETRY_WAIT:
                due = _parse_iso(rt.retry_not_before_utc)
                if due is None or now >= due:
                    self._transition(rt, WorkerState.READY, "RETRY_DUE")
                continue
            if state == WorkerState.WAITING_PROVIDER_QUOTA:
                due = _parse_iso((rt.provider_wait or {}).get("next_eligible_utc"))
                if due is None or now >= due:
                    self._transition(rt, WorkerState.READY, "PROVIDER_QUOTA_ELIGIBLE")
                continue
            if state not in _PENDING_STATES:
                continue
            verdict, detail = self._dependency_verdict(rt)
            if verdict == "UNSATISFIABLE":
                self._transition(rt, WorkerState.CANCELLED, f"DEPENDENCY_UNSATISFIED:{detail}")
                self._write_result(rt, {"outcome": "CANCELLED", "code": "DEPENDENCY_UNSATISFIED", "message": detail})
            elif verdict == "WAITING" and state != WorkerState.WAITING_DEPENDENCY:
                self._transition(rt, WorkerState.WAITING_DEPENDENCY, detail)
            elif verdict == "SATISFIED" and state != WorkerState.READY:
                self._transition(rt, WorkerState.READY, None)

    def _dependency_verdict(self, rt: WorkerRuntime) -> tuple:
        accepted = DEPENDENCY_POLICIES[rt.spec.dependency_policy]
        waiting = []
        for dep in rt.spec.depends_on:
            dstate = self.workers[dep].worker_state
            if dstate == WorkerState.BLOCKED and self.workers[dep].state_reason == "PROVIDER_PROCESS_UNRESOLVED":
                # Whatever the policy: a worker whose provider process may
                # still be running never releases its dependents.
                return "UNSATISFIABLE", f"{dep}=BLOCKED:PROVIDER_PROCESS_UNRESOLVED"
            if dstate in accepted:
                continue
            if dstate in TERMINAL_STATES:
                return "UNSATISFIABLE", f"{dep}={dstate.value}"
            waiting.append(dep)
        if waiting:
            return "WAITING", "waiting for " + ",".join(waiting)
        return "SATISFIED", None

    def _running(self) -> list:
        return [rt for rt in self.workers.values() if rt.worker_state == WorkerState.RUNNING]

    def _same_worktree_conflict(self, rt: WorkerRuntime) -> bool:
        """In-process exclusion: a WRITE worker needs the worktree to itself;
        a READ worker only conflicts with a running WRITE worker there."""
        key = mw.canonical_target_key(rt.spec.worktree_top)
        for other in self._running():
            if mw.canonical_target_key(other.spec.worktree_top) != key:
                continue
            if rt.spec.mode == providers.MODE_WRITE or other.spec.mode == providers.MODE_WRITE:
                return True
        return False

    def _provider_start_held(self, provider_id: str, now: datetime) -> bool:
        """True while ANY worker of this provider is in a quota wait that has
        not yet reached its eligibility time, or is auth-blocked: starting
        another worker of the same provider would only hammer the same wall.
        Derived from durable worker state, so it survives a restart. Other
        providers are never affected."""
        for other in self.workers.values():
            if other.active_provider != provider_id:
                continue
            if other.worker_state == WorkerState.BLOCKED_PROVIDER_AUTH:
                return True
            if other.worker_state == WorkerState.WAITING_PROVIDER_QUOTA:
                due = _parse_iso((other.provider_wait or {}).get("next_eligible_utc"))
                if due is not None and now < due:
                    return True
        return False

    def _start_ready(self, now: datetime) -> bool:
        ready = sorted(
            (rt for rt in self.workers.values() if rt.worker_state == WorkerState.READY),
            key=lambda r: (-r.spec.priority, r.order),
        )
        lease_blocked = False
        changed = False
        for rt in ready:
            if len(self._futures) >= self.max_workers:
                break
            recent = [a for a in rt.attempts[rt.attempt_base:] if a.get("executed")]
            if recent and recent[-1].get("process_confirmed_stopped") is not True:
                # Never start another attempt until the previous provider
                # process is confirmed stopped (a crashed one is INTERRUPTED
                # and needs an explicit operator re-queue instead).
                continue
            if self._provider_start_held(rt.active_provider, now):
                continue
            limit = self.provider_limits.get(rt.active_provider)
            if limit and sum(1 for r in self._running() if r.active_provider == rt.active_provider) >= limit:
                continue
            if self._same_worktree_conflict(rt):
                continue
            if rt.spec.mode == providers.MODE_WRITE and is_unsafe_self_target(Path(rt.spec.worktree_top), self.self_worktree):
                self._block(rt, "SELF_MODIFICATION_REFUSED", "WRITE worker targets the orchestrator's own worktree")
                changed = True
                continue
            lease = None
            if rt.spec.mode == providers.MODE_WRITE:
                lease = DirLease(worktree_lease_dir(Path(rt.spec.worktree_top), self.lease_root))
                if not lease.try_acquire({
                    "pipeline_id": self.manifest.pipeline_id, "worker_id": rt.spec.id, "pid": os.getpid(),
                    "hostname": self.hostname, "started_at_utc": queue._now_iso(),
                    "last_heartbeat_utc": queue._now_iso(), "worktree": rt.spec.worktree_top,
                }):
                    lease_blocked = True
                    continue
            self._launch(rt, lease, now)
            changed = True
        if lease_blocked and not self._futures:
            self._lease_blocked_since = self._lease_blocked_since or now
        elif not lease_blocked:
            self._lease_blocked_since = None
        return changed

    def _launch(self, rt: WorkerRuntime, lease: Optional[DirLease], now: datetime) -> None:
        attempt_no = len(rt.attempts) + 1
        evidence_root = self._worker_dir(rt.spec.id) / "evidence"
        # Process ownership evidence for THIS attempt. The path is persisted in
        # worker.json before the worker runs, so recovery can always find the
        # record the supervised process writes (intent first, then pid).
        process_path = self._worker_dir(rt.spec.id) / "process" / f"attempt-{attempt_no}.json"
        control = supervision.ExecutionControl(
            worker_id=rt.spec.id, attempt=attempt_no, evidence_path=process_path,
            write_json=queue._atomic_write_json,
        )
        self._controls[rt.spec.id] = control
        attempt = {
            "attempt": attempt_no, "provider": rt.active_provider, "started_at_utc": _iso(now),
            "ended_at_utc": None, "status": "RUNNING", "executed": True, "runner_state": None,
            "work_status": None, "evidence_dir": None, "retry_decision": None,
            "budget_class": BUDGET_WORK, "process_evidence_path": str(process_path),
        }
        rt.attempts.append(attempt)
        # Conservative: from dispatch on, a provider process may mutate the
        # worktree, so the provider is fixed unless proven never to have run.
        rt.provider_locked = True
        rt.owner = {
            "pid": os.getpid(), "hostname": self.hostname, "run_id": self.run_id, "provider": rt.active_provider,
            "worktree": rt.spec.worktree_top, "started_at_utc": _iso(now), "last_heartbeat_utc": _iso(now),
        }
        self._transition(rt, WorkerState.RUNNING, None)
        if lease is not None:
            self._leases[rt.spec.id] = lease
        heartbeat_file = self._worker_dir(rt.spec.id) / "heartbeat.json"
        owner = dict(rt.owner)

        def beat(owner=owner, wid=rt.spec.id, lease=lease, path=heartbeat_file) -> None:
            stamp = queue._now_iso()
            queue._atomic_write_json(path, {**owner, "worker_id": wid, "last_heartbeat_utc": stamp})
            if lease is not None:
                lease.touch()
            self._pipeline_lock.touch()

        beat()
        if self.heartbeat_interval:
            hb = _Heartbeat(self.heartbeat_interval, beat)
            hb.start()
            self._heartbeats[rt.spec.id] = hb

        request = claude_runner.WorkOrderRequest(
            repo=rt.spec.worktree_top, work_order=rt.spec.work_order, mode=rt.spec.mode,
            authorize_path=list(rt.spec.authorize_path), model=rt.spec.model,
            run_root=str(evidence_root), label=f"{self.manifest.pipeline_id}-{rt.spec.id}",
            provider=rt.active_provider, required_capabilities=list(rt.spec.required_capabilities) or None,
            execution_control=control,
            # Runner V2.1 R21-B: provenance only (never a safety input) - lets
            # a `work_product.json` this attempt records identify exactly
            # which pipeline/worker/attempt produced it. Resume itself stays
            # an explicit, separate operator action: the pipeline never sets
            # `resume_from` on its own re-queued attempts.
            pipeline_id=self.manifest.pipeline_id, worker_id=rt.spec.id, attempt=attempt_no,
            **({"timeout_seconds": rt.spec.timeout_seconds} if rt.spec.timeout_seconds else {}),
        )
        future = self._pool.submit(self._run_one, request)
        self._futures[future] = rt
        self.observed_max_concurrency = max(self.observed_max_concurrency, len(self._futures))

    def _run_one(self, request) -> tuple:
        try:
            return "RESULT", self.executor(request)
        except Exception as exc:  # noqa: BLE001 - governed outcome, finalised by the scheduler thread
            return "EXCEPTION", exc

    # -- completion / retry / fallback --------------------------------------

    def _stderr_tail(self, evidence_dir: Optional[Path]) -> str:
        if not evidence_dir:
            return ""
        try:
            return (Path(evidence_dir) / "stderr.txt").read_text(encoding="utf-8", errors="replace")[-STDERR_TAIL_CHARS:]
        except OSError:
            return ""

    def _finish(self, future) -> None:
        rt = self._futures.pop(future)
        hb = self._heartbeats.pop(rt.spec.id, None)
        if hb is not None:
            hb.stop()
        kind, payload = future.result()
        now = self._now()
        attempt = rt.attempts[-1]
        attempt["ended_at_utc"] = _iso(now)
        # The executor returned/raised. The supervised provider process must
        # additionally be confirmed dead (or never have started) before the
        # attempt counts as stopped and the write lease may be released.
        control = self._controls.pop(rt.spec.id, None)
        settled = control.settled_after_return() if control is not None else True
        self._record_process(attempt, control)
        attempt["process_confirmed_stopped"] = settled
        lease = self._leases.pop(rt.spec.id, None)
        if lease is not None and not settled:
            self._unresolved_leases[rt.spec.id] = lease
            lease = None
            attempt["process_termination_unresolved"] = True
        try:
            self._classify_and_apply(rt, attempt, kind, payload, now)
        finally:
            if lease is not None:
                lease.release()
            rt.owner = None
            self._save_worker(rt)
            self._save_pipeline()

    def _block_unresolved(self, rt: WorkerRuntime, attempt: dict, kind: str, payload) -> None:
        """Lifecycle safety outranks the provider's verdict: whatever the
        executor reported (even SUCCESS), a provider process whose death was
        not confirmed leaves the worker BLOCKED. The provider's own result is
        preserved as evidence only. The WRITE lease was already moved to
        `_unresolved_leases` by `_finish` and stays held."""
        provider_view: dict = {"executor_outcome": kind}
        if kind == "EXCEPTION":
            attempt.update(status="EXCEPTION", error=f"{type(payload).__name__}: {payload}")
            provider_view["error"] = attempt["error"]
        else:
            evidence = Path(payload.evidence_dir) if payload.evidence_dir else None
            attempt.update(
                status="COMPLETED", runner_state=payload.state.value, work_status=payload.work_status,
                exit_code=payload.exit_code, run_id=payload.run_id,
                evidence_dir=str(evidence) if evidence else None, error_message=payload.error_message,
            )
            provider_view.update(runner_state=payload.state.value, work_status=payload.work_status)
        attempt["process_termination_unresolved"] = True
        attempt["provider_result_superseded"] = provider_view
        attempt["retry_decision"] = "NO_RETRY:PROVIDER_PROCESS_UNRESOLVED"
        rt.provider_locked = True
        self._transition(rt, WorkerState.BLOCKED, "PROVIDER_PROCESS_UNRESOLVED")
        self._write_result(rt, {
            "outcome": "BLOCKED", "code": "PROVIDER_PROCESS_UNRESOLVED",
            "message": "provider process/containment death was not confirmed; the provider result cannot be "
                       "trusted and operator recovery is required before this worker may run again",
            "provider_result": provider_view,
        })

    def _classify_and_apply(self, rt: WorkerRuntime, attempt: dict, kind: str, payload, now: datetime) -> None:
        if attempt.get("process_confirmed_stopped") is not True:
            self._block_unresolved(rt, attempt, kind, payload)
            return
        if kind == "EXCEPTION":
            attempt.update(status="EXCEPTION", error=f"{type(payload).__name__}: {payload}", retry_decision="NO_RETRY:EXECUTOR_EXCEPTION")
            self._transition(rt, WorkerState.FAILED, "EXECUTOR_EXCEPTION")
            self._write_result(rt, {"outcome": "FAILED", "code": "EXECUTOR_EXCEPTION", "message": attempt["error"]})
            return

        result = payload
        runner_state = result.state.value
        evidence = Path(result.evidence_dir) if result.evidence_dir else None
        attempt.update(
            status="COMPLETED", runner_state=runner_state, work_status=result.work_status,
            exit_code=result.exit_code, run_id=result.run_id,
            evidence_dir=str(evidence) if evidence else None, error_message=result.error_message,
        )

        # Provider availability (quota/auth) is decided BEFORE fallback and
        # retry logic, and only after the process is confirmed stopped (checked
        # above). Quota/auth never fall back to another provider or credential.
        condition = self._provider_condition(rt, result, evidence) if result.state == _RS.CLAUDE_ERROR else None
        if condition is not None:
            attempt["provider_condition"] = condition.as_dict()
        if condition is not None and condition.condition in (
            availability.ProviderCondition.QUOTA_EXHAUSTED, availability.ProviderCondition.AUTH_BLOCKED,
        ):
            self._hold_for_provider(rt, attempt, condition, result, now)
            return
        rt.provider_wait = None  # any non-hold outcome ends a previous availability wait

        # Provider fallback: only when the provider provably never ran.
        if runner_state in _FALLBACK_TRIGGER_STATES and evidence is None and rt.state == WorkerState.RUNNING.value:
            attempt.update(executed=False, status="NOT_EXECUTED")
            # An EARLIER attempt may already have run this provider against the
            # worktree: ownership then stays fixed and no fallback is allowed.
            earlier_ran = any(a.get("executed") for a in rt.attempts[rt.attempt_base:-1])
            rt.provider_locked = earlier_ran
            nxt = None if earlier_ran else self._next_fallback(rt)
            if nxt is not None:
                rt.fallbacks_used.append({
                    "from": rt.active_provider, "to": nxt, "at_utc": _iso(now),
                    "reason": runner_state, "phase": "PRE_EXECUTION",
                })
                attempt["retry_decision"] = f"FALLBACK:{nxt}"
                rt.active_provider = nxt
                self._transition(rt, WorkerState.READY, f"FALLBACK_TO:{nxt}")
                return
            attempt["retry_decision"] = "NO_RETRY:PROVIDER_UNAVAILABLE"
            self._transition(rt, WorkerState.BLOCKED, "PROVIDER_UNAVAILABLE")
            self._write_result(rt, {"outcome": "BLOCKED", "code": "PROVIDER_UNAVAILABLE", "message": result.error_message})
            return

        # Evidence finalization is a SEPARATE axis from the provider's work
        # result: a provider that completed its work is never downgraded to
        # WORK_FAILED merely because a secondary evidence artifact could not
        # be written. Absent on older/mocked results => evidence is complete.
        evidence_complete = getattr(result, "evidence_complete", True)
        evidence_error = getattr(result, "evidence_error", None)
        if evidence_complete:
            attempt["evidence_complete"] = True
        else:
            attempt["evidence_complete"] = False
            attempt["evidence_error"] = evidence_error

        rs = result.state
        if rs == _RS.SUCCESS:
            if evidence_complete:
                attempt["retry_decision"] = "NONE:SUCCESS"
                self._transition(rt, WorkerState.SUCCESS, None)
                self._write_result(rt, {"outcome": "SUCCESS"})
            else:
                attempt["retry_decision"] = "NO_RETRY:EVIDENCE_FINALIZATION_FAILED"
                self._transition(rt, WorkerState.PARTIAL, "EVIDENCE_FINALIZATION_FAILED")
                self._write_result(rt, {
                    "outcome": "PARTIAL", "code": "EVIDENCE_FINALIZATION_FAILED",
                    "message": "the provider completed its work successfully, but one or more evidence "
                               "artifacts could not be persisted; the work result is preserved as SUCCESS "
                               "in the attempt record",
                    "work_status": result.work_status, "evidence_error": evidence_error,
                })
        elif rs == _RS.PARTIAL:
            attempt["retry_decision"] = "NO_RETRY:PARTIAL"
            partial_extra = {"outcome": "PARTIAL"}
            partial_reason = None
            if not evidence_complete:
                partial_reason = "EVIDENCE_FINALIZATION_FAILED"
                partial_extra["evidence_error"] = evidence_error
            self._transition(rt, WorkerState.PARTIAL, partial_reason)
            self._write_result(rt, partial_extra)
        elif rs == _RS.BLOCKED or rs in _BLOCKING_REFUSALS:
            attempt["retry_decision"] = f"NO_RETRY:{runner_state}"
            if rs in _BLOCKING_REFUSALS:
                rt.provider_locked = rt.provider_locked and evidence is not None
            self._transition(rt, WorkerState.BLOCKED, runner_state)
            self._write_result(rt, {"outcome": "BLOCKED", "code": runner_state, "message": result.error_message})
        elif rs == _RS.INTERRUPTED:
            attempt["retry_decision"] = "NO_RETRY:INTERRUPTED"
            self._transition(rt, WorkerState.INTERRUPTED, "PROVIDER_PROCESS_INTERRUPTED")
        else:
            self._handle_failure(rt, attempt, result, evidence, now)

    def _provider_condition(self, rt: WorkerRuntime, result, evidence: Optional[Path]):
        """The attempt's availability classification: the runner's own (already
        secret-free) record when present, otherwise derived by the provider
        adapter from the attempt's evidence."""
        recorded = availability.ProviderClassification.from_dict(getattr(result, "provider_condition", None))
        if recorded is not None:
            return recorded
        try:
            provider = self.resolver(rt.active_provider)
        except providers.ProviderError:
            return None
        return provider.classify_failure(
            stdout=self._evidence_text(evidence, "stdout.txt"), stderr=self._evidence_text(evidence, "stderr.txt"),
            error_text=result.error_message,
        )

    @staticmethod
    def _evidence_text(evidence: Optional[Path], name: str) -> str:
        if not evidence:
            return ""
        try:
            return (Path(evidence) / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _hold_for_provider(self, rt: WorkerRuntime, attempt: dict, condition, result, now: datetime) -> None:
        """Quota -> WAITING_PROVIDER_QUOTA; auth -> BLOCKED_PROVIDER_AUTH.
        Neither is a work failure: the attempt is marked as provider-
        availability (not charged to max_attempts), the provider stays fixed
        (no fallback: a quota/auth event is never a reason to switch provider,
        credential or to a paid API), and the worktree/DAG are untouched. The
        write lease is released by `_finish` once the process is confirmed
        stopped; no execution slot is held (the future is already gone)."""
        attempt["budget_class"] = BUDGET_PROVIDER_AVAILABILITY
        rt.provider_locked = True
        previous = rt.provider_wait or {}
        wait = {
            "condition": condition.condition.value, "reason": condition.reason,
            "http_status": condition.http_status, "reset_hint": condition.reset_hint,
            "message_excerpt": condition.message_excerpt, "since_utc": previous.get("since_utc") or _iso(now),
            "last_hit_utc": _iso(now), "next_eligible_utc": None, "eligibility_source": None,
            "consecutive_quota_waits": 0,
            "budget_note": "provider availability wait; not charged to max_attempts",
        }
        if condition.condition == availability.ProviderCondition.AUTH_BLOCKED:
            rt.provider_wait = wait
            attempt["retry_decision"] = "NO_RETRY:PROVIDER_AUTH_BLOCKED"
            self._transition(rt, WorkerState.BLOCKED_PROVIDER_AUTH, "PROVIDER_AUTH_BLOCKED")
            self._write_result(rt, {
                "outcome": "BLOCKED_PROVIDER_AUTH", "code": "PROVIDER_AUTH_BLOCKED",
                "message": "provider credentials were rejected; operator action is required before this worker "
                           "may run again (worktree and evidence preserved)",
                "provider_condition": condition.as_dict(),
            })
            return
        streak = int(previous.get("consecutive_quota_waits") or 0) + 1
        eligible, source = None, "BACKOFF_PROBE"
        reset = availability.parse_reset_hint(condition.reset_hint, now, self.tz_lookup)
        if reset is not None and (reset - now).total_seconds() <= QUOTA_MAX_HINT_HORIZON_SECONDS:
            eligible, source = reset + timedelta(seconds=QUOTA_RESET_MARGIN_SECONDS), "RESET_HINT"
        else:
            delay = min(QUOTA_PROBE_BASE_SECONDS * (2 ** (streak - 1)), QUOTA_PROBE_MAX_SECONDS)
            eligible = now + timedelta(seconds=delay)
        wait.update(
            next_eligible_utc=_iso(eligible), eligibility_source=source, consecutive_quota_waits=streak,
        )
        rt.provider_wait = wait
        attempt["retry_decision"] = f"WAIT:PROVIDER_QUOTA_EXHAUSTED:{source}:until={wait['next_eligible_utc']}"
        self._transition(rt, WorkerState.WAITING_PROVIDER_QUOTA, f"PROVIDER_QUOTA_EXHAUSTED:{source}")
        self._write_result(rt, {
            "outcome": "WAITING_PROVIDER_QUOTA", "code": "PROVIDER_QUOTA_EXHAUSTED",
            "message": "provider quota/session exhausted; worker waits for provider recovery "
                       "(worktree and dependencies preserved, attempt budget untouched)",
            "provider_condition": condition.as_dict(), "next_eligible_utc": wait["next_eligible_utc"],
        })

    def _next_fallback(self, rt: WorkerRuntime) -> Optional[str]:
        tried = {rt.spec.provider, rt.active_provider} | {f["from"] for f in rt.fallbacks_used}
        for candidate in rt.spec.fallback_providers:
            if candidate not in tried and self._candidate_report(rt, candidate)["verdict"] == "PASS":
                return candidate
        return None

    def _handle_failure(self, rt: WorkerRuntime, attempt: dict, result, evidence: Optional[Path], now: datetime) -> None:
        runner_state = result.state.value
        text = f"{result.error_message or ''}\n{self._stderr_tail(evidence)}"
        transient = False
        if result.state in (_RS.CLAUDE_ERROR, _RS.TIMEOUT):
            try:
                transient = bool(self.resolver(rt.active_provider).is_transient_failure(runner_state, text))
            except providers.ProviderError:
                transient = False
            # Structured classification (e.g. HTTP 429/529 in the provider's
            # own envelope) also qualifies; generic execution errors do not.
            transient = transient or (
                (attempt.get("provider_condition") or {}).get("condition")
                == availability.ProviderCondition.TRANSIENT_ERROR.value
            )
        if not transient:
            attempt["retry_decision"] = f"NO_RETRY:NON_TRANSIENT:{runner_state}"
            self._transition(rt, WorkerState.FAILED, runner_state)
            self._write_result(rt, {"outcome": "FAILED", "code": runner_state, "message": result.error_message})
            return
        if rt.attempts_used >= rt.spec.max_attempts:
            attempt["retry_decision"] = "NO_RETRY:MAX_ATTEMPTS_EXHAUSTED"
            self._transition(rt, WorkerState.FAILED, "MAX_ATTEMPTS_EXHAUSTED")
            self._write_result(rt, {
                "outcome": "FAILED", "code": "MAX_ATTEMPTS_EXHAUSTED",
                "message": f"transient failure {runner_state} on attempt {rt.attempts_used}/{rt.spec.max_attempts}",
            })
            return
        delay = min(rt.spec.backoff_seconds * (2 ** (rt.attempts_used - 1)), MAX_BACKOFF_SECONDS)
        rt.retry_not_before_utc = _iso(now + timedelta(seconds=delay))
        attempt["retry_decision"] = f"RETRY:TRANSIENT:{runner_state}:backoff={delay:g}s"
        self._transition(rt, WorkerState.RETRY_WAIT, f"TRANSIENT:{runner_state}")

    # -- main loop ----------------------------------------------------------

    def _enter_draining(self, reason: str) -> None:
        self._draining = True
        self._status = PipelineStatus.DRAINING.value
        self._stop_reason = reason
        self._save_pipeline()

    def _sync_keep_awake(self) -> None:
        pending = any(
            rt.worker_state in _PENDING_STATES | {WorkerState.RETRY_WAIT, WorkerState.WAITING_PROVIDER_QUOTA}
            for rt in self.workers.values()
        )
        useful = bool(self._futures) or (pending and not self._draining)
        if useful:
            self.keep_awake.acquire()
        else:
            self.keep_awake.release()

    def _next_wake(self, now: datetime) -> Optional[float]:
        """Seconds to sleep when nothing is running, or None when no worker
        can make further progress."""
        waits = []
        for rt in self.workers.values():
            if rt.worker_state == WorkerState.RETRY_WAIT:
                due = _parse_iso(rt.retry_not_before_utc)
                waits.append(max((due - now).total_seconds(), 0.0) if due else 0.0)
            elif rt.worker_state == WorkerState.WAITING_PROVIDER_QUOTA:
                due = _parse_iso((rt.provider_wait or {}).get("next_eligible_utc"))
                waits.append(max((due - now).total_seconds(), 0.0) if due else 0.0)
        if self._lease_blocked_since is not None:
            if (now - self._lease_blocked_since).total_seconds() >= self.lease_wait_seconds:
                self._stop_reason = "WORKTREE_LEASE_HELD_BY_OTHER_OWNER"
                return None
            waits.append(self.poll_seconds)
        if not waits:
            return None
        wake = min(waits)
        if self._deadline is not None:
            wake = min(wake, max((self._deadline - now).total_seconds(), 0.0))
        return max(min(wake, 60.0), 0.0)

    def _on_interrupt(self) -> None:
        if self._shutdown.is_set():
            raise _ForcedStop()
        self.request_shutdown()

    def _loop(self) -> None:
        while True:
            try:
                now = self._now()
                if not self._draining and self._shutdown.is_set():
                    self._enter_draining("SHUTDOWN_REQUESTED")
                if not self._draining and self._deadline is not None and now >= self._deadline:
                    self._enter_draining("DEADLINE_REACHED")
                self._refresh(now)
                changed = self._start_ready(now) if not self._draining else False
                self._sync_keep_awake()
                if not self._futures:
                    if changed:
                        continue  # a worker was refused: re-evaluate its dependents
                    if self._draining:
                        return
                    wake = self._next_wake(now)
                    if wake is None:
                        return
                    self._sleep(wake)
                    continue
                done, _ = futures_wait(list(self._futures), timeout=self.poll_seconds, return_when=FIRST_COMPLETED)
                for future in done:
                    self._finish(future)
            except KeyboardInterrupt:
                self._on_interrupt()


# ---------------------------------------------------------------------------
# Status (read-only)
# ---------------------------------------------------------------------------

def read_pipeline_status(state_root, pipeline_id: str, *, pid_alive=None, now: Optional[datetime] = None) -> dict:
    base = Path(state_root) / pipeline_id
    try:
        result = json.loads((base / "pipeline_result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PipelineError("PIPELINE_NOT_FOUND", f"no readable pipeline_result.json under {base}: {exc}")
    pid_alive = pid_alive or mw._pid_alive
    now = now or datetime.now(timezone.utc)
    host = socket.gethostname()
    for entry in result.get("workers", []):
        if entry["state"] != WorkerState.RUNNING.value:
            continue
        try:
            hb = json.loads((base / "workers" / entry["id"] / "heartbeat.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hb = None
        entry["liveness"] = assess_owner(hb, now, host, pid_alive, DEFAULT_LEASE_SECONDS)
        entry["last_heartbeat_utc"] = hb.get("last_heartbeat_utc") if hb else None
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _provider_limit(value: str) -> tuple:
    name, sep, raw = value.partition("=")
    if not sep or not name.strip() or not raw.isdigit() or int(raw) < 1:
        raise argparse.ArgumentTypeError("expected PROVIDER=N with N >= 1 (e.g. claude=2)")
    return name.strip().lower(), int(raw)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runner_pipeline",
        description="Runner V2 pipeline orchestrator: durable multiworker + multiprovider execution.",
    )
    parser.add_argument("--repo", default=None, help="Repository used for the default state root (default: cwd).")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--manifest", required=True, help="Pipeline manifest (JSON).")

    validate_p = sub.add_parser("validate", help="Validate a manifest without executing anything.")
    common(validate_p)

    run_p = sub.add_parser("pipeline", help="Run (or resume) a pipeline from a manifest.")
    common(run_p)
    run_p.add_argument("--state-root", default=None, help="Default: <repo>/runtime/claude_runner/pipelines")
    run_p.add_argument("--max-workers", type=int, default=None)
    run_p.add_argument("--provider-limit", action="append", type=_provider_limit, default=[],
                       help="Per-provider concurrency, e.g. claude=2 (repeatable).")
    run_p.add_argument("--max-runtime-hours", type=float, default=None,
                       help="Stop starting new work after this many hours, then drain.")
    run_p.add_argument("--keep-awake", action="store_true", help="Prevent system sleep while work is pending/running (Windows).")
    run_p.add_argument("--requeue-interrupted", action="store_true",
                       help="Re-queue workers left INTERRUPTED by a crash/restart.")
    run_p.add_argument("--rerun", action="append", default=[], metavar="WORKER_ID",
                       help="Re-queue one failed/blocked/partial/interrupted worker (and cancelled dependents).")
    run_p.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)

    status_p = sub.add_parser("status", help="Print the aggregate result of a pipeline.")
    status_p.add_argument("--state-root", default=None)
    status_p.add_argument("--pipeline-id", required=True)
    return parser


def _state_root(args) -> Path:
    if args.state_root:
        return Path(args.state_root).resolve()
    repo = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
    return (repo / "runtime" / "claude_runner" / "pipelines").resolve()


def _print_manifest_error(exc: ManifestError) -> int:
    print("error: MANIFEST_INVALID: nothing was executed", file=sys.stderr)
    for e in exc.errors:
        who = f" [{e['worker']}]" if e.get("worker") else ""
        print(f"  - {e['code']}{who}: {e['message']}", file=sys.stderr)
    return EXIT_MANIFEST_INVALID


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "status":
        try:
            result = read_pipeline_status(_state_root(args), args.pipeline_id)
        except PipelineError as exc:
            print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
            return EXIT_PIPELINE_REFUSED
        print(json.dumps(result, indent=2))
        return PIPELINE_EXIT_CODES.get(result.get("status"), 0)

    try:
        manifest = load_manifest(args.manifest, self_worktree=default_self_worktree())
    except ManifestError as exc:
        return _print_manifest_error(exc)
    if args.command == "validate":
        print(f"manifest ok pipeline_id={manifest.pipeline_id} workers={len(manifest.workers)}")
        return 0

    runner = PipelineRunner(
        manifest, _state_root(args), max_workers=args.max_workers,
        provider_limits=dict(args.provider_limit),
        max_runtime_seconds=args.max_runtime_hours * 3600 if args.max_runtime_hours else None,
        keep_awake=default_keep_awake() if args.keep_awake else NullKeepAwake(),
        requeue_interrupted=args.requeue_interrupted, rerun=args.rerun, poll_seconds=args.poll_seconds,
    )
    try:
        result = runner.run()
    except PipelineError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return EXIT_PIPELINE_REFUSED
    print(f"pipeline_id={result.pipeline_id} status={result.status} stop_reason={result.stop_reason}")
    print(f"result={result.path}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
