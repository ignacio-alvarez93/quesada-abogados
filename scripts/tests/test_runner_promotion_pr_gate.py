"""FCP-3B-2A: read-only GitHub PR promotion gate.

The intent and the fresh validation are REAL FCP-3B-1 objects built from a
throwaway repository through the existing FCP-1/FCP-2B/FCP-3A fixtures
(plain git for fixture construction only). PR facts are provider-neutral
snapshots built here; the gate reads nothing itself except, in host mode,
one FCP-3B-1 revalidation and one call per method of a fake provider. Every
negative test starts from the complete positive fixture and alters one fact.
"""

import ast
import dataclasses
import inspect
import json
import os
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_integration as ri
from scripts.ai import runner_promotion as rp
from scripts.ai import runner_promotion_authorization as rpa
from scripts.ai import runner_promotion_pr_gate as rpg
from scripts.ai import runner_reconciliation as rr
from scripts.tests.test_runner_integration import _ISOLATED_ENV, _git_dir_state, _rmtree, good_evidence
from scripts.tests.test_runner_promotion import PromotionTestCase
from scripts.tests.test_runner_reconciliation import SCOPES, Fixture, text

MODULE_PATH = Path(rpg.__file__)
WORKFLOW_PATH = MODULE_PATH.parents[2] / ".github" / "workflows" / "fabric-ci.yml"
FF = rpa.FAST_FORWARD_CANDIDATE_TO_DEVELOP
PR = 42
REPO = rpg.CANONICAL_REPOSITORY
JOBS = rpg.REQUIRED_CI_JOBS
RUN_ID = 9001
SHA_A = "a" * 40
_DEFAULT = object()

RESULT_FIELDS = (
    "classification", "candidate_reviewable", "reason_codes", "fingerprint", "mode", "context",
    "snapshot_fingerprint", "changed_path_count", "out_of_scope_path_count", "check_run_count", "required_checks",
    "satisfied_checks", "ci_workflow_run_id", "policy_proven", "source_freshness_proven", "source_authenticated",
    "human_decision_present", "human_approval_required", "authorizes_action", "execution_allowed", "schema",
)
CONTEXT_FIELDS = (
    "repository", "pr_number", "base_ref", "base_sha", "head_ref", "head_sha", "authorized_scopes",
    "intent_fingerprint", "validation_fingerprint", "fingerprint", "schema",
)


class _Str(str):
    """A str subclass that lies about equality."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


class _Truthy:
    """An object claiming every flag."""

    approved = merged = complete = valid = True

    def __bool__(self):
        return True

    def __eq__(self, other):
        return True

    __hash__ = object.__hash__


def reforged(value, fingerprint_fn, **changes):
    draft = dataclasses.replace(value, **changes)
    return dataclasses.replace(draft, fingerprint=fingerprint_fn(draft))


# ---------------------------------------------------------------------------
# Snapshot builders (complete, consistent defaults)
# ---------------------------------------------------------------------------

def pr_meta(intent, **changes):
    return dataclasses.replace(rpg.PullRequestMetadata(
        repository=REPO, number=PR, state="open", merged=False, draft=False, base_repository=REPO,
        base_ref="develop", base_sha=intent.base_sha, head_repository=REPO,
        head_ref=intent.head_ref[len("refs/heads/"):], head_sha=intent.head_sha, base_branch_sha=intent.base_sha,
        changed_files=1,
    ), **changes)


def file_listing(*files, **changes):
    files = files or (rpg.ChangedFile("src/a.py", "modified"),)
    return dataclasses.replace(rpg.ChangedFileListing(
        files=tuple(files), reported_total=len(files), page_size=100, pages_fetched=max(1, -(-len(files) // 100)),
        complete=True,
    ), **changes)


def check_run(intent, job, index=0, **changes):
    return dataclasses.replace(rpg.CheckRun(
        name=job, check_run_id=100 + index, head_sha=intent.head_sha, status="completed", conclusion="success",
        app_slug="github-actions", workflow_name="Fabric CI", workflow_path=".github/workflows/fabric-ci.yml",
        workflow_run_id=RUN_ID, event="pull_request", pull_request_numbers=(PR,),
    ), **changes)


def branch_policy(**changes):
    return dataclasses.replace(rpg.BranchPolicy(
        base_ref="develop", rule_types=("pull_request", "required_status_checks"), required_check_names=JOBS,
        complete=True,
    ), **changes)


def check_listing(intent, runs=None, policy=_DEFAULT, **changes):
    runs = tuple(check_run(intent, n, i) for i, n in enumerate(JOBS)) if runs is None else tuple(runs)
    return dataclasses.replace(rpg.RequiredCheckListing(
        policy=branch_policy() if policy is _DEFAULT else policy, runs=runs, reported_total=len(runs), complete=True,
    ), **changes)


def snapshot(intent, pr=_DEFAULT, files=_DEFAULT, checks=_DEFAULT):
    return rpg.PullRequestSnapshot(
        pull_request=pr_meta(intent) if pr is _DEFAULT else pr,
        changed_files=file_listing() if files is _DEFAULT else files,
        checks=check_listing(intent) if checks is _DEFAULT else checks,
    )


class FakeProvider:
    """Records every call; returns the configured values or raises."""

    def __init__(self, pr, files, checks, fail=None):
        self.values = {"read_pull_request": pr, "read_changed_files": files, "read_required_checks": checks}
        self.fail = fail
        self.calls = []

    def _answer(self, method, *args):
        self.calls.append((method, args))
        if method == self.fail:
            raise RuntimeError("provider-secret-token-xyz")
        return self.values[method]

    def read_pull_request(self, repository, number):
        return self._answer("read_pull_request", repository, number)

    def read_changed_files(self, repository, number):
        return self._answer("read_changed_files", repository, number)

    def read_required_checks(self, repository, base_ref, head_sha):
        return self._answer("read_required_checks", repository, base_ref, head_sha)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class GateAssertions:
    def assertNeverAuthorizes(self, r):
        self.assertIs(type(r), rpg.PrGateResult)
        self.assertIn(r.classification, rpg.CLASSIFICATIONS)
        self.assertIs(r.human_approval_required, True)
        self.assertIs(r.authorizes_action, False)
        self.assertIs(r.execution_allowed, False)
        self.assertIs(r.source_authenticated, False)
        self.assertIs(r.human_decision_present, False)
        self.assertEqual(r.schema, rpg.RESULT_SCHEMA)
        self.assertRegex(r.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(r.fingerprint, rpg.result_fingerprint(r))
        for code in (rpg.PR_GATE_SOURCE_NOT_AUTHENTICATED, rpg.PR_GATE_HUMAN_DECISION_MISSING,
                     rpg.PR_GATE_HUMAN_APPROVAL_REQUIRED, rpg.PR_GATE_NOT_MERGE_READINESS,
                     rpg.PR_GATE_NOT_AUTHORIZATION):
            self.assertIn(code, r.reason_codes)
        self.assertEqual(len(r.reason_codes), len(set(r.reason_codes)))
        self.assertTrue(all(type(c) is str and c.startswith(("PR_GATE_", "INTENT_")) for c in r.reason_codes))
        if r.context is not None:
            self.assertIs(type(r.context), rpg.PrGateContext)
            self.assertEqual(r.context.fingerprint, rpg.context_fingerprint(r.context))
        json.dumps(dataclasses.asdict(r))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.authorizes_action = True  # type: ignore[misc]
        return r

    def assertRejected(self, r, *codes):
        self.assertNeverAuthorizes(r)
        self.assertEqual(r.classification, rpg.REJECTED, r.reason_codes)
        self.assertIs(r.candidate_reviewable, False)
        self.assertNotIn(rpg.PR_GATE_METADATA_CONSISTENT, r.reason_codes)
        for code in codes:
            self.assertIn(code, r.reason_codes)
        return r

    def assertReviewable(self, r, classification=rpg.REVIEWABLE_UNVERIFIED_SNAPSHOT):
        self.assertNeverAuthorizes(r)
        self.assertEqual(r.classification, classification, r.reason_codes)
        self.assertIs(r.candidate_reviewable, True)
        self.assertIn(rpg.PR_GATE_METADATA_CONSISTENT, r.reason_codes)
        self.assertIs(r.policy_proven, True)
        return r


class SharedGateFixture(GateAssertions, unittest.TestCase):
    """One real intent and one real FRESH_FCP3A_READ validation per class."""

    @classmethod
    def setUpClass(cls):
        env = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env.start()
        cls.addClassCleanup(env.stop)
        cls.root = Path(tempfile.mkdtemp(prefix="fcp3b2a-")).resolve()
        cls.addClassCleanup(_rmtree, cls.root)
        cls.fx = Fixture(cls.root)
        cls.fx.head_commit({"src/a.py": text({2: "head\n"})})
        cls.ledger = cls.root / "factory"
        cls.ledger.mkdir()
        cls.kw = dict(attested_sha=cls.fx.base, authorized_scopes=SCOPES, ledger_root=cls.ledger,
                      evidence=good_evidence(cls.fx.wt))
        cls.readiness = rp.assess_promotion_readiness(cls.fx.wt, **cls.kw)
        cls.intent = rpa.prepare_promotion_intent(cls.readiness, proposed_action=FF, authorized_scopes=SCOPES)
        cls.validation = rpa.revalidate_promotion_intent(cls.intent, cls.fx.wt, **cls.kw)

    def setUp(self):
        self.assertEqual(self.readiness.classification, rp.AWAITING_HUMAN_APPROVAL, self.readiness.reason_codes)
        self.assertIs(self.validation.valid, True, self.validation.reason_codes)
        self.assertEqual(self.validation.mode, rpa.MODE_FRESH_FCP3A_READ)

    def gate(self, snap=_DEFAULT, *, intent=_DEFAULT, validation=_DEFAULT, pr_number=PR):
        intent = self.intent if intent is _DEFAULT else intent
        return rpg.evaluate_pr_gate(intent, self.validation if validation is _DEFAULT else validation,
                                    snapshot(self.intent) if snap is _DEFAULT else snap, pr_number=pr_number)

    def with_pr(self, **changes):
        return self.gate(snapshot(self.intent, pr=pr_meta(self.intent, **changes)))

    def with_files(self, *files, **changes):
        listing = file_listing(*files, **changes)
        return self.gate(snapshot(self.intent, pr=pr_meta(self.intent, changed_files=len(listing.files)),
                                  files=listing))

    def with_runs(self, runs, **changes):
        return self.gate(snapshot(self.intent, checks=check_listing(self.intent, runs, **changes)))

    def runs(self, **per_name):
        """The five good runs; `per_name[job index]` = changes for that run."""
        return [check_run(self.intent, n, i, **per_name.get(f"j{i}", {})) for i, n in enumerate(JOBS)]


# ---------------------------------------------------------------------------
# Positive (pure)
# ---------------------------------------------------------------------------

class PositiveTests(SharedGateFixture):
    def test_complete_pinned_pr_is_reviewable_but_never_authorizing(self):
        r = self.assertReviewable(self.gate())
        self.assertEqual(r.mode, rpg.MODE_SUPPLIED_SNAPSHOT)
        self.assertEqual(r.reason_codes, (
            rpg.PR_GATE_METADATA_CONSISTENT, rpg.PR_GATE_SOURCE_FRESHNESS_NOT_PROVEN,
            rpg.PR_GATE_VALIDATION_PROVENANCE_NOT_PROVEN, rpg.PR_GATE_SOURCE_NOT_AUTHENTICATED,
            rpg.PR_GATE_HUMAN_DECISION_MISSING, rpg.PR_GATE_HUMAN_APPROVAL_REQUIRED, rpg.PR_GATE_NOT_MERGE_READINESS,
            rpg.PR_GATE_NOT_AUTHORIZATION))
        self.assertIs(r.source_freshness_proven, False)
        c = r.context
        self.assertEqual((c.repository, c.pr_number, c.base_ref), (REPO, PR, "develop"))
        self.assertEqual((c.base_sha, c.head_sha), (self.intent.base_sha, self.intent.head_sha))
        self.assertEqual(c.head_ref, "feature/fcp2b")
        self.assertEqual(c.authorized_scopes, SCOPES)
        self.assertEqual((c.intent_fingerprint, c.validation_fingerprint),
                         (self.intent.fingerprint, self.validation.fingerprint))
        self.assertEqual((r.changed_path_count, r.out_of_scope_path_count, r.check_run_count), (1, 0, len(JOBS)))
        self.assertEqual((r.required_checks, r.satisfied_checks, r.ci_workflow_run_id), (JOBS, JOBS, RUN_ID))
        self.assertEqual(r.snapshot_fingerprint, rpg.snapshot_fingerprint(snapshot(self.intent)))

    def test_deterministic_and_serializable(self):
        a, b = self.gate(), self.gate()
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(dataclasses.asdict(a), sort_keys=True),
                         json.dumps(dataclasses.asdict(b), sort_keys=True))
        self.assertNotEqual(self.gate(pr_number=43).fingerprint, a.fingerprint)

    def test_unrelated_extra_checks_and_files_in_scope_are_counted(self):
        runs = self.runs() + [check_run(self.intent, "lint", 9, app_slug="other-app", workflow_name=None,
                                        workflow_path=None, workflow_run_id=None, event=None, conclusion="failure")]
        r = self.assertReviewable(self.with_runs(runs))
        self.assertEqual((r.check_run_count, r.satisfied_checks), (len(JOBS) + 1, JOBS))
        files = (rpg.ChangedFile("src/a.py", "modified"), rpg.ChangedFile("src/new.py", "added"),
                 rpg.ChangedFile("src/gone.py", "removed"), rpg.ChangedFile("src/b.py", "renamed", "src/old.py"),
                 rpg.ChangedFile("src/c.py", "copied", "src/a.py"), rpg.ChangedFile("src/año.py", "added"))
        r = self.assertReviewable(self.with_files(*files))
        self.assertEqual((r.changed_path_count, r.out_of_scope_path_count), (6, 0))

    def test_policy_extra_required_check_must_be_satisfied(self):
        policy = branch_policy(required_check_names=JOBS + ("security / scan",))
        extra = check_run(self.intent, "security / scan", 7, app_slug="scanner", workflow_name=None,
                          workflow_path=None, workflow_run_id=None, event=None)
        r = self.assertReviewable(self.gate(snapshot(self.intent, checks=check_listing(
            self.intent, self.runs() + [extra], policy=policy))))
        self.assertEqual(r.required_checks, JOBS + ("security / scan",))
        self.assertEqual(r.satisfied_checks, JOBS + ("security / scan",))
        for runs, code in ((self.runs(), rpg.PR_GATE_CHECK_MISSING),
                           (self.runs() + [dataclasses.replace(extra, conclusion="failure")], rpg.PR_GATE_CHECK_FAILED)):
            with self.subTest(code=code):
                r = self.assertRejected(self.gate(snapshot(self.intent, checks=check_listing(
                    self.intent, runs, policy=policy))), code)
                self.assertNotIn("security / scan", r.satisfied_checks)


# ---------------------------------------------------------------------------
# PR identity and state
# ---------------------------------------------------------------------------

class PullRequestTests(SharedGateFixture):
    def test_wrong_identity_or_state(self):
        i = self.intent
        cases = (
            (dict(head_ref="feature/other"), rpg.PR_GATE_HEAD_REF_MISMATCH),
            (dict(head_ref="refs/heads/feature/fcp2b"), rpg.PR_GATE_HEAD_REF_MISMATCH),
            (dict(base_ref="main"), rpg.PR_GATE_BASE_REF_INVALID),
            (dict(base_ref="refs/heads/develop"), rpg.PR_GATE_BASE_REF_INVALID),
            (dict(head_sha=SHA_A), rpg.PR_GATE_STALE_HEAD),            # changed after the intent
            (dict(base_sha=SHA_A), rpg.PR_GATE_STALE_BASE),
            (dict(base_branch_sha=SHA_A), rpg.PR_GATE_STALE_BASE),     # develop moved
            (dict(repository="someone/quesada-abogados"), rpg.PR_GATE_REPOSITORY_MISMATCH),
            (dict(repository="Ignacio-Alvarez93/Quesada-Abogados"), rpg.PR_GATE_REPOSITORY_MISMATCH),
            (dict(base_repository="someone/quesada-abogados"), rpg.PR_GATE_REPOSITORY_MISMATCH),
            (dict(head_repository="attacker/quesada-abogados"), rpg.PR_GATE_FORK_OR_FOREIGN_HEAD),
            (dict(draft=True), rpg.PR_GATE_PR_DRAFT),
            (dict(state="closed"), rpg.PR_GATE_PR_CLOSED),
            (dict(state="closed", merged=True), rpg.PR_GATE_PR_MERGED),
            (dict(merged=True), rpg.PR_GATE_PR_INCONSISTENT),
            (dict(state="OPEN"), rpg.PR_GATE_PR_STATE_UNKNOWN),
            (dict(state="unknown"), rpg.PR_GATE_PR_STATE_UNKNOWN),
            (dict(state=None), rpg.PR_GATE_PR_STATE_UNKNOWN),
            (dict(merged=None), rpg.PR_GATE_PR_STATE_UNKNOWN),
            (dict(draft=0), rpg.PR_GATE_PR_STATE_UNKNOWN),
            (dict(number=43), rpg.PR_GATE_PR_NUMBER_MISMATCH),
            (dict(number=True), rpg.PR_GATE_PR_NUMBER_MISMATCH),
            (dict(head_sha=i.head_sha.upper()), rpg.PR_GATE_SHA_INVALID),
            (dict(head_sha=i.head_sha[:12]), rpg.PR_GATE_SHA_INVALID),
            (dict(base_sha="c" * 64), rpg.PR_GATE_SHA_INVALID),         # format differs from the intent
            (dict(base_branch_sha=None), rpg.PR_GATE_SHA_INVALID),
            (dict(head_ref=""), rpg.PR_GATE_HEAD_REF_MISMATCH),
        )
        for change, code in cases:
            with self.subTest(change=change):
                self.assertRejected(self.with_pr(**change), code)

    def test_missing_pr(self):
        self.assertRejected(self.gate(None), rpg.PR_GATE_PR_MISSING)
        self.assertRejected(self.gate(snapshot(self.intent, pr=None)), rpg.PR_GATE_PR_MISSING)

    def test_invalid_pr_number(self):
        for number in (0, -1, True, "42", 42.0, 2 ** 31, None):
            with self.subTest(number=number):
                r = self.assertRejected(self.gate(pr_number=number), rpg.PR_GATE_PR_NUMBER_INVALID)
                self.assertIsNone(r.context)

    def test_malformed_or_malicious_snapshot(self):
        good = snapshot(self.intent)

        @dataclasses.dataclass(frozen=True)
        class Approved(rpg.PullRequestSnapshot):
            approved: bool = True

        cases = (
            {}, dataclasses.asdict(good), "open", _Truthy(), good.pull_request,
            Approved(good.pull_request, good.changed_files, good.checks),
            dataclasses.replace(good, pull_request=dataclasses.asdict(good.pull_request)),
            dataclasses.replace(good, pull_request=pr_meta(self.intent, head_sha=_Str(SHA_A))),
            dataclasses.replace(good, pull_request=pr_meta(self.intent, state=_Str("closed"))),
            dataclasses.replace(good, pull_request=pr_meta(self.intent, merged=_Truthy())),
            dataclasses.replace(good, changed_files=_Truthy()),
            dataclasses.replace(good, checks=check_listing(self.intent, complete=1.0)),
        )
        for value in cases:
            with self.subTest(value=type(value)):
                r = self.assertRejected(self.gate(value), rpg.PR_GATE_SNAPSHOT_MALFORMED)
                self.assertIsNone(r.snapshot_fingerprint)
                self.assertIs(r.policy_proven, False)
        r = self.assertRejected(self.gate(dataclasses.replace(good, schema="fcp3b2a-pr-snapshot-v2")),
                                rpg.PR_GATE_SNAPSHOT_MALFORMED)
        self.assertIs(r.policy_proven, False)  # plain data: digested for audit, but nothing evaluated


# ---------------------------------------------------------------------------
# Changed files
# ---------------------------------------------------------------------------

class ChangedFileTests(SharedGateFixture):
    def test_incomplete_pagination_or_counts(self):
        many = tuple(rpg.ChangedFile(f"src/f{n}.py", "added") for n in range(150))
        cases = (
            (file_listing(complete=False), 1),
            (file_listing(complete=1), 1),
            (file_listing(reported_total=2), 1),
            (file_listing(reported_total=True), 1),
            (file_listing(pages_fetched=2), 1),
            (file_listing(page_size=0), 1),
            (file_listing(*many, pages_fetched=1), 150),   # only the first page of two
            (file_listing(), 3),                           # PR metadata reports more files
        )
        for listing, pr_total in cases:
            with self.subTest(listing=listing.reported_total, pr_total=pr_total):
                r = self.gate(snapshot(self.intent, pr=pr_meta(self.intent, changed_files=pr_total), files=listing))
                self.assertRejected(r, rpg.PR_GATE_FILES_INCOMPLETE)
        r = self.gate(snapshot(self.intent, pr=pr_meta(self.intent, changed_files=0), files=file_listing(
            files=(), reported_total=0)))
        self.assertRejected(r, rpg.PR_GATE_FILES_MISSING)
        over = tuple(rpg.ChangedFile(f"src/f{n}.py", "added") for n in range(rpg.MAX_CHANGED_FILES + 1))
        self.assertRejected(self.with_files(*over), rpg.PR_GATE_FILES_INCOMPLETE)

    def test_forbidden_and_rename_source_outside_scope(self):
        cases = (
            (rpg.ChangedFile("docs/readme.md", "modified"),),
            (rpg.ChangedFile("src/a.py", "modified"), rpg.ChangedFile("shared.txt", "added")),
            (rpg.ChangedFile("srcx/a.py", "added"),),                   # prefix, not a path segment
            (rpg.ChangedFile("SRC/a.py", "added"),),                    # case is exact
            (rpg.ChangedFile("src", "added"), rpg.ChangedFile(".github/workflows/fabric-ci.yml", "modified")),
            (rpg.ChangedFile("src/moved.md", "renamed", "docs/readme.md"),),   # source outside
            (rpg.ChangedFile("docs/readme.md", "renamed", "src/a.py"),),       # target outside
            (rpg.ChangedFile("src/copy.py", "copied", "shared.txt"),),
        )
        for files in cases:
            with self.subTest(files=files):
                r = self.assertRejected(self.with_files(*files), rpg.PR_GATE_PATH_OUT_OF_SCOPE)
                self.assertEqual(r.out_of_scope_path_count, 1)

    def test_rename_and_status_anomalies(self):
        cases = (
            (rpg.ChangedFile("src/b.py", "renamed"), rpg.PR_GATE_PATH_ANOMALY),
            (rpg.ChangedFile("src/b.py", "renamed", "src/b.py"), rpg.PR_GATE_PATH_ANOMALY),
            (rpg.ChangedFile("src/b.py", "modified", "src/a.py"), rpg.PR_GATE_PATH_ANOMALY),
            (rpg.ChangedFile("src/sub", "changed"), rpg.PR_GATE_PATH_ANOMALY),    # type change / submodule
            (rpg.ChangedFile("src/a.py", "unchanged"), rpg.PR_GATE_PATH_ANOMALY),
            (rpg.ChangedFile("src/a.py", "MODIFIED"), rpg.PR_GATE_FILE_STATUS_UNKNOWN),
            (rpg.ChangedFile("src/a.py", "deleted"), rpg.PR_GATE_FILE_STATUS_UNKNOWN),
            (rpg.ChangedFile("src/a.py", None), rpg.PR_GATE_FILE_STATUS_UNKNOWN),
        )
        for f, code in cases:
            with self.subTest(file=f):
                self.assertRejected(self.with_files(f), code)
        dup = (rpg.ChangedFile("src/a.py", "modified"), rpg.ChangedFile("src/a.py", "modified"))
        self.assertRejected(self.with_files(*dup), rpg.PR_GATE_PATH_ANOMALY)

    def test_unusual_path_encodings(self):
        for path in ("/src/a.py", "src\\a.py", "src/../x.py", "./src/a.py", "src/./a.py", "src//a.py", "src/",
                     "src/a.py ", " src/a.py", "src/a.py.", "src/a​.py", "src/é.py", "src/a:b.py",
                     "src/a\0.py", "src/a\n.py", "src/a\x7f.py", "src/.git/config", "src/.GIT/hooks/x",
                     "src/GIT~1/config", 'src/"q".py', "src/*.py", "src/a?.py", "src/a .py", "",
                     _Str("src/a.py"), b"src/a.py", None):
            with self.subTest(path=path):
                f = rpg.ChangedFile(path, "added")
                expected = rpg.PR_GATE_SNAPSHOT_MALFORMED if type(path) not in (str, type(None)) \
                    else rpg.PR_GATE_PATH_INVALID
                self.assertRejected(self.with_files(f), expected)
        self.assertRejected(self.with_files(rpg.ChangedFile("src/b.py", "renamed", "src/../docs/x")),
                            rpg.PR_GATE_PATH_INVALID)


# ---------------------------------------------------------------------------
# Check runs and branch policy
# ---------------------------------------------------------------------------

class CheckTests(SharedGateFixture):
    def test_missing_any_required_job(self):
        for index, name in enumerate(JOBS):
            with self.subTest(name=name):
                runs = [r for r in self.runs() if r.name != name]
                r = self.assertRejected(self.with_runs(runs), rpg.PR_GATE_CHECK_MISSING)
                self.assertNotIn(name, r.satisfied_checks)
                self.assertEqual(len(r.satisfied_checks), len(JOBS) - 1)
        self.assertRejected(self.with_runs([]), rpg.PR_GATE_CHECK_MISSING)

    def test_job_outcomes_other_than_success(self):
        cases = (
            (dict(conclusion="failure"), rpg.PR_GATE_CHECK_FAILED),
            (dict(conclusion="timed_out"), rpg.PR_GATE_CHECK_FAILED),
            (dict(conclusion="startup_failure"), rpg.PR_GATE_CHECK_FAILED),
            (dict(conclusion="action_required"), rpg.PR_GATE_CHECK_FAILED),
            (dict(conclusion="cancelled"), rpg.PR_GATE_CHECK_CANCELLED),
            (dict(conclusion="skipped"), rpg.PR_GATE_CHECK_SKIPPED),
            (dict(conclusion="neutral"), rpg.PR_GATE_CHECK_NOT_SUCCESS),
            (dict(conclusion="stale"), rpg.PR_GATE_CHECK_NOT_SUCCESS),
            (dict(status="in_progress", conclusion=None), rpg.PR_GATE_CHECK_PENDING),
            (dict(status="queued", conclusion=None), rpg.PR_GATE_CHECK_PENDING),
            (dict(status="waiting", conclusion=None), rpg.PR_GATE_CHECK_PENDING),
            (dict(status="completed", conclusion=None), rpg.PR_GATE_CHECK_STATUS_UNKNOWN),
            (dict(status="in_progress", conclusion="success"), rpg.PR_GATE_CHECK_STATUS_UNKNOWN),
            (dict(status="done"), rpg.PR_GATE_CHECK_STATUS_UNKNOWN),
            (dict(status="COMPLETED"), rpg.PR_GATE_CHECK_STATUS_UNKNOWN),
            (dict(conclusion="SUCCESS"), rpg.PR_GATE_CHECK_STATUS_UNKNOWN),
            (dict(conclusion="green"), rpg.PR_GATE_CHECK_STATUS_UNKNOWN),
        )
        for change, code in cases:
            with self.subTest(change=change):
                r = self.assertRejected(self.with_runs(self.runs(j2=change)), code)
                self.assertNotIn(JOBS[2], r.satisfied_checks)

    def test_job_bound_to_other_sha_event_workflow_or_pr(self):
        cases = (
            (dict(head_sha=SHA_A), rpg.PR_GATE_CHECK_HEAD_MISMATCH),
            (dict(head_sha=self.intent.base_sha), rpg.PR_GATE_CHECK_HEAD_MISMATCH),
            (dict(event="push"), rpg.PR_GATE_CHECK_EVENT_MISMATCH),
            (dict(event="pull_request_target"), rpg.PR_GATE_CHECK_EVENT_MISMATCH),
            (dict(event=None), rpg.PR_GATE_CHECK_EVENT_MISMATCH),
            (dict(app_slug="totally-github-actions"), rpg.PR_GATE_CHECK_BINDING_MISMATCH),
            (dict(workflow_name="Other CI"), rpg.PR_GATE_CHECK_BINDING_MISMATCH),
            (dict(workflow_path=".github/workflows/evil.yml"), rpg.PR_GATE_CHECK_BINDING_MISMATCH),
            (dict(workflow_run_id=None), rpg.PR_GATE_CHECK_BINDING_MISMATCH),
            (dict(pull_request_numbers=()), rpg.PR_GATE_CHECK_BINDING_MISMATCH),
            (dict(pull_request_numbers=(41,)), rpg.PR_GATE_CHECK_BINDING_MISMATCH),
            (dict(workflow_run_id=RUN_ID + 1), rpg.PR_GATE_CHECK_RUN_CONFLICT),
        )
        for change, code in cases:
            with self.subTest(change=change):
                self.assertRejected(self.with_runs(self.runs(j1=change)), code)
        r = self.assertRejected(self.with_runs(self.runs(j1=dict(workflow_run_id=RUN_ID + 1))))
        self.assertIsNone(r.ci_workflow_run_id)

    def test_unrelated_run_for_another_sha_makes_listing_inconsistent(self):
        other = check_run(self.intent, "lint", 9, head_sha=SHA_A)
        self.assertRejected(self.with_runs(self.runs() + [other]), rpg.PR_GATE_CHECK_HEAD_MISMATCH)
        weird = check_run(self.intent, "lint", 9, status="mystery")
        self.assertRejected(self.with_runs(self.runs() + [weird]), rpg.PR_GATE_CHECK_STATUS_UNKNOWN)

    def test_duplicate_or_conflicting_runs(self):
        rerun = check_run(self.intent, JOBS[0], 50)
        self.assertRejected(self.with_runs(self.runs() + [rerun]), rpg.PR_GATE_CHECK_DUPLICATE)
        failed_rerun = check_run(self.intent, JOBS[0], 50, conclusion="failure")
        self.assertRejected(self.with_runs([failed_rerun] + self.runs()), rpg.PR_GATE_CHECK_DUPLICATE)
        same_id = self.runs(j3=dict(check_run_id=100))
        self.assertRejected(self.with_runs(same_id), rpg.PR_GATE_CHECK_DUPLICATE)

    def test_incomplete_check_listing(self):
        for change in (dict(complete=False), dict(reported_total=len(JOBS) + 1), dict(reported_total=None)):
            with self.subTest(change=change):
                self.assertRejected(self.with_runs(self.runs(), **change), rpg.PR_GATE_CHECKS_INCOMPLETE)

    def test_malformed_runs(self):
        for change in (dict(check_run_id=0), dict(check_run_id=True), dict(name=""), dict(name=_Str(JOBS[0])),
                       dict(pull_request_numbers=[PR]), dict(pull_request_numbers=(True,)), dict(app_slug=None),
                       dict(workflow_run_id="9001"), dict(conclusion=1)):
            with self.subTest(change=change):
                self.assertRejected(self.with_runs(self.runs(j0=change)), rpg.PR_GATE_SNAPSHOT_MALFORMED)

    def test_branch_policy_not_proven(self):
        cases = (
            None,
            branch_policy(complete=False),
            branch_policy(base_ref="main"),
            branch_policy(rule_types=("pull_request", "required_status_checks", "merge_queue")),
            branch_policy(rule_types=("required_signatures", "required_status_checks")),
            branch_policy(rule_types=("pull_request",)),                     # names without the rule
            branch_policy(required_check_names=()),                         # rule without names
        )
        for policy in cases:
            with self.subTest(policy=policy):
                r = self.gate(snapshot(self.intent, checks=check_listing(self.intent, policy=policy)))
                self.assertNeverAuthorizes(r)
                self.assertEqual(r.classification, rpg.POLICY_NOT_PROVEN, r.reason_codes)
                self.assertIs(r.candidate_reviewable, False)
                self.assertIs(r.policy_proven, False)
                self.assertIn(rpg.PR_GATE_POLICY_NOT_PROVEN, r.reason_codes)
                self.assertNotIn(rpg.PR_GATE_METADATA_CONSISTENT, r.reason_codes)
        r = self.gate(snapshot(self.intent, checks=check_listing(self.intent, policy=branch_policy(
            rule_types=("merge_queue", "required_status_checks")))))
        self.assertIn(rpg.PR_GATE_POLICY_RULE_UNMODELED, r.reason_codes)
        # A policy problem never hides a rejection.
        r = self.gate(snapshot(self.intent, pr=pr_meta(self.intent, draft=True),
                               checks=check_listing(self.intent, policy=None)))
        self.assertRejected(r, rpg.PR_GATE_PR_DRAFT, rpg.PR_GATE_POLICY_NOT_PROVEN)

    def test_malformed_policy(self):
        for policy in (branch_policy(required_check_names=(JOBS[0], JOBS[0])), branch_policy(rule_types=["x"]),
                       branch_policy(complete=None), {"complete": True}):
            with self.subTest(policy=policy):
                self.assertRejected(self.gate(snapshot(self.intent, checks=check_listing(self.intent, policy=policy))),
                                    rpg.PR_GATE_SNAPSHOT_MALFORMED)

    def test_ci_success_alone_does_not_make_a_wrong_pr_reviewable(self):
        r = self.gate(snapshot(self.intent, pr=pr_meta(self.intent, base_ref="main")))
        self.assertRejected(r, rpg.PR_GATE_BASE_REF_INVALID)
        self.assertEqual(r.satisfied_checks, JOBS)


# ---------------------------------------------------------------------------
# FCP-3B-1 intent and validation binding
# ---------------------------------------------------------------------------

class IntentBindingTests(SharedGateFixture):
    def test_tampered_or_forged_intent(self):
        i = self.intent
        cases = (
            dataclasses.replace(i, fingerprint="0" * 64), dataclasses.replace(i, head_sha=SHA_A),
            reforged(i, rpa.intent_fingerprint, authorizes_action=True),
            reforged(i, rpa.intent_fingerprint, execution_allowed=True),
            reforged(i, rpa.intent_fingerprint, human_approval_required=False),
            reforged(i, rpa.intent_fingerprint, status="APPROVED"),
            reforged(i, rpa.intent_fingerprint, proposed_action="MERGE_PULL_REQUEST"),
            reforged(i, rpa.intent_fingerprint, proposed_action="git push origin HEAD:develop"),
            reforged(i, rpa.intent_fingerprint, head_ref=_Str(i.head_ref)),
            None, {}, dataclasses.asdict(i), self.validation, self.readiness, _Truthy(),
        )
        for forged in cases:
            with self.subTest(forged=type(forged)):
                r = self.assertRejected(self.gate(intent=forged), rpg.PR_GATE_INTENT_INVALID)
                self.assertIsNone(r.context)
                self.assertTrue({rpa.INTENT_TAMPERED, rpa.INTENT_MALFORMED} & set(r.reason_codes))

    def test_validation_missing_malformed_or_tampered(self):
        v = self.validation
        for value in (None, {}, dataclasses.asdict(v), self.intent, "MATCHES_PROPOSAL", True, _Truthy(),
                      reforged(v, rpa.validation_fingerprint, mode=_Str(rpa.MODE_FRESH_FCP3A_READ))):
            with self.subTest(value=type(value)):
                r = self.assertRejected(self.gate(validation=value), rpg.PR_GATE_VALIDATION_MALFORMED)
                self.assertIsNone(r.context)
        for value in (dataclasses.replace(v, fingerprint="0" * 64),
                      dataclasses.replace(v, mode=rpa.MODE_SUPPLIED_READINESS),  # digest no longer matches
                      reforged(v, rpa.validation_fingerprint, authorizes_action=True),
                      reforged(v, rpa.validation_fingerprint, execution_allowed=True),
                      reforged(v, rpa.validation_fingerprint, human_approval_required=False),
                      reforged(v, rpa.validation_fingerprint, schema="fcp3b1-promotion-intent-validation-v2")):
            with self.subTest(value=value):
                self.assertRejected(self.gate(validation=value), rpg.PR_GATE_VALIDATION_TAMPERED)

    def test_supplied_mode_validation_is_not_fresh(self):
        supplied = rpa.validate_promotion_intent(self.intent, self.readiness)
        self.assertIs(supplied.valid, True)
        self.assertRejected(self.gate(validation=supplied), rpg.PR_GATE_VALIDATION_NOT_FRESH_MODE)
        # Caller re-creates the digest after relabelling the mode: impossible content.
        relabelled = reforged(supplied, rpa.validation_fingerprint, mode=rpa.MODE_FRESH_FCP3A_READ)
        self.assertRejected(self.gate(validation=relabelled), rpg.PR_GATE_VALIDATION_TAMPERED)

    def test_fresh_but_not_valid_validation(self):
        drifted = rpa.revalidate_promotion_intent(self.intent, self.fx.wt, **dict(
            self.kw, authorized_scopes=("docs", "src")))
        self.assertEqual((drifted.mode, drifted.valid), (rpa.MODE_FRESH_FCP3A_READ, False))
        self.assertRejected(self.gate(validation=drifted), rpg.PR_GATE_VALIDATION_NOT_VALID)
        flipped = reforged(drifted, rpa.validation_fingerprint, valid=True, outcome=rpa.MATCHES_PROPOSAL)
        self.assertRejected(self.gate(validation=flipped), rpg.PR_GATE_VALIDATION_TAMPERED)
        self.assertRejected(self.gate(validation=reforged(self.validation, rpa.validation_fingerprint, valid=False)),
                            rpg.PR_GATE_VALIDATION_NOT_VALID)
        self.assertRejected(self.gate(validation=reforged(self.validation, rpa.validation_fingerprint,
                                                          mismatched_fields=("head_sha",))),
                            rpg.PR_GATE_VALIDATION_TAMPERED)

    def test_validation_of_another_intent(self):
        wider = rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=("docs", "src"))
        self.assertRejected(self.gate(intent=wider), rpg.PR_GATE_VALIDATION_INTENT_MISMATCH)
        other = reforged(self.validation, rpa.validation_fingerprint, fresh_readiness_fingerprint="d" * 64)
        self.assertRejected(self.gate(validation=other), rpg.PR_GATE_VALIDATION_INTENT_MISMATCH)

    def test_caller_recreated_validation_is_never_more_than_unverified(self):
        # The FCP-3B-1 digest is unkeyed: a caller can rebuild a byte-identical
        # validation. The pure gate therefore never claims its provenance.
        draft = rpa.PromotionIntentValidation(
            valid=True, outcome=rpa.MATCHES_PROPOSAL, reason_codes=rpg._FRESH_MATCH_REASONS, fingerprint="",
            mode=rpa.MODE_FRESH_FCP3A_READ, intent_fingerprint=self.intent.fingerprint,
            fresh_readiness_fingerprint=self.intent.readiness_fingerprint,
            fresh_readiness_classification=rp.AWAITING_HUMAN_APPROVAL)
        forged = dataclasses.replace(draft, fingerprint=rpa.validation_fingerprint(draft))
        self.assertEqual(forged, self.validation)
        r = self.assertReviewable(self.gate(validation=forged))
        self.assertIn(rpg.PR_GATE_VALIDATION_PROVENANCE_NOT_PROVEN, r.reason_codes)
        self.assertIs(r.authorizes_action, False)

    def test_no_approval_or_consent_input(self):
        for extra in (dict(approved=True), dict(authorizes_action=True), dict(execution_allowed=True),
                      dict(human_decision_present=True), dict(fresh=True), dict(mergeable=True)):
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                rpg.evaluate_pr_gate(self.intent, self.validation, snapshot(self.intent), pr_number=PR, **extra)
        with self.assertRaises(TypeError):  # keyword-only PR number
            rpg.evaluate_pr_gate(self.intent, self.validation, snapshot(self.intent), PR)

    def test_evaluation_never_raises_or_leaks(self):
        with mock.patch.object(rpa, "_intent_errors", side_effect=RuntimeError("secret-detail")):
            r = self.gate()
        self.assertRejected(r, rpg.PR_GATE_EVALUATION_FAILED)
        self.assertNotIn("secret", json.dumps(dataclasses.asdict(r)))
        with mock.patch.object(rpg, "_check_findings", side_effect=RuntimeError("secret-detail")):
            self.assertRejected(self.gate(), rpg.PR_GATE_EVALUATION_FAILED)


# ---------------------------------------------------------------------------
# Host read (one real FCP-3B-1 revalidation, fake provider)
# ---------------------------------------------------------------------------

class HostReadTests(SharedGateFixture):
    def provider(self, **overrides):
        values = dict(pr=pr_meta(self.intent), files=file_listing(), checks=check_listing(self.intent))
        values.update(overrides)
        return FakeProvider(**values)

    def read(self, provider, intent=_DEFAULT, pr_number=PR, **overrides):
        kw = dict(self.kw, **overrides)
        return rpg.read_pr_gate(self.intent if intent is _DEFAULT else intent, provider, self.fx.wt,
                                pr_number=pr_number, **kw)

    def test_host_read_is_reviewable_and_still_non_authorizing(self):
        provider = self.provider()
        with mock.patch.object(rpa, "revalidate_promotion_intent", wraps=rpa.revalidate_promotion_intent) as reval, \
                mock.patch.object(rp, "assess_promotion_readiness", wraps=rp.assess_promotion_readiness) as fcp3a:
            r = self.read(provider)
        self.assertReviewable(r, rpg.REVIEWABLE_HOST_READ)
        self.assertEqual(r.mode, rpg.MODE_HOST_PROVIDER_READ)
        self.assertIs(r.source_freshness_proven, True)
        self.assertIs(r.source_authenticated, False)
        for code in (rpg.PR_GATE_HOST_PROVIDER_READ, rpg.PR_GATE_FRESH_REVALIDATION_IN_CALL,
                     rpg.PR_GATE_HUMAN_DECISION_MISSING):
            self.assertIn(code, r.reason_codes)
        self.assertNotIn(rpg.PR_GATE_VALIDATION_PROVENANCE_NOT_PROVEN, r.reason_codes)
        reval.assert_called_once_with(self.intent, self.fx.wt, expected_remote_url=None, lease_root=None,
                                      max_paths=rr.MAX_PATHS, **self.kw)
        for name in ("evidence", "ledger_root", "authorized_scopes"):
            self.assertIs(reval.call_args.kwargs[name], self.kw[name])
        self.assertEqual(fcp3a.call_count, 1)
        self.assertEqual(provider.calls, [
            ("read_pull_request", (REPO, PR)), ("read_changed_files", (REPO, PR)),
            ("read_required_checks", (REPO, "develop", self.intent.head_sha))])
        for _, args in provider.calls:
            self.assertTrue(all(type(a) in (str, int) for a in args))
        self.assertEqual(r.context.validation_fingerprint, self.validation.fingerprint)

    def test_provider_failure_stops_reading_and_leaks_nothing(self):
        for fail, count in (("read_pull_request", 1), ("read_changed_files", 2), ("read_required_checks", 3)):
            with self.subTest(fail=fail):
                provider = self.provider()
                provider.fail = fail
                r = self.assertRejected(self.read(provider), rpg.PR_GATE_PROVIDER_READ_FAILED)
                self.assertEqual(len(provider.calls), count)
                self.assertNotIn("secret", json.dumps(dataclasses.asdict(r)))
        r = self.assertRejected(self.read(object()), rpg.PR_GATE_PROVIDER_READ_FAILED)
        self.assertIsNotNone(r.context)

    def test_provider_returning_missing_or_garbage(self):
        self.assertRejected(self.read(self.provider(pr=None)), rpg.PR_GATE_PR_MISSING)
        self.assertRejected(self.read(self.provider(pr=_Truthy())), rpg.PR_GATE_SNAPSHOT_MALFORMED)
        failing = check_listing(self.intent, self.runs(j0=dict(conclusion="failure")))
        self.assertRejected(self.read(self.provider(checks=failing)), rpg.PR_GATE_CHECK_FAILED)

    def test_unbindable_request_reads_nothing(self):
        for intent, number, code in ((None, PR, rpg.PR_GATE_INTENT_INVALID),
                                     (reforged(self.intent, rpa.intent_fingerprint, authorizes_action=True), PR,
                                      rpg.PR_GATE_INTENT_INVALID),
                                     (self.intent, 0, rpg.PR_GATE_PR_NUMBER_INVALID)):
            with self.subTest(code=code), \
                    mock.patch.object(rpa, "revalidate_promotion_intent") as reval:
                provider = self.provider()
                self.assertRejected(self.read(provider, intent=intent, pr_number=number), code)
                reval.assert_not_called()
                self.assertEqual(provider.calls, [])

    def test_non_matching_fresh_revalidation_reads_no_pr_facts(self):
        provider = self.provider()
        r = self.read(provider, authorized_scopes=("docs", "src"))
        self.assertRejected(r, rpg.PR_GATE_VALIDATION_NOT_VALID)
        self.assertEqual(provider.calls, [])
        with mock.patch.object(rp, "assess_promotion_readiness", side_effect=RuntimeError("secret")):
            self.assertRejected(self.read(provider), rpg.PR_GATE_VALIDATION_NOT_VALID)
        self.assertEqual(provider.calls, [])

    def test_fcp3a_input_refusals_propagate(self):
        provider = self.provider()
        with self.assertRaises(rp.PromotionInputError):
            self.read(provider, authorized_scopes="src")
        self.assertEqual(provider.calls, [])

    def test_nothing_written_and_no_network(self):
        git_dir = self.fx.repo / ".git"
        before = _git_dir_state([git_dir])
        refuse = mock.Mock(side_effect=AssertionError("network used"))
        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse):
            r = self.read(self.provider())
            self.gate()
        self.assertReviewable(r, rpg.REVIEWABLE_HOST_READ)
        refuse.assert_not_called()
        self.assertEqual(_git_dir_state([git_dir]), before)
        self.assertEqual(sorted(self.ledger.iterdir()), [])


class HostReadDriftTests(GateAssertions, PromotionTestCase):
    def test_head_moved_after_intent_is_rejected_before_any_pr_read(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        worktree, kw = self.kwargs()
        intent = rpa.prepare_promotion_intent(rp.assess_promotion_readiness(worktree, **kw), proposed_action=FF,
                                              authorized_scopes=SCOPES)
        provider = FakeProvider(pr_meta(intent), file_listing(), check_listing(intent))
        self.assertReviewable(rpg.read_pr_gate(intent, provider, worktree, pr_number=PR, **kw),
                              rpg.REVIEWABLE_HOST_READ)
        self.fx.head_commit({"src/a.py": text({3: "after approval\n"})})
        provider = FakeProvider(pr_meta(intent), file_listing(), check_listing(intent))
        r = rpg.read_pr_gate(intent, provider, worktree, pr_number=PR, **kw)
        self.assertRejected(r, rpg.PR_GATE_VALIDATION_NOT_VALID)
        self.assertEqual(provider.calls, [])


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

class StructureTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def test_no_git_process_network_write_or_mutation_entry_points(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        imports = {a.name for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names} | {n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("subprocess", "socket", "os", "shutil", "urllib", "http", "requests", "httpx", "github",
                       "runner_git", "runner_pipeline", "runner_factory_ledger", "claude_runner", "hmac", "secrets",
                       "pickle", "sqlite3", "tempfile", "json"):
            self.assertNotIn(banned, imports, banned)
        for banned in ("_git", "assess_integration", "analyze_reconciliation", "assess_promotion_readiness",
                       "run", "Popen", "system", "check_output", "urlopen", "request", "post", "put", "patch",
                       "delete", "merge", "push", "update_ref", "approve", "create_review", "submit_review",
                       "create_comment", "open", "write_text", "write_bytes", "mkdir", "unlink", "FactoryLedger",
                       "DirLease", "try_acquire", "exec", "eval", "getenv", "environ"):
            self.assertNotIn(banned, attrs | names, banned)

    def test_single_fcp3b1_delegation_site_forwarding_inputs_unchanged(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "revalidate_promotion_intent"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([a.id for a in calls[0].args], ["intent", "worktree"])
        for keyword in calls[0].keywords:
            self.assertIsInstance(keyword.value, ast.Name)
            self.assertEqual(keyword.value.id, keyword.arg)

    def test_public_surface_has_no_approval_or_execution_entry_point(self):
        public = {n.name for n in self.tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")}
        self.assertEqual(public, {
            "PullRequestMetadata", "ChangedFile", "ChangedFileListing", "CheckRun", "BranchPolicy",
            "RequiredCheckListing", "PullRequestSnapshot", "PullRequestMetadataProvider", "PrGateContext",
            "PrGateResult", "context_fingerprint", "result_fingerprint", "snapshot_fingerprint",
            "evaluate_pr_gate", "read_pr_gate"})
        protocol = next(n for n in self.tree.body if isinstance(n, ast.ClassDef)
                        and n.name == "PullRequestMetadataProvider")
        provider_methods = {m.name for m in protocol.body if isinstance(m, ast.FunctionDef)}
        self.assertEqual(provider_methods, {"read_pull_request", "read_changed_files", "read_required_checks"})
        for func in (rpg.evaluate_pr_gate, rpg.read_pr_gate):
            params = set(inspect.signature(func).parameters)
            self.assertFalse(params & {"approved", "approval", "fresh", "token", "credential", "callback", "client",
                                       "authorizes_action", "execution_allowed", "mergeable", "kwargs"}, func.__name__)

    def test_result_and_context_schema(self):
        self.assertEqual(tuple(f.name for f in dataclasses.fields(rpg.PrGateResult)), RESULT_FIELDS)
        self.assertEqual(tuple(f.name for f in dataclasses.fields(rpg.PrGateContext)), CONTEXT_FIELDS)
        for name in RESULT_FIELDS + CONTEXT_FIELDS:
            for word in ("token", "approved", "approval_id", "signature", "credential", "receipt", "command",
                         "mergeable", "permission", "url"):
                self.assertNotIn(word, name)
        for cls in rpg._SNAPSHOT_TYPES + (rpg.PrGateContext, rpg.PrGateResult):
            self.assertTrue(cls.__dataclass_params__.frozen, cls.__name__)
        defaults = {f.name: f.default for f in dataclasses.fields(rpg.PrGateResult)}
        self.assertEqual((defaults["authorizes_action"], defaults["execution_allowed"],
                          defaults["human_approval_required"], defaults["source_authenticated"],
                          defaults["human_decision_present"]), (False, False, True, False, False))

    def test_required_jobs_match_the_fabric_ci_workflow(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^name: Fabric CI$")
        self.assertEqual(rpg.CI_WORKFLOW_NAME, "Fabric CI")
        self.assertEqual(rpg.CI_WORKFLOW_PATH, ".github/workflows/fabric-ci.yml")
        self.assertRegex(workflow, r"(?m)^  pull_request:\n    branches: \[develop, main\]$")
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", workflow))
        self.assertEqual(jobs, {
            "fabric-regression": JOBS[0], "fcp2b-reconciliation": JOBS[1], "fcp3a-promotion": JOBS[2],
            "fcp3b1-authorization-intent": JOBS[3],
            "fcp3b2a-pr-gate": JOBS[4]})
        self.assertEqual(rpg.BASE_BRANCH, "develop")
        self.assertEqual(ri.TRACKING_REF, "refs/remotes/origin/develop")
        self.assertEqual(rpg.CANONICAL_REPOSITORY, "ignacio-alvarez93/quesada-abogados")

    def test_fcp3b1_action_is_never_an_execution_right(self):
        self.assertEqual(rpa.PROPOSED_ACTIONS, (FF,))
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("FAST_FORWARD_CANDIDATE_TO_DEVELOP", re.sub(r'"""[\s\S]*?"""', "", source))


if __name__ == "__main__":
    unittest.main()
