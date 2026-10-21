"""FCP-1B-CORE: read-only canonical-base and integration-candidate assessment.

Every repository here is a throwaway under a temporary directory, built with
PLAIN git (subprocess) - only the module under test is restricted to
`runner_git.run`. Security tests pair each governed refusal/no-marker
assertion with a positive control proving the hostile configuration is
really active, so no assertion is vacuous.
"""

import ast
import dataclasses
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_git
from scripts.ai import runner_integration as ri
from scripts.ai import runner_pipeline as pipeline
from scripts.tests.test_runner_git import install_filter, install_hostile_config, modify_same_size, plain_git

REMOTE_URL = "https://example.invalid/quesada.git"
SCOPES = ("src",)
FEATURE = "feature/fcp-candidate"

# Isolate from the developer's global/system git config, for fixtures and
# for the module under test alike.
_ISOLATED_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _rmtree(path: Path) -> None:
    def onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def commit(repo: Path, message: str, files: dict = None) -> str:
    for rel, text in (files or {}).items():
        write(repo / rel, text)
        plain_git(repo, "add", "--", rel)
    plain_git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return head(repo)


def head(repo: Path, rev: str = "HEAD") -> str:
    return plain_git(repo, "rev-parse", rev).stdout.strip()


class Fixture:
    """`repo` (on develop) with origin/develop tracking ref and remote URL,
    plus a linked candidate worktree `wt` on FEATURE one commit ahead."""

    def __init__(self, root: Path):
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        plain_git(self.repo, "init", "-q", "-b", "develop")
        plain_git(self.repo, "config", "user.email", "fcp1b@example.invalid")
        plain_git(self.repo, "config", "user.name", "FCP1B Tests")
        plain_git(self.repo, "config", "remote.origin.url", REMOTE_URL)
        self.c0 = commit(self.repo, "c0", {"src/a.py": "a = 0\n", "docs/readme.md": "readme\n",
                                           "shared.txt": "shared\n"})
        self.c1 = commit(self.repo, "c1", {"docs/notes.md": "notes\n"})
        self.set_tracking(self.c1)
        self.wt = root / "wt"
        plain_git(self.repo, "worktree", "add", "-q", "-b", FEATURE, str(self.wt), self.c1)
        self.feature_head = commit(self.wt, "feature", {"src/a.py": "a = 1\n"})

    def set_tracking(self, sha: str) -> None:
        plain_git(self.repo, "update-ref", ri.TRACKING_REF, sha)

    def advance_base(self, files: dict) -> str:
        """A new develop commit, mirrored into the tracking ref (as a fetch
        would have done) and returned as the new attested SHA."""
        sha = commit(self.repo, "base advance", files)
        self.set_tracking(sha)
        return sha

    def add_worktree(self, name: str, branch: str, start: str) -> Path:
        path = self.root / name
        plain_git(self.repo, "worktree", "add", "-q", "-b", branch, str(path), start)
        return path


def good_evidence(fixture_or_worktree, **overrides) -> dict:
    """Director-shaped evidence bound to the fixture candidate or to the
    current HEAD/branch of the given worktree."""
    if isinstance(fixture_or_worktree, Fixture):
        sha, branch_ref = fixture_or_worktree.feature_head, f"refs/heads/{FEATURE}"
    else:
        sha = head(fixture_or_worktree)
        branch_ref = plain_git(fixture_or_worktree, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip()
    evidence = {
        "run_id": "run-1", "decision_code": "READY_FOR_HOST_AUDIT", "safety_verdict": "SAFE",
        "evidence_complete": True, "head_sha": sha, "branch_ref": branch_ref or f"refs/heads/{FEATURE}",
    }
    evidence.update(overrides)
    return evidence


class IntegrationTestCase(unittest.TestCase):
    def setUp(self):
        env_patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.root = Path(tempfile.mkdtemp(prefix="fcp1b-")).resolve()
        self.addCleanup(_rmtree, self.root)
        self.fx = Fixture(self.root)

    def assess(self, worktree=None, *, attested=None, scopes=SCOPES, evidence="default", **kwargs):
        worktree = worktree or self.fx.wt
        attested = self.fx.c1 if attested is None else attested
        if evidence == "default":
            evidence = good_evidence(Path(worktree))
        return ri.assess_integration(
            worktree, attested_sha=attested, authorized_scopes=scopes, evidence=evidence, **kwargs,
        )

    def assertClass(self, assessment, classification, reason=None):
        self.assertEqual(assessment.classification, classification, assessment.reason_codes)
        if reason is not None:
            self.assertIn(reason, assessment.reason_codes)
        self.assertIs(assessment.human_approval_required, True)
        self.assertEqual(assessment.eligible, classification == ri.ELIGIBLE_PENDING_APPROVAL)


# ---------------------------------------------------------------------------
# Canonical base
# ---------------------------------------------------------------------------

class CanonicalBaseTests(IntegrationTestCase):
    def test_verified_base(self):
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1, expected_remote_url=REMOTE_URL)
        self.assertEqual(base.status, ri.BASE_VERIFIED)
        self.assertTrue(base.verified)
        self.assertEqual(base.tracking_ref, "refs/remotes/origin/develop")
        self.assertEqual(base.tracking_sha, self.fx.c1)
        self.assertTrue(base.remote_url_matches)
        self.assertEqual(base.local_branch_relation, ri.RELATION_EQUAL)

    def test_missing_tracking_ref(self):
        plain_git(self.fx.repo, "update-ref", "-d", ri.TRACKING_REF)
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1)
        self.assertEqual(base.status, ri.BASE_MISSING)
        self.assertFalse(base.verified)
        self.assertIsNone(base.tracking_sha)

    def test_local_tracking_ref_behind_attested_is_stale(self):
        newer = commit(self.fx.repo, "remote moved on")  # object known locally, tracking ref not updated
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=newer)
        self.assertEqual(base.status, ri.BASE_STALE)
        self.assertFalse(base.verified)

    def test_attested_mismatch_unknown_or_diverged(self):
        unknown = ri.resolve_canonical_base(self.fx.wt, attested_sha="ab" * 20)
        self.assertEqual(unknown.status, ri.BASE_MISMATCHED)
        # The feature commit is a descendant, an unrelated sibling is not.
        plain_git(self.fx.repo, "branch", "sibling", self.fx.c0)
        sibling_wt = self.root / "sib"
        plain_git(self.fx.repo, "worktree", "add", "-q", str(sibling_wt), "sibling")
        sibling = commit(sibling_wt, "sibling")
        diverged = ri.resolve_canonical_base(self.fx.wt, attested_sha=sibling)
        self.assertEqual(diverged.status, ri.BASE_MISMATCHED)
        self.assertFalse(diverged.verified)

    def test_unattested_and_invalid_attestation(self):
        self.assertEqual(ri.resolve_canonical_base(self.fx.wt, attested_sha=None).status, ri.BASE_UNATTESTED)
        for bad in ("", "abc123", self.fx.c1[:12], self.fx.c1.upper(), self.fx.c1 + "0", " " + self.fx.c1):
            with self.subTest(bad=bad):
                base = ri.resolve_canonical_base(self.fx.wt, attested_sha=bad)
                self.assertEqual(base.status, ri.BASE_INVALID_ATTESTATION)
                self.assertFalse(base.verified)

    def test_short_name_ambiguity_fails_closed(self):
        for competitor in ("refs/heads/origin/develop", "refs/tags/origin/develop"):
            with self.subTest(competitor=competitor):
                plain_git(self.fx.repo, "update-ref", competitor, self.fx.c0)
                base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1)
                self.assertEqual(base.status, ri.BASE_AMBIGUOUS)
                self.assertIn(competitor, base.ambiguous_refs)
                # The fully-qualified ref is still what was resolved.
                self.assertEqual(base.tracking_sha, self.fx.c1)
                plain_git(self.fx.repo, "update-ref", "-d", competitor)
        # Positive control: the short name really is ambiguous to plain git.
        plain_git(self.fx.repo, "update-ref", "refs/heads/origin/develop", self.fx.c0)
        warn = plain_git(self.fx.repo, "rev-parse", "origin/develop")
        self.assertIn("ambiguous", warn.stderr)

    def test_symbolic_tracking_ref_is_not_trusted(self):
        plain_git(self.fx.repo, "symbolic-ref", ri.TRACKING_REF, "refs/heads/develop")
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1)
        self.assertEqual(base.status, ri.BASE_AMBIGUOUS)
        self.assertFalse(base.verified)

    def test_local_develop_is_informational_only(self):
        ahead = commit(self.fx.repo, "local only")
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1)
        self.assertEqual(base.status, ri.BASE_VERIFIED)
        self.assertEqual(base.local_branch_relation, ri.RELATION_AHEAD)
        self.assertEqual(base.local_branch_sha, ahead)
        self.assertEqual(base.tracking_sha, self.fx.c1)
        # Diverged: tracking moves to a sibling of local develop.
        plain_git(self.fx.repo, "branch", "remote-side", self.fx.c1)
        side_wt = self.root / "side"
        plain_git(self.fx.repo, "worktree", "add", "-q", str(side_wt), "remote-side")
        remote_side = commit(side_wt, "remote side")
        self.fx.set_tracking(remote_side)
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=remote_side)
        self.assertEqual(base.status, ri.BASE_VERIFIED)
        self.assertEqual(base.local_branch_relation, ri.RELATION_DIVERGED)
        self.assertEqual(base.tracking_sha, remote_side)

    def test_expected_remote_url_must_match_exactly(self):
        for expected in (REMOTE_URL + "/", REMOTE_URL.upper(), "https://example.invalid/other.git"):
            with self.subTest(expected=expected):
                base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1, expected_remote_url=expected)
                self.assertEqual(base.status, ri.BASE_REMOTE_URL_MISMATCH)
                self.assertFalse(base.remote_url_matches)
        plain_git(self.fx.repo, "config", "url.https://evil.invalid/.insteadOf", "https://example.invalid/")
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1, expected_remote_url=REMOTE_URL)
        self.assertEqual(base.status, ri.BASE_REMOTE_URL_MISMATCH)
        # Positive control: the rewrite really applies to the configured URL.
        self.assertIn("evil.invalid", plain_git(self.fx.repo, "ls-remote", "--get-url", "origin").stdout)

    def test_missing_remote_url_with_expectation(self):
        plain_git(self.fx.repo, "config", "--unset", "remote.origin.url")
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1, expected_remote_url=REMOTE_URL)
        self.assertEqual(base.status, ri.BASE_REMOTE_URL_MISMATCH)

    def test_results_are_immutable(self):
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            base.verified = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Candidate and classification
# ---------------------------------------------------------------------------

class CandidateClassificationTests(IntegrationTestCase):
    def test_valid_ahead_only_candidate_is_eligible_pending_approval(self):
        a = self.assess(expected_remote_url=REMOTE_URL)
        self.assertClass(a, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertEqual(a.reason_codes, ())
        c = a.candidate
        self.assertEqual((c.ahead, c.behind), (1, 0))
        self.assertEqual(c.merge_bases, (self.fx.c1,))
        self.assertEqual(c.head_ref, f"refs/heads/{FEATURE}")
        self.assertEqual(c.changed_paths, (("M", "src/a.py"),))
        self.assertEqual(c.authorized_changed_paths, ("src/a.py",))
        self.assertEqual(c.worktree_top, str(self.fx.wt.resolve()))
        self.assertNotEqual(c.git_dir, c.common_dir)
        self.assertTrue(c.lease_acquired)
        self.assertEqual(a.evidence.status, ri.EVIDENCE_BOUND)

    def test_nothing_to_integrate(self):
        empty = self.fx.add_worktree("empty", "feature/empty", self.fx.c1)
        self.assertClass(self.assess(empty), ri.NOTHING_TO_INTEGRATE, "NO_COMMITS_AHEAD")
        behind_only = self.fx.add_worktree("old", "feature/old", self.fx.c0)
        a = self.assess(behind_only)
        self.assertClass(a, ri.NOTHING_TO_INTEGRATE)
        self.assertEqual((a.candidate.ahead, a.candidate.behind), (0, 1))

    def test_behind_without_overlap_is_stale_base(self):
        new_base = self.fx.advance_base({"docs/readme.md": "readme v2\n"})
        a = self.assess(attested=new_base)
        self.assertClass(a, ri.STALE_BASE, "BASE_ADVANCED")
        self.assertEqual((a.candidate.ahead, a.candidate.behind), (1, 1))
        self.assertEqual(a.candidate.overlapping_paths, ())

    def test_behind_with_overlap_needs_reconciliation(self):
        new_base = self.fx.advance_base({"src/a.py": "a = 2\n"})
        a = self.assess(attested=new_base)
        self.assertClass(a, ri.NEEDS_RECONCILIATION, "OVERLAPPING_CHANGES")
        self.assertEqual(a.candidate.overlapping_paths, ("src/a.py",))

    def test_unrelated_histories(self):
        orphan = self.root / "orphan"
        plain_git(self.fx.repo, "worktree", "add", "-q", "--detach", str(orphan), self.fx.c1)
        plain_git(orphan, "checkout", "-q", "--orphan", "feature/orphan")
        plain_git(orphan, "rm", "-rqf", ".")
        commit(orphan, "orphan root", {"src/z.py": "z\n"})
        # Out of scope, the orphan's implicit deletions win by precedence.
        self.assertClass(self.assess(orphan), ri.UNAUTHORIZED_CHANGED_PATHS)
        a = self.assess(orphan, scopes=("src", "docs", "shared.txt"))
        self.assertClass(a, ri.NEEDS_RECONCILIATION, "UNRELATED_HISTORIES")
        self.assertEqual(a.candidate.merge_bases, ())

    def test_dirty_staged_and_untracked(self):
        write(self.fx.wt / "src" / "a.py", "a = 99\n")
        self.assertClass(self.assess(), ri.DIRTY_WORKTREE, "UNSTAGED_CHANGES")
        plain_git(self.fx.wt, "add", "src/a.py")
        a = self.assess()
        self.assertClass(a, ri.DIRTY_WORKTREE, "STAGED_CHANGES")
        self.assertEqual(a.candidate.staged_paths, ("src/a.py",))
        plain_git(self.fx.wt, "reset", "-q", "--hard")
        write(self.fx.wt / "src" / "new" / "b.py", "b\n")
        a = self.assess()
        self.assertClass(a, ri.DIRTY_WORKTREE, "UNTRACKED_FILES")
        self.assertEqual(a.candidate.untracked_paths, ("src/new/b.py",))
        self.assertFalse(a.candidate.clean)

    def test_protected_branch_and_detached_head(self):
        a = self.assess(self.fx.repo)  # the main checkout is on develop
        self.assertClass(a, ri.UNSAFE_WORKTREE, "PROTECTED_BRANCH")
        self.assertTrue(a.candidate.protected_branch)
        plain_git(self.fx.wt, "checkout", "-q", "--detach")
        a = self.assess()
        self.assertClass(a, ri.UNSAFE_WORKTREE, "DETACHED_HEAD")
        self.assertIsNone(a.candidate.head_ref)

    def test_unauthorized_paths(self):
        commit(self.fx.wt, "outside", {"docs/extra.md": "x\n"})
        a = self.assess()
        self.assertClass(a, ri.UNAUTHORIZED_CHANGED_PATHS, "UNAUTHORIZED_PATHS")
        self.assertEqual(a.candidate.unauthorized_changed_paths, ("docs/extra.md",))
        self.assertEqual(a.candidate.authorized_changed_paths, ("src/a.py",))

    def test_cross_scope_renames_are_deleted_plus_added(self):
        plain_git(self.fx.wt, "mv", "src/a.py", "docs/a.py")
        commit(self.fx.wt, "move out of scope")
        a = self.assess()
        self.assertClass(a, ri.UNAUTHORIZED_CHANGED_PATHS)
        self.assertIn(("D", "src/a.py"), a.candidate.changed_paths)
        self.assertIn(("A", "docs/a.py"), a.candidate.changed_paths)
        self.assertEqual(a.candidate.unauthorized_changed_paths, ("docs/a.py",))

        into = self.fx.add_worktree("into", "feature/into", self.fx.c1)
        plain_git(into, "mv", "docs/readme.md", "src/readme.md")
        commit(into, "move into scope")
        a = self.assess(into)
        self.assertClass(a, ri.UNAUTHORIZED_CHANGED_PATHS)
        self.assertEqual(a.candidate.unauthorized_changed_paths, ("docs/readme.md",))
        self.assertEqual(a.candidate.authorized_changed_paths, ("src/readme.md",))

    def test_invalid_or_missing_scope_fails_closed(self):
        for scopes in ((), ("../src",), ("/abs",)):
            with self.subTest(scopes=scopes):
                a = self.assess(scopes=scopes)
                self.assertClass(a, ri.UNAUTHORIZED_CHANGED_PATHS, "SCOPE_INVALID")
                self.assertEqual(a.candidate.unauthorized_changed_paths, ("src/a.py",))

    def test_unattested_base_blocks(self):
        a = ri.assess_integration(self.fx.wt, attested_sha=None, authorized_scopes=SCOPES,
                                  evidence=good_evidence(self.fx))
        self.assertClass(a, ri.BASE_UNVERIFIED, ri.BASE_UNATTESTED)

    def test_failed_git_read_fails_closed(self):
        not_repo = self.root / "plain"
        not_repo.mkdir()
        a = ri.assess_integration(not_repo, attested_sha=self.fx.c1, authorized_scopes=SCOPES)
        self.assertClass(a, ri.UNSAFE_WORKTREE, "GIT_READ_FAILED")
        self.assertEqual(a.base.status, ri.BASE_UNREADABLE)
        with mock.patch.object(ri, "_worktree_entries", side_effect=ri._GitReadError("git worktree list", "boom")):
            a = self.assess()
        self.assertClass(a, ri.UNSAFE_WORKTREE, "GIT_READ_FAILED")
        self.assertIn("boom", a.candidate.read_errors[0])


class TopologyHazardTests(IntegrationTestCase):
    def test_shallow_clone(self):
        shallow = self.root / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--no-local", "--branch", FEATURE,
             self.fx.repo.as_uri(), str(shallow)], check=True, capture_output=True,
        )
        plain_git(shallow, "update-ref", ri.TRACKING_REF, "HEAD")
        # Positive control: the clone really is shallow.
        self.assertEqual(plain_git(shallow, "rev-parse", "--is-shallow-repository").stdout.strip(), "true")
        a = self.assess(shallow, attested=head(shallow))
        self.assertClass(a, ri.UNSAFE_WORKTREE, "SHALLOW_REPOSITORY")
        self.assertEqual(a.base.status, ri.BASE_UNSAFE_REPOSITORY)
        self.assertEqual(a.candidate.merge_bases, ())

    def test_grafts(self):
        (self.fx.repo / ".git" / "info").mkdir(exist_ok=True)
        write(self.fx.repo / ".git" / "info" / "grafts", self.fx.feature_head + "\n")
        # Positive control: plain git honors the graft (history truncated).
        count = plain_git(self.fx.wt, "rev-list", "--count", "HEAD").stdout.strip()
        self.assertEqual(count, "1")
        a = self.assess()
        self.assertClass(a, ri.UNSAFE_WORKTREE, "GRAFTS_PRESENT")
        self.assertEqual(a.base.status, ri.BASE_UNSAFE_REPOSITORY)
        self.assertIsNone(a.candidate.ahead)

    def test_replace_refs(self):
        plain_git(self.fx.repo, "replace", self.fx.feature_head, self.fx.c0)
        # Positive control: plain git sees the replacement object.
        replaced = plain_git(self.fx.wt, "rev-parse", "HEAD^{tree}").stdout.strip()
        real = plain_git(self.fx.wt, "--no-replace-objects", "rev-parse", "HEAD^{tree}").stdout.strip()
        self.assertNotEqual(replaced, real)
        a = self.assess()
        self.assertClass(a, ri.UNSAFE_WORKTREE, "REPLACE_REFS_PRESENT")
        self.assertEqual(a.candidate.head_sha, self.fx.feature_head)
        self.assertEqual(a.candidate.replace_refs, (f"refs/replace/{self.fx.feature_head}",))

    def test_partial_clone_configuration(self):
        plain_git(self.fx.repo, "config", "remote.origin.promisor", "true")
        a = self.assess()
        self.assertClass(a, ri.UNSAFE_WORKTREE, "PARTIAL_CLONE")
        self.assertEqual(a.base.status, ri.BASE_UNSAFE_REPOSITORY)


class OwnershipTests(IntegrationTestCase):
    def test_duplicate_branch_checkout(self):
        dup = self.root / "dup"
        plain_git(self.fx.repo, "worktree", "add", "-q", "--force", str(dup), FEATURE)
        a = self.assess()
        self.assertClass(a, ri.OWNERSHIP_CONFLICT, "DUPLICATE_BRANCH_CHECKOUT")
        self.assertEqual(a.candidate.duplicate_checkouts, (str(dup),))

    def _assert_competing_lease(self, lease_root=None):
        competitor = pipeline.DirLease(pipeline.worktree_lease_dir(self.fx.wt.resolve(), lease_root))
        self.assertTrue(competitor.try_acquire({"pipeline_id": "other", "worker_id": "w", "pid": 1}))
        try:
            a = self.assess(lease_root=lease_root)
            self.assertClass(a, ri.OWNERSHIP_CONFLICT, "WORKTREE_LEASE_HELD")
            self.assertIn(("pipeline_id", "other"), a.candidate.lease_holder)
            self.assertFalse(a.candidate.lease_acquired)
            # The competitor's identity is untouched by the refused attempt.
            self.assertEqual(competitor.holder()["pipeline_id"], "other")
        finally:
            competitor.release()
        self.assertClass(self.assess(lease_root=lease_root), ri.ELIGIBLE_PENDING_APPROVAL)

    def test_competing_worktree_lease_in_git_dir(self):
        self._assert_competing_lease()

    def test_competing_worktree_lease_under_lease_root(self):
        lease_root = self.root / "leases"
        self._assert_competing_lease(lease_root)
        a = self.assess(lease_root=lease_root)
        self.assertEqual(Path(a.candidate.lease_dir).parent, lease_root)

    def test_lease_is_held_during_inspection_and_released(self):
        seen = {}
        original = ri._collect_details

        def probing(repo, identity, base, facts, scopes):
            probe = pipeline.DirLease(Path(facts["lease_dir"]))
            seen["acquirable"] = probe.try_acquire({"pid": 0})
            probe.release()
            seen["holder"] = probe.holder()
            return original(repo, identity, base, facts, scopes)

        with mock.patch.object(ri, "_collect_details", probing):
            a = self.assess()
        self.assertFalse(seen["acquirable"])
        self.assertEqual(seen["holder"]["purpose"], "INTEGRATION_ASSESSMENT")
        lease_dir = Path(a.candidate.lease_dir)
        self.assertFalse((lease_dir / pipeline.DirLease.IDENTITY).exists())
        probe = pipeline.DirLease(lease_dir)
        self.assertTrue(probe.try_acquire({"pid": 0}))
        probe.release()

    def test_active_worker_from_factory_ledger(self):
        ledger_root = self.root / "factory"
        ledger = flog.FactoryLedger(ledger_root)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        a = self.assess(ledger_root=ledger_root)
        self.assertClass(a, ri.OWNERSHIP_CONFLICT, "ACTIVE_WORKER")
        self.assertEqual(a.candidate.active_workers, (("p1", "w1"),))
        ledger.append(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        a = self.assess(ledger_root=ledger_root)
        self.assertClass(a, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertTrue(a.candidate.ledger_checked)
        # An unrelated worktree's worker never blocks.
        ledger.append(flog.WORKER_STARTED, pipeline_id="p2", worker_id="w2", worktree=str(self.root / "else"))
        self.assertClass(self.assess(ledger_root=ledger_root), ri.ELIGIBLE_PENDING_APPROVAL)

    def test_unreadable_ledger_fails_closed(self):
        self.assertClass(self.assess(ledger_root=self.root / "absent"), ri.OWNERSHIP_CONFLICT, "LEDGER_UNREADABLE")
        corrupt = self.root / "corrupt"
        corrupt.mkdir()
        write(corrupt / flog.EVENTS_FILENAME, "{not json\n")
        self.assertClass(self.assess(ledger_root=corrupt), ri.OWNERSHIP_CONFLICT, "LEDGER_UNREADABLE")


class EvidenceTests(IntegrationTestCase):
    def test_missing_evidence(self):
        a = self.assess(evidence=None)
        self.assertClass(a, ri.EVIDENCE_MISSING, "EVIDENCE_MISSING")
        self.assertEqual(a.evidence.status, ri.EVIDENCE_MISSING_STATUS)

    def test_invalid_evidence(self):
        cases = {
            "EVIDENCE_NOT_READY_FOR_HOST_AUDIT": {"decision_code": "SAFETY_REVIEW_REQUIRED"},
            "EVIDENCE_NOT_SAFE": {"safety_verdict": "FAILED_SAFETY"},
            "EVIDENCE_INCOMPLETE": {"evidence_complete": None},
            "EVIDENCE_HEAD_INVALID": {"head_sha": "HEAD"},
            "EVIDENCE_BRANCH_REF_INVALID": {"branch_ref": FEATURE},
            "EVIDENCE_RUN_ID_INVALID": {"run_id": 7},
        }
        for reason, override in cases.items():
            with self.subTest(reason=reason):
                a = self.assess(evidence=good_evidence(self.fx, **override))
                self.assertClass(a, ri.EVIDENCE_MISSING, reason)
                self.assertEqual(a.evidence.status, ri.EVIDENCE_INVALID)
        self.assertEqual(self.assess(evidence=["not", "a", "mapping"]).evidence.status, ri.EVIDENCE_INVALID)

    def test_stale_evidence(self):
        cases = {
            "EVIDENCE_HEAD_MISMATCH": {"head_sha": self.fx.c1},
            "EVIDENCE_BRANCH_MISMATCH": {"branch_ref": "refs/heads/feature/other"},
            "EVIDENCE_WORKTREE_MISMATCH": {"worktree": str(self.fx.repo)},
        }
        for reason, override in cases.items():
            with self.subTest(reason=reason):
                a = self.assess(evidence=good_evidence(self.fx, **override))
                self.assertClass(a, ri.EVIDENCE_MISSING, reason)
                self.assertEqual(a.evidence.status, ri.EVIDENCE_STALE)
        a = self.assess(evidence=good_evidence(self.fx, worktree=str(self.fx.wt)))
        self.assertClass(a, ri.ELIGIBLE_PENDING_APPROVAL)


class PrecedenceAndFingerprintTests(IntegrationTestCase):
    def test_fixed_classification_precedence(self):
        eligible = self.assess()
        self.assertClass(eligible, ri.ELIGIBLE_PENDING_APPROVAL)
        unverified = dataclasses.replace(eligible.base, status=ri.BASE_UNATTESTED, verified=False,
                                         reason_codes=(ri.BASE_UNATTESTED,))
        # (classification, base override, candidate overrides, drop evidence)
        # from highest to lowest precedence. Layer N is injected together with
        # EVERY lower-precedence fault, and must still win.
        layers = [
            (ri.UNSAFE_WORKTREE, None, {"detached": True}, False),
            (ri.OWNERSHIP_CONFLICT, None, {"duplicate_checkouts": ("x",)}, False),
            (ri.DIRTY_WORKTREE, None, {"untracked_paths": ("u",)}, False),
            (ri.BASE_UNVERIFIED, unverified, {}, False),
            (ri.DRIFT_DURING_ASSESSMENT, None, {"drift_reasons": ("HEAD_DRIFT",)}, False),
            (ri.UNAUTHORIZED_CHANGED_PATHS, None, {"unauthorized_changed_paths": ("docs/x",)}, False),
            (ri.EVIDENCE_MISSING, None, {}, True),
            (ri.NOTHING_TO_INTEGRATE, None, {"ahead": 0}, False),
            (ri.NEEDS_RECONCILIATION, None, {"behind": 1, "overlapping_paths": ("src/a.py",)}, False),
            (ri.STALE_BASE, None, {"behind": 1}, False),
        ]
        good = good_evidence(self.fx)
        for depth, (expected, *_rest) in enumerate(layers):
            base, fields, evidence = eligible.base, {}, good
            for _name, layer_base, overrides, drop_evidence in reversed(layers[depth:]):
                base = layer_base or base
                fields.update(overrides)  # higher-precedence layers applied last
                if drop_evidence:
                    evidence = None
            a = ri.classify_integration(base, dataclasses.replace(eligible.candidate, **fields), evidence)
            with self.subTest(expected=expected):
                self.assertClass(a, expected)
                self.assertFalse(a.eligible)
        review = ri.classify_integration(eligible.base, dataclasses.replace(eligible.candidate, ahead=None), good)
        self.assertClass(review, ri.REVIEW_REQUIRED, "UNKNOWN_RELATION")

    def test_only_eligible_is_eligible_and_approval_always_required(self):
        a = self.assess()
        self.assertTrue(a.eligible)
        self.assertTrue(a.human_approval_required)
        for classification, candidate in (
            (ri.DIRTY_WORKTREE, dataclasses.replace(a.candidate, staged_paths=("s",))),
            (ri.STALE_BASE, dataclasses.replace(a.candidate, behind=2)),
        ):
            other = ri.classify_integration(a.base, candidate, good_evidence(self.fx))
            self.assertEqual(other.classification, classification)
            self.assertFalse(other.eligible)
            self.assertTrue(other.human_approval_required)

    def test_stable_deterministic_fingerprint(self):
        first, second = self.assess(), self.assess()
        self.assertRegex(first.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(first.fingerprint, second.fingerprint)
        # Lease root (a run-time choice, not a trusted input) is excluded.
        self.assertEqual(first.fingerprint, self.assess(lease_root=self.root / "leases").fingerprint)
        self.assertNotEqual(first.fingerprint, self.assess(scopes=("src", "docs")).fingerprint)
        commit(self.fx.wt, "more", {"src/b.py": "b\n"})
        self.assertNotEqual(first.fingerprint, self.assess().fingerprint)


class DriftTests(IntegrationTestCase):
    def _assess_with_midway(self, action):
        original = ri._collect_details

        def mutating(*args):
            action()
            return original(*args)

        with mock.patch.object(ri, "_collect_details", mutating):
            return self.assess()

    def test_head_drift(self):
        a = self._assess_with_midway(lambda: commit(self.fx.wt, "concurrent"))
        self.assertClass(a, ri.DRIFT_DURING_ASSESSMENT, "HEAD_DRIFT")

    def test_base_ref_drift(self):
        a = self._assess_with_midway(lambda: self.fx.set_tracking(self.fx.c0))
        self.assertClass(a, ri.DRIFT_DURING_ASSESSMENT, "BASE_REF_DRIFT")

    def test_base_moved_between_resolution_and_inspection(self):
        base = ri.resolve_canonical_base(self.fx.wt, attested_sha=self.fx.c1)
        self.fx.advance_base({"docs/late.md": "late\n"})
        candidate = ri.inspect_candidate(self.fx.wt, base, authorized_scopes=SCOPES)
        a = ri.classify_integration(base, candidate, good_evidence(self.fx))
        self.assertClass(a, ri.DRIFT_DURING_ASSESSMENT, "BASE_REF_DRIFT")

    def test_status_drift(self):
        a = self._assess_with_midway(lambda: write(self.fx.wt / "late.txt", "x\n"))
        self.assertIn("STATUS_DRIFT", a.reason_codes)
        self.assertNotEqual(a.classification, ri.ELIGIBLE_PENDING_APPROVAL)


# ---------------------------------------------------------------------------
# Security and non-mutation
# ---------------------------------------------------------------------------

def _git_dir_state(paths) -> dict:
    """Byte-level state of HEAD/index/refs/packed-refs/config in each git
    dir, plus tracked files of each worktree."""
    state = {}
    for path in paths:
        path = Path(path)
        for f in sorted(path.rglob("*")):
            if f.is_file() and (f.name in ("HEAD", "index", "packed-refs", "config", "ORIG_HEAD")
                                or "refs" in f.relative_to(path).parts or "logs" in f.relative_to(path).parts):
                st = f.stat()
                state[str(f)] = (f.read_bytes(), st.st_mtime_ns)
    return state


class SecurityAndReadOnlyTests(IntegrationTestCase):
    def test_no_hooks_fsmonitor_or_external_diff_run(self):
        markers = install_hostile_config(self.fx.repo, self.root, ext_diff=True)
        for _ in range(2):
            plain_git(self.fx.wt, "status", "--porcelain=v1")
        for marker in markers.iterdir():
            marker.unlink()
        new_base = self.fx.advance_base({"docs/readme.md": "v2\n"})  # exercises both diffs
        for marker in markers.iterdir():
            marker.unlink()
        a = self.assess(attested=new_base)
        self.assertClass(a, ri.STALE_BASE)
        self.assertEqual(sorted(m.name for m in markers.iterdir()), [])
        # Positive controls: the same repository really runs them in plain git.
        plain_git(self.fx.wt, "status", "--porcelain=v1")
        plain_git(self.fx.wt, "diff", self.fx.c1, "HEAD")
        plain_git(self.fx.wt, "hook", "run", "--ignore-missing", "post-index-change")
        fired = {m.name for m in markers.iterdir()}
        self.assertTrue({"fsmonitor", "ext-diff", "hook-post-index-change"} <= fired, fired)

    def test_content_filter_is_refused_not_run(self):
        markers = install_filter(self.fx.wt, self.root)
        modify_same_size(self.fx.wt / "tracked.dat")
        a = self.assess()
        self.assertClass(a, ri.UNSAFE_WORKTREE, "GIT_READ_FAILED")
        self.assertIn(runner_git.REFUSED_PREFIX.strip(), " ".join(a.candidate.read_errors))
        self.assertEqual(list(markers.iterdir()), [])
        # Positive control: plain git status runs the clean filter.
        plain_git(self.fx.wt, "status", "--porcelain=v1")
        self.assertTrue((markers / "filter-evil-clean").exists())

    def test_only_governed_read_only_git_subcommands(self):
        calls = []
        real_run = runner_git.subprocess.run

        def recording(cmd, *args, **kwargs):
            calls.append((list(cmd), dict(kwargs.get("env") or {})))
            return real_run(cmd, *args, **kwargs)

        new_base = self.fx.advance_base({"docs/readme.md": "v2\n"})
        evidence = good_evidence(self.fx)  # computed with plain git BEFORE recording starts
        with mock.patch.object(runner_git.subprocess, "run", recording):
            a = self.assess(attested=new_base, expected_remote_url=REMOTE_URL, ledger_root=self.root,
                            evidence=evidence)
        self.assertClass(a, ri.STALE_BASE)
        allowed = ri._READ_SUBCOMMANDS | {"ls-files", "check-attr"}
        forbidden = {"fetch", "pull", "push", "ls-remote", "remote", "clone", "commit", "merge", "rebase",
                     "reset", "checkout", "switch", "update-ref", "update-index", "gc", "prune", "add",
                     "stash", "restore", "branch", "tag", "replace", "maintenance"}
        self.assertGreater(len(calls), 10)
        for cmd, env in calls:
            self.assertEqual(cmd[:2], ["git", "-C"])
            rest = cmd[3:]
            sub = rest[runner_git._subcommand_index(rest):]
            with self.subTest(cmd=sub[:3]):
                self.assertIn(sub[0], allowed)
                self.assertNotIn(sub[0], forbidden)
                if sub[0] == "worktree":
                    self.assertEqual(sub[1], "list")
                if sub[:2] != ["rev-parse", "--absolute-git-dir"]:  # Runner's own lease-dir lookup
                    self.assertIn("--no-replace-objects", rest)
                    self.assertEqual(env.get("GIT_OPTIONAL_LOCKS"), "0")
                    self.assertEqual(env.get("GIT_NO_LAZY_FETCH"), "1")
                for entry in runner_git.HARDENING_CONFIG:
                    self.assertIn(entry, rest)

    def test_module_never_imports_subprocess_or_mutating_git(self):
        source = Path(ri.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names} | {node.module for node in ast.walk(tree)
                                                if isinstance(node, ast.ImportFrom) and node.module}
        self.assertNotIn("subprocess", imported)
        self.assertNotIn("subprocess.", source.replace("never import subprocess", ""))
        for bad in (("fetch",), ("update-ref",), ("worktree", "add")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ri._git(self.fx.wt, *bad)

    def test_git_option_syntax_is_supported(self):
        for args in (
            ["--no-replace-objects", "rev-parse", "--path-format=absolute", "--git-common-dir",
             "--is-shallow-repository", "--show-object-format"],
            ["--no-replace-objects", "worktree", "list", "--porcelain", "-z"],
            ["--no-replace-objects", "for-each-ref", "--format=%(refname)%00%(objecttype)%00%(symref)"],
            ["--no-replace-objects", "diff", "--name-status", "-z", "--no-renames", "--no-relative",
             "--ignore-submodules=none", self.fx.c1, "HEAD", "--"],
            ["--no-replace-objects", "status", "--porcelain=v1", "--branch", "--untracked-files=all",
             "--ignore-submodules=none"],
        ):
            with self.subTest(args=args[1:3]):
                self.assertEqual(plain_git(self.fx.wt, *args, check=False).returncode, 0)

    def test_assessment_modifies_nothing_but_transient_lease(self):
        # Make the index stat-dirty so an unguarded `git status` would rewrite it.
        os.utime(self.fx.wt / "src" / "a.py", None)
        wt_git_dir = Path(plain_git(self.fx.wt, "rev-parse", "--absolute-git-dir").stdout.strip())
        tracked = {p: p.read_bytes() for p in (self.fx.wt / "src" / "a.py", self.fx.wt / "shared.txt")}
        before_state = _git_dir_state([self.fx.repo / ".git"])
        before_refs = plain_git(self.fx.repo, "for-each-ref").stdout
        before_listing = set(os.listdir(wt_git_dir))

        a = self.assess()
        self.assertClass(a, ri.ELIGIBLE_PENDING_APPROVAL)

        self.assertEqual(_git_dir_state([self.fx.repo / ".git"]), before_state)
        self.assertEqual(plain_git(self.fx.repo, "for-each-ref").stdout, before_refs)
        self.assertEqual({p: p.read_bytes() for p in tracked}, tracked)
        self.assertEqual(head(self.fx.wt), self.fx.feature_head)
        self.assertEqual(set(os.listdir(wt_git_dir)) - before_listing, {pipeline.WRITE_LEASE_DIRNAME})
        lease_dir = wt_git_dir / pipeline.WRITE_LEASE_DIRNAME
        self.assertFalse((lease_dir / pipeline.DirLease.IDENTITY).exists())
        self.assertEqual(plain_git(self.fx.wt, "status", "--porcelain=v1").stdout, "")


if __name__ == "__main__":
    unittest.main()
