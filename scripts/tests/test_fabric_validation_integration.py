"""FCP-8D-02: end-to-end integration of the FCP-8 Validation & Evidence
Engine - contract -> SINGLE / DAG adapter -> rules -> acceptance -> sealed
report -> consultative CLI - over the REAL `FabricDirectorService`.

Offline and synthetic only: single-worker runs are durable Runner artifacts
seeded into temporary roots; DAG runs are submitted and run through the
Director's own gateway over synthetic Git repositories with the FCP-5B-01
fake `Recorder` executor (no real agent, provider, network or remote). Every
read path is checked to leave the roots byte-identical and to call no
mutating Director API. Also pins the single additive FCP-8 CI step."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import re
import shlex
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_validation_acceptance as va
from scripts.ai import fabric_validation_cli as cli
from scripts.ai import fabric_validation_contract as vc
from scripts.ai import fabric_validation_dag as vd
from scripts.ai import fabric_validation_report as rp
from scripts.ai import fabric_validation_rules as vr
from scripts.ai import fabric_validation_single as vs
from scripts.tests import test_fabric_director_dag as tdd
from scripts.tests import test_fabric_validation_cli as tc

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
CI_STEP_NAME = "FCP-8 validation and evidence engine regression without skipped tests"
FCP8_SUITES = (
    "test_fabric_validation_contract", "test_fabric_validation_single", "test_fabric_validation_dag",
    "test_fabric_validation_rules", "test_fabric_validation_acceptance", "test_fabric_validation_report",
    "test_fabric_validation_cli", "test_fabric_validation_integration",
)
FCP8_MODULES = ("contract", "single", "dag", "rules", "acceptance", "report", "cli")

RUN = "fdb-20261030t000000000000-abcdef12"
WORKER = "w-01"
EMAIL = "person@example.invalid"
CMD = "python -m unittest scripts.tests.test_fabric_validation_integration"
CONTRACT_FLAGS = ("certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
                  "auto_retry_allowed", "resume_allowed")
MUTATING_DIRECTOR_METHODS =("submit", "run", "recover", "validate", "submit_and_run", "submit_blueprint",
                             "run_blueprint", "assess_integration", "propose_reconciliation_plan")


def acceptance_record(decision="PASSED", exit_code=0) -> dict:
    """One record shaped like `runner_pipeline._apply_acceptance` output."""
    return {"decision": decision, "commands": [{
        "command": CMD, "argv": shlex.split(CMD, posix=True), "exit_code": exit_code, "timed_out": False,
        "interrupted": False, "duration_seconds": 1.0, "stdout_tail": "Ran 999 tests\n\nOK (provider prose)",
        "stderr_tail": "", "process_attached": True, "confirmed_dead": True, "process_confirmed_stopped": True,
    }]}


def seed_single_run(root: Path, run_id: str = RUN, *, worker_state="SUCCESS", work_status="SUCCESS",
                    work_status_source="RUNNER_ACCEPTANCE", provider_work_status="SUCCESS", safety="SAFE",
                    unauthorized=(), evidence_complete=True, acceptance="PASSED", checkpoint_commit="abc1234",
                    pipeline_id=None) -> tuple:
    """Durable Runner artifacts of one single-worker run under `root`.
    Returns (state_root, director_root). `evidence_complete=None` leaves the
    attempt record without the flag (UNKNOWN); `acceptance=None` omits it."""
    state, director = root / "state", root / "director"
    director.mkdir(parents=True, exist_ok=True)
    evidence_dir = root / "evidence" / run_id / "attempt-1"
    evidence_dir.mkdir(parents=True)
    worker_dir = state / run_id / "workers" / WORKER
    worker_dir.mkdir(parents=True)
    attempt = {"evidence_dir": str(evidence_dir), "author": EMAIL}
    if evidence_complete is not None:
        attempt["evidence_complete"] = evidence_complete
    if acceptance is not None:
        attempt["acceptance"] = acceptance_record(acceptance, 0 if acceptance == "PASSED" else 1)
    (state / run_id / "pipeline_result.json").write_text(json.dumps({
        "schema_version": 1, "pipeline_id": run_id if pipeline_id is None else pipeline_id,
        "status": worker_state, "stop_reason": None, "workers": [{
            "id": WORKER, "state": worker_state, "provider": "claude", "requested_provider": "claude",
            "state_reason": "provider prose", "attempts": 1, "work_attempts_used": 1, "availability_attempts": 0,
            "provider_condition": None, "next_eligible_utc": None, "checkpoint_policy": "ON_SUCCESS",
            "checkpoint_commit": checkpoint_commit,
        }],
    }), encoding="utf-8")
    (worker_dir / "result.json").write_text(json.dumps({
        "worker_id": WORKER, "pipeline_id": run_id, "state": worker_state, "work_status": work_status,
        "provider_work_status": provider_work_status, "work_status_source": work_status_source,
        "runner_state": worker_state, "evidence_dir": str(evidence_dir), "attempts": [attempt],
    }), encoding="utf-8")
    changed = ["scripts/ai/x.py", *unauthorized]
    (evidence_dir / "metadata.json").write_text(json.dumps({
        "work_product_present": True, "changed_paths_after_run": changed,
        "authorized_changed_paths": ["scripts/ai/x.py"], "unauthorized_changed_paths": list(unauthorized),
    }), encoding="utf-8")
    (evidence_dir / "result.json").write_text(json.dumps({
        "execution_mode": "write", "safety_verdict": {"verdict": safety, "reasons": []},
        "normalized_result": {"summary": "provider prose " + EMAIL},
    }), encoding="utf-8")
    return state, director


def snapshot(root: Path) -> dict:
    return tc.snapshot(str(root))


@contextlib.contextmanager
def read_only_guard(test: unittest.TestCase, root: Path):
    """No mutating Director API, no socket, and a byte-identical tree."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("mutating or external call attempted")

    before = snapshot(root)
    with contextlib.ExitStack() as stack:
        for name in MUTATING_DIRECTOR_METHODS:
            stack.enter_context(mock.patch.object(fd.FabricDirectorService, name, refuse))
        for name in ("socket", "create_connection"):
            stack.enter_context(mock.patch.object(socket, name, refuse))
        yield
    test.assertEqual(snapshot(root), before)


def argv(command, run_id, state, director, *extra) -> list:
    return [command, "--run-id", run_id, "--state-root", str(state), "--director-root", str(director), *extra]


def assert_no_authority(test: unittest.TestCase, envelope: dict) -> None:
    for flag in cli.AUTHORITY_FLAGS:
        test.assertIs(envelope[flag], False, flag)
        test.assertIs(envelope["report"][flag], False, flag)
    for flag in CONTRACT_FLAGS:
        test.assertIs(envelope["report"]["classification"][flag], False, flag)
    test.assertEqual(envelope["authority"], cli.AUTHORITY)
    test.assertIs(envelope["authority"]["launcher"], False)


# ---------------------------------------------------------------------------
class _SingleRoots(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def seed(self, **kwargs) -> tuple:
        self.state, self.director = seed_single_run(self.root, **kwargs)
        return self.state, self.director

    def service(self):
        return cli.build_service(str(self.state), str(self.director))

    def run_cli(self, *extra, command="single", run_id=RUN) -> tuple:
        with read_only_guard(self, self.root):
            return tc.invoke(argv(command, run_id, self.state, self.director, *extra))

    def envelope(self, **seed) -> tuple:
        self.seed(**seed)
        code, out, err = self.run_cli()
        self.assertEqual(err, "")
        return code, json.loads(out)


# ---------------------------------------------------------------------------
class SingleEndToEndTests(_SingleRoots):
    """Real Director projections of seeded single-worker runs, end to end."""

    def test_fully_proven_run_is_validation_complete_and_report_verifies(self):
        code, envelope = self.envelope()
        self.assertEqual((code, envelope["verdict"]), (cli.EXIT_COMPLETE, vr.VALIDATION_COMPLETE))
        observation = vs.observe_single_run(self.service(), RUN)
        self.assertEqual(observation.facts, vc.ValidationFacts(True, True, True, True, True, True))
        expected = rp.build_report(observation)
        self.assertEqual(envelope["report"], expected.to_dict())
        self.assertEqual(envelope["report_sha256"], expected.report_sha256)
        verification = rp.verify_report(envelope["report"], observation=observation)
        self.assertTrue(verification.valid)
        self.assertEqual(verification.report_sha256, envelope["report_sha256"])
        assert_no_authority(self, envelope)

    def test_chain_layers_agree_contract_rules_report_cli(self):
        self.seed()
        observation = vs.observe_single_run(self.service(), RUN)
        self.assertEqual(observation.assessment, vc.assess_validation(observation.facts))
        classification = vr.classify_evidence(observation)
        report = rp.build_report(observation)
        envelope = cli.compose(cli.COMMAND_SINGLE, cli.observe(cli.COMMAND_SINGLE, self.service(), RUN))
        self.assertEqual(report.to_dict()["classification"], classification.to_dict())
        self.assertEqual(envelope["report"], report.to_dict())
        self.assertEqual(classification.verdict, report.verdict)
        self.assertEqual(classification.source, vr.SOURCE_SINGLE_RUN)

    def test_report_hash_is_independent_of_roots_and_repeat_runs(self):
        _, first = self.envelope()
        with tempfile.TemporaryDirectory() as other:
            state, director = seed_single_run(Path(other).resolve())
            code, out, _ = tc.invoke(argv("single", RUN, state, director))
        self.assertEqual(json.loads(out)["report_sha256"], first["report_sha256"])
        self.assertEqual(code, cli.EXIT_COMPLETE)
        self.assertEqual(json.loads(self.run_cli()[1]), first)

    def test_report_hash_is_the_sha256_of_its_canonical_body(self):
        _, envelope = self.envelope()
        body = {k: v for k, v in envelope["report"].items() if k != "report_sha256"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(hashlib.sha256(canonical.encode("ascii")).hexdigest(), envelope["report_sha256"])

    def test_bound_acceptance_projection_adds_verified_claim_and_new_hash(self):
        self.seed()
        service = self.service()
        observation = vs.observe_single_run(service, RUN)
        projection = va.project_acceptance(service.evidence(RUN), RUN, completion_policy=va.POLICY_RUNNER_ACCEPTANCE,
                                           acceptance_commands=[CMD])
        self.assertEqual(projection.status, va.STATUS_PASSED)
        with_acceptance = rp.build_report(observation, projection)
        without = rp.build_report(observation)
        self.assertEqual(with_acceptance.verdict, vr.VALIDATION_COMPLETE)
        self.assertIn(rp.ACCEPTANCE_CLAIM_ID, with_acceptance.claims["verified"])
        self.assertNotEqual(with_acceptance.report_sha256, without.report_sha256)
        self.assertTrue(rp.verify_report(with_acceptance, observation=observation, acceptance=projection).valid)
        self.assertFalse(rp.verify_report(with_acceptance, observation=observation).valid)

    def test_acceptance_test_counts_are_never_read_from_prose(self):
        self.seed()
        projection = va.project_acceptance(self.service().evidence(RUN), RUN,
                                           completion_policy=va.POLICY_RUNNER_ACCEPTANCE, acceptance_commands=[CMD])
        self.assertIn("TEST_COUNTS_NOT_IN_RUNNER_CONTRACT", projection.codes)
        self.assertNotIn("999", json.dumps(projection.to_dict()))

    def test_text_format_reports_the_same_digest_and_verdict(self):
        code, envelope = self.envelope()
        text_code, text, err = self.run_cli("--format", "text")
        self.assertEqual((text_code, err), (code, ""))
        self.assertIn(f"report_sha256: {envelope['report_sha256']}", text)
        self.assertIn(f"verdict: {vr.VALIDATION_COMPLETE}", text)
        self.assertIn("ADVISORY ONLY", text)

    def test_outputs_carry_no_paths_ids_emails_or_prose(self):
        _, envelope = self.envelope()
        out = cli.render_json(envelope)
        for text in (str(self.root), self.root.name, RUN, WORKER, EMAIL, "provider prose", "999", "abc1234",
                     "scripts/ai/x.py", "\\"):
            self.assertNotIn(text, out)


# ---------------------------------------------------------------------------
class SingleNegativeTests(_SingleRoots):
    def assert_review(self, codes, **seed):
        code, envelope = self.envelope(**seed)
        self.assertEqual((code, envelope["verdict"]), (cli.EXIT_HUMAN_REVIEW, vr.HUMAN_REVIEW_REQUIRED))
        for reason in codes:
            self.assertIn(reason, envelope["report"]["reason_codes"])
        self.assertFalse(envelope["report"]["classification"]["outcomes"][vr.VALIDATION_COMPLETE])
        assert_no_authority(self, envelope)
        return envelope

    def test_failed_worker_requires_human_review(self):
        self.assert_review([vc.WORK_NOT_SUCCESSFUL], worker_state="FAILED", work_status="FAILED",
                           work_status_source="PROVIDER", provider_work_status="FAILED", acceptance=None,
                           checkpoint_commit=None)

    def test_unsafe_verdict_requires_human_review(self):
        self.assert_review([vc.SAFETY_NOT_CLEAN], safety="UNSAFE")

    def test_unauthorized_path_with_unsafe_verdict_requires_human_review(self):
        self.assert_review([vc.SAFETY_NOT_CLEAN, vc.SCOPE_NOT_CLEAN], safety="UNSAFE",
                           unauthorized=("secrets/.env",))

    def test_scope_violation_with_clean_safety_is_inconsistent_not_complete(self):
        envelope = self.assert_review([vc.INCONSISTENT_SCOPE_VIOLATION_WITH_CLEAN_SAFETY],
                                      unauthorized=("secrets/.env",))
        self.assertNotIn("secrets", json.dumps(envelope))

    def test_incomplete_evidence_keeps_work_success_separate(self):
        envelope = self.assert_review([vc.EVIDENCE_INCOMPLETE], evidence_complete=False)
        outcomes = envelope["report"]["classification"]["outcomes"]
        self.assertTrue(outcomes[vr.WORK_SUCCESS])
        self.assertFalse(outcomes[vr.EVIDENCE_COMPLETE])

    def test_failed_acceptance_is_negative(self):
        envelope = self.assert_review([vc.WORK_NOT_SUCCESSFUL, vc.ACCEPTANCE_NOT_PROVEN], worker_state="FAILED",
                                      work_status="FAILED", work_status_source="PROVIDER",
                                      provider_work_status="FAILED", acceptance="FAILED", checkpoint_commit=None)
        self.assertIn("unit.0.acceptance_proven", envelope["report"]["claims"]["failed"])

    def test_runner_sourced_success_with_failed_acceptance_is_contradiction(self):
        envelope = self.assert_review([vr.OBSERVATION_CONTRADICTION], acceptance="FAILED")
        for claim in ("unit.0.work_success", "unit.0.acceptance_proven"):
            self.assertNotIn(claim, envelope["report"]["claims"]["verified"])

    def test_unknown_evidence_is_unproven_never_pass(self):
        code, envelope = self.envelope(evidence_complete=None)
        self.assertEqual((code, envelope["verdict"]), (cli.EXIT_UNPROVEN, vr.UNPROVEN))
        self.assertIn(vc.EVIDENCE_UNKNOWN, envelope["report"]["reason_codes"])
        self.assertIn("unit.0.evidence_complete", envelope["report"]["claims"]["unknown"])

    def test_provider_sourced_success_is_never_complete(self):
        code, envelope = self.envelope(work_status_source="PROVIDER")
        self.assertNotEqual(envelope["verdict"], vr.VALIDATION_COMPLETE)
        self.assertNotEqual(code, cli.EXIT_COMPLETE)
        self.assertNotIn("unit.0.work_success", envelope["report"]["claims"]["verified"])

    def test_missing_on_success_checkpoint_is_never_complete(self):
        code, envelope = self.envelope(checkpoint_commit=None)
        self.assertNotEqual(envelope["verdict"], vr.VALIDATION_COMPLETE)
        self.assertNotEqual(code, cli.EXIT_COMPLETE)

    def test_foreign_pipeline_result_is_refused_as_identity_mismatch(self):
        self.seed(pipeline_id="fdb-20261030t000000000000-ffffffff")
        code, out, err = self.run_cli()
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))
        self.assertTrue(err.startswith("error: VALIDATION_IDENTITY_MISMATCH: "), err)

    def test_corrupt_worker_result_degrades_to_unproven(self):
        self.seed()
        (self.state / RUN / "workers" / WORKER / "result.json").write_text("{corrupt " + EMAIL, encoding="utf-8")
        code, out, err = self.run_cli()
        self.assertEqual((code, err), (cli.EXIT_UNPROVEN, ""))
        self.assertNotIn(EMAIL, out)
        envelope = json.loads(out)
        self.assertEqual(envelope["verdict"], vr.UNPROVEN)
        self.assertEqual(envelope["report"]["claims"]["verified"], ["unit.0.provenance_bound"])
        for reason in (vc.WORK_SUCCESS_UNKNOWN, vc.EVIDENCE_UNKNOWN, vc.ACCEPTANCE_UNKNOWN):
            self.assertIn(reason, envelope["report"]["reason_codes"])

    def test_run_absent_from_state_root_is_refused(self):
        self.seed()
        code, out, err = self.run_cli(run_id="fdb-20261030t000000000000-00000000")
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))
        self.assertIn("VALIDATION_RUN_NOT_FOUND", err)

    def test_dag_command_on_single_run_is_refused(self):
        self.seed()
        code, out, err = self.run_cli(command="dag")
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))
        self.assertIn("VALIDATION_DAG_REQUEST_NOT_FOUND", err)


# ---------------------------------------------------------------------------
class DagEndToEndTests(tdd.DagTestBase):
    """Real Director DAG gateway over synthetic repos with the fake executor."""

    def run_dag(self, blueprint=None):
        svc, handle, summary, executor = self.submit_and_run(blueprint or self.chain())
        self.run_id = handle.pipeline_id
        return svc, summary

    def invoke(self, command="dag", *extra) -> tuple:
        with read_only_guard(self, self.root):
            return tc.invoke(argv(command, self.run_id, self.state_root, self.director_root, *extra))

    def worker_result_path(self, worker_id) -> Path:
        return self.state_root / self.run_id / "workers" / worker_id / "result.json"

    def test_real_chain_is_unproven_never_complete_and_report_verifies(self):
        svc, summary = self.run_dag()
        self.assertEqual(summary.aggregate_status, "SUCCESS")
        code, out, err = self.invoke()
        envelope = json.loads(out)
        self.assertEqual((code, err, envelope["verdict"]), (cli.EXIT_UNPROVEN, "", vr.UNPROVEN))
        report = envelope["report"]
        self.assertEqual(report["classification"]["source"], vr.SOURCE_DAG_RUN)
        self.assertEqual(report["classification"]["unit_count"], 3)
        for code_ in (vc.SAFETY_UNKNOWN, vc.ACCEPTANCE_UNKNOWN):
            self.assertIn(code_, report["reason_codes"])
        observation = vd.observe_dag_run(svc, self.run_id)
        self.assertTrue(rp.verify_report(report, observation=observation).valid)
        assert_no_authority(self, envelope)

    def test_real_diamond_projects_one_unit_per_worker_in_plan_order(self):
        svc, summary = self.run_dag(self.diamond())
        observation = vd.observe_dag_run(svc, self.run_id)
        self.assertEqual(len(observation.workers), 4)
        report = rp.build_report(observation)
        self.assertEqual(report.to_dict()["classification"]["unit_count"], 4)
        for status_ids in report.claims.values():
            for claim in status_ids:
                self.assertRegex(claim, r"^unit\.[0-3]\.[a-z_]+$")
        self.assertNotEqual(report.verdict, vr.VALIDATION_COMPLETE)

    def test_real_dag_report_hash_is_deterministic_and_bound(self):
        svc, _ = self.run_dag()
        first, second = self.invoke(), self.invoke()
        self.assertEqual(first, second)
        envelope = json.loads(first[1])
        expected = rp.build_report(vd.observe_dag_run(svc, self.run_id))
        self.assertEqual(envelope["report_sha256"], expected.report_sha256)
        for text in (str(self.root), self.run_id, "caller-dag", "provider prose", "\\"):
            self.assertNotIn(text, first[1])

    def test_mismatched_worker_record_requires_human_review(self):
        self.run_dag()
        path = self.worker_result_path("b")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["pipeline_id"] = "fdb-20261030t000000000000-ffffffff"
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out, _ = self.invoke()
        envelope = json.loads(out)
        self.assertEqual((code, envelope["verdict"]), (cli.EXIT_HUMAN_REVIEW, vr.HUMAN_REVIEW_REQUIRED))
        self.assertIn(vc.PROVENANCE_NOT_BOUND, envelope["report"]["reason_codes"])

    def test_missing_worker_record_is_never_complete(self):
        self.run_dag()
        self.worker_result_path("c").unlink()
        code, out, _ = self.invoke()
        envelope = json.loads(out)
        self.assertNotEqual(code, cli.EXIT_COMPLETE)
        self.assertNotEqual(envelope["verdict"], vr.VALIDATION_COMPLETE)
        self.assertIn("unit.2.provenance_bound", envelope["report"]["claims"]["unknown"])

    def test_tampered_provenance_is_refused(self):
        self.run_dag()
        path = self.director_root / self.run_id / fd.DAG_PROVENANCE_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["plan_fingerprint"] = "0" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out, err = self.invoke()
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))
        self.assertTrue(err.startswith("error: VALIDATION_IDENTITY_MISMATCH: "), err)
        self.assertIn("PROVENANCE_REFUSED", err)

    def test_single_command_on_dag_run_is_refused(self):
        self.run_dag()
        code, out, err = self.invoke("single")
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))
        self.assertIn("VALIDATION_MULTIWORKER_RUN", err)

    def test_acceptance_is_not_bindable_to_a_dag_report(self):
        svc, _ = self.run_dag()
        observation = vd.observe_dag_run(svc, self.run_id)
        with tempfile.TemporaryDirectory() as other:
            state, director = seed_single_run(Path(other).resolve())
            single_service = cli.build_service(str(state), str(director))
            projection = va.project_acceptance(single_service.evidence(RUN), RUN,
                                               completion_policy=va.POLICY_RUNNER_ACCEPTANCE,
                                               acceptance_commands=[CMD])
            single_observation = vs.observe_single_run(single_service, RUN)
        report = rp.build_report(observation, projection)
        self.assertIn(rp.ACCEPTANCE_NOT_BINDABLE, report.reason_codes)
        self.assertIsNone(report.to_dict()["acceptance"])
        self.assertNotEqual(report.verdict, vr.VALIDATION_COMPLETE)
        verification = rp.verify_report(report, observation=single_observation)
        self.assertFalse(verification.valid)
        self.assertIn("SOURCE_BINDING_MISMATCH", verification.codes)


# ---------------------------------------------------------------------------
class ReportTamperingTests(_SingleRoots):
    def setUp(self):
        super().setUp()
        self.seed(evidence_complete=False)
        self.observation = vs.observe_single_run(self.service(), RUN)
        self.report = rp.build_report(self.observation).to_dict()
        self.assertEqual(self.report["verdict"], vr.HUMAN_REVIEW_REQUIRED)

    def assert_invalid(self, data, code):
        verification = rp.verify_report(data)
        self.assertFalse(verification.valid)
        self.assertIn(code, verification.codes)
        self.assertIsNone(verification.report_sha256)

    def test_upgraded_verdict_is_rejected(self):
        self.report["verdict"] = vr.VALIDATION_COMPLETE
        self.assert_invalid(self.report, "CONTENT_MISMATCH")

    def test_failed_claim_moved_to_verified_is_rejected(self):
        claims = self.report["claims"]
        claims["verified"].append(claims["failed"].pop())
        self.assertFalse(rp.verify_report(self.report).valid)

    def test_any_authority_flag_set_true_is_rejected(self):
        for flag in rp.AUTHORITY_FLAGS:
            with self.subTest(flag=flag):
                data = dict(self.report, **{flag: True})
                self.assert_invalid(data, "AUTHORITY_FLAG_INVALID")

    def test_forged_digest_is_rejected(self):
        self.report["report_sha256"] = "0" * 64
        self.assert_invalid(self.report, "DIGEST_MISMATCH")

    def test_report_from_another_run_does_not_bind(self):
        with tempfile.TemporaryDirectory() as other:
            state, director = seed_single_run(Path(other).resolve(), safety="UNSAFE")
            foreign = vs.observe_single_run(cli.build_service(str(state), str(director)), RUN)
        self.assertTrue(rp.verify_report(self.report).valid)
        verification = rp.verify_report(self.report, observation=foreign)
        self.assertFalse(verification.valid)
        self.assertIn("SOURCE_BINDING_MISMATCH", verification.codes)


# ---------------------------------------------------------------------------
class DegenerateInputTests(unittest.TestCase):
    def test_non_observation_inputs_are_never_complete(self):
        for value in (None, {}, "VALIDATION_COMPLETE", 1, vc.ValidationFacts(True, True, True, True, True, True)):
            with self.subTest(value=repr(value)):
                report = rp.build_report(value)
                self.assertNotEqual(report.verdict, vr.VALIDATION_COMPLETE)
                self.assertTrue(rp.verify_report(report).valid)
                self.assertEqual(report.claims["verified"], ())

    def test_all_unknown_facts_are_unproven_never_ready(self):
        assessment = vc.assess_validation(vc.ValidationFacts())
        self.assertFalse(assessment.ready_for_human_review)
        report = rp.build_report(assessment)
        self.assertEqual(report.verdict, vr.UNPROVEN)
        self.assertEqual(len(report.claims["unknown"]), len(vc.DIMENSIONS))

    def test_truthy_non_bool_facts_are_malformed_never_verified(self):
        report = rp.build_report(vc.assess_validation(vc.ValidationFacts(1, "True", 1, 1, 1, 1)))
        self.assertEqual(report.claims["verified"], ())
        self.assertNotEqual(report.verdict, vr.VALIDATION_COMPLETE)

    def test_unknown_verdict_never_maps_to_exit_zero(self):
        for verdict in (None, "UNKNOWN", "PASS", "SUCCESS", ""):
            self.assertEqual(cli.exit_code_for({"verdict": verdict}), cli.EXIT_REFUSED)


# ---------------------------------------------------------------------------
class NoAuthorityTests(unittest.TestCase):
    def test_guarantee_properties_cannot_be_raised(self):
        assessment = vc.assess_validation(vc.ValidationFacts(True, True, True, True, True, True))
        report = rp.build_report(assessment)
        for obj in (assessment, vr.classify_evidence(assessment), report):
            for flag in CONTRACT_FLAGS:
                self.assertIs(getattr(obj, flag), False)
                with self.assertRaises(AttributeError):
                    setattr(obj, flag, True)

    def test_fcp8_modules_import_no_process_network_or_runner_execution(self):
        forbidden = ("subprocess", "socket", "urllib", "http", "requests", "shutil", "runner_pipeline",
                     "claude_runner", "runner_providers", "runner_promotion")
        for module in FCP8_MODULES:
            tree = ast.parse((REPO_ROOT / "scripts" / "ai" / f"fabric_validation_{module}.py")
                             .read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported |= {node.module or ""} | {f"{node.module}.{a.name}" for a in node.names}
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            for name in imported:
                for word in forbidden:
                    self.assertNotIn(word, name, f"{module}: {name}")
            for word in ("environ", "getenv", "write_text", "write_bytes", "submit_blueprint", "run_blueprint",
                         "execute_work_order"):
                self.assertNotIn(word, attrs, f"{module}: {word}")


# ---------------------------------------------------------------------------
class CiStepTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.lines = self.text.split("\n")

    def _job_steps(self, job):
        block = re.search(rf"(?ms)^  {job}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.text).group(1)
        return re.findall(r"(?m)^      - name: (.+)$", block), block

    def test_nine_jobs_read_only_permissions_and_50_minute_timeout(self):
        jobs = re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: ", self.text)
        self.assertEqual(len(jobs), 9)
        self.assertEqual(jobs[0], "fabric-regression")
        self.assertEqual(self.text.count("permissions:"), 1)
        self.assertIn("permissions:\n  contents: read\n", self.text)
        _, block = self._job_steps("fabric-regression")
        self.assertIn("    timeout-minutes: 50\n", block)

    def test_single_step_sits_after_fcp7a_and_before_fcp6b(self):
        steps, _ = self._job_steps("fabric-regression")
        self.assertEqual(self.text.count(CI_STEP_NAME), 1)
        idx = steps.index(CI_STEP_NAME)
        self.assertEqual(steps[idx - 1], "FCP-7A-01 provider routing pure policy regression without skipped tests")
        self.assertEqual(steps[idx + 1], "FCP-6B-01 recovery advisory read-only regression without skipped tests")
        self.assertEqual(steps[1:3], ["Setup Python 3.11", "Environment"])
        self.assertEqual(steps[-1], "FCP-5B-01 Director DAG gateway regression without skipped tests")

    def test_step_runs_exactly_the_eight_fcp8_suites_with_strict_gates(self):
        start = self.lines.index(f"      - name: {CI_STEP_NAME}")
        self.assertEqual(self.lines[start + 1], "        run: |")
        self.assertEqual(self.lines[start + 3], "")
        step = self.lines[start + 2]
        self.assertEqual(re.findall(r"scripts\.tests\.(\w+)", step), list(FCP8_SUITES))
        for gate in ("r.wasSuccessful()", "r.testsRun == sum(c)", "sum(c) >= 200", "min(c) >= 25",
                     "not r.skipped", "not r.expected" + "Failures", "not r.unexpectedSuccesses"):
            self.assertIn(gate, step)
        for suite in FCP8_SUITES:
            self.assertEqual(self.text.count(suite), 1, suite)

    def test_gated_suites_meet_the_declared_minimums(self):
        counts = [unittest.defaultTestLoader.loadTestsFromName(f"scripts.tests.{n}").countTestCases()
                  for n in FCP8_SUITES]
        self.assertGreaterEqual(sum(counts), 200)
        self.assertGreaterEqual(min(counts), 25)

    def test_prior_stage_gates_are_preserved(self):
        for gate in ("min(c) >= 45", "r.testsRun >= 45 and not r.skipped", "r.testsRun >= 35 and not r.skipped",
                     "r.testsRun >= 30 and not r.skipped", "r.testsRun >= 122 and not r.skipped",
                     "loadTestsFromName('scripts.tests.test_fabric_dag_blueprint')",
                     "loadTestsFromName('scripts.tests.test_fabric_director_dag')"):
            self.assertIn(gate, self.text)


if __name__ == "__main__":
    unittest.main()
