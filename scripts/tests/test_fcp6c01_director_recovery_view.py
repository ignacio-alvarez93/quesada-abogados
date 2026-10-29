"""FCP-6C-01: Director recovery view - pure observational projection.

Every input is synthetic and shaped like what the host has already read:
a `fabric_director.DirectorDagRunSummary` built with the Director's own
projection helpers, a Runner `pipeline_result.json` and the
`{worker_id: result.json or None}` table. No provider, process, Git, file or
network is used. Nothing is skipped.
"""

import ast
import builtins
import copy
import dataclasses
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_recovery_director_view as view
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_recovery_advisory as ra

MODULE_PATH = Path(view.__file__)
PID = "fdb-20261028t010000000000-abcd1234"
SHA = "a" * 64
FP = "b" * 64
SECRET = "sk-ant-SECRET-TOKEN-4242"
STATE_ROOT = "C:/state/runner"
STAMP = "2026-10-28T01:05:00+00:00"
NO_AUTH = ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed", "resume_allowed",
           "merging_allowed")


def _attempt(n=1, **over):
    attempt = {
        "attempt": n, "provider": "claude", "started_at_utc": STAMP, "ended_at_utc": STAMP, "status": "COMPLETED",
        "executed": True, "runner_state": "SUCCESS", "work_status": "SUCCESS", "provider_work_status": "UNVERIFIED",
        "work_status_source": "RUNNER_ACCEPTANCE", "evidence_dir": f"{STATE_ROOT}/_evidence/abc/run-{n}",
        "retry_decision": "NONE:SUCCESS", "budget_class": "WORK", "process_confirmed_stopped": True,
        "exit_code": 0, "run_id": f"run-{n}", "error_message": None, "evidence_complete": True,
    }
    attempt.update(over)
    return attempt


def _result(wid, state="SUCCESS", attempts=None, **extra):
    attempts = [_attempt()] if attempts is None else attempts
    last = attempts[-1] if attempts else {}
    payload = {
        "worker_id": wid, "pipeline_id": PID, "state": state, "state_reason": None, "provider": "claude",
        "requested_provider": "claude", "mode": "write", "worktree": "C:/repo/wt",
        "runner_state": last.get("runner_state"), "work_status": last.get("work_status"),
        "provider_work_status": last.get("provider_work_status"),
        "work_status_source": last.get("work_status_source"), "attempts": attempts, "fallbacks_used": [],
        "evidence_dir": last.get("evidence_dir"), "artifacts": [], "metadata": {}, "written_at_utc": STAMP,
        "outcome": state,
    }
    payload.update(extra)
    return payload


def _entry(wid, state="SUCCESS", reason=None, result_path=True, condition=None):
    return {
        "id": wid, "provider": "claude", "requested_provider": "claude", "state": state, "state_reason": reason,
        "attempts": 1, "work_attempts_used": 1, "availability_attempts": 0, "provider_condition": condition,
        "next_eligible_utc": None,
        "result_path": f"{STATE_ROOT}/{PID}/workers/{wid}/result.json" if result_path else None,
        "worker_path": f"{STATE_ROOT}/{PID}/workers/{wid}/worker.json", "checkpoint_policy": None,
        "checkpoint_commit": None,
    }


def _pipeline(entries, status=None, stop_reason=None):
    states = [e["state"] for e in entries]
    names = sorted(fi.WORKER_STATES)
    counts = {s: states.count(s) for s in names}
    return {
        "schema_version": 1, "pipeline_id": PID, "status": status or fi._native_overall(states) or "INCOMPLETE",
        "stop_reason": stop_reason, "started_at_utc": STAMP, "ended_at_utc": STAMP, "duration_seconds": 1.0,
        "workers_total": len(entries), "success": counts["SUCCESS"], "partial": counts["PARTIAL"],
        "blocked": counts["BLOCKED"], "failed": counts["FAILED"], "cancelled": counts["CANCELLED"],
        "interrupted": counts["INTERRUPTED"], "waiting_provider_quota": counts["WAITING_PROVIDER_QUOTA"],
        "blocked_provider_auth": counts["BLOCKED_PROVIDER_AUTH"], "state_counts": counts,
        "provider_breakdown": {}, "max_observed_concurrency": 1, "workers": entries,
    }


def _dworker(entry, result, depends_on=()):
    """A Director worker projected the way `_dag_worker_summary` does."""
    record = fd.WORKER_RECORD_MISSING if result is None else fd.WORKER_RECORD_PRESENT
    attempts = (result or {}).get("attempts") or []
    complete = attempts[-1].get("evidence_complete") if attempts else None
    health = {True: fd.EVIDENCE_HEALTH_COMPLETE, False: fd.EVIDENCE_HEALTH_INCOMPLETE}.get(
        complete, fd.EVIDENCE_HEALTH_UNKNOWN)
    work_status = (result or {}).get("work_status")
    reasons = fd._dag_unproven_reasons(worker_state=entry["state"], work_status=work_status, worker_record=record,
                                       evidence_health=health, unauthorized=())
    return fd.DirectorDagWorkerSummary(
        worker_id=entry["id"], depends_on=tuple(depends_on), worker_state=entry["state"],
        state_reason=entry.get("state_reason"), provider="claude", requested_provider="claude",
        work_status=work_status, next_eligible_utc=entry.get("next_eligible_utc"),
        worker_record=record, evidence_dir=(result or {}).get("evidence_dir"), evidence_complete=complete,
        evidence_health=health, unproven_reasons=reasons, runner_proven_success=not reasons,
    )


def _summary(pipeline_result, results, workers=None, **over):
    entries = pipeline_result["workers"]
    workers = tuple(_dworker(e, results.get(e["id"])) for e in entries) if workers is None else workers
    status = pipeline_result["status"]
    aggregate, reasons = fd._classify_dag_aggregate(status, workers)
    fields = dict(run_id=PID, pipeline_id=PID, blueprint_pipeline_id="night-shift", manifest_sha256=SHA,
                  plan_fingerprint=FP, pipeline_status=status, stop_reason=pipeline_result.get("stop_reason"),
                  workers=workers, aggregate_status=aggregate, aggregate_reasons=reasons)
    fields.update(over)
    return fd.DirectorDagRunSummary(**fields)


def _dag(*pairs, **pipeline_over):
    """(summary, pipeline_result, results) from (entry, result) pairs."""
    entries = [e for e, _ in pairs]
    results = {e["id"]: r for e, r in pairs}
    pipeline_result = _pipeline(entries, **pipeline_over)
    return _summary(pipeline_result, results), pipeline_result, results


def _ok(wid):
    return _entry(wid), _result(wid)


def _failed(wid):
    return (_entry(wid, "FAILED", "CLAUDE_ERROR"),
            _result(wid, "FAILED", code="CLAUDE_ERROR", state_reason="CLAUDE_ERROR", message=SECRET,
                    attempts=[_attempt(runner_state="CLAUDE_ERROR", work_status=None, work_status_source="PROVIDER",
                                       retry_decision="NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR")]))


def _build(summary, pipeline_result, results):
    return view.build_view(summary, pipeline_result, results)


class SuccessAndFailureShapesTest(unittest.TestCase):
    def test_two_worker_success_is_consistent_but_not_certified(self):
        out = _build(*_dag(_ok("a"), _ok("b"))).to_dict()
        self.assertEqual(out["consistency_codes"], [])
        self.assertTrue(out["cross_source_consistent"])
        self.assertEqual(out["director"]["aggregate_status"], "SUCCESS")
        self.assertEqual(out["diagnostic"]["diagnostic_status"], "SUCCESS")
        self.assertEqual(out["advisory"]["category"], "HISTORICAL_SUCCESS")
        self.assertFalse(out["certified"])
        self.assertEqual([w["worker_id"] for w in out["workers"]], ["a", "b"])

    def test_three_worker_dag_keeps_director_order(self):
        out = _build(*_dag(_ok("c"), _ok("a"), _ok("b"))).to_dict()
        self.assertEqual([w["worker_id"] for w in out["workers"]], ["c", "a", "b"])
        self.assertEqual([w["director_index"] for w in out["workers"]], [0, 1, 2])
        self.assertEqual([w["runner_index"] for w in out["workers"]], [0, 1, 2])
        self.assertTrue(out["cross_source_consistent"])

    def test_one_independent_failed_worker(self):
        out = _build(*_dag(_ok("a"), _failed("b"), _ok("c"))).to_dict()
        self.assertEqual(out["director"]["aggregate_status"], "FAILED")
        self.assertEqual(out["diagnostic"]["diagnostic_status"], "FAILED")
        self.assertEqual(out["advisory"]["category"], "NATIVE_FAILED")
        self.assertEqual(out["workers"][1]["advisory_category"], "NATIVE_FAILED")
        self.assertEqual(out["workers"][0]["advisory_category"], "HISTORICAL_SUCCESS")
        self.assertTrue(out["cross_source_consistent"])  # sources agree; that is not success

    def test_mixed_success_failed_and_dependent_cancelled(self):
        cancelled = (_entry("c", "CANCELLED", "DEPENDENCY_UNSATISFIED:b=FAILED"),
                     _result("c", "CANCELLED", code="DEPENDENCY_UNSATISFIED",
                             state_reason="DEPENDENCY_UNSATISFIED:b=FAILED", attempts=[]))
        out = _build(*_dag(_ok("a"), _failed("b"), cancelled)).to_dict()
        self.assertEqual(out["director"]["aggregate_status"], "FAILED")
        self.assertEqual(out["workers"][2]["advisory_category"], "DEPENDENCY_CANCELLED")
        self.assertNotEqual(out["advisory"]["category"], "HISTORICAL_SUCCESS")

    def test_auth_blocked_is_human_review_without_authority(self):
        auth = (_entry("a", "BLOCKED_PROVIDER_AUTH", "PROVIDER_AUTH_BLOCKED", condition="PROVIDER_AUTH_BLOCKED"),
                _result("a", "BLOCKED_PROVIDER_AUTH", code="PROVIDER_AUTH_BLOCKED", state_reason="PROVIDER_AUTH_BLOCKED",
                        attempts=[_attempt(runner_state="CLAUDE_ERROR",
                                           retry_decision="NO_RETRY:PROVIDER_AUTH_BLOCKED")]))
        v = _build(*_dag(auth, _ok("b"), status="INCOMPLETE", stop_reason="PROVIDER_AUTH_BLOCKED"))
        out = v.to_dict()
        self.assertEqual(out["advisory"]["category"], "PROVIDER_AUTH_BLOCKED")
        self.assertEqual(out["advisory"]["responsibility"], "HUMAN_REVIEW")
        self.assertEqual(out["director"]["stop_reason"], "PROVIDER_AUTH_BLOCKED")
        for flag in NO_AUTH:
            self.assertIs(getattr(v, flag), False)

    def test_quota_wait_is_observed_not_scheduled(self):
        until = "2026-10-28T09:01:00+00:00"
        entry = _entry("a", "WAITING_PROVIDER_QUOTA", "PROVIDER_QUOTA_EXHAUSTED:RESET_HINT",
                       condition="PROVIDER_QUOTA_EXHAUSTED")
        entry["next_eligible_utc"] = until
        quota = (entry, _result("a", "WAITING_PROVIDER_QUOTA", code="PROVIDER_QUOTA_EXHAUSTED",
                                state_reason="PROVIDER_QUOTA_EXHAUSTED:RESET_HINT", next_eligible_utc=until,
                                attempts=[_attempt(runner_state="CLAUDE_ERROR",
                                                   retry_decision=f"WAIT:PROVIDER_QUOTA_EXHAUSTED:RESET_HINT:until={until}")]))
        v = _build(*_dag(quota, status="INCOMPLETE", stop_reason="WAITING_PROVIDER_QUOTA"))
        out = v.to_dict()
        self.assertEqual(out["advisory"]["observation"], "OBSERVE_EXISTING_WAIT")
        self.assertEqual(out["advisory"]["responsibility"], "RUNNER_NATIVE")
        self.assertNotIn(until, view.canonical_json(v))
        self.assertNotIn("next_eligible_utc", view.canonical_json(v))

    def test_process_unresolved(self):
        unresolved = (_entry("a", "BLOCKED", "PROVIDER_PROCESS_UNRESOLVED"),
                      _result("a", "BLOCKED", code="PROVIDER_PROCESS_UNRESOLVED",
                              state_reason="PROVIDER_PROCESS_UNRESOLVED",
                              attempts=[_attempt(process_confirmed_stopped=False, process_termination_unresolved=True,
                                                 retry_decision="NO_RETRY:PROVIDER_PROCESS_UNRESOLVED")]))
        out = _build(*_dag(unresolved, _ok("b"))).to_dict()
        self.assertEqual(out["advisory"]["category"], "PROCESS_UNRESOLVED")
        self.assertEqual(out["workers"][0]["diagnostic_primary_reason"], "PROCESS_TERMINATION_UNRESOLVED")

    def test_realistic_night_shift_negative_example(self):
        retried = (_entry("tests", "FAILED", "MAX_ATTEMPTS_EXHAUSTED"),
                   _result("tests", "FAILED", code="MAX_ATTEMPTS_EXHAUSTED", state_reason="MAX_ATTEMPTS_EXHAUSTED",
                           attempts=[_attempt(1, runner_state="TIMEOUT",
                                              retry_decision="RETRY:TRANSIENT:TIMEOUT:backoff=30s"),
                                     _attempt(2, runner_state="TIMEOUT",
                                              retry_decision="NO_RETRY:MAX_ATTEMPTS_EXHAUSTED")]))
        rejected = (_entry("docs", "FAILED", "ACCEPTANCE_FAILED"),
                    _result("docs", "FAILED", code="ACCEPTANCE_FAILED", state_reason="ACCEPTANCE_FAILED",
                            acceptance={"decision": "FAILED", "reason": SECRET},
                            attempts=[_attempt(work_status="UNVERIFIED", work_status_source="PROVIDER",
                                               retry_decision="NO_RETRY:ACCEPTANCE_FAILED:FAILED")]))
        v = _build(*_dag(_ok("view"), retried, rejected))
        out = v.to_dict()
        self.assertEqual(out["director"]["aggregate_status"], "FAILED")
        self.assertEqual(out["advisory"]["category"], "ACCEPTANCE_FAILED")
        self.assertEqual([w["advisory_category"] for w in out["workers"]],
                         ["HISTORICAL_SUCCESS", "NATIVE_FAILED", "ACCEPTANCE_FAILED"])
        self.assertTrue(v.cross_source_consistent)
        self.assertNotIn(SECRET, view.canonical_json(v))


class CrossSourceReconciliationTest(unittest.TestCase):
    def test_director_success_with_unverified_diagnostic_is_never_elevated(self):
        weak = (_entry("a"), _result("a", attempts=[_attempt(work_status_source="SOMEONE_ELSE")]))
        summary, pr, results = _dag(weak, _ok("b"))
        claimed = dataclasses.replace(summary, aggregate_status="SUCCESS", aggregate_reasons=())
        v = _build(claimed, pr, results)
        out = v.to_dict()
        self.assertEqual(out["diagnostic"]["diagnostic_status"], "UNVERIFIED")
        self.assertEqual(out["director"]["aggregate_status"], "SUCCESS")  # native, not retouched
        self.assertIn("DIRECTOR_SUCCESS_UNVERIFIED", out["consistency_codes"])
        self.assertIn("AGGREGATE_STATUS_MISMATCH", out["consistency_codes"])
        self.assertIn("DIRECTOR_SUCCESS_UNVERIFIED", out["workers"][0]["consistency_codes"])
        self.assertFalse(v.cross_source_consistent)
        self.assertNotEqual(out["advisory"]["category"], "HISTORICAL_SUCCESS")

    def test_contradictory_director_and_runner_states(self):
        summary, pr, results = _dag(_ok("a"), _ok("b"))
        failed_pr = _pipeline([_entry("a"), _failed("b")[0]])
        failed_results = {"a": results["a"], "b": _failed("b")[1]}
        out = _build(summary, failed_pr, failed_results).to_dict()
        self.assertIn("WORKER_STATE_MISMATCH", out["consistency_codes"])
        self.assertIn("PIPELINE_STATUS_MISMATCH", out["consistency_codes"])
        self.assertIn("DIRECTOR_SUCCESS_UNVERIFIED", out["consistency_codes"])
        self.assertEqual(out["workers"][1]["director_state"], "SUCCESS")
        self.assertEqual(out["workers"][1]["runner_state"], "FAILED")
        self.assertFalse(out["cross_source_consistent"])

    def test_duplicate_runner_ids_preserve_every_declared_worker(self):
        summary, _, results = _dag(_ok("a"), _ok("b"))
        dup_pr = _pipeline([_entry("a"), _entry("b"), _entry("b")])
        out = _build(summary, dup_pr, results).to_dict()
        self.assertIn("DUPLICATE_WORKER_ID", out["consistency_codes"])
        self.assertEqual([w["worker_id"] for w in out["workers"]], ["a", "b", "b"])
        self.assertEqual(out["workers"][2]["director_index"], None)
        self.assertEqual(out["workers"][2]["runner_index"], 2)
        self.assertEqual(len(out["diagnostic"]["workers"]), 3)

    def test_reordered_workers_follow_director_order(self):
        summary, _, results = _dag(_ok("a"), _ok("b"), _ok("c"))
        reordered = _pipeline([_entry("c"), _entry("a"), _entry("b")])
        out = _build(summary, reordered, results).to_dict()
        self.assertIn("WORKER_ORDER_MISMATCH", out["consistency_codes"])
        self.assertEqual([w["worker_id"] for w in out["workers"]], ["a", "b", "c"])
        self.assertEqual([w["runner_index"] for w in out["workers"]], [1, 2, 0])
        self.assertFalse(out["cross_source_consistent"])

    def test_missing_result_fails_closed(self):
        summary, pr, results = _dag(_ok("a"), _ok("b"))
        partial = {"a": results["a"]}
        out = _build(summary, pr, partial).to_dict()
        self.assertIn("MISSING_WORKER_RESULT", out["consistency_codes"])
        self.assertIn("WORKER_RECORD_MISMATCH", out["consistency_codes"])
        self.assertEqual(len(out["workers"]), 2)
        self.assertFalse(out["workers"][1]["result_present"])
        self.assertEqual(out["diagnostic"]["diagnostic_status"], "UNVERIFIED")

    def test_explicit_absent_result_for_pending_worker_is_not_missing(self):
        retry = (_entry("b", "RETRY_WAIT", "TRANSIENT:CLAUDE_ERROR", result_path=False), None)
        out = _build(*_dag(_ok("a"), retry, status="RUNNING")).to_dict()
        self.assertNotIn("MISSING_WORKER_RESULT", out["consistency_codes"])
        self.assertEqual(out["workers"][1]["advisory_category"], "EXISTING_RETRY_WAIT")
        self.assertTrue(out["cross_source_consistent"])

    def test_unexpected_extra_result(self):
        summary, pr, results = _dag(_ok("a"), _ok("b"))
        out = _build(summary, pr, {**results, "intruder": _result("intruder")}).to_dict()
        self.assertIn("EXTRA_WORKER_RESULT", out["consistency_codes"])
        self.assertEqual(out["diagnostic"]["extra_worker_ids"], ["intruder"])
        self.assertEqual([w["worker_id"] for w in out["workers"]], ["a", "b"])

    def test_director_only_worker_is_preserved(self):
        summary, _, results = _dag(_ok("a"), _ok("b"))
        out = _build(summary, _pipeline([_entry("a")]), {"a": results["a"]}).to_dict()
        self.assertIn("WORKER_SET_MISMATCH", out["consistency_codes"])
        self.assertEqual([w["worker_id"] for w in out["workers"]], ["a", "b"])
        self.assertIsNone(out["workers"][1]["runner_index"])

    def test_pipeline_identity_mismatch(self):
        summary, pr, results = _dag(_ok("a"))
        other = dict(pr, pipeline_id="fdb-other")
        out = _build(summary, other, results).to_dict()
        self.assertIn("PIPELINE_ID_MISMATCH", out["consistency_codes"])
        self.assertIn("RUNNER_EVIDENCE_INCONSISTENT", out["consistency_codes"])


class MalformedAndSecretInputTest(unittest.TestCase):
    def test_malformed_runner_sources_fail_closed_without_raising(self):
        summary, _, _ = _dag(_ok("a"))
        for pr, results in ((None, {}), ({"workers": "nope"}, []), (["x"], None), ({"workers": [7, None]}, {})):
            v = _build(summary, pr, results)
            self.assertFalse(v.cross_source_consistent)
            self.assertIn("RUNNER_EVIDENCE_INCONSISTENT", v.consistency_codes)
            self.assertNotEqual(v.to_dict()["diagnostic"]["diagnostic_status"], "SUCCESS")

    def test_untyped_or_malformed_director_summary(self):
        summary, pr, results = _dag(_ok("a"))
        untyped = _build(dataclasses.asdict(summary), pr, results).to_dict()
        self.assertIn("SUMMARY_NOT_TYPED", untyped["consistency_codes"])
        self.assertIsNone(untyped["director"])
        self.assertEqual([w["worker_id"] for w in untyped["workers"]], ["a"])
        bad = dataclasses.replace(summary, manifest_sha256="../etc", aggregate_status="GREAT",
                                  workers=summary.workers + ({"worker_id": "x"},))
        out = _build(bad, pr, results).to_dict()
        self.assertIn("DIRECTOR_SUMMARY_MALFORMED", out["consistency_codes"])
        self.assertIsNone(out["director"]["manifest_sha256"])
        self.assertEqual(out["director"]["aggregate_status"], view.UNRECOGNIZED)

    def test_secrets_paths_timestamps_and_prose_never_exported(self):
        leaky = (_entry("a", "FAILED", f"CLAUDE_ERROR:{SECRET}"),
                 _result("a", "FAILED", code="CLAUDE_ERROR", state_reason=f"CLAUDE_ERROR:{SECRET}", message=SECRET,
                         error=SECRET, prompt=SECRET, stdout=SECRET,
                         attempts=[_attempt(runner_state="CLAUDE_ERROR", error_message=SECRET,
                                            retry_decision="NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR")]))
        summary, pr, results = _dag(leaky, _ok("b"), stop_reason=f"{SECRET} at C:/secret/path")
        summary = dataclasses.replace(summary, aggregate_reasons=summary.aggregate_reasons + (SECRET,))
        text = view.canonical_json(_build(summary, pr, results))
        for forbidden in (SECRET, STATE_ROOT, "C:/", "2026-10-28T", "evidence_dir", "next_eligible", "claude"):
            self.assertNotIn(forbidden, text)
        out = json.loads(text)
        self.assertEqual(out["director"]["stop_reason"], view.UNRECOGNIZED)
        self.assertIn(view.UNRECOGNIZED, out["director"]["aggregate_reasons"])

    def test_inputs_are_not_mutated(self):
        summary, pr, results = _dag(_ok("a"), _failed("b"))
        before = (copy.deepcopy(summary), copy.deepcopy(pr), copy.deepcopy(results))
        v = _build(summary, pr, results)
        out = v.to_dict()
        out["workers"].clear()
        out["director"]["aggregate_status"] = "SUCCESS"
        self.assertEqual((summary, pr, results), before)
        self.assertEqual(len(v.to_dict()["workers"]), 2)
        self.assertEqual(v.to_dict()["director"]["aggregate_status"], "FAILED")


class PurityAndAuthorityTest(unittest.TestCase):
    def test_determinism_and_canonical_json(self):
        args = _dag(_ok("a"), _failed("b"), _ok("c"))
        first, second = view.canonical_json(_build(*args)), view.canonical_json(_build(*copy.deepcopy(args)))
        self.assertEqual(first, second)
        self.assertEqual(first, json.dumps(json.loads(first), sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=True))
        out = json.loads(first)
        self.assertEqual((out["schema"], out["schema_version"]), (view.SCHEMA, view.SCHEMA_VERSION))

    def test_calls_exactly_assess_pipeline_and_advise_pipeline(self):
        summary, pr, results = _dag(_ok("a"), _ok("b"))
        with mock.patch.object(view.fi, "assess_pipeline", wraps=fi.assess_pipeline) as assess, \
                mock.patch.object(view.ra, "advise_pipeline", wraps=ra.advise_pipeline) as advise:
            out = _build(summary, pr, results).to_dict()
        assess.assert_called_once_with(pr, results)
        self.assertIs(assess.call_args.args[0], pr)
        advise.assert_called_once()
        diagnostic = fi.assess_pipeline(pr, results)
        self.assertEqual(out["diagnostic"], diagnostic.to_dict())
        self.assertEqual(out["advisory"], ra.advise_pipeline(diagnostic).to_dict())

    def test_no_io_subprocess_or_director_service_calls_at_runtime(self):
        args = _dag(_ok("a"), _failed("b"))
        boom = mock.Mock(side_effect=AssertionError("I/O attempted"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(fd.FabricDirectorService, "result_blueprint", boom), \
                mock.patch.object(fd.FabricDirectorService, "run_blueprint", boom):
            _build(*args)
        boom.assert_not_called()

    def test_module_source_has_no_io_or_control_imports(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" for a in node.names}
        self.assertEqual(imported, {
            "__future__.annotations", "json", "re", "collections.Counter", "collections.abc.Mapping",
            "dataclasses.dataclass", "typing.Optional", "scripts.ai.fabric_director",
            "scripts.ai.runner_failure_intelligence", "scripts.ai.runner_recovery_advisory",
        })
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(names & {"open", "exec", "eval", "__import__"})
        self.assertFalse(attrs & {"result_blueprint", "run_blueprint", "recover", "submit_blueprint", "run",
                                  "Popen", "system", "read_text", "write_text"})

    def test_no_authority_flags_are_fixed_and_read_only(self):
        v = _build(*_dag(_ok("a")))
        out = v.to_dict()
        self.assertEqual(out["marker"], view.VIEW_MARKER)
        for flag in NO_AUTH:
            self.assertIs(out[flag], False)
            with self.assertRaises(AttributeError):
                setattr(v, flag, True)
        for embedded in (out["diagnostic"], out["advisory"]):
            self.assertFalse(embedded["authorizes_action"] or embedded["execution_allowed"]
                             or embedded["auto_retry_allowed"] or embedded["certified"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            v.consistency_codes = ()
        with self.assertRaises(ValueError):
            dataclasses.replace(v, consistency_codes=("RETRY_NOW",))
        self.assertNotIn("resume_from", view.canonical_json(v))


if __name__ == "__main__":
    unittest.main()
