import ast
import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_director as fd
from scripts.ai import fabric_director_cli as cli

RS = runner.RunState
REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_director_cli.py"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "director-cli-tests@example.invalid")
    _git(repo, "config", "user.name", "Director CLI Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


class CLITestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.stable = _make_repo(self.root, "stable")
        self.target = _make_repo(self.root, "target")
        self.state_root = self.root / "state"
        self.director_root = self.root / "director"
        self.factory_root = self.root / "factory"
        self.work_order_file = self.root / "work_order.md"
        self.work_order_file.write_text("Do the thing.\n", encoding="utf-8")

    def _roots_argv(self) -> list:
        return [
            "--state-root", str(self.state_root),
            "--director-root", str(self.director_root),
            "--factory-root", str(self.factory_root),
            "--self-worktree", str(self.stable),
        ]

    def run_cli(self, argv: list):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exit_code = cli.main(argv)
        except SystemExit as exc:
            # argparse's own usage-error path (e.g. an invalid --mode
            # choice) exits directly rather than returning from main().
            exit_code = exc.code if isinstance(exc.code, int) else 2
        output = buf.getvalue()
        return exit_code, output

    def run_cli_json(self, argv: list):
        exit_code, output = self.run_cli(argv)
        self.assertEqual(exit_code, 0, output)
        return json.loads(output)


# ---------------------------------------------------------------------------
class ProjectStateCLITests(CLITestBase):
    """1. project-state delegates to service.project_state."""

    def test_project_state_delegates_to_service(self):
        with mock.patch.object(
            fd.FabricDirectorService, "project_state", return_value={"ok": True},
        ) as mocked:
            result = self.run_cli_json(self._roots_argv() + ["project-state", "--worktree", str(self.target)])
        mocked.assert_called_once_with(str(self.target))
        self.assertEqual(result, {"ok": True})

    def test_project_state_returns_real_projection(self):
        result = self.run_cli_json(self._roots_argv() + ["project-state", "--worktree", str(self.target)])
        self.assertEqual(result["branch"], "main")
        self.assertTrue(result["clean"])


# ---------------------------------------------------------------------------
class SubmitCLITests(CLITestBase):
    """2-9, 13-14. submit builds the correct spec and reports DirectorRunHandle."""

    def _submit_argv(self, **extra) -> list:
        argv = self._roots_argv() + [
            "submit",
            "--worktree", str(self.target),
            "--work-order-file", str(self.work_order_file),
        ]
        for key, values in extra.items():
            flag = f"--{key.replace('_', '-')}"
            if isinstance(values, bool):
                if values:
                    argv.append(flag)
            elif isinstance(values, list):
                for v in values:
                    argv.extend([flag, v])
            else:
                argv.extend([flag, str(values)])
        return argv

    def test_submit_builds_correct_spec(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv(mode="write", provider="claude", model="opus"))
        spec = captured["spec"]
        self.assertEqual(spec.worktree, str(self.target))
        self.assertEqual(spec.mode, "write")
        self.assertEqual(spec.provider, "claude")
        self.assertEqual(spec.model, "opus")

    def test_submit_preserves_work_order_text_contract(self):
        self.work_order_file.write_text("Line one\nLine two", encoding="utf-8")
        handle = self.run_cli_json(self._submit_argv())
        persisted = Path(handle["work_order_path"]).read_bytes().decode("utf-8")
        self.assertEqual(persisted, "Line one\nLine two\n")

    def test_repeated_authorize_path_maps_exactly(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv(authorize_path=["src/foo", "docs"]))
        self.assertEqual(captured["spec"].authorize_paths, ["src/foo", "docs"])

    def test_repeated_capability_maps_exactly(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv(capability=["SHELL", "READ_FILES"]))
        self.assertEqual(captured["spec"].required_capabilities, ["SHELL", "READ_FILES"])

    def test_allow_shell_flag_maps_exactly(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv(allow_shell=True))
        self.assertTrue(captured["spec"].allow_shell)

        captured.clear()
        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv())
        self.assertFalse(captured["spec"].allow_shell)

    def test_checkpoint_timeout_model_provider_map_exactly(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv(
                **{"checkpoint-policy": "ON_SUCCESS", "timeout-seconds": "120", "model": "opus", "provider": "claude"},
            ))
        spec = captured["spec"]
        self.assertEqual(spec.checkpoint_policy, "ON_SUCCESS")
        self.assertEqual(spec.timeout_seconds, 120)
        self.assertEqual(spec.model, "opus")
        self.assertEqual(spec.provider, "claude")

    def test_acceptance_command_and_completion_policy_map_exactly(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv(
                **{
                    "acceptance-command": ["pytest -q", "true"],
                    "completion-policy": "runner_acceptance",
                },
            ))
        spec = captured["spec"]
        self.assertEqual(spec.acceptance_commands, ["pytest -q", "true"])
        self.assertEqual(spec.completion_policy, "runner_acceptance")

    def test_default_completion_policy_and_acceptance_commands(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv())
        spec = captured["spec"]
        self.assertEqual(spec.completion_policy, "provider_verdict")
        self.assertEqual(spec.acceptance_commands, [])

    def test_invalid_completion_policy_choice_fails_non_zero(self):
        exit_code, _ = self.run_cli(self._submit_argv(**{"completion-policy": "ALWAYS"}))
        self.assertNotEqual(exit_code, 0)

    def test_metadata_key_value_maps_exactly(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv(metadata=["a=1", "b=two"]))
        self.assertEqual(captured["spec"].metadata, {"a": "1", "b": "two"})

    def test_submit_json_field_set_equals_director_run_handle_fields(self):
        handle = self.run_cli_json(self._submit_argv())
        expected = {f.name for f in dataclasses.fields(fd.DirectorRunHandle)}
        self.assertEqual(set(handle.keys()), expected)

    def test_default_mode_and_provider_match_spec_defaults(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit", _capture):
            self.run_cli_json(self._submit_argv())
        spec = captured["spec"]
        default_spec = fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x")
        self.assertEqual(spec.mode, default_spec.mode)
        self.assertEqual(spec.provider, default_spec.provider)

    def test_invalid_mode_fails_non_zero(self):
        exit_code, _ = self.run_cli(self._submit_argv(mode="not-a-real-mode"))
        self.assertNotEqual(exit_code, 0)

    def test_missing_work_order_file_fails_non_zero(self):
        argv = self._roots_argv() + [
            "submit", "--worktree", str(self.target),
            "--work-order-file", str(self.root / "does_not_exist.md"),
        ]
        exit_code, _ = self.run_cli(argv)
        self.assertNotEqual(exit_code, 0)

    def test_invalid_worktree_fails_non_zero_as_director_error(self):
        argv = self._roots_argv() + [
            "submit",
            "--worktree", str(self.root / "not_a_repo"),
            "--work-order-file", str(self.work_order_file),
        ]
        exit_code, _ = self.run_cli(argv)
        self.assertNotEqual(exit_code, 0)


# ---------------------------------------------------------------------------
class SubmitRunCLITests(CLITestBase):
    """10. submit-run delegates to the existing service execution path."""

    def test_submit_run_delegates_to_submit_and_run(self):
        with mock.patch.object(
            fd.FabricDirectorService, "submit_and_run",
        ) as mocked:
            mocked.return_value = fd.DirectorRunSummary(run_id="r1", pipeline_id="r1", worker_state="SUCCESS")
            result = self.run_cli_json(self._roots_argv() + [
                "submit-run", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            ])
        mocked.assert_called_once()
        self.assertEqual(result["worker_state"], "SUCCESS")

    def test_submit_run_json_field_set_equals_director_run_summary_fields(self):
        with mock.patch.object(
            fd.FabricDirectorService, "submit_and_run",
        ) as mocked:
            mocked.return_value = fd.DirectorRunSummary(run_id="r1", pipeline_id="r1")
            result = self.run_cli_json(self._roots_argv() + [
                "submit-run", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            ])
        expected = {f.name for f in dataclasses.fields(fd.DirectorRunSummary)}
        self.assertEqual(set(result.keys()), expected)

    def test_submit_run_executes_through_pipeline_runner_without_real_provider(self):
        fake_result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-cli-1", evidence_dir=None, work_status="SUCCESS",
        )
        with mock.patch("scripts.ai.runner_pipeline.claude_runner.execute_work_order", return_value=fake_result):
            result = self.run_cli_json(self._roots_argv() + [
                "submit-run", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            ])
        self.assertEqual(result["worker_state"], "SUCCESS")
        self.assertEqual(result["work_status"], "SUCCESS")


# ---------------------------------------------------------------------------
class StatusResultCLITests(CLITestBase):
    """11-12, 15. status/result delegate to service; no execution occurs."""

    def test_status_delegates_to_service_status(self):
        with mock.patch.object(fd.FabricDirectorService, "status", return_value={"pipeline_id": "abc"}) as mocked:
            result = self.run_cli_json(self._roots_argv() + ["status", "--run-id", "abc"])
        mocked.assert_called_once_with("abc")
        self.assertEqual(result, {"pipeline_id": "abc"})

    def test_result_delegates_to_service_result(self):
        summary = fd.DirectorRunSummary(run_id="abc", pipeline_id="abc", worker_state="SUCCESS")
        with mock.patch.object(fd.FabricDirectorService, "result", return_value=summary) as mocked:
            result = self.run_cli_json(self._roots_argv() + ["result", "--run-id", "abc"])
        mocked.assert_called_once_with("abc")
        self.assertEqual(result["worker_state"], "SUCCESS")

    def test_result_json_field_set_equals_director_run_summary_fields(self):
        summary = fd.DirectorRunSummary(run_id="abc", pipeline_id="abc")
        with mock.patch.object(fd.FabricDirectorService, "result", return_value=summary):
            result = self.run_cli_json(self._roots_argv() + ["result", "--run-id", "abc"])
        expected = {f.name for f in dataclasses.fields(fd.DirectorRunSummary)}
        self.assertEqual(set(result.keys()), expected)

    def test_status_and_result_never_call_submit_run_or_execute(self):
        with mock.patch.object(fd.FabricDirectorService, "submit") as msub, \
             mock.patch.object(fd.FabricDirectorService, "submit_and_run") as mrun, \
             mock.patch.object(fd.FabricDirectorService, "run") as mrun2, \
             mock.patch.object(fd.FabricDirectorService, "status", return_value={}), \
             mock.patch.object(fd.FabricDirectorService, "result", return_value=fd.DirectorRunSummary(run_id="x", pipeline_id="x")):
            self.run_cli_json(self._roots_argv() + ["status", "--run-id", "x"])
            self.run_cli_json(self._roots_argv() + ["result", "--run-id", "x"])
        msub.assert_not_called()
        mrun.assert_not_called()
        mrun2.assert_not_called()

    def test_project_state_never_calls_submit_run_or_execute(self):
        with mock.patch.object(fd.FabricDirectorService, "submit") as msub, \
             mock.patch.object(fd.FabricDirectorService, "submit_and_run") as mrun, \
             mock.patch.object(fd.FabricDirectorService, "run") as mrun2:
            self.run_cli_json(self._roots_argv() + ["project-state", "--worktree", str(self.target)])
        msub.assert_not_called()
        mrun.assert_not_called()
        mrun2.assert_not_called()


# ---------------------------------------------------------------------------
class DirectScriptInvocationTests(unittest.TestCase):
    """Real child-process invocations proving the CLI is importable without
    external PYTHONPATH configuration - the integration boundary a
    mocked/monkeypatched import can't exercise."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.external_cwd = Path(self._tmp.name).resolve()
        self.env = dict(os.environ)
        self.env.pop("PYTHONPATH", None)

    def _run(self, argv: list, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            argv, cwd=str(cwd), env=self.env, capture_output=True, text=True,
        )

    def test_direct_script_help_from_external_cwd_without_pythonpath(self):
        proc = self._run([sys.executable, str(CLI_PATH), "--help"], cwd=self.external_cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage:", proc.stdout)

    def test_direct_script_subcommand_help_from_external_cwd_without_pythonpath(self):
        proc = self._run(
            [sys.executable, str(CLI_PATH), "project-state", "--help"], cwd=self.external_cwd,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage:", proc.stdout)

    def test_module_invocation_help_from_repo_root(self):
        proc = self._run(
            [sys.executable, "-m", "scripts.ai.fabric_director_cli", "--help"], cwd=REPO_ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage:", proc.stdout)


# ---------------------------------------------------------------------------
class GovernanceStaticTests(unittest.TestCase):
    """16-18. static source checks: no second execution engine/store."""

    def setUp(self):
        self.source = Path(cli.__file__).read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_no_direct_execute_work_order_call(self):
        # The docstring legitimately explains (in prose) why the CLI never
        # calls `execute_work_order` directly; only an actual AST Call node
        # naming it would be a real violation.
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = getattr(target, "attr", None) or getattr(target, "id", None)
            self.assertNotEqual(name, "execute_work_order")

    def test_no_subprocess_based_execution_engine(self):
        self.assertNotIn("import subprocess", self.source)
        self.assertNotIn("subprocess.run(", self.source)
        self.assertNotIn("subprocess.Popen(", self.source)
        self.assertNotIn("subprocess.call(", self.source)

    def test_no_new_store_or_root_other_than_director_roots(self):
        # No Path(...).mkdir / open(...) writes anywhere in the CLI module -
        # every durable write stays inside FabricDirectorService itself.
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr == "mkdir":
                self.fail("fabric_director_cli.py must never create directories itself")
            if isinstance(node, ast.Name) and node.id == "open":
                self.fail("fabric_director_cli.py must never open files directly")

    def test_no_decision_execution_or_worktree_mutation_calls(self):
        forbidden = ("push", "merge", "create_worktree", ".decision(")
        for token in forbidden:
            self.assertNotIn(token, self.source)


# ---------------------------------------------------------------------------
class AuditCLITests(CLITestBase):
    """FABRIC H2-C: `--audit` on `submit`/`submit-run` is sugar over the
    EXISTING `fabric_director.build_audit_spec` - the CLI never hand-
    assembles the safe combination or re-implements the conflict checks
    itself."""

    def _capture_spec(self):
        captured = {}
        original_submit = fd.FabricDirectorService.submit

        def _capture(self, spec):
            captured["spec"] = spec
            return original_submit(self, spec)

        return captured, mock.patch.object(fd.FabricDirectorService, "submit", _capture)

    def test_audit_flag_maps_exactly(self):  # 15
        captured, patcher = self._capture_spec()
        with patcher:
            self.run_cli_json(self._roots_argv() + [
                "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
                "--audit", "--acceptance-command", "true",
            ])
        spec = captured["spec"]
        self.assertEqual(spec.mode, "read-only")
        self.assertEqual(spec.authorize_paths, [])
        self.assertFalse(spec.allow_shell)
        self.assertIsNone(spec.checkpoint_policy)
        self.assertEqual(spec.completion_policy, "runner_acceptance")
        self.assertEqual(spec.acceptance_commands, ["true"])

    def test_audit_requires_acceptance_commands(self):
        exit_code, _output = self.run_cli(self._roots_argv() + [
            "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            "--audit",
        ])
        self.assertNotEqual(exit_code, 0)

    def test_audit_rejects_write_mode(self):
        exit_code, _ = self.run_cli(self._roots_argv() + [
            "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            "--audit", "--acceptance-command", "true", "--mode", "write",
        ])
        self.assertNotEqual(exit_code, 0)

    def test_audit_rejects_authorize_path(self):
        exit_code, _ = self.run_cli(self._roots_argv() + [
            "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            "--audit", "--acceptance-command", "true", "--authorize-path", "src/",
        ])
        self.assertNotEqual(exit_code, 0)

    def test_audit_rejects_allow_shell(self):
        exit_code, _ = self.run_cli(self._roots_argv() + [
            "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            "--audit", "--acceptance-command", "true", "--allow-shell",
        ])
        self.assertNotEqual(exit_code, 0)

    def test_audit_rejects_checkpoint_policy(self):
        exit_code, _ = self.run_cli(self._roots_argv() + [
            "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            "--audit", "--acceptance-command", "true", "--checkpoint-policy", "ON_SUCCESS",
        ])
        self.assertNotEqual(exit_code, 0)

    def test_audit_rejects_conflicting_completion_policy(self):
        exit_code, _ = self.run_cli(self._roots_argv() + [
            "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            "--audit", "--acceptance-command", "true", "--completion-policy", "provider_verdict",
        ])
        self.assertNotEqual(exit_code, 0)

    def test_audit_accepts_matching_completion_policy(self):
        handle = self.run_cli_json(self._roots_argv() + [
            "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            "--audit", "--acceptance-command", "true", "--completion-policy", "runner_acceptance",
        ])
        self.assertTrue(handle["validated"])

    def test_audit_provider_does_not_receive_edit_write_or_shell_capability(self):  # 8
        captured, patcher = self._capture_spec()
        with patcher:
            self.run_cli_json(self._roots_argv() + [
                "submit", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
                "--audit", "--acceptance-command", "true",
            ])
        spec = captured["spec"]
        policy = fd.providers.ExecutionPolicy(mode=spec.mode, allow_shell=spec.allow_shell)
        caps = fd.providers.ClaudeProvider().capabilities(policy)
        self.assertNotIn(fd.providers.Capability.EDIT_FILES, caps)
        self.assertNotIn(fd.providers.Capability.WRITE_FILES, caps)
        self.assertNotIn(fd.providers.Capability.SHELL, caps)
        self.assertNotIn(fd.providers.Capability.TEST_EXECUTION, caps)

    def test_audit_submit_run_passing_acceptance_succeeds(self):
        fake_result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-cli-audit", evidence_dir=None, work_status="UNVERIFIED",
        )
        py = sys.executable.replace("\\", "/")
        with mock.patch("scripts.ai.runner_pipeline.claude_runner.execute_work_order", return_value=fake_result):
            result = self.run_cli_json(self._roots_argv() + [
                "submit-run", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
                "--audit", "--acceptance-command", f"{py} -c exit(0)",
            ])
        self.assertEqual(result["worker_state"], "SUCCESS")
        self.assertEqual(result["work_status"], "SUCCESS")
        self.assertEqual(result["work_status_source"], "RUNNER_ACCEPTANCE")
        self.assertEqual(result["completion_mode"], "SUCCESS_NOOP")
        self.assertIsNone(result["checkpoint_commit"])

    def test_audit_help_documents_audit(self):  # 16
        for subcommand in ("submit", "submit-run"):
            exit_code, output = self.run_cli([subcommand, "--help"])
            self.assertEqual(exit_code, 0)
            self.assertIn("--audit", output)

    def test_submit_run_without_audit_is_unchanged(self):  # 17
        captured, patcher = self._capture_spec()
        original_submit_and_run = fd.FabricDirectorService.submit_and_run

        def _capture_run(self, spec):
            captured["spec"] = spec
            return original_submit_and_run(self, spec)

        with mock.patch.object(fd.FabricDirectorService, "submit_and_run", _capture_run):
            self.run_cli_json(self._roots_argv() + [
                "submit-run", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            ])
        spec = captured["spec"]
        default_spec = fd.DirectorWorkOrderSpec(worktree=str(self.target), work_order_text="x")
        self.assertEqual(spec.mode, default_spec.mode)
        self.assertEqual(spec.completion_policy, default_spec.completion_policy)
        self.assertEqual(spec.acceptance_commands, default_spec.acceptance_commands)
        self.assertEqual(spec.checkpoint_policy, default_spec.checkpoint_policy)
        self.assertEqual(spec.authorize_paths, default_spec.authorize_paths)


if __name__ == "__main__":
    unittest.main()
