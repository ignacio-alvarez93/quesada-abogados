import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_director as fd
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_integration as ri
from scripts.ai import runner_providers as providers
from scripts.ai import runner_reconciliation as rr
from scripts.ai import runner_worktree_inventory as wi
from scripts.ai import runner_worktree_retirement as wr
from scripts.tests.test_runner_git import plain_git
from scripts.tests.test_runner_integration import (
    _ISOLATED_ENV, REMOTE_URL, SCOPES, Fixture, _rmtree, good_evidence,
)
from scripts.tests.test_runner_reconciliation import (
    ACCEPTANCE, Fixture as ReconFixture, change as recon_change, text as recon_text,
)

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

    def make_evidence(
        self, *, work_product_present=False, changed=None, authorized=None, unauthorized=None,
        safety_verdict=None, resume=None, branch_guard=None, write_scope=None, dirty_tree_policy=None,
        execution_mode=None, normalized_result=None, process_supervision=None, evidence_errors=None,
        work_product_data=None,
    ) -> Path:
        evidence = self.root / f"evidence_{uuid.uuid4().hex[:10]}"
        evidence.mkdir()
        metadata = {
            "work_product_present": work_product_present,
            "changed_paths_after_run": changed or [],
            "authorized_changed_paths": authorized or [],
            "unauthorized_changed_paths": unauthorized or [],
        }
        if process_supervision is not None:
            metadata["process_supervision"] = process_supervision
        if evidence_errors is not None:
            metadata["evidence_errors"] = evidence_errors
        (evidence / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        # Mirrors claude_runner's OWN attempt result.json (see
        # `execute_work_order`): the authority for safety/resume/branch-guard/
        # write-scope/dirty-tree-policy/normalized-result evidence().
        result_payload = {
            "safety_verdict": safety_verdict,
            "resume": resume,
            "branch_guard": branch_guard,
            "write_scope": write_scope,
            "dirty_tree_policy": dirty_tree_policy,
            "execution_mode": execution_mode,
            "normalized_result": normalized_result,
        }
        if evidence_errors is not None:
            result_payload["evidence_errors"] = evidence_errors
        (evidence / "result.json").write_text(json.dumps(result_payload), encoding="utf-8")

        if work_product_present:
            (evidence / "work_product.json").write_text(
                json.dumps(work_product_data if work_product_data is not None else {"ok": True}), encoding="utf-8",
            )
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

    def _success_executor(self):
        return lambda request: runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-ledger", evidence_dir=None, work_status="SUCCESS",
        )

    def test_fcp_fix_09_library_default_has_no_ledger(self):
        svc = self.service(executor=self._success_executor())
        self.assertIsNone(svc.factory_ledger)
        self.assertEqual(svc.submit_and_run(self.spec()).worker_state, "SUCCESS")
        self.assertFalse(self.factory_root.exists())

    def test_fcp_fix_09_run_emits_runner_lifecycle_events_once(self):
        from scripts.ai import runner_factory_ledger as flog
        svc = self.service(executor=self._success_executor(), factory_ledger=flog.FactoryLedger(self.factory_root))
        summary = svc.submit_and_run(self.spec())
        events = fd.pipeline.factory_history_report(self.factory_root, pipeline_id=summary.pipeline_id)
        types = [e["event_type"] for e in events]
        self.assertEqual(types.count(flog.WORKER_STARTED), 1)
        self.assertEqual(types.count(flog.WORKER_FINISHED), 1)
        self.assertEqual(flog.FactoryLedger(self.factory_root).status()["active_workers"], [])
        self.assertEqual(svc.factory_state()["counts"]["ACTIVE"], 0)

    def test_fcp_fix_09_ledger_failure_does_not_change_work_classification(self):
        ledger = mock.Mock()
        ledger.append.side_effect = OSError("ledger disk full")
        svc = self.service(executor=self._success_executor(), factory_ledger=ledger)
        summary = svc.submit_and_run(self.spec())
        self.assertTrue(ledger.append.called)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.work_status, "SUCCESS")
        baseline_svc = self.service(executor=self._success_executor())
        baseline = baseline_svc.submit_and_run(self.spec())
        self.assertEqual(
            svc.decision(summary.run_id).decision_code, baseline_svc.decision(baseline.run_id).decision_code,
        )

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


# ---------------------------------------------------------------------------
class EvidenceProjectionTests(DirectorTestBase):
    """FDB-2-1. evidence()/DirectorRunEvidence: a wider structured projection
    over the SAME durable Runner artifacts result() already reads - never a
    second evidence store, never a safety/resume re-evaluation."""

    def _run_with_result(self, result: "runner.WorkOrderResult"):
        executor = lambda request: result
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec())
        svc.run(handle)
        return svc, handle

    def test_success_evidence_projection(self):
        evidence = self.make_evidence(
            work_product_present=True, changed=["M src/a.py"], authorized=["M src/a.py"], unauthorized=[],
            safety_verdict={"verdict": "SAFE", "reasons": []},
            resume={"decision": "NOT_REQUESTED"},
            branch_guard={"decision": "ALLOWED"},
            write_scope={"decision": "ALLOWED", "authorized_scopes": ["src"]},
            dirty_tree_policy={"decision": "NOT_APPLICABLE"},
            execution_mode="write",
            normalized_result={"work_status": "SUCCESS"},
        )
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-ok", evidence_dir=evidence,
            work_status="SUCCESS", evidence_complete=True, work_product_present=True,
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)

        self.assertEqual(ev.run_id, handle.pipeline_id)
        self.assertEqual(ev.pipeline_id, handle.pipeline_id)
        self.assertEqual(ev.worker_id, handle.worker_id)
        self.assertEqual(ev.worker_state, "SUCCESS")
        self.assertEqual(ev.runner_state, "SUCCESS")
        self.assertEqual(ev.work_status, "SUCCESS")
        self.assertEqual(ev.execution_mode, "write")
        self.assertEqual(ev.evidence_dir, str(evidence))
        self.assertTrue(ev.evidence_complete)
        self.assertEqual(ev.evidence_errors, ())
        self.assertEqual(ev.safety_verdict, "SAFE")
        self.assertEqual(ev.safety_reasons, ())
        self.assertEqual(ev.changed_paths, ("M src/a.py",))
        self.assertEqual(ev.authorized_changed_paths, ("M src/a.py",))
        self.assertEqual(ev.unauthorized_changed_paths, ())
        self.assertEqual(ev.branch_guard, {"decision": "ALLOWED"})
        self.assertEqual(ev.write_scope, {"decision": "ALLOWED", "authorized_scopes": ["src"]})
        self.assertEqual(ev.dirty_tree_policy, {"decision": "NOT_APPLICABLE"})
        self.assertEqual(ev.normalized_result, {"work_status": "SUCCESS"})
        self.assertTrue(ev.work_product_present)
        self.assertEqual(ev.work_product_path, str(evidence / "work_product.json"))
        self.assertEqual(ev.work_product, {"ok": True})
        self.assertEqual(ev.resume, {"decision": "NOT_REQUESTED"})
        self.assertIsNotNone(ev.preflight)

    def test_partial_evidence_projection(self):
        evidence = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.PARTIAL, exit_code=0, run_id="run-partial", evidence_dir=evidence,
            work_status="PARTIAL", evidence_complete=True,
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.worker_state, "PARTIAL")
        self.assertEqual(ev.work_status, "PARTIAL")

    def test_failed_safety_evidence_projection(self):
        evidence = self.make_evidence(
            unauthorized=["M src/unauthorized.py"],
            safety_verdict={"verdict": "FAILED_SAFETY", "reasons": ["unauthorized change: src/unauthorized.py"]},
        )
        result = runner.WorkOrderResult(
            state=RS.FAILED_SAFETY, exit_code=4, run_id="run-failed-safety", evidence_dir=evidence,
            error_message="unauthorized change detected",
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.worker_state, "FAILED")
        self.assertEqual(ev.state_reason, "FAILED_SAFETY")
        self.assertEqual(ev.safety_verdict, "FAILED_SAFETY")
        self.assertEqual(ev.safety_reasons, ("unauthorized change: src/unauthorized.py",))
        self.assertEqual(ev.unauthorized_changed_paths, ("M src/unauthorized.py",))

    def test_waiting_provider_quota_evidence_projection(self):
        original_next_wake = fd.pipeline.PipelineRunner._next_wake
        fd.pipeline.PipelineRunner._next_wake = (lambda _runner, _now: None)
        self.addCleanup(setattr, fd.pipeline.PipelineRunner, "_next_wake", original_next_wake)
        result = runner.WorkOrderResult(
            state=RS.CLAUDE_ERROR, exit_code=3, run_id="run-quota-ev", evidence_dir=None,
            error_message="quota exceeded", provider_condition={
                "condition": "PROVIDER_QUOTA_EXHAUSTED", "reason": "QUOTA_MESSAGE",
                "http_status": None, "reset_hint": None, "message_excerpt": "quota exceeded",
            },
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.worker_state, "WAITING_PROVIDER_QUOTA")
        self.assertEqual(ev.provider_condition, "PROVIDER_QUOTA_EXHAUSTED")
        self.assertIsNotNone(ev.next_eligible_utc)
        self.assertIsNone(ev.evidence_dir)
        self.assertEqual(ev.safety_verdict, None)

    def test_blocked_provider_auth_evidence_projection(self):
        result = runner.WorkOrderResult(
            state=RS.CLAUDE_ERROR, exit_code=3, run_id="run-auth-ev", evidence_dir=None,
            error_message="not logged in", provider_condition={
                "condition": "PROVIDER_AUTH_BLOCKED", "reason": "AUTH_MESSAGE",
                "http_status": None, "reset_hint": None, "message_excerpt": "not logged in",
            },
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.worker_state, "BLOCKED_PROVIDER_AUTH")
        self.assertEqual(ev.provider_condition, "PROVIDER_AUTH_BLOCKED")

    def test_evidence_incomplete_is_projected_not_as_work_failure(self):
        evidence = self.make_evidence(work_product_present=False, evidence_errors=["git_before.txt: OSError"])
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-partial-evidence-ev", evidence_dir=evidence,
            work_status="SUCCESS", evidence_complete=False, evidence_error="git_before.txt: OSError",
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.worker_state, "PARTIAL")
        self.assertEqual(ev.work_status, "SUCCESS")
        self.assertFalse(ev.evidence_complete)
        self.assertEqual(ev.evidence_errors, ("git_before.txt: OSError",))

    def test_work_product_present_is_projected_with_path_and_content(self):
        evidence = self.make_evidence(work_product_present=True, work_product_data={
            "base_head": "deadbeef", "branch": "main", "authorized_changed_paths": ["src/a.py"],
            "process_confirmed_stopped": True,
        })
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-wp-present", evidence_dir=evidence,
            work_status="SUCCESS", work_product_present=True,
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertTrue(ev.work_product_present)
        self.assertEqual(ev.work_product_path, str(evidence / "work_product.json"))
        self.assertEqual(ev.work_product["base_head"], "deadbeef")
        self.assertEqual(ev.work_product["branch"], "main")
        self.assertEqual(ev.work_product["authorized_changed_paths"], ["src/a.py"])
        self.assertTrue(ev.work_product["process_confirmed_stopped"])

    def test_work_product_absent_fails_softly(self):
        evidence = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-wp-absent", evidence_dir=evidence, work_status="SUCCESS",
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertFalse(ev.work_product_present)
        self.assertIsNone(ev.work_product_path)
        self.assertIsNone(ev.work_product)

    def test_checkpoint_policy_and_commit_are_projected(self):
        svc = self.service()
        self.seed_pipeline_result(
            "run-checkpoint-ev", "w1",
            {"state": "SUCCESS", "checkpoint_policy": "ON_SUCCESS", "checkpoint_commit": "deadbeef1234"},
        )
        ev = svc.evidence("run-checkpoint-ev")
        self.assertEqual(ev.checkpoint_policy, "ON_SUCCESS")
        self.assertEqual(ev.checkpoint_commit, "deadbeef1234")

    def test_process_supervision_is_projected(self):
        evidence = self.make_evidence(process_supervision={"pid": 1234, "confirmed_stopped": True})
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-supervision", evidence_dir=evidence, work_status="SUCCESS",
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.process_supervision, {"pid": 1234, "confirmed_stopped": True})

    def test_missing_optional_artifacts_fail_softly(self):
        provider_map = {"claude": UnavailableProvider("claude")}
        svc = self.service(provider_map=provider_map)
        handle = svc.submit(self.spec())
        svc.run(handle)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.worker_state, "BLOCKED")
        self.assertIsNone(ev.evidence_dir)
        self.assertIsNone(ev.evidence_complete)
        self.assertEqual(ev.evidence_errors, ())
        self.assertIsNone(ev.work_product_present)
        self.assertIsNone(ev.work_product_path)
        self.assertIsNone(ev.work_product)
        self.assertEqual(ev.changed_paths, ())
        self.assertEqual(ev.authorized_changed_paths, ())
        self.assertEqual(ev.unauthorized_changed_paths, ())
        self.assertIsNone(ev.checkpoint_commit)
        self.assertIsNone(ev.safety_verdict)
        self.assertEqual(ev.safety_reasons, ())
        self.assertIsNone(ev.branch_guard)
        self.assertIsNone(ev.write_scope)
        self.assertIsNone(ev.dirty_tree_policy)
        self.assertIsNone(ev.resume)
        self.assertIsNone(ev.normalized_result)
        self.assertIsNone(ev.process_supervision)

    def test_evidence_does_not_require_or_read_provider_prose(self):
        evidence = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-no-prose", evidence_dir=evidence, work_status="SUCCESS",
        )
        svc, handle = self._run_with_result(result)
        # No stdout.txt/stderr.txt/cli_output were ever written under this
        # synthetic evidence dir; evidence() must still fully resolve.
        self.assertFalse((evidence / "stdout.txt").exists())
        self.assertFalse((evidence / "stderr.txt").exists())
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.work_status, "SUCCESS")

    def test_safety_verdict_comes_from_runner_artifact_not_director_recomputation(self):
        evidence = self.make_evidence(safety_verdict={"verdict": "SAFE", "reasons": []})
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-safety-authority", evidence_dir=evidence,
            work_status="SUCCESS",
        )
        svc, handle = self._run_with_result(result)
        with mock.patch("scripts.ai.fabric_director.claude_runner.evaluate_write_mode_safety") as recompute:
            ev = svc.evidence(handle.pipeline_id)
        recompute.assert_not_called()
        self.assertEqual(ev.safety_verdict, "SAFE")

    def test_resume_evidence_is_projected_but_not_authorized_by_director(self):
        evidence = self.make_evidence(resume={"decision": "ALLOWED_RESUMED", "reason": "provenance validated"})
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-resume-ev", evidence_dir=evidence, work_status="SUCCESS",
        )
        svc, handle = self._run_with_result(result)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.resume, {"decision": "ALLOWED_RESUMED", "reason": "provenance validated"})
        # Projection only: DirectorRunEvidence carries no field that could be
        # mistaken for the Director itself authorizing a resume.
        self.assertFalse(hasattr(ev, "resume_allowed"))
        self.assertFalse(hasattr(ev, "resume_authorized"))

    def test_result_remains_backward_compatible_alongside_evidence(self):
        evidence = self.make_evidence(work_product_present=True)
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-compat", evidence_dir=evidence,
            work_status="SUCCESS", work_product_present=True,
        )
        svc, handle = self._run_with_result(result)
        summary = svc.result(handle.pipeline_id)
        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(summary.worker_state, ev.worker_state)
        self.assertEqual(summary.work_status, ev.work_status)
        self.assertEqual(summary.evidence_dir, ev.evidence_dir)
        self.assertTrue(summary.work_product_present)
        self.assertTrue(ev.work_product_present)

    def test_no_subprocess_cli_usage_in_evidence_path(self):
        source = Path(fd.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("subprocess.Popen(", source)
        self.assertNotIn("subprocess.call(", source)

    def test_no_unrestricted_shell_api_exists_alongside_evidence(self):
        forbidden = {"shell", "exec", "arbitrary_subprocess", "run_shell", "execute_command"}
        public_methods = {name for name in dir(fd.FabricDirectorService) if not name.startswith("_")}
        self.assertIn("evidence", public_methods)
        self.assertEqual(public_methods & forbidden, set())


# ---------------------------------------------------------------------------
class DecisionProjectionTests(DirectorTestBase):
    """FDB-2-2. decision()/DirectorRunDecision: a deterministic, fail-closed
    operational classification over the SAME result()/evidence() projections
    - never a second Runner, never a safety/resume recomputation, never a
    provider-prose parse."""

    def _seed(
        self, run_id, *, state, checkpoint_policy=None, checkpoint_commit=None,
        provider_condition=None, next_eligible_utc=None, evidence_complete=True,
        evidence_error=None, safety_verdict=None, unauthorized=None,
        work_product_present=False, work_status="SUCCESS", runner_state=None,
        make_evidence_dir=True,
    ) -> Path:
        evidence_dir = None
        if make_evidence_dir:
            evidence_dir = self.make_evidence(
                work_product_present=work_product_present, unauthorized=unauthorized or [],
                safety_verdict={"verdict": safety_verdict, "reasons": []} if safety_verdict else None,
            )
        entry = {
            "state": state, "checkpoint_policy": checkpoint_policy, "checkpoint_commit": checkpoint_commit,
            "provider_condition": provider_condition, "next_eligible_utc": next_eligible_utc,
        }
        worker_result = {
            "attempts": [{"evidence_complete": evidence_complete, "evidence_error": evidence_error}],
            "work_status": work_status, "runner_state": runner_state or state,
            "evidence_dir": str(evidence_dir) if evidence_dir else None,
        }
        self.seed_pipeline_result(run_id, "w1", entry, worker_result=worker_result)
        return evidence_dir

    # 1-3: SUCCESS / checkpoint precedence -----------------------------------

    def test_success_safe_complete_ready_for_host_audit(self):
        svc = self.service()
        self._seed("run-d1", state="SUCCESS", safety_verdict="SAFE", work_product_present=True)
        d = svc.decision("run-d1")
        self.assertEqual(d.decision_code, "READY_FOR_HOST_AUDIT")
        self.assertTrue(d.terminal)
        self.assertFalse(d.human_action_required)
        self.assertEqual(d.next_action, "HOST_AUDIT")

    def test_success_checkpoint_present_ready_for_host_audit(self):
        svc = self.service()
        self._seed(
            "run-d2", state="SUCCESS", safety_verdict="SAFE",
            checkpoint_policy="ON_SUCCESS", checkpoint_commit="deadbeef",
        )
        d = svc.decision("run-d2")
        self.assertEqual(d.decision_code, "READY_FOR_HOST_AUDIT")
        self.assertEqual(d.checkpoint_commit, "deadbeef")

    def test_success_checkpoint_missing_checkpoint_review_required(self):
        svc = self.service()
        self._seed(
            "run-d3", state="SUCCESS", safety_verdict="SAFE",
            checkpoint_policy="ON_SUCCESS", checkpoint_commit=None,
        )
        d = svc.decision("run-d3")
        self.assertEqual(d.decision_code, "CHECKPOINT_REVIEW_REQUIRED")
        self.assertTrue(d.terminal)
        self.assertTrue(d.human_action_required)
        self.assertEqual(d.next_action, "REVIEW_CHECKPOINT_EVIDENCE")
        self.assertIn("CHECKPOINT_MISSING", d.reason_codes)

    # 4-6: SAFETY / EVIDENCE precedence over SUCCESS -------------------------

    def test_unauthorized_path_precedence_over_success(self):
        svc = self.service()
        self._seed("run-d4", state="SUCCESS", safety_verdict="SAFE", unauthorized=["M src/bad.py"])
        d = svc.decision("run-d4")
        self.assertEqual(d.decision_code, "SAFETY_REVIEW_REQUIRED")
        self.assertIn("UNAUTHORIZED_PATHS", d.reason_codes)

    def test_non_safe_verdict_precedence_over_success(self):
        svc = self.service()
        self._seed("run-d5", state="SUCCESS", safety_verdict="FAILED_SAFETY")
        d = svc.decision("run-d5")
        self.assertEqual(d.decision_code, "SAFETY_REVIEW_REQUIRED")
        self.assertIn("SAFETY_VERDICT_NOT_SAFE", d.reason_codes)

    def test_evidence_incomplete_precedence_over_success(self):
        svc = self.service()
        self._seed("run-d6", state="SUCCESS", safety_verdict="SAFE", evidence_complete=False, evidence_error="boom")
        d = svc.decision("run-d6")
        self.assertEqual(d.decision_code, "EVIDENCE_REVIEW_REQUIRED")
        self.assertIn("EVIDENCE_INCOMPLETE", d.reason_codes)

    # 7-10: PROVIDER AUTH / QUOTA --------------------------------------------

    def test_provider_auth_block_via_worker_state(self):
        svc = self.service()
        self._seed("run-d7", state="BLOCKED_PROVIDER_AUTH", make_evidence_dir=False)
        d = svc.decision("run-d7")
        self.assertEqual(d.decision_code, "PROVIDER_AUTH_REQUIRED")
        self.assertTrue(d.terminal)
        self.assertTrue(d.human_action_required)
        self.assertEqual(d.next_action, "RESTORE_PROVIDER_AUTH")

    def test_provider_auth_block_via_structured_condition(self):
        svc = self.service()
        self._seed("run-d8", state="QUEUED", provider_condition="PROVIDER_AUTH_BLOCKED", make_evidence_dir=False)
        d = svc.decision("run-d8")
        self.assertEqual(d.decision_code, "PROVIDER_AUTH_REQUIRED")

    def test_provider_quota_wait(self):
        svc = self.service()
        self._seed(
            "run-d9", state="WAITING_PROVIDER_QUOTA", provider_condition="PROVIDER_QUOTA_EXHAUSTED",
            next_eligible_utc="2026-01-01T00:00:00Z", make_evidence_dir=False,
        )
        d = svc.decision("run-d9")
        self.assertEqual(d.decision_code, "WAITING_PROVIDER")
        self.assertFalse(d.terminal)
        self.assertFalse(d.human_action_required)
        self.assertEqual(d.next_action, "WAIT_UNTIL_PROVIDER_ELIGIBLE")

    def test_next_eligible_utc_preserved(self):
        svc = self.service()
        self._seed(
            "run-d10", state="WAITING_PROVIDER_QUOTA", provider_condition="PROVIDER_QUOTA_EXHAUSTED",
            next_eligible_utc="2026-02-02T00:00:00Z", make_evidence_dir=False,
        )
        d = svc.decision("run-d10")
        self.assertEqual(d.next_eligible_utc, "2026-02-02T00:00:00Z")

    # 11-15: transient pipeline states ---------------------------------------

    def test_transient_states_map_to_in_progress(self):
        svc = self.service()
        for i, state in enumerate(["QUEUED", "WAITING_DEPENDENCY", "READY", "RUNNING", "RETRY_WAIT"]):
            run_id = f"run-d-transient-{i}"
            self._seed(run_id, state=state, make_evidence_dir=False)
            d = svc.decision(run_id)
            self.assertEqual(d.decision_code, "IN_PROGRESS", state)
            self.assertFalse(d.terminal, state)
            self.assertFalse(d.human_action_required, state)
            self.assertEqual(d.next_action, "WAIT_FOR_RUNNER", state)

    # 16-17: INTERRUPTED ------------------------------------------------------

    def test_interrupted_with_work_product_recovery_review(self):
        svc = self.service()
        self._seed("run-d16", state="INTERRUPTED", work_product_present=True, work_status=None)
        d = svc.decision("run-d16")
        self.assertEqual(d.decision_code, "RECOVERY_REVIEW_REQUIRED")
        self.assertTrue(d.terminal)
        self.assertTrue(d.human_action_required)
        self.assertTrue(d.work_product_present)

    def test_interrupted_without_work_product_recovery_review(self):
        svc = self.service()
        self._seed("run-d17", state="INTERRUPTED", work_product_present=False, work_status=None)
        d = svc.decision("run-d17")
        self.assertEqual(d.decision_code, "RECOVERY_REVIEW_REQUIRED")
        self.assertFalse(d.work_product_present)

    # 18-21: PARTIAL / BLOCKED / FAILED / CANCELLED --------------------------

    def test_partial_maps_to_partial_review_required(self):
        svc = self.service()
        self._seed("run-d18", state="PARTIAL", work_status="PARTIAL")
        d = svc.decision("run-d18")
        self.assertEqual(d.decision_code, "PARTIAL_REVIEW_REQUIRED")

    def test_blocked_maps_to_blocked_review_required(self):
        svc = self.service()
        self._seed("run-d19", state="BLOCKED", make_evidence_dir=False)
        d = svc.decision("run-d19")
        self.assertEqual(d.decision_code, "BLOCKED_REVIEW_REQUIRED")

    def test_failed_maps_to_failed_review_required(self):
        svc = self.service()
        self._seed("run-d20", state="FAILED", make_evidence_dir=False)
        d = svc.decision("run-d20")
        self.assertEqual(d.decision_code, "FAILED_REVIEW_REQUIRED")

    def test_cancelled_maps_to_cancelled(self):
        svc = self.service()
        self._seed("run-d21", state="CANCELLED", make_evidence_dir=False)
        d = svc.decision("run-d21")
        self.assertEqual(d.decision_code, "CANCELLED")
        self.assertFalse(d.human_action_required)
        self.assertEqual(d.next_action, "NONE")

    # 22: unknown/missing worker state ---------------------------------------

    def test_unknown_worker_state_fails_closed(self):
        svc = self.service()
        self._seed("run-d22", state="SOME_UNEXPECTED_STATE", make_evidence_dir=False)
        d = svc.decision("run-d22")
        self.assertEqual(d.decision_code, "REVIEW_REQUIRED")
        self.assertTrue(d.terminal)
        self.assertTrue(d.human_action_required)
        self.assertIn("UNKNOWN_STRUCTURED_STATE", d.reason_codes)

    # 23-24: no prose parsing / no safety recomputation ----------------------

    def test_decision_ignores_provider_prose(self):
        svc = self.service()
        self._seed("run-d23", state="SUCCESS", safety_verdict="SAFE")
        worker_result_path = self.state_root / "run-d23" / "workers" / "w1" / "result.json"
        payload = json.loads(worker_result_path.read_text(encoding="utf-8"))
        payload["cli_output"] = {"result": "HUMAN PROSE THAT MUST NEVER BE PARSED: FAIL EVERYTHING"}
        worker_result_path.write_text(json.dumps(payload), encoding="utf-8")
        d = svc.decision("run-d23")
        self.assertEqual(d.decision_code, "READY_FOR_HOST_AUDIT")

    def test_safety_verdict_never_recomputed(self):
        svc = self.service()
        self._seed("run-d24", state="SUCCESS", safety_verdict="SAFE")
        with mock.patch("scripts.ai.fabric_director.claude_runner.evaluate_write_mode_safety") as recompute:
            d = svc.decision("run-d24")
        recompute.assert_not_called()
        self.assertEqual(d.safety_verdict, "SAFE")
        self.assertEqual(d.decision_code, "READY_FOR_HOST_AUDIT")

    # 25-27: backward compatibility -------------------------------------------

    def test_result_and_evidence_remain_backward_compatible(self):
        svc = self.service()
        self._seed(
            "run-d25", state="SUCCESS", safety_verdict="SAFE",
            checkpoint_policy="ON_SUCCESS", checkpoint_commit="cafed00d",
        )
        summary = svc.result("run-d25")
        ev = svc.evidence("run-d25")
        svc.decision("run-d25")
        self.assertEqual(summary, svc.result("run-d25"))
        self.assertEqual(ev, svc.evidence("run-d25"))

    def test_old_decision_required_and_decision_type_unchanged(self):
        svc = self.service()
        self._seed("run-d27", state="BLOCKED_PROVIDER_AUTH", make_evidence_dir=False)
        summary = svc.result("run-d27")
        self.assertTrue(summary.decision_required)
        self.assertEqual(summary.decision_type, "PROVIDER_AUTH")
        d = svc.decision("run-d27")
        self.assertEqual(d.decision_code, "PROVIDER_AUTH_REQUIRED")

    # 28-30: no durable store / no subprocess / no shell API ----------------

    def test_decision_creates_no_files(self):
        svc = self.service()
        self._seed("run-d28", state="SUCCESS", safety_verdict="SAFE")
        before = sorted(str(p) for p in self.root.rglob("*") if p.is_file())
        svc.decision("run-d28")
        after = sorted(str(p) for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(before, after)

    def test_decision_path_has_no_subprocess_usage(self):
        source = Path(fd.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("subprocess.Popen(", source)
        self.assertNotIn("subprocess.call(", source)

    def test_decision_adds_no_unrestricted_shell_api(self):
        forbidden = {"shell", "exec", "arbitrary_subprocess", "run_shell", "execute_command"}
        public_methods = {name for name in dir(fd.FabricDirectorService) if not name.startswith("_")}
        self.assertIn("decision", public_methods)
        self.assertEqual(public_methods & forbidden, set())

    # 31-34: determinism and precedence under contradictory input -----------

    def test_decision_is_deterministic_for_identical_structured_evidence(self):
        svc = self.service()
        self._seed(
            "run-d31", state="SUCCESS", safety_verdict="SAFE",
            checkpoint_policy="ON_SUCCESS", checkpoint_commit="abc123",
        )
        d1 = svc.decision("run-d31")
        d2 = svc.decision("run-d31")
        self.assertEqual(d1, d2)

    def test_safety_precedence_over_contradictory_evidence_and_provider_state(self):
        svc = self.service()
        self._seed(
            "run-d32", state="WAITING_PROVIDER_QUOTA", provider_condition="PROVIDER_QUOTA_EXHAUSTED",
            safety_verdict="FAILED_SAFETY", unauthorized=["M src/bad.py"], evidence_complete=False,
        )
        d = svc.decision("run-d32")
        self.assertEqual(d.decision_code, "SAFETY_REVIEW_REQUIRED")

    def test_evidence_incomplete_precedence_over_provider_and_state(self):
        svc = self.service()
        self._seed(
            "run-d33", state="WAITING_PROVIDER_QUOTA", provider_condition="PROVIDER_QUOTA_EXHAUSTED",
            safety_verdict="SAFE", evidence_complete=False,
        )
        d = svc.decision("run-d33")
        self.assertEqual(d.decision_code, "EVIDENCE_REVIEW_REQUIRED")

    def test_provider_auth_precedence_over_contradictory_quota_state(self):
        svc = self.service()
        self._seed(
            "run-d34", state="WAITING_PROVIDER_QUOTA", provider_condition="PROVIDER_AUTH_BLOCKED",
            safety_verdict="SAFE",
        )
        d = svc.decision("run-d34")
        self.assertEqual(d.decision_code, "PROVIDER_AUTH_REQUIRED")


# ---------------------------------------------------------------------------
_ABSENT = object()


class EvidenceTruthfulnessTests(DirectorTestBase):
    """FCP-FIX-07 Objective A. `evidence_complete` is tri-state (True/False/
    None) and only ever True/False when durably recorded - never defaulted
    to True. result()/evidence()/decision() always agree on it."""

    def _seed(
        self, run_id, *, state="SUCCESS", attempt_flag=_ABSENT, attempt_result_flag=_ABSENT,
        metadata_flag=_ABSENT, attempt_evidence_dir=_ABSENT, provider_condition=None, work_status="SUCCESS",
        checkpoint_policy=None,
    ) -> Path:
        evidence_dir = self.make_evidence(safety_verdict={"verdict": "SAFE", "reasons": []})
        for name, flag in (("result.json", attempt_result_flag), ("metadata.json", metadata_flag)):
            if flag is not _ABSENT:
                payload = json.loads((evidence_dir / name).read_text(encoding="utf-8"))
                payload["evidence_complete"] = flag
                (evidence_dir / name).write_text(json.dumps(payload), encoding="utf-8")
        attempt = {"evidence_error": None}
        if attempt_flag is not _ABSENT:
            attempt["evidence_complete"] = attempt_flag
        if attempt_evidence_dir is not _ABSENT:
            attempt["evidence_dir"] = attempt_evidence_dir
        worker_result = {
            "attempts": [attempt], "work_status": work_status, "runner_state": state,
            "evidence_dir": str(evidence_dir),
        }
        self.seed_pipeline_result(
            run_id, "w1", {"state": state, "provider_condition": provider_condition, "checkpoint_policy": checkpoint_policy},
            worker_result=worker_result,
        )
        return evidence_dir

    def _projections(self, svc, run_id):
        summary, ev, d = svc.result(run_id), svc.evidence(run_id), svc.decision(run_id)
        # result() and evidence() (and decision(), built from them) must agree.
        self.assertIs(summary.evidence_complete, ev.evidence_complete)
        self.assertIs(d.evidence_complete, summary.evidence_complete)
        return summary, ev, d

    def test_missing_attempt_flag_is_unknown_not_true(self):
        svc = self.service()
        self._seed("run-e1")
        summary, _, d = self._projections(svc, "run-e1")
        self.assertIsNone(summary.evidence_complete)
        # Work status is preserved independently from evidence health.
        self.assertEqual(summary.work_status, "SUCCESS")
        self.assertEqual(summary.worker_state, "SUCCESS")

    def test_terminal_success_with_unknown_evidence_is_never_ready_for_audit(self):
        svc = self.service()
        self._seed("run-e2")
        _, _, d = self._projections(svc, "run-e2")
        self.assertNotEqual(d.decision_code, "READY_FOR_HOST_AUDIT")
        self.assertEqual(d.decision_code, "EVIDENCE_REVIEW_REQUIRED")
        self.assertTrue(d.terminal)
        self.assertTrue(d.human_action_required)
        self.assertEqual(d.reason_codes, ("EVIDENCE_COMPLETENESS_UNKNOWN",))

    def test_unknown_evidence_precedes_checkpoint_review(self):
        svc = self.service()
        self._seed("run-e2b", checkpoint_policy="ON_SUCCESS")
        _, _, d = self._projections(svc, "run-e2b")
        self.assertEqual(d.decision_code, "EVIDENCE_REVIEW_REQUIRED")

    def test_recorded_true_is_true_and_ready_for_audit(self):
        svc = self.service()
        self._seed("run-e3", attempt_flag=True)
        summary, _, d = self._projections(svc, "run-e3")
        self.assertIs(summary.evidence_complete, True)
        self.assertEqual(d.decision_code, "READY_FOR_HOST_AUDIT")

    def test_recorded_false_is_false_and_fails_closed(self):
        svc = self.service()
        # Even a contradictory later artifact never overrides the attempt record.
        self._seed("run-e4", attempt_flag=False, attempt_result_flag=True)
        summary, _, d = self._projections(svc, "run-e4")
        self.assertIs(summary.evidence_complete, False)
        self.assertEqual(d.decision_code, "EVIDENCE_REVIEW_REQUIRED")
        self.assertEqual(d.reason_codes, ("EVIDENCE_INCOMPLETE",))

    def test_malformed_recorded_flag_is_unknown_never_coerced(self):
        for i, flag in enumerate(("true", 1, None, [], {})):
            with self.subTest(flag=flag):
                svc = self.service()
                run_id = f"run-e5-{i}"
                self._seed(run_id, attempt_flag=flag, attempt_result_flag=True)
                summary, _, d = self._projections(svc, run_id)
                self.assertIsNone(summary.evidence_complete)
                self.assertEqual(d.decision_code, "EVIDENCE_REVIEW_REQUIRED")

    def test_legacy_attempt_without_flag_uses_attempt_own_result_json(self):
        # e.g. FABRIC H2-A quota reconciliation: Runner ends the attempt before
        # recording the flag, but claude_runner's own result.json carries it.
        cases = ((True, "READY_FOR_HOST_AUDIT"), (False, "EVIDENCE_REVIEW_REQUIRED"))
        for i, (flag, code) in enumerate(cases):
            for same_dir in (False, True):
                with self.subTest(flag=flag, attempt_records_own_dir=same_dir):
                    svc = self.service()
                    run_id = f"run-e6-{i}-{same_dir}"
                    evidence_dir = self._seed(run_id, attempt_result_flag=flag)
                    if same_dir:
                        path = self.state_root / run_id / "workers" / "w1" / "result.json"
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        payload["attempts"][-1]["evidence_dir"] = str(evidence_dir)
                        path.write_text(json.dumps(payload), encoding="utf-8")
                    summary, _, d = self._projections(svc, run_id)
                    self.assertIs(summary.evidence_complete, flag)
                    self.assertEqual(d.decision_code, code)

    def test_legacy_metadata_flag_only_proves_incompleteness(self):
        cases = (("meta-false", False, False), ("meta-true", True, None))
        for label, flag, expected in cases:
            with self.subTest(label):
                svc = self.service()
                run_id = f"run-e7-{label}"
                self._seed(run_id, metadata_flag=flag)
                summary, _, _ = self._projections(svc, run_id)
                self.assertIs(summary.evidence_complete, expected)

    def test_fallback_ignored_when_artifacts_are_not_the_attempts_own(self):
        svc = self.service()
        self._seed("run-e8", attempt_result_flag=True, attempt_evidence_dir=str(self.root / "elsewhere"))
        summary, _, d = self._projections(svc, "run-e8")
        self.assertIsNone(summary.evidence_complete)
        self.assertEqual(d.decision_code, "EVIDENCE_REVIEW_REQUIRED")

    def test_no_attempts_is_unknown(self):
        svc = self.service()
        self.seed_pipeline_result("run-e9", "w1", {"state": "QUEUED"}, worker_result={"attempts": []})
        summary, _, d = self._projections(svc, "run-e9")
        self.assertIsNone(summary.evidence_complete)
        self.assertEqual(d.decision_code, "IN_PROGRESS")

    def test_non_success_states_with_unknown_evidence_keep_their_decisions(self):
        cases = (
            ("WAITING_PROVIDER_QUOTA", None, "WAITING_PROVIDER"),
            ("QUEUED", "PROVIDER_QUOTA_EXHAUSTED", "WAITING_PROVIDER"),
            ("BLOCKED_PROVIDER_AUTH", None, "PROVIDER_AUTH_REQUIRED"),
            ("RUNNING", None, "IN_PROGRESS"),
            ("RETRY_WAIT", None, "IN_PROGRESS"),
            ("INTERRUPTED", None, "RECOVERY_REVIEW_REQUIRED"),
            ("FAILED", None, "FAILED_REVIEW_REQUIRED"),
            ("PARTIAL", None, "PARTIAL_REVIEW_REQUIRED"),
            ("BLOCKED", None, "BLOCKED_REVIEW_REQUIRED"),
            ("CANCELLED", None, "CANCELLED"),
        )
        for state, condition, code in cases:
            with self.subTest(state=state, condition=condition):
                svc = self.service()
                run_id = f"run-e10-{state}-{condition}"
                self._seed(run_id, state=state, provider_condition=condition, work_status=None)
                summary, _, d = self._projections(svc, run_id)
                self.assertIsNone(summary.evidence_complete)
                self.assertEqual(d.decision_code, code)

    def test_end_to_end_runner_recorded_flag_is_projected(self):
        for i, flag in enumerate((True, False)):
            with self.subTest(flag=flag):
                evidence = self.make_evidence()
                result = runner.WorkOrderResult(
                    state=RS.SUCCESS, exit_code=0, run_id=f"run-e11-{i}", evidence_dir=evidence,
                    work_status="SUCCESS", evidence_complete=flag, evidence_error=None if flag else "boom",
                )
                svc = self.service(executor=lambda request, r=result: r)
                summary = svc.run(svc.submit(self.spec()))
                self.assertIs(summary.evidence_complete, flag)
                self.assertIs(svc.evidence(summary.run_id).evidence_complete, flag)


# ---------------------------------------------------------------------------
class RecoveryTests(DirectorTestBase):
    """FDB-3-1. recover()/DirectorRecoverySpec: the governed recovery/resume
    gateway. Eligibility and the resumed worktree/scopes are read ONLY from
    this service's OWN existing decision()/evidence() projections - never
    stdout/stderr/provider prose. recover() PREPARES/SUBMITS a brand NEW
    pipeline (via the SAME `_submit` helper submit() uses) and never executes
    it; `claude_runner.evaluate_resume` remains the sole resume authority."""

    def _seed_prior(
        self, run_id, *, state, work_product_present=True, work_product_data=None,
        worker_id="w1", safety_verdict=None, unauthorized=None, evidence_complete=True,
        evidence_error=None, provider="claude", prior_manifest_worker=None, write_prior_manifest=True,
    ) -> Path:
        if write_prior_manifest:
            # Runner always persists pipeline.json (with its executed manifest
            # snapshot) in the SAME `_save_pipeline` call that writes
            # pipeline_result.json; a legacy worker entry has no
            # completion_policy key at all (= provider_verdict).
            self._seed_prior_manifest(run_id, prior_manifest_worker or {"id": worker_id})
        if work_product_data is None and work_product_present:
            work_product_data = {
                "worktree": str(self.target), "authorized_scopes": ["docs/"],
                "provider": provider, "worker_id": worker_id, "attempt": 1,
            }
        evidence_dir = self.make_evidence(
            work_product_present=work_product_present, work_product_data=work_product_data,
            unauthorized=unauthorized or [],
            safety_verdict={"verdict": safety_verdict, "reasons": []} if safety_verdict else None,
        )
        entry = {"state": state, "provider": provider, "requested_provider": provider}
        worker_result = {
            "attempts": [{"evidence_complete": evidence_complete, "evidence_error": evidence_error}],
            "work_status": state, "runner_state": state,
            "evidence_dir": str(evidence_dir),
        }
        self.seed_pipeline_result(run_id, worker_id, entry, worker_result=worker_result)
        return evidence_dir

    def _seed_prior_manifest(self, run_id, worker_entry, *, manifest_sha256=None, pipeline_id=None) -> None:
        worker = {"worktree": str(self.target), "work_order": "work_order.md", "mode": "write"}
        worker.update(worker_entry)
        manifest = {"pipeline_id": pipeline_id or run_id, "workers": [worker]}
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        payload = {
            "schema_version": 1, "pipeline_id": run_id,
            "manifest_sha256": manifest_sha256 or hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "manifest": manifest,
        }
        (self.state_root / run_id).mkdir(parents=True, exist_ok=True)
        (self.state_root / run_id / "pipeline.json").write_text(json.dumps(payload), encoding="utf-8")

    def _seed_acceptance_prior(self, run_id="run-r1", commands=("pytest -q", "ruff check ."), **kw) -> Path:
        return self._seed_prior(run_id, state="FAILED", prior_manifest_worker={
            "id": "w1", "completion_policy": "runner_acceptance", "acceptance_commands": list(commands),
        }, **kw)

    def _manifest_worker(self, handle) -> dict:
        return json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))["workers"][0]

    def recovery_spec(self, **extra) -> fd.DirectorRecoverySpec:
        kw = dict(prior_run_id="run-r1", recovery_work_order_text="Recover please.\n", action="RESUME_WORK_PRODUCT")
        kw.update(extra)
        return fd.DirectorRecoverySpec(**kw)

    # 1-3: explicit host action / recovery work order -------------------------

    def test_recovery_spec_requires_explicit_action(self):  # 1
        with self.assertRaises(TypeError):
            fd.DirectorRecoverySpec(prior_run_id="run-r1", recovery_work_order_text="x")

    def test_wrong_action_refused(self):  # 2
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec(action="JUST_DO_IT"))
        self.assertEqual(ctx.exception.code, "RECOVERY_ACTION_NOT_CONFIRMED")

    def test_empty_recovery_work_order_text_refused(self):  # 3
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec(recovery_work_order_text="   "))
        self.assertEqual(ctx.exception.code, "RECOVERY_WORK_ORDER_REQUIRED")

    # 4-6: prior work product / prior worker checks ----------------------------

    def test_missing_work_product_refused(self):  # 4
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED", work_product_present=False)
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec())
        self.assertEqual(ctx.exception.code, "NO_WORK_PRODUCT")

    def test_prior_worker_id_mismatch_refused(self):  # 5
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED", worker_id="w1")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec(prior_worker_id="not-w1"))
        self.assertEqual(ctx.exception.code, "UNKNOWN_WORKER")

    def test_malformed_work_product_refused(self):  # 6
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED", work_product_data={"worktree": "", "authorized_scopes": []})
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec())
        self.assertEqual(ctx.exception.code, "WORK_PRODUCT_INVALID")

    # 7-9: ineligible decision codes -------------------------------------------

    def test_unsafe_decision_not_eligible(self):  # 7
        svc = self.service()
        self._seed_prior("run-r1", state="SUCCESS", unauthorized=["M src/bad.py"])
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec())
        self.assertEqual(ctx.exception.code, "RECOVERY_NOT_ELIGIBLE")

    def test_evidence_incomplete_decision_not_eligible(self):  # 8
        svc = self.service()
        self._seed_prior("run-r1", state="SUCCESS", evidence_complete=False, evidence_error="boom")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec())
        self.assertEqual(ctx.exception.code, "RECOVERY_NOT_ELIGIBLE")

    def test_ready_for_audit_decision_not_eligible(self):  # 9
        svc = self.service()
        self._seed_prior("run-r1", state="SUCCESS", safety_verdict="SAFE")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec())
        self.assertEqual(ctx.exception.code, "RECOVERY_NOT_ELIGIBLE")

    # 10-13: eligible decision codes --------------------------------------------

    def test_failed_review_required_is_eligible(self):  # 10
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        self.assertTrue(handle.validated)

    def test_partial_review_required_is_eligible(self):  # 11
        svc = self.service()
        self._seed_prior("run-r1", state="PARTIAL")
        handle = svc.recover(self.recovery_spec())
        self.assertTrue(handle.validated)

    def test_recovery_review_required_is_eligible(self):  # 12
        svc = self.service()
        self._seed_prior("run-r1", state="INTERRUPTED")
        handle = svc.recover(self.recovery_spec())
        self.assertTrue(handle.validated)

    def test_blocked_review_required_is_eligible(self):  # 13
        svc = self.service()
        self._seed_prior("run-r1", state="BLOCKED")
        handle = svc.recover(self.recovery_spec())
        self.assertTrue(handle.validated)

    # 14-15: new pipeline, original never mutated -------------------------------

    def test_recover_creates_new_pipeline_id(self):  # 14
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        self.assertNotEqual(handle.pipeline_id, "run-r1")

    def test_original_pipeline_files_remain_untouched(self):  # 15
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        result_path = self.state_root / "run-r1" / "pipeline_result.json"
        worker_result_path = self.state_root / "run-r1" / "workers" / "w1" / "result.json"
        before_result, before_worker_result = result_path.read_bytes(), worker_result_path.read_bytes()
        handle = svc.recover(self.recovery_spec())
        svc.run(handle)
        self.assertEqual(result_path.read_bytes(), before_result)
        self.assertEqual(worker_result_path.read_bytes(), before_worker_result)

    # 16-17: manifest resume_from contract ---------------------------------------

    def test_recovery_manifest_has_exact_resume_from_path(self):  # 16
        svc = self.service()
        evidence_dir = self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["resume_from"], str(evidence_dir / "work_product.json"))

    def test_ordinary_submit_manifest_has_no_resume_from_key(self):  # 17
        svc = self.service()
        handle = svc.submit(self.spec())
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertNotIn("resume_from", manifest["workers"][0])

    # 18-19: authorize paths ------------------------------------------------------

    def test_default_authorize_paths_come_from_work_product(self):  # 18
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED", work_product_data={
            "worktree": str(self.target), "authorized_scopes": ["src/", "docs/readme.md"],
            "provider": "claude", "worker_id": "w1", "attempt": 2,
        })
        handle = svc.recover(self.recovery_spec())
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["authorize_path"], ["src/", "docs/readme.md"])

    def test_explicit_authorize_paths_used_exactly(self):  # 19
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED", work_product_data={
            "worktree": str(self.target), "authorized_scopes": ["src/"],
            "provider": "claude", "worker_id": "w1", "attempt": 1,
        })
        handle = svc.recover(self.recovery_spec(authorize_paths=["only_this.txt"]))
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["authorize_path"], ["only_this.txt"])

    # 20-21: provider resolution ---------------------------------------------------

    def test_default_provider_comes_from_work_product(self):  # 20
        svc = self.service(
            provider_map={"claude": FakeProvider("claude"), "codex": FakeProvider("codex")},
            registered_providers=["claude", "codex"],
        )
        self._seed_prior("run-r1", state="FAILED", provider="codex")
        handle = svc.recover(self.recovery_spec())
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["provider"], "codex")
        self.assertTrue(handle.validated)

    def test_provider_override_accepted_and_validated(self):  # 21
        svc = self.service(
            provider_map={"claude": FakeProvider("claude"), "codex": FakeProvider("codex")},
            registered_providers=["claude", "codex"],
        )
        self._seed_prior("run-r1", state="FAILED", provider="claude")
        handle = svc.recover(self.recovery_spec(provider_override="codex"))
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["provider"], "codex")
        self.assertTrue(handle.validated)

        bad = svc.recover(self.recovery_spec(provider_override="totally-unknown-provider"))
        self.assertFalse(bad.validated)
        self.assertTrue(any(e["code"] == "UNKNOWN_PROVIDER" for e in bad.validation_errors))

    # 22-23: durable lineage metadata ------------------------------------------

    def test_lineage_metadata_present_in_manifest(self):  # 22
        svc = self.service()
        evidence_dir = self._seed_prior("run-r1", state="FAILED", worker_id="w1", work_product_data={
            "worktree": str(self.target), "authorized_scopes": ["docs/"], "provider": "claude",
            "worker_id": "w1", "attempt": 3,
        })
        handle = svc.recover(self.recovery_spec())
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        meta = manifest["workers"][0]["metadata"]
        self.assertEqual(meta["recovered_from_director_run_id"], "run-r1")
        self.assertEqual(meta["recovered_from_worker_id"], "w1")
        self.assertEqual(meta["recovered_from_attempt"], 3)
        self.assertEqual(meta["recovered_from_work_product"], str(evidence_dir / "work_product.json"))

    def test_reserved_lineage_metadata_collision_fails_closed(self):  # 23
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec(metadata={"recovered_from_director_run_id": "evil"}))
        self.assertEqual(ctx.exception.code, "RECOVERY_METADATA_RESERVED_KEY")

    # 24-26: host-supplied work order / execution gateway ------------------------

    def test_recovery_work_order_is_host_supplied_not_original(self):  # 24
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec(recovery_work_order_text="Please finish the migration.\n"))
        persisted = Path(handle.work_order_path).read_bytes().decode("utf-8")
        self.assertEqual(persisted, "Please finish the migration.\n")

    def test_recover_does_not_execute_pipeline(self):  # 25, 32
        executor = mock.Mock()
        svc = self.service(executor=executor)
        self._seed_prior("run-r1", state="FAILED")
        svc.recover(self.recovery_spec())
        executor.assert_not_called()

    def test_recover_then_run_uses_normal_pipeline_runner_path(self):  # 26
        captured = {}

        def executor(request):
            captured["resume_from"] = request.resume_from
            return runner.WorkOrderResult(
                state=RS.SUCCESS, exit_code=0, run_id="run-recovered", evidence_dir=None, work_status="SUCCESS",
            )

        svc = self.service(executor=executor)
        evidence_dir = self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(captured["resume_from"], str(evidence_dir / "work_product.json"))

    # 27-29: recovered execution outcomes are never reinterpreted ---------------

    def test_resume_refused_is_projected_as_blocked_without_override(self):  # 27
        executor = lambda request: runner.WorkOrderResult(
            state=RS.RESUME_REFUSED, exit_code=runner.EXIT_CODES.get(RS.RESUME_REFUSED, 1),
            run_id="run-resumed", evidence_dir=None,
        )
        svc = self.service(executor=executor)
        self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "BLOCKED")
        self.assertEqual(summary.state_reason, "RESUME_REFUSED")
        d = svc.decision(handle.pipeline_id)
        self.assertEqual(d.decision_code, "BLOCKED_REVIEW_REQUIRED")

    def test_recovered_success_follows_normal_result_path(self):  # 28
        executor = lambda request: runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-recovered-ok", evidence_dir=None, work_status="SUCCESS",
        )
        svc = self.service(executor=executor)
        self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "SUCCESS")
        d = svc.decision(handle.pipeline_id)
        self.assertEqual(d.decision_code, "READY_FOR_HOST_AUDIT")

    def test_recovered_invalid_verdict_follows_normal_failed_path(self):  # 29
        executor = lambda request: runner.WorkOrderResult(
            state=RS.WORK_FAILED, exit_code=runner.EXIT_CODES.get(RS.WORK_FAILED, 1),
            run_id="run-recovered-bad", evidence_dir=None, work_status="INVALID_VERDICT",
        )
        svc = self.service(executor=executor)
        self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "FAILED")
        self.assertEqual(summary.work_status, "INVALID_VERDICT")
        d = svc.decision(handle.pipeline_id)
        self.assertEqual(d.decision_code, "FAILED_REVIEW_REQUIRED")

    # 30-33: no bypass / no second engine ----------------------------------------

    def test_decision_has_no_recover_side_effects(self):  # 30
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        with mock.patch.object(svc, "recover") as recover:
            svc.decision("run-r1")
        recover.assert_not_called()

    def test_recover_never_reads_stdout_or_stderr(self):  # 31
        source = Path(fd.__file__).read_text(encoding="utf-8")
        start = source.index("def recover(")
        end = source.index("\n    # -- validate", start)
        body = source[start:end]
        # Skip the method's own docstring (which legitimately documents that
        # recover() never reads provider prose); only the executable code
        # below it matters.
        docstring_end = body.index('"""', body.index('"""') + 3) + 3
        code = body[docstring_end:]
        self.assertNotIn("stdout", code)
        self.assertNotIn("stderr", code)

    def test_no_direct_execute_work_order_call_in_recovery_path(self):  # 32
        source = Path(fd.__file__).read_text(encoding="utf-8")
        self.assertNotIn("execute_work_order(", source)

    def test_no_recovery_specific_persistence_store(self):  # 33
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        before = sorted(str(p) for p in self.director_root.rglob("*") if p.is_file()) if self.director_root.exists() else []
        handle = svc.recover(self.recovery_spec())
        after = sorted(str(p) for p in self.director_root.rglob("*") if p.is_file())
        # Recovery persists exactly the SAME two artifacts submit() always
        # does (work_order.md + manifest.json), under a brand-new director
        # run directory - no additional recovery-only store.
        new_files = sorted(set(after) - set(before))
        self.assertEqual(new_files, sorted([handle.work_order_path, handle.manifest_path]))

    # 34: backward compatibility ---------------------------------------------------

    def test_existing_apis_remain_backward_compatible(self):  # 34
        svc = self.service()
        handle = svc.submit(self.spec())
        self.assertTrue(handle.validated)
        verdict = svc.validate(handle)
        self.assertTrue(verdict["validated"])
        summary = svc.run(handle)
        self.assertEqual(summary.pipeline_id, handle.pipeline_id)
        svc.evidence(handle.pipeline_id)
        svc.decision(handle.pipeline_id)

    # FCP-FIX-04: completion certification continuity ----------------------

    def test_runner_acceptance_prior_carried_forward_without_downgrade(self):
        svc = self.service()
        evidence_dir = self._seed_acceptance_prior()
        handle = svc.recover(self.recovery_spec())
        self.assertTrue(handle.validated, handle.validation_errors)
        worker = self._manifest_worker(handle)
        self.assertEqual(worker["completion_policy"], "runner_acceptance")
        self.assertEqual(worker["acceptance_commands"], ["pytest -q", "ruff check ."])
        # Scope, worktree binding, resume_from and lineage are unchanged.
        self.assertEqual(worker["worktree"], str(self.target))
        self.assertEqual(worker["authorize_path"], ["docs/"])
        self.assertEqual(worker["mode"], providers.MODE_WRITE)
        self.assertEqual(worker["resume_from"], str(evidence_dir / "work_product.json"))
        self.assertEqual(worker["metadata"]["recovered_from_director_run_id"], "run-r1")

    def test_explicit_runner_acceptance_redeclaration_matches_prior(self):
        svc = self.service()
        self._seed_acceptance_prior()
        handle = svc.recover(self.recovery_spec(completion_policy="runner_acceptance"))
        self.assertEqual(self._manifest_worker(handle)["acceptance_commands"], ["pytest -q", "ruff check ."])

    def test_explicit_acceptance_commands_replace_prior_commands(self):
        svc = self.service()
        self._seed_acceptance_prior()
        handle = svc.recover(self.recovery_spec(acceptance_commands=["pytest -q tests/unit"]))
        worker = self._manifest_worker(handle)
        self.assertEqual(worker["completion_policy"], "runner_acceptance")
        self.assertEqual(worker["acceptance_commands"], ["pytest -q tests/unit"])

    def test_explicit_downgrade_to_provider_verdict_refused_before_persisting(self):
        svc = self.service()
        self._seed_acceptance_prior()
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec(completion_policy="provider_verdict"))
        self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_DOWNGRADE")
        self.assertFalse(self.director_root.exists())

    def test_explicit_empty_acceptance_commands_refused_for_acceptance_prior(self):
        svc = self.service()
        self._seed_acceptance_prior()
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec(acceptance_commands=[]))
        self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_REQUIRED")

    def test_provider_verdict_prior_stays_provider_verdict(self):
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED", prior_manifest_worker={
            "id": "w1", "completion_policy": "provider_verdict", "acceptance_commands": [],
        })
        handle = svc.recover(self.recovery_spec())
        worker = self._manifest_worker(handle)
        self.assertEqual(worker["completion_policy"], "provider_verdict")
        self.assertEqual(worker["acceptance_commands"], [])

    def test_legacy_prior_manifest_without_policy_key_is_provider_verdict(self):
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        handle = svc.recover(self.recovery_spec())
        self.assertEqual(self._manifest_worker(handle)["completion_policy"], "provider_verdict")

    def test_upgrade_to_runner_acceptance_requires_explicit_commands(self):
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec(completion_policy="runner_acceptance"))
        self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_REQUIRED")
        handle = svc.recover(self.recovery_spec(completion_policy="runner_acceptance", acceptance_commands=["make test"]))
        worker = self._manifest_worker(handle)
        self.assertEqual(worker["completion_policy"], "runner_acceptance")
        self.assertEqual(worker["acceptance_commands"], ["make test"])

    def test_acceptance_commands_without_acceptance_policy_conflict(self):
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED")
        for extra in ({}, {"completion_policy": "provider_verdict"}):
            with self.assertRaises(fd.DirectorError) as ctx:
                svc.recover(self.recovery_spec(acceptance_commands=["make test"], **extra))
            self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_CONFLICT")

    def test_invalid_explicit_certification_values_refused(self):
        svc = self.service()
        self._seed_acceptance_prior()
        for extra in ({"completion_policy": "whatever"}, {"acceptance_commands": ["  "]},
                      {"acceptance_commands": "pytest"}):
            with self.assertRaises(fd.DirectorError) as ctx:
                svc.recover(self.recovery_spec(**extra))
            self.assertEqual(ctx.exception.code, "INVALID_SPEC")

    def test_unknown_prior_contract_fails_closed_unless_acceptance_declared(self):
        cases = {
            "missing": dict(write_prior_manifest=False),
            "worker-mismatch": dict(prior_manifest_worker={"id": "other", "completion_policy": "runner_acceptance",
                                                          "acceptance_commands": ["x"]}),
        }
        for label, kw in cases.items():
            with self.subTest(label):
                run_id = f"run-{label}"
                svc = self.service()
                self._seed_prior(run_id, state="FAILED", **kw)
                for extra in ({}, {"completion_policy": "provider_verdict"}, {"completion_policy": "runner_acceptance"}):
                    with self.assertRaises(fd.DirectorError) as ctx:
                        svc.recover(self.recovery_spec(prior_run_id=run_id, **extra))
                    self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_UNKNOWN")
                handle = svc.recover(self.recovery_spec(
                    prior_run_id=run_id, completion_policy="runner_acceptance", acceptance_commands=["make test"],
                ))
                self.assertEqual(self._manifest_worker(handle)["acceptance_commands"], ["make test"])

    def test_tampered_prior_manifest_snapshot_is_not_trusted(self):
        svc = self.service()
        self._seed_acceptance_prior()
        # Snapshot rewritten to provider_verdict without its recorded digest.
        self._seed_prior_manifest("run-r1", {"id": "w1", "completion_policy": "provider_verdict"},
                                  manifest_sha256="0" * 64)
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec())
        self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_UNKNOWN")
        # A self-consistent snapshot for a DIFFERENT pipeline is not trusted either.
        self._seed_prior_manifest("run-r1", {"id": "w1"}, pipeline_id="run-other")
        with self.assertRaises(fd.DirectorError) as ctx:
            svc.recover(self.recovery_spec())
        self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_UNKNOWN")

    def test_recovered_runner_acceptance_certifies_missing_verdict_end_to_end(self):
        captured = {}
        result_evidence = self.root / "evidence_recovered_acceptance"
        result_evidence.mkdir()

        def executor(request):
            captured["resume_from"] = request.resume_from
            return runner.WorkOrderResult(
                state=RS.VERDICT_INVALID, exit_code=runner.EXIT_CODES[RS.VERDICT_INVALID],
                run_id="run-recovered-acc", evidence_dir=result_evidence, work_status="INVALID_VERDICT",
            )

        py = sys.executable.replace("\\", "/")
        svc = self.service(executor=executor)
        evidence_dir = self._seed_acceptance_prior(commands=[f"{py} -c exit(0)"])
        handle = svc.recover(self.recovery_spec())
        summary = svc.run(handle)
        self.assertEqual(captured["resume_from"], str(evidence_dir / "work_product.json"))
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.provider_work_status, "INVALID_VERDICT")
        self.assertEqual(summary.work_status_source, runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)
        self.assertEqual(svc.evidence(handle.pipeline_id).acceptance["decision"], "PASSED")

    def test_recovered_explicit_provider_fail_never_overridden_by_acceptance(self):
        result_evidence = self.root / "evidence_recovered_fail"
        result_evidence.mkdir()
        executor = lambda request: runner.WorkOrderResult(
            state=RS.WORK_FAILED, exit_code=runner.EXIT_CODES[RS.WORK_FAILED],
            run_id="run-recovered-fail", evidence_dir=result_evidence, work_status="FAILED",
        )
        py = sys.executable.replace("\\", "/")
        svc = self.service(executor=executor)
        self._seed_acceptance_prior(commands=[f"{py} -c exit(0)"])
        handle = svc.recover(self.recovery_spec())
        self.assertEqual(self._manifest_worker(handle)["completion_policy"], "runner_acceptance")
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "FAILED")
        self.assertEqual(summary.work_status, "FAILED")
        self.assertNotEqual(summary.work_status_source, runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)
        self.assertIsNone(svc.evidence(handle.pipeline_id).acceptance)
        self.assertEqual(svc.decision(handle.pipeline_id).decision_code, "FAILED_REVIEW_REQUIRED")

    # FCP-FIX-07: recovery contract type validation ------------------------

    def test_unhashable_or_non_string_completion_policy_is_controlled_invalid_spec(self):
        for prior in ("acceptance", "verdict"):
            for policy in (["runner_acceptance"], {"runner_acceptance": 1}, {"provider_verdict"}, 1, True):
                with self.subTest(prior=prior, policy=policy):
                    svc = self.service()
                    run_id = f"run-p-{prior}"
                    if not (self.state_root / run_id).exists():
                        if prior == "acceptance":
                            self._seed_acceptance_prior(run_id)
                        else:
                            self._seed_prior(run_id, state="FAILED")
                    with self.assertRaises(fd.DirectorError) as ctx:
                        svc.recover(self.recovery_spec(
                            prior_run_id=run_id, completion_policy=policy, acceptance_commands=["make test"],
                        ))
                    self.assertEqual(ctx.exception.code, "INVALID_SPEC")
                    self.assertFalse(self.director_root.exists())

    def test_invalid_acceptance_command_collections_refused(self):
        svc = self.service()
        self._seed_acceptance_prior()
        for commands in (("pytest -q",), {"pytest -q"}, {"cmd": "pytest -q"}, ["pytest -q", 1], [None], [["x"]], [""]):
            with self.subTest(commands=commands):
                with self.assertRaises(fd.DirectorError) as ctx:
                    svc.recover(self.recovery_spec(completion_policy="runner_acceptance", acceptance_commands=commands))
                self.assertEqual(ctx.exception.code, "INVALID_SPEC")
        self.assertFalse(self.director_root.exists())

    def _seed_raw_prior_manifest(self, run_id, manifest) -> None:
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        payload = {
            "schema_version": 1, "pipeline_id": run_id,
            "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(), "manifest": manifest,
        }
        (self.state_root / run_id / "pipeline.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_malformed_prior_manifest_contract_is_unknown_not_type_error(self):
        worker = {"id": "w1", "worktree": str(self.target), "work_order": "work_order.md", "mode": "write"}
        cases = {
            "policy-list": {"workers": [dict(worker, completion_policy=["runner_acceptance"])]},
            "policy-dict": {"workers": [dict(worker, completion_policy={"runner_acceptance": True})]},
            "policy-null": {"workers": [dict(worker, completion_policy=None)]},
            "policy-int": {"workers": [dict(worker, completion_policy=1)]},
            "commands-dict": {"workers": [dict(worker, completion_policy="runner_acceptance",
                                               acceptance_commands={"a": "pytest"})]},
            "commands-str": {"workers": [dict(worker, completion_policy="runner_acceptance",
                                              acceptance_commands="pytest")]},
            "commands-empty-str": {"workers": [dict(worker, acceptance_commands="")]},
            "commands-non-str": {"workers": [dict(worker, completion_policy="runner_acceptance",
                                                  acceptance_commands=["pytest", 3])]},
            "workers-dict": {"workers": {"w1": worker}},
            "workers-int": {"workers": 7},
            "workers-str": {"workers": "w1"},
        }
        for label, body in cases.items():
            with self.subTest(label):
                run_id = f"run-m-{label}"
                svc = self.service()
                self._seed_prior(run_id, state="FAILED", write_prior_manifest=False)
                self._seed_raw_prior_manifest(run_id, dict(body, pipeline_id=run_id))
                for extra in ({}, {"completion_policy": "provider_verdict"}):
                    with self.assertRaises(fd.DirectorError) as ctx:
                        svc.recover(self.recovery_spec(prior_run_id=run_id, **extra))
                    self.assertEqual(ctx.exception.code, "RECOVERY_CERTIFICATION_UNKNOWN")
                # Explicit human runner_acceptance declaration remains the way out.
                handle = svc.recover(self.recovery_spec(
                    prior_run_id=run_id, completion_policy="runner_acceptance", acceptance_commands=["make test"],
                ))
                worker_out = self._manifest_worker(handle)
                self.assertEqual(worker_out["completion_policy"], "runner_acceptance")
                self.assertEqual(worker_out["acceptance_commands"], ["make test"])

    def test_prior_manifest_null_acceptance_commands_matches_runner_parse(self):
        # Runner's own parse_manifest treats a null acceptance_commands as [].
        svc = self.service()
        self._seed_prior("run-r1", state="FAILED", prior_manifest_worker={"id": "w1", "acceptance_commands": None})
        handle = svc.recover(self.recovery_spec())
        worker = self._manifest_worker(handle)
        self.assertEqual(worker["completion_policy"], "provider_verdict")
        self.assertEqual(worker["acceptance_commands"], [])


# ---------------------------------------------------------------------------
class CompletionModeProjectionTests(DirectorTestBase):
    """FABRIC runner-owned-acceptance V1, Problem 1: `DirectorRunSummary.
    completion_mode` is a pure, additive classification of fields `result()`
    already projects - CHECKPOINT (material changes + an ON_SUCCESS
    checkpoint), SUCCESS_NOOP (success, nothing to persist), or None for
    every non-SUCCESS worker_state."""

    def test_completion_mode_is_none_for_non_success(self):
        svc = self.service()
        self.seed_pipeline_result("run-blocked", "w1", {"state": "BLOCKED"})
        summary = svc.result("run-blocked")
        self.assertIsNone(summary.completion_mode)

    def test_completion_mode_checkpoint_when_commit_present(self):
        svc = self.service()
        self.seed_pipeline_result(
            "run-cp", "w1", {"state": "SUCCESS", "checkpoint_policy": "ON_SUCCESS", "checkpoint_commit": "deadbeef"},
        )
        summary = svc.result("run-cp")
        self.assertEqual(summary.completion_mode, "CHECKPOINT")

    def test_completion_mode_success_noop_when_no_changes_and_no_checkpoint(self):
        svc = self.service()
        self.seed_pipeline_result("run-noop", "w1", {"state": "SUCCESS"})
        summary = svc.result("run-noop")
        self.assertEqual(summary.completion_mode, "SUCCESS_NOOP")
        self.assertIsNone(summary.checkpoint_commit)

    def test_completion_mode_unclassified_when_changes_exist_without_checkpoint(self):
        evidence = self.make_evidence(work_product_present=True, changed=["M a.txt"], authorized=["M a.txt"])
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-orphan", evidence_dir=evidence,
            work_status="SUCCESS", work_product_present=True,
        )
        executor = lambda request: result
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec(mode="write", authorize_paths=["a.txt"]))
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertIsNone(summary.checkpoint_commit)
        # Material changes with no ON_SUCCESS checkpoint recorded for them -
        # neither CHECKPOINT nor SUCCESS_NOOP's "nothing to persist" contract
        # holds, so this is deliberately left unclassified rather than guessed.
        self.assertIsNone(summary.completion_mode)

    def test_submit_run_and_result_projections_agree_on_completion_mode(self):
        evidence = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-noop-real", evidence_dir=evidence, work_status="SUCCESS",
        )
        executor = lambda request: result
        svc = self.service(executor=executor)
        summary = svc.submit_and_run(self.spec())
        self.assertEqual(summary.completion_mode, "SUCCESS_NOOP")
        again = svc.result(summary.pipeline_id)
        self.assertEqual(again.completion_mode, "SUCCESS_NOOP")


# ---------------------------------------------------------------------------
class RunnerOwnedAcceptanceDirectorTests(DirectorTestBase):
    """FABRIC runner-owned-acceptance V1, Problem 2: `DirectorWorkOrderSpec.
    completion_policy`/`acceptance_commands` are additive, OPTIONAL fields -
    every pre-existing caller that never sets them gets the exact prior
    manifest/behavior (completion_policy='provider_verdict', no acceptance
    step is ever attempted)."""

    def test_completion_policy_and_acceptance_commands_absent_by_default(self):
        spec = fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x")
        self.assertEqual(spec.completion_policy, "provider_verdict")
        self.assertEqual(spec.acceptance_commands, [])
        svc = self.service()
        handle = svc.submit(spec)
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["completion_policy"], "provider_verdict")
        self.assertEqual(manifest["workers"][0]["acceptance_commands"], [])

    def test_acceptance_commands_and_completion_policy_map_into_manifest(self):
        svc = self.service()
        handle = svc.submit(self.spec(
            completion_policy="runner_acceptance", acceptance_commands=["pytest -q", "true"],
        ))
        manifest = json.loads(Path(handle.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workers"][0]["completion_policy"], "runner_acceptance")
        self.assertEqual(manifest["workers"][0]["acceptance_commands"], ["pytest -q", "true"])

    def test_runner_acceptance_with_zero_commands_is_refused_before_any_run(self):
        svc = self.service()
        handle = svc.submit(self.spec(completion_policy="runner_acceptance"))
        self.assertFalse(handle.validated)
        self.assertTrue(any(
            e["code"] == "RUNNER_ACCEPTANCE_REQUIRES_ACCEPTANCE_COMMANDS" for e in handle.validation_errors
        ))
        with self.assertRaises(fd.DirectorError):
            svc.run(handle)

    def test_missing_verdict_superseded_by_passing_acceptance_end_to_end(self):
        evidence = self.root / "evidence_missing_verdict"
        evidence.mkdir()
        result = runner.WorkOrderResult(
            state=RS.VERDICT_INVALID, exit_code=runner.EXIT_CODES[RS.VERDICT_INVALID],
            run_id="run-missing-verdict", evidence_dir=evidence, work_status="INVALID_VERDICT",
        )
        executor = lambda request: result
        py = sys.executable.replace("\\", "/")
        svc = self.service(executor=executor)
        summary = svc.submit_and_run(self.spec(
            completion_policy="runner_acceptance", acceptance_commands=[f"{py} -c exit(0)"],
        ))
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.completion_mode, "SUCCESS_NOOP")
        ev = svc.evidence(summary.run_id)
        self.assertEqual(ev.acceptance["decision"], "PASSED")

    def test_missing_verdict_with_failing_acceptance_stays_failed(self):
        evidence = self.root / "evidence_missing_verdict_fail"
        evidence.mkdir()
        result = runner.WorkOrderResult(
            state=RS.VERDICT_INVALID, exit_code=runner.EXIT_CODES[RS.VERDICT_INVALID],
            run_id="run-missing-verdict-fail", evidence_dir=evidence, work_status="INVALID_VERDICT",
        )
        executor = lambda request: result
        py = sys.executable.replace("\\", "/")
        svc = self.service(executor=executor)
        summary = svc.submit_and_run(self.spec(
            completion_policy="runner_acceptance", acceptance_commands=[f"{py} -c exit(1)"],
        ))
        self.assertEqual(summary.worker_state, "FAILED")
        ev = svc.evidence(summary.run_id)
        self.assertEqual(ev.acceptance["decision"], "FAILED")


# ---------------------------------------------------------------------------
class WorkStatusSourceProjectionTests(DirectorTestBase):
    """FABRIC H2-B: `result()`/`evidence()` project `provider_work_status`/
    `work_status`/`work_status_source` verbatim from the worker's own
    durable `result.json` - never recomputed, never parsed from provider
    prose."""

    def test_result_projects_provider_sourced_work_status(self):  # 11
        executor = lambda request: runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-ws-ok", evidence_dir=None, work_status="SUCCESS",
        )
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec())
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.work_status, "SUCCESS")
        self.assertEqual(summary.provider_work_status, "SUCCESS")
        self.assertEqual(summary.work_status_source, runner.WORK_STATUS_SOURCE_PROVIDER)

    def test_result_projects_unverified_as_provider_sourced_not_success(self):  # 11
        executor = lambda request: runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-ws-unverified", evidence_dir=None,
            work_status="UNVERIFIED",
        )
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec())
        summary = svc.run(handle)
        # Backward-compatible WorkerState mapping is unaffected...
        self.assertEqual(summary.worker_state, "SUCCESS")
        # ...but the effective work_status must never be silently promoted.
        self.assertEqual(summary.work_status, "UNVERIFIED")
        self.assertEqual(summary.provider_work_status, "UNVERIFIED")
        self.assertEqual(summary.work_status_source, runner.WORK_STATUS_SOURCE_PROVIDER)

    def test_result_and_evidence_project_runner_acceptance_certified_status(self):  # 11, 12
        evidence_dir = self.root / "evidence_h2b_certified"
        evidence_dir.mkdir()
        result = runner.WorkOrderResult(
            state=RS.VERDICT_INVALID, exit_code=runner.EXIT_CODES[RS.VERDICT_INVALID],
            run_id="run-h2b-certified", evidence_dir=evidence_dir, work_status="INVALID_VERDICT",
        )
        executor = lambda request: result
        py = sys.executable.replace("\\", "/")
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec(
            completion_policy="runner_acceptance", acceptance_commands=[f"{py} -c exit(0)"],
        ))
        summary = svc.run(handle)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.work_status, "SUCCESS")
        self.assertEqual(summary.provider_work_status, "INVALID_VERDICT")
        self.assertEqual(summary.work_status_source, runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)

        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.work_status, "SUCCESS")
        self.assertEqual(ev.provider_work_status, "INVALID_VERDICT")
        self.assertEqual(ev.work_status_source, runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)

    def test_result_and_evidence_remain_backward_compatible_for_legacy_worker_result(self):  # 13
        evidence_dir = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-legacy-ws", evidence_dir=evidence_dir,
            work_status="SUCCESS",
        )
        executor = lambda request: result
        svc = self.service(executor=executor)
        handle = svc.submit(self.spec())
        svc.run(handle)
        worker_result_path = self.state_root / handle.pipeline_id / "workers" / handle.worker_id / "result.json"
        payload = json.loads(worker_result_path.read_text(encoding="utf-8"))
        # Simulate a pre-H2-B durable worker result.json that never recorded
        # provider_work_status/work_status_source: result()/evidence() must
        # fail soft (None), never raise, and `work_status` must keep working
        # exactly as before.
        del payload["provider_work_status"]
        del payload["work_status_source"]
        worker_result_path.write_text(json.dumps(payload), encoding="utf-8")

        again = svc.result(handle.pipeline_id)
        self.assertEqual(again.work_status, "SUCCESS")
        self.assertIsNone(again.provider_work_status)
        self.assertIsNone(again.work_status_source)

        ev = svc.evidence(handle.pipeline_id)
        self.assertEqual(ev.work_status, "SUCCESS")
        self.assertIsNone(ev.provider_work_status)
        self.assertIsNone(ev.work_status_source)


# ---------------------------------------------------------------------------
class AuditProfileTests(DirectorTestBase):
    """FABRIC H2-C: `build_audit_spec` - the first-class read-only AUDIT
    PROFILE, a safe expansion over the EXISTING DirectorWorkOrderSpec /
    PipelineRunner contracts (never a new provider mode, never a second
    execution path; see the FABRIC H2-C work order)."""

    def _audit_spec(self, **extra) -> fd.DirectorWorkOrderSpec:
        py = sys.executable.replace("\\", "/")
        kw = dict(
            worktree=str(self.target), work_order_text="Inspect only.\n",
            acceptance_commands=[f"{py} -c exit(0)"],
        )
        kw.update(extra)
        return fd.build_audit_spec(**kw)

    def test_audit_expands_to_provider_read_only(self):  # 1
        spec = self._audit_spec()
        self.assertEqual(spec.mode, providers.MODE_READ_ONLY)
        self.assertEqual(spec.authorize_paths, [])
        self.assertFalse(spec.allow_shell)
        self.assertIsNone(spec.checkpoint_policy)
        self.assertEqual(spec.completion_policy, "runner_acceptance")

    def test_audit_requires_acceptance_commands(self):  # 2
        with self.assertRaises(fd.DirectorError) as ctx:
            self._audit_spec(acceptance_commands=[])
        self.assertEqual(ctx.exception.code, "AUDIT_REQUIRES_ACCEPTANCE_COMMANDS")

    def test_audit_rejects_write_mode(self):  # 3
        with self.assertRaises(fd.DirectorError) as ctx:
            self._audit_spec(mode="write")
        self.assertEqual(ctx.exception.code, "AUDIT_CONFLICT")

    def test_audit_rejects_authorize_path(self):  # 4
        with self.assertRaises(fd.DirectorError) as ctx:
            self._audit_spec(authorize_paths=["src/"])
        self.assertEqual(ctx.exception.code, "AUDIT_CONFLICT")

    def test_audit_rejects_allow_shell(self):  # 5
        with self.assertRaises(fd.DirectorError) as ctx:
            self._audit_spec(allow_shell=True)
        self.assertEqual(ctx.exception.code, "AUDIT_CONFLICT")

    def test_audit_rejects_checkpoint_policy(self):  # 6
        with self.assertRaises(fd.DirectorError) as ctx:
            self._audit_spec(checkpoint_policy="ON_SUCCESS")
        self.assertEqual(ctx.exception.code, "AUDIT_CONFLICT")

    def test_audit_rejects_conflicting_completion_policy(self):  # 7
        with self.assertRaises(fd.DirectorError) as ctx:
            self._audit_spec(completion_policy="provider_verdict")
        self.assertEqual(ctx.exception.code, "AUDIT_CONFLICT")
        # The exact value audit requires is accepted, never a conflict.
        spec = self._audit_spec(completion_policy="runner_acceptance")
        self.assertEqual(spec.completion_policy, "runner_acceptance")

    def test_audit_mode_grants_provider_no_edit_write_or_shell_capability(self):  # 8
        spec = self._audit_spec()
        policy = providers.ExecutionPolicy(mode=spec.mode, allow_shell=spec.allow_shell)
        caps = providers.ClaudeProvider().capabilities(policy)
        self.assertNotIn(providers.Capability.EDIT_FILES, caps)
        self.assertNotIn(providers.Capability.WRITE_FILES, caps)
        self.assertNotIn(providers.Capability.SHELL, caps)
        self.assertNotIn(providers.Capability.TEST_EXECUTION, caps)
        self.assertIn(providers.Capability.READ_FILES, caps)
        self.assertIn(providers.Capability.SEARCH_FILES, caps)

    def _run_audit(self, *, work_status: str, acceptance_exit: int):
        evidence = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.VERDICT_INVALID if work_status == "INVALID_VERDICT" else RS.SUCCESS,
            exit_code=0, run_id="run-audit", evidence_dir=evidence, work_status=work_status,
        )
        executor = lambda request: result
        svc = self.service(executor=executor)
        py = sys.executable.replace("\\", "/")
        spec = self._audit_spec(acceptance_commands=[f"{py} -c exit({acceptance_exit})"])
        return svc.submit_and_run(spec), svc

    def test_passing_acceptance_yields_success_noop(self):  # 9
        summary, _svc = self._run_audit(work_status="UNVERIFIED", acceptance_exit=0)
        self.assertEqual(summary.worker_state, "SUCCESS")
        self.assertEqual(summary.completion_mode, "SUCCESS_NOOP")

    def test_passing_audit_effective_work_status_success(self):  # 10
        summary, _svc = self._run_audit(work_status="UNVERIFIED", acceptance_exit=0)
        self.assertEqual(summary.work_status, "SUCCESS")

    def test_passing_audit_source_is_runner_acceptance(self):  # 11
        summary, svc = self._run_audit(work_status="UNVERIFIED", acceptance_exit=0)
        self.assertEqual(summary.work_status_source, runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)
        self.assertIsNone(summary.checkpoint_commit)
        self.assertEqual(summary.changed_paths, ())
        self.assertEqual(summary.authorized_changed_paths, ())
        self.assertEqual(summary.unauthorized_changed_paths, ())
        self.assertFalse(summary.work_product_present)
        ev = svc.evidence(summary.run_id)
        self.assertEqual(ev.work_status_source, runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)

    def test_failing_acceptance_yields_failed(self):  # 12
        summary, _svc = self._run_audit(work_status="UNVERIFIED", acceptance_exit=1)
        self.assertEqual(summary.worker_state, "FAILED")

    def test_provider_mutation_yields_failed_safety(self):  # 13
        evidence = self.make_evidence(
            safety_verdict={"verdict": "FAILED_SAFETY", "reasons": ["repository mutated in read-only mode"]},
        )
        result = runner.WorkOrderResult(
            state=RS.FAILED_SAFETY, exit_code=runner.EXIT_CODES[RS.FAILED_SAFETY],
            run_id="run-audit-mutation", evidence_dir=evidence, work_status="FAILED",
        )
        executor = lambda request: result
        svc = self.service(executor=executor)
        summary = svc.submit_and_run(self._audit_spec())
        self.assertEqual(summary.worker_state, "FAILED")
        self.assertEqual(summary.state_reason, "FAILED_SAFETY")
        self.assertNotEqual(summary.work_status, "SUCCESS")
        ev = svc.evidence(summary.run_id)
        self.assertEqual(ev.safety_verdict, "FAILED_SAFETY")

    def test_explicit_fail_not_superseded_by_passing_acceptance(self):  # 14
        evidence = self.make_evidence(work_product_present=False)
        result = runner.WorkOrderResult(
            state=RS.WORK_FAILED, exit_code=runner.EXIT_CODES[RS.WORK_FAILED],
            run_id="run-audit-explicit-fail", evidence_dir=evidence, work_status="FAILED",
        )
        executor = lambda request: result
        svc = self.service(executor=executor)
        py = sys.executable.replace("\\", "/")
        summary = svc.submit_and_run(self._audit_spec(acceptance_commands=[f"{py} -c exit(0)"]))
        self.assertEqual(summary.worker_state, "FAILED")
        self.assertEqual(summary.state_reason, "WORK_FAILED")
        self.assertEqual(summary.work_status, "FAILED")

    def test_evidence_incomplete_cannot_become_audit_success(self):
        evidence = self.make_evidence(work_product_present=False, evidence_errors=["disk full"])
        result = runner.WorkOrderResult(
            state=RS.VERDICT_INVALID, exit_code=runner.EXIT_CODES[RS.VERDICT_INVALID],
            run_id="run-audit-evidence-incomplete", evidence_dir=evidence, work_status="INVALID_VERDICT",
            evidence_complete=False, evidence_error="disk full",
        )
        executor = lambda request: result
        svc = self.service(executor=executor)
        summary = svc.submit_and_run(self._audit_spec())
        self.assertNotEqual(summary.work_status, "SUCCESS")
        self.assertFalse(svc.evidence(summary.run_id).evidence_complete)


# ---------------------------------------------------------------------------
# FCP-1C: Director entry point to the FCP-1B integration assessment
# ---------------------------------------------------------------------------

_GIT_WRITE_SUBCOMMANDS = frozenset({
    "merge", "rebase", "push", "pull", "fetch", "checkout", "switch", "reset", "commit", "update-ref",
    "cherry-pick", "revert", "am", "apply", "stash", "tag", "branch",
})


def git_state(fx) -> tuple:
    """Every observable piece of Git state an integration action would touch."""
    return tuple(
        plain_git(repo, *args).stdout
        for repo in (fx.repo, fx.wt)
        for args in (("for-each-ref",), ("rev-parse", "HEAD"), ("symbolic-ref", "-q", "HEAD"),
                     ("status", "--porcelain=v1", "--untracked-files=all"), ("worktree", "list", "--porcelain"))
    )


class IntegrationAssessmentDirectorTests(DirectorTestBase):
    """FCP-1C: `FabricDirectorService.assess_integration` only validates,
    supplies governed ownership roots and delegates to the FCP-1B core."""

    def setUp(self):
        super().setUp()
        env_patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.fcp_root = self.root / "fcp"
        self.fcp_root.mkdir()
        self.addCleanup(_rmtree, self.fcp_root)
        self.fx = Fixture(self.fcp_root)
        # An existing (empty) ledger: no active workers are recorded.
        self.factory_root.mkdir()

    def assess(self, svc=None, *, attested="default", scopes=None, evidence="default", **kw):
        svc = svc or self.service()
        return svc.assess_integration(
            str(self.fx.wt),
            attested_sha=self.fx.c1 if attested == "default" else attested,
            authorized_scopes=list(SCOPES) if scopes is None else scopes,
            evidence=good_evidence(self.fx) if evidence == "default" else evidence,
            **kw,
        )

    def assertClass(self, a, classification, reason=None):
        self.assertEqual(a.classification, classification, a.reason_codes)
        if reason is not None:
            self.assertIn(reason, a.reason_codes)
        self.assertIs(a.human_approval_required, True)
        self.assertEqual(a.eligible, classification == ri.ELIGIBLE_PENDING_APPROVAL)

    # B. delegation ---------------------------------------------------------

    def test_delegates_to_existing_assessment_core_unchanged(self):
        sentinel = object()
        with mock.patch.object(fd.integration, "assess_integration", return_value=sentinel) as core:
            result = self.assess(expected_remote_url=REMOTE_URL)
        self.assertIs(result, sentinel)
        core.assert_called_once_with(
            str(self.fx.wt), attested_sha=self.fx.c1, authorized_scopes=list(SCOPES),
            expected_remote_url=REMOTE_URL, evidence=good_evidence(self.fx),
            ledger_root=self.factory_root, lease_root=None,
        )
        self.assertIs(fd.integration, ri)

    def test_eligible_candidate_is_projected_from_core(self):
        a = self.assess(expected_remote_url=REMOTE_URL)
        self.assertClass(a, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertIsInstance(a, ri.IntegrationAssessment)
        self.assertEqual(a.reason_codes, ())
        self.assertTrue(a.candidate.ledger_checked)
        self.assertIsNone(a.candidate.ledger_error)
        self.assertEqual(a.candidate.head_sha, self.fx.feature_head)
        self.assertEqual(a.evidence.status, ri.EVIDENCE_BOUND)
        self.assertEqual(a.evidence.run_id, "run-1")

    def test_director_adds_no_classification_rules(self):
        # The same inputs through the core directly give the identical result.
        a = self.assess()
        direct = ri.assess_integration(
            str(self.fx.wt), attested_sha=self.fx.c1, authorized_scopes=list(SCOPES),
            evidence=good_evidence(self.fx), ledger_root=self.factory_root,
        )
        self.assertEqual(a, direct)

    # C. unknown safety facts ------------------------------------------------

    def test_unknown_safety_fact_cannot_become_eligible(self):
        real_inspect = ri.inspect_candidate

        def unknown_clean(*args, **kwargs):
            return dataclasses.replace(real_inspect(*args, **kwargs), clean=None)

        with mock.patch.object(ri, "inspect_candidate", side_effect=unknown_clean):
            a = self.assess()
        self.assertClass(a, ri.REVIEW_REQUIRED, "UNPROVEN_CLEAN")

    def test_unattested_base_is_fail_closed_not_an_error(self):
        self.assertClass(self.assess(attested=None), ri.BASE_UNVERIFIED, ri.BASE_UNATTESTED)

    def test_missing_scope_is_never_eligible(self):
        self.assertClass(self.assess(scopes=[]), ri.UNAUTHORIZED_CHANGED_PATHS, "SCOPE_INVALID")

    def test_unreadable_worktree_is_fail_closed(self):
        a = self.service().assess_integration(
            str(self.root / "does-not-exist"), attested_sha=self.fx.c1, authorized_scopes=list(SCOPES),
        )
        self.assertClass(a, ri.UNSAFE_WORKTREE, "GIT_READ_FAILED")

    # D. evidence -------------------------------------------------------------

    def test_missing_evidence_is_fail_closed(self):
        a = self.assess(evidence=None)
        self.assertClass(a, ri.EVIDENCE_MISSING, "EVIDENCE_MISSING")
        self.assertEqual(a.evidence.status, ri.EVIDENCE_MISSING_STATUS)

    def test_invalid_evidence_is_fail_closed(self):
        for evidence, reason in (
            (good_evidence(self.fx, decision_code="REVIEW_REQUIRED"), "EVIDENCE_NOT_READY_FOR_HOST_AUDIT"),
            (good_evidence(self.fx, safety_verdict="UNSAFE"), "EVIDENCE_NOT_SAFE"),
            (good_evidence(self.fx, evidence_complete=None), "EVIDENCE_INCOMPLETE"),
            (["not", "a", "mapping"], "EVIDENCE_INVALID"),
        ):
            with self.subTest(reason=reason):
                a = self.assess(evidence=evidence)
                self.assertClass(a, ri.EVIDENCE_MISSING, reason)
                self.assertEqual(a.evidence.status, ri.EVIDENCE_INVALID)

    def test_stale_evidence_is_fail_closed(self):
        a = self.assess(evidence=good_evidence(self.fx, head_sha=self.fx.c1))
        self.assertClass(a, ri.EVIDENCE_MISSING, "EVIDENCE_HEAD_MISMATCH")
        self.assertEqual(a.evidence.status, ri.EVIDENCE_STALE)

    # E. ownership ------------------------------------------------------------

    def test_active_worker_in_director_ledger_is_ownership_conflict(self):
        flog.FactoryLedger(self.factory_root).append(
            flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt),
        )
        a = self.assess()
        self.assertClass(a, ri.OWNERSHIP_CONFLICT, "ACTIVE_WORKER")
        self.assertEqual(a.candidate.active_workers, (("p1", "w1"),))

    def test_wired_factory_ledger_root_is_the_one_checked(self):
        other = self.root / "wired-ledger"
        ledger = flog.FactoryLedger(other)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p9", worker_id="w9", worktree=str(self.fx.wt))
        svc = self.service(factory_ledger=ledger)
        self.assertEqual(svc.integration_ledger_root(), other)
        self.assertClass(self.assess(svc), ri.OWNERSHIP_CONFLICT, "ACTIVE_WORKER")

    def test_missing_ledger_root_fails_closed(self):
        svc = self.service(factory_root=self.root / "no-factory-yet")
        a = self.assess(svc)
        self.assertClass(a, ri.OWNERSHIP_CONFLICT, "LEDGER_UNREADABLE")
        self.assertFalse((self.root / "no-factory-yet").exists())

    def test_same_runner_lease_as_director_runs(self):
        lease_root = self.root / "leases"
        svc = self.service(pipeline_runner_options={"lease_root": lease_root, "heartbeat_interval_seconds": None})
        competitor = fd.pipeline.DirLease(fd.pipeline.worktree_lease_dir(self.fx.wt.resolve(), lease_root))
        self.assertTrue(competitor.try_acquire({"pipeline_id": "running", "worker_id": "w1", "pid": 1}))
        try:
            a = self.assess(svc)
            self.assertClass(a, ri.OWNERSHIP_CONFLICT, "WORKTREE_LEASE_HELD")
            self.assertIn(("pipeline_id", "running"), a.candidate.lease_holder)
            self.assertEqual(competitor.holder()["pipeline_id"], "running")
        finally:
            competitor.release()
        a = self.assess(svc)
        self.assertClass(a, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertEqual(Path(a.candidate.lease_dir).parent, lease_root)
        # The assessment released its own lease.
        probe = fd.pipeline.DirLease(Path(a.candidate.lease_dir))
        self.assertTrue(probe.try_acquire({"pid": 1}))
        probe.release()

    # F/G. approval, fingerprint, reason codes --------------------------------

    def test_fingerprint_and_reason_codes_are_stable(self):
        svc = self.service()
        first, second = self.assess(svc), self.assess(svc)
        self.assertRegex(first.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(first.fingerprint, second.fingerprint)
        stale = self.assess(svc, evidence=good_evidence(self.fx, head_sha=self.fx.c1))
        again = self.assess(svc, evidence=good_evidence(self.fx, head_sha=self.fx.c1))
        self.assertEqual(stale.reason_codes, again.reason_codes)
        self.assertEqual(stale.fingerprint, again.fingerprint)
        self.assertNotEqual(stale.fingerprint, first.fingerprint)

    def test_human_approval_always_required(self):
        for kwargs in ({}, {"attested": None}, {"evidence": None}, {"scopes": []}):
            with self.subTest(kwargs=kwargs):
                self.assertIs(self.assess(**kwargs).human_approval_required, True)

    # Validation ---------------------------------------------------------------

    def test_invalid_input_types_are_refused_before_any_read(self):
        svc = self.service()
        cases = (
            dict(worktree="", attested_sha=None, authorized_scopes=[]),
            dict(worktree=None, attested_sha=None, authorized_scopes=[]),
            dict(worktree=str(self.fx.wt), attested_sha=123, authorized_scopes=[]),
            dict(worktree=str(self.fx.wt), attested_sha=None, authorized_scopes="src"),
            dict(worktree=str(self.fx.wt), attested_sha=None, authorized_scopes=["src", 1]),
            dict(worktree=str(self.fx.wt), attested_sha=None, authorized_scopes=[], expected_remote_url=7),
        )
        with mock.patch.object(fd.integration, "assess_integration") as core:
            for kwargs in cases:
                worktree = kwargs.pop("worktree")
                with self.subTest(kwargs=kwargs), self.assertRaises(fd.DirectorError) as ctx:
                    svc.assess_integration(worktree, **kwargs)
                self.assertEqual(ctx.exception.code, "INVALID_SPEC")
        core.assert_not_called()

    # J. no Git writes or integration actions ----------------------------------

    def test_assessment_performs_no_git_writes_or_director_writes(self):
        before = git_state(self.fx)
        with mock.patch.object(ri.runner_git, "run", wraps=ri.runner_git.run) as spy:
            a = self.assess()
        self.assertClass(a, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertEqual(git_state(self.fx), before)
        subcommands = {next(x for x in call.args[1] if not x.startswith("-")) for call in spy.call_args_list}
        self.assertTrue(subcommands)
        self.assertLessEqual(subcommands, ri._READ_SUBCOMMANDS)
        self.assertFalse(subcommands & _GIT_WRITE_SUBCOMMANDS)
        self.assertFalse(self.director_root.exists())
        self.assertFalse(self.state_root.exists())
        self.assertEqual(sorted(p.name for p in self.factory_root.iterdir()), [])


# ---------------------------------------------------------------------------
# FCP-2C: Director entry point to the FCP-2B reconciliation analysis
# ---------------------------------------------------------------------------

class ReconciliationDirectorTests(DirectorTestBase):
    """FCP-2C: `assess_reconciliation` validates, supplies the governed
    ownership roots and delegates ONCE to the FCP-2B core; the plan methods
    are thin delegates. Nothing here authorizes, executes or persists."""

    def setUp(self):
        super().setUp()
        env_patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.fcp_root = self.root / "fcp2"
        self.fcp_root.mkdir()
        self.addCleanup(_rmtree, self.fcp_root)
        self.fx = ReconFixture(self.fcp_root)
        self.factory_root.mkdir()
        self.lease_root = self.root / "leases"

    def service(self, **kw) -> fd.FabricDirectorService:
        kw.setdefault("pipeline_runner_options", {"lease_root": self.lease_root, "heartbeat_interval_seconds": None})
        return super().service(**kw)

    def recon(self, svc=None, *, worktree=None, attested="default", scopes=None, evidence="default", **kw):
        svc = svc or self.service()
        worktree = worktree or self.fx.wt
        return svc.assess_reconciliation(
            str(worktree),
            attested_sha=self.fx.base if attested == "default" else attested,
            authorized_scopes=["src"] if scopes is None else scopes,
            evidence=good_evidence(Path(worktree)) if evidence == "default" else evidence,
            **kw,
        )

    def stale_disjoint(self):
        self.fx.head_commit({"src/a.py": recon_text({2: "head\n"})})
        self.fx.base_commit({"docs/readme.md": "readme v2\n"})

    def assertRecon(self, a, classification, *reasons):
        self.assertIsInstance(a, rr.ReconciliationAnalysis)
        self.assertEqual(a.classification, classification, a.reason_codes)
        for reason in reasons:
            self.assertIn(reason, a.reason_codes)
        self.assertIs(a.human_approval_required, True)
        self.assertIs(a.authorizes_action, False)

    # Delegation ---------------------------------------------------------------

    def test_delegates_exactly_once_to_reconciliation_core_unchanged(self):
        sentinel = object()
        svc = self.service()
        with mock.patch.object(fd.reconciliation, "analyze_reconciliation", return_value=sentinel) as core, \
                mock.patch.object(fd.integration, "assess_integration") as fcp1:
            result = self.recon(svc, expected_remote_url=REMOTE_URL)
        self.assertIs(result, sentinel)
        core.assert_called_once_with(
            str(self.fx.wt), attested_sha=self.fx.base, authorized_scopes=["src"],
            expected_remote_url=REMOTE_URL, evidence=good_evidence(self.fx.wt),
            ledger_root=self.factory_root, lease_root=self.lease_root, max_paths=rr.MAX_PATHS,
        )
        fcp1.assert_not_called()
        self.assertIs(fd.reconciliation, rr)

    def test_no_secondary_fcp1_assessment_and_roots_carried_through(self):
        self.stale_disjoint()
        calls = []
        real = ri.assess_integration

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return real(*args, **kwargs)

        with mock.patch.object(ri, "assess_integration", spy), \
                mock.patch.object(fd.FabricDirectorService, "assess_integration") as director_fcp1:
            a = self.recon()
        director_fcp1.assert_not_called()
        # Only FCP-2B's own initial + post-read FCP-1 passes, both governed.
        self.assertEqual(len(calls), 2)
        for kwargs in calls:
            self.assertEqual(kwargs["ledger_root"], self.factory_root)
            self.assertEqual(kwargs["lease_root"], self.lease_root)
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT)
        self.assertEqual(Path(a.assessment.candidate.lease_dir).parent, self.lease_root)
        self.assertIs(a.assessment.candidate.ledger_checked, True)

    def test_director_adds_no_classification_rules(self):
        self.stale_disjoint()
        a = self.recon()
        direct = rr.analyze_reconciliation(
            str(self.fx.wt), attested_sha=self.fx.base, authorized_scopes=["src"],
            evidence=good_evidence(self.fx.wt), ledger_root=self.factory_root, lease_root=self.lease_root,
        )
        self.assertEqual(dataclasses.asdict(a), dataclasses.asdict(direct))

    # Proven fixtures -----------------------------------------------------------

    def test_stale_base_text_only_is_no_textual_conflict_not_safety(self):
        self.stale_disjoint()
        a = self.recon()
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_PATHS, rr.RECON_SEMANTIC_VALIDATION_REQUIRED)
        self.assertIs(a.semantic_validation_required, True)
        self.assertEqual(a.scope, ("src/a.py",))

    def test_needs_reconciliation_overlap_is_semantic_review(self):
        self.fx.head_commit({"src/a.py": recon_text({5: "head\n"})})
        self.fx.base_commit({"src/a.py": recon_text({5: "base\n"})})
        a = self.recon()
        self.assertEqual(a.assessment_classification, ri.NEEDS_RECONCILIATION)
        self.assertRecon(a, rr.SEMANTIC_REVIEW_REQUIRED, rr.RECON_OVERLAPPING_HUNKS)

    def test_risky_changes_are_human_required(self):
        self.fx.head_commit({"src/old.py": "head edit\n"})
        self.fx.base_commit(delete=("src/old.py",))
        self.assertRecon(self.recon(), rr.HUMAN_REQUIRED, rr.RECON_MODIFY_DELETE)
        other = self.fx.add_worktree("bin-wt", "feature/binary", self.fx.base)
        self.fx.head_commit({"src/blob.bin": b"\x00\x01binary\xff"}, worktree=other)
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        self.assertRecon(self.recon(worktree=other), rr.HUMAN_REQUIRED, rr.RECON_BINARY)

    def test_drift_between_fcp2b_passes_is_fail_closed(self):
        self.stale_disjoint()
        real = rr._read_facts

        def drifting(*args):
            facts = real(*args)
            recon_change(self.fx.wt, "concurrent", {"src/late.py": "late\n"})
            return facts

        with mock.patch.object(rr, "_read_facts", drifting):
            a = self.recon()
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_ASSESSMENT_DRIFT)
        self.assertIsNone(self.service().propose_reconciliation_plan(a, acceptance_commands=list(ACCEPTANCE)))

    # Fail-closed inputs -----------------------------------------------------------

    def assertNotApplicable(self, a, fcp1_classification, fcp1_reason=None):
        self.assertRecon(a, rr.NOT_APPLICABLE, rr.RECON_NOT_APPLICABLE)
        self.assertEqual(a.assessment_classification, fcp1_classification)
        if fcp1_reason is not None:
            self.assertIn(fcp1_reason, a.assessment.reason_codes)
        self.assertIsNone(a.facts)
        self.assertIsNone(self.service().propose_reconciliation_plan(a, acceptance_commands=list(ACCEPTANCE)))

    def test_missing_invalid_or_contradictory_evidence_is_not_optimistic(self):
        self.stale_disjoint()
        for evidence, reason in (
            (None, "EVIDENCE_MISSING"),
            (["not", "a", "mapping"], "EVIDENCE_INVALID"),
            (good_evidence(self.fx.wt, safety_verdict="UNSAFE"), "EVIDENCE_NOT_SAFE"),
            (good_evidence(self.fx.wt, head_sha=self.fx.c0), "EVIDENCE_HEAD_MISMATCH"),
        ):
            with self.subTest(reason=reason):
                self.assertNotApplicable(self.recon(evidence=evidence), ri.EVIDENCE_MISSING, reason)

    def test_unknown_base_is_not_optimistic(self):
        self.stale_disjoint()
        self.assertNotApplicable(self.recon(attested=None), ri.BASE_UNVERIFIED, ri.BASE_UNATTESTED)
        self.assertNotApplicable(self.recon(attested="not-a-sha"), ri.BASE_UNVERIFIED)

    def test_ownership_conflict_is_not_optimistic(self):
        self.stale_disjoint()
        flog.FactoryLedger(self.factory_root).append(
            flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt),
        )
        self.assertNotApplicable(self.recon(), ri.OWNERSHIP_CONFLICT, "ACTIVE_WORKER")

    def test_held_lease_is_not_optimistic(self):
        self.stale_disjoint()
        competitor = fd.pipeline.DirLease(fd.pipeline.worktree_lease_dir(self.fx.wt.resolve(), self.lease_root))
        self.assertTrue(competitor.try_acquire({"pipeline_id": "running", "worker_id": "w1", "pid": 1}))
        try:
            self.assertNotApplicable(self.recon(), ri.OWNERSHIP_CONFLICT, "WORKTREE_LEASE_HELD")
            self.assertEqual(competitor.holder()["pipeline_id"], "running")
        finally:
            competitor.release()

    def test_missing_ledger_is_not_optimistic(self):
        self.stale_disjoint()
        svc = self.service(factory_root=self.root / "no-factory-yet")
        self.assertNotApplicable(self.recon(svc), ri.OWNERSHIP_CONFLICT, "LEDGER_UNREADABLE")
        self.assertFalse((self.root / "no-factory-yet").exists())

    # Validation ------------------------------------------------------------------

    def test_invalid_inputs_refused_before_any_read(self):
        svc = self.service()
        wt = str(self.fx.wt)
        cases = (
            dict(worktree="", attested_sha=None, authorized_scopes=[]),
            dict(worktree="   ", attested_sha=None, authorized_scopes=[]),
            dict(worktree=None, attested_sha=None, authorized_scopes=[]),
            dict(worktree=wt, attested_sha=123, authorized_scopes=[]),
            dict(worktree=wt, attested_sha=None, authorized_scopes="src"),
            dict(worktree=wt, attested_sha=None, authorized_scopes=["src", 1]),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], expected_remote_url=7),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=True),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=False),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=0),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=-1),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=rr.MAX_PATHS + 1),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=10 ** 30),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=1.0),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths="5"),
            dict(worktree=wt, attested_sha=None, authorized_scopes=[], max_paths=None),
        )
        with mock.patch.object(fd.reconciliation, "analyze_reconciliation") as core, \
                mock.patch.object(ri, "_git") as git:
            for kwargs in cases:
                worktree = kwargs.pop("worktree")
                with self.subTest(kwargs=kwargs), self.assertRaises(fd.DirectorError) as ctx:
                    svc.assess_reconciliation(worktree, **kwargs)
                self.assertEqual(ctx.exception.code, "INVALID_SPEC")
        core.assert_not_called()
        git.assert_not_called()

    def test_valid_max_paths_bounds_are_forwarded(self):
        svc = self.service()
        with mock.patch.object(fd.reconciliation, "analyze_reconciliation") as core:
            for value in (1, rr.MAX_PATHS):
                svc.assess_reconciliation(str(self.fx.wt), attested_sha=None, authorized_scopes=[], max_paths=value)
                self.assertEqual(core.call_args.kwargs["max_paths"], value)

    def test_fcp1_assessment_validation_is_unchanged(self):
        with mock.patch.object(fd.integration, "assess_integration") as core:
            with self.assertRaises(fd.DirectorError) as ctx:
                self.service().assess_integration("", attested_sha=None, authorized_scopes=[])
        self.assertEqual((ctx.exception.code, ctx.exception.message),
                         ("INVALID_SPEC", "worktree must be a non-empty string or path"))
        core.assert_not_called()
        self.assertNotIn("max_paths", fd.FabricDirectorService.assess_integration.__code__.co_varnames)

    # Plans ---------------------------------------------------------------------

    def test_proposed_plan_is_core_plan_and_never_authorizing(self):
        self.stale_disjoint()
        svc = self.service()
        a = self.recon(svc)
        plan = svc.propose_reconciliation_plan(a, acceptance_commands=list(ACCEPTANCE))
        self.assertEqual(plan, rr.propose_reconciliation_plan(a, acceptance_commands=list(ACCEPTANCE)))
        self.assertIsInstance(plan, rr.ReconciliationPlan)
        self.assertEqual(plan.status, rr.PLAN_PROPOSED)
        self.assertIs(plan.human_approval_required, True)
        self.assertIs(plan.authorizes_action, False)
        self.assertEqual(plan.acceptance_commands, ACCEPTANCE)
        self.assertIn(rr.STEP_HUMAN_APPROVE_MECHANISM, plan.steps)

    def test_plan_delegation_is_thin(self):
        sentinel_plan, sentinel_validation = object(), object()
        svc = self.service()
        with mock.patch.object(fd.reconciliation, "propose_reconciliation_plan", return_value=sentinel_plan) as p, \
                mock.patch.object(fd.reconciliation, "validate_reconciliation_plan",
                                  return_value=sentinel_validation) as v:
            self.assertIs(svc.propose_reconciliation_plan("a", acceptance_commands=["c"]), sentinel_plan)
            self.assertIs(svc.validate_reconciliation_plan("p", "f"), sentinel_validation)
        p.assert_called_once_with("a", acceptance_commands=["c"])
        v.assert_called_once_with("p", "f")

    def test_invalid_acceptance_commands_or_analysis_are_invalid_spec(self):
        self.stale_disjoint()
        svc = self.service()
        a = self.recon(svc)
        for commands in (None, [], "python -m unittest", [""], ["   "], [1], ["a\nb"], ["a", "a"]):
            with self.subTest(commands=commands), self.assertRaises(fd.DirectorError) as ctx:
                svc.propose_reconciliation_plan(a, acceptance_commands=commands)
            self.assertEqual(ctx.exception.code, "INVALID_SPEC")
        for analysis in (dataclasses.replace(a, classification=rr.SEMANTIC_REVIEW_REQUIRED),
                         dataclasses.replace(a, authorizes_action=True), "analysis", None):
            with self.subTest(analysis=type(analysis).__name__), self.assertRaises(fd.DirectorError) as ctx:
                svc.propose_reconciliation_plan(analysis, acceptance_commands=list(ACCEPTANCE))
            self.assertEqual(ctx.exception.code, "INVALID_SPEC")

    def test_validation_is_not_approval_and_stale_or_tampered_plan_invalidates(self):
        self.stale_disjoint()
        svc = self.service()
        plan = svc.propose_reconciliation_plan(self.recon(svc), acceptance_commands=list(ACCEPTANCE))
        ok = svc.validate_reconciliation_plan(plan, self.recon(svc))
        self.assertIsInstance(ok, rr.PlanValidation)
        self.assertIs(ok.valid, True)
        self.assertIs(ok.human_approval_required, True)
        self.assertIs(ok.authorizes_action, False)
        for reason, tampered in (
            (rr.PLAN_TAMPERED, dataclasses.replace(plan, scope=("src/a.py", "src/b.py"))),
            (rr.PLAN_NOT_PROPOSED, dataclasses.replace(plan, status="APPROVED")),
            (rr.PLAN_AUTHORIZATION_CLAIMED, dataclasses.replace(plan, authorizes_action=True)),
        ):
            with self.subTest(reason=reason):
                v = svc.validate_reconciliation_plan(tampered, self.recon(svc))
                self.assertFalse(v.valid)
                self.assertIn(reason, v.reason_codes)
                self.assertIs(v.authorizes_action, False)
        self.fx.head_commit({"src/a.py": recon_text({3: "newer\n"})})
        stale = svc.validate_reconciliation_plan(plan, self.recon(svc))
        self.assertFalse(stale.valid)
        self.assertIn(rr.PLAN_HEAD_CHANGED, stale.reason_codes)
        self.assertIs(stale.authorizes_action, False)
        self.assertFalse(svc.validate_reconciliation_plan(plan, "not-an-analysis").valid)

    # No Git writes, stores or execution ------------------------------------------

    def test_analysis_and_plan_perform_no_git_writes_or_director_writes(self):
        self.stale_disjoint()
        before = git_state(self.fx)
        svc = self.service()
        with mock.patch.object(ri.runner_git, "run", wraps=ri.runner_git.run) as spy, \
                mock.patch.object(fd.FabricDirectorService, "run") as run, \
                mock.patch.object(fd.FabricDirectorService, "submit") as submit, \
                mock.patch.object(fd.claude_runner, "execute_work_order") as execute:
            a = self.recon(svc)
            plan = svc.propose_reconciliation_plan(a, acceptance_commands=list(ACCEPTANCE))
            svc.validate_reconciliation_plan(plan, self.recon(svc))
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT)
        self.assertEqual(git_state(self.fx), before)
        subcommands = {next(x for x in call.args[1] if not x.startswith("-")) for call in spy.call_args_list}
        self.assertTrue(subcommands)
        self.assertLessEqual(subcommands, ri._READ_SUBCOMMANDS)
        self.assertFalse(subcommands & _GIT_WRITE_SUBCOMMANDS)
        for never in (run, submit, execute):
            never.assert_not_called()
        self.assertFalse(self.director_root.exists())
        self.assertFalse(self.state_root.exists())
        self.assertEqual(sorted(p.name for p in self.factory_root.iterdir()), [])


# ---------------------------------------------------------------------------
# FCP-4C-01: Director entry point to the worktree inventory
# ---------------------------------------------------------------------------

class WorktreeInventoryDirectorTests(DirectorTestBase):
    """FCP-4C-01: `inventory_worktrees` validates and delegates ONCE to the
    inventory core with the Director's own state, ledger and lease roots."""

    def setUp(self):
        super().setUp()
        env_patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.state_root.mkdir()
        self.factory_root.mkdir()

    def test_delegates_with_exact_director_roots(self):
        sentinel = object()
        lease_root = self.root / "leases"
        for svc, ledger_root, lease in (
            (self.service(), self.factory_root, None),
            (self.service(factory_ledger=flog.FactoryLedger(self.root / "wired"),
                          pipeline_runner_options={"lease_root": lease_root}), self.root / "wired", lease_root),
        ):
            with self.subTest(ledger_root=ledger_root):
                with mock.patch.object(fd.worktree_inventory, "inventory_worktrees", return_value=sentinel) as core:
                    self.assertIs(svc.inventory_worktrees(self.target), sentinel)
                core.assert_called_once_with(
                    str(self.target), state_root=self.state_root, ledger_root=ledger_root, lease_root=lease,
                )
        self.assertIs(fd.worktree_inventory, wi)

    def test_real_inventory_is_returned_unchanged(self):
        inv = self.service().inventory_worktrees(str(self.target))
        self.assertIsInstance(inv, wi.WorktreeInventory)
        self.assertEqual(inv.status, wi.INVENTORY_COMPLETE)
        direct = wi.inventory_worktrees(str(self.target), state_root=self.state_root, ledger_root=self.factory_root)
        self.assertEqual(inv, direct)
        self.assertEqual([r.classification for r in inv.records], [wi.PROTECTED])
        self.assertIs(inv.authorizes_action, False)

    def test_unreadable_roots_are_a_fail_closed_result_not_an_error(self):
        inv = self.service(factory_root=self.root / "absent").inventory_worktrees(self.target)
        self.assertEqual(inv.status, wi.INVENTORY_FAILED_CLOSED)
        self.assertTrue(inv.global_errors[0].startswith("LEDGER_UNREADABLE"))
        self.assertEqual(inv.records[0].classification, wi.UNSAFE)

    def test_malformed_repository_is_refused_before_reading(self):
        with mock.patch.object(fd.worktree_inventory, "inventory_worktrees") as core:
            for bad in (None, "", "   ", 42, ["x"]):
                with self.subTest(bad=bad):
                    with self.assertRaises(fd.DirectorError) as ctx:
                        self.service().inventory_worktrees(bad)
                    self.assertEqual(ctx.exception.code, "INVALID_SPEC")
        core.assert_not_called()

    def test_inventory_persists_nothing_in_director_roots(self):
        self.service().inventory_worktrees(self.target)
        self.assertFalse(self.director_root.exists())
        self.assertEqual(list(self.state_root.iterdir()), [])
        self.assertEqual(list(self.factory_root.iterdir()), [])


# ---------------------------------------------------------------------------
# FCP-4D-02: Director entry point to the worktree retirement assessment
# ---------------------------------------------------------------------------

class WorktreeRetirementDirectorTests(DirectorTestBase):
    """FCP-4D-02: `assess_worktree_retirement` validates and delegates ONCE
    to the retirement core with the Director's own roots and self worktree."""

    def setUp(self):
        super().setUp()
        env_patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.state_root.mkdir()
        self.factory_root.mkdir()
        self.queue_root = self.root / "queue"
        self.queue_root.mkdir()

    def test_delegates_with_exact_director_roots(self):
        sentinel = object()
        lease_root = self.root / "leases"
        wired = self.root / "wired"
        for svc, ledger_root, lease in (
            (self.service(), self.factory_root, None),
            (self.service(factory_ledger=flog.FactoryLedger(wired),
                          pipeline_runner_options={"lease_root": lease_root}), wired, lease_root),
        ):
            with self.subTest(ledger_root=ledger_root):
                with mock.patch.object(fd.worktree_retirement, "assess_worktree_retirement",
                                       return_value=sentinel) as core:
                    self.assertIs(svc.assess_worktree_retirement(
                        self.target, queue_roots=[self.queue_root], queue_roots_complete=True), sentinel)
                governed = [str(self.state_root), str(self.factory_root), str(self.director_root), str(ledger_root)]
                governed += [str(lease)] if lease is not None else []
                core.assert_called_once_with(
                    str(self.target), state_root=self.state_root, ledger_root=ledger_root, lease_root=lease,
                    queue_roots=(str(self.queue_root),), queue_roots_complete=True, self_worktree=str(self.stable),
                    governed_roots=tuple(dict.fromkeys(governed)),
                )
        self.assertIs(fd.worktree_retirement, wr)

    def test_defaults_are_fail_closed_and_self_defaults_to_runner(self):
        with mock.patch.object(fd.worktree_retirement, "assess_worktree_retirement") as core:
            self.service(self_worktree=None).assess_worktree_retirement(self.target)
        kwargs = core.call_args.kwargs
        self.assertEqual((kwargs["queue_roots"], kwargs["queue_roots_complete"]), ((), False))
        self.assertEqual(kwargs["self_worktree"], str(fd.pipeline.default_self_worktree()))

    def test_real_report_is_returned_unchanged_and_never_authorizes(self):
        report = self.service().assess_worktree_retirement(
            str(self.target), queue_roots=[str(self.queue_root)], queue_roots_complete=True)
        self.assertIsInstance(report, wr.RetirementReport)
        self.assertEqual(report.status, wr.REPORT_COMPLETE, report.global_errors)
        self.assertEqual([r.classification for r in report.records], [wr.BLOCKED])  # main worktree
        self.assertIn("INVENTORY_PROTECTED", report.records[0].reason_codes)
        self.assertEqual((report.authorizes_action, report.deletion_authorized), (False, False))
        self.assertIs(report.queue_roots_complete_claim, True)
        self.assertIn(str(self.director_root), report.governed_roots)

    def test_unreadable_roots_are_a_fail_closed_result_not_an_error(self):
        report = self.service(factory_root=self.root / "absent").assess_worktree_retirement(
            self.target, queue_roots=[self.queue_root], queue_roots_complete=True)
        self.assertEqual(report.status, wr.REPORT_FAILED_CLOSED)
        self.assertTrue(any(e.startswith("LEDGER_UNREADABLE") for e in report.global_errors))
        for r in report.records:
            self.assertNotEqual(r.classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)

    def test_malformed_input_is_refused_before_reading(self):
        bad_calls = (
            dict(repository=None), dict(repository="   "), dict(repository=42),
            dict(repository="r", queue_roots="single-string"), dict(repository="r", queue_roots=[""]),
            dict(repository="r", queue_roots=[None]), dict(repository="r", queue_roots=["q", "q"]),
            dict(repository="r", queue_roots_complete="yes"), dict(repository="r", queue_roots_complete=1),
        )
        with mock.patch.object(fd.worktree_retirement, "assess_worktree_retirement") as core:
            for kwargs in bad_calls:
                with self.subTest(kwargs=kwargs):
                    repository = kwargs.pop("repository")
                    with self.assertRaises(fd.DirectorError) as ctx:
                        self.service().assess_worktree_retirement(repository, **kwargs)
                    self.assertEqual(ctx.exception.code, "INVALID_SPEC")
        core.assert_not_called()

    def test_assessment_persists_nothing_in_director_roots(self):
        self.service().assess_worktree_retirement(self.target, queue_roots=[self.queue_root])
        self.assertFalse(self.director_root.exists())
        self.assertEqual(list(self.state_root.iterdir()), [])
        self.assertEqual(list(self.factory_root.iterdir()), [])
        self.assertEqual(list(self.queue_root.iterdir()), [])

    def test_no_destructive_director_methods(self):
        names = [n for n in dir(fd.FabricDirectorService) if not n.startswith("__")]
        for word in ("prune", "remove", "delete", "retire_", "cleanup", "unlock", "lock_worktree"):
            self.assertFalse([n for n in names if word in n], word)


if __name__ == "__main__":
    unittest.main()
