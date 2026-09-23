import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import claude_multiworker as mw
from scripts.ai import claude_queue as queue
from scripts.ai import claude_runner as runner
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_process_supervision as sup
from scripts.ai import runner_providers as providers

KNOWN = ["claude", "codex", "fake"]
RS = runner.RunState


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "pipeline-tests@example.invalid")
    _git(repo, "config", "user.name", "Pipeline Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _res(state=RS.SUCCESS, *, evidence=None, error=None, work_status=None) -> runner.WorkOrderResult:
    return runner.WorkOrderResult(
        state=state, exit_code=runner.EXIT_CODES.get(state, 1), run_id=f"run_{uuid.uuid4().hex[:6]}",
        evidence_dir=evidence, error_message=error, work_status=work_status,
    )


class FakeProvider(providers.Provider):
    def __init__(self, provider_id, available=True, caps=None):
        self.provider_id = provider_id
        self.display_name = provider_id
        self._available = available
        self._caps = frozenset(caps if caps is not None else {
            providers.Capability.READ_FILES, providers.Capability.SEARCH_FILES,
            providers.Capability.EDIT_FILES, providers.Capability.WRITE_FILES,
        })

    def probe(self):
        if not self._available:
            return providers.ProviderProbe(self.provider_id, False, reason="not installed")
        return providers.ProviderProbe(self.provider_id, True, executable="x", version="1")

    def capabilities(self, policy):
        return self._caps

    def build_invocation(self, **kw):  # pragma: no cover - never executed
        raise AssertionError("fake provider never builds invocations")

    def normalize_result(self, outcome, *, verdict_required):  # pragma: no cover
        raise AssertionError("fake provider never normalizes")

    def is_transient_failure(self, runner_state, error_text):
        return runner_state == "CLAUDE_ERROR" and "rate limit" in (error_text or "").lower()


class Executor:
    """Scripted executor keyed by worker id (taken from the request label).
    `script[wid]` is a list of results (last one repeats) or a callable."""

    def __init__(self, script=None, hold=None, on_call=None):
        self.script = script or {}
        self.hold = hold or {}
        self.on_call = on_call
        self.calls = []
        self._lock = threading.Lock()
        self._current = 0
        self.max_concurrent = 0
        self.by_provider_peak = {}
        self._by_provider = {}

    def __call__(self, request):
        wid = request.label.split("night-001-", 1)[1]
        with self._lock:
            self.calls.append((wid, request))
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
            p = request.provider
            self._by_provider[p] = self._by_provider.get(p, 0) + 1
            self.by_provider_peak[p] = max(self.by_provider_peak.get(p, 0), self._by_provider[p])
        try:
            if self.on_call:
                self.on_call(wid, request)
            if wid in self.hold:
                assert self.hold[wid].wait(timeout=10), f"hold for {wid} never released"
            entry = self.script.get(wid)
            if callable(entry):
                return entry(request)
            if not entry:
                return _res()
            with self._lock:
                n = sum(1 for w, _ in self.calls if w == wid)
            return entry[min(n, len(entry)) - 1]
        finally:
            with self._lock:
                self._current -= 1
                self._by_provider[request.provider] -= 1

    def calls_for(self, wid):
        return [r for w, r in self.calls if w == wid]


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 9, 21, 22, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=max(seconds, 0.001))
        time.sleep(0.001)


class PipelineTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.stable = _make_repo(self.root, "stable")
        self.next_wt = _make_repo(self.root, "runner_next")
        self.repos = {n: _make_repo(self.root, n) for n in ("a", "b", "c", "d")}
        self.state_root = self.root / "state"
        self.wo = self.root / "wo.txt"
        self.wo.write_text("Do the thing.\n", encoding="utf-8")
        self.providers = {
            "claude": FakeProvider("claude"), "codex": FakeProvider("codex"), "fake": FakeProvider("fake"),
        }

    def worker(self, wid, repo="a", **extra):
        data = {"id": wid, "worktree": str(self.repos.get(repo, repo)), "work_order": str(self.wo)}
        data.update(extra)
        return data

    def manifest(self, workers, pipeline_id="night-001", **extra):
        data = {"pipeline_id": pipeline_id, "workers": workers, **extra}
        return rp.parse_manifest(data, self.root, self_worktree=self.stable, registered_providers=KNOWN)

    def runner(self, manifest, executor=None, **kw):
        kw.setdefault("poll_seconds", 0.01)
        kw.setdefault("heartbeat_interval_seconds", None)
        kw.setdefault("self_worktree", self.stable)
        kw.setdefault("provider_resolver", lambda pid: self.providers[pid] if pid in self.providers else (_ for _ in ()).throw(providers.UnknownProviderError(pid, KNOWN)))
        return rp.PipelineRunner(manifest, self.state_root, executor=executor or Executor(), **kw)

    def states(self, result):
        return {w["id"]: w["state"] for w in result.summary["workers"]}

    def worker_json(self, wid, pipeline_id="night-001"):
        return json.loads((self.state_root / pipeline_id / "workers" / wid / "worker.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
class QueueProviderPersistenceTests(unittest.TestCase):
    """1. provider persisted through queue serialization (+ backwards compat)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.repo = _make_repo(self.root, "repo")
        self.qroot = self.root / "queue"

    def _enqueue(self, **kw):
        return queue.enqueue(self.qroot, work_order_text="do it", repository_path=str(self.repo), mode="read-only", **kw)

    def test_provider_survives_enqueue_reload_and_request(self):
        item = self._enqueue(provider="codex", required_capabilities=["SHELL"])
        self.assertEqual(item.provider, "codex")
        raw = json.loads((self.qroot / item.item_id / "item.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["provider"], "codex")
        reloaded = queue.load_item(self.qroot, item.item_id)
        self.assertEqual((reloaded.provider, reloaded.required_capabilities), ("codex", ["SHELL"]))
        request = queue._build_work_order_request(self.qroot, reloaded)
        self.assertEqual((request.provider, request.required_capabilities), ("codex", ["SHELL"]))

    def test_default_provider_is_claude_and_unknown_fails_closed(self):
        self.assertEqual(self._enqueue().provider, "claude")
        with self.assertRaises(queue.QueueError) as ctx:
            self._enqueue(provider="nonexistent")
        self.assertEqual(ctx.exception.reason, "INVALID_PROVIDER")

    def test_legacy_item_without_provider_field_still_loads_and_builds_same_request(self):
        item = self._enqueue()
        path = self.qroot / item.item_id / "item.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("provider")
        raw.pop("required_capabilities")
        path.write_text(json.dumps(raw), encoding="utf-8")
        legacy = queue.load_item(self.qroot, item.item_id)
        self.assertIsNone(legacy.provider)
        request = queue._build_work_order_request(self.qroot, legacy)
        self.assertIsNone(request.provider)
        self.assertIsNone(request.required_capabilities)

    def test_multiworker_dispatches_each_items_persisted_provider(self):
        repo2 = _make_repo(self.root, "repo2")
        queue.enqueue(self.qroot, work_order_text="a", repository_path=str(self.repo), mode="read-only", provider="claude")
        queue.enqueue(self.qroot, work_order_text="b", repository_path=str(repo2), mode="read-only", provider="codex")
        seen = []

        def executor(request):
            seen.append(request.provider)
            return runner.WorkOrderResult(RS.SUCCESS, 0, "r", None, None)

        result = mw.supervise_multiworker(self.qroot, max_workers=2, executor=executor, heartbeat_interval_seconds=None)
        self.assertEqual(sorted(seen), ["claude", "codex"])
        self.assertEqual(sorted(d.provider for d in result.dispatched), ["claude", "codex"])


# ---------------------------------------------------------------------------
class ManifestTests(PipelineTestBase):
    def assertManifestError(self, data, code):
        with self.assertRaises(rp.ManifestError) as ctx:
            rp.parse_manifest(data, self.root, self_worktree=self.stable, registered_providers=KNOWN)
        self.assertIn(code, [e["code"] for e in ctx.exception.errors])

    def test_valid_manifest_defaults_provider_to_claude(self):
        m = self.manifest([self.worker("x")])
        self.assertEqual(m.workers[0].provider, "claude")
        self.assertEqual(m.workers[0].worktree_top, str(self.repos["a"]))

    def test_dependency_cycle_rejected(self):  # 5
        self.assertManifestError({"pipeline_id": "p", "workers": [
            self.worker("a", depends_on=["b"]), self.worker("b", depends_on=["c"]), self.worker("c", depends_on=["a"]),
        ]}, "DEPENDENCY_CYCLE")

    def test_self_and_unknown_dependency_rejected(self):
        self.assertManifestError({"pipeline_id": "p", "workers": [self.worker("a", depends_on=["a"])]}, "SELF_DEPENDENCY")
        self.assertManifestError({"pipeline_id": "p", "workers": [self.worker("a", depends_on=["zz"])]}, "UNKNOWN_DEPENDENCY")

    def test_malformed_manifest_fails_before_any_worker_executes(self):  # 29
        executor = Executor()
        bad = {"pipeline_id": "../evil", "workers": [
            self.worker("ok"), {"id": "bad", "worktree": str(self.root / "nowhere"), "work_order": "missing.txt", "provider": "zzz"},
        ], "surprise": 1}
        with self.assertRaises(rp.ManifestError) as ctx:
            m = rp.parse_manifest(bad, self.root, self_worktree=self.stable, registered_providers=KNOWN)
            self.runner(m, executor).run()
        codes = {e["code"] for e in ctx.exception.errors}
        self.assertTrue({"INVALID_PIPELINE_ID", "UNKNOWN_MANIFEST_KEY", "INVALID_WORKTREE", "INVALID_WORK_ORDER", "UNKNOWN_PROVIDER"} <= codes)
        self.assertEqual(executor.calls, [])
        self.assertFalse(self.state_root.exists())

    def test_malformed_json_file_reports_and_cli_exits_nonzero_without_executing(self):
        path = self.root / "m.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(rp.ManifestError) as ctx:
            rp.load_manifest(path)
        self.assertEqual(ctx.exception.errors[0]["code"], "MANIFEST_MALFORMED_JSON")
        self.assertEqual(rp.main(["validate", "--manifest", str(path)]), rp.EXIT_MANIFEST_INVALID)

    def test_invalid_numeric_fields_rejected(self):
        for extra, code in (
            ({"max_attempts": 0}, "INVALID_MAX_ATTEMPTS"), ({"backoff_seconds": -1}, "INVALID_BACKOFF"),
            ({"timeout_seconds": 0}, "INVALID_TIMEOUT"), ({"mode": "yolo"}, "INVALID_MODE"),
            ({"dependency_policy": "maybe"}, "INVALID_DEPENDENCY_POLICY"),
        ):
            self.assertManifestError({"pipeline_id": "p", "workers": [self.worker("a", **extra)]}, code)

    def test_stable_runner_write_to_runner_next_allowed(self):  # 25
        m = self.manifest([self.worker("n", repo=str(self.next_wt), mode="write", authorize_path=["docs/"])])
        self.assertEqual(m.workers[0].mode, "write")

    def test_stable_runner_write_to_same_worktree_refused(self):  # 26
        self.assertManifestError({"pipeline_id": "p", "workers": [
            self.worker("s", repo=str(self.stable), mode="write", authorize_path=["docs/"]),
        ]}, "SELF_MODIFICATION_REFUSED")
        # a subdirectory of the stable worktree resolves to the same toplevel
        (self.stable / "sub").mkdir()
        self.assertManifestError({"pipeline_id": "p", "workers": [
            self.worker("s", repo=str(self.stable / "sub"), mode="write", authorize_path=["docs/"]),
        ]}, "SELF_MODIFICATION_REFUSED")

    def test_stable_runner_read_only_on_itself_is_allowed(self):
        self.manifest([self.worker("s", repo=str(self.stable), mode="read-only")])

    def test_runtime_self_check_blocks_even_if_manifest_validation_was_bypassed(self):
        m = self.manifest([self.worker("s", repo=str(self.next_wt), mode="write", authorize_path=["docs/"])])
        executor = Executor()
        result = self.runner(m, executor, self_worktree=self.next_wt).run()
        self.assertEqual(self.states(result)["s"], "BLOCKED")
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.worker_json("s")["state_reason"], "SELF_MODIFICATION_REFUSED")


# ---------------------------------------------------------------------------
class SchedulingTests(PipelineTestBase):
    def test_different_workers_use_different_providers_and_run_concurrently(self):  # 2, 3, 8
        gate = threading.Event()
        holder = {}

        def on_call(wid, request):
            holder[wid] = request.provider
            if len(holder) == 3:
                gate.set()  # all three overlapped

        executor = Executor(hold={"x": gate, "y": gate, "z": gate}, on_call=on_call)
        m = self.manifest([
            self.worker("x", repo="a", provider="claude"), self.worker("y", repo="b", provider="codex"),
            self.worker("z", repo="c", provider="fake"),
        ])
        result = self.runner(m, executor, max_workers=3).run()
        self.assertEqual(holder, {"x": "claude", "y": "codex", "z": "fake"})
        self.assertEqual(executor.max_concurrent, 3)
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(set(result.summary["provider_breakdown"]), {"claude", "codex", "fake"})
        self.assertEqual(self.worker_json("y")["active_provider"], "codex")

    def test_dependency_prevents_early_execution(self):  # 4
        order = []
        executor = Executor(on_call=lambda wid, req: order.append(wid))
        m = self.manifest([
            self.worker("late", repo="b", depends_on=["early"]), self.worker("early", repo="a"),
        ])
        self.runner(m, executor, max_workers=4).run()
        self.assertEqual(order, ["early", "late"])

    def test_dependency_waiting_state_visible_while_dependency_runs(self):
        gate = threading.Event()
        seen = {}

        def on_call(wid, req):
            if wid == "first":
                seen["late_state"] = self.worker_json("late")["state"]
                gate.set()

        executor = Executor(on_call=on_call)
        m = self.manifest([self.worker("first", repo="a"), self.worker("late", repo="b", depends_on=["first"])])
        self.runner(m, executor, max_workers=2).run()
        self.assertEqual(seen["late_state"], "WAITING_DEPENDENCY")

    def test_failed_worker_does_not_stop_independent_worker_and_cancels_dependents(self):  # 6
        executor = Executor({"bad": [_res(RS.WORK_FAILED, work_status="FAILED")]})
        m = self.manifest([
            self.worker("bad", repo="a"), self.worker("dep", repo="b", depends_on=["bad"]),
            self.worker("free", repo="c"),
        ])
        result = self.runner(m, executor, max_workers=1).run()
        self.assertEqual(self.states(result), {"bad": "FAILED", "dep": "CANCELLED", "free": "SUCCESS"})
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(executor.calls_for("dep"), [])
        self.assertTrue(self.worker_json("dep")["state_reason"].startswith("DEPENDENCY_UNSATISFIED"))

    def test_success_or_partial_policy_allows_dependent_after_partial(self):
        executor = Executor({"p": [_res(RS.PARTIAL, work_status="PARTIAL")]})
        m = self.manifest([
            self.worker("p", repo="a"), self.worker("q", repo="b", depends_on=["p"], dependency_policy="success_or_partial"),
        ])
        result = self.runner(m, executor).run()
        self.assertEqual(self.states(result), {"p": "PARTIAL", "q": "SUCCESS"})

    def test_same_write_worktree_never_runs_twice_concurrently(self):  # 7
        state = {"active": 0, "peak": 0}
        lock = threading.Lock()

        def script(request):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return _res()

        executor = Executor({"w1": script, "w2": script})
        m = self.manifest([
            self.worker("w1", repo="a", mode="write", authorize_path=["docs/"]),
            self.worker("w2", repo="a", mode="write", authorize_path=["docs/"]),
        ])
        result = self.runner(m, executor, max_workers=4).run()
        self.assertEqual(state["peak"], 1)
        self.assertEqual(result.status, "SUCCESS")

    def test_read_worker_waits_for_write_worker_on_same_worktree_but_reads_overlap(self):
        executor = Executor()
        m = self.manifest([self.worker("r1", repo="a"), self.worker("r2", repo="a")])
        gate = threading.Event()
        peak = {}

        def on_call(wid, req):
            peak[wid] = executor.max_concurrent
            if len(peak) == 2:
                gate.set()

        executor.on_call = on_call
        executor.hold = {"r1": gate, "r2": gate}
        self.runner(m, executor, max_workers=2).run()
        self.assertEqual(executor.max_concurrent, 2)

    def test_external_write_lease_holder_blocks_then_releases(self):  # 7 (durable)
        lease = rp.DirLease(rp.worktree_lease_dir(self.repos["a"]))
        self.assertTrue(lease.try_acquire({"pipeline_id": "other", "worker_id": "o", "pid": 1, "worktree": str(self.repos["a"])}))
        executor = Executor()
        m = self.manifest([self.worker("w", repo="a", mode="write", authorize_path=["docs/"])])
        result = self.runner(m, executor, lease_wait_seconds=0.05).run()
        self.assertEqual(executor.calls, [])
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.stop_reason, "WORKTREE_LEASE_HELD_BY_OTHER_OWNER")
        lease.release()
        result = self.runner(m, executor).run()
        self.assertEqual(result.status, "SUCCESS")

    def test_lease_identity_and_stale_recovery(self):
        path = rp.worktree_lease_dir(self.repos["a"])
        first = rp.DirLease(path)
        self.assertTrue(first.try_acquire({
            "pipeline_id": "p1", "worker_id": "w1", "pid": 4242, "started_at_utc": "t", "worktree": "wt",
        }))
        holder = rp.DirLease(path).holder()
        self.assertEqual({k: holder[k] for k in ("pipeline_id", "worker_id", "pid", "started_at_utc", "worktree")},
                         {"pipeline_id": "p1", "worker_id": "w1", "pid": 4242, "started_at_utc": "t", "worktree": "wt"})
        self.assertFalse(rp.DirLease(path).try_acquire({"pid": 1}))  # live owner: never stolen
        # Simulate a crashed owner: identity file remains, OS lock is gone.
        first._lock.release()
        first._lock = None
        second = rp.DirLease(path)
        self.assertTrue(second.try_acquire({"pipeline_id": "p2", "worker_id": "w2", "pid": 7}))
        self.assertEqual(second.recovered_from["worker_id"], "w1")
        second.release()

    def test_lease_is_inside_git_dir_not_worktree(self):
        path = rp.worktree_lease_dir(self.repos["a"])
        self.assertIn(str(self.repos["a"] / ".git"), str(path))
        lease = rp.DirLease(path)
        lease.try_acquire({"pid": 1})
        self.assertEqual(_git(self.repos["a"], "status", "--porcelain").stdout.strip(), "")
        lease.release()

    def test_provider_specific_concurrency_respected(self):  # 17
        executor = Executor(script={w: (lambda r: (time.sleep(0.05), _res())[1]) for w in "abcd"})
        m = self.manifest([
            self.worker("a", repo="a", provider="claude"), self.worker("b", repo="b", provider="claude"),
            self.worker("c", repo="c", provider="codex"), self.worker("d", repo="d", provider="codex"),
        ])
        self.runner(m, executor, max_workers=4, provider_limits={"claude": 1, "codex": 2}).run()
        self.assertEqual(executor.by_provider_peak["claude"], 1)
        self.assertEqual(executor.by_provider_peak["codex"], 2)
        self.assertGreaterEqual(executor.max_concurrent, 2)

    def test_global_max_workers_respected(self):
        executor = Executor(script={w: (lambda r: (time.sleep(0.03), _res())[1]) for w in "abcd"})
        m = self.manifest([self.worker(w, repo=w) for w in "abcd"])
        self.runner(m, executor, max_workers=2).run()
        self.assertEqual(executor.max_concurrent, 2)

    def test_priority_orders_ready_workers(self):
        order = []
        executor = Executor(on_call=lambda wid, req: order.append(wid))
        m = self.manifest([
            self.worker("low", repo="a", priority=1), self.worker("high", repo="b", priority=9),
        ])
        self.runner(m, executor, max_workers=1).run()
        self.assertEqual(order, ["high", "low"])

    def test_unavailable_codex_does_not_block_claude_worker(self):  # 18
        self.providers["codex"] = FakeProvider("codex", available=False)
        executor = Executor()
        m = self.manifest([
            self.worker("k", repo="a", provider="codex"), self.worker("dep", repo="c", depends_on=["k"]),
            self.worker("c1", repo="b", provider="claude"),
        ])
        result = self.runner(m, executor, max_workers=2).run()
        self.assertEqual(self.states(result), {"k": "BLOCKED", "dep": "CANCELLED", "c1": "SUCCESS"})
        self.assertEqual(self.worker_json("k")["state_reason"], "PROVIDER_UNAVAILABLE")
        self.assertEqual([w for w, _ in executor.calls], ["c1"])
        pre = json.loads((self.state_root / "night-001" / "workers" / "k" / "preflight.json").read_text(encoding="utf-8"))
        self.assertEqual(pre["candidates"][0]["verdict"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(self.states(result)["k"], "BLOCKED")

    def test_capability_mismatch_at_preflight_blocks_without_execution(self):
        self.providers["codex"] = FakeProvider("codex", caps={providers.Capability.READ_FILES, providers.Capability.SEARCH_FILES})
        executor = Executor()
        m = self.manifest([self.worker("w", provider="codex", mode="write", authorize_path=["docs/"])])
        result = self.runner(m, executor).run()
        self.assertEqual(self.states(result)["w"], "BLOCKED")
        self.assertEqual(self.worker_json("w")["state_reason"], "CAPABILITY_MISMATCH")
        self.assertEqual(executor.calls, [])

    def test_backwards_compatible_single_claude_worker(self):  # 28
        executor = Executor()
        result = self.runner(self.manifest([self.worker("only")]), executor, max_workers=1).run()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.exit_code, 0)
        request = executor.calls_for("only")[0]
        self.assertEqual((request.provider, request.mode, request.repo), ("claude", "read-only", str(self.repos["a"])))
        self.assertNotEqual(request.timeout_seconds, 0)
        self.assertEqual(request.timeout_seconds, runner.DEFAULT_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
class RetryAndFallbackTests(PipelineTestBase):
    RATE = dict(error="Claude API rate limit exceeded (429)")

    def transient(self):
        return _res(RS.CLAUDE_ERROR, evidence=self.root, **self.RATE)

    def test_transient_provider_failure_retries_then_succeeds(self):  # 13
        executor = Executor({"w": [self.transient(), _res()]})
        m = self.manifest([self.worker("w", max_attempts=3)])
        result = self.runner(m, executor).run()
        self.assertEqual(result.status, "SUCCESS")
        attempts = self.worker_json("w")["attempts"]
        self.assertEqual([a["status"] for a in attempts], ["COMPLETED", "COMPLETED"])
        self.assertTrue(attempts[0]["retry_decision"].startswith("RETRY:TRANSIENT"))
        self.assertTrue(attempts[0]["process_confirmed_stopped"])

    def test_backoff_delays_retry_using_clock(self):
        clock = FakeClock()
        m = self.manifest([self.worker("w", max_attempts=2, backoff_seconds=120)])
        executor = Executor({"w": [self.transient(), _res()]})
        start = clock.now
        result = self.runner(m, executor, clock=clock, sleep_fn=clock.sleep).run()
        self.assertEqual(result.status, "SUCCESS")
        self.assertGreaterEqual((clock.now - start).total_seconds(), 120)

    def test_max_attempts_respected(self):  # 16
        executor = Executor({"w": [self.transient()]})
        m = self.manifest([self.worker("w", max_attempts=3)])
        result = self.runner(m, executor).run()
        self.assertEqual(len(executor.calls_for("w")), 3)
        self.assertEqual(self.states(result)["w"], "FAILED")
        self.assertEqual(self.worker_json("w")["state_reason"], "MAX_ATTEMPTS_EXHAUSTED")

    def assertNoRetry(self, results, expected_state, **worker_kw):
        executor = Executor({"w": results})
        m = self.manifest([self.worker("w", max_attempts=5, **worker_kw)])
        result = self.runner(m, executor).run()
        self.assertEqual(len(executor.calls_for("w")), 1)
        self.assertEqual(self.states(result)["w"], expected_state)

    def test_blocked_work_result_does_not_retry(self):  # 14
        self.assertNoRetry([_res(RS.BLOCKED, evidence=self.root, work_status="BLOCKED")], "BLOCKED")

    def test_capability_mismatch_result_does_not_retry(self):  # 15
        self.assertNoRetry([_res(RS.CAPABILITY_MISMATCH, error="missing EDIT_FILES")], "BLOCKED")

    def test_code_or_test_failure_does_not_retry(self):
        self.assertNoRetry([_res(RS.WORK_FAILED, evidence=self.root, work_status="FAILED")], "FAILED")

    def test_non_transient_process_error_does_not_retry(self):
        self.assertNoRetry([_res(RS.CLAUDE_ERROR, evidence=self.root, error="segfault")], "FAILED")

    def test_governance_and_invalid_work_order_refusals_do_not_retry(self):
        for state in (
            RS.DIRTY_TREE_REFUSED, RS.INVALID_WORK_ORDER, RS.BRANCH_GUARD_REFUSED, RS.WRITE_SCOPE_REQUIRED,
            RS.RESUME_REFUSED,
        ):
            with self.subTest(state=state):
                self.setUp()
                self.assertNoRetry([_res(state, evidence=self.root, error="refused")], "BLOCKED")

    def test_failed_safety_and_executor_exception_do_not_retry(self):
        self.assertNoRetry([_res(RS.FAILED_SAFETY, evidence=self.root)], "FAILED")
        self.setUp()

        def boom(request):
            raise RuntimeError("kaput")

        executor = Executor({"w": boom})
        result = self.runner(self.manifest([self.worker("w", max_attempts=4)]), executor).run()
        self.assertEqual((len(executor.calls_for("w")), self.states(result)["w"]), (1, "FAILED"))
        self.assertEqual(self.worker_json("w")["state_reason"], "EXECUTOR_EXCEPTION")

    def test_retry_of_write_job_waits_until_previous_process_confirmed_stopped(self):
        events = []
        real = rp.DirLease.release

        def tracked_release(self_):
            events.append("lease_released")
            return real(self_)

        def script(request):
            events.append("attempt_start")
            n = events.count("attempt_start")
            return self.transient() if n == 1 else _res()

        executor = Executor({"w": script})
        m = self.manifest([self.worker("w", repo="a", mode="write", authorize_path=["docs/"], max_attempts=2)])
        with mock.patch.object(rp.DirLease, "release", tracked_release):
            self.runner(m, executor).run()
        first_start, second_start = [i for i, e in enumerate(events) if e == "attempt_start"]
        self.assertIn("lease_released", events[first_start:second_start])
        # the guard itself: an attempt not confirmed stopped is never followed by another
        w = self.worker_json("w")
        self.assertTrue(all(a["process_confirmed_stopped"] for a in w["attempts"]))

    def test_unconfirmed_previous_attempt_blocks_new_start(self):
        m = self.manifest([self.worker("w", repo="a", mode="write", authorize_path=["docs/"])])
        r = self.runner(m, Executor())
        r._init_state()
        rt = r.workers["w"]
        rt.attempts.append({"attempt": 1, "executed": True, "process_confirmed_stopped": False})
        rt.state = "READY"
        r._pool = mock.Mock()
        r._start_ready(datetime.now(timezone.utc))
        r._pool.submit.assert_not_called()
        r._pipeline_lock.release()

    def test_provider_fallback_before_execution_when_configured(self):  # 12/27 (positive)
        executor = Executor({"w": lambda req: (
            _res(RS.PROVIDER_UNAVAILABLE, error="gone") if req.provider == "codex" else _res()
        )})
        m = self.manifest([self.worker("w", provider="codex", fallback_providers=["claude"])])
        result = self.runner(m, executor).run()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual([r.provider for _, r in executor.calls], ["codex", "claude"])
        w = self.worker_json("w")
        self.assertEqual(w["active_provider"], "claude")
        self.assertEqual(w["fallbacks_used"][0]["phase"], "PRE_EXECUTION")
        self.assertEqual(w["attempts"][0]["status"], "NOT_EXECUTED")

    def test_preflight_fallback_when_primary_unavailable(self):
        self.providers["codex"] = FakeProvider("codex", available=False)
        executor = Executor()
        m = self.manifest([self.worker("w", provider="codex", fallback_providers=["claude"])])
        result = self.runner(m, executor).run()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(executor.calls_for("w")[0].provider, "claude")

    def test_no_fallback_unless_explicitly_configured(self):
        executor = Executor({"w": [_res(RS.PROVIDER_UNAVAILABLE, error="gone")]})
        result = self.runner(self.manifest([self.worker("w", provider="codex")]), executor).run()
        self.assertEqual(self.states(result)["w"], "BLOCKED")
        self.assertEqual(len(executor.calls), 1)

    def test_provider_fallback_cannot_occur_after_write_execution_begins(self):  # 27
        calls = {"n": 0}

        def script(req):
            calls["n"] += 1
            if calls["n"] == 1:  # WRITE provider ran (evidence exists) and hit a transient error
                return self.transient()
            return _res(RS.PROVIDER_UNAVAILABLE, error="codex vanished")

        executor = Executor({"w": script})
        m = self.manifest([self.worker(
            "w", provider="codex", mode="write", authorize_path=["docs/"], max_attempts=3, fallback_providers=["claude"],
        )])
        result = self.runner(m, executor).run()
        self.assertEqual({r.provider for _, r in executor.calls}, {"codex"})
        w = self.worker_json("w")
        self.assertTrue(w["provider_locked"] or w["state"] == "BLOCKED")
        self.assertEqual(w["fallbacks_used"], [])
        self.assertEqual(self.states(result)["w"], "BLOCKED")


# ---------------------------------------------------------------------------
class DurabilityTests(PipelineTestBase):
    def test_durable_reload_preserves_queued_state_and_provider(self):  # 9
        m = self.manifest([self.worker("a", provider="codex"), self.worker("b", repo="b", depends_on=["a"])])
        r = self.runner(m)
        r.request_shutdown()  # stop before scheduling anything
        result = r.run()
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.stop_reason, "SHUTDOWN_REQUESTED")
        reloaded = self.runner(m)
        reloaded._init_state()
        self.assertEqual(reloaded.workers["a"].active_provider, "codex")
        self.assertIn(reloaded.workers["a"].state, ("READY", "QUEUED"))
        self.assertEqual(reloaded.workers["b"].state, "WAITING_DEPENDENCY")
        reloaded._pipeline_lock.release()

    def _crash_with_running_worker(self, mode="read-only"):
        """Persist a RUNNING worker owned by an orchestrator that then died."""
        m = self.manifest([self.worker("w", repo="a", mode=mode, **({"authorize_path": ["docs/"]} if mode == "write" else {}))])
        dead = self.runner(m)
        dead._init_state()
        rt = dead.workers["w"]
        rt.attempts.append({"attempt": 1, "executed": True, "status": "RUNNING", "provider": "claude", "started_at_utc": "t"})
        rt.owner = {"pid": 99999999, "hostname": dead.hostname, "run_id": "dead"}
        rt.provider_locked = True
        dead._force_state(rt, rp.WorkerState.RUNNING, None)
        dead._save_pipeline()
        dead._pipeline_lock.release()
        return m

    def test_stale_running_worker_becomes_interrupted_not_success_and_is_not_reexecuted(self):  # 10, 12
        m = self._crash_with_running_worker()
        executor = Executor()
        result = self.runner(m, executor).run()
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.states(result)["w"], "INTERRUPTED")
        self.assertEqual(result.status, "INCOMPLETE")
        w = self.worker_json("w")
        self.assertEqual(w["state_reason"], "ORCHESTRATOR_DIED_WHILE_RUNNING")
        self.assertEqual(w["attempts"][0]["status"], "INTERRUPTED")

    def test_interrupted_worker_requeued_only_on_explicit_request(self):  # 30
        m = self._crash_with_running_worker()
        self.runner(m, Executor()).run()
        executor = Executor()
        result = self.runner(m, executor, requeue_interrupted=True).run()
        self.assertEqual(self.states(result)["w"], "SUCCESS")
        self.assertEqual(len(executor.calls_for("w")), 1)
        w = self.worker_json("w")
        self.assertEqual(len(w["attempts"]), 2)
        self.assertEqual(w["attempts"][0]["status"], "INTERRUPTED")

    def test_terminal_states_survive_restart_and_are_not_rerun(self):
        m = self.manifest([self.worker("ok", repo="a"), self.worker("bad", repo="b")])
        executor = Executor({"bad": [_res(RS.WORK_FAILED, evidence=self.root)]})
        self.runner(m, executor).run()
        second = Executor()
        result = self.runner(m, second).run()
        self.assertEqual(second.calls, [])
        self.assertEqual(self.states(result), {"ok": "SUCCESS", "bad": "FAILED"})

    def test_heartbeat_prevents_false_stale_detection(self):  # 11
        now = datetime(2026, 9, 21, tzinfo=timezone.utc)
        fresh = {"pid": 1, "hostname": "h", "last_heartbeat_utc": (now - timedelta(seconds=5)).isoformat()}
        old = {**fresh, "last_heartbeat_utc": (now - timedelta(hours=3)).isoformat()}
        inconclusive = lambda pid: None
        self.assertEqual(rp.assess_owner(fresh, now, "h", inconclusive, 1800), "ALIVE")
        self.assertEqual(rp.assess_owner(old, now, "h", inconclusive, 1800), "UNVERIFIABLE")
        self.assertEqual(rp.assess_owner(old, now, "h", lambda pid: False, 1800), "STALE")
        self.assertEqual(rp.assess_owner(old, now, "h", lambda pid: True, 1800), "ALIVE")
        self.assertEqual(rp.assess_owner(old, now, "other-host", lambda pid: False, 1800), "UNVERIFIABLE")

    def test_heartbeat_thread_updates_independent_of_provider_output(self):
        gate = threading.Event()
        seen = []

        def on_call(wid, req):
            hb = self.state_root / "night-001" / "workers" / wid / "heartbeat.json"
            first = json.loads(hb.read_text(encoding="utf-8"))["last_heartbeat_utc"]
            deadline = time.time() + 5
            while time.time() < deadline:  # provider is silent; only the heartbeat thread can change this
                cur = json.loads(hb.read_text(encoding="utf-8"))
                if cur["last_heartbeat_utc"] != first:
                    seen.append(cur)
                    break
                time.sleep(0.01)
            gate.set()

        executor = Executor(on_call=on_call, hold={"w": gate})
        m = self.manifest([self.worker("w", repo="a", mode="write", authorize_path=["docs/"])])
        self.runner(m, executor, heartbeat_interval_seconds=0.02).run()
        self.assertEqual(len(seen), 1)
        for key in ("worker_id", "pid", "provider", "worktree", "started_at_utc", "last_heartbeat_utc"):
            self.assertIn(key, seen[0])

    def test_process_restart_does_not_duplicate_a_running_worker(self):  # 12
        gate = threading.Event()
        started = threading.Event()
        executor = Executor(on_call=lambda w, r: started.set(), hold={"w": gate})
        m = self.manifest([self.worker("w", repo="a")])
        first = self.runner(m, executor)
        thread = threading.Thread(target=first.run)
        thread.start()
        self.assertTrue(started.wait(5))
        second_exec = Executor()
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(m, second_exec).run()
        self.assertEqual(ctx.exception.code, "PIPELINE_LOCKED")
        self.assertEqual(second_exec.calls, [])
        self.assertEqual(self.worker_json("w")["state"], "RUNNING")  # untouched by the refused second run
        gate.set()
        thread.join(10)
        self.assertEqual(len(executor.calls_for("w")), 1)

    def test_changed_manifest_refused_for_existing_pipeline_id(self):
        self.runner(self.manifest([self.worker("w")]), Executor()).run()
        changed = self.manifest([self.worker("w"), self.worker("x", repo="b")])
        executor = Executor()
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(changed, executor).run()
        self.assertEqual(ctx.exception.code, "MANIFEST_CHANGED")
        self.assertEqual(executor.calls, [])

    def test_state_root_inside_target_worktree_refused(self):
        m = self.manifest([self.worker("w")])
        bad = rp.PipelineRunner(
            m, self.repos["a"] / "runtime" / "pipelines", executor=Executor(), self_worktree=self.stable,
            heartbeat_interval_seconds=None,
        )
        with self.assertRaises(rp.PipelineError) as ctx:
            bad.run()
        self.assertEqual(ctx.exception.code, "STATE_ROOT_INSIDE_TARGET_WORKTREE")

    def test_rerun_requeues_failed_worker_and_its_cancelled_dependents_only(self):
        m = self.manifest([
            self.worker("bad", repo="a"), self.worker("dep", repo="b", depends_on=["bad"]), self.worker("ok", repo="c"),
        ])
        self.runner(m, Executor({"bad": [_res(RS.WORK_FAILED, evidence=self.root)]})).run()
        executor = Executor()
        result = self.runner(m, executor, rerun=["bad"]).run()
        self.assertEqual(self.states(result), {"bad": "SUCCESS", "dep": "SUCCESS", "ok": "SUCCESS"})
        self.assertEqual(sorted(w for w, _ in executor.calls), ["bad", "dep"])  # "ok" was not re-run
        with self.assertRaises(rp.PipelineError):
            self.runner(m, Executor(), rerun=["ok"]).run()

    def test_pipeline_can_resume_after_controlled_interruption(self):  # 30
        gate = threading.Event()
        r_holder = {}

        def on_call(wid, req):
            if wid == "first":
                r_holder["r"].request_shutdown()  # operator Ctrl+C mid-run
                gate.set()

        executor = Executor(on_call=on_call, hold={"first": gate})
        m = self.manifest([self.worker("first", repo="a"), self.worker("second", repo="b", depends_on=["first"])])
        r = self.runner(m, executor, max_workers=1)
        r_holder["r"] = r
        result = r.run()
        self.assertEqual(self.states(result)["first"], "SUCCESS")
        self.assertNotEqual(self.states(result)["second"], "SUCCESS")
        self.assertEqual(result.status, "INCOMPLETE")
        resumed = Executor()
        result = self.runner(m, resumed, max_workers=1).run()
        self.assertEqual([w for w, _ in resumed.calls], ["second"])  # only the unfinished one
        self.assertEqual(result.status, "SUCCESS")


# ---------------------------------------------------------------------------
class NightShiftTests(PipelineTestBase):
    def test_deadline_stops_new_scheduling_and_draining_lets_running_finish(self):  # 19, 20
        clock = FakeClock()
        gate = threading.Event()

        def on_call(wid, req):
            if wid == "one":
                clock.now += timedelta(hours=9)  # the 8h window elapses while it runs
                gate.set()

        executor = Executor(on_call=on_call, hold={"one": gate})
        m = self.manifest([self.worker("one", repo="a"), self.worker("two", repo="b", depends_on=["one"]), self.worker("free", repo="c")])
        result = self.runner(m, executor, max_workers=1, clock=clock, sleep_fn=clock.sleep, max_runtime_seconds=8 * 3600).run()
        st = self.states(result)
        self.assertEqual(st["one"], "SUCCESS")  # running job was allowed to finish (DRAINING)
        self.assertNotIn(st["two"], ("RUNNING", "SUCCESS"))
        self.assertEqual([w for w, _ in executor.calls], ["one"])  # nothing new started
        self.assertEqual(result.stop_reason, "DEADLINE_REACHED")
        self.assertEqual(result.status, "INCOMPLETE")
        persisted = json.loads((self.state_root / "night-001" / "pipeline.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["stop_reason"], "DEADLINE_REACHED")
        self.assertIsNotNone(persisted["deadline_utc"])

    def test_pipeline_deadline_in_manifest_is_honoured(self):
        clock = FakeClock()
        past = (clock.now - timedelta(minutes=1)).isoformat()
        executor = Executor()
        m = self.manifest([self.worker("w")], deadline_utc=past)
        result = self.runner(m, executor, clock=clock, sleep_fn=clock.sleep).run()
        self.assertEqual(executor.calls, [])
        self.assertEqual(result.stop_reason, "DEADLINE_REACHED")

    def test_not_before_delays_start(self):
        clock = FakeClock()
        not_before = (clock.now + timedelta(minutes=30)).isoformat()
        seen = {}
        executor = Executor(on_call=lambda w, r: seen.setdefault("t", clock.now))
        m = self.manifest([self.worker("w")], not_before_utc=not_before)
        self.runner(m, executor, clock=clock, sleep_fn=clock.sleep, poll_seconds=60).run()
        self.assertGreaterEqual(seen["t"], datetime.fromisoformat(not_before))

    def test_keep_awake_lifecycle_mocked(self):  # 21
        calls = []
        api = lambda flags: calls.append(flags)
        ka = rp.WindowsKeepAwake(api=api)
        executor = Executor()
        m = self.manifest([self.worker("w")])
        self.runner(m, executor, keep_awake=ka).run()
        self.assertEqual(calls[0], rp.WindowsKeepAwake.ES_CONTINUOUS | rp.WindowsKeepAwake.ES_SYSTEM_REQUIRED)
        self.assertEqual(calls[-1], rp.WindowsKeepAwake.ES_CONTINUOUS)  # released, power plan untouched
        self.assertEqual(calls.count(calls[0]), 1)  # acquired once (idempotent)
        self.assertFalse(ka.active)

    def test_keep_awake_released_when_run_raises(self):
        calls = []
        ka = rp.WindowsKeepAwake(api=calls.append)
        boom = mock.Mock(side_effect=RuntimeError("scheduler bug"))
        r = self.runner(self.manifest([self.worker("w")]), Executor(), keep_awake=ka)
        r._refresh = boom
        with self.assertRaises(RuntimeError):
            r.run()
        self.assertFalse(ka.active)

    def test_keep_awake_not_held_when_no_useful_work(self):
        ka = rp.NullKeepAwake()
        m = self.manifest([self.worker("w")])
        r = self.runner(m, Executor(), keep_awake=ka)
        r.request_shutdown()
        r.run()
        self.assertFalse(ka.active)

    def test_keep_awake_degrades_cleanly_on_unsupported_os(self):
        with mock.patch.object(rp.platform, "system", return_value="Linux"):
            ka = rp.default_keep_awake()
        self.assertIsInstance(ka, rp.NullKeepAwake)
        ka.acquire()
        ka.release()
        with mock.patch.object(rp.platform, "system", return_value="Windows"):
            self.assertIsInstance(rp.default_keep_awake(), rp.WindowsKeepAwake)

    def test_graceful_shutdown_persists_state_and_lets_running_finish(self):  # 22
        gate = threading.Event()
        holder = {}

        def on_call(wid, req):
            holder["r"].request_shutdown()
            time.sleep(0.05)
            gate.set()

        executor = Executor(on_call=on_call, hold={"a": gate})
        m = self.manifest([self.worker("a", repo="a"), self.worker("b", repo="b")])
        r = self.runner(m, executor, max_workers=1)
        holder["r"] = r
        result = r.run()
        st = self.states(result)
        self.assertEqual(st["a"], "SUCCESS")
        self.assertNotIn(st["b"], ("RUNNING", "SUCCESS", "FAILED"))
        persisted = json.loads((self.state_root / "night-001" / "pipeline.json").read_text(encoding="utf-8"))
        self.assertEqual((persisted["status"], persisted["stop_reason"]), ("INCOMPLETE", "SHUTDOWN_REQUESTED"))
        self.assertEqual(self.worker_json("b")["state"], st["b"])

    def test_keyboard_interrupt_first_drains_second_forces_and_persists(self):  # 22
        m = self.manifest([self.worker("a", repo="a")])
        r = self.runner(m, Executor())
        r._on_interrupt()
        self.assertTrue(r._shutdown.is_set())
        with self.assertRaises(rp._ForcedStop):
            r._on_interrupt()

    def test_forced_shutdown_marks_running_worker_interrupted_and_persists(self):
        gate = threading.Event()
        started = threading.Event()
        executor = Executor(on_call=lambda w, req: started.set(), hold={"w": gate})
        m = self.manifest([self.worker("w", repo="a")])
        r = self.runner(m, executor)
        original = r._start_ready
        calls = {"n": 0}

        def interrupting(now):
            out = original(now)
            calls["n"] += 1
            if calls["n"] >= 2:
                raise KeyboardInterrupt
            return out

        r._start_ready = interrupting
        real_wait = rp.futures_wait

        def wait_then_interrupt(*a, **k):
            started.wait(5)
            raise KeyboardInterrupt

        try:
            with mock.patch.object(rp, "futures_wait", wait_then_interrupt):
                result = r.run()
        finally:
            gate.set()
        self.assertEqual(self.states(result)["w"], "INTERRUPTED")
        self.assertEqual(result.stop_reason, "FORCED_SHUTDOWN")
        self.assertEqual(self.worker_json("w")["state"], "INTERRUPTED")
        self.assertEqual(self.worker_json("w")["attempts"][0]["status"], "INTERRUPTED")


# ---------------------------------------------------------------------------
class IsolationAndAggregateTests(PipelineTestBase):
    def test_per_worker_logs_and_results_remain_isolated(self):  # 23
        def script(request):
            evidence = Path(request.run_root) / "run_x"
            evidence.mkdir(parents=True)
            (evidence / "stdout.txt").write_text(f"OUT-{request.provider}-{request.label}", encoding="utf-8")
            (evidence / "stderr.txt").write_text(f"ERR-{request.label}", encoding="utf-8")
            return _res(evidence=evidence)

        executor = Executor({"x": script, "y": script})
        m = self.manifest([self.worker("x", repo="a", provider="claude"), self.worker("y", repo="b", provider="codex")])
        self.runner(m, executor, max_workers=2).run()
        base = self.state_root / "night-001" / "workers"
        rx = json.loads((base / "x" / "result.json").read_text(encoding="utf-8"))
        ry = json.loads((base / "y" / "result.json").read_text(encoding="utf-8"))
        for rec, wid, prov in ((rx, "x", "claude"), (ry, "y", "codex")):
            self.assertEqual(rec["worker_id"], wid)
            self.assertEqual(rec["provider"], prov)
            self.assertTrue(rec["evidence_dir"].startswith(str(base / wid / "evidence")))
            self.assertTrue(all(str(base / wid) in a for a in rec["artifacts"]))
            self.assertEqual(len(rec["attempts"]), 1)
            self.assertTrue((base / wid / "preflight.json").exists())
        stdout_x = (Path(rx["evidence_dir"]) / "stdout.txt").read_text(encoding="utf-8")
        stdout_y = (Path(ry["evidence_dir"]) / "stdout.txt").read_text(encoding="utf-8")
        self.assertIn("claude", stdout_x)
        self.assertNotIn("codex", stdout_x)
        self.assertNotIn("claude", stdout_y)
        self.assertNotEqual(rx["evidence_dir"], ry["evidence_dir"])

    def test_aggregate_pipeline_result_is_correct(self):  # 24
        executor = Executor({
            "s1": [_res()], "p1": [_res(RS.PARTIAL, work_status="PARTIAL")],
            "b1": [_res(RS.BLOCKED, evidence=self.root, work_status="BLOCKED")],
            "f1": [_res(RS.WORK_FAILED, evidence=self.root, work_status="FAILED")],
        })
        m = self.manifest([
            self.worker("s1", repo="a", provider="claude"), self.worker("p1", repo="b", provider="codex"),
            self.worker("b1", repo="c", provider="claude"), self.worker("f1", repo="d", provider="codex"),
            self.worker("c1", repo="a", provider="claude", depends_on=["f1"]),
        ])
        result = self.runner(m, executor, max_workers=4).run()
        agg = json.loads(result.path.read_text(encoding="utf-8"))
        self.assertEqual(agg["pipeline_id"], "night-001")
        self.assertEqual((agg["workers_total"], agg["success"], agg["partial"], agg["blocked"], agg["failed"], agg["cancelled"]),
                         (5, 1, 1, 1, 1, 1))
        self.assertEqual(agg["status"], "FAILED")
        self.assertEqual(result.exit_code, rp.PIPELINE_EXIT_CODES["FAILED"])
        self.assertEqual(agg["provider_breakdown"]["claude"]["total"], 3)
        self.assertEqual(agg["provider_breakdown"]["codex"]["PARTIAL"], 1)
        self.assertIsNotNone(agg["started_at_utc"])
        self.assertIsNotNone(agg["ended_at_utc"])
        self.assertGreaterEqual(agg["duration_seconds"], 0)
        for w in agg["workers"]:
            self.assertTrue(Path(w["worker_path"]).exists())
            if w["state"] != "SUCCESS" or w["id"] == "s1":
                self.assertTrue(Path(w["result_path"]).exists(), w)

    def test_overall_status_precedence_and_exit_codes(self):
        self.assertEqual(rp.PIPELINE_EXIT_CODES["SUCCESS"], 0)
        m = self.manifest([self.worker("a", repo="a"), self.worker("b", repo="b")])
        result = self.runner(m, Executor({"a": [_res(RS.PARTIAL, work_status="PARTIAL")]})).run()
        self.assertEqual(result.status, "PARTIAL")

    def test_status_command_reports_liveness_of_running_worker(self):
        gate = threading.Event()
        started = threading.Event()
        executor = Executor(on_call=lambda w, r: started.set(), hold={"w": gate})
        m = self.manifest([self.worker("w", repo="a")])
        thread = threading.Thread(target=self.runner(m, executor).run)
        thread.start()
        self.assertTrue(started.wait(5))
        status = rp.read_pipeline_status(self.state_root, "night-001")
        gate.set()
        thread.join(10)
        entry = status["workers"][0]
        self.assertEqual((status["status"], entry["state"], entry["liveness"]), ("RUNNING", "RUNNING", "ALIVE"))

    def test_cli_validate_and_status_roundtrip(self):
        manifest_path = self.root / "m.json"
        manifest_path.write_text(json.dumps({"pipeline_id": "cli-1", "workers": [self.worker("w")]}), encoding="utf-8")
        self.assertEqual(rp.main(["validate", "--manifest", str(manifest_path)]), 0)
        self.assertEqual(rp.main(["status", "--state-root", str(self.state_root), "--pipeline-id", "nope"]), rp.EXIT_PIPELINE_REFUSED)


# ---------------------------------------------------------------------------
def _wait_until(predicate, timeout=20.0, interval=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


class _StuckProcess:
    """A supervised process whose death can never be confirmed."""
    pid = 4242
    confirmed_dead = False

    def __init__(self):
        self.evidence = {"status": "RUNNING", "identity": {"pid": 4242}, "confirmed_dead": False}
        self.terminate_calls = []

    def terminate(self, reason="X"):
        self.terminate_calls.append(reason)
        return sup.TerminationResult(None, reason, "SIGNAL_UNAVAILABLE", "FAILED", None, None, False)


class ProcessSupervisionPipelineTests(PipelineTestBase):
    SLEEP = [sys.executable, "-c", "import time; time.sleep(120)"]

    def runner(self, manifest, executor=None, **kw):
        # Recovery tests drive the pid probe explicitly; the recorded process
        # group is reported empty unless a test injects its own probe. (A dead
        # leader pid alone is deliberately not enough to resolve an attempt.)
        kw.setdefault("group_probe_fn", lambda pgid: True)
        return super().runner(manifest, executor, **kw)

    def supervised(self, request):
        """Executor double that runs a REAL supervised local process through
        the same transport the providers use."""
        outcome = providers.run_process(
            self.SLEEP, request.repo, None, 120, provider_id=request.provider, control=request.execution_control,
        )
        return _res(RS.INTERRUPTED if outcome.interrupted else RS.SUCCESS)

    def double_interrupt(self, r, ready):
        """First Ctrl+C -> DRAINING, second -> forced. Both are raised out of the
        scheduler's wait once `ready()` holds; later waits (the forced path's
        bounded wait for terminations) are real."""
        real_wait = rp.futures_wait
        state = {"n": 0}

        def patched(fs, *a, **k):
            state["n"] += 1
            if state["n"] <= 2:
                _wait_until(ready)
                raise KeyboardInterrupt
            return real_wait(fs, *a, **k)

        return mock.patch.object(rp, "futures_wait", patched)

    @staticmethod
    def provider_running(r, wid):
        control = r._controls.get(wid)
        return control is not None and control.process is not None and control.process.pid is not None \
            and control.process.evidence.get("status") == sup.STATUS_RUNNING

    def evidence(self, wid, attempt=1):
        path = self.state_root / "night-001" / "workers" / wid / "process" / f"attempt-{attempt}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_each_attempt_gets_its_own_control_and_process_evidence_path(self):  # 11, 19
        executor = Executor()
        m = self.manifest([self.worker("a", repo="a"), self.worker("b", repo="b", provider="codex")])
        result = self.runner(m, executor).run()
        self.assertEqual(result.status, "SUCCESS")
        controls = {wid: req.execution_control for wid, req in executor.calls}
        self.assertEqual(set(controls), {"a", "b"})
        self.assertIsNot(controls["a"], controls["b"])
        for wid in ("a", "b"):
            self.assertEqual((controls[wid].worker_id, controls[wid].attempt), (wid, 1))
            attempt = self.worker_json(wid)["attempts"][0]
            self.assertTrue(attempt["process_evidence_path"].endswith("attempt-1.json"))
            self.assertEqual(Path(attempt["process_evidence_path"]).parent.parent.name, wid)
            self.assertEqual(Path(attempt["process_evidence_path"]).parent.name, "process")
            self.assertTrue(attempt["process_confirmed_stopped"])

    def test_forced_shutdown_terminates_supervised_provider_and_confirms_death(self):  # 15
        m = self.manifest([self.worker("w", repo="a")])
        r = self.runner(m, Executor({"w": self.supervised}))
        with self.double_interrupt(r, lambda: self.provider_running(r, "w")):
            result = r.run()
        self.assertEqual(self.states(result)["w"], "INTERRUPTED")
        self.assertEqual(result.stop_reason, "FORCED_SHUTDOWN")
        attempt = self.worker_json("w")["attempts"][0]
        self.assertEqual(attempt["status"], "INTERRUPTED")
        self.assertIs(attempt["process_confirmed_stopped"], True)
        self.assertNotIn("process_termination_unresolved", attempt)
        self.assertTrue(attempt["process"]["confirmed_dead"])
        ev = self.evidence("w")
        self.assertTrue(ev["confirmed_dead"])
        self.assertEqual(ev["termination_reason"], "FORCED_SHUTDOWN")
        self.assertEqual(ev["identity"]["provider"], "claude")
        self.assertTrue(_wait_until(lambda: mw._pid_alive(ev["identity"]["pid"]) is False),
                        "provider process still running after forced shutdown")

    def test_forced_shutdown_terminates_claude_and_codex_workers_independently(self):  # 15, concurrency
        m = self.manifest([self.worker("a", repo="a"), self.worker("b", repo="b", provider="codex")])
        r = self.runner(m, Executor({"a": self.supervised, "b": self.supervised}), max_workers=2)
        with self.double_interrupt(r, lambda: self.provider_running(r, "a") and self.provider_running(r, "b")):
            result = r.run()
        self.assertEqual(self.states(result), {"a": "INTERRUPTED", "b": "INTERRUPTED"})
        a, b = self.evidence("a"), self.evidence("b")
        self.assertEqual((a["identity"]["provider"], b["identity"]["provider"]), ("claude", "codex"))
        self.assertNotEqual(a["identity"]["pid"], b["identity"]["pid"])
        for ev in (a, b):
            self.assertTrue(ev["confirmed_dead"])
            self.assertEqual(ev["termination_reason"], "FORCED_SHUTDOWN")

    def test_forced_shutdown_releases_write_lease_only_after_provider_confirmed_dead(self):  # lease
        m = self.manifest([self.worker("w", repo="a", mode="write", authorize_path=["docs/"])])
        r = self.runner(m, Executor({"w": self.supervised}))
        with self.double_interrupt(r, lambda: self.provider_running(r, "w")):
            r.run()
        self.assertTrue(self.evidence("w")["confirmed_dead"])
        lease = rp.DirLease(rp.worktree_lease_dir(self.repos["a"]))
        self.assertTrue(lease.try_acquire({"pid": 1}), "lease not released after confirmed termination")
        lease.release()

    def test_forced_shutdown_with_unconfirmed_death_fails_closed_and_keeps_lease(self):  # lease
        gate, stub = threading.Event(), _StuckProcess()

        def stuck(request):
            request.execution_control.attach(stub)  # a provider whose death cannot be confirmed
            gate.wait(30)
            return _res(RS.INTERRUPTED)

        m = self.manifest([self.worker("w", repo="a", mode="write", authorize_path=["docs/"])])
        r = self.runner(m, Executor({"w": stuck}), forced_termination_wait_seconds=0.2)
        self.addCleanup(lambda: [lease.release() for lease in list(r._leases.values())])
        self.addCleanup(gate.set)
        with self.double_interrupt(r, lambda: self.provider_running(r, "w")):
            result = r.run()
        self.assertEqual(self.states(result)["w"], "INTERRUPTED")
        attempt = self.worker_json("w")["attempts"][0]
        self.assertIs(attempt["process_confirmed_stopped"], False)
        self.assertIs(attempt["process_termination_unresolved"], True)
        self.assertEqual(attempt["process_termination_detail"], "PROCESS_LIVENESS_UNCONFIRMED")
        self.assertEqual(stub.terminate_calls, ["FORCED_SHUTDOWN"])
        contender = rp.DirLease(rp.worktree_lease_dir(self.repos["a"]))
        self.assertFalse(contender.try_acquire({"pid": 2}), "lease released while provider liveness unknown")

    def test_forced_shutdown_does_not_touch_workers_that_never_started_a_provider(self):
        started, gate = threading.Event(), threading.Event()
        executor = Executor(on_call=lambda w, req: started.set(), hold={"w": gate})
        m = self.manifest([self.worker("w", repo="a")])
        r = self.runner(m, executor)
        self.addCleanup(gate.set)
        with self.double_interrupt(r, started.is_set):
            result = r.run()
        self.assertEqual(self.states(result)["w"], "INTERRUPTED")
        attempt = self.worker_json("w")["attempts"][0]
        self.assertEqual(attempt["process_termination_detail"], "NO_PROCESS_STARTED_AND_LAUNCH_BLOCKED")
        self.assertTrue(executor.calls_for("w")[0].execution_control.cancelled)

    # -- recovery stays conservative ---------------------------------------

    def _crash(self, evidence, *, pid_alive):
        m = self.manifest([self.worker("w", repo="a")])
        dead = self.runner(m)
        dead._init_state()
        rt = dead.workers["w"]
        path = self.root / "process-evidence.json"
        if evidence is not None:
            path.write_text(json.dumps(evidence), encoding="utf-8")
        rt.attempts.append({
            "attempt": 1, "executed": True, "status": "RUNNING", "provider": "claude", "started_at_utc": "t",
            "process_evidence_path": str(path),
        })
        rt.owner = {"pid": 99999999, "hostname": dead.hostname, "run_id": "dead"}
        rt.provider_locked = True
        dead._force_state(rt, rp.WorkerState.RUNNING, None)
        dead._save_pipeline()
        dead._pipeline_lock.release()
        return m, path, (lambda pid: pid_alive)

    RUNNING = {"status": "RUNNING",
               "identity": {"pid": 5150, "process_group": 5150, "containment_mode": "POSIX_PROCESS_GROUP"},
               "confirmed_dead": False}

    def test_recovery_with_possibly_running_provider_is_unresolved_and_refuses_requeue(self):  # 16
        m, _, alive = self._crash(self.RUNNING, pid_alive=True)
        executor = Executor()
        result = self.runner(m, executor, pid_alive_fn=alive).run()
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.states(result)["w"], "INTERRUPTED")
        recovery = self.worker_json("w")["attempts"][0]["process_recovery"]
        self.assertEqual(recovery["resolution"], "UNRESOLVED")
        self.assertEqual(recovery["pid"], 5150)
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(m, executor, pid_alive_fn=alive, requeue_interrupted=True).run()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.worker_json("w")["state"], "INTERRUPTED")

    def test_recovery_inconclusive_liveness_is_treated_as_alive(self):  # 16
        m, _, _ = self._crash(self.RUNNING, pid_alive=None)
        self.runner(m, Executor(), pid_alive_fn=lambda pid: None).run()
        self.assertEqual(self.worker_json("w")["attempts"][0]["process_recovery"]["resolution"], "UNRESOLVED")

    def test_recovery_launch_intent_without_pid_is_unresolved_even_if_nothing_is_alive(self):  # 16
        m, _, alive = self._crash({"status": "LAUNCHING", "identity": None, "confirmed_dead": False}, pid_alive=False)
        self.runner(m, Executor(), pid_alive_fn=alive).run()
        recovery = self.worker_json("w")["attempts"][0]["process_recovery"]
        self.assertEqual((recovery["resolution"], recovery["detail"]), ("UNRESOLVED", "LAUNCH_INTENT_WITHOUT_PID"))

    def test_recovery_with_dead_provider_allows_explicit_requeue_only(self):  # 16
        m, _, alive = self._crash(self.RUNNING, pid_alive=False)
        executor = Executor()
        self.runner(m, executor, pid_alive_fn=alive).run()
        self.assertEqual(executor.calls, [])  # never auto re-executed
        self.assertEqual(self.worker_json("w")["attempts"][0]["process_recovery"]["resolution"], "RESOLVED")
        result = self.runner(m, executor, pid_alive_fn=alive, requeue_interrupted=True).run()
        self.assertEqual(self.states(result)["w"], "SUCCESS")

    def test_recovery_with_recorded_dead_process_is_resolved(self):  # 16
        done = {"status": "TERMINATED", "identity": {"pid": 5150}, "confirmed_dead": True}
        m, _, alive = self._crash(done, pid_alive=True)  # pid reuse must not matter once death was recorded
        self.runner(m, Executor(), pid_alive_fn=alive).run()
        recovery = self.worker_json("w")["attempts"][0]["process_recovery"]
        self.assertEqual((recovery["resolution"], recovery["detail"]), ("RESOLVED", "PROCESS_RECORDED_DEAD"))

    def test_operator_resolving_the_process_evidence_unblocks_requeue(self):  # 16
        m, path, alive = self._crash(self.RUNNING, pid_alive=True)
        self.runner(m, Executor(), pid_alive_fn=alive).run()
        with self.assertRaises(rp.PipelineError):
            self.runner(m, Executor(), pid_alive_fn=alive, requeue_interrupted=True).run()
        path.unlink()  # operator stopped the process and cleared the record
        result = self.runner(m, Executor(), pid_alive_fn=alive, requeue_interrupted=True).run()
        self.assertEqual(self.states(result)["w"], "SUCCESS")

    # -- FIX2: requeue must not depend on process_recovery existing ---------

    def _interrupted(self, evidence, attempts_extra=(), **attempt):
        """A dead orchestrator's INTERRUPTED worker whose attempt carries
        unresolved markers but NO process_recovery record."""
        m = self.manifest([self.worker("w", repo="a")])
        dead = self.runner(m)
        dead._init_state()
        rt = dead.workers["w"]
        path = self.root / "process-evidence.json"
        if evidence is not None:
            path.write_text(json.dumps(evidence), encoding="utf-8")
        rt.attempts.append({
            "attempt": 1, "executed": True, "status": "INTERRUPTED", "provider": "claude",
            "started_at_utc": "t", "ended_at_utc": "t", "process_evidence_path": str(path), **attempt,
        })
        rt.attempts.extend(dict(a) for a in attempts_extra)
        rt.provider_locked = True
        dead._force_state(rt, rp.WorkerState.INTERRUPTED, "FORCED_SHUTDOWN")
        dead._save_worker(rt)
        dead._save_pipeline()
        dead._pipeline_lock.release()
        return m, path

    def test_requeue_refuses_process_termination_unresolved_without_process_recovery(self):  # FIX2 1
        m, _ = self._interrupted(self.RUNNING, process_confirmed_stopped=False, process_termination_unresolved=True)
        self.assertNotIn("process_recovery", self.worker_json("w")["attempts"][0])
        executor = Executor()
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(m, executor, pid_alive_fn=lambda pid: True, requeue_interrupted=True).run()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.worker_json("w")["state"], "INTERRUPTED")
        with self.assertRaises(rp.PipelineError):
            self.runner(m, executor, pid_alive_fn=lambda pid: True, rerun=["w"]).run()

    def test_requeue_refuses_unconfirmed_stop_without_process_recovery(self):  # FIX2 1
        m, _ = self._interrupted(self.RUNNING, process_confirmed_stopped=False)
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(m, pid_alive_fn=lambda pid: True, requeue_interrupted=True).run()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")

    def test_requeue_refuses_unresolved_flag_when_no_evidence_can_prove_otherwise(self):  # FIX2 1
        m, _ = self._interrupted(
            None, process_evidence_path=None, process_confirmed_stopped=False, process_termination_unresolved=True,
        )
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(m, pid_alive_fn=lambda pid: False, requeue_interrupted=True).run()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")

    def test_requeue_looks_past_a_later_non_executed_attempt(self):  # FIX2 1
        m, _ = self._interrupted(
            self.RUNNING, attempts_extra=[{"attempt": 2, "executed": False, "status": "NOT_EXECUTED"}],
            process_confirmed_stopped=False, process_termination_unresolved=True,
        )
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(m, pid_alive_fn=lambda pid: True, requeue_interrupted=True).run()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")

    def test_requeue_reassesses_unresolved_latest_attempt_and_allows_only_a_safe_resolution(self):  # FIX2 2
        m, _ = self._interrupted(self.RUNNING, process_confirmed_stopped=False, process_termination_unresolved=True)
        probes = []
        executor = Executor()
        result = self.runner(
            m, executor, pid_alive_fn=lambda pid: False, requeue_interrupted=True,
            group_probe_fn=lambda pgid: probes.append(pgid) or True,
        ).run()
        self.assertEqual(probes, [5150])  # the evidence was actually re-assessed
        self.assertEqual(self.states(result)["w"], "SUCCESS")
        recovery = self.worker_json("w")["attempts"][0]["process_recovery"]
        self.assertEqual((recovery["resolution"], recovery["detail"]), ("RESOLVED", "PROCESS_GROUP_EMPTY"))
        self.assertEqual(len(executor.calls), 1)

    def test_requeue_accepts_a_stopped_attempt_whose_evidence_records_death(self):  # FIX2 2
        done = {"status": "TERMINATED", "identity": {"pid": 5150}, "confirmed_dead": True}
        m, _ = self._interrupted(done, process_confirmed_stopped=False)  # e.g. EXECUTOR_EXCEPTION attempt
        result = self.runner(m, pid_alive_fn=lambda pid: True, requeue_interrupted=True).run()
        self.assertEqual(self.states(result)["w"], "SUCCESS")

    # -- FIX2: recovery is containment-aware --------------------------------

    def test_recovery_dead_leader_does_not_resolve_while_the_process_group_may_hold_processes(self):  # FIX2 6
        m, _, alive = self._crash(self.RUNNING, pid_alive=False)  # leader pid gone...
        self.runner(m, Executor(), pid_alive_fn=alive, group_probe_fn=lambda pgid: False).run()  # ...group not empty
        recovery = self.worker_json("w")["attempts"][0]["process_recovery"]
        self.assertEqual(
            (recovery["resolution"], recovery["detail"]),
            ("UNRESOLVED", "PROCESS_GROUP_MAY_STILL_CONTAIN_PROCESSES"),
        )
        with self.assertRaises(rp.PipelineError) as ctx:
            self.runner(m, Executor(), pid_alive_fn=alive, group_probe_fn=lambda pgid: False,
                        requeue_interrupted=True).run()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")

    def test_recovery_inconclusive_containment_probe_is_unresolved(self):  # FIX2 7
        m, _, alive = self._crash(self.RUNNING, pid_alive=False)
        self.runner(m, Executor(), pid_alive_fn=alive, group_probe_fn=lambda pgid: None).run()
        recovery = self.worker_json("w")["attempts"][0]["process_recovery"]
        self.assertEqual((recovery["resolution"], recovery["detail"]), ("UNRESOLVED", "PROCESS_GROUP_PROBE_INCONCLUSIVE"))

    def _assert_identity_unresolved(self, identity, detail):
        m, _, alive = self._crash({"status": "RUNNING", "identity": identity, "confirmed_dead": False}, pid_alive=False)
        self.runner(m, Executor(), pid_alive_fn=alive).run()
        recovery = self.worker_json("w")["attempts"][0]["process_recovery"]
        self.assertEqual((recovery["resolution"], recovery["detail"]), ("UNRESOLVED", detail))

    def test_recovery_posix_identity_without_recorded_group_is_unresolved(self):  # FIX2 7
        self._assert_identity_unresolved(
            {"pid": 5150, "containment_mode": "POSIX_PROCESS_GROUP"}, "NO_PROCESS_GROUP_RECORDED")

    def test_recovery_degraded_containment_cannot_prove_descendants_gone(self):  # FIX2 7
        self._assert_identity_unresolved(
            {"pid": 5150, "containment_mode": "DEGRADED_PID_ONLY"}, "CONTAINMENT_CANNOT_PROVE_DESCENDANTS_GONE")

    def test_recovery_unknown_containment_is_unresolved(self):  # FIX2 7
        self._assert_identity_unresolved({"pid": 5150}, "CONTAINMENT_CANNOT_PROVE_DESCENDANTS_GONE")

    def test_recovery_never_signals_any_process(self):  # 8, 16
        m, _, alive = self._crash(self.RUNNING, pid_alive=True)
        with mock.patch("os.kill") as kill, mock.patch.object(sup.SupervisedProcess, "terminate") as terminate:
            self.runner(m, Executor(), pid_alive_fn=alive).run()
        kill.assert_not_called()
        terminate.assert_not_called()

    # -- FINAL CLOSURE 1: missing/corrupt evidence never erases known uncertainty --

    def _assert_requeue_refused(self, m, **kw):
        executor = Executor()
        for flag in ({"requeue_interrupted": True}, {"rerun": ["w"]}):
            with self.assertRaises(rp.PipelineError) as ctx:
                self.runner(m, executor, pid_alive_fn=lambda pid: False, **flag, **kw).run()
            self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")
        self.assertEqual(executor.calls, [])
        self.assertEqual(self.worker_json("w")["state"], "INTERRUPTED")

    def test_unresolved_marker_with_missing_evidence_is_unresolved_and_requeue_refused(self):  # 1, 3
        for attempt in (
            {"process_confirmed_stopped": False, "process_termination_unresolved": True},
            {"process_termination_unresolved": True},
            {"process_confirmed_stopped": False},
        ):
            with self.subTest(attempt=attempt):
                self.setUp()  # fresh repos/state per sub-case
                m, path = self._interrupted(None, **attempt)
                self.assertFalse(path.exists())
                r = self.runner(m)
                r._init_state()
                recovery = r._assess_process_evidence(r.workers["w"].attempts[0])
                r._pipeline_lock.release()
                self.assertEqual(recovery["resolution"], "UNRESOLVED")
                self.assertEqual(recovery["detail"], "UNRESOLVED_MARKER_WITH_MISSING_PROCESS_EVIDENCE")
                self._assert_requeue_refused(m)

    def test_unresolved_marker_with_corrupt_evidence_is_unresolved_and_requeue_refused(self):  # 2, 3
        for raw, detail in (("{not json", "PROCESS_EVIDENCE_UNREADABLE:JSONDecodeError"),
                            ("[]", "PROCESS_EVIDENCE_MALFORMED"), ("", "PROCESS_EVIDENCE_UNREADABLE:JSONDecodeError")):
            with self.subTest(raw=raw):
                self.setUp()
                m, path = self._interrupted(None, process_confirmed_stopped=False, process_termination_unresolved=True)
                path.write_text(raw, encoding="utf-8")
                r = self.runner(m)
                r._init_state()
                recovery = r._assess_process_evidence(r.workers["w"].attempts[0])
                r._pipeline_lock.release()
                self.assertEqual((recovery["resolution"], recovery["detail"]), ("UNRESOLVED", detail))
                self._assert_requeue_refused(m)

    def test_unmarked_attempt_without_evidence_keeps_the_operator_path(self):  # regression guard
        m, path = self._interrupted(None)  # no explicit unresolved marker: nothing known to protect
        self.assertFalse(path.exists())
        result = self.runner(m, pid_alive_fn=lambda pid: False, requeue_interrupted=True).run()
        self.assertEqual(self.states(result)["w"], "SUCCESS")

    def test_marker_is_only_lifted_by_evidence_that_records_death(self):  # 1
        m, path = self._interrupted(None, process_confirmed_stopped=False)
        self._assert_requeue_refused(m)
        path.write_text(json.dumps({"status": "TERMINATED", "identity": {"pid": 1}, "confirmed_dead": True}),
                        encoding="utf-8")
        result = self.runner(m, pid_alive_fn=lambda pid: True, requeue_interrupted=True).run()
        self.assertEqual(self.states(result)["w"], "SUCCESS")

    # -- FINAL CLOSURE 2: unresolved containment never becomes SUCCESS -------------

    @staticmethod
    def _unresolved_success(request):
        request.execution_control.attach(_StuckProcess())  # provider finished "successfully"; death unproven
        return _res(RS.SUCCESS, work_status="SUCCESS")

    def _run_unresolved(self, workers, script=None, **kw):
        executor = Executor(script or {"w": self._unresolved_success})
        r = self.runner(self.manifest(workers), executor, **kw)
        self.addCleanup(lambda: [lease.release() for lease in list(r._unresolved_leases.values())])
        return r, executor, r.run()

    def test_unresolved_containment_cannot_transition_a_worker_to_success(self):  # 4, 5
        r, _, result = self._run_unresolved([self.worker("w", repo="a")])
        self.assertEqual(self.states(result)["w"], "BLOCKED")
        self.assertNotEqual(result.status, "SUCCESS")
        w = self.worker_json("w")
        self.assertEqual(w["state_reason"], "PROVIDER_PROCESS_UNRESOLVED")
        attempt = w["attempts"][0]
        self.assertIs(attempt["process_confirmed_stopped"], False)
        self.assertIs(attempt["process_termination_unresolved"], True)
        self.assertEqual(attempt["retry_decision"], "NO_RETRY:PROVIDER_PROCESS_UNRESOLVED")
        # The provider's own result is preserved, never discarded.
        self.assertEqual(attempt["provider_result_superseded"]["runner_state"], "SUCCESS")
        self.assertEqual(attempt["work_status"], "SUCCESS")
        payload = json.loads((self.state_root / "night-001" / "workers" / "w" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual((payload["outcome"], payload["code"]), ("BLOCKED", "PROVIDER_PROCESS_UNRESOLVED"))

    def test_unresolved_containment_after_executor_exception_is_blocked_not_failed(self):  # 5
        def boom(request):
            request.execution_control.attach(_StuckProcess())
            raise RuntimeError("provider transport exploded")

        _, _, result = self._run_unresolved([self.worker("w", repo="a")], {"w": boom})
        self.assertEqual(self.states(result)["w"], "BLOCKED")
        self.assertIn("provider transport exploded", self.worker_json("w")["attempts"][0]["error"])

    def test_dependency_policy_success_does_not_release_downstream_of_unresolved_worker(self):  # 6
        for policy in ("success", "success_or_partial", "completed"):
            with self.subTest(policy=policy):
                self.setUp()
                _, executor, result = self._run_unresolved(
                    [self.worker("w", repo="a"),
                     self.worker("down", repo="b", depends_on=["w"], dependency_policy=policy)],
                    {"w": self._unresolved_success},
                )
                states = self.states(result)
                self.assertEqual(states["w"], "BLOCKED")
                self.assertEqual(states["down"], "CANCELLED")
                self.assertEqual(executor.calls_for("down"), [], "dependent started after an unresolved provider")
                self.assertIn("PROVIDER_PROCESS_UNRESOLVED", self.worker_json("down")["state_reason"])

    def test_write_lease_stays_held_under_unresolved_completion(self):  # 7
        r, _, result = self._run_unresolved([self.worker("w", repo="a", mode="write", authorize_path=["docs/"])])
        self.assertEqual(self.states(result)["w"], "BLOCKED")
        self.assertIn("w", r._unresolved_leases)
        contender = rp.DirLease(rp.worktree_lease_dir(self.repos["a"]))
        self.assertFalse(contender.try_acquire({"pid": 2}), "WRITE lease released although the provider is unresolved")

    def test_unresolved_blocked_worker_is_not_requeueable_without_evidence_of_death(self):  # 1, 3
        _, executor, _ = self._run_unresolved([self.worker("w", repo="a")])
        state = self.worker_json("w")
        self.assertEqual(state["state"], "BLOCKED")
        fresh = Executor()
        with self.assertRaises(rp.PipelineError) as ctx:  # BLOCKED workers are only re-run explicitly
            self.runner(self.manifest([self.worker("w", repo="a")]), fresh,
                        pid_alive_fn=lambda pid: False, rerun=["w"]).run()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")
        self.assertEqual(fresh.calls, [])
        self.assertEqual(self.worker_json("w")["state"], "BLOCKED")

    def test_confirmed_stop_still_yields_success(self):  # unchanged happy path
        result = self.runner(self.manifest([self.worker("w", repo="a")]), Executor()).run()
        self.assertEqual(self.states(result)["w"], "SUCCESS")


class EvidenceFinalizationIntegrityTests(PipelineTestBase):
    """R21-A regression coverage: a provider process that exits 0 with a
    SUCCESS work verdict must never be reported as a work failure merely
    because a secondary evidence artifact (e.g. git_before.txt) could not be
    persisted during evidence finalization."""

    def _evidence_dir_missing_git_before(self, stdout_text):
        evidence = self.root / "evidence_incomplete"
        evidence.mkdir()
        (evidence / "stdout.txt").write_text(stdout_text, encoding="utf-8")
        (evidence / "result.json").write_text(json.dumps({"state": "SUCCESS"}), encoding="utf-8")
        # git_before.txt is deliberately absent: reproduces the observed defect.
        return evidence

    def test_missing_git_before_after_successful_work_is_partial_not_failed(self):
        stdout_text = "FORMAL_CLOSURE=CLOSED\nVERDICT=SUCCESS\n"
        evidence = self._evidence_dir_missing_git_before(stdout_text)
        scripted = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run_missing_git_before", evidence_dir=evidence,
            error_message=None, work_status="SUCCESS",
            evidence_complete=False,
            evidence_error="git_before.txt: FileNotFoundError: reproduced missing evidence artifact",
        )
        executor = Executor({"w": lambda request: scripted})
        outcome = self.runner(self.manifest([self.worker("w", repo="a")]), executor).run()

        # Finalization did not throw, and the worker was not marked FAILED.
        self.assertEqual(self.states(outcome)["w"], "PARTIAL")

        worker = self.worker_json("w")
        self.assertEqual(worker["state_reason"], "EVIDENCE_FINALIZATION_FAILED")
        attempt = worker["attempts"][0]
        # The provider's own SUCCESS work verdict is preserved, never rewritten
        # into a generic work failure.
        self.assertEqual(attempt["work_status"], "SUCCESS")
        self.assertEqual(attempt["runner_state"], "SUCCESS")
        self.assertFalse(attempt["evidence_complete"])
        self.assertIn("git_before.txt", attempt["evidence_error"])

        # stdout/result remain recoverable from evidence despite the missing
        # secondary artifact.
        self.assertFalse((evidence / "git_before.txt").exists())
        self.assertIn("VERDICT=SUCCESS", (evidence / "stdout.txt").read_text(encoding="utf-8"))

    def test_complete_evidence_success_path_is_unchanged(self):
        scripted = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run_ok", evidence_dir=self.root,
            error_message=None, work_status="SUCCESS",
        )
        executor = Executor({"w": lambda request: scripted})
        outcome = self.runner(self.manifest([self.worker("w", repo="a")]), executor).run()
        self.assertEqual(self.states(outcome)["w"], "SUCCESS")
        worker = self.worker_json("w")
        self.assertIsNone(worker["state_reason"])
        self.assertTrue(worker["attempts"][0]["evidence_complete"])

    def test_real_execute_work_order_survives_git_before_write_failure(self):
        """End-to-end reproduction at the claude_runner layer: the provider
        process exits 0 with a SUCCESS verdict, but persisting git_before.txt
        fails; execute_work_order must not raise, and must report the work
        as SUCCESS with evidence_complete=False."""
        import pathlib

        repo = self.repos["a"]
        work_order = self.root / "verdict_wo.txt"
        work_order.write_text("Do the work.\nReport VERDICT=SUCCESS or VERDICT=FAILED.\n", encoding="utf-8")

        orig_locate = providers.ClaudeProvider.locate_executable
        orig_invoke = runner.invoke_claude
        orig_write_text = pathlib.Path.write_text

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            payload = json.dumps({"result": "FORMAL_CLOSURE=CLOSED\nVERDICT=SUCCESS\n", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.2,
            )

        def flaky_write_text(self_path, data, *a, **k):
            if self_path.name == "git_before.txt":
                raise FileNotFoundError(f"reproduced missing evidence dir for {self_path}")
            return orig_write_text(self_path, data, *a, **k)

        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"
        runner.invoke_claude = fake_invoke
        pathlib.Path.write_text = flaky_write_text
        try:
            request = runner.WorkOrderRequest(repo=str(repo), work_order=str(work_order))
            result = runner.execute_work_order(request)
        finally:
            pathlib.Path.write_text = orig_write_text
            runner.invoke_claude = orig_invoke
            providers.ClaudeProvider.locate_executable = orig_locate

        self.assertEqual(result.state, RS.SUCCESS)
        self.assertEqual(result.work_status, "SUCCESS")
        self.assertFalse(result.evidence_complete)
        self.assertIn("git_before.txt", result.evidence_error)
        self.assertFalse((result.evidence_dir / "git_before.txt").exists())
        self.assertTrue((result.evidence_dir / "stdout.txt").exists())
        self.assertIn("VERDICT=SUCCESS", (result.evidence_dir / "stdout.txt").read_text(encoding="utf-8"))


class FactoryLedgerPipelineIntegrationTests(PipelineTestBase):
    """R21-C: the factory ledger is opt-in (None by default) and, when
    supplied, records worker/module lifecycle events a real pipeline run
    produces."""

    def _ledger(self):
        return flog.FactoryLedger(self.root / "factory")

    def test_worker_lifecycle_and_module_state_are_recorded(self):
        ledger = self._ledger()
        manifest = self.manifest([
            self.worker("w1", repo="a", metadata={"module": "knowledge", "module_version": "v1", "role": "implementer"}),
        ])
        outcome = self.runner(manifest, factory_ledger=ledger).run()
        self.assertEqual(self.states(outcome)["w1"], "SUCCESS")

        events = ledger.events(pipeline_id="night-001", worker_id="w1")
        types = [e["event_type"] for e in events]
        self.assertIn("WORKER_STARTED", types)
        self.assertIn("WORKER_FINISHED", types)
        self.assertIn("MODULE_STATE_CHANGED", types)

        started = next(e for e in events if e["event_type"] == "WORKER_STARTED")
        self.assertEqual(started["provider"], "claude")
        self.assertEqual(started["module"], "knowledge")
        self.assertEqual(started["module_version"], "v1")
        self.assertEqual(started["role"], "implementer")
        self.assertEqual(started["worktree"], str(self.repos["a"]))
        self.assertIsNotNone(started["base_commit"])

        finished = next(e for e in events if e["event_type"] == "WORKER_FINISHED")
        self.assertEqual(finished["state"], "SUCCESS")

        modules = ledger.modules()
        self.assertEqual(modules["knowledge@v1"]["state"], "SUCCESS")
        self.assertEqual(modules["knowledge@v1"]["provider"], "claude")

    def test_worker_without_module_metadata_has_no_module_entry(self):
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a")])
        self.runner(manifest, factory_ledger=ledger).run()
        events = ledger.events(pipeline_id="night-001")
        self.assertTrue(events)
        self.assertEqual(ledger.modules(), {})

    def test_failed_worker_records_failed_module_state(self):
        # Evidence present => the provider actually ran (CLAUDE_ERROR with no
        # evidence instead means it never started, e.g. missing CLI on PATH).
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a", metadata={"module": "billing"})])
        executor = Executor({"w1": [_res(RS.CLAUDE_ERROR, evidence=self.root, error="boom")]})
        self.runner(manifest, executor, factory_ledger=ledger).run()
        self.assertEqual(ledger.modules()["billing"]["state"], "FAILED")

    def test_blocked_precondition_records_blocked_module_state(self):
        # A genuine precondition/availability block (provider never ran, no
        # evidence produced) must stay BLOCKED, never collapse into FAILED.
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a", metadata={"module": "billing"})])
        executor = Executor({"w1": [_res(RS.PROVIDER_UNAVAILABLE, error="provider offline")]})
        self.runner(manifest, executor, factory_ledger=ledger).run()
        self.assertEqual(ledger.modules()["billing"]["state"], "BLOCKED")

    def test_partial_worker_module_state_is_not_collapsed_to_failed(self):
        # PARTIAL must remain distinguishable from both SUCCESS and FAILED.
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a", metadata={"module": "billing"})])
        executor = Executor({"w1": [_res(RS.PARTIAL, evidence=self.root, work_status="PARTIAL")]})
        self.runner(manifest, executor, factory_ledger=ledger).run()
        self.assertEqual(ledger.modules()["billing"]["state"], "PARTIAL")

    def test_factory_history_state_matches_materialized_module_state(self):
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a", metadata={"module": "knowledge"})])
        self.runner(manifest, factory_ledger=ledger).run()
        history = rp.factory_history_report(self.root / "factory", module="knowledge")
        module_changes = [e for e in history if e["event_type"] == "MODULE_STATE_CHANGED"]
        self.assertTrue(module_changes)
        self.assertEqual(module_changes[-1]["state"], ledger.modules()["knowledge"]["state"])

    def test_module_materialization_is_deterministic_on_replay(self):
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a", metadata={"module": "billing"})])
        executor = Executor({"w1": [_res(RS.CLAUDE_ERROR, evidence=self.root, error="boom")]})
        self.runner(manifest, executor, factory_ledger=ledger).run()

        events, _skipped = flog.read_events(self.root / "factory")
        first = flog.materialize_modules(events)
        second = flog.materialize_modules(list(events))
        self.assertEqual(first, second)
        self.assertEqual(first["billing"]["state"], "FAILED")

        # A freshly constructed ledger over the same on-disk events replays
        # to the exact same module state as the in-memory one that wrote them.
        reloaded = flog.FactoryLedger(self.root / "factory").modules()
        self.assertEqual(reloaded, ledger.modules())

    def test_ledger_disabled_by_default_writes_nothing(self):
        factory_root = self.root / "factory"
        manifest = self.manifest([self.worker("w1", repo="a")])
        self.runner(manifest).run()
        self.assertFalse(factory_root.exists())

    def test_two_providers_two_modules_tracked_independently(self):
        ledger = self._ledger()
        manifest = self.manifest([
            self.worker("w1", repo="a", provider="claude", metadata={"module": "knowledge"}),
            self.worker("w2", repo="b", provider="codex", metadata={"module": "billing"}),
        ])
        outcome = self.runner(manifest, factory_ledger=ledger).run()
        self.assertEqual(self.states(outcome), {"w1": "SUCCESS", "w2": "SUCCESS"})
        modules = ledger.modules()
        self.assertEqual(modules["knowledge"]["provider"], "claude")
        self.assertEqual(modules["billing"]["provider"], "codex")

    def test_factory_status_report_combines_live_state_and_ledger_modules(self):
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a", metadata={"module": "knowledge"})])
        self.runner(manifest, factory_ledger=ledger).run()
        report = rp.factory_status_report(self.state_root, self.root / "factory")
        self.assertEqual(report["counts"]["TERMINAL"], 1)
        self.assertEqual(report["workers"][0]["state"], "SUCCESS")
        self.assertEqual(report["modules"]["knowledge"]["state"], "SUCCESS")

    def test_factory_history_report_filters_by_module(self):
        ledger = self._ledger()
        manifest = self.manifest([
            self.worker("w1", repo="a", metadata={"module": "knowledge"}),
            self.worker("w2", repo="b", metadata={"module": "billing"}),
        ])
        self.runner(manifest, factory_ledger=ledger).run()
        history = rp.factory_history_report(self.root / "factory", module="knowledge")
        self.assertTrue(history)
        self.assertTrue(all(e["module"] == "knowledge" for e in history))

    def test_factory_status_and_history_cli_commands(self):
        ledger = self._ledger()
        manifest = self.manifest([self.worker("w1", repo="a", metadata={"module": "knowledge"})])
        self.runner(manifest, factory_ledger=ledger).run()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rp.main([
                "--repo", str(self.root), "factory-status",
                "--state-root", str(self.state_root), "--factory-root", str(self.root / "factory"),
            ])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["modules"]["knowledge"]["state"], "SUCCESS")

        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            code = rp.main([
                "--repo", str(self.root), "factory-history",
                "--factory-root", str(self.root / "factory"), "--module", "knowledge",
            ])
        self.assertEqual(code, 0)
        events = json.loads(buf2.getvalue())
        self.assertTrue(all(e["module"] == "knowledge" for e in events))


class GovernedCheckpointPipelineTests(PipelineTestBase):
    """R21-E: an OPTIONAL `checkpoint_policy=ON_SUCCESS` turns a completed
    write-mode attempt's own work product into exactly one deterministic WIP
    commit before the worker is reported SUCCESS, so a dependent CLOSER
    worker (`dependency_policy=success`, the pre-existing DAG mechanism,
    unchanged) never starts against a dirty or uncommitted worktree."""

    def _write_product(self, repo, rel_path, *, branch=None, base_head=None, content="hello\n", extra=None):
        branch = branch or _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        base_head = base_head or _git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / rel_path).write_text(content, encoding="utf-8")
        record = {
            "schema_version": runner.WORK_PRODUCT_SCHEMA_VERSION,
            "worktree": str(repo), "branch": branch, "base_head": base_head,
            "process_confirmed_stopped": True, "authorized_changed_paths": [f"?? {rel_path}"],
            "runner_owned_paths": [],
        }
        if extra:
            record.update(extra)
        return record

    def _scripted_success(self, repo, rel_path, **kw) -> runner.WorkOrderResult:
        evidence = self.root / f"evidence_{uuid.uuid4().hex[:8]}"
        evidence.mkdir()
        record = self._write_product(repo, rel_path, **kw)
        (evidence / "work_product.json").write_text(json.dumps(record), encoding="utf-8")
        return runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id=f"run_{uuid.uuid4().hex[:6]}", evidence_dir=evidence,
            work_status="SUCCESS", work_product_present=True,
        )

    # -- manifest validation -------------------------------------------------

    def test_checkpoint_policy_none_by_default(self):
        spec = self.manifest([self.worker("A", repo="a")]).workers[0]
        self.assertIsNone(spec.checkpoint_policy)

    def test_checkpoint_policy_requires_write_mode(self):
        with self.assertRaises(rp.ManifestError) as ctx:
            self.manifest([self.worker("A", repo="a", mode="read-only", checkpoint_policy="ON_SUCCESS")])
        self.assertIn("CHECKPOINT_POLICY_REQUIRES_WRITE_MODE", {e["code"] for e in ctx.exception.errors})

    def test_invalid_checkpoint_policy_value_rejected(self):
        with self.assertRaises(rp.ManifestError) as ctx:
            self.manifest([
                self.worker("A", repo="a", mode="write", authorize_path=["out.txt"], checkpoint_policy="ALWAYS"),
            ])
        self.assertIn("INVALID_CHECKPOINT_POLICY", {e["code"] for e in ctx.exception.errors})

    # -- backward compatibility ----------------------------------------------

    def test_no_checkpoint_policy_preserves_prior_behavior(self):
        repo = self.repos["a"]
        base_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        executor = Executor({"A": lambda request: self._scripted_success(repo, "out.txt")})
        manifest = self.manifest([self.worker("A", repo="a", mode="write", authorize_path=["out.txt"])])
        outcome = self.runner(manifest, executor).run()
        self.assertEqual(self.states(outcome)["A"], "SUCCESS")
        # No commit was ever attempted: HEAD unchanged, tree left dirty exactly
        # as unmanaged write-mode workers have always left it.
        self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout.strip(), base_head)
        self.assertNotEqual(_git(repo, "status", "--porcelain").stdout.strip(), "")
        self.assertNotIn("checkpoint", self.worker_json("A")["attempts"][0])

    # -- builder -> closer handoff --------------------------------------------

    def test_builder_checkpoint_gates_closer_start(self):
        repo = self.repos["a"]
        seen = {}

        def closer(request):
            seen["head_at_start"] = _git(repo, "rev-parse", "HEAD").stdout.strip()
            seen["status_at_start"] = _git(repo, "status", "--porcelain").stdout
            return _res()

        manifest = self.manifest([
            self.worker(
                "A", repo="a", mode="write", authorize_path=["out.txt"], checkpoint_policy="ON_SUCCESS",
                metadata={"role": "BUILDER"},
            ),
            self.worker("B", repo="a", provider="codex", depends_on=["A"], metadata={"role": "CLOSER"}),
        ])
        executor = Executor({"A": lambda request: self._scripted_success(repo, "out.txt"), "B": closer})
        outcome = self.runner(manifest, executor).run()
        self.assertEqual(self.states(outcome), {"A": "SUCCESS", "B": "SUCCESS"})

        head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(seen["head_at_start"], head)
        self.assertEqual(seen["status_at_start"], "")  # clean worktree when B started

        checkpoint = self.worker_json("A")["attempts"][0]["checkpoint"]
        self.assertEqual(checkpoint["decision"], "CREATED")
        self.assertEqual(checkpoint["commit_hash"], head)
        self.assertIn("runner-checkpoint(wip):", _git(repo, "log", "-1", "--pretty=%B").stdout)
        self.assertEqual(self.states(outcome)["B"], "SUCCESS")

        # No merge, no push, no PR: exactly one linear commit ahead of base,
        # on the SAME branch, against a repo with no remote at all.
        self.assertEqual(_git(repo, "remote").stdout.strip(), "")
        self.assertEqual(_git(repo, "rev-list", "--count", head).stdout.strip(), "2")
        summary = next(w for w in outcome.summary["workers"] if w["id"] == "A")
        self.assertEqual(summary["checkpoint_commit"], head)

    def test_checkpoint_failure_blocks_closer_and_commits_nothing(self):
        repo = self.repos["a"]
        base_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        def builder(request):
            record = self._write_product(repo, "out.txt")
            # An extra dirty path the recorded work product knows nothing
            # about - independent, defense-in-depth re-verification at
            # checkpoint time must refuse this regardless of the provider's
            # own reported state.
            (repo / "unexpected.txt").write_text("surprise\n", encoding="utf-8")
            evidence = self.root / "evidence_unauthorized"
            evidence.mkdir()
            (evidence / "work_product.json").write_text(json.dumps(record), encoding="utf-8")
            return runner.WorkOrderResult(
                state=RS.SUCCESS, exit_code=0, run_id="run_unauth", evidence_dir=evidence,
                work_status="SUCCESS", work_product_present=True,
            )

        closer_calls = []
        manifest = self.manifest([
            self.worker("A", repo="a", mode="write", authorize_path=["out.txt"], checkpoint_policy="ON_SUCCESS"),
            self.worker("B", repo="a", depends_on=["A"]),
        ])
        executor = Executor({"A": builder, "B": lambda request: closer_calls.append(1) or _res()})
        outcome = self.runner(manifest, executor).run()

        self.assertEqual(self.states(outcome)["A"], "BLOCKED")
        self.assertEqual(self.states(outcome)["B"], "CANCELLED")
        self.assertFalse(closer_calls, "closer must never start after a failed checkpoint")

        worker_a = self.worker_json("A")
        self.assertEqual(worker_a["state_reason"], "CHECKPOINT_FAILED")
        checkpoint = worker_a["attempts"][0]["checkpoint"]
        self.assertEqual(checkpoint["decision"], "REFUSED_UNKNOWN_DIRTY_PATH")
        self.assertIsNone(checkpoint["commit_hash"])
        self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout.strip(), base_head)
        self.assertEqual(_git(repo, "diff", "--cached", "--name-only").stdout.strip(), "")

    def test_diff_check_failure_blocks_closer(self):
        repo = self.repos["a"]
        base_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        conflict_markers = "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n"
        executor = Executor({
            "A": lambda request: self._scripted_success(repo, "out.txt", content=conflict_markers),
            "B": lambda request: _res(),
        })
        manifest = self.manifest([
            self.worker("A", repo="a", mode="write", authorize_path=["out.txt"], checkpoint_policy="ON_SUCCESS"),
            self.worker("B", repo="a", depends_on=["A"]),
        ])
        outcome = self.runner(manifest, executor).run()
        self.assertEqual(self.states(outcome)["A"], "BLOCKED")
        self.assertEqual(self.states(outcome)["B"], "CANCELLED")
        self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout.strip(), base_head)
        checkpoint = self.worker_json("A")["attempts"][0]["checkpoint"]
        self.assertEqual(checkpoint["decision"], "REFUSED_DIFF_CHECK_FAILED")

    def test_branch_changed_blocks_checkpoint(self):
        repo = self.repos["a"]
        base_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        def builder(request):
            result = self._scripted_success(repo, "out.txt")
            _git(repo, "checkout", "-q", "-b", "feature/moved-during-run")
            return result

        manifest = self.manifest([
            self.worker("A", repo="a", mode="write", authorize_path=["out.txt"], checkpoint_policy="ON_SUCCESS"),
        ])
        outcome = self.runner(manifest, Executor({"A": builder})).run()
        self.assertEqual(self.states(outcome)["A"], "BLOCKED")
        self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout.strip(), base_head)
        checkpoint = self.worker_json("A")["attempts"][0]["checkpoint"]
        self.assertEqual(checkpoint["decision"], "REFUSED_BRANCH_CHANGED")

    def test_partial_result_never_triggers_checkpoint(self):
        repo = self.repos["a"]
        base_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        def builder(request):
            evidence = self.root / "evidence_partial"
            evidence.mkdir()
            record = self._write_product(repo, "out.txt")
            (evidence / "work_product.json").write_text(json.dumps(record), encoding="utf-8")
            return runner.WorkOrderResult(
                state=RS.PARTIAL, exit_code=runner.EXIT_CODES[RS.PARTIAL], run_id="run_partial",
                evidence_dir=evidence, work_status="PARTIAL", work_product_present=True,
            )

        manifest = self.manifest([
            self.worker("A", repo="a", mode="write", authorize_path=["out.txt"], checkpoint_policy="ON_SUCCESS"),
            self.worker("B", repo="a", depends_on=["A"]),
        ])
        executor = Executor({"A": builder, "B": lambda request: _res()})
        outcome = self.runner(manifest, executor).run()
        self.assertEqual(self.states(outcome)["A"], "PARTIAL")
        self.assertEqual(self.states(outcome)["B"], "CANCELLED")
        self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout.strip(), base_head)
        self.assertNotIn("checkpoint", self.worker_json("A")["attempts"][0])

    def test_checkpoint_created_event_recorded_in_factory_ledger(self):
        repo = self.repos["a"]
        ledger = flog.FactoryLedger(self.root / "factory")
        executor = Executor({"A": lambda request: self._scripted_success(repo, "out.txt")})
        manifest = self.manifest([
            self.worker(
                "A", repo="a", mode="write", authorize_path=["out.txt"], checkpoint_policy="ON_SUCCESS",
                metadata={"module": "demo"},
            ),
        ])
        self.runner(manifest, executor, factory_ledger=ledger).run()
        events = ledger.events(pipeline_id="night-001", worker_id="A", event_type="CHECKPOINT_CREATED")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["result_commit"], _git(repo, "rev-parse", "HEAD").stdout.strip())
        self.assertEqual(events[0]["module"], "demo")


if __name__ == "__main__":
    unittest.main()
