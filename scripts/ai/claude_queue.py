"""Durable single-worker queue storage foundation for Claude Runner V1.5.

RUNNER-1.5C added persistence only: enqueue/load/list, the state machine,
the durable OS lock, and orphan RUNNING recovery. RUNNER-1.5D adds a
single-worker `run_next()` primitive that connects that durable queue to
the governed Runner (`claude_runner.execute_work_order()`) for exactly one
QUEUED item per call. This module still does NOT classify quota errors,
does NOT replay/reconcile checkpoints, does NOT retry or requeue anything
automatically, and does NOT commit/push/merge/switch branches/create
worktrees or schedule multiple concurrent workers.

Every queue item is a directory containing:

* item.json     - schema_version, item_id, timestamps, state, repository
                   identity/path, requested execution mode, authorized
                   paths, timeout/model/label, durable work_order filename
                   and SHA-256, and an append-only event history.
* work_order.txt - the complete Work Order text, copied in at enqueue time
                   so the queue never depends on /tmp or any external
                   source afterward.

No conversational session ID is ever stored and no --resume/--continue
semantics are introduced anywhere in this module (mirrors claude_runner.py's
one-Work-Order-per-fresh-invocation contract).

Governance: docs/resolutions/20260912_resolucion_modelo_direccion_tecnica_y_
ejecucion_claude.md and CLAUDE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

# claude_runner is imported by fully-qualified package path first so that
# `from scripts.ai import claude_queue` (tests, and any other module-style
# import) resolves it identically to `test_claude_runner.py`. Running this
# file directly as a script (`python scripts/ai/claude_queue.py ...`) has no
# `scripts` package on sys.path, so that import fails there; the fallback
# below is a plain sibling import, which works because Python always puts a
# directly-run script's own directory at the front of sys.path.
try:
    from scripts.ai import claude_runner
except ImportError:  # pragma: no cover - exercised only via direct-script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_runner


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
DEFAULT_QUEUE_SUBDIR = Path("runtime") / "claude_runner" / "queue"
ITEM_METADATA_FILENAME = "item.json"
WORK_ORDER_FILENAME = "work_order.txt"
LOCK_FILENAME = "queue.lock"
MAX_WORK_ORDER_CHARS = 200_000


class QueueError(Exception):
    """Raised for queue validation/integrity failures with a known reason."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class QueueState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_QUOTA = "WAITING_QUOTA"
    BLOCKED_ON_CHECKPOINT = "BLOCKED_ON_CHECKPOINT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    FAILED_SAFETY = "FAILED_SAFETY"


# Central, explicit transition table. Anything not listed here is illegal.
# WAITING_QUOTA and BLOCKED_ON_CHECKPOINT deliberately have NO outgoing
# transitions in 1.5C: reconciling them back to QUEUED/RUNNING is a future,
# explicit, presumably-manual mechanism, not something this module invents.
# FAILED_SAFETY and SUCCEEDED and FAILED are terminal: no automatic retry.
_ALLOWED_TRANSITIONS = {
    QueueState.QUEUED: {QueueState.RUNNING},
    QueueState.RUNNING: {
        QueueState.WAITING_QUOTA,
        QueueState.BLOCKED_ON_CHECKPOINT,
        QueueState.SUCCEEDED,
        QueueState.FAILED,
        QueueState.FAILED_SAFETY,
    },
    QueueState.WAITING_QUOTA: set(),
    QueueState.BLOCKED_ON_CHECKPOINT: set(),
    QueueState.SUCCEEDED: set(),
    QueueState.FAILED: set(),
    QueueState.FAILED_SAFETY: set(),
}


def validate_transition(from_state: QueueState, to_state: QueueState) -> None:
    """Fails closed (raises QueueError) on any transition not explicitly
    allowed above, including no-op self-transitions and any attempt to
    move a terminal or manual-reconciliation-only state elsewhere."""
    allowed = _ALLOWED_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise QueueError(
            "ILLEGAL_TRANSITION",
            f"Illegal queue state transition: {from_state.value} -> {to_state.value}",
        )


# ---------------------------------------------------------------------------
# Item metadata
# ---------------------------------------------------------------------------

@dataclass
class QueueEvent:
    event: str
    at_utc: str
    detail: Optional[str] = None


@dataclass
class QueueAttempt:
    """One durable execution attempt of a queue item (RUNNER-1.5D).

    Deliberately minimal: no conversational/session id and no Claude
    transcript or stdout/stderr copied here - only enough to reconcile a
    queue item with its Runner evidence directory.
    """

    attempt_id: str
    started_at_utc: str
    ended_at_utc: Optional[str]
    status: str  # "RUNNING" | "COMPLETED" | "EXCEPTION"
    runner_state: Optional[str]
    runner_exit_code: Optional[int]
    runner_run_id: Optional[str]
    runner_evidence_dir: Optional[str]
    final_queue_state: Optional[str]


@dataclass
class QueueItem:
    schema_version: int
    item_id: str
    created_at_utc: str
    updated_at_utc: str
    state: str
    repository_path: str
    mode: str
    authorize_path: list
    timeout_seconds: Optional[int]
    model: Optional[str]
    label: Optional[str]
    work_order_filename: str
    work_order_sha256: str
    history: list
    attempts: list


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Writes `data` to `target` via a same-directory temporary file,
    flush+fsync, then os.replace, so a process killed mid-write can never
    leave a partially written file at `target`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(target))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _atomic_write_json(target: Path, payload: dict) -> None:
    data = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False).encode("utf-8")
    _atomic_write_bytes(target, data)


def _item_to_dict(item: QueueItem) -> dict:
    return asdict(item)


def _dict_to_item(payload: dict) -> QueueItem:
    return QueueItem(
        schema_version=payload["schema_version"],
        item_id=payload["item_id"],
        created_at_utc=payload["created_at_utc"],
        updated_at_utc=payload["updated_at_utc"],
        state=payload["state"],
        repository_path=payload["repository_path"],
        mode=payload["mode"],
        authorize_path=payload.get("authorize_path") or [],
        timeout_seconds=payload.get("timeout_seconds"),
        model=payload.get("model"),
        label=payload.get("label"),
        work_order_filename=payload["work_order_filename"],
        work_order_sha256=payload["work_order_sha256"],
        history=payload.get("history") or [],
        # schema-version-1 items predate the attempts list (RUNNER-1.5D); a
        # missing field means "no attempts recorded yet", never a corrupt item.
        attempts=payload.get("attempts") or [],
    )


_REQUIRED_ITEM_FIELDS = (
    "schema_version",
    "item_id",
    "created_at_utc",
    "updated_at_utc",
    "state",
    "repository_path",
    "mode",
    "work_order_filename",
    "work_order_sha256",
)


# ---------------------------------------------------------------------------
# Queue root / item paths
# ---------------------------------------------------------------------------

def resolve_queue_root(repo: Path, queue_root_arg: Optional[str] = None) -> Path:
    """Default queue root is <repo>/runtime/claude_runner/queue; explicitly
    overrideable (tests and future callers) via `queue_root_arg`."""
    if queue_root_arg:
        return Path(queue_root_arg).resolve()
    return (repo / DEFAULT_QUEUE_SUBDIR).resolve()


def _validate_item_id(item_id: str) -> str:
    """Queue item ids are single safe path segments.

    Generated ids use timestamp_UUID, but load callers may supply ids
    obtained from durable state or operator input. Never allow an id to
    escape the queue root through path separators or traversal.
    """
    if not isinstance(item_id, str) or not item_id:
        raise QueueError("INVALID_ITEM_ID", "Queue item_id must be a non-empty string")
    if item_id in {".", ".."} or "/" in item_id or "\\" in item_id:
        raise QueueError("INVALID_ITEM_ID", f"Unsafe queue item_id: {item_id!r}")
    if not all(ch.isalnum() or ch in "._-" for ch in item_id):
        raise QueueError("INVALID_ITEM_ID", f"Unsafe queue item_id: {item_id!r}")
    return item_id


def _item_dir(queue_root: Path, item_id: str) -> Path:
    return queue_root / _validate_item_id(item_id)


def _item_metadata_path(queue_root: Path, item_id: str) -> Path:
    return _item_dir(queue_root, item_id) / ITEM_METADATA_FILENAME


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def validate_work_order_source(text: str) -> str:
    if text is None or not isinstance(text, str):
        raise QueueError("INVALID_WORK_ORDER", "Work Order source must be a UTF-8 text string")
    if not text.strip():
        raise QueueError("INVALID_WORK_ORDER", "Work Order source must not be empty")
    if len(text) > MAX_WORK_ORDER_CHARS:
        raise QueueError(
            "INVALID_WORK_ORDER",
            f"Work Order source exceeds {MAX_WORK_ORDER_CHARS} characters ({len(text)})",
        )
    return text


def generate_item_id() -> str:
    """Collision-resistant: UTC timestamp (sortable, diagnostic) plus a
    random UUID4 suffix (collision resistance), matching claude_runner.py's
    run-directory naming convention."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex
    return f"{timestamp}_{suffix}"


def enqueue(
    queue_root: Path,
    *,
    work_order_text: str,
    repository_path: str,
    mode: str,
    authorize_path: Optional[list] = None,
    timeout_seconds: Optional[int] = None,
    model: Optional[str] = None,
    label: Optional[str] = None,
) -> QueueItem:
    """Validates the Work Order source, generates an item_id, publishes one
    durable item directory atomically (no half-created item ever visible at
    its final path), copies the Work Order in as work_order.txt, persists
    its SHA-256, and writes item.json with an initial QUEUED history event."""
    text = validate_work_order_source(work_order_text)
    work_order_bytes = text.encode("utf-8")
    work_order_sha256 = hashlib.sha256(work_order_bytes).hexdigest()

    item_id = generate_item_id()
    queue_root.mkdir(parents=True, exist_ok=True)
    final_dir = _item_dir(queue_root, item_id)

    # Publish via a temporary sibling directory + atomic rename, so a
    # concurrent reader never observes a partially populated item
    # directory at its final, well-known path.
    staging_dir = queue_root / f".{item_id}.staging-{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=False, exist_ok=False)
    try:
        (staging_dir / WORK_ORDER_FILENAME).write_bytes(work_order_bytes)

        now = _now_iso()
        history = [asdict(QueueEvent(event="ENQUEUED", at_utc=now, detail=f"item_id={item_id}"))]
        item = QueueItem(
            schema_version=SCHEMA_VERSION,
            item_id=item_id,
            created_at_utc=now,
            updated_at_utc=now,
            state=QueueState.QUEUED.value,
            repository_path=str(repository_path),
            mode=mode,
            authorize_path=list(authorize_path) if authorize_path else [],
            timeout_seconds=timeout_seconds,
            model=model,
            label=label,
            work_order_filename=WORK_ORDER_FILENAME,
            work_order_sha256=work_order_sha256,
            history=history,
            attempts=[],
        )
        _atomic_write_json(staging_dir / ITEM_METADATA_FILENAME, _item_to_dict(item))

        os.replace(str(staging_dir), str(final_dir))
    except BaseException:
        if staging_dir.exists():
            _rmtree_best_effort(staging_dir)
        raise

    return item


def _rmtree_best_effort(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Load / list
# ---------------------------------------------------------------------------

def load_item(queue_root: Path, item_id: str) -> QueueItem:
    """Fails closed on malformed/corrupt JSON, missing required fields,
    missing durable Work Order file, hash mismatch, or item_id/path
    inconsistency."""
    item_dir = _item_dir(queue_root, item_id)
    metadata_path = item_dir / ITEM_METADATA_FILENAME
    if not metadata_path.exists():
        raise QueueError("MISSING_ITEM", f"Queue item metadata not found: {metadata_path}")

    try:
        raw = metadata_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise QueueError("CORRUPT_METADATA", f"Queue item metadata unreadable: {exc}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QueueError("CORRUPT_METADATA", f"Queue item metadata is not valid JSON: {exc}")

    missing = [f for f in _REQUIRED_ITEM_FIELDS if f not in payload]
    if missing:
        raise QueueError(
            "SCHEMA_MISMATCH", f"Queue item metadata missing required field(s): {missing}"
        )

    if payload["item_id"] != item_id:
        raise QueueError(
            "ITEM_ID_MISMATCH",
            f"item_id in metadata ({payload['item_id']!r}) does not match "
            f"directory name ({item_id!r})",
        )

    if payload["schema_version"] != SCHEMA_VERSION:
        raise QueueError(
            "SCHEMA_MISMATCH",
            f"Unsupported schema_version {payload['schema_version']!r} "
            f"(expected {SCHEMA_VERSION})",
        )

    if payload["work_order_filename"] != WORK_ORDER_FILENAME:
        raise QueueError(
            "SCHEMA_MISMATCH",
            f"Unsupported work_order_filename {payload['work_order_filename']!r}; "
            f"expected canonical {WORK_ORDER_FILENAME!r}",
        )

    try:
        QueueState(payload["state"])
    except ValueError:
        raise QueueError("SCHEMA_MISMATCH", f"Unknown queue state: {payload['state']!r}")

    work_order_path = item_dir / payload["work_order_filename"]
    if not work_order_path.exists():
        raise QueueError(
            "MISSING_WORK_ORDER", f"Durable Work Order file not found: {work_order_path}"
        )

    actual_bytes = work_order_path.read_bytes()
    actual_hash = hashlib.sha256(actual_bytes).hexdigest()
    if actual_hash != payload["work_order_sha256"]:
        raise QueueError(
            "HASH_MISMATCH",
            f"Durable Work Order hash mismatch for {item_id}: "
            f"expected {payload['work_order_sha256']}, got {actual_hash}",
        )

    return _dict_to_item(payload)


def list_items(queue_root: Path) -> list:
    """Deterministic order: created_at_utc then item_id.

    Fail closed on every published item that cannot be validated. A corrupt
    item must never become silently invisible to status, recovery or a future
    worker, because that could make an unhealthy queue appear safe.
    Temporary/staging directories remain ignored because they are not
    published queue items.
    """
    if not queue_root.exists():
        return []
    items = []
    for entry in queue_root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        items.append(load_item(queue_root, entry.name))
    items.sort(key=lambda it: (it.created_at_utc, it.item_id))
    return items


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def transition_item(
    queue_root: Path, item_id: str, to_state: QueueState, *, detail: Optional[str] = None
) -> QueueItem:
    """Validates the transition centrally (fail closed on illegal moves),
    appends an audit event, and persists item.json atomically."""
    item = load_item(queue_root, item_id)
    from_state = QueueState(item.state)
    validate_transition(from_state, to_state)

    now = _now_iso()
    item.state = to_state.value
    item.updated_at_utc = now
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event=f"TRANSITION:{from_state.value}->{to_state.value}",
                at_utc=now,
                detail=detail,
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


# ---------------------------------------------------------------------------
# Attempts (RUNNER-1.5D)
# ---------------------------------------------------------------------------

def generate_attempt_id() -> str:
    """Collision-resistant, matching generate_item_id()'s convention: a
    sortable UTC timestamp plus a random UUID4 suffix."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex
    return f"attempt_{timestamp}_{suffix}"


def start_attempt(queue_root: Path, item_id: str, attempt: QueueAttempt) -> QueueItem:
    """Atomically transitions QUEUED->RUNNING and appends `attempt` (already
    status="RUNNING") to the item's durable attempts list in the same
    write, so the attempt is always visibly RUNNING in item.json before any
    executor is invoked, and the item is never RUNNING without a matching
    durable attempt record."""
    item = load_item(queue_root, item_id)
    from_state = QueueState(item.state)
    validate_transition(from_state, QueueState.RUNNING)

    now = _now_iso()
    item.state = QueueState.RUNNING.value
    item.updated_at_utc = now
    item.attempts = list(item.attempts) + [asdict(attempt)]
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event=f"TRANSITION:{from_state.value}->{QueueState.RUNNING.value}",
                at_utc=now,
                detail=f"attempt_id={attempt.attempt_id}",
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


def finalize_attempt(
    queue_root: Path,
    item_id: str,
    attempt_id: str,
    *,
    to_state: QueueState,
    status: str,
    ended_at_utc: str,
    runner_state: Optional[str],
    runner_exit_code: Optional[int],
    runner_run_id: Optional[str],
    runner_evidence_dir: Optional[str],
    detail: Optional[str] = None,
) -> QueueItem:
    """Atomically transitions RUNNING->`to_state` and finalizes the matching
    attempt record in the same write, so item.json can never claim a
    terminal/manual-reconciliation queue state while its corresponding
    attempt still shows status="RUNNING"."""
    item = load_item(queue_root, item_id)
    from_state = QueueState(item.state)
    validate_transition(from_state, to_state)

    updated_attempts = []
    found = False
    for raw in item.attempts:
        if raw.get("attempt_id") == attempt_id:
            found = True
            raw = dict(raw)
            raw["ended_at_utc"] = ended_at_utc
            raw["status"] = status
            raw["runner_state"] = runner_state
            raw["runner_exit_code"] = runner_exit_code
            raw["runner_run_id"] = runner_run_id
            raw["runner_evidence_dir"] = runner_evidence_dir
            raw["final_queue_state"] = to_state.value
        updated_attempts.append(raw)
    if not found:
        raise QueueError(
            "MISSING_ATTEMPT", f"Attempt {attempt_id!r} not found on item {item_id!r}"
        )

    now = _now_iso()
    item.attempts = updated_attempts
    item.state = to_state.value
    item.updated_at_utc = now
    item.history = list(item.history) + [
        asdict(
            QueueEvent(
                event=f"TRANSITION:{from_state.value}->{to_state.value}",
                at_utc=now,
                detail=detail or f"attempt_id={attempt_id}",
            )
        )
    ]
    _atomic_write_json(_item_metadata_path(queue_root, item_id), _item_to_dict(item))
    return item


# ---------------------------------------------------------------------------
# OS advisory exclusive lock
# ---------------------------------------------------------------------------

class QueueLockError(Exception):
    pass


class QueueLock:
    """Real OS advisory exclusive lock over one lock file inside the queue
    root, using fcntl.flock on POSIX and msvcrt.locking on Windows.
    PID/hostname/timestamps written into the file are diagnostic only -
    they are never consulted to decide whether the lock is held; only the
    OS lock call itself decides that. A second process cannot acquire this
    lock while the first holds it, and process death releases it through
    OS semantics (the OS releases file locks when the owning process exits
    or its file descriptor is closed, even on a crash)."""

    def __init__(self, queue_root: Path):
        self.queue_root = Path(queue_root).resolve()
        self.lock_path = self.queue_root / LOCK_FILENAME
        self._fh = None

    @property
    def is_held(self) -> bool:
        return self._fh is not None

    def acquire(self, blocking: bool = False) -> None:
        self.queue_root.mkdir(parents=True, exist_ok=True)
        # Never truncate an existing lock file (another process may be
        # about to lock it); only create it if it does not exist yet.
        if not self.lock_path.exists():
            with open(self.lock_path, "ab"):
                pass
        fh = open(self.lock_path, "r+b")
        try:
            # msvcrt.locking requires at least one byte to lock, and an
            # existing-but-empty lock file (e.g. left by a prior version,
            # or a process that created it but crashed before writing to
            # it) must not silently fail to lock. Guarantee >=1 byte here
            # rather than only at creation time.
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"\0")
                fh.flush()
                fh.seek(0)
            if platform.system() == "Windows":
                import msvcrt

                mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), mode, 1)
                except OSError as exc:
                    fh.close()
                    raise QueueLockError(f"Could not acquire queue lock: {exc}") from exc
            else:
                import fcntl

                flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    fcntl.flock(fh.fileno(), flags)
                except OSError as exc:
                    fh.close()
                    raise QueueLockError(f"Could not acquire queue lock: {exc}") from exc
        except BaseException:
            fh.close()
            raise
        self._fh = fh
        try:
            self._fh.seek(0)
            self._fh.write(b"\0")
            diag = f"pid={os.getpid()} host={socket.gethostname()} at={_now_iso()}\n".encode(
                "utf-8"
            )
            self._fh.write(diag)
            self._fh.flush()
        except OSError:
            pass

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if platform.system() == "Windows":
                import msvcrt

                try:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "QueueLock":
        self.acquire(blocking=False)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Crash recovery (orphaned RUNNING items)
# ---------------------------------------------------------------------------

def recover_orphaned_running_items(
    queue_root: Path, *, lock: QueueLock
) -> list:
    """Recover orphaned RUNNING items only under the real exclusive OS lock.

    The caller must pass the QueueLock instance that it currently owns for
    this exact queue root. This makes the single-worker recovery precondition
    executable rather than a docstring-only convention.
    """
    resolved_root = Path(queue_root).resolve()
    if not isinstance(lock, QueueLock) or not lock.is_held:
        raise QueueLockError(
            "Orphan recovery requires an actively held exclusive QueueLock"
        )
    if lock.queue_root != resolved_root:
        raise QueueLockError(
            "QueueLock belongs to a different queue root; orphan recovery refused"
        )

    recovered = []
    for item in list_items(queue_root):
        if QueueState(item.state) != QueueState.RUNNING:
            continue

        recovery_detail = (
            "orphaned-RUNNING: item was RUNNING when the current process "
            "acquired the exclusive queue lock, indicating a previous "
            "owner did not reach a terminal state (crash or kill); "
            "recovered fail-closed rather than requeued/retried because "
            "a partial authorized repository change may exist"
        )

        # Pre-1.5D schema-v1 items may legitimately have no attempt record.
        # Preserve that backward-compatible recovery path.
        if not item.attempts:
            recovered_item = transition_item(
                queue_root,
                item.item_id,
                QueueState.BLOCKED_ON_CHECKPOINT,
                detail=recovery_detail,
            )
            recovered.append(recovered_item)
            continue

        # RUNNER-1.5D+: a crashed worker may leave exactly one active RUNNING
        # attempt. Recovery must finalize that same attempt atomically with
        # RUNNING -> BLOCKED_ON_CHECKPOINT; otherwise durable state would claim
        # the item is blocked while its corresponding attempt remains RUNNING.
        running_attempts = [
            raw for raw in item.attempts
            if isinstance(raw, dict) and raw.get("status") == "RUNNING"
        ]
        if len(running_attempts) != 1:
            raise QueueError(
                "CORRUPT_ATTEMPT",
                f"RUNNING item {item.item_id!r} has {len(running_attempts)} "
                "RUNNING attempts; orphan recovery refused fail-closed",
            )

        attempt_id = running_attempts[0].get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise QueueError(
                "CORRUPT_ATTEMPT",
                f"RUNNING item {item.item_id!r} has an invalid active attempt_id",
            )

        recovered_item = finalize_attempt(
            queue_root,
            item.item_id,
            attempt_id,
            to_state=QueueState.BLOCKED_ON_CHECKPOINT,
            status="ORPHANED",
            ended_at_utc=_now_iso(),
            runner_state=None,
            runner_exit_code=None,
            runner_run_id=None,
            runner_evidence_dir=None,
            detail=recovery_detail,
        )
        recovered.append(recovered_item)

    return recovered


# ---------------------------------------------------------------------------
# Single-worker run-next (RUNNER-1.5D)
# ---------------------------------------------------------------------------

def _build_work_order_request(queue_root: Path, item: QueueItem) -> "claude_runner.WorkOrderRequest":
    """Builds exactly one claude_runner.WorkOrderRequest from durable queue
    data: the durable item work_order.txt path (never the original enqueue
    source), the persisted mode/authorize_path/model/label, and timeout
    only when the item explicitly requested one (otherwise the Runner's own
    default applies)."""
    work_order_path = _item_dir(queue_root, item.item_id) / item.work_order_filename
    kwargs = dict(
        repo=item.repository_path,
        work_order=str(work_order_path),
        mode=item.mode,
        authorize_path=list(item.authorize_path),
        model=item.model,
        label=item.label,
    )
    if item.timeout_seconds is not None:
        kwargs["timeout_seconds"] = item.timeout_seconds
    return claude_runner.WorkOrderRequest(**kwargs)


def _verify_write_evidence_mutation(item: QueueItem, result: "claude_runner.WorkOrderResult"):
    """Returns True/False for a post-invocation write-mode attempt's
    verified `safety_check.repository_mutated`, or None if the Runner
    evidence cannot be trusted (missing, unreadable, malformed, or
    inconsistent with the returned run_id/evidence_dir/state) - callers
    must fail closed to FAILED_SAFETY on None rather than guess."""
    if result.evidence_dir is None or result.run_id is None:
        return None
    try:
        evidence_dir = Path(result.evidence_dir).resolve()
    except OSError:
        return None
    if not evidence_dir.is_dir() or evidence_dir.name != result.run_id:
        return None

    try:
        expected_base = (Path(item.repository_path).resolve() / claude_runner.RUNTIME_SUBDIR).resolve()
        evidence_dir.relative_to(expected_base)
    except (OSError, ValueError):
        return None

    result_json_path = evidence_dir / "result.json"
    if not result_json_path.exists():
        return None
    try:
        payload = json.loads(result_json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if payload.get("state") != result.state.value:
        return None
    safety_check = payload.get("safety_check")
    if not isinstance(safety_check, dict):
        return None
    mutated = safety_check.get("repository_mutated")
    if not isinstance(mutated, bool):
        return None
    return mutated


def _map_runner_result_to_queue_state(
    item: QueueItem, result: "claude_runner.WorkOrderResult"
) -> QueueState:
    """Fail-closed result mapping (RUNNER-1.5D).

    RunState.FAILED_SAFETY always maps to FAILED_SAFETY, unconditionally.
    A deterministic pre-invocation Runner refusal (WorkOrderResult.error_
    message set - the Work Order file was never sent to Claude) maps to
    FAILED. Otherwise, an actual invocation happened: in write mode the
    verified repository_mutated flag from the Runner's own evidence always
    takes precedence over the process result - a mutated tree always maps
    to BLOCKED_ON_CHECKPOINT (human reconciliation required before another
    write invocation can satisfy the clean-tree invariant), an unmutated
    tree maps to SUCCEEDED only on RunState.SUCCESS and FAILED otherwise;
    read-only maps RunState.SUCCESS to SUCCEEDED and anything else to
    FAILED (FAILED_SAFETY already handled above).
    """
    if result.state == claude_runner.RunState.FAILED_SAFETY:
        return QueueState.FAILED_SAFETY
    if result.error_message is not None:
        return QueueState.FAILED

    if item.mode == claude_runner.MODE_WRITE:
        mutated = _verify_write_evidence_mutation(item, result)
        if mutated is None:
            return QueueState.FAILED_SAFETY
        if mutated:
            return QueueState.BLOCKED_ON_CHECKPOINT
        return QueueState.SUCCEEDED if result.state == claude_runner.RunState.SUCCESS else QueueState.FAILED

    return QueueState.SUCCEEDED if result.state == claude_runner.RunState.SUCCESS else QueueState.FAILED


class RunNextOutcome(str, Enum):
    NO_WORK = "NO_WORK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    DISPATCHED = "DISPATCHED"


@dataclass
class RunNextResult:
    outcome: str
    item_id: Optional[str] = None
    attempt_id: Optional[str] = None
    queue_state: Optional[str] = None
    runner_state: Optional[str] = None
    recovered_item_ids: list = field(default_factory=list)


def run_next(
    queue_root: Path,
    *,
    executor=None,
    wait_for_lock: bool = False,
) -> RunNextResult:
    """Single-worker run-next (RUNNER-1.5D).

    Acquires the exclusive QueueLock and holds it for the complete dispatch
    lifecycle (orphan recovery through final queue-state persistence), so a
    second worker can never execute concurrently. Immediately recovers
    orphaned RUNNING items under that same held lock; if any were
    recovered, stops and dispatches nothing this call (deterministic
    RECOVERY_REQUIRED), so an operator can reconcile checkpoints first. If
    none were recovered, selects the first QUEUED item in the existing
    deterministic order (or returns NO_WORK without invoking anything),
    atomically transitions it QUEUED->RUNNING with a durable attempt record
    visible before the executor runs, invokes the executor (by default
    claude_runner.execute_work_order - the sole place any Runner branch/
    dirty-tree/write-scope/safety guard lives), and finalizes the attempt
    and queue state atomically from the fail-closed result mapping. An
    executor that raises instead of returning a WorkOrderResult is treated
    as an uncertain outcome and finalized fail-closed to
    BLOCKED_ON_CHECKPOINT without any automatic second attempt.
    """
    if executor is None:
        executor = claude_runner.execute_work_order

    lock = QueueLock(queue_root)
    lock.acquire(blocking=wait_for_lock)
    try:
        recovered = recover_orphaned_running_items(queue_root, lock=lock)
        if recovered:
            return RunNextResult(
                outcome=RunNextOutcome.RECOVERY_REQUIRED.value,
                recovered_item_ids=[it.item_id for it in recovered],
            )

        queued = [it for it in list_items(queue_root) if QueueState(it.state) == QueueState.QUEUED]
        if not queued:
            return RunNextResult(outcome=RunNextOutcome.NO_WORK.value)

        selected = queued[0]
        attempt_id = generate_attempt_id()
        attempt = QueueAttempt(
            attempt_id=attempt_id,
            started_at_utc=_now_iso(),
            ended_at_utc=None,
            status="RUNNING",
            runner_state=None,
            runner_exit_code=None,
            runner_run_id=None,
            runner_evidence_dir=None,
            final_queue_state=None,
        )
        item = start_attempt(queue_root, selected.item_id, attempt)
        request = _build_work_order_request(queue_root, item)

        try:
            result = executor(request)
        except Exception as exc:
            item = finalize_attempt(
                queue_root, item.item_id, attempt_id,
                to_state=QueueState.BLOCKED_ON_CHECKPOINT,
                status="EXCEPTION",
                ended_at_utc=_now_iso(),
                runner_state=None,
                runner_exit_code=None,
                runner_run_id=None,
                runner_evidence_dir=None,
                detail=(
                    f"executor raised {type(exc).__name__}: {exc}; execution outcome "
                    "is uncertain, recovered fail-closed without an automatic retry"
                ),
            )
            return RunNextResult(
                outcome=RunNextOutcome.DISPATCHED.value,
                item_id=item.item_id,
                attempt_id=attempt_id,
                queue_state=item.state,
                runner_state=None,
            )

        to_state = _map_runner_result_to_queue_state(item, result)
        item = finalize_attempt(
            queue_root, item.item_id, attempt_id,
            to_state=to_state,
            status="COMPLETED",
            ended_at_utc=_now_iso(),
            runner_state=result.state.value,
            runner_exit_code=result.exit_code,
            runner_run_id=result.run_id,
            runner_evidence_dir=str(result.evidence_dir) if result.evidence_dir else None,
            detail=result.error_message,
        )
        return RunNextResult(
            outcome=RunNextOutcome.DISPATCHED.value,
            item_id=item.item_id,
            attempt_id=attempt_id,
            queue_state=item.state,
            runner_state=result.state.value,
        )
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_repo_path() -> str:
    return str(Path.cwd())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude_queue",
        description=(
            "Durable single-worker queue and governed run-next dispatcher for "
            "Claude Runner V1.5 (RUNNER-1.5D). May execute at most one queued "
            "Work Order per run-next through claude_runner.execute_work_order; "
            "does not classify quota, replay checkpoints, retry automatically, "
            "commit, push, merge, switch branches, create worktrees, or "
            "schedule multiple workers."
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

    enqueue_p = subparsers.add_parser("enqueue", help="Enqueue one Work Order.")
    enqueue_p.add_argument("--work-order", required=True, help="Path to a UTF-8 Work Order text file.")
    enqueue_p.add_argument("--repository-path", required=True, help="Target repository path for this item.")
    enqueue_p.add_argument("--mode", default="read-only", help="Requested execution mode (default: read-only).")
    enqueue_p.add_argument("--authorize-path", dest="authorize_path", action="append", default=None)
    enqueue_p.add_argument("--timeout-seconds", type=int, default=None)
    enqueue_p.add_argument("--model", default=None)
    enqueue_p.add_argument("--label", default=None)

    subparsers.add_parser("status", help="List all queue items (deterministic order).")

    recover_p = subparsers.add_parser(
        "recover", help="Acquire the exclusive queue lock and recover orphaned RUNNING items."
    )
    recover_p.add_argument("--wait", action="store_true", help="Block until the lock is available.")

    run_next_p = subparsers.add_parser(
        "run-next",
        help=(
            "Acquire the exclusive queue lock, recover orphaned RUNNING "
            "items if any (stopping without dispatch when it does), "
            "otherwise execute at most one QUEUED item through the "
            "governed Claude Runner."
        ),
    )
    run_next_p.add_argument(
        "--wait", action="store_true", help="Block until the queue lock is available."
    )

    return parser


def _resolve_queue_root_from_args(args: argparse.Namespace) -> Path:
    repo = Path(args.repo).resolve() if args.repo else Path(_default_repo_path()).resolve()
    return resolve_queue_root(repo, args.queue_root)


def _cmd_enqueue(args: argparse.Namespace) -> int:
    wo_path = Path(args.work_order)
    try:
        text = wo_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: could not read Work Order file as UTF-8: {exc}", file=sys.stderr)
        return 11
    queue_root = _resolve_queue_root_from_args(args)
    try:
        item = enqueue(
            queue_root,
            work_order_text=text,
            repository_path=args.repository_path,
            mode=args.mode,
            authorize_path=args.authorize_path,
            timeout_seconds=args.timeout_seconds,
            model=args.model,
            label=args.label,
        )
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    print(f"item_id={item.item_id} state={item.state}")
    print(f"queue_root={queue_root}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        items = list_items(queue_root)
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1
    for item in items:
        print(f"{item.item_id}\t{item.state}\t{item.created_at_utc}\t{item.repository_path}")
    return 0


def _cmd_recover(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    lock = QueueLock(queue_root)
    try:
        lock.acquire(blocking=args.wait)
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        try:
            recovered = recover_orphaned_running_items(queue_root, lock=lock)
        except QueueError as exc:
            print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
            return 1
    finally:
        lock.release()
    for item in recovered:
        print(f"recovered item_id={item.item_id} -> {item.state}")
    print(f"recovered_count={len(recovered)}")
    return 0


def _cmd_run_next(args: argparse.Namespace) -> int:
    queue_root = _resolve_queue_root_from_args(args)
    try:
        result = run_next(queue_root, wait_for_lock=args.wait)
    except QueueLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except QueueError as exc:
        print(f"error: {exc.reason}: {exc.message}", file=sys.stderr)
        return 1

    if result.outcome == RunNextOutcome.NO_WORK.value:
        print("outcome=NO_WORK")
        return 0
    if result.outcome == RunNextOutcome.RECOVERY_REQUIRED.value:
        print(
            "outcome=RECOVERY_REQUIRED recovered_item_ids="
            + ",".join(result.recovered_item_ids)
        )
        return 0
    print(
        f"outcome=DISPATCHED item_id={result.item_id} attempt_id={result.attempt_id} "
        f"queue_state={result.queue_state} runner_state={result.runner_state}"
    )
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "enqueue":
        return _cmd_enqueue(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "recover":
        return _cmd_recover(args)
    if args.command == "run-next":
        return _cmd_run_next(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
