import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import runner_providers as providers


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _make_git_repo(root: Path, name: str = "repo") -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "runner-tests@example.invalid")
    _git(repo, "config", "user.name", "Runner Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed commit")
    return repo


def _outcome(returncode=0, stdout="", stderr="", timed_out=False, interrupted=False):
    return providers.ProcessOutcome(returncode, stdout, stderr, timed_out, interrupted, 0.1)


def _claude_json(text: str, is_error: bool = False) -> str:
    return json.dumps({"type": "result", "result": text, "is_error": is_error})


class FakeProvider(providers.Provider):
    """Provider double: records the cwd it was asked to run in and returns a
    scripted outcome; never spawns a process."""

    def __init__(self, provider_id="fake", caps=None, stdout="", returncode=0, available=True):
        self.provider_id = provider_id
        self.display_name = provider_id.title()
        self._caps = frozenset(caps if caps is not None else {
            providers.Capability.READ_FILES, providers.Capability.SEARCH_FILES,
            providers.Capability.EDIT_FILES, providers.Capability.WRITE_FILES,
        })
        self._stdout = stdout
        self._returncode = returncode
        self._available = available
        self.executed_cwds = []

    def probe(self):
        if not self._available:
            return providers.ProviderProbe(self.provider_id, False, reason="fake unavailable")
        return providers.ProviderProbe(self.provider_id, True, executable="fake-exe", version="0.0-fake")

    def capabilities(self, policy):
        return self._caps

    def build_invocation(self, *, executable, cwd, prompt_text, policy, model=None):
        return providers.Invocation(
            self.provider_id, [executable, "--fake"], cwd, prompt_text.encode("utf-8"),
        )

    def execute(self, invocation, timeout_seconds, transport=None):
        self.executed_cwds.append(Path(invocation.cwd))
        return _outcome(self._returncode, self._stdout)

    def normalize_result(self, outcome, *, verdict_required):
        return providers.normalize_outcome(
            outcome=outcome, provider_reported_error=False,
            result_text=outcome.stdout, verdict_required=verdict_required,
        )


def _registry_with(*fakes):
    registry = providers.build_default_registry()
    for fake in fakes:
        registry.register(fake.provider_id, lambda f=fake: f)
    return registry


class TempRepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.addCleanup(self._tmp.cleanup)

    def work_order(self, text="Report a fact.\n", name="wo.txt") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def request(self, **kwargs) -> runner.WorkOrderRequest:
        kwargs.setdefault("repo", str(self.repo))
        if "work_order" not in kwargs:
            kwargs["work_order"] = str(self.work_order())
        kwargs.setdefault("run_root", str(self.root / "runs"))
        return runner.WorkOrderRequest(**kwargs)

    def run_with(self, registry, request):
        with mock.patch.object(providers, "_DEFAULT_REGISTRY", registry):
            return runner.execute_work_order(request)


class RegistryTest(unittest.TestCase):
    def test_provider_registration_and_resolution(self):
        registry = providers.build_default_registry()
        self.assertEqual(registry.ids(), ["claude", "codex"])
        self.assertIsInstance(registry.create("claude"), providers.ClaudeProvider)
        self.assertIsInstance(registry.create("codex"), providers.CodexProvider)

    def test_duplicate_and_invalid_registration_rejected(self):
        registry = providers.build_default_registry()
        with self.assertRaises(ValueError):
            registry.register("claude", providers.ClaudeProvider)
        with self.assertRaises(ValueError):
            registry.register("Mixed", providers.ClaudeProvider)

    def test_unknown_provider_rejected_cleanly(self):
        with self.assertRaises(providers.UnknownProviderError) as ctx:
            providers.resolve_provider("nonesuch")
        self.assertEqual(ctx.exception.code, "PROVIDER_UNKNOWN")
        self.assertIn("claude", ctx.exception.message)

    def test_unknown_provider_refused_by_runner_before_any_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_git_repo(Path(tmp))
            wo = Path(tmp) / "wo.txt"
            wo.write_text("x\n", encoding="utf-8")
            result = runner.execute_work_order(
                runner.WorkOrderRequest(repo=str(repo), work_order=str(wo), provider="nonesuch"))
            self.assertEqual(result.state, runner.RunState.PROVIDER_UNKNOWN)
            self.assertEqual(result.exit_code, 12)
            self.assertIsNone(result.evidence_dir)
            self.assertFalse((repo / "runtime").exists())

    def test_cli_accepts_provider_flag_and_defaults_to_none(self):
        parser = runner.build_arg_parser()
        self.assertIsNone(parser.parse_args(["--repo", "x", "--work-order", "y"]).provider)
        self.assertEqual(
            parser.parse_args(["--repo", "x", "--work-order", "y", "--provider", "codex"]).provider, "codex")

    def test_default_provider_is_claude_for_backwards_compatibility(self):
        self.assertEqual(providers.DEFAULT_PROVIDER_ID, "claude")
        self.assertIsInstance(providers.resolve_provider(None), providers.ClaudeProvider)
        self.assertIsNone(runner.WorkOrderRequest(repo="r", work_order="w").provider)

    def test_two_providers_coexist_with_independent_instances(self):
        registry = _registry_with(FakeProvider("alpha"), FakeProvider("beta"))
        self.assertEqual(registry.ids(), ["alpha", "beta", "claude", "codex"])
        self.assertIsNot(registry.create("claude"), registry.create("claude"))
        self.assertEqual({registry.create("claude").provider_id, registry.create("codex").provider_id},
                         {"claude", "codex"})


class ClaudeAdapterTest(unittest.TestCase):
    def test_invocation_shape_and_prompt_not_in_argv(self):
        prompt = "do the thing\n" * 3
        inv = providers.ClaudeProvider().build_invocation(
            executable="claude", cwd=Path("."), prompt_text=prompt,
            policy=providers.ExecutionPolicy(mode="read-only"), model="m1")
        self.assertEqual(inv.argv[:3], ["claude", "--print", "--output-format"])
        self.assertEqual(inv.argv[inv.argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(inv.argv[inv.argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(inv.argv[-2:], ["--model", "m1"])
        self.assertNotIn(prompt, inv.argv)
        self.assertEqual(inv.stdin_bytes, prompt.encode("utf-8"))
        self.assertEqual(inv.prompt_transport, "stdin")

    def test_write_mode_and_shell_are_representable_only_via_policy(self):
        provider = providers.ClaudeProvider()
        write = provider.build_invocation(
            executable="c", cwd=Path("."), prompt_text="p", policy=providers.ExecutionPolicy(mode="write"))
        self.assertIn("Edit", write.argv[write.argv.index("--tools") + 1])
        self.assertNotIn("Bash", write.argv[write.argv.index("--tools") + 1])
        shell = provider.build_invocation(
            executable="c", cwd=Path("."), prompt_text="p",
            policy=providers.ExecutionPolicy(mode="read-only", allow_shell=True))
        self.assertIn("Bash", shell.argv[shell.argv.index("--tools") + 1])
        self.assertNotIn(providers.Capability.SHELL, provider.capabilities(providers.ExecutionPolicy()))
        self.assertIn(providers.Capability.SHELL,
                      provider.capabilities(providers.ExecutionPolicy(allow_shell=True)))

    def test_legacy_build_cli_command_matches_adapter(self):
        self.assertEqual(
            runner.build_cli_command("claude", model="m", mode="write"),
            providers.ClaudeProvider().build_invocation(
                executable="claude", cwd=Path("."), prompt_text="",
                policy=providers.ExecutionPolicy(mode="write"), model="m").argv)


class PromptTransportTest(unittest.TestCase):
    """Real subprocess round trips through the neutral transport."""

    ECHO = [sys.executable, "-c",
            "import sys,hashlib,os;d=sys.stdin.buffer.read();"
            "sys.stdout.write(hashlib.sha256(d).hexdigest()+'|'+str(len(d))+'|'+os.getcwd())"]

    def _roundtrip(self, prompt: str, cwd: Path):
        data = prompt.encode("utf-8")
        outcome = providers.run_process(self.ECHO, cwd, data, 60)
        digest, length, child_cwd = outcome.stdout.split("|", 2)
        return digest, int(length), child_cwd, data

    def test_long_multiline_prompt_is_transported_byte_exact(self):
        prompt = "".join(f"line {i}: Work Order paragraph with ünïcode — and CRLF\r\n\n" for i in range(20000))
        self.assertGreater(len(prompt), 900_000)
        with tempfile.TemporaryDirectory() as tmp:
            digest, length, _, data = self._roundtrip(prompt, Path(tmp))
        self.assertEqual(length, len(data))
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())

    def test_shell_metacharacters_quotes_and_backticks_survive_unchanged(self):
        prompt = ('He said "hi" and \'bye\'; `rm -rf /` $(whoami) ${HOME} %PATH% $VAR |&<> \\n \\\\ '
                  "-- --tools Read\n```bash\necho \"$x\" && cat <<EOF\nEOF\n```\n")
        with tempfile.TemporaryDirectory() as tmp:
            digest, length, _, data = self._roundtrip(prompt, Path(tmp))
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        inv = providers.ClaudeProvider().build_invocation(
            executable="claude", cwd=Path("."), prompt_text=prompt, policy=providers.ExecutionPolicy())
        self.assertFalse(any(prompt in part or "rm -rf" in part for part in inv.argv))

    def test_process_starts_in_explicit_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            _, _, child_cwd, _ = self._roundtrip("x", target)
            self.assertEqual(Path(child_cwd).resolve(), target)

    def test_stdin_is_never_inherited_no_tty_wait(self):
        probe = [sys.executable, "-c", "import sys;print(repr(sys.stdin.read()))"]
        with tempfile.TemporaryDirectory() as tmp:
            outcome = providers.run_process(probe, Path(tmp), None, 30)
        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(outcome.stdout.strip(), "''")


class WorktreeBindingTest(TempRepoCase):
    def test_binding_accepts_exact_worktree(self):
        head = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertIsNone(providers.verify_worktree_binding(self.repo, self.repo, head))

    def test_binding_rejects_cwd_in_another_checkout(self):
        other = _make_git_repo(self.root, "other")
        error = providers.verify_worktree_binding(self.repo, other)
        self.assertIn("is not the requested worktree", error)

    def test_binding_rejects_head_drift(self):
        self.assertIn("HEAD", providers.verify_worktree_binding(self.repo, self.repo, "0" * 40))

    def test_runner_executes_provider_in_exact_requested_worktree(self):
        fake = FakeProvider(stdout="ok")
        result = self.run_with(_registry_with(fake), self.request(provider="fake"))
        self.assertEqual(result.state, runner.RunState.SUCCESS)
        self.assertEqual([p.resolve() for p in fake.executed_cwds], [self.repo.resolve()])

    def test_runner_refuses_when_provider_invocation_targets_another_checkout(self):
        other = _make_git_repo(self.root, "other")

        class WrongCwd(FakeProvider):
            def build_invocation(self, *, executable, cwd, prompt_text, policy, model=None):
                return super().build_invocation(
                    executable=executable, cwd=other, prompt_text=prompt_text, policy=policy)

        fake = WrongCwd()
        result = self.run_with(_registry_with(fake), self.request(provider="fake"))
        self.assertEqual(result.state, runner.RunState.WORKTREE_BINDING_FAILED)
        self.assertEqual(result.exit_code, 15)
        self.assertEqual(fake.executed_cwds, [])


class PreflightTest(TempRepoCase):
    def test_unavailable_provider_reports_cleanly_without_evidence_or_execution(self):
        with mock.patch("shutil.which", lambda name: None):
            probe = providers.CodexProvider().probe()
            self.assertFalse(probe.available)
            self.assertEqual(probe.label, "UNAVAILABLE")
            result = runner.execute_work_order(self.request(provider="codex"))
        self.assertEqual(result.state, runner.RunState.PROVIDER_UNAVAILABLE)
        self.assertEqual(result.exit_code, 13)
        self.assertIn("UNAVAILABLE", result.error_message)
        self.assertIn("codex", result.error_message)

    def test_missing_claude_keeps_legacy_claude_error_state(self):
        with mock.patch("shutil.which", lambda name: None):
            result = runner.execute_work_order(self.request())
        self.assertEqual(result.state, runner.RunState.CLAUDE_ERROR)

    def test_available_probe_label(self):
        with mock.patch("shutil.which", lambda name: "C:/x/codex.exe"), \
                mock.patch.object(providers, "probe_executable_version", lambda exe, timeout=30: "codex 9.9"):
            probe = providers.CodexProvider().probe()
        self.assertEqual((probe.label, probe.version), ("AVAILABLE", "codex 9.9"))

    def test_capability_mismatch_fails_before_execution(self):
        read_only = FakeProvider(caps={providers.Capability.READ_FILES, providers.Capability.SEARCH_FILES})
        _git(self.repo, "checkout", "-q", "-b", "feature/x")  # write mode refuses main
        req = self.request(provider="fake", mode="write", authorize_path=["README.md"])
        result = self.run_with(_registry_with(read_only), req)
        self.assertEqual(result.state, runner.RunState.CAPABILITY_MISMATCH)
        self.assertEqual(result.exit_code, 14)
        self.assertEqual(read_only.executed_cwds, [])
        self.assertIn("EDIT_FILES", result.error_message)
        preflight = json.loads((result.evidence_dir / "result.json").read_text(encoding="utf-8"))["preflight"]
        self.assertEqual(preflight["verdict"], "CAPABILITY_MISMATCH")
        self.assertEqual(preflight["missing_capabilities"], ["EDIT_FILES", "WRITE_FILES"])

    def test_explicit_shell_request_refused_when_governance_does_not_grant_it(self):
        fake = FakeProvider()
        result = self.run_with(
            _registry_with(fake), self.request(provider="fake", required_capabilities=["SHELL", "bogus"]))
        self.assertEqual(result.state, runner.RunState.CAPABILITY_MISMATCH)
        self.assertIn("SHELL", result.error_message)
        self.assertIn("bogus", result.error_message)
        self.assertEqual(fake.executed_cwds, [])

    def test_preflight_records_required_facts_without_mutating(self):
        before = _git(self.repo, "status", "--porcelain").stdout
        fake = FakeProvider(stdout="ok")
        result = self.run_with(_registry_with(fake), self.request(provider="fake"))
        pre = json.loads((result.evidence_dir / "preflight.json").read_text(encoding="utf-8"))
        for key in ("provider_id", "provider_status", "provider_version", "worktree_path", "branch", "head",
                    "dirty", "requested_capabilities", "provider_capabilities", "prompt_chars",
                    "prompt_bytes", "execution_policy"):
            self.assertIn(key, pre)
        self.assertEqual((pre["verdict"], pre["provider_status"], pre["branch"], pre["dirty"]),
                         ("PASS", "AVAILABLE", "main", False))
        self.assertEqual(pre["head"], _git(self.repo, "rev-parse", "HEAD").stdout.strip())
        self.assertEqual(_git(self.repo, "status", "--porcelain").stdout, before)


class VerdictNormalizationTest(TempRepoCase):
    CONTRACT = "Do work.\nEnd with VERDICT=X_READY or VERDICT=X_BLOCKED:<blocker>\n"

    def _run(self, wo_text, stdout, returncode=0):
        fake = FakeProvider(stdout=stdout, returncode=returncode)
        result = self.run_with(
            _registry_with(fake),
            self.request(provider="fake", work_order=str(self.work_order(wo_text))))
        return result, json.loads((result.evidence_dir / "result.json").read_text(encoding="utf-8"))

    def test_exit_zero_with_blocked_verdict_is_blocked_not_success(self):
        result, payload = self._run(self.CONTRACT, "analysis...\nVERDICT=X_BLOCKED:missing creds\n")
        self.assertEqual(result.state, runner.RunState.BLOCKED)
        self.assertEqual(result.exit_code, 6)
        self.assertEqual(result.work_status, "BLOCKED")
        self.assertEqual(payload["normalized_result"]["process_status"], "OK")
        self.assertEqual(payload["work_status"], "BLOCKED")

    def test_claude_json_envelope_blocked_verdict(self):
        provider = providers.ClaudeProvider()
        norm = provider.normalize_result(
            _outcome(0, _claude_json("done\nVERDICT=Y_BLOCKED:reason")), verdict_required=True)
        self.assertEqual((norm.process_status, norm.work_status),
                         (providers.ProcessStatus.OK, providers.WorkStatus.BLOCKED))

    def test_success_and_partial_verdicts(self):
        self.assertEqual(self._run(self.CONTRACT, "VERDICT=X_READY\n")[0].state, runner.RunState.SUCCESS)
        result, _ = self._run(self.CONTRACT, "VERDICT=X_PARTIAL\n")
        self.assertEqual((result.state, result.exit_code), (runner.RunState.PARTIAL, 7))

    def test_failed_verdict_with_clean_process(self):
        result, _ = self._run(self.CONTRACT, "VERDICT=X_FAILED\n")
        self.assertEqual((result.state, result.work_status), (runner.RunState.WORK_FAILED, "FAILED"))

    def test_nonzero_exit_is_failed_using_existing_governed_state(self):
        result, payload = self._run(self.CONTRACT, "VERDICT=X_READY\n", returncode=1)
        self.assertEqual(result.state, runner.RunState.CLAUDE_ERROR)
        self.assertEqual(result.work_status, "FAILED")
        self.assertEqual(payload["normalized_result"]["process_status"], "NONZERO_EXIT")

    def test_provider_reported_error_is_failed(self):
        norm = providers.ClaudeProvider().normalize_result(
            _outcome(0, _claude_json("VERDICT=X_READY", is_error=True)), verdict_required=True)
        self.assertEqual(norm.work_status, providers.WorkStatus.FAILED)

    def test_absent_verdict_when_required_is_never_success(self):
        result, _ = self._run(self.CONTRACT, "I finished everything, all good.\n")
        self.assertEqual(result.state, runner.RunState.VERDICT_INVALID)
        self.assertEqual(result.work_status, "INVALID_VERDICT")
        self.assertNotEqual(result.exit_code, 0)

    def test_malformed_verdict_is_never_success(self):
        for text in ("VERDICT=\n", "VERDICT=MAYBE\n", "prose VERDICT=X_READY inline only\n", "VERDICT X_READY\n"):
            result, _ = self._run(self.CONTRACT, text)
            self.assertEqual(result.state, runner.RunState.VERDICT_INVALID, text)

    def test_conflicting_verdicts_take_most_severe(self):
        result, _ = self._run(self.CONTRACT, "VERDICT=X_READY\nlater\nVERDICT=X_BLOCKED:oops\n")
        self.assertEqual(result.state, runner.RunState.BLOCKED)

    def test_negated_ready_is_not_success(self):
        self.assertEqual(providers.classify_verdict_value("X_NOT_READY"), providers.WorkStatus.FAILED)

    def test_no_verdict_contract_is_recorded_unverified_never_success_status(self):
        result, payload = self._run("Report a fact.\n", "PONG")
        self.assertEqual(result.state, runner.RunState.SUCCESS)  # legacy contract preserved
        self.assertEqual(result.work_status, "UNVERIFIED")
        self.assertFalse(payload["normalized_result"]["verdict_required"])

    def test_require_verdict_override(self):
        fake = FakeProvider(stdout="nothing")
        result = self.run_with(_registry_with(fake), self.request(provider="fake", require_verdict=True))
        self.assertEqual(result.state, runner.RunState.VERDICT_INVALID)

    def test_timeout_and_interrupt_are_never_work_success(self):
        for kwargs, status in (({"timed_out": True, "returncode": None}, providers.ProcessStatus.TIMED_OUT),
                               ({"interrupted": True, "returncode": None}, providers.ProcessStatus.INTERRUPTED)):
            norm = providers.normalize_outcome(
                outcome=_outcome(stdout="VERDICT=X_READY", **kwargs), provider_reported_error=False,
                result_text="VERDICT=X_READY", verdict_required=True)
            self.assertEqual((norm.process_status, norm.work_status), (status, providers.WorkStatus.FAILED))


class MultiworkerCompatibilityTest(TempRepoCase):
    def test_two_worker_requests_select_different_providers_concurrently(self):
        repo_b = _make_git_repo(self.root, "repo_b")
        alpha = FakeProvider("alpha", stdout="a")
        beta = FakeProvider("beta", stdout="b")
        registry = _registry_with(alpha, beta)
        barrier = threading.Barrier(2, timeout=30)
        for fake in (alpha, beta):
            original = fake.execute

            def execute(invocation, timeout_seconds, transport=None, _orig=original):
                barrier.wait()  # both workers must be inside execute at the same time
                return _orig(invocation, timeout_seconds, transport)

            fake.execute = execute

        results = {}

        def work(key, repo, provider_id):
            wo = self.root / f"wo_{key}.txt"
            wo.write_text("task\n", encoding="utf-8")
            results[key] = runner.execute_work_order(runner.WorkOrderRequest(
                repo=str(repo), work_order=str(wo), provider=provider_id,
                run_root=str(self.root / f"runs_{key}")))

        with mock.patch.object(providers, "_DEFAULT_REGISTRY", registry):
            threads = [threading.Thread(target=work, args=("a", self.repo, "alpha")),
                       threading.Thread(target=work, args=("b", repo_b, "beta"))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)

        self.assertEqual({k: r.state for k, r in results.items()},
                         {"a": runner.RunState.SUCCESS, "b": runner.RunState.SUCCESS})
        self.assertEqual([p.resolve() for p in alpha.executed_cwds], [self.repo.resolve()])
        self.assertEqual([p.resolve() for p in beta.executed_cwds], [repo_b.resolve()])
        meta_a = json.loads((results["a"].evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        meta_b = json.loads((results["b"].evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual((meta_a["provider"]["provider_id"], meta_b["provider"]["provider_id"]), ("alpha", "beta"))

    def test_registry_creates_fresh_instance_per_resolution_no_global_provider_state(self):
        a, b = providers.resolve_provider("claude"), providers.resolve_provider("claude")
        self.assertIsNot(a, b)


class CoreNeutralityTest(unittest.TestCase):
    def test_no_provider_specific_branching_in_orchestration_core(self):
        source = (Path(runner.__file__)).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        self.assertIsNone(re.search(r"(==|!=)\s*[\"'](claude|codex)[\"']", code))
        self.assertIsNone(re.search(r"provider_id\s*(==|!=|in\b)", code))
        self.assertNotIn("isinstance(provider", code)
        self.assertNotIn("codex", code.lower().replace('"""', ""))  # adapter names never appear in core code


if __name__ == "__main__":
    unittest.main()
