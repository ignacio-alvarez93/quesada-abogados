import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_director as fd
from scripts.ai import runner_providers as providers

KNOWN = ["claude"]
RS = runner.RunState


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "director-tests@example.invalid")
    _git(repo, "config", "user.name", "Director Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


class FakeProvider(providers.Provider):
    def __init__(self, provider_id="claude"):
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
        return runner_state == "CLAUDE_ERROR" and "rate limit" in (error_text or "").lower()


class UnavailableProvider(FakeProvider):
    def probe(self):
        return providers.ProviderProbe(self.provider_id, False, reason="not installed")


def _resolver(providers_map):
    def _resolve(pid):
        if pid not in providers_map:
            raise providers.UnknownProviderError(pid, KNOWN)
        return providers_map[pid]
    return _resolve


class DirectorTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.stable = _make_repo(self.root, "stable")
        self.target = _make_repo(self.root, "target")
        self.state_root = self.root / "state"
        self.director_root = self.root / "director"
        self.factory_root = self.root / "factory"

    def service(self, *, provider_map=None, executor=None, **kw) -> fd.FabricDirectorService:
        provider_map = provider_map if provider_map is not None else {"claude": FakeProvider("claude")}
        kw.setdefault("state_root", self.state_root)
        kw.setdefault("director_root", self.director_root)
        kw.setdefault("factory_root", self.factory_root)
        kw.setdefault("self_worktree", self.stable)
        kw.setdefault("registered_providers", KNOWN)
        kw.setdefault("provider_resolver", _resolver(provider_map))
        kw.setdefault("pipeline_runner_options", {"poll_seconds": 0.01, "heartbeat_interval_seconds": None})
        if executor is not None:
            kw["executor"] = executor
        return fd.FabricDirectorService(**kw)

    def spec(self, **extra) -> fd.DirectorWorkOrderSpec:
        kw = dict(worktree=str(self.target), work_order_text="Do the thing.\n")
        kw.update(extra)
        return fd.DirectorWorkOrderSpec(**kw)

    def make_evidence(self, *, work_product_present=False, changed=None, authorized=None, unauthorized=None) -> Path:
        evidence = self.root / f"evidence_{uuid.uuid4().hex[:10]}"
        evidence.mkdir()
        metadata = {
            "work_product_present": work_product_present,
            "changed_paths_after_run": changed or [],
            "authorized_changed_paths": authorized or [],
            "unauthorized_changed_paths": unauthorized or [],
        }
        (evidence / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        if work_product_present:
            (evidence / "work_product.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        return evidence

    def seed_pipeline_result(self, run_id: str, worker_id: str, worker_entry: dict, worker_result: dict = None) -> None:
        """Writes synthetic durable Runner artifacts directly - used only for
        projecting a worker state/decision that FDB-1 need not re-derive by
        actually driving the full Runner state machine (e.g. RETRY_WAIT,
        which requires a multi-attempt manifest outside FDB-1's single-
        attempt-by-default V1 contract)."""
        base = self.state_root / run_id / "workers" / worker_id
        base.mkdir(parents=True)
        entry = {
            "id": worker_id, "provider": "claude", "requested_provider": "claude",
            "state_reason": None, "attempts": 0, "work_attempts_used": 0, "availability_attempts": 0,
            "provider_condition": None, "next_eligible_utc": None, "result_path": None,
            "worker_path": None, "checkpoint_policy": None, "checkpoint_commit": None,
        }
        entry.update(worker_entry)
        pipeline_payload = {
            "schema_version": 1, "pipeline_id": run_id, "status": "INCOMPLETE", "stop_reason": None,
            "workers": [entry],
        }
        (self.state_root / run_id / "pipeline_result.json").write_text(json.dumps(pipeline_payload), encoding="utf-8")
        if worker_result is not None:
            (base / "result.json").write_text(json.dumps(worker_result), encoding="utf-8")


# ---------------------------------------------------------------------------
class ProjectStateTests(DirectorTestBase):
    """1. project_state returns branch/head/clean without mutation."""

    def test_project_state_reports_clean_repo_without_mutating_it(self):
        svc = self.service()
        before_head = _git(self.target, "rev-parse", "HEAD").stdout.strip()
        state = svc.project_state(self.target)
        after_head = _git(self.target, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["head"], before_head)
        self.assertTrue(state["clean"])
        self.assertIn("porcelain_status", state)
        self.assertEqual(before_head, after_head)

    def test_project_state_reports_dirty_repo(self):
        svc = self.service()
        (self.target / "untracked.txt").write_text("x", encoding="utf-8")
        state = svc.project_state(self.target)
        self.assertFalse(state["clean"])

    def test_project_state_rejects_non_worktree(self):
        svc = self.service()
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.project_state(self.root / "not_a_repo")
        self.assertEqual(ctx.exception.code, "INVALID_WORKTREE")


# ---------------------------------------------------------------------------
class SubmitTests(DirectorTestBase):
    """2-12, 27-28. submit()/validate() contract."""

    def test_submit_persists_work_order_and_manifest_outside_target_worktree(self):
        svc = self.service()
        handle = svc.submit(self.spec())
        self.assertTrue(Path(handle.work_order_path).exists())
        self.assertTrue(Path(handle.manifest_path).exists())
        director_dir = Path(handle.director_dir).resolve()
        self.assertIn(self.director_root.resolve(), [director_dir, *director_dir.parents])
        self.assertNotIn(self.target.resolve(), [director_dir, *director_dir.parents])

    def test_caller_cannot_supply_pipeline_id_or_worker_id(self):
        with self.assertRaises(TypeError):
            fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x", pipeline_id="caller-chosen")
        with self.assertRaises(TypeError):
            fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x", worker_id="caller-chosen")

    def test_generated_pipeline_id_is_a_safe_path_segment(self):
        svc = self.service()
        handle = svc.submit(self.spec())
        pid = handle.pipeline_id
        self.assertTrue(0 < len(pid) <= 64)
        self.assertTrue(all(c.isalnum() or c in "-_." for c in pid))
        self.assertNotIn(pid, (".", ".."))
        self.assertFalse(pid.startswith("."))

    def test_generated_worker_id_is_a_safe_path_segment(self):
        svc = self.service()
        handle = svc.submit(self.spec())
        wid = handle.worker_id
        self.assertTrue(0 < len(wid) <= 64)
        self.assertTrue(all(c.isalnum() or c in "-_." for c in wid))
        self.assertNotIn(wid, (".", ".."))

    def test_work_order_text_survives_persistence_with_only_documented_newline_normalization(self):
        svc = self.service()
        handle = svc.submit(self.spec(work_order_text="Line one\nLine two"))
        persisted = Path(handle.work_order_path).read_bytes().decode("utf-8")
        self.assertEqual(persisted, "Line one\nLine two\n")

        handle2 = svc.submit(self.spec(work_order_text="Already terminated\n"))
        persisted2 = Path(handle2.work_order_path).read_bytes().decode("utf-8")
        self.assertEqual(persisted2, "Already terminated\n")

    def test_default_mode_is_read_only(self):
        spec = fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x")
        self.assertEqual(spec.mode, "read-only")
        svc = self.service()
        handle = svc.submit(spec)
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["mode"], "read-only")

    def test_allow_shell_is_false_by_default(self):
        spec = fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x")
        self.assertFalse(spec.allow_shell)
        svc = self.service()
        handle = svc.submit(spec)
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertFalse(manifest["workers"][0]["allow_shell"])

    def test_checkpoint_policy_absent_by_default(self):
        spec = fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x")
        self.assertIsNone(spec.checkpoint_policy)
        svc = self.service()
        handle = svc.submit(spec)
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertIsNone(manifest["workers"][0]["checkpoint_policy"])

    def test_authorize_paths_map_into_manifest_authorize_path(self):
        svc = self.service()
        handle = svc.submit(self.spec(authorize_paths=["src/foo", "docs"]))
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["authorize_path"], ["src/foo", "docs"])

    def test_required_capabilities_map_into_manifest(self):
        svc = self.service()
        handle = svc.submit(self.spec(required_capabilities=["SHELL"]))
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["required_capabilities"], ["SHELL"])

    def test_parse_manifest_is_used_and_invalid_manifest_is_refused(self):
        svc = self.service()
        handle = svc.submit(self.spec(provider="totally-unknown-provider"))
        self.assertFalse(handle.validated)
        self.assertTrue(any(e["code"] == "UNKNOWN_PROVIDER" for e in handle.validation_errors))
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.run(handle)
        self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")

    def test_validate_reuses_parse_manifest_for_a_valid_manifest(self):
        svc = self.service()
        handle = svc.submit(self.spec())
        self.assertTrue(handle.validated)
        verdict = svc.validate(handle)
        self.assertTrue(verdict["validated"])
        self.assertEqual(verdict["errors"], [])

    def test_path_traversal_worktree_is_rejected(self):
        svc = self.service()
        traversal = str(self.target / ".." / ".." / ".." / "definitely_not_a_repo")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.submit(self.spec(worktree=traversal))
        self.assertEqual(ctx.exception.code, "INVALID_WORKTREE")

    def test_duplicate_director_run_directory_fails_closed(self):
        svc = self.service()
        with mock.patch.object(svc, "_generate_pipeline_id", return_value="fdb-fixed-collision"):
            svc.submit(self.spec())
            with self.assertRaises(fd.DirectorError) as ctx:
                svc.submit(self.spec())
        self.assertEqual(ctx.exception.code, "DIRECTOR_RUN_COLLISION")

    def test_submit_does_not_mutate_target_worktree(self):
        svc = self.service()
        before = _git(self.target, "status", "--porcelain").stdout
        before_head = _git(self.target, "rev-parse", "HEAD").stdout
        svc.submit(self.spec())
        after = _git(self.target, "status", "--porcelain").stdout
        after_head = _git(self.target, "rev-parse", "HEAD").stdout
        self.assertEqual(before, after)
        self.assertEqual(before_head, after_head)


# ---------------------------------------------------------------------------
class RunTests(DirectorTestBase):
    """13-15, 26, 29. run()/submit_and_run()/status()/factory_state() wiring."""

    def test_no_subprocess_cli_usage_in_module_source(self):
        source = Path(fd.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("subprocess.Popen(", source)
        self.assertNotIn("subprocess.call(", source)
        # Do not grep comments/docstrings: only executable call arguments
        # matter. A docstring may legitimately explain that runner_pipeline.py
        # is NOT invoked through a subprocess.
        import ast
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for argument in node.args:
                for literal in ast.walk(argument):
                    if (
                        isinstance(literal, ast.Constant)
                        and isinstance(literal.value, str)
                    ):
                        self.assertNotIn(
                            "runner_pipeline.py",
                            literal.value,
                        )

    def test_run_uses_pipeline_runner_programmatically(self):
        executor = mock.Mock(side_effect=lambda request: runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-1", evidence_dir=None, work_status="SUCCESS",
        ))
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec())
        summary = svc.run(handle)
        self.assertTrue(executor.called)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.pipeline_id, handle.pipeline_id)

    def test_submit_and_run_is_composition_of_submit_then_run(self):
        executor = lambda request: runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-2", evidence_dir=None, work_status="SUCCESS",
        )
        svc = self.service(executor=executor)
        spec = self.spec()
        with mock.patch.object(svc, "submit", wraps=svc.submit) as msub, \
             mock.patch.object(svc, "run", wraps=svc.run) as mrun:
            summary = svc.submit_and_run(spec)
        msub.assert_called_once_with(spec)
        mrun.assert_called_once()
        self.assertEqual(summary.worker_state, "SUCCESS")

    def test_status_delegates_to_read_pipeline_status(self):
        svc = self.service()
        with mock.patch("scripts.ai.fabric_director.pipeline.read_pipeline_status") as mocked:
            mocked.return_value = {"pipeline_id": "abc", "workers": []}
            result = svc.status("abc")
        mocked.assert_called_once_with(svc.state_root, "abc")
        self.assertEqual(result, {"pipeline_id": "abc", "workers": []})

    def test_factory_state_delegates_to_factory_status_report(self):
        svc = self.service()
        with mock.patch("scripts.ai.fabric_director.pipeline.factory_status_report") as mocked:
            mocked.return_value = {"counts": {}}
            result = svc.factory_state()
        mocked.assert_called_once_with(svc.state_root, svc.factory_root)
        self.assertEqual(result, {"counts": {}})

    def test_no_unrestricted_shell_api_exists(self):
        forbidden = {"shell", "exec", "arbitrary_subprocess", "run_shell", "execute_command"}
        public_methods = {name for name in dir(fd.FabricDirectorService) if not name.startswith("_")}
        self.assertEqual(public_methods & forbidden, set())


# ---------------------------------------------------------------------------
class ResultProjectionTests(DirectorTestBase):
    """16-25. result()/status() compact projection over durable artifacts."""

    def _run_with_result(self, result: "runner.WorkOrderResult"):
        executor = lambda request: result
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec())
        summary = svc.run(handle)
        return svc, handle, summary

    def test_success_result_reads_work_status_runner_state_and_evidence(self):
        evidence = self.make_evidence(
            work_product_present=True, changed=["M src/a.py"],
            authorized=["M src/a.py"], unauthorized=[],
        )
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-ok", evidence_dir=evidence,
            work_status="SUCCESS", evidence_complete=True, work_product_present=True,
        )
        svc, handle, summary = self._run_with_result(result)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.runner_state, "SUCCESS")
        self.assertEqual(summary.work_status, "SUCCESS")
        self.assertEqual(summary.evidence_dir, str(evidence))
        self.assertTrue(summary.evidence_complete)
        self.assertIsNone(summary.evidence_error)
        self.assertTrue(summary.work_product_present)
        self.assertEqual(summary.changed_paths, ("M src/a.py",))
        self.assertEqual(summary.authorized_changed_paths, ("M src/a.py",))
        self.assertEqual(summary.unauthorized_changed_paths, ())
        self.assertFalse(summary.decision_required)

        # Re-fetching by run_id alone (no handle needed) must agree.
        again = svc.result(handle.pipeline_id)
        self.assertEqual(again.work_status, "SUCCESS")

    def test_result_does_not_depend_on_cli_output_prose(self):
        evidence = self.make_evidence(work_product_present=False)
        # A worker result.json carrying an unrelated "cli_output" prose blob
        # must never be consulted.
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-prose", evidence_dir=evidence, work_status="SUCCESS",
        )
        svc, handle, summary = self._run_with_result(result)
        worker_result_path = self.state_root / handle.pipeline_id / "workers" / handle.worker_id / "result.json"
        payload = json.loads(worker_result_path.read_text(encoding="utf-8"))
        payload["cli_output"] = {"parsed": True, "result": "HUMAN PROSE THAT MUST NEVER BE PARSED"}
        worker_result_path.write_text(json.dumps(payload), encoding="utf-8")
        again = svc.result(handle.pipeline_id)
        self.assertEqual(again.work_status, "SUCCESS")

    def test_evidence_incomplete_is_not_reported_as_work_failed(self):
        evidence = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-partial-evidence", evidence_dir=evidence,
            work_status="SUCCESS", evidence_complete=False, evidence_error="git_before.txt: OSError",
        )
        svc, handle, summary = self._run_with_result(result)
        self.assertEqual(summary.worker_state, "PARTIAL")
        self.assertEqual(summary.work_status, "SUCCESS")
        self.assertFalse(summary.evidence_complete)
        self.assertEqual(summary.evidence_error, "git_before.txt: OSError")

    def test_missing_optional_evidence_gives_none_or_empty_rather_than_failure(self):
        provider_map = {"claude": UnavailableProvider("claude")}
        svc = self.service(provider_map=provider_map)
        handle = svc.submit(self.spec())
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "BLOCKED")
        self.assertIsNone(summary.evidence_dir)
        self.assertIsNone(summary.evidence_complete)
        self.assertIsNone(summary.work_product_present)
        self.assertEqual(summary.changed_paths, ())
        self.assertEqual(summary.authorized_changed_paths, ())
        self.assertEqual(summary.unauthorized_changed_paths, ())
        self.assertIsNone(summary.checkpoint_commit)

    def test_waiting_provider_quota_projects_no_decision_required(self):

        # Projection test only: once WAITING_PROVIDER_QUOTA has been
        # durably produced, there is no reason to wait for the real
        # provider reset time. Prevent a real multi-minute scheduler sleep
        # without changing production behavior.
        original_next_wake = fd.pipeline.PipelineRunner._next_wake
        fd.pipeline.PipelineRunner._next_wake = (
            lambda _runner, _now: None
        )
        self.addCleanup(
            setattr,
            fd.pipeline.PipelineRunner,
            "_next_wake",
            original_next_wake,
        )
        result = runner.WorkOrderResult(
            state=RS.CLAUDE_ERROR, exit_code=3, run_id="run-quota", evidence_dir=None,
            error_message="quota exceeded", provider_condition={
                "condition": "PROVIDER_QUOTA_EXHAUSTED", "reason": "QUOTA_MESSAGE",
                "http_status": None, "reset_hint": None, "message_excerpt": "quota exceeded",
            },
        )
        svc, handle, summary = self._run_with_result(result)
        self.assertEqual(summary.worker_state, "WAITING_PROVIDER_QUOTA")
        self.assertFalse(summary.decision_required)
        self.assertIsNone(summary.decision_type)
        self.assertEqual(summary.provider_condition, "PROVIDER_QUOTA_EXHAUSTED")
        self.assertIsNotNone(summary.next_eligible_utc)

    def test_blocked_provider_auth_projects_decision_required(self):
        result = runner.WorkOrderResult(
            state=RS.CLAUDE_ERROR, exit_code=3, run_id="run-auth", evidence_dir=None,
            error_message="not logged in", provider_condition={
                "condition": "PROVIDER_AUTH_BLOCKED", "reason": "AUTH_MESSAGE",
                "http_status": None, "reset_hint": None, "message_excerpt": "not logged in",
            },
        )
        svc, handle, summary = self._run_with_result(result)
        self.assertEqual(summary.worker_state, "BLOCKED_PROVIDER_AUTH")
        self.assertTrue(summary.decision_required)
        self.assertEqual(summary.decision_type, "PROVIDER_AUTH")

    def test_retry_wait_does_not_request_human_decision(self):
        # RETRY_WAIT requires max_attempts > 1, outside FDB-1's generated
        # single-attempt-by-default manifest; projected here directly over a
        # synthetic durable artifact (see `seed_pipeline_result`).
        svc = self.service()
        self.seed_pipeline_result("run-retry", "w1", {"state": "RETRY_WAIT", "state_reason": "TRANSIENT:CLAUDE_ERROR"})
        summary = svc.result("run-retry")
        self.assertEqual(summary.worker_state, "RETRY_WAIT")
        self.assertFalse(summary.decision_required)
        self.assertIsNone(summary.decision_type)

    def test_checkpoint_commit_is_projected_from_pipeline_result(self):
        svc = self.service()
        self.seed_pipeline_result(
            "run-checkpoint", "w1",
            {"state": "SUCCESS", "checkpoint_policy": "ON_SUCCESS", "checkpoint_commit": "deadbeef1234"},
        )
        summary = svc.result("run-checkpoint")
        self.assertEqual(summary.checkpoint_commit, "deadbeef1234")


if __name__ == "__main__":
    unittest.main()
