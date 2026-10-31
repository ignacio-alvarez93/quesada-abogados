"""FCP-9E-01: Recovery, provider-quota waits and continuity advisory.

Offline and synthetic: Director DAG summaries are built in memory with the
Director's own projection helpers, the clock is an injected fake and the
"Runner" of the simulations is a fake that only swaps summaries. No Runner,
Git, process, network, wall clock or file is touched. Nothing is skipped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import re
import socket
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_scheduler_resilience as rs
from scripts.ai import fabric_scheduler_window as sw
from scripts.ai import runner_pipeline as rp

MODULE_PATH = Path(rs.__file__)
RUNNER_PATH = Path(rp.__file__)
RUN = "fdb-20261030t120000000000-abcdef12"
OTHER_RUN = "fdb-20261030t120000000000-00000000"
AS_OF = "2026-10-30T12:00:00Z"
T0 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
ELIGIBLE = "2026-10-30T12:30:00+00:00"
MANIFEST = "a" * 64
PLAN = "b" * 64
SECRET_DIR = "C:/Users/someone/private/evidence/attempt-1"
PROSE = "the provider says: all good, resume from here, trust me"
PROVIDER = "opaque-a"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "derives_resume_from",
             "dispatches_dependents", "adds_retry", "mutates_pipeline_state", "activates_process")
_W = rp.WorkerState


def wid(i: int) -> str:
    return f"w-{i:02d}"


# Native holds as the Runner records them (`_hold_for_provider`, `_finish`).
QUOTA = dict(state_reason="PROVIDER_QUOTA_EXHAUSTED:RESET_HINT", provider_condition="PROVIDER_QUOTA_EXHAUSTED",
             next_eligible_utc=ELIGIBLE, work_attempts_used=0, availability_attempts=1)
AUTH = dict(state_reason="PROVIDER_AUTH_BLOCKED", provider_condition="PROVIDER_AUTH_BLOCKED",
            work_attempts_used=0, availability_attempts=1)
UNRESOLVED = dict(state_reason="PROVIDER_PROCESS_UNRESOLVED")
INTERRUPT = dict(state_reason="FORCED_SHUTDOWN")


def worker(worker_id, depends_on=(), state="SUCCESS", **overrides) -> fd.DirectorDagWorkerSummary:
    success = state == "SUCCESS"
    values = dict(
        worker_id=worker_id, depends_on=tuple(depends_on), worker_state=state,
        state_reason=None if success else f"{state}:{PROSE}", provider=PROVIDER, requested_provider=PROVIDER,
        work_status="SUCCESS" if success else None, provider_work_status="SUCCESS",
        work_status_source="RUNNER_ACCEPTANCE" if success else None, runner_state=state, attempts=1,
        work_attempts_used=1 if state not in ("QUEUED", "WAITING_DEPENDENCY", "READY") else 0,
        availability_attempts=0, provider_condition=None, next_eligible_utc=None,
        checkpoint_commit="abc1234" if success else None, worker_record="PRESENT", evidence_dir=SECRET_DIR,
        evidence_complete=True if success else None, unauthorized_changed_paths=(),
    )
    values.update(overrides)
    values["evidence_health"] = {True: "COMPLETE", False: "INCOMPLETE"}.get(values["evidence_complete"], "UNKNOWN")
    values["unproven_reasons"] = fd._dag_unproven_reasons(
        worker_state=values["worker_state"], work_status=values["work_status"],
        worker_record=values["worker_record"], evidence_health=values["evidence_health"],
        unauthorized=values["unauthorized_changed_paths"],
    )
    values["runner_proven_success"] = not values["unproven_reasons"]
    return fd.DirectorDagWorkerSummary(**values)


def dag(states, *, edges=None, overrides=None, pipeline_status=None, **summary_overrides):
    """Default edges: a chain w-00 <- w-01 <- ...; `edges` maps index -> deps."""
    overrides = overrides or {}
    workers = []
    for i, state in enumerate(states):
        deps = edges.get(i, ()) if edges is not None else ((i - 1,) if i else ())
        workers.append(worker(wid(i), depends_on=tuple(wid(d) for d in deps), state=state, **overrides.get(i, {})))
    workers = tuple(workers)
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
                  plan_fingerprint=PLAN, pipeline_status=pipeline_status, stop_reason=None, workers=workers,
                  aggregate_status=aggregate, aggregate_reasons=reasons)
    values.update(summary_overrides)
    return fd.DirectorDagRunSummary(**values)


def assess(summary, *, clock=None, **extra):
    values = dict(run_id=RUN, dag_summary=summary, as_of_utc=None if clock else AS_OF)
    values.update(extra)
    return rs.assess_resilience(rs.ResilienceRequest(**values), clock=clock)


class FakeClock:
    """Injected clock: returns the instant it was set to and counts calls."""

    def __init__(self, instant: datetime):
        self.instant, self.calls = instant, 0

    def __call__(self):
        self.calls += 1
        return self.instant

    def advance(self, seconds: float):
        self.instant += timedelta(seconds=seconds)


class FakeService:
    """Only `result_blueprint` exists; every other access or write fails."""

    def __init__(self, summary, *, raises=None):
        self.__dict__.update(calls=[], forbidden=[], _summary=summary, _raises=raises)

    def result_blueprint(self, run_id):
        self.calls.append(("result_blueprint", run_id))
        if self._raises is not None:
            raise self._raises
        return self._summary

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"forbidden access: {name}")

    def __setattr__(self, name, value):
        raise AssertionError(f"forbidden write: {name}")


class FakeProcess:
    """A provider process owned by the fake Runner; any use by the adapter
    is recorded."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.__dict__.setdefault("touched", []).append(name)
        raise AssertionError(f"process touched: {name}")


class FakeRunner:
    """The ONLY component that advances state in the simulations: it swaps
    the summary the fake Director returns, exactly as the real Runner's
    `_refresh` / `_finish` would."""

    def __init__(self, summary):
        self.summary, self.transitions, self.process = summary, [], FakeProcess()

    def service(self):
        runner = self

        class _Service:
            def result_blueprint(self, run_id):
                return runner.summary

        return _Service()

    def advance(self, summary, label):
        self.transitions.append(label)
        self.summary = summary


def _module_code() -> str:
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def _assert_no_authority(test, assessment):
    for flag in ALL_FLAGS:
        test.assertIs(getattr(assessment, flag), False, flag)
        test.assertIs(assessment.to_dict()[flag], False, flag)


# ---------------------------------------------------------------------------
# Vocabulary pinned to the Runner
# ---------------------------------------------------------------------------
class RunnerVocabularyTests(unittest.TestCase):
    def test_the_five_runner_holds_are_reused_with_their_exact_runner_names(self):
        source = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertEqual(rs.WAITING_PROVIDER_QUOTA, _W.WAITING_PROVIDER_QUOTA.value)
        self.assertEqual(rs.BLOCKED_PROVIDER_AUTH, _W.BLOCKED_PROVIDER_AUTH.value)
        self.assertEqual(rs.INTERRUPTED, _W.INTERRUPTED.value)
        self.assertIn('"decision": "PROCESS_UNRESOLVED"', source)
        self.assertIn(f'_transition(rt, WorkerState.BLOCKED, "{rs.PROCESS_UNRESOLVED_NATIVE_REASON}")', source)
        self.assertIn('_enter_draining("DEADLINE_REACHED")', source)
        self.assertEqual(rs.RUNNER_HOLD_REASONS, ("PROCESS_UNRESOLVED", "BLOCKED_PROVIDER_AUTH", "INTERRUPTED",
                                                  "DEADLINE_REACHED", "WAITING_PROVIDER_QUOTA"))

    def test_runner_stop_reasons_are_exactly_the_literals_the_runner_assigns(self):
        source = RUNNER_PATH.read_text(encoding="utf-8")
        literals = set(re.findall(r'_stop_reason = "([A-Z_]+)"', source))
        literals |= set(re.findall(r'_enter_draining\("([A-Z_]+)"\)', source))
        self.assertEqual(set(rs.RUNNER_STOP_REASONS), literals)

    def test_budget_classes_mirror_the_runner_and_cover_every_native_state(self):
        self.assertEqual((rs.BUDGET_WORK, rs.BUDGET_PROVIDER_AVAILABILITY), (rp.BUDGET_WORK,
                                                                             rp.BUDGET_PROVIDER_AVAILABILITY))
        classes = {s.value: rs.budget_class_for(s.value) for s in _W}
        self.assertEqual({s for s, c in classes.items() if c == rs.BUDGET_PROVIDER_AVAILABILITY},
                         {"WAITING_PROVIDER_QUOTA", "BLOCKED_PROVIDER_AUTH"})
        self.assertEqual({s for s, c in classes.items() if c == rs.BUDGET_WORK}, {"RETRY_WAIT", "FAILED", "PARTIAL"})
        self.assertEqual(rs.budget_class_for(None), rs.BUDGET_NOT_APPLICABLE)

    def test_every_reason_has_a_rule_and_every_action_a_single_actor(self):
        self.assertEqual(tuple(rs.REASON_RULES), rs.REASONS)
        self.assertEqual(set(rs.ACTOR_OF_ACTION), set(rs.ACTIONS))
        self.assertTrue(set(rs.ACTOR_OF_ACTION.values()) <= set(rs.ACTORS))
        used = {a for _, actions in rs.REASON_RULES.values() for a in actions}
        self.assertEqual(used, set(rs.ACTIONS))
        for reason in rs.RUNNER_HOLD_REASONS[:4]:
            self.assertTrue(all(rs.ACTOR_OF_ACTION[a] == rs.ACTOR_HUMAN for a in rs.REASON_RULES[reason][1]))
        self.assertTrue(all(rs.ACTOR_OF_ACTION[a] == rs.ACTOR_RUNNER
                            for a in rs.REASON_RULES[rs.WAITING_PROVIDER_QUOTA][1]))


# ---------------------------------------------------------------------------
# Provider quota: availability, not work failure
# ---------------------------------------------------------------------------
class QuotaWaitTests(unittest.TestCase):
    def test_quota_wait_before_eligibility_is_a_runner_owned_wait(self):
        a = assess(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: QUOTA},
                       stop_reason="WAITING_PROVIDER_QUOTA"))
        node = a.node_of(wid(1))
        self.assertEqual((a.outcome, a.operational_reason, a.next_action, a.actor),
                         (rs.WAITING_PROVIDER_QUOTA, rs.WAITING_PROVIDER_QUOTA, rs.AWAIT_PROVIDER_QUOTA_RECOVERY,
                          rs.ACTOR_RUNNER))
        self.assertEqual((node.category, node.next_eligible_utc, node.seconds_until_eligible),
                         (rs.CATEGORY_AVAILABILITY, "2026-10-30T12:30:00Z", 1800))
        self.assertEqual(a.earliest_quota_eligible_utc, "2026-10-30T12:30:00Z")
        self.assertFalse(a.human_action_required)
        _assert_no_authority(self, a)

    def test_quota_eligibility_reached_only_points_to_the_runner_reevaluation(self):
        clock = FakeClock(datetime(2026, 10, 30, 12, 30, tzinfo=timezone.utc))
        a = assess(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: QUOTA}), clock=clock)
        node = a.node_of(wid(1))
        self.assertEqual((node.reason, node.next_action, node.seconds_until_eligible),
                         (rs.WAITING_PROVIDER_QUOTA, rs.OBSERVE_RUNNER_QUOTA_REEVALUATION, 0))
        self.assertIn(rs.QUOTA_ELIGIBILITY_REACHED, node.codes)
        self.assertEqual(a.outcome, rs.WAITING_PROVIDER_QUOTA)
        self.assertIs(a.dispatch_allowed, False)
        self.assertIs(a.auto_retry_allowed, False)
        self.assertNotEqual(node.native_state, _W.READY.value)

    def test_availability_holds_never_consume_max_attempts_but_work_failures_do(self):
        a = assess(dag(("WAITING_PROVIDER_QUOTA", "BLOCKED_PROVIDER_AUTH", "RETRY_WAIT", "FAILED"),
                       edges={}, overrides={0: QUOTA, 1: AUTH}))
        by_id = {n.node_id: n for n in a.nodes}
        for i in (0, 1):
            self.assertEqual(by_id[wid(i)].budget_class, rs.BUDGET_PROVIDER_AVAILABILITY)
            self.assertIs(by_id[wid(i)].consumes_max_attempts, False)
            self.assertEqual((by_id[wid(i)].work_attempts_used, by_id[wid(i)].availability_attempts), (0, 1))
        for i in (2, 3):
            self.assertEqual(by_id[wid(i)].budget_class, rs.BUDGET_WORK)
            self.assertIs(by_id[wid(i)].consumes_max_attempts, True)
        self.assertEqual(by_id[wid(2)].reason, rs.TRANSIENT_RETRY_WAIT)
        self.assertEqual(by_id[wid(2)].next_action, rs.OBSERVE_RUNNER_RETRY)
        self.assertEqual(by_id[wid(3)].reason, rs.WORK_NOT_SUCCESSFUL)

    def test_quota_wait_without_eligibility_instant_fails_closed(self):
        for bad in (None, "tomorrow-ish", "2026-10-30T12:30:00"):
            with self.subTest(next_eligible_utc=bad):
                a = assess(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"),
                               overrides={1: {**QUOTA, "next_eligible_utc": bad}}))
                node = a.node_of(wid(1))
                self.assertEqual((a.outcome, node.reason), (rs.UNKNOWN, rs.UNKNOWN_STATE))
                self.assertIn(rs.QUOTA_ELIGIBILITY_UNKNOWN, node.codes)
                self.assertIsNone(node.next_eligible_utc)
                self.assertIn(rs.NODE_UNKNOWN, a.codes)

    def test_quota_wait_with_a_contradicting_provider_condition_fails_closed(self):
        for condition in (None, "PROVIDER_AUTH_BLOCKED", "QUOTA_PROSE"):
            with self.subTest(condition=condition):
                a = assess(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"),
                               overrides={1: {**QUOTA, "provider_condition": condition}}))
                self.assertEqual(a.outcome, rs.UNKNOWN)
                self.assertIn(rs.PROVIDER_CONDITION_MISMATCH, a.node_of(wid(1)).codes)

    def test_availability_hold_accounted_as_work_fails_closed(self):
        for counts in ({"availability_attempts": 0}, {"availability_attempts": None}, {"work_attempts_used": None},
                       {"availability_attempts": True}, {"work_attempts_used": -1}):
            with self.subTest(counts=counts):
                a = assess(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: {**QUOTA, **counts}}))
                node = a.node_of(wid(1))
                self.assertEqual(node.reason, rs.UNKNOWN_STATE)
                self.assertIn(rs.ATTEMPT_ACCOUNTING_INCONSISTENT, node.codes)


# ---------------------------------------------------------------------------
# Auth, interruption, unresolved process, deadline
# ---------------------------------------------------------------------------
class ContinuityHoldTests(unittest.TestCase):
    def test_auth_block_requires_a_human_and_holds_dependents_on_that_human(self):
        a = assess(dag(("BLOCKED_PROVIDER_AUTH", "QUEUED", "WAITING_DEPENDENCY"), overrides={0: AUTH},
                       stop_reason="PROVIDER_AUTH_BLOCKED"))
        self.assertEqual((a.outcome, a.operational_reason, a.next_action, a.actor),
                         (rs.HUMAN_ACTION_REQUIRED, rs.BLOCKED_PROVIDER_AUTH, rs.RESTORE_PROVIDER_AUTH, rs.ACTOR_HUMAN))
        for i in (1, 2):
            node = a.node_of(wid(i))
            self.assertEqual((node.reason, node.next_action, node.held_by),
                             (rs.DEPENDENCY_HELD, rs.RESOLVE_UPSTREAM_HOLD, (wid(i - 1),)))
            self.assertIn(rs.UPSTREAM_REQUIRES_HUMAN, node.codes)
        self.assertEqual(a.held_dependents, (wid(1), wid(2)))

    def test_auth_block_with_a_contradicting_condition_fails_closed(self):
        a = assess(dag(("SUCCESS", "BLOCKED_PROVIDER_AUTH"),
                       overrides={1: {**AUTH, "provider_condition": "PROVIDER_QUOTA_EXHAUSTED"}}))
        self.assertEqual(a.outcome, rs.UNKNOWN)
        self.assertIn(rs.PROVIDER_CONDITION_MISMATCH, a.node_of(wid(1)).codes)

    def test_interrupted_on_a_clean_worktree_is_a_human_review_never_a_resume(self):
        a = assess(dag(("INTERRUPTED", "QUEUED"), overrides={0: INTERRUPT}, stop_reason="FORCED_SHUTDOWN"),
                   worktree_state=rs.WORKTREE_CLEAN)
        node = a.node_of(wid(0))
        self.assertEqual((node.reason, node.next_action, node.codes), (rs.INTERRUPTED, rs.REVIEW_INTERRUPTED_WORK, ()))
        self.assertEqual(a.outcome, rs.HUMAN_ACTION_REQUIRED)
        self.assertIs(a.resume_allowed, False)
        self.assertIs(a.derives_resume_from, False)

    def test_no_resume_is_ever_derived_from_a_dirty_worktree(self):
        a = assess(dag(("SUCCESS", "INTERRUPTED"), overrides={1: {**INTERRUPT, "evidence_dir": SECRET_DIR}}),
                   worktree_state=rs.WORKTREE_DIRTY)
        node = a.node_of(wid(1))
        self.assertEqual(node.next_action, rs.REVIEW_DIRTY_WORKTREE)
        self.assertIn(rs.WORKTREE_DIRTY_NO_DERIVED_RESUME, node.codes)
        text = rs.canonical_json(a)
        self.assertNotIn("resume_from\"", text.replace("derives_resume_from\"", ""))
        self.assertNotIn("work_product", text)
        self.assertNotIn("private", text)
        self.assertEqual(json.loads(text)["derives_resume_from"], False)

    def test_unobserved_worktree_is_flagged_never_assumed_clean(self):
        a = assess(dag(("SUCCESS", "INTERRUPTED"), overrides={1: INTERRUPT}))
        node = a.node_of(wid(1))
        self.assertEqual((a.worktree_state, node.next_action), (rs.WORKTREE_UNKNOWN, rs.REVIEW_INTERRUPTED_WORK))
        self.assertIn(rs.WORKTREE_STATE_UNOBSERVED, node.codes)

    def test_process_unresolved_outranks_every_other_hold_and_holds_dependents(self):
        a = assess(dag(("BLOCKED_PROVIDER_AUTH", "BLOCKED", "QUEUED", "CANCELLED"), edges={2: (1,), 3: (1,)},
                       overrides={0: AUTH, 1: UNRESOLVED}))
        self.assertEqual((a.operational_reason, a.next_action, a.outcome),
                         (rs.PROCESS_UNRESOLVED, rs.CONFIRM_PROVIDER_PROCESS_STOPPED, rs.HUMAN_ACTION_REQUIRED))
        self.assertEqual(a.node_of(wid(1)).category, rs.CATEGORY_CONTINUITY)
        self.assertEqual(a.node_of(wid(2)).reason, rs.DEPENDENCY_HELD)
        self.assertEqual(a.node_of(wid(3)).reason, rs.CANCELLED)

    def test_an_ordinary_native_block_is_work_not_an_unresolved_process(self):
        a = assess(dag(("SUCCESS", "BLOCKED"), overrides={1: {"state_reason": "CHECKPOINT_FAILED: tree dirty"}}))
        node = a.node_of(wid(1))
        self.assertEqual((node.reason, node.next_action), (rs.WORK_NOT_SUCCESSFUL, rs.REVIEW_WORK_OUTCOME))
        self.assertEqual(a.outcome, rs.SETTLED)

    def test_runner_deadline_stops_everything_not_running_but_keeps_availability_accounting(self):
        a = assess(dag(("RUNNING", "WAITING_PROVIDER_QUOTA", "QUEUED", "RETRY_WAIT"), edges={2: (0,)},
                       overrides={1: QUOTA}, pipeline_status="DRAINING", stop_reason="DEADLINE_REACHED"))
        self.assertIn(rs.DEADLINE_REACHED_BY_RUNNER, a.codes)
        self.assertEqual(a.node_of(wid(0)).reason, rs.RUNNING)
        for i in (1, 2, 3):
            node = a.node_of(wid(i))
            self.assertEqual((node.reason, node.next_action), (rs.DEADLINE_REACHED, rs.DECIDE_NEW_EXECUTION_WINDOW))
            self.assertIsNone(node.next_eligible_utc)
        self.assertEqual(a.node_of(wid(1)).budget_class, rs.BUDGET_PROVIDER_AVAILABILITY)
        self.assertEqual((a.outcome, a.operational_reason), (rs.HUMAN_ACTION_REQUIRED, rs.DEADLINE_REACHED))
        self.assertIsNone(a.earliest_quota_eligible_utc)

    def test_window_deadline_is_evaluated_with_the_injected_clock_inclusively(self):
        window = sw.ExecutionWindow(None, "2026-10-30T13:00:00Z")
        summary = dag(("SUCCESS", "QUEUED"))
        before = assess(summary, clock=FakeClock(datetime(2026, 10, 30, 12, 59, 59, tzinfo=timezone.utc)),
                        window=window)
        at = assess(summary, clock=FakeClock(datetime(2026, 10, 30, 13, 0, 0, tzinfo=timezone.utc)), window=window)
        self.assertEqual(before.node_of(wid(1)).reason, rs.PENDING)
        self.assertEqual(before.outcome, rs.IN_PROGRESS)
        self.assertEqual(at.node_of(wid(1)).reason, rs.DEADLINE_REACHED)
        self.assertIn(rs.DEADLINE_PASSED_PER_WINDOW, at.codes)
        self.assertNotIn(rs.DEADLINE_REACHED_BY_RUNNER, at.codes)

    def test_window_not_yet_open_is_informational_only(self):
        a = assess(dag(("QUEUED", "QUEUED")), window=sw.ExecutionWindow("2026-10-30T13:00:00Z", None))
        self.assertIn(rs.WINDOW_NOT_OPEN, a.codes)
        self.assertEqual((a.outcome, a.node_of(wid(1)).reason), (rs.IN_PROGRESS, rs.PENDING))


# ---------------------------------------------------------------------------
# Dependents never fire on a hold
# ---------------------------------------------------------------------------
class DependentHoldTests(unittest.TestCase):
    def test_holds_propagate_transitively_naming_only_direct_held_dependencies(self):
        a = assess(dag(("WAITING_PROVIDER_QUOTA", "QUEUED", "QUEUED", "WAITING_DEPENDENCY"), overrides={0: QUOTA}))
        for i in (1, 2, 3):
            node = a.node_of(wid(i))
            self.assertEqual((node.reason, node.next_action, node.held_by),
                             (rs.DEPENDENCY_HELD, rs.AWAIT_UPSTREAM, (wid(i - 1),)))
            self.assertNotIn(rs.UPSTREAM_REQUIRES_HUMAN, node.codes)
        self.assertEqual(a.outcome, rs.WAITING_PROVIDER_QUOTA)

    def test_human_requirement_propagates_through_a_diamond(self):
        a = assess(dag(("SUCCESS", "INTERRUPTED", "QUEUED", "QUEUED"), edges={1: (0,), 2: (0,), 3: (1, 2)},
                       overrides={1: INTERRUPT}))
        self.assertEqual(a.node_of(wid(2)).reason, rs.PENDING)
        node = a.node_of(wid(3))
        self.assertEqual((node.reason, node.next_action, node.held_by),
                         (rs.DEPENDENCY_HELD, rs.RESOLVE_UPSTREAM_HOLD, (wid(1),)))

    def test_dependents_of_progressing_or_finished_upstreams_are_not_held(self):
        for upstream in ("SUCCESS", "RETRY_WAIT", "RUNNING", "FAILED"):
            with self.subTest(upstream=upstream):
                a = assess(dag((upstream, "QUEUED")))
                node = a.node_of(wid(1))
                self.assertEqual((node.reason, node.held_by, node.next_action), (rs.PENDING, (), rs.OBSERVE_RUNNER))

    def test_a_dependent_that_advanced_past_a_never_releasing_hold_is_unknown(self):
        cases = (("WAITING_PROVIDER_QUOTA", QUOTA, "RUNNING"), ("BLOCKED_PROVIDER_AUTH", AUTH, "SUCCESS"),
                 ("INTERRUPTED", INTERRUPT, "FAILED"), ("BLOCKED", UNRESOLVED, "RUNNING"))
        for upstream, values, dependent in cases:
            with self.subTest(upstream=upstream, dependent=dependent):
                a = assess(dag((upstream, dependent), overrides={0: values}))
                node = a.node_of(wid(1))
                self.assertEqual((node.reason, a.outcome), (rs.UNKNOWN_STATE, rs.UNKNOWN))
                self.assertIn(rs.DEPENDENT_ADVANCED_PAST_HOLD, node.codes)
                self.assertEqual(a.next_action, rs.REVIEW_STATE_INTEGRITY)

    def test_dependents_of_an_unknown_node_are_held(self):
        a = assess(dag(("WAITING_PROVIDER_QUOTA", "QUEUED"), overrides={0: {**QUOTA, "next_eligible_utc": None}}))
        node = a.node_of(wid(1))
        self.assertEqual((node.reason, node.next_action), (rs.DEPENDENCY_HELD, rs.RESOLVE_UPSTREAM_HOLD))


# ---------------------------------------------------------------------------
# Injected clock and simulated recovery
# ---------------------------------------------------------------------------
class ClockAndSimulationTests(unittest.TestCase):
    def test_injected_clock_is_called_exactly_once_and_matches_as_of(self):
        summary = dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: QUOTA})
        clock = FakeClock(T0)
        via_clock = assess(summary, clock=clock)
        self.assertEqual(clock.calls, 1)
        self.assertEqual(rs.canonical_json(via_clock), rs.canonical_json(assess(summary)))

    def test_instant_sources_are_refused_fail_closed(self):
        summary = dag(("SUCCESS",))
        cases = (
            (dict(as_of_utc=AS_OF), FakeClock(T0), rs.AS_OF_SOURCE_INVALID),
            (dict(as_of_utc=None), None, rs.AS_OF_SOURCE_INVALID),
            (dict(as_of_utc=None), mock.Mock(side_effect=RuntimeError("no clock")), rs.CLOCK_UNAVAILABLE),
            (dict(as_of_utc=None), "not-callable", rs.CLOCK_UNAVAILABLE),
            (dict(as_of_utc=None), lambda: datetime(2026, 10, 30, 12, 0), rs.AS_OF_INVALID),
            (dict(as_of_utc="2026-10-30 12:00:00"), None, rs.AS_OF_INVALID),
            (dict(as_of_utc=AS_OF, window=sw.ExecutionWindow("2026-10-30T14:00:00Z", "2026-10-30T13:00:00Z")),
             None, rs.WINDOW_INVALID),
        )
        for extra, clock, code in cases:
            with self.subTest(code=code, extra=extra):
                request = rs.ResilienceRequest(run_id=RUN, dag_summary=summary, **extra)
                a = rs.assess_resilience(request, clock=clock)
                self.assertEqual((a.outcome, a.request_reasons), (rs.REFUSED, (code,)))
                self.assertEqual((a.nodes, a.codes, a.run_id, a.next_action), ((), (), None, None))

    def test_simulated_quota_recovery_is_driven_only_by_the_fake_runner(self):
        quota = dag(("SUCCESS", "WAITING_PROVIDER_QUOTA", "QUEUED"), overrides={1: QUOTA},
                    stop_reason="WAITING_PROVIDER_QUOTA")
        runner, clock = FakeRunner(quota), FakeClock(T0)
        service = runner.service()
        timeline = []
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")) as popen, \
                mock.patch.object(os, "kill", side_effect=AssertionError("kill")) as kill:
            for _ in range(3):  # waiting: 12:00, 12:15, 12:30 (eligible)
                timeline.append(rs.observe_resilience(service, RUN, clock=clock))
                clock.advance(900)
            self.assertEqual(runner.transitions, [])
            runner.advance(dag(("SUCCESS", "RUNNING", "QUEUED"), overrides={1: {**QUOTA, "next_eligible_utc": None,
                                                                                 "state_reason": None}}),
                           "PROVIDER_QUOTA_ELIGIBLE->RUNNING")
            timeline.append(rs.observe_resilience(service, RUN, clock=clock))
            runner.advance(dag(("SUCCESS", "SUCCESS", "SUCCESS"), overrides={1: {"availability_attempts": 1}}),
                           "SUCCESS")
            timeline.append(rs.observe_resilience(service, RUN, clock=clock))
        popen.assert_not_called()
        kill.assert_not_called()
        self.assertEqual(runner.process.touched, [])
        self.assertEqual([a.next_action for a in timeline],
                         [rs.AWAIT_PROVIDER_QUOTA_RECOVERY, rs.AWAIT_PROVIDER_QUOTA_RECOVERY,
                          rs.OBSERVE_RUNNER_QUOTA_REEVALUATION, rs.OBSERVE_RUNNER, rs.NO_ACTION])
        self.assertEqual([a.outcome for a in timeline],
                         [rs.WAITING_PROVIDER_QUOTA] * 3 + [rs.IN_PROGRESS, rs.SETTLED])
        self.assertEqual([a.node_of(wid(1)).seconds_until_eligible for a in timeline[:3]], [1800, 900, 0])
        self.assertTrue(all(a.node_of(wid(2)).reason == rs.DEPENDENCY_HELD for a in timeline[:3]))
        self.assertEqual(timeline[3].node_of(wid(2)).reason, rs.PENDING)
        self.assertEqual({a.node_of(wid(1)).work_attempts_used for a in timeline[:3]}, {0})
        self.assertEqual(runner.transitions, ["PROVIDER_QUOTA_ELIGIBLE->RUNNING", "SUCCESS"])
        for a in timeline:
            _assert_no_authority(self, a)

    def test_simulated_forced_shutdown_never_automates_the_requeue(self):
        runner, clock = FakeRunner(dag(("INTERRUPTED", "QUEUED"), overrides={0: INTERRUPT},
                                       stop_reason="FORCED_SHUTDOWN")), FakeClock(T0)
        seen = []
        for _ in range(4):
            seen.append(rs.observe_resilience(runner.service(), RUN, clock=clock, worktree_state=rs.WORKTREE_DIRTY))
            clock.advance(86400)
        self.assertEqual(runner.transitions, [])
        self.assertEqual({(a.outcome, a.next_action) for a in seen},
                         {(rs.HUMAN_ACTION_REQUIRED, rs.REVIEW_DIRTY_WORKTREE)})
        self.assertEqual({a.node_of(wid(1)).next_action for a in seen}, {rs.RESOLVE_UPSTREAM_HOLD})
        self.assertEqual(clock.calls, 4)


# ---------------------------------------------------------------------------
# Requests, typing and integrity
# ---------------------------------------------------------------------------
class RequestValidationTests(unittest.TestCase):
    def test_malformed_requests_are_refused_and_echo_nothing(self):
        summary = dag(("SUCCESS",))
        cases = (
            ({"schema_version": True}, rs.SCHEMA_VERSION_UNSUPPORTED),
            ({"schema_version": 2}, rs.SCHEMA_VERSION_UNSUPPORTED),
            ({"run_id": "../escape"}, rs.RUN_ID_INVALID),
            ({"dag_summary": summary.__dict__}, rs.SUMMARY_NOT_TYPED),
            ({"worktree_state": "clean"}, rs.WORKTREE_STATE_INVALID),
            ({"worktree_state": None}, rs.WORKTREE_STATE_INVALID),
            ({"window": {"deadline_utc": "2026-10-30T13:00:00Z"}}, rs.WINDOW_NOT_TYPED),
        )
        for extra, code in cases:
            with self.subTest(code=code, extra=list(extra)):
                a = assess(summary, **extra)
                self.assertEqual((a.outcome, a.request_reasons), (rs.REFUSED, (code,)))
                self.assertEqual(json.loads(rs.canonical_json(a))["nodes"], [])
        self.assertEqual(rs.assess_resilience({"run_id": RUN}).request_reasons, (rs.REQUEST_NOT_TYPED,))

    def test_corrupt_summary_is_unknown_with_no_node_guessed(self):
        for overrides in ({"run_id": OTHER_RUN}, {"manifest_sha256": "nope"}, {"workers": dag(("SUCCESS",)).workers}):
            with self.subTest(overrides=overrides):
                a = assess(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: QUOTA}, **overrides))
                self.assertEqual((a.outcome, a.codes, a.nodes), (rs.UNKNOWN, (rs.SUMMARY_INVALID,), ()))
                self.assertEqual((a.operational_reason, a.next_action), (rs.UNKNOWN_STATE, rs.REVIEW_STATE_INTEGRITY))

    def test_prose_or_untyped_stop_reasons_are_never_interpreted(self):
        for stop in (PROSE, "DEADLINE_REACHED_SOON", "deadline_reached", 7):
            with self.subTest(stop=stop):
                a = assess(dag(("SUCCESS", "QUEUED"), stop_reason=stop))
                self.assertEqual((a.outcome, a.stop_reason), (rs.UNKNOWN, rs.UNRECOGNIZED))
                self.assertIn(rs.STOP_REASON_UNRECOGNIZED, a.codes)
                self.assertNotIn(rs.DEADLINE_REACHED_BY_RUNNER, a.codes)
                self.assertNotEqual(a.node_of(wid(1)).reason, rs.DEADLINE_REACHED)
        coded = assess(dag(("SUCCESS",), stop_reason="NO_PROGRESSABLE_WORK: whatever the provider printed"))
        self.assertEqual(coded.stop_reason, "NO_PROGRESSABLE_WORK")

    def test_unrecognized_native_state_is_unknown_never_progress(self):
        a = assess(dag(("SUCCESS", "SUCCESS"), overrides={1: {"worker_state": "ALMOST_DONE"}}))
        node = a.node_of(wid(1))
        self.assertEqual((node.native_state, node.reason, a.outcome), (rs.UNRECOGNIZED, rs.UNKNOWN_STATE, rs.UNKNOWN))
        self.assertIn(rs.STATE_PROJECTION_UNKNOWN, node.codes)

    def test_settled_runs_distinguish_completed_from_unsuccessful_work(self):
        done = assess(dag(("SUCCESS", "SUCCESS")))
        self.assertEqual((done.outcome, done.operational_reason, done.next_action, done.actor),
                         (rs.SETTLED, rs.COMPLETED, rs.NO_ACTION, rs.ACTOR_NONE))
        failed = assess(dag(("SUCCESS", "FAILED", "CANCELLED"),
                            overrides={1: {"state_reason": "MAX_ATTEMPTS_EXHAUSTED"},
                                       2: {"state_reason": "DEPENDENCY_UNSATISFIED:w-01=FAILED"}}))
        self.assertEqual((failed.outcome, failed.operational_reason, failed.next_action),
                         (rs.SETTLED, rs.WORK_NOT_SUCCESSFUL, rs.REVIEW_WORK_OUTCOME))
        self.assertTrue(failed.human_action_required)
        self.assertIs(failed.certified, False)

    def test_bounds_hold_for_the_largest_dag(self):
        self.assertEqual(rs.MAX_NODES, 64)
        states = ("WAITING_PROVIDER_QUOTA",) + ("QUEUED",) * (rs.MAX_NODES - 1)
        a = assess(dag(states, overrides={0: QUOTA}))
        self.assertEqual(len(a.nodes), rs.MAX_NODES)
        self.assertEqual(len(a.held_dependents), rs.MAX_NODES - 1)
        self.assertLessEqual(len(rs.canonical_json(a)), rs.MAX_CANONICAL_JSON_BYTES)


# ---------------------------------------------------------------------------
# Authority, purity, determinism
# ---------------------------------------------------------------------------
class AuthorityAndPurityTests(unittest.TestCase):
    def test_zero_authority_flags_are_read_only_and_unforgeable(self):
        a = assess(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: QUOTA}))
        _assert_no_authority(self, a)
        for flag in ALL_FLAGS:
            with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
                setattr(a, flag, True)
            with self.assertRaises(TypeError):
                dataclasses.replace(a, **{flag: True})
        self.assertNotIn("dispatch_allowed", {f.name for f in dataclasses.fields(rs.ResilienceAssessment)})

    def test_hand_made_nodes_and_assessments_cannot_overclaim(self):
        good = assess(dag(("WAITING_PROVIDER_QUOTA", "QUEUED"), overrides={0: QUOTA}))
        quota = good.node_of(wid(0))
        forged = (
            dict(next_action=rs.NO_ACTION),
            dict(reason=rs.COMPLETED),
            dict(seconds_until_eligible=0),
            dict(availability_attempts=0),
            dict(codes=(rs.QUOTA_ELIGIBILITY_REACHED,)),
            dict(held_by=(wid(9),)),
        )
        for change in forged:
            with self.subTest(change=change), self.assertRaises(ValueError):
                dataclasses.replace(quota, **change)
        with self.assertRaises(ValueError):
            dataclasses.replace(good.node_of(wid(1)), held_by=())
        for change in (dict(outcome=rs.SETTLED), dict(outcome=rs.IN_PROGRESS), dict(next_action=rs.NO_ACTION),
                       dict(operational_reason=rs.COMPLETED), dict(earliest_quota_eligible_utc=None),
                       dict(codes=(rs.DEADLINE_REACHED_BY_RUNNER,)), dict(request_reasons=(rs.READ_FAILED,))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                dataclasses.replace(good, **change)

    def test_assessment_never_mutates_its_input(self):
        summary = dag(("BLOCKED_PROVIDER_AUTH", "QUEUED"), overrides={0: AUTH})
        snapshot = copy.deepcopy(summary)
        window = sw.ExecutionWindow(None, "2026-10-30T13:00:00Z")
        request = rs.ResilienceRequest(run_id=RUN, dag_summary=summary, as_of_utc=AS_OF, window=window)
        rs.assess_resilience(request)
        self.assertEqual(summary, snapshot)
        self.assertEqual(request.window, sw.ExecutionWindow(None, "2026-10-30T13:00:00Z"))

    def test_assessment_is_deterministic_and_canonical_json_is_exact_type_only(self):
        summary = dag(("WAITING_PROVIDER_QUOTA", "INTERRUPTED", "QUEUED"), edges={2: (0, 1)},
                      overrides={0: QUOTA, 1: INTERRUPT})
        first, second = assess(summary), assess(copy.deepcopy(summary))
        self.assertEqual(rs.canonical_json(first), rs.canonical_json(second))
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertRegex(first.fingerprint, r"^[0-9a-f]{64}$")

        class Sub(rs.ResilienceAssessment):
            pass

        with self.assertRaises(TypeError):
            rs.canonical_json(Sub(**{f.name: getattr(first, f.name) for f in dataclasses.fields(first)}))

    def test_output_carries_no_provider_path_prose_or_secret(self):
        summary = dag(("WAITING_PROVIDER_QUOTA", "FAILED"), edges={},
                      overrides={0: QUOTA, 1: {"state_reason": f"FAILED: token=sk-abcdef123456 {PROSE}"}})
        text = rs.canonical_json(assess(summary))
        for needle in (PROVIDER, SECRET_DIR, "private", "trust me", "sk-abcdef", "bp-private", MANIFEST):
            self.assertNotIn(needle, text)

    def test_observe_reads_result_blueprint_exactly_once_and_nothing_else(self):
        service = FakeService(dag(("SUCCESS", "WAITING_PROVIDER_QUOTA"), overrides={1: QUOTA}))
        a = rs.observe_resilience(service, RUN, as_of_utc=AS_OF)
        self.assertEqual(service.calls, [("result_blueprint", RUN)])
        self.assertEqual(service.forbidden, [])
        self.assertEqual(a.outcome, rs.WAITING_PROVIDER_QUOTA)
        refused = FakeService(None)
        self.assertEqual(rs.observe_resilience(refused, "bad/id", as_of_utc=AS_OF).request_reasons,
                         (rs.RUN_ID_INVALID,))
        self.assertEqual(refused.calls, [])

    def test_observe_read_failures_are_unobservable_never_progress(self):
        cases = ((fd.DirectorError("DAG_PROVENANCE_MISMATCH", "x"), rs.PROVENANCE_REFUSED),
                 (fd.DirectorError("PIPELINE_NOT_FOUND", "x"), rs.READ_FAILED), (OSError("disk"), rs.READ_FAILED))
        for exc, code in cases:
            with self.subTest(code=code):
                a = rs.observe_resilience(FakeService(None, raises=exc), RUN, as_of_utc=AS_OF)
                self.assertEqual((a.outcome, a.request_reasons, a.nodes), (rs.UNOBSERVABLE, (code,), ()))
                _assert_no_authority(self, a)

    def test_assessment_touches_no_process_file_socket_or_wall_clock(self):
        summary = dag(("BLOCKED", "QUEUED"), overrides={0: UNRESOLVED})
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("Popen")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("run")), \
                mock.patch.object(os, "kill", side_effect=AssertionError("kill")), \
                mock.patch.object(os, "system", side_effect=AssertionError("system")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("socket")), \
                mock.patch.object(builtins, "open", side_effect=AssertionError("open")):
            a = assess(summary, clock=FakeClock(T0))
        self.assertEqual(a.operational_reason, rs.PROCESS_UNRESOLVED)

    def test_module_imports_and_calls_stay_inside_the_advisory_boundary(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
                imported |= {f"{node.module}.{a.name}" for a in node.names if node.module == "scripts.ai"}
        self.assertTrue(imported <= {"__future__", "hashlib", "dataclasses", "datetime", "typing", "scripts",
                                     "fabric_director", "fabric_scheduler_contract", "fabric_scheduler_state",
                                     "fabric_scheduler_window", "runner_pipeline", "scripts.ai.fabric_director",
                                     "scripts.ai.fabric_scheduler_contract", "scripts.ai.fabric_scheduler_state",
                                     "scripts.ai.fabric_scheduler_window", "scripts.ai.runner_pipeline"}, imported)
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        forbidden = {"submit", "submit_blueprint", "submit_and_run", "run_blueprint", "run", "recover", "status",
                     "requeue", "rerun", "create_checkpoint", "execute_work_order", "evaluate_resume", "now",
                     "sleep", "Popen", "kill", "write_text", "open", "acquire", "release", "_transition"}
        self.assertEqual(called & forbidden, set())
        code = _module_code()
        for token in ("datetime.now", "time.time", "os.environ", "subprocess", "threading", "pending_resume_from"):
            self.assertNotIn(token, code)


if __name__ == "__main__":
    unittest.main()
