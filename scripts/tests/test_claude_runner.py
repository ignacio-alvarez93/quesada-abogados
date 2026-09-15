import json
import subprocess
import unittest
from pathlib import Path

from scripts.ai import claude_runner as runner


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _make_git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "runner-tests@example.invalid")
    _git(repo, "config", "user.name", "Runner Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed commit")
    return repo


def _make_work_order(root: Path, text: str = "Report a deterministic repository fact.\n") -> Path:
    path = root / "work_order.txt"
    path.write_text(text, encoding="utf-8")
    return path


class ArgumentValidationTest(unittest.TestCase):
    def test_timeout_must_be_positive(self):
        parser = runner.build_arg_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--repo", "x", "--work-order", "y", "--timeout-seconds", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_timeout_must_be_int(self):
        parser = runner.build_arg_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--repo", "x", "--work-order", "y", "--timeout-seconds", "abc"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_required_repo(self):
        parser = runner.build_arg_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--work-order", "y"])
        self.assertEqual(ctx.exception.code, 2)

    def test_defaults_applied(self):
        parser = runner.build_arg_parser()
        args = parser.parse_args(["--repo", "x", "--work-order", "y"])
        self.assertEqual(args.timeout_seconds, runner.DEFAULT_TIMEOUT_SECONDS)
        self.assertIsNone(args.model)
        self.assertIsNone(args.run_root)
        self.assertIsNone(args.label)


class RepositoryValidationTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_path_raises_invalid_repository(self):
        with self.assertRaises(runner.RunnerError) as ctx:
            runner.validate_repository_path(str(self.root / "does-not-exist"))
        self.assertEqual(ctx.exception.state, runner.RunState.INVALID_REPOSITORY)

    def test_file_instead_of_directory_raises_invalid_repository(self):
        f = self.root / "afile.txt"
        f.write_text("x", encoding="utf-8")
        with self.assertRaises(runner.RunnerError) as ctx:
            runner.validate_repository_path(str(f))
        self.assertEqual(ctx.exception.state, runner.RunState.INVALID_REPOSITORY)

    def test_plain_directory_is_not_a_git_worktree(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertFalse(runner.is_git_worktree(plain))
        with self.assertRaises(runner.RunnerError) as ctx:
            runner.validate_git_worktree(plain)
        self.assertEqual(ctx.exception.state, runner.RunState.INVALID_REPOSITORY)

    def test_real_git_repo_is_a_worktree(self):
        repo = _make_git_repo(self.root)
        self.assertTrue(runner.is_git_worktree(repo))
        runner.validate_git_worktree(repo)  # must not raise


class GitSnapshotTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_snapshot_reports_clean_status_on_fresh_repo(self):
        snap = runner.capture_git_snapshot(self.repo)
        # --branch always emits a "## <branch>" header line; a clean tree
        # has no other status lines beyond that.
        status_lines = [
            line for line in snap.porcelain_status.splitlines() if not line.startswith("##")
        ]
        self.assertEqual(status_lines, [])
        self.assertTrue(len(snap.head) > 0)
        self.assertIn("branch:", snap.raw_text)

    def test_compare_detects_new_untracked_file(self):
        before = runner.capture_git_snapshot(self.repo)
        (self.repo / "new_file.txt").write_text("mutated\n", encoding="utf-8")
        after = runner.capture_git_snapshot(self.repo)
        safety = runner.compare_git_snapshots(before, after)
        self.assertTrue(safety.repository_mutated)
        self.assertTrue(safety.status_changed)
        self.assertFalse(safety.head_changed)
        self.assertFalse(safety.branch_changed)

    def test_compare_detects_head_change(self):
        before = runner.capture_git_snapshot(self.repo)
        (self.repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
        _git(self.repo, "add", "tracked.txt")
        _git(self.repo, "commit", "-q", "-m", "second commit")
        after = runner.capture_git_snapshot(self.repo)
        safety = runner.compare_git_snapshots(before, after)
        self.assertTrue(safety.repository_mutated)
        self.assertTrue(safety.head_changed)

    def test_compare_clean_when_nothing_changes(self):
        before = runner.capture_git_snapshot(self.repo)
        after = runner.capture_git_snapshot(self.repo)
        safety = runner.compare_git_snapshots(before, after)
        self.assertFalse(safety.repository_mutated)
        self.assertEqual(safety.notes, [])


class WorkOrderValidationTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_raises_invalid_work_order(self):
        with self.assertRaises(runner.RunnerError) as ctx:
            runner.validate_work_order(str(self.root / "missing.txt"))
        self.assertEqual(ctx.exception.state, runner.RunState.INVALID_WORK_ORDER)

    def test_empty_file_raises_invalid_work_order(self):
        path = self.root / "empty.txt"
        path.write_text("   \n", encoding="utf-8")
        with self.assertRaises(runner.RunnerError) as ctx:
            runner.validate_work_order(str(path))
        self.assertEqual(ctx.exception.state, runner.RunState.INVALID_WORK_ORDER)

    def test_oversized_file_raises_invalid_work_order(self):
        path = self.root / "big.txt"
        path.write_text("x" * (runner.MAX_WORK_ORDER_CHARS + 1), encoding="utf-8")
        with self.assertRaises(runner.RunnerError) as ctx:
            runner.validate_work_order(str(path))
        self.assertEqual(ctx.exception.state, runner.RunState.INVALID_WORK_ORDER)

    def test_valid_file_returns_text(self):
        path = _make_work_order(self.root, "do the thing\n")
        resolved, text = runner.validate_work_order(str(path))
        self.assertEqual(resolved, path.resolve())
        self.assertEqual(text, "do the thing\n")


class CliCommandTest(unittest.TestCase):
    def test_command_is_read_only_and_non_interactive(self):
        cmd = runner.build_cli_command("claude", model=None)
        self.assertIn("--print", cmd)
        self.assertIn("--restricted", cmd)
        joined = " ".join(cmd)
        self.assertIn("--tools Read,Grep,Glob", joined)
        self.assertIn("--permission-prompts none", joined)
        self.assertIn("--output-format json", joined)
        self.assertNotIn("Bash", cmd)
        self.assertNotIn("--resume", cmd)
        self.assertNotIn("-r", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)

    def test_model_is_appended_when_given(self):
        cmd = runner.build_cli_command("claude", model="sonnet")
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")

    def test_model_omitted_when_not_given(self):
        cmd = runner.build_cli_command("claude", model=None)
        self.assertNotIn("--model", cmd)


class ParseCliResultTest(unittest.TestCase):
    def test_parses_valid_json(self):
        payload = json.dumps({"result": "PONG", "is_error": False})
        parsed = runner.parse_cli_result(payload)
        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["cli_result"]["result"], "PONG")

    def test_empty_stdout(self):
        parsed = runner.parse_cli_result("")
        self.assertFalse(parsed["parsed"])
        self.assertEqual(parsed["reason"], "empty stdout")

    def test_invalid_json(self):
        parsed = runner.parse_cli_result("not json at all")
        self.assertFalse(parsed["parsed"])
        self.assertIn("raw_excerpt", parsed)


class ClassifyStateTest(unittest.TestCase):
    def _make_outcome(self, **overrides):
        base = dict(
            returncode=0, stdout="", stderr="", timed_out=False,
            interrupted=False, duration_seconds=1.0,
        )
        base.update(overrides)
        return runner.ProcessOutcome(**base)

    def _clean_safety(self):
        return runner.SafetyCheck(
            repository_mutated=False, branch_changed=False,
            head_changed=False, status_changed=False, notes=[],
        )

    def _mutated_safety(self):
        return runner.SafetyCheck(
            repository_mutated=True, branch_changed=False,
            head_changed=False, status_changed=True, notes=["x"],
        )

    def test_safety_violation_overrides_success(self):
        outcome = self._make_outcome(returncode=0)
        parsed = {"parsed": True, "cli_result": {"is_error": False}}
        state = runner.classify_state(outcome, self._mutated_safety(), parsed)
        self.assertEqual(state, runner.RunState.FAILED_SAFETY)

    def test_timeout_state(self):
        outcome = self._make_outcome(timed_out=True, returncode=None)
        state = runner.classify_state(outcome, self._clean_safety(), {"parsed": False})
        self.assertEqual(state, runner.RunState.TIMEOUT)

    def test_interrupted_state(self):
        outcome = self._make_outcome(interrupted=True, returncode=None)
        state = runner.classify_state(outcome, self._clean_safety(), {"parsed": False})
        self.assertEqual(state, runner.RunState.INTERRUPTED)

    def test_nonzero_returncode_is_claude_error(self):
        outcome = self._make_outcome(returncode=1)
        state = runner.classify_state(outcome, self._clean_safety(), {"parsed": False})
        self.assertEqual(state, runner.RunState.CLAUDE_ERROR)

    def test_is_error_true_is_claude_error(self):
        outcome = self._make_outcome(returncode=0)
        parsed = {"parsed": True, "cli_result": {"is_error": True}}
        state = runner.classify_state(outcome, self._clean_safety(), parsed)
        self.assertEqual(state, runner.RunState.CLAUDE_ERROR)

    def test_success_state(self):
        outcome = self._make_outcome(returncode=0)
        parsed = {"parsed": True, "cli_result": {"is_error": False, "result": "PONG"}}
        state = runner.classify_state(outcome, self._clean_safety(), parsed)
        self.assertEqual(state, runner.RunState.SUCCESS)


class CreateRunDirTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_location_is_under_repo_runtime(self):
        run_dir = runner.create_run_dir(self.repo, None, None)
        self.assertTrue(run_dir.exists())
        self.assertEqual(run_dir.parent, self.repo / "runtime" / "claude_runner" / "runs")

    def test_two_calls_produce_distinct_directories(self):
        first = runner.create_run_dir(self.repo, None, None)
        second = runner.create_run_dir(self.repo, None, None)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_run_root_override(self):
        override = self.root / "custom_evidence"
        run_dir = runner.create_run_dir(self.repo, str(override), None)
        self.assertEqual(run_dir.parent, override)

    def test_label_is_sanitized_and_appended(self):
        run_dir = runner.create_run_dir(self.repo, None, "weird label!!")
        self.assertTrue(run_dir.name.endswith("weird_label__"))


class MainEndToEndTest(unittest.TestCase):
    """Exercises main() with invoke_claude monkeypatched so no live Claude
    quota is consumed and no real Claude CLI call is made."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = runner.get_claude_executable
        runner.get_claude_executable = lambda: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        runner.get_claude_executable = self._orig_get_exec
        self._tmp.cleanup()

    def _run_main(self, extra_args=None):
        args = [
            "--repo", str(self.repo),
            "--work-order", str(self.work_order),
        ] + (extra_args or [])
        return runner.main(args)

    def test_invalid_repository_path_no_run_dir_created(self):
        code = runner.main([
            "--repo", str(self.root / "nope"),
            "--work-order", str(self.work_order),
        ])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.INVALID_REPOSITORY])
        self.assertFalse((self.root / "nope").exists())

    def test_repo_not_a_worktree_writes_evidence(self):
        plain = self.root / "plain_dir"
        plain.mkdir()
        code = runner.main([
            "--repo", str(plain),
            "--work-order", str(self.work_order),
        ])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.INVALID_REPOSITORY])
        runs = list((plain / "runtime" / "claude_runner" / "runs").iterdir())
        self.assertEqual(len(runs), 1)
        run_dir = runs[0]
        for name in ("prompt.txt", "stdout.txt", "stderr.txt", "metadata.json",
                     "result.json", "git_before.txt", "git_after.txt"):
            self.assertTrue((run_dir / name).exists(), name)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "INVALID_REPOSITORY")

    def test_invalid_work_order_writes_evidence(self):
        code = runner.main([
            "--repo", str(self.repo),
            "--work-order", str(self.root / "missing_wo.txt"),
        ])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.INVALID_WORK_ORDER])
        runs = list((self.repo / "runtime" / "claude_runner" / "runs").iterdir())
        self.assertEqual(len(runs), 1)
        result = json.loads((runs[0] / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["state"], "INVALID_WORK_ORDER")

    def test_success_path_creates_all_artifacts(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            payload = json.dumps({"result": "PONG", "is_error": False, "type": "result"})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.5,
            )

        runner.invoke_claude = fake_invoke
        code = self._run_main()
        self.assertEqual(code, 0)

        runs = list((self.repo / "runtime" / "claude_runner" / "runs").iterdir())
        self.assertEqual(len(runs), 1)
        run_dir = runs[0]
        for name in ("prompt.txt", "stdout.txt", "stderr.txt", "metadata.json",
                     "result.json", "git_before.txt", "git_after.txt"):
            self.assertTrue((run_dir / name).exists(), name)

        self.assertEqual((run_dir / "prompt.txt").read_text(encoding="utf-8"),
                          self.work_order.read_text(encoding="utf-8"))
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "SUCCESS")
        self.assertEqual(metadata["exit_code"], 0)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(result["safety_check"]["repository_mutated"])

    def test_claude_error_on_nonzero_returncode(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            return runner.ProcessOutcome(
                returncode=1, stdout="", stderr="boom", timed_out=False,
                interrupted=False, duration_seconds=0.1,
            )

        runner.invoke_claude = fake_invoke
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.CLAUDE_ERROR])

    def test_timeout_state_end_to_end(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            return runner.ProcessOutcome(
                returncode=None, stdout="", stderr="", timed_out=True,
                interrupted=False, duration_seconds=timeout_seconds,
            )

        runner.invoke_claude = fake_invoke
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.TIMEOUT])

    def test_failed_safety_when_invocation_mutates_repository(self):
        """Simulates a rogue tool call mutating the repo during invocation
        and proves the runner detects it, reports FAILED_SAFETY, and does
        NOT clean up or revert the mutation."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "unexpected_write.txt").write_text("mutated by run\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.2,
            )

        runner.invoke_claude = fake_invoke
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.FAILED_SAFETY])
        # The mutation must still be present: the runner must never
        # silently clean, restore, or reset it.
        self.assertTrue((self.repo / "unexpected_write.txt").exists())

        runs = list((self.repo / "runtime" / "claude_runner" / "runs").iterdir())
        result = json.loads((runs[0] / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["safety_check"]["repository_mutated"])


class GetClaudeExecutableTest(unittest.TestCase):
    def test_raises_claude_error_when_not_on_path(self):
        import shutil as shutil_mod
        orig = shutil_mod.which
        shutil_mod.which = lambda name: None
        try:
            with self.assertRaises(runner.RunnerError) as ctx:
                runner.get_claude_executable()
            self.assertEqual(ctx.exception.state, runner.RunState.CLAUDE_ERROR)
        finally:
            shutil_mod.which = orig


if __name__ == "__main__":
    unittest.main()
