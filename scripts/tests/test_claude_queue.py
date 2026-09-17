import hashlib
import inspect
import json
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import claude_queue as queue
from scripts.ai import claude_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_git_cmd(args: list, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed in {cwd}: {result.stderr}")
    return result


def _init_git_repo(path: Path) -> None:
    """Real, minimal git repository fixture (RUNNER-1.5E checkpoint tests
    exercise real `git` subprocess calls, never a fake/mocked repository)."""
    path.mkdir(parents=True, exist_ok=True)
    _run_git_cmd(["init", "-q"], cwd=path)
    _run_git_cmd(["config", "user.email", "test@example.com"], cwd=path)
    _run_git_cmd(["config", "user.name", "Test"], cwd=path)

    # Claude Runner evidence is runtime infrastructure, not repository work.
    # Production repositories keep runtime/claude_runner outside Git status;
    # mirror that invariant in temporary Git fixtures without introducing a
    # tracked .gitignore file that could affect checkpoint assertions.
    exclude_path = path / ".git" / "info" / "exclude"
    with exclude_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n/runtime/claude_runner/\n")

    (path / ".gitkeep").write_text("keep\n", encoding="utf-8")
    _run_git_cmd(["add", "."], cwd=path)
    _run_git_cmd(["commit", "-q", "-m", "initial"], cwd=path)


class _TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.queue_root = self.root / "queue"

    def tearDown(self):
        self._tmp.cleanup()


class _RecordingExecutor:
    """Fake executor (RUNNER-1.5D dependency injection): records every
    WorkOrderRequest it was called with and returns a preset
    WorkOrderResult, so tests never invoke the real Claude CLI."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        return self.result


def _explode_if_called(request):
    raise AssertionError("executor must not run in this scenario")


def _write_evidence(repo_dir: Path, run_id: str, *, state: str, repository_mutated) -> Path:
    evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / run_id
    evidence_dir.mkdir(parents=True)
    payload = {"state": state, "safety_check": {"repository_mutated": repository_mutated}}
    (evidence_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    return evidence_dir


def _write_evidence_with_cli_output(
    repo_dir: Path, run_id: str, *, state: str, repository_mutated, cli_output, stderr_text=None,
) -> Path:
    """Like `_write_evidence` but also carries a `cli_output` field (parsed
    Claude CLI JSON, or a `{"parsed": False, ...}` failure marker) and,
    optionally, a `stderr.txt` file - the two trustworthy evidence channels
    RUNNER-1.5F-A's quota classifier is allowed to read."""
    evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / run_id
    evidence_dir.mkdir(parents=True)
    payload = {
        "state": state,
        "safety_check": {"repository_mutated": repository_mutated},
        "cli_output": cli_output,
    }
    (evidence_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    if stderr_text is not None:
        (evidence_dir / "stderr.txt").write_text(stderr_text, encoding="utf-8")
    return evidence_dir


# The only structural signal RUNNER-1.5F-A's default classifier trusts,
# reused across tests to build CONFIRMED_QUOTA evidence.
_CONFIRMED_QUOTA_CLI_OUTPUT = {
    "parsed": True,
    "cli_result": {"is_error": True, "result": "Claude AI usage limit reached|1700000000"},
}


def _make_confirmed_quota_item(root: Path, queue_root: Path, *, repo_name="repo", epoch=None, epoch_str=None):
    """Drives one item through a real `run_next()` dispatch to a genuine
    CONFIRMED_QUOTA WAITING_QUOTA state (RUNNER-1.5F-B2A supervisor tests),
    with a caller-controlled provider epoch so tests can produce a due,
    not-yet-due, or manual-only (unrepresentable epoch) barrier item through
    the same real classification/persistence path production uses."""
    repo_dir = root / repo_name
    _init_git_repo(repo_dir)
    item = queue.enqueue(
        queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
    )
    run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
    epoch_text = epoch_str if epoch_str is not None else str(epoch)
    cli_output = {
        "parsed": True,
        "cli_result": {"is_error": True, "result": f"Claude AI usage limit reached|{epoch_text}"},
    }
    evidence_dir = _write_evidence_with_cli_output(
        repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False, cli_output=cli_output,
    )
    executor = _RecordingExecutor(runner.WorkOrderResult(
        state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
        evidence_dir=evidence_dir, error_message=None,
    ))
    result = queue.run_next(queue_root, executor=executor)
    assert result.queue_state == queue.QueueState.WAITING_QUOTA.value
    return repo_dir, item


class ResolveQueueRootTest(_TempDirCase):
    def test_default_is_under_repo_runtime_claude_runner_queue(self):
        repo = self.root / "repo"
        repo.mkdir()
        resolved = queue.resolve_queue_root(repo, None)
        self.assertEqual(resolved, (repo / "runtime" / "claude_runner" / "queue").resolve())

    def test_explicit_override_is_used_verbatim(self):
        repo = self.root / "repo"
        repo.mkdir()
        override = self.root / "custom_queue_location"
        resolved = queue.resolve_queue_root(repo, str(override))
        self.assertEqual(resolved, override.resolve())


# ---------------------------------------------------------------------------
# Enqueue: validation, durable copy, hash integrity
# ---------------------------------------------------------------------------

class EnqueueValidationTest(_TempDirCase):
    def test_empty_source_rejected(self):
        with self.assertRaises(queue.QueueError) as ctx:
            queue.enqueue(
                self.queue_root, work_order_text="   \n", repository_path="repo", mode="read-only",
            )
        self.assertEqual(ctx.exception.reason, "INVALID_WORK_ORDER")

    def test_non_string_rejected(self):
        with self.assertRaises(queue.QueueError):
            queue.enqueue(
                self.queue_root, work_order_text=None, repository_path="repo", mode="read-only",
            )

    def test_oversized_source_rejected(self):
        text = "x" * (queue.MAX_WORK_ORDER_CHARS + 1)
        with self.assertRaises(queue.QueueError):
            queue.enqueue(
                self.queue_root, work_order_text=text, repository_path="repo", mode="read-only",
            )

    def test_valid_source_returns_queued_item(self):
        item = queue.enqueue(
            self.queue_root,
            work_order_text="Do the thing.\n",
            repository_path="C:/repo",
            mode="read-only",
        )
        self.assertEqual(item.state, queue.QueueState.QUEUED.value)
        self.assertEqual(item.schema_version, queue.SCHEMA_VERSION)


class DurableCopyTest(_TempDirCase):
    def test_work_order_survives_source_deletion_ascii(self):
        source = self.root / "source_wo.txt"
        text = "Report a deterministic repository fact.\n"
        source.write_text(text, encoding="utf-8")

        read_text = source.read_text(encoding="utf-8")
        item = queue.enqueue(
            self.queue_root, work_order_text=read_text, repository_path="repo", mode="read-only",
        )
        source.unlink()
        self.assertFalse(source.exists())

        loaded = queue.load_item(self.queue_root, item.item_id)
        stored_path = self.queue_root / loaded.item_id / loaded.work_order_filename
        self.assertEqual(stored_path.read_text(encoding="utf-8"), text)

    def test_work_order_survives_source_deletion_unicode(self):
        source = self.root / "source_wo_unicode.txt"
        text = "Trabaja con expedientes: áéíóú ñ 中文 🚀 — em dash\n"
        source.write_text(text, encoding="utf-8")

        read_text = source.read_text(encoding="utf-8")
        item = queue.enqueue(
            self.queue_root, work_order_text=read_text, repository_path="repo", mode="read-only",
        )
        source.unlink()

        stored_path = self.queue_root / item.item_id / item.work_order_filename
        stored_bytes = stored_path.read_bytes()
        self.assertEqual(stored_bytes, text.encode("utf-8"))
        expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(item.work_order_sha256, expected_hash)

        loaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(loaded.work_order_sha256, expected_hash)

    def test_queue_root_does_not_reference_source_directory(self):
        source_dir = self.root / "external_source"
        source_dir.mkdir()
        source = source_dir / "wo.txt"
        source.write_text("content\n", encoding="utf-8")

        item = queue.enqueue(
            self.queue_root,
            work_order_text=source.read_text(encoding="utf-8"),
            repository_path="repo",
            mode="read-only",
        )
        import shutil

        shutil.rmtree(source_dir)
        self.assertFalse(source_dir.exists())

        # Fully reloading from disk must still succeed with no dependency
        # on the now-deleted external source directory.
        loaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(loaded.item_id, item.item_id)


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------

class AtomicityTest(_TempDirCase):
    def test_publication_leaves_no_staging_directory(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        entries = list(self.queue_root.iterdir())
        staging_dirs = [e for e in entries if e.name.startswith(".")]
        self.assertEqual(staging_dirs, [])

    def test_item_directory_contains_both_files_atomically(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        item_dir = self.queue_root / item.item_id
        self.assertTrue((item_dir / queue.ITEM_METADATA_FILENAME).exists())
        self.assertTrue((item_dir / item.work_order_filename).exists())

    def test_transition_leaves_no_tmp_files(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        item_dir = self.queue_root / item.item_id
        names = sorted(p.name for p in item_dir.iterdir())
        self.assertEqual(names, sorted([queue.ITEM_METADATA_FILENAME, item.work_order_filename]))

    def test_failed_replace_does_not_corrupt_existing_metadata(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        original_replace = queue.os.replace

        def _boom(*args, **kwargs):
            raise OSError("simulated crash during os.replace")

        queue.os.replace = _boom
        try:
            with self.assertRaises(OSError):
                queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        finally:
            queue.os.replace = original_replace

        # The pre-existing item.json must still be intact and loadable.
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.QUEUED.value)


# ---------------------------------------------------------------------------
# Deterministic listing
# ---------------------------------------------------------------------------

class ListingTest(_TempDirCase):
    def test_listing_is_sorted_by_created_at_then_item_id(self):
        fixed_times = iter([
            "2026-09-16T00:00:00+00:00",
            "2026-09-16T00:00:01+00:00",
            "2026-09-16T00:00:01+00:00",
        ])
        original_now = queue._now_iso
        try:
            queue._now_iso = lambda: next(fixed_times)
            first = queue.enqueue(
                self.queue_root, work_order_text="a\n", repository_path="repo", mode="read-only",
            )
            second = queue.enqueue(
                self.queue_root, work_order_text="b\n", repository_path="repo", mode="read-only",
            )
            third = queue.enqueue(
                self.queue_root, work_order_text="c\n", repository_path="repo", mode="read-only",
            )
        finally:
            queue._now_iso = original_now

        items = queue.list_items(self.queue_root)
        self.assertEqual([it.item_id for it in items][0], first.item_id)
        tied = sorted([second.item_id, third.item_id])
        self.assertEqual([it.item_id for it in items][1:], tied)

    def test_listing_deterministic_across_repeated_calls(self):
        for i in range(4):
            queue.enqueue(
                self.queue_root, work_order_text=f"wo {i}\n", repository_path="repo", mode="read-only",
            )
        first_call = [it.item_id for it in queue.list_items(self.queue_root)]
        second_call = [it.item_id for it in queue.list_items(self.queue_root)]
        self.assertEqual(first_call, second_call)

    def test_empty_queue_root_returns_empty_list(self):
        self.assertEqual(queue.list_items(self.queue_root), [])

    def test_corrupt_item_fails_closed_in_listing(self):
        queue.enqueue(
            self.queue_root, work_order_text="good\n", repository_path="repo", mode="read-only",
        )
        bad_dir = self.queue_root / "bad-item"
        bad_dir.mkdir()
        (bad_dir / queue.ITEM_METADATA_FILENAME).write_text("not json", encoding="utf-8")

        with self.assertRaises(queue.QueueError) as ctx:
            queue.list_items(self.queue_root)
        self.assertEqual(ctx.exception.reason, "CORRUPT_METADATA")


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------

class TransitionValidationTest(unittest.TestCase):
    def test_queued_to_running_allowed(self):
        queue.validate_transition(queue.QueueState.QUEUED, queue.QueueState.RUNNING)

    def test_running_may_reach_each_terminal_or_waiting_state(self):
        for target in (
            queue.QueueState.WAITING_QUOTA,
            queue.QueueState.BLOCKED_ON_CHECKPOINT,
            queue.QueueState.SUCCEEDED,
            queue.QueueState.FAILED,
            queue.QueueState.FAILED_SAFETY,
        ):
            queue.validate_transition(queue.QueueState.RUNNING, target)

    def test_queued_to_succeeded_is_illegal(self):
        with self.assertRaises(queue.QueueError) as ctx:
            queue.validate_transition(queue.QueueState.QUEUED, queue.QueueState.SUCCEEDED)
        self.assertEqual(ctx.exception.reason, "ILLEGAL_TRANSITION")

    def test_failed_safety_is_never_retryable(self):
        for target in queue.QueueState:
            with self.assertRaises(queue.QueueError):
                queue.validate_transition(queue.QueueState.FAILED_SAFETY, target)

    def test_succeeded_and_failed_are_terminal(self):
        for source in (queue.QueueState.SUCCEEDED, queue.QueueState.FAILED):
            for target in queue.QueueState:
                with self.assertRaises(queue.QueueError):
                    queue.validate_transition(source, target)

    def test_waiting_quota_does_not_silently_return_to_queued(self):
        with self.assertRaises(queue.QueueError):
            queue.validate_transition(queue.QueueState.WAITING_QUOTA, queue.QueueState.QUEUED)
        with self.assertRaises(queue.QueueError):
            queue.validate_transition(queue.QueueState.WAITING_QUOTA, queue.QueueState.RUNNING)

    def test_blocked_on_checkpoint_does_not_silently_return_to_queued(self):
        with self.assertRaises(queue.QueueError):
            queue.validate_transition(queue.QueueState.BLOCKED_ON_CHECKPOINT, queue.QueueState.QUEUED)
        with self.assertRaises(queue.QueueError):
            queue.validate_transition(queue.QueueState.BLOCKED_ON_CHECKPOINT, queue.QueueState.RUNNING)

    def test_self_transition_is_illegal(self):
        with self.assertRaises(queue.QueueError):
            queue.validate_transition(queue.QueueState.QUEUED, queue.QueueState.QUEUED)


class TransitionItemTest(_TempDirCase):
    def test_transition_persists_new_state_and_history_event(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        updated = queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        self.assertEqual(updated.state, queue.QueueState.RUNNING.value)
        self.assertGreater(len(updated.history), 1)
        self.assertIn("QUEUED->RUNNING", updated.history[-1]["event"])

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.RUNNING.value)

    def test_illegal_transition_raises_and_does_not_persist(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        with self.assertRaises(queue.QueueError):
            queue.transition_item(self.queue_root, item.item_id, queue.QueueState.SUCCEEDED)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.QUEUED.value)


# ---------------------------------------------------------------------------
# Fail-closed integrity checks
# ---------------------------------------------------------------------------

class IntegrityFailClosedTest(_TempDirCase):
    def _make_raw_item(self, item_id, overrides=None, write_work_order=True):
        item_dir = self.queue_root / item_id
        item_dir.mkdir(parents=True)
        wo_text = "content\n"
        if write_work_order:
            (item_dir / queue.WORK_ORDER_FILENAME).write_bytes(wo_text.encode("utf-8"))
        payload = {
            "schema_version": queue.SCHEMA_VERSION,
            "item_id": item_id,
            "created_at_utc": "2026-09-16T00:00:00+00:00",
            "updated_at_utc": "2026-09-16T00:00:00+00:00",
            "state": queue.QueueState.QUEUED.value,
            "repository_path": "repo",
            "mode": "read-only",
            "authorize_path": [],
            "timeout_seconds": None,
            "model": None,
            "label": None,
            "work_order_filename": queue.WORK_ORDER_FILENAME,
            "work_order_sha256": hashlib.sha256(wo_text.encode("utf-8")).hexdigest(),
            "history": [],
        }
        if overrides:
            payload.update(overrides)
        (item_dir / queue.ITEM_METADATA_FILENAME).write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return item_dir

    def test_malformed_json_fails_closed(self):
        item_dir = self.queue_root / "bad"
        item_dir.mkdir(parents=True)
        (item_dir / queue.ITEM_METADATA_FILENAME).write_text("{not json", encoding="utf-8")
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "bad")
        self.assertEqual(ctx.exception.reason, "CORRUPT_METADATA")

    def test_missing_required_field_fails_closed(self):
        self._make_raw_item("missing-field", overrides={"state": None})
        # Remove a required field entirely rather than nulling it.
        path = self.queue_root / "missing-field" / queue.ITEM_METADATA_FILENAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["mode"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "missing-field")
        self.assertEqual(ctx.exception.reason, "SCHEMA_MISMATCH")

    def test_unknown_schema_version_fails_closed(self):
        self._make_raw_item("bad-schema", overrides={"schema_version": 999})
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "bad-schema")
        self.assertEqual(ctx.exception.reason, "SCHEMA_MISMATCH")

    def test_unknown_state_fails_closed(self):
        self._make_raw_item("bad-state", overrides={"state": "NOT_A_REAL_STATE"})
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "bad-state")
        self.assertEqual(ctx.exception.reason, "SCHEMA_MISMATCH")

    def test_missing_work_order_file_fails_closed(self):
        self._make_raw_item("no-wo", write_work_order=False)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "no-wo")
        self.assertEqual(ctx.exception.reason, "MISSING_WORK_ORDER")

    def test_hash_mismatch_fails_closed(self):
        item_dir = self._make_raw_item("bad-hash")
        (item_dir / queue.WORK_ORDER_FILENAME).write_text("tampered content\n", encoding="utf-8")
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "bad-hash")
        self.assertEqual(ctx.exception.reason, "HASH_MISMATCH")

    def test_item_id_mismatch_fails_closed(self):
        self._make_raw_item("dir-name", overrides={"item_id": "different-id"})
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "dir-name")
        self.assertEqual(ctx.exception.reason, "ITEM_ID_MISMATCH")

    def test_item_id_path_traversal_is_rejected(self):
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "../outside")
        self.assertEqual(ctx.exception.reason, "INVALID_ITEM_ID")

        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "..\\outside")
        self.assertEqual(ctx.exception.reason, "INVALID_ITEM_ID")

    def test_work_order_filename_is_schema_fixed_and_cannot_escape_item_dir(self):
        self._make_raw_item(
            "bad-work-order-path",
            overrides={"work_order_filename": "../outside.txt"},
        )
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "bad-work-order-path")
        self.assertEqual(ctx.exception.reason, "SCHEMA_MISMATCH")

    def test_missing_item_directory_fails_closed(self):
        with self.assertRaises(queue.QueueError) as ctx:
            queue.load_item(self.queue_root, "does-not-exist")
        self.assertEqual(ctx.exception.reason, "MISSING_ITEM")


# ---------------------------------------------------------------------------
# Orphan RUNNING recovery
# ---------------------------------------------------------------------------

class OrphanRecoveryTest(_TempDirCase):
    def test_running_item_recovered_to_blocked_on_checkpoint(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)

        with queue.QueueLock(self.queue_root) as lock:
            recovered = queue.recover_orphaned_running_items(self.queue_root, lock=lock)

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].item_id, item.item_id)
        self.assertEqual(recovered[0].state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        last_event = reloaded.history[-1]
        self.assertIn("RUNNING->BLOCKED_ON_CHECKPOINT", last_event["event"])
        self.assertIn("orphaned-RUNNING", last_event["detail"])

    def test_non_running_items_are_left_untouched(self):
        queued_item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        with queue.QueueLock(self.queue_root) as lock:
            recovered = queue.recover_orphaned_running_items(self.queue_root, lock=lock)
        self.assertEqual(recovered, [])
        reloaded = queue.load_item(self.queue_root, queued_item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.QUEUED.value)

    def test_recovered_blocked_item_is_not_automatically_retryable(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        with queue.QueueLock(self.queue_root) as lock:
            queue.recover_orphaned_running_items(self.queue_root, lock=lock)
        with self.assertRaises(queue.QueueError):
            queue.transition_item(self.queue_root, item.item_id, queue.QueueState.QUEUED)
        with self.assertRaises(queue.QueueError):
            queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)


class RecoveryLockPreconditionTest(_TempDirCase):
    def test_recovery_without_held_lock_is_refused(self):
        item = queue.enqueue(
            self.queue_root,
            work_order_text="content\n",
            repository_path="repo",
            mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)

        unheld = queue.QueueLock(self.queue_root)
        with self.assertRaises(queue.QueueLockError):
            queue.recover_orphaned_running_items(self.queue_root, lock=unheld)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.RUNNING.value)

    def test_recovery_with_lock_for_different_root_is_refused(self):
        other_root = self.root / "other-queue"
        with queue.QueueLock(other_root) as wrong_lock:
            with self.assertRaises(queue.QueueLockError):
                queue.recover_orphaned_running_items(
                    self.queue_root, lock=wrong_lock
                )


# ---------------------------------------------------------------------------
# OS advisory exclusive lock
# ---------------------------------------------------------------------------

_LOCK_HOLDER_SCRIPT = """
import sys
import time

sys.path.insert(0, {repo_root!r})

from pathlib import Path
from scripts.ai import claude_queue as queue

lock = queue.QueueLock(Path({queue_root!r}))
lock.acquire(blocking=False)
print("LOCKED", flush=True)
time.sleep({hold_seconds})
"""


class QueueLockContentionTest(_TempDirCase):
    def test_second_in_process_handle_cannot_acquire_while_first_holds(self):
        first = queue.QueueLock(self.queue_root)
        first.acquire(blocking=False)
        try:
            second = queue.QueueLock(self.queue_root)
            with self.assertRaises(queue.QueueLockError):
                second.acquire(blocking=False)
        finally:
            first.release()

    def test_lock_file_contains_at_least_one_byte(self):
        lock = queue.QueueLock(self.queue_root)
        lock.acquire(blocking=False)
        try:
            self.assertGreaterEqual(lock.lock_path.stat().st_size, 1)
        finally:
            lock.release()

    def test_release_allows_reacquisition(self):
        lock = queue.QueueLock(self.queue_root)
        lock.acquire(blocking=False)
        lock.release()
        lock2 = queue.QueueLock(self.queue_root)
        lock2.acquire(blocking=False)
        lock2.release()

    def test_real_second_process_cannot_acquire_while_first_holds_and_death_releases(self):
        script = _LOCK_HOLDER_SCRIPT.format(
            repo_root=str(REPO_ROOT), queue_root=str(self.queue_root), hold_seconds=60,
        )
        script_path = self.root / "lock_holder.py"
        script_path.write_text(script, encoding="utf-8")

        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = proc.stdout.readline()
            self.assertEqual(line.strip(), "LOCKED")

            contender = queue.QueueLock(self.queue_root)
            with self.assertRaises(queue.QueueLockError):
                contender.acquire(blocking=False)
        finally:
            proc.kill()
            proc.wait(timeout=10)

        # Process death must release the OS lock even without an explicit
        # release() call inside the killed process.
        deadline = time.monotonic() + 5
        acquired = False
        last_exc = None
        while time.monotonic() < deadline and not acquired:
            reclaimer = queue.QueueLock(self.queue_root)
            try:
                reclaimer.acquire(blocking=False)
                acquired = True
                reclaimer.release()
            except queue.QueueLockError as exc:
                last_exc = exc
                time.sleep(0.2)
        self.assertTrue(acquired, f"lock was not released after process death: {last_exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class CliTest(_TempDirCase):
    def test_enqueue_status_recover_roundtrip(self):
        wo_path = self.root / "wo.txt"
        wo_path.write_text("Do the thing.\n", encoding="utf-8")

        code = queue.main([
            "--queue-root", str(self.queue_root),
            "enqueue",
            "--work-order", str(wo_path),
            "--repository-path", "C:/repo",
            "--mode", "read-only",
        ])
        self.assertEqual(code, 0)

        items = queue.list_items(self.queue_root)
        self.assertEqual(len(items), 1)

        code = queue.main(["--queue-root", str(self.queue_root), "status"])
        self.assertEqual(code, 0)

        queue.transition_item(self.queue_root, items[0].item_id, queue.QueueState.RUNNING)
        code = queue.main(["--queue-root", str(self.queue_root), "recover"])
        self.assertEqual(code, 0)

        reloaded = queue.load_item(self.queue_root, items[0].item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

    def test_enqueue_missing_work_order_file_errors(self):
        code = queue.main([
            "--queue-root", str(self.queue_root),
            "enqueue",
            "--work-order", str(self.root / "missing.txt"),
            "--repository-path", "C:/repo",
        ])
        self.assertEqual(code, 11)

    def test_parser_requires_a_subcommand(self):
        parser = queue.build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--queue-root", str(self.queue_root)])


# ---------------------------------------------------------------------------
# Attempts schema (RUNNER-1.5D): backward compatibility + explicit persistence
# ---------------------------------------------------------------------------

class AttemptsSchemaTest(_TempDirCase):
    def test_new_items_persist_attempts_explicitly(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        raw = json.loads(
            (self.queue_root / item.item_id / queue.ITEM_METADATA_FILENAME).read_text(encoding="utf-8")
        )
        self.assertIn("attempts", raw)
        self.assertEqual(raw["attempts"], [])

    def test_schema_v1_item_missing_attempts_field_loads_as_empty_list(self):
        item_dir = self.queue_root / "legacy-item"
        item_dir.mkdir(parents=True)
        wo_text = "content\n"
        (item_dir / queue.WORK_ORDER_FILENAME).write_bytes(wo_text.encode("utf-8"))
        payload = {
            "schema_version": queue.SCHEMA_VERSION,
            "item_id": "legacy-item",
            "created_at_utc": "2026-09-16T00:00:00+00:00",
            "updated_at_utc": "2026-09-16T00:00:00+00:00",
            "state": queue.QueueState.QUEUED.value,
            "repository_path": "repo",
            "mode": "read-only",
            "authorize_path": [],
            "timeout_seconds": None,
            "model": None,
            "label": None,
            "work_order_filename": queue.WORK_ORDER_FILENAME,
            "work_order_sha256": hashlib.sha256(wo_text.encode("utf-8")).hexdigest(),
            "history": [],
            # deliberately no "attempts" key: pre-1.5D schema-version-1 item.
        }
        (item_dir / queue.ITEM_METADATA_FILENAME).write_text(json.dumps(payload), encoding="utf-8")

        loaded = queue.load_item(self.queue_root, "legacy-item")
        self.assertEqual(loaded.attempts, [])


# ---------------------------------------------------------------------------
# run_next: selection, no-work, attempt visibility
# ---------------------------------------------------------------------------

class RunNextNoWorkTest(_TempDirCase):
    def test_empty_queue_returns_no_work_without_invoking_executor(self):
        result = queue.run_next(self.queue_root, executor=_explode_if_called)
        self.assertEqual(result.outcome, queue.RunNextOutcome.NO_WORK.value)
        self.assertIsNone(result.item_id)

    def test_queue_with_only_terminal_items_returns_no_work(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.SUCCEEDED)
        result = queue.run_next(self.queue_root, executor=_explode_if_called)
        self.assertEqual(result.outcome, queue.RunNextOutcome.NO_WORK.value)


class RunNextSelectionTest(_TempDirCase):
    def test_run_next_selects_first_queued_item_deterministically(self):
        fixed_times = iter([
            "2026-09-16T00:00:00+00:00",
            "2026-09-16T00:00:01+00:00",
            "2026-09-16T00:00:01+00:00",
        ])
        original_now = queue._now_iso
        try:
            queue._now_iso = lambda: next(fixed_times)
            first = queue.enqueue(
                self.queue_root, work_order_text="a\n", repository_path="repo", mode="read-only",
            )
            queue.enqueue(
                self.queue_root, work_order_text="b\n", repository_path="repo", mode="read-only",
            )
            queue.enqueue(
                self.queue_root, work_order_text="c\n", repository_path="repo", mode="read-only",
            )
        finally:
            queue._now_iso = original_now

        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.outcome, queue.RunNextOutcome.DISPATCHED.value)
        self.assertEqual(result.item_id, first.item_id)
        self.assertEqual(len(executor.calls), 1)


class RunNextAttemptVisibleBeforeExecutorTest(_TempDirCase):
    def test_attempt_and_state_are_running_before_executor_is_invoked(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        observed = {}

        def _executor(request):
            reloaded = queue.load_item(self.queue_root, item.item_id)
            observed["state"] = reloaded.state
            observed["attempt_status"] = reloaded.attempts[-1]["status"]
            observed["attempt_id"] = reloaded.attempts[-1]["attempt_id"]
            observed["started_at_utc"] = reloaded.attempts[-1]["started_at_utc"]
            return runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
                evidence_dir=None, error_message=None,
            )

        result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(observed["state"], queue.QueueState.RUNNING.value)
        self.assertEqual(observed["attempt_status"], "RUNNING")
        self.assertIsNotNone(observed["started_at_utc"])
        self.assertEqual(observed["attempt_id"], result.attempt_id)


# ---------------------------------------------------------------------------
# run_next: WorkOrderRequest construction from durable queue data
# ---------------------------------------------------------------------------

class RunNextRequestConstructionTest(_TempDirCase):
    def test_request_built_from_durable_queue_data(self):
        item = queue.enqueue(
            self.queue_root,
            work_order_text="Do a governed thing.\n",
            repository_path="C:/some/repo",
            mode="write",
            authorize_path=["src/module.py", "docs/**"],
            timeout_seconds=120,
            model="claude-sonnet-5",
            label="wo-label",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.WRITE_SCOPE_REQUIRED, exit_code=23, run_id="rid",
            evidence_dir=None, error_message="refused",
        ))
        queue.run_next(self.queue_root, executor=executor)

        self.assertEqual(len(executor.calls), 1)
        request = executor.calls[0]
        expected_wo_path = self.queue_root / item.item_id / queue.WORK_ORDER_FILENAME
        self.assertEqual(Path(request.work_order), expected_wo_path)
        self.assertEqual(request.repo, "C:/some/repo")
        self.assertEqual(request.mode, "write")
        self.assertEqual(request.authorize_path, ["src/module.py", "docs/**"])
        self.assertEqual(request.timeout_seconds, 120)
        self.assertEqual(request.model, "claude-sonnet-5")
        self.assertEqual(request.label, "wo-label")

    def test_default_timeout_applies_when_item_did_not_request_one(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)
        request = executor.calls[0]
        self.assertEqual(request.timeout_seconds, runner.DEFAULT_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# run_next: no shell-out
# ---------------------------------------------------------------------------

class NoShellOutTest(_TempDirCase):
    def test_module_never_invokes_popen(self):
        # RUNNER-1.5E: claude_queue now imports `subprocess` for narrowly-
        # scoped, read-only `git` inspection during checkpoint capture, but
        # Popen (the mechanism claude_runner uses to invoke the interactive
        # `claude` CLI process) must never be used from this module at all.
        import subprocess as real_subprocess

        original_popen = real_subprocess.Popen

        def _boom(*args, **kwargs):
            raise AssertionError("claude_queue must never Popen a process (that is claude_runner's job)")

        real_subprocess.Popen = _boom
        try:
            queue.enqueue(
                self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
            )
            executor = _RecordingExecutor(runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
                evidence_dir=None, error_message=None,
            ))
            result = queue.run_next(self.queue_root, executor=executor)
            self.assertEqual(result.outcome, queue.RunNextOutcome.DISPATCHED.value)
        finally:
            real_subprocess.Popen = original_popen

    def test_run_next_never_touches_subprocess_when_no_checkpoint_capture_is_needed(self):
        import subprocess as real_subprocess

        original_popen = real_subprocess.Popen
        original_run = real_subprocess.run

        def _boom(*args, **kwargs):
            raise AssertionError(
                "claude_queue must never shell out at all when no checkpoint capture is required"
            )

        real_subprocess.Popen = _boom
        real_subprocess.run = _boom
        try:
            queue.enqueue(
                self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
            )
            executor = _RecordingExecutor(runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
                evidence_dir=None, error_message=None,
            ))
            result = queue.run_next(self.queue_root, executor=executor)
            self.assertEqual(result.outcome, queue.RunNextOutcome.DISPATCHED.value)
        finally:
            real_subprocess.Popen = original_popen
            real_subprocess.run = original_run

    def test_checkpoint_capture_only_ever_invokes_explicit_git_argv_with_shell_false(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )

        import subprocess as real_subprocess

        original_run = real_subprocess.run
        observed_calls = []

        def _spy_run(cmd, *args, **kwargs):
            observed_calls.append((list(cmd), kwargs.get("shell", False)))
            if not cmd or cmd[0] != "git":
                raise AssertionError(f"unexpected non-git subprocess invocation: {cmd!r}")
            for token in cmd:
                self.assertNotIn("claude", str(token).lower())
            return original_run(cmd, *args, **kwargs)

        real_subprocess.run = _spy_run
        try:
            def _executor(request):
                raise RuntimeError("simulated executor crash to force checkpoint capture")

            result = queue.run_next(self.queue_root, executor=_executor)
        finally:
            real_subprocess.run = original_run

        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertTrue(observed_calls, "expected at least one git subprocess call during checkpoint capture")
        for cmd, shell in observed_calls:
            self.assertEqual(cmd[0], "git")
            self.assertFalse(shell)


# ---------------------------------------------------------------------------
# run_next: fail-closed result mapping
# ---------------------------------------------------------------------------

class ReadOnlyMappingTest(_TempDirCase):
    def test_success_maps_to_succeeded(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.SUCCEEDED.value)

    def test_failed_safety_maps_to_failed_safety(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.FAILED_SAFETY, exit_code=20, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)

    def test_other_non_success_maps_to_failed(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)


class WriteModeMappingTest(_TempDirCase):
    def _enqueue_write_item(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root,
            work_order_text="Edit something.\n",
            repository_path=str(repo_dir),
            mode="write",
            authorize_path=["src"],
        )
        return repo_dir, item

    def test_write_success_with_mutation_blocks_on_checkpoint(self):
        repo_dir, item = self._enqueue_write_item()
        run_id = "20260916T000000Z_deadbeef"
        evidence_dir = _write_evidence(repo_dir, run_id, state="SUCCESS", repository_mutated=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

    def test_write_success_without_mutation_succeeds(self):
        repo_dir, item = self._enqueue_write_item()
        run_id = "20260916T000000Z_cafef00d"
        evidence_dir = _write_evidence(repo_dir, run_id, state="SUCCESS", repository_mutated=False)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.SUCCEEDED.value)

    def test_write_non_success_with_mutation_blocks_on_checkpoint(self):
        repo_dir, item = self._enqueue_write_item()
        run_id = "20260916T000000Z_11111111"
        evidence_dir = _write_evidence(repo_dir, run_id, state="TIMEOUT", repository_mutated=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.TIMEOUT, exit_code=4, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

    def test_write_non_success_without_mutation_fails(self):
        repo_dir, item = self._enqueue_write_item()
        run_id = "20260916T000000Z_22222222"
        evidence_dir = _write_evidence(repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)


class PreInvocationRefusalMappingTest(_TempDirCase):
    def test_write_scope_required_refusal_maps_to_failed(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="write",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.WRITE_SCOPE_REQUIRED, exit_code=23, run_id="rid",
            evidence_dir=repo_dir / "runtime" / "claude_runner" / "runs" / "rid",
            error_message="Write mode requires at least one --authorize-path",
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)

    def test_invalid_repository_refusal_maps_to_failed_without_evidence(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.INVALID_REPOSITORY, exit_code=10, run_id=None,
            evidence_dir=None, error_message="Repository path does not exist",
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)


class WriteEvidenceFailClosedTest(_TempDirCase):
    def _enqueue_write_item(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir),
            mode="write", authorize_path=["src"],
        )
        return repo_dir, item

    def test_missing_evidence_dir_fails_closed(self):
        self._enqueue_write_item()
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)

    def test_missing_result_json_fails_closed(self):
        repo_dir, _item = self._enqueue_write_item()
        run_id = "20260916T000000Z_aaaaaaaa"
        evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / run_id
        evidence_dir.mkdir(parents=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)

    def test_malformed_result_json_fails_closed(self):
        repo_dir, _item = self._enqueue_write_item()
        run_id = "20260916T000000Z_bbbbbbbb"
        evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / run_id
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "result.json").write_text("{not json", encoding="utf-8")
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)

    def test_missing_repository_mutated_field_fails_closed(self):
        repo_dir, _item = self._enqueue_write_item()
        run_id = "20260916T000000Z_cccccccc"
        evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / run_id
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "result.json").write_text(
            json.dumps({"state": "SUCCESS", "safety_check": {}}), encoding="utf-8"
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)

    def test_evidence_dir_name_inconsistent_with_run_id_fails_closed(self):
        repo_dir, _item = self._enqueue_write_item()
        real_run_id = "20260916T000000Z_dddddddd"
        evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / real_run_id
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "result.json").write_text(
            json.dumps({"state": "SUCCESS", "safety_check": {"repository_mutated": False}}),
            encoding="utf-8",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="a-different-run-id",
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)

    def test_evidence_dir_outside_expected_runs_base_fails_closed(self):
        repo_dir, _item = self._enqueue_write_item()
        run_id = "20260916T000000Z_eeeeeeee"
        outside_dir = self.root / "outside" / run_id
        outside_dir.mkdir(parents=True)
        (outside_dir / "result.json").write_text(
            json.dumps({"state": "SUCCESS", "safety_check": {"repository_mutated": False}}),
            encoding="utf-8",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=outside_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)


# ---------------------------------------------------------------------------
# run_next: executor exception -> fail-closed BLOCKED_ON_CHECKPOINT, no retry
# ---------------------------------------------------------------------------

class ExecutorExceptionTest(_TempDirCase):
    def test_executor_exception_blocks_on_checkpoint_without_retry(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        calls = []

        def _executor(request):
            calls.append(request)
            raise RuntimeError("simulated executor crash")

        result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(result.outcome, queue.RunNextOutcome.DISPATCHED.value)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertEqual(len(calls), 1)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertEqual(reloaded.attempts[-1]["status"], "EXCEPTION")
        self.assertIsNotNone(reloaded.attempts[-1]["ended_at_utc"])

        # A second run_next call must not automatically retry the same item.
        second_result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(second_result.outcome, queue.RunNextOutcome.NO_WORK.value)
        self.assertEqual(len(calls), 1)


# ---------------------------------------------------------------------------
# run_next: orphan recovery stops dispatch
# ---------------------------------------------------------------------------

class RunNextOrphanRecoveryTest(_TempDirCase):
    def test_orphaned_running_item_stops_run_next_without_dispatch(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        # Simulate a crashed prior worker: RUNNING with no matching attempt,
        # exactly like RUNNER-1.5C's pre-existing orphan scenario.
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)

        calls = []

        def _executor(request):
            calls.append(request)
            return runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
                evidence_dir=None, error_message=None,
            )

        result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(result.outcome, queue.RunNextOutcome.RECOVERY_REQUIRED.value)
        self.assertEqual(result.recovered_item_ids, [item.item_id])
        self.assertEqual(calls, [])

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)


# ---------------------------------------------------------------------------
# run_next: exclusive lock prevents concurrent execution
# ---------------------------------------------------------------------------

class RunNextLockContentionTest(_TempDirCase):
    def test_held_lock_prevents_concurrent_run_next(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        holder = queue.QueueLock(self.queue_root)
        holder.acquire(blocking=False)
        try:
            with self.assertRaises(queue.QueueLockError):
                queue.run_next(self.queue_root, executor=_explode_if_called)
        finally:
            holder.release()

        result = queue.run_next(self.queue_root, executor=_RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        )))
        self.assertEqual(result.outcome, queue.RunNextOutcome.DISPATCHED.value)


# ---------------------------------------------------------------------------
# run_next: finalized attempt metadata and no conversational data
# ---------------------------------------------------------------------------

class FinalizedAttemptMetadataTest(_TempDirCase):
    def test_finalized_attempt_matches_final_queue_state(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="the-run-id",
            evidence_dir=Path("some/evidence/dir"), error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.SUCCEEDED.value)
        self.assertEqual(len(reloaded.attempts), 1)
        attempt = reloaded.attempts[0]
        self.assertEqual(attempt["attempt_id"], result.attempt_id)
        self.assertEqual(attempt["status"], "COMPLETED")
        self.assertEqual(attempt["final_queue_state"], queue.QueueState.SUCCEEDED.value)
        self.assertEqual(attempt["runner_state"], "SUCCESS")
        self.assertEqual(attempt["runner_exit_code"], 0)
        self.assertEqual(attempt["runner_run_id"], "the-run-id")
        self.assertIsNotNone(attempt["ended_at_utc"])


class NoConversationalDataPersistedTest(_TempDirCase):
    def test_attempt_record_carries_no_session_or_transcript_data(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[0]
        allowed_keys = {
            "attempt_id", "started_at_utc", "ended_at_utc", "status",
            "runner_state", "runner_exit_code", "runner_run_id",
            "runner_evidence_dir", "final_queue_state",
        }
        self.assertEqual(set(attempt.keys()), allowed_keys)

        raw_text = (self.queue_root / item.item_id / queue.ITEM_METADATA_FILENAME).read_text(
            encoding="utf-8"
        )
        for forbidden in ("session_id", "conversation_id", "transcript", "--resume", "--continue"):
            self.assertNotIn(forbidden, raw_text)


# ---------------------------------------------------------------------------
# run-next CLI
# ---------------------------------------------------------------------------

class RunNextCliTest(_TempDirCase):
    def test_run_next_cli_no_work_is_not_an_error(self):
        code = queue.main(["--queue-root", str(self.queue_root), "run-next"])
        self.assertEqual(code, 0)


class RunNextActiveAttemptCrashRecoveryTest(_TempDirCase):
    def test_orphaned_1_5d_running_attempt_is_finalized_before_dispatch(self):
        item = queue.enqueue(
            self.queue_root,
            work_order_text="content\n",
            repository_path="repo",
            mode="read-only",
        )

        attempt_id = queue.generate_attempt_id()
        attempt = queue.QueueAttempt(
            attempt_id=attempt_id,
            started_at_utc=queue._now_iso(),
            ended_at_utc=None,
            status="RUNNING",
            runner_state=None,
            runner_exit_code=None,
            runner_run_id=None,
            runner_evidence_dir=None,
            final_queue_state=None,
        )
        queue.start_attempt(self.queue_root, item.item_id, attempt)

        calls = []

        def executor(request):
            calls.append(request)
            raise AssertionError("executor must not run while orphan recovery is required")

        result = queue.run_next(self.queue_root, executor=executor)

        self.assertEqual(result.outcome, queue.RunNextOutcome.RECOVERY_REQUIRED.value)
        self.assertEqual(calls, [])

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(
            reloaded.state,
            queue.QueueState.BLOCKED_ON_CHECKPOINT.value,
        )

        active = next(
            raw for raw in reloaded.attempts
            if raw["attempt_id"] == attempt_id
        )
        self.assertEqual(active["status"], "ORPHANED")
        self.assertIsNotNone(active["ended_at_utc"])
        self.assertEqual(
            active["final_queue_state"],
            queue.QueueState.BLOCKED_ON_CHECKPOINT.value,
        )

    def test_multiple_running_attempts_fail_closed_during_recovery(self):
        item = queue.enqueue(
            self.queue_root,
            work_order_text="content\n",
            repository_path="repo",
            mode="read-only",
        )

        first = queue.QueueAttempt(
            attempt_id="attempt_first",
            started_at_utc=queue._now_iso(),
            ended_at_utc=None,
            status="RUNNING",
            runner_state=None,
            runner_exit_code=None,
            runner_run_id=None,
            runner_evidence_dir=None,
            final_queue_state=None,
        )
        queue.start_attempt(self.queue_root, item.item_id, first)

        # Deliberately corrupt durable state to simulate an impossible
        # multiple-active-attempt condition.
        metadata_path = (
            self.queue_root / item.item_id / queue.ITEM_METADATA_FILENAME
        )
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        second = dict(payload["attempts"][0])
        second["attempt_id"] = "attempt_second"
        payload["attempts"].append(second)
        metadata_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        with queue.QueueLock(self.queue_root) as lock:
            with self.assertRaises(queue.QueueError) as ctx:
                queue.recover_orphaned_running_items(
                    self.queue_root,
                    lock=lock,
                )

        self.assertEqual(ctx.exception.reason, "CORRUPT_ATTEMPT")


# ---------------------------------------------------------------------------
# RUNNER-1.5E: checkpoints schema (backward compatibility + explicit persistence)
# ---------------------------------------------------------------------------

class CheckpointsSchemaTest(_TempDirCase):
    def test_new_items_persist_checkpoints_explicitly(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        raw = json.loads(
            (self.queue_root / item.item_id / queue.ITEM_METADATA_FILENAME).read_text(encoding="utf-8")
        )
        self.assertIn("checkpoints", raw)
        self.assertEqual(raw["checkpoints"], [])

    def test_schema_v1_item_missing_checkpoints_field_loads_as_empty_list(self):
        item_dir = self.queue_root / "legacy-item"
        item_dir.mkdir(parents=True)
        wo_text = "content\n"
        (item_dir / queue.WORK_ORDER_FILENAME).write_bytes(wo_text.encode("utf-8"))
        payload = {
            "schema_version": queue.SCHEMA_VERSION,
            "item_id": "legacy-item",
            "created_at_utc": "2026-09-16T00:00:00+00:00",
            "updated_at_utc": "2026-09-16T00:00:00+00:00",
            "state": queue.QueueState.QUEUED.value,
            "repository_path": "repo",
            "mode": "read-only",
            "authorize_path": [],
            "timeout_seconds": None,
            "model": None,
            "label": None,
            "work_order_filename": queue.WORK_ORDER_FILENAME,
            "work_order_sha256": hashlib.sha256(wo_text.encode("utf-8")).hexdigest(),
            "history": [],
            "attempts": [],
            # deliberately no "checkpoints" key: pre-1.5E schema-version-1 item.
        }
        (item_dir / queue.ITEM_METADATA_FILENAME).write_text(json.dumps(payload), encoding="utf-8")

        loaded = queue.load_item(self.queue_root, "legacy-item")
        self.assertEqual(loaded.checkpoints, [])


# ---------------------------------------------------------------------------
# RUNNER-1.5E: deterministic checkpoint identity
# ---------------------------------------------------------------------------

class CheckpointIdentityTest(unittest.TestCase):
    def test_deterministic_for_same_item_and_attempt(self):
        first = queue.compute_checkpoint_id("item-1", "attempt-1")
        second = queue.compute_checkpoint_id("item-1", "attempt-1")
        self.assertEqual(first, second)

    def test_differs_for_different_attempt(self):
        first = queue.compute_checkpoint_id("item-1", "attempt-1")
        second = queue.compute_checkpoint_id("item-1", "attempt-2")
        self.assertNotEqual(first, second)

    def test_differs_for_different_item(self):
        first = queue.compute_checkpoint_id("item-1", "attempt-1")
        second = queue.compute_checkpoint_id("item-2", "attempt-1")
        self.assertNotEqual(first, second)

    def test_legacy_identity_is_deterministic_and_attempt_independent(self):
        first = queue.compute_checkpoint_id("item-1", None)
        second = queue.compute_checkpoint_id("item-1", None)
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# RUNNER-1.5E: repository snapshot contract (real git repositories)
# ---------------------------------------------------------------------------

class CheckpointSnapshotContractTest(_TempDirCase):
    def _repo(self):
        repo_dir = self.root / "snap-repo"
        _init_git_repo(repo_dir)
        return repo_dir

    def _item(self, repo_dir):
        return queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )

    def _manifest(self, item, record):
        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / record.checkpoint_id
        return checkpoint_dir, json.loads((checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME).read_text(encoding="utf-8"))

    def test_modified_tracked_file_bytes_and_unicode_content_preserved(self):
        repo_dir = self._repo()
        tracked = repo_dir / "tracked.txt"
        tracked.write_text("original\n", encoding="utf-8")
        _run_git_cmd(["add", "tracked.txt"], cwd=repo_dir)
        _run_git_cmd(["commit", "-q", "-m", "add tracked"], cwd=repo_dir)

        new_content = "modified áéíóú ñ 中文 🚀\n"
        tracked.write_bytes(new_content.encode("utf-8"))

        item = self._item(repo_dir)
        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att1")
        self.assertEqual(record.status, "CAPTURED")

        checkpoint_dir, manifest = self._manifest(item, record)
        entry = next(e for e in manifest["entries"] if e["path"] == "tracked.txt")
        self.assertEqual(entry["change_type"], "modified")
        expected_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        self.assertEqual(entry["sha256"], expected_hash)
        blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / entry["blob_filename"]
        self.assertEqual(blob_path.read_bytes(), new_content.encode("utf-8"))

    def test_binary_tracked_file_bytes_preserved_and_binary_patch_captured(self):
        repo_dir = self._repo()
        binary_path = repo_dir / "data.bin"
        binary_path.write_bytes(bytes(range(256)))
        _run_git_cmd(["add", "data.bin"], cwd=repo_dir)
        _run_git_cmd(["commit", "-q", "-m", "add binary"], cwd=repo_dir)

        modified = bytes(reversed(range(256))) + b"\x00\x01\x02\xff"
        binary_path.write_bytes(modified)

        item = self._item(repo_dir)
        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-bin")
        self.assertEqual(record.status, "CAPTURED")

        checkpoint_dir, manifest = self._manifest(item, record)
        entry = next(e for e in manifest["entries"] if e["path"] == "data.bin")
        blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / entry["blob_filename"]
        self.assertEqual(blob_path.read_bytes(), modified)
        self.assertEqual(entry["sha256"], hashlib.sha256(modified).hexdigest())

        patch_path = checkpoint_dir / queue.CHECKPOINT_PATCH_FILENAME
        patch_bytes = patch_path.read_bytes()
        self.assertEqual(hashlib.sha256(patch_bytes).hexdigest(), record.patch_sha256)
        self.assertIn(b"GIT binary patch", patch_bytes)

    def test_untracked_file_full_content_preserved(self):
        repo_dir = self._repo()
        item = self._item(repo_dir)
        untracked = repo_dir / "new_untracked.txt"
        content = "brand new untracked content\n"
        untracked.write_text(content, encoding="utf-8")

        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-un")
        checkpoint_dir, manifest = self._manifest(item, record)
        entry = next(e for e in manifest["entries"] if e["path"] == "new_untracked.txt")
        self.assertEqual(entry["origin"], "untracked")
        blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / entry["blob_filename"]
        self.assertEqual(blob_path.read_text(encoding="utf-8"), content)

    def test_deletion_recorded_explicitly_without_blob(self):
        repo_dir = self._repo()
        to_delete = repo_dir / "doomed.txt"
        to_delete.write_text("will be deleted\n", encoding="utf-8")
        _run_git_cmd(["add", "doomed.txt"], cwd=repo_dir)
        _run_git_cmd(["commit", "-q", "-m", "add doomed"], cwd=repo_dir)
        to_delete.unlink()

        item = self._item(repo_dir)
        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-del")
        _checkpoint_dir, manifest = self._manifest(item, record)
        entry = next(e for e in manifest["entries"] if e["path"] == "doomed.txt")
        self.assertEqual(entry["change_type"], "deleted")
        self.assertFalse(entry["exists"])
        self.assertIsNone(entry["blob_filename"])
        self.assertIsNone(entry["sha256"])

    def test_manifest_entries_are_deterministically_ordered(self):
        repo_dir = self._repo()
        item = self._item(repo_dir)
        (repo_dir / "zzz.txt").write_text("z\n", encoding="utf-8")
        (repo_dir / "aaa.txt").write_text("a\n", encoding="utf-8")
        (repo_dir / "mmm.txt").write_text("m\n", encoding="utf-8")

        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-order")
        _checkpoint_dir, manifest = self._manifest(item, record)
        paths = [e["path"] for e in manifest["entries"]]
        self.assertEqual(paths, sorted(paths))

    def test_capture_never_mutates_repository(self):
        repo_dir = self._repo()
        (repo_dir / "untouched.txt").write_text("hello\n", encoding="utf-8")
        item = self._item(repo_dir)
        before_status = _run_git_cmd(["status", "--porcelain=v1", "--untracked-files=all"], cwd=repo_dir).stdout
        before_head = _run_git_cmd(["rev-parse", "HEAD"], cwd=repo_dir).stdout

        queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-nomut")

        after_status = _run_git_cmd(["status", "--porcelain=v1", "--untracked-files=all"], cwd=repo_dir).stdout
        after_head = _run_git_cmd(["rev-parse", "HEAD"], cwd=repo_dir).stdout
        self.assertEqual(before_status, after_status)
        self.assertEqual(before_head, after_head)

    def test_atomic_publication_leaves_no_staging_directory(self):
        repo_dir = self._repo()
        (repo_dir / "a.txt").write_text("a\n", encoding="utf-8")
        item = self._item(repo_dir)
        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-atomic")
        checkpoints_root = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME
        entries = list(checkpoints_root.iterdir())
        staging = [e for e in entries if e.name.startswith(".")]
        self.assertEqual(staging, [])
        self.assertTrue((checkpoints_root / record.checkpoint_id).is_dir())

    def test_symlink_target_recorded_not_dereferenced(self):
        repo_dir = self._repo()
        item = self._item(repo_dir)
        target_file = repo_dir / "real_target.txt"
        target_file.write_text("actual content\n", encoding="utf-8")
        link_path = repo_dir / "link_to_target.txt"
        try:
            link_path.symlink_to(target_file.name)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unsupported on this platform/user: {exc}")

        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-symlink")
        self.assertEqual(record.status, "CAPTURED")
        _checkpoint_dir, manifest = self._manifest(item, record)
        entry = next(e for e in manifest["entries"] if e["path"] == "link_to_target.txt")
        self.assertTrue(entry["is_symlink"])
        self.assertEqual(entry["symlink_target"], "real_target.txt")
        self.assertIsNone(entry["blob_filename"])


# ---------------------------------------------------------------------------
# RUNNER-1.5E: checkpoint reuse and corruption fail-closed
# ---------------------------------------------------------------------------

class CheckpointReuseAndCorruptionTest(_TempDirCase):
    def test_second_call_reuses_published_checkpoint_without_recapturing(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        (repo_dir / "one.txt").write_text("one\n", encoding="utf-8")
        first = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-reuse")
        self.assertEqual(first.status, "CAPTURED")

        # Mutate the repo further AFTER the first capture; a genuine reuse
        # must not re-derive from this new state.
        (repo_dir / "one.txt").write_text("mutated after capture\n", encoding="utf-8")

        second = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-reuse")
        self.assertEqual(second.checkpoint_id, first.checkpoint_id)
        self.assertEqual(second.manifest_sha256, first.manifest_sha256)

        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / first.checkpoint_id
        manifest = json.loads((checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME).read_text(encoding="utf-8"))
        entry = next(e for e in manifest["entries"] if e["path"] == "one.txt")
        blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / entry["blob_filename"]
        self.assertEqual(blob_path.read_text(encoding="utf-8"), "one\n")

    def test_corrupted_existing_checkpoint_fails_closed_without_overwriting(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        (repo_dir / "one.txt").write_text("one\n", encoding="utf-8")
        first = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-corrupt")
        self.assertEqual(first.status, "CAPTURED")

        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / first.checkpoint_id
        manifest_path = checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["patch_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        second = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-corrupt")
        self.assertEqual(second.status, "FAILED")
        self.assertIn("patch hash mismatch", second.error)
        self.assertTrue(manifest_path.exists())

    def test_capture_self_validation_rejects_a_checkpoint_whose_blob_write_silently_failed(self):
        """Capture-creation invariant (RUNNER-1.5E-FIX1): a checkpoint must
        never be reported CAPTURED unless it independently re-validates
        clean from disk via the same validator reconciliation uses. This
        simulates a durability gap (a blob write that silently produced no
        file) and proves capture fails closed instead of publishing a
        checkpoint that would only be discovered broken later, during
        reconciliation."""
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        (repo_dir / "one.txt").write_text("one\n", encoding="utf-8")

        real_atomic_write_bytes = queue._atomic_write_bytes

        def _drop_blob_writes(target, data):
            if target.parent.name == queue.CHECKPOINT_BLOBS_DIRNAME:
                return  # simulate a durability gap: the blob never lands on disk
            real_atomic_write_bytes(target, data)

        with mock.patch.object(queue, "_atomic_write_bytes", side_effect=_drop_blob_writes):
            record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-selfcheck")

        self.assertEqual(record.status, "FAILED")
        self.assertIn("blob", record.error)

        # The published checkpoint directory is deliberately left on disk
        # for forensics (never fabricated/repaired), so a retry
        # deterministically fails the same way instead of masking the gap.
        retry = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-selfcheck")
        self.assertEqual(retry.status, "FAILED")

    def test_checkpoint_survives_nested_windows_style_relative_paths(self):
        """Windows-compatible regression: nested directories and backslash
        path handling must round-trip through manifest normalization and
        compact blob addressing without depending on the developer
        machine's absolute path."""
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        nested_dir = repo_dir / "a" / "b" / "c"
        nested_dir.mkdir(parents=True)
        tracked = nested_dir / "tracked_nested.txt"
        tracked.write_text("nested tracked\n", encoding="utf-8")
        _run_git_cmd(["add", "-A"], cwd=repo_dir)
        _run_git_cmd(["commit", "-q", "-m", "add nested"], cwd=repo_dir)
        tracked.write_text("nested tracked modified\n", encoding="utf-8")

        untracked_nested = nested_dir / "untracked_nested.txt"
        untracked_nested.write_text("nested untracked\n", encoding="utf-8")

        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        record = queue.capture_or_reuse_checkpoint(self.queue_root, item, attempt_id="att-nested")
        self.assertEqual(record.status, "CAPTURED")

        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / record.checkpoint_id
        manifest = json.loads((checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME).read_text(encoding="utf-8"))
        paths = {e["path"] for e in manifest["entries"]}
        self.assertIn("a/b/c/tracked_nested.txt", paths)
        self.assertIn("a/b/c/untracked_nested.txt", paths)
        for e in manifest["entries"]:
            self.assertNotIn("\\", e["path"])
            blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / e["blob_filename"]
            self.assertTrue(blob_path.exists())


# ---------------------------------------------------------------------------
# RUNNER-1.5E: run_next integration - checkpoint capture on BLOCKED_ON_CHECKPOINT
# ---------------------------------------------------------------------------

class RunNextCheckpointIntegrationTest(_TempDirCase):
    def test_write_mode_mutation_attaches_captured_checkpoint(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="Edit something.\n", repository_path=str(repo_dir),
            mode="write", authorize_path=["src"],
        )
        (repo_dir / "src").mkdir()
        (repo_dir / "src" / "new_file.py").write_text("print('hi')\n", encoding="utf-8")

        run_id = "20260916T000000Z_deadbeef"
        evidence_dir = _write_evidence(repo_dir, run_id, state="SUCCESS", repository_mutated=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertIsNotNone(result.checkpoint_id)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(len(reloaded.checkpoints), 1)
        cp = reloaded.checkpoints[0]
        self.assertEqual(cp["status"], "CAPTURED")
        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / cp["checkpoint_id"]
        manifest = json.loads((checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME).read_text(encoding="utf-8"))
        paths = [e["path"] for e in manifest["entries"]]
        self.assertIn("src/new_file.py", paths)

        attempt = reloaded.attempts[-1]
        self.assertEqual(attempt["checkpoint_id"], cp["checkpoint_id"])
        self.assertEqual(attempt["checkpoint_status"], "CAPTURED")

    def test_executor_exception_attaches_checkpoint_when_repository_valid(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )

        def _executor(request):
            raise RuntimeError("boom")

        result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.checkpoints[-1]["status"], "CAPTURED")

    def test_checkpoint_capture_failure_still_blocks_without_retry(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n",
            repository_path=str(self.root / "does-not-exist"), mode="read-only",
        )

        def _executor(request):
            raise RuntimeError("boom")

        result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.checkpoints[-1]["status"], "FAILED")
        self.assertIsNotNone(reloaded.checkpoints[-1]["error"])

        second = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(second.outcome, queue.RunNextOutcome.NO_WORK.value)


# ---------------------------------------------------------------------------
# RUNNER-1.5E: orphan recovery captures checkpoints
# ---------------------------------------------------------------------------

class OrphanCheckpointCaptureTest(_TempDirCase):
    def test_orphaned_1_5d_attempt_captures_checkpoint_before_finalizing(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        attempt_id = queue.generate_attempt_id()
        attempt = queue.QueueAttempt(
            attempt_id=attempt_id, started_at_utc=queue._now_iso(), ended_at_utc=None,
            status="RUNNING", runner_state=None, runner_exit_code=None, runner_run_id=None,
            runner_evidence_dir=None, final_queue_state=None,
        )
        queue.start_attempt(self.queue_root, item.item_id, attempt)

        with queue.QueueLock(self.queue_root) as lock:
            recovered = queue.recover_orphaned_running_items(self.queue_root, lock=lock)

        self.assertEqual(len(recovered), 1)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertEqual(len(reloaded.checkpoints), 1)
        self.assertEqual(reloaded.checkpoints[0]["status"], "CAPTURED")
        self.assertEqual(reloaded.checkpoints[0]["attempt_id"], attempt_id)

    def test_legacy_orphan_item_level_checkpoint(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)

        with queue.QueueLock(self.queue_root) as lock:
            queue.recover_orphaned_running_items(self.queue_root, lock=lock)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertEqual(len(reloaded.checkpoints), 1)
        self.assertIsNone(reloaded.checkpoints[0]["attempt_id"])
        self.assertEqual(reloaded.checkpoints[0]["status"], "CAPTURED")


# ---------------------------------------------------------------------------
# RUNNER-1.5E: explicit capture-checkpoint primitive + CLI
# ---------------------------------------------------------------------------

class CaptureCheckpointPrimitiveTest(_TempDirCase):
    def test_repairs_previously_failed_checkpoint_without_invoking_executor(self):
        missing_repo = self.root / "future-repo"
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(missing_repo), mode="read-only",
        )

        def _executor(request):
            raise RuntimeError("boom")

        result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.checkpoints[-1]["status"], "FAILED")

        _init_git_repo(missing_repo)

        repaired = queue.capture_checkpoint_for_item(self.queue_root, item.item_id)
        self.assertEqual(repaired.checkpoints[-1]["status"], "CAPTURED")
        self.assertEqual(len(repaired.attempts), 1)

    def test_requires_blocked_on_checkpoint_state(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        with self.assertRaises(queue.QueueError) as ctx:
            queue.capture_checkpoint_for_item(self.queue_root, item.item_id)
        self.assertEqual(ctx.exception.reason, "INVALID_STATE_FOR_CHECKPOINT_CAPTURE")

    def test_cli_capture_checkpoint_command(self):
        missing_repo = self.root / "future-repo-cli"
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(missing_repo), mode="read-only",
        )

        def _executor(request):
            raise RuntimeError("boom")

        queue.run_next(self.queue_root, executor=_executor)
        _init_git_repo(missing_repo)

        code = queue.main([
            "--queue-root", str(self.queue_root), "capture-checkpoint", "--item-id", item.item_id,
        ])
        self.assertEqual(code, 0)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.checkpoints[-1]["status"], "CAPTURED")


# ---------------------------------------------------------------------------
# RUNNER-1.5E: explicit human reconciliation
# ---------------------------------------------------------------------------

class ReconciliationTest(_TempDirCase):
    def _blocked_item(self, *, runner_state="SUCCESS", clean_after=True):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="Edit something.\n", repository_path=str(repo_dir),
            mode="write", authorize_path=["src"],
        )
        (repo_dir / "src").mkdir()
        (repo_dir / "src" / "file.py").write_text("print(1)\n", encoding="utf-8")
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence(repo_dir, run_id, state=runner_state, repository_mutated=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=getattr(runner.RunState, runner_state), exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        if clean_after:
            _run_git_cmd(["add", "-A"], cwd=repo_dir)
            _run_git_cmd(["commit", "-q", "-m", "commit authorized change"], cwd=repo_dir)
        return repo_dir, item

    def test_accept_requires_prior_runner_success(self):
        _repo_dir, item = self._blocked_item(runner_state="TIMEOUT", clean_after=True)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "ACCEPT", note="reviewed")
        self.assertEqual(ctx.exception.reason, "ACCEPT_REQUIRES_SUCCESS")

    def test_accept_moves_to_succeeded_and_marks_checkpoint_resolved(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        result = queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "ACCEPT", note="verified correct",
        )
        self.assertEqual(result.state, queue.QueueState.SUCCEEDED.value)
        cp = result.checkpoints[-1]
        self.assertTrue(cp["resolved"])
        self.assertEqual(cp["resolution"], "ACCEPT")
        self.assertEqual(cp["resolution_note"], "verified correct")
        self.assertIsNotNone(cp["resolved_at_utc"])

    def test_fail_moves_to_failed(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        result = queue.reconcile_checkpoint(self.queue_root, item.item_id, "FAIL", note="rejecting change")
        self.assertEqual(result.state, queue.QueueState.FAILED.value)

    def test_retry_moves_to_queued_and_next_run_next_creates_a_different_fresh_attempt(self):
        repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        result = queue.reconcile_checkpoint(self.queue_root, item.item_id, "RETRY", note="retry with fixes")
        self.assertEqual(result.state, queue.QueueState.QUEUED.value)
        self.assertEqual(len(result.attempts), 1)
        first_attempt_id = result.attempts[0]["attempt_id"]

        run_id = "20260916T000000Z_retrydone"
        evidence_dir = _write_evidence(repo_dir, run_id, state="SUCCESS", repository_mutated=False)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        next_result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(next_result.outcome, queue.RunNextOutcome.DISPATCHED.value)
        self.assertEqual(next_result.queue_state, queue.QueueState.SUCCEEDED.value)
        self.assertNotEqual(next_result.attempt_id, first_attempt_id)
        self.assertEqual(len(executor.calls), 1)

    def test_reconciliation_requires_non_empty_note(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "ACCEPT", note="   ")
        self.assertEqual(ctx.exception.reason, "MISSING_NOTE")

    def test_reconciliation_rejects_unknown_resolution(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "MAYBE", note="n/a")
        self.assertEqual(ctx.exception.reason, "INVALID_RESOLUTION")

    def test_reconciliation_refuses_dirty_repository(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=False)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "ACCEPT", note="attempt reconcile")
        self.assertEqual(ctx.exception.reason, "DIRTY_REPOSITORY")

    def test_reconciliation_verifies_checkpoint_hashes_before_resolving(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        loaded = queue.load_item(self.queue_root, item.item_id)
        checkpoint_id = loaded.checkpoints[-1]["checkpoint_id"]
        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / checkpoint_id
        manifest_path = checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        tampered = False
        for entry in payload["entries"]:
            if entry.get("blob_filename"):
                blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / entry["blob_filename"]
                blob_path.write_bytes(b"tampered")
                tampered = True
                break
        self.assertTrue(tampered, "expected at least one blob to tamper with")

        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "ACCEPT", note="verify")
        self.assertEqual(ctx.exception.reason, "CHECKPOINT_INTEGRITY_FAILED")

    def _delete_a_checkpoint_blob(self, item_id: str) -> str:
        """Reproduces the reported incident: a manifest-referenced blob is
        absent under checkpoints/<checkpoint_id>/blobs/<blob_id>.blob
        (FileNotFoundError inside `_load_and_validate_checkpoint`), rather
        than merely tampering its bytes. Returns the checkpoint_id."""
        loaded = queue.load_item(self.queue_root, item_id)
        checkpoint_id = loaded.checkpoints[-1]["checkpoint_id"]
        checkpoint_dir = self.queue_root / item_id / queue.CHECKPOINTS_SUBDIR_NAME / checkpoint_id
        manifest_path = checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        deleted = False
        for entry in payload["entries"]:
            if entry.get("blob_filename"):
                blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / entry["blob_filename"]
                blob_path.unlink()
                deleted = True
                break
        self.assertTrue(deleted, "expected at least one blob to delete")
        return checkpoint_id

    def test_missing_blob_fails_accept_closed(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        self._delete_a_checkpoint_blob(item.item_id)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "ACCEPT", note="verify")
        self.assertEqual(ctx.exception.reason, "CHECKPOINT_INTEGRITY_FAILED")
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

    def test_missing_blob_fails_retry_closed(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        self._delete_a_checkpoint_blob(item.item_id)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "RETRY", note="retry anyway")
        self.assertEqual(ctx.exception.reason, "CHECKPOINT_INTEGRITY_FAILED")
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

    def test_missing_blob_permits_terminal_fail_rejection(self):
        """Reproduces the exact reported incident: operator committed the
        target so it is clean, then FAIL must succeed instead of raising
        CHECKPOINT_INTEGRITY_FAILED and leaving the item permanently
        BLOCKED_ON_CHECKPOINT."""
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        checkpoint_id = self._delete_a_checkpoint_blob(item.item_id)

        result = queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "FAIL", note="checkpoint blob missing, rejecting",
        )
        self.assertEqual(result.state, queue.QueueState.FAILED.value)

        cp = [c for c in result.checkpoints if c["checkpoint_id"] == checkpoint_id][0]
        self.assertTrue(cp["resolved"])
        self.assertEqual(cp["resolution"], "FAIL")
        self.assertTrue(cp["integrity_failed_at_reconciliation"])
        self.assertIsNotNone(cp["integrity_failure_detail"])

        last_event = result.history[-1]
        self.assertTrue(last_event["event"].startswith("RECONCILE_CORRUPT_CHECKPOINT_REJECTED:"))
        self.assertIn("checkpoint_integrity_failed=true", last_event["detail"])

    def test_missing_blob_fail_rejection_never_applies_checkpoint_content(self):
        """The corrupted-checkpoint FAIL path must never restore/apply
        anything from the checkpoint - the repository is untouched."""
        repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        self._delete_a_checkpoint_blob(item.item_id)
        before = _run_git_cmd(["rev-parse", "HEAD"], cwd=repo_dir).stdout
        queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "FAIL", note="reject corrupt checkpoint",
        )
        after = _run_git_cmd(["rev-parse", "HEAD"], cwd=repo_dir).stdout
        self.assertEqual(before, after)

    def test_missing_blob_fail_rejection_is_independent_of_repository_cleanliness(self):
        """A corrupted-checkpoint FAIL never trusts/depends on the current
        target repository, so it must succeed even if the repository is
        left dirty (unlike an ordinary ACCEPT/RETRY/valid-checkpoint FAIL,
        which requires a clean tree)."""
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=False)
        self._delete_a_checkpoint_blob(item.item_id)
        result = queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "FAIL", note="reject corrupt checkpoint despite dirty tree",
        )
        self.assertEqual(result.state, queue.QueueState.FAILED.value)

    def test_missing_blob_fail_rejection_is_terminal_and_not_re_reconcilable(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        self._delete_a_checkpoint_blob(item.item_id)
        queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "FAIL", note="reject corrupt checkpoint",
        )
        for resolution in ("ACCEPT", "FAIL", "RETRY"):
            with self.assertRaises(queue.QueueError) as ctx:
                queue.reconcile_checkpoint(
                    self.queue_root, item.item_id, resolution, note="second attempt",
                )
            self.assertEqual(ctx.exception.reason, "INVALID_STATE_FOR_RECONCILIATION")

    def test_missing_blob_fail_rejection_survives_reload_after_restart(self):
        """Simulates a process restart: a fresh `load_item`/`list_items`
        (never the in-memory result of the reconciling call) must observe
        the terminal FAILED state and the recorded integrity failure, and
        must not itself error out on the still-corrupted checkpoint
        directory on disk."""
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        checkpoint_id = self._delete_a_checkpoint_blob(item.item_id)
        queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "FAIL", note="reject corrupt checkpoint",
        )

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.FAILED.value)
        cp = [c for c in reloaded.checkpoints if c["checkpoint_id"] == checkpoint_id][0]
        self.assertTrue(cp["resolved"])
        self.assertTrue(cp["integrity_failed_at_reconciliation"])

        all_items = queue.list_items(self.queue_root)
        self.assertEqual([it.item_id for it in all_items], [item.item_id])

    def test_tampered_blob_hash_mismatch_permits_terminal_fail_rejection(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        loaded = queue.load_item(self.queue_root, item.item_id)
        checkpoint_id = loaded.checkpoints[-1]["checkpoint_id"]
        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / checkpoint_id
        manifest_path = checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in payload["entries"]:
            if entry.get("blob_filename"):
                blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / entry["blob_filename"]
                blob_path.write_bytes(b"tampered-bytes")
                break

        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "RETRY", note="n/a")
        self.assertEqual(ctx.exception.reason, "CHECKPOINT_INTEGRITY_FAILED")

        result = queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "FAIL", note="reject tampered checkpoint",
        )
        self.assertEqual(result.state, queue.QueueState.FAILED.value)

    def test_capture_failed_checkpoint_permits_terminal_fail_but_not_accept_or_retry(self):
        """A legacy-style capture failure (checkpoint status FAILED, never
        even published) is a distinct untrustworthy-checkpoint case from a
        missing blob, but must be governed by the same liveness rule: only
        FAIL may terminally resolve it."""
        missing_repo = self.root / "does-not-exist"
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(missing_repo), mode="read-only",
        )

        def _executor(request):
            raise RuntimeError("boom")

        result = queue.run_next(self.queue_root, executor=_executor)
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.checkpoints[-1]["status"], "FAILED")

        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "ACCEPT", note="n/a")
        self.assertEqual(ctx.exception.reason, "CHECKPOINT_NOT_CAPTURED")

        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "RETRY", note="n/a")
        self.assertEqual(ctx.exception.reason, "CHECKPOINT_NOT_CAPTURED")

        result = queue.reconcile_checkpoint(
            self.queue_root, item.item_id, "FAIL", note="repository never existed; rejecting",
        )
        self.assertEqual(result.state, queue.QueueState.FAILED.value)

    def test_reconcile_cli_fail_path_rejects_corrupt_checkpoint(self):
        """CLI-level regression: the same `reconcile --resolution FAIL` the
        operator already used in the incident now succeeds against a
        corrupted checkpoint instead of exiting non-zero."""
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir),
            mode="write", authorize_path=["src"],
        )
        (repo_dir / "src").mkdir()
        (repo_dir / "src" / "f.py").write_text("x\n", encoding="utf-8")
        run_id = "20260917T000000Z_corruptcli"
        evidence_dir = _write_evidence(repo_dir, run_id, state="SUCCESS", repository_mutated=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)
        _run_git_cmd(["add", "-A"], cwd=repo_dir)
        _run_git_cmd(["commit", "-q", "-m", "commit"], cwd=repo_dir)
        self._delete_a_checkpoint_blob(item.item_id)

        code = queue.main([
            "--queue-root", str(self.queue_root), "reconcile",
            "--item-id", item.item_id, "--resolution", "FAIL", "--note", "corrupt checkpoint",
        ])
        self.assertEqual(code, 0)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.FAILED.value)

    def test_checkpoint_remains_present_and_marked_resolved_after_reconciliation(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        result = queue.reconcile_checkpoint(self.queue_root, item.item_id, "FAIL", note="discarded")
        self.assertEqual(len(result.checkpoints), 1)
        cp = result.checkpoints[0]
        self.assertTrue(cp["resolved"])
        checkpoint_dir = self.queue_root / item.item_id / queue.CHECKPOINTS_SUBDIR_NAME / cp["checkpoint_id"]
        self.assertTrue(checkpoint_dir.exists())
        self.assertTrue((checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME).exists())

    def test_legacy_blocked_item_accept_refused(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        with queue.QueueLock(self.queue_root) as lock:
            queue.recover_orphaned_running_items(self.queue_root, lock=lock)

        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "ACCEPT", note="n/a")
        self.assertEqual(ctx.exception.reason, "ACCEPT_REQUIRES_ATTEMPT")

    def test_legacy_blocked_item_fail_allowed(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        with queue.QueueLock(self.queue_root) as lock:
            queue.recover_orphaned_running_items(self.queue_root, lock=lock)

        result = queue.reconcile_checkpoint(self.queue_root, item.item_id, "FAIL", note="cannot verify")
        self.assertEqual(result.state, queue.QueueState.FAILED.value)

    def test_failed_safety_cannot_be_reconciled(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.FAILED_SAFETY, exit_code=20, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)
        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(self.queue_root, item.item_id, "FAIL", note="n/a")
        self.assertEqual(ctx.exception.reason, "INVALID_STATE_FOR_RECONCILIATION")

    def test_generic_transition_still_cannot_leave_blocked_on_checkpoint(self):
        _repo_dir, item = self._blocked_item(runner_state="SUCCESS", clean_after=True)
        for target in (
            queue.QueueState.QUEUED, queue.QueueState.RUNNING,
            queue.QueueState.SUCCEEDED, queue.QueueState.FAILED,
        ):
            with self.assertRaises(queue.QueueError):
                queue.transition_item(self.queue_root, item.item_id, target)


    def test_reconciliation_detects_manifest_metadata_tampering(self):
        _repo_dir, item = self._blocked_item(
            runner_state="SUCCESS",
            clean_after=True,
        )

        loaded = queue.load_item(self.queue_root, item.item_id)
        checkpoint_id = loaded.checkpoints[-1]["checkpoint_id"]
        checkpoint_dir = (
            self.queue_root
            / item.item_id
            / queue.CHECKPOINTS_SUBDIR_NAME
            / checkpoint_id
        )
        manifest_path = checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["captured_at_utc"] = "2099-01-01T00:00:00+00:00"
        manifest_path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaises(queue.QueueError) as ctx:
            queue.reconcile_checkpoint(
                self.queue_root,
                item.item_id,
                "ACCEPT",
                note="must reject altered manifest",
            )

        self.assertEqual(
            ctx.exception.reason,
            "CHECKPOINT_INTEGRITY_FAILED",
        )


class ReconcileCliTest(_TempDirCase):
    def test_reconcile_cli_fail_path(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir),
            mode="write", authorize_path=["src"],
        )
        (repo_dir / "src").mkdir()
        (repo_dir / "src" / "f.py").write_text("x\n", encoding="utf-8")
        run_id = "20260916T000000Z_cliabcd"
        evidence_dir = _write_evidence(repo_dir, run_id, state="SUCCESS", repository_mutated=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)
        _run_git_cmd(["add", "-A"], cwd=repo_dir)
        _run_git_cmd(["commit", "-q", "-m", "commit"], cwd=repo_dir)

        code = queue.main([
            "--queue-root", str(self.queue_root), "reconcile",
            "--item-id", item.item_id, "--resolution", "FAIL", "--note", "cli test",
        ])
        self.assertEqual(code, 0)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.FAILED.value)

    def test_reconcile_cli_requires_note_argument(self):
        parser = queue.build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "--queue-root", str(self.queue_root), "reconcile",
                "--item-id", "x", "--resolution", "FAIL",
            ])

    def test_reconcile_cli_requires_valid_resolution_choice(self):
        parser = queue.build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "--queue-root", str(self.queue_root), "reconcile",
                "--item-id", "x", "--resolution", "MAYBE", "--note", "n",
            ])

    def test_reconcile_cli_nonzero_exit_on_dirty_repository(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir),
            mode="write", authorize_path=["src"],
        )
        (repo_dir / "src").mkdir()
        (repo_dir / "src" / "f.py").write_text("x\n", encoding="utf-8")
        run_id = "20260916T000000Z_dirtycli"
        evidence_dir = _write_evidence(repo_dir, run_id, state="SUCCESS", repository_mutated=True)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)
        # Deliberately left dirty (no commit) before reconciliation.

        code = queue.main([
            "--queue-root", str(self.queue_root), "reconcile",
            "--item-id", item.item_id, "--resolution", "ACCEPT", "--note", "n",
        ])
        self.assertNotEqual(code, 0)


# ---------------------------------------------------------------------------
# RUNNER-1.5F-A: conservative quota classification (read-only)
# ---------------------------------------------------------------------------

class QuotaClassificationReadOnlyTest(_TempDirCase):
    def test_confirmed_quota_from_cli_result_maps_to_waiting_quota(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[-1]
        self.assertEqual(attempt["quota_classification"], queue.QuotaClassification.CONFIRMED_QUOTA.value)
        self.assertEqual(attempt["quota_reason_code"], "CLI_RESULT_USAGE_LIMIT_MESSAGE")
        self.assertEqual(attempt["quota_evidence_run_id"], run_id)
        self.assertIsNotNone(attempt["quota_detected_at_utc"])

    def test_confirmed_quota_from_stderr_fallback_maps_to_waiting_quota(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output={"parsed": False, "reason": "stdout is not valid JSON"},
            stderr_text="some preamble\nClaude AI usage limit reached|1700000000\n",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)

    def test_work_order_text_mentioning_quota_never_influences_classification(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root,
            work_order_text="Please review our Claude AI usage limit reached|999 quota policy.\n",
            repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output={"parsed": True, "cli_result": {"is_error": True, "result": "unrelated tool failure"}},
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertNotIn("quota_classification", reloaded.attempts[-1])

    def test_successful_answer_content_mentioning_quota_never_triggers_waiting_quota(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        cli_output = {
            "parsed": True,
            "cli_result": {
                "is_error": False,
                "result": (
                    "The client's quota analysis is done. Claude AI usage limit "
                    "reached|123 was just an example phrase discussed."
                ),
            },
        }
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="SUCCESS", repository_mutated=False, cli_output=cli_output,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.SUCCEEDED.value)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertNotIn("quota_classification", reloaded.attempts[-1])

    def test_ambiguous_error_text_remains_not_confirmed_and_fails(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        cli_output = {"parsed": True, "cli_result": {"is_error": True, "result": "quota exceeded, please retry"}}
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False, cli_output=cli_output,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)

    def test_missing_evidence_remains_not_confirmed_and_fails(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)

    def test_malformed_result_json_remains_not_confirmed_and_fails(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / run_id
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "result.json").write_text("{not json", encoding="utf-8")
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)

    def test_pre_invocation_refusal_never_becomes_waiting_quota_even_if_state_is_claude_error(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=None,
            evidence_dir=None, error_message="deterministic pre-invocation refusal",
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)


# ---------------------------------------------------------------------------
# RUNNER-1.5F-A: quota classification precedence in write mode
# ---------------------------------------------------------------------------

def _fake_confirmed_quota_classifier(calls):
    def _classifier(item, result):
        calls.append((item, result))
        return queue.QuotaClassificationResult(
            classification=queue.QuotaClassification.CONFIRMED_QUOTA.value,
            reason_code="FAKE_INJECTED",
            detected_at_utc="2026-01-01T00:00:00+00:00",
            evidence_run_id=result.run_id,
            evidence_path=None,
        )
    return _classifier


class QuotaClassificationWriteModeTest(_TempDirCase):
    def _enqueue_write_item(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="Edit something.\n", repository_path=str(repo_dir),
            mode="write", authorize_path=["src"],
        )
        return repo_dir, item

    def test_write_confirmed_quota_without_mutation_maps_to_waiting_quota(self):
        repo_dir, _item = self._enqueue_write_item()
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)

    def test_write_confirmed_quota_with_mutation_still_blocks_on_checkpoint(self):
        repo_dir, _item = self._enqueue_write_item()
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=True,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        calls = []
        result = queue.run_next(
            self.queue_root, executor=executor,
            quota_classifier=_fake_confirmed_quota_classifier(calls),
        )
        self.assertEqual(result.queue_state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertIsNotNone(result.checkpoint_id)
        self.assertEqual(calls, [], "checkpoint safety must win without ever consulting the classifier")

    def test_write_missing_safety_evidence_fails_safety_even_with_confirmed_quota_classifier(self):
        self._enqueue_write_item()
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        calls = []
        result = queue.run_next(
            self.queue_root, executor=executor,
            quota_classifier=_fake_confirmed_quota_classifier(calls),
        )
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)
        self.assertEqual(calls, [], "FAILED_SAFETY must win without ever consulting the classifier")


class QuotaClassifierPrecedenceTest(_TempDirCase):
    def test_failed_safety_precedes_quota_classification(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.FAILED_SAFETY, exit_code=20, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        calls = []
        result = queue.run_next(
            self.queue_root, executor=executor,
            quota_classifier=_fake_confirmed_quota_classifier(calls),
        )
        self.assertEqual(result.queue_state, queue.QueueState.FAILED_SAFETY.value)
        self.assertEqual(calls, [])


# ---------------------------------------------------------------------------
# RUNNER-1.5F-A: WAITING_QUOTA attempt durability and audit metadata
# ---------------------------------------------------------------------------

class QuotaAttemptDurabilityTest(_TempDirCase):
    def _waiting_quota_item(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)
        return repo_dir, item

    def test_waiting_quota_attempt_finalized_not_running(self):
        _repo_dir, item = self._waiting_quota_item()
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.WAITING_QUOTA.value)
        attempt = reloaded.attempts[-1]
        self.assertEqual(attempt["status"], "COMPLETED")
        self.assertIsNotNone(attempt["ended_at_utc"])
        self.assertEqual(attempt["final_queue_state"], queue.QueueState.WAITING_QUOTA.value)

    def test_no_checkpoint_created_for_waiting_quota(self):
        _repo_dir, item = self._waiting_quota_item()
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.checkpoints, [])

    def test_generic_transition_still_cannot_leave_waiting_quota(self):
        _repo_dir, item = self._waiting_quota_item()
        for target in (
            queue.QueueState.QUEUED, queue.QueueState.RUNNING,
            queue.QueueState.SUCCEEDED, queue.QueueState.FAILED,
        ):
            with self.assertRaises(queue.QueueError):
                queue.transition_item(self.queue_root, item.item_id, target)


class QuotaNoConversationalDataPersistedTest(_TempDirCase):
    def test_quota_attempt_record_allowed_keys_and_no_session_data(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[-1]
        allowed_keys = {
            "attempt_id", "started_at_utc", "ended_at_utc", "status",
            "runner_state", "runner_exit_code", "runner_run_id",
            "runner_evidence_dir", "final_queue_state",
            "quota_classification", "quota_reason_code", "quota_detected_at_utc",
            "quota_evidence_run_id", "quota_evidence_path",
            "quota_reset_epoch", "quota_retry_not_before_utc",
        }
        self.assertEqual(set(attempt.keys()), allowed_keys)

        raw_text = (self.queue_root / item.item_id / queue.ITEM_METADATA_FILENAME).read_text(
            encoding="utf-8"
        )
        for forbidden in ("session_id", "conversation_id", "transcript", "--resume", "--continue"):
            self.assertNotIn(forbidden, raw_text)


# ---------------------------------------------------------------------------
# RUNNER-1.5F-B1: trusted quota reset-time extraction and durable metadata
# ---------------------------------------------------------------------------

class QuotaResetMetadataExtractionTest(_TempDirCase):
    def test_confirmed_quota_from_cli_result_persists_epoch_and_utc_retry_time(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[-1]
        self.assertEqual(attempt["quota_reset_epoch"], 1700000000)
        self.assertEqual(
            attempt["quota_retry_not_before_utc"], queue._epoch_seconds_to_utc_iso(1700000000),
        )
        parsed = datetime.fromisoformat(attempt["quota_retry_not_before_utc"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_confirmed_quota_from_stderr_fallback_persists_epoch_and_utc_retry_time(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output={"parsed": False, "reason": "stdout is not valid JSON"},
            stderr_text="some preamble\nClaude AI usage limit reached|1700000500\n",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[-1]
        self.assertEqual(attempt["quota_reset_epoch"], 1700000500)
        self.assertEqual(
            attempt["quota_retry_not_before_utc"], queue._epoch_seconds_to_utc_iso(1700000500),
        )

    def test_work_order_text_mentioning_epoch_cannot_produce_reset_metadata(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root,
            work_order_text="Please review our Claude AI usage limit reached|1700000000 quota policy.\n",
            repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output={"parsed": True, "cli_result": {"is_error": True, "result": "unrelated tool failure"}},
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.FAILED.value)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[-1]
        self.assertNotIn("quota_reset_epoch", attempt)
        self.assertNotIn("quota_retry_not_before_utc", attempt)

    def test_successful_answer_mentioning_epoch_cannot_produce_reset_metadata(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        cli_output = {
            "parsed": True,
            "cli_result": {
                "is_error": False,
                "result": (
                    "Everything succeeded. Claude AI usage limit reached|1700000000 "
                    "was just an example phrase discussed."
                ),
            },
        }
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="SUCCESS", repository_mutated=False, cli_output=cli_output,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.SUCCEEDED.value)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[-1]
        self.assertNotIn("quota_reset_epoch", attempt)
        self.assertNotIn("quota_retry_not_before_utc", attempt)

    def test_extreme_digit_epoch_remains_confirmed_without_retry_metadata(self):
        repo_dir = self.root / "repo_extreme_epoch"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root,
            work_order_text="content\n",
            repository_path=str(repo_dir),
            mode="read-only",
        )

        huge_epoch = "9" * 5000
        run_id = "20260916T000000Z_extremeepoch"
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir,
            run_id,
            state="CLAUDE_ERROR",
            repository_mutated=False,
            cli_output={
                "parsed": True,
                "cli_result": {
                    "is_error": True,
                    "result": f"Claude AI usage limit reached|{huge_epoch}",
                },
            },
        )

        result = queue.classify_quota_default(
            item,
            runner.WorkOrderResult(
                state=runner.RunState.CLAUDE_ERROR,
                exit_code=3,
                run_id=run_id,
                evidence_dir=evidence_dir,
                error_message=None,
            ),
        )

        self.assertEqual(
            result.classification,
            queue.QuotaClassification.CONFIRMED_QUOTA.value,
        )
        self.assertIsNone(result.quota_reset_epoch)
        self.assertIsNone(result.quota_retry_not_before_utc)


    def test_unrepresentable_epoch_remains_confirmed_without_retry_timestamp(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        huge_epoch = "9" * 30
        cli_output = {
            "parsed": True,
            "cli_result": {"is_error": True, "result": f"Claude AI usage limit reached|{huge_epoch}"},
        }
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False, cli_output=cli_output,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        attempt = reloaded.attempts[-1]
        self.assertEqual(attempt["quota_classification"], queue.QuotaClassification.CONFIRMED_QUOTA.value)
        self.assertEqual(attempt["quota_reset_epoch"], int(huge_epoch))
        self.assertIsNone(attempt["quota_retry_not_before_utc"])


class EpochToUtcIsoHelperTest(unittest.TestCase):
    def test_epoch_zero_converts_to_unix_epoch_utc(self):
        self.assertEqual(queue._epoch_seconds_to_utc_iso(0), "1970-01-01T00:00:00+00:00")

    def test_known_epoch_converts_to_aware_utc_datetime(self):
        iso = queue._epoch_seconds_to_utc_iso(1700000000)
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_unrepresentable_epoch_returns_none_without_raising(self):
        self.assertIsNone(queue._epoch_seconds_to_utc_iso(10 ** 30))


# ---------------------------------------------------------------------------
# RUNNER-1.5F-B1: backward-compatible loading of pre-existing quota attempts
# ---------------------------------------------------------------------------

class BackwardCompatibleQuotaAttemptLoadingTest(_TempDirCase):
    def test_old_waiting_quota_item_without_reset_fields_loads_and_is_not_due(self):
        repo_dir = self.root / "repo"
        repo_dir.mkdir()
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        item_dir = self.queue_root / item.item_id
        metadata_path = item_dir / queue.ITEM_METADATA_FILENAME
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        payload["state"] = queue.QueueState.WAITING_QUOTA.value
        payload["attempts"] = [{
            # Deliberately the exact pre-RUNNER-1.5F-B1 attempt shape: no
            # quota_reset_epoch / quota_retry_not_before_utc keys at all.
            "attempt_id": "attempt_legacy",
            "started_at_utc": "2026-01-01T00:00:00+00:00",
            "ended_at_utc": "2026-01-01T00:05:00+00:00",
            "status": "COMPLETED",
            "runner_state": "CLAUDE_ERROR",
            "runner_exit_code": 3,
            "runner_run_id": "run_legacy",
            "runner_evidence_dir": None,
            "final_queue_state": queue.QueueState.WAITING_QUOTA.value,
            "quota_classification": queue.QuotaClassification.CONFIRMED_QUOTA.value,
            "quota_reason_code": "CLI_RESULT_USAGE_LIMIT_MESSAGE",
            "quota_detected_at_utc": "2026-01-01T00:05:00+00:00",
            "quota_evidence_run_id": "run_legacy",
            "quota_evidence_path": None,
        }]
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.WAITING_QUOTA.value)
        self.assertFalse(queue.is_waiting_quota_due(reloaded))
        self.assertFalse(
            queue.is_waiting_quota_due(reloaded, now_utc=datetime(2099, 1, 1, tzinfo=timezone.utc))
        )


# ---------------------------------------------------------------------------
# RUNNER-1.5F-B1: pure due-time predicate (is_waiting_quota_due)
# ---------------------------------------------------------------------------

def _make_bare_item(*, state: str, attempts=None) -> "queue.QueueItem":
    now = "2026-01-01T00:00:00+00:00"
    return queue.QueueItem(
        schema_version=queue.SCHEMA_VERSION,
        item_id="item1",
        created_at_utc=now,
        updated_at_utc=now,
        state=state,
        repository_path="repo",
        mode="read-only",
        authorize_path=[],
        timeout_seconds=None,
        model=None,
        label=None,
        work_order_filename=queue.WORK_ORDER_FILENAME,
        work_order_sha256="0" * 64,
        history=[],
        attempts=attempts or [],
        checkpoints=[],
    )


def _make_quota_attempt(*, final_queue_state="WAITING_QUOTA", quota_classification="CONFIRMED_QUOTA",
                         quota_retry_not_before_utc="2026-06-01T00:00:00+00:00", **overrides):
    attempt = {
        "attempt_id": "attempt_1",
        "started_at_utc": "2026-01-01T00:00:00+00:00",
        "ended_at_utc": "2026-01-01T00:05:00+00:00",
        "status": "COMPLETED",
        "runner_state": "CLAUDE_ERROR",
        "runner_exit_code": 3,
        "runner_run_id": "run1",
        "runner_evidence_dir": "/evidence",
        "final_queue_state": final_queue_state,
        "quota_classification": quota_classification,
        "quota_reason_code": "CLI_RESULT_USAGE_LIMIT_MESSAGE",
        "quota_detected_at_utc": "2026-01-01T00:05:00+00:00",
        "quota_evidence_run_id": "run1",
        "quota_evidence_path": "/evidence",
        "quota_reset_epoch": 1780358400,
        "quota_retry_not_before_utc": quota_retry_not_before_utc,
    }
    attempt.update(overrides)
    return attempt


class IsWaitingQuotaDueTest(unittest.TestCase):
    def test_false_before_reset_time(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[_make_quota_attempt()])
        now = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=now))

    def test_true_exactly_at_reset_time(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[_make_quota_attempt()])
        now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(queue.is_waiting_quota_due(item, now_utc=now))

    def test_true_after_reset_time(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[_make_quota_attempt()])
        now = datetime(2026, 6, 2, 0, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(queue.is_waiting_quota_due(item, now_utc=now))

    def test_default_now_utc_uses_current_time_when_omitted(self):
        item = _make_bare_item(
            state=queue.QueueState.WAITING_QUOTA.value,
            attempts=[_make_quota_attempt(quota_retry_not_before_utc="2000-01-01T00:00:00+00:00")],
        )
        self.assertTrue(queue.is_waiting_quota_due(item))

    def test_false_for_queued_state(self):
        item = _make_bare_item(
            state=queue.QueueState.QUEUED.value,
            attempts=[_make_quota_attempt(final_queue_state="QUEUED")],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_for_failed_state(self):
        item = _make_bare_item(
            state=queue.QueueState.FAILED.value,
            attempts=[_make_quota_attempt(final_queue_state="FAILED")],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_for_succeeded_state(self):
        item = _make_bare_item(
            state=queue.QueueState.SUCCEEDED.value,
            attempts=[_make_quota_attempt(final_queue_state="SUCCEEDED")],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_when_latest_attempt_is_not_the_quota_attempt(self):
        item = _make_bare_item(
            state=queue.QueueState.WAITING_QUOTA.value,
            attempts=[_make_quota_attempt(), _make_quota_attempt(final_queue_state="FAILED")],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_when_latest_attempt_classification_is_not_confirmed(self):
        item = _make_bare_item(
            state=queue.QueueState.WAITING_QUOTA.value,
            attempts=[_make_quota_attempt(quota_classification="NOT_CONFIRMED")],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_when_no_attempts(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[])
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_for_old_item_missing_retry_timestamp_key_entirely(self):
        legacy_attempt = _make_quota_attempt()
        del legacy_attempt["quota_retry_not_before_utc"]
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[legacy_attempt])
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_for_none_retry_timestamp(self):
        item = _make_bare_item(
            state=queue.QueueState.WAITING_QUOTA.value,
            attempts=[_make_quota_attempt(quota_retry_not_before_utc=None)],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_for_malformed_retry_timestamp(self):
        item = _make_bare_item(
            state=queue.QueueState.WAITING_QUOTA.value,
            attempts=[_make_quota_attempt(quota_retry_not_before_utc="not-a-timestamp")],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    def test_false_for_naive_persisted_retry_timestamp(self):
        item = _make_bare_item(
            state=queue.QueueState.WAITING_QUOTA.value,
            attempts=[_make_quota_attempt(quota_retry_not_before_utc="2026-06-01T00:00:00")],
        )
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 2, tzinfo=timezone.utc)))

    def test_false_for_naive_injected_now_utc(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[_make_quota_attempt()])
        naive_now = datetime(2026, 6, 2, 0, 0, 0)
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=naive_now))

    def test_injected_aware_time_is_deterministic(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[_make_quota_attempt()])
        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        far_past = datetime(1999, 1, 1, tzinfo=timezone.utc)
        self.assertTrue(queue.is_waiting_quota_due(item, now_utc=far_future))
        self.assertFalse(queue.is_waiting_quota_due(item, now_utc=far_past))

    def test_non_utc_aware_now_is_normalized_before_comparison(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[_make_quota_attempt()])
        plus_two = timezone(timedelta(hours=2))
        # 2026-06-01T02:00:00+02:00 == 2026-06-01T00:00:00 UTC, exactly at reset.
        now = datetime(2026, 6, 1, 2, 0, 0, tzinfo=plus_two)
        self.assertTrue(queue.is_waiting_quota_due(item, now_utc=now))

    def test_no_mutation_or_side_effects(self):
        item = _make_bare_item(state=queue.QueueState.WAITING_QUOTA.value, attempts=[_make_quota_attempt()])
        before = json.dumps(queue._item_to_dict(item), sort_keys=True)
        queue.is_waiting_quota_due(item, now_utc=datetime(2026, 6, 1, tzinfo=timezone.utc))
        after = json.dumps(queue._item_to_dict(item), sort_keys=True)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# RUNNER-1.5F-A: explicit fresh requeue (resume_waiting_quota)
# ---------------------------------------------------------------------------

class ResumeWaitingQuotaTest(_TempDirCase):
    def _waiting_quota_item(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)
        return repo_dir, item

    def test_resume_transitions_to_queued_and_next_run_next_creates_fresh_attempt(self):
        repo_dir, item = self._waiting_quota_item()
        result = queue.resume_waiting_quota(self.queue_root, item.item_id, note="reset time passed")
        self.assertEqual(result.state, queue.QueueState.QUEUED.value)
        self.assertEqual(len(result.attempts), 1, "resume itself must never create a new attempt")
        first_attempt_id = result.attempts[0]["attempt_id"]

        run_id2 = "20260916T000000Z_freshdone"
        evidence_dir2 = _write_evidence(repo_dir, run_id2, state="SUCCESS", repository_mutated=False)
        executor2 = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id2,
            evidence_dir=evidence_dir2, error_message=None,
        ))
        next_result = queue.run_next(self.queue_root, executor=executor2)
        self.assertEqual(next_result.outcome, queue.RunNextOutcome.DISPATCHED.value)
        self.assertEqual(next_result.queue_state, queue.QueueState.SUCCEEDED.value)
        self.assertNotEqual(next_result.attempt_id, first_attempt_id)
        self.assertEqual(len(executor2.calls), 1)

    def test_resume_requires_non_empty_note(self):
        _repo_dir, item = self._waiting_quota_item()
        with self.assertRaises(queue.QueueError) as ctx:
            queue.resume_waiting_quota(self.queue_root, item.item_id, note="   ")
        self.assertEqual(ctx.exception.reason, "MISSING_NOTE")

    def test_resume_refuses_dirty_repository(self):
        repo_dir, item = self._waiting_quota_item()
        (repo_dir / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        with self.assertRaises(queue.QueueError) as ctx:
            queue.resume_waiting_quota(self.queue_root, item.item_id, note="attempt resume")
        self.assertEqual(ctx.exception.reason, "DIRTY_REPOSITORY")

    def test_resume_refuses_wrong_state(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        with self.assertRaises(queue.QueueError) as ctx:
            queue.resume_waiting_quota(self.queue_root, item.item_id, note="n/a")
        self.assertEqual(ctx.exception.reason, "INVALID_STATE_FOR_RESUME")

    def test_resume_performs_no_executor_invocation(self):
        _repo_dir, item = self._waiting_quota_item()
        result = queue.resume_waiting_quota(self.queue_root, item.item_id, note="no executor call")
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(result.attempts[0]["status"], "COMPLETED")

    def test_resume_history_event_references_prior_attempt_and_quota_reason(self):
        _repo_dir, item = self._waiting_quota_item()
        result = queue.resume_waiting_quota(self.queue_root, item.item_id, note="resumed after reset")
        last_event = result.history[-1]
        self.assertEqual(last_event["event"], "RESUME_WAITING_QUOTA:WAITING_QUOTA->QUEUED")
        self.assertIn("prior_attempt_id=", last_event["detail"])
        self.assertIn("quota_reason_code=CLI_RESULT_USAGE_LIMIT_MESSAGE", last_event["detail"])
        self.assertIn("note=resumed after reset", last_event["detail"])

    def test_resume_allowed_even_when_reset_time_is_still_in_the_future(self):
        # RUNNER-1.5F-B1: is_waiting_quota_due() must never gate the
        # existing, explicit, governed manual resume primitive - resuming
        # is always an explicit operator action regardless of the durable
        # retry-not-before instant.
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        future_epoch = 9999999999  # far future, still representable (~year 2286)
        cli_output = {
            "parsed": True,
            "cli_result": {"is_error": True, "result": f"Claude AI usage limit reached|{future_epoch}"},
        }
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False, cli_output=cli_output,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        result = queue.run_next(self.queue_root, executor=executor)
        self.assertEqual(result.queue_state, queue.QueueState.WAITING_QUOTA.value)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertFalse(queue.is_waiting_quota_due(reloaded, now_utc=datetime.now(timezone.utc)))

        resumed = queue.resume_waiting_quota(
            self.queue_root, item.item_id, note="operator resumes before reset"
        )
        self.assertEqual(resumed.state, queue.QueueState.QUEUED.value)


class ResumeQuotaCliTest(_TempDirCase):
    def test_resume_quota_cli_requires_item_id_and_note(self):
        parser = queue.build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--queue-root", str(self.queue_root), "resume-quota"])

    def test_resume_quota_cli_success_path(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_clisuccess"
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)

        code = queue.main([
            "--queue-root", str(self.queue_root), "resume-quota",
            "--item-id", item.item_id, "--note", "reset time passed",
        ])
        self.assertEqual(code, 0)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.QUEUED.value)

    def test_resume_quota_cli_nonzero_exit_on_dirty_repository(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        run_id = "20260916T000000Z_clidirty"
        evidence_dir = _write_evidence_with_cli_output(
            repo_dir, run_id, state="CLAUDE_ERROR", repository_mutated=False,
            cli_output=_CONFIRMED_QUOTA_CLI_OUTPUT,
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        ))
        queue.run_next(self.queue_root, executor=executor)
        (repo_dir / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

        code = queue.main([
            "--queue-root", str(self.queue_root), "resume-quota",
            "--item-id", item.item_id, "--note", "n",
        ])
        self.assertNotEqual(code, 0)


# ---------------------------------------------------------------------------
# RUNNER-1.5F-B2A: governed single-worker supervisor cycle (supervisor_once)
# ---------------------------------------------------------------------------

class SupervisorOnceEmptyQueueTest(_TempDirCase):
    def test_empty_queue_performs_zero_executor_calls(self):
        result = queue.supervisor_once(self.queue_root, executor=_explode_if_called)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.NO_WORK.value)
        self.assertEqual(result.reason, queue.SupervisorReason.NO_QUEUED_WORK.value)


class SupervisorOnceOrdinaryDispatchTest(_TempDirCase):
    def test_ordinary_queued_work_dispatches_exactly_once(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        result = queue.supervisor_once(self.queue_root, executor=executor)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.DISPATCHED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.DISPATCHED_QUEUED_ITEM.value)
        self.assertEqual(result.queue_state, queue.QueueState.SUCCEEDED.value)
        self.assertEqual(len(executor.calls), 1)


class SupervisorOnceOrphanRecoveryTest(_TempDirCase):
    def test_running_orphan_recovers_without_dispatch(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)

        result = queue.supervisor_once(self.queue_root, executor=_explode_if_called)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.RECOVERY_REQUIRED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.ORPHAN_RECOVERY_REQUIRED.value)
        self.assertEqual(result.recovered_item_ids, [item.item_id])

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)


class SupervisorOnceCheckpointBarrierTest(_TempDirCase):
    def test_blocked_checkpoint_prevents_dispatch_of_other_queued_work(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        blocked_item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        queue.transition_item(self.queue_root, blocked_item.item_id, queue.QueueState.RUNNING)
        recovery = queue.run_next(self.queue_root, executor=_explode_if_called)
        self.assertEqual(recovery.outcome, queue.RunNextOutcome.RECOVERY_REQUIRED.value)
        reloaded = queue.load_item(self.queue_root, blocked_item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

        queue.enqueue(
            self.queue_root, work_order_text="other\n", repository_path=str(repo_dir), mode="read-only",
        )

        result = queue.supervisor_once(self.queue_root, executor=_explode_if_called)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.CHECKPOINT_PENDING_RECONCILIATION.value)
        self.assertEqual(result.item_id, blocked_item.item_id)


class SupervisorOnceManualQuotaBarrierTest(_TempDirCase):
    def test_manual_only_quota_barrier_blocks_dispatch_without_mutation(self):
        # Unrepresentable epoch: CONFIRMED_QUOTA but no trusted retry time
        # (mirrors QuotaResetMetadataExtractionTest's unrepresentable-epoch
        # case), leaving the item manual-resume-only.
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch_str="9" * 30)
        queue.enqueue(
            self.queue_root, work_order_text="other\n", repository_path=str(repo_dir), mode="read-only",
        )
        before = queue.load_item(self.queue_root, item.item_id)

        result = queue.supervisor_once(self.queue_root, executor=_explode_if_called)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.QUOTA_MANUAL_RESUME_REQUIRED.value)
        self.assertEqual(result.item_id, item.item_id)

        after = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(before.updated_at_utc, after.updated_at_utc)
        self.assertEqual(before.history, after.history)


class SupervisorOnceTrustedFutureBarrierTest(_TempDirCase):
    def test_future_trusted_barrier_returns_next_wake_utc_without_mutation(self):
        future_epoch = 4102444800  # 2100-01-01T00:00:00Z
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=future_epoch)
        before = queue.load_item(self.queue_root, item.item_id)

        result = queue.supervisor_once(
            self.queue_root, executor=_explode_if_called,
            now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.outcome, queue.SupervisorOutcome.WAITING_QUOTA.value)
        self.assertEqual(result.reason, queue.SupervisorReason.QUOTA_BARRIER_NOT_DUE.value)
        self.assertEqual(result.next_wake_utc, queue._epoch_seconds_to_utc_iso(future_epoch))

        after = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(before.updated_at_utc, after.updated_at_utc)
        self.assertEqual(before.state, after.state)


class SupervisorOnceMultipleFutureBarriersTest(_TempDirCase):
    def test_next_wake_utc_is_latest_across_multiple_future_barriers(self):
        earlier_epoch = 4102444800  # 2100-01-01T00:00:00Z
        later_epoch = 4133980800  # 2101-01-01T00:00:00Z
        _make_confirmed_quota_item(self.root, self.queue_root, repo_name="repo_a", epoch=earlier_epoch)
        _make_confirmed_quota_item(self.root, self.queue_root, repo_name="repo_b", epoch=later_epoch)

        result = queue.supervisor_once(
            self.queue_root, executor=_explode_if_called,
            now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.outcome, queue.SupervisorOutcome.WAITING_QUOTA.value)
        self.assertEqual(result.next_wake_utc, queue._epoch_seconds_to_utc_iso(later_epoch))


class SupervisorOnceMixedQuotaStatesTest(_TempDirCase):
    def test_mixed_trusted_and_manual_only_fails_to_manual_with_no_mutation(self):
        _repo_a, manual_item = _make_confirmed_quota_item(
            self.root, self.queue_root, repo_name="repo_a", epoch_str="9" * 30,
        )
        _repo_b, trusted_item = _make_confirmed_quota_item(
            self.root, self.queue_root, repo_name="repo_b", epoch=4102444800,
        )
        before_manual = queue.load_item(self.queue_root, manual_item.item_id)
        before_trusted = queue.load_item(self.queue_root, trusted_item.item_id)

        result = queue.supervisor_once(
            self.queue_root, executor=_explode_if_called,
            now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.outcome, queue.SupervisorOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.QUOTA_MANUAL_RESUME_REQUIRED.value)

        after_manual = queue.load_item(self.queue_root, manual_item.item_id)
        after_trusted = queue.load_item(self.queue_root, trusted_item.item_id)
        self.assertEqual(before_manual.updated_at_utc, after_manual.updated_at_utc)
        self.assertEqual(before_trusted.updated_at_utc, after_trusted.updated_at_utc)


class SupervisorOnceAutoRequeueTest(_TempDirCase):
    def test_all_due_quota_state_auto_requeues_one_item_and_dispatches_once(self):
        past_epoch = 1000000000  # 2001-09-09, unambiguously due by 2026
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=past_epoch)
        prior = queue.load_item(self.queue_root, item.item_id)
        prior_attempt_id = prior.attempts[-1]["attempt_id"]
        prior_quota_reason = prior.attempts[-1]["quota_reason_code"]

        run_id2 = "20260916T000000Z_freshafterauto"
        evidence_dir2 = _write_evidence(repo_dir, run_id2, state="SUCCESS", repository_mutated=False)
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id2,
            evidence_dir=evidence_dir2, error_message=None,
        ))

        result = queue.supervisor_once(
            self.queue_root, executor=executor, now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.outcome, queue.SupervisorOutcome.DISPATCHED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.QUOTA_AUTO_RESUMED_THEN_DISPATCHED.value)
        self.assertEqual(result.auto_resumed_item_id, item.item_id)
        self.assertEqual(result.queue_state, queue.QueueState.SUCCEEDED.value)
        self.assertEqual(len(executor.calls), 1)

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(len(reloaded.attempts), 2, "auto-resume itself must never create a new attempt")
        fresh_attempt_id = reloaded.attempts[1]["attempt_id"]
        self.assertNotEqual(fresh_attempt_id, prior_attempt_id)
        self.assertEqual(fresh_attempt_id, result.attempt_id)

        auto_events = [
            h for h in reloaded.history
            if h["event"] == "AUTO_RESUME_WAITING_QUOTA:WAITING_QUOTA->QUEUED"
        ]
        self.assertEqual(len(auto_events), 1)
        detail = auto_events[0]["detail"]
        self.assertIn(f"prior_attempt_id={prior_attempt_id}", detail)
        self.assertIn(f"quota_reason_code={prior_quota_reason}", detail)
        self.assertIn("head=", detail)
        self.assertNotIn("note=", detail, "must never pretend to be a human/operator note")


class SupervisorOnceAutoRequeueSafetyStopTest(_TempDirCase):
    _PAST_EPOCH = 1000000000  # 2001-09-09, unambiguously due by 2026
    _NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_dirty_repository_stops_fail_closed_without_dispatch(self):
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=self._PAST_EPOCH)
        (repo_dir / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        before = queue.load_item(self.queue_root, item.item_id)

        result = queue.supervisor_once(self.queue_root, executor=_explode_if_called, now_utc=self._NOW)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.SAFETY_STOP.value)
        self.assertIn("DIRTY_REPOSITORY", result.reason)

        after = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(before.state, after.state)
        self.assertEqual(before.updated_at_utc, after.updated_at_utc)

    def test_unresolved_checkpoint_stops_fail_closed_without_dispatch(self):
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=self._PAST_EPOCH)
        item_dir = self.queue_root / item.item_id
        metadata_path = item_dir / queue.ITEM_METADATA_FILENAME
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        payload["checkpoints"] = [{
            "checkpoint_id": "cp_test", "item_id": item.item_id, "attempt_id": None,
            "captured_at_utc": "2026-01-01T00:00:00+00:00", "repository_path": str(repo_dir),
            "head": None, "status": "CAPTURED", "error": None,
            "manifest_filename": None, "manifest_sha256": None,
            "patch_filename": None, "patch_sha256": None, "entry_count": 0,
            "resolved": False, "resolution": None, "resolved_at_utc": None, "resolution_note": None,
        }]
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        result = queue.supervisor_once(self.queue_root, executor=_explode_if_called, now_utc=self._NOW)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.SAFETY_STOP.value)
        self.assertIn("UNRESOLVED_CHECKPOINT", result.reason)

    def test_invalid_repository_stops_fail_closed_without_dispatch(self):
        repo_dir, item = _make_confirmed_quota_item(
            self.root,
            self.queue_root,
            epoch=self._PAST_EPOCH,
        )

        # Cross-platform way to make this temporary repository cease being a
        # Git work tree. Avoid deleting .git: Windows may temporarily deny
        # removal of object files even though the production behavior under
        # test is only `_git_is_worktree(...) == False`.
        _run_git_cmd(["config", "core.bare", "true"], cwd=repo_dir)

        result = queue.supervisor_once(self.queue_root, executor=_explode_if_called, now_utc=self._NOW)
        self.assertEqual(result.outcome, queue.SupervisorOutcome.SAFETY_STOP.value)
        self.assertIn("INVALID_REPOSITORY", result.reason)


class AutoResumeRevalidationTest(_TempDirCase):
    """RUNNER-1.5F-B2A: `_auto_resume_one_waiting_quota_item` must re-load
    and re-validate durable state under its own lock rather than trusting a
    decision computed by an earlier planning read, even when called
    directly (as a later looping supervisor eventually would, cycle after
    cycle)."""

    def test_item_no_longer_waiting_quota_is_revalidated_and_refused(self):
        _repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=1000000000)
        queue.resume_waiting_quota(self.queue_root, item.item_id, note="operator got there first")

        with self.assertRaises(queue.QueueError) as ctx:
            queue._auto_resume_one_waiting_quota_item(
                self.queue_root, item.item_id, now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(ctx.exception.reason, "INVALID_STATE_FOR_AUTO_RESUME")

    def test_item_no_longer_due_at_mutation_time_is_revalidated_and_refused(self):
        future_epoch = 4102444800  # 2100-01-01T00:00:00Z
        _repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=future_epoch)

        with self.assertRaises(queue.QueueError) as ctx:
            queue._auto_resume_one_waiting_quota_item(
                self.queue_root, item.item_id, now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(ctx.exception.reason, "QUOTA_NOT_DUE_AT_MUTATION_TIME")


class SupervisorOnceNowUtcValidationTest(_TempDirCase):
    def test_invalid_now_utc_fails_closed(self):
        with self.assertRaises(queue.QueueError) as ctx:
            queue.supervisor_once(
                self.queue_root, executor=_explode_if_called,
                now_utc=datetime(2026, 1, 1),  # naive, must be refused
            )
        self.assertEqual(ctx.exception.reason, "INVALID_NOW_UTC")


class SupervisorOnceStaticSafetyTest(unittest.TestCase):
    def test_no_sleep_or_poll_loop(self):
        source = "\n".join([
            inspect.getsource(queue.supervisor_once),
            inspect.getsource(queue._handle_quota_barrier),
            inspect.getsource(queue._auto_resume_one_waiting_quota_item),
        ])
        for forbidden in ("time.sleep", "sleep(", "while True", "while 1", "for _ in itertools.count"):
            self.assertNotIn(forbidden, source)


class SupervisorOnceCliTest(_TempDirCase):
    def test_supervisor_once_cli_no_work_is_not_an_error(self):
        code = queue.main(["--queue-root", str(self.queue_root), "supervisor-once"])
        self.assertEqual(code, 0)

    def test_supervisor_once_cli_reports_operator_required_for_blocked_checkpoint(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        queue.run_next(self.queue_root, executor=_explode_if_called)

        code = queue.main(["--queue-root", str(self.queue_root), "supervisor-once"])
        self.assertEqual(code, 0)
        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)

    def test_supervisor_once_cli_lock_contention_is_an_error(self):
        holder = queue.QueueLock(self.queue_root)
        holder.acquire(blocking=False)
        try:
            code = queue.main(["--queue-root", str(self.queue_root), "supervisor-once"])
            self.assertNotEqual(code, 0)
        finally:
            holder.release()


# ---------------------------------------------------------------------------
# supervisor_once: one uninterrupted lock scope (RUNNER-1.5F-B2A-FIX1)
# ---------------------------------------------------------------------------

class SupervisorOnceLockScopeTest(_TempDirCase):
    """Proves the TOCTOU window FIX1 closes stays closed: the exclusive
    QueueLock is already held before supervisor_once's first global
    list_items() observation, and a second contender can never acquire it
    while that observation, an injected executor call, or an all-due quota
    auto-resume followed by dispatch is in progress."""

    def test_global_observation_happens_with_lock_already_held(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        contention_could_acquire = []
        real_list_items = queue.list_items

        def _spy_list_items(queue_root):
            contender = queue.QueueLock(queue_root)
            try:
                contender.acquire(blocking=False)
            except queue.QueueLockError:
                contention_could_acquire.append(False)
            else:
                contention_could_acquire.append(True)
                contender.release()
            return real_list_items(queue_root)

        queue.list_items = _spy_list_items
        try:
            result = queue.supervisor_once(
                self.queue_root,
                executor=_RecordingExecutor(runner.WorkOrderResult(
                    state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
                    evidence_dir=None, error_message=None,
                )),
            )
        finally:
            queue.list_items = real_list_items

        self.assertTrue(contention_could_acquire, "list_items was never observed")
        self.assertFalse(
            any(contention_could_acquire),
            "a second lock contender must never acquire while supervisor_once holds the lock",
        )
        self.assertEqual(result.outcome, queue.SupervisorOutcome.DISPATCHED.value)

    def test_lock_remains_held_during_injected_executor_call(self):
        queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        contention_could_acquire = []

        def _executor(request):
            contender = queue.QueueLock(self.queue_root)
            try:
                contender.acquire(blocking=False)
            except queue.QueueLockError:
                contention_could_acquire.append(False)
            else:
                contention_could_acquire.append(True)
                contender.release()
            return runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
                evidence_dir=None, error_message=None,
            )

        result = queue.supervisor_once(self.queue_root, executor=_executor)
        self.assertEqual(contention_could_acquire, [False])
        self.assertEqual(result.outcome, queue.SupervisorOutcome.DISPATCHED.value)

    def test_lock_remains_held_across_all_due_auto_resume_and_dispatch(self):
        past_epoch = 1000000000  # 2001-09-09, unambiguously due by 2026
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=past_epoch)
        run_id2 = "20260916T000000Z_" + uuid.uuid4().hex[:8]
        evidence_dir2 = _write_evidence(repo_dir, run_id2, state="SUCCESS", repository_mutated=False)
        contention_could_acquire = []

        def _executor(request):
            contender = queue.QueueLock(self.queue_root)
            try:
                contender.acquire(blocking=False)
            except queue.QueueLockError:
                contention_could_acquire.append(False)
            else:
                contention_could_acquire.append(True)
                contender.release()
            return runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id2,
                evidence_dir=evidence_dir2, error_message=None,
            )

        result = queue.supervisor_once(
            self.queue_root, executor=_executor, now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(contention_could_acquire, [False])
        self.assertEqual(result.outcome, queue.SupervisorOutcome.DISPATCHED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.QUOTA_AUTO_RESUMED_THEN_DISPATCHED.value)
        self.assertEqual(result.auto_resumed_item_id, item.item_id)


class LockHeldPrimitivesRejectUnheldOrWrongRootLockTest(_TempDirCase):
    """RUNNER-1.5F-B2A-FIX1: `_run_next_locked` and
    `_auto_resume_one_waiting_quota_item_locked` must fail closed
    (QueueLockError) when passed an unheld lock or a lock actively held for
    a different queue root, never silently proceeding without the real
    exclusivity guarantee `_require_held_lock` exists to enforce."""

    def test_run_next_locked_rejects_unheld_lock(self):
        unheld_lock = queue.QueueLock(self.queue_root)
        with self.assertRaises(queue.QueueLockError):
            queue._run_next_locked(self.queue_root, lock=unheld_lock, executor=_explode_if_called)

    def test_run_next_locked_rejects_lock_for_different_root(self):
        other_root = self.root / "other_queue"
        other_lock = queue.QueueLock(other_root)
        other_lock.acquire(blocking=False)
        try:
            with self.assertRaises(queue.QueueLockError):
                queue._run_next_locked(self.queue_root, lock=other_lock, executor=_explode_if_called)
        finally:
            other_lock.release()

    def test_auto_resume_locked_rejects_unheld_lock(self):
        _repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=1000000000)
        unheld_lock = queue.QueueLock(self.queue_root)
        with self.assertRaises(queue.QueueLockError):
            queue._auto_resume_one_waiting_quota_item_locked(
                self.queue_root, item.item_id, lock=unheld_lock,
                now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_auto_resume_locked_rejects_lock_for_different_root(self):
        _repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=1000000000)
        other_root = self.root / "other_queue"
        other_lock = queue.QueueLock(other_root)
        other_lock.acquire(blocking=False)
        try:
            with self.assertRaises(queue.QueueLockError):
                queue._auto_resume_one_waiting_quota_item_locked(
                    self.queue_root, item.item_id, lock=other_lock,
                    now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
        finally:
            other_lock.release()


# ---------------------------------------------------------------------------
# RUNNER-1.5F-B2B: foreground governed supervisor loop (run_supervisor_loop)
# ---------------------------------------------------------------------------

class _FakeSleeper:
    """Records every delay it is called with; never really sleeps. Raises
    KeyboardInterrupt on the call index given in `interrupt_on_call`
    (0-based), if any."""

    def __init__(self, interrupt_on_call=None):
        self.calls = []
        self.interrupt_on_call = interrupt_on_call

    def __call__(self, seconds):
        index = len(self.calls)
        self.calls.append(seconds)
        if self.interrupt_on_call is not None and index == self.interrupt_on_call:
            raise KeyboardInterrupt()


class _FakeMonotonicClock:
    """Deterministic monotonic clock: advances by `step` seconds every call,
    so `max_runtime_seconds` tests never depend on real wall-clock time."""

    def __init__(self, step=1.0, start=0.0):
        self.value = start
        self.step = step
        self.calls = 0

    def __call__(self):
        self.calls += 1
        current = self.value
        self.value += self.step
        return current


class _FakeSupervisor:
    """Fake `supervisor` injection (mirrors `executor` injection): returns
    the next preset SupervisorResult from `results` on each call, recording
    every call's kwargs. Used only to isolate run_supervisor_loop's own
    STOP/WAIT/CONTINUE policy from real queue/Runner mechanics; production
    never overrides `supervisor`."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, queue_root, **kwargs):
        self.calls.append(kwargs)
        return self.results.pop(0)


def _supervisor_result(outcome, reason="reason", **kwargs):
    return queue.SupervisorResult(outcome=outcome, reason=reason, **kwargs)


class SupervisorLoopNoWorkTest(_TempDirCase):
    def test_no_work_exits_immediately_without_sleep(self):
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            self.queue_root, executor=_explode_if_called, sleeper=sleeper,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.NO_WORK.value)
        self.assertEqual(result.reason, queue.SupervisorReason.NO_QUEUED_WORK.value)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(result.dispatch_count, 0)
        self.assertEqual(sleeper.calls, [])


class SupervisorLoopSequentialDispatchTest(_TempDirCase):
    def test_multiple_queued_items_dispatch_sequentially_one_executor_call_each(self):
        for i in range(3):
            queue.enqueue(
                self.queue_root, work_order_text=f"content {i}\n",
                repository_path="repo", mode="read-only",
            )
        executor = _RecordingExecutor(runner.WorkOrderResult(
            state=runner.RunState.SUCCESS, exit_code=0, run_id="rid",
            evidence_dir=None, error_message=None,
        ))
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            self.queue_root, executor=executor, sleeper=sleeper,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.NO_WORK.value)
        self.assertEqual(result.dispatch_count, 3)
        self.assertEqual(result.cycles, 4)
        self.assertEqual(len(executor.calls), 3)
        self.assertEqual(sleeper.calls, [])

        items = queue.list_items(self.queue_root)
        self.assertTrue(all(it.state == queue.QueueState.SUCCEEDED.value for it in items))


class SupervisorLoopOperatorRequiredTest(_TempDirCase):
    def test_blocked_checkpoint_stops_without_sleep_or_retry(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        blocked_item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        queue.transition_item(self.queue_root, blocked_item.item_id, queue.QueueState.RUNNING)
        queue.run_next(self.queue_root, executor=_explode_if_called)

        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            self.queue_root, executor=_explode_if_called, sleeper=sleeper,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.CHECKPOINT_PENDING_RECONCILIATION.value)
        self.assertEqual(result.last_item_id, blocked_item.item_id)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(sleeper.calls, [])


class SupervisorLoopRecoveryRequiredTest(_TempDirCase):
    def test_orphaned_running_item_stops_without_sleep_or_retry(self):
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path="repo", mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)

        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            self.queue_root, executor=_explode_if_called, sleeper=sleeper,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.RECOVERY_REQUIRED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.ORPHAN_RECOVERY_REQUIRED.value)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(sleeper.calls, [])

        reloaded = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(reloaded.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)


class SupervisorLoopSafetyStopTest(_TempDirCase):
    def test_dirty_repository_during_auto_resume_stops_without_sleep_or_retry(self):
        past_epoch = 1000000000  # 2001-09-09, unambiguously due by 2026
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=past_epoch)
        (repo_dir / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        before = queue.load_item(self.queue_root, item.item_id)

        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            self.queue_root, executor=_explode_if_called, sleeper=sleeper,
            clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.SAFETY_STOP.value)
        self.assertIn("DIRTY_REPOSITORY", result.reason)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(sleeper.calls, [])

        after = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(before.state, after.state)
        self.assertEqual(before.updated_at_utc, after.updated_at_utc)


class SupervisorLoopManualQuotaNeverSleepsTest(_TempDirCase):
    def test_manual_only_quota_barrier_stops_without_sleep(self):
        repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch_str="9" * 30)
        queue.enqueue(
            self.queue_root, work_order_text="other\n", repository_path=str(repo_dir), mode="read-only",
        )
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            self.queue_root, executor=_explode_if_called, sleeper=sleeper,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.reason, queue.SupervisorReason.QUOTA_MANUAL_RESUME_REQUIRED.value)
        self.assertEqual(sleeper.calls, [])


class SupervisorLoopRuntimeBudgetBoundaryTest(_TempDirCase):
    """RUNNER-1.5F-B2B-FIX1: a real, durable WAITING_QUOTA item whose trusted
    quota delay exceeds the configured max_runtime_seconds budget must stop
    with LIMIT_REACHED/MAX_RUNTIME_REACHED without ever calling sleeper and
    without mutating the item's durable state."""

    def test_real_trusted_barrier_exceeding_runtime_budget_stops_without_mutation(self):
        future_epoch = 4102444800  # 2100-01-01T00:00:00Z
        _repo_dir, item = _make_confirmed_quota_item(self.root, self.queue_root, epoch=future_epoch)
        before = queue.load_item(self.queue_root, item.item_id)

        sleeper = _FakeSleeper()
        monotonic_clock = _FakeMonotonicClock(step=1.0)
        result = queue.run_supervisor_loop(
            self.queue_root, executor=_explode_if_called, sleeper=sleeper,
            clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
            max_runtime_seconds=5.0, monotonic_clock=monotonic_clock,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.LIMIT_REACHED.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.MAX_RUNTIME_REACHED.value)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(sleeper.calls, [])

        after = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(before.updated_at_utc, after.updated_at_utc)
        self.assertEqual(before.state, after.state)


class SupervisorLoopFakeSupervisorPolicyTest(unittest.TestCase):
    """Isolates run_supervisor_loop's own STOP/WAIT/CONTINUE decisions from
    real queue/Runner mechanics via an injected fake `supervisor` callable -
    mirrors how `executor` injection isolates `run_next`/`supervisor_once`
    from the real Claude CLI."""

    def test_dispatched_continues_immediately_without_sleep(self):
        fake = _FakeSupervisor([
            _supervisor_result(queue.SupervisorOutcome.DISPATCHED.value, item_id="a"),
            _supervisor_result(queue.SupervisorOutcome.DISPATCHED.value, item_id="b"),
            _supervisor_result(queue.SupervisorOutcome.NO_WORK.value, reason="NO_QUEUED_WORK"),
        ])
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.NO_WORK.value)
        self.assertEqual(result.cycles, 3)
        self.assertEqual(result.dispatch_count, 2)
        self.assertEqual(sleeper.calls, [])

    def test_trusted_future_waiting_quota_sleeps_exact_delay_then_reevaluates(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        next_wake = now + timedelta(seconds=100)
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc=next_wake.isoformat(),
            ),
            _supervisor_result(queue.SupervisorOutcome.NO_WORK.value, reason="NO_QUEUED_WORK"),
        ])
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper, clock=lambda: now,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.NO_WORK.value)
        self.assertEqual(result.cycles, 2)
        self.assertEqual(sleeper.calls, [100.0])

    def test_already_due_next_wake_causes_no_positive_sleep_and_immediate_reevaluation(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        past = now - timedelta(seconds=5)
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc=past.isoformat(),
            ),
            _supervisor_result(queue.SupervisorOutcome.NO_WORK.value, reason="NO_QUEUED_WORK"),
        ])
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper, clock=lambda: now,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.NO_WORK.value)
        self.assertEqual(result.cycles, 2)
        self.assertEqual(sleeper.calls, [])

    def test_missing_next_wake_utc_fails_closed(self):
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc=None,
            ),
        ])
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper,
            clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.SAFETY_STOP.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.UNUSABLE_NEXT_WAKE_UTC.value)
        self.assertEqual(sleeper.calls, [])

    def test_naive_next_wake_utc_fails_closed(self):
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc="2026-01-01T00:00:00",
            ),
        ])
        sleeper = _FakeSleeper()
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper,
            clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.SAFETY_STOP.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.UNUSABLE_NEXT_WAKE_UTC.value)
        self.assertEqual(sleeper.calls, [])

    def test_keyboard_interrupt_from_sleeper_produces_interrupted_result(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        next_wake = now + timedelta(seconds=50)
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc=next_wake.isoformat(),
            ),
        ])
        sleeper = _FakeSleeper(interrupt_on_call=0)
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper, clock=lambda: now,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.INTERRUPTED.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.INTERRUPTED_DURING_QUOTA_SLEEP.value)
        self.assertEqual(result.next_wake_utc, next_wake.isoformat())
        self.assertEqual(sleeper.calls, [50.0])

    def test_no_generic_failure_retry_is_introduced(self):
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.DISPATCHED.value, item_id="a",
                queue_state=queue.QueueState.FAILED.value, runner_state="CLAUDE_ERROR",
            ),
            _supervisor_result(queue.SupervisorOutcome.NO_WORK.value, reason="NO_QUEUED_WORK"),
        ])
        result = queue.run_supervisor_loop(Path("unused"), supervisor=fake, sleeper=_FakeSleeper())
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.NO_WORK.value)
        self.assertEqual(result.dispatch_count, 1)
        self.assertEqual(len(fake.calls), 2, "a FAILED terminal item must never be retried automatically")

    def test_max_cycles_stops_deterministically(self):
        fake = _FakeSupervisor([
            _supervisor_result(queue.SupervisorOutcome.DISPATCHED.value, item_id="a"),
            _supervisor_result(queue.SupervisorOutcome.DISPATCHED.value, item_id="b"),
            _supervisor_result(queue.SupervisorOutcome.DISPATCHED.value, item_id="c"),
        ])
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=_FakeSleeper(), max_cycles=2,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.LIMIT_REACHED.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.MAX_CYCLES_REACHED.value)
        self.assertEqual(result.cycles, 2)
        self.assertEqual(result.dispatch_count, 2)
        self.assertEqual(result.last_item_id, "b")
        self.assertEqual(len(fake.calls), 2)

    def test_max_runtime_seconds_stops_deterministically_with_injectable_monotonic_clock(self):
        fake = _FakeSupervisor([
            _supervisor_result(queue.SupervisorOutcome.DISPATCHED.value, item_id=f"item{i}")
            for i in range(10)
        ])
        monotonic_clock = _FakeMonotonicClock(step=1.0)
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=_FakeSleeper(),
            max_runtime_seconds=3.5, monotonic_clock=monotonic_clock,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.LIMIT_REACHED.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.MAX_RUNTIME_REACHED.value)
        self.assertEqual(result.cycles, 3)
        self.assertEqual(result.dispatch_count, 3)
        self.assertLess(len(fake.calls), 10, "must stop well before exhausting the fake supervisor's results")

    def test_quota_delay_exceeding_remaining_runtime_budget_stops_without_sleep(self):
        # RUNNER-1.5F-B2B-FIX1: remaining budget (max_runtime_seconds=5.0)
        # is recomputed from the monotonic clock right before sleeping and
        # found to be 3.0s, which the 10s quota delay exceeds.
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        next_wake = now + timedelta(seconds=10)
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc=next_wake.isoformat(),
                queue_state=queue.QueueState.WAITING_QUOTA.value,
            ),
            _supervisor_result(queue.SupervisorOutcome.NO_WORK.value, reason="NO_QUEUED_WORK"),
        ])
        sleeper = _FakeSleeper()
        monotonic_clock = _FakeMonotonicClock(step=1.0)
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper, clock=lambda: now,
            max_runtime_seconds=5.0, monotonic_clock=monotonic_clock,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.LIMIT_REACHED.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.MAX_RUNTIME_REACHED.value)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(result.dispatch_count, 0)
        self.assertEqual(result.next_wake_utc, next_wake.isoformat())
        self.assertEqual(result.last_queue_state, queue.QueueState.WAITING_QUOTA.value)
        self.assertEqual(sleeper.calls, [])
        self.assertEqual(len(fake.calls), 1, "no second supervisor_once cycle may occur")

    def test_quota_delay_exactly_equal_to_remaining_runtime_budget_stops_without_sleep(self):
        # remaining budget at the check point is exactly 1.0s; a delay equal
        # to (not just greater than) that remaining budget must also stop.
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        next_wake = now + timedelta(seconds=1.0)
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc=next_wake.isoformat(),
            ),
            _supervisor_result(queue.SupervisorOutcome.NO_WORK.value, reason="NO_QUEUED_WORK"),
        ])
        sleeper = _FakeSleeper()
        monotonic_clock = _FakeMonotonicClock(step=1.0)
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper, clock=lambda: now,
            max_runtime_seconds=3.0, monotonic_clock=monotonic_clock,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.LIMIT_REACHED.value)
        self.assertEqual(result.reason, queue.SupervisorLoopReason.MAX_RUNTIME_REACHED.value)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(sleeper.calls, [])
        self.assertEqual(len(fake.calls), 1, "no second supervisor_once cycle may occur")

    def test_quota_delay_strictly_shorter_than_remaining_budget_sleeps_then_continues(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        next_wake = now + timedelta(seconds=5.0)
        fake = _FakeSupervisor([
            _supervisor_result(
                queue.SupervisorOutcome.WAITING_QUOTA.value,
                reason="QUOTA_BARRIER_NOT_DUE", next_wake_utc=next_wake.isoformat(),
            ),
            _supervisor_result(queue.SupervisorOutcome.NO_WORK.value, reason="NO_QUEUED_WORK"),
        ])
        sleeper = _FakeSleeper()
        monotonic_clock = _FakeMonotonicClock(step=1.0)
        result = queue.run_supervisor_loop(
            Path("unused"), supervisor=fake, sleeper=sleeper, clock=lambda: now,
            max_runtime_seconds=10.0, monotonic_clock=monotonic_clock,
        )
        self.assertEqual(result.outcome, queue.SupervisorLoopOutcome.NO_WORK.value)
        self.assertEqual(result.cycles, 2)
        self.assertEqual(sleeper.calls, [5.0])
        self.assertEqual(len(fake.calls), 2, "a strictly-shorter delay must still start a new cycle")

    def test_invalid_max_cycles_rejected(self):
        with self.assertRaises(queue.QueueError) as ctx:
            queue.run_supervisor_loop(Path("unused"), supervisor=_FakeSupervisor([]), max_cycles=0)
        self.assertEqual(ctx.exception.reason, "INVALID_LOOP_BOUND")

    def test_invalid_max_runtime_seconds_rejected(self):
        with self.assertRaises(queue.QueueError) as ctx:
            queue.run_supervisor_loop(
                Path("unused"), supervisor=_FakeSupervisor([]), max_runtime_seconds=-1,
            )
        self.assertEqual(ctx.exception.reason, "INVALID_LOOP_BOUND")

    def test_naive_clock_return_value_fails_closed(self):
        fake = _FakeSupervisor([_supervisor_result(queue.SupervisorOutcome.NO_WORK.value)])
        with self.assertRaises(queue.QueueError) as ctx:
            queue.run_supervisor_loop(
                Path("unused"), supervisor=fake, clock=lambda: datetime(2026, 1, 1),
            )
        self.assertEqual(ctx.exception.reason, "INVALID_CLOCK")


class SupervisorLoopStaticSafetyTest(unittest.TestCase):
    def test_no_direct_dispatch_bypass_and_no_session_reuse(self):
        source = inspect.getsource(queue.run_supervisor_loop)
        for forbidden in (
            "execute_work_order", "run_next(", "_run_next_locked(",
            "_auto_resume_one_waiting_quota_item", "--resume", "--continue",
        ):
            self.assertNotIn(forbidden, source)

    def test_no_busy_polling(self):
        source = inspect.getsource(queue.run_supervisor_loop)
        for forbidden in ("for _ in itertools.count",):
            self.assertNotIn(forbidden, source)


class SupervisorLoopCliTest(_TempDirCase):
    def test_supervise_cli_no_work_exit_code_zero(self):
        code = queue.main(["--queue-root", str(self.queue_root), "supervise"])
        self.assertEqual(code, 0)

    def test_supervise_cli_operator_required_is_nonzero_and_distinguishable(self):
        repo_dir = self.root / "repo"
        _init_git_repo(repo_dir)
        item = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_dir), mode="read-only",
        )
        queue.transition_item(self.queue_root, item.item_id, queue.QueueState.RUNNING)
        queue.run_next(self.queue_root, executor=_explode_if_called)

        code = queue.main(["--queue-root", str(self.queue_root), "supervise"])
        self.assertNotEqual(code, 0)
        self.assertNotEqual(code, 130)

    def test_supervise_cli_max_cycles_flag_parsed_and_forwarded(self):
        # An empty queue never invokes the (real, production-default) Claude
        # executor at all - NO_WORK terminates the very first cycle before
        # any bound could even matter - so this only proves --max-cycles is
        # parsed/forwarded without ever risking a real Claude CLI call.
        code = queue.main([
            "--queue-root", str(self.queue_root), "supervise", "--max-cycles", "5",
        ])
        self.assertEqual(code, 0)

    def test_supervise_cli_invalid_max_cycles_is_an_error(self):
        code = queue.main([
            "--queue-root", str(self.queue_root), "supervise", "--max-cycles", "0",
        ])
        self.assertNotEqual(code, 0)

    def test_supervise_cli_lock_contention_is_an_error(self):
        holder = queue.QueueLock(self.queue_root)
        holder.acquire(blocking=False)
        try:
            code = queue.main(["--queue-root", str(self.queue_root), "supervise"])
            self.assertNotEqual(code, 0)
        finally:
            holder.release()


if __name__ == "__main__":
    unittest.main()
