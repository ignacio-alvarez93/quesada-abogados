"""FCP-12A-05: Self-Dogfood end-to-end certification evaluator V1 - only
READY_FOR_HOST_AUDIT or BLOCKED. Offline: Runner evidence is the FCP-12A-03
real-shaped on-disk fixture read by the real reader; guardrail snapshots are
synthetic facts. Mocks prove regressions, never a real dogfood run."""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_self_dogfood_certification as fc
from scripts.ai import fabric_self_dogfood_evidence as ev
from scripts.ai import fabric_self_dogfood_guardrails as g
from scripts.ai import fabric_validation_contract as vc
from scripts.tests.test_fabric_self_dogfood_evidence import BASE as ATTEMPT_BASE
from scripts.tests.test_fabric_self_dogfood_evidence import BRANCH, COMMIT, PID, PROVIDER, SCOPES, WID, Fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_self_dogfood_certification.py"

FCP11_BASE = "a" * 40
OTHER = "8" * 40
COMMON = "C:/Users/Op/Desktop/IGNACIO/quesada-abogados/.git"
CONTROLLER = "C:/Users/Op/Desktop/IGNACIO/fcp12-nightshift-runtime/controller-fcp12-stable-v1"
TARGET = "C:/Users/Op/Desktop/IGNACIO/quesada-fcp12-self-dogfood-v1"
ALL_FLAGS = (
    "certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
    "auto_retry_allowed", "resume_allowed", "release_allowed", "human_approval_granted", "host_ci_verified",
    "closure_complete", "git_allowed", "ledger_write_allowed", "binding_decision", "merge_performed",
    "host_audit_performed", "host_ci_assumed", "audit_verified", "rollback_allowed", "external_claims_accepted",
)


def plan(**overrides):
    values = dict(base_commit=FCP11_BASE, controller_commit=FCP11_BASE, controller_path=CONTROLLER,
                  target_path=TARGET, target_branch=BRANCH, attempt_base_head=ATTEMPT_BASE,
                  authorized_scopes=tuple(SCOPES))
    values.update(overrides)
    return g.IsolationPlan(**values)


def controller(**overrides):
    values = dict(declared_path=CONTROLLER, resolved_path=CONTROLLER, link_component_observed=False,
                  git_dir=COMMON + "/worktrees/controller-fcp12-stable-v1", git_common_dir=COMMON, branch="HEAD",
                  head=FCP11_BASE, porcelain_status="")
    values.update(overrides)
    return g.WorktreeSnapshot(**values)


def target_snapshot(**overrides):
    values = dict(declared_path=TARGET, resolved_path=TARGET, link_component_observed=False,
                  git_dir=COMMON + "/worktrees/quesada-fcp12-self-dogfood-v1", git_common_dir=COMMON,
                  branch=BRANCH, head=ATTEMPT_BASE, porcelain_status="")
    values.update(overrides)
    return g.WorktreeSnapshot(**values)


def guardrails(**overrides):
    values = dict(schema_version=1, action=g.ACTION_CONFIRM_ISOLATION, plan=plan(),
                  process=g.ControllerProcess(module_path=CONTROLLER + "/scripts/ai/runner_pipeline.py",
                                              worktree_top=CONTROLLER),
                  controller_before=controller(), target_before=target_snapshot(), controller_after=controller(),
                  target_after=target_snapshot(head=COMMIT), target_checkpoint_commit=COMMIT)
    values.update(overrides)
    return g.GuardrailRequest(**values)


def audit(**overrides):
    values = dict(audit_id="audit-wo05-1", auditor_kind=fc.AUDITOR_HUMAN, auditor_id="reviewer-ana",
                  subject_pipeline_id=PID, subject_worker_id=WID, subject_commit=COMMIT, verdict=fc.AUDIT_PASS)
    values.update(overrides)
    return fc.AuditRecord(**values)


def suite(**overrides):
    values = dict(suite_id="test_fabric_self_dogfood_evidence", provenance=fc.PROVENANCE_SYNTHETIC_REGRESSION,
                  tests_run=30, failures=0, errors=0, skipped=0)
    values.update(overrides)
    return fc.CapabilityClaim(**values)


def ready_validation():
    return vc.assess_validation(vc.ValidationFacts(**{d: True for d in vc.DIMENSIONS}))


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="fcp12cert_")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.fx = Fixture(Path(os.path.realpath(tmp)))

    def request(self, write=True, **overrides):
        if write:
            self.fx.write()
        values = dict(schema_version=1, action=fc.ACTION_REQUEST_HOST_AUDIT,
                      target=fc.CertificationTarget(pipeline_id=PID, worker_id=WID, ref=BRANCH,
                                                    base_commit=FCP11_BASE),
                      evidence_request=self.fx.request(), guardrails=guardrails(), validation=ready_validation(),
                      capabilities=(), audits=(audit(),))
        values.update(overrides)
        return fc.CertificationRequest(**values)

    def evaluate(self, write=True, **overrides):
        return fc.evaluate_certification(self.request(write, **overrides))

    def blocked(self, *expected, write=True, **overrides):
        a = self.evaluate(write, **overrides)
        self.assertEqual(a.decision, fc.BLOCKED, a.reasons)
        for code in expected:
            self.assertIn(code, a.reasons)
        self.assertFalse(a.ready_for_host_audit)
        self.assertIsNone(a.binding)
        self.assertIsNone(a.next_step)
        return a


class PositivePathTests(_Base):
    def test_fully_consistent_attempt_is_only_ready_for_host_audit(self):
        a = self.evaluate()
        self.assertEqual((a.decision, a.reasons, a.trace), (fc.READY_FOR_HOST_AUDIT, (), ()))
        self.assertEqual((a.evidence_status, a.capability_status, a.audit_status, a.security_status,
                          a.rollback_status), ("RUNNER_CORROBORATED", "NOT_DECLARED", "CLAIMED_UNVERIFIED",
                                               "PROVEN_LOCAL", "ANCHORED"))
        self.assertEqual((a.rollback_anchor, a.checkpoint_commit), (ATTEMPT_BASE, COMMIT))
        self.assertEqual((a.host_ci_status, a.human_authorization), ("UNKNOWN", "NONE"))
        self.assertEqual(a.pending_host_requirements,
                         ("HOST_CI_ON_PULL_REQUEST", "FCP3_HUMAN_AUTHORIZATION", "FINAL_HOST_AUDIT"))
        self.assertEqual(a.next_step, fc.NEXT_STEP_HOST_AUDIT)
        self.assertRegex(a.binding, r"^[0-9a-f]{64}$")
        body = json.loads(fc.canonical_json(a))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(a, flag), False, flag)
            self.assertIs(body[flag], False, flag)

    def test_synthetic_capability_is_reported_separately_and_never_replaces_evidence(self):
        a = self.evaluate(capabilities=(suite(), suite(suite_id="test_fabric_self_dogfood_contract")))
        self.assertEqual((a.decision, a.capability_status, a.evidence_status),
                         (fc.READY_FOR_HOST_AUDIT, "SYNTHETIC_DECLARED", "RUNNER_CORROBORATED"))
        self.assertNotEqual(a.binding, self.evaluate().binding)

    def test_deterministic_order_insensitive_and_secret_free(self):
        audits = (audit(), audit(audit_id="audit-wo05-2", auditor_kind=fc.AUDITOR_INDEPENDENT_AGENT,
                                 auditor_id="codex-auditor"))
        first = fc.canonical_json(self.evaluate(audits=audits))
        second = fc.canonical_json(self.evaluate(audits=tuple(reversed(audits))))
        self.assertEqual(first, second)
        blocked = fc.canonical_json(self.evaluate(audits=(audit(auditor_id=PROVIDER, auditor_kind="PROVIDER"),),
                                                  host_ci={"token": "ghp_SECRETSECRET", "conclusion": "success"}))
        for text in (first, blocked):
            for leaked in (str(self.fx.base), "provider prose", "VERDICT", "reviewer-ana", "codex-auditor",
                           "ghp_SECRET", "scripts/ai", TARGET, "\\", "MERGED"):
                self.assertNotIn(leaked, text)
        with self.assertRaises(TypeError):
            fc.canonical_json(json.loads(first))


class OutputVocabularyTests(_Base):
    def test_malformed_requests_are_blocked_never_another_decision(self):
        good = self.request()
        cases = [None, {}, "READY_FOR_HOST_AUDIT", dataclasses.asdict(fc.CertificationTarget()),
                 dataclasses.replace(good, schema_version=True), dataclasses.replace(good, schema_version="1"),
                 dataclasses.replace(good, action="MERGED"), dataclasses.replace(good, action=None),
                 dataclasses.replace(good, target=None),
                 dataclasses.replace(good, target=fc.CertificationTarget(PID, "wo-sk-ABCDEFGHIJKLMNOP", BRANCH,
                                                                         FCP11_BASE)),
                 dataclasses.replace(good, target=fc.CertificationTarget(PID, WID, BRANCH, "HEAD"))]
        for bad in cases:
            with self.subTest(bad=type(bad).__name__):
                a = fc.evaluate_certification(bad)
                self.assertEqual(a.decision, fc.BLOCKED)
                self.assertTrue(set(a.reasons) & set(fc.INVALID_REASONS), a.reasons)
                self.assertEqual((a.evidence_status, a.audit_status), (fc.NOT_EVALUATED, fc.NOT_EVALUATED))
        self.assertEqual(fc.DECISIONS, ("READY_FOR_HOST_AUDIT", "BLOCKED"))

    def test_closing_or_merging_is_always_blocked_even_when_everything_holds(self):
        for action in (fc.ACTION_DECLARE_CLOSED, fc.ACTION_REQUEST_MERGE):
            a = self.blocked(action=action)
            self.assertEqual(a.reasons, (fc.CLOSURE_REQUIRES_HOST_CI_AND_FCP3_HUMAN_AUTHORIZATION,))
            self.assertEqual(a.evidence_status, "RUNNER_CORROBORATED")
            self.assertFalse(a.merge_performed)
            self.assertFalse(a.closure_complete)

    def test_hand_made_assessments_cannot_overclaim(self):
        ready = self.evaluate()
        bad = [
            dict(reasons=(fc.AUDIT_MISSING,)), dict(audit_status=fc.AUDIT_MISSING_STATUS),
            dict(evidence_status=fc.EVIDENCE_NOT_CORROBORATED), dict(rollback_anchor=None),
            dict(action=fc.ACTION_REQUEST_MERGE), dict(binding=None), dict(trace=((fc.TRACE_EVIDENCE, "MERGED"),)),
            dict(decision="MERGED"), dict(security_status="SECURE"),
        ]
        for overrides in bad:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    dataclasses.replace(ready, **overrides)
        with self.assertRaises(ValueError):
            fc.CertificationAssessment(decision=fc.BLOCKED, reasons=())
        with self.assertRaises(ValueError):
            fc.CertificationAssessment(decision=fc.BLOCKED, reasons=(fc.AUDIT_MISSING,), binding="0" * 64)


class FalsePositiveTests(_Base):
    def test_provider_success_words_with_partial_runner_state_are_blocked(self):
        self.fx.worker.update(state="PARTIAL", state_reason="EVIDENCE_FINALIZATION_FAILED")
        a = self.blocked(fc.EVIDENCE_NOT_CORROBORATED_REASON, fc.CLOSURE_CONTRACT_DENIED,
                         capabilities=(suite(), suite(suite_id="test_fabric_self_dogfood_contract")))
        self.assertIn((fc.TRACE_EVIDENCE, ev.WORKER_NOT_SUCCESS), a.trace)
        self.assertEqual((a.evidence_status, a.capability_status), ("NOT_CORROBORATED", "SYNTHETIC_DECLARED"))
        self.assertEqual(a.security_status, "NOT_PROVEN")

    def test_pre_made_or_missing_evidence_is_never_runner_evidence(self):
        self.fx.write()
        real = ev.read_evidence(self.fx.request())
        self.assertTrue(real.corroborated)
        a = self.blocked(fc.EVIDENCE_NOT_RUNNER_READ, write=False, evidence_request=real)
        self.assertEqual(a.evidence_status, "NOT_CORROBORATED")
        self.blocked(fc.EVIDENCE_REQUEST_MISSING, write=False, evidence_request=None)
        empty = Path(tempfile.mkdtemp(prefix="fcp12cert_empty_"))
        self.addCleanup(shutil.rmtree, empty, True)
        (empty / "state").mkdir()
        (empty / "factory").mkdir()
        nothing = ev.EvidenceRequest(schema_version=1, state_root=os.path.realpath(empty / "state"),
                                     factory_root=os.path.realpath(empty / "factory"), pipeline_id=PID,
                                     worker_id=WID, observed_target_head=COMMIT)
        a = self.blocked(fc.EVIDENCE_NOT_CORROBORATED_REASON, write=False, evidence_request=nothing,
                         capabilities=(suite(),))
        self.assertIn((fc.TRACE_EVIDENCE, ev.EVIDENCE_MISSING), a.trace)

    def test_supplied_ci_or_human_authorization_is_refused_never_assumed(self):
        for overrides, code in ((dict(host_ci="PASS"), fc.HOST_CI_CLAIM_NOT_ACCEPTED),
                                (dict(human_authorization={"approved": True}), fc.HUMAN_AUTHORIZATION_NOT_ACCEPTED)):
            a = self.blocked(code, fc.SECURITY_NOT_PROVEN_REASON, **overrides)
            self.assertEqual((a.host_ci_status, a.human_authorization, a.security_status),
                             ("UNKNOWN", "NONE", "NOT_PROVEN"))


class PartialSuccessAndCapabilityTests(_Base):
    def test_partial_or_mislabeled_synthetic_capability_blocks(self):
        cases = [
            (suite(failures=1), fc.CAPABILITY_PARTIAL), (suite(skipped=2), fc.CAPABILITY_PARTIAL),
            (suite(errors=1), fc.CAPABILITY_PARTIAL), (suite(tests_run=0), fc.CAPABILITY_PARTIAL),
            (suite(provenance="RUNNER_REAL"), fc.CAPABILITY_PROVENANCE_REFUSED),
            (suite(provenance=None), fc.CAPABILITY_PROVENANCE_REFUSED),
            (suite(tests_run=True), fc.CAPABILITY_MALFORMED), (suite(tests_run=-1), fc.CAPABILITY_MALFORMED),
            (suite(suite_id="../x"), fc.CAPABILITY_MALFORMED),
        ]
        for claim, code in cases:
            with self.subTest(code=code, claim=claim):
                a = self.blocked(code, capabilities=(suite(suite_id="ok_suite"), claim))
                self.assertEqual(a.capability_status, "REFUSED")
        self.blocked(fc.CAPABILITY_MALFORMED, capabilities=[suite()])
        self.blocked(fc.CAPABILITY_MALFORMED, capabilities=(suite(), suite()))

    def test_validation_not_ready_is_a_partial_success_and_blocks(self):
        partial = vc.assess_validation(vc.ValidationFacts(**{d: d != vc.DIMENSIONS[-1] for d in vc.DIMENSIONS}))
        a = self.blocked(fc.CLOSURE_CONTRACT_DENIED, validation=partial)
        self.assertIn((fc.TRACE_CLOSURE, "VALIDATION_NOT_READY"), a.trace)
        self.assertEqual(a.evidence_status, "RUNNER_CORROBORATED")
        a = self.blocked(fc.CLOSURE_CONTRACT_DENIED, validation={"classification": vc.READY_FOR_HUMAN_REVIEW})
        self.assertIn((fc.TRACE_CLOSURE, "VALIDATION_NOT_TYPED"), a.trace)


class AuditTests(_Base):
    def test_absent_audit_blocks(self):
        a = self.blocked(fc.AUDIT_MISSING, audits=())
        self.assertEqual(a.reasons, (fc.AUDIT_MISSING,))
        self.assertEqual(a.audit_status, "MISSING")
        self.blocked(fc.AUDIT_MALFORMED, audits=None)
        self.blocked(fc.AUDIT_MALFORMED, audits=({"verdict": "PASS"},))

    def test_self_unbound_failed_or_inconclusive_audits_block(self):
        cases = [
            (audit(auditor_kind="PROVIDER"), fc.AUDIT_NOT_INDEPENDENT),
            (audit(auditor_kind="RUNNER"), fc.AUDIT_NOT_INDEPENDENT),
            (audit(auditor_kind="HOST_CI"), fc.AUDIT_NOT_INDEPENDENT),
            (audit(auditor_id=PROVIDER), fc.AUDIT_NOT_INDEPENDENT),
            (audit(subject_commit=OTHER), fc.AUDIT_UNBOUND), (audit(subject_worker_id="wo04_recovery"),
                                                              fc.AUDIT_UNBOUND),
            (audit(verdict=fc.AUDIT_FAIL), fc.AUDIT_FAILED),
            (audit(verdict=fc.AUDIT_INCONCLUSIVE), fc.AUDIT_INCONCLUSIVE_REASON),
            (audit(verdict="APPROVED"), fc.AUDIT_MALFORMED), (audit(auditor_kind="ROBOT"), fc.AUDIT_MALFORMED),
        ]
        for record, code in cases:
            with self.subTest(code=code, record=record):
                a = self.blocked(code, audits=(record,))
                self.assertNotEqual(a.audit_status, "CLAIMED_UNVERIFIED")

    def test_contradicting_or_duplicate_audits_block(self):
        a = self.blocked(fc.AUDIT_CONTRADICTED, fc.AUDIT_FAILED,
                         audits=(audit(), audit(audit_id="audit-wo05-2", verdict=fc.AUDIT_FAIL)))
        self.assertEqual(a.audit_status, "CONTRADICTED")
        self.blocked(fc.AUDIT_MALFORMED, audits=(audit(), audit()))


class RefAndBaseTests(_Base):
    def test_wrong_ref_is_blocked(self):
        target = lambda ref: fc.CertificationTarget(PID, WID, ref, FCP11_BASE)  # noqa: E731
        a = self.blocked(fc.REF_PROTECTED, fc.REF_MISMATCH, target=target("main"))
        self.assertNotIn(fc.TARGET_MALFORMED, a.reasons)
        self.blocked(fc.REF_PROTECTED, target=target("develop"))
        self.blocked(fc.REF_MISMATCH, target=target("feature/fcp12-other"))
        for bad in ("HEAD", "../main", "refs/heads/x..y", "feature/x.lock", ""):
            self.blocked(fc.TARGET_MALFORMED, target=target(bad))
        a = self.blocked(fc.ISOLATION_NOT_PROVEN, guardrails=guardrails(
            target_after=target_snapshot(head=COMMIT, branch="feature/fcp12-other")))
        self.assertIn((fc.TRACE_GUARDRAILS, g.TARGET_DRIFT), a.trace)

    def test_unexpected_base_or_controller_head_blocks_and_unanchors_rollback(self):
        a = self.blocked(fc.BASE_COMMIT_MISMATCH, fc.ROLLBACK_ANCHOR_UNPROVEN,
                         target=fc.CertificationTarget(PID, WID, BRANCH, OTHER))
        self.assertEqual((a.rollback_status, a.rollback_anchor), ("UNPROVEN", None))
        a = self.blocked(fc.ISOLATION_NOT_PROVEN, fc.CLOSURE_CONTRACT_DENIED, fc.ROLLBACK_ANCHOR_UNPROVEN,
                         guardrails=guardrails(controller_after=controller(head=OTHER)))
        self.assertIn((fc.TRACE_GUARDRAILS, g.CONTROLLER_DRIFT), a.trace)
        self.assertIn((fc.TRACE_CLOSURE, "CONTROLLER_HEAD_MOVED"), a.trace)

    def test_missing_or_admission_only_guardrails_block(self):
        self.blocked(fc.GUARDRAILS_MISSING, fc.SECURITY_NOT_PROVEN_REASON, guardrails=None)
        admit = guardrails(action=g.ACTION_ADMIT_ATTEMPT, controller_after=None, target_after=None,
                           target_checkpoint_commit=None)
        self.assertTrue(g.assess_guardrails(admit).isolation_holds)
        self.blocked(fc.GUARDRAILS_NOT_CONFIRMATION, fc.CLOSURE_CONTRACT_DENIED, guardrails=admit)


class ContradictionTests(_Base):
    def test_guardrails_disagreeing_with_runner_evidence_block(self):
        moved = guardrails(target_after=target_snapshot(head=OTHER), target_checkpoint_commit=OTHER)
        self.assertTrue(g.assess_guardrails(moved).isolation_holds)
        a = self.blocked(fc.EVIDENCE_CONTRADICTED, fc.CLOSURE_CONTRACT_DENIED, guardrails=moved)
        self.assertIn((fc.TRACE_CLOSURE, "TARGET_HEAD_UNEXPECTED"), a.trace)
        other_base = guardrails(plan=plan(attempt_base_head=OTHER), target_before=target_snapshot(head=OTHER))
        self.assertTrue(g.assess_guardrails(other_base).isolation_holds)
        a = self.blocked(fc.EVIDENCE_CONTRADICTED, fc.ROLLBACK_ANCHOR_UNPROVEN, guardrails=other_base)
        self.assertEqual(a.rollback_status, "UNPROVEN")

    def test_evidence_observed_head_or_ledger_contradiction_blocks(self):
        self.fx.write()
        a = self.blocked(fc.EVIDENCE_NOT_CORROBORATED_REASON, write=False,
                         evidence_request=self.fx.request(observed_target_head=OTHER))
        self.assertIn((fc.TRACE_EVIDENCE, ev.TARGET_HEAD_MISMATCH), a.trace)
        self.fx.events[1]["result_commit"] = OTHER
        a = self.blocked(fc.EVIDENCE_NOT_CORROBORATED_REASON)
        self.assertIn((fc.TRACE_EVIDENCE, ev.LEDGER_MISMATCH), a.trace)

    def test_subject_or_scope_mismatch_blocks(self):
        self.fx.write()
        a = self.blocked(fc.SUBJECT_MISMATCH, write=False, evidence_request=self.fx.request(worker_id="wo04_recovery"))
        self.assertEqual(a.evidence_status, "NOT_CORROBORATED")
        narrow = guardrails(plan=plan(authorized_scopes=(SCOPES[0],)))
        self.assertTrue(g.assess_guardrails(narrow).isolation_holds)
        self.blocked(fc.SCOPE_NOT_PLANNED, write=False, guardrails=narrow)


class RobustnessTests(_Base):
    def test_hostile_inputs_and_faults_never_raise(self):
        class Hostile:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for overrides in (dict(audits=(Hostile(),)), dict(capabilities=Hostile()), dict(validation=Hostile()),
                          dict(guardrails=Hostile()), dict(evidence_request=Hostile())):
            with self.subTest(overrides=list(overrides)):
                self.assertEqual(self.evaluate(**overrides).decision, fc.BLOCKED)
        with mock.patch.object(ev, "read_evidence", side_effect=RuntimeError("disk")):
            a = self.evaluate()
        self.assertEqual((a.decision, a.reasons, a.action), (fc.BLOCKED, (fc.CERTIFIER_FAULT,),
                                                             fc.ACTION_REQUEST_HOST_AUDIT))

    def test_no_git_process_network_or_write_at_runtime(self):
        self.fx.write()
        request = self.request(write=False)
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("network")), \
                mock.patch.object(os, "replace", side_effect=AssertionError("write")), \
                mock.patch.object(os, "remove", side_effect=AssertionError("write")):
            a = fc.evaluate_certification(request)
        self.assertEqual(a.decision, fc.READY_FOR_HOST_AUDIT, a.reasons)

    def test_module_imports_only_stdlib_and_sibling_contracts(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update([node.module.split(".")[0]] + [a.name for a in node.names]
                                if node.module == "scripts.ai" else [node.module.split(".")[0]])
        allowed = {"__future__", "hashlib", "json", "re", "dataclasses", "typing", "scripts", "claude_runner",
                   "fabric_control_plane_contract", "fabric_self_dogfood_contract", "fabric_self_dogfood_evidence",
                   "fabric_self_dogfood_guardrails", "fabric_validation_contract"}
        self.assertEqual(imported - allowed, set())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("open", "write_text", "subprocess", "run_git", "urlopen", "environ", "now", "MERGED"):
            self.assertNotIn(forbidden, names, forbidden)
        self.assertNotIn('"MERGED"', MODULE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(fc.SUPPORTED_SIBLINGS[0], (fc.dc.SCHEMA, fc.dc.SCHEMA_VERSION))
        self.assertEqual(cp.OUTCOME_UNKNOWN, fc.HOST_CI_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
