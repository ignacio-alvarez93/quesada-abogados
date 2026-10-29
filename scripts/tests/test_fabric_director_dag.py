"""FCP-5B-01: Director DAG multi-Work-Order gateway over the EXISTING Runner.

Every repository/worktree here is an ephemeral `git init` under a temporary
directory (feature branches unless a test needs a protected one) and every
Work Order is a temporary file. Workers execute ONLY through the real
`runner_pipeline.PipelineRunner` with an injected fake executor (or, for the
Runner-guard tests, the real `claude_runner.execute_work_order` behind a
provider registry whose provider refuses to build any invocation), so no real
provider, process or project worktree is ever touched. Nothing is skipped.
"""

import ast
import copy
import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_dag_blueprint as bp
from scripts.ai import fabric_director as fd
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_providers as providers
from scripts.tests.test_fabric_director import FakeProvider, UnavailableProvider, _git, _make_repo

RS = runner.RunState
KNOWN = ["claude", "codex"]
RATE_LIMIT = "Claude API rate limit exceeded (429)"

TEST_PATH = Path(__file__).resolve()
REPO_ROOT = TEST_PATH.parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
CI_STEP_NAME = "FCP-5B-01 Director DAG gateway regression without skipped tests"
# FCP-6A-01 amendment: the one additive step since FCP-5B-01, placed earlier in the job.
FCP6A01_CI_STEP_NAME = "FCP-6A-01 failure intelligence read-only regression without skipped tests"
# LF-normalized sha256 of the workflow as merged at 2ccc522 (before FCP-5B-01).
WORKFLOW_2CCC522_SHA256 = "17baf23db9d82e8c1603ab568b12291f03b1f81b4a8d9746c17192d2de8795b4"
# LF-normalized sha256 at 2ccc522 of what FCP-5B-01 must not change: the 5A
# compiler, the Runner, providers, CLI, ledger, FCP-4 retirement and the
# original single-worker suites.
PINNED_SOURCES = {
    "scripts/ai/fabric_dag_blueprint.py": "7964c889412d63e615a80d939b918e1d5681dfb20af91a69a9069a07a614ee2f",
    "scripts/ai/runner_pipeline.py": "760e6bf3f940afd214918d19863ef381f90266a2f7ae8da6ffdec361d00ce8cc",
    "scripts/ai/claude_runner.py": "367f8090060a018075d0225daa5c842af02f53c27c21aa59dd48851651042935",
    "scripts/ai/runner_providers.py": "639976096e6369aa6d93c236dbbbfeb2df38cf045b267b82f560effda4ad207a",
    "scripts/ai/fabric_director_cli.py": "0e992a865669f0a63d29f7b8fb35225878605d54c4971add4d5a581b2d16fc83",
    "scripts/ai/runner_factory_ledger.py": "adf5867005e7c83850e284f35afa3d00d4589954555159a434fb8b077f1c2b33",
    "scripts/ai/runner_worktree_retirement.py": "58ab30c4de9be940e6984c7f07d66d8201a54e9f51ef3dab123958f3d9a40dbe",
    "scripts/tests/test_fabric_director.py": "93f350d24fa4ae392380d39e1fe56cf76fc89902a0a263a1aad4ff2c57f44d58",
    "scripts/tests/test_fabric_director_cli.py": "5a5057c50b13c4fcedde94f94756baef53b08cd97c3e5195de7affa8b00ca797",
    "scripts/tests/test_runner_pipeline.py": "1129beaaf48ec47d00439747556eb0c0b9630bc191371cdee1380cfc182f96e7",
}
# The service's public surface as merged at 2ccc522; FCP-5B-01 only adds to it.
ORIGINAL_PUBLIC_METHODS = frozenset({
    "project_state", "submit", "recover", "validate", "run", "submit_and_run", "status", "result", "evidence",
    "decision", "integration_ledger_root", "assess_integration", "assess_reconciliation",
    "propose_reconciliation_plan", "validate_reconciliation_plan", "inventory_worktrees",
    "assess_worktree_retirement", "factory_state",
})
DAG_METHODS = (
    "submit_blueprint", "_dag_handle", "_load_dag_binding", "run_blueprint", "result_blueprint", "_dag_worker_summary",
)
MUTATING_GIT_SUBCOMMANDS = {
    "add", "am", "branch", "checkout", "cherry-pick", "clean", "commit", "fetch", "gc", "init", "merge", "mv",
    "prune", "pull", "push", "rebase", "reset", "restore", "revert", "rm", "stash", "switch", "tag",
    "update-ref", "worktree",
}


def ok(**extra) -> runner.WorkOrderResult:
    kw = dict(state=RS.SUCCESS, exit_code=0, run_id="run-ok", evidence_dir=None, work_status="SUCCESS")
    kw.update(extra)
    return runner.WorkOrderResult(**kw)


def failed(evidence_dir: Path, error="provider exploded") -> runner.WorkOrderResult:
    # An evidence dir marks that the provider actually ran; without one Runner
    # treats CLAUDE_ERROR as "never ran" (BLOCKED PROVIDER_UNAVAILABLE).
    return runner.WorkOrderResult(state=RS.CLAUDE_ERROR, exit_code=3, run_id="run-err", evidence_dir=evidence_dir,
                                  error_message=error)


class Recorder:
    """Thread-safe fake executor. `outcomes[wid]` is the per-attempt list of
    WorkOrderResult / exception / callable(request); the last one repeats."""

    def __init__(self, outcomes=None, hold_seconds=0.0):
        self.outcomes = outcomes or {}
        self.hold_seconds = hold_seconds
        self.lock = threading.Lock()
        self.requests = []
        self.events = []
        self.active = {}
        self.max_active = 0
        self.same_repo_overlaps = []

    def attempts(self, wid):
        return [r.attempt for r in self.requests if r.worker_id == wid]

    def order(self, kind, wid):
        return self.events.index((kind, wid))

    def __call__(self, request):
        with self.lock:
            self.requests.append(request)
            self.events.append(("start", request.worker_id))
            overlap = [w for w, repo in self.active.items() if repo == request.repo]
            if overlap:
                self.same_repo_overlaps.append((request.worker_id, tuple(overlap)))
            self.active[request.worker_id] = request.repo
            self.max_active = max(self.max_active, len(self.active))
            planned = self.outcomes.get(request.worker_id, [ok()])
            outcome = planned[min(len(self.attempts(request.worker_id)) - 1, len(planned) - 1)]
        try:
            if callable(outcome) and not isinstance(outcome, runner.WorkOrderResult):
                outcome = outcome(request)
            if isinstance(outcome, BaseException):
                raise outcome
            time.sleep(self.hold_seconds)
            return outcome
        finally:
            with self.lock:
                self.active.pop(request.worker_id, None)
                self.events.append(("end", request.worker_id))


class NoInvocationProvider(FakeProvider):
    """Real-registry stand-in for the Runner-guard tests: available, but any
    attempt to actually build a provider invocation fails the test."""

    def build_invocation(self, **kw):
        raise AssertionError("a provider invocation must never be built in these tests")


def _resolver(providers_map):
    def _resolve(pid):
        if pid not in providers_map:
            raise providers.UnknownProviderError(pid, KNOWN)
        return providers_map[pid]
    return _resolve


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class DagTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.stable = _make_repo(self.root, "stable")
        self.repos = {n: _make_repo(self.root, n) for n in ("a", "b", "c", "d")}
        for repo in self.repos.values():
            _git(repo, "checkout", "-q", "-b", "feature/fcp5b01-test")
        self.wos = {}
        for name in ("a", "b", "c", "d"):
            path = self.root / "work_orders" / f"wo_{name}.md"
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"Work Order {name}.\n", encoding="utf-8")
            self.wos[name] = path
        self.state_root = self.root / "state"
        self.director_root = self.root / "director"
        self.factory_root = self.root / "factory"
        self.lease_root = self.root / "leases"

    def service(self, executor=None, *, provider_map=None, options=None, **kw) -> fd.FabricDirectorService:
        provider_map = provider_map if provider_map is not None else {p: FakeProvider(p) for p in KNOWN}
        kw.setdefault("state_root", self.state_root)
        kw.setdefault("director_root", self.director_root)
        kw.setdefault("factory_root", self.factory_root)
        kw.setdefault("self_worktree", self.stable)
        kw.setdefault("registered_providers", KNOWN)
        kw.setdefault("provider_resolver", _resolver(provider_map))
        kw.setdefault("pipeline_runner_options", {
            "poll_seconds": 0.01, "heartbeat_interval_seconds": None, "lease_root": self.lease_root, **(options or {}),
        })
        kw["executor"] = executor if executor is not None else Recorder()
        return fd.FabricDirectorService(**kw)

    def node(self, nid, repo=None, *, depends_on=(), provider="claude", mode="read-only", **extra):
        repo = repo or nid
        return bp.BlueprintNode(
            id=nid, worktree=str(self.repos.get(repo, repo)), work_order=str(self.wos.get(repo, self.wos["a"])),
            provider=provider, mode=mode, depends_on=depends_on, **extra,
        )

    def blueprint(self, nodes, pipeline_id="caller-dag", **extra):
        return bp.DagBlueprint(pipeline_id=pipeline_id, nodes=tuple(nodes), **extra)

    def chain(self):
        return self.blueprint([
            self.node("a"), self.node("b", depends_on=("a",)), self.node("c", depends_on=("b",)),
        ])

    def diamond(self, **extra):
        return self.blueprint([
            self.node("a"), self.node("b", depends_on=("a",)), self.node("c", depends_on=("a",)),
            self.node("d", depends_on=("b", "c")),
        ], **extra)

    def submit_and_run(self, blueprint, executor=None, **svc_kw):
        executor = executor if executor is not None else Recorder()
        svc = self.service(executor, **svc_kw)
        handle = svc.submit_blueprint(blueprint)
        return svc, handle, svc.run_blueprint(handle), executor

    def assertDirectorError(self, code, fn, *args):
        with self.assertRaises(fd.DirectorError) as ctx:
            fn(*args)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception

    def director_entries(self):
        return sorted(p.name for p in self.director_root.iterdir()) if self.director_root.exists() else []

    def worker(self, summary, wid):
        return next(w for w in summary.workers if w.worker_id == wid)

    def make_evidence(self, *, unauthorized=None) -> Path:
        evidence = self.root / f"evidence_{uuid.uuid4().hex[:10]}"
        evidence.mkdir()
        (evidence / "metadata.json").write_text(json.dumps({
            "work_product_present": False, "changed_paths_after_run": list(unauthorized or []),
            "authorized_changed_paths": [], "unauthorized_changed_paths": list(unauthorized or []),
        }), encoding="utf-8")
        (evidence / "result.json").write_text(json.dumps({"evidence_complete": True}), encoding="utf-8")
        return evidence


# ---------------------------------------------------------------------------
class SubmitBlueprintTests(DagTestBase):
    """Submit validates once through FCP-5A, persists a binding, runs nothing."""

    def shapes(self):
        return {
            "independent-2": (self.blueprint([self.node("a"), self.node("b")]), {"a": (), "b": ()}),
            "chain-3": (self.chain(), {"a": (), "b": ("a",), "c": ("b",)}),
            "fan-out-fan-in-4": (self.diamond(), {"a": (), "b": ("a",), "c": ("a",), "d": ("b", "c")}),
        }

    def test_valid_shapes_compile_once_persist_binding_and_execute_nothing(self):
        for label, (blueprint, edges) in self.shapes().items():
            with self.subTest(label):
                executor = Recorder()
                svc = self.service(executor)
                real_compile, real_parse = bp.compile_blueprint, rp.parse_manifest
                with mock.patch.object(bp, "compile_blueprint", wraps=real_compile) as compile_spy, \
                        mock.patch.object(rp, "parse_manifest", wraps=real_parse) as parse_spy, \
                        mock.patch.object(rp.PipelineRunner, "run", side_effect=AssertionError("ran")):
                    handle = svc.submit_blueprint(blueprint)
                self.assertEqual(compile_spy.call_count, 1)
                self.assertEqual(parse_spy.call_count, 1)  # the parser, only inside compile_blueprint
                bound = compile_spy.call_args.args[0]
                self.assertEqual(parse_spy.call_args.args[0], bp.compose_manifest_data(bound))
                self.assertEqual(compile_spy.call_args.kwargs,
                                 {"self_worktree": self.stable, "registered_providers": KNOWN})
                self.assertEqual(executor.requests, [])
                self.assertFalse((self.state_root / handle.pipeline_id).exists())

                self.assertIsInstance(handle, fd.DirectorDagHandle)
                self.assertEqual(handle.worker_ids, tuple(edges))
                manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
                self.assertEqual(manifest["pipeline_id"], handle.pipeline_id)
                self.assertEqual({w["id"]: tuple(w["depends_on"]) for w in manifest["workers"]}, edges)
                self.assertEqual(json.loads(handle.plan.manifest_json), manifest)
                self.assertTrue(bp.verify_plan(handle.plan))
                self.assertEqual(handle.plan.fingerprint, handle.plan_fingerprint)
                self.assertEqual(handle.plan.manifest_sha256, handle.manifest_sha256)
                self.assertEqual(Path(handle.plan_path).read_bytes().decode("utf-8"),
                                 bp.canonical_plan_json(handle.plan))
                self.assertEqual(sorted(p.name for p in Path(handle.director_dir).iterdir()),
                                 [fd.DAG_PLAN_FILENAME, fd.DAG_PROVENANCE_FILENAME, fd.DAG_MANIFEST_FILENAME])

    def test_director_owns_a_fresh_execution_id_and_never_mutates_the_blueprint(self):
        blueprint = self.diamond()
        before = copy.deepcopy(blueprint)
        svc = self.service()
        first, second = svc.submit_blueprint(blueprint), svc.submit_blueprint(blueprint)
        self.assertEqual(blueprint, before)
        self.assertEqual(blueprint.pipeline_id, "caller-dag")
        self.assertNotEqual(first.pipeline_id, second.pipeline_id)
        for handle in (first, second):
            self.assertRegex(handle.pipeline_id, r"^fdb-[0-9a-z-]+$")
            self.assertEqual(handle.director_run_id, handle.pipeline_id)
            self.assertEqual(handle.blueprint_pipeline_id, "caller-dag")
            self.assertEqual(Path(handle.director_dir), self.director_root / handle.pipeline_id)
            self.assertNotIn("caller-dag", handle.director_dir)
            self.assertEqual(handle.state_root, str(self.state_root))
        self.assertNotEqual(first.plan.fingerprint, second.plan.fingerprint)  # bound to different ids

    def test_provenance_is_minimal_and_confers_nothing(self):
        handle = self.service().submit_blueprint(self.chain())
        provenance = json.loads(Path(handle.provenance_path).read_text(encoding="utf-8"))
        self.assertEqual(set(provenance), {
            "schema", "pipeline_id", "blueprint_pipeline_id", "worker_ids", "work_orders", "manifest_sha256",
            "plan_fingerprint", "plan_status", "execution_permit", "submitted_at_utc",
        })
        self.assertEqual(provenance["schema"], fd.DAG_PROVENANCE_SCHEMA)
        self.assertEqual(provenance["worker_ids"], ["a", "b", "c"])
        self.assertIs(provenance["execution_permit"], False)
        self.assertEqual(provenance["plan_status"], bp.STATUS_STRUCTURALLY_VALID)
        for flag in ("executed", "approved", "merged", "integrated", "execution_permit"):
            self.assertIs(getattr(handle.plan, flag), False, flag)
        rendered = json.dumps(provenance).lower()
        for word in ("approved\": true", "token", "signature", "secret"):
            self.assertNotIn(word, rendered)

    def test_work_orders_are_referenced_in_place_never_copied(self):
        handle = self.service().submit_blueprint(self.chain())
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        declared = [str(self.wos[n]) for n in ("a", "b", "c")]
        self.assertEqual([w["work_order"] for w in manifest["workers"]], declared)
        self.assertEqual(json.loads(Path(handle.provenance_path).read_text(encoding="utf-8"))["work_orders"], declared)
        self.assertEqual(list(Path(handle.director_dir).glob("*.md")), [])
        for repo in self.repos.values():
            self.assertEqual(_git(repo, "status", "--porcelain").stdout, "")

    def test_handle_is_a_distinct_frozen_type_without_a_worker_id(self):
        handle = self.service().submit_blueprint(self.chain())
        self.assertNotIsInstance(handle, fd.DirectorRunHandle)
        self.assertNotIn("worker_id", {f.name for f in dataclasses.fields(fd.DirectorDagHandle)})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            handle.manifest_path = "elsewhere"

    def test_invalid_graphs_are_refused_before_anything_is_persisted(self):
        cases = {
            "DEPENDENCY_CYCLE": [self.node("a", depends_on=("b",)), self.node("b", depends_on=("a",))],
            "DUPLICATE_WORKER_ID": [self.node("a"), self.node("a", "b")],
            "UNKNOWN_DEPENDENCY": [self.node("a"), self.node("b", depends_on=("zz",))],
            "SELF_DEPENDENCY": [self.node("a"), self.node("b", depends_on=("b",))],
            "UNKNOWN_PROVIDER": [self.node("a"), self.node("b", provider="ghost")],
            "INVALID_MODE": [self.node("a"), self.node("b", mode="root")],
            "SELF_MODIFICATION_REFUSED": [self.node("a"), self.node("b", str(self.stable), mode="write",
                                                                     authorize_path=("src",))],
            "INVALID_WORKTREE": [self.node("a"), self.node("b", str(self.root / "missing"))],
        }
        executor = Recorder()
        svc = self.service(executor)
        for code, nodes in cases.items():
            with self.subTest(code):
                exc = self.assertDirectorError("MANIFEST_INVALID", svc.submit_blueprint, self.blueprint(nodes))
                self.assertIsInstance(exc.__cause__, rp.ManifestError)
                self.assertIn(code, [e["code"] for e in exc.__cause__.errors])
        adapter = {
            "BLUEPRINT_TOO_FEW_NODES": self.blueprint([self.node("a")]),
            "BLUEPRINT_NOT_IMMUTABLE": self.blueprint([self.node("a"), self.node("b", depends_on=["a"])]),
            "BLUEPRINT_PATH_NOT_ABSOLUTE": self.blueprint([self.node("a"),
                                                           dataclasses.replace(self.node("b"), worktree="b")]),
        }
        for code, blueprint in adapter.items():
            with self.subTest(code):
                exc = self.assertDirectorError("BLUEPRINT_REFUSED", svc.submit_blueprint, blueprint)
                self.assertIsInstance(exc.__cause__, bp.BlueprintError)
                self.assertIn(code, [e["code"] for e in exc.__cause__.errors])
        self.assertEqual(self.director_entries(), [])
        self.assertFalse(self.state_root.exists())
        self.assertEqual(executor.requests, [])

    def test_type_confusion_is_refused_without_compiling(self):
        svc = self.service()
        good = self.chain()
        with mock.patch.object(bp, "compile_blueprint", side_effect=AssertionError("compiled")) as spy:
            for bad in (None, dataclasses.asdict(good), good.nodes, json.dumps(dataclasses.asdict(good)),
                        dataclasses.replace(good, pipeline_id=7)):
                with self.subTest(type(bad).__name__):
                    self.assertDirectorError("BLUEPRINT_REFUSED", svc.submit_blueprint, bad)
        spy.assert_not_called()
        self.assertEqual(self.director_entries(), [])

    def test_omitted_self_worktree_keeps_runners_default_self_guard(self):
        svc = self.service(self_worktree=None)
        blueprint = self.blueprint([self.node("a"), self.node("b", mode="write", authorize_path=("src",))])
        with mock.patch.object(rp, "default_self_worktree", return_value=self.repos["b"]):
            exc = self.assertDirectorError("MANIFEST_INVALID", svc.submit_blueprint, blueprint)
        self.assertIn("SELF_MODIFICATION_REFUSED", [e["code"] for e in exc.__cause__.errors])

    def test_directory_collision_is_refused_and_never_overwrites(self):
        svc = self.service()
        fixed = "fdb-20261028t000000000000-deadbeef"
        with mock.patch.object(svc, "_generate_pipeline_id", return_value=fixed):
            first = svc.submit_blueprint(self.chain())
            snapshot = {p.name: p.read_bytes() for p in Path(first.director_dir).iterdir()}
            self.assertDirectorError("DIRECTOR_RUN_COLLISION", svc.submit_blueprint, self.diamond())
        self.assertEqual({p.name: p.read_bytes() for p in Path(first.director_dir).iterdir()}, snapshot)

    def test_existing_runner_state_for_the_id_is_a_collision(self):
        svc = self.service()
        fixed = "fdb-20261028t000000000000-cafebabe"
        (self.state_root / fixed).mkdir(parents=True)
        with mock.patch.object(svc, "_generate_pipeline_id", return_value=fixed):
            self.assertDirectorError("DIRECTOR_RUN_COLLISION", svc.submit_blueprint, self.chain())
        self.assertEqual(self.director_entries(), [])


# ---------------------------------------------------------------------------
class RunBlueprintExecutionTests(DagTestBase):
    """Execution is PipelineRunner's alone: order, concurrency, retries."""

    def test_executes_through_the_same_single_runner_helper_and_options_as_run(self):
        executor = Recorder()
        svc = self.service(executor, factory_ledger=flog.FactoryLedger(self.factory_root))
        single = svc.submit(fd.DirectorWorkOrderSpec(worktree=str(self.repos["a"]), work_order_text="One.\n"))
        handle = svc.submit_blueprint(self.diamond())
        with mock.patch.object(rp, "PipelineRunner", wraps=rp.PipelineRunner) as runner_spy, \
                mock.patch.object(svc, "_run_manifest", wraps=svc._run_manifest) as helper_spy:
            svc.run(single)
            summary = svc.run_blueprint(handle)
        self.assertEqual(helper_spy.call_count, 2)
        self.assertEqual(runner_spy.call_count, 2)
        (single_args, single_kwargs), (dag_args, dag_kwargs) = runner_spy.call_args_list
        self.assertEqual(single_kwargs, dag_kwargs)
        self.assertIs(dag_kwargs["executor"], executor)
        self.assertIs(dag_kwargs["factory_ledger"], svc.factory_ledger)
        self.assertEqual(dag_kwargs["lease_root"], self.lease_root)
        self.assertEqual(single_args[1], dag_args[1])
        self.assertEqual(dag_args[0].pipeline_id, handle.pipeline_id)
        self.assertEqual(summary.aggregate_status, "SUCCESS")
        events = fd.pipeline.factory_history_report(self.factory_root, pipeline_id=handle.pipeline_id)
        self.assertEqual([e["event_type"] for e in events].count(flog.WORKER_STARTED), 4)

    def test_one_invocation_per_worker_in_dependency_order_with_identity_fidelity(self):
        svc, handle, summary, executor = self.submit_and_run(self.diamond(), Recorder(hold_seconds=0.02))
        self.assertEqual(sorted(r.worker_id for r in executor.requests), ["a", "b", "c", "d"])
        for request in executor.requests:
            self.assertEqual(request.pipeline_id, handle.pipeline_id)
            self.assertEqual(request.attempt, 1)
            self.assertEqual(Path(request.repo), self.repos[request.worker_id])
            self.assertEqual(Path(request.work_order), self.wos[request.worker_id])
            self.assertEqual(request.label, f"{handle.pipeline_id}-{request.worker_id}")
        for dep, wid in (("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")):
            self.assertLess(executor.order("end", dep), executor.order("start", wid), (dep, wid))
        self.assertEqual([w.worker_id for w in summary.workers], ["a", "b", "c", "d"])
        self.assertEqual(self.worker(summary, "d").depends_on, ("b", "c"))
        self.assertEqual(summary.pipeline_status, "SUCCESS")
        self.assertEqual(summary.aggregate_status, "SUCCESS")
        self.assertEqual(summary.aggregate_reasons, ())
        for w in summary.workers:
            self.assertEqual((w.worker_state, w.work_status, w.work_status_source, w.attempts),
                             ("SUCCESS", "SUCCESS", "PROVIDER", 1))
            self.assertEqual((w.worker_record, w.evidence_health, w.runner_proven_success),
                             (fd.WORKER_RECORD_PRESENT, fd.EVIDENCE_HEALTH_COMPLETE, True))

    def test_declared_order_is_kept_and_dependencies_still_govern(self):
        blueprint = self.blueprint([
            self.node("c", depends_on=("b",)), self.node("b", depends_on=("a",)), self.node("a"),
        ])
        _, handle, summary, executor = self.submit_and_run(blueprint)
        self.assertEqual(handle.worker_ids, ("c", "b", "a"))
        self.assertEqual([w.worker_id for w in summary.workers], ["c", "b", "a"])
        self.assertEqual([r.worker_id for r in executor.requests], ["a", "b", "c"])

    def test_independent_worktrees_run_concurrently_under_runner_limits(self):
        barrier = threading.Barrier(2, timeout=20)

        def meet(request):
            barrier.wait()
            return ok()

        blueprint = self.blueprint([
            self.node("a", mode="write", authorize_path=("src",)),
            self.node("b", mode="write", authorize_path=("src",)),
        ], max_workers=2)
        _, _, summary, executor = self.submit_and_run(blueprint, Recorder({"a": [meet], "b": [meet]}))
        self.assertEqual(summary.aggregate_status, "SUCCESS")
        self.assertEqual(executor.max_active, 2)

    def test_max_workers_and_provider_limits_are_the_runners(self):
        nodes = [self.node("a"), self.node("b"), self.node("c")]
        _, handle, summary, executor = self.submit_and_run(self.blueprint(nodes, max_workers=1),
                                                           Recorder(hold_seconds=0.05))
        self.assertEqual(executor.max_active, 1)
        self.assertEqual(self.service().status(handle.pipeline_id)["max_observed_concurrency"], 1)
        limited = self.blueprint([self.node("a"), self.node("b"), self.node("c", provider="codex")],
                                 max_workers=3, provider_limits=(("claude", 1),))
        recorder = Recorder(hold_seconds=0.05)
        _, _, summary, _ = self.submit_and_run(limited, recorder)
        self.assertEqual(summary.aggregate_status, "SUCCESS")
        a_end, b_start = recorder.order("end", "a"), recorder.order("start", "b")
        b_end, a_start = recorder.order("end", "b"), recorder.order("start", "a")
        self.assertTrue(a_end < b_start or b_end < a_start, recorder.events)  # claude limit 1: never overlap

    def test_same_write_worktree_is_serialized_by_runner(self):
        blueprint = self.blueprint([
            self.node("a", mode="write", authorize_path=("src",)),
            self.node("b", "a", mode="write", authorize_path=("docs",)),
        ], max_workers=2)
        _, _, summary, executor = self.submit_and_run(blueprint, Recorder(hold_seconds=0.05))
        self.assertEqual(summary.aggregate_status, "SUCCESS")
        self.assertEqual(executor.same_repo_overlaps, [])
        self.assertEqual(len(executor.requests), 2)

    def test_native_retry_semantics(self):
        blueprint = self.blueprint([self.node("a", max_attempts=2), self.node("b", max_attempts=3)])
        executor = Recorder({
            "a": [failed(self.make_evidence(), RATE_LIMIT), ok()], "b": [failed(self.make_evidence(), "segfault")],
        })
        _, _, summary, _ = self.submit_and_run(blueprint, executor)
        self.assertEqual(executor.attempts("a"), [1, 2])  # transient: retried by Runner
        self.assertEqual(executor.attempts("b"), [1])  # non-transient: never retried
        a, b = self.worker(summary, "a"), self.worker(summary, "b")
        self.assertEqual((a.worker_state, a.attempts, a.work_attempts_used), ("SUCCESS", 2, 2))
        self.assertEqual((b.worker_state, b.state_reason, b.attempts), ("FAILED", "CLAUDE_ERROR", 1))
        self.assertEqual(summary.aggregate_status, "FAILED")
        self.assertIn("b:WORKER_STATE_NOT_SUCCESS", summary.aggregate_reasons)

    def test_intermediate_failure_cancels_dependents_fail_closed(self):
        executor = Recorder({"b": [failed(self.make_evidence(), "segfault")]})
        _, _, summary, _ = self.submit_and_run(self.chain(), executor)
        self.assertEqual(sorted(r.worker_id for r in executor.requests), ["a", "b"])
        states = {w.worker_id: (w.worker_state, w.state_reason) for w in summary.workers}
        self.assertEqual(states["a"], ("SUCCESS", None))
        self.assertEqual(states["b"], ("FAILED", "CLAUDE_ERROR"))
        self.assertEqual(states["c"][0], "CANCELLED")
        self.assertTrue(states["c"][1].startswith("DEPENDENCY_UNSATISFIED"))
        self.assertEqual(summary.pipeline_status, "FAILED")
        self.assertEqual(summary.aggregate_status, "FAILED")
        self.assertTrue(self.worker(summary, "a").runner_proven_success)
        self.assertFalse(self.worker(summary, "c").runner_proven_success)

    def test_partial_blocked_interrupted_and_exception_stay_visible(self):
        cases = {
            "PARTIAL": ({"b": [runner.WorkOrderResult(state=RS.PARTIAL, exit_code=7, run_id="p", evidence_dir=None,
                                                      work_status="PARTIAL")]}, None, "PARTIAL"),
            "BLOCKED": ({}, {"claude": FakeProvider("claude"), "codex": UnavailableProvider("codex")}, "BLOCKED"),
            "INTERRUPTED": ({"b": [runner.WorkOrderResult(state=RS.INTERRUPTED, exit_code=130, run_id="i",
                                                          evidence_dir=None)]}, None, "INTERRUPTED"),
            "EXECUTOR_EXCEPTION": ({"b": [RuntimeError("boom")]}, None, "FAILED"),
        }
        expected_pipeline = {"PARTIAL": "PARTIAL", "BLOCKED": "BLOCKED", "INTERRUPTED": "INCOMPLETE",
                             "EXECUTOR_EXCEPTION": "FAILED"}
        for label, (outcomes, provider_map, b_state) in cases.items():
            with self.subTest(label):
                blueprint = self.blueprint([self.node("a"), self.node("b", provider="codex")])
                executor = Recorder(outcomes)
                kw = {"provider_map": provider_map} if provider_map else {}
                _, _, summary, _ = self.submit_and_run(blueprint, executor, **kw)
                b = self.worker(summary, "b")
                self.assertEqual(b.worker_state, b_state)
                self.assertFalse(b.runner_proven_success)
                self.assertTrue(self.worker(summary, "a").runner_proven_success)
                self.assertEqual(summary.pipeline_status, expected_pipeline[label])
                self.assertEqual(summary.aggregate_status, expected_pipeline[label])
                self.assertNotEqual(summary.aggregate_status, "SUCCESS")
                if label == "BLOCKED":
                    self.assertEqual(executor.attempts("b"), [])  # Runner's preflight, never dispatched
                    self.assertEqual(b.state_reason, "PROVIDER_UNAVAILABLE")
                else:
                    self.assertEqual(executor.attempts("b"), [1])  # no automatic replay

    def test_uncertain_evidence_is_never_success(self):
        executor = Recorder({"b": [ok(evidence_complete=False, evidence_error="metadata.json: OSError")]})
        _, _, summary, _ = self.submit_and_run(self.blueprint([self.node("a"), self.node("b")]), executor)
        b = self.worker(summary, "b")
        self.assertEqual((b.worker_state, b.state_reason), ("PARTIAL", "EVIDENCE_FINALIZATION_FAILED"))
        self.assertEqual((b.evidence_complete, b.evidence_health), (False, fd.EVIDENCE_HEALTH_INCOMPLETE))
        self.assertIn("EVIDENCE_INCOMPLETE", b.unproven_reasons)
        self.assertEqual(summary.aggregate_status, "PARTIAL")

    def test_unauthorized_paths_downgrade_a_native_success(self):
        evidence = self.make_evidence(unauthorized=["M secrets.txt"])
        executor = Recorder({"b": [ok(evidence_dir=evidence)]})
        _, _, summary, _ = self.submit_and_run(self.blueprint([self.node("a"), self.node("b")]), executor)
        self.assertEqual(summary.pipeline_status, "SUCCESS")  # Runner's, verbatim
        self.assertEqual(summary.aggregate_status, fd.DAG_AGGREGATE_UNVERIFIED)
        self.assertEqual(summary.aggregate_reasons, ("b:UNAUTHORIZED_PATHS",))
        self.assertEqual(self.worker(summary, "b").unauthorized_changed_paths, ("M secrets.txt",))

    def test_runner_owned_acceptance_source_is_projected(self):
        executor = Recorder({"b": [ok(work_status="UNVERIFIED")]})
        blueprint = self.blueprint([
            self.node("a"),
            self.node("b", completion_policy="runner_acceptance", acceptance_commands=("python -c pass",)),
        ])
        with mock.patch.object(rp.PipelineRunner, "_apply_acceptance",
                               return_value={"decision": "PASSED", "commands": []}) as acceptance:
            _, _, summary, _ = self.submit_and_run(blueprint, executor)
        acceptance.assert_called_once()
        b = self.worker(summary, "b")
        self.assertEqual((b.work_status, b.provider_work_status, b.work_status_source),
                         ("SUCCESS", "UNVERIFIED", runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE))
        self.assertTrue(b.runner_proven_success)
        self.assertEqual(self.worker(summary, "a").work_status_source, runner.WORK_STATUS_SOURCE_PROVIDER)

    def test_runner_guards_stay_final_authority_at_execution_time(self):
        develop = _make_repo(self.root, "develop_repo")
        _git(develop, "checkout", "-q", "-b", "develop")
        (self.repos["c"] / "junk.txt").write_text("dirty\n", encoding="utf-8")
        blueprint = self.blueprint([
            self.node("a"),
            self.node("b", str(develop), mode="write", authorize_path=("src",)),
            self.node("c", mode="write", authorize_path=("src",)),
        ])

        def dispatch(request):
            return runner.execute_work_order(request) if request.worker_id in ("b", "c") else ok()

        guard = NoInvocationProvider("claude")
        with mock.patch.object(providers, "resolve_provider", return_value=guard):
            svc = self.service(Recorder({"a": [ok()], "b": [dispatch], "c": [dispatch]}))
            handle = svc.submit_blueprint(blueprint)  # structural validity is no permit
            summary = svc.run_blueprint(handle)
        b, c = self.worker(summary, "b"), self.worker(summary, "c")
        self.assertEqual((b.worker_state, b.state_reason), ("BLOCKED", "BRANCH_GUARD_REFUSED"))
        self.assertEqual((c.worker_state, c.state_reason), ("BLOCKED", "DIRTY_TREE_REFUSED"))
        self.assertEqual(summary.aggregate_status, "BLOCKED")
        self.assertEqual(_git(develop, "status", "--porcelain").stdout, "")
        self.assertEqual(_git(self.repos["c"], "status", "--porcelain").stdout, "?? junk.txt\n")

    def test_no_mutating_git_no_shell_and_no_worktree_change(self):
        heads = {n: _git(r, "rev-parse", "HEAD").stdout for n, r in self.repos.items()}
        branches = {n: _git(r, "branch", "--show-current").stdout for n, r in self.repos.items()}
        calls = []
        real_run, real_popen = subprocess.run, subprocess.Popen

        def spy_run(cmd, *args, **kwargs):
            calls.append([str(a) for a in cmd])
            return real_run(cmd, *args, **kwargs)

        def spy_popen(cmd, *args, **kwargs):
            calls.append([str(a) for a in cmd])
            return real_popen(cmd, *args, **kwargs)

        svc = self.service(Recorder())
        blueprint = self.blueprint([
            self.node("a", mode="write", authorize_path=("src",)), self.node("b", depends_on=("a",)),
        ])
        with mock.patch("subprocess.run", side_effect=spy_run), mock.patch("subprocess.Popen", side_effect=spy_popen):
            summary = svc.run_blueprint(svc.submit_blueprint(blueprint))
        self.assertEqual(summary.aggregate_status, "SUCCESS")
        self.assertTrue(calls)
        for argv in calls:
            self.assertIn("git", Path(argv[0]).name.lower(), argv)  # never a shell or provider binary
            self.assertFalse(MUTATING_GIT_SUBCOMMANDS & set(argv), argv)
        self.assertEqual({n: _git(r, "rev-parse", "HEAD").stdout for n, r in self.repos.items()}, heads)
        self.assertEqual({n: _git(r, "branch", "--show-current").stdout for n, r in self.repos.items()}, branches)
        for repo in self.repos.values():
            self.assertEqual(_git(repo, "status", "--porcelain").stdout, "")
            self.assertEqual(_git(repo, "worktree", "list", "--porcelain").stdout.count("worktree "), 1)


# ---------------------------------------------------------------------------
class RunBlueprintRefusalTests(DagTestBase):
    """Handle identity and Director-owned path binding; fail closed early."""

    def setUp(self):
        super().setUp()
        self.executor = Recorder()
        self.svc = self.service(self.executor)
        self.handle = self.svc.submit_blueprint(self.chain())

    def assertNotRun(self, code, handle):
        with mock.patch.object(rp, "load_manifest", wraps=rp.load_manifest) as load_spy, \
                mock.patch.object(rp, "PipelineRunner", side_effect=AssertionError("runner built")):
            exc = self.assertDirectorError(code, self.svc.run_blueprint, handle)
        self.assertEqual(self.executor.requests, [])
        return exc, load_spy

    def test_single_worker_handle_and_other_types_are_refused(self):
        single = self.svc.submit(fd.DirectorWorkOrderSpec(worktree=str(self.repos["a"]), work_order_text="x"))
        for bad in (single, dataclasses.asdict(self.handle), None, self.handle.pipeline_id):
            with self.subTest(type(bad).__name__):
                self.assertNotRun("INVALID_DAG_HANDLE", bad)

    def test_forged_handles_are_refused_before_loading_any_manifest(self):
        outside = self.root / "outside_manifest.json"
        shutil.copyfile(self.handle.manifest_path, outside)
        other = self.svc.submit_blueprint(self.diamond())
        forgeries = {
            "external manifest": dict(manifest_path=str(outside)),
            "other director dir": dict(director_dir=str(self.root)),
            "state root": dict(state_root=str(self.root / "elsewhere")),
            "worker ids": dict(worker_ids=("a", "b")),
            "fingerprint": dict(plan_fingerprint="0" * 64),
            "manifest digest": dict(manifest_sha256="0" * 64),
            "caller id": dict(blueprint_pipeline_id="someone-else"),
            "other plan": dict(plan=other.plan),
            "other pipeline": dict(pipeline_id=other.pipeline_id),
            "run id": dict(director_run_id=other.pipeline_id),
        }
        for label, change in forgeries.items():
            with self.subTest(label):
                _, load_spy = self.assertNotRun("DAG_HANDLE_MISMATCH", dataclasses.replace(self.handle, **change))
                load_spy.assert_not_called()

    def test_unknown_or_traversal_pipeline_ids_are_refused(self):
        for pid in ("../" + self.handle.pipeline_id, "fdb-../../x", "caller-dag", 7, "fdb-20990101t000000000000-0"):
            with self.subTest(pid):
                self.assertNotRun("DAG_RUN_UNKNOWN", dataclasses.replace(self.handle, pipeline_id=pid))

    def test_tampered_durable_binding_is_refused(self):
        tampers = {
            fd.DAG_PLAN_FILENAME: lambda t: t.replace('"read-only"', '"write"'),
            fd.DAG_PROVENANCE_FILENAME: lambda t: t.replace('"c"', '"z"'),
            fd.DAG_MANIFEST_FILENAME: lambda t: t.replace('"read-only"', '"write"'),
        }
        director_dir = Path(self.handle.director_dir)
        for name, change in tampers.items():
            with self.subTest(name):
                path = director_dir / name
                original = path.read_bytes()
                path.write_bytes(change(original.decode("utf-8")).encode("utf-8"))
                try:
                    self.assertNotRun("DAG_PROVENANCE_MISMATCH", self.handle)
                finally:
                    path.write_bytes(original)
        (director_dir / fd.DAG_PLAN_FILENAME).write_bytes(b"\xff not json")
        self.assertNotRun("DAG_PROVENANCE_MISMATCH", self.handle)

    def test_runner_revalidates_at_execution_time(self):
        self.wos["b"].unlink()
        exc, load_spy = self.assertNotRun("MANIFEST_INVALID", self.handle)
        load_spy.assert_called_once()
        self.assertIn("INVALID_WORK_ORDER", [e["code"] for e in exc.__cause__.errors])

    def test_revalidated_manifest_must_match_the_plan(self):
        real_load = rp.load_manifest

        def drifted(*args, **kwargs):
            manifest = real_load(*args, **kwargs)
            return dataclasses.replace(manifest, sha256="0" * 64)

        with mock.patch.object(rp, "load_manifest", side_effect=drifted), \
                mock.patch.object(rp, "PipelineRunner", side_effect=AssertionError("runner built")):
            self.assertDirectorError("DAG_MANIFEST_MISMATCH", self.svc.run_blueprint, self.handle)
        self.assertEqual(self.executor.requests, [])

    def test_executes_once_and_never_replays(self):
        self.svc.run_blueprint(self.handle)
        self.assertEqual(len(self.executor.requests), 3)
        with mock.patch.object(rp, "PipelineRunner", side_effect=AssertionError("runner built")):
            self.assertDirectorError("DAG_ALREADY_EXECUTED", self.svc.run_blueprint, self.handle)
        self.assertEqual(len(self.executor.requests), 3)

    def test_another_services_roots_do_not_accept_the_handle(self):
        other = self.service(self.executor, director_root=self.root / "other_director")
        with mock.patch.object(rp, "PipelineRunner", side_effect=AssertionError("runner built")):
            self.assertDirectorError("DAG_RUN_UNKNOWN", other.run_blueprint, self.handle)
        moved = self.service(self.executor, state_root=self.root / "other_state")
        with mock.patch.object(rp, "PipelineRunner", side_effect=AssertionError("runner built")):
            self.assertDirectorError("DAG_HANDLE_MISMATCH", moved.run_blueprint, self.handle)
        self.assertEqual(self.executor.requests, [])


# ---------------------------------------------------------------------------
class ResultBlueprintTests(DagTestBase):
    """Read-only reconstruction from Runner's own durable records only."""

    def setUp(self):
        super().setUp()
        self.svc, self.handle, self.summary, _ = self.submit_and_run(self.diamond())
        self.run_id = self.handle.pipeline_id
        self.base = self.state_root / self.run_id

    def edit_json(self, path: Path, change) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_result_blueprint_equals_the_run_summary_and_writes_nothing(self):
        before = sorted((str(p), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file())
        again = self.svc.result_blueprint(self.run_id)
        self.assertEqual(again, self.summary)
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()),
                         before)
        self.assertIsInstance(again, fd.DirectorDagRunSummary)
        self.assertEqual((again.run_id, again.blueprint_pipeline_id, again.plan_fingerprint),
                         (self.run_id, "caller-dag", self.handle.plan_fingerprint))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            again.aggregate_status = "SUCCESS"

    def test_never_parses_provider_prose(self):
        result_path = self.base / "workers" / "a" / "result.json"
        self.edit_json(result_path, lambda d: d.update(stdout="WORK_STATUS=FAILED VERDICT=FAIL", cli_output="FAIL"))
        self.assertEqual(self.svc.result_blueprint(self.run_id).aggregate_status, "SUCCESS")

    def test_missing_or_malformed_worker_record_is_not_success(self):
        (self.base / "workers" / "b" / "result.json").unlink()
        (self.base / "workers" / "c" / "result.json").write_text("{not json", encoding="utf-8")
        summary = self.svc.result_blueprint(self.run_id)
        for wid in ("b", "c"):
            w = self.worker(summary, wid)
            self.assertEqual(w.worker_state, "SUCCESS")  # Runner's pipeline view, verbatim
            self.assertEqual((w.worker_record, w.work_status, w.evidence_health),
                             (fd.WORKER_RECORD_MISSING, None, fd.EVIDENCE_HEALTH_UNKNOWN))
            self.assertFalse(w.runner_proven_success)
        self.assertEqual(summary.pipeline_status, "SUCCESS")
        self.assertEqual(summary.aggregate_status, fd.DAG_AGGREGATE_UNVERIFIED)

    def test_foreign_worker_record_content_is_not_projected(self):
        foreign = {
            "worker_id": lambda d: d.update(worker_id="a"),
            "pipeline_id": lambda d: d.update(pipeline_id="fdb-someone-else"),
            "state": lambda d: d.update(state="FAILED"),
        }
        for label, change in foreign.items():
            with self.subTest(label):
                path = self.base / "workers" / "d" / "result.json"
                original = path.read_bytes()
                self.edit_json(path, change)
                try:
                    d = self.worker(self.svc.result_blueprint(self.run_id), "d")
                    self.assertEqual((d.worker_record, d.work_status, d.runner_state),
                                     (fd.WORKER_RECORD_MISMATCH, None, None))
                    self.assertFalse(d.runner_proven_success)
                finally:
                    path.write_bytes(original)

    def test_unknown_evidence_completeness_is_unknown_not_complete(self):
        self.edit_json(self.base / "workers" / "c" / "result.json",
                       lambda d: [a.pop("evidence_complete", None) for a in d["attempts"]])
        c = self.worker(self.svc.result_blueprint(self.run_id), "c")
        self.assertEqual((c.evidence_complete, c.evidence_health), (None, fd.EVIDENCE_HEALTH_UNKNOWN))
        self.assertIn("EVIDENCE_UNKNOWN", c.unproven_reasons)

    def test_unrecognized_pipeline_status_is_unknown(self):
        self.edit_json(self.base / "pipeline_result.json", lambda d: d.update(status="TOTALLY_FINE"))
        summary = self.svc.result_blueprint(self.run_id)
        self.assertEqual(summary.aggregate_status, fd.DAG_AGGREGATE_UNKNOWN)
        self.assertEqual(summary.aggregate_reasons[0], "PIPELINE_STATUS_UNKNOWN")

    def test_runner_state_must_belong_to_this_submission(self):
        tampers = {
            "manifest digest": ("pipeline.json", lambda d: d.update(manifest_sha256="0" * 64)),
            "manifest body": ("pipeline.json", lambda d: d["manifest"]["workers"][0].update(mode="write")),
            "no manifest": ("pipeline.json", lambda d: d.pop("manifest")),
            "worker dropped": ("pipeline_result.json", lambda d: d["workers"].pop()),
            "worker reordered": ("pipeline_result.json", lambda d: d["workers"].reverse()),
            "worker renamed": ("pipeline_result.json", lambda d: d["workers"][0].update(id="w1")),
            "other pipeline": ("pipeline_result.json", lambda d: d.update(pipeline_id="fdb-other")),
            "workers type": ("pipeline_result.json", lambda d: d.update(workers={"a": {}})),
        }
        for label, (name, change) in tampers.items():
            with self.subTest(label):
                path = self.base / name
                original = path.read_bytes()
                self.edit_json(path, change)
                try:
                    self.assertDirectorError("DAG_PROVENANCE_MISMATCH", self.svc.result_blueprint, self.run_id)
                finally:
                    path.write_bytes(original)
        (self.base / "pipeline.json").unlink()
        self.assertDirectorError("DAG_PROVENANCE_MISMATCH", self.svc.result_blueprint, self.run_id)

    def test_unknown_unexecuted_and_single_worker_ids(self):
        single = self.svc.submit_and_run(fd.DirectorWorkOrderSpec(worktree=str(self.repos["a"]),
                                                                   work_order_text="x"))
        for bad in (single.run_id, "../" + self.run_id, "fdb-x/../../y", None, 5, "fdb-20990101t000000000000-0"):
            with self.subTest(bad):
                self.assertDirectorError("DAG_RUN_UNKNOWN", self.svc.result_blueprint, bad)
        pending = self.svc.submit_blueprint(self.chain())
        self.assertDirectorError("PIPELINE_NOT_FOUND", self.svc.result_blueprint, pending.pipeline_id)


# ---------------------------------------------------------------------------
class SingleWorkerCompatibilityTests(DagTestBase):
    """The single-Work-Order APIs refuse multi-worker runs; nothing else changes."""

    def setUp(self):
        super().setUp()
        self.svc, self.handle, _, _ = self.submit_and_run(self.chain())

    def test_single_worker_projections_refuse_dag_runs_deterministically(self):
        messages = set()
        for method in (self.svc.result, self.svc.evidence, self.svc.decision):
            for _ in range(2):
                with self.subTest(method.__name__):
                    exc = self.assertDirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", method,
                                                   self.handle.pipeline_id)
                    self.assertIn("result_blueprint()", exc.message)
                    messages.add(exc.message)
        self.assertEqual(len(messages), 1)

    def test_refusal_happens_before_any_worker_artifact_is_read(self):
        with mock.patch.object(fd.FabricDirectorService, "_load_json",
                               side_effect=AssertionError("artifact read")):
            for method in (self.svc.result, self.svc.evidence):
                self.assertDirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", method, self.handle.pipeline_id)

    def test_recover_refuses_a_dag_run(self):
        spec = fd.DirectorRecoverySpec(prior_run_id=self.handle.pipeline_id, recovery_work_order_text="Resume.\n",
                                       action="RESUME_WORK_PRODUCT")
        before = self.director_entries()
        self.assertDirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", self.svc.recover, spec)
        self.assertEqual(self.director_entries(), before)

    def test_any_multiworker_runner_state_is_refused_even_without_provenance(self):
        base = self.state_root / "foreign-multi"
        base.mkdir(parents=True)
        workers = [{"id": w, "state": "SUCCESS"} for w in ("x", "y")]
        (base / "pipeline_result.json").write_text(json.dumps({"pipeline_id": "foreign-multi", "workers": workers}),
                                                   encoding="utf-8")
        for method in (self.svc.result, self.svc.evidence, self.svc.decision):
            self.assertDirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", method, "foreign-multi")

    def test_dag_provenance_alone_triggers_the_refusal(self):
        status_path = self.state_root / self.handle.pipeline_id / "pipeline_result.json"
        data = json.loads(status_path.read_text(encoding="utf-8"))
        data["workers"] = data["workers"][:1]
        status_path.write_text(json.dumps(data), encoding="utf-8")
        self.assertDirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", self.svc.result, self.handle.pipeline_id)

    def test_status_still_exposes_runners_canonical_multiworker_view(self):
        status = self.svc.status(self.handle.pipeline_id)
        self.assertEqual(status, rp.read_pipeline_status(self.state_root, self.handle.pipeline_id))
        self.assertEqual([w["id"] for w in status["workers"]], ["a", "b", "c"])

    def test_single_worker_flow_is_unchanged(self):
        summary = self.svc.submit_and_run(fd.DirectorWorkOrderSpec(worktree=str(self.repos["a"]),
                                                                    work_order_text="x"))
        self.assertEqual((summary.worker_id, summary.worker_state, summary.work_status), ("w1", "SUCCESS", "SUCCESS"))
        self.assertEqual(self.svc.evidence(summary.run_id).worker_id, "w1")
        self.assertEqual(self.svc.decision(summary.run_id).decision_code, "READY_FOR_HOST_AUDIT")
        self.assertFalse((self.director_root / summary.run_id / fd.DAG_PROVENANCE_FILENAME).exists())


# ---------------------------------------------------------------------------
class ModuleContractTests(unittest.TestCase):
    def setUp(self):
        self.source = Path(fd.__file__).read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        service = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "FabricDirectorService")
        self.methods = {m.name: m for m in service.body if isinstance(m, ast.FunctionDef)}

    def test_no_second_engine_scheduler_or_concurrency_primitive(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        for forbidden in ("threading", "concurrent", "concurrent.futures", "asyncio", "subprocess", "multiprocessing",
                          "queue", "shutil", "os", "time", "sched", "graphlib"):
            self.assertNotIn(forbidden, imported, forbidden)
        names = {n.name.lower() for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for word in ("topolog", "cycle", "schedul", "retry", "lease", "queue", "dispatch"):
            self.assertFalse([n for n in names if word in n], word)

    def test_dag_methods_only_use_runners_public_validation_status_and_shared_runner(self):
        used = set()
        for name in DAG_METHODS:
            for node in ast.walk(self.methods[name]):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "pipeline":
                    used.add(node.attr)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {
                        "parse_manifest", "PipelineRunner", "execute_work_order", "executor", "_find_cycle",
                        "write_text", "unlink", "rmtree", "rename", "replace_file",
                    }, f"{name}: {node.func.attr}")
        self.assertEqual(used, {"ManifestError", "load_manifest", "PipelineError"})
        run_calls = [n.func.attr for n in ast.walk(self.methods["run_blueprint"])
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertEqual(run_calls.count("_run_manifest"), 1)
        self.assertEqual(run_calls.count("load_manifest"), 1)

    def test_only_additive_gateway_public_surface(self):
        public = {n for n in dir(fd.FabricDirectorService) if not n.startswith("_")}
        self.assertEqual(public - ORIGINAL_PUBLIC_METHODS, {"submit_blueprint", "run_blueprint", "result_blueprint"})
        self.assertEqual(ORIGINAL_PUBLIC_METHODS - public, set())
        for word in ("retire", "prune", "delete", "remove", "cleanup", "approve", "promote", "merge", "push",
                     "commit", "shell", "exec", "replay", "retry", "recover"):
            self.assertFalse([n for n in public - ORIGINAL_PUBLIC_METHODS if word in n.lower()], word)
        self.assertNotIn("runner_worktree_retirement_", self.source)
        self.assertNotRegex(self.source.lower(), r"d-1\.\.d-12 (?:is |are )?approved")

    def test_aggregate_never_promotes_towards_success(self):
        def worker(wid, *reasons):
            return fd.DirectorDagWorkerSummary(worker_id=wid, depends_on=(), unproven_reasons=reasons,
                                               runner_proven_success=not reasons)
        proven, unproven = worker("a"), worker("b", "EVIDENCE_UNKNOWN")
        for status in ("FAILED", "PARTIAL", "BLOCKED", "CANCELLED", "INCOMPLETE", "RUNNING", "DRAINING"):
            for workers in ((proven, proven), (proven, unproven)):
                self.assertEqual(fd._classify_dag_aggregate(status, workers)[0], status)
        self.assertEqual(fd._classify_dag_aggregate("SUCCESS", (proven, proven)), ("SUCCESS", ()))
        self.assertEqual(fd._classify_dag_aggregate("SUCCESS", (proven, unproven)),
                         (fd.DAG_AGGREGATE_UNVERIFIED, ("b:EVIDENCE_UNKNOWN",)))
        for status in (None, "", "success", 0, ["SUCCESS"]):
            self.assertEqual(fd._classify_dag_aggregate(status, (proven, proven))[0], fd.DAG_AGGREGATE_UNKNOWN)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


# ---------------------------------------------------------------------------
class ScopeAndWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.lines = self.text.split("\n")

    def _job_steps(self, job):
        block = re.search(rf"(?ms)^  {job}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.text).group(1)
        return re.findall(r"(?m)^      - name: (.+)$", block), block

    def test_runner_compiler_and_original_suites_are_untouched(self):
        for rel, digest in PINNED_SOURCES.items():
            self.assertEqual(_lf_sha256(REPO_ROOT / rel), digest, rel)

    def test_nine_jobs_and_read_only_permissions(self):
        jobs = re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: ", self.text)
        self.assertEqual(len(jobs), 9)
        self.assertEqual(jobs[0], "fabric-regression")
        self.assertIn("permissions:\n  contents: read\n", self.text)
        self.assertEqual(self.text.count("permissions:"), 1)

    def test_step_is_last_in_fabric_regression_after_runner_queue_and_5a_adjacency_holds(self):
        steps, block = self._job_steps("fabric-regression")
        self.assertEqual(steps[-2:], ["Runner Queue Multiworker regression", CI_STEP_NAME])
        fcp5a = steps.index("FCP-5A-01 DAG blueprint bridge regression without skipped tests")
        self.assertEqual(steps[fcp5a - 1], "Pipeline and infrastructure regression")
        self.assertEqual(steps[fcp5a + 1], "Runner Queue Multiworker regression")
        self.assertIn("runs-on: windows-latest", block)
        self.assertIn('python-version: "3.11"', block)

    def test_step_runs_only_this_suite_with_zero_skips_and_nonzero_count(self):
        self.assertEqual(self.text.count("test_fabric_director_dag"), 1)
        start = self.lines.index(f"      - name: {CI_STEP_NAME}")
        step = "\n".join(self.lines[start:start + 3])
        self.assertIn("loadTestsFromName('scripts.tests.test_fabric_director_dag')", step)
        self.assertIn("r.wasSuccessful() and r.testsRun and not r.skipped", step)
        self.assertEqual(re.findall(r"scripts\.tests\.(\w+)", step), ["test_fabric_director_dag"])

    def test_existing_suites_keep_their_ci_executions(self):
        for module in ("test_fabric_director", "test_fabric_director_cli", "test_runner_pipeline",
                       "test_fabric_dag_blueprint", "test_claude_multiworker"):
            self.assertRegex(self.text, rf"scripts\.tests\.{module}(?![\w])", module)

    def test_removing_the_step_restores_the_2ccc522_workflow(self):
        start = self.lines.index(f"      - name: {CI_STEP_NAME}")
        end = start + 1
        while end < len(self.lines) and self.lines[end].startswith("        "):
            end += 1
        self.assertEqual(self.lines[end], "")
        lines = self.lines[:start] + self.lines[end + 1:]
        # FCP-6A-01 amendment: also strip exactly the one FCP-6A-01 step,
        # which must sit EARLIER in the job than the FCP-5B-01 step.
        header = f"      - name: {FCP6A01_CI_STEP_NAME}"
        self.assertEqual(lines.count(header), 1)
        newest = lines.index(header)
        self.assertLess(newest, start)
        newest_end = newest + 1
        while newest_end < len(lines) and lines[newest_end].startswith("        "):
            newest_end += 1
        self.assertEqual(lines[newest_end], "")
        lines = lines[:newest] + lines[newest_end + 1:]
        # FCP-6B-01 amendment: also strip exactly the one FCP-6B-01 step,
        # which must sit immediately before the FCP-6A-01 step.
        header = "      - name: FCP-6B-01 recovery advisory read-only regression without skipped tests"
        self.assertEqual(lines.count(header), 1)
        fcp6b = lines.index(header)
        fcp6b_end = fcp6b + 1
        while fcp6b_end < len(lines) and lines[fcp6b_end].startswith("        "):
            fcp6b_end += 1
        self.assertEqual(lines[fcp6b_end], "")
        self.assertEqual(fcp6b_end + 1, newest)
        lines = lines[:fcp6b] + lines[fcp6b_end + 1:]
        # FCP-6C-01..04: remove only its additional CI step before validating
        # the historical workflow byte-for-byte fingerprint.
        header = "      - name: FCP-6C-01..04 nightshift composed regression without skipped tests"
        self.assertEqual(lines.count(header), 1)
        fcp6c = lines.index(header)
        fcp6c_end = fcp6c + 1
        while fcp6c_end < len(lines) and lines[fcp6c_end].startswith("        "):
            fcp6c_end += 1
        self.assertEqual(lines[fcp6c_end], "")
        lines = lines[:fcp6c] + lines[fcp6c_end + 1:]
        # FCP-7A-01: remove only its one additional CI step, which must sit
        # immediately before the FCP-6B-01 step, before validating the
        # historical workflow byte-for-byte fingerprint.
        header = "      - name: FCP-7A-01 provider routing pure policy regression without skipped tests"
        self.assertEqual(self.lines.count(header), 1)
        self.assertEqual(lines.count(header), 1)
        fcp7a = lines.index(header)
        fcp7a_end = fcp7a + 1
        while fcp7a_end < len(lines) and lines[fcp7a_end].startswith("        "):
            fcp7a_end += 1
        self.assertEqual(lines[fcp7a_end], "")
        self.assertEqual(fcp7a_end + 1, fcp6b)
        lines = lines[:fcp7a] + lines[fcp7a_end + 1:]
        # FCP-7C-01: remove only its one additional CI step, which must sit
        # immediately before the FCP-7A-01 step.
        header = "      - name: FCP-7B/7C provider router gateway and governed routed CLI regression without skipped tests"
        self.assertEqual(self.lines.count(header), 1)
        self.assertEqual(lines.count(header), 1)
        fcp7c = lines.index(header)
        fcp7c_end = fcp7c + 1
        while fcp7c_end < len(lines) and lines[fcp7c_end].startswith("        "):
            fcp7c_end += 1
        self.assertEqual(lines[fcp7c_end], "")
        self.assertEqual(fcp7c_end + 1, fcp7a)
        restored = "\n".join(lines[:fcp7c] + lines[fcp7c_end + 1:])
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(), WORKFLOW_2CCC522_SHA256)


if __name__ == "__main__":
    unittest.main()
