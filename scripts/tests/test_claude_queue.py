import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts.ai import claude_queue as queue
from scripts.ai import claude_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    def test_module_never_imports_subprocess(self):
        self.assertFalse(hasattr(queue, "subprocess"))

    def test_run_next_never_touches_subprocess_module(self):
        import subprocess as real_subprocess

        original_popen = real_subprocess.Popen
        original_run = real_subprocess.run

        def _boom(*args, **kwargs):
            raise AssertionError("claude_queue.run_next must never shell out")

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


if __name__ == "__main__":
    unittest.main()
