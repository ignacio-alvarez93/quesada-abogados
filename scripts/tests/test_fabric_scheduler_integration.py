"""FCP-9E-02: end-to-end integration of the FCP-9 Scheduler & Parallel
Execution phase over the REAL `runner_pipeline.PipelineRunner`.

Every repository/worktree is an ephemeral `git init` under a temporary
directory (the Director DAG suite's `DagTestBase`) and every Work Order is a
temporary file. Workers execute ONLY through the real `PipelineRunner` -
directly, or composed by the real `FabricDirectorService` behind the FCP-9D-01
gateway - with an injected fake executor and a provider registry whose
providers refuse to build any invocation, so no real provider, shell, network
or project worktree is ever touched. The only processes spawned are the
Runner's own read-only `git` calls, which `no_foreign_processes` pins.

Synchronization is a `threading.Barrier` / `threading.Event` with a finite
timeout, released in cleanup, so a regression fails fast instead of hanging.
Quota waits run on an injected fake clock. The FCP-9 modules are consulted
before and after execution and are proven to never dispatch, mutate, certify
or authorize anything. Also pins the single additive FCP-9 CI step. Nothing
here is skipped.
"""

import contextlib
import json
import os
import platform
import re
import subprocess
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_dag_blueprint as bp
from scripts.ai import fabric_director as fd
from scripts.ai import fabric_scheduler_conflicts as cf
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import fabric_scheduler_gateway as gw
from scripts.ai import fabric_scheduler_plan as pl
from scripts.ai import fabric_scheduler_resilience as rs
from scripts.ai import fabric_scheduler_state as st
from scripts.ai import fabric_scheduler_window as sw
from scripts.ai import runner_pipeline as rp
from scripts.tests.test_fabric_director import _git
from scripts.tests.test_fabric_director_dag import KNOWN, DagTestBase, NoInvocationProvider, _resolver, failed, ok

RS = runner.RunState
TEST_PATH = Path(__file__).resolve()
REPO_ROOT = TEST_PATH.parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
CI_STEP_NAME = "FCP-9 scheduler and parallel execution regression without skipped tests"
FCP9_SUITES = (
    "test_fabric_scheduler_contract", "test_fabric_scheduler_window", "test_fabric_scheduler_conflicts",
    "test_fabric_scheduler_plan", "test_fabric_scheduler_capacity", "test_fabric_scheduler_state",
    "test_fabric_scheduler_gateway", "test_fabric_scheduler_cli", "test_fabric_scheduler_resilience",
    "test_fabric_scheduler_integration",
)
# Per-suite floors pinned by the CI step, in FCP9_SUITES order.
FCP9_SUITE_MINIMUMS = (60, 45, 50, 45, 55, 50, 55, 50, 40, 30)
FCP9_TOTAL_MINIMUM = 300
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized")
# Structured, provider-neutral availability fact (never provider prose).
QUOTA_CONDITION = {"condition": "PROVIDER_QUOTA_EXHAUSTED", "reason": "STRUCTURED_TEST_FACT", "http_status": 429}
SYNC_TIMEOUT = 20.0
NO_OVERLAP_WINDOW = 0.25
GIT_NAMES = frozenset({"git", "git.exe"})


def quota() -> runner.WorkOrderResult:
    return runner.WorkOrderResult(state=RS.CLAUDE_ERROR, exit_code=3, run_id="run-quota", evidence_dir=None,
                                  provider_condition=dict(QUOTA_CONDITION))


def now_utc() -> str:
    return sc._utc_text(datetime.now(timezone.utc))


def _tree_snapshot(root: Path) -> dict:
    snapshot = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            stat = path.stat()
            snapshot[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


class FakeClock:
    """Injected Runner clock: every wait advances fake time, never real time."""

    def __init__(self, start=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=max(seconds, 0.001))
        time.sleep(0.001)


class Probe:
    """Thread-safe fake executor recording observable concurrency.

    `outcomes[wid]` is the per-attempt list of results (the last repeats).
    Workers in `rendezvous` meet at one finite-timeout Barrier, so they can
    only succeed if the Runner really ran them at the same time. Every other
    worker holds for `hold` seconds on an Event (set on cleanup), which gives
    a concurrent peer a window in which it would be observed."""

    def __init__(self, outcomes=None, *, rendezvous=(), hold=0.0):
        self.outcomes = outcomes or {}
        self.rendezvous = frozenset(rendezvous)
        self.barrier = threading.Barrier(len(self.rendezvous), timeout=SYNC_TIMEOUT) if self.rendezvous else None
        self.hold = hold
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.requests = []
        self.events = []
        self.active = {}
        self.max_active = 0
        self.provider_peak = {}
        self.overlaps = set()

    def close(self):
        self.release.set()
        if self.barrier is not None:
            self.barrier.abort()

    def attempts(self, wid):
        return [r for r in self.requests if r.worker_id == wid]

    def order(self, kind, wid):
        return self.events.index((kind, wid))

    def started(self):
        return [w for k, w in self.events if k == "start"]

    def __call__(self, request):
        wid = request.worker_id
        with self.lock:
            self.requests.append(request)
            self.events.append(("start", wid))
            for other in self.active:
                self.overlaps.add(frozenset((wid, other)))
            self.active[wid] = (request.repo, request.provider)
            self.max_active = max(self.max_active, len(self.active))
            same = sum(1 for _, p in self.active.values() if p == request.provider)
            self.provider_peak[request.provider] = max(self.provider_peak.get(request.provider, 0), same)
            planned = self.outcomes.get(wid, [ok()])
            outcome = planned[min(len(self.attempts(wid)), len(planned)) - 1]
        try:
            if wid in self.rendezvous:
                self.barrier.wait()
            elif self.hold:
                self.release.wait(self.hold)
            return outcome
        finally:
            with self.lock:
                self.active.pop(wid, None)
                self.events.append(("end", wid))


@contextlib.contextmanager
def no_foreign_processes(test):
    """Every process spawned inside the block must be a non-shell `git`; a
    shell, provider CLI or any other executable fails the test before it
    starts."""
    # The stdlib caches `platform.uname()`; on Windows its first call runs
    # `cmd /c ver`. Prime it outside the guard so the verdict never depends on
    # test order - only processes spawned by the code under test are pinned.
    platform.uname()
    real_popen = subprocess.Popen
    spawned = []

    def guarded(cmd, *args, **kwargs):
        test.assertFalse(kwargs.get("shell"), cmd)
        argv = [cmd] if isinstance(cmd, (str, bytes)) else list(cmd)
        name = Path(str(argv[0])).name.lower()
        test.assertIn(name, GIT_NAMES, argv)
        spawned.append(argv)
        return real_popen(cmd, *args, **kwargs)

    with mock.patch.object(subprocess, "Popen", guarded):
        yield spawned


class IntegrationBase(DagTestBase):
    def setUp(self):
        super().setUp()
        self.provider_map = {p: NoInvocationProvider(p) for p in KNOWN}

    def probe(self, outcomes=None, **kw) -> Probe:
        probe = Probe(outcomes, **kw)
        self.addCleanup(probe.close)
        return probe

    def service(self, executor=None, *, provider_map=None, options=None, **kw):
        return super().service(executor, provider_map=provider_map or self.provider_map, options=options, **kw)

    def write(self, nid, repo=None, **extra):
        return self.node(nid, repo, mode="write", authorize_path=("src",), **extra)

    # -- FCP-9 consultations -------------------------------------------------

    def conflicts(self, blueprint) -> cf.ConflictRequest:
        workers = tuple(cf.WorkerClaims(worker_id=n.id, mode=n.mode, worktree=n.worktree,
                                        worktree_link_state=cf.LINK_NONE) for n in blueprint.nodes)
        return cf.ConflictRequest(dag_id=blueprint.pipeline_id, allowed_roots=(str(self.root),), workers=workers)

    def plan(self, blueprint, states=None, **kw) -> pl.DagPlan:
        states = states or {}
        node_states = tuple((n.id, states.get(n.id, "QUEUED")) for n in blueprint.nodes)
        request = pl.DagPlanRequest(blueprint=blueprint, as_of_utc=now_utc(), node_states=node_states,
                                    conflict_request=self.conflicts(blueprint), **kw)
        return pl.plan_dag(request, self_worktree=self.stable, registered_providers=KNOWN)

    def decisions(self, plan):
        return {d.node_id: (d.decision, d.reasons) for d in plan.decisions}

    def bases(self, handle):
        nodes = {n.id: n for n in handle.plan.nodes}
        return tuple(sorted((wid, _git(Path(nodes[wid].worktree_top), "rev-parse", "HEAD").stdout.strip())
                            for wid in handle.worker_ids))

    def review(self, handle) -> gw.GatewayReview:
        review = gw.preview(handle, gw.ReviewContext(as_of_utc=now_utc(), base_commits=self.bases(handle)))
        self.assertTrue(review.reviewed, review.reasons)
        return review

    def confirmation(self, review, **kw) -> gw.HostConfirmation:
        at = review.as_of_utc
        values = dict(review_fingerprint=review.review_fingerprint,
                      confirmation_token=gw.confirmation_token_for(review, at), confirmed_at_utc=at,
                      base_commits=review.base_commits, host_confirmed=True)
        values.update(kw)
        return gw.HostConfirmation(**values)

    def dispatch(self, blueprint, executor, **svc_kw):
        """submit_blueprint -> gateway preview -> Host confirmation -> gateway
        submit (the ONE `run_blueprint`), with every spawned process pinned."""
        svc = self.service(executor, **svc_kw)
        handle = svc.submit_blueprint(blueprint)
        review = self.review(handle)
        with no_foreign_processes(self) as spawned:
            result = gw.submit(svc, handle, review, self.confirmation(review))
        self.assertEqual(result.outcome, gw.DISPATCHED, result.reasons)
        self.spawned = spawned
        return svc, handle, result

    def observe(self, svc, handle, as_of=None) -> st.StateProjection:
        return st.observe_scheduler_state(svc, handle.pipeline_id, as_of_utc=as_of or now_utc(),
                                          expected_manifest_sha256=handle.manifest_sha256,
                                          expected_plan_fingerprint=handle.plan_fingerprint)

    def worker(self, summary, wid):
        return next(w for w in summary.workers if w.worker_id == wid)

    def assertNoAuthority(self, obj):
        for flag in ALL_FLAGS:
            self.assertIs(getattr(obj, flag), False, (type(obj).__name__, flag))

    # -- direct Runner -------------------------------------------------------

    def runner_manifest(self, workers, pipeline_id="fcp9e02-direct", **extra):
        data = {"pipeline_id": pipeline_id, "workers": workers, **extra}
        return rp.parse_manifest(data, self.root, self_worktree=self.stable, registered_providers=KNOWN)

    def runner_worker(self, wid, repo, **extra):
        data = {"id": wid, "worktree": str(self.repos[repo]), "work_order": str(self.wos[repo])}
        data.update(extra)
        return data

    def pipeline_runner(self, manifest, executor, **kw):
        kw.setdefault("poll_seconds", 0.01)
        kw.setdefault("heartbeat_interval_seconds", None)
        kw.setdefault("self_worktree", self.stable)
        kw.setdefault("lease_root", self.lease_root)
        kw.setdefault("provider_resolver", _resolver(self.provider_map))
        return rp.PipelineRunner(manifest, self.state_root, executor=executor, **kw)

    def worker_json(self, pipeline_id, wid):
        path = self.state_root / pipeline_id / "workers" / wid / "worker.json"
        return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
class ParallelWorktreeTests(IntegrationBase):
    """Independent WOs in separate worktrees overlap; the plan predicted it."""

    def independent(self):
        return self.blueprint([self.write("a"), self.write("b")], max_workers=2)

    def test_plan_admits_two_independent_writers_and_runner_runs_them_concurrently(self):
        blueprint = self.independent()
        plan = self.plan(blueprint)
        self.assertEqual(plan.outcome, pl.ADMISSIBLE)
        self.assertEqual(plan.admitted, ("a", "b"))
        probe = self.probe(rendezvous=("a", "b"))
        svc, handle, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertEqual(probe.max_active, 2)
        self.assertIn(frozenset(("a", "b")), probe.overlaps)
        self.assertFalse(probe.barrier.broken)
        self.assertEqual(svc.status(handle.pipeline_id)["max_observed_concurrency"], 2)

    def test_state_projection_reports_observed_concurrency_and_never_claims_unproven_success(self):
        probe = self.probe(rendezvous=("a", "b"))
        svc, handle, _ = self.dispatch(self.independent(), probe)
        projection = self.observe(svc, handle)
        self.assertEqual(projection.request_reasons, ())
        self.assertEqual(projection.max_observed_concurrency, 2)
        self.assertEqual(projection.pipeline_status, "SUCCESS")
        self.assertEqual([n.native_state for n in projection.nodes], ["SUCCESS", "SUCCESS"])
        # A fake executor leaves no FCP-8 proof of work: never projected as SUCCESS.
        self.assertEqual(projection.outcome, st.UNVERIFIED)
        for node in projection.nodes:
            self.assertEqual(node.status, st.UNVERIFIED)
            self.assertIn(st.FCP8_WORK_UNPROVEN, node.codes)
        self.assertNoAuthority(projection)

    def test_each_worker_targets_only_its_own_worktree(self):
        probe = self.probe(rendezvous=("a", "b"))
        self.dispatch(self.independent(), probe)
        repos = {r.worker_id: Path(r.repo).resolve() for r in probe.requests}
        self.assertEqual(repos, {"a": self.repos["a"], "b": self.repos["b"]})
        self.assertEqual(sorted(len(probe.attempts(w)) for w in "ab"), [1, 1])

    def test_only_read_only_git_processes_are_spawned_during_execution(self):
        probe = self.probe(rendezvous=("a", "b"))
        self.dispatch(self.independent(), probe)
        self.assertTrue(self.spawned)
        for argv in self.spawned:
            self.assertIn(Path(str(argv[0])).name.lower(), GIT_NAMES)
            self.assertNotIn("commit", argv)
            self.assertNotIn("push", argv)

    def test_readers_of_the_same_worktree_may_overlap(self):
        blueprint = self.blueprint([self.node("a"), self.node("b", "a")], max_workers=2)
        self.assertEqual(self.plan(blueprint).admitted, ("a", "b"))
        probe = self.probe(rendezvous=("a", "b"))
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual((result.runner_aggregate_status, probe.max_active), ("SUCCESS", 2))


# ---------------------------------------------------------------------------
class SameWorktreeSerializationTests(IntegrationBase):
    """Writers of one worktree never overlap - in the plan or in the Runner."""

    def test_plan_holds_the_second_writer_of_one_worktree(self):
        blueprint = self.blueprint([self.write("a"), self.write("b", "a")], max_workers=2)
        plan = self.plan(blueprint)
        self.assertEqual(plan.admitted, ("a",))
        self.assertEqual(self.decisions(plan)["b"], (pl.WAITING, (pl.CONFLICT_WITH_ADMITTED,)))
        running = self.plan(blueprint, {"a": "RUNNING"})
        self.assertEqual(self.decisions(running)["b"], (pl.WAITING, (pl.CONFLICT_WITH_RUNNING,)))

    def test_runner_serializes_two_writers_of_the_same_worktree(self):
        blueprint = self.blueprint([self.write("a"), self.write("b", "a")], max_workers=2)
        probe = self.probe(hold=NO_OVERLAP_WINDOW)
        svc, handle, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertEqual((probe.max_active, probe.overlaps), (1, set()))
        first, second = probe.started()
        self.assertLess(probe.order("end", first), probe.order("start", second))
        self.assertEqual(svc.status(handle.pipeline_id)["max_observed_concurrency"], 1)

    def test_reader_waits_for_a_writer_of_the_same_worktree(self):
        blueprint = self.blueprint([self.write("a"), self.node("b", "a")], max_workers=2)
        self.assertEqual(self.decisions(self.plan(blueprint))["b"], (pl.WAITING, (pl.CONFLICT_WITH_ADMITTED,)))
        probe = self.probe(hold=NO_OVERLAP_WINDOW)
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual((result.runner_aggregate_status, probe.overlaps), ("SUCCESS", set()))

    def test_unrelated_worktree_still_runs_beside_the_serialized_pair(self):
        blueprint = self.blueprint([self.write("a"), self.write("b", "a"), self.write("c")], max_workers=3)
        plan = self.plan(blueprint)
        self.assertEqual(plan.admitted, ("a", "c"))
        probe = self.probe(rendezvous=("a", "c"), hold=NO_OVERLAP_WINDOW)
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertIn(frozenset(("a", "c")), probe.overlaps)
        self.assertNotIn(frozenset(("a", "b")), probe.overlaps)


# ---------------------------------------------------------------------------
class ProviderLimitTests(IntegrationBase):
    """provider_limits=1 serializes one provider; =2 lets it overlap."""

    def pair(self, limit):
        return self.blueprint([self.write("a"), self.write("b")], max_workers=2, provider_limits=(("claude", limit),))

    def test_provider_limit_one_is_planned_and_enforced(self):
        blueprint = self.pair(1)
        self.assertEqual(self.decisions(self.plan(blueprint))["b"], (pl.WAITING, (pl.PROVIDER_LIMIT_REACHED,)))
        probe = self.probe(hold=NO_OVERLAP_WINDOW)
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertEqual((probe.provider_peak, probe.overlaps), ({"claude": 1}, set()))

    def test_provider_limit_two_is_planned_and_overlaps(self):
        blueprint = self.pair(2)
        self.assertEqual(self.plan(blueprint).admitted, ("a", "b"))
        probe = self.probe(rendezvous=("a", "b"))
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertEqual(probe.provider_peak, {"claude": 2})

    def test_provider_limit_never_holds_another_provider(self):
        blueprint = self.blueprint([self.write("a"), self.write("b"), self.write("c", provider="codex")],
                                   max_workers=3, provider_limits=(("claude", 1),))
        plan = self.plan(blueprint)
        self.assertEqual(plan.admitted, ("a", "c"))
        probe = self.probe(rendezvous=("a", "c"), hold=NO_OVERLAP_WINDOW)
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertIn(frozenset(("a", "c")), probe.overlaps)
        self.assertEqual(probe.provider_peak["claude"], 1)

    def test_request_limits_only_narrow_the_manifest_limits(self):
        blueprint = self.pair(2)
        narrowed = self.plan(blueprint, provider_limits=(("claude", 1),), max_workers=1)
        self.assertEqual((narrowed.effective_max_workers, narrowed.effective_provider_limits),
                         (1, (("claude", 1),)))
        widened = self.plan(blueprint, provider_limits=(("claude", 5),), max_workers=8)
        self.assertEqual((widened.effective_max_workers, widened.effective_provider_limits),
                         (2, (("claude", 2),)))

    def test_max_workers_one_serializes_independent_worktrees(self):
        blueprint = self.blueprint([self.write("a"), self.write("b", provider="codex")], max_workers=1)
        self.assertEqual(self.decisions(self.plan(blueprint))["b"], (pl.WAITING, (pl.WORKER_LIMIT_REACHED,)))
        probe = self.probe(hold=NO_OVERLAP_WINDOW)
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual((result.runner_aggregate_status, probe.max_active), ("SUCCESS", 1))


# ---------------------------------------------------------------------------
class DependencyAndPriorityTests(IntegrationBase):
    def test_dependency_runs_after_its_upstream_and_plan_agrees(self):
        blueprint = self.blueprint([self.write("a"), self.write("b", depends_on=("a",)), self.write("c")],
                                   max_workers=3)
        plan = self.plan(blueprint)
        self.assertEqual(plan.admitted, ("a", "c"))
        self.assertEqual(self.decisions(plan)["b"], (pl.WAITING, (pl.DEPENDENCY_PENDING,)))
        after = self.plan(blueprint, {"a": "SUCCESS", "c": "SUCCESS"})
        self.assertEqual(after.admitted, ("b",))
        probe = self.probe(rendezvous=("a", "c"))
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertLess(probe.order("end", "a"), probe.order("start", "b"))
        self.assertIn(frozenset(("a", "c")), probe.overlaps)

    def test_failed_upstream_cancels_dependent_and_is_never_replayed(self):
        blueprint = self.blueprint([self.node("a"), self.node("b", depends_on=("a",))])
        probe = self.probe({"a": [failed(self.make_evidence(), "segfault")]})
        svc, handle, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "FAILED")
        self.assertEqual([r.worker_id for r in probe.requests], ["a"])
        b = self.worker(result.summary, "b")
        self.assertEqual(b.worker_state, "CANCELLED")
        plan = self.plan(blueprint, {"a": "FAILED", "b": "QUEUED"})
        self.assertEqual(self.decisions(plan)["b"], (pl.REFUSED, (pl.DEPENDENCY_UNSATISFIABLE,)))
        self.assertEqual(self.observe(svc, handle).outcome, st.NOT_SUCCESSFUL)
        assessment = rs.observe_resilience(svc, handle.pipeline_id, as_of_utc=now_utc(),
                                           worktree_state=rs.WORKTREE_CLEAN)
        self.assertEqual(assessment.node_of("b").reason, rs.CANCELLED)
        self.assertNoAuthority(assessment)

    def test_runner_dispatches_by_priority_exactly_as_planned(self):
        blueprint = self.blueprint([self.node("a", priority=0), self.node("b", priority=10),
                                    self.node("c", priority=5)], max_workers=1)
        plan = self.plan(blueprint)
        self.assertEqual(plan.planning_order, ("b", "c", "a"))
        self.assertEqual(plan.admitted, ("b",))
        probe = self.probe()
        _, _, result = self.dispatch(blueprint, probe)
        self.assertEqual(result.runner_aggregate_status, "SUCCESS")
        self.assertEqual(probe.started(), list(plan.planning_order))

    def test_equal_priority_keeps_declared_order_in_plan_and_runner(self):
        blueprint = self.blueprint([self.node("c"), self.node("a"), self.node("b")], max_workers=1)
        plan = self.plan(blueprint)
        self.assertEqual(plan.planning_order, ("c", "a", "b"))
        probe = self.probe()
        self.dispatch(blueprint, probe)
        self.assertEqual(probe.started(), ["c", "a", "b"])


# ---------------------------------------------------------------------------
class ProviderQuotaTests(IntegrationBase):
    """A quota hold waits on the SAME provider; nothing is ever switched."""

    def quota_run(self, nodes, outcomes, *, runtime=120, **extra):
        clock = FakeClock()
        probe = self.probe(outcomes)
        options = {"clock": clock, "sleep_fn": clock.sleep, "max_runtime_seconds": runtime}
        svc, handle, result = self.dispatch(self.blueprint(nodes, max_workers=3, **extra), probe, options=options)
        return svc, handle, result, probe, clock

    def test_quota_hold_keeps_the_provider_and_holds_its_other_worker(self):
        # claude:1 makes `c` start only after `a` has recorded its quota hold.
        svc, handle, result, probe, _ = self.quota_run(
            [self.node("a"), self.node("b", provider="codex"), self.node("c")], {"a": [quota()]},
            provider_limits=(("claude", 1),))
        summary = result.summary
        a, b, c = (self.worker(summary, w) for w in "abc")
        self.assertEqual((a.worker_state, a.provider, a.requested_provider), ("WAITING_PROVIDER_QUOTA", "claude", "claude"))
        self.assertEqual((a.provider_condition, a.work_attempts_used, a.availability_attempts),
                         ("PROVIDER_QUOTA_EXHAUSTED", 0, 1))
        self.assertEqual(b.worker_state, "SUCCESS")  # another provider is never held
        self.assertEqual((c.worker_state, c.attempts), ("READY", 0))  # same provider: held, not switched
        self.assertEqual([(r.worker_id, r.provider) for r in probe.requests], [("a", "claude"), ("b", "codex")])
        self.assertEqual(summary.stop_reason, "DEADLINE_REACHED")

    def test_scheduler_reads_the_quota_hold_without_authorizing_a_switch(self):
        svc, handle, result, _, clock = self.quota_run([self.node("a"), self.node("c")], {"a": [quota()]})
        as_of = sc._utc_text(clock.now)
        projection = self.observe(svc, handle, as_of)
        node = projection.node_of("a")
        self.assertEqual((node.status, node.provider_condition), (st.WAITING_PROVIDER_QUOTA, "PROVIDER_QUOTA_EXHAUSTED"))
        self.assertIsNotNone(node.next_eligible_utc)
        assessment = rs.observe_resilience(svc, handle.pipeline_id, as_of_utc=as_of)
        a = assessment.node_of("a")
        self.assertEqual(a.budget_class, rs.BUDGET_PROVIDER_AVAILABILITY)
        self.assertEqual((a.work_attempts_used, a.availability_attempts), (0, 1))
        for obj in (projection, assessment):
            self.assertNoAuthority(obj)
        plan = self.plan(self.blueprint([self.node("a"), self.node("c")]), {"a": "WAITING_PROVIDER_QUOTA"})
        self.assertEqual(self.decisions(plan)["c"], (pl.WAITING, (pl.PROVIDER_HELD,)))
        self.assertEqual(plan.admitted, ())

    def test_declared_fallback_is_never_used_for_a_quota_hold(self):
        clock = FakeClock()
        probe = self.probe({"a": [quota()]})
        manifest = self.runner_manifest([self.runner_worker("a", "a", provider="claude",
                                                            fallback_providers=["codex"])])
        with no_foreign_processes(self):
            result = self.pipeline_runner(manifest, probe, clock=clock, sleep_fn=clock.sleep,
                                          max_runtime_seconds=120).run()
        worker = self.worker_json("fcp9e02-direct", "a")
        self.assertEqual(worker["state"], "WAITING_PROVIDER_QUOTA")
        self.assertEqual((worker["active_provider"], worker["fallbacks_used"]), ("claude", []))
        self.assertEqual([r.provider for r in probe.requests], ["claude"])
        self.assertEqual(result.summary["waiting_provider_quota"], 1)

    def test_quota_recovery_resumes_on_the_same_provider_without_work_budget(self):
        clock = FakeClock()
        starts = []
        probe = self.probe({"a": [quota(), ok()]})
        manifest = self.runner_manifest([self.runner_worker("a", "a", provider="claude", max_attempts=1)])

        def timed(request):
            starts.append(clock.now)
            return probe(request)

        result = self.pipeline_runner(manifest, timed, clock=clock, sleep_fn=clock.sleep).run()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual([r.provider for r in probe.requests], ["claude", "claude"])
        self.assertGreaterEqual((starts[1] - starts[0]).total_seconds(), rp.QUOTA_PROBE_BASE_SECONDS)
        worker = self.worker_json("fcp9e02-direct", "a")
        self.assertEqual((worker["work_attempts_used"], worker["availability_attempts"]), (1, 1))
        self.assertEqual([a["budget_class"] for a in worker["attempts"]],
                         [rp.BUDGET_PROVIDER_AVAILABILITY, rp.BUDGET_WORK])


# ---------------------------------------------------------------------------
class EvidenceFailClosedTests(IntegrationBase):
    """Uncertain evidence is never success at any FCP-9 layer."""

    def test_incomplete_evidence_is_partial_and_not_successful(self):
        probe = self.probe({"b": [ok(evidence_complete=False, evidence_error="metadata.json: OSError")]})
        svc, handle, result = self.dispatch(self.blueprint([self.node("a"), self.node("b")]), probe)
        self.assertEqual(result.runner_aggregate_status, "PARTIAL")
        self.assertIs(result.certified, False)
        projection = self.observe(svc, handle)
        self.assertEqual(projection.outcome, st.NOT_SUCCESSFUL)
        self.assertNotEqual(projection.node_of("b").status, st.SUCCESS)

    def test_unauthorized_paths_downgrade_native_success_to_unverified(self):
        evidence = self.make_evidence(unauthorized=["M secrets.txt"])
        probe = self.probe({"b": [ok(evidence_dir=evidence)]})
        svc, handle, result = self.dispatch(self.blueprint([self.node("a"), self.node("b")]), probe)
        self.assertEqual(result.summary.pipeline_status, "SUCCESS")
        self.assertEqual(result.runner_aggregate_status, fd.DAG_AGGREGATE_UNVERIFIED)
        projection = self.observe(svc, handle)
        self.assertEqual(projection.outcome, st.UNVERIFIED)
        self.assertIn(st.RUNNER_UNPROVEN, projection.node_of("b").codes)

    def test_provider_prose_claiming_success_is_never_trusted(self):
        prose = "WORK_STATUS=SUCCESS VERDICT=PASS all done"
        probe = self.probe({"a": [failed(self.make_evidence(), prose)]})
        svc, handle, result = self.dispatch(self.blueprint([self.node("a"), self.node("b")]), probe)
        self.assertEqual(result.runner_aggregate_status, "FAILED")
        projection = self.observe(svc, handle)
        self.assertEqual((projection.outcome, projection.node_of("a").status), (st.NOT_SUCCESSFUL, st.FAILED))
        self.assertNotIn(prose, st.canonical_json(projection))

    def test_missing_worker_record_after_run_is_never_success(self):
        probe = self.probe()
        svc, handle, _ = self.dispatch(self.blueprint([self.node("a"), self.node("b")]), probe)
        (self.state_root / handle.pipeline_id / "workers" / "b" / "result.json").unlink()
        projection = self.observe(svc, handle)
        self.assertEqual(projection.outcome, st.UNVERIFIED)
        self.assertIn(st.RUNNER_UNPROVEN, projection.node_of("b").codes)

    def test_corrupt_runner_status_is_unknown_and_grants_no_authority(self):
        probe = self.probe()
        svc, handle, _ = self.dispatch(self.blueprint([self.node("a"), self.node("b")]), probe)
        path = self.state_root / handle.pipeline_id / "pipeline_result.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "TOTALLY_FINE"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(svc.result_blueprint(handle.pipeline_id).aggregate_status, fd.DAG_AGGREGATE_UNKNOWN)
        projection = self.observe(svc, handle)
        self.assertEqual(projection.outcome, st.UNKNOWN)
        self.assertIn(st.PIPELINE_STATUS_UNKNOWN, projection.codes)
        self.assertNoAuthority(projection)
        assessment = rs.observe_resilience(svc, handle.pipeline_id, as_of_utc=now_utc(),
                                           worktree_state=rs.WORKTREE_CLEAN)
        self.assertNoAuthority(assessment)

    def test_unobservable_run_is_rejected_not_guessed(self):
        svc = self.service(self.probe())
        missing = "fdb-20261030t120000000000-00000000"
        self.assertEqual(st.observe_scheduler_state(svc, missing, as_of_utc=now_utc()).outcome, st.UNOBSERVABLE)
        self.assertEqual(rs.observe_resilience(svc, missing, as_of_utc=now_utc()).outcome, rs.UNOBSERVABLE)
        self.assertEqual(st.observe_scheduler_state(svc, "../escape", as_of_utc=now_utc()).outcome, st.REFUSED)


# ---------------------------------------------------------------------------
class GatewayAuthorityTests(IntegrationBase):
    """Preview and planning never mutate; only a confirmed submit runs."""

    def submitted(self, probe):
        svc = self.service(probe)
        handle = svc.submit_blueprint(self.blueprint([self.write("a"), self.write("b")], max_workers=2))
        return svc, handle

    def test_preview_and_planning_mutate_nothing_and_run_nothing(self):
        probe = self.probe()
        svc, handle = self.submitted(probe)
        blueprint = self.blueprint([self.write("a"), self.write("b")], max_workers=2)
        before = _tree_snapshot(self.root)
        with mock.patch.object(rp.PipelineRunner, "run", side_effect=AssertionError("ran")), \
                mock.patch.object(fd.FabricDirectorService, "run_blueprint", side_effect=AssertionError("ran")):
            review = self.review(handle)
            plan = self.plan(blueprint)
            capacity_window = sw.evaluate_window(blueprint, as_of=now_utc())
        self.assertEqual(_tree_snapshot(self.root), before)
        self.assertEqual(probe.requests, [])
        self.assertFalse((self.state_root / handle.pipeline_id).exists())
        self.assertEqual(capacity_window.status, sw.READY)
        for obj in (review, plan, capacity_window):
            self.assertNoAuthority(obj)
        self.assertIs(review.direction_approval, False)
        self.assertIs(review.human_approval, False)

    def test_unconfirmed_submit_never_reaches_the_runner(self):
        probe = self.probe()
        svc, handle = self.submitted(probe)
        review = self.review(handle)
        with mock.patch.object(rp.PipelineRunner, "run", side_effect=AssertionError("ran")) as run:
            result = gw.submit(svc, handle, review, self.confirmation(review, host_confirmed=False))
        self.assertEqual((result.outcome, result.dispatch_attempted), (gw.REFUSED, False))
        self.assertIn(gw.HOST_CONFIRMATION_NOT_EXPLICIT, result.reasons)
        run.assert_not_called()
        self.assertEqual(probe.requests, [])
        self.assertFalse((self.state_root / handle.pipeline_id).exists())

    def test_base_moved_after_review_is_refused_before_dispatch(self):
        probe = self.probe()
        svc, handle = self.submitted(probe)
        review = self.review(handle)
        (self.repos["a"] / "later.txt").write_text("later\n", encoding="utf-8")
        _git(self.repos["a"], "add", "later.txt")
        _git(self.repos["a"], "commit", "-q", "-m", "later")
        result = gw.submit(svc, handle, review, self.confirmation(review, base_commits=self.bases(handle)))
        self.assertEqual(result.outcome, gw.REFUSED)
        self.assertIn(gw.BASE_CHANGED, result.reasons)
        self.assertEqual(probe.requests, [])

    def test_second_submit_is_refused_by_the_director_and_never_retried(self):
        probe = self.probe()
        svc, handle = self.submitted(probe)
        review = self.review(handle)
        confirmation = self.confirmation(review)
        self.assertEqual(gw.submit(svc, handle, review, confirmation).outcome, gw.DISPATCHED)
        started = len(probe.requests)
        again = gw.submit(svc, handle, review, confirmation)
        self.assertEqual((again.outcome, again.director_error_code), (gw.DIRECTOR_REFUSED, "DAG_ALREADY_EXECUTED"))
        self.assertEqual(len(probe.requests), started)

    def test_consultations_are_deterministic(self):
        probe = self.probe()
        blueprint = self.blueprint([self.write("a"), self.write("b", "a"), self.node("c")], max_workers=2)
        as_of = now_utc()
        request = pl.DagPlanRequest(blueprint=blueprint, as_of_utc=as_of,
                                    node_states=tuple((n.id, "QUEUED") for n in blueprint.nodes),
                                    conflict_request=self.conflicts(blueprint))
        plans = [pl.plan_dag(request, self_worktree=self.stable, registered_providers=KNOWN) for _ in range(2)]
        self.assertEqual(pl.canonical_json(plans[0]), pl.canonical_json(plans[1]))
        svc, handle, _ = self.dispatch(blueprint, probe)
        context = gw.ReviewContext(as_of_utc=as_of, base_commits=self.bases(handle))
        self.assertEqual(gw.canonical_json(gw.preview(handle, context)), gw.canonical_json(gw.preview(handle, context)))
        later = now_utc()
        self.assertEqual(st.canonical_json(self.observe(svc, handle, later)),
                         st.canonical_json(self.observe(svc, handle, later)))
        first = rs.observe_resilience(svc, handle.pipeline_id, as_of_utc=later)
        second = rs.observe_resilience(svc, handle.pipeline_id, as_of_utc=later)
        self.assertEqual(rs.canonical_json(first), rs.canonical_json(second))

    def test_readers_never_write_runner_or_director_state(self):
        probe = self.probe()
        svc, handle, _ = self.dispatch(self.blueprint([self.node("a"), self.node("b")]), probe)
        before = _tree_snapshot(self.root)
        with mock.patch.object(fd.FabricDirectorService, "run_blueprint", side_effect=AssertionError("ran")), \
                mock.patch.object(fd.FabricDirectorService, "recover", side_effect=AssertionError("recover")):
            self.observe(svc, handle)
            rs.observe_resilience(svc, handle.pipeline_id, as_of_utc=now_utc())
        self.assertEqual(_tree_snapshot(self.root), before)
        self.assertEqual(len(probe.requests), 2)


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

    def test_single_step_sits_after_environment_and_before_fcp7(self):
        steps, _ = self._job_steps("fabric-regression")
        self.assertEqual(self.text.count(CI_STEP_NAME), 1)
        idx = steps.index(CI_STEP_NAME)
        self.assertEqual(steps[idx - 1], 'FCP-6C-01..04 nightshift composed regression without skipped tests')
        self.assertEqual(steps[idx + 1],
                         'Director and CLI regression')
        fcp8 = steps.index("FCP-8 validation and evidence engine regression without skipped tests")
        self.assertEqual(steps[fcp8 + 1], "FCP-6B-01 recovery advisory read-only regression without skipped tests")
        self.assertEqual(steps[-2:], ["Runner Queue Multiworker regression",
                                      "FCP-5B-01 Director DAG gateway regression without skipped tests"])

    def test_step_runs_exactly_the_ten_fcp9_suites_with_strict_gates(self):
        start = self.lines.index(f"      - name: {CI_STEP_NAME}")
        self.assertEqual(self.lines[start + 1], "        run: |")
        self.assertEqual(self.lines[start + 3], "")
        step = self.lines[start + 2]
        self.assertEqual(re.findall(r"scripts\.tests\.(\w+)", step), list(FCP9_SUITES))
        self.assertIn("m=" + repr(FCP9_SUITE_MINIMUMS).replace(" ", ""), step)
        for gate in ("r.wasSuccessful()", "r.testsRun == sum(c)", f"sum(c) >= {FCP9_TOTAL_MINIMUM}",
                     "len(c) == len(m)", "all(x >= y for x, y in zip(c, m))", "not r.skipped",
                     "not r.expected" + "Failures", "not r.unexpectedSuccesses"):
            self.assertIn(gate, step)
        for suite in FCP9_SUITES:
            self.assertEqual(self.text.count(suite), 1, suite)

    def test_gated_suites_meet_the_declared_minimums(self):
        counts = [unittest.defaultTestLoader.loadTestsFromName(f"scripts.tests.{n}").countTestCases()
                  for n in FCP9_SUITES]
        self.assertGreaterEqual(sum(counts), FCP9_TOTAL_MINIMUM)
        for suite, count, minimum in zip(FCP9_SUITES, counts, FCP9_SUITE_MINIMUMS):
            self.assertGreaterEqual(count, minimum, suite)

    def test_prior_stage_gates_are_preserved(self):
        for gate in ("min(c) >= 45", "r.testsRun >= 45 and not r.skipped", "r.testsRun >= 35 and not r.skipped",
                     "r.testsRun >= 30 and not r.skipped", "r.testsRun >= 122 and not r.skipped",
                     "sum(c) >= 200 and min(c) >= 25",
                     "loadTestsFromName('scripts.tests.test_fabric_dag_blueprint')",
                     "loadTestsFromName('scripts.tests.test_fabric_director_dag')"):
            self.assertIn(gate, self.text)


if __name__ == "__main__":
    unittest.main()
