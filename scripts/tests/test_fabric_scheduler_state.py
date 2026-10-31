"""FCP-9C-02: Scheduler state projection and reliable tracking.

Offline and synthetic: Director DAG summaries are built in memory with the
Director's own projection helpers, the Runner status is a dict shaped like
`runner_pipeline.PipelineRunner.build_result` + `read_pipeline_status`, and
the FCP-8 evaluations are derived with the real FCP-8 functions. No Runner,
Git, process, network, clock or file is touched. Nothing here is skipped.
"""

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
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import fabric_scheduler_state as st
from scripts.ai import fabric_validation_dag as vd
from scripts.ai import fabric_validation_rules as vr
from scripts.ai import runner_pipeline as rp

MODULE_PATH = Path(st.__file__)
TEST_PATH = Path(__file__).resolve()
RUN = "fdb-20261030t120000000000-abcdef12"
OTHER_RUN = "fdb-20261030t120000000000-00000000"
AS_OF = "2026-10-30T12:00:00Z"
BEAT = "2026-10-30T11:59:30.250000+00:00"
STARTED = "2026-10-30T11:00:00+00:00"
MANIFEST = "a" * 64
PLAN = "b" * 64
SECRET_DIR = "C:/Users/someone/private/evidence/attempt-1"
PROSE = "the provider says: all good, trust me"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized")
_W = rp.WorkerState


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def wid(i: int) -> str:
    return f"w-{i:02d}"


def worker(worker_id, depends_on=(), state="SUCCESS", **overrides) -> fd.DirectorDagWorkerSummary:
    """A worker whose health/proof are derived by the Director's own helper
    unless explicitly overridden."""
    success = state == "SUCCESS"
    values = dict(
        worker_id=worker_id, depends_on=tuple(depends_on), worker_state=state,
        state_reason=None if success else f"{state}:{PROSE}", provider="opaque-a", requested_provider="opaque-a",
        work_status="SUCCESS" if success else None, provider_work_status="SUCCESS",
        work_status_source="RUNNER_ACCEPTANCE" if success else None, runner_state=state, attempts=1,
        work_attempts_used=1, availability_attempts=0, provider_condition=None, next_eligible_utc=None,
        checkpoint_commit="abc1234" if success else None, worker_record="PRESENT", evidence_dir=SECRET_DIR,
        evidence_complete=True if success else None, unauthorized_changed_paths=(),
    )
    values.update(overrides)
    if "evidence_health" not in overrides:
        values["evidence_health"] = {True: "COMPLETE", False: "INCOMPLETE"}.get(values["evidence_complete"],
                                                                                "UNKNOWN")
    if "unproven_reasons" not in overrides:
        values["unproven_reasons"] = fd._dag_unproven_reasons(
            worker_state=values["worker_state"], work_status=values["work_status"],
            worker_record=values["worker_record"], evidence_health=values["evidence_health"],
            unauthorized=values["unauthorized_changed_paths"],
        )
    if "runner_proven_success" not in overrides:
        values["runner_proven_success"] = not values["unproven_reasons"]
    return fd.DirectorDagWorkerSummary(**values)


def dag(states=("SUCCESS", "SUCCESS", "SUCCESS"), pipeline_status=None, overrides=None, **summary_overrides):
    """A chain w-00 <- w-01 <- ... in the given native states."""
    overrides = overrides or {}
    workers = tuple(worker(wid(i), **{"depends_on": (wid(i - 1),) if i else (), "state": state,
                                      **overrides.get(i, {})})
                    for i, state in enumerate(states))
    if pipeline_status is None:
        terminal = {s.value for s in rp.TERMINAL_STATES}
        if any(s not in terminal for s in states):
            pipeline_status = "INCOMPLETE"
        elif all(s == "SUCCESS" for s in states):
            pipeline_status = "SUCCESS"
        else:
            pipeline_status = next(p for p in ("FAILED", "BLOCKED", "CANCELLED", "PARTIAL") if p in states)
    aggregate, reasons = fd._classify_dag_aggregate(pipeline_status, workers)
    values = dict(run_id=RUN, pipeline_id=RUN, blueprint_pipeline_id="bp-private", manifest_sha256=MANIFEST,
                  plan_fingerprint=PLAN, pipeline_status=pipeline_status, stop_reason=PROSE, workers=workers,
                  aggregate_status=aggregate, aggregate_reasons=reasons)
    values.update(summary_overrides)
    return fd.DirectorDagRunSummary(**values)


def runner_status(summary, *, beats=None, **overrides) -> dict:
    """Shaped like `build_result` + `read_pipeline_status` liveness."""
    beats = beats or {}
    states = [w.worker_state for w in summary.workers]
    counts = {s.value: states.count(s.value) for s in _W}
    entries = []
    for w in summary.workers:
        entry = {"id": w.worker_id, "provider": "opaque-a", "state": w.worker_state, "state_reason": PROSE,
                 "attempts": 1, "result_path": SECRET_DIR, "worker_path": SECRET_DIR}
        if w.worker_state == "RUNNING":
            liveness, beat = beats.get(w.worker_id, ("ALIVE", BEAT))
            entry.update(liveness=liveness, last_heartbeat_utc=beat)
        entries.append(entry)
    result = {
        "schema_version": 1, "pipeline_id": summary.run_id, "status": summary.pipeline_status, "stop_reason": PROSE,
        "started_at_utc": STARTED, "ended_at_utc": None, "duration_seconds": 3600.0,
        "workers_total": len(states), "success": counts["SUCCESS"], "partial": counts["PARTIAL"],
        "blocked": counts["BLOCKED"], "failed": counts["FAILED"], "cancelled": counts["CANCELLED"],
        "interrupted": counts["INTERRUPTED"], "waiting_provider_quota": counts["WAITING_PROVIDER_QUOTA"],
        "blocked_provider_auth": counts["BLOCKED_PROVIDER_AUTH"], "state_counts": counts,
        "provider_breakdown": {"opaque-a": {"total": len(states)}}, "max_observed_concurrency": 2,
        "workers": entries,
    }
    result.update(overrides)
    return result


class _Reader:
    def __init__(self, summary):
        self.summary = summary

    def result_blueprint(self, run_id):
        return self.summary


def fcp8(summary):
    observation = vd.observe_dag_run(_Reader(summary), RUN)
    return observation, vr.classify_evidence(observation)


def request(summary, *, status="default", with_fcp8=True, **extra):
    if status == "default":
        status = runner_status(summary)
    observation, classification = fcp8(summary) if with_fcp8 else (None, None)
    values = dict(run_id=RUN, as_of_utc=AS_OF, dag_summary=summary, runner_status=status,
                  dag_observation=observation, evidence_classification=classification)
    values.update(extra)
    return st.StateProjectionRequest(**values)


def project(summary, **kwargs):
    return st.project_state(request(summary, **kwargs))


class FakeService:
    """Only `result_blueprint` and `status` exist; every call is recorded and
    any other attribute access or write fails."""

    def __init__(self, summary, status=None, *, raises=None, status_raises=None):
        self.__dict__.update(calls=[], forbidden=[], _summary=summary, _status=status, _raises=raises,
                             _status_raises=status_raises)

    def result_blueprint(self, run_id):
        self.calls.append(("result_blueprint", run_id))
        if self._raises is not None:
            raise self._raises
        return self._summary

    def status(self, run_id):
        self.calls.append(("status", run_id))
        if self._status_raises is not None:
            raise self._status_raises
        return self._status

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"forbidden access: {name}")

    def __setattr__(self, name, value):
        raise AssertionError(f"forbidden write: {name}")


# ---------------------------------------------------------------------------
# Node status from native states
# ---------------------------------------------------------------------------
class NodeStatusTests(unittest.TestCase):
    def test_every_native_state_maps_to_exactly_one_documented_status(self):
        self.assertEqual(set(st.STATUS_OF_NATIVE), {s.value for s in _W})
        self.assertTrue(set(st.STATUS_OF_NATIVE.values()) <= set(st.NODE_STATUSES) - {st.UNVERIFIED, st.UNKNOWN})
        self.assertEqual({st.STATUS_OF_NATIVE[s] for s in ("QUEUED", "WAITING_DEPENDENCY", "RETRY_WAIT")},
                         {st.PENDING})
        self.assertEqual({st.STATUS_OF_NATIVE[s] for s in ("BLOCKED", "BLOCKED_PROVIDER_AUTH", "INTERRUPTED")},
                         {st.BLOCKED})
        self.assertEqual({st.STATUS_OF_NATIVE[s] for s in ("FAILED", "PARTIAL")}, {st.FAILED})

    def test_pending_and_ready_nodes_keep_the_run_in_progress(self):
        p = project(dag(("SUCCESS", "READY", "QUEUED", "WAITING_DEPENDENCY", "RETRY_WAIT")))
        self.assertEqual([n.status for n in p.nodes], [st.SUCCESS, st.READY, st.PENDING, st.PENDING, st.PENDING])
        self.assertEqual([n.native_state for n in p.nodes][2:], ["QUEUED", "WAITING_DEPENDENCY", "RETRY_WAIT"])
        self.assertEqual(p.outcome, st.IN_PROGRESS)
        self.assertFalse(p.finished)

    def test_success_requires_runner_proof_and_bound_fcp8(self):
        p = project(dag())
        self.assertEqual(p.outcome, st.SUCCESS)
        self.assertTrue(p.finished)
        self.assertEqual({n.status for n in p.nodes}, {st.SUCCESS})
        self.assertEqual(p.fcp8_classification, vd.ALL_WORKERS_PROVEN)
        self.assertIs(p.fcp8_work_success, True)
        self.assertEqual(p.metrics["completed"], 3)

    def test_native_success_without_fcp8_is_unverified_and_not_finished(self):
        p = project(dag(), with_fcp8=False)
        self.assertEqual({n.status for n in p.nodes}, {st.UNVERIFIED})
        self.assertTrue(all(st.FCP8_EVALUATION_MISSING in n.codes for n in p.nodes))
        self.assertEqual(p.outcome, st.UNVERIFIED)
        self.assertFalse(p.finished)
        self.assertIsNone(p.fcp8_classification)

    def test_native_success_with_incomplete_evidence_is_unverified(self):
        p = project(dag(overrides={1: {"evidence_complete": False}}))
        node = p.node_of(wid(1))
        self.assertEqual(node.status, st.UNVERIFIED)
        self.assertIn(st.RUNNER_UNPROVEN, node.codes)
        self.assertIn(st.FCP8_EVIDENCE_UNCERTAIN, node.codes)
        self.assertEqual(p.aggregate_status, fd.DAG_AGGREGATE_UNVERIFIED)
        self.assertEqual(p.outcome, st.UNVERIFIED)

    def test_native_success_without_checkpoint_is_unverified(self):
        p = project(dag(overrides={0: {"checkpoint_commit": None}}))
        node = p.node_of(wid(0))
        self.assertEqual(node.status, st.UNVERIFIED)
        self.assertEqual(node.codes, (st.FCP8_WORK_UNPROVEN,))
        self.assertEqual(p.outcome, st.UNVERIFIED)

    def test_failed_and_partial_runs_are_not_successful_only_with_fcp8(self):
        summary = dag(("SUCCESS", "FAILED", "PARTIAL"))
        p = project(summary)
        self.assertEqual([n.status for n in p.nodes], [st.SUCCESS, st.FAILED, st.FAILED])
        self.assertEqual(p.outcome, st.NOT_SUCCESSFUL)
        self.assertTrue(p.finished)
        self.assertEqual(project(summary, with_fcp8=False).outcome, st.UNVERIFIED)

    def test_cancelled_and_blocked_are_projected_verbatim(self):
        p = project(dag(("BLOCKED", "CANCELLED")))
        self.assertEqual([n.status for n in p.nodes], [st.BLOCKED, st.CANCELLED])
        self.assertEqual(p.pipeline_status, "BLOCKED")
        self.assertEqual(p.outcome, st.NOT_SUCCESSFUL)

    def test_provider_quota_wait_pauses_with_its_native_eligibility_instant(self):
        summary = dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: {
            "provider_condition": "PROVIDER_QUOTA_EXHAUSTED", "next_eligible_utc": "2026-10-30T14:00:00+02:00"}})
        p = project(summary)
        node = p.node_of(wid(1))
        self.assertEqual(node.status, st.WAITING_PROVIDER_QUOTA)
        self.assertEqual(node.provider_condition, "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual(node.next_eligible_utc, "2026-10-30T12:00:00Z")
        self.assertEqual(p.outcome, st.PAUSED)
        self.assertEqual(p.metrics["paused_provider_quota"], 1)
        bad = project(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: {"next_eligible_utc": "soon"}}))
        self.assertIsNone(bad.node_of(wid(1)).next_eligible_utc)
        self.assertIn(st.TIMESTAMP_INVALID, bad.node_of(wid(1)).codes)

    def test_auth_block_and_interruption_are_operator_pauses(self):
        p = project(dag(("BLOCKED_PROVIDER_AUTH", "INTERRUPTED", "QUEUED"), pipeline_status="INCOMPLETE"))
        self.assertEqual([n.status for n in p.nodes][:2], [st.BLOCKED, st.BLOCKED])
        self.assertEqual(p.outcome, st.IN_PROGRESS)
        p = project(dag(("SUCCESS", "BLOCKED_PROVIDER_AUTH", "INTERRUPTED")))
        self.assertEqual(p.outcome, st.PAUSED)
        self.assertEqual(p.metrics["paused_operator"], 2)
        self.assertEqual(p.metrics["completed"], 1)

    def test_unrecognized_native_state_is_unknown_never_success(self):
        p = project(dag(("SUCCESS", "DONE_PROBABLY")), status=None, with_fcp8=False)
        node = p.node_of(wid(1))
        self.assertEqual(node.status, st.UNKNOWN)
        self.assertEqual(node.native_state, st.UNRECOGNIZED)
        self.assertIn(st.NATIVE_STATE_UNRECOGNIZED, node.codes)
        self.assertEqual(p.outcome, st.UNKNOWN)
        self.assertIn(st.NODE_UNKNOWN, p.codes)

    def test_self_contradicting_director_record_is_unknown(self):
        summary = dag(overrides={2: {"runner_proven_success": True, "unproven_reasons": ("EVIDENCE_UNKNOWN",)}})
        p = project(summary, status=None)
        self.assertEqual(p.node_of(wid(2)).status, st.UNKNOWN)
        self.assertIn(st.NODE_RECORD_INCONSISTENT, p.node_of(wid(2)).codes)
        self.assertEqual(p.outcome, st.UNKNOWN)

    def test_native_reason_is_only_its_leading_code_never_prose(self):
        summary = dag(("FAILED", "CANCELLED", "BLOCKED"), overrides={
            0: {"state_reason": "PROVIDER_EXIT_NONZERO"}, 1: {"state_reason": "DEPENDENCY_UNSATISFIED:w-00=FAILED"},
            2: {"state_reason": PROSE, "provider_condition": "maybe quota?"}})
        p = project(summary)
        self.assertEqual([n.native_reason for n in p.nodes], ["PROVIDER_EXIT_NONZERO", "DEPENDENCY_UNSATISFIED", None])
        self.assertIn(st.NATIVE_REASON_UNRECOGNIZED, p.node_of(wid(2)).codes)
        self.assertIn(st.PROVIDER_CONDITION_UNRECOGNIZED, p.node_of(wid(2)).codes)
        self.assertIsNone(p.node_of(wid(2)).provider_condition)
        text = st.canonical_json(p)
        for leak in (PROSE, "w-00=FAILED", "maybe quota", SECRET_DIR, "opaque-a", "bp-private"):
            self.assertNotIn(leak, text)


# ---------------------------------------------------------------------------
# RUNNING: heartbeat evidence vs unverifiable
# ---------------------------------------------------------------------------
class HeartbeatTests(unittest.TestCase):
    def running(self, beat=("ALIVE", BEAT), **kwargs):
        summary = dag(("SUCCESS", "RUNNING", "QUEUED"))
        return project(summary, status=runner_status(summary, beats={wid(1): beat}), **kwargs).node_of(wid(1))

    def test_fresh_alive_heartbeat_is_verified_evidence(self):
        node = self.running()
        self.assertEqual((node.status, node.heartbeat), (st.RUNNING, st.HB_VERIFIED))
        self.assertEqual(node.last_heartbeat_utc, "2026-10-30T11:59:30.250000Z")
        self.assertEqual(node.codes, ())

    def test_running_without_runner_status_is_unverifiable(self):
        p = project(dag(("SUCCESS", "RUNNING", "QUEUED")), status=None)
        node = p.node_of(wid(1))
        self.assertEqual((node.status, node.heartbeat), (st.RUNNING, st.HB_UNVERIFIABLE))
        self.assertIn(st.HEARTBEAT_NOT_OBSERVED, node.codes)
        self.assertIsNone(node.last_heartbeat_utc)
        self.assertIn(st.RUNNING_HEARTBEAT_UNVERIFIED, p.codes)
        self.assertEqual(p.metrics["running_heartbeat_verified"], 0)
        self.assertEqual(p.outcome, st.IN_PROGRESS)

    def test_runner_stale_verdict_or_old_beat_is_stale(self):
        self.assertEqual(self.running(("STALE", BEAT)).heartbeat, st.HB_STALE)
        old = self.running(("ALIVE", "2026-10-30T11:29:59Z"))
        self.assertEqual((old.heartbeat, old.codes), (st.HB_STALE, (st.HEARTBEAT_STALE,)))
        boundary = self.running(("ALIVE", "2026-10-30T11:30:00Z"))
        self.assertEqual(boundary.heartbeat, st.HB_VERIFIED)
        narrowed = self.running(("ALIVE", BEAT), max_heartbeat_age_seconds=10)
        self.assertEqual(narrowed.heartbeat, st.HB_STALE)

    def test_pid_only_liveness_missing_or_future_beat_is_unverifiable(self):
        for beat, code in ((("ALIVE", None), st.HEARTBEAT_UNVERIFIABLE),
                           (("UNVERIFIABLE", BEAT), st.HEARTBEAT_UNVERIFIABLE),
                           ((None, None), st.HEARTBEAT_UNVERIFIABLE),
                           (("ALIVE", "garbage"), st.HEARTBEAT_UNVERIFIABLE),
                           (("ALIVE", "2026-10-30T12:00:01Z"), st.HEARTBEAT_FROM_FUTURE)):
            node = self.running(beat)
            self.assertEqual((node.status, node.heartbeat), (st.RUNNING, st.HB_UNVERIFIABLE), beat)
            self.assertIn(code, node.codes, beat)
        self.assertIsNone(self.running(("ALIVE", "2026-10-30T12:00:01Z")).last_heartbeat_utc)

    def test_heartbeat_age_may_only_narrow_the_runner_lease(self):
        self.assertEqual(st.MAX_HEARTBEAT_AGE_SECONDS, int(rp.DEFAULT_LEASE_SECONDS))
        for bad in (0, -1, st.MAX_HEARTBEAT_AGE_SECONDS + 1, True, 1.5, "60"):
            p = project(dag(), max_heartbeat_age_seconds=bad)
            self.assertEqual(p.request_reasons, (st.MAX_HEARTBEAT_AGE_INVALID,), bad)

    def test_non_running_nodes_never_claim_a_heartbeat(self):
        summary = dag(("SUCCESS", "READY"))
        status = runner_status(summary)
        status["workers"][1].update(liveness="ALIVE", last_heartbeat_utc=BEAT)
        p = project(summary, status=status)
        self.assertEqual({n.heartbeat for n in p.nodes}, {st.HB_NOT_APPLICABLE})
        self.assertTrue(all(n.last_heartbeat_utc is None for n in p.nodes))


# ---------------------------------------------------------------------------
# Runner status cross-checks and grounded metrics
# ---------------------------------------------------------------------------
class StatusAndMetricsTests(unittest.TestCase):
    def test_state_changed_between_the_two_reads_is_unknown(self):
        summary = dag(("SUCCESS", "RUNNING", "QUEUED"))
        status = runner_status(summary)
        status["workers"][1]["state"] = "SUCCESS"
        p = project(summary, status=status)
        self.assertEqual(p.node_of(wid(1)).status, st.UNKNOWN)
        self.assertIn(st.STATUS_ENTRY_MISMATCH, p.node_of(wid(1)).codes)
        self.assertEqual(p.outcome, st.UNKNOWN)

    def test_status_of_another_run_order_or_aggregate_is_a_mismatch(self):
        summary = dag()
        for status in (runner_status(summary, pipeline_id=OTHER_RUN), runner_status(summary, status="FAILED"),
                       runner_status(summary, workers=list(reversed(runner_status(summary)["workers"])))):
            p = project(summary, status=status)
            self.assertIn(st.STATUS_MISMATCH, p.codes)
            self.assertEqual(p.outcome, st.UNKNOWN)
            self.assertFalse(p.finished)

    def test_malformed_status_is_unknown_never_success(self):
        summary = dag()
        for status in ([], "SUCCESS", {"workers": "all"}, {"workers": [1, 2, 3]}, {}):
            p = project(summary, status=status)
            self.assertIn(st.STATUS_MALFORMED, p.codes, status)
            self.assertEqual(p.outcome, st.UNKNOWN, status)

    def test_native_counts_must_agree_with_the_worker_states(self):
        summary = dag()
        for overrides in ({"success": 2}, {"workers_total": 4}, {"workers_total": True}, {"state_counts": {}},
                          {"failed": None}):
            p = project(summary, status=runner_status(summary, **overrides))
            self.assertIn(st.METRICS_MISMATCH, p.codes, overrides)
            self.assertEqual(p.outcome, st.UNKNOWN, overrides)

    def test_max_observed_concurrency_is_native_or_absent(self):
        summary = dag()
        self.assertEqual(project(summary).max_observed_concurrency, 2)
        missing = project(summary, status=runner_status(summary, max_observed_concurrency=None))
        self.assertIsNone(missing.max_observed_concurrency)
        self.assertIn(st.CONCURRENCY_NOT_OBSERVED, missing.codes)
        self.assertEqual(missing.outcome, st.SUCCESS)
        not_read = project(summary, status=None)
        self.assertIsNone(not_read.max_observed_concurrency)
        self.assertIn(st.STATUS_NOT_OBSERVED, not_read.codes)
        for bad in (-1, rp.MAX_PIPELINE_WORKERS + 1, "2", 2.0, True):
            p = project(summary, status=runner_status(summary, max_observed_concurrency=bad))
            self.assertIsNone(p.max_observed_concurrency, bad)
            self.assertIn(st.METRICS_MISMATCH, p.codes, bad)

    def test_run_timestamps_are_normalized_and_contradictions_fail_closed(self):
        summary = dag()
        p = project(summary, status=runner_status(summary, ended_at_utc="2026-10-30T13:30:00+02:00"))
        self.assertEqual((p.started_at_utc, p.ended_at_utc), ("2026-10-30T11:00:00Z", "2026-10-30T11:30:00Z"))
        self.assertEqual(p.outcome, st.SUCCESS)
        inverted = project(summary, status=runner_status(summary, ended_at_utc="2026-10-30T10:00:00Z"))
        self.assertIn(st.TIMESTAMP_INCONSISTENT, inverted.codes)
        self.assertEqual(inverted.outcome, st.UNKNOWN)
        future = project(summary, status=runner_status(summary, started_at_utc="2026-10-31T00:00:00Z"))
        self.assertIsNone(future.started_at_utc)
        self.assertIn(st.RUN_TIMESTAMP_FROM_FUTURE, future.codes)
        garbage = project(summary, status=runner_status(summary, started_at_utc="yesterday"))
        self.assertIsNone(garbage.started_at_utc)
        self.assertIn(st.RUN_TIMESTAMP_INVALID, garbage.codes)

    def test_metrics_are_counts_only_never_durations(self):
        p = project(dag(("SUCCESS", "FAILED", "CANCELLED", "RUNNING", "QUEUED"), pipeline_status="RUNNING"))
        metrics = p.metrics
        self.assertEqual(metrics["workers_total"], 5)
        self.assertEqual(metrics["completed"], 3)
        self.assertEqual(sum(n for _, n in metrics["status_counts"]), 5)
        self.assertEqual(dict(metrics["status_counts"])[st.RUNNING], 1)
        self.assertEqual(metrics["running_heartbeat_verified"], 1)
        text = st.canonical_json(p)
        for word in ("duration", "eta", "rate", "elapsed", "3600"):
            self.assertNotIn(word, text.lower(), word)
        self.assertEqual(p.outcome, st.IN_PROGRESS)

    def test_unknown_nodes_are_never_counted_as_completed(self):
        summary = dag(("SUCCESS", "FAILED"))
        status = runner_status(summary)
        status["workers"][1]["state"] = "SUCCESS"
        p = project(summary, status=status)
        self.assertEqual(p.metrics["completed"], 1)
        self.assertEqual(dict(p.metrics["status_counts"])[st.UNKNOWN], 1)


# ---------------------------------------------------------------------------
# Aggregation, corruption and FCP-8 binding
# ---------------------------------------------------------------------------
class AggregationTests(unittest.TestCase):
    def test_runner_still_running_is_never_finished(self):
        p = project(dag(pipeline_status="RUNNING"))
        self.assertEqual(p.outcome, st.IN_PROGRESS)
        self.assertEqual(project(dag(pipeline_status="DRAINING")).outcome, st.IN_PROGRESS)

    def test_aggregate_contradicting_worker_states_is_unknown(self):
        for summary in (dag(("SUCCESS", "SUCCESS"), pipeline_status="INCOMPLETE"),
                        dag(("FAILED", "QUEUED"), pipeline_status="FAILED"),
                        dag(("FAILED", "INTERRUPTED"), pipeline_status="FAILED")):
            p = project(summary)
            self.assertIn(st.AGGREGATE_STATE_MISMATCH, p.codes)
            self.assertEqual(p.outcome, st.UNKNOWN)

    def test_unrecognized_pipeline_status_is_unknown(self):
        summary = dag(pipeline_status="ALMOST_DONE")
        p = project(summary, status=None)
        self.assertEqual(p.pipeline_status, st.UNRECOGNIZED)
        self.assertIn(st.PIPELINE_STATUS_UNKNOWN, p.codes)
        self.assertEqual(p.outcome, st.UNKNOWN)

    def test_corrupt_summaries_are_unknown_with_fcp8_codes_and_no_nodes(self):
        one = dag(("SUCCESS",))
        cyclic = dag(overrides={0: {"depends_on": (wid(2),)}})
        duplicate = dag(workers=(worker(wid(0)), worker(wid(0))), aggregate_status="SUCCESS", aggregate_reasons=())
        mismatch = dag(aggregate_status="FAILED")
        for summary, code in ((one, "TOO_FEW_WORKERS"), (cyclic, "DEPENDENCY_CYCLE"),
                              (duplicate, "DUPLICATE_WORKER_ID"), (mismatch, "AGGREGATE_STATUS_MISMATCH")):
            p = project(summary, status=None, with_fcp8=False)
            self.assertEqual(p.outcome, st.UNKNOWN, code)
            self.assertEqual(p.codes, (st.SUMMARY_INVALID,), code)
            self.assertIn(code, p.fcp8_codes)
            self.assertEqual(p.nodes, ())
            self.assertFalse(p.finished)

    def test_unsafe_worker_id_is_never_echoed(self):
        summary = dag(workers=(worker("../../etc"), worker("w-01", ("../../etc",))))
        p = project(summary, status=None, with_fcp8=False)
        self.assertEqual((p.outcome, p.codes, p.fcp8_codes), (st.UNKNOWN, (st.SUMMARY_INVALID,), ("WORKER_ID_INVALID",)))
        self.assertNotIn("etc", st.canonical_json(p))

    def test_stale_provenance_against_expected_digests_is_unknown(self):
        p = project(dag(), expected_manifest_sha256="c" * 64, with_fcp8=False)
        self.assertEqual(p.outcome, st.UNKNOWN)
        self.assertIn("STALE_PROVENANCE", p.fcp8_codes)
        self.assertEqual(project(dag(), expected_manifest_sha256=MANIFEST, expected_plan_fingerprint=PLAN).outcome,
                         st.SUCCESS)

    def test_fcp8_observation_of_another_projection_is_a_mismatch(self):
        summary = dag()
        foreign, _ = fcp8(dag(("SUCCESS", "SUCCESS")))
        p = project(summary, dag_observation=foreign, evidence_classification=None)
        self.assertIn(st.FCP8_OBSERVATION_MISMATCH, p.codes)
        self.assertEqual({n.status for n in p.nodes}, {st.UNKNOWN})
        self.assertEqual(p.outcome, st.UNKNOWN)
        self.assertIsNone(p.fcp8_classification)
        refused = vd._refused(vd.UNOBSERVABLE, ("READ_FAILED",))
        self.assertEqual(project(summary, dag_observation=refused, evidence_classification=None).outcome, st.UNKNOWN)

    def test_fcp8_classification_must_be_derived_from_that_observation(self):
        summary = dag()
        _, foreign = fcp8(dag(("SUCCESS", "FAILED")))
        p = project(summary, evidence_classification=foreign)
        self.assertIn(st.FCP8_CLASSIFICATION_MISMATCH, p.codes)
        self.assertEqual(p.outcome, st.UNKNOWN)
        observation, _ = fcp8(summary)
        missing = project(summary, evidence_classification=None)
        self.assertIn(st.FCP8_CLASSIFICATION_MISSING, missing.codes)
        self.assertIsNone(missing.fcp8_work_success)
        self.assertEqual(missing.outcome, st.SUCCESS)
        orphan = project(summary, dag_observation=None, evidence_classification=vr.classify_evidence(observation))
        self.assertEqual(orphan.request_reasons, (st.CLASSIFICATION_WITHOUT_OBSERVATION,))

    def test_garbage_requests_never_raise_and_echo_nothing(self):
        summary = dag()
        cases = [
            (None, st.REQUEST_NOT_TYPED), ({"run_id": RUN}, st.REQUEST_NOT_TYPED),
            (request(summary, schema_version=2), st.SCHEMA_VERSION_UNSUPPORTED),
            (request(summary, schema_version=True), st.SCHEMA_VERSION_UNSUPPORTED),
            (request(summary, run_id="../" + RUN), st.RUN_ID_INVALID),
            (request(summary, as_of_utc="2026-10-30T12:00:00"), st.AS_OF_INVALID),
            (request(summary, expected_plan_fingerprint="ABC"), st.EXPECTED_DIGEST_INVALID),
            (request(summary, dag_summary=dataclasses.asdict(summary)), st.SUMMARY_NOT_TYPED),
            (request(summary, dag_observation=fcp8(summary)[0].to_dict()), st.FCP8_OBSERVATION_NOT_TYPED),
            (request(summary, evidence_classification="VALIDATION_COMPLETE"), st.FCP8_CLASSIFICATION_NOT_TYPED),
        ]
        for value, reason in cases:
            p = st.project_state(value)
            self.assertEqual(p.outcome, st.REFUSED, reason)
            self.assertIn(reason, p.request_reasons)
            self.assertEqual((p.run_id, p.nodes, p.codes, p.pipeline_status), (None, (), (), None))
            self.assertFalse(p.finished)
            st.canonical_json(p)


# ---------------------------------------------------------------------------
# The reader: one read of each public Director query interface
# ---------------------------------------------------------------------------
class ObserverTests(unittest.TestCase):
    def test_reads_result_blueprint_then_status_once_each_and_nothing_else(self):
        summary = dag(("SUCCESS", "RUNNING", "QUEUED"))
        service = FakeService(summary, runner_status(summary))
        p = st.observe_scheduler_state(service, RUN, as_of_utc=AS_OF)
        self.assertEqual(service.calls, [("result_blueprint", RUN), ("status", RUN)])
        self.assertEqual(service.forbidden, [])
        self.assertEqual(p.node_of(wid(1)).heartbeat, st.HB_VERIFIED)
        self.assertEqual(p, project(summary))

    def test_status_read_is_optional(self):
        summary = dag()
        service = FakeService(summary)
        p = st.observe_scheduler_state(service, RUN, as_of_utc=AS_OF, read_status=False)
        self.assertEqual(service.calls, [("result_blueprint", RUN)])
        self.assertEqual(p.outcome, st.SUCCESS)
        self.assertIn(st.STATUS_NOT_OBSERVED, p.codes)

    def test_failed_reads_are_unobservable_and_status_failure_only_removes_proof(self):
        cases = ((fd.DirectorError("DAG_PROVENANCE_MISMATCH", PROSE), st.PROVENANCE_REFUSED),
                 (fd.DirectorError("PIPELINE_NOT_FOUND", PROSE), st.READ_FAILED), (OSError(SECRET_DIR), st.READ_FAILED))
        for exc, reason in cases:
            service = FakeService(None, raises=exc)
            p = st.observe_scheduler_state(service, RUN, as_of_utc=AS_OF)
            self.assertEqual((p.outcome, p.request_reasons), (st.UNOBSERVABLE, (reason,)))
            self.assertEqual(service.calls, [("result_blueprint", RUN)])
            self.assertNotIn(SECRET_DIR, st.canonical_json(p))
        summary = dag(("SUCCESS", "RUNNING", "QUEUED"))
        p = st.observe_scheduler_state(FakeService(summary, status_raises=OSError("gone")), RUN, as_of_utc=AS_OF)
        self.assertIn(st.STATUS_READ_FAILED, p.codes)
        self.assertEqual(p.node_of(wid(1)).heartbeat, st.HB_UNVERIFIABLE)
        self.assertEqual(p.outcome, st.IN_PROGRESS)

    def test_invalid_run_id_reads_nothing(self):
        service = FakeService(dag())
        for run_id in (None, "", "../x", RUN.upper(), "pipeline-1"):
            p = st.observe_scheduler_state(service, run_id, as_of_utc=AS_OF)
            self.assertEqual(p.request_reasons, (st.RUN_ID_INVALID,))
        self.assertEqual(service.calls, [])

    def test_untyped_summary_from_the_reader_is_refused(self):
        service = FakeService({"status": "SUCCESS"}, {"status": "SUCCESS"})
        p = st.observe_scheduler_state(service, RUN, as_of_utc=AS_OF)
        self.assertEqual((p.outcome, p.request_reasons), (st.REFUSED, (st.SUMMARY_NOT_TYPED,)))


# ---------------------------------------------------------------------------
# Guarantees: authority, typing, determinism, purity, governed surface
# ---------------------------------------------------------------------------
class GuaranteeTests(unittest.TestCase):
    def test_zero_authority_flags_are_fixed_and_serialized(self):
        for p in (project(dag()), st.project_state(None)):
            for flag in ALL_FLAGS:
                self.assertIs(getattr(p, flag), False)
            data = p.to_dict()
            for flag in ALL_FLAGS:
                self.assertIs(data[flag], False)
            self.assertEqual(data["marker"], st.STATE_MARKER)
            self.assertNotIn("certified", {f.name for f in dataclasses.fields(p)})
            with self.assertRaises(TypeError):
                dataclasses.replace(p, certified=True)

    def test_hand_made_outputs_cannot_overclaim(self):
        node = project(dag(), with_fcp8=False).nodes[0]
        with self.assertRaises(ValueError):
            dataclasses.replace(node, status=st.SUCCESS)
        running = project(dag(("SUCCESS", "RUNNING", "QUEUED")), status=None).node_of(wid(1))
        with self.assertRaises(ValueError):
            dataclasses.replace(running, heartbeat=st.HB_VERIFIED)
        with self.assertRaises(ValueError):
            dataclasses.replace(running, codes=(), last_heartbeat_utc=None)
        with self.assertRaises(ValueError):
            dataclasses.replace(node, native_reason=PROSE)
        unverified = project(dag(), with_fcp8=False)
        with self.assertRaises(ValueError):
            dataclasses.replace(unverified, outcome=st.SUCCESS)
        with self.assertRaises(ValueError):
            dataclasses.replace(unverified, fcp8_classification=vd.ALL_WORKERS_PROVEN)
        unknown = project(dag(), status=runner_status(dag(), success=0))
        with self.assertRaises(ValueError):
            dataclasses.replace(unknown, codes=())
        with self.assertRaises(ValueError):
            dataclasses.replace(st.project_state(None), run_id=RUN)
        with self.assertRaises(ValueError):
            dataclasses.replace(project(dag()), max_observed_concurrency=99)

    def test_canonical_json_is_exact_type_deterministic_and_bounded(self):
        summary = dag(("SUCCESS", "RUNNING", "WAITING_PROVIDER_QUOTA"))
        first = st.canonical_json(project(summary))
        self.assertEqual(first, st.canonical_json(project(summary)))
        status = runner_status(summary)
        reordered = dict(reversed(list(status.items())))
        self.assertEqual(st.canonical_json(project(summary, status=reordered)), first)
        self.assertEqual(json.loads(first)["schema"], st.SCHEMA)
        self.assertTrue(first.isascii())

        class Sub(st.StateProjection):
            pass
        with self.assertRaises(TypeError):
            st.canonical_json(Sub(**{f.name: getattr(project(summary), f.name)
                                     for f in dataclasses.fields(st.StateProjection)}))
        with self.assertRaises(TypeError):
            st.canonical_json(project(summary).to_dict())
        self.assertLess(len(st.canonical_json(project(dag(("SUCCESS",) * vd.MAX_WORKERS)))),
                        st.MAX_CANONICAL_JSON_BYTES)

    def test_projection_never_mutates_or_persists_its_inputs(self):
        summary = dag(("SUCCESS", "RUNNING", "QUEUED"))
        req = request(summary)
        before = copy.deepcopy(req)
        status_before = copy.deepcopy(req.runner_status)
        st.project_state(req)
        self.assertEqual(req, before)
        self.assertEqual(req.runner_status, status_before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            req.as_of_utc = "2027-01-01T00:00:00Z"
        p = st.project_state(req)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.outcome = st.SUCCESS

    def test_no_io_processes_network_or_execution_entry_points(self):
        req = request(dag(("SUCCESS", "RUNNING", "QUEUED")))
        boom = AssertionError("I/O or execution entry point")
        with mock.patch.object(subprocess, "Popen", side_effect=boom), \
                mock.patch.object(builtins, "open", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(Path, "read_text", side_effect=boom), \
                mock.patch.object(Path, "write_text", side_effect=boom), \
                mock.patch.object(rp, "read_pipeline_status", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom), \
                mock.patch.object(fd.FabricDirectorService, "result_blueprint", side_effect=boom), \
                mock.patch.object(fd.FabricDirectorService, "status", side_effect=boom):
            p = st.project_state(req)
        self.assertEqual(p.outcome, st.IN_PROGRESS)

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_director", "fabric_scheduler_contract", "fabric_scheduler_window", "fabric_validation_dag",
               "fabric_validation_rules", "runner_pipeline")
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "re", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "DirLease", "lease_dir", "ledger", "_launch", "_start_ready", ".now(", "utcnow", "sleep",
                     "while ", "claude", "codex", "eval(", "exec(", "importlib", "random", "stdout", "stderr",
                     ".submit", "run_blueprint", "recover(", "read_pipeline_status", "_load_json", "write_text", "_write"):
            self.assertNotIn(word, code, word)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "service"}
        self.assertEqual(calls, {"result_blueprint", "status"})

    def test_no_mutable_module_state_changes(self):
        modules = (st, vd, vr)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        project(dag(("SUCCESS", "RUNNING", "QUEUED")))
        st.project_state(None)
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_upper_snake(self):
        for vocab in (st.NODE_STATUSES, st.HEARTBEATS, st.OUTCOMES, st.REQUEST_REASONS, st.NODE_CODES, st.RUN_CODES):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z0-9_]*$")
        self.assertFalse(set(st.NODE_UNKNOWN_CODES) & set(st.NODE_UNVERIFIED_CODES))
        self.assertFalse(set(st.RUN_UNKNOWN_CODES) & set(st.RUN_INFO_CODES))
        self.assertFalse(set(st.REFUSAL_REASONS) & set(st.UNOBSERVABLE_REASONS))
        self.assertTrue(set(st.FINISHED_OUTCOMES) <= set(st.OUTCOMES))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


# ---------------------------------------------------------------------------
# Runner / Director / FCP-8 pins
# ---------------------------------------------------------------------------
class PolicyPinTests(unittest.TestCase):
    def test_native_vocabularies_are_reused_not_redefined(self):
        self.assertEqual(set(st.NATIVE_STATES), {s.value for s in _W})
        self.assertEqual(set(st.PIPELINE_STATUSES), {s.value for s in rp.PipelineStatus})
        self.assertEqual(st.RECORD_INCONSISTENCY_CODES, vd._INCONSISTENCY_CODES)
        self.assertTrue(set(st.RECORD_INCONSISTENCY_CODES) <= set(vd.WORKER_CODES))
        self.assertEqual(st.MAX_NODES, fd.blueprints.MAX_BLUEPRINT_NODES)
        self.assertEqual(st.MAX_OBSERVED_CONCURRENCY, rp.MAX_PIPELINE_WORKERS)
        self.assertEqual((st.UNKNOWN, sc.UNKNOWN), ("UNKNOWN", "UNKNOWN"))

    def test_runner_status_and_heartbeat_contract_still_matches(self):
        runner = ast.unparse(ast.parse(Path(rp.__file__).read_text(encoding="utf-8")))
        for key in ("'liveness'", "'last_heartbeat_utc'", "'max_observed_concurrency'", "'state_counts'",
                    "'started_at_utc'", "'ended_at_utc'", "'workers_total'"):
            self.assertIn(key, runner, key)
        for key, _ in st._STATUS_COUNT_KEYS:
            self.assertIn(f"'{key}': counts[", runner, key)
        self.assertEqual(rp.assess_owner(None, None, "h", None, 1.0), "UNVERIFIABLE")
        director = ast.unparse(ast.parse(Path(fd.__file__).read_text(encoding="utf-8")))
        self.assertIn("return pipeline.read_pipeline_status(self.state_root, run_id)", director)


if __name__ == "__main__":
    unittest.main()
