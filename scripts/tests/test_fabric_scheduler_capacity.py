"""FCP-9C-01: Concurrent capacity and provider limits.

The evaluator is pure, so every worktree here is a synthetic, lexical
absolute path under a root that never exists; no repository, process,
network or real provider is ever touched. Provider ids are opaque labels.
Worker states and provider facts are synthetic observations; nothing is
executed. Nothing here is skipped.
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

from scripts.ai import fabric_provider_routing_policy as rt
from scripts.ai import fabric_scheduler_capacity as cap
from scripts.ai import fabric_scheduler_conflicts as cf
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_provider_availability as availability

MODULE_PATH = Path(cap.__file__)
TEST_PATH = Path(__file__).resolve()
ROOT = "/fcp9c01-synthetic"
AS_OF = "2026-10-30T12:00:00Z"
OBSERVED = "2026-10-30T11:59:00Z"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized")
QUOTA = availability.ProviderCondition.QUOTA_EXHAUSTED.value
AUTH = availability.ProviderCondition.AUTH_BLOCKED.value
TRANSIENT = availability.ProviderCondition.TRANSIENT_ERROR.value
_DEFAULT = object()


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def spec(wid, *, provider="alpha", mode="read-only", worktree=None, **extra):
    top = f"{ROOT}/{worktree or wid}"
    return rp.WorkerSpec(id=wid, worktree=top, work_order=f"{ROOT}/wo_{wid}.md", provider=provider, mode=mode,
                         worktree_top=top, **extra)


def manifest(specs, pipeline_id="fcp9c01-dag", **extra):
    return rp.Manifest(pipeline_id=pipeline_id, workers=list(specs), **extra)


def facts(provider="alpha", slots=2, *, availability_="NONE", capacity="AVAILABLE", observed=OBSERVED,
          condition=None):
    return cap.ProviderCapacityFacts(provider_id=provider, availability=availability_, capacity=capacity,
                                     proven_slots=slots, observed_at_utc=observed, last_condition=condition)


def conflicts(m, *, worktrees=None, dag_id=None):
    worktrees = worktrees or {}
    workers = tuple(
        cf.WorkerClaims(worker_id=s.id, mode=s.mode, worktree=worktrees.get(s.id, s.worktree_top),
                        worktree_link_state=cf.LINK_NONE)
        for s in m.workers
    )
    return cf.ConflictRequest(dag_id=dag_id or m.pipeline_id, allowed_roots=(ROOT,), workers=workers)


def advisory(provider, *, mode="read-only", availability_="NONE"):
    """A real Provider Router advisory (FCP-7), never a hand-made verdict."""
    caps = ("READ_FILES", "SEARCH_FILES")
    if mode == "write":
        caps += tuple(sorted(rt.WRITE_MODE_CAPABILITIES))
    return rt.propose_route(
        rt.RoutingRequest(mode=mode, preference_order=(provider,)),
        (rt.ProviderFacts(provider, True, mode, False, True, caps, availability_, "AVAILABLE"),),
    )


class CapacityTestBase(unittest.TestCase):
    def request(self, m, *, states=None, items=None, provider_facts=_DEFAULT, conflict=_DEFAULT, as_of=AS_OF,
                **kw):
        if items is None:
            states = states or {}
            items = tuple(cap.CapacityItem(s.id, states.get(s.id, "QUEUED")) for s in m.workers)
        if provider_facts is _DEFAULT:
            providers = sorted({s.provider for s in m.workers})
            provider_facts = tuple(facts(p, cap.MAX_WORKERS) for p in providers)
        return cap.CapacityRequest(
            manifest=m, as_of_utc=as_of, items=items, provider_facts=provider_facts,
            conflict_request=conflicts(m) if conflict is _DEFAULT else conflict, **kw,
        )

    def evaluate(self, m, **kw):
        return cap.evaluate_capacity(self.request(m, **kw))

    def decisions(self, plan):
        return {d.item_id: (d.decision, d.reasons) for d in plan.decisions}

    def assertRefused(self, plan, *reasons):
        self.assertEqual(plan.outcome, cap.REFUSED)
        for reason in reasons:
            self.assertIn(reason, plan.request_reasons)
        self.assertEqual(
            (plan.decisions, plan.dag_id, plan.request_fingerprint, plan.planning_order, plan.provider_budgets,
             plan.group_budgets, plan.effective_max_workers),
            ((), None, None, (), (), (), None))
        return plan

    def workers(self, n, prefix="w", **extra):
        return [spec(f"{prefix}{i:02d}", **extra) for i in range(n)]


# ---------------------------------------------------------------------------
# 0 / 1 / 2 slots and the global caps
# ---------------------------------------------------------------------------
class SlotCountTests(CapacityTestBase):
    def test_zero_slots_full_provider_enables_nothing(self):
        m = manifest(self.workers(3), max_workers=3)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 0, capacity="FULL"),))
        budget = plan.budget_of("alpha")
        self.assertEqual((budget.status, budget.reasons, budget.budget, budget.free, budget.assigned),
                         (cap.HELD, (cap.CAPACITY_FULL,), 0, 0, 0))
        self.assertEqual(plan.admitted, ())
        self.assertEqual(set(self.decisions(plan).values()), {(cap.WAITING, (cap.PROVIDER_HELD,))})
        self.assertEqual(plan.outcome, cap.WAITING)

    def test_one_proven_slot_admits_exactly_one(self):
        m = manifest(self.workers(3), max_workers=3)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 1),))
        self.assertEqual(plan.admitted, ("w00",))
        self.assertEqual(plan.decision_of("w01").reasons, (cap.PROVIDER_LIMIT_REACHED,))
        self.assertEqual(plan.decision_of("w02").reasons, (cap.PROVIDER_LIMIT_REACHED,))
        self.assertEqual((plan.budget_of("alpha").budget, plan.budget_of("alpha").assigned), (1, 1))

    def test_two_proven_slots_admit_two(self):
        m = manifest(self.workers(4), max_workers=4)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 2),))
        self.assertEqual(plan.admitted, ("w00", "w01"))
        self.assertEqual([plan.decision_of(w).slot for w in ("w00", "w01")], [0, 1])
        self.assertEqual(plan.outcome, cap.SCHEDULABLE)

    def test_default_cap_is_the_runner_default_not_one(self):
        m = manifest(self.workers(4))
        plan = self.evaluate(m, provider_facts=(facts("alpha", cap.MAX_WORKERS),))
        self.assertEqual(plan.effective_max_workers, rp.DEFAULT_MAX_WORKERS)
        self.assertGreater(plan.effective_max_workers, 1)
        self.assertEqual(len(plan.admitted), rp.DEFAULT_MAX_WORKERS)
        self.assertEqual(plan.decision_of("w03").reasons, (cap.WORKER_LIMIT_REACHED,))

    def test_never_exceeds_max_pipeline_workers(self):
        n = rp.MAX_PIPELINE_WORKERS + 3
        m = manifest(self.workers(n), max_workers=rp.MAX_PIPELINE_WORKERS,
                     provider_limits={"alpha": rp.MAX_PIPELINE_WORKERS})
        plan = self.evaluate(m, provider_facts=(facts("alpha", rp.MAX_PIPELINE_WORKERS),))
        self.assertEqual(len(plan.admitted), rp.MAX_PIPELINE_WORKERS)
        self.assertEqual(sum(1 for d in plan.decisions if cap.WORKER_LIMIT_REACHED in d.reasons), 3)
        over = rp.MAX_PIPELINE_WORKERS + 1
        self.assertRefused(self.evaluate(manifest(self.workers(2), max_workers=over)), cap.MANIFEST_LIMITS_INVALID)
        self.assertRefused(self.evaluate(manifest(self.workers(2)), max_workers=over), cap.MAX_WORKERS_INVALID)
        self.assertRefused(self.evaluate(manifest(self.workers(2)), provider_facts=(facts("alpha", over),)),
                           cap.FACTS_MALFORMED)
        self.assertRefused(self.evaluate(manifest(self.workers(2)), provider_limits=(("alpha", over),)),
                           cap.PROVIDER_LIMITS_MALFORMED)

    def test_budget_is_the_minimum_of_proof_provider_limit_and_cap(self):
        m = manifest(self.workers(6), max_workers=4, provider_limits={"alpha": 3})
        plan = self.evaluate(m, provider_facts=(facts("alpha", 5),))
        self.assertEqual((plan.budget_of("alpha").budget, plan.budget_of("alpha").limit), (3, 3))
        self.assertEqual(len(plan.admitted), 3)
        plan = self.evaluate(manifest(self.workers(6), max_workers=4, provider_limits={"alpha": 5}),
                             provider_facts=(facts("alpha", 2),))
        self.assertEqual(len(plan.admitted), 2)

    def test_request_limits_only_narrow_the_manifest(self):
        m = manifest(self.workers(5), max_workers=3, provider_limits={"alpha": 2})
        widened = self.evaluate(m, max_workers=8, provider_limits=(("alpha", 5),))
        self.assertEqual((widened.effective_max_workers, widened.effective_provider_limits), (3, (("alpha", 2),)))
        self.assertEqual(len(widened.admitted), 2)
        narrowed = self.evaluate(m, max_workers=1)
        self.assertEqual((narrowed.effective_max_workers, len(narrowed.admitted)), (1, 1))
        new_limit = self.evaluate(manifest(self.workers(5), max_workers=3), provider_limits=(("alpha", 1),))
        self.assertEqual(new_limit.effective_provider_limits, (("alpha", 1),))
        self.assertEqual(len(new_limit.admitted), 1)

    def test_running_workers_consume_provider_and_global_slots(self):
        m = manifest(self.workers(4), max_workers=3)
        plan = self.evaluate(m, states={"w00": "RUNNING"}, provider_facts=(facts("alpha", 2),))
        self.assertEqual((plan.occupied_slots, plan.free_slots), (1, 2))
        self.assertEqual((plan.budget_of("alpha").occupied, plan.budget_of("alpha").free), (1, 1))
        self.assertEqual(plan.admitted, ("w01",))
        self.assertEqual(plan.decision_of("w00").decision, cap.INACTIVE)
        full = self.evaluate(m, states={"w00": "RUNNING", "w01": "RUNNING"}, provider_facts=(facts("alpha", 2),))
        self.assertEqual(full.admitted, ())
        self.assertEqual(full.budget_of("alpha").status, cap.SATURATED)


# ---------------------------------------------------------------------------
# Multiple providers
# ---------------------------------------------------------------------------
class MultiProviderTests(CapacityTestBase):
    def test_providers_have_independent_budgets_under_one_global_cap(self):
        m = manifest([spec("a1"), spec("a2"), spec("b1", provider="beta"), spec("b2", provider="beta")],
                     max_workers=3)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 1), facts("beta", 2)))
        self.assertEqual(plan.admitted, ("a1", "b1", "b2"))
        self.assertEqual(plan.decision_of("a2").reasons, (cap.PROVIDER_LIMIT_REACHED,))
        shared = self.evaluate(manifest(m.workers, max_workers=2), provider_facts=(facts("alpha", 2), facts("beta", 2)))
        self.assertEqual(shared.admitted, ("a1", "a2"))
        self.assertEqual(shared.decision_of("b1").reasons, (cap.WORKER_LIMIT_REACHED,))

    def test_held_provider_never_moves_work_to_another_provider(self):
        m = manifest([spec("a1", fallback_providers=["beta"]), spec("b1", provider="beta")], max_workers=4)
        items = (cap.CapacityItem("a1", "QUEUED", active_provider="alpha"), cap.CapacityItem("b1", "QUEUED"))
        plan = self.evaluate(m, items=items, provider_facts=(facts("alpha", 2, availability_="QUOTA_WAIT"),
                                                             facts("beta", 4)))
        self.assertEqual(plan.admitted, ("b1",))
        held = plan.decision_of("a1")
        self.assertEqual((held.decision, held.reasons, held.provider), (cap.WAITING, (cap.PROVIDER_HELD,), "alpha"))
        self.assertEqual(plan.budget_of("beta").assigned, 1)
        self.assertIs(plan.provider_switch_authorized, False)

    def test_unobserved_provider_of_a_worker_with_fallbacks_is_unknown(self):
        m = manifest([spec("a1", fallback_providers=["beta"])], max_workers=2)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 2), facts("beta", 2)))
        self.assertEqual(self.decisions(plan)["a1"], (cap.UNKNOWN, (cap.ACTIVE_PROVIDER_UNOBSERVED,)))
        self.assertEqual(plan.outcome, cap.UNKNOWN)

    def test_unknown_state_worker_occupies_every_provider_it_could_use(self):
        m = manifest([spec("x", fallback_providers=["beta"]), spec("a1"), spec("b1", provider="beta")],
                     max_workers=3)
        items = (cap.CapacityItem("a1", "QUEUED"), cap.CapacityItem("b1", "QUEUED"))
        plan = self.evaluate(m, items=items, provider_facts=(facts("alpha", 1), facts("beta", 1)))
        self.assertEqual((plan.budget_of("alpha").occupied, plan.budget_of("beta").occupied), (1, 1))
        self.assertEqual(plan.admitted, ())
        self.assertEqual(self.decisions(plan)["x"], (cap.UNKNOWN, (cap.ITEM_STATE_UNKNOWN,)))
        self.assertEqual(plan.outcome, cap.UNKNOWN)

    def test_active_provider_must_be_declared_for_the_worker(self):
        m = manifest([spec("a1"), spec("b1", provider="beta")])
        items = (cap.CapacityItem("a1", "QUEUED", active_provider="beta"), cap.CapacityItem("b1", "QUEUED"))
        self.assertRefused(self.evaluate(m, items=items), cap.ACTIVE_PROVIDER_NOT_DECLARED)
        items = (cap.CapacityItem("a1", "QUEUED", active_provider="Not Valid"),)
        self.assertRefused(self.evaluate(m, items=items), cap.ACTIVE_PROVIDER_NOT_DECLARED)


# ---------------------------------------------------------------------------
# Quota, authentication and Runner holds
# ---------------------------------------------------------------------------
class QuotaAndAuthTests(CapacityTestBase):
    def test_quota_wait_and_auth_blocked_never_enable_slots(self):
        m = manifest(self.workers(2), max_workers=2)
        for state, reason, condition in (("QUOTA_WAIT", cap.AVAILABILITY_QUOTA_WAIT, QUOTA),
                                         ("AUTH_BLOCKED", cap.AVAILABILITY_AUTH_BLOCKED, AUTH)):
            for last in (None, condition):
                with self.subTest(state=state, last=last):
                    plan = self.evaluate(m, provider_facts=(facts("alpha", 2, availability_=state, condition=last),))
                    budget = plan.budget_of("alpha")
                    self.assertEqual((budget.status, budget.reasons, budget.budget, budget.free),
                                     (cap.HELD, (reason,), 0, 0))
                    self.assertEqual(plan.admitted, ())
                    self.assertEqual(plan.outcome, cap.WAITING)

    def test_runner_provider_hold_states_hold_only_that_provider(self):
        m = manifest([spec("h"), spec("a1"), spec("b1", provider="beta")], max_workers=3)
        for state in ("WAITING_PROVIDER_QUOTA", "BLOCKED_PROVIDER_AUTH"):
            with self.subTest(state=state):
                items = (cap.CapacityItem("h", state, active_provider="alpha"), cap.CapacityItem("a1", "QUEUED"),
                         cap.CapacityItem("b1", "QUEUED"))
                plan = self.evaluate(m, items=items)
                self.assertEqual(plan.budget_of("alpha").reasons, (cap.RUNNER_PROVIDER_HOLD,))
                self.assertEqual(plan.decision_of("a1").reasons, (cap.PROVIDER_HELD,))
                self.assertEqual(self.decisions(plan)["h"], (cap.INACTIVE, (cap.ITEM_NOT_PENDING,)))
                self.assertEqual(plan.admitted, ("b1",))

    def test_retry_wait_and_terminal_workers_hold_no_slot(self):
        m = manifest(self.workers(3), max_workers=2)
        plan = self.evaluate(m, states={"w00": "RETRY_WAIT", "w01": "SUCCESS"}, provider_facts=(facts("alpha", 1),))
        self.assertEqual(self.decisions(plan)["w00"], (cap.INACTIVE, (cap.ITEM_NOT_PENDING,)))
        self.assertEqual(self.decisions(plan)["w01"], (cap.INACTIVE, (cap.ITEM_TERMINAL,)))
        self.assertEqual((plan.occupied_slots, plan.admitted), (0, ("w02",)))


# ---------------------------------------------------------------------------
# Unknown capacity fails closed
# ---------------------------------------------------------------------------
class UnknownCapacityTests(CapacityTestBase):
    def test_missing_facts_are_unknown(self):
        m = manifest(self.workers(2))
        plan = self.evaluate(m, provider_facts=())
        self.assertEqual((plan.budget_of("alpha").status, plan.budget_of("alpha").reasons),
                         (cap.UNKNOWN, (cap.NO_FACTS,)))
        self.assertEqual(set(self.decisions(plan).values()), {(cap.UNKNOWN, (cap.PROVIDER_CAPACITY_UNKNOWN,))})
        self.assertEqual((plan.outcome, plan.admitted), (cap.UNKNOWN, ()))

    def test_unknown_availability_capacity_or_proof_enables_nothing(self):
        m = manifest(self.workers(2))
        for fact, reason in ((facts("alpha", 2, availability_="UNKNOWN"), cap.AVAILABILITY_UNKNOWN),
                             (facts("alpha", 2, capacity="UNKNOWN"), cap.CAPACITY_UNKNOWN),
                             (facts("alpha", None), cap.PROVEN_SLOTS_UNKNOWN)):
            with self.subTest(reason=reason):
                plan = self.evaluate(m, provider_facts=(fact,))
                budget = plan.budget_of("alpha")
                self.assertEqual((budget.status, budget.reasons, budget.budget, budget.free),
                                 (cap.UNKNOWN, (reason,), 0, 0))
                self.assertEqual((plan.outcome, plan.admitted), (cap.UNKNOWN, ()))

    def test_unknown_dominates_hold_in_the_provider_status(self):
        plan = self.evaluate(manifest(self.workers(1)),
                             provider_facts=(facts("alpha", None, availability_="QUOTA_WAIT"),))
        self.assertEqual(plan.budget_of("alpha").status, cap.UNKNOWN)
        self.assertEqual(plan.budget_of("alpha").reasons, (cap.PROVEN_SLOTS_UNKNOWN, cap.AVAILABILITY_QUOTA_WAIT))
        self.assertEqual(plan.decision_of("w00").reasons, (cap.PROVIDER_CAPACITY_UNKNOWN,))

    def test_stale_and_future_facts_are_unknown(self):
        m = manifest(self.workers(1))
        for observed, reason in (("2026-10-30T11:44:59Z", cap.FACTS_STALE),
                                 ("2026-10-30T12:00:01Z", cap.FACTS_FROM_FUTURE)):
            with self.subTest(reason=reason):
                plan = self.evaluate(m, provider_facts=(facts("alpha", 2, observed=observed),))
                self.assertEqual(plan.budget_of("alpha").reasons, (reason,))
                self.assertEqual(plan.outcome, cap.UNKNOWN)
        edge = self.evaluate(m, provider_facts=(facts("alpha", 2, observed="2026-10-30T11:45:00Z"),))
        self.assertEqual(edge.admitted, ("w00",))
        tight = self.evaluate(m, provider_facts=(facts("alpha", 2),), max_fact_age_seconds=30)
        self.assertEqual(tight.budget_of("alpha").reasons, (cap.FACTS_STALE,))

    def test_unobserved_worker_state_is_unknown_and_takes_a_slot(self):
        m = manifest(self.workers(3), max_workers=2)
        plan = self.evaluate(m, items=(cap.CapacityItem("w01", "QUEUED"), cap.CapacityItem("w02", "QUEUED")),
                             provider_facts=(facts("alpha", 2),))
        self.assertEqual(self.decisions(plan)["w00"], (cap.UNKNOWN, (cap.ITEM_STATE_UNKNOWN,)))
        self.assertEqual((plan.occupied_slots, plan.free_slots), (1, 1))
        self.assertEqual(plan.admitted, ("w01",))
        self.assertEqual(plan.outcome, cap.UNKNOWN)

    def test_missing_or_unidentified_conflict_analysis_fails_closed(self):
        m = manifest(self.workers(2), max_workers=2)
        plan = self.evaluate(m, conflict=None)
        self.assertEqual(set(self.decisions(plan).values()), {(cap.UNKNOWN, (cap.CONFLICTS_UNASSESSED,))})
        plan = self.evaluate(m, conflict=conflicts(m, worktrees={"w00": None}))
        self.assertEqual(self.decisions(plan)["w00"], (cap.UNKNOWN, (cap.CONFLICT_UNIDENTIFIED,)))
        self.assertEqual(plan.admitted, ("w01",))


# ---------------------------------------------------------------------------
# Discrepancies between facts, observations and Router verdicts
# ---------------------------------------------------------------------------
class DiscrepancyTests(CapacityTestBase):
    def test_last_condition_contradicting_availability_is_unknown(self):
        m = manifest(self.workers(1))
        for availability_, condition in (("NONE", QUOTA), ("NONE", AUTH), ("QUOTA_WAIT", AUTH),
                                         ("AUTH_BLOCKED", QUOTA), ("QUOTA_WAIT", TRANSIENT)):
            with self.subTest(availability=availability_, condition=condition):
                plan = self.evaluate(m, provider_facts=(facts("alpha", 2, availability_=availability_,
                                                              condition=condition),))
                self.assertIn(cap.CONDITION_DISCREPANCY, plan.budget_of("alpha").reasons)
                self.assertEqual(plan.budget_of("alpha").status, cap.UNKNOWN)
                self.assertEqual(plan.admitted, ())
        consistent = self.evaluate(m, provider_facts=(facts("alpha", 2, condition=TRANSIENT),))
        self.assertEqual(consistent.admitted, ("w00",))

    def test_available_capacity_with_zero_proven_slots_is_a_discrepancy(self):
        plan = self.evaluate(manifest(self.workers(1)), provider_facts=(facts("alpha", 0),))
        self.assertEqual(plan.budget_of("alpha").reasons, (cap.CAPACITY_DISCREPANCY,))
        self.assertEqual(plan.outcome, cap.UNKNOWN)

    def test_more_running_than_proven_slots_is_a_discrepancy(self):
        m = manifest(self.workers(3), max_workers=3)
        plan = self.evaluate(m, states={"w00": "RUNNING", "w01": "RUNNING"}, provider_facts=(facts("alpha", 1),))
        self.assertEqual(plan.budget_of("alpha").reasons, (cap.OCCUPANCY_DISCREPANCY,))
        self.assertEqual(plan.decision_of("w02").reasons, (cap.PROVIDER_CAPACITY_UNKNOWN,))

    def test_router_verdicts_are_read_never_reinterpreted(self):
        m = manifest([spec("a1"), spec("a2")], max_workers=2)
        cases = (
            (advisory("alpha"), (cap.SCHEDULABLE, ())),
            (advisory("alpha", availability_="QUOTA_WAIT"), (cap.REFUSED, (cap.ROUTING_REFUSED,))),
            (advisory("beta"), (cap.UNKNOWN, (cap.ROUTING_DISCREPANCY,))),
            (advisory("alpha", mode="write"), (cap.UNKNOWN, (cap.ROUTING_DISCREPANCY,))),
        )
        self.assertEqual([c[0].rationale for c in cases].count(rt.SELECTED_FIRST_ELIGIBLE_PREFERENCE), 3)
        for routed, expected in cases:
            with self.subTest(rationale=routed.rationale, provider=routed.selected_provider, mode=routed.mode):
                items = (cap.CapacityItem("a1", "QUEUED", routing_advisory=routed), cap.CapacityItem("a2", "QUEUED"))
                plan = self.evaluate(m, items=items)
                self.assertEqual(self.decisions(plan)["a1"], expected)
                self.assertEqual(plan.decision_of("a1").provider, "alpha")
        items = (cap.CapacityItem("a1", "QUEUED", routing_advisory={"selected_provider": "alpha"}),)
        self.assertRefused(self.evaluate(m, items=items), cap.ROUTING_ADVISORY_NOT_TYPED)


# ---------------------------------------------------------------------------
# Re-evaluation after facts change
# ---------------------------------------------------------------------------
class FactChangeTests(CapacityTestBase):
    def test_capacity_follows_the_facts_both_ways(self):
        m = manifest(self.workers(3), max_workers=3)
        steps = (
            (facts("alpha", 2, availability_="QUOTA_WAIT", condition=QUOTA), ()),
            (facts("alpha", 1), ("w00",)),
            (facts("alpha", 2), ("w00", "w01")),
            (facts("alpha", 3), ("w00", "w01", "w02")),
            (facts("alpha", 3, availability_="AUTH_BLOCKED", condition=AUTH), ()),
            (facts("alpha", 3, availability_="UNKNOWN"), ()),
        )
        prints = set()
        for fact, admitted in steps:
            with self.subTest(fact=fact):
                plan = self.evaluate(m, provider_facts=(fact,))
                self.assertEqual(plan.admitted, admitted)
                prints.add(plan.request_fingerprint)
        self.assertEqual(len(prints), len(steps))

    def test_recovery_after_quota_requires_the_condition_to_clear(self):
        m = manifest(self.workers(1))
        stale_condition = self.evaluate(m, provider_facts=(facts("alpha", 1, condition=QUOTA),))
        self.assertEqual(stale_condition.outcome, cap.UNKNOWN)
        cleared = self.evaluate(m, provider_facts=(facts("alpha", 1),))
        self.assertEqual(cleared.admitted, ("w00",))

    def test_a_started_worker_is_counted_on_the_next_evaluation(self):
        m = manifest(self.workers(3), max_workers=3)
        first = self.evaluate(m, provider_facts=(facts("alpha", 2),))
        self.assertEqual(first.admitted, ("w00", "w01"))
        second = self.evaluate(m, states={"w00": "RUNNING"}, provider_facts=(facts("alpha", 2),))
        self.assertEqual(second.admitted, ("w01",))
        self.assertEqual(second.decision_of("w02").reasons, (cap.PROVIDER_LIMIT_REACHED,))
        third = self.evaluate(m, states={"w00": "SUCCESS"}, provider_facts=(facts("alpha", 2),))
        self.assertEqual(third.admitted, ("w01", "w02"))


# ---------------------------------------------------------------------------
# Contention: priority, dependencies, worktree exclusion, resource groups
# ---------------------------------------------------------------------------
class ContentionTests(CapacityTestBase):
    def test_priority_first_then_stable_declared_order(self):
        m = manifest([spec("low"), spec("high", priority=5), spec("mid1", priority=1), spec("mid2", priority=1)],
                     max_workers=3)
        plan = self.evaluate(m)
        self.assertEqual(plan.planning_order, ("high", "mid1", "mid2", "low"))
        self.assertEqual(plan.admitted, ("high", "mid1", "mid2"))
        self.assertEqual(plan.decision_of("low").reasons, (cap.WORKER_LIMIT_REACHED,))
        self.assertEqual(self.evaluate(m).planning_order, plan.planning_order)

    def test_a_worker_is_passed_over_only_for_its_own_reason(self):
        m = manifest([spec("a1", priority=9), spec("a2", priority=8), spec("b1", provider="beta")], max_workers=2)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 1), facts("beta", 1)))
        self.assertEqual(plan.admitted, ("a1", "b1"))
        self.assertEqual(plan.decision_of("a2").reasons, (cap.PROVIDER_LIMIT_REACHED,))

    def test_dependencies_follow_the_runner_policies(self):
        m = manifest([spec("a"), spec("b", depends_on=["a"]), spec("c", depends_on=["a"],
                                                                    dependency_policy="completed")],
                     max_workers=3)
        pending = self.evaluate(m)
        self.assertEqual(pending.admitted, ("a",))
        self.assertEqual(pending.decision_of("b").reasons, (cap.DEPENDENCY_PENDING,))
        done = self.evaluate(m, states={"a": "SUCCESS"})
        self.assertEqual(done.admitted, ("b", "c"))
        failed = self.evaluate(m, states={"a": "FAILED"})
        self.assertEqual(self.decisions(failed)["b"], (cap.REFUSED, (cap.DEPENDENCY_UNSATISFIABLE,)))
        self.assertEqual(failed.admitted, ("c",))
        unknown = self.evaluate(m, items=(cap.CapacityItem("b", "QUEUED"), cap.CapacityItem("c", "QUEUED")))
        self.assertEqual(self.decisions(unknown)["b"], (cap.UNKNOWN, (cap.DEPENDENCY_STATE_UNKNOWN,)))

    def test_writers_on_one_worktree_are_never_planned_together(self):
        m = manifest([spec("w1", mode="write", worktree="shared"), spec("w2", mode="write", worktree="shared"),
                      spec("r1", worktree="other"), spec("r2", worktree="other")], max_workers=4)
        plan = self.evaluate(m)
        self.assertEqual(plan.admitted, ("w1", "r1", "r2"))
        self.assertEqual(plan.decision_of("w2").reasons, (cap.CONFLICT_WITH_ADMITTED,))
        running = self.evaluate(m, states={"w1": "RUNNING"})
        self.assertEqual(running.decision_of("w2").reasons, (cap.CONFLICT_WITH_RUNNING,))

    def test_resource_groups_bound_their_members(self):
        m = manifest(self.workers(4), max_workers=4)
        group = cap.ResourceGroup("db.shared", 1, ("w01", "w00"))
        plan = self.evaluate(m, resource_groups=(group,))
        self.assertEqual(plan.admitted, ("w00", "w02", "w03"))
        self.assertEqual(plan.decision_of("w01").reasons, (cap.GROUP_LIMIT_REACHED,))
        budget = plan.group_budgets[0]
        self.assertEqual((budget.group_id, budget.members, budget.limit, budget.assigned, budget.status),
                         ("db.shared", ("w00", "w01"), 1, 1, cap.AVAILABLE))
        busy = self.evaluate(m, states={"w00": "RUNNING"}, resource_groups=(group,))
        self.assertEqual(busy.group_budgets[0].status, cap.SATURATED)
        self.assertEqual(busy.decision_of("w01").reasons, (cap.GROUP_LIMIT_REACHED,))

    def test_global_cap_is_checked_before_provider_and_group(self):
        m = manifest(self.workers(3), max_workers=1)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 1),),
                             resource_groups=(cap.ResourceGroup("g", 1, ("w01", "w02")),))
        self.assertEqual(plan.admitted, ("w00",))
        self.assertEqual({plan.decision_of(w).reasons for w in ("w01", "w02")}, {(cap.WORKER_LIMIT_REACHED,)})


# ---------------------------------------------------------------------------
# Fail-closed request validation
# ---------------------------------------------------------------------------
class ValidationTests(CapacityTestBase):
    def test_untyped_requests_and_manifests_are_refused(self):
        self.assertRefused(cap.evaluate_capacity(None), cap.REQUEST_NOT_TYPED)
        self.assertRefused(cap.evaluate_capacity({"manifest": None}), cap.REQUEST_NOT_TYPED)
        m = manifest(self.workers(1))
        for bad in (None, {"pipeline_id": "x"}, m.raw):
            with self.subTest(bad=bad):
                req = dataclasses.replace(self.request(m), manifest=bad, conflict_request=None)
                self.assertRefused(cap.evaluate_capacity(req), cap.MANIFEST_NOT_TYPED)
        self.assertRefused(cap.evaluate_capacity(dataclasses.replace(self.request(m), schema_version=2)),
                           cap.SCHEMA_VERSION_UNSUPPORTED)
        for as_of in ("2026-10-30T12:00:00", "", None, 0):
            with self.subTest(as_of=as_of):
                self.assertRefused(self.evaluate(m, as_of=as_of), cap.AS_OF_INVALID)

    def test_invalid_manifests_are_refused(self):
        cases = (
            [spec("a", depends_on=["b"]), spec("b", depends_on=["a"])],
            [spec("a"), spec("a")],
            [spec("a", depends_on=["ghost"])],
            [spec("a", dependency_policy="whatever")],
            [spec("a", mode="admin")],
            [spec("a", provider="Bad Provider")],
            [spec("a", priority=True)],
            [],
        )
        for workers in cases:
            with self.subTest(workers=[w.id for w in workers]):
                self.assertRefused(self.evaluate(manifest(workers), conflict=None), cap.MANIFEST_INVALID)
        for limits in ({"alpha": 0}, {"alpha": True}, {"Bad": 1}):
            with self.subTest(limits=limits):
                self.assertRefused(self.evaluate(manifest(self.workers(1), provider_limits=limits)),
                                   cap.MANIFEST_LIMITS_INVALID)

    def test_items_are_validated(self):
        m = manifest(self.workers(2))
        cases = (
            ([cap.CapacityItem("w00", "QUEUED")], cap.ITEMS_MALFORMED),
            ((("w00", "QUEUED"),), cap.ITEMS_MALFORMED),
            ((cap.CapacityItem("ghost", "QUEUED"),), cap.ITEM_UNKNOWN_WORKER),
            ((cap.CapacityItem(["w00"], "QUEUED"),), cap.ITEM_UNKNOWN_WORKER),
            ((cap.CapacityItem("w00", "QUEUED"), cap.CapacityItem("w00", "RUNNING")), cap.ITEM_DUPLICATE),
            ((cap.CapacityItem("w00", "DONE"),), cap.ITEM_STATE_INVALID),
            ((cap.CapacityItem("w00", None),), cap.ITEM_STATE_INVALID),
        )
        for items, reason in cases:
            with self.subTest(reason=reason, items=items):
                self.assertRefused(self.evaluate(m, items=items), reason)

    def test_facts_and_age_are_validated(self):
        m = manifest(self.workers(1))
        cases = (
            ([facts()], cap.FACTS_MALFORMED),
            ((facts(availability_="AVAILABLE"),), cap.FACTS_MALFORMED),
            ((facts(capacity="NONE"),), cap.FACTS_MALFORMED),
            ((facts(slots=-1),), cap.FACTS_MALFORMED),
            ((facts(slots=True),), cap.FACTS_MALFORMED),
            ((facts(condition="QUOTA"),), cap.FACTS_MALFORMED),
            ((facts(provider=["alpha"]),), cap.FACTS_MALFORMED),
            ((facts(observed="yesterday"),), cap.FACTS_TIME_INVALID),
            ((facts(), facts(slots=1)), cap.FACTS_DUPLICATE),
            (rt.ProviderFacts("alpha", True, "read-only", False, True, (), "NONE", "AVAILABLE"),
             cap.FACTS_MALFORMED),
        )
        for provider_facts, reason in cases:
            with self.subTest(reason=reason, facts=provider_facts):
                self.assertRefused(self.evaluate(m, provider_facts=provider_facts), reason)
        for age in (0, -1, cap.MAX_FACT_AGE_SECONDS + 1, 1.5, True, None):
            with self.subTest(age=age):
                self.assertRefused(self.evaluate(m, max_fact_age_seconds=age), cap.MAX_FACT_AGE_INVALID)

    def test_groups_and_limits_are_validated(self):
        m = manifest(self.workers(2))
        cases = (
            ((cap.ResourceGroup("Upper", 1, ("w00",)),), cap.GROUPS_MALFORMED),
            ((cap.ResourceGroup("g", 0, ("w00",)),), cap.GROUPS_MALFORMED),
            ((cap.ResourceGroup("g", cap.MAX_WORKERS + 1, ("w00",)),), cap.GROUPS_MALFORMED),
            ((cap.ResourceGroup("g", 1, ()),), cap.GROUPS_MALFORMED),
            ((cap.ResourceGroup("g", 1, ("w00", "w00")),), cap.GROUPS_MALFORMED),
            ((cap.ResourceGroup("g", 1, ["w00"]),), cap.GROUPS_MALFORMED),
            ([cap.ResourceGroup("g", 1, ("w00",))], cap.GROUPS_MALFORMED),
            ((cap.ResourceGroup("g", 1, ("ghost",)),), cap.GROUP_MEMBER_UNKNOWN),
            ((cap.ResourceGroup("g", 1, ("w00",)), cap.ResourceGroup("g", 2, ("w01",))), cap.GROUP_DUPLICATE),
        )
        for groups, reason in cases:
            with self.subTest(reason=reason, groups=groups):
                self.assertRefused(self.evaluate(m, resource_groups=groups), reason)
        for limits, reason in (((("alpha", 0),), cap.PROVIDER_LIMITS_MALFORMED),
                               ([("alpha", 1)], cap.PROVIDER_LIMITS_MALFORMED),
                               ((("alpha", 1, 2),), cap.PROVIDER_LIMITS_MALFORMED),
                               ((("alpha", 1), ("alpha", 2)), cap.PROVIDER_LIMIT_DUPLICATE)):
            with self.subTest(limits=limits):
                self.assertRefused(self.evaluate(m, provider_limits=limits), reason)
        for value in (0, True, 2.0, "2"):
            with self.subTest(max_workers=value):
                self.assertRefused(self.evaluate(m, max_workers=value), cap.MAX_WORKERS_INVALID)

    def test_conflict_request_must_describe_exactly_this_manifest(self):
        m = manifest([spec("a", mode="write"), spec("b")])
        good = conflicts(m)
        cases = (
            ({"dag_id": "x"}, cap.CONFLICT_REQUEST_NOT_TYPED),
            (dataclasses.replace(good, dag_id="other-dag"), cap.CONFLICT_DAG_MISMATCH),
            (dataclasses.replace(good, workers=good.workers[:1]), cap.CONFLICT_WORKERS_MISMATCH),
            (dataclasses.replace(good, workers=(dataclasses.replace(good.workers[0], mode="read-only"),)
                                 + good.workers[1:]), cap.CONFLICT_MODE_MISMATCH),
            (conflicts(m, worktrees={"a": f"{ROOT}/elsewhere"}), cap.CONFLICT_WORKTREE_MISMATCH),
            (dataclasses.replace(good, allowed_roots=()), cap.CONFLICT_REQUEST_REFUSED),
        )
        for conflict, reason in cases:
            with self.subTest(reason=reason):
                self.assertRefused(self.evaluate(m, conflict=conflict), reason)
        alias = self.evaluate(m, conflict=conflicts(m, worktrees={"a": f"{ROOT}/x/../a"}))
        self.assertNotEqual(alias.outcome, cap.REFUSED)

    def test_garbage_never_raises_and_echoes_nothing(self):
        m = manifest(self.workers(1))
        garbage = (None, 0, "x", object(), [], {}, (object(),), (None,), float("nan"))
        for field in ("items", "provider_facts", "resource_groups", "provider_limits", "max_workers",
                      "max_fact_age_seconds", "as_of_utc", "schema_version", "conflict_request"):
            for value in garbage:
                if field in ("conflict_request", "max_workers") and value is None:
                    continue  # the documented defaults
                with self.subTest(field=field, value=value):
                    plan = cap.evaluate_capacity(dataclasses.replace(self.request(m), **{field: value}))
                    self.assertRefused(plan)
                    self.assertNotIn("object at", cap.canonical_json(plan))


# ---------------------------------------------------------------------------
# Output invariants and authority
# ---------------------------------------------------------------------------
class OutputTests(CapacityTestBase):
    def test_zero_authority_and_no_provider_switch_or_fallback(self):
        m = manifest([spec("a1", mode="write", fallback_providers=["beta"], allow_shell=True,
                           checkpoint_policy="ON_SUCCESS"), spec("b1", provider="beta")], max_workers=2)
        items = (cap.CapacityItem("a1", "QUEUED", active_provider="alpha"), cap.CapacityItem("b1", "QUEUED"))
        plan = self.evaluate(m, items=items, provider_facts=(facts("alpha", 2, availability_="QUOTA_WAIT"),
                                                             facts("beta", 2)))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(plan, flag), False)
            with self.assertRaises(AttributeError):
                setattr(plan, flag, True)
        text = cap.canonical_json(plan)
        payload = json.loads(text)
        for flag in ALL_FLAGS:
            self.assertIs(payload[flag], False)
        self.assertEqual(payload["marker"], cap.CAPACITY_MARKER)
        self.assertEqual(payload["schema"], cap.SCHEMA)
        self.assertEqual(payload["decisions"][0]["provider"], "alpha")
        for word in ("fallback", "allow_shell", "ON_SUCCESS", ROOT, "wo_", "switch_to", "paid", "api_key"):
            self.assertNotIn(word, text, word)
        self.assertEqual(set(payload["decisions"][0]),
                         {"item_id", "state", "provider", "priority", "decision", "reasons", "slot"})

    def test_hand_made_outputs_cannot_overclaim(self):
        m = manifest(self.workers(3), max_workers=3)
        plan = self.evaluate(m, provider_facts=(facts("alpha", 1),))
        waiting = plan.decision_of("w01")
        with self.assertRaises(ValueError):
            dataclasses.replace(waiting, decision=cap.SCHEDULABLE)
        promoted = dataclasses.replace(waiting, reasons=(), decision=cap.SCHEDULABLE, slot=1)
        with self.assertRaises(ValueError):  # exceeds the provider's budget
            dataclasses.replace(plan, decisions=(plan.decisions[0], promoted, plan.decisions[2]))
        budget = plan.budget_of("alpha")
        with self.assertRaises(ValueError):
            dataclasses.replace(budget, budget=2, free=2)
        held = self.evaluate(m, provider_facts=(facts("alpha", 2, availability_="QUOTA_WAIT"),)).budget_of("alpha")
        with self.assertRaises(ValueError):
            dataclasses.replace(held, budget=1, free=1)
        with self.assertRaises(ValueError):
            dataclasses.replace(held, status=cap.AVAILABLE)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, outcome=cap.IDLE)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, effective_max_workers=cap.MAX_WORKERS + 1, free_slots=cap.MAX_WORKERS + 1)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, request_reasons=(cap.AS_OF_INVALID,))
        with self.assertRaises(ValueError):
            cap.GroupBudget("g", cap.SATURATED, 1, ("w00",), 0, 1, 0)

    def test_canonical_json_is_exact_type_and_bounded(self):
        plan = self.evaluate(manifest(self.workers(2), max_workers=2))

        class Sub(cap.CapacityPlan):
            def to_dict(self):
                return {"dispatch_allowed": True}

        with self.assertRaises(TypeError):
            cap.canonical_json(Sub(**{f.name: getattr(plan, f.name) for f in dataclasses.fields(plan)}))
        with self.assertRaises(TypeError):
            cap.canonical_json(plan.to_dict())
        text = cap.canonical_json(plan)
        self.assertTrue(text.isascii())
        self.assertLessEqual(len(text), cap.MAX_CANONICAL_JSON_BYTES)
        self.assertEqual(json.loads(text)["counts"], {cap.SCHEDULABLE: 2, cap.WAITING: 0, cap.REFUSED: 0,
                                                      cap.UNKNOWN: 0, cap.INACTIVE: 0})


# ---------------------------------------------------------------------------
# Determinism, no mutation, no I/O
# ---------------------------------------------------------------------------
class DeterminismAndPurityTests(CapacityTestBase):
    def test_deterministic_and_fingerprint_tracks_every_input(self):
        m = manifest(self.workers(3), max_workers=3)
        first, second = self.evaluate(m), self.evaluate(m)
        self.assertEqual(cap.canonical_json(first), cap.canonical_json(second))
        self.assertEqual(first, second)
        variants = (
            self.evaluate(m, states={"w00": "RUNNING"}),
            self.evaluate(m, as_of="2026-10-30T12:00:01Z"),
            self.evaluate(m, max_workers=1),
            self.evaluate(m, conflict=None),
            self.evaluate(m, provider_facts=(facts("alpha", 3),)),
            self.evaluate(m, provider_facts=(facts("alpha", cap.MAX_WORKERS, observed="2026-10-30T11:58:00Z"),)),
            self.evaluate(m, resource_groups=(cap.ResourceGroup("g", 1, ("w00",)),)),
            self.evaluate(m, provider_limits=(("alpha", 2),)),
            self.evaluate(m, max_fact_age_seconds=600),
            self.evaluate(manifest(self.workers(3), max_workers=2)),
        )
        prints = {first.request_fingerprint} | {v.request_fingerprint for v in variants}
        self.assertEqual(len(prints), 1 + len(variants))
        same_instant = self.evaluate(m, as_of="2026-10-30T14:00:00+02:00")
        self.assertEqual(same_instant.request_fingerprint, first.request_fingerprint)
        reordered = self.evaluate(m, items=tuple(reversed(self.request(m).items)))
        self.assertEqual(reordered.request_fingerprint, first.request_fingerprint)

    def test_preview_never_mutates_its_inputs(self):
        m = manifest([spec("a", mode="write"), spec("b", depends_on=["a"])], max_workers=2,
                     provider_limits={"alpha": 2})
        request = self.request(m, states={"a": "SUCCESS"}, resource_groups=(cap.ResourceGroup("g", 1, ("a", "b")),))
        before = copy.deepcopy(request)
        workers_before = list(m.workers)
        cap.evaluate_capacity(request)
        self.assertEqual(request, before)
        self.assertEqual(m.workers, workers_before)
        self.assertEqual(m.provider_limits, {"alpha": 2})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.max_workers = 16
        plan = cap.evaluate_capacity(request)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.outcome = cap.SCHEDULABLE

    def test_no_io_processes_network_or_runner_entry_points(self):
        m = manifest([spec("a", mode="write"), spec("b")], max_workers=2)
        request = self.request(m)
        boom = AssertionError("I/O or execution entry point")
        with mock.patch.object(subprocess, "Popen", side_effect=boom), \
                mock.patch.object(builtins, "open", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(os, "stat", side_effect=boom), \
                mock.patch.object(os, "replace", side_effect=boom), \
                mock.patch.object(os, "mkdir", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom), \
                mock.patch.object(rp.DirLease, "try_acquire", side_effect=boom):
            plan = cap.evaluate_capacity(request)
        self.assertEqual(plan.admitted, ("a", "b"))

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_provider_routing_policy", "fabric_scheduler_conflicts", "fabric_scheduler_contract",
               "fabric_scheduler_plan", "fabric_scheduler_window", "runner_pipeline", "runner_provider_availability")
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "re", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "DirLease", "lease_dir", "ledger", "_launch", "_start_ready", ".now(", "utcnow", "sleep",
                     "while ", "claude", "codex", "eval(", "exec(", "importlib", "random",
                     "propose_route", "classify_provider_failure", "plan_dag("):
            self.assertNotIn(word, code, word)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_mutable_module_state_changes(self):
        modules = (cap, rt, availability)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        self.evaluate(manifest(self.workers(3), max_workers=2))
        cap.evaluate_capacity(None)
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_upper_snake(self):
        for vocab in (cap.DECISIONS, cap.OUTCOMES, cap.REQUEST_REASONS, cap.PROVIDER_REASONS, cap.ITEM_REASONS,
                      cap.BUDGET_STATUSES):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(cap.REQUEST_REASONS) & set(cap.ITEM_REASONS))
        self.assertFalse(set(cap.PROVIDER_REASONS) & set(cap.ITEM_REASONS))
        groups = (cap.INACTIVE_REASONS, cap.REFUSING_REASONS, cap.UNKNOWN_REASONS, cap.WAITING_REASONS)
        self.assertEqual(sum(len(g) for g in groups), len(cap.ITEM_REASONS))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


# ---------------------------------------------------------------------------
# Runner and Provider Router policy pins
# ---------------------------------------------------------------------------
class PolicyPinTests(unittest.TestCase):
    def test_limits_mirror_the_runner(self):
        self.assertEqual(cap.MAX_WORKERS, rp.MAX_PIPELINE_WORKERS)
        self.assertEqual(cap.DEFAULT_MAX_WORKERS, rp.DEFAULT_MAX_WORKERS)
        self.assertGreater(cap.DEFAULT_MAX_WORKERS, 1)
        self.assertEqual(cap.MAX_PROVEN_SLOTS, rp.MAX_PIPELINE_WORKERS)
        self.assertEqual(cap.MAX_PROVIDERS, rt.MAX_PROVIDERS)
        self.assertEqual(set(cap.NODE_STATES), {s.value for s in rp.WorkerState} | {cap.STATE_UNKNOWN})

    def test_router_and_availability_vocabularies_are_reused_not_redefined(self):
        self.assertEqual(
            (cap.NO_FACTS, cap.AVAILABILITY_UNKNOWN, cap.CAPACITY_UNKNOWN, cap.AVAILABILITY_QUOTA_WAIT,
             cap.AVAILABILITY_AUTH_BLOCKED, cap.CAPACITY_FULL),
            (rt.NO_FACTS, rt.AVAILABILITY_UNKNOWN, rt.CAPACITY_UNKNOWN, rt.AVAILABILITY_QUOTA_WAIT,
             rt.AVAILABILITY_AUTH_BLOCKED, rt.CAPACITY_FULL))
        self.assertEqual(set(cap._CONDITIONS), {c.value for c in availability.ProviderCondition})
        self.assertEqual(set(cap._CONDITION_AVAILABILITY), set(cap._CONDITIONS))
        self.assertTrue(set(v for v in cap._CONDITION_AVAILABILITY.values() if v) <= set(rt.AVAILABILITY_STATES))
        self.assertEqual((cap.SCHEDULABLE, cap.WAITING, cap.REFUSED, cap.UNKNOWN),
                         (sc.SCHEDULABLE, sc.WAITING, sc.REFUSED, sc.UNKNOWN))

    def test_planning_order_and_provider_holds_match_the_runner(self):
        runner_tree = ast.parse(Path(rp.__file__).read_text(encoding="utf-8"))
        self.assertIn("key=lambda r: (-r.spec.priority, r.order)", ast.unparse(runner_tree))
        own = ast.unparse(ast.parse(MODULE_PATH.read_text(encoding="utf-8")))
        self.assertIn("key=lambda i: (-specs[i].priority, i)", own)
        held = next(n for n in ast.walk(runner_tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_provider_start_held")
        referenced = {n.attr for n in ast.walk(held) if isinstance(n, ast.Attribute) and n.attr.isupper()}
        self.assertEqual(referenced, set(cap._PROVIDER_HOLDING_STATES))


if __name__ == "__main__":
    unittest.main()
