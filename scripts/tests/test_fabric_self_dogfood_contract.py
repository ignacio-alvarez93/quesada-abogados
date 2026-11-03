"""FCP-12A-01: Self-Dogfood & Closure contract V1 - deny-by-default closure
assessment. Offline, synthetic facts only (mocks prove regressions, never a
real dogfood run)."""

from __future__ import annotations

import ast
import builtins
import dataclasses
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as cr
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_self_dogfood_contract as dc
from scripts.ai import fabric_validation_contract as vc

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_self_dogfood_contract.py"

BASE = "a" * 40
ATTEMPT_BASE = "b" * 40
CHECKPOINT = "c" * 40
PIPELINE = "fcp12-self-dogfood-v1"
WORKER = "wo01_contract"
LEAF = "20261103T010203Z_0123abcd"
PROVIDER = "claude"
SHA = "d" * 64
ALL_FLAGS = (
    "certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
    "auto_retry_allowed", "resume_allowed", "release_allowed", "human_approval_granted", "host_ci_verified",
    "closure_complete", "git_allowed", "ledger_write_allowed",
)


def lineage(**overrides):
    values = dict(pipeline_id=PIPELINE, worker_id=WORKER, attempt=1, attempt_leaf=LEAF, provider_id=PROVIDER,
                  attempt_base_head=ATTEMPT_BASE)
    values.update(overrides)
    return dc.DogfoodLineage(**values)


def message(**overrides):
    values = dict(pipeline_id=PIPELINE, worker_id=WORKER, attempt=1, provider_id=PROVIDER, base_head=ATTEMPT_BASE)
    values.update(overrides)
    return cr.build_checkpoint_message(**values)


def completion(noop=False, **overrides):
    values = dict(
        status_evidence_kind="PIPELINE_RESULT", worker_state="SUCCESS",
        completion_policy=cr.COMPLETION_POLICY_RUNNER_ACCEPTANCE,
        work_status_source=cr.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE, checkpoint_policy="ON_SUCCESS",
    )
    if noop:
        values.update(checkpoint_decision="SKIPPED_NO_WORK_PRODUCT", checkpoint_commit=None, checkpoint_message=None,
                      authorized_changed_paths=(), work_product_present=False)
    else:
        values.update(checkpoint_decision="CREATED", checkpoint_commit=CHECKPOINT, checkpoint_message=message(),
                      authorized_changed_paths=("scripts/ai/fabric_self_dogfood_contract.py",),
                      work_product_present=True)
    values.update(overrides)
    return dc.RunnerCompletion(**values)


def identity(noop=False, **overrides):
    values = dict(base_commit=BASE, controller_commit=BASE, controller_head_observed=BASE,
                  target_head_observed=ATTEMPT_BASE if noop else CHECKPOINT, target_isolated=True)
    values.update(overrides)
    return dc.DogfoodIdentity(**values)


def ready_validation():
    return vc.assess_validation(vc.ValidationFacts(**{d: True for d in vc.DIMENSIONS}))


def ref(kind, **overrides):
    needed = cp._placeholders(kind)
    values = dict(kind=kind, condition=cp.PRESENT, content_sha256=SHA, size_bytes=10)
    if needed & {"{pipeline}", "{evidence_key}"}:
        values["pipeline_id"] = PIPELINE
    if needed & {"{worker}", "{evidence_key}"}:
        values["worker_id"] = WORKER
    if "{attempt}" in needed:
        values["attempt_leaf"] = LEAF
    values.update(overrides)
    return cp.EvidenceRef(**values)


def evidence():
    return tuple(ref(k) for k in dc.REQUIRED_EVIDENCE_KINDS)


def request(noop=False, **overrides):
    values = dict(schema_version=1, action=dc.ACTION_REQUEST_HUMAN_REVIEW, identity=identity(noop),
                  lineage=lineage(), completion=completion(noop), validation=ready_validation(), evidence=evidence())
    values.update(overrides)
    return dc.CloseRequest(**values)


def assess(**overrides):
    return dc.assess_closure(request(**overrides))


class PositivePathTests(unittest.TestCase):
    def test_checkpoint_closure_is_review_requestable_only(self):
        a = assess()
        self.assertEqual((a.decision, a.reasons, a.completion_mode),
                         (dc.REVIEW_REQUESTABLE, (), cr.COMPLETION_MODE_CHECKPOINT))
        self.assertTrue(a.review_requestable)
        for flag in ALL_FLAGS:
            self.assertIs(getattr(a, flag), False, flag)

    def test_success_noop_closure_is_review_requestable(self):
        a = assess(noop=True)
        self.assertEqual((a.decision, a.completion_mode), (dc.REVIEW_REQUESTABLE, cr.COMPLETION_MODE_SUCCESS_NOOP))

    def test_release_is_always_denied_even_when_everything_is_proven(self):
        a = assess(action=dc.ACTION_REQUEST_RELEASE)
        self.assertEqual((a.decision, a.reasons), (dc.DENIED, (dc.RELEASE_REQUIRES_FCP3_HUMAN_AUTHORIZATION,)))
        self.assertFalse(a.release_allowed)
        self.assertFalse(a.promotion_allowed)


class RequestShapeTests(unittest.TestCase):
    def test_untyped_requests_are_invalid(self):
        for bad in (None, {}, "request", dataclasses.asdict(request()), [request()]):
            a = dc.assess_closure(bad)
            self.assertEqual((a.decision, a.reasons), (dc.INVALID_REQUEST, (dc.REQUEST_NOT_TYPED,)))

    def test_schema_version_must_be_exactly_int_one(self):
        for bad in (None, 0, 2, True, 1.0, "1"):
            a = assess(schema_version=bad)
            self.assertEqual(a.decision, dc.INVALID_REQUEST, repr(bad))
            self.assertIn(dc.SCHEMA_UNSUPPORTED, a.reasons)

    def test_unknown_action_is_invalid(self):
        for bad in (None, "APPROVE", "request_human_review", 1):
            a = assess(action=bad)
            self.assertEqual((a.decision, a.reasons), (dc.INVALID_REQUEST, (dc.ACTION_UNKNOWN,)))

    def test_parts_of_the_wrong_type_are_denied_not_raised(self):
        a = assess(identity={}, lineage=None, completion="x", validation={"classification": "READY"}, evidence=[])
        self.assertEqual(a.decision, dc.DENIED)
        for code in (dc.IDENTITY_MALFORMED, dc.LINEAGE_MALFORMED, dc.COMPLETION_MALFORMED, dc.VALIDATION_NOT_TYPED,
                     dc.EVIDENCE_NOT_TYPED):
            self.assertIn(code, a.reasons)


class IdentityTests(unittest.TestCase):
    def test_controller_head_change_is_refused(self):
        a = assess(identity=identity(controller_head_observed="e" * 40))
        self.assertEqual(a.reasons, (dc.CONTROLLER_HEAD_MOVED,))

    def test_controller_must_be_pinned_at_base(self):
        a = assess(identity=identity(controller_commit="e" * 40, controller_head_observed="e" * 40))
        self.assertEqual(a.reasons, (dc.CONTROLLER_NOT_AT_BASE,))

    def test_target_isolation_must_be_explicitly_true(self):
        self.assertEqual(assess(identity=identity(target_isolated=False)).reasons, (dc.TARGET_NOT_ISOLATED,))
        for bad in (None, 1, "True"):
            self.assertEqual(assess(identity=identity(target_isolated=bad)).reasons, (dc.TARGET_ISOLATION_UNKNOWN,))

    def test_unexpected_target_head_is_refused(self):
        self.assertEqual(assess(identity=identity(target_head_observed=ATTEMPT_BASE)).reasons,
                         (dc.TARGET_HEAD_UNEXPECTED,))
        self.assertEqual(assess(noop=True, identity=identity(noop=True, target_head_observed=CHECKPOINT)).reasons,
                         (dc.TARGET_HEAD_UNEXPECTED,))

    def test_malformed_commits_are_refused(self):
        for bad in (None, "A" * 40, "a" * 39, "main", b"a" * 40):
            a = assess(identity=identity(base_commit=bad))
            self.assertEqual(a.decision, dc.DENIED)
            self.assertIn(dc.IDENTITY_MALFORMED, a.reasons)


class LineageTests(unittest.TestCase):
    def test_corrupt_lineage_is_refused(self):
        for overrides in (dict(pipeline_id="../x"), dict(worker_id="CON"), dict(attempt=0), dict(attempt=True),
                          dict(attempt="1"), dict(attempt_leaf="latest"), dict(provider_id=None),
                          dict(attempt_base_head="HEAD")):
            a = assess(lineage=lineage(**overrides))
            self.assertEqual(a.decision, dc.DENIED, overrides)
            self.assertIn(dc.LINEAGE_MALFORMED, a.reasons)

    def test_checkpoint_message_binds_lineage(self):
        for overrides in (dict(attempt=2), dict(worker_id="other"), dict(provider_id="codex"),
                          dict(base_head="e" * 40)):
            a = assess(completion=completion(checkpoint_message=message(**overrides)))
            self.assertEqual(a.reasons, (dc.CHECKPOINT_LINEAGE_MISMATCH,), overrides)
        a = assess(completion=completion(checkpoint_message="runner-checkpoint(wip): forged"))
        self.assertEqual(a.reasons, (dc.CHECKPOINT_LINEAGE_MISMATCH,))


class RunnerOwnedStatusTests(unittest.TestCase):
    def test_provider_sourced_success_is_not_enough(self):
        a = assess(completion=completion(work_status_source=cr.WORK_STATUS_SOURCE_PROVIDER))
        self.assertEqual(a.reasons, (dc.SUCCESS_NOT_RUNNER_CERTIFIED,))
        a = assess(completion=completion(completion_policy=cr.COMPLETION_POLICY_PROVIDER_VERDICT))
        self.assertEqual(a.reasons, (dc.COMPLETION_NOT_RUNNER_ACCEPTANCE,))

    def test_status_must_come_from_runner_owned_evidence(self):
        for bad in ("ATTEMPT_METADATA", "DIRECTOR_DAG_MANIFEST", "provider_stdout", None):
            a = assess(completion=completion(status_evidence_kind=bad))
            self.assertEqual(a.reasons, (dc.STATUS_NOT_RUNNER_OWNED,), bad)

    def test_non_success_or_unrecognized_worker_state_is_refused(self):
        for state in ("PARTIAL", "FAILED", "RUNNING", "INTERRUPTED"):
            a = assess(completion=completion(worker_state=state))
            self.assertEqual(a.decision, dc.DENIED)
            self.assertIn(dc.WORKER_NOT_SUCCESS, a.reasons)
        for bad in ("success", "SUCCESS ", None, 1):
            a = assess(completion=completion(worker_state=bad))
            self.assertIn(dc.STATUS_UNRECOGNIZED, a.reasons)

    def test_checkpoint_policy_and_decision_are_enforced(self):
        self.assertIn(dc.CHECKPOINT_POLICY_MISSING, assess(completion=completion(checkpoint_policy=None)).reasons)
        a = assess(completion=completion(checkpoint_decision="REFUSED_PROCESS_NOT_CONFIRMED_STOPPED"))
        self.assertIn(dc.CHECKPOINT_REFUSED, a.reasons)
        a = assess(completion=completion(checkpoint_decision="SKIPPED_NO_WORK_PRODUCT"))
        self.assertIn(dc.CHECKPOINT_INCONSISTENT, a.reasons)
        a = assess(completion=completion(checkpoint_commit="zz"))
        self.assertIn(dc.CHECKPOINT_MALFORMED, a.reasons)

    def test_changes_without_checkpoint_are_unclassified(self):
        a = assess(completion=completion(checkpoint_commit=None, checkpoint_message=None))
        self.assertIsNone(a.completion_mode)
        self.assertIn(dc.COMPLETION_MODE_UNCLASSIFIED, a.reasons)

    def test_protected_historical_ci_is_refused_in_any_spelling(self):
        for path in (".github/workflows/fabric-ci.yml", ".github\\workflows\\FCP11-Control-Plane.yml",
                     "./.github/workflows/fabric-ci.yml"):
            paths = ("scripts/ai/fabric_self_dogfood_contract.py", path)
            a = assess(completion=completion(authorized_changed_paths=paths))
            self.assertEqual(a.reasons, (dc.PROTECTED_PATH_CHANGED,), path)

    def test_corrupt_changed_paths_are_refused(self):
        for bad in (["a.py"], ("a.py", 3), ("",), ("a\x00b",), None):
            a = assess(completion=completion(authorized_changed_paths=bad))
            self.assertIn(dc.COMPLETION_MALFORMED, a.reasons)
        self.assertIn(dc.COMPLETION_MALFORMED, assess(completion=completion(work_product_present=1)).reasons)


class ValidationTests(unittest.TestCase):
    def test_validation_must_be_ready(self):
        not_ready = vc.assess_validation(vc.ValidationFacts(**{d: True for d in vc.DIMENSIONS[:-1]}))
        self.assertEqual(assess(validation=not_ready).reasons, (dc.VALIDATION_NOT_READY,))

    def test_tampered_validation_is_refused(self):
        tampered = vc.assess_validation(vc.ValidationFacts())
        object.__setattr__(tampered, "classification", vc.READY_FOR_HUMAN_REVIEW)
        object.__setattr__(tampered, "ready_for_human_review", True)
        self.assertEqual(assess(validation=tampered).reasons, (dc.VALIDATION_TAMPERED,))

    def test_unreviewed_validation_version_fails_closed(self):
        with mock.patch.object(vc, "SCHEMA_VERSION", 2):
            self.assertEqual(assess().reasons, (dc.VALIDATION_VERSION_UNSUPPORTED,))


class EvidenceTests(unittest.TestCase):
    def test_every_required_kind_is_needed(self):
        for kind in dc.REQUIRED_EVIDENCE_KINDS:
            refs = tuple(r for r in evidence() if r.kind != kind)
            self.assertEqual(assess(evidence=refs).reasons, (dc.EVIDENCE_REQUIRED_MISSING,), kind)

    def test_non_present_evidence_is_refused(self):
        refs = evidence()[:-1] + (ref("FACTORY_EVENTS", condition=cp.CORRUPT, cause=cp.SOURCE_NOT_JSON,
                                      content_sha256=None, size_bytes=None),)
        self.assertEqual(assess(evidence=refs).reasons, (dc.EVIDENCE_NOT_PRESENT,))

    def test_evidence_must_be_bound_to_lineage(self):
        for overrides in (dict(pipeline_id="other-pipeline"), dict(worker_id="other"),
                          dict(attempt_leaf="20261103T010203Z_ffffffff")):
            kind = "ATTEMPT_RESULT"
            refs = tuple(ref(kind, **overrides) if r.kind == kind else r for r in evidence())
            self.assertEqual(assess(evidence=refs).reasons, (dc.EVIDENCE_PROVENANCE_MISMATCH,), overrides)

    def test_duplicate_or_ambiguous_evidence_is_refused(self):
        self.assertEqual(assess(evidence=evidence() + (ref("WORKER_RESULT"),)).reasons, (dc.EVIDENCE_DUPLICATE,))
        other = ref("ATTEMPT_RESULT", attempt_leaf="20261103T010203Z_ffffffff")
        self.assertIn(dc.EVIDENCE_DUPLICATE, assess(evidence=evidence() + (other,)).reasons)

    def test_untyped_or_tampered_evidence_is_refused(self):
        as_dicts = tuple(r.to_dict() for r in evidence())
        self.assertEqual(assess(evidence=as_dicts).reasons, (dc.EVIDENCE_NOT_TYPED,))
        self.assertEqual(assess(evidence=list(evidence())).reasons, (dc.EVIDENCE_NOT_TYPED,))
        refs = evidence()
        object.__setattr__(refs[0], "content_sha256", None)
        self.assertEqual(assess(evidence=refs).reasons, (dc.EVIDENCE_NOT_TYPED,))


class OutputContractTests(unittest.TestCase):
    def test_hand_made_assessment_cannot_overclaim(self):
        with self.assertRaises(ValueError):
            dc.DogfoodClosureAssessment(dc.REVIEW_REQUESTABLE, (dc.CONTROLLER_HEAD_MOVED,), "CHECKPOINT")
        with self.assertRaises(ValueError):
            dc.DogfoodClosureAssessment(dc.REVIEW_REQUESTABLE, (), None)
        with self.assertRaises(ValueError):
            dc.DogfoodClosureAssessment(dc.DENIED, (), "CHECKPOINT")
        with self.assertRaises(ValueError):
            dc.DogfoodClosureAssessment(dc.DENIED, (dc.TARGET_NOT_ISOLATED, dc.CONTROLLER_HEAD_MOVED), None)
        with self.assertRaises(ValueError):
            dc.DogfoodClosureAssessment(dc.INVALID_REQUEST, (dc.CONTROLLER_HEAD_MOVED,), None)
        with self.assertRaises(ValueError):
            dc.DogfoodClosureAssessment("APPROVED", (), "CHECKPOINT")

    def test_guarantees_are_not_settable(self):
        a = assess()
        with self.assertRaises((AttributeError, TypeError)):
            dataclasses.replace(a, release_allowed=True)
        with self.assertRaises(AttributeError):
            a.release_allowed = True
        self.assertNotIn("release_allowed", {f.name for f in dataclasses.fields(a)})

    def test_canonical_json_is_deterministic_and_never_echoes_tainted_input(self):
        tainted = "sk-ant-SECRET0123456789 nacho@example.com C:\\Users\\x"
        a = assess(completion=completion(worker_state=tainted, status_evidence_kind=tainted),
                   identity=identity(base_commit=tainted))
        text = dc.canonical_json(a)
        self.assertEqual(text, dc.canonical_json(dc.assess_closure(request(
            completion=completion(worker_state=tainted, status_evidence_kind=tainted),
            identity=identity(base_commit=tainted)))))
        for fragment in ("sk-ant", "SECRET", "example.com", "Users"):
            self.assertNotIn(fragment, text)
        payload = json.loads(text)
        self.assertEqual((payload["schema"], payload["schema_version"]), (dc.SCHEMA, dc.SCHEMA_VERSION))
        self.assertEqual(payload["marker"], dc.DOGFOOD_MARKER)
        for flag in ALL_FLAGS:
            self.assertIs(payload[flag], False, flag)
        with self.assertRaises(TypeError):
            dc.canonical_json(a.to_dict())

    def test_reason_vocabulary_is_unique(self):
        self.assertEqual(len(dc.REASONS), len(set(dc.REASONS)))
        self.assertTrue(set(dc.REQUIRED_EVIDENCE_KINDS) <= set(cp.EVIDENCE_KINDS))
        self.assertTrue(set(dc.STATUS_EVIDENCE_KINDS) <= set(dc.REQUIRED_EVIDENCE_KINDS))


class PurityTests(unittest.TestCase):
    def test_module_imports_no_side_effect_libraries(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("os", "subprocess", "socket", "shutil", "pathlib", "urllib", "http", "time", "random"):
            self.assertNotIn(forbidden, imported)

    def test_assessment_performs_no_io_process_or_network(self):
        boom = mock.Mock(side_effect=AssertionError("side effect"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(os, "system", boom):
            self.assertEqual(assess().decision, dc.REVIEW_REQUESTABLE)
            self.assertEqual(assess(action=dc.ACTION_REQUEST_RELEASE).decision, dc.DENIED)
        boom.assert_not_called()

    def test_corrupt_inputs_never_raise(self):
        weird = (None, 0, -1, True, 1.5, "", "x" * 5000, b"\x00", [], {}, (), object(), float("nan"))
        names = {
            "identity": [f.name for f in dataclasses.fields(dc.DogfoodIdentity)],
            "lineage": [f.name for f in dataclasses.fields(dc.DogfoodLineage)],
            "completion": [f.name for f in dataclasses.fields(dc.RunnerCompletion)],
        }
        builders = {"identity": identity, "lineage": lineage, "completion": completion}
        for part, fields_ in names.items():
            for name in fields_:
                baseline = getattr(builders[part](), name)
                for value in weird:
                    a = assess(**{part: builders[part](**{name: value})})
                    self.assertIn(a.decision, (dc.DENIED, dc.REVIEW_REQUESTABLE), (part, name, value))
                    if a.decision == dc.REVIEW_REQUESTABLE:
                        # Only the valid baseline value, or an UNKNOWN work-product flag
                        # (classification follows the checkpoint commit), may pass.
                        self.assertTrue(value is baseline or (part, name, value) == (
                            "completion", "work_product_present", None), (part, name, value))


if __name__ == "__main__":
    unittest.main()
