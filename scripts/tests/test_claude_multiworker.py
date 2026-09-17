import hashlib
import json
import os
import platform
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.ai import claude_multiworker as mw
from scripts.ai import claude_queue as queue
from scripts.ai import claude_runner as runner


def _run_git_cmd(args: list, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed in {cwd}: {result.stderr}")
    return result


def _init_git_repo(path: Path) -> None:
    """Idempotent: a test helper, not production Git behavior. Two queue
    items may legitimately target the SAME already-initialized temporary
    repository (e.g. target-exclusivity tests), and re-running `git init`/
    `git config` on an already-initialized repo is a harmless no-op, but
    `git commit` correctly fails with a nonzero exit code when there is
    nothing new to commit - so the initial commit is only ever made once."""
    already_initialized = (path / ".git").exists()
    path.mkdir(parents=True, exist_ok=True)
    _run_git_cmd(["init", "-q"], cwd=path)
    _run_git_cmd(["config", "user.email", "test@example.com"], cwd=path)
    _run_git_cmd(["config", "user.name", "Test"], cwd=path)
    if already_initialized:
        return
    exclude_path = path / ".git" / "info" / "exclude"
    with exclude_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n/runtime/claude_runner/\n")
    (path / ".gitkeep").write_text("keep\n", encoding="utf-8")
    _run_git_cmd(["add", "."], cwd=path)
    _run_git_cmd(["commit", "-q", "-m", "initial"], cwd=path)


def _poll_until(predicate, timeout=5.0, interval=0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _success_result(run_id=None) -> runner.WorkOrderResult:
    return runner.WorkOrderResult(
        state=runner.RunState.SUCCESS, exit_code=0,
        run_id=run_id or f"run_{uuid.uuid4().hex[:8]}", evidence_dir=None, error_message=None,
    )


def _explode_if_called(request):
    raise AssertionError("executor must not run in this scenario")


class _SuccessExecutor:
    """Fake executor: always SUCCEEDS immediately, recording every call."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, request):
        with self.lock:
            self.calls.append(request)
        return _success_result()


class _ConcurrencyTrackingExecutor:
    """Fake executor that tracks peak concurrent in-flight calls and can
    hold specific repositories open on a shared Event until released,
    deterministically proving overlap without relying on real timing."""

    def __init__(self, hold_repo_paths=None, hold_event=None):
        self._lock = threading.Lock()
        self._current = 0
        self.max_concurrent = 0
        self.calls = []
        self._hold_repo_paths = {str(Path(p).resolve()) for p in (hold_repo_paths or [])}
        self._hold_event = hold_event or threading.Event()

    def __call__(self, request):
        with self._lock:
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
            self.calls.append(request)
        try:
            if str(Path(request.repo).resolve()) in self._hold_repo_paths:
                if not self._hold_event.wait(timeout=10):
                    raise AssertionError("hold_event was never released")
            return _success_result()
        finally:
            with self._lock:
                self._current -= 1

    def current_in_flight(self) -> int:
        with self._lock:
            return self._current


class _WriteMutationExecutor:
    """Fake executor (RUNNER-V2B-FIX0): the second call to reach this
    executor releases the first, so both real target repositories are
    guaranteed to be mutated and awaiting checkpoint capture at
    overlapping instants - deterministically reproducing the real
    incident's dual concurrent WRITE flight shape without real Claude.
    Writes one distinct new untracked file per repository (distinct blob
    identity per item) and durable Runner evidence recording
    repository_mutated=True, so `_map_runner_result_to_queue_state` routes
    every item through checkpoint capture exactly like a real write-mode
    Work Order that actually changed files."""

    def __init__(self):
        self._lock = threading.Lock()
        self._current = 0
        self.max_concurrent = 0
        self.calls = []
        self._release_event = threading.Event()

    def __call__(self, request):
        with self._lock:
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
            self.calls.append(request)
            is_second = self._current >= 2
        if is_second:
            self._release_event.set()
        else:
            if not self._release_event.wait(timeout=10):
                raise AssertionError("second concurrent call never arrived")
        try:
            repo = Path(request.repo)
            marker = repo.name
            (repo / f"{marker}_written.txt").write_text(f"written by {marker}\n", encoding="utf-8")
            run_id = f"run_{uuid.uuid4().hex[:8]}"
            evidence_dir = _write_evidence(repo, run_id, state="SUCCESS", repository_mutated=True)
            return runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
                evidence_dir=evidence_dir, error_message=None,
            )
        finally:
            with self._lock:
                self._current -= 1


def _write_evidence(repo_dir: Path, run_id: str, *, state: str, repository_mutated) -> Path:
    evidence_dir = repo_dir / "runtime" / "claude_runner" / "runs" / run_id
    evidence_dir.mkdir(parents=True)
    payload = {"state": state, "safety_check": {"repository_mutated": repository_mutated}}
    (evidence_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    return evidence_dir


class _ExternalizedWriteMutationExecutor:
    """Fake executor (RUNNER-V2B-FIX2): mirrors `_WriteMutationExecutor`
    above exactly, except it writes Claude Runner evidence under
    `request.run_root` - whatever the coordinator itself told it to use -
    instead of hardcoding a target-local path, so a passing test here
    proves the coordinator's own externalized `run_root` plumbing actually
    determines where evidence lands, not a test-fixture assumption. Asserts
    `request.run_root` is set at all, since RUNNER-V2B-FIX2 requires
    `claude_multiworker.py` to always supply one. The second call to reach
    this executor releases the first, so both real target repositories are
    guaranteed to be mutated and awaiting checkpoint capture at overlapping
    instants, exactly like `_WriteMutationExecutor`."""

    def __init__(self):
        self._lock = threading.Lock()
        self._current = 0
        self.max_concurrent = 0
        self.calls = []
        self._release_event = threading.Event()

    def __call__(self, request):
        with self._lock:
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
            self.calls.append(request)
            is_second = self._current >= 2
        if is_second:
            self._release_event.set()
        else:
            if not self._release_event.wait(timeout=10):
                raise AssertionError("second concurrent call never arrived")
        try:
            assert request.run_root is not None, "coordinator must pass an explicit run_root"
            repo = Path(request.repo)
            marker = repo.name
            (repo / f"{marker}_written.txt").write_text(f"written by {marker}\n", encoding="utf-8")
            run_id = f"run_{uuid.uuid4().hex[:8]}"
            evidence_dir = Path(request.run_root) / run_id
            evidence_dir.mkdir(parents=True)
            payload = {"state": "SUCCESS", "safety_check": {"repository_mutated": True}}
            (evidence_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
            return runner.WorkOrderResult(
                state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
                evidence_dir=evidence_dir, error_message=None,
            )
        finally:
            with self._lock:
                self._current -= 1


class _TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.queue_root = self.root / "queue"

    def tearDown(self):
        self._tmp.cleanup()

    def _enqueue(self, repo_dir: Path, *, mode="read-only", authorize_path=None, label=None):
        _init_git_repo(repo_dir)
        return queue.enqueue(
            self.queue_root, work_order_text="do the thing\n", repository_path=str(repo_dir),
            mode=mode, authorize_path=authorize_path, label=label,
        )


class CanonicalTargetKeyTest(unittest.TestCase):
    def test_rejects_empty_path(self):
        with self.assertRaises(mw.MultiworkerError) as ctx:
            mw.canonical_target_key("")
        self.assertEqual(ctx.exception.reason, "INVALID_TARGET_IDENTITY")

    @unittest.skipUnless(
        platform.system() == "Windows", "case-insensitive path equivalence is Windows-specific"
    )
    def test_equivalent_windows_style_paths_normalize_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            sub = root / "Repo"
            sub.mkdir()
            variant_a = str(sub)
            variant_b = str(sub).upper()
            key_a = mw.canonical_target_key(variant_a)
            key_b = mw.canonical_target_key(variant_b)
            self.assertEqual(key_a, key_b)

    def test_trailing_separator_and_dot_segments_normalize_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            sub = root / "repo"
            sub.mkdir()
            key_a = mw.canonical_target_key(str(sub))
            key_b = mw.canonical_target_key(str(sub / "." ))
            self.assertEqual(key_a, key_b)


class MaxWorkersValidationTest(_TempDirCase):
    def test_max_workers_three_is_rejected_before_touching_queue(self):
        with self.assertRaises(mw.MultiworkerError) as ctx:
            mw.supervise_multiworker(self.queue_root, max_workers=3, executor=_explode_if_called)
        self.assertEqual(ctx.exception.reason, "MAX_WORKERS_EXCEEDS_LIMIT")
        self.assertFalse(self.queue_root.exists())

    def test_max_workers_zero_is_rejected(self):
        with self.assertRaises(mw.MultiworkerError) as ctx:
            mw.supervise_multiworker(self.queue_root, max_workers=0, executor=_explode_if_called)
        self.assertEqual(ctx.exception.reason, "INVALID_MAX_WORKERS")

    def test_default_max_workers_is_two(self):
        self.assertEqual(mw.DEFAULT_MAX_WORKERS, 2)
        self.assertEqual(mw.MAX_ALLOWED_WORKERS, 2)


class ConcurrencyOverlapTest(_TempDirCase):
    def test_two_distinct_targets_overlap_and_third_waits_for_a_slot(self):
        repo_a = self.root / "repo_a"
        repo_b = self.root / "repo_b"
        repo_c = self.root / "repo_c"
        item_a = self._enqueue(repo_a, label="a")
        item_b = self._enqueue(repo_b, label="b")
        item_c = self._enqueue(repo_c, label="c")

        hold_event = threading.Event()
        executor = _ConcurrencyTrackingExecutor(hold_repo_paths=[repo_a, repo_b], hold_event=hold_event)

        result_box = {}

        def _run():
            result_box["result"] = mw.supervise_multiworker(
                self.queue_root, max_workers=2, executor=executor,
                heartbeat_interval_seconds=None,
            )

        thread = threading.Thread(target=_run)
        thread.start()
        try:
            self.assertTrue(
                _poll_until(lambda: executor.current_in_flight() == 2, timeout=5.0),
                "both repo_a and repo_b calls never reached the tracked executor concurrently",
            )
            # repo_c must not have been claimed yet: both slots are busy.
            c_state = queue.load_item(self.queue_root, item_c.item_id).state
            self.assertEqual(c_state, queue.QueueState.QUEUED.value)
        finally:
            hold_event.set()
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())
        result = result_box["result"]
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.PROGRESSED.value)
        self.assertLessEqual(result.max_observed_concurrency, 2)
        self.assertEqual(executor.max_concurrent, 2)
        self.assertEqual(len(result.dispatched), 3)

        # Every item reached SUCCEEDED, no item was left RUNNING, and every
        # dispatch carries a unique worker_id/attempt_id (durable evidence).
        worker_ids = set()
        attempt_ids = set()
        for item_id in (item_a.item_id, item_b.item_id, item_c.item_id):
            item = queue.load_item(self.queue_root, item_id)
            self.assertEqual(item.state, queue.QueueState.SUCCEEDED.value)
            self.assertNotEqual(item.state, queue.QueueState.RUNNING.value)
        for record in result.dispatched:
            worker_ids.add(record.worker_id)
            attempt_ids.add(record.attempt_id)
        self.assertEqual(len(attempt_ids), 3)
        self.assertLessEqual(len(worker_ids), 2)

        for item_id in (item_a.item_id, item_b.item_id, item_c.item_id):
            claim = mw._load_claim(self.queue_root, item_id)
            self.assertIsNotNone(claim)
            self.assertEqual(claim["status"], "FINALIZED")
            self.assertEqual(claim["final_queue_state"], queue.QueueState.SUCCEEDED.value)

    def test_max_observed_concurrency_never_exceeds_two_with_five_items(self):
        items = [self._enqueue(self.root / f"repo_{i}", label=str(i)) for i in range(5)]
        executor = _ConcurrencyTrackingExecutor()
        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=executor, heartbeat_interval_seconds=None,
        )
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.PROGRESSED.value)
        self.assertLessEqual(executor.max_concurrent, 2)
        self.assertLessEqual(result.max_observed_concurrency, 2)
        self.assertEqual(len(result.dispatched), 5)
        for item in items:
            self.assertEqual(
                queue.load_item(self.queue_root, item.item_id).state,
                queue.QueueState.SUCCEEDED.value,
            )


class DualWriteCheckpointSmokeTest(_TempDirCase):
    """RUNNER-V2B-FIX1: end-to-end synthetic reproduction of the real
    incident - two independent queue items, two independent real target
    repositories, both write-mode, both mutated and finalized to
    BLOCKED_ON_CHECKPOINT under real overlapping executor concurrency. The
    shared queue_root is nested inside item_a's own target repository (the
    DEFAULT `resolve_queue_root` convention) with the production-assumption
    git-exclude rule removed, mirroring a target repository that was never
    configured to hide runtime/claude_runner from git - the exact
    configuration the real incident was captured under. Never invokes real
    Claude.

    Once both items independently capture valid checkpoints and reach
    BLOCKED_ON_CHECKPOINT, the established operator-barrier contract
    (BarrierTest, `claude_multiworker._dispatch_cycle_locked`) means the
    coordinator's own next dispatch cycle refuses all further claims, so
    the correct final outcome for this run is OPERATOR_REQUIRED, not
    PROGRESSED - this smoke proves the dual-write capture property itself
    (both concurrent, both captured, both distinct, no cross-item
    overwrite), not a bare top-level outcome."""

    def test_two_concurrent_write_mode_items_both_capture_valid_checkpoints(self):
        repo_a = self.root / "repo_a"
        repo_b = self.root / "repo_b"
        _init_git_repo(repo_a)
        exclude_path = repo_a / ".git" / "info" / "exclude"
        exclude_path.write_text("", encoding="utf-8")
        self.queue_root = queue.resolve_queue_root(repo_a, None)

        item_a = queue.enqueue(
            self.queue_root, work_order_text="do the thing\n", repository_path=str(repo_a),
            mode="write", authorize_path=["."],
        )
        item_b = self._enqueue(repo_b, mode="write", authorize_path=["."])

        executor = _WriteMutationExecutor()
        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=executor, heartbeat_interval_seconds=None,
        )

        # Both independent WRITE-mode items were claimed concurrently
        # (proven below via executor.max_concurrent and each item's own
        # captured checkpoint), each mutated its own real target repo, and
        # each finalization independently captured a checkpoint. Per the
        # established operator-barrier contract (BarrierTest: "any
        # BLOCKED_ON_CHECKPOINT item anywhere is a global operator
        # barrier"), once both items are BLOCKED_ON_CHECKPOINT the
        # coordinator's next dispatch cycle correctly refuses to claim
        # anything else, so the run's final outcome is OPERATOR_REQUIRED -
        # not PROGRESSED - with nothing left in flight and no queued work
        # eligible for a new claim.
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(
            result.reason, mw.MultiworkerReason.CHECKPOINT_PENDING_RECONCILIATION.value,
        )
        self.assertIn(result.blocking_item_id, {item_a.item_id, item_b.item_id})
        self.assertEqual(len(result.dispatched), 2)
        self.assertEqual(executor.max_concurrent, 2)

        blob_digests = []
        checkpoint_ids = []
        checkpoint_dirs = []
        for item_id, repo_dir in ((item_a.item_id, repo_a), (item_b.item_id, repo_b)):
            item = queue.load_item(self.queue_root, item_id)
            self.assertEqual(item.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
            self.assertEqual(len(item.checkpoints), 1)
            checkpoint = item.checkpoints[0]
            self.assertEqual(
                checkpoint["status"], "CAPTURED",
                f"checkpoint for {item_id} unexpectedly FAILED: {checkpoint.get('error')}",
            )
            checkpoint_ids.append(checkpoint["checkpoint_id"])
            checkpoint_dir = (
                self.queue_root / item_id / queue.CHECKPOINTS_SUBDIR_NAME / checkpoint["checkpoint_id"]
            )
            checkpoint_dirs.append(checkpoint_dir)
            manifest = json.loads(
                (checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            written_paths = {e["path"] for e in manifest["entries"]}
            self.assertEqual(written_paths, {f"{repo_dir.name}_written.txt"})
            for entry in manifest["entries"]:
                blob_filename = entry.get("blob_filename")
                if not blob_filename:
                    continue
                blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / blob_filename
                self.assertTrue(blob_path.exists(), f"referenced blob missing/unreadable: {blob_path}")
                self.assertEqual(len(blob_path.read_bytes()), entry["size"])
                blob_digests.append(entry["sha256"])

            # Post-finalization integrity re-verification (the same
            # validator `reconcile_checkpoint`/explicit capture-checkpoint
            # retry uses) must independently confirm CAPTURED from disk.
            revalidated = queue._load_and_validate_checkpoint(
                checkpoint_dir, item_id, checkpoint["attempt_id"], str(repo_dir),
            )
            self.assertEqual(revalidated.status, "CAPTURED")

        self.assertEqual(len(blob_digests), len(set(blob_digests)))
        # Distinct checkpoint identities/artifacts per item, and neither
        # item's checkpoint directory was clobbered/removed by the other's
        # finalization (both still exist, independently, after both workers
        # have finalized).
        self.assertEqual(len(checkpoint_ids), len(set(checkpoint_ids)))
        for checkpoint_dir in checkpoint_dirs:
            self.assertTrue(checkpoint_dir.is_dir())


class ExternalizedEvidenceCheckpointSmokeTest(_TempDirCase):
    """RUNNER-V2B-FIX2: end-to-end proof that V2 multiworker's Claude
    evidence is externalized - never part of any target repository's own
    working tree - for exactly the topology the real incident was captured
    under: `queue_root` external to both target repositories (the
    `_TempDirCase` default: `self.queue_root` is a sibling of both, never
    nested inside either), both items write-mode, both mutated and
    finalized to BLOCKED_ON_CHECKPOINT under real overlapping executor
    concurrency. Never invokes real Claude."""

    def _repo_without_git_exclude(self, name):
        repo_dir = self.root / name
        _init_git_repo(repo_dir)
        # _init_git_repo() already adds "/runtime/claude_runner/" to
        # .git/info/exclude; undo it here so an assertion that no
        # Runner-owned evidence path is ever reported by git actually
        # proves evidence was never WRITTEN there, not merely hidden.
        (repo_dir / ".git" / "info" / "exclude").write_text("", encoding="utf-8")
        return repo_dir

    def test_two_concurrent_write_mode_items_leave_target_worktrees_clean_of_runner_evidence(self):
        repo_a = self._repo_without_git_exclude("repo_a")
        repo_b = self._repo_without_git_exclude("repo_b")
        item_a = queue.enqueue(
            self.queue_root, work_order_text="do the thing\n", repository_path=str(repo_a),
            mode="write", authorize_path=["."],
        )
        item_b = queue.enqueue(
            self.queue_root, work_order_text="do the thing\n", repository_path=str(repo_b),
            mode="write", authorize_path=["."],
        )

        executor = _ExternalizedWriteMutationExecutor()
        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=executor, heartbeat_interval_seconds=None,
        )

        self.assertEqual(result.outcome, mw.MultiworkerOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(
            result.reason, mw.MultiworkerReason.CHECKPOINT_PENDING_RECONCILIATION.value,
        )
        self.assertEqual(len(result.dispatched), 2)
        self.assertEqual(executor.max_concurrent, 2)

        # Every claimed job's WorkOrderRequest carried an explicit,
        # coordinator-owned run_root - external to its own target repository
        # - never the Runner's own target-local default.
        self.assertEqual(len(executor.calls), 2)
        for request in executor.calls:
            self.assertIsNotNone(request.run_root)
            repo_resolved = Path(request.repo).resolve()
            run_root_resolved = Path(request.run_root).resolve()
            with self.assertRaises(ValueError):
                run_root_resolved.relative_to(repo_resolved)

        blob_digests = []
        checkpoint_ids = []
        for item_id, repo_dir in ((item_a.item_id, repo_a), (item_b.item_id, repo_b)):
            item = queue.load_item(self.queue_root, item_id)
            self.assertEqual(item.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
            self.assertEqual(len(item.checkpoints), 1)
            checkpoint = item.checkpoints[0]
            self.assertEqual(
                checkpoint["status"], "CAPTURED",
                f"checkpoint for {item_id} unexpectedly FAILED: {checkpoint.get('error')}",
            )
            checkpoint_ids.append(checkpoint["checkpoint_id"])
            checkpoint_dir = (
                self.queue_root / item_id / queue.CHECKPOINTS_SUBDIR_NAME / checkpoint["checkpoint_id"]
            )
            manifest = json.loads(
                (checkpoint_dir / queue.CHECKPOINT_MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            written_paths = {e["path"] for e in manifest["entries"]}
            self.assertEqual(written_paths, {f"{repo_dir.name}_written.txt"})
            # Nothing Runner-owned was ever excluded, because nothing
            # Runner-owned was ever reported by git in the first place - the
            # target repository's own working tree never contained any.
            self.assertEqual(manifest["excluded_governance_paths"], [])
            for entry in manifest["entries"]:
                blob_filename = entry.get("blob_filename")
                if not blob_filename:
                    continue
                blob_path = checkpoint_dir / queue.CHECKPOINT_BLOBS_DIRNAME / blob_filename
                self.assertTrue(blob_path.exists(), f"referenced blob missing/unreadable: {blob_path}")
                blob_bytes = blob_path.read_bytes()
                self.assertEqual(len(blob_bytes), entry["size"])
                self.assertEqual(hashlib.sha256(blob_bytes).hexdigest(), entry["sha256"])
                blob_digests.append(entry["sha256"])

            # Post-finalization integrity re-verification, independent of
            # the other target's own finalization having already happened.
            revalidated = queue._load_and_validate_checkpoint(
                checkpoint_dir, item_id, checkpoint["attempt_id"], str(repo_dir),
            )
            self.assertEqual(revalidated.status, "CAPTURED")

            # The target repository's own git status carries only the
            # genuine authorized source mutation - no Runner evidence path
            # anywhere, proving evidence never touched this working tree.
            status = _run_git_cmd(
                ["status", "--porcelain=v1", "--untracked-files=all"], cwd=repo_dir,
            )
            status_paths = {line[3:].strip() for line in status.stdout.splitlines() if line.strip()}
            self.assertEqual(status_paths, {f"{repo_dir.name}_written.txt"})

        self.assertEqual(len(blob_digests), len(set(blob_digests)))
        self.assertEqual(len(checkpoint_ids), len(set(checkpoint_ids)))


class TargetExclusivityTest(_TempDirCase):
    def test_two_items_same_target_never_overlap(self):
        repo = self.root / "shared_repo"
        item1 = self._enqueue(repo, label="one")
        item2 = self._enqueue(repo, label="two")

        executor = _ConcurrencyTrackingExecutor()
        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=executor, heartbeat_interval_seconds=None,
        )
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.PROGRESSED.value)
        # Same-target items must never be claimed within the same cycle:
        # peak observed concurrency across the whole run is still bounded
        # by 2 overall, but the two SAME-target calls could never overlap
        # each other specifically.
        self.assertEqual(
            queue.load_item(self.queue_root, item1.item_id).state, queue.QueueState.SUCCEEDED.value,
        )
        self.assertEqual(
            queue.load_item(self.queue_root, item2.item_id).state, queue.QueueState.SUCCEEDED.value,
        )
        self.assertGreaterEqual(result.cycles, 2)

    @unittest.skipUnless(
        platform.system() == "Windows", "case-insensitive path equivalence is Windows-specific"
    )
    def test_windows_style_equivalent_paths_cannot_bypass_exclusivity(self):
        repo = self.root / "shared_repo2"
        _init_git_repo(repo)
        resolved = str(repo.resolve())
        alt_spelling = resolved.upper()
        item1 = queue.enqueue(
            self.queue_root, work_order_text="wo1\n", repository_path=resolved, mode="read-only",
        )
        item2 = queue.enqueue(
            self.queue_root, work_order_text="wo2\n", repository_path=alt_spelling, mode="read-only",
        )

        hold_event = threading.Event()
        executor = _ConcurrencyTrackingExecutor(hold_repo_paths=[resolved], hold_event=hold_event)
        result_box = {}

        def _run():
            result_box["result"] = mw.supervise_multiworker(
                self.queue_root, max_workers=2, executor=executor, heartbeat_interval_seconds=None,
            )

        thread = threading.Thread(target=_run)
        thread.start()
        try:
            self.assertTrue(_poll_until(lambda: executor.current_in_flight() >= 1, timeout=5.0))
            time.sleep(0.2)
            # The second (equivalent-path) item must still be QUEUED while
            # the first is in flight, even though its spelling differs.
            self.assertEqual(executor.current_in_flight(), 1)
            self.assertEqual(
                queue.load_item(self.queue_root, item2.item_id).state, queue.QueueState.QUEUED.value,
            )
        finally:
            hold_event.set()
            thread.join(timeout=10)
        result = result_box["result"]
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.PROGRESSED.value)
        self.assertEqual(
            queue.load_item(self.queue_root, item1.item_id).state, queue.QueueState.SUCCEEDED.value,
        )
        self.assertEqual(
            queue.load_item(self.queue_root, item2.item_id).state, queue.QueueState.SUCCEEDED.value,
        )


class ClaimRaceTest(_TempDirCase):
    def test_two_racing_threads_cannot_claim_the_same_item(self):
        repo = self.root / "race_repo"
        item = self._enqueue(repo)

        results = []
        results_lock = threading.Lock()
        start_barrier = threading.Barrier(2)

        def _attempt_claim():
            start_barrier.wait(timeout=5)
            lock = queue.QueueLock(self.queue_root)
            lock.acquire(blocking=True)
            try:
                outcome = mw._dispatch_cycle_locked(
                    self.queue_root, lock=lock, free_slot_indices=[0],
                    in_flight_item_ids=set(), coordinator_run_id=f"run-{uuid.uuid4().hex}",
                    hostname="host", lease_seconds=60.0,
                    now=mw._resolve_now(None), pid_alive=lambda pid: True,
                )
            finally:
                lock.release()
            with results_lock:
                results.append(outcome)

        threads = [threading.Thread(target=_attempt_claim) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        claimed_counts = [len(r.claimed) for r in results]
        self.assertEqual(sorted(claimed_counts), [0, 1])
        final_item = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(final_item.state, queue.QueueState.RUNNING.value)
        self.assertEqual(len(final_item.attempts), 1)


class ClaimDurabilityTest(_TempDirCase):
    def test_durable_claim_exists_before_executor_starts_and_survives_reload(self):
        repo = self.root / "durable_repo"
        item = self._enqueue(repo)

        entered = threading.Event()
        release = threading.Event()
        seen_claim = {}

        def _blocking_executor(request):
            entered.set()
            claim = mw._load_claim(self.queue_root, item.item_id)
            seen_claim["claim"] = claim
            release.wait(timeout=10)
            return _success_result()

        result_box = {}

        def _run():
            result_box["result"] = mw.supervise_multiworker(
                self.queue_root, max_workers=1, executor=_blocking_executor,
                heartbeat_interval_seconds=None,
            )

        thread = threading.Thread(target=_run)
        thread.start()
        try:
            self.assertTrue(entered.wait(timeout=5))
        finally:
            release.set()
            thread.join(timeout=10)

        claim = seen_claim["claim"]
        self.assertIsNotNone(claim, "claim file must exist before the executor is ever invoked")
        self.assertEqual(claim["item_id"], item.item_id)
        self.assertEqual(claim["status"], "ACTIVE")
        self.assertIn("worker_id", claim)
        self.assertIn("attempt_id", claim)

        # Reload from disk fresh (simulating a later inspection/restart) and
        # confirm the finalized claim persisted correctly.
        reloaded = mw._load_claim(self.queue_root, item.item_id)
        self.assertEqual(reloaded["status"], "FINALIZED")
        self.assertEqual(reloaded["final_queue_state"], queue.QueueState.SUCCEEDED.value)


class BarrierTest(_TempDirCase):
    def test_blocked_on_checkpoint_prevents_new_claims_while_independent_work_finalizes(self):
        repo_x = self.root / "repo_x"
        repo_y = self.root / "repo_y"
        repo_z = self.root / "repo_z"
        item_x = self._enqueue(repo_x, mode="write", authorize_path=["."], label="x")
        item_y = self._enqueue(repo_y, label="y")
        item_z = self._enqueue(repo_z, label="z")

        y_release = threading.Event()
        y_entered = threading.Event()

        def _executor(request):
            if str(Path(request.repo).resolve()) == str(repo_x.resolve()):
                run_id = f"run_{uuid.uuid4().hex[:8]}"
                evidence_dir = _write_evidence(repo_x, run_id, state="SUCCESS", repository_mutated=True)
                return runner.WorkOrderResult(
                    state=runner.RunState.SUCCESS, exit_code=0, run_id=run_id,
                    evidence_dir=evidence_dir, error_message=None,
                )
            if str(Path(request.repo).resolve()) == str(repo_y.resolve()):
                y_entered.set()
                y_release.wait(timeout=10)
                return _success_result()
            raise AssertionError(f"unexpected repo dispatched: {request.repo}")

        result_box = {}

        def _run():
            result_box["result"] = mw.supervise_multiworker(
                self.queue_root, max_workers=2, executor=_executor, heartbeat_interval_seconds=None,
            )

        thread = threading.Thread(target=_run)
        thread.start()
        try:
            self.assertTrue(y_entered.wait(timeout=5))
            self.assertTrue(
                _poll_until(
                    lambda: queue.load_item(self.queue_root, item_x.item_id).state
                    == queue.QueueState.BLOCKED_ON_CHECKPOINT.value,
                    timeout=5.0,
                )
            )
            # z must never be claimed while x is BLOCKED_ON_CHECKPOINT, even
            # though y (an independent, already-running job) has not
            # finished yet.
            self.assertEqual(
                queue.load_item(self.queue_root, item_z.item_id).state, queue.QueueState.QUEUED.value,
            )
        finally:
            y_release.set()
            thread.join(timeout=10)

        result = result_box["result"]
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.blocking_item_id, item_x.item_id)
        self.assertEqual(
            queue.load_item(self.queue_root, item_y.item_id).state, queue.QueueState.SUCCEEDED.value,
        )
        self.assertEqual(
            queue.load_item(self.queue_root, item_z.item_id).state, queue.QueueState.QUEUED.value,
        )
        x_item = queue.load_item(self.queue_root, item_x.item_id)
        self.assertTrue(x_item.checkpoints)

    def test_waiting_quota_blocks_all_new_claims_globally(self):
        repo_q = self.root / "repo_q"
        _init_git_repo(repo_q)
        item_q = queue.enqueue(
            self.queue_root, work_order_text="content\n", repository_path=str(repo_q), mode="read-only",
        )
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        cli_output = {
            "parsed": True,
            "cli_result": {"is_error": True, "result": "Claude AI usage limit reached|4102444800"},
        }
        evidence_dir = repo_q / "runtime" / "claude_runner" / "runs" / run_id
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "result.json").write_text(json.dumps({
            "state": "CLAUDE_ERROR",
            "safety_check": {"repository_mutated": False},
            "cli_output": cli_output,
        }), encoding="utf-8")
        quota_executor = lambda request: runner.WorkOrderResult(  # noqa: E731
            state=runner.RunState.CLAUDE_ERROR, exit_code=3, run_id=run_id,
            evidence_dir=evidence_dir, error_message=None,
        )
        pre_result = queue.run_next(self.queue_root, executor=quota_executor)
        self.assertEqual(pre_result.queue_state, queue.QueueState.WAITING_QUOTA.value)

        item_r = self._enqueue(self.root / "repo_r", label="r")

        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=_explode_if_called, heartbeat_interval_seconds=None,
        )
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.QUOTA_WAIT.value)
        self.assertEqual(
            queue.load_item(self.queue_root, item_r.item_id).state, queue.QueueState.QUEUED.value,
        )
        self.assertEqual(
            queue.load_item(self.queue_root, item_q.item_id).state, queue.QueueState.WAITING_QUOTA.value,
        )

    def test_failed_safety_is_never_automatically_retried(self):
        repo_f = self.root / "repo_f"
        item_f = self._enqueue(repo_f)

        def _executor(request):
            return runner.WorkOrderResult(
                state=runner.RunState.FAILED_SAFETY, exit_code=20, run_id="run_fs",
                evidence_dir=None, error_message=None,
            )

        first = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=_executor, heartbeat_interval_seconds=None,
        )
        self.assertEqual(first.outcome, mw.MultiworkerOutcome.PROGRESSED.value)
        self.assertEqual(
            queue.load_item(self.queue_root, item_f.item_id).state, queue.QueueState.FAILED_SAFETY.value,
        )

        second = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=_explode_if_called, heartbeat_interval_seconds=None,
        )
        self.assertEqual(second.outcome, mw.MultiworkerOutcome.NO_WORK.value)
        self.assertEqual(
            queue.load_item(self.queue_root, item_f.item_id).state, queue.QueueState.FAILED_SAFETY.value,
        )


class OrphanRecoveryTest(_TempDirCase):
    def _make_running_item_with_foreign_claim(self, repo: Path, *, claim_overrides: dict):
        item = self._enqueue(repo)
        attempt_id = queue.generate_attempt_id()
        attempt = queue.QueueAttempt(
            attempt_id=attempt_id, started_at_utc=queue._now_iso(), ended_at_utc=None,
            status="RUNNING", runner_state=None, runner_exit_code=None,
            runner_run_id=None, runner_evidence_dir=None, final_queue_state=None,
        )
        queue.start_attempt(self.queue_root, item.item_id, attempt)
        claim = {
            "schema_version": mw.CLAIM_SCHEMA_VERSION,
            "item_id": item.item_id,
            "attempt_id": attempt_id,
            "worker_id": "old-run:w0",
            "coordinator_run_id": "OLD_RUN",
            "target_key": mw.canonical_target_key(str(repo)),
            "repository_path": str(repo),
            "pid": 999999,
            "hostname": "some-host",
            "claimed_at_utc": queue._now_iso(),
            "heartbeat_at_utc": queue._now_iso(),
            "lease_seconds": 60.0,
            "status": "ACTIVE",
            "finalized_at_utc": None,
            "final_queue_state": None,
        }
        claim.update(claim_overrides)
        mw._write_claim(self.queue_root, item.item_id, claim)
        return item

    def test_live_or_unverifiable_foreign_claim_blocks_without_duplicate_dispatch(self):
        repo = self.root / "orphan_repo_alive"

        item = self._make_running_item_with_foreign_claim(
            repo, claim_overrides={"hostname": socket.gethostname(), "pid": os.getpid()},
        )
        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=_explode_if_called,
            coordinator_run_id="NEW_RUN", heartbeat_interval_seconds=None,
        )
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.blocking_item_id, item.item_id)
        self.assertEqual(
            queue.load_item(self.queue_root, item.item_id).state, queue.QueueState.RUNNING.value,
        )

    def test_demonstrably_dead_foreign_claim_is_safely_orphan_recovered(self):
        repo = self.root / "orphan_repo_dead"

        old_heartbeat = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        item = self._make_running_item_with_foreign_claim(
            repo,
            claim_overrides={
                "hostname": socket.gethostname(), "pid": 4444444, "lease_seconds": 1.0,
                "heartbeat_at_utc": old_heartbeat,
            },
        )
        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=_explode_if_called,
            coordinator_run_id="NEW_RUN", heartbeat_interval_seconds=None,
            pid_alive_fn=lambda pid: False,
        )
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(result.blocking_item_id, item.item_id)
        recovered = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(recovered.state, queue.QueueState.BLOCKED_ON_CHECKPOINT.value)
        self.assertTrue(recovered.checkpoints)
        claim = mw._load_claim(self.queue_root, item.item_id)
        self.assertEqual(claim["status"], "ORPHAN_RECOVERED")

    def test_not_yet_stale_dead_pid_is_still_treated_as_unverifiable(self):
        repo = self.root / "orphan_repo_fresh"

        item = self._make_running_item_with_foreign_claim(
            repo,
            claim_overrides={
                "hostname": socket.gethostname(), "pid": 4444445, "lease_seconds": 3600.0,
                "heartbeat_at_utc": queue._now_iso(),
            },
        )
        result = mw.supervise_multiworker(
            self.queue_root, max_workers=2, executor=_explode_if_called,
            coordinator_run_id="NEW_RUN", heartbeat_interval_seconds=None,
            pid_alive_fn=lambda pid: False,
        )
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(
            queue.load_item(self.queue_root, item.item_id).state, queue.QueueState.RUNNING.value,
        )


class RuntimeBudgetTest(_TempDirCase):
    def test_budget_exhaustion_never_abandons_an_in_flight_claim(self):
        repo_a = self.root / "budget_repo_a"
        item_a = self._enqueue(repo_a)

        entered = threading.Event()
        release = threading.Event()

        def _executor(request):
            entered.set()
            release.wait(timeout=10)
            return _success_result()

        clock_calls = {"n": 0}

        def fake_monotonic():
            clock_calls["n"] += 1
            # Calls 1-2 cover start_monotonic and the first (still-within-
            # budget) check, so item_a's claim phase runs once; every call
            # afterward reports the budget as exhausted, so no *new*
            # dispatch happens, without ever abandoning the already-claimed
            # item mid-flight.
            return 0.0 if clock_calls["n"] <= 2 else 1000.0

        result_box = {}

        def _run():
            result_box["result"] = mw.supervise_multiworker(
                self.queue_root, max_workers=2, executor=_executor,
                max_runtime_seconds=1.0, monotonic_clock=fake_monotonic,
                heartbeat_interval_seconds=None,
            )

        thread = threading.Thread(target=_run)
        thread.start()
        try:
            self.assertTrue(entered.wait(timeout=5))
        finally:
            release.set()
            thread.join(timeout=10)

        result = result_box["result"]
        self.assertEqual(result.outcome, mw.MultiworkerOutcome.RUNTIME_BUDGET_EXHAUSTED.value)
        item = queue.load_item(self.queue_root, item_a.item_id)
        self.assertNotEqual(item.state, queue.QueueState.RUNNING.value)
        self.assertEqual(item.state, queue.QueueState.SUCCEEDED.value)
        self.assertEqual(len(result.dispatched), 1)


class ClaimMetadataNamespaceTest(_TempDirCase):
    """RUNNER-V2A-MULTIWORKER-CORE-FIX1 regression: claim metadata must live
    outside the queue item directory namespace entirely, so it can never be
    mistaken for a queue item and can never change `queue.list_items()`."""

    def test_claim_metadata_root_is_a_sibling_not_a_child_of_queue_root(self):
        meta_root = mw._multiworker_meta_root(self.queue_root)
        self.assertEqual(meta_root.parent, self.queue_root.parent)
        self.assertNotEqual(meta_root, self.queue_root)
        with self.assertRaises(ValueError):
            meta_root.relative_to(self.queue_root)

    def test_claim_creation_never_changes_list_items_and_is_invisible(self):
        repo = self.root / "meta_repo"
        item = self._enqueue(repo)
        before_ids = [it.item_id for it in queue.list_items(self.queue_root)]

        request = queue._build_work_order_request(self.queue_root, item)
        job = mw._ClaimedJob(
            slot_index=0, item_id=item.item_id, attempt_id="attempt_x",
            worker_id="run:w0", target_key=mw.canonical_target_key(str(repo)),
            request=request,
        )
        claim_payload = mw._build_claim_payload(job, "run", "host", 123, 60.0)
        mw._write_claim(self.queue_root, item.item_id, claim_payload)

        # The claim file must exist under the sibling metadata root...
        meta_root = mw._multiworker_meta_root(self.queue_root)
        self.assertTrue((meta_root / "claims" / f"{item.item_id}.json").exists())

        # ...and must never appear as a published child of queue_root, so it
        # can never be mistaken for (or loaded as) a queue item.
        if self.queue_root.exists():
            for entry in self.queue_root.iterdir():
                self.assertNotEqual(entry.name, "multiworker")

        after_items = queue.list_items(self.queue_root)
        self.assertEqual([it.item_id for it in after_items], before_ids)
        self.assertEqual(len(after_items), 1)

    def test_two_queue_roots_sharing_a_parent_do_not_collide(self):
        parent = self.root / "shared_parent"
        queue_root_a = parent / "queue_a"
        queue_root_b = parent / "queue_b"
        repo_a = self.root / "collision_repo_a"
        repo_b = self.root / "collision_repo_b"
        _init_git_repo(repo_a)
        _init_git_repo(repo_b)
        item_a = queue.enqueue(
            queue_root_a, work_order_text="a\n", repository_path=str(repo_a), mode="read-only",
        )
        item_b = queue.enqueue(
            queue_root_b, work_order_text="b\n", repository_path=str(repo_b), mode="read-only",
        )

        job_a = mw._ClaimedJob(
            slot_index=0, item_id=item_a.item_id, attempt_id="attempt_a", worker_id="w0",
            target_key=mw.canonical_target_key(str(repo_a)),
            request=queue._build_work_order_request(queue_root_a, item_a),
        )
        job_b = mw._ClaimedJob(
            slot_index=0, item_id=item_b.item_id, attempt_id="attempt_b", worker_id="w0",
            target_key=mw.canonical_target_key(str(repo_b)),
            request=queue._build_work_order_request(queue_root_b, item_b),
        )
        mw._write_claim(queue_root_a, item_a.item_id, mw._build_claim_payload(job_a, "run_a", "host", 1, 60.0))
        mw._write_claim(queue_root_b, item_b.item_id, mw._build_claim_payload(job_b, "run_b", "host", 2, 60.0))

        self.assertNotEqual(
            mw._multiworker_meta_root(queue_root_a), mw._multiworker_meta_root(queue_root_b),
        )
        claim_a = mw._load_claim(queue_root_a, item_a.item_id)
        claim_b = mw._load_claim(queue_root_b, item_b.item_id)
        self.assertEqual(claim_a["item_id"], item_a.item_id)
        self.assertEqual(claim_b["item_id"], item_b.item_id)

        # Each queue root's own list_items() sees exactly its own item,
        # unaffected by the sibling queue root's claim metadata.
        self.assertEqual([it.item_id for it in queue.list_items(queue_root_a)], [item_a.item_id])
        self.assertEqual([it.item_id for it in queue.list_items(queue_root_b)], [item_b.item_id])


class EvidenceRootNamespaceTest(_TempDirCase):
    """RUNNER-V2B-FIX2: the externalized Claude-evidence sidecar root must
    be a deterministic sibling of `queue_root` (never a descendant, never
    the same location as the `.multiworker` claims sidecar), collision-free
    between two distinct queue roots sharing a parent, and must be exactly
    what `_dispatch_cycle_locked()` threads into each claimed job's
    `WorkOrderRequest.run_root`."""

    def test_evidence_root_is_a_sibling_not_a_child_of_queue_root(self):
        evidence_root = mw._multiworker_evidence_root(self.queue_root)
        self.assertEqual(evidence_root.parent, self.queue_root.parent)
        self.assertNotEqual(evidence_root, self.queue_root)
        with self.assertRaises(ValueError):
            evidence_root.relative_to(self.queue_root)

    def test_evidence_root_is_distinct_from_claims_meta_root(self):
        self.assertNotEqual(
            mw._multiworker_evidence_root(self.queue_root),
            mw._multiworker_meta_root(self.queue_root),
        )

    def test_evidence_run_root_is_nested_under_evidence_root_by_item_id(self):
        run_root = mw._evidence_run_root(self.queue_root, "some-item-id")
        self.assertEqual(
            Path(run_root), mw._multiworker_evidence_root(self.queue_root) / "some-item-id",
        )

    def test_two_queue_roots_sharing_a_parent_get_distinct_evidence_roots(self):
        parent = self.root / "shared_parent"
        queue_root_a = parent / "queue_a"
        queue_root_b = parent / "queue_b"
        self.assertNotEqual(
            mw._multiworker_evidence_root(queue_root_a), mw._multiworker_evidence_root(queue_root_b),
        )

    def test_dispatch_cycle_threads_evidence_run_root_into_claimed_request(self):
        repo = self.root / "dispatch_repo"
        item = self._enqueue(repo, mode="write", authorize_path=["."])
        lock = queue.QueueLock(self.queue_root)
        lock.acquire(blocking=False)
        try:
            claim_result = mw._dispatch_cycle_locked(
                self.queue_root, lock=lock, free_slot_indices=[0], in_flight_item_ids=set(),
                coordinator_run_id="run", hostname="host", lease_seconds=60.0,
                now=datetime.now(timezone.utc), pid_alive=lambda pid: True,
            )
        finally:
            lock.release()
        self.assertEqual(len(claim_result.claimed), 1)
        job = claim_result.claimed[0]
        self.assertEqual(job.request.run_root, mw._evidence_run_root(self.queue_root, item.item_id))
        repo_resolved = Path(job.request.repo).resolve()
        run_root_resolved = Path(job.request.run_root).resolve()
        with self.assertRaises(ValueError):
            run_root_resolved.relative_to(repo_resolved)


class ClaimPublicationFailureTest(_TempDirCase):
    """RUNNER-V2A-MULTIWORKER-CORE-FIX1 regression: a claim-file write that
    fails AFTER the durable QUEUED->RUNNING transition must never be
    silently absorbed - the item stays RUNNING (no silent revert to
    QUEUED), no claim is fabricated, and a later cycle must never dispatch
    a duplicate attempt against that same item."""

    def test_claim_write_failure_after_running_transition_is_fail_closed(self):
        repo = self.root / "claim_fail_repo"
        item = self._enqueue(repo)

        lock = queue.QueueLock(self.queue_root)
        lock.acquire(blocking=True)
        try:
            with patch.object(mw, "_write_claim", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    mw._dispatch_cycle_locked(
                        self.queue_root, lock=lock, free_slot_indices=[0],
                        in_flight_item_ids=set(), coordinator_run_id="run-1",
                        hostname="host", lease_seconds=60.0,
                        now=mw._resolve_now(None), pid_alive=lambda pid: True,
                    )
        finally:
            lock.release()

        after_failure = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(after_failure.state, queue.QueueState.RUNNING.value)
        self.assertEqual(len(after_failure.attempts), 1)
        self.assertIsNone(mw._load_claim(self.queue_root, item.item_id))

        # A fresh coordinator (e.g. after a restart) must treat this
        # claimless RUNNING item as an unverifiable foreign claim - never
        # re-claim/re-dispatch it, and never fabricate a claim to "fix" it.
        lock2 = queue.QueueLock(self.queue_root)
        lock2.acquire(blocking=True)
        try:
            result = mw._dispatch_cycle_locked(
                self.queue_root, lock=lock2, free_slot_indices=[0],
                in_flight_item_ids=set(), coordinator_run_id="run-2",
                hostname="host", lease_seconds=60.0,
                now=mw._resolve_now(None), pid_alive=lambda pid: True,
            )
        finally:
            lock2.release()

        self.assertEqual(result.claimed, [])
        self.assertIsNotNone(result.barrier)
        self.assertEqual(result.barrier.outcome, mw.MultiworkerOutcome.OPERATOR_REQUIRED.value)
        self.assertEqual(
            result.barrier.reason, mw.MultiworkerReason.LIVE_OR_UNVERIFIABLE_FOREIGN_CLAIM.value,
        )
        still_one_attempt = queue.load_item(self.queue_root, item.item_id)
        self.assertEqual(still_one_attempt.state, queue.QueueState.RUNNING.value)
        self.assertEqual(len(still_one_attempt.attempts), 1)
        self.assertIsNone(mw._load_claim(self.queue_root, item.item_id))


class CliSmokeTest(_TempDirCase):
    def test_max_workers_three_rejected_at_cli(self):
        repo = self.root / "cli_repo"
        repo.mkdir(parents=True)
        exit_code = mw.main([
            "--queue-root", str(self.queue_root), "--repo", str(repo),
            "supervise", "--max-workers", "3",
        ])
        self.assertEqual(exit_code, 1)

    def test_status_on_empty_queue(self):
        repo = self.root / "cli_repo2"
        repo.mkdir(parents=True)
        exit_code = mw.main([
            "--queue-root", str(self.queue_root), "--repo", str(repo), "status",
        ])
        self.assertEqual(exit_code, 0)

    def test_supervise_no_work_via_cli_with_real_default_executor_path_untouched(self):
        repo = self.root / "cli_repo3"
        repo.mkdir(parents=True)
        exit_code = mw.main([
            "--queue-root", str(self.queue_root), "--repo", str(repo),
            "supervise", "--max-workers", "2",
        ])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
