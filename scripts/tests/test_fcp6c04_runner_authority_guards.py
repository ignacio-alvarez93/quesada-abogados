"""FCP-6C-04: regression guards proving that FCP-6A-01 failure intelligence
(`runner_failure_intelligence`) and FCP-6B-01 recovery advisory
(`runner_recovery_advisory`) never change a Runner / Director / claude_runner
authority boundary.

Method: every scenario drives the Runner's OWN native decision methods
(`PipelineRunner._classify_and_apply`, `_refresh`, `_start_ready`,
`_recover_running`, `_apply_operator_requests`, `_finalize`) against
synthetic `WorkOrderResult`s inside a private tmpdir. `PipelineRunner.run()`,
the thread pool, real providers, real processes, Git and the network are
never reached: the executor and every launch path are forbidden mocks. The
evidence the Runner persisted is then read and passed SEPARATELY through
`assess_pipeline` / `advise_pipeline`, and the native verdict is shown to be
identical before and after (same durable bytes, same runtime record, same
next native decision).
"""

import ast
import builtins
import copy
import dataclasses
import json
import os
import socket
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_director as fd
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_providers as providers
from scripts.ai import runner_recovery_advisory as ra

RS = runner.RunState
AI_DIR = Path(rp.__file__).resolve().parent
TEST_PATH = Path(__file__).resolve()
NOW = datetime(2026, 10, 28, 22, 0, tzinfo=timezone.utc)
AUTHORITY_FLAGS = (
    "certified", "authorizes_action", "auto_retry_allowed", "execution_allowed", "resume_allowed",
    "merging_allowed",
)


class _FakeProvider(providers.Provider):
    def __init__(self, provider_id, available=True):
        self.provider_id = provider_id
        self.display_name = provider_id
        self._available = available

    def probe(self):
        if not self._available:
            return providers.ProviderProbe(self.provider_id, False, reason="not installed")
        return providers.ProviderProbe(self.provider_id, True, executable="x", version="1")

    def capabilities(self, policy):
        return frozenset({
            providers.Capability.READ_FILES, providers.Capability.SEARCH_FILES,
            providers.Capability.EDIT_FILES, providers.Capability.WRITE_FILES,
        })

    def build_invocation(self, **kw):  # pragma: no cover - never executed
        raise AssertionError("fake provider never builds invocations")

    def normalize_result(self, outcome, *, verdict_required):  # pragma: no cover - never executed
        raise AssertionError("fake provider never normalizes")

    def is_transient_failure(self, runner_state, error_text):
        return runner_state == "CLAUDE_ERROR" and "rate limit" in (error_text or "").lower()


def _res(state=RS.SUCCESS, *, error=None, work_status=None, condition=None) -> runner.WorkOrderResult:
    return runner.WorkOrderResult(
        state=state, exit_code=runner.EXIT_CODES.get(state, 1), run_id="run_fcp6c04",
        evidence_dir=None, error_message=error, work_status=work_status, provider_condition=condition,
    )


def _condition(kind: str, excerpt: str = "provider said no") -> dict:
    return {"condition": kind, "reason": "SYNTHETIC", "http_status": None, "reset_hint": None,
            "message_excerpt": excerpt}


class _Bench:
    """One synthetic pipeline under a private tmpdir. Native Runner methods
    run for real; everything that could execute or probe is a forbidden mock."""

    def __init__(self, root: Path, specs: list, pipeline_id: str = "fcp6c04-night"):
        self.root = root
        self.now = NOW
        self.state_root = root / "state"
        self.pipeline_id = pipeline_id
        self.providers = {"claude": _FakeProvider("claude"), "codex": _FakeProvider("codex")}
        self.executor = mock.Mock(side_effect=AssertionError("executor must never be reached"))
        self.pid_alive = mock.Mock(side_effect=AssertionError("no live process may be probed"))
        manifest = rp.Manifest(
            pipeline_id=pipeline_id, workers=specs, sha256="0" * 64,
            raw={"pipeline_id": pipeline_id, "workers": [s.to_dict() for s in specs]},
        )
        self.runner = rp.PipelineRunner(
            manifest, self.state_root, executor=self.executor, provider_resolver=self._resolve,
            clock=lambda: self.now, self_worktree=root / "orchestrator", lease_root=root / "leases",
            heartbeat_interval_seconds=None, pid_alive_fn=self.pid_alive,
            group_probe_fn=mock.Mock(side_effect=AssertionError("no process group may be probed")),
        )
        self.runner.workers = {s.id: rp.WorkerRuntime(spec=s, order=i) for i, s in enumerate(specs)}
        self.runner._initialized = True

    def _resolve(self, pid):
        if pid not in self.providers:
            raise providers.UnknownProviderError(pid, sorted(self.providers))
        return self.providers[pid]

    def rt(self, wid) -> rp.WorkerRuntime:
        return self.runner.workers[wid]

    def attempt(self, wid, *, confirmed=True) -> tuple:
        """What `_launch` + `_finish` leave behind, minus the process itself."""
        rt = self.rt(wid)
        rt.state = rp.WorkerState.RUNNING.value
        attempt = {
            "attempt": len(rt.attempts) + 1, "provider": rt.active_provider, "status": "RUNNING",
            "executed": True, "budget_class": rp.BUDGET_WORK, "retry_decision": None,
            "process_confirmed_stopped": confirmed,
        }
        rt.attempts.append(attempt)
        rt.provider_locked = True
        return rt, attempt

    def finish(self, wid, result, *, confirmed=True, ran=True) -> rp.WorkerRuntime:
        """`_finish` minus the future/lease: classify natively, then persist
        exactly as `_finish` does. `ran=False` keeps `evidence_dir` None
        (the Runner's own proof that the provider never ran)."""
        rt, attempt = self.attempt(wid, confirmed=confirmed)
        if ran:
            evidence = self.root / "evidence" / self.pipeline_id / wid / f"attempt-{attempt['attempt']}"
            evidence.mkdir(parents=True)
            result = dataclasses.replace(result, evidence_dir=evidence)
        self.runner._classify_and_apply(rt, attempt, "RESULT", result, self.now)
        rt.owner = None
        self.runner._save_worker(rt)
        self.runner._save_pipeline()
        return rt

    def close(self) -> None:
        self.runner._finalize(forced=False)

    def files(self) -> dict:
        base = self.state_root / self.pipeline_id
        return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}

    def evidence(self) -> tuple:
        base = self.state_root / self.pipeline_id
        pipeline_result = json.loads((base / "pipeline_result.json").read_text(encoding="utf-8"))
        results = {}
        for entry in pipeline_result["workers"]:
            path = base / "workers" / entry["id"] / "result.json"
            if path.exists():
                results[entry["id"]] = json.loads(path.read_text(encoding="utf-8"))
        return pipeline_result, results

    def runtime_snapshot(self) -> dict:
        return {wid: copy.deepcopy(rt.to_dict()) for wid, rt in self.runner.workers.items()}

    def analyse(self) -> tuple:
        """6A then 6B over the persisted evidence, proving nothing native
        moved: durable bytes and in-memory runtime records are identical."""
        before_files, before_rt = self.files(), self.runtime_snapshot()
        pipeline_result, results = self.evidence()
        diagnostic = fi.assess_pipeline(pipeline_result, results)
        advisory = ra.advise_pipeline(diagnostic)
        if self.files() != before_files:
            raise AssertionError("6A/6B changed Runner durable state")
        if self.runtime_snapshot() != before_rt:
            raise AssertionError("6A/6B changed Runner runtime state")
        return diagnostic, advisory


class _GuardBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.wo = self.root / "wo.md"
        self.wo.write_text("Synthetic FCP-6C-04 work order.\n", encoding="utf-8")
        (self.root / "orchestrator").mkdir()

    def spec(self, wid, *, worktree="wt-a", mode=providers.MODE_READ_ONLY, **kw) -> rp.WorkerSpec:
        wt = self.root / worktree
        wt.mkdir(parents=True, exist_ok=True)
        return rp.WorkerSpec(id=wid, worktree=str(wt), work_order=str(self.wo), mode=mode, worktree_top=str(wt), **kw)

    def bench(self, *specs, pipeline_id="fcp6c04-night") -> _Bench:
        return _Bench(self.root, list(specs), pipeline_id=pipeline_id)

    def worker_advisory(self, advisory, wid) -> "ra.WorkerRecoveryAdvisory":
        return next(w for w in advisory.workers if w.worker_id == wid)

    def assert_zero_authority(self, *advisories):
        for advisory in advisories:
            for flag in AUTHORITY_FLAGS:
                self.assertIs(getattr(advisory, flag), False, flag)
                self.assertIs(advisory.to_dict()[flag], False, flag)

    def parse(self, worker: dict):
        """Native manifest validator with git_toplevel stubbed to a tmp dir
        (no Git process); the Work Order file is real and in the tmpdir."""
        data = {"pipeline_id": "fcp6c04-parse", "workers": [{
            "id": "w1", "worktree": str(self.root / "wt-a"), "work_order": str(self.wo), **worker,
        }]}
        with mock.patch.object(rp, "git_toplevel", return_value=self.root / "wt-a"):
            return rp.parse_manifest(data, self.root, self_worktree=self.root / "orchestrator",
                                     registered_providers=["claude", "codex"])

    def manifest_codes(self, worker: dict) -> set:
        with self.assertRaises(rp.ManifestError) as ctx:
            self.parse(worker)
        return {e["code"] for e in ctx.exception.errors}


# ---------------------------------------------------------------------------
# (i) retry permissions and max_attempts
# ---------------------------------------------------------------------------
class RetryAuthorityTests(_GuardBase):
    def test_transient_retry_wait_is_runner_owned_and_unchanged_by_analysis(self):
        b = self.bench(self.spec("A", max_attempts=2, backoff_seconds=30.0))
        rt = b.finish("A", _res(RS.CLAUDE_ERROR, error="rate limit"))
        self.assertEqual(rt.state, "RETRY_WAIT")
        self.assertTrue(rt.attempts[-1]["retry_decision"].startswith("RETRY:TRANSIENT:CLAUDE_ERROR"))
        due = rt.retry_not_before_utc
        _, advisory = b.analyse()
        worker = self.worker_advisory(advisory, "A")
        self.assertEqual((worker.category, worker.responsibility, worker.observation),
                         ("EXISTING_RETRY_WAIT", "RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT"))
        self.assert_zero_authority(advisory, worker)
        # The Runner's own schedule, budget and spec are exactly as it left them.
        self.assertEqual((rt.retry_not_before_utc, rt.attempts_used, rt.spec.max_attempts), (due, 1, 2))
        self.assertNotIn(due, ra.canonical_json(advisory))
        b.executor.assert_not_called()

    def test_max_attempts_exhaustion_is_decided_natively_after_analysis(self):
        b = self.bench(self.spec("A", max_attempts=2, backoff_seconds=30.0))
        b.finish("A", _res(RS.CLAUDE_ERROR, error="rate limit"))
        b.analyse()
        b.now += timedelta(seconds=31)
        b.runner._refresh(b.now)
        self.assertEqual(b.rt("A").state, "READY")
        rt = b.finish("A", _res(RS.CLAUDE_ERROR, error="rate limit"))
        self.assertEqual((rt.state, rt.state_reason), ("FAILED", "MAX_ATTEMPTS_EXHAUSTED"))
        self.assertEqual(rt.attempts[-1]["retry_decision"], "NO_RETRY:MAX_ATTEMPTS_EXHAUSTED")
        b.close()
        _, advisory = b.analyse()
        worker = self.worker_advisory(advisory, "A")
        self.assertEqual(worker.category, "NATIVE_FAILED")
        self.assertNotEqual(worker.responsibility, "RUNNER_NATIVE")
        self.assert_zero_authority(advisory, worker)
        # Exhausted stays exhausted: no transition out of FAILED exists.
        self.assertEqual(rp._ALLOWED_TRANSITIONS[rp.WorkerState.FAILED], set())
        with self.assertRaises(rp.PipelineError):
            b.runner._transition(rt, rp.WorkerState.READY, "ADVISED")

    def test_non_transient_failure_never_retries_despite_spare_budget(self):
        b = self.bench(self.spec("A", max_attempts=5))
        rt = b.finish("A", _res(RS.CLAUDE_ERROR, error="segfault"))
        self.assertEqual(rt.state, "FAILED")
        self.assertEqual(rt.attempts[-1]["retry_decision"], "NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR")
        b.close()
        _, advisory = b.analyse()
        worker = self.worker_advisory(advisory, "A")
        self.assertEqual(worker.category, "NATIVE_FAILED")
        self.assertNotIn(worker.observation, ("OBSERVE_EXISTING_WAIT", "OBSERVE_EXISTING_RUN"))
        b.runner._refresh(b.now + timedelta(days=1))
        self.assertEqual((rt.state, rt.attempts_used, rt.retry_not_before_utc), ("FAILED", 1, None))

    def test_manifest_max_attempts_bounds_are_native_and_advisory_has_no_budget_input(self):
        for bad in (0, 21, True, "3"):
            self.assertIn("INVALID_MAX_ATTEMPTS", self.manifest_codes({"max_attempts": bad}), bad)
        self.assertEqual(self.parse({"max_attempts": 20}).workers[0].max_attempts, 20)
        for cls in (ra.WorkerRecoveryAdvisory, ra.PipelineRecoveryAdvisory, fi.WorkerDiagnostic):
            names = {f.name for f in dataclasses.fields(cls)}
            self.assertFalse(names & {"max_attempts", "backoff_seconds", "retry_not_before_utc"}, cls)


# ---------------------------------------------------------------------------
# (ii) structural resume_from and dirty-tree refusals
# ---------------------------------------------------------------------------
class ResumeAndDirtyTreeTests(_GuardBase):
    def test_resume_from_structural_refusals_stay_native(self):
        self.assertIn("RESUME_FROM_REQUIRES_WRITE_MODE",
                      self.manifest_codes({"resume_from": str(self.root / "wp.json")}))
        self.assertIn("INVALID_RESUME_FROM", self.manifest_codes({"mode": "write", "resume_from": "  "}))
        self.assertIn("INVALID_RESUME_FROM", self.manifest_codes({"mode": "write", "resume_from": 7}))

    def test_dirty_tree_refusal_blocks_and_never_derives_resume_from(self):
        b = self.bench(self.spec("A", mode=providers.MODE_WRITE, max_attempts=3))
        rt = b.finish("A", _res(RS.DIRTY_TREE_REFUSED, error="dirty"))
        self.assertEqual((rt.state, rt.state_reason), ("BLOCKED", "DIRTY_TREE_REFUSED"))
        self.assertEqual(rt.attempts[-1]["retry_decision"], "NO_RETRY:DIRTY_TREE_REFUSED")
        b.close()
        diagnostic, advisory = b.analyse()
        self.assertIn("SAFETY_REFUSAL", diagnostic.reason_codes)
        worker = self.worker_advisory(advisory, "A")
        self.assertEqual((worker.category, worker.responsibility), ("SAFETY_REFUSED", "HUMAN_REVIEW"))
        self.assertIs(worker.resume_allowed, False)
        self.assertIsNone(rt.pending_resume_from)
        self.assertIsNone(rt.spec.resume_from)
        self.assertNotIn("resume_from", ra.canonical_json(advisory))

    def test_resume_refused_is_safety_refusal_not_a_resume_licence(self):
        b = self.bench(self.spec("A", mode=providers.MODE_WRITE, resume_from=str(self.root / "wp.json")))
        rt = b.finish("A", _res(RS.RESUME_REFUSED, error="refused"))
        self.assertEqual((rt.state, rt.state_reason), ("BLOCKED", "RESUME_REFUSED"))
        b.close()
        _, advisory = b.analyse()
        self.assertEqual(advisory.category, "SAFETY_REFUSED")
        self.assert_zero_authority(advisory, *advisory.workers)
        self.assertEqual(rt.spec.resume_from, str(self.root / "wp.json"))
        self.assertNotIn(str(self.root), ra.canonical_json(advisory))

    def test_claude_runner_dirty_tree_and_resume_verdicts_are_pure_and_unchanged(self):
        snapshot = runner.GitSnapshot(branch="feature/x", head="a" * 40, porcelain_status=" M app/x.py\n",
                                      raw_text="", captured_at="2026-10-28T22:00:00+00:00")
        record = self.root / "work_product.json"
        record.write_text(json.dumps({
            "schema_version": runner.WORK_PRODUCT_SCHEMA_VERSION, "authorized_changed_paths": [" M app/x.py"],
            "worktree": str(self.root / "wt-a"), "branch": "feature/x", "base_head": "a" * 40,
            "process_confirmed_stopped": False,
        }), encoding="utf-8")

        def verdicts():
            return (runner.evaluate_dirty_tree(snapshot).decision,
                    runner.evaluate_resume(str(record), self.root / "wt-a", snapshot, ["app/"]).decision)

        before = verdicts()
        self.assertEqual(before, ("REFUSED_DIRTY", "REFUSED_PROCESS_NOT_CONFIRMED_STOPPED"))
        b = self.bench(self.spec("A", mode=providers.MODE_WRITE))
        b.finish("A", _res(RS.DIRTY_TREE_REFUSED))
        b.close()
        b.analyse()
        self.assertEqual(verdicts(), before)


# ---------------------------------------------------------------------------
# (iii) worktree safety and provider control
# ---------------------------------------------------------------------------
class WorktreeAndProviderControlTests(_GuardBase):
    def test_self_modification_is_refused_natively_without_launch(self):
        b = self.bench(self.spec("A", worktree="orchestrator/nested", mode=providers.MODE_WRITE))
        b.rt("A").state = "READY"
        with mock.patch.object(b.runner, "_launch", side_effect=AssertionError("no launch")):
            b.runner._start_ready(b.now)
        self.assertEqual((b.rt("A").state, b.rt("A").state_reason), ("BLOCKED", "SELF_MODIFICATION_REFUSED"))
        b.close()
        _, advisory = b.analyse()
        self.assertEqual(advisory.category, "SAFETY_REFUSED")
        self.assertTrue(rp.is_unsafe_self_target(Path(b.rt("A").spec.worktree_top), b.root / "orchestrator"))
        b.executor.assert_not_called()

    def test_state_root_inside_target_worktree_is_still_refused_after_analysis(self):
        spec = self.spec("A", worktree="wt-a")
        inner = _Bench(self.root, [spec])
        inner.runner.state_root = self.root / "wt-a" / "state"
        inner.runner.dir = inner.runner.state_root / inner.pipeline_id
        outer = self.bench(self.spec("A"))
        outer.finish("A", _res(RS.CLAUDE_ERROR, error="boom"))
        outer.close()
        outer.analyse()
        with self.assertRaises(rp.PipelineError) as ctx:
            inner.runner._check_state_root()
        self.assertEqual(ctx.exception.code, "STATE_ROOT_INSIDE_TARGET_WORKTREE")

    def test_same_worktree_write_exclusion_holds_while_advisory_observes_run(self):
        b = self.bench(self.spec("A", mode=providers.MODE_WRITE), self.spec("B", mode=providers.MODE_WRITE))
        b.rt("A").state = "RUNNING"
        b.rt("B").state = "READY"
        b.runner._save_pipeline()
        _, advisory = b.analyse()
        self.assertEqual(self.worker_advisory(advisory, "A").category, "EXISTING_RUN_IN_PROGRESS")
        self.assert_zero_authority(advisory, *advisory.workers)
        self.assertTrue(b.runner._same_worktree_conflict(b.rt("B")))
        with mock.patch.object(b.runner, "_launch", side_effect=AssertionError("no launch")):
            b.runner._start_ready(b.now)
        self.assertEqual(b.rt("B").state, "READY")

    def test_provider_lock_forbids_fallback_after_execution_and_advisory_names_no_provider(self):
        b = self.bench(self.spec("A", fallback_providers=["codex"], max_attempts=3))
        b.finish("A", _res(RS.CLAUDE_ERROR, error="rate limit"))
        b.now += timedelta(seconds=1)
        b.runner._refresh(b.now)
        rt = b.finish("A", _res(RS.PROVIDER_UNAVAILABLE, error="gone"), ran=False)
        self.assertEqual((rt.state, rt.active_provider, rt.fallbacks_used), ("BLOCKED", "claude", []))
        self.assertEqual(rt.attempts[-1]["retry_decision"], "NO_RETRY:PROVIDER_UNAVAILABLE")
        b.close()
        _, advisory = b.analyse()
        text = ra.canonical_json(advisory)
        self.assertNotIn("codex", text)
        self.assertNotIn("claude", text)
        self.assertEqual(rt.active_provider, "claude")

    def test_unexecuted_fallback_remains_the_runner_manifest_choice(self):
        b = self.bench(self.spec("A", fallback_providers=["codex"]))
        rt = b.finish("A", _res(RS.PROVIDER_UNAVAILABLE, error="gone"), ran=False)
        self.assertEqual((rt.state, rt.active_provider), ("READY", "codex"))
        self.assertEqual(rt.attempts[-1]["retry_decision"], "FALLBACK:codex")
        _, advisory = b.analyse()
        self.assertEqual(self.worker_advisory(advisory, "A").category, "EXISTING_RUN_IN_PROGRESS")
        self.assertNotIn("codex", ra.canonical_json(advisory))


# ---------------------------------------------------------------------------
# (iv) dependents of a failed worker
# ---------------------------------------------------------------------------
class DependentTests(_GuardBase):
    def test_dependent_of_failed_worker_is_cancelled_and_stays_cancelled(self):
        b = self.bench(self.spec("A"), self.spec("B", worktree="wt-b", depends_on=["A"]))
        b.finish("A", _res(RS.CLAUDE_ERROR, error="boom"))
        b.runner._refresh(b.now)
        self.assertEqual((b.rt("B").state, b.rt("B").state_reason), ("CANCELLED", "DEPENDENCY_UNSATISFIED:A=FAILED"))
        b.close()
        _, advisory = b.analyse()
        self.assertEqual(self.worker_advisory(advisory, "B").category, "DEPENDENCY_CANCELLED")
        self.assertEqual(self.worker_advisory(advisory, "B").responsibility, "HUMAN_REVIEW")
        self.assertEqual(advisory.category, "NATIVE_FAILED")
        b.runner._refresh(b.now + timedelta(days=1))
        self.assertEqual(b.rt("B").state, "CANCELLED")
        self.assertEqual(b.rt("B").attempts, [])

    def test_unresolved_upstream_never_releases_dependents_under_any_policy(self):
        b = self.bench(self.spec("A"), self.spec("B", worktree="wt-b", depends_on=["A"], dependency_policy="completed"))
        b.finish("A", _res(RS.SUCCESS, work_status="SUCCESS"), confirmed=False)
        self.assertEqual(b.rt("A").state_reason, "PROVIDER_PROCESS_UNRESOLVED")
        b.runner._refresh(b.now)
        self.assertEqual(b.rt("B").state, "CANCELLED")
        self.assertIn("PROVIDER_PROCESS_UNRESOLVED", b.rt("B").state_reason)
        b.close()
        _, advisory = b.analyse()
        self.assertEqual(self.worker_advisory(advisory, "A").category, "PROCESS_UNRESOLVED")
        self.assertEqual(b.runner._dependency_verdict(b.rt("B"))[0], "UNSATISFIABLE")

    def test_auth_blocked_upstream_keeps_dependent_waiting(self):
        b = self.bench(self.spec("A"), self.spec("B", worktree="wt-b", depends_on=["A"]))
        b.finish("A", _res(RS.CLAUDE_ERROR, condition=_condition("PROVIDER_AUTH_BLOCKED")))
        b.runner._refresh(b.now)
        self.assertEqual(b.rt("B").state, "WAITING_DEPENDENCY")
        b.close()
        self.assertEqual(b.runner._status, "INCOMPLETE")
        _, advisory = b.analyse()
        self.assertEqual(self.worker_advisory(advisory, "B").category, "EXISTING_RUN_IN_PROGRESS")
        b.runner._refresh(b.now + timedelta(days=2))
        self.assertEqual(b.rt("B").state, "WAITING_DEPENDENCY")

    def test_dependent_requeue_is_operator_only(self):
        b = self.bench(self.spec("A"), self.spec("B", worktree="wt-b", depends_on=["A"]))
        b.finish("A", _res(RS.CLAUDE_ERROR, error="boom"))
        b.runner._refresh(b.now)
        b.close()
        with mock.patch.object(rp.PipelineRunner, "_requeue", side_effect=AssertionError("no requeue")), \
                mock.patch.object(rp.PipelineRunner, "_requeue_cancelled_dependents",
                                  side_effect=AssertionError("no dependent requeue")):
            b.analyse()
            b.runner._apply_operator_requests()  # no operator request -> nothing moves
        self.assertEqual((b.rt("A").state, b.rt("B").state), ("FAILED", "CANCELLED"))


# ---------------------------------------------------------------------------
# (v) blocked quota and credentials
# ---------------------------------------------------------------------------
class QuotaAndCredentialTests(_GuardBase):
    def test_quota_wait_schedule_and_budget_belong_to_runner(self):
        b = self.bench(self.spec("A", max_attempts=1))
        rt = b.finish("A", _res(RS.CLAUDE_ERROR, condition=_condition("PROVIDER_QUOTA_EXHAUSTED")))
        self.assertEqual(rt.state, "WAITING_PROVIDER_QUOTA")
        self.assertEqual((rt.attempts_used, rt.availability_attempts, rt.provider_locked), (0, 1, True))
        eligible = rt.provider_wait["next_eligible_utc"]
        self.assertEqual(eligible, rp._iso(NOW + timedelta(seconds=rp.QUOTA_PROBE_BASE_SECONDS)))
        _, advisory = b.analyse()
        worker = self.worker_advisory(advisory, "A")
        self.assertEqual((worker.category, worker.observation),
                         ("EXISTING_PROVIDER_QUOTA_WAIT", "OBSERVE_EXISTING_WAIT"))
        self.assertNotIn(eligible, ra.canonical_json(advisory))
        b.runner._refresh(b.now + timedelta(seconds=10))
        self.assertEqual(rt.state, "WAITING_PROVIDER_QUOTA")
        self.assertEqual(rt.provider_wait["next_eligible_utc"], eligible)

    def test_quota_hold_blocks_same_provider_only(self):
        b = self.bench(self.spec("A"), self.spec("B", worktree="wt-b"), self.spec("C", worktree="wt-c", provider="codex"))
        b.finish("A", _res(RS.CLAUDE_ERROR, condition=_condition("PROVIDER_QUOTA_EXHAUSTED")))
        b.rt("B").state = b.rt("C").state = "READY"
        b.runner._save_pipeline()
        b.analyse()
        launched = []
        with mock.patch.object(b.runner, "_launch", side_effect=lambda rt, lease, now: launched.append(rt.spec.id)):
            b.runner._start_ready(b.now)
        self.assertEqual(launched, ["C"])
        self.assertTrue(b.runner._provider_start_held("claude", b.now))
        self.assertFalse(b.runner._provider_start_held("codex", b.now))

    def test_auth_block_is_operator_only_never_fallback_and_never_echoes_credentials(self):
        secret = "sk-ant-SYNTHETIC0000000000credential"
        b = self.bench(self.spec("A", fallback_providers=["codex"], max_attempts=5))
        rt = b.finish("A", _res(RS.CLAUDE_ERROR, condition=_condition("PROVIDER_AUTH_BLOCKED", f"bad key {secret}")))
        self.assertEqual((rt.state, rt.active_provider, rt.fallbacks_used), ("BLOCKED_PROVIDER_AUTH", "claude", []))
        self.assertEqual(rt.attempts[-1]["retry_decision"], "NO_RETRY:PROVIDER_AUTH_BLOCKED")
        self.assertEqual(rp._ALLOWED_TRANSITIONS[rp.WorkerState.BLOCKED_PROVIDER_AUTH], {rp.WorkerState.CANCELLED})
        _, advisory = b.analyse()
        worker = self.worker_advisory(advisory, "A")
        self.assertEqual((worker.category, worker.responsibility, worker.observation),
                         ("PROVIDER_AUTH_BLOCKED", "HUMAN_REVIEW", "REVIEW_PROVIDER_CREDENTIALS"))
        text = ra.canonical_json(advisory) + fi.canonical_json(fi.assess_pipeline(*b.evidence()))
        self.assertNotIn("sk-ant", text)
        self.assertNotIn("bad key", text)
        b.runner._refresh(b.now + timedelta(days=3))
        self.assertEqual(rt.state, "BLOCKED_PROVIDER_AUTH")
        self.assertTrue(b.runner._provider_start_held("claude", b.now))


# ---------------------------------------------------------------------------
# (vi) process ownership and confirmed acceptance
# ---------------------------------------------------------------------------
class OwnershipAndAcceptanceTests(_GuardBase):
    def test_unconfirmed_process_outranks_provider_success(self):
        b = self.bench(self.spec("A"))
        rt = b.finish("A", _res(RS.SUCCESS, work_status="SUCCESS"), confirmed=False)
        self.assertEqual((rt.state, rt.state_reason), ("BLOCKED", "PROVIDER_PROCESS_UNRESOLVED"))
        b.close()
        _, advisory = b.analyse()
        self.assertEqual(advisory.category, "PROCESS_UNRESOLVED")
        self.assertNotEqual(advisory.category, "HISTORICAL_SUCCESS")
        self.assertEqual(b.runner._status, "BLOCKED")

    def test_next_attempt_never_starts_before_previous_process_confirmed_stopped(self):
        b = self.bench(self.spec("A"))
        b.rt("A").attempts.append({"attempt": 1, "executed": True, "process_confirmed_stopped": False})
        b.rt("A").state = "READY"
        b.runner._save_pipeline()
        b.analyse()
        with mock.patch.object(b.runner, "_launch", side_effect=AssertionError("no launch")):
            b.runner._start_ready(b.now)
        self.assertEqual(b.rt("A").state, "READY")

    def test_dead_orchestrator_worker_becomes_interrupted_and_foreign_host_is_refused(self):
        b = self.bench(self.spec("A"))
        rt = b.rt("A")
        rt.state = "RUNNING"
        rt.owner = {"hostname": b.runner.hostname, "pid": 1}
        rt.attempts.append({"attempt": 1, "executed": True, "status": "RUNNING"})
        b.runner._recover_running()
        self.assertEqual((rt.state, rt.state_reason), ("INTERRUPTED", "ORCHESTRATOR_DIED_WHILE_RUNNING"))
        b.runner._save_pipeline()
        _, advisory = b.analyse()
        self.assertEqual(advisory.category, "INTERRUPTED")
        b.runner._apply_operator_requests()  # no explicit operator re-queue
        self.assertEqual(rt.state, "INTERRUPTED")
        foreign = self.bench(self.spec("F", worktree="wt-f"), pipeline_id="fcp6c04-foreign")
        foreign.rt("F").state = "RUNNING"
        foreign.rt("F").owner = {"hostname": "another-host.invalid", "pid": 1}
        with self.assertRaises(rp.PipelineError) as ctx:
            foreign.runner._recover_running()
        self.assertEqual(ctx.exception.code, "FOREIGN_HOST_RUNNING_WORKER")

    def test_operator_rerun_still_refused_while_process_unresolved(self):
        b = self.bench(self.spec("A"))
        rt = b.finish("A", _res(RS.SUCCESS, work_status="SUCCESS"), confirmed=False)
        b.close()
        _, advisory = b.analyse()
        self.assertEqual(advisory.category, "PROCESS_UNRESOLVED")
        b.runner.rerun = ["A"]
        with self.assertRaises(rp.PipelineError) as ctx:
            b.runner._apply_operator_requests()
        self.assertEqual(ctx.exception.code, "PROVIDER_PROCESS_UNRESOLVED")
        self.assertEqual(rt.state, "BLOCKED")

    def test_runner_acceptance_alone_decides_success(self):
        commands = ["python -m unittest synthetic"]
        verdict = _res(RS.VERDICT_INVALID, work_status=providers.WorkStatus.INVALID_VERDICT.value)
        outcomes = {}
        for decision, wid in (("FAILED", "F"), ("PASSED", "P")):
            b = self.bench(self.spec(wid, completion_policy=runner.COMPLETION_POLICY_RUNNER_ACCEPTANCE,
                                     acceptance_commands=commands), pipeline_id=f"fcp6c04-acc-{wid.lower()}")
            with mock.patch.object(b.runner, "_apply_acceptance",
                                   return_value={"decision": decision, "reason": "synthetic"}):
                rt = b.finish(wid, verdict)
            b.close()
            _, advisory = b.analyse()
            outcomes[decision] = (rt.state, rt.attempts[-1]["work_status_source"], advisory)
        failed, passed = outcomes["FAILED"], outcomes["PASSED"]
        self.assertEqual(failed[:2], ("FAILED", runner.WORK_STATUS_SOURCE_PROVIDER))
        self.assertEqual((failed[2].category, failed[2].responsibility), ("ACCEPTANCE_FAILED", "CORRECT_WORK"))
        self.assertEqual(passed[:2], ("SUCCESS", runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE))
        self.assertEqual(passed[2].category, "HISTORICAL_SUCCESS")
        self.assert_zero_authority(failed[2], passed[2])

    def test_analysis_never_upgrades_or_downgrades_native_success(self):
        b = self.bench(self.spec("A"))
        b.finish("A", _res(RS.SUCCESS, work_status="SUCCESS"))
        b.close()
        _, advisory = b.analyse()
        self.assertEqual((advisory.category, advisory.diagnostic_status), ("HISTORICAL_SUCCESS", "SUCCESS"))
        self.assertIs(advisory.certified, False)
        pipeline_result, results = b.evidence()
        tampered = copy.deepcopy(results)
        tampered["A"]["attempts"][-1].pop("process_confirmed_stopped")
        weak = ra.advise_pipeline(fi.assess_pipeline(pipeline_result, tampered))
        self.assertNotEqual(weak.category, "HISTORICAL_SUCCESS")
        # Runner's own aggregate and exit code are untouched by either reading.
        self.assertEqual(b.evidence()[0]["status"], "SUCCESS")
        self.assertEqual(rp.PIPELINE_EXIT_CODES[b.runner._status], 0)


# ---------------------------------------------------------------------------
# (vii) the advisory has no executable effect
# ---------------------------------------------------------------------------
class NoExecutableEffectTests(_GuardBase):
    def _scenarios(self) -> list:
        evidence = []
        cases = (
            ("fcp6c04-x-fail", _res(RS.CLAUDE_ERROR, error="boom"), True),
            ("fcp6c04-x-quota", _res(RS.CLAUDE_ERROR, condition=_condition("PROVIDER_QUOTA_EXHAUSTED")), True),
            ("fcp6c04-x-auth", _res(RS.CLAUDE_ERROR, condition=_condition("PROVIDER_AUTH_BLOCKED")), True),
            ("fcp6c04-x-dirty", _res(RS.DIRTY_TREE_REFUSED), True),
            ("fcp6c04-x-unres", _res(RS.SUCCESS, work_status="SUCCESS"), False),
            ("fcp6c04-x-ok", _res(RS.SUCCESS, work_status="SUCCESS"), True),
        )
        for pid, result, confirmed in cases:
            b = self.bench(self.spec("A"), pipeline_id=pid)
            b.finish("A", result, confirmed=confirmed)
            b.close()
            evidence.append((b, b.files(), b.evidence()))
        return evidence

    def test_analysis_runs_with_every_execution_path_forbidden(self):
        scenarios = self._scenarios()
        forbid = mock.Mock(side_effect=AssertionError("forbidden side effect"))
        patches = [
            mock.patch.object(subprocess, "run", forbid), mock.patch.object(subprocess, "Popen", forbid),
            mock.patch.object(os, "system", forbid), mock.patch.object(socket, "socket", forbid),
            mock.patch.object(builtins, "open", forbid),
            mock.patch.object(Path, "write_text", forbid), mock.patch.object(Path, "write_bytes", forbid),
            mock.patch.object(Path, "mkdir", forbid), mock.patch.object(Path, "unlink", forbid),
            mock.patch.object(runner, "execute_work_order", forbid),
            mock.patch.object(runner, "create_checkpoint", forbid),
            mock.patch.object(runner, "evaluate_resume", forbid),
        ]
        patches += [mock.patch.object(rp.PipelineRunner, name, forbid) for name in (
            "run", "_launch", "_start_ready", "_requeue", "_requeue_cancelled_dependents", "_transition",
            "_force_state", "_save_worker", "_save_pipeline", "_apply_operator_requests",
        )]
        patches += [mock.patch.object(fd.FabricDirectorService, name, forbid) for name in (
            "submit", "_submit", "recover", "run", "submit_and_run", "run_blueprint",
        )]
        for p in patches:
            p.start()
        try:
            advisories = [ra.advise_pipeline(fi.assess_pipeline(*ev)) for _, _, ev in scenarios]
        finally:
            for p in reversed(patches):
                p.stop()
        forbid.assert_not_called()
        self.assertEqual(len({a.category for a in advisories}), len(advisories))
        for (b, files, _), advisory in zip(scenarios, advisories):
            self.assertEqual(b.files(), files)
            self.assert_zero_authority(advisory, *advisory.workers)
            b.executor.assert_not_called()

    def test_no_native_authority_imports_or_consumes_6a_or_6b(self):
        guarded = {"runner_failure_intelligence", "runner_recovery_advisory"}
        consumers = {}
        for path in sorted(AI_DIR.glob("*.py")):
            if path.stem in guarded:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {a.name.rsplit(".", 1)[-1] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                     for a in n.names}
            names |= {n.module.rsplit(".", 1)[-1] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            if names & guarded:
                consumers[path.name] = sorted(names & guarded)
        approved_observational_consumers = {
            "fabric_recovery_director_view.py": {
                "runner_failure_intelligence", "runner_recovery_advisory",
            },
            "fabric_recovery_report_cli.py": {
                "runner_failure_intelligence", "runner_recovery_advisory",
            },
        }
        self.assertEqual(
            {name: set(imports) for name, imports in consumers.items()},
            approved_observational_consumers,
            "only two approved read-only adapters may consume 6A/6B; native authorities must not",
        )

    def test_advisory_vocabulary_cannot_confirm_a_director_recovery(self):
        observations = {obs for _, obs in ra.CATEGORY_RULES.values()}
        vocabulary = observations | set(ra.CATEGORY_RULES) | set(ra.RESPONSIBILITIES)
        self.assertNotIn("RESUME_WORK_PRODUCT", vocabulary)
        self.assertFalse(vocabulary & fd._RECOVERY_ELIGIBLE_DECISION_CODES)
        with mock.patch.object(rp, "default_self_worktree", return_value=self.root / "orchestrator"):
            service = fd.FabricDirectorService(state_root=self.root / "state", factory_root=self.root / "factory",
                                               director_root=self.root / "director", registered_providers=["claude"])
        with mock.patch.object(fd.FabricDirectorService, "_submit", side_effect=AssertionError("no submit")):
            for action in sorted(observations):
                with self.assertRaises(fd.DirectorError) as ctx:
                    service.recover(fd.DirectorRecoverySpec(prior_run_id="fdb-none", recovery_work_order_text="x",
                                                            action=action))
                self.assertEqual(ctx.exception.code, "RECOVERY_ACTION_NOT_CONFIRMED")
        self.assertFalse((self.root / "director").exists())

    def test_director_decision_and_recover_eligibility_unchanged_by_analysis(self):
        with mock.patch.object(rp, "default_self_worktree", return_value=self.root / "orchestrator"):
            service = fd.FabricDirectorService(state_root=self.root / "state", factory_root=self.root / "factory",
                                               director_root=self.root / "director", registered_providers=["claude"])
        expected = {}
        for run_id, result in (
            ("fdb-fcp6c04-fail", _res(RS.CLAUDE_ERROR, error="boom")),
            ("fdb-fcp6c04-quota", _res(RS.CLAUDE_ERROR, condition=_condition("PROVIDER_QUOTA_EXHAUSTED"))),
        ):
            b = self.bench(self.spec("w1"), pipeline_id=run_id)
            b.finish("w1", result)
            b.close()
            before = service.decision(run_id)
            _, advisory = b.analyse()
            self.assertEqual(service.decision(run_id), before)
            self.assert_zero_authority(advisory)
            with mock.patch.object(fd.FabricDirectorService, "_submit", side_effect=AssertionError("no submit")):
                with self.assertRaises(fd.DirectorError) as ctx:
                    service.recover(fd.DirectorRecoverySpec(prior_run_id=run_id, recovery_work_order_text="resume",
                                                            action="RESUME_WORK_PRODUCT"))
            expected[run_id] = (before.decision_code in fd._RECOVERY_ELIGIBLE_DECISION_CODES, ctx.exception.code)
        # Eligible failure still needs Runner's own work product; a quota wait is never eligible.
        self.assertEqual(expected["fdb-fcp6c04-fail"], (True, "NO_WORK_PRODUCT"))
        self.assertEqual(expected["fdb-fcp6c04-quota"], (False, "RECOVERY_NOT_ELIGIBLE"))
        self.assertFalse((self.root / "director").exists())

    def test_this_suite_skips_nothing_and_runs_no_live_pipeline(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for banned in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(banned, attrs | names)
        calls = {(n.func.value.attr if isinstance(n.func.value, ast.Attribute) else getattr(n.func.value, "id", None),
                  n.func.attr)
                 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn(("runner", "run"), calls)
        self.assertNotIn(("runner", "execute_work_order"), calls)


if __name__ == "__main__":
    unittest.main()
