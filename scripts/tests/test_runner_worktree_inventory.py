"""FCP-4C-01: read-only worktree inventory and ownership check.

Every repository is a throwaway under a temporary directory, built with
PLAIN git (subprocess) - only the module under test is restricted to the
governed `runner_integration`/`runner_git` read path. Security tests pair
each "nothing fired / nothing changed" assertion with a positive control.
"""

import ast
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_git
from scripts.ai import runner_integration as ri
from scripts.ai import runner_pipeline as pipeline
from scripts.ai import runner_worktree_inventory as wi
from scripts.tests.test_runner_git import install_filter, install_hostile_config, modify_same_size, plain_git
from scripts.tests.test_runner_integration import _ISOLATED_ENV, _git_dir_state, _rmtree, commit, write

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE = "feature/fcp4c01"

# Holds the canonical Runner write lease from ANOTHER process until stdin
# closes or the process is killed.
_LEASE_HOLDER = textwrap.dedent("""
    import os, sys
    from pathlib import Path
    from scripts.ai import runner_pipeline as pipeline
    lease = pipeline.DirLease(Path(sys.argv[1]))
    ok = lease.try_acquire({"pipeline_id": "other", "worker_id": "w9", "pid": os.getpid(),
                            "hostname": "elsewhere", "last_heartbeat_utc": sys.argv[2]})
    print("ready" if ok else "busy", flush=True)
    sys.stdin.readline()
""")


class Fixture:
    """`repo` (main worktree, on develop) plus a linked worktree `wt` on
    FEATURE, and empty Runner state/ledger roots."""

    def __init__(self, root: Path):
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        plain_git(self.repo, "init", "-q", "-b", "develop")
        plain_git(self.repo, "config", "user.email", "fcp4c01@example.invalid")
        plain_git(self.repo, "config", "user.name", "FCP4C01 Tests")
        self.c0 = commit(self.repo, "c0", {"src/a.py": "a = 0\n", "shared.txt": "shared\n"})
        self.wt = self.add("wt", FEATURE)
        self.state_root = root / "state"
        self.state_root.mkdir()
        self.ledger_root = root / "factory"
        self.ledger_root.mkdir()

    def add(self, name: str, branch=None, *extra) -> Path:
        path = self.root / name
        args = ["worktree", "add", "-q", *extra]
        if branch is not None:
            args += ["-b", branch]
        plain_git(self.repo, *args, str(path), *([] if branch else [self.c0]))
        return path

    def write_worker(self, pipeline_id: str, worker_id: str, worktree: Path, state: str, **runtime) -> Path:
        spec = pipeline.WorkerSpec(id=worker_id, worktree=str(worktree), work_order="wo", mode="write",
                                   worktree_top=str(worktree))
        data = pipeline.WorkerRuntime(spec=spec, order=0, state=state, **runtime).to_dict()
        path = self.state_root / pipeline_id / "workers" / worker_id / "worker.json"
        write(path, json.dumps(data))
        return path


class InventoryTestCase(unittest.TestCase):
    def setUp(self):
        env_patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.root = Path(tempfile.mkdtemp(prefix="fcp4c01-")).resolve()
        self.addCleanup(_rmtree, self.root)
        self.fx = Fixture(self.root)

    def inventory(self, repository=None, **kwargs):
        kwargs.setdefault("state_root", self.fx.state_root)
        kwargs.setdefault("ledger_root", self.fx.ledger_root)
        return wi.inventory_worktrees(repository or self.fx.repo, **kwargs)

    def record(self, inventory, path: Path):
        key = os.path.normcase(str(path.resolve()))
        matches = [r for r in inventory.records if r.worktree_key == key]
        self.assertEqual(len(matches), 1, [r.worktree_key for r in inventory.records])
        return matches[0]

    def assertClass(self, record, classification, *reasons):
        self.assertEqual(record.classification, classification, record.reason_codes)
        for reason in reasons:
            self.assertIn(reason, record.reason_codes)
        self.assertIs(record.authorizes_action, False)
        self.assertIs(record.human_review_required, True)

    def hold_lease(self, lease_dir: Path, stamp: str = "2026-01-01T00:00:00+00:00") -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-c", _LEASE_HOLDER, str(lease_dir), stamp], cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        def stop():
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)
            proc.stdin.close()
            proc.stdout.close()

        self.addCleanup(stop)
        self.assertEqual(proc.stdout.readline().strip(), "ready")
        return proc


# ---------------------------------------------------------------------------
# Registry topology
# ---------------------------------------------------------------------------

class TopologyTests(InventoryTestCase):
    def test_main_linked_detached_locked_prunable_duplicate_and_protected(self):
        detached = self.fx.add("det", None, "--detach")
        locked = self.fx.add("locked", "feature/locked")
        plain_git(self.fx.repo, "worktree", "lock", "--reason", "host hold", str(locked))
        gone = self.fx.add("gone", "feature/gone")
        _rmtree(gone)
        dup = self.fx.add("dup", None, "--force")
        plain_git(dup, "checkout", "-q", "--ignore-other-worktrees", FEATURE)
        protected = self.fx.add("prot", "main")

        inv = self.inventory()
        self.assertEqual(inv.status, wi.INVENTORY_COMPLETE)
        self.assertTrue(inv.complete)
        self.assertEqual(len(inv.records), 7)

        main = inv.records[0]
        self.assertTrue(main.is_main)
        self.assertClass(main, wi.PROTECTED, "MAIN_WORKTREE", "PROTECTED_BRANCH")
        self.assertClass(self.record(inv, detached), wi.DETACHED, "DETACHED_HEAD")
        self.assertTrue(self.record(inv, detached).listed_detached)
        lr = self.record(inv, locked)
        self.assertClass(lr, wi.GIT_LOCKED, "WORKTREE_LOCKED")
        self.assertEqual(lr.locked_reason, "host hold")
        gr = self.record(inv, gone)
        self.assertClass(gr, wi.MISSING_PATH, "PRUNABLE")
        self.assertIs(gr.path_exists, False)
        self.assertIsNone(gr.clean)
        for path in (self.fx.wt, dup):
            r = self.record(inv, path)
            self.assertClass(r, wi.OWNERSHIP_INCONSISTENT, "DUPLICATE_BRANCH_CHECKOUT")
            self.assertEqual(len(r.duplicate_checkouts), 1)
        self.assertClass(self.record(inv, protected), wi.PROTECTED, "PROTECTED_BRANCH")
        self.assertFalse(self.record(inv, protected).is_main)
        self.assertEqual(sum(n for _, n in inv.counts), 7)
        # Nothing was pruned/unlocked: git still lists every entry.
        listing = plain_git(self.fx.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn("prunable", listing)
        self.assertIn("locked host hold", listing)

    def test_clean_unbound_linked_worktree_is_only_a_review_candidate(self):
        inv = self.inventory()
        r = self.record(inv, self.fx.wt)
        self.assertClass(r, wi.IDLE_CLEAN_UNBOUND)
        self.assertEqual(r.reason_codes, ())
        self.assertEqual(r.head_ref, f"refs/heads/{FEATURE}")
        self.assertEqual(r.head_sha, self.fx.c0)
        self.assertEqual(r.lease_state, wi.LEASE_NOT_CREATED)
        self.assertTrue(r.git_dir.replace("\\", "/").endswith("/worktrees/wt"))
        self.assertIs(inv.authorizes_action, False)
        names = set(wi.CLASSIFICATION_PRECEDENCE)
        self.assertFalse({n for n in names if "ELIGIBLE" in n or "DELET" in n or "PRUN" in n})
        self.assertNotIn("eligible", {f.name for f in dataclasses.fields(wi.WorktreeRecord)})

    def test_registry_unreadable_fails_closed_without_records(self):
        not_repo = self.root / "plain"
        not_repo.mkdir()
        inv = self.inventory(not_repo)
        self.assertEqual(inv.status, wi.INVENTORY_FAILED_CLOSED)
        self.assertFalse(inv.complete)
        self.assertEqual(inv.records, ())
        self.assertTrue(inv.global_errors[0].startswith("REGISTRY_UNREADABLE"))

    def test_individual_unreadable_worktree_does_not_hide_others(self):
        other = self.root / "other"
        other.mkdir()
        plain_git(other, "init", "-q")
        broken = self.fx.add("broken", "feature/broken")
        (broken / ".git").unlink()  # git may create it hidden on Windows, which refuses "w"
        (broken / ".git").write_text(f"gitdir: {(other / '.git').as_posix()}\n", encoding="utf-8")
        inv = self.inventory()
        self.assertEqual(inv.status, wi.INVENTORY_COMPLETE)
        r = self.record(inv, broken)
        self.assertClass(r, wi.UNSAFE, "GIT_READ_FAILED")
        self.assertTrue(r.read_errors)
        self.assertClass(self.record(inv, self.fx.wt), wi.IDLE_CLEAN_UNBOUND)
        self.assertEqual(len(inv.records), 3)

    def test_inventory_from_any_worktree_is_identical(self):
        self.assertEqual(self.inventory(self.fx.wt).fingerprint, self.inventory(self.fx.repo).fingerprint)


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------

class LeaseTests(InventoryTestCase):
    def lease_dir(self, lease_root=None) -> Path:
        return pipeline.worktree_lease_dir(self.fx.wt.resolve(), lease_root)

    def test_lease_held_by_another_process_is_active(self):
        proc = self.hold_lease(self.lease_dir())
        r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.ACTIVE_LEASED, "WORKTREE_LEASE_HELD")
        self.assertEqual(r.lease_state, wi.LEASE_HELD)
        self.assertIn(("pipeline_id", "other"), r.lease_holder)
        # Never stolen or rewritten: the holder's identity is untouched.
        self.assertEqual(pipeline.DirLease(self.lease_dir()).holder()["pipeline_id"], "other")
        proc.stdin.write("\n")
        proc.stdin.flush()
        proc.wait(timeout=30)
        self.assertClass(self.record(self.inventory(), self.fx.wt), wi.IDLE_CLEAN_UNBOUND)

    def test_held_lease_under_lease_root(self):
        lease_root = self.root / "leases"
        self.hold_lease(self.lease_dir(lease_root))
        r = self.record(self.inventory(lease_root=lease_root), self.fx.wt)
        self.assertClass(r, wi.ACTIVE_LEASED, "WORKTREE_LEASE_HELD")
        self.assertEqual(Path(r.lease_dir).parent, lease_root)
        # The default (git-dir) namespace is a different lease and is free.
        self.assertClass(self.record(self.inventory(), self.fx.wt), wi.IDLE_CLEAN_UNBOUND)

    def test_residue_of_killed_holder_is_not_active_and_is_preserved(self):
        lease_dir = self.lease_dir()
        proc = self.hold_lease(lease_dir)
        proc.kill()
        proc.wait(timeout=30)
        identity = lease_dir / pipeline.DirLease.IDENTITY
        before = identity.read_bytes()
        r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.IDLE_CLEAN_UNBOUND)
        self.assertEqual(r.lease_state, wi.LEASE_FREE)
        self.assertIn("LEASE_IDENTITY_RESIDUE", r.advisories)
        self.assertEqual(identity.read_bytes(), before)

    def test_identity_file_alone_never_makes_a_lease_active(self):
        lease_dir = self.lease_dir()
        write(lease_dir / pipeline.DirLease.IDENTITY, json.dumps({"pipeline_id": "ghost", "pid": 1}))
        r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.IDLE_CLEAN_UNBOUND)
        self.assertEqual(r.lease_state, wi.LEASE_NOT_CREATED)
        self.assertIn("LEASE_IDENTITY_RESIDUE", r.advisories)
        self.assertFalse((lease_dir / "queue.lock").exists())

    def test_probe_failure_fails_closed(self):
        lease = pipeline.DirLease(self.lease_dir())
        self.assertTrue(lease.try_acquire({"pid": 0}))
        lease.release()  # leaves the lock file, so the probe really reaches the OS lock
        with mock.patch.object(wi.queue.QueueLock, "acquire", side_effect=PermissionError("denied")):
            r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.UNSAFE, "LEASE_PROBE_FAILED")

    def test_fingerprint_ignores_lease_identity_timestamps(self):
        lease_dir = self.lease_dir()
        fingerprints = []
        for stamp in ("2026-01-01T00:00:00+00:00", "2026-02-02T00:00:00+00:00"):
            write(lease_dir / pipeline.DirLease.IDENTITY, json.dumps({"pid": 1, "last_heartbeat_utc": stamp}))
            fingerprints.append(self.inventory().fingerprint)
        self.assertEqual(fingerprints[0], fingerprints[1])


# ---------------------------------------------------------------------------
# Pipeline state and factory ledger
# ---------------------------------------------------------------------------

class RunnerStateTests(InventoryTestCase):
    def test_worker_states(self):
        stopped = [{"attempt": 1, "executed": True, "process_confirmed_stopped": True}]
        cases = (
            ("RUNNING", {}, wi.ACTIVE_PIPELINE, "PIPELINE_WORKER_RUNNING"),
            ("QUEUED", {}, wi.ACTIVE_PIPELINE, "PIPELINE_WORKER_PENDING"),
            ("WAITING_PROVIDER_QUOTA", {"attempts": stopped}, wi.ACTIVE_PIPELINE, "PIPELINE_WORKER_PENDING"),
            ("INTERRUPTED", {"attempts": stopped}, wi.RECOVERY_PENDING, "WORKER_INTERRUPTED"),
            ("BLOCKED_PROVIDER_AUTH", {"attempts": stopped}, wi.RECOVERY_PENDING, "WORKER_BLOCKED_PROVIDER_AUTH"),
            ("BLOCKED", {"attempts": stopped, "state_reason": "CHECKPOINT_FAILED"}, wi.RECOVERY_PENDING,
             "CHECKPOINT_FAILED"),
            ("RETRY_WAIT", {"attempts": stopped, "pending_resume_from": "x/work_product.json"},
             wi.RECOVERY_PENDING, "PENDING_RESUME_FROM"),
            # A terminal state is not safe while its process is unresolved.
            ("FAILED", {"attempts": [{"attempt": 1, "executed": True, "process_confirmed_stopped": False}]},
             wi.RECOVERY_PENDING, "PROCESS_TERMINATION_UNRESOLVED"),
            ("SUCCESS", {"attempts": [{"attempt": 1, "executed": True, "process_confirmed_stopped": True,
                                       "process_recovery": {"resolution": "UNRESOLVED"}}]},
             wi.RECOVERY_PENDING, "PROCESS_TERMINATION_UNRESOLVED"),
            ("SUCCESS", {"attempts": [{"attempt": 1, "executed": True,
                                       "acceptance_termination_unresolved": True,
                                       "process_confirmed_stopped": True}]},
             wi.RECOVERY_PENDING, "PROCESS_TERMINATION_UNRESOLVED"),
        )
        for state, runtime, classification, reason in cases:
            with self.subTest(state=state, reason=reason):
                path = self.fx.write_worker("p1", "w1", self.fx.wt, state, **runtime)
                r = self.record(self.inventory(), self.fx.wt)
                self.assertClass(r, classification, reason)
                self.assertEqual([(b.pipeline_id, b.worker_id, b.state) for b in r.pipeline_workers],
                                 [("p1", "w1", state)])
                path.unlink()

    def test_cleanly_finished_worker_is_history_only(self):
        self.fx.write_worker("p1", "w1", self.fx.wt, "SUCCESS",
                             attempts=[{"attempt": 1, "executed": True, "process_confirmed_stopped": True}])
        r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.IDLE_CLEAN_UNBOUND)
        self.assertIn("TERMINAL_PIPELINE_HISTORY", r.advisories)

    def test_worker_on_unregistered_path_is_reported(self):
        ghost = self.root / "ghost"
        self.fx.write_worker("p1", "w1", ghost, "QUEUED")
        self.fx.write_worker("p1", "w2", self.root / "old", "SUCCESS",
                             attempts=[{"attempt": 1, "executed": True, "process_confirmed_stopped": True}])
        inv = self.inventory()
        r = self.record(inv, ghost)
        self.assertFalse(r.registered)
        self.assertClass(r, wi.ACTIVE_PIPELINE, "UNREGISTERED_WORKTREE_REFERENCED")
        # Clean terminal history on an unregistered path is not a record.
        self.assertEqual(len(inv.records), 3)
        self.assertEqual(inv.records[-1].worktree_key, r.worktree_key)

    def test_ledger_start_without_finish(self):
        ledger = flog.FactoryLedger(self.fx.ledger_root)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.OWNERSHIP_INCONSISTENT, "LEDGER_OPEN_WORKER")
        self.assertEqual(r.ledger_open_workers, (("p1", "w1"),))
        ledger.append(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        self.assertClass(self.record(self.inventory(), self.fx.wt), wi.IDLE_CLEAN_UNBOUND)
        # Bound by branch as well; an unrelated worktree never blocks.
        ledger.append(flog.WORKER_STARTED, pipeline_id="p2", worker_id="w2", branch=FEATURE)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p3", worker_id="w3", worktree=str(self.root / "else"))
        inv = self.inventory()
        self.assertClass(self.record(inv, self.fx.wt), wi.OWNERSHIP_INCONSISTENT, "LEDGER_OPEN_WORKER")
        self.assertClass(self.record(inv, self.root / "else"), wi.OWNERSHIP_INCONSISTENT,
                         "UNREGISTERED_WORKTREE_REFERENCED", "LEDGER_OPEN_WORKER")

    def assertFailedClosed(self, inv, code):
        self.assertEqual(inv.status, wi.INVENTORY_FAILED_CLOSED)
        self.assertFalse(inv.complete)
        self.assertTrue(any(e.startswith(code) for e in inv.global_errors), inv.global_errors)
        self.assertEqual(len(inv.records), 2)  # nothing concealed
        for r in inv.records:
            self.assertIn("GLOBAL_STATE_UNREADABLE", r.reason_codes)
            self.assertNotEqual(r.classification, wi.IDLE_CLEAN_UNBOUND)
        self.assertClass(self.record(inv, self.fx.wt), wi.UNSAFE)

    def test_corrupt_or_missing_ledger_fails_closed(self):
        write(self.fx.ledger_root / flog.EVENTS_FILENAME, '{"event_type": "WORKER_STARTED"\n')
        self.assertFailedClosed(self.inventory(), "LEDGER_CORRUPT")
        (self.fx.ledger_root / flog.EVENTS_FILENAME).write_bytes(b"\xff\xfe not utf-8\n")
        # Positive control: the ledger reader itself silently degrades this.
        self.assertEqual(flog.read_events(self.fx.ledger_root), ([], 0))
        self.assertFailedClosed(self.inventory(), "LEDGER_UNREADABLE")
        self.assertFailedClosed(self.inventory(ledger_root=self.root / "absent"), "LEDGER_UNREADABLE")

    def test_corrupt_worker_or_pipeline_state_fails_closed(self):
        path = self.fx.write_worker("p1", "w1", self.fx.wt, "SUCCESS")
        path.write_text("{broken", encoding="utf-8")
        self.assertFailedClosed(self.inventory(), "WORKER_STATE_CORRUPT")
        path.write_text(json.dumps({"spec": {}, "state": "SUCCESS"}), encoding="utf-8")
        self.assertFailedClosed(self.inventory(), "WORKER_STATE_CORRUPT")
        path.write_text(json.dumps({"spec": {"worktree": str(self.fx.wt)}, "state": "NOT_A_STATE"}),
                        encoding="utf-8")
        self.assertFailedClosed(self.inventory(), "WORKER_STATE_CORRUPT")
        path.unlink()
        write(self.fx.state_root / "p1" / "pipeline.json", "[1, 2")
        self.assertFailedClosed(self.inventory(), "PIPELINE_STATE_CORRUPT")
        self.assertFailedClosed(self.inventory(state_root=self.root / "absent"), "PIPELINE_STATE_UNREADABLE")

    def test_evidence_root_is_not_a_pipeline(self):
        write(self.fx.state_root / pipeline.EVIDENCE_ROOT_DIRNAME / "abc" / "run" / "result.json", "{}")
        self.assertEqual(self.inventory().status, wi.INVENTORY_COMPLETE)

    def test_runner_state_change_during_inventory_is_drift(self):
        real = wi._read_runner_state
        calls = []

        def changing(state_root, ledger_root):
            if calls:
                self.fx.write_worker("p9", "w9", self.fx.wt, "QUEUED")
            calls.append(1)
            return real(state_root, ledger_root)

        with mock.patch.object(wi, "_read_runner_state", changing):
            r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.UNSAFE, "RUNNER_STATE_DRIFT", "PIPELINE_WORKER_PENDING")

    def test_head_change_during_inspection_is_drift(self):
        real = ri._status

        def committing(repo):
            out = real(repo)
            if Path(repo).resolve() == self.fx.wt.resolve():
                plain_git(self.fx.wt, "commit", "-q", "--allow-empty", "-m", "racing")
            return out

        with mock.patch.object(wi.ri, "_status", committing):
            r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.UNSAFE, "HEAD_DRIFT")


# ---------------------------------------------------------------------------
# Content state and branch-relation independence
# ---------------------------------------------------------------------------

class ContentTests(InventoryTestCase):
    def test_dirty_kinds_are_distinguished(self):
        wt = self.fx.wt
        cases = {
            "STAGED_CHANGES": lambda: (write(wt / "src/a.py", "a = 1\n"), plain_git(wt, "add", "src/a.py")),
            "UNSTAGED_CHANGES": lambda: write(wt / "shared.txt", "changed\n"),
            "UNTRACKED_FILES": lambda: write(wt / "new.txt", "new\n"),
        }
        for reason, make_dirty in cases.items():
            with self.subTest(reason=reason):
                make_dirty()
                r = self.record(self.inventory(), wt)
                self.assertClass(r, wi.DIRTY, reason)
                self.assertIs(r.clean, False)
                plain_git(wt, "reset", "-q", "--hard")
                plain_git(wt, "clean", "-q", "-fd")
        self.assertClass(self.record(self.inventory(), wt), wi.IDLE_CLEAN_UNBOUND)

    def test_conflicts_are_unmerged(self):
        wt = self.fx.wt
        plain_git(wt, "branch", "side")
        commit(wt, "ours", {"shared.txt": "ours\n"})
        plain_git(wt, "checkout", "-q", "side")
        commit(wt, "theirs", {"shared.txt": "theirs\n"})
        plain_git(wt, "checkout", "-q", FEATURE)
        self.assertNotEqual(plain_git(wt, "merge", "-q", "side", check=False).returncode, 0)
        r = self.record(self.inventory(), wt)
        self.assertClass(r, wi.DIRTY, "UNMERGED_PATHS")
        self.assertEqual(r.unmerged_paths, ("shared.txt",))

    def test_dirty_is_never_hidden_or_upgraded(self):
        write(self.fx.wt / "new.txt", "new\n")
        self.hold_lease(pipeline.worktree_lease_dir(self.fx.wt.resolve()))
        r = self.record(self.inventory(), self.fx.wt)
        self.assertClass(r, wi.ACTIVE_LEASED, "WORKTREE_LEASE_HELD", "UNTRACKED_FILES")
        # Unknown cleanliness is never idle, whatever else holds.
        clean = self.record(self.inventory(), self.fx.repo)
        probe = dataclasses.replace(clean, is_main=False, protected_branch=False, clean=None)
        self.assertClass(wi.classify_record(probe), wi.UNSAFE, "UNPROVEN_CLEAN")
        idle = dataclasses.replace(probe, clean=True)
        self.assertClass(wi.classify_record(idle), wi.IDLE_CLEAN_UNBOUND)
        for field, value, code in (
            ("runner_state_readable", False, "GLOBAL_STATE_UNREADABLE"),
            ("lease_state", wi.LEASE_UNRESOLVED, "LEASE_UNRESOLVED"),
            ("registered", False, "UNREGISTERED_WORKTREE_REFERENCED"),
            ("protected_branch", None, "UNPROVEN_UNPROTECTED_BRANCH"),
        ):
            with self.subTest(field=field):
                result = wi.classify_record(dataclasses.replace(idle, **{field: value}))
                self.assertNotEqual(result.classification, wi.IDLE_CLEAN_UNBOUND)
                self.assertIn(code, result.reason_codes)

    def test_fixed_precedence_lists_every_reason(self):
        base = self.record(self.inventory(), self.fx.wt)
        everything = dataclasses.replace(
            base, read_errors=("boom",), locked=True, staged_paths=("x",), detached=True,
            duplicate_checkouts=("/elsewhere",), lease_state=wi.LEASE_HELD,
            pipeline_workers=(wi.WorkerBinding("p", "w", "INTERRUPTED", None, "write", ("WORKER_INTERRUPTED",)),),
        )
        r = wi.classify_record(everything)
        self.assertEqual(r.classification, wi.UNSAFE)
        order = ["GIT_READ_FAILED", "WORKER_INTERRUPTED", "WORKTREE_LEASE_HELD",
                 "DUPLICATE_BRANCH_CHECKOUT", "WORKTREE_LOCKED", "STAGED_CHANGES", "DETACHED_HEAD"]
        self.assertEqual([c for c in r.reason_codes if c in order], order)
        self.assertEqual(wi.classify_record(dataclasses.replace(everything, read_errors=())).classification,
                         wi.RECOVERY_PENDING)

    def test_merged_and_new_ahead_zero_branches_are_judged_alike(self):
        merged = self.fx.add("merged", "feature/merged")
        commit(merged, "work", {"src/b.py": "b = 1\n"})
        fresh = self.fx.add("fresh", "feature/fresh")  # ahead 0, never worked on
        before = self.record(self.inventory(), merged)
        plain_git(self.fx.repo, "merge", "-q", "--ff-only", "feature/merged")
        inv = self.inventory()
        after, new = self.record(inv, merged), self.record(inv, fresh)
        # Being merged (or ahead 0) changes nothing: neither is proof of safety.
        self.assertEqual(after.fingerprint, before.fingerprint)
        for r in (after, new):
            self.assertClass(r, wi.IDLE_CLEAN_UNBOUND)
        fields = {f.name for f in dataclasses.fields(wi.WorktreeRecord)}
        self.assertFalse(fields & {"ahead", "behind", "merged", "merge_bases"})


# ---------------------------------------------------------------------------
# Security, read-only behavior and determinism
# ---------------------------------------------------------------------------

class SecurityTests(InventoryTestCase):
    def test_no_hooks_or_fsmonitor_run(self):
        markers = install_hostile_config(self.fx.repo, self.root)
        for marker in markers.iterdir():
            marker.unlink()
        inv = self.inventory()
        self.assertEqual(inv.status, wi.INVENTORY_COMPLETE)
        self.assertEqual(sorted(m.name for m in markers.iterdir()), [])
        plain_git(self.fx.repo, "status", "--porcelain=v1")
        self.assertIn("fsmonitor", {m.name for m in markers.iterdir()})

    def test_content_filter_is_refused_not_run(self):
        markers = install_filter(self.fx.wt, self.root)
        modify_same_size(self.fx.wt / "tracked.dat")
        inv = self.inventory()
        r = self.record(inv, self.fx.wt)
        self.assertClass(r, wi.UNSAFE, "GIT_READ_FAILED")
        self.assertIn(runner_git.REFUSED_PREFIX.strip(), " ".join(r.read_errors))
        self.assertEqual(list(markers.iterdir()), [])
        self.assertClass(inv.records[0], wi.PROTECTED)  # other records unaffected
        plain_git(self.fx.wt, "status", "--porcelain=v1")
        self.assertTrue((markers / "filter-evil-clean").exists())

    def test_redirecting_environment_never_yields_idle(self):
        other = self.root / "other"
        other.mkdir()
        plain_git(other, "init", "-q")
        before = _git_dir_state([other / ".git"])
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git"), "GIT_INDEX_FILE": str(self.root / "ix")}):
            # Positive control: plain git really is redirected.
            self.assertEqual(Path(plain_git(self.fx.wt, "rev-parse", "--absolute-git-dir").stdout.strip()),
                             other / ".git")
            inv = self.inventory()
        self.assertEqual(len(inv.records), 2)
        self.assertEqual(inv.records[0].head_sha, self.fx.c0)
        r = self.record(inv, self.fx.wt)
        self.assertEqual(r.head_ref, f"refs/heads/{FEATURE}")
        self.assertClass(r, wi.UNSAFE, "LEASE_UNRESOLVED")
        self.assertEqual(_git_dir_state([other / ".git"]), before)
        self.assertFalse((self.root / "ix").exists())

    def test_only_governed_read_only_git_subcommands(self):
        calls = []
        real_run = runner_git.subprocess.run

        def recording(cmd, *args, **kwargs):
            calls.append((list(cmd), dict(kwargs.get("env") or {})))
            return real_run(cmd, *args, **kwargs)

        self.fx.add("det", None, "--detach")
        with mock.patch.object(runner_git.subprocess, "run", recording):
            self.inventory()
        allowed = ri._READ_SUBCOMMANDS | {"ls-files", "check-attr"}
        self.assertGreater(len(calls), 10)
        for cmd, env in calls:
            rest = cmd[3:]
            sub = rest[runner_git._subcommand_index(rest):]
            with self.subTest(cmd=sub[:3]):
                self.assertEqual(cmd[:2], ["git", "-C"])
                self.assertIn(sub[0], allowed)
                if sub[0] == "worktree":
                    self.assertEqual(sub[1], "list")
                if sub[:2] != ["rev-parse", "--absolute-git-dir"]:  # Runner's own lease-dir lookup
                    self.assertIn("--no-replace-objects", rest)
                    self.assertEqual(env.get("GIT_OPTIONAL_LOCKS"), "0")
                for entry in runner_git.HARDENING_CONFIG:
                    self.assertIn(entry, rest)

    def test_module_never_imports_subprocess_or_mutates(self):
        source = Path(wi.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names}
        self.assertNotIn("subprocess", imported)
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        forbidden = {"mkdir", "unlink", "rmtree", "write_text", "write_bytes", "open", "rename", "replace",
                     "try_acquire", "touch", "_atomic_write_json", "FactoryLedger", "PipelineRunner"}
        self.assertEqual(called & forbidden, set())
        self.assertNotIn("subprocess", source)

    def test_inventory_modifies_nothing(self):
        os.utime(self.fx.wt / "src" / "a.py", None)  # stat-dirty: an unguarded status would rewrite the index
        self.fx.add("det", None, "--detach")
        lease_dir = pipeline.worktree_lease_dir(self.fx.wt.resolve())
        state = lambda: (_git_dir_state([self.fx.repo / ".git"]),  # noqa: E731
                         plain_git(self.fx.repo, "for-each-ref").stdout,
                         plain_git(self.fx.repo, "worktree", "list", "--porcelain").stdout,
                         sorted(str(p) for p in self.root.rglob("*") if "markers" not in p.parts))
        before = state()
        self.inventory()
        self.assertEqual(state(), before)
        self.assertFalse(lease_dir.exists())

    def test_deterministic_order_fingerprint_and_immutability(self):
        self.fx.add("zeta", "feature/zeta")
        self.fx.add("alpha", "feature/alpha")
        first, second = self.inventory(), self.inventory()
        self.assertEqual(first, second)
        self.assertEqual(first.fingerprint, second.fingerprint)
        keys = [r.worktree_key for r in first.records]
        self.assertTrue(first.records[0].is_main)
        self.assertEqual(keys[1:], sorted(keys[1:]))
        self.assertEqual(len(set(r.fingerprint for r in first.records)), len(first.records))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.records[0].classification = wi.IDLE_CLEAN_UNBOUND  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.status = wi.INVENTORY_COMPLETE  # type: ignore[misc]
        write(self.fx.wt / "new.txt", "x\n")
        self.assertNotEqual(self.inventory().fingerprint, first.fingerprint)
        json.dumps(dataclasses.asdict(first))  # JSON-serializable as-is


if __name__ == "__main__":
    unittest.main()
