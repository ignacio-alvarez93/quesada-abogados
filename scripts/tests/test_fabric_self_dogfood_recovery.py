"""FCP-12A-04: Self-Dogfood failure recovery contract V1 - non-binding
failure classification and fail-closed recovery-handoff check. Offline,
synthetic Runner-shaped records only: the diagnostics, advisories and
Director decisions are produced by the REAL FCP-6A / FCP-6B / Director
classifiers over them (mocks prove regressions, never a real recovery)."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import inspect
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as cr
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_director as fd
from scripts.ai import fabric_self_dogfood_contract as dc
from scripts.ai import fabric_self_dogfood_guardrails as g
from scripts.ai import fabric_self_dogfood_recovery as r
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_recovery_advisory as ra

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_self_dogfood_recovery.py"
TEST_PATH = Path(__file__).resolve()

PID = "fcp12-self-dogfood-night-20261103-v1"
WID = "wo04_recovery"
PROVIDER = "claude"
RUN_ID = "fdb-fcp12-wo04-recovery"
LEAF = "20261103T231500Z_0123abcd"
BASE = "a" * 40
ATTEMPT_BASE = "b" * 40
OTHER = "d" * 40
SHA = "e" * 64
COMMON = "C:/Users/Op/Desktop/IGNACIO/quesada-abogados/.git"
CONTROLLER = "C:/Users/Op/Desktop/IGNACIO/fcp12-nightshift-runtime/controller-fcp12-stable-v1"
TARGET = "C:/Users/Op/Desktop/IGNACIO/quesada-fcp12-self-dogfood-v1"
STATE = "C:/Users/Op/fabric-state"
EVIDENCE_DIR = STATE + "/_evidence/0123456789abcdef01234567/" + LEAF
BRANCH = "feature/fcp12-self-dogfood-v1"
SCOPES = ("scripts/ai/fabric_self_dogfood_recovery.py", "scripts/tests/test_fabric_self_dogfood_recovery.py")
DIRTY_IN_SCOPE = " M scripts/ai/fabric_self_dogfood_recovery.py\n"
ALL_FLAGS = (
    "certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
    "auto_retry_allowed", "resume_allowed", "release_allowed", "human_approval_granted", "host_ci_verified",
    "closure_complete", "git_allowed", "ledger_write_allowed", "binding_decision", "recovery_executed",
    "pipeline_submission_allowed", "commit_allowed", "rollback_allowed",
)

# Runner-shaped worker outcomes: (state, state_reason, outcome, code, runner_state, retry_decision, extra attempt).
TIMEOUT_EXHAUSTED = ("FAILED", "MAX_ATTEMPTS_EXHAUSTED", "FAILED", "MAX_ATTEMPTS_EXHAUSTED", "TIMEOUT",
                     "NO_RETRY:MAX_ATTEMPTS_EXHAUSTED")
PARTIAL = ("PARTIAL", None, "PARTIAL", None, "PARTIAL", "NO_RETRY:PARTIAL")
QUOTA = ("WAITING_PROVIDER_QUOTA", "PROVIDER_QUOTA_EXHAUSTED", "WAITING_PROVIDER_QUOTA", "PROVIDER_QUOTA_EXHAUSTED",
         "CLAUDE_ERROR", "WAIT:PROVIDER_QUOTA_EXHAUSTED:next=2026-11-04T01:00:00+00:00")
SAFETY = ("FAILED", "FAILED_SAFETY", "FAILED", "FAILED_SAFETY", "FAILED_SAFETY", "NO_RETRY:NON_TRANSIENT:FAILED_SAFETY")
NATIVE_FAILED = ("FAILED", "CLAUDE_ERROR", "FAILED", "CLAUDE_ERROR", "CLAUDE_ERROR",
                 "NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR")


def records(outcome=TIMEOUT_EXHAUSTED, *, attempt=None, result=None, summary=None):
    state, reason, out, code, runner_state, retry = outcome
    last = {
        "attempt": 1, "provider": PROVIDER, "started_at_utc": "2026-11-03T23:15:00+00:00",
        "ended_at_utc": "2026-11-03T23:45:00+00:00", "status": "COMPLETED", "executed": True,
        "runner_state": runner_state, "work_status": None, "provider_work_status": None,
        "work_status_source": None, "evidence_dir": EVIDENCE_DIR, "retry_decision": retry, "run_id": LEAF,
        "evidence_complete": True, "process_confirmed_stopped": True,
    }
    last.update(attempt or {})
    res = {
        "worker_id": WID, "pipeline_id": PID, "state": state, "state_reason": reason, "provider": PROVIDER,
        "requested_provider": PROVIDER, "mode": "write", "worktree": TARGET, "runner_state": runner_state,
        "work_status": None, "provider_work_status": None, "work_status_source": None, "attempts": [last],
        "fallbacks_used": [], "evidence_dir": EVIDENCE_DIR,
        "artifacts": [EVIDENCE_DIR + "/metadata.json", EVIDENCE_DIR + "/result.json",
                      EVIDENCE_DIR + "/work_product.json"],
        "preflight": STATE + "/" + PID + "/workers/" + WID + "/preflight.json", "metadata": {},
        "written_at_utc": "2026-11-03T23:45:01+00:00", "outcome": out, "code": code,
    }
    res.update(result or {})
    summ = {
        "id": WID, "provider": PROVIDER, "requested_provider": PROVIDER, "state": state, "state_reason": reason,
        "attempts": 1, "work_attempts_used": 1, "availability_attempts": 0,
        "provider_condition": "PROVIDER_QUOTA_EXHAUSTED" if state == "WAITING_PROVIDER_QUOTA" else None,
        "next_eligible_utc": None, "result_path": STATE + "/" + PID + "/workers/" + WID + "/result.json",
        "worker_path": STATE + "/" + PID + "/workers/" + WID + "/worker.json", "checkpoint_policy": "ON_SUCCESS",
        "checkpoint_commit": None,
    }
    summ.update(summary or {})
    return res, summ


def evidence(outcome=TIMEOUT_EXHAUSTED, *, diagnostic_of=None, **changes):
    res, summ = records(outcome, **changes)
    if "drop_result" in changes:
        res = None
    src_res, src_summ = diagnostic_of if diagnostic_of is not None else (res, summ)
    diag = fi.assess_worker(WID, src_res, pipeline_id=PID, summary=src_summ, summary_index=0)
    return r.FailureEvidence(pipeline_id=PID, worker_id=WID, provider_id=PROVIDER, result=res, summary=summ,
                             diagnostic=diag, advisory=ra.advise_worker(diag))


def plan(**overrides):
    values = dict(base_commit=BASE, controller_commit=BASE, controller_path=CONTROLLER, target_path=TARGET,
                  target_branch=BRANCH, attempt_base_head=ATTEMPT_BASE, authorized_scopes=SCOPES)
    values.update(overrides)
    return g.IsolationPlan(**values)


def controller(**overrides):
    values = dict(declared_path=CONTROLLER, resolved_path=CONTROLLER, link_component_observed=False,
                  git_dir=COMMON + "/worktrees/controller-fcp12-stable-v1", git_common_dir=COMMON, branch="HEAD",
                  head=BASE, porcelain_status="")
    values.update(overrides)
    return g.WorktreeSnapshot(**values)


def target(**overrides):
    values = dict(declared_path=TARGET, resolved_path=TARGET, link_component_observed=False,
                  git_dir=COMMON + "/worktrees/quesada-fcp12-self-dogfood-v1", git_common_dir=COMMON,
                  branch=BRANCH, head=ATTEMPT_BASE, porcelain_status="")
    values.update(overrides)
    return g.WorktreeSnapshot(**values)


def guardrails(**overrides):
    values = dict(schema_version=1, action=g.ACTION_CONFIRM_ISOLATION, plan=plan(),
                  process=g.ControllerProcess(module_path=CONTROLLER + "/scripts/ai/runner_pipeline.py",
                                              worktree_top=CONTROLLER),
                  controller_before=controller(), target_before=target(), controller_after=controller(),
                  target_after=target(porcelain_status=DIRTY_IN_SCOPE))
    values.update(overrides)
    return g.GuardrailRequest(**values)


def director_decision(worker_state="FAILED", **overrides):
    """The Director's own `_classify_decision` over projected fields."""
    summary = fd.DirectorRunSummary(run_id=RUN_ID, pipeline_id=PID, worker_id=WID, worker_state=worker_state,
                                    evidence_complete=True, work_product_present=True)
    run_evidence = fd.DirectorRunEvidence(run_id=RUN_ID, safety_verdict="SAFE", evidence_complete=True)
    decision = fd._classify_decision(summary, run_evidence)
    return dataclasses.replace(decision, **overrides) if overrides else decision


def work_product_ref(**overrides):
    values = dict(kind="ATTEMPT_WORK_PRODUCT", condition=cp.PRESENT, pipeline_id=PID, worker_id=WID,
                  attempt_leaf=LEAF, cause=None, content_sha256=SHA, size_bytes=512)
    values.update(overrides)
    return cp.EvidenceRef(**values)


def handoff(worker_state="FAILED", **overrides):
    values = dict(schema_version=1, action=r.DIRECTOR_RECOVERY_ACTION, prior_run_id=RUN_ID, pipeline_id=PID,
                  worker_id=WID, provider_id=PROVIDER, attempt=1, attempt_leaf=LEAF, base_head=ATTEMPT_BASE,
                  work_product=work_product_ref(), director_decision=director_decision(worker_state))
    values.update(overrides)
    return r.RecoveryHandoff(**values)


def request(action=r.ACTION_REQUEST_HANDOFF, ev=None, **overrides):
    values = dict(schema_version=1, action=action, evidence=ev if ev is not None else evidence(),
                  guardrails=guardrails(), handoff=handoff() if action == r.ACTION_REQUEST_HANDOFF else None)
    values.update(overrides)
    return r.RecoveryRequest(**values)


def classify(ev, **overrides):
    return r.assess_recovery(request(r.ACTION_CLASSIFY, ev, **overrides))


class Base(unittest.TestCase):
    def assert_zero_authority(self, assessment):
        payload = json.loads(r.canonical_json(assessment))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(assessment, flag), False, flag)
            self.assertIs(payload[flag], False, flag)
        self.assertEqual(payload["recovery_marker"], r.RECOVERY_MARKER)


class PositiveHandoffTests(Base):
    def test_timeout_exhausted_with_work_product_is_an_admissible_human_handoff(self):
        a = r.assess_recovery(request())
        self.assertEqual((a.decision, a.reasons), (r.HANDOFF_ADMISSIBLE, ()))
        self.assertEqual(a.failure_classes, (r.CLASS_TIMEOUT, r.CLASS_NATIVE_FAILURE))
        self.assertEqual((a.primary_class, a.advisory_category, a.responsibility),
                         (r.CLASS_TIMEOUT, "NATIVE_FAILED", "HUMAN_REVIEW"))
        self.assertEqual(a.next_step, r.NEXT_STEP_HUMAN_THEN_DIRECTOR)
        self.assertRegex(a.binding, r"^[0-9a-f]{64}$")
        self.assertTrue(a.handoff_admissible)
        self.assert_zero_authority(a)

    def test_partial_work_is_admissible_as_correct_work(self):
        ev = evidence(PARTIAL, attempt={"work_status": "PARTIAL", "provider_work_status": "PARTIAL",
                                        "work_status_source": "PROVIDER"},
                      result={"work_status": "PARTIAL", "provider_work_status": "PARTIAL",
                              "work_status_source": "PROVIDER"})
        a = r.assess_recovery(request(ev=ev, handoff=handoff("PARTIAL")))
        self.assertEqual((a.decision, a.failure_classes, a.responsibility),
                         (r.HANDOFF_ADMISSIBLE, (r.CLASS_PARTIAL,), "CORRECT_WORK"))
        self.assertEqual(r.assess_recovery(request(ev=ev, handoff=handoff("PARTIAL"))), a)

    def test_deterministic_and_binding_tracks_the_handoff_facts(self):
        self.assertEqual(r.canonical_json(r.assess_recovery(request())), r.canonical_json(r.assess_recovery(request())))
        moved = r.assess_recovery(request(handoff=handoff(work_product=work_product_ref(content_sha256="f" * 64))))
        self.assertEqual(moved.decision, r.HANDOFF_ADMISSIBLE)
        self.assertNotEqual(moved.binding, r.assess_recovery(request()).binding)
        # The caller's records are only read.
        ev = evidence()
        snapshot = copy.deepcopy((ev.result, ev.summary))
        r.assess_recovery(request(ev=ev))
        self.assertEqual((ev.result, ev.summary), snapshot)


class ClassificationTests(Base):
    def test_quota_is_runner_owned_and_never_a_handoff(self):
        ev = evidence(QUOTA)
        c = classify(ev)
        self.assertEqual((c.decision, c.failure_classes, c.responsibility),
                         (r.CLASSIFIED, (r.CLASS_QUOTA,), "RUNNER_NATIVE"))
        self.assertIsNone(c.next_step)
        a = r.assess_recovery(request(ev=ev, handoff=handoff("WAITING_PROVIDER_QUOTA")))
        self.assertEqual(a.decision, r.DENIED)
        self.assertIn(r.RUNNER_OWNS_RECOVERY, a.reasons)
        self.assertIn(r.DIRECTOR_NOT_ELIGIBLE, a.reasons)  # the Director's own WAITING_PROVIDER
        self.assert_zero_authority(a)

    def test_transient_timeout_retry_wait_is_runner_owned_without_a_result_file(self):
        retry = ("RETRY_WAIT", "TRANSIENT:TIMEOUT", None, None, "TIMEOUT", "RETRY:TRANSIENT:TIMEOUT:backoff=30s")
        _, summ = records(retry, summary={"result_path": None})  # a first-attempt retry wait wrote no result
        diag = fi.assess_worker(WID, None, pipeline_id=PID, summary=summ, summary_index=0)
        self.assertEqual(diag.reason_codes, ("TRANSIENT_RETRY_WAIT",))
        # Without result.json the TIMEOUT token is not observable: never guessed.
        ev = r.FailureEvidence(PID, WID, PROVIDER, None, summ, diag, ra.advise_worker(diag))
        self.assertEqual(classify(ev).failure_classes, (r.CLASS_RUNNER_WAIT,))
        ev_full = evidence(retry, result={"outcome": None, "code": None})
        self.assertEqual(classify(ev_full).failure_classes, (r.CLASS_TIMEOUT, r.CLASS_RUNNER_WAIT))
        for e in (ev, ev_full):
            a = r.assess_recovery(request(r.ACTION_REQUEST_HANDOFF, e, handoff=handoff("RETRY_WAIT")))
            self.assertEqual(a.decision, r.DENIED)
            self.assertIn(r.RUNNER_OWNS_RECOVERY, a.reasons)

    def test_unsafe_state_safety_refusal_and_unresolved_process(self):
        cases = (
            evidence(SAFETY, attempt={"unauthorized_changed_paths": ["scripts/ai/claude_runner.py"]}),
            evidence(NATIVE_FAILED, attempt={"process_confirmed_stopped": False}),
        )
        for ev in cases:
            c = classify(ev)
            self.assertEqual(c.primary_class, r.CLASS_UNSAFE_STATE)
            self.assertIn(r.RUNNER_SAFETY_SIGNAL, c.reasons)
            a = r.assess_recovery(request(ev=ev))
            self.assertEqual(a.decision, r.DENIED)
            self.assertIn(r.RUNNER_SAFETY_SIGNAL, a.reasons)
        self.assertIn(r.PROCESS_NOT_CONFIRMED_STOPPED, r.assess_recovery(request(ev=cases[1])).reasons)
        # Isolation the guardrails cannot prove is unsafe too (dirty controller, symlinked target).
        for rails in (guardrails(controller_after=controller(porcelain_status=" M scripts/ai/runner_git.py\n")),
                      guardrails(target_after=target(link_component_observed=True)),
                      guardrails(action=g.ACTION_ADMIT_ATTEMPT, controller_after=None, target_after=None),
                      None):
            c = classify(evidence(), guardrails=rails)
            self.assertIn(r.CLASS_UNSAFE_STATE, c.failure_classes)
            self.assertIn(r.ISOLATION_NOT_PROVEN, c.reasons)
            self.assertEqual(r.assess_recovery(request(guardrails=rails)).decision, r.DENIED)

    def test_wrong_head_target_or_controller(self):
        cases = (
            (guardrails(target_after=target(head=OTHER, porcelain_status=DIRTY_IN_SCOPE)), r.TARGET_HEAD_UNEXPECTED),
            (guardrails(target_before=target(head=OTHER), target_after=target(head=OTHER)), r.TARGET_HEAD_UNEXPECTED),
            (guardrails(controller_after=controller(head=OTHER)), r.CONTROLLER_HEAD_MOVED),
        )
        for rails, code in cases:
            c = classify(evidence(), guardrails=rails)
            self.assertEqual(c.primary_class, r.CLASS_WRONG_HEAD, code)
            self.assertIn(code, c.reasons)
            a = r.assess_recovery(request(guardrails=rails))
            self.assertEqual(a.decision, r.DENIED)
            self.assertIn(code, a.reasons)
        # A handoff naming another base HEAD than the plan is refused as well.
        self.assertIn(r.HANDOFF_BASE_HEAD_MISMATCH,
                      r.assess_recovery(request(handoff=handoff(base_head=OTHER))).reasons)

    def test_divergent_checkpoints(self):
        cases = (
            dict(ev=evidence(summary={"checkpoint_commit": OTHER})),  # pipeline vs worker result
            dict(ev=evidence(attempt={"checkpoint": {"decision": "CREATED", "commit_hash": OTHER}}),
                 guardrails=guardrails(target_after=target(head=OTHER), target_checkpoint_commit=OTHER)),
            dict(handoff=handoff(checkpoint_commit=OTHER)),
            dict(guardrails=guardrails(target_after=target(head=OTHER), target_checkpoint_commit=OTHER)),
        )
        for case in cases:
            a = r.assess_recovery(request(**case))
            self.assertEqual(a.decision, r.DENIED)
            self.assertEqual(a.primary_class, r.CLASS_DIVERGENT_CHECKPOINTS)
            self.assertTrue({r.CHECKPOINT_SOURCES_DIVERGE, r.CHECKPOINT_WITHOUT_SUCCESS} & set(a.reasons), a.reasons)
        # All sources agree on a commit, yet the worker FAILED: a checkpoint without success.
        agreed = request(ev=evidence(summary={"checkpoint_commit": OTHER},
                                     attempt={"checkpoint": {"decision": "CREATED", "commit_hash": OTHER}}),
                         guardrails=guardrails(target_after=target(head=OTHER), target_checkpoint_commit=OTHER),
                         handoff=handoff(checkpoint_commit=OTHER))
        self.assertIn(r.CHECKPOINT_WITHOUT_SUCCESS, r.assess_recovery(agreed).reasons)

    def test_runner_success_has_nothing_to_recover(self):
        success = ("SUCCESS", None, "SUCCESS", None, "SUCCESS", "NONE:SUCCESS")
        fields = {"work_status": "SUCCESS", "work_status_source": "RUNNER_ACCEPTANCE"}
        ev = evidence(success, attempt=fields, result=fields)
        self.assertEqual(ev.diagnostic.reason_codes, ("SUCCESS_CONSISTENT",))
        c = classify(ev)
        self.assertEqual((c.failure_classes, c.responsibility), ((r.CLASS_NO_FAILURE,), "NONE"))
        a = r.assess_recovery(request(ev=ev, handoff=handoff("SUCCESS")))
        self.assertEqual(a.decision, r.DENIED)
        self.assertTrue({r.NOTHING_TO_RECOVER, r.RESPONSIBILITY_NOT_HUMAN, r.DIRECTOR_NOT_ELIGIBLE} <= set(a.reasons))


class InvalidEvidenceTests(Base):
    def test_unbound_or_forged_diagnostic_is_invalid_and_its_codes_are_ignored(self):
        quota_records = records(QUOTA)
        forged = evidence()
        object.__setattr__(forged.diagnostic, "reason_codes", ("PARTIAL_COMPLETION",))
        cases = (
            evidence(diagnostic_of=quota_records),  # a diagnostic of other records
            forged,
            dataclasses.replace(evidence(), diagnostic=evidence().diagnostic.to_dict()),
            dataclasses.replace(evidence(), diagnostic=None),
        )
        for ev in cases:
            c = classify(ev)
            self.assertIn(r.DIAGNOSTIC_UNBOUND, c.reasons)
            self.assertEqual(c.failure_classes, (r.CLASS_INVALID_EVIDENCE,))  # QUOTA / PARTIAL never read
            self.assertIsNone(c.responsibility)
            self.assertEqual(r.assess_recovery(request(ev=ev)).decision, r.DENIED)

    def test_foreign_or_tampered_advisory_is_refused(self):
        ev = evidence()
        tampered = ra.advise_worker(ev.diagnostic)
        object.__setattr__(tampered, "responsibility", "HUMAN_REVIEW")
        object.__setattr__(tampered, "category", "PARTIAL_COMPLETION")
        partial_ev = evidence(PARTIAL)

        class WorkerRecoveryAdvisory:  # look-alike, wrong module
            pass

        for advisory in (tampered, partial_ev.advisory, ra.advise_worker(None), WorkerRecoveryAdvisory(), None):
            a = r.assess_recovery(request(ev=dataclasses.replace(ev, advisory=advisory)))
            self.assertEqual(a.decision, r.DENIED)
            self.assertIn(r.ADVISORY_UNBOUND, a.reasons)
            self.assertIn(r.CLASS_INVALID_EVIDENCE, a.failure_classes)

    def test_incomplete_or_contradictory_runner_evidence_is_invalid(self):
        cases = (
            evidence(attempt={"evidence_complete": False}),
            evidence(result={"outcome": "SUCCESS"}),  # state FAILED, outcome SUCCESS
            evidence(result={"pipeline_id": "another-pipeline"}),
            evidence(result={"worktree": "C:/Users/Op/Desktop/IGNACIO/some-other-worktree"}),
            evidence(result={"attempts": "not-a-list"}),
        )
        for ev in cases:
            c = classify(ev)
            self.assertEqual(c.primary_class, r.CLASS_INVALID_EVIDENCE, c.reasons)
            self.assertEqual(r.assess_recovery(request(ev=ev)).decision, r.DENIED)
        self.assertIn(r.EVIDENCE_NOT_COMPLETE, r.assess_recovery(request(ev=cases[0])).reasons)
        self.assertIn(r.EVIDENCE_PROVENANCE_MISMATCH, classify(cases[3]).reasons)


class HandoffTests(Base):
    def test_handoff_must_be_structured_and_bound_to_this_attempt(self):
        cases = (
            (None, r.HANDOFF_MISSING),
            ({"action": r.DIRECTOR_RECOVERY_ACTION}, r.HANDOFF_MALFORMED),
            (handoff(schema_version=True), r.HANDOFF_MALFORMED),
            (handoff(attempt="1"), r.HANDOFF_MALFORMED),
            (handoff(action="REVIEW_NATIVE_FAILURE"), r.HANDOFF_ACTION_NOT_CONFIRMED),
            (handoff(action=None), r.HANDOFF_ACTION_NOT_CONFIRMED),
            (handoff(attempt=2), r.HANDOFF_LINEAGE_MISMATCH),
            (handoff(attempt_leaf="20261103T231500Z_ffffffff"), r.HANDOFF_LINEAGE_MISMATCH),
            (handoff(worker_id="wo05_other"), r.HANDOFF_LINEAGE_MISMATCH),
            (handoff(work_product=None), r.WORK_PRODUCT_NOT_REFERENCED),
            (handoff(work_product=work_product_ref(condition=cp.MISSING, cause=cp.SOURCE_ABSENT,
                                                   content_sha256=None, size_bytes=None)),
             r.WORK_PRODUCT_NOT_REFERENCED),
            (handoff(work_product=work_product_ref(attempt_leaf="20261103T231500Z_ffffffff")),
             r.WORK_PRODUCT_NOT_REFERENCED),
        )
        for value, code in cases:
            a = r.assess_recovery(request(handoff=value))
            self.assertEqual(a.decision, r.DENIED, code)
            self.assertIn(code, a.reasons)
        # The Runner never listed a work product for this attempt.
        no_product = evidence(result={"artifacts": [EVIDENCE_DIR + "/metadata.json"]})
        self.assertIn(r.WORK_PRODUCT_NOT_REFERENCED, r.assess_recovery(request(ev=no_product)).reasons)

    def test_director_decision_must_be_typed_matching_and_eligible(self):
        cases = (
            (director_decision().__dict__, r.DIRECTOR_DECISION_NOT_TYPED),
            (director_decision(run_id="fdb-another-run"), r.DIRECTOR_DECISION_MISMATCH),
            (director_decision(worker_state="PARTIAL"), r.DIRECTOR_DECISION_MISMATCH),
            (director_decision(decision_code="READY_FOR_HOST_AUDIT"), r.DIRECTOR_NOT_ELIGIBLE),
            (director_decision(human_action_required=False), r.DIRECTOR_NOT_ELIGIBLE),
        )
        for decision, code in cases:
            a = r.assess_recovery(request(handoff=handoff(director_decision=decision)))
            self.assertEqual(a.decision, r.DENIED, code)
            self.assertIn(code, a.reasons)
        self.assertIn(director_decision().decision_code, fd._RECOVERY_ELIGIBLE_DECISION_CODES)

    def test_runner_preconditions_are_required(self):
        read_only = evidence(result={"mode": "read-only"})
        self.assertIn(r.NOT_WRITE_MODE, r.assess_recovery(request(ev=read_only)).reasons)
        # Dirty paths outside the authorized scope: the Runner's scope rule refuses them.
        rails = guardrails(target_after=target(porcelain_status=" M scripts/ai/runner_pipeline.py\n"))
        a = r.assess_recovery(request(guardrails=rails))
        self.assertEqual(a.decision, r.DENIED)
        self.assertIn(r.ISOLATION_NOT_PROVEN, a.reasons)

    def test_automation_and_external_authority_are_refused(self):
        for ops, code in ((("AUTO_COMMIT",), r.AUTOMATION_FORBIDDEN), (("ROLLBACK", "RESET"), r.AUTOMATION_FORBIDDEN),
                          (("AUTO_SUBMIT_PIPELINE",), r.AUTOMATION_FORBIDDEN), (("SOMETHING_NEW",), r.HANDOFF_MALFORMED)):
            a = r.assess_recovery(request(handoff=handoff(requested_operations=ops)))
            self.assertEqual(a.decision, r.DENIED)
            self.assertIn(code, a.reasons)
        a = r.assess_recovery(request(external_authorization={"approved_by": "someone"}))
        self.assertEqual(a.decision, r.DENIED)
        self.assertIn(r.EXTERNAL_AUTHORIZATION_NOT_ACCEPTED, a.reasons)
        # Even over a clean, admissible situation, automated recovery is always refused.
        auto = r.assess_recovery(request(r.ACTION_AUTO_RECOVER))
        self.assertEqual((auto.decision, auto.reasons), (r.DENIED, (r.AUTOMATED_RECOVERY_FORBIDDEN,)))
        self.assertIsNone(auto.binding)
        self.assert_zero_authority(auto)


class InvalidAndCorruptInputTests(Base):
    def test_invalid_requests(self):
        for value, code in ((None, r.REQUEST_NOT_TYPED), ({"action": "CLASSIFY"}, r.REQUEST_NOT_TYPED),
                            (request(schema_version=True), r.SCHEMA_UNSUPPORTED),
                            (request(schema_version="1"), r.SCHEMA_UNSUPPORTED),
                            (request(action="RETRY_NOW"), r.ACTION_UNKNOWN),
                            (request(action=["CLASSIFY"]), r.ACTION_UNKNOWN),
                            (request(r.ACTION_CLASSIFY, handoff=handoff()), r.HANDOFF_NOT_EXPECTED)):
            a = r.assess_recovery(value)
            self.assertEqual(a.decision, r.INVALID_REQUEST)
            self.assertIn(code, a.reasons)
            self.assertEqual((a.failure_classes, a.binding, a.responsibility), ((), None, None))

    def test_corrupt_and_hostile_inputs_never_raise_and_never_admit(self):
        class Hostile:
            def __eq__(self, other):
                raise RuntimeError("foreign code")

            __hash__ = object.__hash__

            def get(self, *_):
                raise RuntimeError("foreign code")

        res, summ = records()
        corrupt = (
            r.FailureEvidence(PID, WID, PROVIDER, Hostile(), summ, None, None),
            r.FailureEvidence(PID, WID, PROVIDER, res, Hostile(), None, None),
            r.FailureEvidence("../escape", WID, PROVIDER, res, summ, None, None),
            r.FailureEvidence(PID, WID, Hostile(), res, summ, None, None),
            evidence(result={"state": Hostile()}),
            evidence(attempt={"run_id": Hostile(), "checkpoint": Hostile()}),
            evidence(summary={"checkpoint_commit": ["not", "a", "commit"]}),
            evidence(result={"checkpoint": {"commit_hash": "zz"}}),
            "not evidence", None, 42,
        )
        for ev in corrupt:
            for action in (r.ACTION_CLASSIFY, r.ACTION_REQUEST_HANDOFF, r.ACTION_AUTO_RECOVER):
                a = r.assess_recovery(request(action, ev) if ev is not None else request(action, evidence=None))
                self.assertIn(a.decision, (r.CLASSIFIED, r.DENIED), (ev, action))
                self.assertIn(r.CLASS_INVALID_EVIDENCE, a.failure_classes)
                self.assert_zero_authority(a)
        for rails in (Hostile(), "rails", guardrails(plan=Hostile()), guardrails(target_after=Hostile())):
            a = r.assess_recovery(request(guardrails=rails))
            self.assertEqual(a.decision, r.DENIED)
        hostile_handoff = handoff(director_decision=Hostile(), work_product=Hostile(),
                                  requested_operations=(Hostile(),))
        self.assertEqual(r.assess_recovery(request(handoff=hostile_handoff)).decision, r.DENIED)

    def test_assessment_cannot_be_forged(self):
        with self.assertRaises(ValueError):  # a blocking class is never admissible
            r.RecoveryAssessment(decision=r.HANDOFF_ADMISSIBLE, reasons=(), action=r.ACTION_REQUEST_HANDOFF,
                                 failure_classes=(r.CLASS_QUOTA,), responsibility="HUMAN_REVIEW", binding="0" * 64)
        with self.assertRaises(ValueError):  # a Runner-owned responsibility is never admissible
            r.RecoveryAssessment(decision=r.HANDOFF_ADMISSIBLE, reasons=(), action=r.ACTION_REQUEST_HANDOFF,
                                 failure_classes=(r.CLASS_TIMEOUT,), responsibility="RUNNER_NATIVE", binding="0" * 64)
        with self.assertRaises(ValueError):  # AUTO_RECOVER can never be admissible
            r.RecoveryAssessment(decision=r.HANDOFF_ADMISSIBLE, reasons=(), action=r.ACTION_AUTO_RECOVER,
                                 failure_classes=(r.CLASS_TIMEOUT,), responsibility="HUMAN_REVIEW", binding="0" * 64)
        with self.assertRaises(ValueError):
            r.RecoveryAssessment(decision=r.DENIED, reasons=(), action=r.ACTION_REQUEST_HANDOFF,
                                 failure_classes=(r.CLASS_TIMEOUT,))
        with self.assertRaises(ValueError):
            r.RecoveryAssessment(decision=r.CLASSIFIED, reasons=("APPROVED",), action=r.ACTION_CLASSIFY,
                                 failure_classes=(r.CLASS_TIMEOUT,))
        with self.assertRaises(TypeError):
            r.canonical_json(r.assess_recovery(request()).to_dict())
        a = r.assess_recovery(request())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.decision = r.DENIED  # type: ignore[misc]

    def test_sibling_contract_version_drift_fails_closed(self):
        for target_module, name in ((dc, "SCHEMA"), (g, "SCHEMA_VERSION")):
            with mock.patch.object(target_module, name, "fcp12-future" if name == "SCHEMA" else 2):
                a = r.assess_recovery(request())
                self.assertEqual(a.decision, r.DENIED)
                self.assertIn(r.CONTRACT_VERSION_UNSUPPORTED, a.reasons)
                self.assertEqual(a.primary_class, r.CLASS_INVALID_EVIDENCE)


class ReuseAndPurityTests(unittest.TestCase):
    def test_mirrors_are_pinned_to_the_real_fcp6_runner_and_director(self):
        self.assertEqual(r.RA_CATEGORY_RULES, ra.CATEGORY_RULES)
        self.assertEqual(r.RA_REASON_CATEGORY, ra._REASON_CATEGORY)
        self.assertEqual(r.RA_RESPONSIBILITIES, ra.RESPONSIBILITIES)
        self.assertEqual((r.RA_SCHEMA_WORKER, r.RA_ADVISORY_MARKER), (ra.SCHEMA_WORKER, ra.ADVISORY_MARKER))
        self.assertEqual(r.RA_ADVISORY_TYPE, ra.WorkerRecoveryAdvisory.__name__)
        self.assertEqual(set(r.RA_ZERO_AUTHORITY_FLAGS), set(ra.advise_worker(None)._guarantees()) - {"marker"})
        self.assertEqual(set(r._FI_CLASS), set(fi.REASON_PRECEDENCE))
        self.assertEqual(r._TIMEOUT, cr.RunState.TIMEOUT.value)
        self.assertIn(repr(r.DIRECTOR_RECOVERY_ACTION), inspect.getsource(fd.FabricDirectorService.recover))
        # The FCP-6B vocabulary can never confirm a Director recovery by itself.
        self.assertNotIn(r.DIRECTOR_RECOVERY_ACTION, {o for _, o in ra.CATEGORY_RULES.values()})

    def test_module_imports_no_side_effect_library_and_respects_the_fcp6c04_guard(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.rsplit(".", 1)[-1] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported |= {node.module.rsplit(".", 1)[-1]} | {a.name for a in node.names}
        for forbidden in ("os", "subprocess", "socket", "shutil", "pathlib", "urllib", "http", "time", "random",
                          "datetime", "threading", "runner_git", "runner_pipeline", "runner_failure_intelligence",
                          "runner_recovery_advisory", "runner_promotion", "runner_factory_ledger"):
            self.assertNotIn(forbidden, imported)
        called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("PipelineRunner", "recover", "submit", "run", "create_checkpoint", "evaluate_resume",
                          "execute_work_order", "open", "sleep"):
            self.assertNotIn(forbidden, called)

    def test_assessment_performs_no_io_process_git_or_network(self):
        boom = mock.Mock(side_effect=AssertionError("side effect"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(os, "system", boom), mock.patch.object(Path, "resolve", boom), \
                mock.patch.object(os.path, "realpath", boom), \
                mock.patch.object(fd.FabricDirectorService, "recover", boom), \
                mock.patch.object(cr, "evaluate_resume", boom), mock.patch.object(cr, "create_checkpoint", boom):
            self.assertEqual(r.assess_recovery(request()).decision, r.HANDOFF_ADMISSIBLE)
            self.assertEqual(r.assess_recovery(request(r.ACTION_AUTO_RECOVER)).decision, r.DENIED)
            self.assertEqual(r.assess_recovery(request(r.ACTION_CLASSIFY, evidence(QUOTA))).decision, r.CLASSIFIED)
        boom.assert_not_called()

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest", "xfail"):
            self.assertNotIn(forbidden, names)


if __name__ == "__main__":
    unittest.main()
