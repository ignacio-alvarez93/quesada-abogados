import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
