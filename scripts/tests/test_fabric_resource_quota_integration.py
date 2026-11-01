"""FCP-10D-02: end-to-end integration of the FCP-10 Resource / Quota Manager.

One synthetic evidence set flows through every real stage, each consuming the
previous stage's native types exactly as is: FCP-10A-02 `adapt_observations`
(adapter) -> FCP-10B-01 `evaluate_resources` (over the real FCP-9C-01
`evaluate_capacity` plan) -> FCP-10B-02 `evaluate_budget` -> FCP-10C-01
`allocate` -> FCP-10C-02 `advise_recovery` -> FCP-10D-01 report (in memory and
through its real CLI over a file in a private temporary directory). Quota /
auth holds are produced by the real `PipelineRunner._hold_for_provider` (only
its persistence is replaced by an in-memory host) and worker diagnostics by
the real FCP-6 `assess_worker`, through the existing FCP-10 test fixtures.
Nothing calls an AI provider, a network, a process or Git; nothing is
dispatched, retried, reserved, bought or committed. Also pins the single
additive FCP-10 CI step. Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import copy
import io
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.ai import fabric_resource_quota_allocation as al
from scripts.ai import fabric_resource_quota_budget as bg
from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_resource_quota_observation as qo
from scripts.ai import fabric_resource_quota_recovery as rq
from scripts.ai import fabric_resource_quota_report as rep
from scripts.ai import fabric_resource_quota_resource as rr
from scripts.ai import fabric_scheduler_capacity as cap
from scripts.tests import test_fabric_resource_quota_allocation as afx
from scripts.tests import test_fabric_resource_quota_observation as ofx
from scripts.tests import test_fabric_resource_quota_recovery as rfx

TEST_PATH = Path(__file__).resolve()
REPO_ROOT = TEST_PATH.parents[2]
AI_DIR = REPO_ROOT / "scripts" / "ai"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
CI_STEP_NAME = "FCP-10 resource quota manager regression without skipped tests"
FCP10_SUITES = (
    "test_fabric_resource_quota_contract", "test_fabric_resource_quota_observation",
    "test_fabric_resource_quota_resource", "test_fabric_resource_quota_budget",
    "test_fabric_resource_quota_allocation", "test_fabric_resource_quota_recovery",
    "test_fabric_resource_quota_report", "test_fabric_resource_quota_integration",
)
# Per-suite floors pinned by the CI step, in FCP10_SUITES order.
FCP10_SUITE_MINIMUMS = (30, 30, 30, 30, 30, 30, 30, 30)
FCP10_TOTAL_MINIMUM = 240
FCP10_MODULES = tuple(f"fabric_resource_quota_{n}" for n in (
    "contract", "observation", "resource", "budget", "allocation", "recovery", "report"))
AS_OF = afx.AS_OF
OBSERVED = afx.OBSERVED
NEXT_ELIGIBLE = "2026-10-31T15:01:00Z"
PROVIDERS = ("alpha", "beta")
HOLD_CONDITION = {"QUOTA_WAIT": ofx.QUOTA, "AUTH_BLOCKED": ofx.AUTH}
HOLD_MESSAGE = {"QUOTA_WAIT": rfx.QUOTA_RESET_MESSAGE, "AUTH_BLOCKED": rfx.AUTH_MESSAGE}
FORBIDDEN_IMPORTS = frozenset({
    "subprocess", "socket", "ssl", "urllib", "http", "requests", "httpx", "asyncio", "multiprocessing",
    "threading", "ftplib", "smtplib", "anthropic", "openai", "claude_runner", "fabric_director",
})


# ---------------------------------------------------------------------------
# Chain fixtures (synthetic inputs, real engines)
# ---------------------------------------------------------------------------
def provider_facts(alpha="NONE", observed=OBSERVED):
    """FCP-9C-01 facts of both providers; alpha's agree with its hold."""
    return (cap.ProviderCapacityFacts("alpha", alpha, "AVAILABLE", cap.MAX_WORKERS, observed,
                                      HOLD_CONDITION.get(alpha)),
            cap.ProviderCapacityFacts("beta", "NONE", "AVAILABLE", cap.MAX_WORKERS, observed))


def quota_records(alpha="NONE", hold=None, observed=OBSERVED, with_facts=True):
    """A02 source records: alpha's Runner hold (if any) plus FCP-9 facts."""
    records = [rfx.wait_record(hold)] if hold is not None else []
    if with_facts:
        records.append(afx.quota_record("alpha", availability=alpha, condition=HOLD_CONDITION.get(alpha),
                                        observed=observed))
    records.append(afx.quota_record("beta", observed=observed))
    return tuple(records)


def run_chain(alpha="NONE", records=None, m=None, active=None, observations=None, demands=None, reservation=2000,
              receipts=None, deadline=None, workers=(), composite=None, as_of=AS_OF, observed=OBSERVED,
              hold_at=rfx.HIT, max_age=None, with_facts=True):
    """Every stage once, each over the previous stage's native inputs."""
    hold = None
    if alpha in HOLD_MESSAGE:
        hold, hold_result = rfx.runner_hold(message=HOLD_MESSAGE[alpha], now=hold_at)
    else:
        hold_result = None
    m = afx.manifest() if m is None else m
    quota_kw = {} if max_age is None else {"max_evidence_age_seconds": max_age}
    quota = qo.ObservationRequest(
        request_id="obs-1", as_of_utc=as_of, provider_ids=PROVIDERS,
        records=quota_records(alpha, hold, observed, with_facts) if records is None else tuple(records), **quota_kw)
    snapshot = qo.adapt_observations(quota)
    capacity_request = afx.capacity_request(m, None, active, as_of_utc=as_of,
                                            provider_facts=provider_facts(alpha, observed))
    base = cap.evaluate_capacity(capacity_request)
    observations = afx.core_obs(observed=observed) if observations is None else observations
    resource_request = afx.resource_request(m, capacity_request, observations, demands, as_of_utc=as_of)
    resource = rr.evaluate_resources(resource_request)
    budgets = () if reservation is None else tuple(
        afx.budget_request(p, reservation, receipts=receipts, as_of_utc=as_of) for p in PROVIDERS)
    budget_evaluations = {b.reservation.provider_id: bg.evaluate_budget(b) for b in budgets}
    allocation_request = al.AllocationRequest(request_id="alloc-1", capacity_request=capacity_request,
                                              quota_request=quota, resource_request=resource_request,
                                              budget_requests=budgets)
    plan = al.allocate(allocation_request)
    recovery_request = rq.RecoveryRequest(request_id="rec-1", quota_request=quota, workers=tuple(workers),
                                          deadline_utc=deadline, composite=composite)
    advice = rq.advise_recovery(recovery_request)
    # The report asks exactly what its CLI asks: no workers, no composite.
    report_recovery = rq.RecoveryRequest(request_id="obs-1", quota_request=quota, deadline_utc=deadline)
    report = rep.build_report(*rep.evaluate(quota, report_recovery, budgets[0] if budgets else None))
    return SimpleNamespace(hold=hold, hold_result=hold_result, manifest=m, quota=quota, snapshot=snapshot,
                           capacity_request=capacity_request, base=base, resource_request=resource_request,
                           resource=resource, budgets=budgets, budget_evaluations=budget_evaluations,
                           allocation_request=allocation_request, plan=plan, recovery_request=recovery_request,
                           advice=advice, report=report)


def decision(report, subject, subject_id):
    for item in report["decisions"]:
        if (item["subject"], item["id"]) == (subject, subject_id):
            return item
    return None


def report_provider(report, provider_id):
    for item in report["quota"]["providers"]:
        if item["provider_id"] == provider_id:
            return item
    return None


def capacity_doc(provider, availability="NONE", observed=OBSERVED) -> dict:
    payload = {"provider_id": provider, "availability": availability, "capacity": "AVAILABLE",
               "proven_slots": cap.MAX_WORKERS, "observed_at_utc": observed}
    if availability in HOLD_CONDITION:
        payload["last_condition"] = HOLD_CONDITION[availability]
    return {"evidence_id": f"q-{provider}", "source": qc.SOURCE_SCHEDULER_CAPACITY_FACTS, "provider_id": provider,
            "payload": payload}


def budget_doc(reservation=2000) -> dict:
    """The JSON form of `afx.budget_request(provider='alpha')`."""
    return {
        "policy": {"policy_id": "bpol", "currency": "EUR", "granularity": "0.01", "limits": [
            {"limit_id": "tok", "scope": "GLOBAL", "unit": qc.UNIT_TOTAL_TOKENS, "maximum": 10000,
             "window": {"kind": "ROLLING", "duration_seconds": 86400}}]},
        "executions": [{"execution_id": "e1", "provider_id": "alpha", "incurred_at_utc": "2026-10-31T11:00:00Z"}],
        "receipts": [{"receipt_id": "r1", "execution_id": "e1", "basis": "OBSERVED", "reliability": "CALLER_OBSERVED",
                      "recorded_at_utc": "2026-10-31T11:05:00Z",
                      "quantities": [{"unit": qc.UNIT_TOTAL_TOKENS, "minimum": 1500, "maximum": 1500}]}],
        "reservation": {"reservation_id": "next", "provider_id": "alpha",
                        "amounts": [[qc.UNIT_TOTAL_TOKENS, reservation]]},
    }


def document_of(chain, budget=True) -> dict:
    """The report input document of exactly the chain's quota evidence."""
    records = []
    if chain.hold is not None:
        records.append({"evidence_id": f"ev-wait-{chain.hold.spec.id}", "source": qc.SOURCE_RUNNER_PROVIDER_WAIT,
                        "provider_id": "alpha", "payload": json.loads(json.dumps(chain.hold.to_dict()))})
    alpha = chain.snapshot.provider_view("alpha").availability
    records += [capacity_doc("alpha", alpha), capacity_doc("beta")]
    doc = {"schema": rep.INPUT_SCHEMA, "schema_version": rep.INPUT_SCHEMA_VERSION, "request_id": "obs-1",
           "as_of_utc": AS_OF, "provider_ids": list(PROVIDERS), "records": records}
    if budget:
        doc["budget"] = budget_doc()
    return doc


def _tree(root: Path) -> dict:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class ChainTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rep.engines()  # the report's lazy engine import, done before any guard

    def assertNoStageClears(self, chain, provider_id):
        """Fail closed: no stage turns a held / doubtful provider into a go."""
        self.assertNotEqual(chain.plan.provider_allocation(provider_id).verdict, al.READY)
        self.assertNotEqual(chain.advice.provider(provider_id).status, rq.CLEAR)
        self.assertNotEqual(decision(chain.report, rep.SUBJECT_PROVIDER, provider_id)["status"], rep.CLEAR)
        self.assertNotEqual(chain.report["status"], rep.CLEAR)
        self.assertNotEqual(rep.exit_code_for(chain.report), rep.EXIT_OK)
        for worker in chain.plan.workers:
            if worker.provider == provider_id:
                self.assertNotEqual(worker.decision, al.SCHEDULABLE)
                self.assertIsNone(worker.slot)


# ---------------------------------------------------------------------------
class ClearChainTests(ChainTestBase):
    def test_every_stage_agrees_on_a_clear_evidence_set(self):
        chain = run_chain()
        self.assertEqual(chain.snapshot.outcome, qo.OBSERVED)
        self.assertEqual(chain.resource.verdict, rr.READY)
        self.assertEqual({p: e.verdict for p, e in chain.budget_evaluations.items()},
                         {"alpha": bg.READY, "beta": bg.READY})
        self.assertEqual((chain.plan.outcome, chain.plan.verdict), (al.SCHEDULABLE, al.READY))
        self.assertEqual(chain.plan.allocated, ("w0", "w1", "w2"))
        self.assertEqual(chain.advice.outcome, rq.CLEAR)
        self.assertEqual((chain.report["status"], rep.exit_code_for(chain.report)), (rep.CLEAR, rep.EXIT_OK))
        self.assertEqual(chain.report["next_safe_step"], {"actor": rep.ACTOR_NONE, "action": rep.NO_ACTION})

    def test_allocation_recovery_and_report_consume_one_quota_snapshot(self):
        chain = run_chain()
        fingerprint = chain.snapshot.snapshot_fingerprint
        self.assertEqual(chain.advice.quota_snapshot_fingerprint, fingerprint)
        self.assertEqual(chain.report["sources"]["quota"]["fingerprint"], fingerprint)
        quota_evidence = {e for view in chain.snapshot.providers for e in view.evidence_ids}
        self.assertTrue(quota_evidence <= set(chain.plan.evidence_ids))
        self.assertEqual(set(chain.advice.evidence_ids), quota_evidence)

    def test_allocation_only_narrows_fcp9_and_the_resource_evaluation(self):
        chain = run_chain(observations=afx.core_obs(cpu_free=1500))
        self.assertEqual(chain.plan.base_max_workers, chain.base.effective_max_workers)
        self.assertLessEqual(chain.plan.max_workers, chain.resource.max_workers)
        self.assertLessEqual(chain.plan.max_workers, chain.base.effective_max_workers)
        limits = {p.provider_id: p.limit for p in chain.resource.providers}
        for provider in chain.plan.providers:
            self.assertLessEqual(provider.limit, limits[provider.provider_id])
            self.assertLessEqual(provider.limit, provider.base_limit)
        self.assertEqual((chain.resource.max_workers, chain.plan.max_workers, chain.plan.allocated),
                         (3, 3, ("w0", "w1", "w2")))
        self.assertFalse(chain.plan.limits_relaxed)

    def test_partial_resource_headroom_fills_slots_in_the_runner_order(self):
        chain = run_chain(observations=afx.core_obs(cpu_free=1000))
        self.assertEqual((chain.resource.max_workers, chain.plan.max_workers, chain.plan.runner_max_workers),
                         (2, 2, 2))
        self.assertEqual(chain.plan.allocated, ("w0", "w1"))
        self.assertEqual([chain.plan.worker(w).slot for w in ("w0", "w1")], [0, 1])
        self.assertEqual(chain.plan.worker("w2").decision, al.WAITING)
        self.assertEqual(chain.plan.planning_order, ("w0", "w1", "w2"))

    def test_budget_evidence_is_the_one_the_allocation_and_the_report_cite(self):
        chain = run_chain()
        alpha = chain.budget_evaluations["alpha"]
        self.assertIn("r1", alpha.evidence_ids)
        self.assertIn("r1", chain.plan.evidence_ids)
        self.assertEqual(chain.report["budget"]["evidence_ids"], list(alpha.evidence_ids))
        self.assertEqual(chain.report["sources"]["budget"]["fingerprint"], alpha.request_fingerprint)
        self.assertEqual(chain.report["reserved_capacity"]["budget_reservations"], [
            {"limit_id": "tok", "unit": qc.UNIT_TOTAL_TOKENS, "maximum": 10000, "reservation_in_scope": True,
             "reserved": 2000, "projected": 3500, "remaining": 8500}])

    def test_no_declared_budget_leaves_the_allocation_bounded_only_by_evidence(self):
        chain = run_chain(reservation=None)
        self.assertEqual(chain.budgets, ())
        self.assertEqual(chain.plan.allocated, ("w0", "w1", "w2"))
        self.assertNotIn("r1", chain.plan.evidence_ids)
        self.assertIsNone(chain.report["budget"])
        self.assertIsNone(chain.report["sources"]["budget"])
        self.assertEqual(chain.report["status"], rep.CLEAR)


# ---------------------------------------------------------------------------
class QuotaWaitChainTests(ChainTestBase):
    def test_runner_quota_wait_holds_only_its_own_provider_through_every_stage(self):
        chain = run_chain("QUOTA_WAIT")
        alpha = chain.plan.provider_allocation("alpha")
        self.assertEqual((alpha.verdict, alpha.reasons), (al.WAIT, (al.PROVIDER_QUOTA_WAIT,)))
        self.assertEqual((chain.plan.quota_held, chain.plan.allocated), (("w0", "w1"), ("w2",)))
        self.assertEqual(chain.plan.exhausted_providers, ("alpha",))
        view = chain.advice.provider("alpha")
        self.assertEqual((view.recovery, view.status, view.actor, view.action),
                         (rq.COOLDOWN_PENDING, rq.WAITING, rq.ACTOR_RUNNER, rq.AWAIT_RUNNER_ELIGIBILITY))
        self.assertEqual(chain.advice.provider("beta").status, rq.CLEAR)
        self.assertEqual((chain.report["status"], rep.exit_code_for(chain.report)), (rep.WAITING, rep.EXIT_WAITING))
        self.assertNoStageClears(chain, "alpha")

    def test_the_runner_eligibility_instant_is_echoed_unchanged_by_every_stage(self):
        chain = run_chain("QUOTA_WAIT")
        self.assertEqual(chain.hold.provider_wait["next_eligible_utc"].replace("+00:00", "Z"), NEXT_ELIGIBLE)
        self.assertEqual(chain.snapshot.provider_view("alpha").next_eligible_utc, NEXT_ELIGIBLE)
        self.assertEqual(chain.plan.provider_allocation("alpha").next_eligible_utc, NEXT_ELIGIBLE)
        self.assertEqual(chain.advice.provider("alpha").next_eligible_utc, NEXT_ELIGIBLE)
        self.assertEqual(report_provider(chain.report, "alpha")["next_eligible_utc"], NEXT_ELIGIBLE)
        self.assertEqual(chain.advice.provider("alpha").eligibility_source, qc.ELIGIBILITY_RESET_HINT)

    def test_quota_wait_evidence_ids_are_echoed_by_every_stage(self):
        chain = run_chain("QUOTA_WAIT")
        held = {"ev-wait-w1", "q-alpha"}
        self.assertEqual(set(chain.snapshot.provider_view("alpha").evidence_ids), held)
        self.assertTrue(held <= set(chain.plan.provider_allocation("alpha").evidence_ids))
        self.assertEqual(set(chain.advice.provider("alpha").evidence_ids), held)
        self.assertEqual(set(decision(chain.report, rep.SUBJECT_PROVIDER, "alpha")["evidence_ids"]), held)

    def test_quota_wait_never_reassigns_a_worker_or_proposes_its_fallback(self):
        m = afx.manifest([afx.spec("w0", fallback_providers=["beta"]), afx.spec("w1"),
                          afx.spec("w2", provider="beta")])
        chain = run_chain("QUOTA_WAIT", m=m)
        self.assertEqual(chain.plan.worker("w0").provider, "alpha")
        self.assertIn("w0", chain.plan.quota_held)
        self.assertNotIn("w0", chain.plan.allocated)
        payload = json.loads(al.canonical_json(chain.plan))
        self.assertFalse(payload["provider_reassigned"] or payload["fallback_proposed"])
        self.assertFalse(chain.advice.provider_switch_authorized)
        self.assertFalse(chain.report["provider_switch_authorized"])
        for action in ("PROVIDER_SWITCH", "FALLBACK_PROPOSAL", "RETRY", "RESUME"):
            self.assertIn(action, chain.report["not_authorized_actions"])

    def test_elapsed_eligibility_stays_held_until_the_runner_itself_probes(self):
        chain = run_chain("QUOTA_WAIT", as_of="2026-10-31T15:05:00Z", observed="2026-10-31T15:04:30Z",
                          hold_at=datetime(2026, 10, 31, 14, 59, 30, tzinfo=timezone.utc), max_age=900)
        self.assertEqual(chain.snapshot.provider_view("alpha").availability, "QUOTA_WAIT")
        self.assertEqual(chain.plan.provider_allocation("alpha").quota_availability, "QUOTA_WAIT")
        view = chain.advice.provider("alpha")
        self.assertEqual((view.recovery, view.action), (rq.RECOVERY_UNCONFIRMED, rq.OBSERVE_RUNNER_QUOTA_PROBE))
        self.assertNoStageClears(chain, "alpha")

    def test_a_deadline_before_eligibility_is_a_human_window_decision(self):
        chain = run_chain("QUOTA_WAIT", deadline="2026-10-31T15:00:00Z")
        view = chain.advice.provider("alpha")
        self.assertEqual((view.recovery, view.status, view.actor, view.action),
                         (rq.DEADLINE_BLOCKED, rq.BLOCKED, rq.ACTOR_HUMAN, rq.DECIDE_NEW_EXECUTION_WINDOW))
        self.assertIn(rq.DEADLINE_PRECEDES_ELIGIBILITY, view.reasons)
        self.assertEqual(chain.report["deadline_utc"], "2026-10-31T15:00:00Z")
        self.assertEqual((chain.report["status"], chain.report["next_safe_step"]),
                         (rep.BLOCKED, {"actor": rep.ACTOR_HUMAN, "action": rq.DECIDE_NEW_EXECUTION_WINDOW}))
        # The allocation has no deadline of its own: it still only waits.
        self.assertEqual(chain.plan.provider_allocation("alpha").verdict, al.WAIT)

    def test_a_runner_wait_without_capacity_facts_is_held_by_every_stage(self):
        """A02 cannot prove alpha's capacity: C01 says UNKNOWN, C02 / D01 a
        Runner-owned cooldown. Severities differ, but none is a go."""
        chain = run_chain("QUOTA_WAIT", with_facts=False)
        self.assertIn(qo.CAPACITY_UNKNOWN, chain.snapshot.provider_view("alpha").reasons)
        alpha = chain.plan.provider_allocation("alpha")
        self.assertEqual((alpha.verdict, alpha.reasons), (al.UNKNOWN, (al.QUOTA_EVIDENCE_UNCERTAIN,
                                                                       al.PROVIDER_QUOTA_WAIT)))
        self.assertEqual(chain.advice.provider("alpha").recovery, rq.COOLDOWN_PENDING)
        self.assertEqual(chain.report["status"], rep.WAITING)
        self.assertNoStageClears(chain, "alpha")


# ---------------------------------------------------------------------------
class AuthBlockedChainTests(ChainTestBase):
    def test_auth_block_refuses_its_provider_and_requires_a_human(self):
        chain = run_chain("AUTH_BLOCKED")
        alpha = chain.plan.provider_allocation("alpha")
        self.assertEqual((alpha.verdict, alpha.reasons), (al.REFUSE, (al.PROVIDER_AUTH_BLOCKED,)))
        for wid in ("w0", "w1"):
            self.assertEqual(chain.plan.worker(wid).decision, al.REFUSED)
            self.assertFalse(chain.plan.worker(wid).replannable)
        self.assertEqual(chain.plan.allocated, ("w2",))
        view = chain.advice.provider("alpha")
        self.assertEqual((view.recovery, view.status, view.actor, view.action),
                         (rq.AUTH_BLOCKED, rq.BLOCKED, rq.ACTOR_HUMAN, rq.RESTORE_PROVIDER_AUTH))
        self.assertEqual((chain.report["status"], rep.exit_code_for(chain.report)), (rep.BLOCKED, rep.EXIT_BLOCKED))
        self.assertEqual(chain.report["next_safe_step"], {"actor": rep.ACTOR_HUMAN, "action": rq.RESTORE_PROVIDER_AUTH})
        self.assertNoStageClears(chain, "alpha")

    def test_auth_block_echoes_its_evidence_and_never_an_eligibility_instant(self):
        chain = run_chain("AUTH_BLOCKED")
        self.assertIsNone(chain.plan.provider_allocation("alpha").next_eligible_utc)
        self.assertIsNone(chain.advice.provider("alpha").next_eligible_utc)
        self.assertIsNone(report_provider(chain.report, "alpha")["next_eligible_utc"])
        self.assertEqual(set(chain.advice.provider("alpha").evidence_ids), {"ev-wait-w1", "q-alpha"})
        self.assertIn("ev-wait-w1", chain.plan.provider_allocation("alpha").evidence_ids)

    def test_an_auth_blocked_worker_is_blocked_and_never_retried(self):
        hold, result = rfx.runner_hold(message=rfx.AUTH_MESSAGE)
        chain = run_chain("AUTH_BLOCKED", workers=(rfx.evidence(result, auditor_text=None),))
        worker = chain.advice.worker("w1")
        self.assertEqual((worker.work_verdict, worker.status, worker.action),
                         (rq.VERDICT_BLOCKED, rq.BLOCKED, rq.RESTORE_PROVIDER_AUTH))
        self.assertEqual(chain.advice.outcome, rq.BLOCKED)
        self.assertFalse(chain.advice.auto_retry_allowed or chain.advice.retry_scheduled
                         or chain.advice.resume_allowed)


# ---------------------------------------------------------------------------
class UncertainEvidenceChainTests(ChainTestBase):
    def assertUnknownEverywhere(self, chain, provider_id):
        self.assertEqual(chain.plan.provider_allocation(provider_id).verdict, al.UNKNOWN)
        self.assertEqual(chain.advice.provider(provider_id).status, rq.UNKNOWN)
        self.assertEqual((chain.report["status"], rep.exit_code_for(chain.report)), (rep.UNKNOWN, rep.EXIT_UNKNOWN))
        self.assertEqual(chain.report["next_safe_step"],
                         {"actor": rep.ACTOR_HUMAN, "action": rep.REVIEW_QUOTA_EVIDENCE})
        self.assertNoStageClears(chain, provider_id)

    def test_stale_quota_evidence_is_unknown_in_every_stage(self):
        chain = run_chain(records=(afx.quota_record("alpha", observed="2026-10-31T09:00:00Z"),
                                   afx.quota_record("beta")))
        self.assertIn(qo.EVIDENCE_STALE, chain.snapshot.provider_view("alpha").reasons)
        self.assertUnknownEverywhere(chain, "alpha")

    def test_future_dated_quota_evidence_is_never_success(self):
        chain = run_chain(records=(afx.quota_record("alpha", observed="2026-10-31T12:30:00Z"),
                                   afx.quota_record("beta")))
        self.assertIn(qo.EVIDENCE_FROM_FUTURE, chain.snapshot.provider_view("alpha").reasons)
        self.assertUnknownEverywhere(chain, "alpha")

    def test_a_rejected_record_is_never_dropped(self):
        untyped = qo.SourceRecord("q-alpha", qc.SOURCE_SCHEDULER_CAPACITY_FACTS, "alpha", None)
        chain = run_chain(records=(untyped, afx.quota_record("beta")))
        self.assertEqual(chain.snapshot.outcome, qo.UNKNOWN)
        self.assertEqual(len(chain.report["quota"]["rejected_records"]), 1)
        quota_decision = decision(chain.report, rep.SUBJECT_QUOTA_EVIDENCE, "obs-1")
        self.assertIn(rep.EVIDENCE_REJECTED, quota_decision["reasons"])
        self.assertUnknownEverywhere(chain, "alpha")

    def test_a_provider_without_evidence_is_unknown_not_assumed_available(self):
        chain = run_chain(records=(afx.quota_record("alpha"),))
        self.assertIn(qo.NO_EVIDENCE, chain.snapshot.provider_view("beta").reasons)
        self.assertEqual(chain.advice.provider("beta").reasons, (rq.QUOTA_EVIDENCE_MISSING,))
        self.assertNotIn("w2", chain.plan.allocated)
        self.assertUnknownEverywhere(chain, "beta")

    def test_contradictory_records_fail_closed_without_inventing_a_hold(self):
        hold, _result = rfx.runner_hold()
        chain = run_chain(records=(rfx.wait_record(hold), afx.quota_record("alpha"), afx.quota_record("beta")))
        self.assertIn(qo.EVIDENCE_CONTRADICTORY, chain.snapshot.provider_view("alpha").reasons)
        self.assertEqual(chain.advice.provider("alpha").recovery, rq.PROVIDER_UNKNOWN)
        self.assertUnknownEverywhere(chain, "alpha")


# ---------------------------------------------------------------------------
class ResourceAndBudgetChainTests(ChainTestBase):
    def test_saturated_host_resources_hold_every_start_while_quota_is_clear(self):
        chain = run_chain(observations=afx.core_obs(cpu_free=0))
        self.assertEqual((chain.resource.verdict, chain.resource.reasons), (rr.WAIT, (rr.RESOURCE_SATURATED,)))
        self.assertEqual((chain.plan.verdict, chain.plan.reasons), (al.WAIT, (al.RESOURCE_SATURATED,)))
        self.assertEqual(chain.plan.allocated, ())
        self.assertEqual(chain.plan.runner_max_workers, None)
        # Quota recovery is a separate question and stays the evidence's own.
        self.assertEqual(chain.advice.outcome, rq.CLEAR)

    def test_unknown_host_resources_never_enable_a_slot(self):
        chain = run_chain(observations=afx.core_obs(observed="2026-10-31T09:00:00Z"))
        self.assertEqual(chain.resource.verdict, rr.UNKNOWN)
        self.assertEqual((chain.plan.outcome, chain.plan.reasons), (al.UNKNOWN, (al.RESOURCE_UNKNOWN,)))
        self.assertEqual(chain.plan.allocated, ())

    def test_a_demand_that_can_never_fit_is_refused(self):
        chain = run_chain(demands=afx.core_demands(cpu=9000))
        self.assertEqual(chain.resource.verdict, rr.REFUSE)
        self.assertEqual((chain.plan.outcome, chain.plan.reasons), (al.REFUSED, (al.DEMAND_EXCEEDS_CAPACITY,)))
        self.assertEqual(chain.plan.allocated, ())

    def test_a_saturated_budget_waits_in_the_allocation_and_the_report(self):
        chain = run_chain(reservation=9000)
        self.assertEqual(chain.budget_evaluations["alpha"].verdict, bg.WAIT)
        for provider in chain.plan.providers:
            self.assertEqual((provider.verdict, provider.reasons), (al.WAIT, (al.BUDGET_SATURATED,)))
        self.assertEqual(chain.plan.allocated, ())
        self.assertEqual(decision(chain.report, rep.SUBJECT_BUDGET, "bud-alpha")["status"], rep.WAITING)
        self.assertEqual((chain.report["status"], chain.report["next_safe_step"]),
                         (rep.WAITING, {"actor": rep.ACTOR_DIRECTION, "action": rep.REQUEST_DIRECTION}))

    def test_a_reservation_beyond_the_limit_is_refused_and_never_relaxed(self):
        chain = run_chain(reservation=20000)
        self.assertEqual(chain.budget_evaluations["alpha"].verdict, bg.REFUSE)
        alpha = chain.plan.provider_allocation("alpha")
        self.assertEqual(alpha.verdict, al.REFUSE)
        self.assertIn(al.RESERVATION_EXCEEDS_LIMIT, alpha.reasons)
        self.assertEqual((chain.report["status"], rep.exit_code_for(chain.report)), (rep.BLOCKED, rep.EXIT_BLOCKED))
        self.assertFalse(chain.plan.limits_relaxed)
        self.assertIn("LIMIT_RAISE", chain.report["not_authorized_actions"])
        self.assertIn("PURCHASE", chain.report["not_authorized_actions"])

    def test_unverified_usage_makes_the_budget_unknown_everywhere(self):
        unverified = (bg.UsageReceipt(receipt_id="r1", execution_id="e1", basis=bg.BASIS_OBSERVED,
                                      reliability=qc.RELIABILITY_UNVERIFIED, recorded_at_utc="2026-10-31T11:05:00Z",
                                      quantities=(bg.UsageQuantity(qc.UNIT_TOTAL_TOKENS, 1500, 1500),)),)
        chain = run_chain(receipts=unverified)
        self.assertEqual(chain.budget_evaluations["alpha"].verdict, bg.UNKNOWN)
        for provider in chain.plan.providers:
            self.assertEqual((provider.verdict, provider.reasons), (al.UNKNOWN, (al.BUDGET_UNKNOWN,)))
        self.assertEqual(chain.plan.allocated, ())
        self.assertEqual(chain.report["status"], rep.UNKNOWN)


# ---------------------------------------------------------------------------
class WorkVerdictAndCompositeTests(ChainTestBase):
    def test_runner_success_with_an_auditor_blocked_is_never_pass(self):
        chain = run_chain(workers=(rfx.evidence(rfx.success_result(), auditor_text="VERDICT=BLOCKED"),))
        worker = chain.advice.worker("w1")
        self.assertEqual(worker.work_verdict, rq.VERDICT_BLOCKED)
        self.assertNotEqual(chain.advice.outcome, rq.CLEAR)
        self.assertFalse(chain.advice.verdict_upgraded)

    def test_an_absent_audit_or_a_provider_claim_is_never_pass(self):
        for text in (None, "looks good to me"):
            chain = run_chain(workers=(rfx.evidence(rfx.success_result(), provider_text="VERDICT=PASS",
                                                    auditor_text=text),))
            worker = chain.advice.worker("w1")
            self.assertEqual(worker.provider_verdict, rq.VERDICT_PASS)
            self.assertNotEqual(worker.work_verdict, rq.VERDICT_PASS, text)

    def test_a_composite_without_host_attestation_is_blocked_never_consolidated(self):
        chain = run_chain("QUOTA_WAIT", workers=rfx.clean_workers(), composite=rfx.composite(attest=False))
        self.assertEqual(chain.advice.composite.outcome, rq.COMPOSITE_BLOCKED)
        self.assertEqual(chain.advice.outcome, rq.BLOCKED)
        self.assertFalse(chain.advice.checkpoint_consolidated or chain.advice.commit_created)
        self.assertIn("CHECKPOINT_CONSOLIDATION", chain.report["not_authorized_actions"])

    def test_a_composite_meeting_its_criterion_still_consolidates_nothing(self):
        # The criterion needs the cited Direction act bound to the attested evidence, not the id alone.
        chain = run_chain(workers=rfx.clean_workers(), composite=rfx.composite(act=True))
        self.assertEqual(chain.advice.composite.outcome, rq.COMPOSITE_CRITERIA_MET)
        self.assertFalse(chain.advice.checkpoint_consolidated or chain.advice.commit_created
                         or chain.advice.history_rewritten or chain.advice.authorizes_action)
        self.assertFalse(chain.report["checkpoint_consolidated"] or chain.report["commit_created"])

    def test_a_legitimate_composite_meets_every_predicate_and_consolidates_nothing(self):
        evidence = rfx.composite(act=True)
        chain = run_chain(workers=rfx.clean_workers(), composite=evidence)
        composite = chain.advice.composite
        self.assertEqual((composite.outcome, composite.reasons), (rq.COMPOSITE_CRITERIA_MET, ()))
        self.assertEqual(composite.evidence_fingerprint, rq.composite_evidence_fingerprint(evidence))
        self.assertEqual(evidence.attestation.evidence_fingerprint, composite.evidence_fingerprint)
        self.assertEqual(evidence.direction_authorization.evidence_fingerprint, composite.evidence_fingerprint)
        self.assertEqual((composite.direction_authorization_id, composite.direction_authorization_verified),
                         ("dir-auth-1", True))
        for worker_id in composite.component_ids:
            worker = chain.advice.worker(worker_id)
            self.assertEqual((worker.runner_verdict, worker.provider_verdict, worker.reasons),
                             (rq.VERDICT_PASS, rq.VERDICT_PASS, ()), worker_id)
            self.assertEqual(chain.advice.provider(worker.provider_id).recovery, rq.AVAILABLE_OBSERVED)
        self.assertTrue(composite.requires_direction_authorization)
        self.assertFalse(composite.consolidation_performed)
        for flag in ("checkpoint_consolidated", "commit_created", "history_rewritten", "merging_allowed",
                     "authorizes_action"):
            self.assertIs(getattr(chain.advice, flag), False, flag)
        self.assertFalse(chain.report["checkpoint_consolidated"] or chain.report["commit_created"])
        self.assertIn("CHECKPOINT_CONSOLIDATION", chain.report["not_authorized_actions"])

    def test_an_incomplete_result_with_a_foreign_success_diagnostic_blocks_the_chain(self):
        # F-R5-01: same worker, same native SUCCESS state, but the diagnostic is a
        # real FCP-6 SUCCESS_CONSISTENT of another run; this very result's attempt
        # is incomplete, so FCP-6 itself would never call it a success.
        incomplete = rfx.success_result()
        incomplete["attempts"][-1]["evidence_complete"] = False
        foreign = rq.WorkerEvidence(
            worker_id="w1", provider_id="alpha", result=incomplete, summary=rfx.summary_of(incomplete),
            pipeline_id=rfx.PIPELINE, auditor_verdict_text="VERDICT=PASS",
            diagnostic=rfx.fi.assess_worker("w1", rfx.success_result(), pipeline_id=rfx.PIPELINE,
                                            summary=rfx.summary_of(rfx.success_result())))
        self.assertEqual(foreign.diagnostic.reason_codes, (rq.SUCCESS_CONSISTENT,))
        self.assertEqual((incomplete["state"], foreign.diagnostic.native_state), ("SUCCESS", "SUCCESS"))
        native = rfx.fi.assess_worker("w1", incomplete, pipeline_id=rfx.PIPELINE, summary=foreign.summary)
        self.assertNotIn(rq.SUCCESS_CONSISTENT, native.reason_codes)
        chain = run_chain(workers=(foreign, rfx.evidence(rfx.success_result("w2"))),
                          composite=rfx.composite(act=True))
        worker = chain.advice.worker("w1")
        self.assertIn(rq.RUNNER_EVIDENCE_INTEGRITY, worker.reasons)
        self.assertEqual((worker.diagnostic_reasons, worker.runner_verdict), ((), rq.VERDICT_UNVERIFIED))
        composite = chain.advice.composite
        self.assertEqual(composite.outcome, rq.COMPOSITE_BLOCKED)
        self.assertIn(rq.COMPONENT_EVIDENCE_UNSAFE, composite.reasons)
        self.assertTrue(composite.direction_authorization_verified)
        self.assertEqual(chain.advice.outcome, rq.BLOCKED)
        self.assertFalse(chain.advice.checkpoint_consolidated or chain.advice.commit_created
                         or chain.advice.verdict_upgraded or chain.report["checkpoint_consolidated"])

    def test_bound_native_success_diagnostics_meet_the_criterion_and_consolidate_nothing(self):
        # Each component carries the diagnostic FCP-6 produced for its own records,
        # one of them a native reconciliation: bound, CRITERIA_MET, nothing done.
        reconciled = rfx.success_result("w2", decision="NONE:SUCCESS:RECONCILED_FROM_PRIOR_ATTEMPT",
                                        state_reason="RECONCILED_FROM_PRIOR_ATTEMPT",
                                        reconciliation={"decision": "RECONCILED_FROM_PRIOR_ATTEMPT"})
        workers = (rfx.evidence(rfx.success_result("w1")), rfx.evidence(reconciled))
        for worker in workers:
            self.assertEqual(worker.diagnostic.reason_codes, (rq.SUCCESS_CONSISTENT,))
            self.assertTrue(rq._diagnostic_ok(worker.diagnostic, worker), worker.worker_id)
        # Swapping the two genuine diagnostics breaks the binding (identity) both ways.
        swapped = rq.WorkerEvidence(**{**workers[0].__dict__, "diagnostic": workers[1].diagnostic})
        self.assertFalse(rq._diagnostic_ok(swapped.diagnostic, swapped))
        evidence = rfx.composite(act=True)
        chain = run_chain(workers=workers, composite=evidence)
        composite = chain.advice.composite
        self.assertEqual((composite.outcome, composite.reasons), (rq.COMPOSITE_CRITERIA_MET, ()))
        for worker_id in ("w1", "w2"):
            self.assertEqual(chain.advice.worker(worker_id).runner_verdict, rq.VERDICT_PASS)
        self.assertFalse(composite.consolidation_performed)
        for flag in ("checkpoint_consolidated", "commit_created", "history_rewritten", "verdict_upgraded",
                     "authorizes_action", "state_mutated"):
            self.assertIs(getattr(chain.advice, flag), False, flag)
        # Denial precedence is preserved: an auditor BLOCKED still outweighs the verified act.
        blocked = (workers[0], rfx.evidence(reconciled, auditor_text="VERDICT=BLOCKED"))
        denied = run_chain(workers=blocked, composite=evidence).advice
        self.assertEqual((denied.composite.outcome, denied.outcome), (rq.COMPOSITE_BLOCKED, rq.BLOCKED))
        self.assertIn(rq.COMPONENT_AUDITOR_NOT_PASS, denied.composite.reasons)

    def test_a_stale_success_diagnostic_over_a_provider_hold_never_meets_the_criterion(self):
        # F-R6-01: each worker's diagnostic is FCP-6's own SUCCESS_CONSISTENT of its
        # clean summary; only `provider_condition` of the summary handed over differs.
        # A02 observes NONE for both providers and the Direction act is verified.
        evidence = rfx.composite(act=True)
        legit = run_chain(workers=(rfx.evidence(rfx.success_result("w1")), rfx.evidence(rfx.success_result("w2"))),
                          composite=evidence)
        self.assertEqual((legit.advice.composite.outcome, legit.advice.outcome), (rq.COMPOSITE_CRITERIA_MET, rq.CLEAR))
        self.assertEqual(legit.advice.provider("alpha").recovery, rq.AVAILABLE_OBSERVED)
        self.assertFalse(legit.advice.composite.consolidation_performed)
        for condition in ("PROVIDER_AUTH_BLOCKED", "PROVIDER_QUOTA_EXHAUSTED"):
            clean = rfx.evidence(rfx.success_result("w1"))
            held = rq.WorkerEvidence(**{**clean.__dict__,
                                        "summary": {**clean.summary, "provider_condition": condition}})
            chain = self.assertHeldComponentBlocks(held, evidence)
            self.assertEqual(chain.advice.worker("w1").diagnostic_reasons, ())

    def test_a_current_diagnostic_of_a_held_success_summary_blocks_the_chain(self):
        # FCP-6's own reading of the held summary is contradictory: C02 keeps its
        # codes, carries the hold to the provider and never resolves to success.
        evidence = rfx.composite(act=True)
        for condition, held_code, recovery in (
                ("PROVIDER_AUTH_BLOCKED", rq.PROVIDER_AUTH_BLOCKED, rq.AUTH_BLOCKED),
                ("PROVIDER_QUOTA_EXHAUSTED", rq.PROVIDER_QUOTA_WAIT, rq.PROVIDER_UNKNOWN)):
            summary = {**rfx.summary_of(rfx.success_result("w1")), "provider_condition": condition}
            held = rfx.evidence(rfx.success_result("w1"), summary=summary)
            self.assertIn("CONFLICTING_EVIDENCE", held.diagnostic.reason_codes)
            chain = self.assertHeldComponentBlocks(held, evidence)
            worker = chain.advice.worker("w1")
            self.assertEqual(worker.diagnostic_reasons, held.diagnostic.reason_codes)
            self.assertIn(held_code, worker.reasons)
            self.assertEqual(chain.advice.provider("alpha").recovery, recovery)

    def assertHeldComponentBlocks(self, held, evidence):
        """A02 observes NONE and the Direction act is verified, yet the held
        component is no Runner PASS and the composite stays BLOCKED."""
        chain = run_chain(workers=(held, rfx.evidence(rfx.success_result("w2"))), composite=evidence)
        self.assertEqual(chain.snapshot.provider_view("alpha").availability, "NONE")
        worker = chain.advice.worker("w1")
        self.assertNotEqual(worker.runner_verdict, rq.VERDICT_PASS)
        self.assertIn(rq.RUNNER_EVIDENCE_INTEGRITY, worker.reasons)
        self.assertNotEqual(chain.advice.provider("alpha").recovery, rq.AVAILABLE_OBSERVED)
        composite = chain.advice.composite
        self.assertTrue(composite.direction_authorization_verified)
        self.assertEqual(composite.outcome, rq.COMPOSITE_BLOCKED)
        self.assertTrue({rq.COMPONENT_EVIDENCE_UNSAFE, rq.COMPONENT_VERDICT_NOT_PASS,
                         rq.QUOTA_NOT_RECOVERED} <= set(composite.reasons))
        self.assertEqual(chain.advice.outcome, rq.BLOCKED)
        self.assertIn(rq.COMPOSITE_CRITERIA_NOT_MET, chain.advice.reasons)
        self.assertFalse(composite.consolidation_performed)
        for flag in ("checkpoint_consolidated", "commit_created", "verdict_upgraded", "state_mutated"):
            self.assertIs(getattr(chain.advice, flag), False, flag)
            self.assertIs(chain.report[flag], False, flag)
        return chain

    def test_a_stale_wait_diagnostic_never_hides_a_human_signal_in_the_composite(self):
        # R7 H-1: each component's diagnostic is FCP-6's genuine wait of its clean
        # records, which then gained a process, safety or evidence signal. A02
        # observes NONE and the Direction act is verified: still no WAITING /
        # RUNNER advice, no CLEAR, no CRITERIA_MET and nothing consolidated.
        evidence = rfx.composite(act=True)
        signals = {
            "process_termination_unresolved": (
                lambda r: r["attempts"][-1].update(process_termination_unresolved=True),
                "PROCESS_TERMINATION_UNRESOLVED"),
            "unauthorized_changed_paths": (
                lambda r: r.update(unauthorized_changed_paths=["scripts/ai/other.py"]), "SAFETY_REFUSAL"),
            "safety_verdict": (lambda r: r.update(safety_verdict={"verdict": "FAILED_SAFETY"}), "SAFETY_REFUSAL"),
            "evidence_incomplete": (lambda r: r["attempts"][-1].update(evidence_complete=False),
                                    "EVIDENCE_INCOMPLETE"),
        }
        for base, clean in (("quota", rfx.runner_hold()[1]), ("retry", rfx.retry_wait_result())):
            genuine = rfx.evidence(clean)
            self.assertEqual(rq.worker_rule(rfx.advise(rfx.available(), (genuine,)).worker("w1").reasons)[:2],
                             (rq.WAITING, rq.ACTOR_RUNNER))
            for name, (mutate, code) in signals.items():
                with self.subTest(base=base, signal=name):
                    result = copy.deepcopy(clean)
                    mutate(result)
                    self.assertIn(code, rfx.fi.assess_worker("w1", result, pipeline_id=rfx.PIPELINE,
                                                             summary=genuine.summary).reason_codes)
                    stale = rq.WorkerEvidence(**{**genuine.__dict__, "result": result})
                    chain = run_chain(workers=(stale, rfx.evidence(rfx.success_result("w2"))), composite=evidence)
                    self.assertEqual(chain.snapshot.provider_view("alpha").availability, "NONE")
                    worker = chain.advice.worker("w1")
                    self.assertEqual((worker.status, worker.actor, worker.action),
                                     (rq.UNKNOWN, rq.ACTOR_HUMAN, rq.REVIEW_RUNNER_EVIDENCE))
                    self.assertIn(rq.RUNNER_EVIDENCE_INTEGRITY, worker.reasons)
                    composite = chain.advice.composite
                    self.assertTrue(composite.direction_authorization_verified)
                    self.assertEqual(composite.outcome, rq.COMPOSITE_BLOCKED)
                    self.assertIn(rq.COMPONENT_EVIDENCE_UNSAFE, composite.reasons)
                    self.assertEqual(chain.advice.outcome, rq.BLOCKED)
                    self.assertNotEqual(chain.advice.provider("alpha").recovery, rq.AVAILABLE_OBSERVED)
                    self.assertFalse(composite.consolidation_performed)
                    for flag in ("checkpoint_consolidated", "commit_created", "verdict_upgraded", "state_mutated"):
                        self.assertIs(getattr(chain.advice, flag), False, flag)

    def test_a_runner_quota_wait_keeps_its_wait_only_while_its_diagnostic_is_current(self):
        # The chain's own Runner hold, with FCP-6's current diagnostic: WAITING /
        # RUNNER. The same diagnostic over records that later report an unresolved
        # process is integrity for a human; FCP-6's new reading blocks for a human.
        _hold, held = rfx.runner_hold(message=rfx.QUOTA_RESET_MESSAGE, now=rfx.HIT)
        current = rfx.evidence(held)
        chain = run_chain(alpha="QUOTA_WAIT", workers=(current,))
        worker = chain.advice.worker("w1")
        self.assertEqual((worker.status, worker.actor, worker.action),
                         (rq.WAITING, rq.ACTOR_RUNNER, rq.AWAIT_RUNNER_QUOTA_REEVALUATION))
        self.assertEqual(chain.advice.provider("alpha").recovery, rq.COOLDOWN_PENDING)
        self.assertEqual(chain.advice.outcome, rq.WAITING)
        unresolved = copy.deepcopy(held)
        unresolved["attempts"][-1].update(process_termination_unresolved=True, process_confirmed_stopped=False)
        stale = rq.WorkerEvidence(**{**current.__dict__, "result": unresolved})
        chain = run_chain(alpha="QUOTA_WAIT", workers=(stale,))
        worker = chain.advice.worker("w1")
        self.assertEqual((worker.status, worker.actor, worker.action),
                         (rq.UNKNOWN, rq.ACTOR_HUMAN, rq.REVIEW_RUNNER_EVIDENCE))
        self.assertNotIn(chain.advice.outcome, (rq.WAITING, rq.CLEAR))
        fresh = rfx.evidence(unresolved)
        chain = run_chain(alpha="QUOTA_WAIT", workers=(fresh,))
        worker = chain.advice.worker("w1")
        self.assertEqual((worker.status, worker.actor, worker.action),
                         (rq.BLOCKED, rq.ACTOR_HUMAN, rq.CONFIRM_PROVIDER_PROCESS_STOPPED))
        self.assertEqual(chain.advice.outcome, rq.BLOCKED)
        self.assertFalse(chain.advice.retry_scheduled or chain.advice.resume_from_derived
                         or chain.advice.state_mutated)

    def test_a_blocked_refused_or_incomplete_component_always_blocks_the_composite(self):
        cases = (
            (rfx.ended_result("BLOCKED", "WORK_BLOCKED", worker_id="w1"), rq.COMPONENT_VERDICT_NOT_PASS),
            (rfx.ended_result("BLOCKED", "PROVIDER_UNAVAILABLE", worker_id="w1"), rq.COMPONENT_VERDICT_NOT_PASS),
            (rfx.ended_result("FAILED", "EVIDENCE_FINALIZATION_FAILED", worker_id="w1", evidence_complete=False),
             rq.COMPONENT_VERDICT_NOT_PASS),
            (None, rq.COMPONENT_EVIDENCE_UNSAFE),
        )
        for result, reason in cases:
            worker = (rfx.evidence(result) if result is not None
                      else rfx.evidence(None, worker_id="w1", summary=None))
            # Same verified Direction act as the legitimate case: it never outweighs a component.
            chain = run_chain(workers=(worker, rfx.evidence(rfx.success_result("w2"))),
                              composite=rfx.composite(act=True))
            composite = chain.advice.composite
            self.assertEqual(composite.outcome, rq.COMPOSITE_BLOCKED, reason)
            self.assertIn(reason, composite.reasons)
            self.assertTrue(composite.direction_authorization_verified)
            self.assertEqual(chain.advice.outcome, rq.BLOCKED)
            self.assertFalse(chain.advice.checkpoint_consolidated or chain.advice.commit_created
                             or chain.advice.authorizes_action)
        # A well-formed id without its bound Direction act is a citation, never a permission.
        chain = run_chain(workers=rfx.clean_workers(), composite=rfx.composite())
        self.assertEqual((chain.advice.composite.outcome, chain.advice.composite.reasons),
                         (rq.COMPOSITE_BLOCKED, (rq.DIRECTION_AUTHORIZATION_UNVERIFIED,)))
        self.assertFalse(chain.advice.composite.direction_authorization_verified)


# ---------------------------------------------------------------------------
class ReportCliChainTests(ChainTestBase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="fcp10d02"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def cli(self, doc, *extra) -> tuple:
        path = self.root / "input.json"
        path.write_bytes(json.dumps(doc).encode("utf-8"))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rep.main(["--input-file", str(path), *extra])
        self.assertEqual(err.getvalue(), "")
        return code, out.getvalue()

    def test_the_document_maps_onto_the_very_requests_of_the_chain(self):
        for alpha in ("NONE", "QUOTA_WAIT", "AUTH_BLOCKED"):
            chain = run_chain(alpha)
            quota, recovery, budget = rep.build_requests(document_of(chain))
            self.assertEqual(qo.canonical_json(qo.adapt_observations(quota)), qo.canonical_json(chain.snapshot), alpha)
            self.assertEqual(recovery.quota_request, quota)
            native = afx.budget_request("alpha", 2000, request_id="obs-1")
            self.assertEqual(bg.canonical_json(bg.evaluate_budget(budget)),
                             bg.canonical_json(bg.evaluate_budget(native)))

    def test_cli_report_equals_the_in_memory_chain_report(self):
        for alpha, exit_code in (("NONE", rep.EXIT_OK), ("QUOTA_WAIT", rep.EXIT_WAITING),
                                 ("AUTH_BLOCKED", rep.EXIT_BLOCKED)):
            chain = run_chain(alpha)
            code, out = self.cli(document_of(chain, budget=False))
            report = json.loads(out)
            expected = rep.build_report(*rep.evaluate(
                chain.quota, rq.RecoveryRequest(request_id="obs-1", quota_request=chain.quota), None))
            self.assertEqual(report, expected, alpha)
            self.assertEqual(code, exit_code, alpha)
            self.assertTrue(rep.verify_report(report))
            self.assertEqual(report["sources"]["quota"]["fingerprint"], chain.snapshot.snapshot_fingerprint)

    def test_cli_with_budget_equals_the_chain_report_up_to_the_budget_request_id(self):
        chain = run_chain("QUOTA_WAIT")
        code, out = self.cli(document_of(chain))
        report = json.loads(out)
        self.assertEqual(code, rep.EXIT_WAITING)
        self.assertEqual(report["status"], chain.report["status"])
        self.assertEqual(report["reserved_capacity"], chain.report["reserved_capacity"])
        self.assertEqual(report["budget"], chain.report["budget"])
        self.assertEqual(report["quota"], chain.report["quota"])

    def test_text_and_json_renderings_agree_and_the_input_is_left_untouched(self):
        chain = run_chain("QUOTA_WAIT")
        doc = document_of(chain)
        _code, out = self.cli(doc)
        before = _tree(self.root)
        code, text = self.cli(doc, "--format", "text")
        self.assertEqual(_tree(self.root), before)
        self.assertEqual(code, rep.EXIT_WAITING)
        self.assertIn(f"report_sha256: {json.loads(out)['report_sha256']}", text.splitlines())
        self.assertIn("status: WAITING", text.splitlines())
        self.assertNotIn("session limit", text + out)  # provider prose is never echoed
        self.assertNotIn("resets 3pm", text + out)


# ---------------------------------------------------------------------------
class DeterminismAndAuthorityTests(ChainTestBase):
    SCENARIOS = ({}, {"alpha": "QUOTA_WAIT"}, {"alpha": "AUTH_BLOCKED"}, {"reservation": 9000},
                 {"observations": afx.core_obs(cpu_free=1000)})

    @staticmethod
    def canonical(chain) -> tuple:
        return (qo.canonical_json(chain.snapshot), rr.canonical_json(chain.resource),
                tuple(bg.canonical_json(e) for e in chain.budget_evaluations.values()),
                al.canonical_json(chain.plan), rq.canonical_json(chain.advice), rep.render_json(chain.report))

    def test_the_chain_is_deterministic(self):
        for kw in self.SCENARIOS:
            self.assertEqual(self.canonical(run_chain(**kw)), self.canonical(run_chain(**kw)), kw)

    def test_no_stage_mutates_its_inputs(self):
        hold, _result = rfx.runner_hold()
        m = afx.manifest()
        hold_before, manifest_before = copy.deepcopy(hold.to_dict()), copy.deepcopy(m)
        records = quota_records("QUOTA_WAIT", hold)
        chain = run_chain("QUOTA_WAIT", records=records, m=m)
        run_chain("QUOTA_WAIT", records=records, m=m)
        self.assertEqual(hold.to_dict(), hold_before)
        self.assertEqual(m, manifest_before)
        self.assertEqual(chain.quota.records, records)

    def test_every_stage_keeps_every_zero_authority_flag(self):
        for kw in self.SCENARIOS:
            chain = run_chain(**kw)
            results = [chain.snapshot, chain.resource, chain.plan, chain.advice,
                       *chain.budget_evaluations.values()]
            for result in results:
                for flag, value in type(result)._guarantees().items():
                    if type(value) is bool:
                        self.assertIs(getattr(result, flag), False, (type(result).__name__, flag))
            for flag in rep.AUTHORITY_FLAGS:
                self.assertIs(chain.report[flag], False, flag)
            self.assertEqual(chain.report["authority"]["execution_authority"], "RUNNER")
            self.assertFalse(chain.report["authority"]["launcher"])
            self.assertEqual(chain.report["not_authorized_actions"], list(rep.NOT_AUTHORIZED_ACTIONS))

    def test_the_chain_spawns_no_process_opens_no_socket_and_reads_no_file(self):
        def refuse(*_a, **_k):
            raise AssertionError("FCP-10 must not reach the OS")

        with contextlib.ExitStack() as stack:
            for target, name in ((subprocess, "Popen"), (subprocess, "run"), (os, "system"), (socket, "socket"),
                                 (socket, "create_connection"), (builtins, "open")):
                stack.enter_context(mock.patch.object(target, name, refuse))
            for kw in self.SCENARIOS:
                self.assertIsNotNone(run_chain(**kw).report["report_sha256"])

    def test_fcp10_modules_import_no_network_process_or_ai_client(self):
        for name in FCP10_MODULES:
            tree = ast.parse((AI_DIR / f"{name}.py").read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                    imported |= {a.name.rsplit(".", 1)[-1] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported |= {(node.module or "").split(".")[0]} | {a.name for a in node.names}
            self.assertFalse(imported & FORBIDDEN_IMPORTS, name)


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

    def test_single_step_sits_after_governed_git_and_before_pipeline(self):
        steps, _ = self._job_steps("fabric-regression")
        self.assertEqual(self.text.count(CI_STEP_NAME), 1)
        idx = steps.index(CI_STEP_NAME)
        self.assertEqual(steps[idx - 1], "Governed Git security regression")
        self.assertEqual(steps[idx + 1], "Pipeline and infrastructure regression")

    def test_protected_fcp5_7_8_9_adjacencies_are_unchanged(self):
        steps, _ = self._job_steps("fabric-regression")
        self.assertEqual(steps, [
            "Checkout", "Setup Python 3.11", "Environment",
            "FCP-7B/7C provider router gateway and governed routed CLI regression without skipped tests",
            "FCP-7A-01 provider routing pure policy regression without skipped tests",
            "FCP-8 validation and evidence engine regression without skipped tests",
            "FCP-6B-01 recovery advisory read-only regression without skipped tests",
            "FCP-6A-01 failure intelligence read-only regression without skipped tests",
            "FCP-6C-01..04 nightshift composed regression without skipped tests",
            "FCP-9 scheduler and parallel execution regression without skipped tests",
            "Director and CLI regression", "Governed Git security regression", CI_STEP_NAME,
            "Pipeline and infrastructure regression",
            "FCP-5A-01 DAG blueprint bridge regression without skipped tests",
            "Runner Queue Multiworker regression",
            "FCP-5B-01 Director DAG gateway regression without skipped tests",
        ])

    def test_step_runs_exactly_the_eight_fcp10_suites_with_strict_gates(self):
        start = self.lines.index(f"      - name: {CI_STEP_NAME}")
        self.assertEqual(self.lines[start + 1], "        run: |")
        self.assertEqual(self.lines[start + 3], "")
        step = self.lines[start + 2]
        self.assertEqual(re.findall(r"scripts\.tests\.(\w+)", step), list(FCP10_SUITES))
        self.assertIn("m=" + repr(FCP10_SUITE_MINIMUMS).replace(" ", ""), step)
        for gate in ("r.wasSuccessful()", "r.testsRun == sum(c)", f"sum(c) >= {FCP10_TOTAL_MINIMUM}",
                     "len(c) == len(m)", "all(x >= y for x, y in zip(c, m))", "not r.skipped",
                     "not r.expected" + "Failures", "not r.unexpectedSuccesses"):
            self.assertIn(gate, step)
        for suite in FCP10_SUITES:
            self.assertEqual(self.text.count(suite), 1, suite)

    def test_gated_suites_meet_the_declared_minimums(self):
        counts = [unittest.defaultTestLoader.loadTestsFromName(f"scripts.tests.{n}").countTestCases()
                  for n in FCP10_SUITES]
        self.assertGreaterEqual(sum(counts), FCP10_TOTAL_MINIMUM)
        for suite, count, minimum in zip(FCP10_SUITES, counts, FCP10_SUITE_MINIMUMS):
            self.assertGreaterEqual(count, minimum, suite)

    def test_prior_stage_gates_are_preserved(self):
        for gate in ("min(c) >= 45", "r.testsRun >= 45 and not r.skipped", "r.testsRun >= 35 and not r.skipped",
                     "r.testsRun >= 30 and not r.skipped", "r.testsRun >= 122 and not r.skipped",
                     "sum(c) >= 200 and min(c) >= 25", "sum(c) >= 300",
                     "loadTestsFromName('scripts.tests.test_fabric_dag_blueprint')",
                     "loadTestsFromName('scripts.tests.test_fabric_director_dag')",
                     "python -m unittest scripts.tests.test_runner_git -q"):
            self.assertIn(gate, self.text)


if __name__ == "__main__":
    unittest.main()
