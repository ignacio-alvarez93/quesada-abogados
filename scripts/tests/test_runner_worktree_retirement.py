"""FCP-4D-02: read-only worktree retirement ASSESSMENT.

Every repository is a throwaway under a temporary directory, built with
PLAIN git (subprocess) - only the module under test is restricted to the
governed `runner_integration._git` read path. Each "nothing is a
candidate / nothing changed" assertion is paired with a positive control.
No test here is skipped: environment-dependent outcomes (Windows long
paths, byte-range locks) are asserted as "read correctly OR failed closed,
never a candidate".
"""

import ast
import dataclasses
import hashlib
import json
import os
import platform
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_queue as queue
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_git
from scripts.ai import runner_integration as ri
from scripts.ai import runner_pipeline as pipeline
from scripts.ai import runner_worktree_inventory as wi
from scripts.ai import runner_worktree_retirement as wr
from scripts.tests.test_runner_git import plain_git
from scripts.tests.test_runner_integration import commit, write
from scripts.tests.test_runner_worktree_inventory import FEATURE, InventoryTestCase

TRACKING = "refs/remotes/origin/develop"
SECRET = "S3CR3T-VALUE-NEVER-REPORTED"


class RetirementTestCase(InventoryTestCase):
    """InventoryTestCase's fixture (main `repo` on develop + clean linked
    `wt` on FEATURE at the same commit) plus a remote-tracking ref (so the
    shared commit is not local-only) and an empty declared queue root."""

    def setUp(self):
        super().setUp()
        plain_git(self.fx.repo, "update-ref", TRACKING, self.fx.c0)
        self.queue_root = self.root / "queue"
        self.queue_root.mkdir()

    def assess(self, repository=None, **kwargs):
        kwargs.setdefault("state_root", self.fx.state_root)
        kwargs.setdefault("ledger_root", self.fx.ledger_root)
        kwargs.setdefault("queue_roots", (str(self.queue_root),))
        kwargs.setdefault("queue_roots_complete", True)
        kwargs.setdefault("self_worktree", str(self.fx.repo))
        return wr.assess_worktree_retirement(repository or self.fx.repo, **kwargs)

    def rec(self, report, path: Path):
        key = os.path.normcase(str(Path(path).resolve()))
        matches = [r for r in report.records if r.worktree_key == key]
        self.assertEqual(len(matches), 1, [r.worktree_key for r in report.records])
        return matches[0]

    def assertRet(self, record, classification, *reasons):
        self.assertEqual(record.classification, classification, record.reason_codes)
        for reason in reasons:
            self.assertIn(reason, record.reason_codes)
        self.assertIs(record.human_review_required, True)
        self.assertIs(record.authorizes_action, False)
        self.assertIs(record.deletion_authorized, False)
        self.assertEqual(record.limitations, wr.LIMITATIONS)

    def git_dir(self, worktree: Path) -> Path:
        return Path(plain_git(worktree, "rev-parse", "--absolute-git-dir").stdout.strip())

    def enqueue(self, target, state=None, checkpoints=None, root=None) -> Path:
        root = Path(root or self.queue_root)
        item = queue.enqueue(root, work_order_text="wo\n", repository_path=str(target), mode="write")
        meta = root / item.item_id / queue.ITEM_METADATA_FILENAME
        if state is not None or checkpoints is not None:
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["state"] = state or data["state"]
            data["checkpoints"] = checkpoints or []
            meta.write_text(json.dumps(data), encoding="utf-8")
        return meta


def idle_facts(**overrides) -> wr.RetirementFacts:
    """Every candidate requirement proven: classifies as CANDIDATE."""
    fields = dict(
        worktree_key="k", path="p",
        first_inventory_status=wi.INVENTORY_COMPLETE, second_inventory_status=wi.INVENTORY_COMPLETE,
        in_first_inventory=True, in_second_inventory=True,
        inventory_classification=wi.IDLE_CLEAN_UNBOUND, second_inventory_classification=wi.IDLE_CLEAN_UNBOUND,
        inventory_lease_state=wi.LEASE_NOT_CREATED, first_record_fingerprint="f", second_record_fingerprint="f",
        self_worktree_known=True, governed_roots_resolved=True, supplemental_checked=True, ignored_count=0,
        paused_probe_ok=True, index_flags_proven=True, head_ref_consistent=True, topology_proven=True,
        local_only_commits=0, unique_commits=0, queue_roots_declared=True, queue_roots_complete_claim=True,
    )
    fields.update(overrides)
    return wr.RetirementFacts(**fields)


# ---------------------------------------------------------------------------
# High-signal realistic scenarios
# ---------------------------------------------------------------------------

class RealisticScenarioTests(RetirementTestCase):
    def test_clean_unbound_worktree_is_only_a_candidate_for_human_review(self):
        report = self.assess()
        self.assertEqual(report.status, wr.REPORT_COMPLETE, report.global_errors)
        self.assertEqual(report.schema, "fcp4d02-worktree-retirement-assessment-v1")
        r = self.rec(report, self.fx.wt)
        self.assertRet(r, wr.CANDIDATE_FOR_HUMAN_REVIEW)
        self.assertEqual(r.reason_codes, ())
        self.assertIn("NO_LOCAL_ONLY_COMMITS_IS_NOT_REMOTE_PROOF", r.advisories)
        self.assertEqual((r.facts.local_only_commits, r.facts.unique_commits, r.facts.ignored_count), (0, 0, 0))
        main = self.rec(report, self.fx.repo)
        self.assertRet(main, wr.BLOCKED, "INVENTORY_PROTECTED", "INVENTORY:MAIN_WORKTREE", "SELF_WORKTREE")
        self.assertIs(report.authorizes_action, False)
        self.assertIs(report.deletion_authorized, False)
        self.assertIs(report.human_review_required, True)
        self.assertEqual(dict(report.counts)[wr.CANDIDATE_FOR_HUMAN_REVIEW], 1)

    def test_fcp4c_idle_alone_never_becomes_a_candidate(self):
        # 156 IDLE_CLEAN_UNBOUND on the host are NOT removal eligibility:
        # without declared queue roots + completeness claim, still insufficient.
        inv = self.inventory()
        self.assertEqual(self.record(inv, self.fx.wt).classification, wi.IDLE_CLEAN_UNBOUND)  # control
        r = self.rec(self.assess(queue_roots=(), queue_roots_complete=False), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "QUEUE_ROOTS_NOT_DECLARED")
        r = self.rec(self.assess(queue_roots_complete=False), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "QUEUE_ROOTS_NOT_DECLARED_COMPLETE")
        self.assertIs(self.assess(queue_roots_complete=False).queue_roots_complete_claim, False)

    def test_dirty_worktree_is_blocked_with_inventory_findings_reused(self):
        write(self.fx.wt / "new.txt", "x\n")
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "INVENTORY_DIRTY", "INVENTORY:UNTRACKED_FILES")
        self.assertEqual(r.facts.inventory_classification, wi.DIRTY)
        self.assertFalse(r.facts.supplemental_checked)  # never improved by later checks

    def test_ignored_runner_runtime_secrets_and_databases_are_blocked(self):
        write(self.git_dir(self.fx.repo) / "info" / "exclude", "runtime/\n.env*\n*.db*\ndatabase/\nbuild/\n")
        cases = (
            ("runtime/claude_runner/queue/item.json", "IGNORED_RUNNER_RUNTIME"),
            (".env.local", "IGNORED_SECRET_ENV"),
            ("data/app.db", "IGNORED_DATABASE_FILE"),
            ("data/app.db-wal", "IGNORED_DATABASE_FILE"),
            ("database/dump.sql", "IGNORED_DATABASE_DIR"),
        )
        for rel, code in cases:
            with self.subTest(rel=rel):
                write(self.fx.wt / rel, SECRET + "\n")
                report = self.assess()
                r = self.rec(report, self.fx.wt)
                self.assertRet(r, wr.BLOCKED, code, "IGNORED_FILES_PRESENT")
                self.assertIn((code, rel), r.facts.ignored_sensitive)
                self.assertNotIn(SECRET, json.dumps(dataclasses.asdict(report)))
                (self.fx.wt / rel).unlink()
        # Other ignored content: review, not blocked; never allowlisted.
        write(self.fx.wt / "build" / "out.txt", "artifact\n")
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "IGNORED_FILES_PRESENT")
        self.assertEqual(r.facts.ignored_paths, ("build/out.txt",))
        # Positive control: the inventory itself does not see ignored files.
        self.assertEqual(self.record(self.inventory(), self.fx.wt).classification, wi.IDLE_CLEAN_UNBOUND)

    def test_sensitive_ignored_file_contents_are_never_read(self):
        write(self.git_dir(self.fx.repo) / "info" / "exclude", ".env*\n")
        secret = self.fx.wt / ".env"
        write(secret, SECRET + "\n")
        opened = []
        real_open = open

        def recording_open(file, *args, **kwargs):
            opened.append(os.path.normcase(str(file)))
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", recording_open), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read_bytes")) as rb, \
                mock.patch.object(Path, "read_text", autospec=True, side_effect=Path.read_text) as rt:
            r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "IGNORED_SECRET_ENV")
        rb.assert_not_called()
        self.assertNotIn(os.path.normcase(str(secret)), opened)
        self.assertNotIn(secret, [c.args[0] for c in rt.call_args_list])

    def test_bounded_ignored_overflow_is_insufficient_and_never_hides_secrets(self):
        write(self.git_dir(self.fx.repo) / "info" / "exclude", "build/\n.env*\n")
        for i in range(wr.MAX_IGNORED_ENTRIES + 1):
            write(self.fx.wt / "build" / f"f{i:04d}.o", "")
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "IGNORED_ENUMERATION_OVERFLOW", "IGNORED_FILES_PRESENT")
        self.assertEqual(r.facts.ignored_count, wr.MAX_IGNORED_ENTRIES + 1)
        self.assertEqual(len(r.facts.ignored_paths), wr.MAX_IGNORED_ENTRIES)
        write(self.fx.wt / "zzz" / ".env", "x\n")  # sorts after the retained window
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "IGNORED_SECRET_ENV", "IGNORED_ENUMERATION_OVERFLOW")
        self.assertNotIn("zzz/.env", r.facts.ignored_paths)

    def test_paused_git_operations_are_blocked(self):
        plain_git(self.fx.wt, "bisect", "start")  # real, leaves the tree clean and on the branch
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "PAUSED_BISECT")
        self.assertEqual(self.record(self.inventory(), self.fx.wt).classification, wi.IDLE_CLEAN_UNBOUND)
        plain_git(self.fx.wt, "bisect", "reset")
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)
        git_dir = self.git_dir(self.fx.wt)
        for marker, code in wr._PAUSED_MARKERS:
            with self.subTest(marker=marker):
                target = git_dir / marker
                if marker in ("rebase-merge", "rebase-apply", "sequencer"):
                    target.mkdir()
                else:
                    target.write_text(self.fx.c0 + "\n", encoding="utf-8")
                self.assertRet(self.rec(self.assess(), self.fx.wt), wr.BLOCKED, code)
                (target.rmdir() if target.is_dir() else target.unlink())
        # Markers are read from the worktree's OWN git dir, not the main one.
        (self.git_dir(self.fx.repo) / "MERGE_HEAD").write_text(self.fx.c0 + "\n", encoding="utf-8")
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)

    def test_hidden_index_flags_are_insufficient_evidence(self):
        plain_git(self.fx.wt, "update-index", "--skip-worktree", "shared.txt")
        write(self.fx.wt / "shared.txt", "hidden local edit\n")
        # Positive control: status (and so the inventory) cannot see the edit.
        self.assertEqual(plain_git(self.fx.wt, "status", "--porcelain").stdout, "")
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "HIDDEN_INDEX_SKIP_WORKTREE")
        self.assertEqual(r.facts.skip_worktree_paths, ("shared.txt",))
        plain_git(self.fx.wt, "update-index", "--no-skip-worktree", "shared.txt")
        plain_git(self.fx.wt, "checkout", "--", "shared.txt")
        plain_git(self.fx.wt, "update-index", "--assume-unchanged", "src/a.py")
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "HIDDEN_INDEX_ASSUME_UNCHANGED")
        self.assertEqual(r.facts.assume_unchanged_paths, ("src/a.py",))

    def test_unprovable_index_flags_fail_closed(self):
        real = ri._git

        def odd(repo, *args, **kwargs):
            if args[:1] == ("ls-files",):
                return 0, "K weird\0"
            return real(repo, *args, **kwargs)

        with mock.patch.object(wr.ri, "_git", odd):
            r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "SUPPLEMENTAL_READ_FAILED")
        self.assertFalse(r.facts.index_flags_proven)

    def test_local_only_and_unique_commits_and_worktree_refs_need_review(self):
        tip = commit(self.fx.wt, "local work", {"src/b.py": "b\n"})
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "LOCAL_ONLY_COMMITS", "UNIQUE_LOCAL_COMMITS")
        self.assertEqual((r.facts.local_only_commits, r.facts.unique_commits), (1, 1))
        plain_git(self.fx.repo, "branch", "other", tip)  # reachable elsewhere, still not on a remote
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "LOCAL_ONLY_COMMITS")
        self.assertEqual(r.facts.unique_commits, 0)
        plain_git(self.fx.repo, "update-ref", "refs/remotes/origin/feature", tip)
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)
        plain_git(self.fx.wt, "update-ref", "refs/worktree/keep", tip)
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "WORKTREE_LOCAL_REFS")
        self.assertEqual(r.facts.worktree_local_refs, ("refs/worktree/keep",))

    def test_no_remote_tracking_refs_means_local_only(self):
        plain_git(self.fx.repo, "update-ref", "-d", TRACKING)
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "LOCAL_ONLY_COMMITS")

    def test_untrustworthy_topology_is_insufficient_and_skips_reachability(self):
        common = self.git_dir(self.fx.repo)
        c1 = commit(self.fx.repo, "c1")
        cases = (
            ("GRAFTS", lambda: write(common / "info" / "grafts", f"{c1}\n"),
             lambda: (common / "info" / "grafts").unlink()),
            ("SHALLOW", lambda: write(common / "shallow", f"{self.fx.c0}\n"), lambda: (common / "shallow").unlink()),
            ("REPLACE_REFS", lambda: plain_git(self.fx.repo, "replace", c1, self.fx.c0),
             lambda: plain_git(self.fx.repo, "replace", "-d", c1)),
            ("PARTIAL_CLONE", lambda: plain_git(self.fx.repo, "config", "remote.origin.promisor", "true"),
             lambda: plain_git(self.fx.repo, "config", "--unset", "remote.origin.promisor")),
        )
        for hazard, apply, undo in cases:
            with self.subTest(hazard=hazard):
                apply()
                r = self.rec(self.assess(), self.fx.wt)
                self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "UNTRUSTWORTHY_TOPOLOGY")
                self.assertIn(hazard, r.facts.topology_hazards)
                self.assertIsNone(r.facts.local_only_commits)
                undo()
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)


# ---------------------------------------------------------------------------
# Queue roots
# ---------------------------------------------------------------------------

class QueueTests(RetirementTestCase):
    def test_active_queue_states_block_and_terminal_or_checkpoints_need_review(self):
        S = queue.QueueState
        for state in (S.QUEUED, S.RUNNING, S.WAITING_QUOTA, S.BLOCKED_ON_CHECKPOINT):
            with self.subTest(state=state):
                meta = self.enqueue(self.fx.wt, state.value)
                r = self.rec(self.assess(), self.fx.wt)
                self.assertRet(r, wr.BLOCKED, "QUEUE_ITEM_ACTIVE")
                self.assertEqual([i[2] for i in r.facts.queue_items], [state.value])
                _rmtree_item(meta)
        for state in (S.SUCCEEDED, S.FAILED, S.FAILED_SAFETY):
            with self.subTest(state=state):
                meta = self.enqueue(self.fx.wt, state.value)
                self.assertRet(self.rec(self.assess(), self.fx.wt), wr.REVIEW_REQUIRED, "QUEUE_ITEM_TERMINAL_HISTORY")
                _rmtree_item(meta)
        self.enqueue(self.fx.wt, S.SUCCEEDED.value, checkpoints=[{"checkpoint_id": "c1"}])
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.REVIEW_REQUIRED, "QUEUE_ITEM_CHECKPOINTS")

    def test_items_for_other_targets_do_not_affect_a_worktree(self):
        self.enqueue(self.root / "elsewhere", queue.QueueState.RUNNING.value)
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)

    def test_path_aliases_match_canonically(self):
        aliases = [str(self.fx.wt / ".." / self.fx.wt.name), str(self.fx.wt) + os.sep, self.fx.wt.as_posix()]
        if platform.system() == "Windows":
            aliases.append(str(self.fx.wt).upper())
        for alias in aliases:
            with self.subTest(alias=alias):
                meta = self.enqueue(alias, queue.QueueState.QUEUED.value)
                self.assertRet(self.rec(self.assess(), self.fx.wt), wr.BLOCKED, "QUEUE_ITEM_ACTIVE")
                r = self.rec(self.assess(self_worktree=alias), self.fx.wt)
                self.assertRet(r, wr.BLOCKED, "SELF_WORKTREE")
                _rmtree_item(meta)

    def test_every_declared_root_is_read(self):
        second = self.root / "queue2"
        second.mkdir()
        self.enqueue(self.fx.wt, queue.QueueState.RUNNING.value, root=second)
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)  # undeclared: unseen
        r = self.rec(self.assess(queue_roots=(str(self.queue_root), str(second))), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "QUEUE_ITEM_ACTIVE")

    def test_missing_corrupt_or_unresolvable_queue_roots_fail_closed(self):
        report = self.assess(queue_roots=(str(self.root / "absent"),))
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertRet(self.rec(report, self.fx.wt), wr.INSUFFICIENT_EVIDENCE, "QUEUE_ROOT_MISSING")
        meta = self.enqueue(self.fx.wt)
        meta.write_text("{not json", encoding="utf-8")
        report = self.assess()
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertTrue(any(e.startswith("QUEUE_ROOT_UNREADABLE") for e in report.global_errors))
        self.assertRet(self.rec(report, self.fx.wt), wr.INSUFFICIENT_EVIDENCE, "QUEUE_ROOT_UNREADABLE")
        _rmtree_item(meta)
        meta = self.enqueue("placeholder")
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["repository_path"] = "   "
        meta.write_text(json.dumps(data), encoding="utf-8")
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.INSUFFICIENT_EVIDENCE,
                       "QUEUE_ITEM_TARGET_UNRESOLVABLE")

    def test_half_applied_queue_item_fails_closed_and_staging_is_not_an_item(self):
        (self.queue_root / ".x.staging-1234").mkdir()  # never published: ignored by list_items
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)
        meta = self.enqueue(self.fx.wt, queue.QueueState.SUCCEEDED.value)
        (meta.parent / queue.WORK_ORDER_FILENAME).write_text("tampered\n", encoding="utf-8")
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.INSUFFICIENT_EVIDENCE, "QUEUE_ROOT_UNREADABLE")
        _rmtree_item(meta)
        (self.queue_root / "20260101T000000Z_half").mkdir()  # published dir, no item.json yet
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.INSUFFICIENT_EVIDENCE, "QUEUE_ROOT_UNREADABLE")

    def test_queue_change_between_reads_is_drift(self):
        real = wr._read_queues
        calls = []

        def drifting(roots):
            calls.append(1)
            if len(calls) == 2:
                self.enqueue(self.fx.wt, queue.QueueState.SUCCEEDED.value)
            return real(roots)

        with mock.patch.object(wr, "_read_queues", drifting):
            r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "QUEUE_STATE_DRIFT", "QUEUE_ITEM_TERMINAL_HISTORY")

    def test_windows_long_queue_root_reads_or_fails_closed(self):
        deep = self.root / "q"
        for i in range(12):
            deep = deep / f"segment_{i:02d}_{'x' * 18}"
        self.assertGreater(len(str(deep)), 300)
        queue._long_path_mkdir(deep, parents=True, exist_ok=True)
        self.addCleanup(_rmtree_item, self.root / "q" / "x")  # the fixture's own rmtree is not long-path safe
        payload_item = queue.enqueue(self.queue_root, work_order_text="wo\n", repository_path=str(self.fx.wt),
                                     mode="write")
        src = self.queue_root / payload_item.item_id
        dst = deep / payload_item.item_id
        queue._long_path_mkdir(dst)
        for name in (queue.ITEM_METADATA_FILENAME, queue.WORK_ORDER_FILENAME):
            data = (src / name).read_bytes()
            with open(queue._windows_long_path(dst / name), "wb") as fh:
                fh.write(data)
        _rmtree_item(src / queue.ITEM_METADATA_FILENAME)
        r = self.rec(self.assess(queue_roots=(str(deep),)), self.fx.wt)
        # Either the item was read (QUEUED => blocked) or the root failed
        # closed - never silently empty, never a candidate.
        self.assertIn(r.classification, (wr.BLOCKED, wr.INSUFFICIENT_EVIDENCE), r.reason_codes)
        self.assertTrue({"QUEUE_ITEM_ACTIVE", "QUEUE_ROOT_MISSING", "QUEUE_ROOT_UNREADABLE"} & set(r.reason_codes))

    def test_locked_queue_item_handle_fails_closed(self):
        meta = self.enqueue(self.fx.wt, queue.QueueState.SUCCEEDED.value)
        if platform.system() == "Windows":
            import msvcrt
            fh = open(meta, "r+b")
            self.addCleanup(fh.close)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            self.addCleanup(lambda: (fh.seek(0), msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)))
            r = self.rec(self.assess(), self.fx.wt)
        else:  # no mandatory byte-range locks: inject the same OS refusal
            real = Path.read_text

            def denied(path, *a, **k):
                if path.name == queue.ITEM_METADATA_FILENAME:
                    raise PermissionError(13, "locked")
                return real(path, *a, **k)

            with mock.patch.object(Path, "read_text", denied):
                r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "QUEUE_ROOT_UNREADABLE")

    def test_open_shared_handle_on_worktree_file_is_harmless(self):
        with open(self.fx.wt / "shared.txt", "rb"):
            self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)


def _rmtree_item(meta: Path) -> None:
    import shutil
    shutil.rmtree(queue._windows_long_path(meta.parent))


# ---------------------------------------------------------------------------
# Self, governed roots, ledger, pipeline and lease
# ---------------------------------------------------------------------------

class OwnershipTests(RetirementTestCase):
    def test_self_and_overlapping_governed_roots_are_blocked(self):
        self.assertRet(self.rec(self.assess(self_worktree=str(self.fx.wt)), self.fx.wt), wr.BLOCKED, "SELF_WORKTREE")
        r = self.rec(self.assess(governed_roots=(str(self.fx.wt / "runtime" / "x"),)), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "GOVERNED_ROOT_OVERLAP")
        self.assertIn(("governed_root", os.path.normcase(str((self.fx.wt / "runtime" / "x").resolve()))),
                      r.facts.overlapping_roots)
        inner_queue = self.fx.wt / "q"
        r = self.rec(self.assess(queue_roots=(str(inner_queue),)), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "GOVERNED_ROOT_OVERLAP", "QUEUE_ROOT_MISSING")
        r = self.rec(self.assess(governed_roots=(str(self.root),)), self.fx.wt)  # enclosing root
        self.assertRet(r, wr.BLOCKED, "GOVERNED_ROOT_OVERLAP")
        r = self.rec(self.assess(self_worktree=str(self.fx.wt / "nested")), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "GOVERNED_ROOT_OVERLAP")

    def test_unknown_self_worktree_is_insufficient(self):
        report = self.assess(self_worktree=None)
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertRet(self.rec(report, self.fx.wt), wr.INSUFFICIENT_EVIDENCE, "SELF_WORKTREE_UNKNOWN")

    def test_ledger_work_product_and_history_need_review(self):
        ledger = flog.FactoryLedger(self.fx.ledger_root)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        ledger.append(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "LEDGER_HISTORY")
        self.assertNotIn("LEDGER_WORK_PRODUCT", r.reason_codes)
        ledger.append(flog.WORK_PRODUCT_CREATED, pipeline_id="p1", worker_id="w1", branch=FEATURE)
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "LEDGER_WORK_PRODUCT", "LEDGER_HISTORY")
        self.assertEqual(r.facts.ledger_work_products, ((flog.WORK_PRODUCT_CREATED, "p1", "w1"),))

    def test_open_ledger_worker_and_pipeline_states(self):
        ledger = flog.FactoryLedger(self.fx.ledger_root)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.BLOCKED, "INVENTORY_OWNERSHIP_INCONSISTENT",
                       "INVENTORY:LEDGER_OPEN_WORKER")
        ledger.append(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        stopped = [{"attempt": 1, "executed": True, "process_confirmed_stopped": True}]
        cases = (
            ("RUNNING", {}, "INVENTORY_ACTIVE_PIPELINE"),
            ("RETRY_WAIT", {"attempts": stopped, "pending_resume_from": "x/work_product.json"},
             "INVENTORY_RECOVERY_PENDING"),
            ("INTERRUPTED", {"attempts": stopped}, "INVENTORY_RECOVERY_PENDING"),
        )
        for state, extra, code in cases:
            with self.subTest(state=state):
                path = self.fx.write_worker("pipe", "w1", self.fx.wt, state, **extra)
                self.assertRet(self.rec(self.assess(), self.fx.wt), wr.BLOCKED, code)
                path.unlink()
        self.fx.write_worker("pipe", "w1", self.fx.wt, "SUCCESS", attempts=stopped)
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.REVIEW_REQUIRED, "PIPELINE_HISTORY")

    def test_global_corrupt_state_makes_every_record_insufficient(self):
        write(self.fx.ledger_root / flog.EVENTS_FILENAME, '{"event_type": "WORKER_STARTED"\n')  # torn line
        report = self.assess()
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertEqual(len(report.records), 2)  # nothing concealed
        self.assertRet(self.rec(report, self.fx.wt), wr.INSUFFICIENT_EVIDENCE, "INVENTORY_NOT_COMPLETE",
                       "INVENTORY_UNSAFE", "INVENTORY:GLOBAL_STATE_UNREADABLE", "LEDGER_UNREADABLE")
        (self.fx.ledger_root / flog.EVENTS_FILENAME).unlink()
        write(self.fx.state_root / "pipe" / "workers" / "w1" / "worker.json", "{corrupt")
        report = self.assess()
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertRet(self.rec(report, self.fx.wt), wr.INSUFFICIENT_EVIDENCE, "INVENTORY_NOT_COMPLETE")
        report = self.assess(state_root=self.root / "absent-state")
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        for r in report.records:
            self.assertNotEqual(r.classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)

    def test_per_record_unreadable_worktree_does_not_hide_others(self):
        other = self.root / "other"
        other.mkdir()
        plain_git(other, "init", "-q")
        broken = self.fx.add("broken", "feature/broken")
        (broken / ".git").unlink()
        (broken / ".git").write_text(f"gitdir: {(other / '.git').as_posix()}\n", encoding="utf-8")
        report = self.assess()
        self.assertRet(self.rec(report, broken), wr.INSUFFICIENT_EVIDENCE, "INVENTORY_UNSAFE",
                       "INVENTORY:GIT_READ_FAILED")
        self.assertRet(self.rec(report, self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)

    def test_os_lease_contention_blocks(self):
        lease_dir = pipeline.worktree_lease_dir(self.fx.wt.resolve())
        proc = self.hold_lease(lease_dir)
        self.assertRet(self.rec(self.assess(), self.fx.wt), wr.BLOCKED, "INVENTORY_ACTIVE_LEASED",
                       "INVENTORY:WORKTREE_LEASE_HELD")
        self.assertEqual(pipeline.DirLease(lease_dir).holder()["pipeline_id"], "other")
        proc.kill()
        proc.wait(timeout=30)

    def test_residual_lease_diagnostics_need_review_and_p1_is_the_only_rewrite(self):
        lease_dir = pipeline.worktree_lease_dir(self.fx.wt.resolve())
        proc = self.hold_lease(lease_dir)
        proc.kill()
        proc.wait(timeout=30)
        identity = lease_dir / pipeline.DirLease.IDENTITY
        lock = lease_dir / queue.LOCK_FILENAME
        identity_before = identity.read_bytes()
        lock.write_bytes(b"\0pid=424242 host=ghost at=2000-01-01T00:00:00+00:00\n")
        r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.REVIEW_REQUIRED, "LEASE_DIAGNOSTIC_RESIDUE", "LEASE_LOCK_FILE_PRESENT")
        self.assertEqual(identity.read_bytes(), identity_before)  # evidence preserved
        # Known inherited P1: the FCP-4C probe may rewrite the free lock's
        # diagnostic bytes; it is documented, never claimed byte-perfect.
        self.assertTrue(lock.exists())
        self.assertRegex(lock.read_bytes().decode("utf-8", "replace"), r"pid=\d+ host=")
        self.assertIn("LEASE_PROBE_MAY_REWRITE_QUEUE_LOCK_DIAGNOSTIC_BYTES", r.limitations)


# ---------------------------------------------------------------------------
# Two-inventory identity checks
# ---------------------------------------------------------------------------

class InventoryIdentityTests(RetirementTestCase):
    def between_inventories(self, action):
        real = wi.inventory_worktrees
        calls = []

        def wrapped(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                action()
            return real(*args, **kwargs)

        return mock.patch.object(wr.inv, "inventory_worktrees", wrapped), calls

    def test_exactly_two_inventories(self):
        patch, calls = self.between_inventories(lambda: None)
        with patch:
            self.assertRet(self.rec(self.assess(), self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)
        self.assertEqual(len(calls), 2)

    def test_changed_record_fingerprint_is_insufficient(self):
        patch, _ = self.between_inventories(lambda: commit(self.fx.wt, "moved"))
        with patch:
            r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "RECORD_FINGERPRINT_CHANGED")
        self.assertNotEqual(r.facts.first_record_fingerprint, r.facts.second_record_fingerprint)

    def test_disappearing_and_appearing_records_are_reported_not_omitted(self):
        gone = self.fx.add("gone", "feature/gone")
        late = self.root / "late"
        patch, _ = self.between_inventories(lambda: (
            plain_git(self.fx.repo, "worktree", "remove", "--force", str(gone)),
            plain_git(self.fx.repo, "worktree", "add", "-q", "-b", "feature/late", str(late)),
        ))
        with patch:
            report = self.assess()
        self.assertRet(self.rec(report, gone), wr.INSUFFICIENT_EVIDENCE, "RECORD_ABSENT_FROM_SECOND_INVENTORY")
        self.assertRet(self.rec(report, late), wr.INSUFFICIENT_EVIDENCE, "RECORD_ABSENT_FROM_FIRST_INVENTORY")
        self.assertRet(self.rec(report, self.fx.wt), wr.CANDIDATE_FOR_HUMAN_REVIEW)

    def test_second_inventory_blocking_class_is_never_hidden(self):
        patch, _ = self.between_inventories(lambda: write(self.fx.wt / "late.txt", "x\n"))
        with patch:
            r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.BLOCKED, "INVENTORY_DIRTY", "RECORD_FINGERPRINT_CHANGED")

    def test_inventory_raising_fails_closed_without_candidates(self):
        with mock.patch.object(wr.inv, "inventory_worktrees", side_effect=RuntimeError("boom")):
            report = self.assess()
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertEqual(report.records, ())
        self.assertTrue(report.global_errors[0].startswith("INVENTORY_RAISED"))

    def test_registry_unreadable_fails_closed(self):
        plain = self.root / "plain"
        plain.mkdir()
        report = self.assess(plain)
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertEqual(report.records, ())

    def test_admin_state_change_during_supplemental_reads_fails_closed(self):
        real = wr._admin_state
        calls = []

        def changing(git_dir):
            calls.append(1)
            state = real(git_dir)
            return state + (("changed", len(calls)),)

        with mock.patch.object(wr, "_admin_state", changing):
            r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "GIT_ADMIN_STATE_CHANGED")

    def test_supplemental_read_error_fails_closed(self):
        real = ri._git

        def failing(repo, *args, **kwargs):
            if args[:1] == ("rev-list",):
                raise ri._GitReadError("git rev-list", "boom")
            return real(repo, *args, **kwargs)

        with mock.patch.object(wr.ri, "_git", failing):
            r = self.rec(self.assess(), self.fx.wt)
        self.assertRet(r, wr.INSUFFICIENT_EVIDENCE, "SUPPLEMENTAL_READ_FAILED")


# ---------------------------------------------------------------------------
# Pure classification: mapping, precedence, monotonicity
# ---------------------------------------------------------------------------

class ClassificationTests(unittest.TestCase):
    def test_baseline_is_candidate(self):
        a = wr.classify_retirement(idle_facts())
        self.assertEqual(a.classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)
        self.assertEqual((a.authorizes_action, a.deletion_authorized, a.human_review_required), (False, False, True))

    def test_every_inventory_class_maps_and_never_improves(self):
        expected = {
            wi.UNSAFE: wr.INSUFFICIENT_EVIDENCE, wi.RECOVERY_PENDING: wr.BLOCKED, wi.ACTIVE_LEASED: wr.BLOCKED,
            wi.ACTIVE_PIPELINE: wr.BLOCKED, wi.OWNERSHIP_INCONSISTENT: wr.BLOCKED, wi.MISSING_PATH: wr.BLOCKED,
            wi.PROTECTED: wr.BLOCKED, wi.GIT_LOCKED: wr.BLOCKED, wi.DIRTY: wr.BLOCKED, wi.DETACHED: wr.BLOCKED,
        }
        self.assertEqual(set(expected) | {wi.IDLE_CLEAN_UNBOUND}, set(wi.CLASSIFICATION_PRECEDENCE))
        for cls, target in expected.items():
            with self.subTest(cls=cls):
                a = wr.classify_retirement(idle_facts(inventory_classification=cls, inventory_reason_codes=("X",)))
                self.assertEqual(a.classification, target)
                self.assertIn(f"INVENTORY_{cls}", a.reason_codes)
                self.assertIn("INVENTORY:X", a.reason_codes)
                a = wr.classify_retirement(idle_facts(second_inventory_classification=cls))
                self.assertEqual(a.classification, target)
        a = wr.classify_retirement(idle_facts(inventory_classification="SOMETHING_NEW"))
        self.assertEqual(a.classification, wr.INSUFFICIENT_EVIDENCE)

    def test_any_single_unproven_fact_prevents_a_candidate(self):
        degradations = dict(
            first_inventory_status=wi.INVENTORY_FAILED_CLOSED, second_inventory_status=None,
            in_first_inventory=False, in_second_inventory=False, second_record_fingerprint="g",
            first_record_fingerprint=None, inventory_classification=None, self_worktree_known=False,
            governed_roots_resolved=False, supplemental_checked=False, supplemental_errors=("e",),
            supplemental_status_entries=("?? x",), ignored_count=None, paused_probe_ok=False,
            index_flags_proven=False, head_ref_consistent=False, topology_proven=False, local_only_commits=None,
            unique_commits=None, git_admin_state_changed=True, queue_roots_declared=False,
            queue_roots_complete_claim=False, queue_errors=("QUEUE_ROOT_MISSING",), queue_drift=True,
            ledger_error="x", ledger_drift=True, topology_hazards=("SHALLOW",),
            skip_worktree_paths=("a",), assume_unchanged_paths=("a",),
        )
        names = {f.name for f in dataclasses.fields(wr.RetirementFacts)}
        for name, value in degradations.items():
            self.assertIn(name, names)
            with self.subTest(name=name):
                a = wr.classify_retirement(idle_facts(**{name: value}))
                self.assertIn(a.classification, (wr.INSUFFICIENT_EVIDENCE, wr.BLOCKED), a.reason_codes)

    def test_unproven_fact_is_never_hidden_behind_a_review_finding(self):
        for name, value in (("head_ref_consistent", False), ("paused_probe_ok", False),
                            ("index_flags_proven", False), ("unique_commits", None)):
            with self.subTest(name=name):
                a = wr.classify_retirement(idle_facts(ignored_count=1, **{name: value}))
                self.assertEqual(a.classification, wr.INSUFFICIENT_EVIDENCE, a.reason_codes)
                self.assertIn("IGNORED_FILES_PRESENT", a.reason_codes)

    def test_fixed_precedence_retains_every_reason_in_order(self):
        facts = idle_facts(
            inventory_advisories=("TERMINAL_PIPELINE_HISTORY",), ignored_count=3,
            ignored_sensitive=(("IGNORED_SECRET_ENV", ".env"),), queue_drift=True,
            queue_items=(("q", "i", "SUCCEEDED", 1),), local_only_commits=2,
        )
        a = wr.classify_retirement(facts)
        self.assertEqual(a.classification, wr.BLOCKED)
        tiers = {"IGNORED_SECRET_ENV": 0, "QUEUE_STATE_DRIFT": 1, "PIPELINE_HISTORY": 2,
                 "IGNORED_FILES_PRESENT": 2, "QUEUE_ITEM_TERMINAL_HISTORY": 2, "QUEUE_ITEM_CHECKPOINTS": 2,
                 "LOCAL_ONLY_COMMITS": 2}
        self.assertEqual(set(a.reason_codes), set(tiers))
        order = [tiers[c] for c in a.reason_codes]
        self.assertEqual(order, sorted(order))

    def test_monotonic_adding_findings_never_improves(self):
        rank = {c: i for i, c in enumerate(wr.CLASSIFICATION_PRECEDENCE)}
        additions = (
            dict(ignored_count=1), dict(worktree_local_refs=("refs/worktree/x",)),
            dict(queue_items=(("q", "i", "QUEUED", 0),)), dict(ledger_history=(("E", "p", "w"),)),
            dict(paused_operations=(("MERGE_HEAD", "PAUSED_MERGE"),)), dict(is_self_worktree=True),
            dict(overlapping_roots=(("state_root", "x"),)), dict(queue_errors=("QUEUE_ROOT_MISSING",)),
            dict(inventory_lease_state=wi.LEASE_FREE), dict(skip_worktree_paths=("a",)),
        )
        for first in additions:
            base = wr.classify_retirement(idle_facts(**first))
            for second in additions:
                with self.subTest(first=first, second=second):
                    both = wr.classify_retirement(idle_facts(**{**first, **second}))
                    self.assertLessEqual(rank[both.classification], rank[base.classification])

    def test_non_evidence_never_upgrades(self):
        # Branch names, merge status, ahead==0, age, module closure: not facts here at all.
        names = {f.name for f in dataclasses.fields(wr.RetirementFacts)}
        for banned in ("merged", "ahead", "age", "created", "module_closed", "closed"):
            self.assertFalse(any(banned in n for n in names), banned)
        dirty = idle_facts(inventory_classification=wi.DIRTY, worktree_key="merged-and-closed", path="done")
        self.assertEqual(wr.classify_retirement(dirty).classification, wr.BLOCKED)

    def test_sensitive_path_rules(self):
        S = wr._sensitive_codes
        self.assertEqual(S("runtime/claude_runner/x"), ("IGNORED_RUNNER_RUNTIME",))
        self.assertEqual(S("Runtime/Claude_Runner/x"), ("IGNORED_RUNNER_RUNTIME",))
        self.assertEqual(S("a/.env.prod"), ("IGNORED_SECRET_ENV",))
        self.assertEqual(S("x.sqlite.db"), ("IGNORED_DATABASE_FILE",))
        self.assertEqual(S("database/x"), ("IGNORED_DATABASE_DIR",))
        self.assertEqual(S("runtime/other/x"), ())
        self.assertEqual(S("build/out.o"), ())


# ---------------------------------------------------------------------------
# Read-only behavior, determinism, contract shape
# ---------------------------------------------------------------------------

class ReadOnlyAndContractTests(RetirementTestCase):
    def snapshot(self, exclude=()):
        files = {}
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and p not in exclude:
                files[str(p)] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            elif p.is_dir():
                files[str(p)] = "dir"
        return (files, plain_git(self.fx.repo, "for-each-ref").stdout,
                plain_git(self.fx.repo, "worktree", "list", "--porcelain").stdout)

    def test_assessment_modifies_nothing_beyond_documented_lease_diagnostic(self):
        os.utime(self.fx.wt / "src" / "a.py", None)  # stat-dirty: unguarded status would rewrite the index
        write(self.git_dir(self.fx.repo) / "info" / "exclude", "build/\n")
        write(self.fx.wt / "build" / "o.txt", "x\n")
        self.enqueue(self.fx.wt, queue.QueueState.SUCCEEDED.value)
        flog.FactoryLedger(self.fx.ledger_root).append(flog.WORK_PRODUCT_CREATED, pipeline_id="p", worker_id="w",
                                                       worktree=str(self.fx.wt))
        lease = pipeline.DirLease(pipeline.worktree_lease_dir(self.fx.wt.resolve()))
        self.assertTrue(lease.try_acquire({"pid": 0}))
        lease.release()
        lock = lease.directory / queue.LOCK_FILENAME
        before = self.snapshot(exclude=(lock,))
        lock_existed = lock.exists()
        report = self.assess()
        self.assertEqual(self.snapshot(exclude=(lock,)), before)
        self.assertEqual(lock.exists(), lock_existed)
        self.assertEqual(self.rec(report, self.fx.wt).classification, wr.REVIEW_REQUIRED)

    def test_only_governed_read_only_git_subcommands_and_ls_files_shape(self):
        calls = []
        real_run = runner_git.subprocess.run

        def recording(cmd, *args, **kwargs):
            calls.append((list(cmd), dict(kwargs.get("env") or {})))
            return real_run(cmd, *args, **kwargs)

        git_calls = []
        real_git = ri._git

        def recording_git(repo, *args, **kwargs):
            git_calls.append(args)
            return real_git(repo, *args, **kwargs)

        with mock.patch.object(runner_git.subprocess, "run", recording), \
                mock.patch.object(wr.ri, "_git", recording_git):
            self.assess()
        self.assertEqual([a for a in git_calls if a[0] == "ls-files"], [("ls-files", "-v", "-z")])
        allowed = ri._READ_SUBCOMMANDS | {"check-attr"}
        forbidden = {"fetch", "pull", "push", "commit", "merge", "rebase", "reset", "checkout", "switch",
                     "update-ref", "update-index", "gc", "prune", "add", "rm", "clean", "stash", "restore",
                     "branch", "tag", "replace", "maintenance", "bisect", "worktree remove", "read-tree"}
        for cmd, env in calls:
            rest = cmd[3:]
            sub = rest[runner_git._subcommand_index(rest):]
            with self.subTest(cmd=sub[:3]):
                self.assertIn(sub[0], allowed)
                self.assertNotIn(sub[0], forbidden)
                if sub[0] == "worktree":
                    self.assertEqual(sub[1], "list")
                if sub[0] == "ls-files" and "--stage" not in sub:  # runner_git's own preflight uses --stage
                    self.assertEqual(sub[1:], ["-v", "-z"])
                if sub[:2] != ["rev-parse", "--absolute-git-dir"]:
                    self.assertIn("--no-replace-objects", rest)
                    self.assertEqual(env.get("GIT_OPTIONAL_LOCKS"), "0")

    def test_module_has_no_forbidden_imports_apis_or_capability_labels(self):
        source = Path(wr.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names} | {node.module for node in ast.walk(tree)
                                                if isinstance(node, ast.ImportFrom) and node.module}
        for bad in ("subprocess", "shutil", "sqlite3", "runner_promotion_host_ledger", "runner_pipeline",
                    "runner_git", "threading", "multiprocessing"):
            self.assertFalse(any(bad in name for name in imported), bad)
        called = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                  for node in ast.walk(tree) if isinstance(node, ast.Call)}
        forbidden = {"mkdir", "unlink", "rmtree", "rmdir", "remove", "write_text", "write_bytes", "open", "rename",
                     "replace", "touch", "try_acquire", "acquire", "release", "_atomic_write_json", "append_event",
                     "FactoryLedger", "HostLedger", "PipelineRunner", "QueueLock", "DirLease", "run", "Popen",
                     "system", "transition_item", "enqueue", "chmod", "utime"}
        self.assertEqual(called & forbidden, set())
        for word in ("HostLedger", "subprocess.", "os.remove", "shutil."):
            self.assertNotIn(word, source.replace("SQLite HostLedger", "").replace("HOST_LEDGER", ""))

    def test_no_positive_capability_fields(self):
        report = self.assess()
        bad = re.compile(r"eligib|approv|delet|prune|remov", re.IGNORECASE)

        def walk(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if bad.search(k):
                        self.assertEqual(k, "deletion_authorized", path + k)
                        self.assertIs(v, False)
                    walk(v, path + k + ".")
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    walk(v, path)

        payload = dataclasses.asdict(report)
        walk(payload)
        self.assertIs(payload["deletion_authorized"], False)
        for r in payload["records"]:
            self.assertIs(r["deletion_authorized"], False)
            self.assertIs(r["authorizes_action"], False)
        for cls in wr.CLASSIFICATION_PRECEDENCE:
            self.assertIsNone(bad.search(cls))

    def test_deterministic_fingerprint_and_immutability(self):
        self.fx.add("zeta", "feature/zeta")
        first, second = self.assess(), self.assess()
        self.assertEqual(first, second)
        self.assertEqual(first.fingerprint, second.fingerprint)
        keys = [r.worktree_key for r in first.records]
        self.assertEqual(keys[0], os.path.normcase(str(self.fx.repo.resolve())))
        self.assertEqual(keys[1:], sorted(keys[1:]))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.records[0].classification = wr.CANDIDATE_FOR_HUMAN_REVIEW  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.records[0].facts.ignored_count = 0  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.status = wr.REPORT_COMPLETE  # type: ignore[misc]
        json.dumps(dataclasses.asdict(first))
        write(self.fx.wt / "new.txt", "x\n")
        self.assertNotEqual(self.assess().fingerprint, first.fingerprint)

    def test_fingerprint_excludes_lease_timestamps_and_pids(self):
        identity = pipeline.worktree_lease_dir(self.fx.wt.resolve()) / pipeline.DirLease.IDENTITY
        prints = []
        for pid, stamp in ((1, "2026-01-01T00:00:00+00:00"), (2, "2026-02-02T00:00:00+00:00")):
            write(identity, json.dumps({"pid": pid, "last_heartbeat_utc": stamp}))
            report = self.assess()
            self.assertRet(self.rec(report, self.fx.wt), wr.REVIEW_REQUIRED, "LEASE_DIAGNOSTIC_RESIDUE")
            prints.append((report.fingerprint, self.rec(report, self.fx.wt).fingerprint))
        self.assertEqual(prints[0], prints[1])

    def test_classification_is_pure(self):
        facts = idle_facts(ignored_count=2)
        with mock.patch.object(wr.ri, "_git", side_effect=AssertionError("no I/O")), \
                mock.patch.object(wr.inv, "inventory_worktrees", side_effect=AssertionError("no I/O")):
            a, b = wr.classify_retirement(facts), wr.classify_retirement(facts)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
