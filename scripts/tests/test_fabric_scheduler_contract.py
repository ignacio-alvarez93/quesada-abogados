"""FCP-9A-01: Scheduler contract V1 - consultative batch planning model.
Offline, synthetic requests only."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import socket
import subprocess
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_scheduler_contract as sc

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_scheduler_contract.py"
TEST_PATH = Path(__file__).resolve()

ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized")
AS_OF = "2026-10-30T10:00:00+00:00"
ALL_CAPS = sc.CAPABILITIES


def item(item_id="w1", **overrides):
    values = {"mode": sc.MODE_READ_ONLY, "attested_capabilities": ALL_CAPS, "upstream_state": sc.UPSTREAM_NONE}
    values.update(overrides)
    return sc.ScheduleItem(item_id=item_id, **values)


def request(*items, **overrides):
    items = items or (item(),)
    values = {"dag_id": "fdb-dag-1", "item_count": len(items), "items": tuple(items), "as_of_utc": AS_OF}
    values.update(overrides)
    return sc.ScheduleRequest(**values)


def parallel(*items, max_concurrency=4, **overrides):
    return request(*items, concurrency_preference=sc.CONCURRENCY_PARALLEL, max_concurrency=max_concurrency,
                   **overrides)


def decisions(plan):
    return {d.item_id: d.decision for d in plan.decisions}


def refused_with(test, req, reason):
    plan = sc.plan_batch(req)
    test.assertEqual(plan.outcome, sc.REFUSED)
    test.assertIn(reason, plan.request_reasons)
    test.assertEqual(plan.decisions, ())
    test.assertIsNone(plan.dag_id)
    return plan


# ---------------------------------------------------------------------------
class PositivePlanningTests(unittest.TestCase):
    def test_single_ready_item_is_schedulable_in_slot_zero(self):
        plan = sc.plan_batch(request())
        self.assertEqual(plan.outcome, sc.SCHEDULABLE)
        d = plan.decision_of("w1")
        self.assertEqual((d.decision, d.reasons, d.slot), (sc.SCHEDULABLE, (), 0))
        self.assertEqual(plan.dag_id, "fdb-dag-1")
        self.assertEqual(plan.item_count, 1)

    def test_parallel_assigns_slots_by_priority_then_declared_order(self):
        plan = sc.plan_batch(parallel(item("a", priority=0), item("b", priority=5), item("c", priority=0),
                                      max_concurrency=2))
        self.assertEqual(plan.decision_of("b").slot, 0)
        self.assertEqual(plan.decision_of("a").slot, 1)
        self.assertEqual(plan.decision_of("c").decision, sc.WAITING)
        self.assertEqual(plan.decision_of("c").reasons, (sc.CONCURRENCY_LIMIT_REACHED,))

    def test_serial_preference_plans_exactly_one_slot(self):
        plan = sc.plan_batch(request(item("a"), item("b"), item("c"), max_concurrency=16))
        self.assertEqual(plan.effective_concurrency, 1)
        self.assertEqual([d.decision for d in plan.decisions], [sc.SCHEDULABLE, sc.WAITING, sc.WAITING])

    def test_parallel_never_exceeds_max_concurrency(self):
        items = tuple(item(f"w{i}") for i in range(10))
        for cap in (1, 3, 10, 16):
            plan = sc.plan_batch(parallel(*items, max_concurrency=cap))
            self.assertEqual(sum(d.decision == sc.SCHEDULABLE for d in plan.decisions), min(cap, 10))

    def test_provider_limits_cap_per_provider_and_stay_neutral(self):
        plan = sc.plan_batch(parallel(
            item("a", provider_id="alpha"), item("b", provider_id="alpha"), item("c", provider_id="beta"),
            provider_limits=(("alpha", 1),)))
        self.assertEqual(decisions(plan), {"a": sc.SCHEDULABLE, "b": sc.WAITING, "c": sc.SCHEDULABLE})
        self.assertEqual(plan.decision_of("b").reasons, (sc.PROVIDER_LIMIT_REACHED,))

    def test_no_provider_is_special_cased(self):
        for pid in ("claude", "codex", "gemini", "x"):
            plan = sc.plan_batch(request(item(provider_id=pid)))
            self.assertEqual(plan.outcome, sc.SCHEDULABLE, pid)
        code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2].lower()
        for name in ("claude", "codex", "gemini", "openai", "anthropic"):
            self.assertNotIn(name, code, name)

    def test_satisfied_and_none_upstream_are_equivalent(self):
        a = sc.plan_batch(request(item(upstream_state=sc.UPSTREAM_NONE)))
        b = sc.plan_batch(request(item(upstream_state=sc.UPSTREAM_SATISFIED)))
        self.assertEqual((a.outcome, b.outcome), (sc.SCHEDULABLE, sc.SCHEDULABLE))

    def test_window_open_inside_bounds_is_schedulable(self):
        plan = sc.plan_batch(request(not_before_utc="2026-10-30T09:00:00Z", deadline_utc="2026-10-30T11:00:00Z"))
        self.assertEqual(plan.outcome, sc.SCHEDULABLE)


class HoldDecisionTests(unittest.TestCase):
    def test_window_not_open_is_waiting(self):
        plan = sc.plan_batch(request(not_before_utc="2026-10-30T11:00:00Z"))
        self.assertEqual(plan.outcome, sc.WAITING)
        self.assertEqual(plan.decisions[0].reasons, (sc.WINDOW_NOT_OPEN,))

    def test_window_expired_is_refused_at_and_after_deadline(self):
        for deadline in (AS_OF, "2026-10-30T09:59:59Z"):
            plan = sc.plan_batch(request(deadline_utc=deadline))
            self.assertEqual(plan.decisions[0].decision, sc.REFUSED, deadline)
            self.assertEqual(plan.decisions[0].reasons, (sc.WINDOW_EXPIRED,))

    def test_upstream_states_map_to_fixed_decisions(self):
        expected = {sc.UPSTREAM_PENDING: sc.WAITING, sc.UPSTREAM_BLOCKED: sc.REFUSED,
                    sc.UPSTREAM_UNKNOWN: sc.UNKNOWN}
        for state, decision in expected.items():
            self.assertEqual(sc.plan_batch(request(item(upstream_state=state))).decisions[0].decision, decision)

    def test_upstream_defaults_to_unknown_fail_closed(self):
        plan = sc.plan_batch(request(sc.ScheduleItem(item_id="w1", mode=sc.MODE_READ_ONLY,
                                                     attested_capabilities=ALL_CAPS)))
        self.assertEqual(plan.outcome, sc.UNKNOWN)
        self.assertIn(sc.UPSTREAM_STATE_UNKNOWN, plan.decisions[0].reasons)

    def test_unattested_capabilities_are_unknown(self):
        plan = sc.plan_batch(request(item(attested_capabilities=None)))
        self.assertEqual(plan.decisions[0].decision, sc.UNKNOWN)
        self.assertEqual(plan.decisions[0].reasons, (sc.CAPABILITIES_UNATTESTED,))

    def test_missing_attested_capability_is_refused(self):
        cases = [
            item(attested_capabilities=("READ_FILES",)),
            item(mode=sc.MODE_WRITE, attested_capabilities=("READ_FILES", "SEARCH_FILES")),
            item(required_capabilities=("TEST_EXECUTION",), attested_capabilities=("READ_FILES", "SEARCH_FILES")),
        ]
        for case in cases:
            d = sc.plan_batch(request(case)).decisions[0]
            self.assertEqual((d.decision, d.reasons), (sc.REFUSED, (sc.CAPABILITY_NOT_ATTESTED,)), case)

    def test_required_capabilities_mirror_runner_rule(self):
        self.assertEqual(sc.required_capabilities_for(item()), ("READ_FILES", "SEARCH_FILES"))
        self.assertEqual(sc.required_capabilities_for(item(mode=sc.MODE_WRITE, required_capabilities=("SHELL",))),
                         ("EDIT_FILES", "READ_FILES", "SEARCH_FILES", "SHELL", "WRITE_FILES"))

    def test_provider_unassigned_under_limits_is_unknown(self):
        plan = sc.plan_batch(parallel(item("a"), item("b", provider_id="alpha"), provider_limits=(("alpha", 1),)))
        self.assertEqual(plan.decision_of("a").reasons, (sc.PROVIDER_UNASSIGNED,))
        self.assertEqual(plan.decision_of("b").decision, sc.SCHEDULABLE)
        self.assertEqual(plan.outcome, sc.UNKNOWN)

    def test_in_batch_dependency_never_planned_concurrently(self):
        plan = sc.plan_batch(parallel(item("a"), item("b", depends_on=("a",), priority=99)))
        self.assertEqual(decisions(plan), {"a": sc.SCHEDULABLE, "b": sc.WAITING})
        self.assertEqual(plan.decision_of("b").reasons, (sc.DEPENDENCY_IN_BATCH,))

    def test_precedence_refused_over_unknown_over_waiting(self):
        d = sc.plan_batch(request(item(upstream_state=sc.UPSTREAM_BLOCKED, attested_capabilities=None),
                                  not_before_utc="2026-10-30T11:00:00Z")).decisions[0]
        self.assertEqual(d.decision, sc.REFUSED)
        self.assertEqual(d.reasons, (sc.UPSTREAM_IS_BLOCKED, sc.CAPABILITIES_UNATTESTED, sc.WINDOW_NOT_OPEN))
        d = sc.plan_batch(request(item(attested_capabilities=None, upstream_state=sc.UPSTREAM_PENDING))).decisions[0]
        self.assertEqual(d.decision, sc.UNKNOWN)

    def test_unknown_and_held_items_never_consume_slots(self):
        plan = sc.plan_batch(request(item("hi", priority=10, upstream_state=sc.UPSTREAM_UNKNOWN), item("lo")))
        self.assertEqual(plan.decision_of("hi").slot, None)
        self.assertEqual(plan.decision_of("lo").slot, 0)

    def test_batch_outcome_is_most_cautious_summary(self):
        cases = [
            ((item("a"), item("b", upstream_state=sc.UPSTREAM_UNKNOWN)), sc.UNKNOWN),
            ((item("a"), item("b", upstream_state=sc.UPSTREAM_BLOCKED)), sc.SCHEDULABLE),
            ((item("a", upstream_state=sc.UPSTREAM_PENDING), item("b", upstream_state=sc.UPSTREAM_BLOCKED)),
             sc.WAITING),
            ((item("a", upstream_state=sc.UPSTREAM_BLOCKED),), sc.REFUSED),
        ]
        for items, outcome in cases:
            self.assertEqual(sc.plan_batch(request(*items)).outcome, outcome, items)


class RequestRefusalTests(unittest.TestCase):
    def test_untyped_and_subclassed_requests_refused(self):
        class Sub(sc.ScheduleRequest):
            pass
        duck = type("Duck", (), dict(vars(request())))()
        for bad in (None, {}, "req", duck, Sub(**{f.name: getattr(request(), f.name)
                                                 for f in dataclasses.fields(sc.ScheduleRequest)})):
            plan = sc.plan_batch(bad)
            self.assertEqual(plan.request_reasons, (sc.REQUEST_NOT_TYPED,))

    def test_bool_is_never_accepted_as_int(self):
        refused_with(self, request(item(priority=True)), sc.PRIORITY_INVALID)
        refused_with(self, request(item_count=True), sc.ITEM_COUNT_INVALID)
        refused_with(self, parallel(item(), max_concurrency=True), sc.MAX_CONCURRENCY_INVALID)
        refused_with(self, request(schema_version=True), sc.SCHEMA_VERSION_UNSUPPORTED)
        refused_with(self, request(item(provider_id="a"), provider_limits=(("a", True),)), sc.PROVIDER_LIMITS_MALFORMED)

    def test_int_and_str_subclasses_refused(self):
        class MyInt(int):
            pass

        class MyStr(str):
            pass
        refused_with(self, request(item(priority=MyInt(1))), sc.PRIORITY_INVALID)
        refused_with(self, request(item(item_id=MyStr("w1"))), sc.ITEM_ID_INVALID)
        refused_with(self, request(item(mode=MyStr(sc.MODE_WRITE))), sc.MODE_UNKNOWN)

    def test_bounds_on_priority_count_and_concurrency(self):
        refused_with(self, request(item(priority=sc.MAX_PRIORITY + 1)), sc.PRIORITY_INVALID)
        refused_with(self, request(item(priority=sc.MIN_PRIORITY - 1)), sc.PRIORITY_INVALID)
        self.assertEqual(sc.plan_batch(request(item(priority=sc.MAX_PRIORITY))).outcome, sc.SCHEDULABLE)
        for bad in (0, sc.MAX_CONCURRENCY + 1, -1, 2.0):
            refused_with(self, parallel(item(), max_concurrency=bad), sc.MAX_CONCURRENCY_INVALID)
        many = tuple(item(f"w{i}") for i in range(sc.MAX_ITEMS + 1))
        refused_with(self, request(*many), sc.ITEMS_TOO_MANY)
        self.assertEqual(sc.plan_batch(request(*many[:sc.MAX_ITEMS])).item_count, sc.MAX_ITEMS)

    def test_empty_and_count_mismatch_refused(self):
        refused_with(self, request(items=(), item_count=1), sc.ITEMS_EMPTY)
        refused_with(self, request(item("a"), item("b"), item_count=1), sc.ITEM_COUNT_MISMATCH)
        refused_with(self, request(item_count=0), sc.ITEM_COUNT_INVALID)

    def test_duplicate_item_id_refused(self):
        refused_with(self, request(item("a"), item("a")), sc.ITEM_ID_DUPLICATE)

    def test_mutable_sequences_refused(self):
        refused_with(self, request(items=[item()]), sc.ITEMS_NOT_TUPLE)
        refused_with(self, request(item(required_capabilities=["SHELL"])), sc.CAPABILITIES_MALFORMED)
        refused_with(self, request(item(attested_capabilities=list(ALL_CAPS))), sc.ATTESTED_CAPABILITIES_MALFORMED)
        refused_with(self, request(item(depends_on=["x"])), sc.DEPENDS_ON_MALFORMED)
        refused_with(self, request(item(depends_on={"x"})), sc.DEPENDS_ON_MALFORMED)
        refused_with(self, request(provider_limits={"alpha": 1}), sc.PROVIDER_LIMITS_MALFORMED)
        refused_with(self, request(provider_limits=(["alpha", 1],)), sc.PROVIDER_LIMITS_MALFORMED)

    def test_items_must_be_typed(self):
        refused_with(self, request(items=({"item_id": "w1", "mode": "write"},), item_count=1), sc.ITEM_NOT_TYPED)

    def test_unknown_vocabulary_values_refused(self):
        refused_with(self, request(item(mode="WRITE")), sc.MODE_UNKNOWN)
        refused_with(self, request(item(required_capabilities=("ROOT",))), sc.CAPABILITY_UNKNOWN)
        refused_with(self, request(item(required_capabilities=("SHELL", "SHELL"), mode=sc.MODE_WRITE)),
                     sc.CAPABILITY_DUPLICATE)
        refused_with(self, request(item(attested_capabilities=("READ_FILES", "ROOT"))),
                     sc.ATTESTED_CAPABILITIES_MALFORMED)
        refused_with(self, request(item(upstream_state="DONE")), sc.UPSTREAM_STATE_INVALID)
        refused_with(self, request(concurrency_preference="AUTO"), sc.CONCURRENCY_PREFERENCE_UNKNOWN)
        refused_with(self, request(schema_version=2), sc.SCHEMA_VERSION_UNSUPPORTED)
        with self.assertRaises(TypeError):
            sc.ScheduleItem(item_id="w1", mode=sc.MODE_READ_ONLY, unknown_field=1)

    def test_shell_requires_write_mode(self):
        refused_with(self, request(item(required_capabilities=("SHELL",))), sc.SHELL_REQUIRES_WRITE_MODE)
        self.assertEqual(sc.plan_batch(request(item(mode=sc.MODE_WRITE, required_capabilities=("SHELL",)))).outcome,
                         sc.SCHEDULABLE)

    def test_paths_and_untrusted_ids_refused(self):
        for bad in ("", ".", "..", ".hidden", "a/b", "a\\b", "C:", "../x", "a b", "a\nb", "x" * 65, "ñ", "a\x00",
                    "C:\\Users\\x", "/etc/passwd"):
            refused_with(self, request(item(item_id=bad)), sc.ITEM_ID_INVALID)
            refused_with(self, request(dag_id=bad), sc.DAG_ID_INVALID)
        for bad in ("Claude", "a/b", "-x", "x" * 33, 7):
            refused_with(self, request(item(provider_id=bad)), sc.PROVIDER_ID_INVALID)

    def test_dependency_graph_errors_refused(self):
        refused_with(self, request(item("a", depends_on=("a",))), sc.DEPENDENCY_SELF)
        refused_with(self, request(item("a", depends_on=("zz",))), sc.DEPENDENCY_UNKNOWN)
        refused_with(self, request(item("a"), item("b", depends_on=("a", "a"))), sc.DEPENDENCY_DUPLICATE)
        refused_with(self, request(item("a", depends_on=("c",)), item("b", depends_on=("a",)),
                                   item("c", depends_on=("b",))), sc.DEPENDENCY_CYCLE)
        refused_with(self, request(item("a", depends_on=tuple(f"d{i}" for i in range(sc.MAX_DEPENDS_ON + 1)))),
                     sc.DEPENDS_ON_MALFORMED)

    def test_provider_limit_duplicates_and_bounds_refused(self):
        refused_with(self, request(provider_limits=(("alpha", 1), ("alpha", 2))), sc.PROVIDER_LIMIT_DUPLICATE)
        for bad in (0, sc.MAX_PROVIDER_LIMIT + 1):
            refused_with(self, request(provider_limits=(("alpha", bad),)), sc.PROVIDER_LIMITS_MALFORMED)

    def test_timestamps_must_be_aware_bounded_and_ordered(self):
        for bad in ("2026-10-30T10:00:00", "2026-10-30", "yesterday", "", None, 1730282400,
                    "2026-10-30T10:00:00+00:00" + " " * 20, "２０２６-10-30T10:00:00Z"):
            refused_with(self, request(as_of_utc=bad), sc.AS_OF_INVALID)
        refused_with(self, request(not_before_utc="soon"), sc.WINDOW_INVALID)
        refused_with(self, request(deadline_utc="2026-10-30T10:00:00"), sc.WINDOW_INVALID)
        refused_with(self, request(not_before_utc="2026-10-30T12:00:00Z", deadline_utc="2026-10-30T12:00:00Z"),
                     sc.WINDOW_INVERTED)

    def test_all_reasons_reported_in_vocabulary_order(self):
        plan = sc.plan_batch(request(item(item_id="a/b", priority="1", mode="x"), dag_id="..", max_concurrency=0))
        self.assertEqual(plan.request_reasons, sc._ordered(plan.request_reasons, sc.REQUEST_REASONS))
        self.assertTrue({sc.DAG_ID_INVALID, sc.ITEM_ID_INVALID, sc.PRIORITY_INVALID, sc.MODE_UNKNOWN,
                         sc.MAX_CONCURRENCY_INVALID} <= set(plan.request_reasons))

    def test_planner_never_raises_on_hostile_input(self):
        weird = (object(), b"x", 1.5, float("nan"), (None,), frozenset(), [], {})
        for value in weird:
            for name in ("dag_id", "item_count", "items", "as_of_utc", "not_before_utc", "deadline_utc",
                         "concurrency_preference", "max_concurrency", "provider_limits", "schema_version"):
                self.assertEqual(sc.plan_batch(request(**{name: value})).outcome, sc.REFUSED, (name, value))
            for name in ("item_id", "mode", "priority", "provider_id", "required_capabilities",
                         "attested_capabilities", "depends_on", "upstream_state"):
                self.assertEqual(sc.plan_batch(request(item(**{name: value}))).outcome, sc.REFUSED, (name, value))


class AuthorityTests(unittest.TestCase):
    def test_every_plan_grants_nothing(self):
        for plan in (sc.plan_batch(request()), sc.plan_batch(None), sc.plan_batch(parallel(item("a"), item("b")))):
            for flag in ALL_FLAGS:
                self.assertIs(getattr(plan, flag), False, flag)
            data = json.loads(sc.canonical_json(plan))
            for flag in ALL_FLAGS:
                self.assertIs(data[flag], False, flag)
            self.assertEqual(data["marker"], sc.SCHEDULER_MARKER)

    def test_authority_flags_not_fields_and_not_settable(self):
        names = {f.name for f in dataclasses.fields(sc.BatchPlan)} | {f.name for f in dataclasses.fields(sc.ItemDecision)}
        self.assertFalse(names & set(ALL_FLAGS))
        plan = sc.plan_batch(request())
        for flag in ALL_FLAGS:
            with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
                setattr(plan, flag, True)
            with self.assertRaises(TypeError):
                dataclasses.replace(plan, **{flag: True})
        for cls in (sc.ScheduleItem, sc.ScheduleRequest):
            self.assertFalse({f.name for f in dataclasses.fields(cls)} & set(ALL_FLAGS))

    def test_subclass_cannot_serialize_authority(self):
        class Evil(sc.BatchPlan):
            @property
            def execution_allowed(self):
                return True

            def to_dict(self):
                return {"execution_allowed": True}
        plan = sc.plan_batch(request())
        evil = Evil(**{f.name: getattr(plan, f.name) for f in dataclasses.fields(sc.BatchPlan)})
        with self.assertRaises(TypeError):
            sc.canonical_json(evil)

    def test_hand_made_decision_cannot_overclaim(self):
        with self.assertRaises(ValueError):
            sc.ItemDecision(item_id="a", decision=sc.SCHEDULABLE, reasons=(sc.UPSTREAM_STATE_UNKNOWN,), priority=0,
                            slot=0)
        with self.assertRaises(ValueError):
            sc.ItemDecision(item_id="a", decision=sc.WAITING, reasons=(), priority=0, slot=None)
        with self.assertRaises(ValueError):
            sc.ItemDecision(item_id="a", decision=sc.UNKNOWN, reasons=(sc.UPSTREAM_STATE_UNKNOWN,), priority=0, slot=0)
        with self.assertRaises(ValueError):
            sc.ItemDecision(item_id="a", decision=sc.SCHEDULABLE, reasons=(), priority=0, slot=None)
        with self.assertRaises(ValueError):
            sc.ItemDecision(item_id="a", decision=sc.WAITING, reasons=("MAYBE",), priority=0, slot=None)

    def test_hand_made_plan_cannot_exceed_capacity_or_misstate_outcome(self):
        plan = sc.plan_batch(parallel(item("a"), item("b"), max_concurrency=2))
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, effective_concurrency=1)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, outcome=sc.WAITING)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, concurrency_preference=sc.CONCURRENCY_SERIAL)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, item_count=3)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, decisions=plan.decisions + plan.decisions[:1], item_count=3)
        with self.assertRaises(ValueError):
            dataclasses.replace(sc.plan_batch(None), dag_id="x")
        with self.assertRaises(ValueError):
            dataclasses.replace(sc.plan_batch(None), outcome=sc.SCHEDULABLE)

    def test_schedulable_never_means_authorized_and_unknown_never_schedulable(self):
        for state in sc.UPSTREAM_STATES:
            for attested in (None, (), ALL_CAPS):
                plan = sc.plan_batch(request(item(upstream_state=state, attested_capabilities=attested)))
                d = plan.decisions[0]
                if state == sc.UPSTREAM_UNKNOWN or attested is None:
                    self.assertNotEqual(d.decision, sc.SCHEDULABLE)
                self.assertFalse(plan.execution_allowed or plan.dispatch_allowed or plan.authorizes_action)


class DeterminismAndSerializationTests(unittest.TestCase):
    def test_canonical_json_deterministic_and_pinned_shape(self):
        req = parallel(item("a", priority=1), item("b", depends_on=("a",)))
        texts = {sc.canonical_json(sc.plan_batch(req)) for _ in range(5)}
        self.assertEqual(len(texts), 1)
        data = json.loads(texts.pop())
        self.assertEqual(set(data), {"schema", "schema_version", "outcome", "dag_id", "item_count",
                                     "request_fingerprint", "concurrency_preference", "effective_concurrency",
                                     "request_reasons", "counts", "decisions", "marker", *ALL_FLAGS})
        self.assertEqual((data["schema"], data["schema_version"]), (sc.SCHEMA, sc.SCHEMA_VERSION))
        self.assertEqual(data["counts"], {sc.SCHEDULABLE: 1, sc.WAITING: 1, sc.REFUSED: 0, sc.UNKNOWN: 0})
        self.assertEqual(set(data["decisions"][0]), {"item_id", "decision", "reasons", "priority", "slot"})

    def test_equivalent_requests_share_fingerprint(self):
        a = request(item(mode=sc.MODE_WRITE, required_capabilities=("SHELL", "TEST_EXECUTION")),
                    as_of_utc="2026-10-30T12:00:00+02:00", provider_limits=(("b", 1), ("a", 2)))
        b = request(item(mode=sc.MODE_WRITE, required_capabilities=("TEST_EXECUTION", "SHELL")),
                    as_of_utc="2026-10-30T10:00:00Z", provider_limits=(("a", 2), ("b", 1)))
        self.assertEqual(sc.canonical_request_json(a), sc.canonical_request_json(b))
        self.assertEqual(sc.plan_batch(a).request_fingerprint, sc.plan_batch(b).request_fingerprint)
        self.assertNotEqual(sc.plan_batch(a).request_fingerprint,
                            sc.plan_batch(request(item("other"))).request_fingerprint)

    def test_item_order_is_semantic_tie_break(self):
        a = sc.plan_batch(request(item("x"), item("y")))
        b = sc.plan_batch(request(item("y"), item("x")))
        self.assertEqual(a.decision_of("x").slot, 0)
        self.assertEqual(b.decision_of("y").slot, 0)
        self.assertNotEqual(a.request_fingerprint, b.request_fingerprint)

    def test_canonical_request_json_refuses_invalid(self):
        with self.assertRaises(ValueError):
            sc.canonical_request_json(request(dag_id="a/b"))
        with self.assertRaises(ValueError):
            sc.canonical_request_json(None)
        data = json.loads(sc.canonical_request_json(request()))
        self.assertEqual((data["schema"], data["schema_version"]), (sc.REQUEST_SCHEMA, sc.REQUEST_SCHEMA_VERSION))
        self.assertEqual(data["as_of_utc"], "2026-10-30T10:00:00Z")

    def test_worst_case_sizes_fit_bound(self):
        def wid(i):
            return f"{i:02d}" + "x" * 62
        items = tuple(
            sc.ScheduleItem(item_id=wid(i), mode=sc.MODE_WRITE, priority=sc.MIN_PRIORITY, provider_id="p" * 32,
                            required_capabilities=ALL_CAPS, attested_capabilities=ALL_CAPS,
                            depends_on=tuple(wid(j) for j in range(max(0, i - sc.MAX_DEPENDS_ON), i)),
                            upstream_state=sc.UPSTREAM_SATISFIED)
            for i in range(sc.MAX_ITEMS))
        req = parallel(*items, max_concurrency=sc.MAX_CONCURRENCY, provider_limits=(("p" * 32, 16),),
                       not_before_utc="2026-10-30T09:00:00.123456+00:00", deadline_utc="2026-10-30T11:00:00+00:00")
        self.assertLessEqual(len(sc.canonical_request_json(req)), sc.MAX_CANONICAL_JSON_BYTES)
        plan = sc.plan_batch(req)
        self.assertEqual(plan.item_count, sc.MAX_ITEMS)
        self.assertLessEqual(len(sc.canonical_json(plan)), sc.MAX_CANONICAL_JSON_BYTES)

    def test_size_limit_fails_closed(self):
        with mock.patch.object(sc, "MAX_CANONICAL_JSON_BYTES", 64):
            plan = sc.plan_batch(request())
            self.assertEqual(plan.request_reasons, (sc.REQUEST_TOO_LARGE,))
            self.assertEqual(plan.outcome, sc.REFUSED)
            with self.assertRaises(ValueError):
                sc.canonical_request_json(request())
        plan = sc.plan_batch(request())
        with mock.patch.object(sc, "MAX_CANONICAL_JSON_BYTES", 64):
            with self.assertRaises(ValueError):
                sc.canonical_json(plan)

    def test_output_carries_no_free_text_or_raw_input(self):
        secret = "sk-SECRET-token user@example.com C:\\Users\\x Work Order text"
        plan = sc.plan_batch(request(item(item_id=secret)))
        text = sc.canonical_json(plan)
        for word in ("SECRET", "example.com", "Users", "Work Order"):
            self.assertNotIn(word, text)
        names = {f.name for cls in (sc.ScheduleItem, sc.ScheduleRequest) for f in dataclasses.fields(cls)}
        for word in ("path", "text", "message", "token", "secret", "email", "prompt", "stdout", "stderr", "body",
                     "metadata", "worktree", "work_order", "note", "description"):
            self.assertFalse([n for n in names if word in n.split("_")], word)

    def test_plan_values_are_only_validated_ids_codes_ints_and_bools(self):
        vocab = set(sc.DECISIONS) | set(sc.ITEM_REASONS) | set(sc.REQUEST_REASONS) | set(sc.CONCURRENCY_PREFERENCES)
        plan = sc.plan_batch(parallel(item("a"), item("b", upstream_state=sc.UPSTREAM_PENDING)))
        data = json.loads(sc.canonical_json(plan))
        for d in data["decisions"]:
            self.assertIn(d["decision"], vocab)
            self.assertTrue(set(d["reasons"]) <= vocab)
        self.assertRegex(data["request_fingerprint"], r"^[0-9a-f]{64}$")


class ImmutabilityAndPurityTests(unittest.TestCase):
    def test_inputs_and_outputs_frozen(self):
        req = request()
        plan = sc.plan_batch(req)
        for obj, name in ((req, "dag_id"), (req.items[0], "priority"), (plan, "outcome"),
                          (plan.decisions[0], "decision")):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(obj, name, "x")
        self.assertIs(type(plan.decisions), tuple)
        self.assertIs(type(plan.request_reasons), tuple)

    def test_preview_never_mutates_request(self):
        req = parallel(item("a", depends_on=()), item("b", depends_on=("a",)), provider_limits=(("alpha", 1),))
        before = copy.deepcopy(req)
        before_text = sc.canonical_request_json(req)
        sc.plan_batch(req)
        sc.plan_batch(req)
        self.assertEqual(req, before)
        self.assertEqual(sc.canonical_request_json(req), before_text)

    def test_no_clock_io_process_or_network(self):
        def boom(*a, **k):
            raise AssertionError("I/O or clock attempted")
        patches = [mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom),
                   mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom),
                   mock.patch.object(os, "listdir", boom), mock.patch.object(os, "scandir", boom),
                   mock.patch.object(os, "stat", boom), mock.patch.object(os, "system", boom),
                   mock.patch.object(os, "getenv", boom), mock.patch.object(time, "time", boom)]
        for p in patches:
            p.start()
        try:
            for req in (request(), None, parallel(item("a"), item("b", depends_on=("a",))), request(dag_id="a/b")):
                sc.canonical_json(sc.plan_batch(req))
        finally:
            for p in reversed(patches):
                p.stop()

    def test_module_imports_only_pure_stdlib(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imported, {"__future__", "dataclasses", "datetime", "hashlib", "json", "re", "typing"})
        code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
        code = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
        for word in ("runner_", "claude_runner", "fabric_director", "subprocess", "shutil", "socket", "open(",
                     "Path(", "os.", "environ", "eval(", "exec(", "__import__", "importlib", "git", ".now(",
                     "utcnow", "today(", "import time", "time.time(", "monotonic", "threading", "ThreadPool", "multiprocessing", "random"):
            self.assertNotIn(word, code, word)

    def test_no_mutable_module_state_changes(self):
        snapshot = {k: copy.deepcopy(v) for k, v in vars(sc).items()
                    if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
        sc.plan_batch(request())
        sc.plan_batch(parallel(item("a"), item("b", provider_id="alpha"), provider_limits=(("alpha", 1),)))
        sc.plan_batch(None)
        self.assertEqual({k: v for k, v in vars(sc).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_upper_snake(self):
        for vocab in (sc.REQUEST_REASONS, sc.ITEM_REASONS, sc.DECISIONS, sc.UPSTREAM_STATES,
                      sc.CONCURRENCY_PREFERENCES):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(sc.REFUSING_REASONS) & set(sc.UNKNOWN_REASONS) & set(sc.WAITING_REASONS))
        self.assertFalse(set(sc.REQUEST_REASONS) & set(sc.ITEM_REASONS))
        self.assertEqual(sc.DECISIONS, ("SCHEDULABLE", "WAITING", "REFUSED", "UNKNOWN"))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


class RunnerContractPinTests(unittest.TestCase):
    """Only the tests import the Runner/Fabric, to prove the mirrored
    constants match the real ones; the contract never does."""

    def test_limits_mirror_runner_and_blueprint(self):
        from scripts.ai import fabric_dag_blueprint, runner_pipeline
        self.assertEqual(sc.MAX_CONCURRENCY, runner_pipeline.MAX_PIPELINE_WORKERS)
        self.assertEqual(sc.MAX_ITEMS, fabric_dag_blueprint.MAX_BLUEPRINT_NODES)

    def test_modes_and_capabilities_mirror_runner_providers(self):
        from scripts.ai import fabric_provider_routing_policy as routing
        from scripts.ai import runner_providers
        self.assertEqual(sc.MODES, (runner_providers.MODE_READ_ONLY, runner_providers.MODE_WRITE))
        self.assertEqual(set(sc.CAPABILITIES), {c.value for c in runner_providers.Capability})
        self.assertEqual(sc.CAPABILITIES, routing.CAPABILITIES)
        self.assertEqual(sc._PROVIDER_ID_RE.pattern, routing._PROVIDER_ID_RE.pattern)
        for pid in runner_providers.registered_provider_ids():
            self.assertTrue(sc._valid_provider_id(pid), pid)

    def test_required_capabilities_match_runner_rule(self):
        from scripts.ai import runner_providers
        for mode in sc.MODES:
            for extra in ((), ("TEST_EXECUTION",), ("STRUCTURED_RESULT",)):
                policy = runner_providers.ExecutionPolicy(mode=mode, allow_shell=False)
                native = runner_providers.required_capabilities(policy, extra)
                self.assertEqual(sc.required_capabilities_for(item(mode=mode, required_capabilities=extra)),
                                 tuple(sorted(c.value for c in native)))

    def test_accepted_ids_are_runner_safe_segments(self):
        from scripts.ai import runner_pipeline
        for good in ("a", "w1", "fdb-20261030t093917114560-a6c665b7", "d02_integration", "a.b", "-x", "x" * 64):
            self.assertTrue(sc._safe_id(good), good)
            self.assertTrue(runner_pipeline._safe_segment(good), good)
        for bad in ("", ".", "..", ".x", "a/b", "x" * 65):
            self.assertFalse(sc._safe_id(bad), bad)

    def test_planning_order_mirrors_runner_dispatch_key(self):
        source = (REPO_ROOT / "scripts" / "ai" / "runner_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("key=lambda r: (-r.spec.priority, r.order)", source)
        plan = sc.plan_batch(parallel(item("a", priority=-1), item("b", priority=3), item("c", priority=3),
                                      max_concurrency=3))
        self.assertEqual([plan.decision_of(x).slot for x in ("b", "c", "a")], [0, 1, 2])

    def test_timestamps_accepted_by_runner_parser_semantics(self):
        from scripts.ai import runner_pipeline
        for value in ("2026-10-30T10:00:00Z", "2026-10-30T10:00:00+02:00"):
            self.assertIsNotNone(sc._parse_utc(value))
            self.assertIsNotNone(runner_pipeline._parse_iso(value))
            self.assertEqual(sc._parse_utc(value), runner_pipeline._parse_iso(value))
        self.assertIsNone(sc._parse_utc("2026-10-30T10:00:00"))
        self.assertIsNone(runner_pipeline._parse_iso("2026-10-30T10:00:00"))
        self.assertIsInstance(sc._parse_utc(AS_OF), datetime)


if __name__ == "__main__":
    unittest.main()
