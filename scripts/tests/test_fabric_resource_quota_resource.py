"""FCP-10B-01: Host / Runner resource inventory and constraints.

Manifests are native `runner_pipeline.Manifest`s, capacity plans are produced
by the real FCP-9C-01 `evaluate_capacity` and conflict graphs by the real
FCP-9B-01 `analyze_conflicts`; worktrees are synthetic lexical paths under a
root that never exists. Host observations are synthetic injected values:
nothing probes the host, executes, reserves, buys or sends anything.
Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_resource_quota_resource as rr
from scripts.ai import fabric_scheduler_capacity as cap
from scripts.ai import fabric_scheduler_conflicts as cf
from scripts.ai import runner_pipeline as rp

MODULE_PATH = Path(rr.__file__)
TEST_PATH = Path(__file__).resolve()
ROOT = "/fcp10b01-synthetic"
AS_OF = "2026-10-31T12:00:00Z"
OBSERVED = "2026-10-31T11:59:30Z"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "reservation_held",
             "quota_authority", "purchase_allowed", "remote_api_allowed", "lock_acquired", "lease_acquired",
             "host_probed")


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def spec(wid, provider="alpha", worktree=None, mode="read-only", **extra):
    top = f"{ROOT}/{worktree or wid}"
    return rp.WorkerSpec(id=wid, worktree=top, work_order=f"{ROOT}/wo_{wid}.md", provider=provider, mode=mode,
                         worktree_top=top, **extra)


def manifest(specs=None, pipeline_id="fcp10b01-dag", max_workers=4, **extra):
    specs = specs if specs is not None else [spec("w0"), spec("w1"), spec("w2")]
    return rp.Manifest(pipeline_id=pipeline_id, workers=list(specs), max_workers=max_workers, **extra)


def plan_for(m, states=None, **kw):
    """A real FCP-9C-01 plan; workers are QUEUED unless stated otherwise
    ("UNOBSERVED": no item at all, so FCP-9C-01 counts it as occupying)."""
    states = states or {}
    items = tuple(cap.CapacityItem(s.id, states.get(s.id, "QUEUED")) for s in m.workers
                  if states.get(s.id) != "UNOBSERVED")
    providers = sorted({p for s in m.workers for p in [s.provider] + list(s.fallback_providers)})
    facts = tuple(cap.ProviderCapacityFacts(p, "NONE", "AVAILABLE", cap.MAX_WORKERS, OBSERVED) for p in providers)
    return cap.evaluate_capacity(cap.CapacityRequest(manifest=m, as_of_utc=AS_OF, items=items, provider_facts=facts,
                                                     **kw))


def graph_for(m, worktrees=None, dag_id=None):
    worktrees = worktrees or {}
    workers = tuple(cf.WorkerClaims(worker_id=s.id, mode=s.mode, worktree=worktrees.get(s.id, s.worktree_top),
                                    worktree_link_state=cf.LINK_NONE) for s in m.workers)
    return cf.analyze_conflicts(cf.ConflictRequest(dag_id=dag_id or m.pipeline_id, allowed_roots=(ROOT,),
                                                   workers=workers))


def obs(evidence_id, resource_id, kind, capacity, in_use=0, reserve=0, source=rr.SOURCE_CALLER_HOST_SNAPSHOT,
        reliability=qc.RELIABILITY_CALLER_OBSERVED, observed=OBSERVED, unit=None):
    return rr.HostResourceObservation(
        evidence_id=evidence_id, resource_id=resource_id, kind=kind, unit=rr.KIND_UNIT.get(kind) if unit is None
        else unit, capacity=capacity, in_use=in_use, reserve=reserve, source=source, reliability=reliability,
        observed_at_utc=observed)


def demand(resource_id, kind, amount, provider=None, unit=None):
    return rr.ResourceDemand(resource_id=resource_id, kind=kind,
                             unit=rr.KIND_UNIT.get(kind) if unit is None else unit, amount=amount,
                             provider_id=provider)


def core_obs(cpu=(8000, 2000, 1000), mem=(16384, 4096, 2048), proc=(1000, 300, 100)):
    """CPU 5000 free, MEMORY 10240 free, PROCESS_SLOTS 600 free by default."""
    return (obs("o-cpu", "cpu", rr.KIND_CPU, *cpu), obs("o-mem", "mem", rr.KIND_MEMORY, *mem),
            obs("o-proc", "proc", rr.KIND_PROCESS_SLOTS, *proc))


def core_demands(cpu=2000, mem=4096, proc=20):
    return (demand("cpu", rr.KIND_CPU, cpu), demand("mem", rr.KIND_MEMORY, mem),
            demand("proc", rr.KIND_PROCESS_SLOTS, proc))


def request(m=None, plan=None, observations=None, demands=None, **kw):
    m = manifest() if m is None else m
    fields = dict(request_id="res-1", as_of_utc=AS_OF, manifest=m, capacity_plan=plan_for(m) if plan is None else plan,
                  observations=core_obs() if observations is None else observations,
                  demands=core_demands() if demands is None else demands)
    fields.update(kw)
    return rr.ResourceRequest(**fields)


def evaluate(**kw):
    return rr.evaluate_resources(request(**kw))


class ResourceTestBase(unittest.TestCase):
    def assertRefused(self, evaluation, *codes):
        self.assertEqual(evaluation.verdict, rr.REFUSE)
        for code in codes:
            self.assertIn(code, evaluation.request_reasons)
        self.assertEqual((evaluation.request_id, evaluation.max_workers, evaluation.providers, evaluation.resources,
                          evaluation.reasons, evaluation.evidence_ids), (None, None, (), (), (), ()))
        return evaluation

    def assertHolds(self, evaluation, verdict, *codes):
        """Not READY: no new start anywhere the reasons apply."""
        self.assertEqual(evaluation.verdict, verdict)
        for code in codes:
            self.assertIn(code, evaluation.reasons)
        self.assertEqual(evaluation.headroom, 0)
        self.assertEqual(evaluation.max_workers, min(evaluation.base_max_workers, evaluation.occupied_slots))
        return evaluation


# ---------------------------------------------------------------------------
# Request validation (fail closed, nothing echoed)
# ---------------------------------------------------------------------------
class RequestTests(ResourceTestBase):
    def test_untyped_requests_are_refused_without_raising(self):
        for bad in (None, {}, "res-1", request().__dict__):
            self.assertRefused(rr.evaluate_resources(bad), rr.REQUEST_NOT_TYPED)

        class Sub(rr.ResourceRequest):
            pass

        self.assertRefused(rr.evaluate_resources(Sub(**request().__dict__)), rr.REQUEST_NOT_TYPED)

    def test_request_scalars_are_exact_and_strict_utc(self):
        self.assertRefused(evaluate(request_id="Bad Id"), rr.REQUEST_ID_INVALID)
        self.assertRefused(evaluate(as_of_utc="2026-10-31T13:00:00+01:00"), rr.AS_OF_INVALID)
        self.assertRefused(evaluate(as_of_utc="2026-10-31T12:00:00"), rr.AS_OF_INVALID)
        self.assertRefused(evaluate(schema_version=True), rr.SCHEMA_VERSION_UNSUPPORTED)
        for age in (0, True, qc.MAX_EVIDENCE_AGE_SECONDS + 1, 1.0):
            self.assertRefused(evaluate(max_evidence_age_seconds=age), rr.MAX_EVIDENCE_AGE_INVALID)

    def test_manifest_must_be_native_and_valid(self):
        m = manifest()
        self.assertRefused(evaluate(m=m, manifest={"pipeline_id": "x"}), rr.MANIFEST_NOT_TYPED)
        broken = dataclasses.replace(m, max_workers=0)
        self.assertRefused(evaluate(m=m, manifest=broken), rr.MANIFEST_INVALID)

    def test_capacity_plan_must_be_a_real_plan_of_the_same_manifest(self):
        m = manifest()
        self.assertRefused(evaluate(m=m, plan=plan_for(m).to_dict()), rr.CAPACITY_PLAN_NOT_TYPED)
        self.assertRefused(evaluate(m=m, plan=cap.evaluate_capacity(None)), rr.CAPACITY_PLAN_REFUSED)
        other = manifest(pipeline_id="other-dag")
        self.assertRefused(evaluate(m=m, plan=plan_for(other)), rr.CAPACITY_PLAN_MISMATCH)
        fewer = manifest([spec("w0"), spec("w1")])
        self.assertRefused(evaluate(m=m, plan=plan_for(fewer)), rr.CAPACITY_PLAN_MISMATCH)

    def test_a_plan_above_the_manifest_limits_is_refused(self):
        wide = manifest(max_workers=8, provider_limits={"alpha": 6})
        narrow = manifest(max_workers=2)
        self.assertRefused(evaluate(m=narrow, plan=plan_for(wide)), rr.CAPACITY_PLAN_EXCEEDS_MANIFEST)
        limited = manifest(max_workers=8, provider_limits={"alpha": 3})
        self.assertRefused(evaluate(m=limited, plan=plan_for(wide)), rr.CAPACITY_PLAN_EXCEEDS_MANIFEST)
        default = manifest(max_workers=None)
        self.assertRefused(evaluate(m=default, plan=plan_for(wide)), rr.CAPACITY_PLAN_EXCEEDS_MANIFEST)
        self.assertEqual(evaluate(m=default).base_max_workers, rp.DEFAULT_MAX_WORKERS)

    def test_conflict_graph_must_be_typed_identified_dag_and_not_refused(self):
        m = manifest()
        self.assertRefused(evaluate(m=m, conflict_graph=graph_for(m).to_dict()), rr.CONFLICT_GRAPH_NOT_TYPED)
        self.assertRefused(evaluate(m=m, conflict_graph=cf.analyze_conflicts(None)), rr.CONFLICT_GRAPH_REFUSED)
        self.assertRefused(evaluate(m=m, conflict_graph=graph_for(manifest(pipeline_id="other-dag"))),
                           rr.CONFLICT_GRAPH_MISMATCH)

    def test_observations_always_carry_unit_amounts_source_quality_and_utc(self):
        cpu = rr.KIND_CPU
        cases = (
            ([obs("o-x", "cpu", cpu, 1)], rr.OBSERVATIONS_MALFORMED),
            ((obs("o-x", "cpu", "GPU", 1),), rr.OBSERVATION_KIND_UNKNOWN),
            ((obs("o-x", "cpu", cpu, 1, unit=rr.UNIT_MEMORY_MIB),), rr.OBSERVATION_UNIT_MISMATCH),
            ((obs("o-x", "cpu", cpu, 1, unit=None.__class__.__name__),), rr.OBSERVATION_UNIT_MISMATCH),
            ((obs("o-x", "cpu", cpu, -1),), rr.OBSERVATION_AMOUNT_INVALID),
            ((obs("o-x", "cpu", cpu, 8, in_use=True),), rr.OBSERVATION_AMOUNT_INVALID),
            ((obs("o-x", "cpu", cpu, 8, reserve=None),), rr.OBSERVATION_AMOUNT_INVALID),
            ((obs("o-x", "cpu", cpu, rr.UNIT_MAXIMUM[rr.UNIT_CPU_MILLICORES] + 1),), rr.OBSERVATION_AMOUNT_INVALID),
            ((obs("o-x", "cpu", cpu, 8, source=qc.SOURCE_ROUTER_PROVIDER_FACTS),), rr.OBSERVATION_SOURCE_UNKNOWN),
            ((obs("o-x", "cpu", cpu, 8, reliability="TRUSTED"),), rr.OBSERVATION_RELIABILITY_UNKNOWN),
            ((obs("o-x", "cpu", cpu, 8, reliability=qc.RELIABILITY_RUNNER_CLASSIFIED),),
             rr.OBSERVATION_RELIABILITY_OVERCLAIMED),
            ((obs("o-x", "cpu", cpu, 8, source=rr.SOURCE_OPERATOR_DECLARATION),),
             rr.OBSERVATION_RELIABILITY_OVERCLAIMED),
            ((obs("o-x", "cpu", cpu, 8, observed="2026-10-31T11:59:30+02:00"),), rr.OBSERVATION_TIME_INVALID),
            ((obs("o-x", "cpu", cpu, 8, observed=None),), rr.OBSERVATION_TIME_INVALID),
            ((obs("O X", "cpu", cpu, 8),), rr.OBSERVATION_ID_INVALID),
            ((obs("o-x", "CPU 0", cpu, 8),), rr.OBSERVATION_RESOURCE_INVALID),
        )
        for observations, code in cases:
            with self.subTest(code=code):
                self.assertRefused(evaluate(observations=observations), code)

    def test_demands_are_explicit_typed_and_unambiguous(self):
        mem = rr.KIND_MEMORY
        self.assertRefused(evaluate(demands=()), rr.DEMANDS_EMPTY)
        self.assertRefused(evaluate(demands=list(core_demands())), rr.DEMANDS_MALFORMED)
        self.assertRefused(evaluate(demands=core_demands() + ("mem",)), rr.DEMANDS_MALFORMED)
        self.assertRefused(evaluate(demands=(demand("mem", mem, 0),)), rr.DEMAND_AMOUNT_INVALID)
        self.assertRefused(evaluate(demands=(demand("mem", mem, True),)), rr.DEMAND_AMOUNT_INVALID)
        self.assertRefused(evaluate(demands=(demand("mem", mem, 1, unit=rr.UNIT_PROCESSES),)),
                           rr.DEMAND_UNIT_MISMATCH)
        self.assertRefused(evaluate(demands=(demand("mem", "RAM", 1),)), rr.DEMAND_KIND_UNKNOWN)
        self.assertRefused(evaluate(demands=(demand("Mem!", mem, 1),)), rr.DEMAND_RESOURCE_INVALID)
        self.assertRefused(evaluate(demands=core_demands() + (demand("mem", mem, 1, provider="zeta"),)),
                           rr.DEMAND_PROVIDER_UNKNOWN)
        self.assertRefused(evaluate(demands=core_demands() + (demand("mem", mem, 1),)), rr.DEMAND_DUPLICATE)
        self.assertRefused(evaluate(demands=core_demands() + (demand("cpu", mem, 1, provider="alpha"),)),
                           rr.RESOURCE_KIND_AMBIGUOUS)

    def test_identifiers_are_unique_and_never_secret_shaped(self):
        self.assertRefused(evaluate(request_id="sk-abcdef123456"), rr.ID_SECRET_SHAPED)
        self.assertRefused(evaluate(observations=core_obs() + (obs("a" * 40, "gpu", rr.KIND_SPECIAL, 1),)),
                           rr.ID_SECRET_SHAPED)
        self.assertRefused(evaluate(observations=core_obs() + (obs("o-cpu", "cpu", rr.KIND_CPU, 8000),)),
                           rr.ID_DUPLICATE)
        self.assertRefused(evaluate(request_id="o-mem"), rr.ID_DUPLICATE)


# ---------------------------------------------------------------------------
# Narrowing (never raises a limit)
# ---------------------------------------------------------------------------
class NarrowingTests(ResourceTestBase):
    def test_fresh_certain_resources_narrow_to_occupied_plus_headroom(self):
        m = manifest()
        result = evaluate(m=m, plan=plan_for(m, {"w0": "RUNNING", "w1": "QUEUED", "w2": "QUEUED"}))
        self.assertEqual(result.verdict, rr.READY)
        self.assertEqual((result.base_max_workers, result.occupied_slots, result.headroom, result.max_workers),
                         (4, 1, 2, 3))
        self.assertEqual(result.provider_limits, (("alpha", 3),))
        self.assertEqual(result.evidence_ids, ("o-cpu", "o-mem", "o-proc"))
        self.assertEqual(result.resource_view("cpu").free, 8000 - 2000 - 1000)
        self.assertTrue(result.runner_representable)

    def test_abundant_resources_never_raise_the_manifest_or_plan(self):
        roomy = core_obs(cpu=(1_000_000, 0, 0), mem=(16_000_000, 0, 0), proc=(4_000_000, 0, 0))
        m = manifest(max_workers=3)
        result = evaluate(m=m, observations=roomy, demands=core_demands(1, 1, 1))
        self.assertEqual((result.headroom, result.max_workers), (rr.MAX_WORKERS, 3))
        narrowed = evaluate(m=m, plan=plan_for(m, max_workers=2), observations=roomy, demands=core_demands(1, 1, 1))
        self.assertEqual((narrowed.base_max_workers, narrowed.max_workers), (2, 2))
        self.assertEqual(narrowed.provider_budget("alpha").limit, 2)

    def test_provider_limits_of_the_manifest_bound_each_provider(self):
        m = manifest([spec("w0"), spec("w1", provider="beta")], provider_limits={"alpha": 1})
        result = evaluate(m=m)
        self.assertEqual(result.provider_budget("alpha").base_limit, 1)
        self.assertEqual(result.provider_limits, (("alpha", 1), ("beta", 2)))
        self.assertEqual(result.max_workers, 2)

    def test_largest_demand_of_any_provider_bounds_the_global_headroom(self):
        m = manifest([spec("w0"), spec("w1", provider="beta")], max_workers=8)
        demands = core_demands(cpu=500, mem=1024) + (demand("mem", rr.KIND_MEMORY, 5120, provider="beta"),)
        result = evaluate(m=m, demands=demands)
        self.assertEqual(result.provider_budget("alpha").headroom, 10)
        self.assertEqual(result.provider_budget("beta").headroom, 2)
        self.assertEqual((result.headroom, result.max_workers), (2, 2))
        self.assertEqual(result.provider_budget("beta").resource_ids, ("cpu", "mem", "proc"))

    def test_reserve_is_never_handed_out(self):
        result = evaluate(observations=core_obs(mem=(16384, 4096, 10240)))
        self.assertHolds(result, rr.WAIT, rr.RESOURCE_SATURATED)
        self.assertEqual(result.resource_view("mem").free, 2048)
        over = evaluate(observations=core_obs(mem=(16384, 10000, 10000)))
        self.assertEqual(over.resource_view("mem").free, 0)

    def test_saturation_waits_with_zero_new_starts(self):
        m = manifest()
        result = evaluate(m=m, plan=plan_for(m, {"w0": "RUNNING", "w1": "QUEUED", "w2": "QUEUED"}),
                          observations=core_obs(cpu=(8000, 6500, 0)))
        self.assertHolds(result, rr.WAIT, rr.RESOURCE_SATURATED)
        self.assertEqual((result.max_workers, result.provider_limits), (1, (("alpha", 1),)))
        self.assertTrue(result.runner_representable)
        idle = evaluate(observations=core_obs(cpu=(8000, 6500, 0)))
        self.assertHolds(idle, rr.WAIT, rr.RESOURCE_SATURATED)
        self.assertEqual((idle.max_workers, idle.provider_limits), (0, (("alpha", 0),)))
        self.assertFalse(idle.runner_representable)

    def test_process_slots_and_special_units_constrain_like_any_resource(self):
        result = evaluate(observations=core_obs(proc=(100, 55, 5)), demands=core_demands(proc=20))
        self.assertEqual((result.headroom, result.max_workers), (2, 2))
        m = manifest()
        gpu = core_obs() + (obs("o-gpu", "gpu", rr.KIND_SPECIAL, 1),)
        special = evaluate(m=m, observations=gpu, demands=core_demands() + (demand("gpu", rr.KIND_SPECIAL, 1),),
                           conflict_graph=graph_for(m))
        self.assertEqual((special.verdict, special.headroom, special.max_workers), (rr.READY, 1, 1))

    def test_demand_above_capacity_minus_reserve_is_refused_per_provider(self):
        m = manifest([spec("w0"), spec("w1", provider="beta")])
        demands = core_demands() + (demand("mem", rr.KIND_MEMORY, 15000, provider="beta"),)
        result = evaluate(m=m, demands=demands)
        beta = result.provider_budget("beta")
        self.assertEqual((beta.verdict, beta.reasons, beta.limit), (rr.REFUSE, (rr.DEMAND_EXCEEDS_CAPACITY,), 0))
        self.assertEqual((result.verdict, result.headroom), (rr.READY, 2))
        everyone = evaluate(m=m, demands=core_demands(mem=15000))
        self.assertHolds(everyone, rr.REFUSE, rr.DEMAND_EXCEEDS_CAPACITY)

    def test_occupancy_is_the_plans_including_unobserved_workers(self):
        m = manifest()
        plan = plan_for(m, {"w0": "RUNNING", "w1": "UNOBSERVED", "w2": "QUEUED"})
        self.assertEqual(plan.occupied_slots, 2)
        result = evaluate(m=m, plan=plan)
        self.assertEqual((result.occupied_slots, result.max_workers), (2, 4))
        self.assertEqual(result.provider_budget("alpha").occupied, 2)

    def test_repeated_observations_aggregate_most_restrictively(self):
        repeated = core_obs() + (obs("o-cpu-2", "cpu", rr.KIND_CPU, 8000, 4000, 0, observed="2026-10-31T11:59:50Z"),
                                 obs("o-cpu-3", "cpu", rr.KIND_CPU, 8000, 1000, 1500))
        result = evaluate(observations=repeated)
        view = result.resource_view("cpu")
        self.assertEqual((view.in_use, view.reserve, view.free), (4000, 1500, 2500))
        self.assertEqual(view.evidence_ids, ("o-cpu", "o-cpu-2", "o-cpu-3"))
        self.assertEqual(result.headroom, 1)

    def test_narrowed_values_are_accepted_by_the_runners_own_manifest_rules(self):
        m = manifest([spec("w0"), spec("w1", provider="beta")], provider_limits={"beta": 3})
        result = evaluate(m=m)
        narrowed = dataclasses.replace(m, max_workers=result.max_workers, provider_limits=dict(result.provider_limits))
        self.assertEqual(cap._manifest_reasons(narrowed), set())
        self.assertLessEqual(result.max_workers, m.max_workers)
        for provider, limit in result.provider_limits:
            self.assertLessEqual(limit, m.provider_limits.get(provider, m.max_workers))


# ---------------------------------------------------------------------------
# Fail closed: unknown, stale, future, unverified, contradictory
# ---------------------------------------------------------------------------
class FailClosedTests(ResourceTestBase):
    def test_an_unobserved_demanded_resource_is_unknown(self):
        m = manifest()
        result = evaluate(m=m, plan=plan_for(m, {"w0": "RUNNING", "w1": "QUEUED", "w2": "QUEUED"}),
                          observations=core_obs()[:2])
        self.assertHolds(result, rr.UNKNOWN, rr.NO_EVIDENCE)
        self.assertEqual(result.resource_view("proc").reasons, (rr.NO_EVIDENCE,))
        self.assertEqual(result.resource_view("proc").free, None)
        self.assertEqual(result.max_workers, 1)

    def test_stale_evidence_is_unknown_and_the_boundary_is_fresh(self):
        stale = core_obs()[:2] + (obs("o-proc", "proc", rr.KIND_PROCESS_SLOTS, 1000, observed="2026-10-31T11:44:59Z"),)
        self.assertHolds(evaluate(observations=stale), rr.UNKNOWN, rr.EVIDENCE_STALE)
        edge = core_obs()[:2] + (obs("o-proc", "proc", rr.KIND_PROCESS_SLOTS, 1000, observed="2026-10-31T11:45:00Z"),)
        self.assertEqual(evaluate(observations=edge).verdict, rr.READY)
        self.assertHolds(evaluate(max_evidence_age_seconds=10), rr.UNKNOWN, rr.EVIDENCE_STALE)

    def test_future_dated_evidence_is_unknown(self):
        future = core_obs()[1:] + (obs("o-cpu", "cpu", rr.KIND_CPU, 8000, observed="2026-10-31T12:00:01Z"),)
        result = self.assertHolds(evaluate(observations=future), rr.UNKNOWN, rr.EVIDENCE_FROM_FUTURE)
        self.assertEqual(result.resource_view("cpu").reasons, (rr.EVIDENCE_FROM_FUTURE,))

    def test_unverified_quality_never_enables_capacity(self):
        declared = core_obs()[1:] + (obs("o-cpu", "cpu", rr.KIND_CPU, 64000, source=rr.SOURCE_OPERATOR_DECLARATION,
                                         reliability=qc.RELIABILITY_UNVERIFIED),)
        self.assertHolds(evaluate(observations=declared), rr.UNKNOWN, rr.EVIDENCE_UNVERIFIED)
        modest = core_obs()[1:] + (obs("o-cpu", "cpu", rr.KIND_CPU, 64000, reliability=qc.RELIABILITY_UNVERIFIED),)
        self.assertHolds(evaluate(observations=modest), rr.UNKNOWN, rr.EVIDENCE_UNVERIFIED)

    def test_contradictory_states_are_unknown_never_most_favourable(self):
        impossible = core_obs(mem=(16384, 20000, 0))
        self.assertHolds(evaluate(observations=impossible), rr.UNKNOWN, rr.EVIDENCE_CONTRADICTORY)
        disagreeing = core_obs() + (obs("o-mem-2", "mem", rr.KIND_MEMORY, 32768),)
        result = self.assertHolds(evaluate(observations=disagreeing), rr.UNKNOWN, rr.EVIDENCE_CONTRADICTORY)
        self.assertEqual(result.resource_view("mem").capacity, None)

    def test_every_provider_must_declare_cpu_memory_and_process_slots(self):
        result = evaluate(demands=core_demands()[:2])
        self.assertHolds(result, rr.UNKNOWN, rr.DEMAND_UNDECLARED)
        m = manifest([spec("w0"), spec("w1", provider="beta")])
        only_alpha = (demand("cpu", rr.KIND_CPU, 1, provider="alpha"), demand("mem", rr.KIND_MEMORY, 1, provider="alpha"),
                      demand("proc", rr.KIND_PROCESS_SLOTS, 1, provider="alpha"))
        partial = evaluate(m=m, demands=only_alpha)
        self.assertEqual(partial.provider_budget("alpha").verdict, rr.READY)
        self.assertEqual(partial.provider_budget("beta").reasons, (rr.DEMAND_UNDECLARED,))
        self.assertHolds(partial, rr.UNKNOWN, rr.DEMAND_UNDECLARED)

    def test_an_uncertain_resource_nobody_demands_is_informational(self):
        extra = core_obs() + (obs("o-gpu", "gpu", rr.KIND_SPECIAL, 1, observed="2026-10-30T00:00:00Z"),)
        result = evaluate(observations=extra)
        self.assertEqual(result.verdict, rr.READY)
        self.assertEqual(result.resource_view("gpu").reasons, (rr.EVIDENCE_STALE,))
        self.assertNotIn("o-gpu", result.evidence_ids)

    def test_one_providers_doubt_holds_the_global_ceiling(self):
        m = manifest([spec("w0"), spec("w1", provider="beta")])
        demands = core_demands() + (demand("scratch", rr.KIND_MEMORY, 1, provider="beta"),)
        result = evaluate(m=m, demands=demands)
        self.assertEqual(result.provider_budget("alpha").verdict, rr.READY)
        self.assertEqual(result.provider_budget("beta").reasons, (rr.NO_EVIDENCE,))
        self.assertHolds(result, rr.UNKNOWN, rr.NO_EVIDENCE)

    def test_refusal_needs_certain_evidence(self):
        stale_small = core_obs()[:2] + (obs("o-proc", "proc", rr.KIND_PROCESS_SLOTS, 1,
                                            observed="2026-10-30T00:00:00Z"),)
        result = evaluate(observations=stale_small, demands=core_demands(proc=50))
        self.assertHolds(result, rr.UNKNOWN, rr.EVIDENCE_STALE)
        self.assertNotIn(rr.DEMAND_EXCEEDS_CAPACITY, result.reasons)


# ---------------------------------------------------------------------------
# Shared resources and FCP-9B-01 conflicts
# ---------------------------------------------------------------------------
class ConflictTests(ResourceTestBase):
    def gpu(self):
        return (core_obs() + (obs("o-gpu", "gpu", rr.KIND_SPECIAL, 2),),
                core_demands() + (demand("gpu", rr.KIND_SPECIAL, 1),))

    def test_a_shared_resource_needs_the_conflict_analysis(self):
        observations, demands = self.gpu()
        result = evaluate(observations=observations, demands=demands)
        self.assertHolds(result, rr.UNKNOWN, rr.CONFLICTS_UNASSESSED)
        self.assertEqual(result.conflict_outcome, None)

    def test_an_unidentified_conflict_graph_holds_the_shared_resource(self):
        m = manifest()
        observations, demands = self.gpu()
        graph = graph_for(m, worktrees={"w1": None})
        self.assertEqual(graph.outcome, cf.UNKNOWN)
        result = evaluate(m=m, observations=observations, demands=demands, conflict_graph=graph)
        self.assertHolds(result, rr.UNKNOWN, rr.CONFLICT_UNIDENTIFIED)
        self.assertEqual(result.conflict_outcome, cf.UNKNOWN)

    def test_identified_conflicts_are_echoed_and_never_relaxed(self):
        m = manifest([spec("w0"), spec("w1", worktree="w0", mode="write"), spec("w2")])
        graph = graph_for(m)
        self.assertEqual(graph.outcome, cf.CONFLICTS)
        observations, demands = self.gpu()
        result = evaluate(m=m, observations=observations, demands=demands, conflict_graph=graph)
        self.assertEqual((result.verdict, result.conflict_outcome, result.max_workers), (rr.READY, cf.CONFLICTS, 2))
        self.assertFalse(graph.compatible("w0", "w1"))
        self.assertFalse(hasattr(result, "compatible"))

    def test_without_a_shared_resource_the_graph_is_only_echoed(self):
        m = manifest()
        graph = graph_for(m, worktrees={"w1": None})
        result = evaluate(m=m, conflict_graph=graph)
        self.assertEqual((result.verdict, result.conflict_outcome), (rr.READY, cf.UNKNOWN))


# ---------------------------------------------------------------------------
# Output invariants
# ---------------------------------------------------------------------------
class OutputTests(ResourceTestBase):
    def test_evaluation_rederives_and_never_raises_a_limit(self):
        result = evaluate()
        with self.assertRaises(ValueError):
            dataclasses.replace(result, max_workers=result.base_max_workers + 1)
        with self.assertRaises(ValueError):
            dataclasses.replace(result, base_max_workers=result.base_max_workers + 1,
                                max_workers=result.max_workers + 1)
        with self.assertRaises(ValueError):
            dataclasses.replace(result, verdict=rr.WAIT)
        with self.assertRaises(ValueError):
            dataclasses.replace(result, evidence_ids=())
        waiting = evaluate(observations=core_obs(cpu=(8000, 8000, 0)))
        with self.assertRaises(ValueError):
            dataclasses.replace(waiting, headroom=1, max_workers=1)
        with self.assertRaises(ValueError):
            dataclasses.replace(waiting, reasons=(), verdict=rr.READY)

    def test_provider_budgets_and_views_refuse_overclaims(self):
        budget = evaluate().provider_budget("alpha")
        with self.assertRaises(ValueError):
            dataclasses.replace(budget, limit=budget.base_limit + 1)
        with self.assertRaises(ValueError):
            dataclasses.replace(budget, reasons=(rr.EVIDENCE_STALE,), verdict=rr.UNKNOWN)
        with self.assertRaises(ValueError):
            dataclasses.replace(budget, base_limit=rr.MAX_WORKERS + 1, limit=budget.limit)
        view = evaluate().resource_view("cpu")
        with self.assertRaises(ValueError):
            dataclasses.replace(view, free=view.free + 1)
        with self.assertRaises(ValueError):
            dataclasses.replace(view, reasons=(rr.EVIDENCE_STALE,))
        with self.assertRaises(ValueError):
            dataclasses.replace(view, unit=rr.UNIT_MEMORY_MIB)
        with self.assertRaises(ValueError):
            dataclasses.replace(view, evidence_ids=())
        loose = dataclasses.replace(evaluate().provider_budget("alpha"), base_limit=4, limit=2)
        with self.assertRaises(ValueError):  # a provider base above the global base
            dataclasses.replace(evaluate(m=manifest(max_workers=2)), providers=(loose,))

    def test_a_refused_evaluation_echoes_nothing(self):
        refused = rr.evaluate_resources(None)
        with self.assertRaises(ValueError):
            dataclasses.replace(refused, max_workers=1)
        with self.assertRaises(ValueError):
            dataclasses.replace(refused, request_reasons=())
        self.assertFalse(refused.runner_representable)

    def test_every_authority_flag_is_false_by_construction(self):
        for result in (evaluate(), evaluate(observations=()), rr.evaluate_resources(None)):
            data = json.loads(rr.canonical_json(result))
            self.assertEqual(data["marker"], rr.RESOURCE_MARKER)
            for flag in ALL_FLAGS:
                self.assertIs(getattr(result, flag), False, flag)
                self.assertIs(data[flag], False, flag)
                self.assertNotIn(flag, {f.name for f in dataclasses.fields(result)})
                with self.assertRaises(AttributeError):
                    setattr(result, flag, True)

    def test_canonical_json_is_exact_type_deterministic_and_bounded(self):
        first = evaluate()
        again = evaluate(observations=tuple(reversed(core_obs())), demands=tuple(reversed(core_demands())))
        self.assertEqual(rr.canonical_json(first), rr.canonical_json(again))
        self.assertEqual(json.loads(rr.canonical_json(first))["schema"], rr.SCHEMA)
        offset = evaluate(as_of_utc="2026-10-31T12:00:00+00:00")
        self.assertEqual(offset.request_fingerprint, first.request_fingerprint)
        self.assertNotEqual(evaluate(as_of_utc="2026-10-31T12:00:01Z").request_fingerprint, first.request_fingerprint)
        with self.assertRaises(TypeError):
            rr.canonical_json(first.to_dict())
        self.assertEqual(rr.validate_request(request()), ())


# ---------------------------------------------------------------------------
# Purity and governance
# ---------------------------------------------------------------------------
class PurityTests(ResourceTestBase):
    def test_evaluation_never_mutates_inputs(self):
        m = manifest()
        req = request(m=m, conflict_graph=graph_for(m))
        before = copy.deepcopy(req)
        rr.evaluate_resources(req)
        self.assertEqual(req, before)
        self.assertEqual((m.max_workers, m.provider_limits), (4, {}))
        for obj in (req, req.observations[0], req.demands[0]):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(obj, dataclasses.fields(obj)[0].name, "x")

    def test_no_host_probe_io_process_network_clock_or_runner_entry_point(self):
        m = manifest()
        req = request(m=m, conflict_graph=graph_for(m))
        boom = AssertionError("I/O, probe or execution entry point")
        patches = [mock.patch.object(subprocess, "Popen", side_effect=boom),
                   mock.patch.object(builtins, "open", side_effect=boom),
                   mock.patch.object(socket, "socket", side_effect=boom),
                   mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom),
                   mock.patch.object(rp.PipelineRunner, "_start_ready", side_effect=boom),
                   mock.patch.object(rp.DirLease, "try_acquire", side_effect=boom),
                   mock.patch.object(cap, "evaluate_capacity", side_effect=boom),
                   mock.patch.object(cf, "analyze_conflicts", side_effect=boom)]
        patches += [mock.patch.object(os, name, side_effect=boom)
                    for name in ("stat", "replace", "mkdir", "cpu_count", "getloadavg", "sysconf", "listdir")
                    if hasattr(os, name)]
        for patch in patches:
            patch.start()
        try:
            result = rr.evaluate_resources(req)
            rr.canonical_json(result)
        finally:
            for patch in reversed(patches):
                patch.stop()
        self.assertEqual(result.verdict, rr.READY)

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_resource_quota_contract", "fabric_scheduler_capacity", "fabric_scheduler_conflicts",
               "fabric_scheduler_contract")
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("psutil", "platform", "multiprocessing", "resource.", "shutil", "ctypes", "wmi", "/proc",
                     "cpu_count", "getloadavg", "sysconf", "subprocess", "open(", "Path(", "os.", "socket",
                     "Thread", "Executor", "PipelineRunner", "DirLease", "lease_dir", "ledger", "_launch",
                     "_start_ready", ".now(", "utcnow", "time.", "sleep", "while ", "claude", "codex", "eval(",
                     "exec(", "importlib", "random", "requests.", "urllib", "environ", "evaluate_capacity(",
                     "analyze_conflicts(", "cookie", "keyring", "customer"):
            self.assertNotIn(word, code, word)
        for word in ("price", "cost", "currency", "money"):
            self.assertNotRegex(code, rf"\b{word}\b", word)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_mutable_module_state_changes(self):
        modules = (rr, qc, cap, cf)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        evaluate()
        evaluate(observations=())
        rr.evaluate_resources(None)
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_reused(self):
        for vocab in (rr.RESOURCE_KINDS, rr.UNITS, rr.SOURCES, rr.REQUEST_REASONS, rr.RESULT_REASONS):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(rr.REQUEST_REASONS) & set(rr.RESULT_REASONS))
        self.assertEqual(set(rr.KIND_UNIT), set(rr.RESOURCE_KINDS))
        self.assertEqual(set(rr.KIND_UNIT.values()), set(rr.UNITS))
        self.assertEqual(set(rr.UNIT_MAXIMUM), set(rr.UNITS))
        self.assertFalse(set(rr.UNITS) & set(qc.UNITS))
        for code in rr.RESOURCE_REASONS:
            self.assertIn(code, qc.UNKNOWN_REASONS)
        for code in rr.CONFLICT_REASONS:
            self.assertIn(code, cap.UNKNOWN_REASONS)
        self.assertEqual(rr.VERDICTS, qc.VERDICTS)
        self.assertEqual(rr.RELIABILITIES, qc.RELIABILITIES)
        self.assertEqual(rr.MAX_WORKERS, rp.MAX_PIPELINE_WORKERS)
        self.assertIn(rr.SOURCE_OPERATOR_DECLARATION, qc.EVIDENCE_SOURCES)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
