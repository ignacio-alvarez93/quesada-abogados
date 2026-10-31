"""FCP-10C-01: Advisory allocation and effective limits with FCP-9.

Manifests are native `runner_pipeline.Manifest`s; capacity plans come from
the real FCP-9C-01 `evaluate_capacity` (with the real FCP-9B-01 conflict
analysis), quota snapshots from the real FCP-10A-02 `adapt_observations`
(a Runner quota wait produced by the Runner's own `_hold_for_provider`),
resource evaluations from the real FCP-10B-01 `evaluate_resources` and
budgets from the real FCP-10B-02 `evaluate_budget`. Worktrees are synthetic
lexical paths under a root that never exists and every observation is a
synthetic injected value: nothing executes, probes, reserves, buys or sends
anything. Nothing here is skipped.
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
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_resource_quota_allocation as al
from scripts.ai import fabric_resource_quota_budget as bg
from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_resource_quota_observation as qo
from scripts.ai import fabric_resource_quota_resource as rr
from scripts.ai import fabric_scheduler_capacity as cap
from scripts.ai import fabric_scheduler_conflicts as cf
from scripts.ai import runner_pipeline as rp
from scripts.tests import test_fabric_resource_quota_observation as obs_fixtures

MODULE_PATH = Path(al.__file__)
TEST_PATH = Path(__file__).resolve()
ROOT = "/fcp10c01-synthetic"
AS_OF = "2026-10-31T12:00:00Z"
OBSERVED = "2026-10-31T11:59:30Z"
DAY = qc.QuotaWindow(qc.WINDOW_ROLLING, 86400)
TOTAL = qc.UNIT_TOTAL_TOKENS
QUOTA = obs_fixtures.QUOTA
AUTH = obs_fixtures.AUTH
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "reservation_held",
             "quota_authority", "purchase_allowed", "remote_api_allowed", "provider_reassigned",
             "fallback_proposed", "limits_relaxed", "blueprint_run")


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


# ---------------------------------------------------------------------------
# FCP-9 fixtures
# ---------------------------------------------------------------------------
def spec(wid, provider="alpha", worktree=None, mode="read-only", **extra):
    top = f"{ROOT}/{worktree or wid}"
    return rp.WorkerSpec(id=wid, worktree=top, work_order=f"{ROOT}/wo_{wid}.md", provider=provider, mode=mode,
                         worktree_top=top, **extra)


def manifest(specs=None, max_workers=4, **extra):
    specs = specs if specs is not None else [spec("w0"), spec("w1"), spec("w2", provider="beta")]
    return rp.Manifest(pipeline_id="fcp10c01-dag", workers=list(specs), max_workers=max_workers, **extra)


def providers_of(m):
    return sorted({p for s in m.workers for p in [s.provider] + list(s.fallback_providers)})


def claims(m):
    return cf.ConflictRequest(dag_id=m.pipeline_id, allowed_roots=(ROOT,), workers=tuple(
        cf.WorkerClaims(worker_id=s.id, mode=s.mode, worktree=s.worktree_top, worktree_link_state=cf.LINK_NONE)
        for s in m.workers))


def capacity_request(m, states=None, active=None, **kw):
    """Workers are READY unless stated otherwise; every provider has fresh,
    available FCP-9 facts; conflicts are assessed."""
    states, active = states or {}, active or {}
    fields = dict(manifest=m, as_of_utc=AS_OF, conflict_request=claims(m),
                  items=tuple(cap.CapacityItem(s.id, states.get(s.id, "READY"), active.get(s.id)) for s in m.workers),
                  provider_facts=tuple(cap.ProviderCapacityFacts(p, "NONE", "AVAILABLE", cap.MAX_WORKERS, OBSERVED)
                                       for p in providers_of(m)))
    fields.update(kw)
    return cap.CapacityRequest(**fields)


# ---------------------------------------------------------------------------
# FCP-10 A/B fixtures
# ---------------------------------------------------------------------------
def quota_record(provider, availability="NONE", capacity="AVAILABLE", slots=cap.MAX_WORKERS, observed=OBSERVED,
                 condition=None):
    return qo.SourceRecord(evidence_id=f"q-{provider}", source=qc.SOURCE_SCHEDULER_CAPACITY_FACTS,
                           provider_id=provider, payload=cap.ProviderCapacityFacts(
                               provider, availability, capacity, slots, observed, condition))


def quota_request(providers, records=None, **kw):
    fields = dict(request_id="obs-1", as_of_utc=AS_OF, provider_ids=tuple(providers),
                  records=tuple(quota_record(p) for p in providers) if records is None else tuple(records))
    fields.update(kw)
    return qo.ObservationRequest(**fields)


def host(evidence_id, resource_id, kind, capacity, in_use=0, reserve=0, observed=OBSERVED,
         reliability=qc.RELIABILITY_CALLER_OBSERVED):
    return rr.HostResourceObservation(
        evidence_id=evidence_id, resource_id=resource_id, kind=kind, unit=rr.KIND_UNIT[kind], capacity=capacity,
        in_use=in_use, reserve=reserve, source=rr.SOURCE_CALLER_HOST_SNAPSHOT, reliability=reliability,
        observed_at_utc=observed)


def core_obs(cpu_free=8000, **kw):
    return (host("h-cpu", "cpu", rr.KIND_CPU, 8000, in_use=8000 - cpu_free, **kw),
            host("h-mem", "mem", rr.KIND_MEMORY, 65536), host("h-proc", "proc", rr.KIND_PROCESS_SLOTS, 4096))


def demand(resource_id, kind, amount, provider=None):
    return rr.ResourceDemand(resource_id=resource_id, kind=kind, unit=rr.KIND_UNIT[kind], amount=amount,
                             provider_id=provider)


def core_demands(cpu=500, extra=()):
    """With `core_obs` defaults: 16 starts fit (CPU 8000 / 500)."""
    return (demand("cpu", rr.KIND_CPU, cpu), demand("mem", rr.KIND_MEMORY, 1024),
            demand("proc", rr.KIND_PROCESS_SLOTS, 4)) + tuple(extra)


def resource_request(m, creq, observations=None, demands=None, **kw):
    fields = dict(request_id="res-1", as_of_utc=AS_OF, manifest=m, capacity_plan=cap.evaluate_capacity(creq),
                  observations=core_obs() if observations is None else observations,
                  demands=core_demands() if demands is None else demands)
    fields.update(kw)
    return rr.ResourceRequest(**fields)


def usage_limit(limit_id="tok", maximum=10_000, scope=qc.SCOPE_GLOBAL, **kw):
    return qc.QuotaLimit(limit_id=limit_id, scope=scope, unit=TOTAL, maximum=maximum, window=DAY, **kw)


def budget_request(provider, amount, limits=None, used=1500, receipts=None, **kw):
    """One budget question per provider: only its reservation differs.
    By default 1500 of 10000 global tokens are already used."""
    fields = dict(
        request_id=f"bud-{provider}", as_of_utc=AS_OF,
        policy=bg.BudgetPolicy(policy_id="bpol", currency="EUR", granularity=D("0.01"),
                               limits=(usage_limit(),) if limits is None else tuple(limits)),
        executions=(bg.BudgetExecution(execution_id="e1", provider_id="alpha",
                                       incurred_at_utc="2026-10-31T11:00:00Z"),),
        receipts=(bg.UsageReceipt(receipt_id="r1", execution_id="e1", basis=bg.BASIS_OBSERVED,
                                  reliability=qc.RELIABILITY_CALLER_OBSERVED, recorded_at_utc="2026-10-31T11:05:00Z",
                                  quantities=(bg.UsageQuantity(TOTAL, used, used),)),) if receipts is None
        else receipts,
        reservation=qc.AdvisoryReservation(reservation_id="next", provider_id=provider, amounts=((TOTAL, amount),)),
    )
    fields.update(kw)
    return bg.BudgetRequest(**fields)


def concurrency_policy(*limits):
    return qc.QuotaPolicy(policy_id="cpol", limits=tuple(
        qc.QuotaLimit(limit_id=f"conc-{i}", scope=scope, unit=qc.UNIT_CONCURRENT_EXECUTIONS, maximum=maximum,
                      provider_id=provider)
        for i, (scope, maximum, provider) in enumerate(limits)))


def allocation_request(m=None, states=None, active=None, cap_kw=None, quota=None, observations=None, demands=None,
                       budgets=(), policy=None, **kw):
    m = manifest() if m is None else m
    creq = capacity_request(m, states, active, **(cap_kw or {}))
    fields = dict(request_id="alloc-1", capacity_request=creq,
                  quota_request=quota_request(providers_of(m)) if quota is None else quota,
                  resource_request=resource_request(m, creq, observations, demands), budget_requests=budgets,
                  quota_policy=policy)
    fields.update(kw)
    return al.AllocationRequest(**fields)


def allocate(**kw):
    return al.allocate(allocation_request(**kw))


class AllocationTestBase(unittest.TestCase):
    def assertRefused(self, plan, *codes):
        self.assertEqual((plan.outcome, plan.verdict), (al.REFUSED, al.REFUSE))
        for code in codes:
            self.assertIn(code, plan.request_reasons)
        self.assertEqual((plan.request_id, plan.providers, plan.workers, plan.max_workers, plan.evidence_ids),
                         (None, (), (), None, ()))
        return plan

    def assertNeverRelaxed(self, plan, req):
        """Every effective limit is at most FCP-9's own base and FCP-9 under
        the narrowed limits admitted at least what is allocated."""
        base = cap.evaluate_capacity(req.capacity_request)
        self.assertEqual(plan.base_max_workers, base.effective_max_workers)
        self.assertLessEqual(plan.max_workers, base.effective_max_workers)
        base_limits = dict(base.effective_provider_limits)
        for provider in plan.providers:
            self.assertLessEqual(provider.limit, base_limits.get(provider.provider_id, base.effective_max_workers))
        for worker in plan.workers:
            if worker.decision == al.SCHEDULABLE:
                self.assertEqual(worker.capacity_decision, al.SCHEDULABLE)
        return base


# ---------------------------------------------------------------------------
# Request validation (fail closed, nothing echoed)
# ---------------------------------------------------------------------------
class RequestTests(AllocationTestBase):
    def test_untyped_requests_are_refused_without_raising(self):
        for bad in (None, "alloc", 3, {"request_id": "alloc-1"}, [allocation_request()]):
            self.assertRefused(al.allocate(bad), al.REQUEST_NOT_TYPED)

    def test_identity_and_schema_are_validated(self):
        self.assertRefused(allocate(request_id="Bad Id"), al.REQUEST_ID_INVALID)
        self.assertRefused(allocate(request_id="sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"),
                           al.REQUEST_ID_INVALID)
        self.assertRefused(allocate(schema_version=2), al.SCHEMA_VERSION_UNSUPPORTED)
        self.assertRefused(allocate(schema_version=True), al.SCHEMA_VERSION_UNSUPPORTED)

    def test_a_refused_fcp9_capacity_request_refuses_the_allocation(self):
        req = allocation_request()
        bad = dataclasses.replace(req.capacity_request, max_workers=0)
        self.assertRefused(al.allocate(dataclasses.replace(req, capacity_request=bad)), al.CAPACITY_REQUEST_REFUSED)
        self.assertRefused(al.allocate(dataclasses.replace(req, capacity_request=None)), al.CAPACITY_REQUEST_REFUSED)

    def test_quota_evidence_must_be_valid_and_of_the_same_instant(self):
        m = manifest()
        self.assertRefused(allocate(m=m, quota=qo.ObservationRequest("Bad", AS_OF)), al.QUOTA_REQUEST_REFUSED)
        self.assertRefused(allocate(m=m, quota="obs"), al.QUOTA_REQUEST_REFUSED)
        later = quota_request(providers_of(m), as_of_utc="2026-10-31T12:00:01Z")
        self.assertRefused(allocate(m=m, quota=later), al.QUOTA_INSTANT_MISMATCH)

    def test_resource_evidence_must_be_bound_to_the_base_plan(self):
        m = manifest()
        req = allocation_request(m=m)
        self.assertRefused(al.allocate(dataclasses.replace(req, resource_request=None)), al.RESOURCE_REQUEST_NOT_TYPED)
        other_plan = cap.evaluate_capacity(capacity_request(m, states={"w0": "QUEUED"}))
        mismatched = dataclasses.replace(req.resource_request, capacity_plan=other_plan)
        self.assertRefused(al.allocate(dataclasses.replace(req, resource_request=mismatched)), al.RESOURCE_PLAN_MISMATCH)
        later = dataclasses.replace(req.resource_request, as_of_utc="2026-10-31T11:00:00Z")
        self.assertRefused(al.allocate(dataclasses.replace(req, resource_request=later)), al.RESOURCE_INSTANT_MISMATCH)
        refused = dataclasses.replace(req.resource_request, demands=())
        self.assertRefused(al.allocate(dataclasses.replace(req, resource_request=refused)), al.RESOURCE_REQUEST_REFUSED)

    def test_budget_requests_are_validated_per_provider(self):
        good = budget_request("alpha", 2000)
        self.assertRefused(allocate(budgets=[good]), al.BUDGET_REQUESTS_MALFORMED)
        self.assertRefused(allocate(budgets=(good, "x")), al.BUDGET_REQUESTS_MALFORMED)
        self.assertRefused(allocate(budgets=(dataclasses.replace(good, reservation=None),)),
                           al.BUDGET_RESERVATION_MISSING)
        self.assertRefused(allocate(budgets=(budget_request("gamma", 10),)), al.BUDGET_PROVIDER_UNKNOWN)
        self.assertRefused(allocate(budgets=(good, dataclasses.replace(good, request_id="bud-2"))),
                           al.BUDGET_PROVIDER_DUPLICATE)
        self.assertRefused(allocate(budgets=(good, budget_request("beta", 10, used=1600))),
                           al.BUDGET_EVIDENCE_MISMATCH)
        self.assertRefused(allocate(budgets=(dataclasses.replace(good, as_of_utc="2026-10-31T12:30:00Z"),)),
                           al.BUDGET_INSTANT_MISMATCH)
        self.assertRefused(allocate(budgets=(dataclasses.replace(good, request_id="Bad"),)),
                           al.BUDGET_REQUEST_REFUSED)

    def test_quota_policy_is_validated_and_only_concurrency_is_accepted(self):
        self.assertRefused(allocate(policy="cpol"), al.POLICY_REFUSED)
        cumulative = qc.QuotaPolicy("cpol", (usage_limit(),))
        self.assertRefused(allocate(policy=cumulative), al.POLICY_LIMIT_NOT_CONCURRENT)
        self.assertRefused(allocate(policy=concurrency_policy((qc.SCOPE_PROVIDER, 1, "gamma"))),
                           al.POLICY_PROVIDER_UNKNOWN)


# ---------------------------------------------------------------------------
# Allocation with FCP-9 (order, dependencies, exclusivity, only narrowing)
# ---------------------------------------------------------------------------
class AllocationTests(AllocationTestBase):
    def test_ample_evidence_reproduces_fcp9_and_cites_its_evidence(self):
        req = allocation_request()
        plan = al.allocate(req)
        base = self.assertNeverRelaxed(plan, req)
        self.assertEqual((plan.outcome, plan.verdict, plan.reasons), (al.SCHEDULABLE, al.READY, ()))
        self.assertEqual(plan.allocated, base.admitted)
        self.assertEqual(plan.allocated, ("w0", "w1", "w2"))
        self.assertEqual((plan.max_workers, plan.runner_max_workers), (4, 4))
        self.assertEqual(plan.dag_id, "fcp10c01-dag")
        self.assertTrue({"q-alpha", "q-beta", "h-cpu", "h-mem", "h-proc"} <= set(plan.evidence_ids))
        self.assertEqual(plan.replannable, ("w0", "w1", "w2"))
        self.assertEqual((plan.quota_held, plan.exhausted_providers), ((), ()))

    def test_resource_headroom_narrows_the_limits_handed_back_to_fcp9(self):
        req = allocation_request(observations=core_obs(cpu_free=1000))
        plan = al.allocate(req)
        self.assertNeverRelaxed(plan, req)
        self.assertEqual((plan.headroom, plan.max_workers, plan.runner_max_workers), (2, 2, 2))
        self.assertEqual(plan.allocated, ("w0", "w1"))
        w2 = plan.worker("w2")
        self.assertEqual((w2.decision, w2.capacity_decision), (al.WAITING, al.WAITING))
        self.assertIn(cap.WORKER_LIMIT_REACHED, w2.capacity_reasons)
        self.assertNotEqual(plan.narrowed_plan_fingerprint, plan.base_plan_fingerprint)
        self.assertEqual(dict(plan.runner_provider_limits), {"alpha": 2, "beta": 2})

    def test_priority_then_declared_order_is_the_deterministic_tie_break(self):
        m = manifest([spec("w0"), spec("w1", priority=5), spec("w2"), spec("w3", priority=5)])
        plan = allocate(m=m, observations=core_obs(cpu_free=1500))
        self.assertEqual(plan.planning_order, ("w1", "w3", "w0", "w2"))
        self.assertEqual(plan.allocated, ("w1", "w3", "w0"))
        self.assertEqual([plan.worker(i).slot for i in plan.allocated], [0, 1, 2])
        self.assertEqual(json.loads(al.canonical_json(plan))["tie_break"], al.TIE_BREAK)
        again = allocate(m=m, observations=tuple(reversed(core_obs(cpu_free=1500))))
        self.assertEqual(again.allocated, plan.allocated)
        self.assertEqual(again.planning_order, plan.planning_order)

    def test_dependencies_already_authorized_by_fcp9_are_kept(self):
        m = manifest([spec("w0"), spec("w1", depends_on=["w0"]), spec("w2", provider="beta")])
        plan = allocate(m=m)
        w1 = plan.worker("w1")
        self.assertEqual((w1.decision, w1.slot), (al.WAITING, None))
        self.assertIn(cap.DEPENDENCY_PENDING, w1.capacity_reasons)
        self.assertEqual(plan.allocated, ("w0", "w2"))

    def test_worktree_exclusivity_is_never_relaxed(self):
        m = manifest([spec("w0", mode="write", worktree="shared"), spec("w1", mode="write", worktree="shared"),
                      spec("w2", provider="beta")])
        plan = allocate(m=m)
        self.assertEqual(plan.allocated, ("w0", "w2"))
        self.assertIn(cap.CONFLICT_WITH_ADMITTED, plan.worker("w1").capacity_reasons)
        unassessed = allocate(m=m, cap_kw={"conflict_request": None})
        self.assertEqual(unassessed.allocated, ())
        self.assertEqual(unassessed.outcome, al.UNKNOWN)

    def test_limits_are_never_raised_above_manifest_or_the_callers_own(self):
        m = manifest(max_workers=2, provider_limits={"alpha": 1})
        req = allocation_request(m=m, cap_kw={"provider_limits": (("beta", 1),)})
        plan = al.allocate(req)
        self.assertNeverRelaxed(plan, req)
        self.assertEqual((plan.base_max_workers, plan.max_workers), (2, 2))
        self.assertEqual({p.provider_id: p.limit for p in plan.providers}, {"alpha": 1, "beta": 1})
        self.assertEqual(plan.allocated, ("w0", "w2"))
        for observations in (core_obs(cpu_free=8000), core_obs(cpu_free=500), core_obs(cpu_free=0)):
            req = allocation_request(m=m, observations=observations)
            self.assertNeverRelaxed(al.allocate(req), req)

    def test_running_workers_occupy_slots_and_stay_inactive(self):
        plan = allocate(states={"w0": "RUNNING"}, observations=core_obs(cpu_free=1000))
        self.assertEqual((plan.occupied_slots, plan.headroom, plan.max_workers), (1, 2, 3))
        w0 = plan.worker("w0")
        self.assertEqual((w0.decision, w0.reasons, w0.replannable), (al.INACTIVE, (), False))
        self.assertEqual(plan.allocated, ("w1", "w2"))
        self.assertEqual(plan.provider_allocation("alpha").limit, 3)


# ---------------------------------------------------------------------------
# Quota exhaustion and authorization holds (fail closed, evidence echoed)
# ---------------------------------------------------------------------------
class QuotaTests(AllocationTestBase):
    NEXT_ELIGIBLE = "2026-10-31T15:01:00Z"

    def runner_wait_quota(self, with_facts=True):
        """alpha in a real Runner quota wait (the Runner's own eligibility
        instant), confirmed by FCP-9 facts unless `with_facts` is False;
        beta fine."""
        records = [obs_fixtures.wait_record(evidence_id="q-alpha-wait"), quota_record("beta")]
        if with_facts:
            records.append(quota_record("alpha", availability="QUOTA_WAIT", condition=QUOTA))
        return quota_request(["alpha", "beta"], records=records)

    def held_facts(self, availability="QUOTA_WAIT", condition=QUOTA):
        """FCP-9's own facts agreeing with the hold."""
        return {"provider_facts": (
            cap.ProviderCapacityFacts("alpha", availability, "AVAILABLE", cap.MAX_WORKERS, OBSERVED, condition),
            cap.ProviderCapacityFacts("beta", "NONE", "AVAILABLE", cap.MAX_WORKERS, OBSERVED))}

    def test_exhausted_quota_holds_only_its_own_workers_and_echoes_evidence(self):
        plan = allocate(quota=self.runner_wait_quota(), cap_kw=self.held_facts())
        alpha = plan.provider_allocation("alpha")
        self.assertEqual((alpha.verdict, alpha.reasons), (al.WAIT, (al.PROVIDER_QUOTA_WAIT,)))
        self.assertEqual((alpha.quota_availability, alpha.next_eligible_utc), ("QUOTA_WAIT", self.NEXT_ELIGIBLE))
        self.assertTrue({"q-alpha", "q-alpha-wait"} <= set(alpha.evidence_ids))
        self.assertEqual((alpha.headroom, alpha.limit, alpha.runner_limit), (0, 0, None))
        self.assertEqual(plan.exhausted_providers, ("alpha",))
        self.assertEqual(plan.quota_held, ("w0", "w1"))
        self.assertEqual(plan.allocated, ("w2",))
        self.assertEqual(plan.worker("w2").slot, 0)
        for wid in ("w0", "w1"):
            self.assertEqual(plan.worker(wid).decision, al.WAITING)

    def test_a_runner_wait_alone_stays_unknown_and_still_returns_its_evidence(self):
        """A quota wait proves no capacity: fail closed, never inferred."""
        plan = allocate(quota=self.runner_wait_quota(with_facts=False))
        alpha = plan.provider_allocation("alpha")
        self.assertEqual(alpha.verdict, al.UNKNOWN)
        self.assertEqual(alpha.reasons, (al.QUOTA_EVIDENCE_UNCERTAIN, al.PROVIDER_QUOTA_WAIT))
        self.assertEqual((alpha.next_eligible_utc, alpha.evidence_ids[-1]), (self.NEXT_ELIGIBLE, "q-alpha-wait"))
        self.assertEqual([plan.worker(w).decision for w in ("w0", "w1")], [al.UNKNOWN, al.UNKNOWN])
        self.assertEqual((plan.outcome, plan.quota_held, plan.exhausted_providers), (al.UNKNOWN, ("w0", "w1"),
                                                                                      ("alpha",)))

    def test_replannable_workers_stay_on_their_already_assigned_apt_provider(self):
        m = manifest([spec("w0", fallback_providers=["beta"]), spec("w1"), spec("w2", provider="beta"),
                      spec("w3", provider="beta")])
        plan = allocate(m=m, active={"w0": "alpha"}, quota=self.runner_wait_quota(), cap_kw=self.held_facts(),
                        observations=core_obs(cpu_free=500))
        self.assertEqual(plan.worker("w0").provider, "alpha")
        self.assertEqual(plan.quota_held, ("w0", "w1"))
        self.assertEqual(plan.replannable, ("w2", "w3"))
        self.assertEqual(plan.allocated, ("w2",))
        self.assertEqual(plan.worker("w3").decision, al.WAITING)
        text = al.canonical_json(plan)
        self.assertFalse(json.loads(text)["fallback_proposed"])
        self.assertFalse(json.loads(text)["provider_reassigned"])

    def test_an_unobserved_assignment_is_never_replannable(self):
        m = manifest([spec("w0", fallback_providers=["beta"]), spec("w1", provider="beta")])
        plan = allocate(m=m)
        w0 = plan.worker("w0")
        self.assertIn(cap.ACTIVE_PROVIDER_UNOBSERVED, w0.capacity_reasons)
        self.assertEqual((w0.decision, w0.replannable), (al.UNKNOWN, False))
        self.assertEqual(plan.replannable, ("w1",))

    def test_auth_blocked_refuses_its_workers_and_proposes_nothing(self):
        records = (quota_record("alpha", availability="AUTH_BLOCKED", condition=AUTH), quota_record("beta"))
        plan = allocate(quota=quota_request(["alpha", "beta"], records=records),
                        cap_kw=self.held_facts("AUTH_BLOCKED", AUTH))
        alpha = plan.provider_allocation("alpha")
        self.assertEqual((alpha.verdict, alpha.quota_availability), (al.REFUSE, "AUTH_BLOCKED"))
        self.assertEqual([plan.worker(w).decision for w in ("w0", "w1")], [al.REFUSED, al.REFUSED])
        self.assertEqual(plan.quota_held, ("w0", "w1"))
        self.assertEqual(plan.exhausted_providers, ())
        self.assertEqual(plan.allocated, ("w2",))

    def test_a_withdrawn_slot_is_not_handed_to_another_worker(self):
        """FCP-9's facts still say alpha is free, A02 says it is waiting: the
        Runner cannot hold a 0 limit, so the slot is withdrawn, not moved."""
        records = (quota_record("alpha", availability="QUOTA_WAIT", condition=QUOTA), quota_record("beta"))
        req = allocation_request(quota=quota_request(["alpha", "beta"], records=records),
                                 observations=core_obs(cpu_free=1000))
        plan = al.allocate(req)
        self.assertEqual([plan.worker(w).capacity_decision for w in ("w0", "w1", "w2")],
                         [al.SCHEDULABLE, al.SCHEDULABLE, al.WAITING])
        self.assertEqual([plan.worker(w).decision for w in ("w0", "w1", "w2")], [al.WAITING] * 3)
        self.assertEqual(plan.allocated, ())

    def test_uncertain_or_missing_quota_evidence_is_unknown_never_ready(self):
        stale = quota_request(["alpha", "beta"], records=(quota_record("alpha", observed="2026-10-31T10:00:00Z"),
                                                          quota_record("beta")))
        plan = allocate(quota=stale)
        self.assertEqual(plan.provider_allocation("alpha").verdict, al.UNKNOWN)
        self.assertIn(al.QUOTA_EVIDENCE_UNCERTAIN, plan.worker("w0").reasons)
        self.assertEqual(plan.outcome, al.UNKNOWN)
        self.assertEqual(plan.allocated, ("w2",))
        missing = allocate(quota=quota_request(["beta"], records=(quota_record("beta"),)))
        self.assertEqual(missing.provider_allocation("alpha").verdict, al.UNKNOWN)
        self.assertEqual(missing.provider_allocation("alpha").quota_availability, None)

    def test_no_quota_evidence_at_all_holds_every_worker(self):
        plan = allocate(quota=quota_request([], records=()))
        self.assertEqual((plan.verdict, plan.headroom), (al.UNKNOWN, 0))
        self.assertIn(al.QUOTA_EVIDENCE_UNCERTAIN, plan.reasons)
        self.assertEqual(plan.allocated, ())
        self.assertEqual(plan.max_workers, 0)
        self.assertIsNone(plan.runner_max_workers)

    def test_proven_slots_and_full_capacity_hold_their_provider(self):
        records = (quota_record("alpha", slots=1), quota_record("beta", capacity="FULL"))
        plan = allocate(states={"w0": "RUNNING"}, quota=quota_request(["alpha", "beta"], records=records))
        self.assertIn(al.PROVEN_SLOTS_SATURATED, plan.provider_allocation("alpha").reasons)
        self.assertEqual(plan.provider_allocation("alpha").runner_limit, 1)
        self.assertIn(al.CAPACITY_FULL, plan.provider_allocation("beta").reasons)
        self.assertEqual(plan.allocated, ())
        self.assertEqual(plan.worker("w1").decision, al.WAITING)


# ---------------------------------------------------------------------------
# B01 resources, B02 budgets, A01 concurrency policy
# ---------------------------------------------------------------------------
class ConstraintTests(AllocationTestBase):
    def test_unknown_resources_hold_everything(self):
        plan = allocate(observations=core_obs(reliability=qc.RELIABILITY_UNVERIFIED))
        self.assertEqual((plan.verdict, plan.allocated), (al.UNKNOWN, ()))
        self.assertIn(al.RESOURCE_UNKNOWN, plan.reasons)
        self.assertTrue(all(al.RESOURCE_UNKNOWN in w.reasons for w in plan.workers))

    def test_a_demand_that_never_fits_refuses_only_its_provider(self):
        demands = core_demands(extra=(demand("cpu", rr.KIND_CPU, 9000, provider="alpha"),))
        plan = allocate(demands=demands)
        self.assertEqual(plan.provider_allocation("alpha").verdict, al.REFUSE)
        self.assertIn(al.DEMAND_EXCEEDS_CAPACITY, plan.worker("w0").reasons)
        self.assertEqual(plan.worker("w0").decision, al.REFUSED)
        self.assertEqual(plan.allocated, ("w2",))

    def test_saturated_resources_wait_at_current_occupancy(self):
        plan = allocate(states={"w0": "RUNNING"}, observations=core_obs(cpu_free=0))
        self.assertEqual((plan.verdict, plan.headroom, plan.max_workers), (al.WAIT, 0, 1))
        self.assertIn(al.RESOURCE_SATURATED, plan.reasons)
        self.assertEqual(plan.allocated, ())

    def test_provider_budget_is_sized_by_its_own_reservation(self):
        limits = (usage_limit(), usage_limit("tok-alpha", 5000, scope=qc.SCOPE_PROVIDER, provider_id="alpha"))
        budgets = (budget_request("alpha", 2000, limits=limits), budget_request("beta", 100, limits=limits))
        plan = allocate(budgets=budgets)
        alpha = plan.provider_allocation("alpha")
        self.assertEqual((alpha.verdict, alpha.headroom, alpha.limit), (al.READY, 1, 1))
        self.assertIn("r1", alpha.evidence_ids)
        self.assertEqual(plan.allocated, ("w0", "w2"))
        self.assertEqual(plan.worker("w1").decision, al.WAITING)

    def test_a_shared_budget_is_divided_by_the_largest_reservation(self):
        budgets = (budget_request("alpha", 2000), budget_request("beta", 4000))
        plan = allocate(budgets=budgets)
        self.assertEqual((plan.verdict, plan.headroom), (al.READY, 2))
        self.assertEqual(plan.allocated, ("w0", "w1"))
        self.assertEqual(plan.worker("w2").decision, al.WAITING)

    def test_a_cost_budget_is_sized_exactly_in_decimal(self):
        cost = bg.CostLimit(limit_id="money", scope=qc.SCOPE_GLOBAL, maximum=D("4.50"), window=DAY)
        tariff = bg.Tariff(tariff_id="t-tot", provider_id="alpha", unit=TOTAL, rate=D("1"), per_quantity=1000,
                           currency="EUR", effective_from_utc="2026-01-01T00:00:00Z")
        m = manifest([spec("w0"), spec("w1"), spec("w2")])
        plan = allocate(m=m, budgets=(budget_request("alpha", 1000, limits=(cost,), tariffs=(tariff,)),))
        self.assertEqual((plan.headroom, plan.allocated), (3, ("w0", "w1", "w2")))
        tight = allocate(m=m, budgets=(budget_request("alpha", 1000, limits=(dataclasses.replace(
            cost, maximum=D("3.49")),), tariffs=(tariff,)),))
        self.assertEqual((tight.headroom, tight.allocated), (1, ("w0",)))

    def test_saturated_overrun_unknown_or_missing_budgets_hold(self):
        saturated = allocate(budgets=(budget_request("alpha", 9000), budget_request("beta", 10)))
        self.assertIn(al.BUDGET_SATURATED, saturated.provider_allocation("alpha").reasons)
        self.assertEqual(saturated.allocated, ("w2",))
        overrun = allocate(budgets=(budget_request("alpha", 1, used=12_000), budget_request("beta", 1, used=12_000)))
        self.assertEqual(overrun.allocated, ())
        self.assertEqual({p.verdict for p in overrun.providers}, {al.WAIT})
        missing = allocate(budgets=(budget_request("alpha", 10),))
        self.assertIn(al.BUDGET_EVIDENCE_MISSING, missing.provider_allocation("beta").reasons)
        self.assertEqual(missing.allocated, ("w0", "w1"))
        no_receipts = allocate(budgets=(budget_request("alpha", 10, receipts=()), budget_request("beta", 10,
                                                                                               receipts=())))
        self.assertTrue(all(al.BUDGET_UNKNOWN in p.reasons for p in no_receipts.providers))
        self.assertEqual(no_receipts.allocated, ())

    def test_a_reservation_that_alone_exceeds_a_budget_is_refused(self):
        plan = allocate(budgets=(budget_request("alpha", 20_000), budget_request("beta", 10)))
        self.assertIn(al.RESERVATION_EXCEEDS_LIMIT, plan.provider_allocation("alpha").reasons)
        self.assertEqual(plan.worker("w0").decision, al.REFUSED)
        self.assertEqual(plan.allocated, ("w2",))

    def test_concurrency_policy_caps_global_and_provider_slots(self):
        plan = allocate(policy=concurrency_policy((qc.SCOPE_GLOBAL, 2, None)))
        self.assertEqual((plan.max_workers, plan.allocated), (2, ("w0", "w1")))
        per_provider = allocate(policy=concurrency_policy((qc.SCOPE_PROVIDER, 1, "alpha")))
        self.assertEqual(per_provider.allocated, ("w0", "w2"))
        saturated = allocate(states={"w0": "RUNNING"}, policy=concurrency_policy((qc.SCOPE_GLOBAL, 1, None)))
        self.assertIn(al.CONCURRENCY_LIMIT_SATURATED, saturated.reasons)
        self.assertEqual((saturated.max_workers, saturated.allocated), (1, ()))


# ---------------------------------------------------------------------------
# Output invariants
# ---------------------------------------------------------------------------
class OutputTests(AllocationTestBase):
    def test_hand_made_plans_cannot_raise_limits_or_claim_withdrawn_slots(self):
        plan = allocate(observations=core_obs(cpu_free=1000))
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, max_workers=4)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, headroom=3)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, reasons=(al.RESOURCE_SATURATED,), verdict=al.WAIT)
        alpha = plan.provider_allocation("alpha")
        with self.assertRaises(ValueError):
            dataclasses.replace(alpha, limit=alpha.base_limit + 1)
        with self.assertRaises(ValueError):
            dataclasses.replace(alpha, reasons=(al.PROVIDER_QUOTA_WAIT,), verdict=al.WAIT)
        w2 = plan.worker("w2")
        with self.assertRaises(ValueError):
            dataclasses.replace(w2, decision=al.SCHEDULABLE, slot=2)
        held = dataclasses.replace(plan.worker("w0"), reasons=(al.PROVIDER_QUOTA_WAIT,), decision=al.WAITING,
                                   slot=None)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, workers=(held,) + plan.workers[1:])
        with self.assertRaises(ValueError):
            dataclasses.replace(plan.worker("w0"), decision=al.SCHEDULABLE, reasons=(al.PROVIDER_QUOTA_WAIT,))

    def test_a_refused_plan_echoes_nothing(self):
        refused = al.allocate(None)
        self.assertEqual(json.loads(al.canonical_json(refused))["providers"], [])
        with self.assertRaises(ValueError):
            dataclasses.replace(refused, request_id="alloc-1")

    def test_every_authority_flag_is_false_by_construction(self):
        plan = allocate()
        data = json.loads(al.canonical_json(plan))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(plan, flag), False, flag)
            self.assertIs(data[flag], False, flag)
            with self.assertRaises(AttributeError):
                setattr(plan, flag, True)
        self.assertEqual(data["marker"], al.ALLOCATION_MARKER)

    def test_canonical_json_is_exact_type_deterministic_and_fingerprinted(self):
        first, second = allocate(), allocate()
        self.assertEqual(al.canonical_json(first), al.canonical_json(second))
        self.assertRegex(first.request_fingerprint, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first.request_fingerprint, allocate(request_id="alloc-2").request_fingerprint)
        with self.assertRaises(TypeError):
            al.canonical_json(dataclasses.asdict(first))


# ---------------------------------------------------------------------------
# Purity and governed surface
# ---------------------------------------------------------------------------
class PurityTests(AllocationTestBase):
    def test_allocation_never_mutates_inputs(self):
        req = allocation_request(budgets=(budget_request("alpha", 10), budget_request("beta", 10)),
                                 policy=concurrency_policy((qc.SCOPE_GLOBAL, 3, None)))
        before = copy.deepcopy(req)
        al.allocate(req)
        self.assertEqual(req, before)
        self.assertEqual((req.capacity_request.manifest.max_workers, req.capacity_request.manifest.provider_limits),
                         (4, {}))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            req.request_id = "x"

    def test_no_io_process_network_runner_or_director_entry_point(self):
        req = allocation_request(budgets=(budget_request("alpha", 10), budget_request("beta", 10)))
        boom = AssertionError("I/O or execution entry point")
        patches = [mock.patch.object(subprocess, "Popen", side_effect=boom),
                   mock.patch.object(builtins, "open", side_effect=boom),
                   mock.patch.object(socket, "socket", side_effect=boom),
                   mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom),
                   mock.patch.object(rp.PipelineRunner, "_start_ready", side_effect=boom),
                   mock.patch.object(rp.PipelineRunner, "_launch", side_effect=boom),
                   mock.patch.object(rp.DirLease, "try_acquire", side_effect=boom),
                   mock.patch.object(fd.FabricDirectorService, "run_blueprint", side_effect=boom),
                   mock.patch.object(Path, "exists", side_effect=boom),
                   mock.patch.object(Path, "resolve", side_effect=boom)]
        for patch in patches:
            patch.start()
        try:
            plan = al.allocate(req)
            al.canonical_json(plan)
        finally:
            for patch in reversed(patches):
                patch.stop()
        self.assertEqual(plan.verdict, al.READY)

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_resource_quota_budget", "fabric_resource_quota_contract", "fabric_resource_quota_observation",
               "fabric_resource_quota_resource", "fabric_scheduler_capacity", "fabric_scheduler_contract",
               "fabric_scheduler_window")
        self.assertEqual(imported, {"__future__", "dataclasses", "decimal", "hashlib", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "DirLease", "lease_dir", "ledger", "_launch", "_start_ready", "run_blueprint", "fabric_director",
                     "parse_manifest", "plan_dag(", ".now(", "utcnow", "time.", "sleep", "while ", "claude", "codex",
                     "eval(", "exec(", "importlib", "random", "requests.", "urllib", "environ", "psutil", "cookie",
                     "keyring", "customer", "fallback_providers"):
            self.assertNotIn(word, code, word)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_mutable_module_state_changes(self):
        modules = (al, qc, qo, rr, bg, cap)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        allocate()
        allocate(budgets=(budget_request("alpha", 9000), budget_request("beta", 10)))
        al.allocate(None)
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_reused(self):
        for vocab in (al.REQUEST_REASONS, al.RESULT_REASONS, al.QUOTA_HOLD_REASONS):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(al.REQUEST_REASONS) & set(al.RESULT_REASONS))
        self.assertEqual(al.VERDICTS, qc.VERDICTS)
        self.assertEqual((al.DECISIONS, al.OUTCOMES), (cap.DECISIONS, cap.OUTCOMES))
        self.assertEqual(al.MAX_WORKERS, rp.MAX_PIPELINE_WORKERS)
        self.assertIn(al.PROVIDER_AUTH_BLOCKED, qc.REFUSING_REASONS)
        self.assertIn(al.PROVIDER_QUOTA_WAIT, qc.WAITING_REASONS)
        self.assertIn(al.CAPACITY_FULL, cap.PROVIDER_HELD_REASONS)
        self.assertEqual((al.DEMAND_EXCEEDS_CAPACITY, al.RESOURCE_SATURATED),
                         (rr.DEMAND_EXCEEDS_CAPACITY, rr.RESOURCE_SATURATED))
        self.assertTrue(set(al.QUOTA_HOLD_REASONS) <= set(al.RESULT_REASONS))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
