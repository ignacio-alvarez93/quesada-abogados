import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts.ai import claude_queue as queue

REPO_ROOT = Path(__file__).resolve().parents[2]


class _TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.queue_root = self.root / "queue"

    def tearDown(self):
        self._tmp.cleanup()


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
            (item_dir / queue.WORK_ORDER_FILENAME).write_text(wo_text, encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
