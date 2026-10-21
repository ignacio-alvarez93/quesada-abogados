import ast
import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_director as fd
from scripts.ai import fabric_director_cli as cli
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_integration as ri
from scripts.tests.test_runner_integration import (
    _ISOLATED_ENV, FEATURE, REMOTE_URL, SCOPES, Fixture, _rmtree, good_evidence,
)

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
        with mock.patch(
            "scripts.ai.runner_pipeline.claude_runner.execute_work_order",
            return_value=fake_result,
        ), mock.patch.object(
            fd.providers.ClaudeProvider,
            "probe",
            return_value=fd.providers.ProviderProbe(
                provider_id="claude",
                available=True,
                executable="claude-test-stub",
                version="test",
            ),
        ):
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
class EvidenceDecisionCLITests(CLITestBase):
    """Read-only projection commands delegate to the canonical Director."""

    def test_evidence_delegates_and_serializes_full_dataclass(self):
        evidence = fd.DirectorRunEvidence(run_id="run-evidence")
        with mock.patch.object(fd.FabricDirectorService, "evidence", return_value=evidence) as called:
            result = self.run_cli_json(self._roots_argv() + ["evidence", "--run-id", "run-evidence"])
        called.assert_called_once_with("run-evidence")
        self.assertEqual(result, json.loads(json.dumps(dataclasses.asdict(evidence))))

    def test_decision_delegates_and_serializes_full_dataclass(self):
        decision = fd.DirectorRunDecision(run_id="run-decision")
        with mock.patch.object(fd.FabricDirectorService, "decision", return_value=decision) as called:
            result = self.run_cli_json(self._roots_argv() + ["decision", "--run-id", "run-decision"])
        called.assert_called_once_with("run-decision")
        self.assertEqual(result, json.loads(json.dumps(dataclasses.asdict(decision))))

    def test_projection_commands_do_not_execute_or_submit(self):
        # Error paths still must never schedule any work.
        with mock.patch.object(fd.FabricDirectorService, "submit") as submitted, \
             mock.patch.object(fd.FabricDirectorService, "submit_and_run") as submitted_run, \
             mock.patch.object(fd.FabricDirectorService, "run") as run, \
             mock.patch.object(fd.FabricDirectorService, "evidence", side_effect=fd.DirectorError("MISSING", "Not found")), \
             mock.patch.object(fd.FabricDirectorService, "decision", side_effect=fd.DirectorError("MISSING", "Not found")):
            for command in ("evidence", "decision"):
                status, stdout = self.run_cli(self._roots_argv() + [command, "--run-id", "missing"])
                self.assertNotEqual(status, 0)
                self.assertEqual(stdout, "")
        submitted.assert_not_called()
        submitted_run.assert_not_called()
        run.assert_not_called()

    def _seed_success_artifacts(self, run_id: str, attempt: dict) -> None:
        evidence_dir = self.root / f"evidence-{run_id}"
        evidence_dir.mkdir()
        (evidence_dir / "metadata.json").write_text(json.dumps({"work_product_present": False}), encoding="utf-8")
        (evidence_dir / "result.json").write_text(
            json.dumps({"safety_verdict": {"verdict": "SAFE", "reasons": []}}), encoding="utf-8",
        )
        worker_dir = self.state_root / run_id / "workers" / "w1"
        worker_dir.mkdir(parents=True)
        (self.state_root / run_id / "pipeline_result.json").write_text(json.dumps({
            "pipeline_id": run_id, "status": "COMPLETE",
            "workers": [{"id": "w1", "state": "SUCCESS", "provider": "claude"}],
        }), encoding="utf-8")
        (worker_dir / "result.json").write_text(json.dumps({
            "attempts": [attempt], "work_status": "SUCCESS", "runner_state": "SUCCESS",
            "evidence_dir": str(evidence_dir),
        }), encoding="utf-8")

    def test_fcp_fix_07_cli_projections_agree_on_tri_state_evidence_completeness(self):
        cases = (
            ("run-unknown", {}, None, "EVIDENCE_REVIEW_REQUIRED"),
            ("run-true", {"evidence_complete": True}, True, "READY_FOR_HOST_AUDIT"),
            ("run-false", {"evidence_complete": False, "evidence_error": "boom"}, False, "EVIDENCE_REVIEW_REQUIRED"),
        )
        for run_id, attempt, expected, code in cases:
            with self.subTest(run_id):
                self._seed_success_artifacts(run_id, attempt)
                outputs = {
                    command: self.run_cli_json(self._roots_argv() + [command, "--run-id", run_id])
                    for command in ("result", "evidence", "decision")
                }
                for command, value in outputs.items():
                    self.assertIs(value["evidence_complete"], expected, command)
                self.assertEqual(outputs["result"]["work_status"], "SUCCESS")
                self.assertEqual(outputs["decision"]["decision_code"], code)

    def test_both_commands_require_run_id(self):
        for command in ("evidence", "decision"):
            exit_code, output = self.run_cli(self._roots_argv() + [command])
            self.assertNotEqual(exit_code, 0)
            self.assertEqual(output, "")


# ---------------------------------------------------------------------------
class RecoverSubmitCLITests(CLITestBase):
    """FDB-CLI-02: recovery requires explicit host intent and does not execute."""

    def _argv(self):
        return self._roots_argv() + [
            "recover-submit", "--prior-run-id", "prior-123",
            "--work-order-file", str(self.work_order_file),
            "--action", "RESUME_WORK_PRODUCT",
        ]

    def test_recovery_delegates_full_spec_and_returns_handle(self):
        handle = fd.DirectorRunHandle(
            director_run_id="new-1", pipeline_id="new-1", worker_id="worker-1",
            worktree=str(self.target), director_dir="director", work_order_path="wo",
            manifest_path="manifest", state_root="state", validated=True,
        )
        with mock.patch.object(fd.FabricDirectorService, "recover", return_value=handle) as recovered:
            value = self.run_cli_json(self._argv() + [
                "--provider", "codex", "--authorize-path", "scripts/ai",
                "--metadata", "origin=cli",
            ])
        recovered.assert_called_once()
        spec = recovered.call_args.args[0]
        self.assertIsInstance(spec, fd.DirectorRecoverySpec)
        self.assertEqual(spec.prior_run_id, "prior-123")
        self.assertEqual(spec.action, "RESUME_WORK_PRODUCT")
        self.assertEqual(spec.recovery_work_order_text, "Do the thing.\n")
        self.assertEqual(spec.provider_override, "codex")
        self.assertEqual(spec.authorize_paths, ["scripts/ai"])
        self.assertEqual(spec.metadata, {"origin": "cli"})
        self.assertEqual(value, json.loads(json.dumps(dataclasses.asdict(handle))))

    def test_recovery_refuses_missing_explicit_action(self):
        argv = self._argv()
        argv.remove("--action")
        argv.remove("RESUME_WORK_PRODUCT")
        with mock.patch.object(fd.FabricDirectorService, "recover") as recovered:
            code, output = self.run_cli(argv)
        self.assertNotEqual(code, 0)
        self.assertFalse(output)
        recovered.assert_not_called()

    def test_recovery_never_executes(self):
        handle = fd.DirectorRunHandle(
            director_run_id="new-1", pipeline_id="new-1", worker_id="worker-1",
            worktree=str(self.target), director_dir="director", work_order_path="wo",
            manifest_path="manifest", state_root="state", validated=True,
        )
        with mock.patch.object(fd.FabricDirectorService, "recover", return_value=handle), \
             mock.patch.object(fd.FabricDirectorService, "run") as run, \
             mock.patch.object(fd.FabricDirectorService, "submit_and_run") as submit_run:
            self.run_cli_json(self._argv())
        run.assert_not_called()
        submit_run.assert_not_called()

    def _handle(self):
        return fd.DirectorRunHandle(
            director_run_id="new-1", pipeline_id="new-1", worker_id="worker-1",
            worktree=str(self.target), director_dir="director", work_order_path="wo",
            manifest_path="manifest", state_root="state", validated=True,
        )

    def test_recovery_omitted_certification_flags_carry_prior_forward(self):  # FCP-FIX-04
        with mock.patch.object(fd.FabricDirectorService, "recover", return_value=self._handle()) as recovered:
            self.run_cli_json(self._argv())
        spec = recovered.call_args.args[0]
        self.assertIsNone(spec.completion_policy)
        self.assertIsNone(spec.acceptance_commands)

    def test_recovery_forwards_explicit_certification_flags(self):  # FCP-FIX-04
        with mock.patch.object(fd.FabricDirectorService, "recover", return_value=self._handle()) as recovered:
            self.run_cli_json(self._argv() + [
                "--completion-policy", "runner_acceptance",
                "--acceptance-command", "pytest -q", "--acceptance-command", "ruff check .",
            ])
        spec = recovered.call_args.args[0]
        self.assertEqual(spec.completion_policy, "runner_acceptance")
        self.assertEqual(spec.acceptance_commands, ["pytest -q", "ruff check ."])

    def test_recovery_unknown_completion_policy_refused_before_director(self):  # FCP-FIX-04
        with mock.patch.object(fd.FabricDirectorService, "recover") as recovered:
            code, output = self.run_cli(self._argv() + ["--completion-policy", "trust_me"])
        self.assertNotEqual(code, 0)
        self.assertFalse(output)
        recovered.assert_not_called()

    def test_recovery_certification_downgrade_reported_as_director_error(self):  # FCP-FIX-04
        error = fd.DirectorError("RECOVERY_CERTIFICATION_DOWNGRADE", "refused")
        with mock.patch.object(fd.FabricDirectorService, "recover", side_effect=error):
            code, output = self.run_cli(self._argv() + ["--completion-policy", "provider_verdict"])
        self.assertEqual(code, 1)
        self.assertFalse(output)

    def test_recovery_missing_work_order_refused_before_director(self):
        argv = self._argv()
        argv[argv.index("--work-order-file") + 1] = str(self.root / "not-found.txt")
        with mock.patch.object(fd.FabricDirectorService, "recover") as recovered:
            code, output = self.run_cli(argv)
        self.assertNotEqual(code, 0)
        self.assertFalse(output)
        recovered.assert_not_called()


# ---------------------------------------------------------------------------
class RecoverRunCLITests(CLITestBase):
    """FDB-CLI-03: explicit execution via the canonical Director.run(handle)."""

    def _argv(self):
        return self._roots_argv() + [
            "recover-run", "--prior-run-id", "prior-123",
            "--work-order-file", str(self.work_order_file),
            "--action", "RESUME_WORK_PRODUCT", "--execute-confirm", "RUN_RECOVERY",
        ]

    def _handle(self):
        return fd.DirectorRunHandle(
            director_run_id="new-1", pipeline_id="new-1", worker_id="worker-1",
            worktree=str(self.target), director_dir="director", work_order_path="wo",
            manifest_path="manifest", state_root="state", validated=True,
        )

    def test_recover_run_delegates_to_service_run_with_exact_handle(self):
        handle = self._handle()
        summary = fd.DirectorRunSummary(run_id="new-1", pipeline_id="new-1", worker_state="SUCCESS")
        with mock.patch.object(fd.FabricDirectorService, "recover", return_value=handle) as recovered, \
             mock.patch.object(fd.FabricDirectorService, "run", return_value=summary) as run:
            output = self.run_cli_json(self._argv())
        recovered.assert_called_once()
        spec = recovered.call_args.args[0]
        self.assertEqual(spec.prior_run_id, "prior-123")
        self.assertEqual(spec.action, "RESUME_WORK_PRODUCT")
        self.assertEqual(spec.recovery_work_order_text, "Do the thing.\n")
        run.assert_called_once_with(handle)
        self.assertEqual(output, json.loads(json.dumps(dataclasses.asdict(summary))))

    def test_recover_run_forwards_certification_flags(self):  # FCP-FIX-04
        summary = fd.DirectorRunSummary(run_id="new-1", pipeline_id="new-1", worker_state="SUCCESS")
        with mock.patch.object(fd.FabricDirectorService, "recover", return_value=self._handle()) as recovered, \
             mock.patch.object(fd.FabricDirectorService, "run", return_value=summary):
            self.run_cli_json(self._argv() + ["--acceptance-command", "make test"])
        spec = recovered.call_args.args[0]
        self.assertIsNone(spec.completion_policy)
        self.assertEqual(spec.acceptance_commands, ["make test"])

    def test_recover_run_requires_second_execution_confirmation(self):
        argv = self._argv()
        argv.remove("--execute-confirm")
        argv.remove("RUN_RECOVERY")
        with mock.patch.object(fd.FabricDirectorService, "recover") as recovered, \
             mock.patch.object(fd.FabricDirectorService, "run") as run:
            code, output = self.run_cli(argv)
        self.assertNotEqual(code, 0)
        self.assertFalse(output)
        recovered.assert_not_called()
        run.assert_not_called()

    def test_recover_run_requires_new_work_order(self):
        argv = self._argv()
        argv[argv.index("--work-order-file") + 1] = str(self.root / "missing.txt")
        with mock.patch.object(fd.FabricDirectorService, "recover") as recovered, \
             mock.patch.object(fd.FabricDirectorService, "run") as run:
            code, output = self.run_cli(argv)
        self.assertNotEqual(code, 0)
        self.assertFalse(output)
        recovered.assert_not_called()
        run.assert_not_called()

    def test_recover_failure_does_not_execute(self):
        with mock.patch.object(fd.FabricDirectorService, "recover", side_effect=fd.DirectorError("RECOVERY_NOT_ELIGIBLE", "refused")), \
             mock.patch.object(fd.FabricDirectorService, "run") as run:
            code, output = self.run_cli(self._argv())
        self.assertEqual(code, 1)
        self.assertFalse(output)
        run.assert_not_called()

    def test_recover_submit_stays_submission_only(self):
        argv = self._argv()
        argv[argv.index("recover-run")] = "recover-submit"
        del argv[argv.index("--execute-confirm"):argv.index("--execute-confirm") + 2]
        with mock.patch.object(fd.FabricDirectorService, "recover", return_value=self._handle()), \
             mock.patch.object(fd.FabricDirectorService, "run") as run:
            result = self.run_cli_json(argv)
        self.assertEqual(result["pipeline_id"], "new-1")
        run.assert_not_called()


# ---------------------------------------------------------------------------
class FactoryLedgerCLITests(CLITestBase):
    """FCP-FIX-09: Director CLI -> PipelineRunner -> existing FactoryLedger."""

    MARKER = "FCP-FIX-09-WORK-ORDER-MARKER"

    def setUp(self):
        super().setUp()
        self.work_order_file.write_text(f"{self.MARKER}: do the thing.\n", encoding="utf-8")

    def _submit_run(self, *, global_argv=None):
        fake_result = runner.WorkOrderResult(
            state=RS.SUCCESS, exit_code=0, run_id="run-cli-ledger", evidence_dir=None, work_status="SUCCESS",
        )
        argv = self._roots_argv() + list(global_argv or []) + [
            "submit-run", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
        ]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch(
            "scripts.ai.runner_pipeline.claude_runner.execute_work_order", return_value=fake_result,
        ), mock.patch.object(
            fd.providers.ClaudeProvider, "probe",
            return_value=fd.providers.ProviderProbe(
                provider_id="claude", available=True, executable="claude-test-stub", version="test",
            ),
        ), redirect_stdout(out), redirect_stderr(err):
            exit_code = cli.main(argv)
        return exit_code, out.getvalue(), err.getvalue()

    def test_submit_run_records_one_start_and_finish_in_configured_factory_root(self):
        exit_code, output, _ = self._submit_run()
        self.assertEqual(exit_code, 0)
        summary = json.loads(output)
        self.assertEqual(summary["worker_state"], "SUCCESS")
        events = fd.pipeline.factory_history_report(self.factory_root, pipeline_id=summary["pipeline_id"])
        types = [e["event_type"] for e in events]
        self.assertEqual(types.count(flog.WORKER_STARTED), 1)
        self.assertEqual(types.count(flog.WORKER_FINISHED), 1)
        finished = [e for e in events if e["event_type"] == flog.WORKER_FINISHED][0]
        self.assertEqual(finished["worker_id"], summary["worker_id"])
        self.assertEqual(finished["provider"], "claude")
        self.assertEqual(finished["state"], "SUCCESS")
        # Projections over the SAME configured roots: nothing left active.
        self.assertEqual(flog.FactoryLedger(self.factory_root).status()["active_workers"], [])
        svc = fd.FabricDirectorService(state_root=self.state_root, factory_root=self.factory_root)
        self.assertEqual(svc.factory_state()["counts"]["ACTIVE"], 0)

    def test_ledger_never_carries_work_order_text_or_secret_shaped_fields(self):
        exit_code, _, _ = self._submit_run()
        self.assertEqual(exit_code, 0)
        raw = (self.factory_root / flog.EVENTS_FILENAME).read_text(encoding="utf-8")
        self.assertNotIn(self.MARKER, raw)
        for line in raw.splitlines():
            event = json.loads(line)
            keys = set(event) | set(event.get("extra") or {})
            self.assertEqual(keys & flog._SECRET_LIKE_KEYS, set())

    def test_ledger_is_rooted_at_service_factory_root(self):
        parser = cli.build_arg_parser()
        configured = cli._build_service(parser.parse_args(self._roots_argv() + ["status", "--run-id", "x"]))
        self.assertIsInstance(configured.factory_ledger, flog.FactoryLedger)
        self.assertEqual(configured.factory_ledger.root, self.factory_root)
        # Omitted --factory-root: the service's own default, never a CLI guess.
        defaulted = cli._build_service(parser.parse_args(["status", "--run-id", "x"]))
        self.assertEqual(defaulted.factory_ledger.root, defaulted.factory_root)
        opted_out = cli._build_service(parser.parse_args(["--no-factory-ledger", "status", "--run-id", "x"]))
        self.assertIsNone(opted_out.factory_ledger)

    def test_no_factory_ledger_opt_out_writes_nothing(self):
        exit_code, output, _ = self._submit_run(global_argv=["--no-factory-ledger"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output)["worker_state"], "SUCCESS")
        self.assertFalse(self.factory_root.exists())

    def test_ledger_failure_does_not_corrupt_work_result(self):
        # A regular file where the ledger directory should be: every append
        # fails, and Runner's best-effort ledger semantics must absorb it.
        self.factory_root.write_text("not a directory\n", encoding="utf-8")
        exit_code, output, err = self._submit_run()
        self.assertEqual(exit_code, 0, err)
        summary = json.loads(output)
        self.assertEqual(summary["worker_state"], "SUCCESS")
        self.assertEqual(summary["work_status"], "SUCCESS")

    def test_read_only_commands_do_not_touch_ledger(self):
        self.run_cli_json(self._roots_argv() + ["project-state", "--worktree", str(self.target)])
        self.assertFalse(self.factory_root.exists())


# ---------------------------------------------------------------------------
class PipelineErrorCLITests(CLITestBase):
    """FCP-FIX-09: governed PipelineError -> deterministic exit + stderr."""

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            exit_code = cli.main(argv)
        return exit_code, out.getvalue(), err.getvalue()

    def test_unknown_run_id_status_is_governed_error(self):
        exit_code, output, err = self._run(self._roots_argv() + ["status", "--run-id", "does-not-exist"])
        self.assertEqual(exit_code, fd.pipeline.EXIT_PIPELINE_REFUSED)
        self.assertEqual(output, "")
        self.assertTrue(err.startswith("error: PIPELINE_NOT_FOUND: "), err)
        self.assertNotIn("Traceback", err)

    def test_runner_pipeline_error_during_submit_run_is_governed_error(self):
        with mock.patch.object(
            fd.pipeline.PipelineRunner, "run",
            side_effect=fd.pipeline.PipelineError("LEASE_LOCATION_UNRESOLVED", "cannot resolve git dir"),
        ):
            exit_code, output, err = self._run(self._roots_argv() + [
                "submit-run", "--worktree", str(self.target), "--work-order-file", str(self.work_order_file),
            ])
        self.assertEqual(exit_code, fd.pipeline.EXIT_PIPELINE_REFUSED)
        self.assertEqual(output, "")
        self.assertEqual(err, "error: LEASE_LOCATION_UNRESOLVED: cannot resolve git dir\n")

    def test_unknown_programming_errors_are_not_concealed(self):
        with mock.patch.object(fd.FabricDirectorService, "status", side_effect=RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                self._run(self._roots_argv() + ["status", "--run-id", "x"])

    def test_director_error_contract_unchanged(self):
        exit_code, output, err = self._run(self._roots_argv() + [
            "submit", "--worktree", str(self.root / "missing"), "--work-order-file", str(self.work_order_file),
        ])
        self.assertEqual(exit_code, 1)
        self.assertEqual(output, "")
        self.assertTrue(err.startswith("error: "))


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
        forbidden = ("push", "merge", "create_worktree")
        for token in forbidden:
            self.assertNotIn(token, self.source)
        # The CLI may delegate once to the canonical Director decision;
        # it must never define or invoke a separate decision engine.
        calls = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "decision"]
        self.assertEqual(len(calls), 1)
        target = calls[0].func.value
        self.assertIsInstance(target, ast.Name)
        self.assertEqual(target.id, "service")


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
        with mock.patch(
            "scripts.ai.runner_pipeline.claude_runner.execute_work_order",
            return_value=fake_result,
        ), mock.patch.object(
            fd.providers.ClaudeProvider,
            "probe",
            return_value=fd.providers.ProviderProbe(
                provider_id="claude",
                available=True,
                executable="claude-test-stub",
                version="test",
            ),
        ):
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


# ---------------------------------------------------------------------------
class AssessIntegrationCLITests(CLITestBase):
    """FCP-1C: `assess-integration` is a thin JSON projection of
    `FabricDirectorService.assess_integration` (the FCP-1B core)."""

    def setUp(self):
        super().setUp()
        env_patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.fcp_root = self.root / "fcp"
        self.fcp_root.mkdir()
        self.addCleanup(_rmtree, self.fcp_root)
        self.fx = Fixture(self.fcp_root)
        self.factory_root.mkdir()
        self.evidence_file = self.root / "evidence.json"
        self.write_evidence(good_evidence(self.fx))

    def write_evidence(self, payload) -> None:
        self.evidence_file.write_text(json.dumps(payload), encoding="utf-8")

    def assess_argv(self, *, attested="default", scopes=SCOPES, evidence=True, extra=()) -> list:
        argv = self._roots_argv() + ["assess-integration", "--worktree", str(self.fx.wt)]
        attested = self.fx.c1 if attested == "default" else attested
        if attested is not None:
            argv += ["--attested-sha", attested]
        for scope in scopes:
            argv += ["--authorize-path", scope]
        if evidence:
            argv += ["--evidence-file", str(self.evidence_file)]
        return argv + list(extra)

    def run_cli_err(self, argv: list):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            exit_code = cli.main(argv)
        return exit_code, out.getvalue(), err.getvalue()

    def assertProjected(self, result, classification, reason=None):
        self.assertEqual(result["classification"], classification, result["reason_codes"])
        if reason is not None:
            self.assertIn(reason, result["reason_codes"])
        self.assertIs(result["human_approval_required"], True)
        self.assertIs(result["eligible"], classification == ri.ELIGIBLE_PENDING_APPROVAL)

    # A. successful projection ----------------------------------------------

    def test_successful_assessment_projection(self):
        result = self.run_cli_json(self.assess_argv(extra=["--expected-remote-url", REMOTE_URL]))
        self.assertProjected(result, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertEqual(result["reason_codes"], [])
        self.assertRegex(result["fingerprint"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["base"]["status"], ri.BASE_VERIFIED)
        self.assertEqual(result["base"]["tracking_sha"], self.fx.c1)
        self.assertIs(result["base"]["remote_url_matches"], True)
        self.assertEqual(result["candidate"]["head_sha"], self.fx.feature_head)
        self.assertEqual(result["candidate"]["head_ref"], f"refs/heads/{FEATURE}")
        self.assertIs(result["candidate"]["ledger_checked"], True)
        self.assertEqual(result["evidence"]["status"], ri.EVIDENCE_BOUND)
        self.assertEqual(result["evidence"]["run_id"], "run-1")
        self.assertEqual(
            set(result), {"classification", "eligible", "human_approval_required", "reason_codes",
                          "fingerprint", "base", "candidate", "evidence"},
        )

    def test_projection_equals_director_assessment(self):
        result = self.run_cli_json(self.assess_argv())
        service = fd.FabricDirectorService(
            state_root=self.state_root, director_root=self.director_root, factory_root=self.factory_root,
            self_worktree=self.stable,
        )
        direct = service.assess_integration(
            str(self.fx.wt), attested_sha=self.fx.c1, authorized_scopes=list(SCOPES),
            evidence=good_evidence(self.fx),
        )
        self.assertEqual(result, json.loads(json.dumps(dataclasses.asdict(direct))))

    # B. delegation ----------------------------------------------------------

    def test_delegates_to_director_service(self):
        captured = {}
        real = fd.FabricDirectorService.assess_integration

        def spy(service, worktree, **kwargs):
            captured.update(worktree=worktree, ledger_root=service.integration_ledger_root(), **kwargs)
            return real(service, worktree, **kwargs)

        with mock.patch.object(fd.FabricDirectorService, "assess_integration", spy):
            self.run_cli_json(self.assess_argv(scopes=["src", "docs"]))
        self.assertEqual(captured, {
            "worktree": str(self.fx.wt), "attested_sha": self.fx.c1, "authorized_scopes": ["src", "docs"],
            "expected_remote_url": None, "evidence": good_evidence(self.fx), "ledger_root": self.factory_root,
        })

    # C/D. fail-closed projections -----------------------------------------

    def test_missing_information_is_fail_closed_projection(self):
        cases = (
            (dict(attested=None), ri.BASE_UNVERIFIED, ri.BASE_UNATTESTED),
            (dict(attested="not-a-sha"), ri.BASE_UNVERIFIED, ri.BASE_INVALID_ATTESTATION),
            (dict(scopes=()), ri.UNAUTHORIZED_CHANGED_PATHS, "SCOPE_INVALID"),
            (dict(evidence=False), ri.EVIDENCE_MISSING, "EVIDENCE_MISSING"),
        )
        for kwargs, classification, reason in cases:
            with self.subTest(kwargs=kwargs):
                exit_code, output = self.run_cli(self.assess_argv(**kwargs))
                self.assertEqual(exit_code, 0, output)
                self.assertProjected(json.loads(output), classification, reason)

    def test_invalid_or_stale_evidence_is_fail_closed(self):
        for payload, reason in (
            (good_evidence(self.fx, safety_verdict="UNSAFE"), "EVIDENCE_NOT_SAFE"),
            (good_evidence(self.fx, head_sha=self.fx.c1), "EVIDENCE_HEAD_MISMATCH"),
            ([1, 2, 3], "EVIDENCE_INVALID"),
            (None, "EVIDENCE_MISSING"),
        ):
            with self.subTest(reason=reason):
                self.write_evidence(payload)
                self.assertProjected(self.run_cli_json(self.assess_argv()), ri.EVIDENCE_MISSING, reason)

    def test_unreadable_worktree_is_fail_closed_projection(self):
        argv = self._roots_argv() + ["assess-integration", "--worktree", str(self.root / "missing")]
        self.assertProjected(self.run_cli_json(argv), ri.UNSAFE_WORKTREE, "GIT_READ_FAILED")

    # E. ownership ------------------------------------------------------------

    def test_ownership_conflict_projection(self):
        flog.FactoryLedger(self.factory_root).append(
            flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt),
        )
        result = self.run_cli_json(self.assess_argv())
        self.assertProjected(result, ri.OWNERSHIP_CONFLICT, "ACTIVE_WORKER")
        self.assertEqual(result["candidate"]["active_workers"], [["p1", "w1"]])

    def test_missing_factory_ledger_fails_closed_even_with_no_factory_ledger(self):
        argv = self.assess_argv()
        argv[argv.index("--factory-root") + 1] = str(self.root / "absent-factory")
        for extra in ([], ["--no-factory-ledger"]):
            with self.subTest(extra=extra):
                result = self.run_cli_json(extra + argv)
                self.assertProjected(result, ri.OWNERSHIP_CONFLICT, "LEDGER_UNREADABLE")
        self.assertFalse((self.root / "absent-factory").exists())

    # G. stability ------------------------------------------------------------

    def test_fingerprint_and_reason_codes_are_stable(self):
        first, second = self.run_cli_json(self.assess_argv()), self.run_cli_json(self.assess_argv())
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.write_evidence(good_evidence(self.fx, decision_code="REVIEW_REQUIRED"))
        third, fourth = self.run_cli_json(self.assess_argv()), self.run_cli_json(self.assess_argv())
        self.assertEqual(third["reason_codes"], fourth["reason_codes"])
        self.assertEqual(third["fingerprint"], fourth["fingerprint"])
        self.assertNotEqual(third["fingerprint"], first["fingerprint"])

    # H. CLI validation and structured errors ----------------------------------

    def test_missing_worktree_is_usage_error(self):
        err = io.StringIO()
        with redirect_stderr(err):
            exit_code, output = self.run_cli(self._roots_argv() + ["assess-integration"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(output, "")
        self.assertIn("--worktree", err.getvalue())

    def test_unreadable_evidence_file_is_cli_error(self):
        argv = self.assess_argv()
        argv[argv.index("--evidence-file") + 1] = str(self.root / "no-such-evidence.json")
        exit_code, output, err = self.run_cli_err(argv)
        self.assertEqual(exit_code, 1)
        self.assertEqual(output, "")
        self.assertTrue(err.startswith("error: cannot read --evidence-file "), err)

    def test_malformed_evidence_json_is_cli_error(self):
        self.evidence_file.write_text("{not json", encoding="utf-8")
        with mock.patch.object(fd.integration, "assess_integration") as core:
            exit_code, output, err = self.run_cli_err(self.assess_argv())
        core.assert_not_called()
        self.assertEqual(exit_code, 1)
        self.assertEqual(output, "")
        self.assertIn("is not valid JSON", err)

    def test_director_error_is_structured_stderr(self):
        with mock.patch.object(
            fd.FabricDirectorService, "assess_integration",
            side_effect=fd.DirectorError("INVALID_SPEC", "authorized_scopes must be a list of strings"),
        ):
            exit_code, output, err = self.run_cli_err(self.assess_argv())
        self.assertEqual(exit_code, 1)
        self.assertEqual(output, "")
        self.assertEqual(err, "error: INVALID_SPEC: authorized_scopes must be a list of strings\n")

    # I. existing commands ------------------------------------------------------

    def test_existing_commands_remain_registered(self):
        parser = cli.build_arg_parser()
        sub = next(a for a in parser._actions if isinstance(a, cli.argparse._SubParsersAction))
        self.assertLessEqual(
            {"project-state", "submit", "submit-run", "status", "result", "evidence", "decision",
             "recover-submit", "recover-run", "assess-integration"},
            set(sub.choices),
        )
        result = self.run_cli_json(self._roots_argv() + ["project-state", "--worktree", str(self.fx.wt)])
        self.assertEqual(result["branch"], FEATURE)

    def test_direct_script_help_lists_assess_integration(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, str(CLI_PATH), "assess-integration", "--help"],
            cwd=str(self.root), env=env, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for flag in ("--worktree", "--attested-sha", "--authorize-path", "--expected-remote-url", "--evidence-file"):
            self.assertIn(flag, proc.stdout)

    # J. no Git writes or integration actions ----------------------------------

    def test_assessment_performs_no_git_writes(self):
        def state():
            return tuple(
                _git(repo, *args).stdout
                for repo in (self.fx.repo, self.fx.wt)
                for args in (("for-each-ref",), ("rev-parse", "HEAD"), ("symbolic-ref", "HEAD"),
                             ("status", "--porcelain=v1", "--untracked-files=all"), ("worktree", "list", "--porcelain"))
            )

        before = state()
        with mock.patch.object(ri.runner_git, "run", wraps=ri.runner_git.run) as spy:
            result = self.run_cli_json(self.assess_argv())
        self.assertProjected(result, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertEqual(state(), before)
        subcommands = {next(x for x in call.args[1] if not x.startswith("-")) for call in spy.call_args_list}
        self.assertTrue(subcommands)
        self.assertLessEqual(subcommands, ri._READ_SUBCOMMANDS)
        self.assertFalse(self.director_root.exists())
        self.assertFalse(self.state_root.exists())

    def test_cli_assessment_is_a_single_service_delegation(self):
        tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "assess_integration"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].func.value.id, "service")
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("runner_integration", Path(cli.__file__).read_text(encoding="utf-8"))
        self.assertFalse(names & {"classify_integration", "inspect_candidate", "resolve_canonical_base"})


if __name__ == "__main__":
    unittest.main()
