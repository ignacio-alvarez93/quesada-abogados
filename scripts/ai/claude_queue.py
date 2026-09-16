"""Durable single-worker queue storage foundation for Claude Runner V1.5.

RUNNER-1.5C: persistence only. This module does NOT invoke Claude, does NOT
classify quota errors, does NOT replay checkpoints, does NOT retry, and does
NOT commit/push/merge/switch branches/create worktrees or schedule multiple
workers. It exists so a future single worker (RUNNER-1.5D+) has a durable,
crash-safe place to enqueue Work Orders and record their state.

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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


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
        recovered.append(
            transition_item(
                queue_root,
                item.item_id,
                QueueState.BLOCKED_ON_CHECKPOINT,
                detail=(
                    "orphaned-RUNNING: item was RUNNING when the current process "
                    "acquired the exclusive queue lock, indicating a previous "
                    "owner did not reach a terminal state (crash or kill); "
                    "recovered fail-closed rather than requeued/retried because "
                    "a partial authorized repository change may exist"
                ),
            )
        )
    return recovered


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_repo_path() -> str:
    return str(Path.cwd())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude_queue",
        description=(
            "Durable single-worker queue storage foundation for Claude Runner "
            "V1.5 (RUNNER-1.5C). Persistence only: does not invoke Claude, "
            "classify quota, replay checkpoints, retry, commit, push, merge, "
            "switch branches, create worktrees, or schedule multiple workers."
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


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "enqueue":
        return _cmd_enqueue(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "recover":
        return _cmd_recover(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
