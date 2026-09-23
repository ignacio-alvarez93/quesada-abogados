import json
import subprocess
import unittest
from pathlib import Path

from scripts.ai import claude_runner as runner
from scripts.ai import runner_providers as providers


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
    # Force the initial branch name so these tests do not depend on the
    # host's init.defaultBranch config (observed as "master" here, but
    # RUNNER-1C's branch-guard tests need a deterministic "main").
    _git(repo, "init", "-q", "-b", "main")
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

    def test_label_is_hashed_not_embedded_raw(self):
        """R21-A-FIX1: the leaf name never embeds raw label text (which
        could itself be long/unsafe for a filesystem path); it carries a
        short, deterministic digest instead."""
        import hashlib

        run_dir = runner.create_run_dir(self.repo, None, "weird label!!")
        digest = hashlib.sha1("weird label!!".encode("utf-8")).hexdigest()[:10]
        self.assertTrue(run_dir.name.endswith(f"_{digest}"))
        self.assertNotIn("weird", run_dir.name)

    def test_leaf_name_is_bounded_regardless_of_label_length(self):
        """R21-A-FIX1 / Windows path bounding: a giant label (e.g. a
        pipeline orchestrator's "<pipeline_id>-<worker_id>", each up to 64
        chars) must never make the run directory's own leaf name grow
        unboundedly - only ancestor directories this function does not
        control may still be long."""
        giant_label = ("pipeline-" + "p" * 64) + "-" + ("worker-" + "w" * 64)
        run_dir = runner.create_run_dir(self.repo, None, giant_label)
        self.assertLessEqual(len(run_dir.name), 40)

    def test_same_label_produces_same_digest_across_calls(self):
        """Deterministic: two runs sharing a label get the same digest
        fragment (diagnostics can group them), while the timestamp/uuid
        prefix still keeps the directories distinct."""
        first = runner.create_run_dir(self.repo, None, "night-001-worker-a")
        second = runner.create_run_dir(self.repo, None, "night-001-worker-a")
        self.assertNotEqual(first, second)
        self.assertEqual(first.name.rsplit("_", 1)[1], second.name.rsplit("_", 1)[1])

    def test_distinct_labels_sharing_a_truncation_prefix_do_not_collide(self):
        """A raw-text-truncation scheme could make two different long
        labels indistinguishable; the digest must not."""
        label_a = "x" * 60 + "-AAAA"
        label_b = "x" * 60 + "-BBBB"
        run_a = runner.create_run_dir(self.repo, None, label_a)
        run_b = runner.create_run_dir(self.repo, None, label_b)
        self.assertNotEqual(run_a.name.rsplit("_", 1)[1], run_b.name.rsplit("_", 1)[1])


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
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
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


class EvidenceSelfMutationExclusionTest(unittest.TestCase):
    """Runner V2.1 R21-A-FIX1: Runner-owned pre-invocation evidence
    bookkeeping (the evidence run directory and `git_before.txt`, created
    UNDER the repository before the provider ever runs) must never be
    attributed to the provider by the post-run safety comparison, while a
    genuine provider mutation - authorized or not - must still be caught.
    These tests deliberately use no repository-level ignore rule for the
    evidence path, so the exclusion must come from the comparison baseline
    itself, not from `.gitignore`."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def test_evidence_bookkeeping_alone_is_not_reported_as_mutation(self):
        """A no-op provider run, with the evidence dir left untracked and
        un-ignored inside the repo, must still be SAFE/SUCCESS: the evidence
        run directory and git_before.txt are the only filesystem writes
        that happen before the safety baseline is captured."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            payload = json.dumps({"result": "PONG", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.1,
            )

        runner.invoke_claude = fake_invoke
        request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
        result = runner.execute_work_order(request)

        self.assertEqual(result.state, runner.RunState.SUCCESS)
        metadata = json.loads((result.evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["safety_baseline_excludes_runner_evidence"])
        self.assertFalse(metadata["changed_paths_after_run"])
        result_payload = json.loads((result.evidence_dir / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(result_payload["safety_check"]["repository_mutated"])

    def test_provider_unauthorized_mutation_still_detected_in_read_only_mode(self):
        """The exclusion is narrow: a REAL provider-caused mutation must
        still fail safe, even with the evidence directory present and
        un-ignored."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "rogue.txt").write_text("mutated\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.1,
            )

        runner.invoke_claude = fake_invoke
        request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
        result = runner.execute_work_order(request)

        self.assertEqual(result.state, runner.RunState.FAILED_SAFETY)
        metadata = json.loads((result.evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertIn("?? rogue.txt", metadata["changed_paths_after_run"])
        # The evidence tree itself must never appear in the diff at all.
        self.assertFalse(
            any("runtime" in line for line in metadata["changed_paths_after_run"]),
            metadata["changed_paths_after_run"],
        )

    def test_evidence_metadata_carries_full_label_despite_bounded_leaf_name(self):
        """Requirement G: a long, identifying label (pipeline_id-worker_id
        style) is never lost even though it no longer appears in the run
        directory's own (bounded) leaf name."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            payload = json.dumps({"result": "PONG", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.1,
            )

        runner.invoke_claude = fake_invoke
        giant_label = ("night-shift-pipeline-" + "p" * 64) + "-" + ("worker-" + "w" * 64)
        request = runner.WorkOrderRequest(
            repo=str(self.repo), work_order=str(self.work_order), label=giant_label,
        )
        result = runner.execute_work_order(request)

        self.assertEqual(result.state, runner.RunState.SUCCESS)
        self.assertLessEqual(len(result.evidence_dir.name), 40)
        metadata = json.loads((result.evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["label"], giant_label)


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


# ---------------------------------------------------------------------------
# RUNNER-1C: write mode
# ---------------------------------------------------------------------------

class WriteModeArgumentValidationTest(unittest.TestCase):
    def test_mode_defaults_to_read_only(self):
        parser = runner.build_arg_parser()
        args = parser.parse_args(["--repo", "x", "--work-order", "y"])
        self.assertEqual(args.mode, runner.MODE_READ_ONLY)
        self.assertFalse(args.allow_dirty)

    def test_mode_write_is_accepted(self):
        parser = runner.build_arg_parser()
        args = parser.parse_args(["--repo", "x", "--work-order", "y", "--mode", "write"])
        self.assertEqual(args.mode, runner.MODE_WRITE)

    def test_invalid_mode_rejected(self):
        parser = runner.build_arg_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--repo", "x", "--work-order", "y", "--mode", "bogus"])
        self.assertEqual(ctx.exception.code, 2)

    def test_allow_dirty_flag(self):
        parser = runner.build_arg_parser()
        args = parser.parse_args(["--repo", "x", "--work-order", "y", "--mode", "write", "--allow-dirty"])
        self.assertTrue(args.allow_dirty)


class WriteModeCliCommandTest(unittest.TestCase):
    def test_write_mode_adds_editing_tools_but_never_bash(self):
        cmd = runner.build_cli_command("claude", model=None, mode=runner.MODE_WRITE)
        joined = " ".join(cmd)
        self.assertIn("--tools Read,Grep,Glob,Edit,Write,NotebookEdit", joined)
        self.assertIn("--restricted", cmd)
        self.assertNotIn("Bash", cmd)
        self.assertNotIn("PowerShell", cmd)
        self.assertNotIn("--resume", cmd)
        self.assertNotIn("-r", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertNotIn("--allow-dangerously-skip-permissions", cmd)

    def test_write_mode_uses_accept_edits_permission_mode(self):
        # Verified live against the installed CLI: "dontAsk" auto-denies
        # Write/Edit (no approver), which silently no-ops every write-mode
        # run; "acceptEdits" is required for Write/Edit to actually take
        # effect while --restricted still blocks git/settings files.
        cmd = runner.build_cli_command("claude", model=None, mode=runner.MODE_WRITE)
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "acceptEdits")

    def test_read_only_mode_still_uses_dont_ask(self):
        cmd = runner.build_cli_command("claude", model=None, mode=runner.MODE_READ_ONLY)
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")

    def test_read_only_mode_explicit_matches_default(self):
        explicit = runner.build_cli_command("claude", model=None, mode=runner.MODE_READ_ONLY)
        default = runner.build_cli_command("claude", model=None)
        self.assertEqual(explicit, default)
        self.assertIn("--tools Read,Grep,Glob", " ".join(explicit))


class BranchGuardTest(unittest.TestCase):
    def _snap(self, branch: str) -> runner.GitSnapshot:
        return runner.GitSnapshot(
            branch=branch, head="deadbeef", porcelain_status=f"## {branch}\n",
            raw_text="", captured_at="now",
        )

    def test_allows_feature_branch(self):
        decision = runner.evaluate_branch_guard(self._snap("feature/claude-runner"))
        self.assertEqual(decision.decision, "ALLOWED")

    def test_refuses_main(self):
        decision = runner.evaluate_branch_guard(self._snap("main"))
        self.assertEqual(decision.decision, "REFUSED_PROTECTED_BRANCH")

    def test_refuses_master(self):
        decision = runner.evaluate_branch_guard(self._snap("master"))
        self.assertEqual(decision.decision, "REFUSED_PROTECTED_BRANCH")

    def test_refuses_develop(self):
        decision = runner.evaluate_branch_guard(self._snap("develop"))
        self.assertEqual(decision.decision, "REFUSED_PROTECTED_BRANCH")

    def test_refuses_detached_head(self):
        decision = runner.evaluate_branch_guard(self._snap("HEAD"))
        self.assertEqual(decision.decision, "REFUSED_DETACHED_HEAD")


class DirtyTreeGuardTest(unittest.TestCase):
    def _snap(self, status_body: str) -> runner.GitSnapshot:
        return runner.GitSnapshot(
            branch="feature/x", head="deadbeef",
            porcelain_status=f"## feature/x\n{status_body}",
            raw_text="", captured_at="now",
        )

    def test_clean_tree_allowed(self):
        decision = runner.evaluate_dirty_tree(self._snap(""))
        self.assertEqual(decision.decision, "ALLOWED_CLEAN")
        self.assertEqual(decision.preexisting_dirty_paths, [])

    def test_dirty_tree_always_refused(self):
        decision = runner.evaluate_dirty_tree(self._snap(" M tracked.txt\n"))
        self.assertEqual(decision.decision, "REFUSED_DIRTY")
        self.assertEqual(decision.preexisting_dirty_paths, [" M tracked.txt"])

    def test_dirty_tree_refused_even_with_multiple_paths(self):
        decision = runner.evaluate_dirty_tree(self._snap(" M tracked.txt\n?? new.txt\n"))
        self.assertEqual(decision.decision, "REFUSED_DIRTY")
        self.assertEqual(decision.preexisting_dirty_paths, [" M tracked.txt", "?? new.txt"])


class ComputeChangedPathsTest(unittest.TestCase):
    def _snap(self, status_body: str) -> runner.GitSnapshot:
        return runner.GitSnapshot(
            branch="feature/x", head="deadbeef",
            porcelain_status=f"## feature/x\n{status_body}",
            raw_text="", captured_at="now",
        )

    def test_no_change_on_clean_run(self):
        before = self._snap("")
        after = self._snap("")
        self.assertEqual(runner.compute_changed_paths_after_run(before, after), [])

    def test_new_file_detected_on_clean_before(self):
        before = self._snap("")
        after = self._snap("?? created.txt\n")
        self.assertEqual(runner.compute_changed_paths_after_run(before, after), ["?? created.txt"])

    def test_preexisting_dirty_path_excluded_from_runner_caused_changes(self):
        before = self._snap(" M preexisting.txt\n")
        after = self._snap(" M preexisting.txt\n?? new_by_run.txt\n")
        self.assertEqual(
            runner.compute_changed_paths_after_run(before, after),
            ["?? new_by_run.txt"],
        )


class WriteModeSafetyVerdictTest(unittest.TestCase):
    def test_file_changes_alone_are_safe_in_write_mode(self):
        safety = runner.SafetyCheck(
            repository_mutated=True, branch_changed=False,
            head_changed=False, status_changed=True, notes=["x"],
        )
        verdict = runner.evaluate_write_mode_safety(safety)
        self.assertEqual(verdict.verdict, "SAFE")

    def test_branch_change_is_failed_safety_in_write_mode(self):
        safety = runner.SafetyCheck(
            repository_mutated=True, branch_changed=True,
            head_changed=False, status_changed=False, notes=["x"],
        )
        verdict = runner.evaluate_write_mode_safety(safety)
        self.assertEqual(verdict.verdict, "FAILED_SAFETY")

    def test_head_change_is_failed_safety_in_write_mode(self):
        safety = runner.SafetyCheck(
            repository_mutated=True, branch_changed=False,
            head_changed=True, status_changed=False, notes=["x"],
        )
        verdict = runner.evaluate_write_mode_safety(safety)
        self.assertEqual(verdict.verdict, "FAILED_SAFETY")


class WriteModeClassifyStateTest(unittest.TestCase):
    def _make_outcome(self, **overrides):
        base = dict(returncode=0, stdout="", stderr="", timed_out=False,
                    interrupted=False, duration_seconds=1.0)
        base.update(overrides)
        return runner.ProcessOutcome(**base)

    def test_write_mode_tolerates_status_change(self):
        safety = runner.SafetyCheck(
            repository_mutated=True, branch_changed=False,
            head_changed=False, status_changed=True, notes=["x"],
        )
        parsed = {"parsed": True, "cli_result": {"is_error": False}}
        state = runner.classify_state(self._make_outcome(), safety, parsed, mode=runner.MODE_WRITE)
        self.assertEqual(state, runner.RunState.SUCCESS)

    def test_write_mode_fails_safety_on_branch_change(self):
        safety = runner.SafetyCheck(
            repository_mutated=True, branch_changed=True,
            head_changed=False, status_changed=False, notes=["x"],
        )
        parsed = {"parsed": True, "cli_result": {"is_error": False}}
        state = runner.classify_state(self._make_outcome(), safety, parsed, mode=runner.MODE_WRITE)
        self.assertEqual(state, runner.RunState.FAILED_SAFETY)

    def test_read_only_default_still_fails_on_any_mutation(self):
        safety = runner.SafetyCheck(
            repository_mutated=True, branch_changed=False,
            head_changed=False, status_changed=True, notes=["x"],
        )
        parsed = {"parsed": True, "cli_result": {"is_error": False}}
        state = runner.classify_state(self._make_outcome(), safety, parsed)
        self.assertEqual(state, runner.RunState.FAILED_SAFETY)


class WriteModeMainEndToEndTest(unittest.TestCase):
    """Exercises main() with --mode write and invoke_claude monkeypatched
    so no live Claude quota is consumed and no real Claude CLI call is
    made."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        _git(self.repo, "checkout", "-q", "-b", "feature/write-mode-test")
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def _run_main(self, extra_args=None):
        args = [
            "--repo", str(self.repo),
            "--work-order", str(self.work_order),
            "--mode", "write",
        ] + (extra_args or [])
        return runner.main(args)

    def _runs_dir(self):
        return self.repo / "runtime" / "claude_runner" / "runs"

    def test_refused_on_main_branch(self):
        _git(self.repo, "checkout", "-q", "main")
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.BRANCH_GUARD_REFUSED])
        run_dir = list(self._runs_dir().iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "BRANCH_GUARD_REFUSED")
        self.assertEqual(metadata["branch_guard"]["decision"], "REFUSED_PROTECTED_BRANCH")

    def test_refused_on_develop_branch(self):
        _git(self.repo, "checkout", "-q", "-b", "develop")
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.BRANCH_GUARD_REFUSED])

    def test_refused_on_detached_head(self):
        head = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        _git(self.repo, "checkout", "-q", head)
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.BRANCH_GUARD_REFUSED])
        run_dir = list(self._runs_dir().iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["branch_guard"]["decision"], "REFUSED_DETACHED_HEAD")

    def test_refused_on_dirty_tree(self):
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.DIRTY_TREE_REFUSED])
        run_dir = list(self._runs_dir().iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "DIRTY_TREE_REFUSED")
        self.assertEqual(metadata["dirty_tree_policy"]["decision"], "REFUSED_DIRTY")

    def test_allow_dirty_flag_does_not_permit_dirty_write_execution(self):
        """RUNNER-1F: --allow-dirty is unsupported for write execution and
        has no effect - a dirty tree is refused before invoke_claude
        regardless of whether the flag is supplied."""
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code = self._run_main(["--allow-dirty", "--authorize-path", "README.md"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.DIRTY_TREE_REFUSED])
        self.assertEqual(invoked, [])
        run_dir = list(self._runs_dir().iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "DIRTY_TREE_REFUSED")
        self.assertEqual(metadata["dirty_tree_policy"]["decision"], "REFUSED_DIRTY")

    def test_succeeds_on_clean_feature_branch_and_reports_created_file(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "created_by_run.txt").write_text("hello\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.3,
            )

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "created_by_run.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        self.assertTrue((self.repo / "created_by_run.txt").exists())

        run_dir = list(self._runs_dir().iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["execution_mode"], "write")
        self.assertEqual(metadata["branch_guard"]["decision"], "ALLOWED")
        self.assertEqual(metadata["dirty_tree_policy"]["decision"], "ALLOWED_CLEAN")
        self.assertEqual(metadata["write_scope"]["decision"], "ALLOWED")
        self.assertEqual(metadata["write_scope"]["authorized_scopes"], ["created_by_run.txt"])
        self.assertIn("?? created_by_run.txt", metadata["changed_paths_after_run"])
        self.assertIn("?? created_by_run.txt", metadata["authorized_changed_paths"])
        self.assertEqual(metadata["unauthorized_changed_paths"], [])
        self.assertEqual(metadata["safety_verdict"]["verdict"], "SAFE")

        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertIn("?? created_by_run.txt", result["changed_paths_after_run"])

    def test_dirty_tree_refused_even_when_dirty_path_is_outside_authorized_scope(self):
        """A pre-existing dirty path outside the authorized scope must
        still refuse the run: RUNNER-1F removed the narrower RUNNER-1E
        scope-overlap check (which could not detect a further edit to
        such a path, since it leaves the same porcelain line) in favor of
        an unconditional clean-tree requirement."""
        (self.repo / "README.md").write_text("preexisting dirty change\n", encoding="utf-8")
        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code = self._run_main(["--allow-dirty", "--authorize-path", "new_by_run.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.DIRTY_TREE_REFUSED])
        self.assertEqual(invoked, [])

        run_dir = list(self._runs_dir().iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["dirty_tree_policy"]["decision"], "REFUSED_DIRTY")
        self.assertTrue(any("README.md" in line for line in metadata["preexisting_dirty_paths"]))

    def test_failed_safety_when_run_creates_a_commit(self):
        """Defense-in-depth: no tool granted in write mode can invoke git,
        but if something still advanced HEAD, the runner must still catch
        it and must NOT revert it."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "sneaky.txt").write_text("x\n", encoding="utf-8")
            _git(Path(cwd), "add", "sneaky.txt")
            _git(Path(cwd), "commit", "-q", "-m", "unauthorized commit")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.2,
            )

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "sneaky.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.FAILED_SAFETY])

        run_dir = list(self._runs_dir().iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["safety_verdict"]["verdict"], "FAILED_SAFETY")
        # The unauthorized commit must not be reverted.
        log = _git(self.repo, "log", "--oneline").stdout
        self.assertIn("unauthorized commit", log)

    def test_read_only_mode_unaffected_by_write_mode_flags(self):
        """RUNNER-1B invariant: without --mode write, branch guard and
        dirty-tree guard never trigger, even on main with a dirty tree."""
        _git(self.repo, "checkout", "-q", "main")
        (self.repo / "README.md").write_text("dirty on main\n", encoding="utf-8")

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            payload = json.dumps({"result": "PONG", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.1,
            )

        runner.invoke_claude = fake_invoke
        code = runner.main([
            "--repo", str(self.repo),
            "--work-order", str(self.work_order),
        ])
        # Branch/dirty-tree guards are write-mode-only; a read-only run on
        # main with a dirty tree neither gets refused pre-invocation nor
        # newly mutated by the (no-op) invocation, so it is SUCCESS - the
        # unchanged RUNNER-1B contract this slice must not touch.
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        run_dir = list((self.repo / "runtime" / "claude_runner" / "runs").iterdir())[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertIsNone(metadata["branch_guard"])
        self.assertIsNone(metadata["dirty_tree_policy"])
        self.assertEqual(metadata["execution_mode"], "read-only")


# ---------------------------------------------------------------------------
# Runner V2.1 R21-B: work-product preservation + governed resume
# ---------------------------------------------------------------------------

class ResumeValidationTest(unittest.TestCase):
    """Pure-function coverage of `evaluate_resume` against fabricated
    work-product records: every SAFETY RULES #4 check in isolation,
    independent of any real git repository or Claude CLI invocation."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _snapshot(self, branch="feature/x", head="abc123", dirty_lines=("?? partial.txt",)):
        porcelain = "## feature/x\n" + "".join(f"{line}\n" for line in dirty_lines)
        return runner.GitSnapshot(
            branch=branch, head=head, porcelain_status=porcelain, raw_text="",
            captured_at="2026-01-01T00:00:00+00:00",
        )

    def _write_record(self, name="work_product.json", **overrides):
        record = {
            "schema_version": runner.WORK_PRODUCT_SCHEMA_VERSION,
            "worktree": str(self.repo), "branch": "feature/x", "base_head": "abc123",
            "process_confirmed_stopped": True, "authorized_changed_paths": ["?? partial.txt"],
        }
        record.update(overrides)
        path = self.root / name
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def test_valid_resume_allowed(self):
        record_path = self._write_record()
        decision = runner.evaluate_resume(str(record_path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "ALLOWED_RESUMED")

    def test_missing_record_refused(self):
        decision = runner.evaluate_resume(
            str(self.root / "missing.json"), self.repo, self._snapshot(), ["partial.txt"],
        )
        self.assertEqual(decision.decision, "REFUSED_RECORD_UNREADABLE")

    def test_malformed_json_refused(self):
        path = self.root / "bad.json"
        path.write_text("not json", encoding="utf-8")
        decision = runner.evaluate_resume(str(path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_RECORD_UNREADABLE")

    def test_non_object_json_refused(self):
        path = self.root / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        decision = runner.evaluate_resume(str(path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_RECORD_UNREADABLE")

    def test_schema_version_mismatch_refused(self):
        record_path = self._write_record(schema_version=999)
        decision = runner.evaluate_resume(str(record_path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_SCHEMA_VERSION")

    def test_worktree_mismatch_refused(self):
        record_path = self._write_record(worktree=str(self.root / "other-repo"))
        decision = runner.evaluate_resume(str(record_path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_WORKTREE_MISMATCH")

    def test_branch_mismatch_refused(self):
        record_path = self._write_record()
        snap = self._snapshot(branch="feature/y")
        decision = runner.evaluate_resume(str(record_path), self.repo, snap, ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_BRANCH_MISMATCH")

    def test_head_mismatch_refused(self):
        record_path = self._write_record()
        snap = self._snapshot(head="def456")
        decision = runner.evaluate_resume(str(record_path), self.repo, snap, ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_HEAD_MISMATCH")

    def test_process_not_confirmed_stopped_refused(self):
        """SAFETY RULES #4: prior process confirmed stopped is required -
        a process still alive/unknown must refuse resume."""
        record_path = self._write_record(process_confirmed_stopped=False)
        decision = runner.evaluate_resume(str(record_path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_PROCESS_NOT_CONFIRMED_STOPPED")

    def test_process_confirmed_stopped_missing_field_refused(self):
        record_path = self._write_record()
        raw = json.loads(record_path.read_text(encoding="utf-8"))
        del raw["process_confirmed_stopped"]
        record_path.write_text(json.dumps(raw), encoding="utf-8")
        decision = runner.evaluate_resume(str(record_path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_PROCESS_NOT_CONFIRMED_STOPPED")

    def test_unrecognized_dirty_path_refused(self):
        """An extra dirty file not part of the recorded work product must
        refuse resume, even though it would also be individually authorized."""
        record_path = self._write_record()
        snap = self._snapshot(dirty_lines=("?? partial.txt", "?? stray.txt"))
        decision = runner.evaluate_resume(str(record_path), self.repo, snap, ["partial.txt", "stray.txt"])
        self.assertEqual(decision.decision, "REFUSED_UNRECOGNIZED_DIRTY_PATH")
        self.assertIn("stray.txt", decision.reason)

    def test_dirty_path_out_of_current_scope_refused(self):
        record_path = self._write_record(authorized_changed_paths=["?? partial.txt", "?? extra.txt"])
        snap = self._snapshot(dirty_lines=("?? partial.txt", "?? extra.txt"))
        decision = runner.evaluate_resume(str(record_path), self.repo, snap, ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_DIRTY_PATH_OUT_OF_SCOPE")

    def test_malformed_authorized_changed_paths_refused(self):
        record_path = self._write_record(authorized_changed_paths="not-a-list")
        decision = runner.evaluate_resume(str(record_path), self.repo, self._snapshot(), ["partial.txt"])
        self.assertEqual(decision.decision, "REFUSED_RECORD_MALFORMED")

    def test_clean_tree_against_valid_record_still_allowed(self):
        """No dirty lines left at all: trivially every (empty) constraint holds."""
        record_path = self._write_record()
        snap = self._snapshot(dirty_lines=())
        decision = runner.evaluate_resume(str(record_path), self.repo, snap, ["partial.txt"])
        self.assertEqual(decision.decision, "ALLOWED_RESUMED")


class GovernedResumeMainEndToEndTest(unittest.TestCase):
    """End-to-end wiring of work-product recording and --resume-from through
    `main()`: no live Claude CLI call, `invoke_claude` monkeypatched."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        _git(self.repo, "checkout", "-q", "-b", "feature/resume-test")
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def _runs_dir(self):
        return self.repo / "runtime" / "claude_runner" / "runs"

    def _run_main(self, extra_args):
        args = [
            "--repo", str(self.repo), "--work-order", str(self.work_order), "--mode", "write",
        ] + extra_args
        before = set(self._runs_dir().iterdir()) if self._runs_dir().exists() else set()
        code = runner.main(args)
        after = set(self._runs_dir().iterdir())
        new_dirs = after - before
        assert len(new_dirs) == 1, f"expected exactly one new run dir, got {new_dirs!r}"
        return code, new_dirs.pop()

    def test_dirty_tree_without_resume_token_still_refused(self):
        """A dirty tree left by a prior GOVERNED attempt is NOT automatically
        resumable: without an explicit --resume-from, RUNNER-1F still
        refuses it exactly as before."""
        (self.repo / "partial.txt").write_text("partial work\n", encoding="utf-8")
        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code, _ = self._run_main(["--authorize-path", "partial.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.DIRTY_TREE_REFUSED])
        self.assertEqual(invoked, [])

    def test_incomplete_authorized_write_records_work_product(self):
        """A write-mode attempt that leaves authorized, safety-clean partial
        work behind (simulating a quota hit mid-run: nonzero return code, no
        unauthorized change) records a work-product checkpoint."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "partial.txt").write_text("partial work\n", encoding="utf-8")
            return runner.ProcessOutcome(
                returncode=1, stdout="", stderr="quota exceeded",
                timed_out=False, interrupted=False, duration_seconds=0.2,
            )

        runner.invoke_claude = fake_invoke
        code, run_dir = self._run_main(["--authorize-path", "partial.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.CLAUDE_ERROR])

        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["work_product_present"])
        work_product_path = run_dir / "work_product.json"
        self.assertTrue(work_product_path.exists())
        work_product = json.loads(work_product_path.read_text(encoding="utf-8"))
        self.assertEqual(work_product["state"], "CLAUDE_ERROR")
        self.assertTrue(work_product["incomplete"])
        self.assertEqual(work_product["reason_incomplete"], "CLAUDE_ERROR")
        self.assertTrue(work_product["process_confirmed_stopped"])
        self.assertIn("?? partial.txt", work_product["authorized_changed_paths"])
        self.assertEqual(work_product["branch"], "feature/resume-test")
        self.assertEqual(work_product["worktree"], str(self.repo.resolve()))

        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["work_product_present"])
        return work_product_path

    def test_explicit_resume_allowed_and_preserves_prior_work(self):
        """A validated resume proceeds (dirty-tree guard bypassed), and the
        prior attempt's partial work is preserved - never reset or deleted -
        while the resumed attempt can add further authorized work."""
        work_product_path = self.test_incomplete_authorized_write_records_work_product()
        original_content = (self.repo / "partial.txt").read_text(encoding="utf-8")

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "more_work.txt").write_text("more work\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.3,
            )

        runner.invoke_claude = fake_invoke
        code, run_dir = self._run_main([
            "--authorize-path", "partial.txt", "--authorize-path", "more_work.txt",
            "--resume-from", str(work_product_path),
        ])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])

        # No reset/delete: the original partial work is untouched, and the
        # resumed attempt's own new authorized file is present alongside it.
        self.assertEqual((self.repo / "partial.txt").read_text(encoding="utf-8"), original_content)
        self.assertTrue((self.repo / "more_work.txt").exists())

        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["dirty_tree_policy"]["decision"], "ALLOWED_RESUMED")
        self.assertEqual(metadata["resume"]["decision"], "ALLOWED_RESUMED")
        # The resumed run's OWN changed-paths accounting excludes the
        # already-dirty carried-over file: only what THIS invocation changed.
        self.assertIn("?? more_work.txt", metadata["authorized_changed_paths"])
        self.assertNotIn("?? partial.txt", metadata["changed_paths_after_run"])

    def test_resume_refused_with_additional_unauthorized_dirty_file(self):
        """SAFETY RULES #4/#7: an extra dirty file the prior work product
        never recorded refuses resume outright - no partial acceptance."""
        work_product_path = self.test_incomplete_authorized_write_records_work_product()
        (self.repo / "stray.txt").write_text("unexpected\n", encoding="utf-8")

        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code, run_dir = self._run_main([
            "--authorize-path", "partial.txt", "--authorize-path", "stray.txt",
            "--resume-from", str(work_product_path),
        ])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.RESUME_REFUSED])
        self.assertEqual(invoked, [])

        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["resume"]["decision"], "REFUSED_UNRECOGNIZED_DIRTY_PATH")
        # No reset/delete: both files are still exactly as they were.
        self.assertTrue((self.repo / "partial.txt").exists())
        self.assertTrue((self.repo / "stray.txt").exists())

    def test_resume_refused_when_prior_process_not_confirmed_stopped(self):
        """SAFETY RULES #4: a work product tampered to claim its prior
        process was never confirmed stopped must refuse resume."""
        work_product_path = self.test_incomplete_authorized_write_records_work_product()
        record = json.loads(work_product_path.read_text(encoding="utf-8"))
        record["process_confirmed_stopped"] = False
        work_product_path.write_text(json.dumps(record), encoding="utf-8")

        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code, run_dir = self._run_main(["--authorize-path", "partial.txt", "--resume-from", str(work_product_path)])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.RESUME_REFUSED])
        self.assertEqual(invoked, [])

        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["resume"]["decision"], "REFUSED_PROCESS_NOT_CONFIRMED_STOPPED")

    def test_resume_refused_on_branch_mismatch(self):
        work_product_path = self.test_incomplete_authorized_write_records_work_product()
        record = json.loads(work_product_path.read_text(encoding="utf-8"))
        record["branch"] = "feature/some-other-branch"
        work_product_path.write_text(json.dumps(record), encoding="utf-8")

        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code, run_dir = self._run_main(["--authorize-path", "partial.txt", "--resume-from", str(work_product_path)])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.RESUME_REFUSED])
        self.assertEqual(invoked, [])

        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["resume"]["decision"], "REFUSED_BRANCH_MISMATCH")

    def test_resume_refused_on_unexpected_head_change(self):
        work_product_path = self.test_incomplete_authorized_write_records_work_product()
        record = json.loads(work_product_path.read_text(encoding="utf-8"))
        record["base_head"] = "0" * 40
        work_product_path.write_text(json.dumps(record), encoding="utf-8")

        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code, run_dir = self._run_main(["--authorize-path", "partial.txt", "--resume-from", str(work_product_path)])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.RESUME_REFUSED])
        self.assertEqual(invoked, [])

        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["resume"]["decision"], "REFUSED_HEAD_MISMATCH")

    def test_clean_write_success_also_records_work_product(self):
        """Work-product recording is not limited to incomplete attempts: a
        clean SUCCESS that left authorized changes behind is just as
        resumable a checkpoint."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "created.txt").write_text("hello\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.2,
            )

        runner.invoke_claude = fake_invoke
        code, run_dir = self._run_main(["--authorize-path", "created.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])

        work_product = json.loads((run_dir / "work_product.json").read_text(encoding="utf-8"))
        self.assertFalse(work_product["incomplete"])
        self.assertIsNone(work_product["reason_incomplete"])

    def test_failed_safety_run_does_not_record_work_product(self):
        """A run with an unauthorized changed path is a governance
        violation, not a checkpoint: no work product is recorded for it."""

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "authorized.txt").write_text("ok\n", encoding="utf-8")
            (Path(cwd) / "unauthorized.txt").write_text("not ok\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.2,
            )

        runner.invoke_claude = fake_invoke
        code, run_dir = self._run_main(["--authorize-path", "authorized.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.FAILED_SAFETY])

        self.assertFalse((run_dir / "work_product.json").exists())
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertFalse(metadata["work_product_present"])


# ---------------------------------------------------------------------------
# RUNNER-1E: authorized write scope
# ---------------------------------------------------------------------------

class WriteScopeArgumentTest(unittest.TestCase):
    def test_authorize_path_defaults_to_none(self):
        parser = runner.build_arg_parser()
        args = parser.parse_args(["--repo", "x", "--work-order", "y", "--mode", "write"])
        self.assertIsNone(args.authorize_path)

    def test_authorize_path_is_repeatable(self):
        parser = runner.build_arg_parser()
        args = parser.parse_args([
            "--repo", "x", "--work-order", "y", "--mode", "write",
            "--authorize-path", "a/b.py",
            "--authorize-path", "c/d",
        ])
        self.assertEqual(args.authorize_path, ["a/b.py", "c/d"])


class NormalizeAuthorizedScopeTest(unittest.TestCase):
    def test_simple_relative_path_normalized(self):
        self.assertEqual(runner.normalize_authorized_scope("scripts/ai/claude_runner.py"),
                          "scripts/ai/claude_runner.py")

    def test_backslashes_normalized_to_forward_slashes(self):
        self.assertEqual(runner.normalize_authorized_scope("scripts\\ai\\claude_runner.py"),
                          "scripts/ai/claude_runner.py")

    def test_leading_dot_slash_normalized(self):
        self.assertEqual(runner.normalize_authorized_scope("./scripts/ai"), "scripts/ai")

    def test_glob_scope_preserved(self):
        self.assertEqual(runner.normalize_authorized_scope("scripts/ai/*.py"), "scripts/ai/*.py")

    def test_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            runner.normalize_authorized_scope("")

    def test_whitespace_only_rejected(self):
        with self.assertRaises(ValueError):
            runner.normalize_authorized_scope("   ")

    def test_posix_absolute_path_rejected(self):
        with self.assertRaises(ValueError):
            runner.normalize_authorized_scope("/etc/passwd")

    def test_windows_absolute_path_rejected(self):
        with self.assertRaises(ValueError):
            runner.normalize_authorized_scope("C:/Windows/System32")

    def test_parent_traversal_rejected(self):
        with self.assertRaises(ValueError):
            runner.normalize_authorized_scope("../outside_repo")

    def test_embedded_parent_traversal_rejected(self):
        with self.assertRaises(ValueError):
            runner.normalize_authorized_scope("scripts/../../outside_repo")

    def test_dot_alone_rejected_as_empty(self):
        with self.assertRaises(ValueError):
            runner.normalize_authorized_scope(".")


class EvaluateWriteScopeTest(unittest.TestCase):
    def test_none_is_refused_missing(self):
        decision = runner.evaluate_write_scope(None)
        self.assertEqual(decision.decision, "REFUSED_MISSING_SCOPE")
        self.assertEqual(decision.authorized_scopes, [])

    def test_empty_list_is_refused_missing(self):
        decision = runner.evaluate_write_scope([])
        self.assertEqual(decision.decision, "REFUSED_MISSING_SCOPE")

    def test_single_valid_scope_allowed(self):
        decision = runner.evaluate_write_scope(["scripts/ai/claude_runner.py"])
        self.assertEqual(decision.decision, "ALLOWED")
        self.assertEqual(decision.authorized_scopes, ["scripts/ai/claude_runner.py"])

    def test_multiple_valid_scopes_allowed(self):
        decision = runner.evaluate_write_scope(["scripts/ai", "scripts/tests/test_claude_runner.py"])
        self.assertEqual(decision.decision, "ALLOWED")
        self.assertEqual(decision.authorized_scopes,
                          ["scripts/ai", "scripts/tests/test_claude_runner.py"])

    def test_one_invalid_scope_among_valid_ones_refuses_whole_set(self):
        decision = runner.evaluate_write_scope(["scripts/ai", "../outside"])
        self.assertEqual(decision.decision, "REFUSED_INVALID_SCOPE")
        self.assertEqual(decision.authorized_scopes, [])


class PathIsAuthorizedTest(unittest.TestCase):
    def test_exact_file_match(self):
        self.assertTrue(runner.path_is_authorized("scripts/ai/claude_runner.py",
                                                    ["scripts/ai/claude_runner.py"]))

    def test_directory_subtree_match(self):
        self.assertTrue(runner.path_is_authorized("scripts/ai/sub/new_file.py", ["scripts/ai"]))

    def test_glob_match(self):
        self.assertTrue(runner.path_is_authorized("scripts/ai/claude_runner.py", ["scripts/ai/*.py"]))

    def test_sibling_path_not_matched(self):
        self.assertFalse(runner.path_is_authorized("scripts/tests/other.py", ["scripts/ai"]))

    def test_prefix_that_is_not_a_directory_boundary_not_matched(self):
        # "scripts/ai" must not authorize "scripts/ai_extra/file.py": the
        # match requires an exact path or a "/"-bounded subtree, not a
        # bare string prefix.
        self.assertFalse(runner.path_is_authorized("scripts/ai_extra/file.py", ["scripts/ai"]))

    def test_multiple_scopes_any_match(self):
        scopes = ["scripts/ai", "docs/resolutions"]
        self.assertTrue(runner.path_is_authorized("docs/resolutions/x.md", scopes))
        self.assertFalse(runner.path_is_authorized("docs/other/x.md", scopes))


class ClassifyChangedPathsTest(unittest.TestCase):
    def test_all_lines_authorized(self):
        lines = ["?? scripts/ai/new.py", " M scripts/ai/claude_runner.py"]
        authorized, unauthorized = runner.classify_changed_paths(lines, ["scripts/ai"])
        self.assertEqual(authorized, lines)
        self.assertEqual(unauthorized, [])

    def test_mixed_authorized_and_unauthorized(self):
        lines = ["?? scripts/ai/new.py", "?? outside/rogue.py"]
        authorized, unauthorized = runner.classify_changed_paths(lines, ["scripts/ai"])
        self.assertEqual(authorized, ["?? scripts/ai/new.py"])
        self.assertEqual(unauthorized, ["?? outside/rogue.py"])

    def test_deletion_line_classified_by_its_path(self):
        lines = [" D scripts/ai/old.py"]
        authorized, unauthorized = runner.classify_changed_paths(lines, ["scripts/ai"])
        self.assertEqual(authorized, lines)
        self.assertEqual(unauthorized, [])

    def test_rename_authorized_only_when_both_sides_in_scope(self):
        lines = ["R  scripts/ai/old.py -> scripts/ai/new.py"]
        authorized, unauthorized = runner.classify_changed_paths(lines, ["scripts/ai"])
        self.assertEqual(authorized, lines)
        self.assertEqual(unauthorized, [])

    def test_rename_crossing_scope_boundary_is_unauthorized(self):
        lines = ["R  scripts/ai/old.py -> outside/new.py"]
        authorized, unauthorized = runner.classify_changed_paths(lines, ["scripts/ai"])
        self.assertEqual(authorized, [])
        self.assertEqual(unauthorized, lines)


class WriteScopeMainEndToEndTest(unittest.TestCase):
    """RUNNER-1E: exercises main() with --mode write and real authorized-
    scope enforcement, invoke_claude monkeypatched so no live Claude quota
    is consumed and no real Claude CLI call is made."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        _git(self.repo, "checkout", "-q", "-b", "feature/write-scope-test")
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def _run_main(self, extra_args=None):
        args = [
            "--repo", str(self.repo),
            "--work-order", str(self.work_order),
            "--mode", "write",
        ] + (extra_args or [])
        return runner.main(args)

    def _runs_dir(self):
        return self.repo / "runtime" / "claude_runner" / "runs"

    def _latest_metadata(self):
        run_dir = list(self._runs_dir().iterdir())[0]
        return json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))

    def test_missing_write_scope_refused_before_invocation(self):
        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code = self._run_main()
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.WRITE_SCOPE_REQUIRED])
        self.assertEqual(invoked, [])
        metadata = self._latest_metadata()
        self.assertEqual(metadata["state"], "WRITE_SCOPE_REQUIRED")
        self.assertEqual(metadata["write_scope"]["decision"], "REFUSED_MISSING_SCOPE")

    def test_path_traversal_scope_refused_before_invocation(self):
        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code = self._run_main(["--authorize-path", "../outside_repo"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.WRITE_SCOPE_INVALID])
        self.assertEqual(invoked, [])
        metadata = self._latest_metadata()
        self.assertEqual(metadata["write_scope"]["decision"], "REFUSED_INVALID_SCOPE")

    def test_absolute_scope_refused_before_invocation(self):
        code = self._run_main(["--authorize-path", "/etc/passwd"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.WRITE_SCOPE_INVALID])

    def test_authorized_single_file_succeeds(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "README.md").write_text("updated\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "README.md"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        metadata = self._latest_metadata()
        self.assertEqual(metadata["unauthorized_changed_paths"], [])
        self.assertTrue(any("README.md" in line for line in metadata["authorized_changed_paths"]))

    def test_authorized_directory_subtree_succeeds(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            sub = Path(cwd) / "authorized_dir" / "nested"
            sub.mkdir(parents=True)
            (sub / "new_file.txt").write_text("x\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "authorized_dir"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        metadata = self._latest_metadata()
        self.assertEqual(metadata["unauthorized_changed_paths"], [])
        self.assertTrue(
            any("authorized_dir/nested/new_file.txt" in line.replace("\\", "/")
                for line in metadata["authorized_changed_paths"])
        )

    def test_multiple_authorized_scopes_succeeds(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "one.txt").write_text("1\n", encoding="utf-8")
            (Path(cwd) / "two.txt").write_text("2\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "one.txt", "--authorize-path", "two.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        metadata = self._latest_metadata()
        self.assertEqual(len(metadata["authorized_changed_paths"]), 2)
        self.assertEqual(metadata["unauthorized_changed_paths"], [])

    def test_unauthorized_sibling_file_fails_safety_and_is_preserved(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "authorized.txt").write_text("ok\n", encoding="utf-8")
            (Path(cwd) / "rogue_sibling.txt").write_text("not ok\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "authorized.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.FAILED_SAFETY])

        # Preserved for inspection, never reverted.
        self.assertTrue((self.repo / "authorized.txt").exists())
        self.assertTrue((self.repo / "rogue_sibling.txt").exists())

        metadata = self._latest_metadata()
        self.assertTrue(any("authorized.txt" in line for line in metadata["authorized_changed_paths"]))
        self.assertTrue(any("rogue_sibling.txt" in line for line in metadata["unauthorized_changed_paths"]))
        self.assertEqual(metadata["safety_verdict"]["verdict"], "FAILED_SAFETY")

    def test_mixed_authorized_and_unauthorized_changes_fail_safety(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "in_scope.txt").write_text("ok\n", encoding="utf-8")
            (Path(cwd) / "out_of_scope.txt").write_text("not ok\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "in_scope.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.FAILED_SAFETY])
        metadata = self._latest_metadata()
        self.assertEqual(len(metadata["authorized_changed_paths"]), 1)
        self.assertEqual(len(metadata["unauthorized_changed_paths"]), 1)

    def test_deletion_of_authorized_tracked_file_succeeds(self):
        (self.repo / "to_delete.txt").write_text("bye\n", encoding="utf-8")
        _git(self.repo, "add", "to_delete.txt")
        _git(self.repo, "commit", "-q", "-m", "add file to delete")

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "to_delete.txt").unlink()
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "to_delete.txt"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        metadata = self._latest_metadata()
        self.assertTrue(any("to_delete.txt" in line for line in metadata["authorized_changed_paths"]))

    def test_rename_within_authorized_scope_succeeds(self):
        (self.repo / "authorized_dir").mkdir()
        (self.repo / "authorized_dir" / "old.txt").write_text("x\n", encoding="utf-8")
        _git(self.repo, "add", "authorized_dir/old.txt")
        _git(self.repo, "commit", "-q", "-m", "add file to rename")

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            _git(Path(cwd), "mv", "authorized_dir/old.txt", "authorized_dir/new.txt")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "authorized_dir"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.SUCCESS])

    def test_rename_crossing_scope_boundary_fails_safety(self):
        (self.repo / "authorized_dir").mkdir()
        (self.repo / "authorized_dir" / "old.txt").write_text("x\n", encoding="utf-8")
        _git(self.repo, "add", "authorized_dir/old.txt")
        _git(self.repo, "commit", "-q", "-m", "add file to rename")

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "outside_dir").mkdir()
            _git(Path(cwd), "mv", "authorized_dir/old.txt", "outside_dir/old.txt")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        runner.invoke_claude = fake_invoke
        code = self._run_main(["--authorize-path", "authorized_dir"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.FAILED_SAFETY])
        metadata = self._latest_metadata()
        self.assertTrue(len(metadata["unauthorized_changed_paths"]) >= 1)

    def test_preexisting_dirty_path_in_scope_fails_closed_before_invocation(self):
        """A pre-existing dirty file's porcelain line does not change even
        if the runner edits it further, so V1 fails closed instead of
        trying to detect that edit after the fact."""
        (self.repo / "README.md").write_text("preexisting dirty change\n", encoding="utf-8")

        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        code = self._run_main(["--allow-dirty", "--authorize-path", "README.md"])
        self.assertEqual(code, runner.EXIT_CODES[runner.RunState.DIRTY_TREE_REFUSED])
        self.assertEqual(invoked, [])
        metadata = self._latest_metadata()
        self.assertEqual(metadata["dirty_tree_policy"]["decision"], "REFUSED_DIRTY")
        self.assertTrue(any("README.md" in line for line in metadata["dirty_tree_policy"]["preexisting_dirty_paths"]))

    def test_hidden_mutation_of_preexisting_out_of_scope_dirty_path_is_refused(self):
        """RUNNER-1F regression test for the exact defect found in PR #2
        review after RUNNER-1E: compute_changed_paths_after_run compares
        porcelain status LINES before/after, so a pre-existing dirty file
        OUTSIDE the authorized scope keeps the identical ' M rogue.txt'
        porcelain line even if something further mutates its *contents*
        during the run - the old RUNNER-1E overlap check only fails closed
        when the dirty path is INSIDE the authorized scope, so this
        out-of-scope hidden mutation would previously evade
        unauthorized_changed_paths detection entirely under --allow-dirty.
        V1's fix-closed rule must refuse before invoke_claude regardless,
        with or without --allow-dirty, so the simulated hidden edit inside
        fake_invoke must never actually run."""
        (self.repo / "rogue.txt").write_text("committed\n", encoding="utf-8")
        _git(self.repo, "add", "rogue.txt")
        _git(self.repo, "commit", "-q", "-m", "add rogue.txt")
        # Pre-existing dirty change outside the authorized scope, before
        # the runner is ever invoked.
        (self.repo / "rogue.txt").write_text("dirty v1 (preexisting)\n", encoding="utf-8")
        preexisting_status = _git(self.repo, "status", "--porcelain=v1").stdout
        self.assertEqual(preexisting_status.rstrip("\n"), " M rogue.txt")

        invoked = []

        def fake_invoke_with_hidden_mutation(cmd, cwd, prompt_text, timeout_seconds):
            # Simulates the exact hidden mutation this test guards against:
            # a further edit to the same pre-existing dirty, out-of-scope
            # file. Its porcelain line stays " M rogue.txt" either way, so
            # if invoked this call would be undetectable via status-line
            # diffing alone. It must never run.
            invoked.append(1)
            (Path(cwd) / "rogue.txt").write_text("dirty v2 (hidden mutation)\n", encoding="utf-8")
            (Path(cwd) / "in_scope.txt").write_text("authorized change\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(returncode=0, stdout=payload, stderr="",
                                          timed_out=False, interrupted=False, duration_seconds=0.1)

        for allow_dirty_args in ([], ["--allow-dirty"]):
            with self.subTest(allow_dirty_args=allow_dirty_args):
                invoked.clear()
                runner.invoke_claude = fake_invoke_with_hidden_mutation
                run_dirs_before = set(self._runs_dir().iterdir()) if self._runs_dir().exists() else set()
                code = self._run_main(allow_dirty_args + ["--authorize-path", "in_scope.txt"])

                self.assertEqual(code, runner.EXIT_CODES[runner.RunState.DIRTY_TREE_REFUSED])
                # The hidden mutation never happened: invoke_claude was
                # never called, and rogue.txt still holds only the
                # pre-existing dirty content.
                self.assertEqual(invoked, [])
                self.assertEqual(
                    (self.repo / "rogue.txt").read_text(encoding="utf-8"),
                    "dirty v1 (preexisting)\n",
                )
                self.assertFalse((self.repo / "in_scope.txt").exists())

                new_run_dirs = set(self._runs_dir().iterdir()) - run_dirs_before
                self.assertEqual(len(new_run_dirs), 1)
                run_dir = new_run_dirs.pop()
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["state"], "DIRTY_TREE_REFUSED")
                self.assertEqual(metadata["dirty_tree_policy"]["decision"], "REFUSED_DIRTY")
                self.assertTrue(
                    any("rogue.txt" in line for line in metadata["dirty_tree_policy"]["preexisting_dirty_paths"])
                )


# ---------------------------------------------------------------------------
# RUNNER-1.5B: programmatic single-Work-Order execution API
# ---------------------------------------------------------------------------

class ExecuteWorkOrderReadOnlyTest(unittest.TestCase):
    """Proves execute_work_order() (the future claude_queue.py entry point)
    returns the same state/exit_code and writes evidence to the same
    location as the equivalent main() CLI invocation, without shelling out."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def _runs_dir(self):
        return self.repo / "runtime" / "claude_runner" / "runs"

    def test_success_matches_cli_state_and_evidence_location(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            payload = json.dumps({"result": "PONG", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.1,
            )

        runner.invoke_claude = fake_invoke
        request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
        result = runner.execute_work_order(request)

        self.assertEqual(result.state, runner.RunState.SUCCESS)
        self.assertEqual(result.exit_code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        self.assertIsNone(result.error_message)
        self.assertEqual(result.evidence_dir.parent, self._runs_dir())
        self.assertEqual(result.run_id, result.evidence_dir.name)

        metadata = json.loads((result.evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "SUCCESS")

        # The equivalent main() invocation produces the same state/exit code
        # and evidence layout in a fresh run directory.
        code = runner.main(["--repo", str(self.repo), "--work-order", str(self.work_order)])
        self.assertEqual(code, result.exit_code)
        runs = sorted(self._runs_dir().iterdir())
        self.assertEqual(len(runs), 2)

    def test_does_not_depend_on_argparse_namespace(self):
        """The public request contract is a plain dataclass, not
        argparse.Namespace: it can be constructed without ever invoking
        argparse, as a future queue would."""
        request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
        self.assertNotIsInstance(request, __import__("argparse").Namespace)
        self.assertIsInstance(request, runner.WorkOrderRequest)


class ExecuteWorkOrderRefusalTest(unittest.TestCase):
    """Deterministic pre-invocation refusal via the programmatic API must
    match the CLI path: no Claude invocation, matching state/exit_code, and
    evidence written to the same location for cases where main() writes it."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        _git(self.repo, "checkout", "-q", "-b", "feature/api-refusal-test")
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def test_missing_write_scope_refused_before_invocation(self):
        invoked = []
        runner.invoke_claude = lambda *a, **k: invoked.append(1)
        request = runner.WorkOrderRequest(
            repo=str(self.repo),
            work_order=str(self.work_order),
            mode=runner.MODE_WRITE,
            run_root=str(self.repo.parent / "runner_api_evidence"),
        )
        result = runner.execute_work_order(request)

        self.assertEqual(invoked, [])
        self.assertEqual(result.state, runner.RunState.WRITE_SCOPE_REQUIRED)
        self.assertEqual(result.exit_code, runner.EXIT_CODES[runner.RunState.WRITE_SCOPE_REQUIRED])
        self.assertIsNotNone(result.error_message)
        self.assertIsNotNone(result.evidence_dir)
        metadata = json.loads((result.evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "WRITE_SCOPE_REQUIRED")

        # main() on an equivalent invocation is refused identically.
        code = runner.main([
            "--repo", str(self.repo),
            "--work-order", str(self.work_order),
            "--mode", "write",
            "--run-root", str(self.repo.parent / "runner_cli_evidence"),
        ])
        self.assertEqual(code, result.exit_code)

    def test_invalid_repository_no_evidence_matches_cli(self):
        request = runner.WorkOrderRequest(repo=str(self.root / "nope"), work_order=str(self.work_order))
        result = runner.execute_work_order(request)

        self.assertEqual(result.state, runner.RunState.INVALID_REPOSITORY)
        self.assertEqual(result.exit_code, runner.EXIT_CODES[runner.RunState.INVALID_REPOSITORY])
        self.assertIsNone(result.run_id)
        self.assertIsNone(result.evidence_dir)
        self.assertFalse((self.root / "nope").exists())

        code = runner.main(["--repo", str(self.root / "nope"), "--work-order", str(self.work_order)])
        self.assertEqual(code, result.exit_code)


class ExecuteWorkOrderSafetyFailureTest(unittest.TestCase):
    """FAILED_SAFETY precedence and no-auto-revert must hold identically
    through the programmatic API."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.work_order = _make_work_order(self.root)
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def test_failed_safety_on_unexpected_mutation_matches_cli_and_is_not_reverted(self):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            (Path(cwd) / "unexpected_write.txt").write_text("mutated by run\n", encoding="utf-8")
            payload = json.dumps({"result": "done", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.2,
            )

        runner.invoke_claude = fake_invoke
        request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
        result = runner.execute_work_order(request)

        self.assertEqual(result.state, runner.RunState.FAILED_SAFETY)
        self.assertEqual(result.exit_code, runner.EXIT_CODES[runner.RunState.FAILED_SAFETY])
        self.assertIsNone(result.error_message)
        self.assertTrue((self.repo / "unexpected_write.txt").exists())

        result_payload = json.loads((result.evidence_dir / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result_payload["safety_check"]["repository_mutated"])

        # Equivalent CLI invocation on a fresh repository must produce the
        # same FAILED_SAFETY result and preserve the unexpected mutation.
        import tempfile
        with tempfile.TemporaryDirectory() as cli_tmp:
            cli_root = Path(cli_tmp)
            cli_repo = _make_git_repo(cli_root)
            code = runner.main([
                "--repo", str(cli_repo),
                "--work-order", str(self.work_order),
            ])

            self.assertEqual(code, result.exit_code)
            self.assertTrue((cli_repo / "unexpected_write.txt").exists())

            cli_runs_dir = cli_repo / "runtime" / "claude_runner" / "runs"
            cli_runs = list(cli_runs_dir.iterdir())
            self.assertEqual(len(cli_runs), 1)

            cli_payload = json.loads(
                (cli_runs[0] / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(cli_payload["state"], "FAILED_SAFETY")
            self.assertTrue(cli_payload["safety_check"]["repository_mutated"])


class EvidenceFinalizationIntegrityTest(unittest.TestCase):
    """Runner V2.1 R21-A: a post-provider evidence-artifact write failure
    (e.g. git_before.txt cannot be persisted) must never turn a completed,
    SUCCESS-verdict provider run into an uncaught exception or a reported
    work failure."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.work_order = _make_work_order(
            self.root, text="Do the work.\nReport VERDICT=SUCCESS or VERDICT=FAILED at the end.\n",
        )
        self._orig_invoke = runner.invoke_claude
        self._orig_get_exec = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            payload = json.dumps({"result": "FORMAL_CLOSURE=CLOSED\nVERDICT=SUCCESS\n", "is_error": False})
            return runner.ProcessOutcome(
                returncode=0, stdout=payload, stderr="", timed_out=False,
                interrupted=False, duration_seconds=0.2,
            )

        runner.invoke_claude = fake_invoke

    def tearDown(self):
        runner.invoke_claude = self._orig_invoke
        providers.ClaudeProvider.locate_executable = self._orig_get_exec
        self._tmp.cleanup()

    def _patched_write_text(self, failing_name):
        orig_write_text = Path.write_text

        def flaky(self_path, data, *a, **k):
            if self_path.name == failing_name:
                raise FileNotFoundError(f"reproduced missing evidence artifact: {self_path}")
            return orig_write_text(self_path, data, *a, **k)

        return orig_write_text, flaky

    def test_missing_git_before_does_not_raise_and_preserves_success(self):
        orig_write_text, flaky = self._patched_write_text("git_before.txt")
        Path.write_text = flaky
        try:
            request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
            result = runner.execute_work_order(request)  # must not raise
        finally:
            Path.write_text = orig_write_text

        # Work result semantics are untouched by the evidence failure.
        self.assertEqual(result.state, runner.RunState.SUCCESS)
        self.assertEqual(result.exit_code, runner.EXIT_CODES[runner.RunState.SUCCESS])
        self.assertEqual(result.work_status, "SUCCESS")

        # Evidence failure is explicit, not silently reported as complete.
        self.assertFalse(result.evidence_complete)
        self.assertIsNotNone(result.evidence_error)
        self.assertIn("git_before.txt", result.evidence_error)

        # The missing artifact really is missing; everything else the runner
        # could still write is recoverable.
        self.assertFalse((result.evidence_dir / "git_before.txt").exists())
        self.assertTrue((result.evidence_dir / "stdout.txt").exists())
        self.assertIn("VERDICT=SUCCESS", (result.evidence_dir / "stdout.txt").read_text(encoding="utf-8"))

        result_payload = json.loads((result.evidence_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result_payload["state"], "SUCCESS")
        self.assertEqual(result_payload["work_status"], "SUCCESS")
        self.assertFalse(result_payload["evidence_complete"])
        self.assertTrue(any("git_before.txt" in e for e in result_payload["evidence_errors"]))

    def test_git_before_is_persisted_before_the_provider_is_invoked(self):
        """Requirement 8: the pre-execution snapshot is written deterministically
        before invocation, not bundled with the post-execution evidence, so it
        cannot be erased by a later evidence-write failure."""
        seen_git_before_exists = []
        orig_invoke = runner.invoke_claude

        def probing_invoke(cmd, cwd, prompt_text, timeout_seconds):
            runs = list((self.repo / "runtime" / "claude_runner" / "runs").iterdir())
            self.assertEqual(len(runs), 1)
            seen_git_before_exists.append((runs[0] / "git_before.txt").exists())
            return orig_invoke(cmd, cwd, prompt_text, timeout_seconds)

        runner.invoke_claude = probing_invoke
        try:
            request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
            result = runner.execute_work_order(request)
        finally:
            runner.invoke_claude = orig_invoke

        self.assertEqual(seen_git_before_exists, [True])
        self.assertTrue(result.evidence_complete)
        self.assertIsNone(result.evidence_error)

    def test_complete_evidence_path_is_unchanged(self):
        request = runner.WorkOrderRequest(repo=str(self.repo), work_order=str(self.work_order))
        result = runner.execute_work_order(request)

        self.assertEqual(result.state, runner.RunState.SUCCESS)
        self.assertTrue(result.evidence_complete)
        self.assertIsNone(result.evidence_error)
        for name in ("prompt.txt", "stdout.txt", "stderr.txt", "metadata.json",
                     "result.json", "git_before.txt", "git_after.txt"):
            self.assertTrue((result.evidence_dir / name).exists(), name)


class SupervisedTransportSeamTest(unittest.TestCase):
    """The per-execution transport hands the provider id and the attempt's
    ExecutionControl to the real supervised invoker only; substituted
    `invoke_claude` doubles keep their historical 4-argument contract."""

    def setUp(self):
        self._orig_invoke = runner.invoke_claude
        self.addCleanup(lambda: setattr(runner, "invoke_claude", self._orig_invoke))

    def test_real_invoker_receives_provider_id_and_control(self):
        from unittest import mock

        control = object()
        outcome = runner.ProcessOutcome(0, "", "", False, False, 0.0)
        with mock.patch.object(providers, "run_process", return_value=outcome) as run:
            got = runner._transport_for("codex", control)(["x"], Path("."), b"prompt", 9)
        self.assertIs(got, outcome)
        run.assert_called_once_with(["x"], Path("."), b"prompt", 9, provider_id="codex", control=control)

    def test_substituted_invoker_keeps_four_argument_contract(self):
        seen = []

        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            seen.append((cmd, prompt_text, timeout_seconds))
            return runner.ProcessOutcome(0, "{}", "", False, False, 0.0)

        runner.invoke_claude = fake_invoke
        runner._transport_for("claude", object())(["x"], Path("."), "pü".encode("utf-8"), 3)
        self.assertEqual(seen, [(["x"], "pü", 3)])

    def test_work_order_request_defaults_to_no_execution_control(self):
        request = runner.WorkOrderRequest(repo=".", work_order="wo.txt")
        self.assertIsNone(request.execution_control)


if __name__ == "__main__":
    unittest.main()



class ExecutionModeFailClosedRegressionTest(unittest.TestCase):
    """Unknown programmatic modes must never silently become read-only."""

    def test_unknown_mode_is_rejected_by_cli_builder(self):
        with self.assertRaises(ValueError):
            runner.build_cli_command(
                "claude",
                mode="WRITE",
            )

    def test_canonical_write_still_gets_write_tools(self):
        cmd = runner.build_cli_command(
            "claude",
            mode=runner.MODE_WRITE,
        )
        joined = " ".join(cmd)

        self.assertIn(
            "--tools Read,Grep,Glob,Edit,Write,NotebookEdit",
            joined,
        )
        self.assertIn(
            "--permission-mode acceptEdits",
            joined,
        )

    def test_read_only_still_gets_read_only_tools(self):
        cmd = runner.build_cli_command(
            "claude",
            mode=runner.MODE_READ_ONLY,
        )
        joined = " ".join(cmd)

        self.assertIn(
            "--tools Read,Grep,Glob",
            joined,
        )
        self.assertNotIn(
            "Edit,Write,NotebookEdit",
            joined,
        )
