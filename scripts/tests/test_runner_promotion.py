"""FCP-3A: deterministic, read-only promotion-readiness preflight.

Repositories are throwaways under a temporary directory, built with PLAIN
git through the existing FCP-1/FCP-2B fixtures (fixture construction only).
The module under test reads nothing itself: every fact comes from one
FCP-2B `analyze_reconciliation` call. Tamper tests start from REAL analyses
and alter exactly one received fact.
"""

import ast
import dataclasses
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_integration as ri
from scripts.ai import runner_pipeline as pipeline
from scripts.ai import runner_promotion as rp
from scripts.ai import runner_reconciliation as rr
from scripts.tests.test_runner_git import plain_git
from scripts.tests.test_runner_integration import REMOTE_URL, _git_dir_state, _rmtree, good_evidence, head, write
from scripts.tests.test_runner_reconciliation import SCOPES, Fixture, _isolate_env, hash_blob, text

MODULE_PATH = Path(rp.__file__)

READINESS_FIELDS = (
    "classification", "reason_codes", "fingerprint", "reconciliation_classification",
    "reconciliation_fingerprint", "reconciliation_reason_codes", "assessment_classification",
    "assessment_fingerprint", "assessment_reason_codes", "worktree_key", "head_ref", "head_sha", "base_sha",
    "attested_sha", "base_status", "merge_bases", "evidence_status", "ledger_checked",
    "semantic_validation_required", "human_approval_required", "authorizes_action", "execution_allowed", "schema",
)


class PromotionTestCase(unittest.TestCase):
    def setUp(self):
        _isolate_env(self)
        self.root = Path(tempfile.mkdtemp(prefix="fcp3a-")).resolve()
        self.addCleanup(_rmtree, self.root)
        self.fx = Fixture(self.root)
        self.ledger = self.root / "factory"
        self.ledger.mkdir()

    def kwargs(self, worktree=None, **overrides):
        worktree = worktree or self.fx.wt
        kw = dict(attested_sha=self.fx.base, authorized_scopes=SCOPES, ledger_root=self.ledger)
        kw.update(overrides)
        if "evidence" not in kw:
            kw["evidence"] = good_evidence(Path(worktree))
        return worktree, kw

    def assess(self, worktree=None, **overrides):
        worktree, kw = self.kwargs(worktree, **overrides)
        return rp.assess_promotion_readiness(worktree, **kw)

    def analyze(self, worktree=None, **overrides):
        worktree, kw = self.kwargs(worktree, **overrides)
        return rr.analyze_reconciliation(worktree, **kw)

    def assertInvariants(self, r):
        self.assertIs(type(r), rp.PromotionReadiness)
        self.assertIn(r.classification, rp.READINESS_CLASSIFICATIONS)
        self.assertIs(r.human_approval_required, True)
        self.assertIs(r.authorizes_action, False)
        self.assertIs(r.execution_allowed, False)
        self.assertEqual(r.schema, rp.READINESS_SCHEMA)
        self.assertRegex(r.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(r.fingerprint, rp.readiness_fingerprint(r))
        self.assertIn(rp.PROMO_HUMAN_DECISION_REQUIRED, r.reason_codes)
        self.assertIn(rp.PROMO_NOT_AUTHORIZATION, r.reason_codes)
        json.dumps(dataclasses.asdict(r))  # safe to serialize
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.authorizes_action = True  # type: ignore[misc]

    def assertReadiness(self, r, classification, *reasons):
        self.assertInvariants(r)
        self.assertEqual(r.classification, classification, r.reason_codes)
        for reason in reasons:
            self.assertIn(reason, r.reason_codes)

    def assertBlocked(self, r, *reasons):
        self.assertReadiness(r, rp.BLOCKED, *reasons)
        self.assertFalse(r.semantic_validation_required)


# ---------------------------------------------------------------------------
# Positive outcomes (real Git)
# ---------------------------------------------------------------------------

class AwaitingHumanApprovalTests(PromotionTestCase):
    def setUp(self):
        super().setUp()
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})

    def test_eligible_is_only_awaiting_human_approval(self):
        r = self.assess()
        self.assertReadiness(r, rp.AWAITING_HUMAN_APPROVAL, rp.PROMO_ELIGIBLE_PENDING_HUMAN_APPROVAL,
                             "FCP1_ELIGIBLE_PENDING_APPROVAL", "FCP2B_NOT_APPLICABLE")
        self.assertEqual(r.assessment_classification, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertEqual(r.reconciliation_classification, rr.NOT_APPLICABLE)
        self.assertEqual(r.assessment_reason_codes, ())
        self.assertEqual(r.reconciliation_reason_codes, (rr.RECON_NOT_APPLICABLE, "FCP1_ELIGIBLE_PENDING_APPROVAL"))
        self.assertEqual((r.head_sha, r.base_sha, r.attested_sha), (head(self.fx.wt), self.fx.base, self.fx.base))
        self.assertEqual(r.head_ref, "refs/heads/feature/fcp2b")
        self.assertEqual(r.merge_bases, (self.fx.c0,))
        self.assertEqual((r.base_status, r.evidence_status), (ri.BASE_VERIFIED, ri.EVIDENCE_BOUND))
        self.assertTrue(r.ledger_checked)
        self.assertFalse(r.semantic_validation_required)

    def test_bound_to_fcp2b_and_fcp1_fingerprints(self):
        analysis = self.analyze()
        r = rp.classify_promotion_readiness(analysis)
        self.assertEqual(r.reconciliation_fingerprint, analysis.fingerprint)
        self.assertEqual(r.assessment_fingerprint, analysis.assessment.fingerprint)
        self.assertEqual(r.worktree_key, analysis.assessment.candidate.worktree_key)
        # The live preflight yields the identical, deterministic result.
        live = self.assess()
        self.assertEqual(live, r)
        self.assertEqual(live.fingerprint, self.assess().fingerprint)

    def test_fingerprint_covers_every_field(self):
        r = self.assess()
        for name, value in (("classification", rp.BLOCKED), ("head_sha", "0" * 40), ("reason_codes", ()),
                            ("authorizes_action", True), ("execution_allowed", True),
                            ("reconciliation_fingerprint", "f" * 64), ("assessment_fingerprint", "e" * 64),
                            ("worktree_key", "x"), ("base_sha", "1" * 40)):
            self.assertNotEqual(rp.readiness_fingerprint(dataclasses.replace(r, **{name: value})), r.fingerprint, name)

    def test_without_ledger_root_is_blocked(self):
        r = self.assess(ledger_root=None)
        self.assertBlocked(r, rp.PROMO_LEDGER_NOT_CHECKED, "FCP1_ELIGIBLE_PENDING_APPROVAL")
        self.assertFalse(r.ledger_checked)

    def test_lease_released_and_nothing_written(self):
        git_dir = self.fx.repo / ".git"
        before = _git_dir_state([git_dir])
        files = {p: p.read_bytes() for p in self.fx.wt.rglob("*") if p.is_file() and ".git" not in p.parts}
        r = self.assess()
        self.assertReadiness(r, rp.AWAITING_HUMAN_APPROVAL)
        self.assertEqual(_git_dir_state([git_dir]), before)
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        self.assertEqual(sorted(self.ledger.iterdir()), [])  # no ledger event written
        probe = pipeline.DirLease(pipeline.worktree_lease_dir(self.fx.wt.resolve(), None))
        self.assertTrue(probe.try_acquire({"pid": 0}))
        probe.release()

    def test_no_network(self):
        refuse = mock.Mock(side_effect=AssertionError("network used"))
        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse):
            r = self.assess(expected_remote_url=REMOTE_URL)
        self.assertReadiness(r, rp.AWAITING_HUMAN_APPROVAL)
        refuse.assert_not_called()


class ReconciliationReviewTests(PromotionTestCase):
    def assertReview(self, r, fcp1, fcp2b):
        self.assertReadiness(r, rp.RECONCILIATION_REVIEW_REQUIRED, rp.PROMO_RECONCILIATION_REVIEW,
                             rp.PROMO_SEMANTIC_REVIEW_REQUIRED, rp.PROMO_FRESH_REVALIDATION_REQUIRED,
                             f"FCP1_{fcp1}", f"FCP2B_{fcp2b}")
        self.assertEqual((r.assessment_classification, r.reconciliation_classification), (fcp1, fcp2b))
        self.assertIn(rr.RECON_SEMANTIC_VALIDATION_REQUIRED, r.reconciliation_reason_codes)
        self.assertTrue(r.semantic_validation_required)
        self.assertNotIn(rp.PROMO_ELIGIBLE_PENDING_HUMAN_APPROVAL, r.reason_codes)

    def test_stale_base_textual_disjoint_is_not_semantic_approval(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.fx.base_commit({"docs/readme.md": "readme v2\n"})
        r = self.assess()
        self.assertReview(r, ri.STALE_BASE, rr.NO_TEXTUAL_CONFLICT)
        self.assertIn(rr.RECON_DISJOINT_PATHS, r.reconciliation_reason_codes)

    def test_needs_reconciliation_disjoint_hunks(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.fx.base_commit({"src/a.py": text({8: "base\n"})})
        self.assertReview(self.assess(), ri.NEEDS_RECONCILIATION, rr.NO_TEXTUAL_CONFLICT)

    def test_overlapping_hunks_semantic_review(self):
        self.fx.head_commit({"src/a.py": text({5: "head\n"})})
        self.fx.base_commit({"src/a.py": text({5: "base\n"})})
        self.assertReview(self.assess(), ri.NEEDS_RECONCILIATION, rr.SEMANTIC_REVIEW_REQUIRED)

    def test_binary_symlink_and_case_hazards_need_human(self):
        self.fx.head_commit({"src/blob.bin": b"\x00\x01binary\xff", "src/Readme.md": "head\n"})
        target = hash_blob(self.fx.repo, b"../shared.txt")
        self.fx.base_commit({"src/readme.md": "base\n"}, index_entries=(("120000", target, "docs/link"),))
        r = self.assess()
        self.assertReview(r, ri.STALE_BASE, rr.HUMAN_REQUIRED)
        for code in (rr.RECON_BINARY, rr.RECON_SYMLINK, rr.RECON_CASE_COLLISION):
            self.assertIn(code, r.reconciliation_reason_codes)

    def test_modify_delete_needs_human(self):
        self.fx.head_commit({"src/old.py": "head edit\n"})
        self.fx.base_commit(delete=("src/old.py",))
        self.assertReview(self.assess(), ri.NEEDS_RECONCILIATION, rr.HUMAN_REQUIRED)

    def test_review_without_ledger_root_is_blocked(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.fx.base_commit({"docs/readme.md": "readme v2\n"})
        self.assertBlocked(self.assess(ledger_root=None), rp.PROMO_LEDGER_NOT_CHECKED)


# ---------------------------------------------------------------------------
# Fail-closed outcomes (real Git)
# ---------------------------------------------------------------------------

class BlockedTests(PromotionTestCase):
    def setUp(self):
        super().setUp()
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})

    def assertFcp1Blocked(self, r, fcp1, reason=None):
        self.assertBlocked(r, rp.PROMO_FCP1_NOT_PROMOTABLE, f"FCP1_{fcp1}", "FCP2B_NOT_APPLICABLE")
        self.assertEqual(r.assessment_classification, fcp1)
        if reason:
            self.assertIn(reason, r.assessment_reason_codes)

    def test_missing_invalid_and_stale_evidence(self):
        self.assertFcp1Blocked(self.assess(evidence=None), ri.EVIDENCE_MISSING, "EVIDENCE_MISSING")
        self.assertFcp1Blocked(self.assess(evidence=good_evidence(self.fx.wt, safety_verdict="UNSAFE")),
                               ri.EVIDENCE_MISSING, "EVIDENCE_NOT_SAFE")
        self.assertFcp1Blocked(self.assess(evidence=good_evidence(self.fx.wt, head_sha=self.fx.c0)),
                               ri.EVIDENCE_MISSING, "EVIDENCE_HEAD_MISMATCH")
        self.assertFcp1Blocked(self.assess(evidence="not a mapping"), ri.EVIDENCE_MISSING, "EVIDENCE_INVALID")

    def test_missing_invalid_or_wrong_attestation(self):
        self.assertFcp1Blocked(self.assess(attested_sha=None), ri.BASE_UNVERIFIED, ri.BASE_UNATTESTED)
        self.assertFcp1Blocked(self.assess(attested_sha="xyz"), ri.BASE_UNVERIFIED, ri.BASE_INVALID_ATTESTATION)
        self.assertFcp1Blocked(self.assess(attested_sha=head(self.fx.wt)), ri.BASE_UNVERIFIED)

    def test_unknown_base_and_remote_mismatch(self):
        plain_git(self.fx.repo, "update-ref", "-d", ri.TRACKING_REF)
        self.assertFcp1Blocked(self.assess(), ri.BASE_UNVERIFIED, ri.BASE_MISSING)
        self.fx.set_base(self.fx.c0)
        self.assertFcp1Blocked(self.assess(expected_remote_url="https://example.invalid/other.git"),
                               ri.BASE_UNVERIFIED, ri.BASE_REMOTE_URL_MISMATCH)

    def test_dirty_tree(self):
        write(self.fx.wt / "src" / "untracked.py", "x\n")
        self.assertFcp1Blocked(self.assess(), ri.DIRTY_WORKTREE, "UNTRACKED_FILES")

    def test_out_of_scope_and_invalid_scope(self):
        self.assertFcp1Blocked(self.assess(authorized_scopes=("docs",)), ri.UNAUTHORIZED_CHANGED_PATHS)
        self.assertFcp1Blocked(self.assess(authorized_scopes=()), ri.UNAUTHORIZED_CHANGED_PATHS)
        self.assertFcp1Blocked(self.assess(authorized_scopes=("../outside",)), ri.UNAUTHORIZED_CHANGED_PATHS)

    def test_active_worker_and_unreadable_ledger(self):
        ledger = flog.FactoryLedger(self.ledger)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        self.assertFcp1Blocked(self.assess(), ri.OWNERSHIP_CONFLICT, "ACTIVE_WORKER")
        self.assertFcp1Blocked(self.assess(ledger_root=self.root / "absent"), ri.OWNERSHIP_CONFLICT,
                               "LEDGER_UNREADABLE")

    def test_held_lease(self):
        competitor = pipeline.DirLease(pipeline.worktree_lease_dir(self.fx.wt.resolve(), None))
        self.assertTrue(competitor.try_acquire({"pipeline_id": "other", "worker_id": "w", "pid": 1}))
        try:
            self.assertFcp1Blocked(self.assess(), ri.OWNERSHIP_CONFLICT, "WORKTREE_LEASE_HELD")
        finally:
            competitor.release()

    def test_nothing_to_integrate_and_unknown_worktree(self):
        other = self.fx.add_worktree("idle-wt", "feature/idle", self.fx.c0)
        self.assertFcp1Blocked(self.assess(other), ri.NOTHING_TO_INTEGRATE)
        self.assertFcp1Blocked(self.assess(self.root / "missing", evidence=good_evidence(self.fx.wt)),
                               ri.UNSAFE_WORKTREE, "GIT_READ_FAILED")

    def test_fcp2b_fail_closed_read_failure_leaks_no_detail(self):
        self.fx.base_commit({"src/a.py": text({9: "base\n"})})
        real = ri._git

        def failing(repo, *args, **kwargs):
            if "--raw" in args:
                raise ri._GitReadError("git diff", "simulated secret read failure")
            return real(repo, *args, **kwargs)

        with mock.patch.object(ri, "_git", failing):
            r = self.assess()
        self.assertBlocked(r, rp.PROMO_RECONCILIATION_FAIL_CLOSED, "FCP2B_FAIL_CLOSED", "FCP1_NEEDS_RECONCILIATION")
        self.assertIn(rr.RECON_READ_FAILED, r.reconciliation_reason_codes)
        self.assertNotIn("simulated", json.dumps(dataclasses.asdict(r)))

    def test_fcp2b_fail_closed_on_drift(self):
        self.fx.base_commit({"src/a.py": text({9: "base\n"})})
        real = rr._read_facts

        def drifting(worktree, assessment, max_paths):
            facts = real(worktree, assessment, max_paths)
            write(self.fx.wt / "src" / "drift.py", "drift\n")
            return facts

        with mock.patch.object(rr, "_read_facts", drifting):
            r = self.assess()
        self.assertBlocked(r, rp.PROMO_RECONCILIATION_FAIL_CLOSED)
        self.assertIn(rr.RECON_ASSESSMENT_DRIFT, r.reconciliation_reason_codes)

    def test_no_secret_evidence_or_prose_in_result(self):
        r = self.assess(evidence=good_evidence(self.fx.wt, run_id="run-SECRET-123"))
        self.assertReadiness(r, rp.AWAITING_HUMAN_APPROVAL)
        dumped = json.dumps(dataclasses.asdict(r))
        self.assertNotIn("SECRET", dumped)
        self.assertNotIn(str(self.ledger), dumped)
        self.assertEqual(tuple(f.name for f in dataclasses.fields(rp.PromotionReadiness)), READINESS_FIELDS)


# ---------------------------------------------------------------------------
# Delegation and input refusal
# ---------------------------------------------------------------------------

class DelegationTests(PromotionTestCase):
    def setUp(self):
        super().setUp()
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})

    def test_exactly_one_delegation_with_forwarded_inputs(self):
        worktree, kw = self.kwargs(expected_remote_url=REMOTE_URL, lease_root=self.root / "leases", max_paths=17)
        with mock.patch.object(rr, "analyze_reconciliation", wraps=rr.analyze_reconciliation) as analyze, \
                mock.patch.object(ri, "assess_integration", wraps=ri.assess_integration) as fcp1:
            r = rp.assess_promotion_readiness(worktree, **kw)
        self.assertReadiness(r, rp.AWAITING_HUMAN_APPROVAL)
        analyze.assert_called_once_with(worktree, **kw)
        self.assertIs(analyze.call_args.kwargs["evidence"], kw["evidence"])
        self.assertIs(analyze.call_args.kwargs["authorized_scopes"], kw["authorized_scopes"])
        self.assertEqual(fcp1.call_count, 1)  # only FCP-2B's own FCP-1 pass

    def test_stale_delegation_reassesses_only_inside_fcp2b(self):
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        with mock.patch.object(rr, "analyze_reconciliation", wraps=rr.analyze_reconciliation) as analyze, \
                mock.patch.object(ri, "assess_integration", wraps=ri.assess_integration) as fcp1:
            r = self.assess()
        self.assertReadiness(r, rp.RECONCILIATION_REVIEW_REQUIRED)
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(fcp1.call_count, 2)  # FCP-2B's assessment and drift re-assessment

    def test_invalid_max_paths_refused_before_any_read(self):
        for value in (True, False, 0, -1, rr.MAX_PATHS + 1, 10 ** 30, 1.0, "8", None):
            with self.subTest(value=value), \
                    mock.patch.object(rr, "analyze_reconciliation") as analyze, \
                    mock.patch.object(ri, "assess_integration") as fcp1, \
                    mock.patch.object(ri, "_git") as git:
                with self.assertRaises(rr.ReconciliationInputError):
                    self.assess(max_paths=value)
                analyze.assert_not_called()
                fcp1.assert_not_called()
                git.assert_not_called()
        # FCP-2B's own refusal is preserved unchanged for the same values.
        with self.assertRaises(rr.ReconciliationInputError):
            self.analyze(max_paths=True)

    def test_malformed_inputs_refused_before_any_read(self):
        cases = (
            dict(worktree=None), dict(worktree=""), dict(worktree=42), dict(worktree="bad\0path"),
            dict(authorized_scopes="src"), dict(authorized_scopes=None), dict(authorized_scopes=("src", 1)),
            dict(attested_sha=123), dict(expected_remote_url=b"https://x"), dict(ledger_root=5),
            dict(lease_root=""),
        )
        for case in cases:
            worktree, kw = self.kwargs()
            worktree = case.pop("worktree", worktree)
            kw.update(case)
            with self.subTest(case=case), mock.patch.object(rr, "analyze_reconciliation") as analyze:
                with self.assertRaises(rp.PromotionInputError):
                    rp.assess_promotion_readiness(worktree, **kw)
                analyze.assert_not_called()

    def test_delegate_failure_is_blocked_without_detail(self):
        with mock.patch.object(rr, "analyze_reconciliation", side_effect=RuntimeError("secret detail")) as analyze:
            r = self.assess()
        analyze.assert_called_once()
        self.assertBlocked(r, rp.PROMO_RECONCILIATION_FAILED)
        self.assertIsNone(r.reconciliation_fingerprint)
        self.assertNotIn("secret", json.dumps(dataclasses.asdict(r)))
        with mock.patch.object(rr, "analyze_reconciliation", side_effect=rr.ReconciliationInputError("refused")):
            with self.assertRaises(rr.ReconciliationInputError):
                self.assess()

    def test_delegate_returning_garbage_is_blocked(self):
        for garbage in (None, {}, "AWAITING_HUMAN_APPROVAL", object()):
            with self.subTest(garbage=garbage), mock.patch.object(rr, "analyze_reconciliation", return_value=garbage):
                self.assertBlocked(self.assess(), rp.PROMO_MALFORMED_ANALYSIS)


# ---------------------------------------------------------------------------
# Tampered / inconsistent facts (pure classification of real analyses)
# ---------------------------------------------------------------------------

def _with_assessment(analysis, **candidate_or_assessment):
    """The analysis with its FCP-1 assessment altered (the FCP-2B fingerprint
    does not cover the embedded assessment, so it stays valid)."""
    a = analysis.assessment
    candidate_fields = {k: v for k, v in candidate_or_assessment.items()
                        if k in {f.name for f in dataclasses.fields(ri.IntegrationCandidate)}}
    assessment_fields = {k: v for k, v in candidate_or_assessment.items() if k not in candidate_fields}
    a = dataclasses.replace(a, candidate=dataclasses.replace(a.candidate, **candidate_fields), **assessment_fields)
    return dataclasses.replace(analysis, assessment=a)


def _refingerprinted(analysis, **changes):
    draft = dataclasses.replace(analysis, **changes)
    return dataclasses.replace(draft, fingerprint=rr._digest(rr._analysis_payload(draft)))


class TamperTests(PromotionTestCase):
    def setUp(self):
        super().setUp()
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.eligible = self.analyze()
        self.assertReadiness(rp.classify_promotion_readiness(self.eligible), rp.AWAITING_HUMAN_APPROVAL)

    def stale(self):
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        analysis = self.analyze()
        self.assertReadiness(rp.classify_promotion_readiness(analysis), rp.RECONCILIATION_REVIEW_REQUIRED)
        return analysis

    def test_not_an_analysis(self):
        for value in (None, {}, "x", dataclasses.asdict(self.eligible), self.eligible.assessment):
            with self.subTest(value=type(value)):
                self.assertBlocked(rp.classify_promotion_readiness(value), rp.PROMO_MALFORMED_ANALYSIS)

    def test_analysis_fingerprint_tampered(self):
        forged = dataclasses.replace(self.eligible, head_ref="refs/heads/other")
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_ANALYSIS_TAMPERED)
        self.assertBlocked(rp.classify_promotion_readiness(dataclasses.replace(self.eligible, fingerprint="0" * 64)),
                           rp.PROMO_ANALYSIS_TAMPERED)

    def test_analysis_claims_authorization(self):
        for change in (dict(authorizes_action=True), dict(human_approval_required=False),
                       dict(schema="other"), dict(classification="APPROVED")):
            with self.subTest(change=change):
                self.assertBlocked(rp.classify_promotion_readiness(_refingerprinted(self.eligible, **change)),
                                   rp.PROMO_ANALYSIS_TAMPERED)

    def test_assessment_tampered(self):
        a = self.eligible.assessment
        for change in (dict(classification=ri.STALE_BASE), dict(fingerprint="0" * 64), dict(reason_codes=("X",)),
                       dict(eligible=False), dict(human_approval_required=False)):
            with self.subTest(change=change):
                forged = dataclasses.replace(self.eligible, assessment=dataclasses.replace(a, **change))
                self.assertBlocked(rp.classify_promotion_readiness(forged))
        forged = dataclasses.replace(self.eligible, assessment=None)
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_MALFORMED_ASSESSMENT)
        forged = dataclasses.replace(self.eligible, assessment=dataclasses.replace(a, candidate={"clean": True}))
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_MALFORMED_ASSESSMENT)

    def test_fingerprint_bound_candidate_fact_tampered(self):
        forged = _with_assessment(self.eligible, head_sha="0" * 40)
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_ASSESSMENT_TAMPERED)

    def test_provenance_mismatch(self):
        for change in (dict(head_sha="0" * 40), dict(worktree_key="elsewhere"), dict(base_sha="1" * 40),
                       dict(merge_bases=()), dict(assessment_fingerprint="2" * 64)):
            with self.subTest(change=change):
                r = rp.classify_promotion_readiness(_refingerprinted(self.eligible, **change))
                self.assertBlocked(r)
                self.assertTrue({rp.PROMO_PROVENANCE_MISMATCH, rp.PROMO_ASSESSMENT_MISMATCH} & set(r.reason_codes))

    def test_unfingerprinted_safety_facts_are_reconfirmed(self):
        # None of these facts is covered by the FCP-1 fingerprint, so only
        # FCP-1's own predicates, re-applied here, can catch them.
        for change in (dict(clean=None), dict(clean=False), dict(staged_paths=("src/a.py",)),
                       dict(lease_acquired=False), dict(protected_branch=None), dict(shallow=None),
                       dict(partial_clone=True), dict(duplicate_checkouts=("x",)), dict(drift_reasons=("HEAD_DRIFT",)),
                       dict(read_errors=("boom",)), dict(replace_refs=("refs/replace/x",))):
            with self.subTest(change=change):
                r = rp.classify_promotion_readiness(_with_assessment(self.eligible, **change))
                self.assertBlocked(r, rp.PROMO_SAFETY_UNPROVEN)
                self.assertNotIn("boom", json.dumps(dataclasses.asdict(r)))

    def test_ledger_facts_are_required(self):
        for change in (dict(ledger_checked=False), dict(ledger_error="x"), dict(active_workers=(("p", "w"),))):
            with self.subTest(change=change):
                self.assertBlocked(rp.classify_promotion_readiness(_with_assessment(self.eligible, **change)),
                                   rp.PROMO_LEDGER_NOT_CHECKED)

    def test_evidence_binding_tampered(self):
        a = self.eligible.assessment
        evidence = dataclasses.replace(a.evidence, status=ri.EVIDENCE_STALE)
        forged = dataclasses.replace(self.eligible, assessment=dataclasses.replace(a, evidence=evidence))
        self.assertBlocked(rp.classify_promotion_readiness(forged))

    def test_eligible_with_non_matching_fcp2b_is_inconsistent(self):
        a = self.eligible.assessment
        for classification in (rr.NO_TEXTUAL_CONFLICT, rr.SEMANTIC_REVIEW_REQUIRED, rr.HUMAN_REQUIRED):
            with self.subTest(classification=classification):
                forged = rr._result(classification, [rr.RECON_NO_TEXTUAL_CONFLICT], assessment=a)
                self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_INCONSISTENT_CLASSIFICATION)
        forged = _refingerprinted(self.eligible, reason_codes=(rr.RECON_NOT_APPLICABLE,))
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_INCONSISTENT_CLASSIFICATION)

    def test_stale_with_not_applicable_or_fail_closed(self):
        analysis = self.stale()
        a = analysis.assessment
        forged = rr._result(rr.NOT_APPLICABLE, [rr.RECON_NOT_APPLICABLE], assessment=a)
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_INCONSISTENT_CLASSIFICATION)
        forged = rr._result(rr.FAIL_CLOSED, [rr.RECON_ASSESSMENT_DRIFT], assessment=a, facts=analysis.facts)
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_RECONCILIATION_FAIL_CLOSED)
        forged = _refingerprinted(analysis, semantic_validation_required=False)
        self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_INCONSISTENT_CLASSIFICATION)

    def test_stale_reassessment_facts_tampered(self):
        analysis = self.stale()
        for change in (dict(reassessment_classification=ri.ELIGIBLE_PENDING_APPROVAL),
                       dict(reassessment_fingerprint="0" * 64), dict(reassessment_fingerprint=None),
                       dict(read_errors=((rr.RECON_READ_FAILED, "x"),)), dict(assessment_fingerprint="1" * 64)):
            with self.subTest(change=change):
                forged = _refingerprinted(analysis, facts=dataclasses.replace(analysis.facts, **change))
                self.assertBlocked(rp.classify_promotion_readiness(forged), rp.PROMO_REASSESSMENT_UNPROVEN)
        self.assertBlocked(rp.classify_promotion_readiness(_refingerprinted(analysis, facts=None)),
                           rp.PROMO_REASSESSMENT_UNPROVEN)

    def test_stale_unfingerprinted_safety_fact_reconfirmed(self):
        analysis = self.stale()
        self.assertBlocked(rp.classify_promotion_readiness(_with_assessment(analysis, clean=None)),
                           rp.PROMO_SAFETY_UNPROVEN)

    def test_fcp2b_fail_closed_without_assessment(self):
        failed = rr.classify_reconciliation(None, rr.ReconciliationFacts(
            read_errors=((rr.RECON_ASSESSMENT_FAILED, "secret boom"),)))
        r = rp.classify_promotion_readiness(failed)
        self.assertBlocked(r, rp.PROMO_RECONCILIATION_FAIL_CLOSED, "FCP2B_FAIL_CLOSED")
        self.assertIsNone(r.assessment_fingerprint)
        self.assertNotIn("secret", json.dumps(dataclasses.asdict(r)))


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

class StructureTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def test_no_git_process_network_or_fcp1_entry_points(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        imports = {a.name for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names} | {n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("subprocess", "socket", "runner_git", "runner_pipeline", "runner_factory_ledger",
                       "urllib", "http", "requests", "shutil"):
            self.assertNotIn(banned, imports)
        for banned in ("assess_integration", "inspect_candidate", "resolve_canonical_base", "classify_integration",
                       "_git", "_read_facts", "classify_reconciliation", "propose_reconciliation_plan", "run",
                       "Popen", "system", "write_text", "write_bytes", "mkdir", "unlink", "open"):
            self.assertNotIn(banned, attrs | names, banned)

    def test_single_delegation_site(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "analyze_reconciliation"]
        self.assertEqual(len(calls), 1)
        self.assertEqual({k.arg for k in calls[0].keywords}, {
            "attested_sha", "authorized_scopes", "expected_remote_url", "evidence", "ledger_root", "lease_root",
            "max_paths"})

    def test_no_mutation_or_approval_surface(self):
        public = {n.name for n in self.tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")}
        self.assertEqual(public, {"PromotionReadiness", "PromotionInputError", "readiness_fingerprint",
                                  "classify_promotion_readiness", "assess_promotion_readiness"})
        for name in READINESS_FIELDS:
            self.assertFalse(any(word in name for word in ("token", "callback", "approve", "approved", "intent")))
        self.assertTrue(dataclasses.fields(rp.PromotionReadiness))
        self.assertTrue(rp.PromotionReadiness.__dataclass_params__.frozen)


if __name__ == "__main__":
    unittest.main()
