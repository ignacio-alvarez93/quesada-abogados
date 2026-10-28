"""FCP-6A-01: Failure Intelligence V1 - pure read-only diagnostics.

Every input is a synthetic dictionary shaped exactly like what the Runner
persists (`PipelineRunner._write_result` -> `workers/<id>/result.json`,
`PipelineRunner.build_result` -> `pipeline_result.json`); the key sets are
pinned against the Runner's own source below. No provider, process, Git
repository, file or network is used. Nothing is skipped.
"""

import ast
import copy
import dataclasses
import json
import unittest
from pathlib import Path

from scripts.ai import claude_runner as runner
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_pipeline as rp

MODULE_PATH = Path(fi.__file__)
PIPELINE_PATH = Path(rp.__file__)
PID = "night-1"
SECRET = "sk-ant-SECRET-TOKEN-4242"
STATE_ROOT = "C:/state/runner"


def _attempt(n=1, **over):
    attempt = {
        "attempt": n, "provider": "claude", "started_at_utc": "2026-10-28T01:00:00+00:00",
        "ended_at_utc": "2026-10-28T01:05:00+00:00", "status": "COMPLETED", "executed": True,
        "runner_state": "SUCCESS", "work_status": "SUCCESS", "provider_work_status": "UNVERIFIED",
        "work_status_source": "RUNNER_ACCEPTANCE", "evidence_dir": f"{STATE_ROOT}/_evidence/abc/run-{n}",
        "retry_decision": "NONE:SUCCESS", "budget_class": "WORK",
        "process_evidence_path": f"{STATE_ROOT}/{PID}/workers/w/process/attempt-{n}.json",
        "process_confirmed_stopped": True, "exit_code": 0, "run_id": f"run-{n}",
        "error_message": None, "evidence_complete": True,
    }
    attempt.update(over)
    return attempt


def _result(wid="a", state="SUCCESS", outcome=None, attempts=None, **extra):
    attempts = [_attempt()] if attempts is None else attempts
    last = attempts[-1] if attempts else {}
    payload = {
        "worker_id": wid, "pipeline_id": PID, "state": state, "state_reason": None, "provider": "claude",
        "requested_provider": "claude", "mode": "write", "worktree": "C:/repo/wt",
        "runner_state": last.get("runner_state"), "work_status": last.get("work_status"),
        "provider_work_status": last.get("provider_work_status"),
        "work_status_source": last.get("work_status_source"), "attempts": attempts, "fallbacks_used": [],
        "evidence_dir": last.get("evidence_dir"), "artifacts": [],
        "preflight": f"{STATE_ROOT}/{PID}/workers/{wid}/preflight.json", "metadata": {},
        "written_at_utc": "2026-10-28T01:05:01+00:00", "outcome": outcome or state,
    }
    payload.update(extra)
    return payload


def _summary(wid="a", state="SUCCESS", reason=None, result_path=True, condition=None):
    return {
        "id": wid, "provider": "claude", "requested_provider": "claude", "state": state, "state_reason": reason,
        "attempts": 1, "work_attempts_used": 1, "availability_attempts": 0, "provider_condition": condition,
        "next_eligible_utc": None,
        "result_path": f"{STATE_ROOT}/{PID}/workers/{wid}/result.json" if result_path else None,
        "worker_path": f"{STATE_ROOT}/{PID}/workers/{wid}/worker.json", "checkpoint_policy": None,
        "checkpoint_commit": None,
    }


def _pipeline(summaries, status=None):
    states = [s["state"] for s in summaries]
    counts = {s.value: states.count(s.value) for s in rp.WorkerState}
    if status is None:
        status = fi._native_overall(states) or "INCOMPLETE"
    return {
        "schema_version": 1, "pipeline_id": PID, "status": status, "stop_reason": None,
        "started_at_utc": "2026-10-28T01:00:00+00:00", "ended_at_utc": "2026-10-28T02:00:00+00:00",
        "duration_seconds": 3600.0, "workers_total": len(summaries), "success": counts["SUCCESS"],
        "partial": counts["PARTIAL"], "blocked": counts["BLOCKED"], "failed": counts["FAILED"],
        "cancelled": counts["CANCELLED"], "interrupted": counts["INTERRUPTED"],
        "waiting_provider_quota": counts["WAITING_PROVIDER_QUOTA"],
        "blocked_provider_auth": counts["BLOCKED_PROVIDER_AUTH"], "state_counts": counts,
        "provider_breakdown": {}, "max_observed_concurrency": 1, "workers": summaries,
    }


def _assess(result, summary=None, wid="a"):
    return fi.assess_worker(wid, result, pipeline_id=PID, summary=summary)


# Representative Runner fixtures: (summary, result) for every documented path.
def _fixtures():
    return {
        "success": (_summary(), _result()),
        "failed_non_transient": (
            _summary(state="FAILED", reason="CLAUDE_ERROR"),
            _result(state="FAILED", code="CLAUDE_ERROR", state_reason="CLAUDE_ERROR", message=SECRET,
                    attempts=[_attempt(runner_state="CLAUDE_ERROR", work_status=None, work_status_source="PROVIDER",
                                       retry_decision="NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR")])),
        "failed_after_retries": (
            _summary(state="FAILED", reason="MAX_ATTEMPTS_EXHAUSTED"),
            _result(state="FAILED", code="MAX_ATTEMPTS_EXHAUSTED", state_reason="MAX_ATTEMPTS_EXHAUSTED",
                    attempts=[_attempt(1, runner_state="TIMEOUT", retry_decision="RETRY:TRANSIENT:TIMEOUT:backoff=30s"),
                              _attempt(2, runner_state="TIMEOUT", retry_decision="NO_RETRY:MAX_ATTEMPTS_EXHAUSTED")])),
        "retry_wait": (_summary(state="RETRY_WAIT", reason="TRANSIENT:CLAUDE_ERROR", result_path=False), None),
        "quota": (
            _summary(state="WAITING_PROVIDER_QUOTA", reason="PROVIDER_QUOTA_EXHAUSTED:RESET_HINT",
                     condition="PROVIDER_QUOTA_EXHAUSTED"),
            _result(state="WAITING_PROVIDER_QUOTA", code="PROVIDER_QUOTA_EXHAUSTED",
                    state_reason="PROVIDER_QUOTA_EXHAUSTED:RESET_HINT", next_eligible_utc="2026-10-28T09:01:00+00:00",
                    provider_condition={"condition": "PROVIDER_QUOTA_EXHAUSTED", "message_excerpt": SECRET},
                    attempts=[_attempt(runner_state="CLAUDE_ERROR", budget_class="PROVIDER_AVAILABILITY",
                                       retry_decision="WAIT:PROVIDER_QUOTA_EXHAUSTED:RESET_HINT:"
                                                      "until=2026-10-28T09:01:00+00:00")])),
        "auth": (
            _summary(state="BLOCKED_PROVIDER_AUTH", reason="PROVIDER_AUTH_BLOCKED", condition="PROVIDER_AUTH_BLOCKED"),
            _result(state="BLOCKED_PROVIDER_AUTH", code="PROVIDER_AUTH_BLOCKED", state_reason="PROVIDER_AUTH_BLOCKED",
                    attempts=[_attempt(runner_state="CLAUDE_ERROR", retry_decision="NO_RETRY:PROVIDER_AUTH_BLOCKED")])),
        "interrupted": (
            _summary(state="INTERRUPTED", reason="ORCHESTRATOR_DIED_WHILE_RUNNING", result_path=False), None),
        "cancelled_dependent": (
            _summary(state="CANCELLED", reason="DEPENDENCY_UNSATISFIED:a=FAILED"),
            _result(state="CANCELLED", code="DEPENDENCY_UNSATISFIED", state_reason="DEPENDENCY_UNSATISFIED:a=FAILED",
                    message="a=FAILED", attempts=[])),
        "preflight": (
            _summary(state="BLOCKED", reason="CAPABILITY_MISMATCH"),
            _result(state="BLOCKED", code="CAPABILITY_MISMATCH", state_reason="CAPABILITY_MISMATCH", attempts=[])),
        "acceptance_failed": (
            _summary(state="FAILED", reason="ACCEPTANCE_FAILED"),
            _result(state="FAILED", code="ACCEPTANCE_FAILED", state_reason="ACCEPTANCE_FAILED",
                    acceptance={"decision": "FAILED", "reason": SECRET},
                    attempts=[_attempt(work_status="UNVERIFIED", work_status_source="PROVIDER",
                                       retry_decision="NO_RETRY:ACCEPTANCE_FAILED:FAILED")])),
        "checkpoint_failed": (
            _summary(state="BLOCKED", reason="CHECKPOINT_FAILED"),
            _result(state="BLOCKED", code="CHECKPOINT_FAILED", state_reason="CHECKPOINT_FAILED",
                    attempts=[_attempt(retry_decision="NO_RETRY:CHECKPOINT_FAILED:REFUSED_NO_EVIDENCE")])),
        "process_unresolved": (
            _summary(state="BLOCKED", reason="PROVIDER_PROCESS_UNRESOLVED"),
            _result(state="BLOCKED", code="PROVIDER_PROCESS_UNRESOLVED", state_reason="PROVIDER_PROCESS_UNRESOLVED",
                    attempts=[_attempt(process_confirmed_stopped=False, process_termination_unresolved=True,
                                       retry_decision="NO_RETRY:PROVIDER_PROCESS_UNRESOLVED")])),
        "partial_evidence": (
            _summary(state="PARTIAL", reason="EVIDENCE_FINALIZATION_FAILED"),
            _result(state="PARTIAL", code="EVIDENCE_FINALIZATION_FAILED", state_reason="EVIDENCE_FINALIZATION_FAILED",
                    evidence_error=SECRET,
                    attempts=[_attempt(evidence_complete=False, evidence_error=SECRET,
                                       retry_decision="NO_RETRY:EVIDENCE_FINALIZATION_FAILED")])),
    }


class RunnerShapeTests(unittest.TestCase):
    """Fixtures use the Runner's exact persisted keys; constants mirror its enums."""

    def _dict_keys(self, func_name, target):
        tree = ast.parse(PIPELINE_PATH.read_text(encoding="utf-8"))
        func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)
        for node in ast.walk(func):
            if isinstance(node, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == target for k in node.keys
            ):
                return {k.value for k in node.keys if isinstance(k, ast.Constant)}
        self.fail(f"{target} not found in {func_name}")

    def test_result_fixture_keys_are_runner_write_result_keys(self):
        native = self._dict_keys("_write_result", "worker_id") | {"outcome"}
        self.assertEqual(set(_result()) - native, set())
        self.assertEqual(native - set(_result()), set())

    def test_summary_and_pipeline_fixture_keys_are_runner_build_result_keys(self):
        self.assertEqual(set(_summary()), self._dict_keys("build_result", "worker_path"))
        self.assertEqual(set(_pipeline([])), self._dict_keys("build_result", "workers_total"))
        self.assertTrue(set(_attempt()) >= self._dict_keys("_launch", "retry_decision"))

    def test_mirrored_vocabulary_matches_runner_enums(self):
        self.assertEqual(fi.WORKER_STATES, {s.value for s in rp.WorkerState})
        self.assertEqual(fi.PIPELINE_STATUSES, {s.value for s in rp.PipelineStatus})
        self.assertEqual(fi.TERMINAL_STATES, {s.value for s in rp.TERMINAL_STATES})
        self.assertEqual(fi.WORK_STATUS_SOURCES, runner.WORK_STATUS_SOURCES)
        self.assertEqual(fi.SUPPORTED_RUNNER_SCHEMA_VERSION, rp.PIPELINE_SCHEMA_VERSION)
        self.assertLessEqual(fi._SAFETY_CODES - {"SELF_MODIFICATION_REFUSED"}, {s.value for s in runner.RunState})
        self.assertLessEqual(fi._PREFLIGHT_CODES, {s.value for s in runner.RunState})

    def test_module_is_stdlib_only_without_io_or_runner_imports(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported, {"__future__", "dataclasses", "json", "re", "collections", "typing"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("open", "exec", "eval", "__import__", "compile", "input"):
            self.assertNotIn(forbidden, names)
        for forbidden in ("read_text", "write_text", "system", "Popen", "run", "remove", "unlink"):
            self.assertNotIn(forbidden, attrs)
        self.assertFalse(any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree)))


class WorkerStateMatrixTests(unittest.TestCase):
    def test_success_with_complete_evidence_is_consistent_but_not_certified(self):
        diag = _assess(_result(), _summary())
        self.assertEqual(diag.reason_codes, ("SUCCESS_CONSISTENT",))
        self.assertEqual(diag.native_work_status_source, "RUNNER_ACCEPTANCE")
        self.assertEqual((diag.retry_decision_kind, diag.retry_decision_code), ("NONE", "SUCCESS"))
        self.assertFalse(diag.certified)

    def test_success_without_result_is_missing_never_success(self):
        diag = _assess(None, _summary())
        self.assertEqual(diag.primary_reason, "EVIDENCE_MISSING")
        self.assertNotIn("SUCCESS_CONSISTENT", diag.reason_codes)
        self.assertEqual(_assess(None).primary_reason, "EVIDENCE_MISSING")

    def test_native_success_is_never_promoted_to_proof(self):
        cases = {
            "evidence flag absent": [_attempt(evidence_complete=None)],
            "process stop unproven": [{k: v for k, v in _attempt().items() if k != "process_confirmed_stopped"}],
            "unknown source": [_attempt(work_status_source="SELF_ASSERTED")],
            "work status not success": [_attempt(work_status="UNVERIFIED")],
            "no attempts": [],
            "retry decision absent": [_attempt(retry_decision=None)],
        }
        for label, attempts in cases.items():
            with self.subTest(label):
                diag = _assess(_result(attempts=attempts), _summary())
                self.assertNotIn("SUCCESS_CONSISTENT", diag.reason_codes)
                self.assertIn("EVIDENCE_UNPROVEN", diag.reason_codes)
        self.assertEqual(_assess(_result(attempts=[_attempt(work_status_source="SELF_ASSERTED")]))
                         .native_work_status_source, fi.UNRECOGNIZED)

    def test_failed_without_retry(self):
        summary, result = _fixtures()["failed_non_transient"]
        diag = _assess(result, summary)
        self.assertEqual(diag.primary_reason, "NATIVE_FAILED")
        self.assertEqual((diag.retry_decision_kind, diag.retry_decision_code), ("NO_RETRY", "NON_TRANSIENT"))
        self.assertEqual(diag.native_code, "CLAUDE_ERROR")

    def test_failed_after_runner_retries_reports_last_decision_only(self):
        summary, result = _fixtures()["failed_after_retries"]
        diag = _assess(result, summary)
        self.assertEqual(diag.reason_codes, ("NATIVE_FAILED",))
        self.assertEqual((diag.retry_decision_kind, diag.retry_decision_code), ("NO_RETRY", "MAX_ATTEMPTS_EXHAUSTED"))
        self.assertEqual(diag.attempts_recorded, 2)

    def test_retry_wait_is_runner_state_not_a_retry_licence(self):
        summary, _ = _fixtures()["retry_wait"]
        diag = _assess(None, summary)
        self.assertEqual(diag.reason_codes, ("TRANSIENT_RETRY_WAIT",))
        self.assertEqual(diag.native_state_reason, "TRANSIENT")
        self.assertFalse(diag.auto_retry_allowed)
        self.assertFalse(diag.execution_allowed)

    def test_quota_wait_produces_no_new_schedule(self):
        summary, result = _fixtures()["quota"]
        diag = _assess(result, summary)
        self.assertEqual(diag.primary_reason, "PROVIDER_QUOTA_WAIT")
        self.assertEqual((diag.retry_decision_kind, diag.retry_decision_code), ("WAIT", "PROVIDER_QUOTA_EXHAUSTED"))
        text = fi.canonical_json(diag)
        for leaked in ("2026-10-28T09", "until", "next_eligible", "eligib"):
            self.assertNotIn(leaked, text)
        self.assertFalse(diag.auto_retry_allowed)

    def test_auth_blocked_is_never_retryable(self):
        summary, result = _fixtures()["auth"]
        diag = _assess(result, summary)
        self.assertEqual(diag.reason_codes, ("PROVIDER_AUTH_BLOCKED",))
        self.assertFalse(diag.auto_retry_allowed)
        self.assertNotIn("TRANSIENT_RETRY_WAIT", diag.reason_codes)

    def test_interrupted_requires_operator_review(self):
        summary, _ = _fixtures()["interrupted"]
        diag = _assess(None, summary)
        self.assertEqual(diag.reason_codes, ("INTERRUPTED_OPERATOR_REVIEW",))
        acceptance = _result(state="INTERRUPTED", code="ACCEPTANCE_INTERRUPTED", state_reason="ACCEPTANCE_INTERRUPTED",
                             attempts=[_attempt(retry_decision="NO_RETRY:ACCEPTANCE_INTERRUPTED")])
        diag = _assess(acceptance, _summary(state="INTERRUPTED", reason="ACCEPTANCE_INTERRUPTED"))
        self.assertEqual(diag.primary_reason, "INTERRUPTED_OPERATOR_REVIEW")

    def test_cancelled_dependent(self):
        summary, result = _fixtures()["cancelled_dependent"]
        diag = _assess(result, summary)
        self.assertEqual(diag.reason_codes, ("DEPENDENCY_CANCELLED",))
        self.assertEqual(diag.native_state_reason, "DEPENDENCY_UNSATISFIED")
        other = _assess(_result(state="CANCELLED", attempts=[]), _summary(state="CANCELLED", reason="OPERATOR"))
        self.assertEqual(other.primary_reason, "NATIVE_CANCELLED")

    def test_preflight_provider_or_capability_refusal(self):
        for code in ("CAPABILITY_MISMATCH", "PROVIDER_UNAVAILABLE", "PROVIDER_UNKNOWN"):
            with self.subTest(code):
                diag = _assess(_result(state="BLOCKED", code=code, state_reason=code, attempts=[]),
                               _summary(state="BLOCKED", reason=code))
                self.assertEqual(diag.reason_codes, ("PREFLIGHT_REFUSED", "NATIVE_BLOCKED"))

    def test_acceptance_and_checkpoint_failures(self):
        fx = _fixtures()
        self.assertEqual(_assess(fx["acceptance_failed"][1], fx["acceptance_failed"][0]).reason_codes,
                         ("ACCEPTANCE_FAILED", "NATIVE_FAILED"))
        self.assertEqual(_assess(fx["checkpoint_failed"][1], fx["checkpoint_failed"][0]).reason_codes,
                         ("CHECKPOINT_FAILED", "NATIVE_BLOCKED"))

    def test_partial_with_incomplete_evidence_is_preserved(self):
        summary, result = _fixtures()["partial_evidence"]
        diag = _assess(result, summary)
        self.assertEqual(diag.reason_codes, ("PARTIAL_COMPLETION", "EVIDENCE_INCOMPLETE"))
        self.assertEqual(diag.native_state, "PARTIAL")

    def test_pending_states_are_not_terminal(self):
        for state in ("QUEUED", "WAITING_DEPENDENCY", "READY", "RUNNING"):
            with self.subTest(state):
                self.assertEqual(_assess(None, _summary(state=state, result_path=False)).reason_codes,
                                 ("NOT_TERMINAL",))


class DangerousEvidenceTests(unittest.TestCase):
    def test_process_unresolved_blocked(self):
        summary, result = _fixtures()["process_unresolved"]
        diag = _assess(result, summary)
        self.assertEqual(diag.primary_reason, "PROCESS_TERMINATION_UNRESOLVED")

    def test_process_unresolved_under_apparent_success(self):
        variants = {
            "not confirmed stopped": _attempt(process_confirmed_stopped=False),
            "termination flag": _attempt(process_termination_unresolved=True),
            "acceptance unresolved": _attempt(acceptance_termination_unresolved=True),
            "recovery unresolved": _attempt(process_recovery={"resolution": "UNRESOLVED"}),
            "acceptance decision": _attempt(acceptance={"decision": "PROCESS_UNRESOLVED"}),
        }
        for label, attempt in variants.items():
            with self.subTest(label):
                diag = _assess(_result(attempts=[attempt]), _summary())
                self.assertIn("PROCESS_TERMINATION_UNRESOLVED", diag.reason_codes)
                self.assertIn("CONFLICTING_EVIDENCE", diag.reason_codes)
                self.assertNotIn("SUCCESS_CONSISTENT", diag.reason_codes)

    def test_unauthorized_paths_under_apparent_success_never_leak(self):
        variants = {
            "runner state": _result(attempts=[_attempt(runner_state="FAILED_SAFETY")]),
            "paths list": _result(unauthorized_changed_paths=[f"secrets/{SECRET}.env"]),
            "safety verdict": _result(attempts=[_attempt(safety_verdict={"verdict": "FAILED_SAFETY",
                                                                          "reasons": [SECRET]})]),
            "malformed paths": _result(unauthorized_changed_paths=SECRET),
        }
        for label, result in variants.items():
            with self.subTest(label):
                diag = _assess(result, _summary())
                self.assertIn("SAFETY_REFUSAL", diag.reason_codes)
                self.assertIn("CONFLICTING_EVIDENCE", diag.reason_codes)
                self.assertNotIn(SECRET, fi.canonical_json(diag))
        self.assertNotIn("SAFETY_REFUSAL", _assess(_result(unauthorized_changed_paths=[])).reason_codes)

    def test_precedence_uncertainty_and_safety_outrank_waits_and_provider(self):
        quota_and_unresolved = _result(
            state="WAITING_PROVIDER_QUOTA", code="PROVIDER_QUOTA_EXHAUSTED",
            attempts=[_attempt(process_termination_unresolved=True, retry_decision="WAIT:PROVIDER_QUOTA_EXHAUSTED:X")])
        diag = _assess(quota_and_unresolved, _summary(state="WAITING_PROVIDER_QUOTA"))
        self.assertEqual(diag.primary_reason, "PROCESS_TERMINATION_UNRESOLVED")
        self.assertLess(diag.reason_codes.index("PROCESS_TERMINATION_UNRESOLVED"),
                        diag.reason_codes.index("PROVIDER_QUOTA_WAIT"))
        safety_and_preflight = _result(state="BLOCKED", code="PROVIDER_UNAVAILABLE",
                                       attempts=[_attempt(runner_state="FAILED_SAFETY",
                                                          retry_decision="RETRY:TRANSIENT:X")])
        diag = _assess(safety_and_preflight, _summary(state="BLOCKED"))
        self.assertEqual(diag.reason_codes[0], "SAFETY_REFUSAL")
        self.assertLess(diag.reason_codes.index("PREFLIGHT_REFUSED"), diag.reason_codes.index("TRANSIENT_RETRY_WAIT"))
        bad_id = _assess(_result(wid="zz", attempts=[_attempt(process_termination_unresolved=True)]), _summary())
        self.assertEqual(bad_id.primary_reason, "IDENTITY_MISMATCH")
        self.assertEqual(list(fi.REASON_PRECEDENCE), sorted(set(fi.REASON_PRECEDENCE), key=fi._RANK.get))


class MalformedEvidenceTests(unittest.TestCase):
    def test_malformed_shapes_fail_closed(self):
        cases = {
            "result list": ([_result()], _summary()),
            "result string": ("SUCCESS", _summary()),
            "summary list": (_result(), ["SUCCESS"]),
            "attempts not list": (_result(attempts=[_attempt()]) | {"attempts": {"0": _attempt()}}, _summary()),
            "attempt not mapping": (_result(attempts=[_attempt()]) | {"attempts": ["NONE:SUCCESS"]}, _summary()),
            "state missing": ({k: v for k, v in _result().items() if k != "state"}, None),
            "state int": (_result() | {"state": 7}, None),
        }
        for label, (result, summary) in cases.items():
            with self.subTest(label):
                diag = _assess(result, summary)
                self.assertEqual(diag.primary_reason, "MALFORMED_EVIDENCE")
                self.assertNotIn("SUCCESS_CONSISTENT", diag.reason_codes)

    def test_malformed_worker_id_is_not_echoed(self):
        for bad in (None, "", "../x", "a" * 65, ["a"], f"{SECRET} with spaces"):
            with self.subTest(repr(bad)):
                diag = fi.assess_worker(bad, None, pipeline_id=PID)
                self.assertIsNone(diag.worker_id)
                self.assertEqual(diag.primary_reason, "MALFORMED_EVIDENCE")

    def test_worker_and_pipeline_identity_mismatch(self):
        self.assertEqual(_assess(_result(wid="b"), _summary()).primary_reason, "IDENTITY_MISMATCH")
        self.assertEqual(_assess(_result(pipeline_id="other"), _summary()).primary_reason, "IDENTITY_MISMATCH")
        self.assertEqual(_assess(_result(), _summary(wid="b")).primary_reason, "IDENTITY_MISMATCH")

    def test_unknown_future_state_and_prose_are_bounded(self):
        diag = _assess(_result(state="QUANTUM_HOLD", outcome="QUANTUM_HOLD"), _summary(state="QUANTUM_HOLD"))
        self.assertEqual(diag.primary_reason, "UNKNOWN_STATE")
        self.assertEqual(diag.native_state, "QUANTUM_HOLD")
        prose = _assess(_result(state=f"done {SECRET}"), None)
        self.assertEqual(prose.native_state, fi.UNRECOGNIZED)
        self.assertNotIn(SECRET, fi.canonical_json(prose))

    def test_unhashable_tampered_values_do_not_crash(self):
        result = _result(attempts=[_attempt(work_status_source=["RUNNER_ACCEPTANCE"], retry_decision={"x": 1})])
        result["code"] = ["CODE"]
        diag = _assess(result, _summary() | {"state": ["SUCCESS"], "provider_condition": {"a": 1}})
        self.assertEqual(diag.primary_reason, "MALFORMED_EVIDENCE")
        pipe = fi.assess_pipeline(_pipeline([_summary()]) | {"status": ["SUCCESS"]}, {"a": _result()})
        self.assertEqual(pipe.diagnostic_status, fi.DIAGNOSTIC_UNKNOWN)

    def test_future_reason_and_retry_codes_are_bounded_not_trusted(self):
        future = _result(state="FAILED", code="NEW_RUNNER_CODE", state_reason="NEW_RUNNER_CODE:detail",
                         attempts=[_attempt(retry_decision="ESCALATE:SOMETHING")])
        diag = _assess(future, _summary(state="FAILED", reason="NEW_RUNNER_CODE:detail"))
        self.assertEqual(diag.primary_reason, "RETRY_DECISION_UNRECOGNIZED")
        self.assertIn("NATIVE_FAILED", diag.reason_codes)
        self.assertEqual((diag.native_code, diag.native_state_reason), ("NEW_RUNNER_CODE", "NEW_RUNNER_CODE"))
        self.assertEqual(diag.retry_decision_kind, fi.UNRECOGNIZED)
        fallback = _assess(_result(attempts=[_attempt(retry_decision="FALLBACK:secret-provider")]), _summary())
        self.assertEqual((fallback.retry_decision_kind, fallback.retry_decision_code), ("FALLBACK", None))
        self.assertNotIn("secret-provider", fi.canonical_json(fallback))

    def test_conflicting_summary_result_outcome_and_stale_result(self):
        self.assertIn("CONFLICTING_EVIDENCE", _assess(_result(), _summary(state="FAILED")).reason_codes)
        self.assertIn("CONFLICTING_EVIDENCE", _assess(_result(outcome="FAILED"), _summary()).reason_codes)
        self.assertIn("CONFLICTING_EVIDENCE", _assess(_result(state_reason="X"), _summary(reason="Y")).reason_codes)
        stale = _assess(_result(), _summary(result_path=False))
        self.assertIn("CONFLICTING_EVIDENCE", stale.reason_codes)
        self.assertNotIn("SUCCESS_CONSISTENT", stale.reason_codes)
        success_with_wait = _assess(_result(attempts=[_attempt(retry_decision="RETRY:TRANSIENT:X")]), _summary())
        self.assertIn("CONFLICTING_EVIDENCE", success_with_wait.reason_codes)


class PipelineRollupTests(unittest.TestCase):
    def _clean(self, ids=("a", "b")):
        return _pipeline([_summary(w) for w in ids]), {w: _result(w) for w in ids}

    def test_clean_success_rolls_up_in_native_order(self):
        pr, results = self._clean(("b", "a", "c"))
        diag = fi.assess_pipeline(pr, results)
        self.assertEqual(diag.diagnostic_status, "SUCCESS")
        self.assertEqual(diag.reason_codes, ("SUCCESS_CONSISTENT",))
        self.assertEqual([w.worker_id for w in diag.workers], ["b", "a", "c"])
        self.assertFalse(diag.authorizes_action)

    def test_native_success_downgraded_when_any_worker_unproven(self):
        pr, results = self._clean()
        results["b"] = None
        diag = fi.assess_pipeline(pr, results)
        self.assertEqual((diag.native_status, diag.diagnostic_status), ("SUCCESS", fi.DIAGNOSTIC_UNVERIFIED))
        self.assertIn("EVIDENCE_MISSING", diag.reason_codes)
        results["b"] = _result("b", attempts=[_attempt(evidence_complete=None)])
        self.assertEqual(fi.assess_pipeline(pr, results).diagnostic_status, fi.DIAGNOSTIC_UNVERIFIED)

    def test_non_success_native_status_is_never_upgraded(self):
        fx = _fixtures()
        for name, status in (("failed_non_transient", "FAILED"), ("checkpoint_failed", "BLOCKED"),
                             ("partial_evidence", "PARTIAL"), ("cancelled_dependent", "CANCELLED"),
                             ("quota", "INCOMPLETE"), ("retry_wait", "INCOMPLETE")):
            with self.subTest(name):
                summary, result = fx[name]
                summary = dict(summary, id="b")
                result = None if result is None else dict(result, worker_id="b")
                pr = _pipeline([_summary("a"), summary])
                diag = fi.assess_pipeline(pr, {"a": _result("a"), "b": result})
                self.assertEqual((diag.native_status, diag.diagnostic_status), (status, status))
                self.assertNotIn("SUCCESS_CONSISTENT", diag.reason_codes)
        running = _pipeline([_summary("a", state="RUNNING", result_path=False)], status="RUNNING")
        self.assertEqual(fi.assess_pipeline(running, {"a": None}).diagnostic_status, "RUNNING")

    def test_duplicate_missing_and_extra_workers_are_reported_never_dropped(self):
        pr = _pipeline([_summary("a"), _summary("a"), _summary("b")])
        diag = fi.assess_pipeline(pr, {"a": _result("a"), "x": _result("x"), "../evil": {}})
        self.assertEqual(len(diag.workers), 3)
        self.assertEqual([w.primary_reason for w in diag.workers[:2]], ["DUPLICATE_WORKER_ID"] * 2)
        self.assertEqual(diag.missing_worker_ids, ("b",))
        self.assertEqual(diag.extra_worker_ids, ("x",))
        self.assertEqual(diag.unidentified_extra_results, 1)
        for code in ("DUPLICATE_WORKER_ID", "MISSING_WORKER_RESULT", "EXTRA_WORKER_RESULT"):
            self.assertIn(code, diag.reason_codes)
        self.assertEqual(diag.diagnostic_status, fi.DIAGNOSTIC_UNVERIFIED)

    def test_native_aggregate_contradictions(self):
        pr, results = self._clean()
        cases = {
            "status vs states": dict(pr, workers=[_summary("a"), _summary("b", state="FAILED")]),
            "workers_total": dict(pr, workers_total=3),
            "counter": dict(pr, failed=1),
            "state_counts": dict(pr, state_counts=dict(pr["state_counts"], SUCCESS=5)),
            "state_counts shape": dict(pr, state_counts=["SUCCESS"]),
        }
        for label, tampered in cases.items():
            with self.subTest(label):
                diag = fi.assess_pipeline(tampered, results)
                self.assertIn("AGGREGATE_CONTRADICTION", diag.reason_codes)
                self.assertEqual(diag.diagnostic_status, fi.DIAGNOSTIC_UNVERIFIED)

    def test_pipeline_identity_and_schema_fail_closed(self):
        pr, results = self._clean()
        results["b"] = _result("b", pipeline_id="other-pipeline")
        diag = fi.assess_pipeline(pr, results)
        self.assertEqual(diag.primary_reason, "IDENTITY_MISMATCH")
        self.assertEqual(diag.diagnostic_status, fi.DIAGNOSTIC_UNVERIFIED)
        pr, results = self._clean()
        for label, tampered in {"future schema": dict(pr, schema_version=2), "bad id": dict(pr, pipeline_id="../x"),
                                "no id": {k: v for k, v in pr.items() if k != "pipeline_id"}}.items():
            with self.subTest(label):
                diag = fi.assess_pipeline(tampered, results)
                self.assertEqual(diag.primary_reason, "MALFORMED_EVIDENCE")
                self.assertNotEqual(diag.diagnostic_status, "SUCCESS")

    def test_empty_and_malformed_pipelines_are_not_success(self):
        empty = fi.assess_pipeline(_pipeline([], status="SUCCESS"), {})
        self.assertEqual(empty.diagnostic_status, fi.DIAGNOSTIC_UNVERIFIED)
        self.assertIn("EMPTY_PIPELINE", empty.reason_codes)
        for pr, results in ((None, {}), ([], {}), (_pipeline([_summary()]), [_result()]),
                            (dict(_pipeline([_summary()]), workers={"a": _summary()}), {"a": _result()}),
                            (dict(_pipeline([_summary()]), status="WEIRD"), {"a": _result()})):
            with self.subTest(repr(pr)[:40]):
                diag = fi.assess_pipeline(pr, results)
                self.assertNotEqual(diag.diagnostic_status, "SUCCESS")
                self.assertIn(diag.primary_reason, ("MALFORMED_EVIDENCE", "UNKNOWN_STATE"))

    def test_result_mapping_permutation_is_irrelevant_declared_order_is_kept(self):
        pr = _pipeline([_summary("a"), _summary("b", state="FAILED", reason="X")])
        res = {"a": _result("a"), "b": _result("b", state="FAILED", code="X"), "z": None, "y": None}
        forward = fi.assess_pipeline(pr, res)
        backward = fi.assess_pipeline(pr, dict(reversed(list(res.items()))))
        self.assertEqual(fi.canonical_json(forward), fi.canonical_json(backward))
        self.assertEqual(forward.extra_worker_ids, ("y", "z"))
        swapped = fi.assess_pipeline(dict(pr, workers=list(reversed(pr["workers"]))), res)
        self.assertEqual([w.worker_id for w in swapped.workers], ["b", "a"])
        self.assertEqual(swapped.reason_codes, forward.reason_codes)


class PurityAndGuaranteeTests(unittest.TestCase):
    def _every_diagnostic(self):
        fx = _fixtures()
        for name, (summary, result) in fx.items():
            yield name, (summary, result), _assess(result, summary)
        pr = _pipeline([dict(s, id=n) for n, (s, _) in fx.items()])
        results = {n: (None if r is None else dict(r, worker_id=n)) for n, (_, r) in fx.items()}
        yield "pipeline", (pr, results), fi.assess_pipeline(pr, results)

    def test_inputs_are_never_mutated(self):
        fx = _fixtures()
        for name, (summary, result) in fx.items():
            before = copy.deepcopy((summary, result))
            _assess(result, summary)
            self.assertEqual((summary, result), before, name)
        pr = _pipeline([_summary("a"), _summary("a")])
        results = {"a": _result("a"), "x": None}
        before = copy.deepcopy((pr, results))
        fi.assess_pipeline(pr, results)
        self.assertEqual((pr, results), before)

    def test_zero_action_guarantees_are_fixed_and_not_caller_controllable(self):
        for name, _, diag in self._every_diagnostic():
            with self.subTest(name):
                for flag in ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed"):
                    self.assertIs(getattr(diag, flag), False)
                    self.assertIs(diag.to_dict()[flag], False)
                    self.assertNotIn(flag, {f.name for f in dataclasses.fields(diag)})
                    with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
                        setattr(diag, flag, True)
                self.assertEqual(diag.to_dict()["marker"], fi.DIAGNOSTIC_MARKER)
        with self.assertRaises(TypeError):
            fi.WorkerDiagnostic(**{f.name: None for f in dataclasses.fields(fi.WorkerDiagnostic)},
                                authorizes_action=True)
        with self.assertRaises(TypeError):
            dataclasses.replace(_assess(_result()), auto_retry_allowed=True)

    def test_serialization_is_stable_and_leaks_no_raw_input(self):
        poisoned = _result(message=SECRET, error=SECRET, metadata={"token": SECRET}, stderr=SECRET,
                           evidence_dir=f"C:/{SECRET}", artifacts=[f"C:/{SECRET}/prompt.txt"],
                           attempts=[_attempt(error_message=SECRET, evidence_dir=f"C:/{SECRET}",
                                              run_id=SECRET, provider=SECRET)])
        diags = [d for _, _, d in self._every_diagnostic()] + [_assess(poisoned, _summary())]
        for diag in diags:
            text = fi.canonical_json(diag)
            self.assertEqual(text, fi.canonical_json(diag))
            self.assertEqual(json.loads(text), diag.to_dict())
            for leaked in (SECRET, STATE_ROOT, "C:/", "prompt", "work_order", "Bearer", "\\"):
                self.assertNotIn(leaked, text)
        self.assertEqual(_assess(poisoned, _summary()).reason_codes, ("SUCCESS_CONSISTENT",))

    def test_outputs_carry_no_command_work_order_or_path(self):
        for name, _, diag in self._every_diagnostic():
            payload = diag.to_dict()
            keys = set(payload) | {k for w in payload.get("workers", []) for k in w}
            for forbidden in ("command", "work_order", "resume_from", "next_eligible_utc", "path", "credential",
                              "retry_at", "schedule"):
                self.assertFalse(any(forbidden in k for k in keys), (name, forbidden))
            refs = [r for w in payload.get("workers", [payload]) for r in w.get("evidence_refs", [])]
            for ref in refs:
                self.assertRegex(ref, r"^(pipeline_result\.workers(\[\d+\])?|worker_result(\.attempts\[\d+\])?)$")

    def test_repeated_and_interleaved_calls_are_deterministic(self):
        first = [fi.canonical_json(d) for _, _, d in self._every_diagnostic()]
        _assess([1, 2, 3], "junk")
        fi.assess_pipeline(None, None)
        second = [fi.canonical_json(d) for _, _, d in self._every_diagnostic()]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
