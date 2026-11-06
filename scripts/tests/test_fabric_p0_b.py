"""FABRIC-V1-P0 WO-P0-B: Work Order integrity / DAG causality (A02-F1, F2, F3).

Adversarial tests. Every hostile file lives in a synthetic temporary
fixture; no real provider binary and no network is ever used."""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_providers as providers

KNOWN = ["claude", "codex"]
RS = runner.RunState
_PY = sys.executable.replace("\\", "/")
_PASS_CMD = f"{_PY} -c exit(0)"
_FAIL_CMD = f"{_PY} -c exit(1)"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "p0b-tests@example.invalid")
    _git(repo, "config", "user.name", "P0B Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _res(state=RS.SUCCESS, *, work_status=None) -> runner.WorkOrderResult:
    return runner.WorkOrderResult(
        state=state, exit_code=runner.EXIT_CODES.get(state, 1), run_id=f"run_{uuid.uuid4().hex[:6]}",
        evidence_dir=None, error_message=None, work_status=work_status,
    )


class _FakeProvider(providers.Provider):
    def __init__(self, provider_id):
        self.provider_id = provider_id
        self.display_name = provider_id

    def probe(self):
        return providers.ProviderProbe(self.provider_id, True, executable="x", version="1")

    def capabilities(self, policy):
        return frozenset({
            providers.Capability.READ_FILES, providers.Capability.SEARCH_FILES,
            providers.Capability.EDIT_FILES, providers.Capability.WRITE_FILES,
        })

    def build_invocation(self, **kw):  # pragma: no cover - never executed
        raise AssertionError("fake provider never builds invocations")

    def normalize_result(self, outcome, *, verdict_required):  # pragma: no cover
        raise AssertionError("fake provider never normalizes")

    def is_transient_failure(self, runner_state, error_text):
        return False


class _Executor:
    """Scripted executor keyed by the request's provenance worker_id."""

    def __init__(self, script):
        self.script = script
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, request):
        with self._lock:
            self.calls.append(request.worker_id)
        entry = self.script.get(request.worker_id)
        return entry(request) if callable(entry) else (entry or _res(work_status="SUCCESS"))


class _PipelineFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.stable = _make_repo(self.root, "stable")
        self.repos = {n: _make_repo(self.root, n) for n in ("a", "b")}
        self.state_root = self.root / "state"
        (self.root / "wo").mkdir()
        self.wos = {}
        for name in ("a", "b"):
            self.wos[name] = self.root / "wo" / f"{name}.md"
            # Exact LF bytes: `write_text` would emit CRLF on Windows and make
            # the newline-only rewrite below a byte-identical no-op.
            self.wos[name].write_bytes(f"Work Order {name}.\n".encode("utf-8"))

    def worker(self, wid, repo, wo, **extra):
        data = {"id": wid, "worktree": str(self.repos[repo]), "work_order": str(wo)}
        data.update(extra)
        return data

    def manifest(self, workers, pipeline_id="p0b-001"):
        return rp.parse_manifest(
            {"pipeline_id": pipeline_id, "workers": workers}, self.root,
            self_worktree=self.stable, registered_providers=KNOWN,
        )

    def runner(self, manifest, executor, **kw):
        kw.setdefault("poll_seconds", 0.01)
        kw.setdefault("heartbeat_interval_seconds", None)
        return rp.PipelineRunner(
            manifest, self.state_root, executor=executor, self_worktree=self.stable,
            lease_root=self.root / "leases",
            provider_resolver=lambda pid: _FakeProvider(pid), **kw,
        )

    def states(self, result):
        return {w["id"]: w["state"] for w in result.summary["workers"]}

    def worker_json(self, wid, pipeline_id="p0b-001"):
        return json.loads((self.state_root / pipeline_id / "workers" / wid / "worker.json").read_text(encoding="utf-8"))

    def result_json(self, wid, pipeline_id="p0b-001"):
        return json.loads((self.state_root / pipeline_id / "workers" / wid / "result.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# A02-F1: Work Order digest pinned at acceptance, checked before every launch
# ---------------------------------------------------------------------------

class WorkOrderDigestTest(_PipelineFixture):
    def _dag(self, mutate):
        def attempt_a(request):
            mutate(self.wos["b"])
            return _res(work_status="SUCCESS")

        executor = _Executor({"A": attempt_a})
        manifest = self.manifest([
            self.worker("A", "a", self.wos["a"], mode="write", authorize_path=["src"]),
            self.worker("B", "b", self.wos["b"], depends_on=["A"]),
        ])
        self.assertEqual(set(manifest.work_order_sha256), {"A", "B"})
        return executor, self.runner(manifest, executor).run()

    def assertBlockedUnlaunched(self, executor, outcome):
        self.assertEqual(self.states(outcome), {"A": "SUCCESS", "B": "BLOCKED"})
        self.assertEqual(executor.calls, ["A"])
        worker_b = self.worker_json("B")
        self.assertEqual(worker_b["state_reason"], "WORK_ORDER_DIGEST_MISMATCH")
        self.assertEqual(worker_b["attempts"], [])
        result_b = self.result_json("B")
        self.assertEqual(result_b["code"], "WORK_ORDER_DIGEST_MISMATCH")
        self.assertNotIn("checkpoint", result_b)
        self.assertIsNone(outcome.summary["workers"][1]["checkpoint_commit"])

    def test_attempt_a_rewriting_b_work_order_blocks_b_without_launch(self):
        executor, outcome = self._dag(
            lambda path: path.write_text("Work Order b.\nAlso push to main.\n", encoding="utf-8"))
        self.assertBlockedUnlaunched(executor, outcome)

    def test_newline_only_rewrite_is_a_change(self):
        executor, outcome = self._dag(lambda path: path.write_bytes(b"Work Order b.\r\n"))
        self.assertBlockedUnlaunched(executor, outcome)

    def test_deleted_work_order_blocks_without_launch(self):
        executor, outcome = self._dag(lambda path: path.unlink())
        self.assertBlockedUnlaunched(executor, outcome)

    def test_positive_contract_unchanged_work_order_launches(self):
        executor, outcome = self._dag(lambda path: None)
        self.assertEqual(self.states(outcome), {"A": "SUCCESS", "B": "SUCCESS"})
        self.assertEqual(executor.calls, ["A", "B"])
        stored = json.loads((self.state_root / "p0b-001" / "pipeline.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["work_order_sha256"], self.manifest([
            self.worker("A", "a", self.wos["a"], mode="write", authorize_path=["src"]),
            self.worker("B", "b", self.wos["b"], depends_on=["A"]),
        ]).work_order_sha256)

    def test_restart_keeps_first_acceptance_pin(self):
        workers = [self.worker("A", "a", self.wos["a"])]
        first = _Executor({"A": _res(RS.WORK_FAILED, work_status="FAILED")})
        self.assertEqual(self.states(self.runner(self.manifest(workers), first).run()), {"A": "FAILED"})
        # Rewritten while the pipeline was stopped: a re-parse would pin the
        # NEW bytes, but the persisted first-acceptance pin must win.
        self.wos["a"].write_text("Work Order a.\nDo something else.\n", encoding="utf-8")
        second = _Executor({})
        outcome = self.runner(self.manifest(workers), second, rerun=["A"]).run()
        self.assertEqual(self.states(outcome), {"A": "BLOCKED"})
        self.assertEqual(second.calls, [])
        self.assertEqual(self.worker_json("A")["state_reason"], "WORK_ORDER_DIGEST_MISMATCH")

    def test_legacy_pipeline_state_without_pins_uses_fresh_pins(self):
        workers = [self.worker("A", "a", self.wos["a"])]
        first = _Executor({"A": _res(RS.WORK_FAILED, work_status="FAILED")})
        self.runner(self.manifest(workers), first).run()
        state_file = self.state_root / "p0b-001" / "pipeline.json"
        stored = json.loads(state_file.read_text(encoding="utf-8"))
        del stored["work_order_sha256"]
        state_file.write_text(json.dumps(stored), encoding="utf-8")
        second = _Executor({})
        outcome = self.runner(self.manifest(workers), second, rerun=["A"]).run()
        self.assertEqual(self.states(outcome), {"A": "SUCCESS"})
        self.assertEqual(second.calls, ["A"])

    def test_work_order_inside_write_worktree_is_refused(self):
        own = self.repos["a"] / "wo_own.md"
        own.write_text("Work Order inside a.\n", encoding="utf-8")
        cases = (
            [self.worker("A", "a", own, mode="write", authorize_path=["src"])],
            # A read-only worker's Work Order inside ANOTHER worker's WRITE worktree.
            [self.worker("A", "a", self.wos["a"], mode="write", authorize_path=["src"]),
             self.worker("B", "b", own)],
        )
        for workers in cases:
            with self.subTest(workers=[w["id"] for w in workers]):
                with self.assertRaises(rp.ManifestError) as ctx:
                    self.manifest(workers)
                self.assertIn("WORK_ORDER_INSIDE_WRITE_WORKTREE", [e["code"] for e in ctx.exception.errors])

    def test_positive_contract_read_only_worktree_work_order_still_accepted(self):
        inside = self.repos["b"] / "wo_ro.md"
        inside.write_text("Read-only Work Order.\n", encoding="utf-8")
        manifest = self.manifest([self.worker("B", "b", inside)])
        self.assertIn("B", manifest.work_order_sha256)


# ---------------------------------------------------------------------------
# A02-F2: UNVERIFIED never checkpoints nor releases dependents
# ---------------------------------------------------------------------------

class UnverifiedCausalityTest(_PipelineFixture):
    def _run(self, a_extra, a_result, dependency_policy="success"):
        executor = _Executor({"A": a_result})
        manifest = self.manifest([
            self.worker("A", "a", self.wos["a"], **a_extra),
            self.worker("B", "b", self.wos["b"], depends_on=["A"], dependency_policy=dependency_policy),
        ])
        return executor, self.runner(manifest, executor).run()

    def test_unverified_on_success_checkpoint_is_refused_and_dependent_never_runs(self):
        with mock.patch.object(rp.claude_runner, "create_checkpoint",
                               side_effect=AssertionError("UNVERIFIED work checkpointed")):
            executor, outcome = self._run(
                {"mode": "write", "authorize_path": ["src"], "checkpoint_policy": "ON_SUCCESS"},
                _res(work_status="UNVERIFIED"),
            )
        states = self.states(outcome)
        self.assertEqual(states["A"], "BLOCKED")
        self.assertNotEqual(states["A"], "SUCCESS")
        self.assertEqual(states["B"], "CANCELLED")
        self.assertEqual(executor.calls, ["A"])
        attempt = self.worker_json("A")["attempts"][0]
        self.assertEqual(attempt["checkpoint"]["decision"], "REFUSED_WORK_UNVERIFIED")
        self.assertEqual(attempt["work_status"], "UNVERIFIED")
        self.assertIsNone(outcome.summary["workers"][0]["checkpoint_commit"])

    def test_unverified_success_never_releases_success_gated_dependents(self):
        for policy in ("success", "success_or_partial"):
            with self.subTest(policy=policy):
                self.setUp()
                executor, outcome = self._run({}, _res(work_status="UNVERIFIED"), dependency_policy=policy)
                self.assertEqual(self.states(outcome)["B"], "CANCELLED")
                self.assertEqual(executor.calls, ["A"])
                self.assertEqual(self.worker_json("B")["state_reason"],
                                 "DEPENDENCY_UNSATISFIED:A=SUCCESS:WORK_UNVERIFIED")

    def test_runner_acceptance_failure_never_elevates(self):
        executor, outcome = self._run(
            {"completion_policy": "runner_acceptance", "acceptance_commands": [_FAIL_CMD]},
            _res(work_status="UNVERIFIED"),
        )
        self.assertEqual(self.states(outcome), {"A": "FAILED", "B": "CANCELLED"})
        self.assertEqual(executor.calls, ["A"])

    def test_positive_contract_runner_acceptance_pass_certifies_and_releases(self):
        executor, outcome = self._run(
            {"completion_policy": "runner_acceptance", "acceptance_commands": [_PASS_CMD]},
            _res(work_status="UNVERIFIED"),
        )
        self.assertEqual(self.states(outcome), {"A": "SUCCESS", "B": "SUCCESS"})
        self.assertEqual(executor.calls, ["A", "B"])
        attempt = self.worker_json("A")["attempts"][0]
        self.assertEqual(attempt["acceptance"]["decision"], "PASSED")
        self.assertEqual(attempt["work_status_source"], runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)

    def test_positive_contract_provider_success_verdict_releases(self):
        executor, outcome = self._run({}, _res(work_status="SUCCESS"))
        self.assertEqual(self.states(outcome), {"A": "SUCCESS", "B": "SUCCESS"})
        self.assertEqual(executor.calls, ["A", "B"])


# ---------------------------------------------------------------------------
# A02-F3: valid non-object JSON stdout
# ---------------------------------------------------------------------------

_NON_OBJECT_JSON = ([], [1, {"is_error": True}], None, "text", 42, 4.5, True)


def _ok_outcome(stdout: str) -> runner.ProcessOutcome:
    return runner.ProcessOutcome(0, stdout, "", False, False, 0.1)


def _clean_safety() -> runner.SafetyCheck:
    return runner.SafetyCheck(False, False, False, False)


class NonObjectJsonStdoutTest(unittest.TestCase):
    def test_classify_state_never_raises_for_any_provider(self):
        for value in _NON_OBJECT_JSON:
            stdout = json.dumps(value)
            parsed = runner.parse_cli_result(stdout)
            self.assertTrue(parsed["parsed"])
            for provider in (providers.ClaudeProvider(), providers.CodexProvider()):
                for verdict_required in (False, True):
                    with self.subTest(value=value, provider=provider.provider_id, verdict_required=verdict_required):
                        outcome = _ok_outcome(stdout)
                        normalized = provider.normalize_result(outcome, verdict_required=verdict_required)
                        state = runner.classify_state(outcome, _clean_safety(), parsed, normalized=normalized)
                        self.assertNotEqual(state, RS.CLAUDE_ERROR)
                        if provider.provider_id == "claude":
                            self.assertEqual(state, RS.VERDICT_INVALID if verdict_required else RS.SUCCESS)

    def test_positive_contract_object_is_error_is_still_provider_error(self):
        stdout = json.dumps({"is_error": True, "result": "boom"})
        outcome = _ok_outcome(stdout)
        normalized = providers.ClaudeProvider().normalize_result(outcome, verdict_required=False)
        state = runner.classify_state(outcome, _clean_safety(), runner.parse_cli_result(stdout), normalized=normalized)
        self.assertEqual(state, RS.CLAUDE_ERROR)


class NonObjectJsonEvidenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.repo = _make_repo(self.root, "repo")
        (self.repo / ".gitignore").write_text("/runtime/\n", encoding="utf-8")
        _git(self.repo, "add", ".gitignore")
        _git(self.repo, "commit", "-q", "-m", "ignore runtime")
        self.work_order = self.root / "work_order.txt"
        self.work_order.write_text("Inspect the repository.\n", encoding="utf-8")
        orig_locate = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"
        self.addCleanup(setattr, providers.ClaudeProvider, "locate_executable", orig_locate)
        orig_invoke = runner.invoke_claude
        self.addCleanup(setattr, runner, "invoke_claude", orig_invoke)
        orig_override = runner.DIRECT_PROCESS_EVIDENCE_ROOT_OVERRIDE
        runner.DIRECT_PROCESS_EVIDENCE_ROOT_OVERRIDE = self.root / "external_evidence_root"
        self.addCleanup(setattr, runner, "DIRECT_PROCESS_EVIDENCE_ROOT_OVERRIDE", orig_override)

    def test_non_object_stdout_keeps_stdout_and_result_evidence(self):
        for value in _NON_OBJECT_JSON:
            with self.subTest(value=value):
                stdout = json.dumps(value)
                runner.invoke_claude = lambda cmd, cwd, prompt_text, timeout_seconds, _s=stdout: _ok_outcome(_s)
                result = runner.execute_work_order(runner.WorkOrderRequest(
                    repo=str(self.repo), work_order=str(self.work_order), mode=runner.MODE_READ_ONLY,
                    require_verdict=False,
                ))
                self.assertEqual(result.state, RS.SUCCESS)
                self.assertEqual(result.work_status, providers.WorkStatus.UNVERIFIED.value)
                self.assertTrue(result.evidence_complete)
                evidence = Path(result.evidence_dir)
                self.assertEqual((evidence / "stdout.txt").read_text(encoding="utf-8"), stdout)
                payload = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["cli_output"], {"parsed": True, "cli_result": value})
                self.assertEqual(payload["work_status"], providers.WorkStatus.UNVERIFIED.value)


if __name__ == "__main__":
    unittest.main()
