"""FCP-12A-03: Self-Dogfood Runner evidence reader V1 - read-only
normalization of real Runner evidence. Offline: every fixture is a synthetic
on-disk tree with the exact shapes the Runner writes (`runner_pipeline`
`build_result` / `WorkerRuntime.to_dict` / `_write_result`, `claude_runner`
metadata / result / work product / `CheckpointResult`, factory ledger
events). Mocks prove regressions, never a real dogfood run."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as cr
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.ai import fabric_resource_quota_report as qrep
from scripts.ai import fabric_self_dogfood_contract as dc
from scripts.ai import fabric_self_dogfood_evidence as ev
from scripts.ai import runner_pipeline as rp

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_self_dogfood_evidence.py"

PID = "fcp12-self-dogfood-night-20261103-v1"
WID = "wo03_evidence"
LEAF = "20261103T222108Z_1a2b3c4d_0a1b2c3d4e"
PROVIDER = "claude"
BASE = "9" * 40
COMMIT = "7" * 40
BRANCH = "feature/fcp12-self-dogfood-v1"
SCOPES = ["scripts/ai/fabric_self_dogfood_evidence.py", "scripts/tests/test_fabric_self_dogfood_evidence.py"]
LINES = ["?? " + p for p in SCOPES]
ALL_FLAGS = (
    "certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
    "auto_retry_allowed", "resume_allowed", "release_allowed", "human_approval_granted", "host_ci_verified",
    "closure_complete", "git_allowed", "ledger_write_allowed", "write_allowed", "arbitrary_path_read_allowed",
    "provider_words_trusted",
)


def _dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class Fixture:
    """A real-shaped Runner state root + factory ledger root in a temp dir."""

    def __init__(self, base: Path):
        self.base = base
        self.state = base / "state"
        self.factory = base / "factory"
        self.worktree = base / "target"
        self.worker_dir = self.state / PID / "workers" / WID
        self.evidence_dir = self.state / rp.EVIDENCE_ROOT_DIRNAME / rp.evidence_root_key(PID, WID) / LEAF
        self.work_product = {
            "schema_version": cr.WORK_PRODUCT_SCHEMA_VERSION, "run_id": LEAF, "pipeline_id": PID, "worker_id": WID,
            "attempt": 1, "provider": PROVIDER, "worktree": str(self.worktree), "branch": BRANCH, "base_head": BASE,
            "authorized_scopes": list(SCOPES), "authorized_changed_paths": list(LINES),
            "recorded_at_utc": "2026-11-03T22:27:00+00:00", "process_confirmed_stopped": True, "state": "SUCCESS",
            "incomplete": False, "reason_incomplete": None, "evidence_dir": str(self.evidence_dir),
            "runner_evidence_dir": str(self.evidence_dir), "runner_owned_paths": [],
        }
        self.checkpoint = {
            "decision": "CREATED", "commit_hash": COMMIT, "reason": None, "committed_paths": sorted(SCOPES),
            "message": cr.build_checkpoint_message(pipeline_id=PID, worker_id=WID, attempt=1, provider_id=PROVIDER,
                                                   base_head=BASE),
            "work_product_source": "CURRENT_ATTEMPT_WORK_PRODUCT",
        }
        self.attempt = {
            "attempt": 1, "provider": PROVIDER, "started_at_utc": "2026-11-03T22:21:08+00:00",
            "ended_at_utc": "2026-11-03T22:27:00+00:00", "status": "COMPLETED", "executed": True,
            "runner_state": "SUCCESS", "work_status": "SUCCESS", "provider_work_status": "UNVERIFIED",
            "work_status_source": cr.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE, "evidence_dir": str(self.evidence_dir),
            "retry_decision": "NONE:SUCCESS", "budget_class": "WORK",
            "process_evidence_path": str(self.worker_dir / "process" / "attempt-1.json"), "process": {},
            "process_confirmed_stopped": True, "exit_code": 0, "run_id": LEAF, "error_message": None,
            "evidence_complete": True, "acceptance": {"decision": "PASSED", "commands": []},
            "checkpoint": self.checkpoint,
        }
        self.spec = {
            "id": WID, "worktree": str(self.worktree), "work_order": "wo03.md", "provider": PROVIDER, "model": None,
            "mode": "write", "required_capabilities": [], "priority": 0, "depends_on": ["wo02_guardrails"],
            "dependency_policy": "success", "max_attempts": 1, "backoff_seconds": 0.0, "timeout_seconds": 3600,
            "authorize_path": list(SCOPES), "fallback_providers": [], "metadata": {}, "allow_shell": True,
            "checkpoint_policy": "ON_SUCCESS", "resume_from": None,
            "completion_policy": cr.COMPLETION_POLICY_RUNNER_ACCEPTANCE, "acceptance_commands": ["python -m x"],
            "worktree_top": str(self.worktree),
        }
        self.worker = {
            "schema_version": rp.PIPELINE_SCHEMA_VERSION, "spec": self.spec, "order": 2, "state": "SUCCESS",
            "state_reason": None, "active_provider": PROVIDER, "provider_locked": True, "fallbacks_used": [],
            "attempts": [self.attempt], "attempt_base": 0, "retry_not_before_utc": None, "provider_wait": None,
            "work_attempts_used": 1, "availability_attempts": 0, "owner": None,
            "updated_at_utc": "2026-11-03T22:27:02+00:00", "result_path": str(self.worker_dir / "result.json"),
            "pending_resume_from": None,
        }
        names = ("prompt.txt", "stdout.txt", "stderr.txt", "metadata.json", "preflight.json", "result.json",
                 "work_product.json")
        self.result = {
            "worker_id": WID, "pipeline_id": PID, "state": "SUCCESS", "state_reason": None, "provider": PROVIDER,
            "requested_provider": PROVIDER, "mode": "write", "worktree": str(self.worktree), "runner_state": "SUCCESS",
            "work_status": "SUCCESS", "provider_work_status": "UNVERIFIED",
            "work_status_source": cr.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE, "attempts": [self.attempt],
            "fallbacks_used": [], "evidence_dir": str(self.evidence_dir),
            "artifacts": [str(self.evidence_dir / n) for n in names], "preflight": str(self.worker_dir / "preflight.json"),
            "metadata": {"fcp": "FCP-12"}, "written_at_utc": "2026-11-03T22:27:01+00:00", "outcome": "SUCCESS",
            "checkpoint": self.checkpoint, "acceptance": self.attempt["acceptance"],
        }
        self.pipeline_result = {
            "schema_version": rp.PIPELINE_SCHEMA_VERSION, "pipeline_id": PID, "status": "RUNNING", "stop_reason": None,
            "started_at_utc": "2026-11-03T22:00:00+00:00", "ended_at_utc": None, "duration_seconds": 1.0,
            "workers_total": 1, "success": 1, "partial": 0, "blocked": 0, "failed": 0, "cancelled": 0,
            "interrupted": 0, "waiting_provider_quota": 0, "blocked_provider_auth": 0, "state_counts": {},
            "provider_breakdown": {}, "max_observed_concurrency": 1, "workers": [{
                "id": WID, "provider": PROVIDER, "requested_provider": PROVIDER, "state": "SUCCESS",
                "state_reason": None, "attempts": 1, "work_attempts_used": 1, "availability_attempts": 0,
                "provider_condition": None, "next_eligible_utc": None, "result_path": str(self.worker_dir / "result.json"),
                "worker_path": str(self.worker_dir / "worker.json"), "checkpoint_policy": "ON_SUCCESS",
                "checkpoint_commit": COMMIT,
            }],
        }
        safety = {"verdict": "SAFE"}
        common = {
            "provider": {"provider_id": PROVIDER, "display_name": "Claude Code CLI"}, "execution_mode": "write",
            "work_product_present": True, "work_product": self.work_product,
            "authorized_changed_paths": list(LINES), "unauthorized_changed_paths": [], "safety_verdict": safety,
            "evidence_complete": True, "evidence_errors": [],
        }
        self.metadata = {**common, "run_id": LEAF, "state": "SUCCESS", "repository": {
            "requested_path": str(self.worktree), "resolved_path": str(self.worktree), "branch_before": BRANCH,
            "head_before": BASE, "branch_after": BRANCH, "head_after": BASE}}
        self.attempt_result = {**common, "state": "SUCCESS", "work_status": "UNVERIFIED",
                               "provider_work_status": "UNVERIFIED",
                               "work_status_source": cr.WORK_STATUS_SOURCE_PROVIDER,
                               "cli_output": {"result": "provider prose " * 500},
                               "safety_check": {"repository_mutated": True, "branch_changed": False,
                                                "head_changed": False, "status_changed": True, "notes": []}}
        event = {"project": None, "module": None, "module_version": None, "pipeline_id": PID, "worker_id": WID,
                 "provider": PROVIDER, "role": None, "worktree": str(self.worktree), "branch": BRANCH,
                 "base_commit": None, "result_commit": None, "state": None, "state_reason": None,
                 "certification_status": None, "closer": None, "schema_version": 1}
        self.events = [
            {**event, "event_id": "e1", "event_type": "WORKER_STARTED", "timestamp_utc": "2026-11-03T22:21:08+00:00",
             "base_commit": BASE, "state": "RUNNING"},
            {**event, "event_id": "e2", "event_type": "CHECKPOINT_CREATED",
             "timestamp_utc": "2026-11-03T22:27:00+00:00", "base_commit": BASE, "result_commit": COMMIT,
             "state": "CREATED"},
            {**event, "event_id": "e3", "event_type": "WORKER_FINISHED", "timestamp_utc": "2026-11-03T22:27:01+00:00",
             "result_commit": COMMIT, "state": "SUCCESS"},
            {**event, "event_id": "e4", "event_type": "WORK_PRODUCT_CREATED",
             "timestamp_utc": "2026-11-03T22:27:02+00:00", "result_commit": COMMIT, "state": "SUCCESS"},
        ]

    def write(self) -> "Fixture":
        _dump(self.state / PID / "pipeline_result.json", self.pipeline_result)
        _dump(self.worker_dir / "worker.json", self.worker)
        _dump(self.worker_dir / "result.json", self.result)
        _dump(self.worker_dir / "preflight.json", {})
        _dump(self.evidence_dir / "metadata.json", self.metadata)
        _dump(self.evidence_dir / "result.json", self.attempt_result)
        _dump(self.evidence_dir / "work_product.json", self.work_product)
        for name in ("prompt.txt", "stdout.txt", "stderr.txt"):
            (self.evidence_dir / name).write_text("VERDICT: SUCCESS\n", encoding="utf-8")
        self.factory.mkdir(parents=True, exist_ok=True)
        (self.factory / "events.jsonl").write_text(
            "".join(json.dumps(e, sort_keys=True) + "\n" for e in self.events), encoding="utf-8")
        return self

    def request(self, **overrides) -> ev.EvidenceRequest:
        values = dict(schema_version=1, state_root=str(self.state), factory_root=str(self.factory), pipeline_id=PID,
                      worker_id=WID, observed_target_head=COMMIT)
        values.update(overrides)
        return ev.EvidenceRequest(**values)

    def read(self, **overrides) -> ev.SelfDogfoodEvidence:
        return ev.read_evidence(self.request(**overrides))


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="fcp12ev_")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.fx = Fixture(Path(os.path.realpath(tmp)))

    def denied(self, *expected, write=True, **overrides):
        result = (self.fx.write() if write else self.fx).read(**overrides)
        self.assertEqual(result.decision, ev.DENIED, result.reasons)
        for code in expected:
            self.assertIn(code, result.reasons)
        self.assertIsNone(result.lineage())
        self.assertIsNone(result.completion())
        self.assertEqual(result.closure_evidence(), ())
        self.assertIsNone(result.expected_target_head)
        return result


class PositivePathTests(_Base):
    def test_real_shaped_evidence_is_corroborated_and_feeds_the_closure_contract(self):
        result = self.fx.write().read()
        self.assertEqual(result.decision, ev.CORROBORATED, result.reasons)
        self.assertEqual((result.runner_state, result.completion_mode, result.checkpoint_commit),
                         ("SUCCESS", cr.COMPLETION_MODE_CHECKPOINT, COMMIT))
        self.assertEqual(result.changed_paths, tuple(sorted(SCOPES)))
        self.assertEqual([e.kind for e in result.evidence], sorted(dc.REQUIRED_EVIDENCE_KINDS))
        self.assertTrue(all(e.condition == cp.PRESENT for e in result.evidence))
        disk = self.fx.evidence_dir / "work_product.json"
        wp_ref = next(e for e in result.evidence if e.kind == "ATTEMPT_WORK_PRODUCT")
        self.assertEqual(wp_ref.content_sha256, hashlib.sha256(disk.read_bytes()).hexdigest())
        closure = dc.assess_closure(dc.CloseRequest(
            schema_version=1, action=dc.ACTION_REQUEST_HUMAN_REVIEW,
            identity=dc.DogfoodIdentity(BASE, BASE, BASE, result.expected_target_head, True),
            lineage=result.lineage(), completion=result.completion(), validation=None,
            evidence=result.closure_evidence()))
        # Everything this reader supplies is accepted; only the FCP-8A-01
        # validation (not this module's) is still missing.
        self.assertEqual(closure.reasons, (dc.VALIDATION_NOT_TYPED,))
        self.assertEqual(closure.completion_mode, cr.COMPLETION_MODE_CHECKPOINT)

    def test_output_is_deterministic_secret_free_and_zero_authority(self):
        first, second = self.fx.write().read(), self.fx.read()
        self.assertEqual(ev.canonical_json(first), ev.canonical_json(second))
        text = ev.canonical_json(first)
        for leaked in (str(self.fx.base), "provider prose", "VERDICT", "scripts/ai", BRANCH, "\\"):
            self.assertNotIn(leaked, text)
        body = json.loads(text)
        self.assertEqual((body["evidence_verdict"], body["runner_state"], body["audit_verdict"],
                          body["authorization"]), (ev.CORROBORATED, "SUCCESS", "UNKNOWN", "NONE"))
        self.assertEqual(body["changed_paths_count"], 2)
        for flag in ALL_FLAGS:
            self.assertIs(body[flag], False, flag)
            self.assertIs(getattr(first, flag), False, flag)
        with self.assertRaises(TypeError):
            ev.canonical_json(first.to_dict())


class RequestAndRootTests(_Base):
    def test_malformed_requests_are_invalid_and_show_nothing(self):
        self.fx.write()
        cases = [
            dict(schema_version=True), dict(schema_version="1"), dict(pipeline_id="../x"), dict(worker_id="CON"),
            dict(worker_id="wo-sk-ABCDEFGHIJKLMNOP"), dict(observed_target_head="HEAD"),
            dict(observed_target_head="A" * 40), dict(state_root=42), dict(max_file_bytes=0),
            dict(max_file_bytes=ev.MAX_FILE_BYTES + 1), dict(max_file_bytes=True),
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result = self.fx.read(**overrides)
                self.assertEqual(result.decision, ev.INVALID_REQUEST)
                self.assertEqual(result.evidence, ())
        self.assertEqual(ev.read_evidence({"schema_version": 1}).reasons, (ev.REQUEST_NOT_TYPED,))

    def test_hostile_or_overlapping_roots_are_refused(self):
        self.fx.write()
        short = str(self.fx.base / "STATE~1")
        cases = [
            (dict(state_root="state"), ev.STATE_ROOT_REFUSED),
            (dict(state_root=str(self.fx.base / "absent")), ev.STATE_ROOT_REFUSED),
            (dict(state_root=str(self.fx.state / PID / "pipeline_result.json")), ev.STATE_ROOT_REFUSED),
            (dict(state_root=str(self.fx.state) + "\\..\\state"), ev.STATE_ROOT_REFUSED),
            (dict(factory_root=short), ev.FACTORY_ROOT_REFUSED),
            (dict(factory_root="\\\\server\\share\\factory"), ev.FACTORY_ROOT_REFUSED),
            (dict(factory_root=str(self.fx.state)), ev.ROOTS_OVERLAP),
        ]
        for overrides, code in cases:
            with self.subTest(overrides=overrides):
                result = self.fx.read(**overrides)
                self.assertEqual(result.decision, ev.DENIED)
                self.assertIn(code, result.reasons)
                self.assertEqual(result.evidence, ())


class MissingCorruptPartialTests(_Base):
    def test_missing_evidence_is_never_success(self):
        for victim in ("worker_result", "work_product", "ledger", "metadata"):
            with self.subTest(victim=victim):
                self.fx.write()
                path = {"worker_result": self.fx.worker_dir / "result.json",
                        "work_product": self.fx.evidence_dir / "work_product.json",
                        "ledger": self.fx.factory / "events.jsonl",
                        "metadata": self.fx.evidence_dir / "metadata.json"}[victim]
                path.unlink()
                result = self.fx.read()
                self.assertEqual(result.decision, ev.DENIED)
                self.assertIn(ev.EVIDENCE_MISSING, result.reasons)
                self.assertIn(cp.MISSING, {e.condition for e in result.evidence})

    def test_corrupt_files_and_schemas_are_refused(self):
        cases = [
            (lambda f: (f.worker_dir / "worker.json").write_text("{not json", encoding="utf-8"), ev.EVIDENCE_CORRUPT),
            (lambda f: (f.worker_dir / "result.json").write_text('{"a": 1, "a": 2}', encoding="utf-8"),
             ev.EVIDENCE_CORRUPT),
            (lambda f: (f.state / PID / "pipeline_result.json").write_text('{"x": NaN}', encoding="utf-8"),
             ev.EVIDENCE_CORRUPT),
            (lambda f: _dump(f.worker_dir / "worker.json", {**f.worker, "schema_version": 2}),
             ev.EVIDENCE_SCHEMA_UNSUPPORTED),
            (lambda f: _dump(f.evidence_dir / "work_product.json", {**f.work_product, "schema_version": True}),
             ev.EVIDENCE_SCHEMA_UNSUPPORTED),
            (lambda f: _dump(f.worker_dir / "worker.json", {**f.worker, "spec": {**f.spec, "worktree": "x" * 5000}}),
             ev.EVIDENCE_CORRUPT),
            (lambda f: (f.factory / "events.jsonl").open("a", encoding="utf-8").write('{"torn": '),
             ev.EVIDENCE_CORRUPT),
            (lambda f: (f.evidence_dir / "result.json").write_bytes(b"\xef\xbb\xbf{}"), ev.EVIDENCE_CORRUPT),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                mutate(self.fx.write())
                self.denied(code, write=False)

    def test_long_provider_strings_are_tolerated_only_in_attempt_files(self):
        self.fx.attempt_result["cli_output"] = {"result": "y" * 9000}
        self.assertEqual(self.fx.write().read().decision, ev.CORROBORATED)
        bad = {**self.fx.attempt_result, "cli_output": {"k" * 5000: 1}}
        _dump(self.fx.evidence_dir / "result.json", bad)
        self.assertIn(ev.EVIDENCE_CORRUPT, self.fx.read().reasons)

    def test_partial_or_incomplete_evidence_is_denied(self):
        cases = [
            (lambda f: f.worker.update(state="PARTIAL", state_reason="EVIDENCE_FINALIZATION_FAILED"),
             ev.WORKER_NOT_SUCCESS),
            (lambda f: f.attempt.update(evidence_complete=False), ev.EVIDENCE_INCOMPLETE),
            (lambda f: f.metadata.update(evidence_errors=["stdout.txt: disk full"]), ev.EVIDENCE_INCOMPLETE),
            (lambda f: f.work_product.update(incomplete=True), ev.WORK_PRODUCT_MISMATCH),
            (lambda f: f.attempt.update(process_confirmed_stopped=False), ev.ATTEMPT_NOT_COMPLETED),
            (lambda f: f.worker.update(state="BOGUS"), ev.STATUS_UNRECOGNIZED),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fx)
                self.denied(code)


class FalseSuccessAndStaleTests(_Base):
    def test_provider_words_never_make_success(self):
        cases = [
            (lambda f: f.attempt.update(work_status_source=cr.WORK_STATUS_SOURCE_PROVIDER),
             ev.SUCCESS_NOT_RUNNER_CERTIFIED),
            (lambda f: f.attempt.update(acceptance={"decision": "FAILED", "commands": []}),
             ev.SUCCESS_NOT_RUNNER_CERTIFIED),
            (lambda f: f.spec.update(completion_policy=cr.COMPLETION_POLICY_PROVIDER_VERDICT),
             ev.SUCCESS_NOT_RUNNER_CERTIFIED),
            (lambda f: f.attempt_result.update(work_status="SUCCESS",
                                               work_status_source=cr.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE),
             ev.STATUS_SOURCE_INCONSISTENT),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fx)
                self.denied(code)

    def test_provider_transcripts_are_never_opened(self):
        self.fx.worker.update(state="FAILED", state_reason="WORK_FAILED")
        self.fx.write()
        opened = []
        real = qrep.read_input_bytes

        def spy(path):
            opened.append(os.path.basename(path))
            return real(path)

        with mock.patch.object(qrep, "read_input_bytes", spy):
            result = self.fx.read()
        self.assertIn(ev.WORKER_NOT_SUCCESS, result.reasons)
        self.assertFalse({"stdout.txt", "stderr.txt", "prompt.txt", "git_before.txt"} & set(opened))
        self.assertEqual(sorted(set(opened)), ["events.jsonl", "metadata.json", "pipeline_result.json", "result.json",
                                               "work_product.json", "worker.json"])

    def test_stale_or_divergent_records_are_denied(self):
        cases = [
            (lambda f: f.result.update(attempts=[]), ev.STALE_EVIDENCE),
            (lambda f: f.result.update(written_at_utc="2026-11-03T22:00:00+00:00"), ev.STALE_EVIDENCE),
            (lambda f: f.pipeline_result["workers"][0].update(state="RUNNING"), ev.STATE_DIVERGENT),
            (lambda f: f.result.update(state="BLOCKED"), ev.STATE_DIVERGENT),
            (lambda f: f.pipeline_result["workers"][0].update(checkpoint_commit="8" * 40), ev.COMMIT_MISMATCH),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fx)
                self.denied(code)
        self.setUp()
        self.denied(ev.TARGET_HEAD_MISMATCH, observed_target_head=BASE)


class MismatchAndTamperingTests(_Base):
    def test_identity_commit_and_checkpoint_mismatches_are_denied(self):
        cases = [
            (lambda f: f.work_product.update(worker_id="wo02_guardrails"), ev.IDENTITY_MISMATCH),
            (lambda f: f.result.update(pipeline_id="other-pipeline"), ev.IDENTITY_MISMATCH),
            (lambda f: f.metadata.update(run_id="20261103T000000Z_00000000"), ev.IDENTITY_MISMATCH),
            (lambda f: f.checkpoint.update(message=f.checkpoint["message"].replace("attempt=1", "attempt=2")),
             ev.CHECKPOINT_INVALID),
            (lambda f: f.checkpoint.update(commit_hash=BASE), ev.CHECKPOINT_INVALID),
            (lambda f: f.checkpoint.update(committed_paths=SCOPES[:1]), ev.CHECKPOINT_INVALID),
            (lambda f: f.checkpoint.update(work_product_source="RESUMED_WORK_PRODUCT"), ev.CHECKPOINT_INVALID),
            (lambda f: f.metadata["repository"].update(head_after=COMMIT), ev.SAFETY_NOT_PROVEN),
            (lambda f: f.metadata.update(unauthorized_changed_paths=["?? evil.py"]), ev.SAFETY_NOT_PROVEN),
            (lambda f: f.spec.update(checkpoint_policy=None), ev.CHECKPOINT_POLICY_MISSING),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fx)
                self.denied(code)

    def test_ledger_must_corroborate_and_never_authorizes(self):
        cases = [
            (lambda f: f.events[1].update(result_commit="8" * 40), ev.LEDGER_MISMATCH),
            (lambda f: f.events[0].update(base_commit="8" * 40), ev.LEDGER_MISMATCH),
            (lambda f: f.events.pop(2), ev.LEDGER_MISMATCH),
            (lambda f: f.events.append({**f.events[1], "event_id": "e5"}), ev.LEDGER_MISMATCH),
            (lambda f: f.events.append({**f.events[3], "event_id": "e6", "event_type": "MODULE_CERTIFIED",
                                        "certification_status": "CERTIFIED", "closer": "someone"}),
             ev.LEDGER_UNACCEPTED_CLAIM),
            (lambda f: f.events.append({**f.events[3], "event_id": "e1"}), ev.EVIDENCE_CORRUPT),
            (lambda f: f.events.append({**f.events[3], "event_id": "e7", "schema_version": 2}),
             ev.EVIDENCE_CORRUPT),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fx)
                self.denied(code)

    def test_protected_path_and_out_of_scope_work_are_denied(self):
        lines = LINES + ["?? .github/workflows/fabric-ci.yml"]
        self.fx.work_product["authorized_changed_paths"] = lines
        self.fx.metadata["authorized_changed_paths"] = lines
        self.fx.attempt_result["authorized_changed_paths"] = lines
        self.fx.checkpoint["committed_paths"] = sorted(SCOPES + [".github/workflows/fabric-ci.yml"])
        self.denied(ev.PROTECTED_PATH_CHANGED, ev.SCOPE_VIOLATION)

    def test_tampered_output_objects_cannot_claim_more(self):
        good = self.fx.write().read()
        with self.assertRaises(ValueError):
            ev.SelfDogfoodEvidence(ev.CORROBORATED, (), pipeline_id=PID, worker_id=WID)
        with self.assertRaises(ValueError):
            ev.SelfDogfoodEvidence(ev.CORROBORATED, (ev.STALE_EVIDENCE,))
        with self.assertRaises(ValueError):
            dataclasses.replace(good, checkpoint_commit=good.attempt_base_head)
        with self.assertRaises(ValueError):
            dataclasses.replace(good, changed_paths=("../outside.py",))
        with self.assertRaises(ValueError):
            ev.SelfDogfoodEvidence(ev.DENIED, (ev.STALE_EVIDENCE,), completion_mode=cr.COMPLETION_MODE_CHECKPOINT)
        ref = good.evidence[0]
        object.__setattr__(ref, "condition", cp.MISSING)  # tamper after construction
        closure = dc.assess_closure(dc.CloseRequest(
            schema_version=1, action=dc.ACTION_REQUEST_HUMAN_REVIEW,
            identity=dc.DogfoodIdentity(BASE, BASE, BASE, COMMIT, True), lineage=good.lineage(),
            completion=good.completion(), evidence=good.closure_evidence()))
        self.assertIn(dc.EVIDENCE_NOT_TYPED, closure.reasons)


class HostileReferenceTests(_Base):
    def _move_evidence(self, new_dir: Path) -> None:
        self.fx.write()
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.fx.evidence_dir, new_dir)
        for record in (self.fx.attempt, self.fx.result):
            record["evidence_dir"] = str(new_dir)
        self.fx.result["attempts"] = [self.fx.attempt]
        _dump(self.fx.worker_dir / "worker.json", self.fx.worker)
        _dump(self.fx.worker_dir / "result.json", self.fx.result)

    def test_evidence_dir_outside_layout_or_root_is_refused(self):
        foreign = self.fx.state / rp.EVIDENCE_ROOT_DIRNAME / rp.evidence_root_key(PID, "wo02_guardrails") / LEAF
        targets = [
            self.fx.base / "elsewhere" / LEAF,
            foreign,
            self.fx.state / PID / "workers" / WID / "evidence" / LEAF,
        ]
        for target in targets:
            with self.subTest(target=target.name):
                self.setUp()
                self._move_evidence(target)
                result = self.fx.read()
                self.assertEqual(result.decision, ev.DENIED)
                self.assertIn(ev.EVIDENCE_PATH_REFUSED, result.reasons)

    def test_aliasing_relative_and_traversing_references_are_refused(self):
        self.fx.write()
        root_key = rp.evidence_root_key(PID, WID)
        hostile = [
            "relative/" + LEAF,
            str(self.fx.state / rp.EVIDENCE_ROOT_DIRNAME / root_key / ".." / root_key / LEAF),
            str(self.fx.state / rp.EVIDENCE_ROOT_DIRNAME / "ABCDEF~1" / LEAF),
            "\\\\?\\" + str(self.fx.evidence_dir),
            42,
        ]
        for raw in hostile:
            with self.subTest(raw=raw):
                self.fx.attempt["evidence_dir"] = raw
                self.fx.result["attempts"] = [self.fx.attempt]
                _dump(self.fx.worker_dir / "worker.json", self.fx.worker)
                result = self.fx.read()
                self.assertEqual(result.decision, ev.DENIED)
                self.assertIn(ev.EVIDENCE_PATH_REFUSED, result.reasons)

    def test_link_components_and_foreign_artifact_references_are_refused(self):
        self.fx.write()
        real_probe = snap._probe
        leaf_dir = os.path.normcase(str(self.fx.evidence_dir))

        def linked(path):
            kind, st, cause = real_probe(path)
            return (snap._LINK, st, cause) if os.path.normcase(path) == leaf_dir else (kind, st, cause)

        with mock.patch.object(snap, "_probe", linked):
            result = self.fx.read()
        self.assertIn(ev.EVIDENCE_PATH_REFUSED, result.reasons)
        self.assertIn(cp.LINK_REFUSED, {e.cause for e in result.evidence})
        self.setUp()
        self.fx.result["artifacts"].append(str(self.fx.base / "elsewhere" / "metadata.json"))
        self.denied(ev.REFERENCE_MISMATCH)

    def test_changed_during_read_and_oversize_are_unavailable(self):
        self.fx.write()
        real = qrep.read_input_bytes
        target = os.path.normcase(str(self.fx.worker_dir / "worker.json"))

        def racing(path):
            data = real(path)
            if os.path.normcase(path) == target:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(" ")
            return data

        with mock.patch.object(qrep, "read_input_bytes", racing):
            result = self.fx.read()
        self.assertIn(ev.EVIDENCE_UNAVAILABLE, result.reasons)
        self.assertIn(cp.SOURCE_CHANGED_DURING_READ, {e.cause for e in result.evidence})
        small = self.fx.write().read(max_file_bytes=64)
        self.assertIn(ev.EVIDENCE_UNAVAILABLE, small.reasons)


class ReadOnlyTests(_Base):
    def test_reading_never_mutates_the_roots(self):
        self.fx.write()

        def digest():
            return sorted((str(p), p.read_bytes()) for p in self.fx.base.rglob("*") if p.is_file())

        before = digest()
        boom = mock.Mock(side_effect=AssertionError("forbidden side effect"))
        with mock.patch.object(subprocess, "run", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(socket, "socket", boom), mock.patch.object(os, "replace", boom), \
                mock.patch.object(os, "remove", boom), mock.patch.object(os, "mkdir", boom):
            result = self.fx.read()
        self.assertEqual(result.decision, ev.CORROBORATED, result.reasons)
        self.assertEqual(digest(), before)

    def test_module_has_no_writer_git_or_network_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[-1])
        for forbidden in ("subprocess", "socket", "shutil", "pathlib", "urllib", "http", "time", "random",
                          "runner_git", "tempfile"):
            self.assertNotIn(forbidden, imported)
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for writer in ("write_text", "write_bytes", "remove", "unlink", "makedirs", "mkdir", "rename", "rmdir",
                       "_atomic_write_json", "create_checkpoint", "FactoryLedger"):
            self.assertNotIn(writer, attributes, writer)
        self.assertNotIn("open", {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})

    def test_unexpected_fault_fails_closed(self):
        self.fx.write()
        with mock.patch.object(ev, "_attempt_reasons", side_effect=RuntimeError("boom C:\\secret")):
            result = self.fx.read()
        self.assertEqual((result.decision, result.reasons), (ev.DENIED, (ev.READER_FAULT,)))
        self.assertNotIn("secret", ev.canonical_json(result))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
