"""FCP-9B-02: DAG planning and governed admission.

Every repository here is an ephemeral `git init` under a temporary directory
(the Runner pipeline tests' `_make_repo`) and every provider id is one of
their `KNOWN` ids; no real project worktree is ever a target. Structural
refusals are asserted by the NATIVE compiler codes. Node states are
synthetic observations; nothing is executed. Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_dag_blueprint as bp
from scripts.ai import fabric_scheduler_conflicts as cf
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import fabric_scheduler_plan as pl
from scripts.ai import fabric_scheduler_window as sw
from scripts.ai import runner_pipeline as rp
from scripts.tests.test_runner_pipeline import KNOWN, _git, _make_repo

MODULE_PATH = Path(pl.__file__)
TEST_PATH = Path(__file__).resolve()
AS_OF = "2026-10-30T12:00:00Z"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized")
REPOS = ("a", "b", "c", "d", "e")
MUTATING_GIT_SUBCOMMANDS = {
    "add", "am", "branch", "checkout", "cherry-pick", "clean", "commit", "fetch", "gc", "init", "merge", "mv",
    "prune", "pull", "push", "rebase", "reset", "restore", "revert", "rm", "stash", "switch", "tag",
    "update-ref", "worktree",
}
_DEFAULT = object()


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def _tree_snapshot(root: Path) -> dict:
    snapshot = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            stat = path.stat()
            snapshot[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


class PlanTestBase(unittest.TestCase):
    """Repositories are created once per class and only ever read."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="fcp9b02")
        cls.root = Path(cls._tmp).resolve()
        cls.stable = _make_repo(cls.root, "stable")
        cls.repos = {n: _make_repo(cls.root, n) for n in REPOS}
        for repo in cls.repos.values():
            _git(repo, "checkout", "-q", "-b", "feature/fcp9b02-test")
        (cls.root / "work_orders").mkdir()
        cls.wos = {}
        for name in REPOS:
            path = cls.root / "work_orders" / f"wo_{name}.md"
            path.write_text(f"Work Order {name}.\n", encoding="utf-8")
            cls.wos[name] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def node(self, nid, repo=None, *, depends_on=(), provider="fake", mode="read-only", **extra):
        repo = repo or nid
        return bp.BlueprintNode(
            id=nid, worktree=str(self.repos[repo]), work_order=str(self.wos[repo]), provider=provider, mode=mode,
            depends_on=depends_on, **extra,
        )

    def blueprint(self, nodes, pipeline_id="fcp9b02-dag", **extra):
        return bp.DagBlueprint(pipeline_id=pipeline_id, nodes=tuple(nodes), **extra)

    def states(self, blueprint, default="QUEUED", **overrides):
        return tuple((n.id, overrides.get(n.id, default)) for n in blueprint.nodes)

    def conflicts(self, blueprint, *, worktrees=None, dag_id=None, roots=None):
        worktrees = worktrees or {}
        workers = tuple(
            cf.WorkerClaims(worker_id=n.id, mode=n.mode, worktree=worktrees.get(n.id, n.worktree),
                            worktree_link_state=cf.LINK_NONE)
            for n in blueprint.nodes
        )
        return cf.ConflictRequest(dag_id=dag_id or blueprint.pipeline_id,
                                  allowed_roots=roots if roots is not None else (str(self.root),), workers=workers)

    def request(self, blueprint, *, states=_DEFAULT, conflicts=_DEFAULT, as_of=AS_OF, **kw):
        return pl.DagPlanRequest(
            blueprint=blueprint, as_of_utc=as_of,
            node_states=self.states(blueprint) if states is _DEFAULT else states,
            conflict_request=self.conflicts(blueprint) if conflicts is _DEFAULT else conflicts, **kw,
        )

    def run_plan(self, request):
        return pl.plan_dag(request, self_worktree=self.stable, registered_providers=KNOWN)

    def plan(self, blueprint, **kw):
        return self.run_plan(self.request(blueprint, **kw))

    def decisions(self, plan):
        return {d.node_id: (d.decision, d.reasons) for d in plan.decisions}

    def assertRefused(self, plan, *reasons):
        self.assertEqual(plan.outcome, pl.REFUSED)
        for reason in reasons:
            self.assertIn(reason, plan.request_reasons)
        self.assertEqual((plan.decisions, plan.dag_id, plan.request_fingerprint, plan.planning_order),
                         ((), None, None, ()))
        return plan

    def branching(self, **extra):
        return self.blueprint([
            self.node("a"), self.node("b", depends_on=("a",)), self.node("c", depends_on=("a",)),
            self.node("d", depends_on=("b", "c")),
        ], **extra)


# ---------------------------------------------------------------------------
# Branching DAG and independent parallelism
# ---------------------------------------------------------------------------
class BranchingDagTests(PlanTestBase):
    def test_independent_nodes_are_admitted_in_parallel_up_to_max_workers(self):
        blueprint = self.blueprint([self.node(n) for n in ("a", "b", "c", "d")], max_workers=4)
        plan = self.plan(blueprint)
        self.assertEqual(plan.outcome, pl.ADMISSIBLE)
        self.assertEqual(plan.admitted, ("a", "b", "c", "d"))
        self.assertEqual([d.slot for d in plan.decisions], [0, 1, 2, 3])
        self.assertEqual(plan.effective_max_workers, 4)

    def test_default_cap_is_the_runner_default_max_workers(self):
        plan = self.plan(self.blueprint([self.node(n) for n in ("a", "b", "c")]))
        self.assertEqual(plan.effective_max_workers, rp.DEFAULT_MAX_WORKERS)
        self.assertEqual(plan.admitted, ("a", "b"))
        self.assertEqual(self.decisions(plan)["c"], (pl.WAITING, (pl.WORKER_LIMIT_REACHED,)))

    def test_initial_batch_of_a_branching_dag_holds_only_the_root(self):
        plan = self.plan(self.branching(max_workers=4))
        self.assertEqual(plan.admitted, ("a",))
        for nid in ("b", "c", "d"):
            self.assertEqual(self.decisions(plan)[nid], (pl.WAITING, (pl.DEPENDENCY_PENDING,)))

    def test_fan_out_after_root_success_is_parallel(self):
        blueprint = self.branching(max_workers=4)
        plan = self.plan(blueprint, states=self.states(blueprint, a="SUCCESS"))
        self.assertEqual(plan.admitted, ("b", "c"))
        self.assertEqual(self.decisions(plan)["a"], (pl.INACTIVE, (pl.NODE_TERMINAL,)))
        self.assertEqual(self.decisions(plan)["d"], (pl.WAITING, (pl.DEPENDENCY_PENDING,)))

    def test_fan_in_waits_for_every_parent_and_running_parent_holds_a_slot(self):
        blueprint = self.branching(max_workers=2)
        plan = self.plan(blueprint, states=self.states(blueprint, a="SUCCESS", b="SUCCESS", c="RUNNING"))
        self.assertEqual(self.decisions(plan)["c"], (pl.INACTIVE, (pl.NODE_RUNNING,)))
        self.assertEqual(self.decisions(plan)["d"], (pl.WAITING, (pl.DEPENDENCY_PENDING,)))
        self.assertEqual(plan.outcome, pl.WAITING)
        done = self.plan(blueprint, states=self.states(blueprint, a="SUCCESS", b="SUCCESS", c="SUCCESS"))
        self.assertEqual(done.admitted, ("d",))
        idle = self.plan(blueprint, states=self.states(blueprint, default="SUCCESS"))
        self.assertEqual(idle.outcome, pl.IDLE)
        self.assertEqual(idle.admitted, ())

    def test_native_dependency_policies_are_respected(self):
        for policy, parent, expected in (
                (None, "PARTIAL", pl.REFUSED), ("success_or_partial", "PARTIAL", pl.ADMISSIBLE),
                ("completed", "FAILED", pl.ADMISSIBLE), (None, "FAILED", pl.REFUSED),
                ("success", "CANCELLED", pl.REFUSED), ("completed", "RETRY_WAIT", pl.WAITING)):
            blueprint = self.blueprint([self.node("a"), self.node("b", depends_on=("a",), dependency_policy=policy)])
            plan = self.plan(blueprint, states=self.states(blueprint, a=parent))
            self.assertEqual(self.decisions(plan)["b"][0], expected, (policy, parent))
            if expected == pl.REFUSED:
                self.assertEqual(self.decisions(plan)["b"][1], (pl.DEPENDENCY_UNSATISFIABLE,))

    def test_blocked_parent_under_an_accepting_policy_is_ambiguous_not_guessed(self):
        blueprint = self.blueprint([self.node("a"), self.node("b", depends_on=("a",), dependency_policy="completed")])
        plan = self.plan(blueprint, states=self.states(blueprint, a="BLOCKED"))
        self.assertEqual(self.decisions(plan)["b"], (pl.UNKNOWN, (pl.DEPENDENCY_STATE_AMBIGUOUS,)))
        self.assertEqual(plan.outcome, pl.UNKNOWN)


# ---------------------------------------------------------------------------
# Order, ties and fairness
# ---------------------------------------------------------------------------
class OrderTests(PlanTestBase):
    def test_priority_first_then_declared_order(self):
        blueprint = self.blueprint([self.node("a", priority=1), self.node("b", priority=5), self.node("c"),
                                    self.node("d", priority=5)], max_workers=2)
        plan = self.plan(blueprint)
        self.assertEqual(plan.planning_order, ("b", "d", "a", "c"))
        self.assertEqual(plan.admitted, ("b", "d"))

    def test_ties_break_stably_by_declared_order(self):
        forward = self.plan(self.blueprint([self.node(n) for n in ("a", "b", "c")], max_workers=1))
        reverse = self.plan(self.blueprint([self.node(n) for n in ("c", "b", "a")], max_workers=1))
        self.assertEqual(forward.admitted, ("a",))
        self.assertEqual(reverse.admitted, ("c",))
        self.assertEqual(reverse.planning_order, ("c", "b", "a"))

    def test_tied_nodes_never_starve_and_progress_in_declared_order(self):
        ids = ("a", "b", "c", "d", "e")
        blueprint = self.blueprint([self.node(n) for n in ids], max_workers=2)
        states = dict(self.states(blueprint))
        admitted_sequence = []
        for _ in range(len(ids)):
            plan = self.plan(blueprint, states=tuple(states.items()))
            if plan.outcome == pl.IDLE:
                break
            self.assertTrue(plan.admitted)
            for nid in plan.admitted:
                admitted_sequence.append(nid)
                states[nid] = "SUCCESS"  # the TEST plays the Runner; the planner invents nothing
        self.assertEqual(admitted_sequence, list(ids))

    def test_a_provider_limited_tie_keeps_precedence_on_the_next_plan(self):
        blueprint = self.blueprint([self.node("a", provider="codex"), self.node("b", provider="codex"),
                                    self.node("c", provider="fake")], max_workers=3, provider_limits=(("codex", 1),))
        plan = self.plan(blueprint)
        self.assertEqual(plan.admitted, ("a", "c"))
        self.assertEqual(self.decisions(plan)["b"], (pl.WAITING, (pl.PROVIDER_LIMIT_REACHED,)))
        nxt = self.plan(blueprint, states=self.states(blueprint, a="SUCCESS", c="RUNNING"))
        self.assertEqual(nxt.admitted, ("b",))


# ---------------------------------------------------------------------------
# Limits are upper bounds, never raised
# ---------------------------------------------------------------------------
class LimitTests(PlanTestBase):
    def test_request_max_workers_only_narrows(self):
        blueprint = self.blueprint([self.node(n) for n in ("a", "b", "c", "d")], max_workers=2)
        self.assertEqual(self.plan(blueprint, max_workers=4).effective_max_workers, 2)
        self.assertEqual(self.plan(blueprint, max_workers=4).admitted, ("a", "b"))
        self.assertEqual(self.plan(blueprint, max_workers=1).admitted, ("a",))

    def test_request_provider_limits_only_narrow(self):
        blueprint = self.blueprint([self.node(n, provider="codex") for n in ("a", "b", "c")], max_workers=3,
                                   provider_limits=(("codex", 2),))
        self.assertEqual(self.plan(blueprint, provider_limits=(("codex", 3),)).admitted, ("a", "b"))
        self.assertEqual(self.plan(blueprint, provider_limits=(("codex", 1),)).admitted, ("a",))
        widened = self.plan(blueprint, provider_limits=(("codex", 3),))
        self.assertEqual(widened.effective_provider_limits, (("codex", 2),))
        fresh = self.plan(self.blueprint([self.node(n) for n in ("a", "b")]), provider_limits=(("fake", 1),))
        self.assertEqual(fresh.effective_provider_limits, (("fake", 1),))
        self.assertEqual(fresh.admitted, ("a",))

    def test_running_nodes_consume_global_and_provider_capacity(self):
        blueprint = self.blueprint([self.node("a", provider="codex"), self.node("b", provider="codex"),
                                    self.node("c", provider="fake"), self.node("d", provider="fake")],
                                   max_workers=2, provider_limits=(("codex", 1),))
        plan = self.plan(blueprint, states=self.states(blueprint, a="RUNNING"))
        self.assertEqual(self.decisions(plan)["b"], (pl.WAITING, (pl.PROVIDER_LIMIT_REACHED,)))
        self.assertEqual(plan.admitted, ("c",))
        self.assertEqual(self.decisions(plan)["d"], (pl.WAITING, (pl.WORKER_LIMIT_REACHED,)))

    def test_observed_overcommit_admits_nothing(self):
        blueprint = self.blueprint([self.node(n) for n in ("a", "b", "c")], max_workers=1)
        plan = self.plan(blueprint, states=self.states(blueprint, a="RUNNING", b="RUNNING"))
        self.assertEqual(plan.admitted, ())
        self.assertEqual(self.decisions(plan)["c"], (pl.WAITING, (pl.WORKER_LIMIT_REACHED,)))

    def test_provider_hold_states_hold_only_that_provider(self):
        for holding in ("WAITING_PROVIDER_QUOTA", "BLOCKED_PROVIDER_AUTH"):
            blueprint = self.blueprint([self.node("a", provider="codex"), self.node("b", provider="codex"),
                                        self.node("c", provider="fake")], max_workers=3)
            plan = self.plan(blueprint, states=self.states(blueprint, a=holding))
            self.assertEqual(self.decisions(plan)["a"], (pl.INACTIVE, (pl.NODE_NOT_PENDING,)))
            self.assertEqual(self.decisions(plan)["b"], (pl.WAITING, (pl.PROVIDER_HELD,)))
            self.assertEqual(plan.admitted, ("c",))


# ---------------------------------------------------------------------------
# Conflicts and windows combined
# ---------------------------------------------------------------------------
class DiagnosticsTests(PlanTestBase):
    def test_writers_on_one_worktree_are_never_admitted_together(self):
        blueprint = self.blueprint([self.node("a", "a", mode="write"), self.node("b", "a", mode="write"),
                                    self.node("c")], max_workers=3)
        plan = self.plan(blueprint)
        self.assertEqual(plan.admitted, ("a", "c"))
        self.assertEqual(self.decisions(plan)["b"], (pl.WAITING, (pl.CONFLICT_WITH_ADMITTED,)))

    def test_readers_share_a_worktree(self):
        blueprint = self.blueprint([self.node("a", "a"), self.node("b", "a")], max_workers=2)
        self.assertEqual(self.plan(blueprint).admitted, ("a", "b"))

    def test_conflict_with_a_running_node_waits(self):
        blueprint = self.blueprint([self.node("a", "a", mode="write"), self.node("b", "a")], max_workers=2)
        plan = self.plan(blueprint, states=self.states(blueprint, a="RUNNING"))
        self.assertEqual(self.decisions(plan)["b"], (pl.WAITING, (pl.CONFLICT_WITH_RUNNING,)))

    def test_unidentified_footprint_is_unknown_and_never_admitted(self):
        blueprint = self.blueprint([self.node("a"), self.node("b")], max_workers=2)
        plan = self.plan(blueprint, conflicts=self.conflicts(blueprint, worktrees={"b": None}))
        self.assertEqual(self.decisions(plan)["b"], (pl.UNKNOWN, (pl.CONFLICT_UNIDENTIFIED,)))
        self.assertEqual(plan.admitted, ("a",))
        self.assertEqual(plan.outcome, pl.UNKNOWN)

    def test_a_running_node_with_an_unidentified_footprint_holds_everyone(self):
        blueprint = self.blueprint([self.node("a"), self.node("b"), self.node("c")], max_workers=3)
        plan = self.plan(blueprint, states=self.states(blueprint, a="RUNNING"),
                         conflicts=self.conflicts(blueprint, worktrees={"a": None}))
        self.assertEqual(plan.admitted, ())
        for nid in ("b", "c"):
            self.assertEqual(self.decisions(plan)[nid], (pl.WAITING, (pl.CONFLICT_WITH_RUNNING,)))

    def test_missing_conflict_analysis_fails_closed(self):
        blueprint = self.blueprint([self.node("a"), self.node("b")])
        plan = self.plan(blueprint, conflicts=None)
        self.assertEqual(plan.outcome, pl.UNKNOWN)
        self.assertEqual(plan.admitted, ())
        self.assertTrue(all(pl.CONFLICTS_UNASSESSED in d.reasons for d in plan.decisions))

    def test_unknown_states_fail_closed_for_every_peer(self):
        blueprint = self.branching(max_workers=4)
        plan = self.plan(blueprint, states=(("a", "SUCCESS"), ("b", "QUEUED"), ("c", "QUEUED")))
        self.assertEqual(self.decisions(plan)["d"], (pl.UNKNOWN, (pl.NODE_STATE_UNKNOWN,)))
        for nid in ("b", "c"):
            self.assertEqual(self.decisions(plan)[nid], (pl.UNKNOWN, (pl.PEER_STATE_UNKNOWN,)))
        self.assertEqual((plan.outcome, plan.admitted), (pl.UNKNOWN, ()))
        unknown_parent = self.plan(blueprint, states=self.states(blueprint, a="UNKNOWN"))
        self.assertIn(pl.DEPENDENCY_STATE_UNKNOWN, self.decisions(unknown_parent)["b"][1])

    def test_window_wait_and_expiry_come_from_the_native_manifest_bounds(self):
        nodes = [self.node("a"), self.node("b")]
        waiting = self.plan(self.blueprint(nodes, not_before_utc="2026-10-30T13:00:00+00:00"))
        self.assertEqual((waiting.window_status, waiting.admitted), (sw.WAIT_UNTIL, ()))
        self.assertEqual(self.decisions(waiting)["a"], (pl.WAITING, (pl.WINDOW_NOT_OPEN,)))
        expired = self.plan(self.blueprint(nodes, deadline_utc="2026-10-30T12:00:00+00:00"))
        self.assertEqual(expired.window_status, sw.EXPIRED)
        self.assertEqual(self.decisions(expired)["a"], (pl.REFUSED, (pl.WINDOW_EXPIRED,)))
        self.assertEqual(expired.outcome, pl.REFUSED)
        self.assertEqual(expired.request_reasons, ())
        open_ = self.plan(self.blueprint(nodes, not_before_utc="2026-10-30T12:00:00Z",
                                         deadline_utc="2026-10-30T12:00:01Z"))
        self.assertEqual(open_.window_status, sw.READY)

    def test_unevaluable_window_is_refused(self):
        plan = self.plan(self.blueprint([self.node("a"), self.node("b")], deadline_utc="2028-01-01T00:00:00Z"))
        self.assertRefused(plan, pl.WINDOW_INVALID)


# ---------------------------------------------------------------------------
# Refusals, delegation and mismatches
# ---------------------------------------------------------------------------
class RefusalTests(PlanTestBase):
    def test_malformed_requests_are_refused_before_the_compiler_runs(self):
        blueprint = self.blueprint([self.node("a"), self.node("b")])
        cases = (
            (dict(schema_version=2), pl.SCHEMA_VERSION_UNSUPPORTED),
            (dict(schema_version=True), pl.SCHEMA_VERSION_UNSUPPORTED),
            (dict(as_of="2026-10-30T12:00:00"), pl.AS_OF_INVALID),
            (dict(as_of=None), pl.AS_OF_INVALID),
            (dict(states=[("a", "QUEUED")]), pl.NODE_STATES_MALFORMED),
            (dict(states=(("a/..", "QUEUED"),)), pl.NODE_STATES_MALFORMED),
            (dict(states=(("a", "DONE"),)), pl.NODE_STATE_INVALID),
            (dict(states=(("a", "QUEUED"), ("a", "READY"))), pl.NODE_STATE_DUPLICATE),
            (dict(conflicts="graph"), pl.CONFLICT_REQUEST_NOT_TYPED),
            (dict(max_workers=0), pl.MAX_WORKERS_INVALID),
            (dict(max_workers=17), pl.MAX_WORKERS_INVALID),
            (dict(max_workers=True), pl.MAX_WORKERS_INVALID),
            (dict(provider_limits={"fake": 1}), pl.PROVIDER_LIMITS_MALFORMED),
            (dict(provider_limits=(("fake", 0),)), pl.PROVIDER_LIMITS_MALFORMED),
            (dict(provider_limits=(("fake", 1), ("fake", 2))), pl.PROVIDER_LIMIT_DUPLICATE),
        )
        with mock.patch.object(bp, "compile_blueprint", side_effect=AssertionError("must not compile")) as spy:
            self.assertRefused(pl.plan_dag(None), pl.REQUEST_NOT_TYPED)
            self.assertRefused(pl.plan_dag(blueprint), pl.REQUEST_NOT_TYPED)
            for kw, reason in cases:
                self.assertRefused(self.plan(blueprint, **kw), reason)
        spy.assert_not_called()

    def test_cycles_and_unknown_dependencies_are_refused_by_the_native_compiler(self):
        cases = (
            ([self.node("a", depends_on=("b",)), self.node("b", depends_on=("a",))], "DEPENDENCY_CYCLE"),
            ([self.node("a"), self.node("b", depends_on=("zz",))], "UNKNOWN_DEPENDENCY"),
            ([self.node("a", depends_on=("a",)), self.node("b")], "SELF_DEPENDENCY"),
            ([self.node("a"), self.node("a", "b")], "DUPLICATE_WORKER_ID"),
            ([self.node("a", provider="nobody"), self.node("b")], "UNKNOWN_PROVIDER"),
        )
        for nodes, code in cases:
            with mock.patch.object(bp, "compile_blueprint", wraps=bp.compile_blueprint) as spy:
                plan = self.plan(self.blueprint(nodes), states=())
            self.assertRefused(plan, pl.BLUEPRINT_REFUSED)
            self.assertIn(code, plan.blueprint_error_codes)
            spy.assert_called_once()
        code = _module_code()
        for word in ("_find_cycle", "_has_cycle", "parse_manifest", "UNKNOWN_DEPENDENCY", "DEPENDENCY_CYCLE"):
            self.assertNotIn(word, code, word)

    def test_adapter_level_refusals_surface_native_codes_only(self):
        mutable = bp.DagBlueprint(pipeline_id="p", nodes=(self.node("a"), dataclasses.replace(
            self.node("b"), depends_on=["a"])))
        plan = self.plan(mutable, states=(), conflicts=None)
        self.assertRefused(plan, pl.BLUEPRINT_REFUSED)
        self.assertEqual(plan.blueprint_error_codes, ("BLUEPRINT_NOT_IMMUTABLE",))
        plan = self.plan(self.blueprint([self.node("a")]), states=(), conflicts=None)
        self.assertEqual(plan.blueprint_error_codes, ("BLUEPRINT_TOO_FEW_NODES",))
        self.assertNotIn(str(self.root), pl.canonical_json(plan))
        plan = self.run_plan(pl.DagPlanRequest(blueprint={"pipeline_id": "p"}, as_of_utc=AS_OF))
        self.assertEqual(plan.blueprint_error_codes, ("BLUEPRINT_INVALID_TYPE",))

    def test_an_unexpected_compiler_failure_fails_closed(self):
        blueprint = self.blueprint([self.node("a"), self.node("b")])
        with mock.patch.object(bp, "compile_blueprint", side_effect=RuntimeError("boom")):
            plan = self.plan(blueprint)
        self.assertRefused(plan, pl.BLUEPRINT_UNEVALUABLE)
        self.assertEqual(plan.blueprint_error_codes, ())

    def test_compilation_identity_is_verified(self):
        blueprint = self.blueprint([self.node("a"), self.node("b")])
        other = bp.compile_blueprint(self.blueprint([self.node("a"), self.node("c")]), self_worktree=self.stable,
                                     registered_providers=KNOWN)
        with mock.patch.object(bp, "compile_blueprint", return_value=other):
            self.assertRefused(self.plan(blueprint), pl.BLUEPRINT_IDENTITY_MISMATCH)
        own = bp.compile_blueprint(blueprint, self_worktree=self.stable, registered_providers=KNOWN)
        tampered = dataclasses.replace(own, plan=dataclasses.replace(own.plan, fingerprint="0" * 64))
        with mock.patch.object(bp, "compile_blueprint", return_value=tampered):
            self.assertRefused(self.plan(blueprint), pl.BLUEPRINT_IDENTITY_MISMATCH)

    def test_states_for_undeclared_nodes_are_refused(self):
        blueprint = self.blueprint([self.node("a"), self.node("b")])
        plan = self.plan(blueprint, states=(("a", "QUEUED"), ("b", "QUEUED"), ("ghost", "SUCCESS")))
        self.assertRefused(plan, pl.NODE_STATE_UNKNOWN_NODE)

    def test_conflict_request_must_describe_exactly_this_dag(self):
        blueprint = self.blueprint([self.node("a"), self.node("b", mode="write")])
        good = self.conflicts(blueprint)
        self.assertRefused(self.plan(blueprint, conflicts=self.conflicts(blueprint, dag_id="other")),
                           pl.CONFLICT_DAG_MISMATCH)
        self.assertRefused(self.plan(blueprint, conflicts=dataclasses.replace(good, workers=good.workers[:1])),
                           pl.CONFLICT_WORKERS_MISMATCH)
        self.assertRefused(self.plan(blueprint, conflicts=dataclasses.replace(
            good, workers=good.workers + (good.workers[0],))), pl.CONFLICT_WORKERS_MISMATCH)
        self.assertRefused(self.plan(blueprint, conflicts=dataclasses.replace(
            good, workers=(good.workers[0], dataclasses.replace(good.workers[1], worker_id=7)))),
            pl.CONFLICT_WORKERS_MISMATCH)
        self.assertRefused(self.plan(blueprint, conflicts=dataclasses.replace(
            good, workers=(good.workers[0], dataclasses.replace(good.workers[1], mode="read-only")))),
            pl.CONFLICT_MODE_MISMATCH)
        self.assertRefused(self.plan(blueprint, conflicts=self.conflicts(
            blueprint, worktrees={"a": str(self.repos["c"])})), pl.CONFLICT_WORKTREE_MISMATCH)
        self.assertRefused(self.plan(blueprint, conflicts=self.conflicts(blueprint, roots=())),
                           pl.CONFLICT_REQUEST_REFUSED)

    def test_an_alias_spelling_of_the_native_worktree_is_the_same_worktree(self):
        blueprint = self.blueprint([self.node("a"), self.node("b")])
        alias = str(self.repos["a"]) + os.sep
        plan = self.plan(blueprint, conflicts=self.conflicts(blueprint, worktrees={"a": alias}))
        self.assertEqual(plan.admitted, ("a", "b"))


# ---------------------------------------------------------------------------
# Output invariants and authority
# ---------------------------------------------------------------------------
class OutputTests(PlanTestBase):
    def test_zero_authority_and_no_derived_permissions(self):
        blueprint = self.blueprint([
            self.node("a", mode="write", allow_shell=True, required_capabilities=("SHELL",),
                      authorize_path=(str(self.repos["a"]),), checkpoint_policy="ON_SUCCESS"),
            self.node("b"),
        ])
        plan = self.plan(blueprint)
        self.assertEqual(plan.admitted, ("a", "b"))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(plan, flag), False)
            with self.assertRaises(AttributeError):
                setattr(plan, flag, True)
        payload = json.loads(pl.canonical_json(plan))
        for flag in ALL_FLAGS:
            self.assertIs(payload[flag], False)
        self.assertEqual(payload["marker"], pl.PLAN_MARKER)
        self.assertEqual(payload["execution_time_guards_not_evaluated"], list(pl.EXECUTION_TIME_GUARDS_NOT_EVALUATED))
        text = pl.canonical_json(plan)
        for word in ("SHELL", "allow_shell", "authorize_path", "capabilit", "ON_SUCCESS", str(self.root),
                     self.root.as_posix(), "Work Order"):
            self.assertNotIn(word, text, word)
        self.assertEqual(set(payload["decisions"][0]),
                         {"node_id", "state", "provider", "mode", "priority", "decision", "reasons", "slot"})

    def test_hand_made_plans_and_decisions_cannot_overclaim(self):
        plan = self.plan(self.blueprint([self.node("a"), self.node("b"), self.node("c")], max_workers=2))
        waiting = plan.decision_of("c")
        with self.assertRaises(ValueError):
            dataclasses.replace(waiting, decision=pl.ADMISSIBLE)
        with self.assertRaises(ValueError):
            dataclasses.replace(waiting, reasons=(), decision=pl.ADMISSIBLE, slot=None)
        promoted = dataclasses.replace(waiting, reasons=(), decision=pl.ADMISSIBLE, slot=2)
        with self.assertRaises(ValueError):  # exceeds effective_max_workers
            dataclasses.replace(plan, decisions=plan.decisions[:2] + (promoted,))
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, window_status=sw.WAIT_UNTIL)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, outcome=pl.IDLE)
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, effective_provider_limits=(("fake", 1),))
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, planning_order=("a", "b"))
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, request_reasons=(pl.WINDOW_INVALID,))
        with self.assertRaises(ValueError):
            dataclasses.replace(waiting, state="RUNNING")
        with self.assertRaises(ValueError):
            dataclasses.replace(waiting, provider="Not A Provider")

    def test_canonical_json_is_exact_type_and_bounded(self):
        plan = self.plan(self.blueprint([self.node("a"), self.node("b")]))

        class Sub(pl.DagPlan):
            def to_dict(self):
                return {"execution_allowed": True}

        with self.assertRaises(TypeError):
            pl.canonical_json(Sub(**{f.name: getattr(plan, f.name) for f in dataclasses.fields(plan)}))
        with self.assertRaises(TypeError):
            pl.canonical_json(plan.to_dict())
        text = pl.canonical_json(plan)
        self.assertTrue(text.isascii())
        self.assertLessEqual(len(text), pl.MAX_CANONICAL_JSON_BYTES)
        self.assertEqual(json.loads(text)["counts"], {pl.ADMISSIBLE: 2, pl.WAITING: 0, pl.REFUSED: 0,
                                                      pl.UNKNOWN: 0, pl.INACTIVE: 0})


# ---------------------------------------------------------------------------
# Determinism, no mutation, no execution I/O
# ---------------------------------------------------------------------------
class DeterminismAndPurityTests(PlanTestBase):
    def test_deterministic_and_fingerprint_tracks_every_input(self):
        blueprint = self.branching(max_workers=3)
        first, second = self.plan(blueprint), self.plan(blueprint)
        self.assertEqual(pl.canonical_json(first), pl.canonical_json(second))
        self.assertEqual(first, second)
        variants = (
            self.plan(blueprint, states=self.states(blueprint, a="RUNNING")),
            self.plan(blueprint, as_of="2026-10-30T12:00:01Z"),
            self.plan(blueprint, max_workers=1),
            self.plan(blueprint, conflicts=None),
            self.plan(self.branching(max_workers=2)),
        )
        prints = {first.request_fingerprint} | {v.request_fingerprint for v in variants}
        self.assertEqual(len(prints), 1 + len(variants))
        same_instant = self.plan(blueprint, as_of="2026-10-30T14:00:00+02:00")
        self.assertEqual(same_instant.request_fingerprint, first.request_fingerprint)

    def test_preview_never_mutates_its_inputs(self):
        blueprint = self.branching(max_workers=2)
        request = self.request(blueprint, states=self.states(blueprint, a="SUCCESS"))
        before = copy.deepcopy(request)
        self.run_plan(request)
        self.assertEqual(request, before)
        self.assertEqual(request.blueprint, before.blueprint)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.max_workers = 16
        plan = self.run_plan(request)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.outcome = pl.ADMISSIBLE

    def test_no_execution_io_beyond_the_compilers_read_only_inspection(self):
        blueprint = self.blueprint([self.node("a", mode="write"), self.node("b", depends_on=("a",))])
        request = self.request(blueprint)
        before = _tree_snapshot(self.root)
        real_popen = subprocess.Popen
        commands = []

        def recording_popen(cmd, *args, **kwargs):  # every process spawn, `subprocess.run` included
            commands.append(list(cmd))
            return real_popen(cmd, *args, **kwargs)

        real_open = builtins.open

        def read_only_open(file, mode="r", *args, **kwargs):
            if any(ch in mode for ch in "wax+"):
                raise AssertionError(f"write open: {file}")
            return real_open(file, mode, *args, **kwargs)

        boom = AssertionError("execution entry point")
        with mock.patch.object(subprocess, "Popen", side_effect=recording_popen), \
                mock.patch.object(builtins, "open", side_effect=read_only_open), \
                mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom), \
                mock.patch.object(rp.DirLease, "try_acquire", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(os, "replace", side_effect=boom), \
                mock.patch.object(os, "mkdir", side_effect=boom):
            plan = self.run_plan(request)
        self.assertEqual(plan.admitted, ("a",))
        self.assertTrue(commands)
        for cmd in commands:
            self.assertFalse(set(cmd) & MUTATING_GIT_SUBCOMMANDS, cmd)
            self.assertIn("rev-parse", cmd)
        self.assertEqual(_tree_snapshot(self.root), before)

    def test_planning_after_compilation_is_pure(self):
        blueprint = self.branching(max_workers=4)
        compiled = bp.compile_blueprint(blueprint, self_worktree=self.stable, registered_providers=KNOWN)
        request = self.request(blueprint, states=self.states(blueprint, a="SUCCESS"))
        boom = AssertionError("I/O")
        with mock.patch.object(bp, "compile_blueprint", return_value=compiled), \
                mock.patch.object(subprocess, "run", side_effect=boom), \
                mock.patch.object(builtins, "open", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(os, "stat", side_effect=boom):
            plan = self.run_plan(request)
        self.assertEqual(plan.admitted, ("b", "c"))

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
                if node.module is None:
                    imported |= {a.name for a in node.names}
        own = ("fabric_dag_blueprint", "fabric_scheduler_conflicts", "fabric_scheduler_contract",
               "fabric_scheduler_window", "runner_pipeline")
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "re", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "DirLease", "lease_dir", "flog", "ledger", "_launch", "_start_ready", ".now(", "utcnow",
                     "sleep", "while ", "global ", "claude", "codex", "eval(", "exec(", "importlib", "random",
                     "fallback"):
            self.assertNotIn(word, code, word)

    def test_no_mutable_module_state_changes(self):
        snapshot = {k: copy.deepcopy(v) for k, v in vars(pl).items()
                    if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
        self.plan(self.branching())
        pl.plan_dag(None)
        self.assertEqual({k: v for k, v in vars(pl).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_upper_snake(self):
        for vocab in (pl.DECISIONS, pl.OUTCOMES, pl.REQUEST_REASONS, pl.NODE_REASONS, pl.NODE_STATES):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(pl.REQUEST_REASONS) & set(pl.NODE_REASONS))
        groups = (pl.INACTIVE_REASONS, pl.REFUSING_REASONS, pl.UNKNOWN_REASONS, pl.WAITING_REASONS)
        self.assertEqual(sum(len(g) for g in groups), len(pl.NODE_REASONS))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


# ---------------------------------------------------------------------------
# Runner policy pins
# ---------------------------------------------------------------------------
class RunnerPolicyPinTests(unittest.TestCase):
    def test_limits_and_state_vocabulary_mirror_the_runner(self):
        self.assertEqual(pl.MAX_WORKERS, rp.MAX_PIPELINE_WORKERS)
        self.assertEqual(pl.DEFAULT_MAX_WORKERS, rp.DEFAULT_MAX_WORKERS)
        self.assertEqual(pl.MAX_NODES, bp.MAX_BLUEPRINT_NODES)
        self.assertEqual(set(pl.NODE_STATES), {s.value for s in rp.WorkerState} | {pl.STATE_UNKNOWN})
        self.assertEqual(pl._PENDING_STATES, {s.value for s in rp._PENDING_STATES})
        self.assertEqual(pl._TERMINAL_STATES, {s.value for s in rp.TERMINAL_STATES})
        self.assertEqual(sc.MODES, (rp.providers.MODE_READ_ONLY, rp.providers.MODE_WRITE))
        self.assertTrue(set(bp.EXECUTION_TIME_GUARDS_NOT_EVALUATED) < set(pl.EXECUTION_TIME_GUARDS_NOT_EVALUATED))

    def test_planning_order_key_matches_runner_start_ready(self):
        source = ast.unparse(ast.parse(Path(rp.__file__).read_text(encoding="utf-8")))
        self.assertIn("key=lambda r: (-r.spec.priority, r.order)", source)
        plan_source = ast.unparse(ast.parse(MODULE_PATH.read_text(encoding="utf-8")))
        self.assertIn("key=lambda i: (-nodes[i].priority, i)", plan_source)

    def test_provider_holding_states_match_runner_provider_start_held(self):
        tree = ast.parse(Path(rp.__file__).read_text(encoding="utf-8"))
        held = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_provider_start_held")
        referenced = {n.attr for n in ast.walk(held) if isinstance(n, ast.Attribute) and n.attr.isupper()}
        self.assertEqual(referenced, set(pl._PROVIDER_HOLDING_STATES))


if __name__ == "__main__":
    unittest.main()
