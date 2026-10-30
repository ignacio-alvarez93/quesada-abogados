"""FCP-8A-02: single-worker validation evidence adapter over the Director's
`result`/`evidence`/`decision` projections. Offline, synthetic fake service
only - no Runner, Git, process, network or file is touched."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_validation_contract as vc
from scripts.ai import fabric_validation_single as vs

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_validation_single.py"

RUN = "fdb-20261030t000000000000-abcdef12"
WORKER = "w-01"
SECRET_DIR = "C:/Users/someone/private/evidence/attempt-1"
EMAIL = "person@example.invalid"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
             "auto_retry_allowed", "resume_allowed")
FORBIDDEN_METHODS = ("submit", "run", "recover", "submit_and_run", "validate", "execute_work_order",
                     "run_blueprint", "submit_blueprint", "status", "_load_json")


def summary(**overrides) -> fd.DirectorRunSummary:
    values = dict(
        run_id=RUN, pipeline_id=RUN, status="SUCCESS", worker_id=WORKER, provider="claude",
        requested_provider="claude", worker_state="SUCCESS", state_reason=None, work_status="SUCCESS",
        provider_work_status="SUCCESS", work_status_source="RUNNER_ACCEPTANCE", runner_state="SUCCESS",
        attempts=1, checkpoint_commit="abc1234", evidence_dir=SECRET_DIR, evidence_complete=True,
        changed_paths=("scripts/ai/x.py",), authorized_changed_paths=("scripts/ai/x.py",),
        unauthorized_changed_paths=(), work_product_present=True, completion_mode="CHECKPOINT",
    )
    values.update(overrides)
    return fd.DirectorRunSummary(**values)


def evidence(**overrides) -> fd.DirectorRunEvidence:
    values = dict(
        run_id=RUN, pipeline_id=RUN, worker_id=WORKER, provider="claude", requested_provider="claude",
        worker_state="SUCCESS", work_status="SUCCESS", provider_work_status="SUCCESS",
        work_status_source="RUNNER_ACCEPTANCE", runner_state="SUCCESS", execution_mode="write",
        safety_verdict="SAFE", changed_paths=("scripts/ai/x.py",), authorized_changed_paths=("scripts/ai/x.py",),
        unauthorized_changed_paths=(), evidence_dir=SECRET_DIR, evidence_complete=True,
        preflight={"author": EMAIL, "path": SECRET_DIR}, normalized_result={"summary": "provider prose"},
        work_product_present=True, checkpoint_policy="ON_SUCCESS", checkpoint_commit="abc1234",
        acceptance={"decision": "PASSED", "commands": [{"command": f"pytest {SECRET_DIR}", "exit_code": 0}]},
    )
    values.update(overrides)
    return fd.DirectorRunEvidence(**values)


def consistent(summary_overrides=None, evidence_overrides=None, shared=None):
    """A summary/evidence pair plus the Director's OWN decision over them.
    `shared` applies to whichever of the two dataclasses has the field."""
    def own(cls):
        names = {f.name for f in dataclasses.fields(cls)}
        return {k: v for k, v in (shared or {}).items() if k in names}

    s = summary(**{**own(fd.DirectorRunSummary), **(summary_overrides or {})})
    e = evidence(**{**own(fd.DirectorRunEvidence), **(evidence_overrides or {})})
    return s, e, fd._classify_decision(s, e)


class FakeService:
    """Only `result`/`evidence`/`decision` exist; any other attribute access
    is recorded and fails."""

    def __init__(self, s, e, d, *, raises=None):
        self.__dict__["calls"] = []
        self.__dict__["forbidden"] = []
        self.__dict__["_values"] = {"result": s, "evidence": e, "decision": d}
        self.__dict__["_raises"] = raises or {}

    def _read(self, name, run_id):
        self.calls.append((name, run_id))
        if name in self._raises:
            raise self._raises[name]
        return self._values[name]

    def result(self, run_id):
        return self._read("result", run_id)

    def evidence(self, run_id):
        return self._read("evidence", run_id)

    def decision(self, run_id):
        return self._read("decision", run_id)

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"forbidden access: {name}")

    def __setattr__(self, name, value):
        raise AssertionError(f"forbidden write: {name}")


def observe(s, e, d, **kwargs):
    service = FakeService(s, e, d, **kwargs)
    return vs.observe_single_run(service, RUN), service


def observe_consistent(summary_overrides=None, evidence_overrides=None, shared=None):
    return observe(*consistent(summary_overrides, evidence_overrides, shared))[0]


def fact(o, name):
    return getattr(o.facts, name)


def all_unknown_except(o, **expected):
    for name in vc.DIMENSIONS:
        if getattr(o.facts, name) is not expected.get(name):
            return False
    return True


# ---------------------------------------------------------------------------
class ReadDisciplineTests(unittest.TestCase):
    def test_each_source_read_exactly_once_in_order(self):
        _, service = observe(*consistent())
        self.assertEqual(service.calls, [("result", RUN), ("evidence", RUN), ("decision", RUN)])

    def test_no_forbidden_method_is_touched(self):
        _, service = observe(*consistent())
        self.assertEqual(service.forbidden, [])

    def test_failing_read_still_reads_the_others_once(self):
        _, service = observe(*consistent(), raises={"result": RuntimeError("boom")})
        self.assertEqual([c[0] for c in service.calls], ["result", "evidence", "decision"])

    def test_sources_are_not_mutated(self):
        s, e, d = consistent()
        before = copy.deepcopy((s, e, d))
        observe(s, e, d)
        self.assertEqual((s, e, d), before)

    def test_no_io_process_or_network_during_observation(self):
        s, e, d = consistent()
        boom = mock.Mock(side_effect=AssertionError("io"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(Path, "read_text", boom), mock.patch.object(Path, "write_text", boom):
            o, _ = observe(s, e, d)
        boom.assert_not_called()
        self.assertEqual(o.assessment.classification, vc.READY_FOR_HUMAN_REVIEW)

    def test_module_source_has_no_dispatch_io_or_runner_imports(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(f"{node.module}.{a.name}" if node.module else a.name for a in node.names)
                imported.add(node.module or "")
        allowed = {"__future__", "__future__.annotations", "json", "dataclasses", "dataclasses.dataclass",
                   "typing", "typing.Optional", "scripts.ai", "scripts.ai.fabric_director",
                   "scripts.ai.fabric_validation_contract", "fabric_director", "fabric_validation_contract"}
        self.assertEqual(imported - allowed, set())
        called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for name in FORBIDDEN_METHODS + ("PipelineRunner", "open", "Popen", "system", "read_text",
                                         "write_text", "_classify_decision"):
            self.assertNotIn(name, called)


class AuthorityAndPrivacyTests(unittest.TestCase):
    def test_every_authority_flag_is_false(self):
        o = observe_consistent()
        for flag in ALL_FLAGS:
            self.assertIs(getattr(o, flag), False)
            self.assertIs(o.to_dict()[flag], False)
        self.assertEqual(o.to_dict()["marker"], vs.OBSERVATION_MARKER)

    def test_flags_cannot_be_set(self):
        o = observe_consistent()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            o.certified = True  # type: ignore[misc]
        with self.assertRaises(TypeError):
            dataclasses.replace(o, certified=True)

    def test_report_contains_no_ids_paths_pii_or_provider_text(self):
        text = vs.canonical_json(observe_consistent())
        for needle in (RUN, WORKER, SECRET_DIR, "private", EMAIL, "pytest", "provider prose", "scripts/ai",
                       "abc1234", "claude"):
            self.assertNotIn(needle, text)

    def test_canonical_json_is_deterministic_and_typed(self):
        a, b = observe_consistent(), observe_consistent()
        self.assertEqual(vs.canonical_json(a), vs.canonical_json(b))
        self.assertEqual(json.loads(vs.canonical_json(a))["schema"], vs.SCHEMA)
        with self.assertRaises(TypeError):
            vs.canonical_json(a.to_dict())

    def test_observation_rejects_tampered_assessment_or_codes(self):
        o = observe_consistent()
        forged = vc.assess_validation(vc.ValidationFacts(*(True,) * 6))
        with self.assertRaises(ValueError):
            vs.SingleRunObservation(facts=vc.ValidationFacts(), assessment=forged, observation_codes=())
        with self.assertRaises(ValueError):
            dataclasses.replace(o, observation_codes=("WORKER_ID_MISSING", "RUN_ID_INVALID"))
        with self.assertRaises(ValueError):
            dataclasses.replace(o, observation_codes=("NOT_A_CODE",))


class PositiveTests(unittest.TestCase):
    def test_fully_proven_run_is_ready_for_human_review_only(self):
        o = observe_consistent()
        self.assertEqual(o.assessment.classification, vc.READY_FOR_HUMAN_REVIEW)
        self.assertTrue(all(fact(o, d) is True for d in vc.DIMENSIONS))
        self.assertEqual(o.decision_code, "READY_FOR_HOST_AUDIT")
        self.assertEqual(o.checkpoint, vs.CHECKPOINT_RECORDED)
        self.assertEqual(o.preflight, vs.PREFLIGHT_OBSERVED)
        self.assertFalse(o.certified)

    def test_success_noop_without_checkpoint_policy(self):
        o = observe_consistent(
            {"completion_mode": "SUCCESS_NOOP"},
            {"checkpoint_policy": None},
            shared={"changed_paths": (), "authorized_changed_paths": (), "work_product_present": False,
                    "checkpoint_commit": None},
        )
        self.assertIs(fact(o, vc.WORK_SUCCESS), True)
        self.assertIs(fact(o, vc.SCOPE_CLEAN), True)
        self.assertEqual(o.completion_mode, "SUCCESS_NOOP")
        self.assertEqual(o.checkpoint, vs.CHECKPOINT_ABSENT)

    def test_provider_divergence_is_reported_not_hidden(self):
        o = observe_consistent(shared={"provider_work_status": "PARTIAL"})
        self.assertIs(fact(o, vc.WORK_SUCCESS), True)
        self.assertIn("PROVIDER_WORK_STATUS_DIVERGES", o.observation_codes)
        self.assertEqual((o.provider_work_status, o.work_status, o.work_status_source),
                         ("PARTIAL", "SUCCESS", "RUNNER_ACCEPTANCE"))


class WorkStatusSourceTests(unittest.TestCase):
    def test_provider_sourced_success_is_not_certified(self):
        o = observe_consistent(shared={"work_status_source": "PROVIDER"}, evidence_overrides={"acceptance": None})
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIsNone(fact(o, vc.ACCEPTANCE_PROVEN))
        self.assertIn("WORK_STATUS_PROVIDER_ONLY", o.observation_codes)
        self.assertIn("ACCEPTANCE_ABSENT", o.observation_codes)
        self.assertFalse(o.assessment.ready_for_human_review)

    def test_unverified_work_status_on_success_worker_is_unknown(self):
        o = observe_consistent(shared={"work_status": "UNVERIFIED", "work_status_source": "PROVIDER"},
                               evidence_overrides={"acceptance": None})
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("WORK_STATUS_NOT_CERTIFIED_SUCCESS", o.observation_codes)

    def test_missing_work_status_source_is_unknown(self):
        o = observe_consistent(shared={"work_status_source": None}, evidence_overrides={"acceptance": None})
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("WORK_STATUS_SOURCE_MISSING", o.observation_codes)

    def test_unrecognized_work_status_source(self):
        o = observe_consistent(shared={"work_status_source": "SELF_REPORTED"})
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertEqual(o.work_status_source, vs.UNRECOGNIZED)

    def test_runner_source_without_acceptance_record_is_contradiction(self):
        o = observe_consistent(evidence_overrides={"acceptance": None})
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIsNone(fact(o, vc.ACCEPTANCE_PROVEN))
        self.assertIn("ACCEPTANCE_SOURCE_CONTRADICTION", o.observation_codes)

    def test_passed_acceptance_without_runner_source_is_not_proven(self):
        o = observe_consistent(shared={"work_status_source": "PROVIDER"})
        self.assertIsNone(fact(o, vc.ACCEPTANCE_PROVEN))
        self.assertIn("ACCEPTANCE_SOURCE_CONTRADICTION", o.observation_codes)

    def test_failed_acceptance_on_failed_worker(self):
        o = observe_consistent(shared={"worker_state": "FAILED", "work_status": "SUCCESS",
                                       "work_status_source": "PROVIDER", "checkpoint_commit": None,
                                       "completion_mode": None},
                               evidence_overrides={"acceptance": {"decision": "FAILED", "commands": []}})
        self.assertIs(fact(o, vc.WORK_SUCCESS), False)
        self.assertIs(fact(o, vc.ACCEPTANCE_PROVEN), False)
        self.assertIn("RECOVERY_DECISION_NOT_ELEVATED", o.observation_codes)

    def test_malformed_acceptance_decision(self):
        for bad in ({"decision": True}, ["PASSED"], "PASSED"):
            with self.subTest(bad=bad):
                o = observe_consistent(evidence_overrides={"acceptance": bad})
                self.assertIsNone(fact(o, vc.ACCEPTANCE_PROVEN))
                self.assertIsNone(fact(o, vc.WORK_SUCCESS))
                self.assertIn("FIELD_MALFORMED", o.observation_codes)


class EvidenceCompletenessTests(unittest.TestCase):
    def test_incomplete_evidence_keeps_work_success(self):
        o = observe_consistent(shared={"evidence_complete": False})
        self.assertEqual(o.decision_code, "EVIDENCE_REVIEW_REQUIRED")
        self.assertIs(fact(o, vc.EVIDENCE_COMPLETE), False)
        self.assertIs(fact(o, vc.WORK_SUCCESS), True)
        self.assertEqual(o.assessment.classification, vc.TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT)

    def test_unknown_evidence_is_never_true(self):
        o = observe_consistent(shared={"evidence_complete": None})
        self.assertIsNone(fact(o, vc.EVIDENCE_COMPLETE))
        self.assertIn("EVIDENCE_COMPLETE_UNKNOWN", o.observation_codes)
        self.assertFalse(o.assessment.evidence_sufficient)

    def test_evidence_mismatch_is_unknown_without_touching_work(self):
        s, e, d = consistent()
        o, _ = observe(dataclasses.replace(s, evidence_complete=False), e, d)
        self.assertIsNone(fact(o, vc.EVIDENCE_COMPLETE))
        self.assertIn("EVIDENCE_COMPLETE_MISMATCH", o.observation_codes)
        self.assertIs(fact(o, vc.SAFETY_CLEAN), True)

    def test_malformed_evidence_complete(self):
        for bad in (1, "True", 0):
            with self.subTest(bad=bad):
                s, e, d = consistent()
                o, _ = observe(s, dataclasses.replace(e, evidence_complete=bad), d)
                self.assertIsNone(fact(o, vc.EVIDENCE_COMPLETE))
                self.assertIn("FIELD_MALFORMED", o.observation_codes)

    def test_evidence_complete_independent_of_other_conditions(self):
        variants = {
            "failed": {"shared": {"worker_state": "FAILED", "completion_mode": None}},
            "partial": {"shared": {"worker_state": "PARTIAL", "completion_mode": None}},
            "quota": {"shared": {"worker_state": "WAITING_PROVIDER_QUOTA", "completion_mode": None,
                                 "provider_condition": "PROVIDER_QUOTA_EXHAUSTED"}},
            "auth": {"shared": {"worker_state": "BLOCKED_PROVIDER_AUTH", "completion_mode": None,
                                "provider_condition": "PROVIDER_AUTH_BLOCKED"}},
            "unsafe": {"evidence_overrides": {"safety_verdict": "UNSAFE"}},
            "unauthorized": {"shared": {"unauthorized_changed_paths": ("outside.py",)}},
            "preflight": {"evidence_overrides": {"preflight": ["not", "a", "dict"]}},
            "no_preflight": {"evidence_overrides": {"preflight": None}},
            "checkpoint": {"shared": {"checkpoint_commit": None}},
        }
        for value in (True, False, None):
            for name, kw in variants.items():
                with self.subTest(value=value, variant=name):
                    shared = {**kw.get("shared", {}), "evidence_complete": value}
                    o = observe_consistent(kw.get("summary_overrides"), kw.get("evidence_overrides"), shared)
                    self.assertIs(fact(o, vc.EVIDENCE_COMPLETE), value)
                    # Preflight is reported only; every other variant blocks readiness.
                    self.assertIs(o.assessment.ready_for_human_review,
                                  value is True and name in ("preflight", "no_preflight"))


class SafetyScopeTests(unittest.TestCase):
    def test_unsafe_verdict(self):
        o = observe_consistent(evidence_overrides={"safety_verdict": "UNSAFE"})
        self.assertEqual(o.decision_code, "SAFETY_REVIEW_REQUIRED")
        self.assertIs(fact(o, vc.SAFETY_CLEAN), False)
        self.assertIs(fact(o, vc.WORK_SUCCESS), True)
        self.assertFalse(o.assessment.technical_success)

    def test_unauthorized_paths(self):
        o = observe_consistent(shared={"unauthorized_changed_paths": ("C:/elsewhere/secret.py",)},
                               evidence_overrides={"safety_verdict": "UNSAFE"})
        self.assertIs(fact(o, vc.SCOPE_CLEAN), False)
        self.assertIn("UNAUTHORIZED_PATHS_PRESENT", o.observation_codes)
        self.assertNotIn("elsewhere", vs.canonical_json(o))

    def test_missing_safety_verdict(self):
        o = observe_consistent(evidence_overrides={"safety_verdict": None})
        self.assertIsNone(fact(o, vc.SAFETY_CLEAN))
        self.assertIsNone(fact(o, vc.SCOPE_CLEAN))
        self.assertIn("SAFETY_VERDICT_ABSENT", o.observation_codes)

    def test_empty_paths_without_observed_metadata_are_not_clean(self):
        o = observe_consistent(shared={"work_product_present": None, "changed_paths": (),
                                       "authorized_changed_paths": ()})
        self.assertIsNone(fact(o, vc.SCOPE_CLEAN))
        self.assertIn("SCOPE_UNOBSERVED", o.observation_codes)

    def test_unauthorized_paths_mismatch_and_list_type(self):
        s, e, d = consistent()
        o, _ = observe(s, dataclasses.replace(e, unauthorized_changed_paths=("x.py",)), d)
        self.assertIsNone(fact(o, vc.SCOPE_CLEAN))
        self.assertIn("UNAUTHORIZED_PATHS_MISMATCH", o.observation_codes)
        o, _ = observe(dataclasses.replace(s, unauthorized_changed_paths=[]), e, d)
        self.assertIsNone(fact(o, vc.SCOPE_CLEAN))
        self.assertIn("FIELD_MALFORMED", o.observation_codes)

    def test_safety_decision_contradicting_clean_facts(self):
        s, e, d = consistent()
        o, _ = observe(s, e, dataclasses.replace(d, decision_code="SAFETY_REVIEW_REQUIRED"))
        self.assertIsNone(fact(o, vc.SAFETY_CLEAN))
        self.assertIsNone(fact(o, vc.SCOPE_CLEAN))
        self.assertIn("DECISION_CONTRADICTS_SOURCES", o.observation_codes)


class ProviderConditionTests(unittest.TestCase):
    def test_auth_blocked(self):
        o = observe_consistent(shared={"worker_state": "BLOCKED_PROVIDER_AUTH", "completion_mode": None,
                                       "provider_condition": "PROVIDER_AUTH_BLOCKED"})
        self.assertEqual(o.decision_code, "PROVIDER_AUTH_REQUIRED")
        self.assertIs(fact(o, vc.WORK_SUCCESS), False)
        self.assertIn("PROVIDER_AUTH_BLOCKED", o.observation_codes)

    def test_quota_wait_is_unknown_not_failure(self):
        o = observe_consistent(shared={"worker_state": "WAITING_PROVIDER_QUOTA", "completion_mode": None,
                                       "provider_condition": "PROVIDER_QUOTA_EXHAUSTED"})
        self.assertEqual(o.decision_code, "WAITING_PROVIDER")
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("PROVIDER_QUOTA_WAIT", o.observation_codes)
        self.assertIn("WORKER_NOT_TERMINAL", o.observation_codes)

    def test_provider_condition_on_success_worker_is_unknown(self):
        s, e, d = consistent()
        cond = {"provider_condition": "PROVIDER_QUOTA_EXHAUSTED"}
        o, _ = observe(dataclasses.replace(s, **cond), dataclasses.replace(e, **cond),
                       dataclasses.replace(d, **cond))
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("PROVIDER_CONDITION_CONFLICTS_SUCCESS", o.observation_codes)

    def test_provider_condition_mismatch(self):
        s, e, d = consistent()
        o, _ = observe(s, dataclasses.replace(e, provider_condition="PROVIDER_AUTH_BLOCKED"), d)
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("PROVIDER_CONDITION_MISMATCH", o.observation_codes)


class WorkerStateTests(unittest.TestCase):
    def test_partial_and_recovery_decisions_never_elevate(self):
        for state in ("PARTIAL", "INTERRUPTED", "BLOCKED", "FAILED"):
            with self.subTest(state=state):
                o = observe_consistent(shared={"worker_state": state, "completion_mode": None})
                self.assertIs(fact(o, vc.WORK_SUCCESS), False)
                self.assertIn(o.decision_code, vs.RECOVERY_DECISION_CODES)
                self.assertIn("RECOVERY_DECISION_NOT_ELEVATED", o.observation_codes)
                self.assertFalse(o.assessment.technical_success)

    def test_in_progress_is_unknown(self):
        o = observe_consistent(shared={"worker_state": "RUNNING", "completion_mode": None})
        self.assertEqual(o.decision_code, "IN_PROGRESS")
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("WORKER_NOT_TERMINAL", o.observation_codes)

    def test_unrecognized_or_absent_worker_state(self):
        for state in ("DONE", None):
            with self.subTest(state=state):
                o = observe_consistent(shared={"worker_state": state, "completion_mode": None})
                self.assertIsNone(fact(o, vc.WORK_SUCCESS))
                self.assertIn("WORKER_STATE_UNKNOWN", o.observation_codes)
        self.assertEqual(observe_consistent(shared={"worker_state": "DONE"}).worker_state, vs.UNRECOGNIZED)

    def test_worker_state_mismatch_keeps_evidence(self):
        s, e, d = consistent()
        o, _ = observe(s, e, dataclasses.replace(d, worker_state="FAILED"))
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIs(fact(o, vc.EVIDENCE_COMPLETE), True)
        self.assertIn("WORKER_STATE_MISMATCH", o.observation_codes)

    def test_work_status_mismatch(self):
        s, e, d = consistent()
        o, _ = observe(s, dataclasses.replace(e, work_status="FAILED"), d)
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("WORK_STATUS_MISMATCH", o.observation_codes)


class CheckpointTests(unittest.TestCase):
    def test_missing_on_success_checkpoint(self):
        o = observe_consistent(shared={"checkpoint_commit": None, "completion_mode": None})
        self.assertEqual(o.decision_code, "CHECKPOINT_REVIEW_REQUIRED")
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIs(fact(o, vc.EVIDENCE_COMPLETE), True)
        self.assertIn("CHECKPOINT_MISSING", o.observation_codes)
        self.assertEqual(o.checkpoint, vs.CHECKPOINT_ABSENT)

    def test_checkpoint_mismatch(self):
        s, e, d = consistent()
        o, _ = observe(s, e, dataclasses.replace(d, checkpoint_commit="other"))
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertEqual(o.checkpoint, vs.CHECKPOINT_UNKNOWN)
        self.assertIn("CHECKPOINT_MISMATCH", o.observation_codes)


class IdentityJoinTests(unittest.TestCase):
    def test_run_id_mismatch(self):
        s, e, d = consistent()
        o, _ = observe(dataclasses.replace(s, run_id="fdb-other"), e, d)
        self.assertTrue(all_unknown_except(o, provenance_bound=False))
        self.assertIn("RUN_ID_MISMATCH", o.observation_codes)

    def test_pipeline_id_mismatch(self):
        s, e, d = consistent()
        o, _ = observe(s, dataclasses.replace(e, pipeline_id="fdb-other"), d)
        self.assertTrue(all_unknown_except(o, provenance_bound=False))
        self.assertIn("PIPELINE_ID_MISMATCH", o.observation_codes)

    def test_worker_id_mismatch(self):
        s, e, d = consistent()
        o, _ = observe(s, e, dataclasses.replace(d, worker_id="w-02"))
        self.assertTrue(all_unknown_except(o, provenance_bound=False))
        self.assertIn("WORKER_ID_MISMATCH", o.observation_codes)
        self.assertNotIn("w-02", vs.canonical_json(o))

    def test_missing_worker_is_unknown_everywhere(self):
        o = observe_consistent(shared={"worker_id": None})
        self.assertTrue(all_unknown_except(o))
        self.assertEqual(o.observation_codes, ("WORKER_ID_MISSING",))

    def test_malformed_identity(self):
        s, e, d = consistent()
        o, _ = observe(dataclasses.replace(s, worker_id=7), e, d)
        self.assertTrue(all_unknown_except(o))
        self.assertEqual(o.observation_codes, ("IDENTITY_MALFORMED",))

    def test_invalid_run_id_reads_nothing(self):
        for bad in (None, "", 5, b"fdb-x"):
            with self.subTest(bad=bad):
                service = FakeService(*consistent())
                o = vs.observe_single_run(service, bad)
                self.assertEqual(service.calls, [])
                self.assertEqual(o.observation_codes, ("RUN_ID_INVALID",))
                self.assertTrue(all_unknown_except(o))


class SourceTypingTests(unittest.TestCase):
    def test_read_exception_is_unknown(self):
        o, _ = observe(*consistent(), raises={"evidence": OSError("disk")})
        self.assertTrue(all_unknown_except(o))
        self.assertEqual(o.observation_codes, ("EVIDENCE_READ_FAILED",))

    def test_multiworker_refusal(self):
        err = fd.DirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", "dag")
        o, _ = observe(*consistent(), raises={"result": err, "evidence": err, "decision": err})
        self.assertEqual(o.observation_codes, ("MULTIWORKER_REFUSED",))
        self.assertTrue(all_unknown_except(o))

    def test_other_director_error(self):
        o, _ = observe(*consistent(), raises={"decision": fd.DirectorError("X", "y")})
        self.assertEqual(o.observation_codes, ("DECISION_READ_FAILED",))

    def test_wrong_types_including_subclasses_and_dicts(self):
        class SubSummary(fd.DirectorRunSummary):
            pass

        s, e, d = consistent()
        o, _ = observe(SubSummary(**dataclasses.asdict(s)), dataclasses.asdict(e), None)
        self.assertEqual(o.observation_codes, ("RESULT_NOT_TYPED", "EVIDENCE_NOT_TYPED", "DECISION_NOT_TYPED"))
        self.assertTrue(all_unknown_except(o))

    def test_service_without_methods(self):
        o = vs.observe_single_run(object(), RUN)
        self.assertEqual(o.observation_codes, ("RESULT_READ_FAILED", "EVIDENCE_READ_FAILED",
                                               "DECISION_READ_FAILED"))
        self.assertTrue(all_unknown_except(o))

    def test_unrecognized_decision_code(self):
        s, e, d = consistent()
        for bad in ("APPROVED", None, 3):
            with self.subTest(bad=bad):
                o, _ = observe(s, e, dataclasses.replace(d, decision_code=bad))
                self.assertEqual(o.observation_codes, ("DECISION_CODE_UNRECOGNIZED",))
                self.assertTrue(all_unknown_except(o))

    def test_malformed_preflight_is_reported_only(self):
        o = observe_consistent(evidence_overrides={"preflight": "ok"})
        self.assertEqual(o.preflight, vs.PREFLIGHT_MALFORMED)
        self.assertIn("PREFLIGHT_MALFORMED", o.observation_codes)
        self.assertEqual(o.assessment.classification, vc.READY_FOR_HUMAN_REVIEW)


class DecisionContradictionTests(unittest.TestCase):
    def test_ready_decision_over_failed_worker(self):
        s, e, d = consistent(shared={"worker_state": "FAILED", "completion_mode": None})
        o, _ = observe(s, e, dataclasses.replace(d, decision_code="READY_FOR_HOST_AUDIT"))
        self.assertIsNone(fact(o, vc.WORK_SUCCESS))
        self.assertIn("DECISION_CONTRADICTS_SOURCES", o.observation_codes)

    def test_non_success_decision_over_success_facts(self):
        s, e, d = consistent()
        for code in ("IN_PROGRESS", "FAILED_REVIEW_REQUIRED", "REVIEW_REQUIRED", "CANCELLED", "WAITING_PROVIDER"):
            with self.subTest(code=code):
                o, _ = observe(s, e, dataclasses.replace(d, decision_code=code))
                self.assertIsNone(fact(o, vc.WORK_SUCCESS))
                self.assertIn("DECISION_CONTRADICTS_SOURCES", o.observation_codes)
                self.assertFalse(o.assessment.ready_for_human_review)

    def test_evidence_review_decision_over_complete_evidence(self):
        s, e, d = consistent()
        o, _ = observe(s, e, dataclasses.replace(d, decision_code="EVIDENCE_REVIEW_REQUIRED"))
        self.assertIsNone(fact(o, vc.EVIDENCE_COMPLETE))
        self.assertIs(fact(o, vc.WORK_SUCCESS), True)

    def test_acceptance_passed_but_worker_blocked_is_inconsistent(self):
        o = observe_consistent(shared={"worker_state": "BLOCKED", "checkpoint_commit": None,
                                       "completion_mode": None})
        self.assertIs(fact(o, vc.WORK_SUCCESS), False)
        self.assertEqual(o.assessment.classification, vc.INCONSISTENT_FACTS)


class DirectorVocabularyRegressionTests(unittest.TestCase):
    def test_recovery_codes_match_director(self):
        self.assertEqual(vs.RECOVERY_DECISION_CODES, fd._RECOVERY_ELIGIBLE_DECISION_CODES)

    def test_every_director_decision_code_is_known(self):
        seen = set()
        conditions = (None, "PROVIDER_AUTH_BLOCKED", "PROVIDER_QUOTA_EXHAUSTED")
        for state in sorted(vs.WORKER_STATES | {"DONE"}):
            for ec in (True, False, None):
                for verdict in ("SAFE", "UNSAFE", None):
                    for cond in conditions:
                        for commit in ("abc", None):
                            s, e, d = consistent(shared={"worker_state": state, "evidence_complete": ec,
                                                         "provider_condition": cond, "checkpoint_commit": commit},
                                                 evidence_overrides={"safety_verdict": verdict})
                            seen.add(d.decision_code)
                            o, _ = observe(s, e, d)
                            self.assertNotIn("DECISION_CODE_UNRECOGNIZED", o.observation_codes)
                            if o.assessment.ready_for_human_review:
                                self.assertEqual(d.decision_code, "READY_FOR_HOST_AUDIT")
        self.assertEqual(seen, vs.DECISION_CODES)


if __name__ == "__main__":
    unittest.main()
