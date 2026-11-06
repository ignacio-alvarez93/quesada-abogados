"""FABRIC-V1-P0 WO-P0-A: host / provider boundary (A05-F1, A05-F2).

Adversarial tests. Every hostile file lives in a synthetic temporary
fixture; no real provider binary and no network is ever used."""

import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import runner_providers as providers


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


GITIGNORE = "tmp/\n__pycache__/\n*.pyc\n*.log\n/runtime/\n"


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "runner-tests@example.invalid")
    _git(repo, "config", "user.name", "Runner Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    (repo / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "keep.py").write_text("X = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "seed commit")
    _git(repo, "checkout", "-q", "-b", "feature/p0a")
    # Pre-existing ignored file: present before the safety baseline, never
    # attributed to the provider.
    (repo / "tmp").mkdir()
    (repo / "tmp" / "old.txt").write_text("pre-existing\n", encoding="utf-8")
    return repo


def _payload() -> str:
    return json.dumps({"result": "done", "is_error": False, "type": "result"})


class _RunnerFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.repo = _make_repo(self.root)
        self.work_order = self.root / "work_order.txt"
        self.work_order.write_text("Do the authorized change.\n", encoding="utf-8")

        orig_locate = providers.ClaudeProvider.locate_executable
        providers.ClaudeProvider.locate_executable = lambda self: "fake-claude"
        self.addCleanup(setattr, providers.ClaudeProvider, "locate_executable", orig_locate)
        orig_invoke = runner.invoke_claude
        self.addCleanup(setattr, runner, "invoke_claude", orig_invoke)
        orig_override = runner.DIRECT_PROCESS_EVIDENCE_ROOT_OVERRIDE
        runner.DIRECT_PROCESS_EVIDENCE_ROOT_OVERRIDE = self.root / "external_evidence_root"
        self.addCleanup(setattr, runner, "DIRECT_PROCESS_EVIDENCE_ROOT_OVERRIDE", orig_override)

    def run_with(self, write_fn, *, mode=runner.MODE_WRITE, scope=("src",)):
        def fake_invoke(cmd, cwd, prompt_text, timeout_seconds):
            write_fn(Path(cwd))
            return runner.ProcessOutcome(0, _payload(), "", False, False, 0.1)

        runner.invoke_claude = fake_invoke
        request = runner.WorkOrderRequest(
            repo=str(self.repo), work_order=str(self.work_order), mode=mode,
            authorize_path=list(scope) if mode == runner.MODE_WRITE else None,
        )
        result = runner.execute_work_order(request)
        metadata = json.loads((result.evidence_dir / "metadata.json").read_text(encoding="utf-8"))
        return result, metadata


# ---------------------------------------------------------------------------
# A05-F1: new ignored writes outside authorize_path
# ---------------------------------------------------------------------------

class IgnoredPathBoundaryTest(_RunnerFixture):
    def test_new_ignored_tmp_evil_outside_scope_is_failed_safety(self):
        def write(cwd):
            (cwd / "tmp" / "evil.txt").write_text("payload\n", encoding="utf-8")

        result, metadata = self.run_with(write)
        self.assertEqual(result.state, runner.RunState.FAILED_SAFETY)
        self.assertIn("!! tmp/evil.txt", metadata["unauthorized_changed_paths"])
        self.assertEqual(metadata["safety_verdict"]["verdict"], "FAILED_SAFETY")
        self.assertFalse(result.work_product_present)
        self.assertFalse((result.evidence_dir / "work_product.json").exists())
        # Pre-existing ignored file is never attributed to the provider.
        self.assertNotIn("tmp/old.txt", metadata["ignored_path_changes"]["created"])
        self.assertNotIn("!! tmp/old.txt", metadata["unauthorized_changed_paths"])
        # Nothing is reverted.
        self.assertTrue((self.repo / "tmp" / "evil.txt").exists())

    def test_new_ignored_write_in_read_only_mode_is_failed_safety(self):
        def write(cwd):
            (cwd / "tmp" / "evil.txt").write_text("payload\n", encoding="utf-8")

        result, metadata = self.run_with(write, mode=runner.MODE_READ_ONLY)
        self.assertEqual(result.state, runner.RunState.FAILED_SAFETY)
        self.assertEqual(metadata["safety_verdict"]["verdict"], "FAILED_SAFETY")
        self.assertEqual(metadata["ignored_path_changes"]["unauthorized"], ["tmp/evil.txt"])

    def test_deleting_preexisting_ignored_file_outside_scope_is_failed_safety(self):
        def write(cwd):
            (cwd / "tmp" / "old.txt").unlink()

        result, metadata = self.run_with(write)
        self.assertEqual(result.state, runner.RunState.FAILED_SAFETY)
        self.assertEqual(metadata["ignored_path_changes"]["removed"], ["tmp/old.txt"])

    def test_positive_contract_in_scope_work_stays_safe(self):
        def write(cwd):
            (cwd / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
            (cwd / "src" / "build.log").write_text("log\n", encoding="utf-8")

        result, metadata = self.run_with(write)
        self.assertEqual(result.state, runner.RunState.SUCCESS)
        self.assertEqual(metadata["safety_verdict"]["verdict"], "SAFE")
        self.assertEqual(metadata["authorized_changed_paths"], ["?? src/a.py"])
        self.assertEqual(metadata["unauthorized_changed_paths"], [])
        self.assertEqual(metadata["ignored_path_changes"]["authorized"], ["src/build.log"])
        self.assertEqual(metadata["runner_evidence_tampering"], [])
        self.assertTrue(result.work_product_present)
        work_product = json.loads((result.evidence_dir / "work_product.json").read_text(encoding="utf-8"))
        # An ignored file is reported, never checkpointed as work product.
        self.assertEqual(work_product["authorized_changed_paths"], ["?? src/a.py"])

    def test_unavailable_ignored_listing_never_compares_unchanged(self):
        snap = runner.GitSnapshot("b", "h", "", "", "t", ignored_status=None)
        with self.assertRaises(ValueError):
            runner.compute_ignored_path_changes(snap, snap)
        unavailable = runner.GitSnapshot("b", "h", "", "", "t", ignored_status=runner.GIT_STATUS_UNAVAILABLE)
        with self.assertRaises(ValueError):
            runner.compute_ignored_path_changes(unavailable, unavailable)


# ---------------------------------------------------------------------------
# A05-F2: trusted provider executable resolution
# ---------------------------------------------------------------------------

def _make_fake_cli(directory: Path, name: str = "claude") -> Path:
    """A synthetic CLI that must never run: it would only echo a marker."""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = directory / f"{name}.cmd"
        path.write_text("@echo HOSTILE\r\n", encoding="utf-8")
    else:
        path = directory / name
        path.write_text("#!/bin/sh\necho HOSTILE\n", encoding="utf-8")
        path.chmod(0o755)
    return path


class TrustedExecutableTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.hostile_cwd = self.root / "worktree"
        _make_fake_cli(self.hostile_cwd)

    def test_windows_claude_cmd_in_cwd_is_never_selected(self):
        cwd_entries = os.pathsep.join([".", "", "relative" + os.sep + "bin", str(self.hostile_cwd)])
        found = providers.locate_trusted_executable(
            "claude", path=cwd_entries, cwd=self.hostile_cwd, windows=True, pathext=".COM;.EXE;.BAT;.CMD",
        )
        self.assertIsNone(found)
        self.assertEqual(
            providers.trusted_search_dirs(path=cwd_entries, cwd=self.hostile_cwd, windows=True), [])

    def test_untrusted_root_is_excluded_but_trusted_dir_resolves_absolute(self):
        inside = self.hostile_cwd / "node_modules" / ".bin"
        _make_fake_cli(inside)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.assertIsNone(providers.locate_trusted_executable(
            "claude", path=str(inside), cwd=elsewhere, untrusted_roots=(self.hostile_cwd,)))
        trusted = self.root / "trusted_bin"
        expected = _make_fake_cli(trusted)
        found = providers.locate_trusted_executable(
            "claude", path=os.pathsep.join([str(inside), str(trusted)]), cwd=elsewhere,
            untrusted_roots=(self.hostile_cwd,))
        self.assertIsNotNone(found)
        self.assertTrue(os.path.isabs(found))
        self.assertEqual(os.path.normcase(found), os.path.normcase(str(expected)))

    def test_probe_never_runs_cwd_cli_for_version(self):
        empty_trusted = self.root / "empty_bin"
        empty_trusted.mkdir()
        original_cwd = os.getcwd()
        os.chdir(self.hostile_cwd)
        try:
            with mock.patch.dict(os.environ, {"PATH": str(empty_trusted)}), \
                    mock.patch.object(providers, "probe_executable_version",
                                      side_effect=AssertionError("untrusted CLI executed")), \
                    mock.patch.object(providers.subprocess, "run",
                                      side_effect=AssertionError("untrusted CLI executed")):
                for provider in (providers.ClaudeProvider(), providers.CodexProvider()):
                    probe = provider.probe()
                    self.assertFalse(probe.available)
                    self.assertIsNone(probe.executable)
        finally:
            os.chdir(original_cwd)

    def test_probe_excludes_untrusted_root_set_by_runner(self):
        repo_bin = self.hostile_cwd / "bin"
        _make_fake_cli(repo_bin)
        provider = providers.ClaudeProvider()
        provider.untrusted_roots = (self.hostile_cwd,)
        with mock.patch.dict(os.environ, {"PATH": str(repo_bin)}), \
                mock.patch.object(providers, "probe_executable_version",
                                  side_effect=AssertionError("untrusted CLI executed")):
            self.assertFalse(provider.probe().available)

    def test_runner_binds_worktree_as_untrusted_root_before_probe(self):
        seen = []

        def fake_probe(self):
            seen.append(tuple(self.untrusted_roots))
            return providers.ProviderProbe(self.provider_id, False, reason="test")

        repo = self.root / "repo"
        repo.mkdir()
        with mock.patch.object(providers.ClaudeProvider, "probe", fake_probe):
            result = runner.execute_work_order(runner.WorkOrderRequest(repo=str(repo), work_order="x"))
        self.assertEqual(result.state, runner.RunState.CLAUDE_ERROR)
        self.assertEqual(len(seen), 1)
        self.assertEqual([Path(p).resolve() for p in seen[0]], [repo.resolve()])


# ---------------------------------------------------------------------------
# Hostile evidence / bytecode never promotes SAFE nor is imported
# ---------------------------------------------------------------------------

class HostileEvidenceAndBytecodeTest(_RunnerFixture):
    def test_in_scope_pyc_is_never_safe_work_product(self):
        def write(cwd):
            cache = cwd / "src" / "__pycache__"
            cache.mkdir()
            (cache / f"keep.{sys.implementation.cache_tag}.pyc").write_bytes(b"\x00hostile")

        result, metadata = self.run_with(write)
        self.assertEqual(result.state, runner.RunState.FAILED_SAFETY)
        self.assertIn(f"!! src/__pycache__/keep.{sys.implementation.cache_tag}.pyc",
                      metadata["unauthorized_changed_paths"])
        self.assertFalse(result.work_product_present)

    def test_forged_runner_evidence_is_failed_safety_even_when_scope_covers_it(self):
        def write(cwd):
            runs = list((cwd / "runtime" / "claude_runner" / "runs").iterdir())
            self.assertEqual(len(runs), 1)
            run_dir = runs[0]
            (run_dir / "git_before.txt").write_text("forged\n", encoding="utf-8")
            (run_dir / "work_product.json").write_text(json.dumps({
                "schema_version": runner.WORK_PRODUCT_SCHEMA_VERSION,
                "authorized_changed_paths": ["?? anything"], "process_confirmed_stopped": True,
            }), encoding="utf-8")

        # The scope even covers the evidence tree: Runner evidence is never
        # provider work product, whatever the scope says.
        result, metadata = self.run_with(write, scope=("runtime", "src"))
        self.assertEqual(result.state, runner.RunState.FAILED_SAFETY)
        tampering = metadata["runner_evidence_tampering"]
        self.assertIn(f"{runner.RUNNER_EVIDENCE_TAMPERED_PREFIX} git_before.txt", tampering)
        self.assertIn(f"{runner.RUNNER_EVIDENCE_TAMPERED_PREFIX} work_product.json", tampering)
        for entry in tampering:
            self.assertIn(entry, metadata["unauthorized_changed_paths"])
        self.assertFalse(result.work_product_present)

    def test_hardened_env_never_points_bytecode_into_the_worktree(self):
        env = providers.hardened_process_env({"PATH": "x", "PYTEST_ADDOPTS": "-q"})
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(env["PYTEST_ADDOPTS"], "-q -p no:cacheprovider")
        prefix = Path(env["PYTHONPYCACHEPREFIX"])
        self.assertTrue(prefix.is_absolute())
        self.assertFalse(prefix.exists())
        self.assertNotEqual(env["PYTHONPYCACHEPREFIX"], providers.hardened_process_env()["PYTHONPYCACHEPREFIX"])
        with self.assertRaises(ValueError):
            prefix.resolve().relative_to(self.repo.resolve())

    def test_planted_unchecked_hash_pyc_is_not_imported_by_supervised_child(self):
        pkg = self.root / "acceptance_fixture"
        pkg.mkdir()
        (pkg / "target_mod.py").write_text("VALUE = 'good'\n", encoding="utf-8")
        hostile_src = self.root / "hostile_src.py"
        hostile_src.write_text("VALUE = 'evil'\n", encoding="utf-8")
        planted = pkg / "__pycache__" / f"target_mod.{sys.implementation.cache_tag}.pyc"
        py_compile.compile(
            str(hostile_src), cfile=str(planted), doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
        argv = [sys.executable, "-c", "import target_mod; print(target_mod.VALUE)"]

        # Control: the fixture really is hostile for a plain child.
        plain_env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPYCACHEPREFIX",)}
        plain_env["PYTHONDONTWRITEBYTECODE"] = "1"
        control_run = subprocess.run(argv, cwd=str(pkg), capture_output=True, text=True, env=plain_env, timeout=60)
        self.assertEqual(control_run.stdout.strip(), "evil", control_run.stderr)

        control = providers.supervision.ExecutionControl(
            worker_id="w", attempt=1, evidence_path=self.root / "process-evidence" / "attempt-1.json")
        outcome = providers.run_process(argv, pkg, None, 60, provider_id="acceptance", control=control)
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        self.assertEqual(outcome.stdout.strip(), "good")


if __name__ == "__main__":
    unittest.main()
