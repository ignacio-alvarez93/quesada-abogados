"""FCP-4C-01: read-only worktree inventory and ownership check.

Answers ONE question, without changing anything: "which worktrees does Git
have registered for this repository, and what - according to Git, the
Runner worktree lease, durable pipeline state and the factory ledger - is
each one's ownership/safety state right now?" It never prunes, removes,
moves, locks, unlocks, checks out, resets, commits, fetches or rewrites
anything, and NOTHING here is a retirement or deletion decision: the
mildest classification, IDLE_CLEAN_UNBOUND, only means "candidate for HUMAN
review" (`authorizes_action` is always False). Merged branches and
ahead-zero branches are not inspected at all - neither is evidence of
safety - and age is never consulted.

Sources (all reused, none duplicated)
--------------------------------------
* Git registry: `git worktree list --porcelain -z` and every per-worktree
  read go through `runner_integration._git` (and so `runner_git.run`):
  hooks, fsmonitor, external diff/textconv and content filters are
  neutralized or refused, optional index locks/refreshes are disabled,
  repository-redirecting environment variables are dropped and only the
  read-only subcommand allowlist of `runner_integration` can be issued.
* Lease: the SAME per-worktree write lease Runner uses
  (`runner_pipeline.worktree_lease_dir`, same `lease_root` semantics). The
  OS lock is the only authority: it is probed non-blocking with the same
  `claude_queue.QueueLock` primitive `DirLease` wraps and released at once.
  `DirLease.try_acquire` is deliberately NOT used for the probe - it would
  overwrite and, on release, delete a crashed holder's `lease.json`
  residue, which is evidence. A missing lease directory or lock file is
  never created. `lease.json` is read (`DirLease.holder`) for diagnostics
  only; on its own it never makes a worktree active.
* Pipeline state: every `<state_root>/<pipeline_id>/workers/<id>/
  worker.json` (the durable WorkerRuntime record). A worker binds to the
  worktree its persisted spec targets. Non-terminal states are active;
  INTERRUPTED, BLOCKED_PROVIDER_AUTH, a pending governed resume, a failed
  checkpoint and any not-confirmed-stopped provider/acceptance process are
  RECOVERY_PENDING - never a safe terminal state.
* Factory ledger: `runner_factory_ledger.read_events`/`factory_status`.
  An open WORKER_STARTED (no WORKER_FINISHED) bound by worktree or branch
  is informative only - never an ownership authority - but it always
  prevents IDLE_CLEAN_UNBOUND (OWNERSHIP_INCONSISTENT).

Fail-closed rules
-----------------
A registry that cannot be read yields a FAILED_CLOSED inventory with no
records. An unreadable/corrupt ledger or pipeline state (or a missing
root) yields FAILED_CLOSED with every record still reported, each marked
GLOBAL_STATE_UNREADABLE (UNSAFE) - an unreadable state could own any
worktree. A single unreadable worktree only marks its own record. Runner
state is read before and after the per-worktree reads; a record whose
Runner signals changed meanwhile is UNSAFE (RUNNER_STATE_DRIFT).

Classification
--------------
`classify_record` is pure, with the fixed precedence of
`CLASSIFICATION_PRECEDENCE` (most urgent first); `reason_codes` lists every
blocking finding in that order, `advisories` non-blocking observations.
IDLE_CLEAN_UNBOUND additionally requires every mandatory fact to be PROVEN
(registered, readable, clean, branch known, lease probed free, Runner
state readable); anything unproven is UNSAFE. Records are immutable,
ordered deterministically (main worktree first, then by canonical key) and
fingerprinted over trusted canonical fields - lease identity diagnostics
(timestamps, pids) are excluded. A fingerprint authorizes nothing.

Residual limitations: the inventory is a point-in-time snapshot. A lease
taken, a pipeline started or a file written right after a worktree was
inspected is not seen; the lease probe itself briefly holds the OS lock
(a concurrent Runner WRITE worker sees a busy lease and retries, as for
any other holder). Pipeline orchestrator locks are never probed (a
starting orchestrator refuses a busy pipeline lock outright).
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import claude_multiworker as mw
    from scripts.ai import claude_queue as queue
    from scripts.ai import claude_runner
    from scripts.ai import runner_factory_ledger as flog
    from scripts.ai import runner_integration as ri
    from scripts.ai import runner_pipeline as pipeline
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_multiworker as mw  # type: ignore[no-redef]
    import claude_queue as queue  # type: ignore[no-redef]
    import claude_runner  # type: ignore[no-redef]
    import runner_factory_ledger as flog  # type: ignore[no-redef]
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_pipeline as pipeline  # type: ignore[no-redef]


FINGERPRINT_SCHEMA = "fcp4c01-worktree-inventory-v1"

INVENTORY_COMPLETE = "COMPLETE"
INVENTORY_FAILED_CLOSED = "FAILED_CLOSED"

UNSAFE = "UNSAFE"
RECOVERY_PENDING = "RECOVERY_PENDING"
ACTIVE_LEASED = "ACTIVE_LEASED"
ACTIVE_PIPELINE = "ACTIVE_PIPELINE"
OWNERSHIP_INCONSISTENT = "OWNERSHIP_INCONSISTENT"
MISSING_PATH = "MISSING_PATH"
PROTECTED = "PROTECTED"
GIT_LOCKED = "GIT_LOCKED"
DIRTY = "DIRTY"
DETACHED = "DETACHED"
IDLE_CLEAN_UNBOUND = "IDLE_CLEAN_UNBOUND"

# Most urgent first. Unreadable/contradictory facts outrank everything;
# possible in-flight or interrupted work outranks a live lease, which
# outranks pipeline bookkeeping; then ownership contradictions, then
# structural facts (missing, protected, git-locked), then content (dirty)
# and HEAD shape. IDLE_CLEAN_UNBOUND is reached only when nothing matched.
CLASSIFICATION_PRECEDENCE = (
    UNSAFE, RECOVERY_PENDING, ACTIVE_LEASED, ACTIVE_PIPELINE, OWNERSHIP_INCONSISTENT,
    MISSING_PATH, PROTECTED, GIT_LOCKED, DIRTY, DETACHED, IDLE_CLEAN_UNBOUND,
)

# Lease probe outcomes. Only HELD means another owner holds the OS lock.
LEASE_HELD = "HELD"
LEASE_FREE = "FREE"
LEASE_NOT_CREATED = "NOT_CREATED"
LEASE_UNRESOLVED = "UNRESOLVED"
LEASE_PROBE_FAILED = "PROBE_FAILED"
_LEASE_PROVEN_FREE = frozenset({LEASE_FREE, LEASE_NOT_CREATED})

_W = pipeline.WorkerState
_TERMINAL_STATES = frozenset(s.value for s in pipeline.TERMINAL_STATES)
_KNOWN_STATES = frozenset(s.value for s in _W)

_HEADS = "refs/heads/"


# ---------------------------------------------------------------------------
# Results (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkerBinding:
    """One durable pipeline worker whose persisted spec targets a worktree."""

    pipeline_id: str
    worker_id: str
    state: str
    state_reason: Optional[str]
    mode: Optional[str]
    indicators: tuple = ()


@dataclass(frozen=True)
class WorktreeRecord:
    """Facts about one registered (or Runner-referenced but unregistered)
    worktree plus its classification. `authorizes_action` is always False."""

    path: str
    worktree_key: str
    registered: bool
    is_main: bool = False
    bare: bool = False
    path_exists: Optional[bool] = None
    locked: bool = False
    locked_reason: Optional[str] = None
    prunable: bool = False
    prunable_reason: Optional[str] = None
    listed_head: Optional[str] = None
    listed_branch: Optional[str] = None
    listed_detached: bool = False
    worktree_top: Optional[str] = None
    git_dir: Optional[str] = None
    common_dir: Optional[str] = None
    object_format: Optional[str] = None
    head_ref: Optional[str] = None
    head_sha: Optional[str] = None
    detached: Optional[bool] = None
    protected_branch: Optional[bool] = None
    clean: Optional[bool] = None
    staged_paths: tuple = ()
    unstaged_paths: tuple = ()
    untracked_paths: tuple = ()
    unmerged_paths: tuple = ()
    duplicate_checkouts: tuple = ()
    lease_dir: Optional[str] = None
    lease_state: str = LEASE_UNRESOLVED
    lease_holder: tuple = ()
    lease_error: Optional[str] = None
    pipeline_workers: tuple = ()
    ledger_open_workers: tuple = ()
    runner_state_readable: bool = False
    drift_reasons: tuple = ()
    read_errors: tuple = ()
    classification: str = UNSAFE
    reason_codes: tuple = ()
    advisories: tuple = ()
    human_review_required: bool = True
    authorizes_action: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class WorktreeInventory:
    """Whole-repository inventory. COMPLETE only when the registry, the
    pipeline state and the ledger were all read; otherwise FAILED_CLOSED
    (with every record still reported). Never authorizes anything."""

    status: str
    complete: bool
    requested_path: str
    repository_top: Optional[str]
    common_dir: Optional[str]
    state_root: Optional[str]
    ledger_root: Optional[str]
    lease_root: Optional[str]
    global_errors: tuple
    records: tuple
    counts: tuple
    classification_precedence: tuple = CLASSIFICATION_PRECEDENCE
    human_review_required: bool = True
    authorizes_action: bool = False
    fingerprint: str = ""


# ---------------------------------------------------------------------------
# Runner state (pipeline workers + factory ledger), read-only
# ---------------------------------------------------------------------------

class _StateError(Exception):
    pass


def _key(path) -> Optional[str]:
    try:
        return mw.canonical_target_key(str(path))
    except mw.MultiworkerError:
        return None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise _StateError(f"{path}: {type(exc).__name__}: {exc}")


def _worker_indicators(data: dict) -> tuple:
    """Recovery/work-product indicators of one durable worker record. Known
    uncertainty is never erased by missing evidence (mirrors
    PipelineRunner's own re-run gate)."""
    state, reason = data["state"], data.get("state_reason")
    codes = []
    if state == _W.INTERRUPTED.value:
        codes.append("WORKER_INTERRUPTED")
    if state == _W.BLOCKED_PROVIDER_AUTH.value:
        codes.append("WORKER_BLOCKED_PROVIDER_AUTH")
    if state == _W.BLOCKED.value and reason == "CHECKPOINT_FAILED":
        codes.append("CHECKPOINT_FAILED")
    if data.get("pending_resume_from"):
        codes.append("PENDING_RESUME_FROM")
    attempts = data.get("attempts") if isinstance(data.get("attempts"), list) else []
    latest = next((a for a in reversed(attempts) if isinstance(a, dict) and a.get("executed")), None)
    if latest is not None and state != _W.RUNNING.value:
        recovery = latest.get("process_recovery") if isinstance(latest.get("process_recovery"), dict) else {}
        if (
            recovery.get("resolution") == "UNRESOLVED"
            or latest.get("process_confirmed_stopped") is not True
            or latest.get("process_termination_unresolved") is True
            or latest.get("acceptance_termination_unresolved") is True
        ):
            codes.append("PROCESS_TERMINATION_UNRESOLVED")
    return tuple(codes)


def _read_pipeline_bindings(state_root) -> tuple:
    """({worktree_key: [WorkerBinding]}, [errors]). Any unreadable,
    malformed or unbindable worker record is an error (fail closed)."""
    bindings: dict = {}
    errors = []
    root = Path(state_root)
    try:
        if not root.is_dir():
            return bindings, [f"PIPELINE_STATE_UNREADABLE: state root is not a directory: {root}"]
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        return bindings, [f"PIPELINE_STATE_UNREADABLE: {root}: {exc}"]
    for entry in entries:
        if entry.name == pipeline.EVIDENCE_ROOT_DIRNAME or not entry.is_dir():
            continue
        try:
            state_file = entry / "pipeline.json"
            if state_file.exists():
                stored = _read_json(state_file)
                if not isinstance(stored, dict):
                    raise _StateError(f"{state_file}: not a JSON object")
            workers_dir = entry / "workers"
            if not workers_dir.exists():
                continue
            worker_dirs = sorted(workers_dir.iterdir(), key=lambda p: p.name)
        except (_StateError, OSError) as exc:
            errors.append(f"PIPELINE_STATE_CORRUPT: {exc}")
            continue
        for wdir in worker_dirs:
            if not wdir.is_dir():
                continue
            path = wdir / "worker.json"
            try:
                data = _read_json(path)
                spec = data.get("spec") if isinstance(data, dict) else None
                if not isinstance(spec, dict) or data.get("state") not in _KNOWN_STATES:
                    raise _StateError(f"{path}: malformed worker record")
                target = spec.get("worktree_top") or spec.get("worktree")
                key = _key(target) if isinstance(target, str) else None
                if key is None:
                    raise _StateError(f"{path}: worker target worktree is unresolvable")
            except _StateError as exc:
                errors.append(f"WORKER_STATE_CORRUPT: {exc}")
                continue
            bindings.setdefault(key, []).append(WorkerBinding(
                pipeline_id=entry.name, worker_id=wdir.name, state=data["state"],
                state_reason=data.get("state_reason") if isinstance(data.get("state_reason"), str) else None,
                mode=spec.get("mode") if isinstance(spec.get("mode"), str) else None,
                indicators=_worker_indicators(data),
            ))
    return bindings, errors


def _read_ledger_open_workers(ledger_root) -> tuple:
    """([open worker dicts], [errors]). A missing root, an unreadable or
    undecodable events file, or ANY skipped line fails closed."""
    root = Path(ledger_root)
    events_path = root / flog.EVENTS_FILENAME
    try:
        if not root.is_dir():
            return [], [f"LEDGER_UNREADABLE: ledger root is not a directory: {root}"]
        if events_path.exists():
            # read_events degrades an unreadable file to "no history"; an
            # inventory must not, so readability is proven first.
            events_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"LEDGER_UNREADABLE: {events_path}: {type(exc).__name__}: {exc}"]
    events, skipped = flog.read_events(root)
    if skipped:
        return [], [f"LEDGER_CORRUPT: {skipped} unreadable ledger line(s) in {events_path}"]
    return list(flog.factory_status(events)["active_workers"]), []


@dataclass(frozen=True)
class _RunnerState:
    bindings: dict
    ledger_open: list
    errors: tuple

    def workers_for(self, key: str) -> tuple:
        return tuple(sorted(
            self.bindings.get(key, ()), key=lambda b: (b.pipeline_id, b.worker_id),
        ))

    def ledger_for(self, key: str, branch: Optional[str]) -> tuple:
        found = set()
        for worker in self.ledger_open:
            target = worker.get("worktree")
            same_worktree = isinstance(target, str) and target.strip() and _key(target) == key
            same_branch = branch is not None and worker.get("branch") in (branch, _HEADS + branch)
            if same_worktree or same_branch:
                found.add((str(worker.get("pipeline_id")), str(worker.get("worker_id"))))
        return tuple(sorted(found))

    def referenced_keys(self) -> dict:
        """{key: original path} for every worktree a live/recovery-pending
        worker or an open ledger worker targets."""
        refs = {}
        for key, workers in self.bindings.items():
            if any(b.state not in _TERMINAL_STATES or b.indicators for b in workers):
                refs.setdefault(key, key)
        for worker in self.ledger_open:
            target = worker.get("worktree")
            key = _key(target) if isinstance(target, str) and target.strip() else None
            if key is not None:
                refs.setdefault(key, target)
        return refs


def _read_runner_state(state_root, ledger_root) -> _RunnerState:
    bindings, errors = _read_pipeline_bindings(state_root)
    ledger_open, ledger_errors = _read_ledger_open_workers(ledger_root)
    return _RunnerState(bindings=bindings, ledger_open=ledger_open, errors=tuple(errors + ledger_errors))


# ---------------------------------------------------------------------------
# Lease probe (transient; same namespace and OS lock as DirLease)
# ---------------------------------------------------------------------------

def _probe_lease(lease_dir: Path) -> tuple:
    """(lease_state, holder_tuple, error). Never creates the lease
    directory or lock file and never touches `lease.json`."""
    lease = pipeline.DirLease(lease_dir)
    holder = lease.holder() or {}
    holder_items = tuple(sorted((str(k), str(v)) for k, v in holder.items()))
    try:
        if not lease_dir.exists() or not (lease_dir / queue.LOCK_FILENAME).exists():
            # A lock that was never created cannot be held.
            return LEASE_NOT_CREATED, holder_items, None
        lock = queue.QueueLock(lease_dir)
        try:
            lock.acquire(blocking=False)
        except queue.QueueLockError:
            return LEASE_HELD, holder_items, None
        lock.release()
    except OSError as exc:
        return LEASE_PROBE_FAILED, holder_items, f"{type(exc).__name__}: {exc}"
    return LEASE_FREE, holder_items, None


# ---------------------------------------------------------------------------
# Git registry and per-worktree facts (through runner_integration only)
# ---------------------------------------------------------------------------

def _registry(repo) -> tuple:
    """(identity, [entry dicts]) of the repository `repo` belongs to."""
    identity = ri._repo_identity(repo)
    return identity, ri._worktree_entries(repo)


def _inspect(path: str, registry_common: str, is_main: bool, lease_root, facts: dict, errors: list) -> None:
    """Fills `facts` for one existing registered worktree path."""
    identity = ri._repo_identity(path)
    top, fmt = identity["top"], identity["object_format"]
    facts.update(worktree_top=top, git_dir=identity["git_dir"], common_dir=identity["common_dir"],
                 object_format=fmt)
    if _key(top) != facts["worktree_key"]:
        raise ri._GitReadError("git rev-parse", f"worktree resolves to a different toplevel: {top}")
    if _key(identity["common_dir"]) != _key(registry_common):
        raise ri._GitReadError("git rev-parse", "worktree belongs to a different common directory")
    admin_ok = (_key(identity["git_dir"]) == _key(registry_common)) if is_main else (
        _key(Path(identity["git_dir"]).parent) == _key(Path(registry_common) / "worktrees")
    )
    if not admin_ok:
        raise ri._GitReadError("git rev-parse", f"unexpected administrative directory: {identity['git_dir']}")

    head_ref, head_sha = ri._head(path, fmt)
    branch = head_ref[len(_HEADS):] if head_ref else None
    facts.update(head_ref=head_ref, head_sha=head_sha, detached=head_ref is None)
    guard = claude_runner.evaluate_branch_guard(claude_runner.GitSnapshot(
        branch=branch if branch is not None else "HEAD", head=head_sha or "", porcelain_status="",
        raw_text="", captured_at="",
    ))
    facts["protected_branch"] = guard.decision == "REFUSED_PROTECTED_BRANCH"

    porcelain = ri._status(path)
    dirty = claude_runner.evaluate_dirty_tree(claude_runner.GitSnapshot(
        branch=branch or "HEAD", head=head_sha or "", porcelain_status=porcelain, raw_text="", captured_at="",
    ))
    groups = ri._status_paths(porcelain)
    facts.update(
        clean=dirty.decision == "ALLOWED_CLEAN", staged_paths=groups["staged"],
        unstaged_paths=groups["unstaged"], untracked_paths=groups["untracked"],
        unmerged_paths=groups["unmerged"],
    )

    try:
        lease_dir = pipeline.worktree_lease_dir(Path(top), lease_root)
    except (pipeline.PipelineError, OSError) as exc:
        facts.update(lease_state=LEASE_UNRESOLVED, lease_error=str(exc))
    else:
        facts["lease_dir"] = str(lease_dir)
        expected = Path(identity["git_dir"]) / pipeline.WRITE_LEASE_DIRNAME
        if lease_root is None and _key(lease_dir) != _key(expected):
            # Runner's own lookup does not drop redirecting environment
            # variables; if it disagrees with the hardened read, the probe
            # would look at the wrong lock.
            facts.update(lease_state=LEASE_UNRESOLVED, lease_error=f"lease location mismatch: {lease_dir}")
        else:
            state, holder, error = _probe_lease(lease_dir)
            facts.update(lease_state=state, lease_holder=holder, lease_error=error)

    # HEAD re-read: a change during inspection is drift, never ignored.
    if ri._head(path, fmt) != (head_ref, head_sha):
        facts["drift_reasons"] = facts.get("drift_reasons", ()) + ("HEAD_DRIFT",)


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------

def _findings(r: WorktreeRecord) -> tuple:
    found = {name: [] for name in CLASSIFICATION_PRECEDENCE}
    advisories = []

    unsafe = found[UNSAFE]
    if not r.runner_state_readable:
        unsafe.append("GLOBAL_STATE_UNREADABLE")
    if r.read_errors:
        unsafe.append("GIT_READ_FAILED")
    if r.drift_reasons:
        unsafe.extend(r.drift_reasons)
    if r.lease_state == LEASE_PROBE_FAILED:
        unsafe.append("LEASE_PROBE_FAILED")
    if r.registered and r.path_exists and not r.bare and not r.read_errors:
        if r.lease_state == LEASE_UNRESOLVED:
            unsafe.append("LEASE_UNRESOLVED")
        if r.head_sha is None:
            unsafe.append("UNBORN_HEAD")
        if r.listed_head is not None and r.head_sha is not None and r.listed_head != r.head_sha:
            unsafe.append("REGISTRY_HEAD_MISMATCH")
        if r.listed_branch != r.head_ref:
            unsafe.append("REGISTRY_BRANCH_MISMATCH")

    recovery = found[RECOVERY_PENDING]
    for b in r.pipeline_workers:
        recovery.extend(b.indicators)

    if r.lease_state == LEASE_HELD:
        found[ACTIVE_LEASED].append("WORKTREE_LEASE_HELD")
    elif r.lease_holder:
        advisories.append("LEASE_IDENTITY_RESIDUE")

    for b in r.pipeline_workers:
        if b.state == _W.RUNNING.value:
            found[ACTIVE_PIPELINE].append("PIPELINE_WORKER_RUNNING")
        elif b.state not in _TERMINAL_STATES and not b.indicators:
            found[ACTIVE_PIPELINE].append("PIPELINE_WORKER_PENDING")
        elif b.state in _TERMINAL_STATES and not b.indicators:
            advisories.append("TERMINAL_PIPELINE_HISTORY")

    owner = found[OWNERSHIP_INCONSISTENT]
    if not r.registered:
        owner.append("UNREGISTERED_WORKTREE_REFERENCED")
    if r.duplicate_checkouts:
        owner.append("DUPLICATE_BRANCH_CHECKOUT")
    if r.ledger_open_workers:
        owner.append("LEDGER_OPEN_WORKER")

    if r.registered and (r.prunable or r.path_exists is False):
        found[MISSING_PATH].append("PRUNABLE" if r.prunable else "PATH_MISSING")
        if r.prunable and r.path_exists is not False:
            found[MISSING_PATH].append("PRUNABLE_PATH_PRESENT")

    protected = found[PROTECTED]
    if r.is_main:
        protected.append("MAIN_WORKTREE")
    if r.bare:
        protected.append("BARE_REPOSITORY")
    if r.protected_branch:
        protected.append("PROTECTED_BRANCH")

    if r.locked:
        found[GIT_LOCKED].append("WORKTREE_LOCKED")

    dirty = found[DIRTY]
    if r.staged_paths:
        dirty.append("STAGED_CHANGES")
    if r.unstaged_paths:
        dirty.append("UNSTAGED_CHANGES")
    if r.untracked_paths:
        dirty.append("UNTRACKED_FILES")
    if r.unmerged_paths:
        dirty.append("UNMERGED_PATHS")
    if r.clean is False and not dirty:
        dirty.append("DIRTY_UNCLASSIFIED")

    if r.detached or r.listed_detached:
        found[DETACHED].append("DETACHED_HEAD")
    return found, tuple(dict.fromkeys(advisories))


def _unproven(r: WorktreeRecord) -> tuple:
    """Every mandatory fact NOT explicitly proven safe. `_findings` only
    reports facts known to be bad; an unknown one can never become idle."""
    checks = (
        ("UNPROVEN_REGISTERED", r.registered is True and r.path_exists is True and not r.prunable),
        ("UNPROVEN_READS", not r.read_errors and r.worktree_top is not None),
        ("UNPROVEN_RUNNER_STATE", r.runner_state_readable is True),
        ("UNPROVEN_CLEAN", r.clean is True),
        ("UNPROVEN_BRANCH", isinstance(r.head_ref, str) and r.head_ref.startswith(_HEADS)
         and r.detached is False and r.head_sha is not None),
        ("UNPROVEN_UNPROTECTED_BRANCH", r.protected_branch is False),
        ("UNPROVEN_LEASE_FREE", r.lease_state in _LEASE_PROVEN_FREE),
    )
    return tuple(code for code, ok in checks if not ok)


def _record_fingerprint(r: WorktreeRecord) -> str:
    payload = {
        "schema": FINGERPRINT_SCHEMA,
        "worktree_key": r.worktree_key, "registered": r.registered, "is_main": r.is_main, "bare": r.bare,
        "path_exists": r.path_exists, "locked": r.locked, "prunable": r.prunable,
        "listed_head": r.listed_head, "listed_branch": r.listed_branch, "listed_detached": r.listed_detached,
        "git_dir": r.git_dir, "common_dir": r.common_dir, "head_ref": r.head_ref, "head_sha": r.head_sha,
        "clean": r.clean, "staged": list(r.staged_paths), "unstaged": list(r.unstaged_paths),
        "untracked": list(r.untracked_paths), "unmerged": list(r.unmerged_paths),
        "duplicates": [_key(p) for p in r.duplicate_checkouts], "lease_dir": r.lease_dir,
        "lease_state": r.lease_state,
        "pipeline_workers": [[b.pipeline_id, b.worker_id, b.state, b.state_reason, list(b.indicators)]
                             for b in r.pipeline_workers],
        "ledger_open_workers": [list(w) for w in r.ledger_open_workers],
        "runner_state_readable": r.runner_state_readable, "drift": list(r.drift_reasons),
        "read_failed": bool(r.read_errors),
        "classification": r.classification, "reason_codes": list(r.reason_codes),
        "advisories": list(r.advisories),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_record(record: WorktreeRecord) -> WorktreeRecord:
    """Pure, fail-closed classification with the fixed precedence of
    CLASSIFICATION_PRECEDENCE. Returns a new record; never authorizes."""
    found, advisories = _findings(record)
    classification = next((name for name in CLASSIFICATION_PRECEDENCE if found[name]), None)
    if classification is None:
        unproven = _unproven(record)
        found[UNSAFE].extend(unproven)
        classification = UNSAFE if unproven else IDLE_CLEAN_UNBOUND
    reasons = tuple(dict.fromkeys(code for name in CLASSIFICATION_PRECEDENCE for code in found[name]))
    fields = {**record.__dict__, "classification": classification, "reason_codes": reasons,
              "advisories": advisories, "human_review_required": True, "authorizes_action": False,
              "fingerprint": ""}
    staged = WorktreeRecord(**fields)
    return WorktreeRecord(**{**fields, "fingerprint": _record_fingerprint(staged)})


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def _inventory_fingerprint(status: str, common_dir, global_errors: tuple, records: tuple) -> str:
    payload = {
        "schema": FINGERPRINT_SCHEMA, "status": status, "common_dir": _key(common_dir) if common_dir else None,
        "global_errors": list(global_errors), "records": [r.fingerprint for r in records],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _counts(records: tuple) -> tuple:
    return tuple((name, sum(1 for r in records if r.classification == name)) for name in CLASSIFICATION_PRECEDENCE)


def _finish(requested: str, identity: Optional[dict], roots: dict, errors: list, records: list) -> WorktreeInventory:
    ordered = tuple(sorted(records, key=lambda r: (not r.is_main, not r.registered, r.worktree_key)))
    errors = tuple(errors)
    status = INVENTORY_FAILED_CLOSED if errors else INVENTORY_COMPLETE
    common = identity["common_dir"] if identity else None
    return WorktreeInventory(
        status=status, complete=not errors, requested_path=requested,
        repository_top=identity["top"] if identity else None, common_dir=common,
        global_errors=errors, records=ordered, counts=_counts(ordered),
        fingerprint=_inventory_fingerprint(status, common, errors, ordered), **roots,
    )


def inventory_worktrees(repository, *, state_root, ledger_root, lease_root=None) -> WorktreeInventory:
    """Read-only inventory of every worktree registered for the repository
    `repository` belongs to. `state_root`/`ledger_root` are the Runner
    pipeline state and factory ledger roots (both required: an absent root
    fails closed); `lease_root` has Runner's own semantics."""
    requested = str(repository)
    roots = {"state_root": str(state_root), "ledger_root": str(ledger_root),
             "lease_root": None if lease_root is None else str(lease_root)}
    try:
        identity, entries = _registry(requested)
    except (ri._GitReadError, OSError) as exc:
        return _finish(requested, None, roots, [f"REGISTRY_UNREADABLE: {exc}"], [])
    common = identity["common_dir"]

    before = _read_runner_state(state_root, ledger_root)

    by_branch: dict = {}
    for entry in entries:
        if entry.get("branch"):
            by_branch.setdefault(entry["branch"], []).append(entry["worktree"])

    staged = []
    for index, entry in enumerate(entries):
        path = entry["worktree"]
        key = _key(path) or path
        is_main = index == 0
        listed_branch = entry.get("branch") or None
        facts: dict = {
            "path": path, "worktree_key": key, "registered": True, "is_main": is_main,
            "bare": "bare" in entry, "locked": "locked" in entry, "locked_reason": entry.get("locked") or None,
            "prunable": "prunable" in entry, "prunable_reason": entry.get("prunable") or None,
            "listed_head": entry.get("HEAD") or None, "listed_branch": listed_branch,
            "listed_detached": "detached" in entry,
            "duplicate_checkouts": tuple(sorted(
                p for p in by_branch.get(listed_branch, ()) if _key(p) != key
            )) if listed_branch else (),
        }
        errors = []
        try:
            facts["path_exists"] = Path(path).is_dir()
        except OSError as exc:
            facts["path_exists"] = None
            errors.append(f"path: {exc}")
        if facts["path_exists"] and not facts["bare"]:
            try:
                _inspect(path, common, is_main, lease_root, facts, errors)
            except (ri._GitReadError, mw.MultiworkerError, OSError) as exc:
                errors.append(str(exc))
        facts["read_errors"] = tuple(errors)
        staged.append(facts)

    after = _read_runner_state(state_root, ledger_root)
    global_errors = list(dict.fromkeys(before.errors + after.errors))
    readable = not global_errors

    registered_keys = {f["worktree_key"] for f in staged}
    for key, original in sorted(after.referenced_keys().items()):
        if key not in registered_keys:
            staged.append({"path": str(original), "worktree_key": key, "registered": False,
                           "path_exists": Path(key).is_dir()})

    records = []
    for facts in staged:
        key = facts["worktree_key"]
        branch = facts.get("head_ref") or facts.get("listed_branch")
        branch = branch[len(_HEADS):] if branch and branch.startswith(_HEADS) else None
        workers, ledger = after.workers_for(key), after.ledger_for(key, branch)
        drift = tuple(facts.get("drift_reasons", ()))
        if (before.workers_for(key), before.ledger_for(key, branch)) != (workers, ledger):
            drift += ("RUNNER_STATE_DRIFT",)
        facts.update(pipeline_workers=workers, ledger_open_workers=ledger, runner_state_readable=readable,
                     drift_reasons=drift)
        records.append(classify_record(WorktreeRecord(**facts)))
    return _finish(requested, identity, roots, global_errors, records)
