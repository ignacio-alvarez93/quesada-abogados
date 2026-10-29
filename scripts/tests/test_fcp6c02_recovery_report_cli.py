"""FCP-6C-02: read-only recovery report CLI over durable Runner evidence.

Every run lives in its own temporary state root built from the FCP-6A-01
fixtures (which are pinned to the Runner's persisted key sets). No provider,
Director, Git repository, network or GUI is used; `subprocess` is used ONLY
here, to invoke the CLI as a host would. Nothing is skipped.
"""

import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_recovery_report_cli as cli
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_recovery_advisory as ra
from scripts.tests import test_runner_failure_intelligence as fx

PID = fx.PID
SECRET = fx.SECRET
MODULE_PATH = Path(cli.__file__)
REPO_ROOT = MODULE_PATH.resolve().parents[2]
PROTECTED_SOURCES = [
    REPO_ROOT / "scripts" / "ai" / name for name in (
        "runner_failure_intelligence.py", "runner_recovery_advisory.py", "runner_pipeline.py",
        "claude_runner.py", "fabric_director.py", "fabric_director_cli.py", "fabric_recovery_report_cli.py",
    )
] + [REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"]
GUARANTEES = ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed")


def _file_hashes(paths) -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


_SOURCE_HASHES_AT_IMPORT = _file_hashes(PROTECTED_SOURCES)


def _tree_snapshot(root: str) -> list:
    """Names, kinds, sizes, mtimes and content digests of a whole tree."""
    entries = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in sorted(dirs + files):
            path = os.path.join(current, name)
            st = os.lstat(path)
            rel = os.path.relpath(path, root)
            if os.path.islink(path):
                entries.append((rel, "link", os.readlink(path)))
            elif os.path.isfile(path):
                entries.append((rel, "file", st.st_size, st.st_mtime_ns,
                                hashlib.sha256(Path(path).read_bytes()).hexdigest()))
            else:
                entries.append((rel, "dir", st.st_mtime_ns))
    return entries


def _dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    if isinstance(text, str):
        text = text.encode("utf-8")
    path.write_bytes(text)


class _StateCase(unittest.TestCase):
    """A private tmp dir holding `state/` (the state root) and `outside/`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fcp6c02-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "state"
        self.outside = self.tmp / "outside"
        self.state.mkdir()
        self.outside.mkdir()
        self.run_dir = self.state / PID

    def write_run(self, pairs, *, status=None, pipeline=None):
        """`pairs` = [(summary, result-or-None)]; results land at their
        nominal `workers/<summary id>/result.json`."""
        summaries = [s for s, _ in pairs]
        _dump(self.run_dir / "pipeline_result.json", pipeline or fx._pipeline(summaries, status=status))
        for summary, result in pairs:
            if result is not None:
                _dump(self.run_dir / "workers" / summary["id"] / "result.json", result)

    def worker_file(self, wid):
        return self.run_dir / "workers" / wid / "result.json"

    def run_cli(self, *, run_id=PID, state_root=None):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--state-root", str(state_root if state_root is not None else self.state), "--run-id", run_id]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def report(self, **kwargs) -> dict:
        code, out, err = self.run_cli(**kwargs)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assert_clean_output(out)
        report = json.loads(out)
        self.assert_not_authorized(report)
        return report

    def refused(self, code_name, **kwargs) -> str:
        code, out, err = self.run_cli(**kwargs)
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith(f"error: {code_name}: "), err)
        self.assert_clean_output(err)
        return err

    def assert_clean_output(self, text):
        for leak in (SECRET, str(self.tmp), self.tmp.name, "Traceback", "message_excerpt"):
            self.assertNotIn(leak, text)
        text.encode("ascii")

    def assert_not_authorized(self, report):
        self.assertEqual(report["schema"], cli.SCHEMA)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["authority"]["role"], "READER")
        self.assertIs(report["authority"]["launcher"], False)
        for flag in GUARANTEES + ("resume_allowed", "merging_allowed"):
            self.assertIs(report[flag], False)
            self.assertIs(report["advisory"][flag], False)
            for worker in report["advisory"]["workers"]:
                self.assertIs(worker[flag], False)
        for flag in GUARANTEES:
            self.assertIs(report["diagnostic"][flag], False)
            for worker in report["diagnostic"]["workers"]:
                self.assertIs(worker[flag], False)
        self.assertEqual(report["diagnostic"]["marker"], fi.DIAGNOSTIC_MARKER)
        self.assertEqual(report["advisory"]["marker"], ra.ADVISORY_MARKER)

    def reads(self, report):
        return [w["read"] for w in report["inputs"]["workers"]]

    def symlink(self, target: Path, link: Path, *, directory=False):
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(str(target), str(link), target_is_directory=directory)  # failure is a test failure


# ---------------------------------------------------------------------------
class OutcomeReportTests(_StateCase):
    def test_two_successful_workers_with_complete_evidence(self):
        self.write_run([(fx._summary("a"), fx._result("a")), (fx._summary("b"), fx._result("b"))])
        report = self.report()
        self.assertEqual(report["run_id"], PID)
        self.assertEqual(self.reads(report), ["READ", "READ"])
        self.assertEqual(report["diagnostic"]["diagnostic_status"], "SUCCESS")
        self.assertEqual(report["diagnostic"]["reason_codes"], ["SUCCESS_CONSISTENT"])
        self.assertEqual(report["advisory"]["category"], "HISTORICAL_SUCCESS")
        self.assertEqual(report["advisory"]["observation"], "NO_FOLLOWUP_INDICATED")
        self.assertEqual([w["worker_id"] for w in report["diagnostic"]["workers"]], ["a", "b"])

    def test_report_is_exactly_the_public_6a_6b_projection(self):
        pairs = [(fx._summary("a"), fx._result("a")), fx._fixtures()["failed_non_transient"]]
        pairs[1] = (dict(pairs[1][0], id="b"), dict(pairs[1][1], worker_id="b"))
        self.write_run(pairs)
        report = self.report()
        expected = fi.assess_pipeline(
            fx._pipeline([s for s, _ in pairs]), {s["id"]: r for s, r in pairs})
        self.assertEqual(report["diagnostic"], expected.to_dict())
        self.assertEqual(report["advisory"], ra.advise_pipeline(expected).to_dict())

    def test_failure_quota_auth_and_blocked_are_reported_not_acted_on(self):
        cases = {
            "failed_non_transient": ("NATIVE_FAILED", "NATIVE_FAILED", "HUMAN_REVIEW"),
            "quota": ("PROVIDER_QUOTA_WAIT", "EXISTING_PROVIDER_QUOTA_WAIT", "RUNNER_NATIVE"),
            "auth": ("PROVIDER_AUTH_BLOCKED", "PROVIDER_AUTH_BLOCKED", "HUMAN_REVIEW"),
            "preflight": ("PREFLIGHT_REFUSED", "PREFLIGHT_REFUSED", "HUMAN_REVIEW"),
            "checkpoint_failed": ("CHECKPOINT_FAILED", "CHECKPOINT_FAILED", "HUMAN_REVIEW"),
        }
        fixtures = fx._fixtures()
        for name, (reason, category, responsibility) in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.run_dir, ignore_errors=True)
                self.write_run([fixtures[name]])
                report = self.report()
                self.assertEqual(self.reads(report), ["READ"])
                self.assertIn(reason, report["diagnostic"]["reason_codes"])
                self.assertNotEqual(report["diagnostic"]["diagnostic_status"], "SUCCESS")
                self.assertEqual(report["advisory"]["category"], category)
                self.assertEqual(report["advisory"]["responsibility"], responsibility)

    def test_existing_retry_wait_without_result_is_observed_only(self):
        self.write_run([fx._fixtures()["retry_wait"]])
        report = self.report()
        self.assertEqual(self.reads(report), ["ABSENT"])
        self.assertEqual(report["advisory"]["category"], "EXISTING_RETRY_WAIT")
        self.assertEqual(report["advisory"]["observation"], "OBSERVE_EXISTING_WAIT")

    def test_missing_worker_result_is_none_and_unverified(self):
        self.write_run([(fx._summary("a"), fx._result("a")), (fx._summary("b"), None)], status="SUCCESS")
        report = self.report()
        self.assertEqual(self.reads(report), ["READ", "ABSENT"])
        self.assertEqual(report["diagnostic"]["diagnostic_status"], "UNVERIFIED")
        self.assertIn("EVIDENCE_MISSING", report["diagnostic"]["workers"][1]["reason_codes"])
        self.assertEqual(report["advisory"]["category"], "EVIDENCE_GAP")

    def test_missing_workers_directory_reports_every_worker_absent(self):
        self.write_run([(fx._summary("a"), None), (fx._summary("b"), None)], status="SUCCESS")
        report = self.report()
        self.assertEqual(self.reads(report), ["ABSENT", "ABSENT"])
        self.assertEqual(report["diagnostic"]["diagnostic_status"], "UNVERIFIED")

    def test_extra_and_duplicate_workers_are_reported_not_dropped(self):
        self.write_run([(fx._summary("a"), fx._result("a")), (fx._summary("a"), None)], status="SUCCESS")
        _dump(self.worker_file("zz-extra"), fx._result("zz-extra"))
        (self.run_dir / "workers" / ".hidden").mkdir()
        report = self.report()
        self.assertEqual(self.reads(report), ["READ", "DUPLICATE_ID"])
        diag = report["diagnostic"]
        self.assertEqual(len(diag["workers"]), 2)
        self.assertIn("DUPLICATE_WORKER_ID", diag["reason_codes"])
        self.assertIn("EXTRA_WORKER_RESULT", diag["reason_codes"])
        self.assertEqual(diag["extra_worker_ids"], ["zz-extra"])
        self.assertEqual(diag["unidentified_extra_results"], 1)
        self.assertEqual(diag["diagnostic_status"], "UNVERIFIED")
        self.assertEqual(report["advisory"]["category"], "EVIDENCE_INVALID")

    def test_worker_result_of_another_pipeline_is_identity_mismatch(self):
        self.write_run([(fx._summary("a"), dict(fx._result("a"), pipeline_id="other-run"))])
        report = self.report()
        self.assertIn("IDENTITY_MISMATCH", report["diagnostic"]["reason_codes"])
        self.assertEqual(report["advisory"]["category"], "EVIDENCE_INVALID")

    def test_persisted_result_path_is_never_followed(self):
        decoy = self.outside / "result.json"
        _dump(decoy, fx._result("a"))
        summary = dict(fx._summary("a"), result_path=str(decoy), worker_path=str(decoy))
        self.write_run([(summary, None)], status="SUCCESS")
        report = self.report()
        self.assertEqual(self.reads(report), ["ABSENT"])
        self.assertIn("EVIDENCE_MISSING", report["diagnostic"]["reason_codes"])
        self.assertNotEqual(report["diagnostic"]["diagnostic_status"], "SUCCESS")


# ---------------------------------------------------------------------------
class FileValidationTests(_StateCase):
    def test_worker_result_over_size_limit_is_refused_as_malformed(self):
        self.write_run([(fx._summary("a"), fx._result("a"))])
        self.worker_file("a").write_bytes(b" " * (2 * 1024 * 1024 + 1))
        report = self.report()
        self.assertEqual(self.reads(report), ["REFUSED_TOO_LARGE"])
        self.assertIn("MALFORMED_EVIDENCE", report["diagnostic"]["reason_codes"])
        self.assertEqual(report["advisory"]["category"], "EVIDENCE_INVALID")

    def test_pipeline_result_size_limit_is_inclusive_at_two_mib(self):
        self.assertEqual(cli.MAX_JSON_BYTES, 2 * 1024 * 1024)
        self.write_run([(fx._summary("a"), fx._result("a"))])
        body = json.dumps(fx._pipeline([fx._summary("a")])).encode("ascii")
        path = self.run_dir / "pipeline_result.json"
        path.write_bytes(body + b" " * (cli.MAX_JSON_BYTES - len(body)))
        self.assertEqual(self.report()["diagnostic"]["diagnostic_status"], "SUCCESS")
        path.write_bytes(body + b" " * (cli.MAX_JSON_BYTES + 1 - len(body)))
        self.refused("REPORT_PIPELINE_RESULT_TOO_LARGE")

    def test_malformed_pipeline_result_is_a_safe_error_without_bytes(self):
        for name, payload in {
            "truncated": '{"pipeline_id": "%s", "token": "%s"' % (PID, SECRET),
            "nan": '{"pipeline_id": "%s", "x": NaN, "token": "%s"}' % (PID, SECRET),
            "trailing": '{"pipeline_id": "%s"} {"token": "%s"}' % (PID, SECRET),
        }.items():
            with self.subTest(name):
                _dump(self.run_dir / "pipeline_result.json", payload)
                self.refused("REPORT_PIPELINE_RESULT_JSON_INVALID")
        _dump(self.run_dir / "pipeline_result.json", b"\xef\xbb\xbf{}")
        self.refused("REPORT_PIPELINE_RESULT_NOT_UTF8")
        _dump(self.run_dir / "pipeline_result.json", b'{"token": "\xff' + SECRET.encode() + b'"}')
        self.refused("REPORT_PIPELINE_RESULT_NOT_UTF8")
        _dump(self.run_dir / "pipeline_result.json", "[" * 100000 + "]" * 100000)
        self.refused("REPORT_PIPELINE_RESULT_JSON_INVALID")
        _dump(self.run_dir / "pipeline_result.json", [PID])
        self.refused("REPORT_PIPELINE_RESULT_NOT_OBJECT")

    def test_duplicate_key_pipeline_result_is_refused(self):
        _dump(self.run_dir / "pipeline_result.json",
              '{"pipeline_id": "%s", "status": "SUCCESS", "status": "FAILED", "t": "%s"}' % (PID, SECRET))
        self.refused("REPORT_PIPELINE_RESULT_JSON_DUPLICATE_KEY")

    def test_malformed_or_duplicate_worker_json_is_diagnosed_safely(self):
        self.write_run([(fx._summary("a"), fx._result("a")), (fx._summary("b"), fx._result("b"))])
        self.worker_file("a").write_text('{"state": "SUCCESS", "token": "%s"' % SECRET, encoding="utf-8")
        self.worker_file("b").write_text(
            '{"state": "FAILED", "state": "SUCCESS", "token": "%s"}' % SECRET, encoding="utf-8")
        report = self.report()
        self.assertEqual(self.reads(report), ["REFUSED_JSON_INVALID", "REFUSED_JSON_DUPLICATE_KEY"])
        for worker in report["diagnostic"]["workers"]:
            self.assertEqual(worker["primary_reason"], "MALFORMED_EVIDENCE")
        self.assertEqual(report["diagnostic"]["diagnostic_status"], "UNVERIFIED")
        self.assertEqual(report["advisory"]["category"], "EVIDENCE_INVALID")

    def test_run_identity_must_match_pipeline_result(self):
        self.write_run([(fx._summary("a"), fx._result("a"))])
        pipeline = json.loads((self.run_dir / "pipeline_result.json").read_text(encoding="utf-8"))
        _dump(self.run_dir / "pipeline_result.json", dict(pipeline, pipeline_id="other-run"))
        self.refused("REPORT_RUN_IDENTITY_MISMATCH")

    def test_missing_run_state_root_and_pipeline_result_are_errors(self):
        self.refused("REPORT_RUN_NOT_FOUND")
        self.run_dir.mkdir()
        self.refused("REPORT_PIPELINE_RESULT_MISSING")
        (self.run_dir / "pipeline_result.json").mkdir()
        self.refused("REPORT_PIPELINE_RESULT_NOT_REGULAR_FILE")
        self.refused("REPORT_STATE_ROOT_INVALID", state_root=self.tmp / "absent")
        _dump(self.tmp / "plain-file", "{}")
        self.refused("REPORT_STATE_ROOT_INVALID", state_root=self.tmp / "plain-file")
        self.refused("REPORT_STATE_ROOT_INVALID", state_root="")


# ---------------------------------------------------------------------------
class PathSafetyTests(_StateCase):
    def test_run_id_traversal_and_unsafe_names_are_refused(self):
        _dump(self.outside / "pipeline_result.json", fx._pipeline([fx._summary("a")]))
        _dump(self.state / "pipeline_result.json", fx._pipeline([fx._summary("a")]))
        for run_id in ("..", ".", "../outside", "..\\outside", "a/b", "a\\b", ".hidden", "night-1.", "",
                       "C:x", "/abs", "x" * 65, "NUL", "con", "Com1.json", "lpt9", "night 1", "a:b"):
            with self.subTest(run_id=run_id):
                self.refused("REPORT_RUN_ID_INVALID", run_id=run_id)

    def test_unicode_and_control_characters_in_ids_are_refused(self):
        for run_id in ("night\x07-1", "night\x00", "n\u00efght-1", "night\u202e1", "\uff0e\uff0e", "a\n"):
            with self.subTest(run_id=repr(run_id)):
                self.refused("REPORT_RUN_ID_INVALID", run_id=run_id)
        bad_ids = ["b\x07", "\u00e9", "b\u202e"]
        self.write_run([(fx._summary("a"), fx._result("a"))] + [(fx._summary(w), None) for w in bad_ids])
        report = self.report()
        self.assertEqual(self.reads(report), ["READ", "UNSAFE_ID", "UNSAFE_ID", "UNSAFE_ID"])
        self.assertEqual([w["worker_id"] for w in report["inputs"]["workers"]], ["a", None, None, None])
        self.assertIn("MALFORMED_EVIDENCE", report["diagnostic"]["reason_codes"])

    def test_worker_id_traversal_is_never_opened(self):
        _dump(self.outside / "result.json", dict(fx._result("a"), token=SECRET))
        _dump(self.state / "result.json", fx._result("a"))
        evil = ["../../outside", "..", "../..", "..\\..\\outside", "/abs", "C:\\x", ".git", "x/../a"]
        self.write_run([(fx._summary(w), None) for w in evil], status="SUCCESS")
        with mock.patch.object(cli, "_read_regular", wraps=cli._read_regular) as reader:
            report = self.report()
        opened = [os.path.relpath(c.args[0], self.run_dir) for c in reader.call_args_list]
        self.assertEqual(opened, ["pipeline_result.json"])
        self.assertEqual(self.reads(report), ["UNSAFE_ID"] * len(evil))
        self.assertEqual(report["diagnostic"]["missing_worker_ids"], [])
        self.assertIn("MISSING_WORKER_RESULT", report["diagnostic"]["reason_codes"])
        self.assertIn("MALFORMED_EVIDENCE", report["diagnostic"]["reason_codes"])
        self.assertEqual(report["advisory"]["category"], "EVIDENCE_INVALID")

    def test_symlinked_state_files_are_refused(self):
        self.write_run([(fx._summary("a"), fx._result("a")), (fx._summary("b"), fx._result("b"))])
        decoy = self.outside / "result.json"
        _dump(decoy, fx._result("b"))
        self.worker_file("b").unlink()
        self.symlink(decoy, self.worker_file("b"))
        report = self.report()
        self.assertEqual(self.reads(report), ["READ", "REFUSED_SYMLINK"])
        self.assertEqual(report["diagnostic"]["workers"][1]["primary_reason"], "MALFORMED_EVIDENCE")
        self.assertNotEqual(report["diagnostic"]["diagnostic_status"], "SUCCESS")

        real = self.outside / "pipeline_result.json"
        shutil.move(str(self.run_dir / "pipeline_result.json"), str(real))
        self.symlink(real, self.run_dir / "pipeline_result.json")
        self.refused("REPORT_PIPELINE_RESULT_SYMLINK")

    def test_symlinked_directories_are_refused_at_every_level(self):
        self.write_run([(fx._summary("a"), fx._result("a"))])
        # workers/<id>/ as a link to a real worker directory elsewhere.
        shutil.move(str(self.run_dir / "workers" / "a"), str(self.outside / "a"))
        self.symlink(self.outside / "a", self.run_dir / "workers" / "a", directory=True)
        self.assertEqual(self.reads(self.report()), ["REFUSED_SYMLINK"])
        # workers/ itself.
        shutil.move(str(self.run_dir / "workers"), str(self.outside / "workers"))
        self.symlink(self.outside / "workers", self.run_dir / "workers", directory=True)
        self.refused("REPORT_WORKERS_DIR_REFUSED")
        # the run directory.
        shutil.move(str(self.run_dir), str(self.outside / PID))
        self.symlink(self.outside / PID, self.run_dir, directory=True)
        self.refused("REPORT_RUN_DIR_REFUSED")
        # the state root.
        self.symlink(self.state, self.tmp / "state-link", directory=True)
        self.refused("REPORT_STATE_ROOT_INVALID", state_root=self.tmp / "state-link")

    def test_windows_junctions_are_refused_like_symlinks(self):
        self.write_run([(fx._summary("a"), fx._result("a"))])
        shutil.move(str(self.run_dir), str(self.outside / PID))
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(self.outside / PID), str(self.run_dir))
        else:
            self.symlink(self.outside / PID, self.run_dir, directory=True)
        self.assertTrue((self.run_dir / "pipeline_result.json").is_file())
        self.refused("REPORT_RUN_DIR_REFUSED")


# ---------------------------------------------------------------------------
class ReadOnlyAndOutputTests(_StateCase):
    def test_cli_is_read_only_across_every_scenario(self):
        fixtures = fx._fixtures()
        pairs = [(fx._summary("ok"), fx._result("ok"))] + [
            (dict(s, id=f"w{i}"), dict(r, worker_id=f"w{i}") if r else None)
            for i, (s, r) in enumerate(fixtures.values())
        ]
        self.write_run(pairs)
        self.worker_file("w0").write_text('{"x": 1, "x": 2}', encoding="utf-8")
        _dump(self.outside / "r.json", fx._result("w1"))
        self.worker_file("w1").unlink()
        self.symlink(self.outside / "r.json", self.worker_file("w1"))
        _dump(self.worker_file("extra"), fx._result("extra"))
        before = _tree_snapshot(str(self.tmp))
        for kwargs in ({}, {"run_id": "../outside"}, {"run_id": "missing"}, {}):
            self.run_cli(**kwargs)
        self.assertEqual(_tree_snapshot(str(self.tmp)), before)

    def test_stdout_is_stable_sorted_ascii_json_without_secrets(self):
        fixtures = fx._fixtures()
        pairs = [fixtures["acceptance_failed"], fixtures["partial_evidence"]]
        pairs[1] = (dict(pairs[1][0], id="b"), dict(pairs[1][1], worker_id="b", stderr=SECRET))
        self.write_run(pairs)
        first = self.run_cli()
        second = self.run_cli()
        self.assertEqual(first, second)
        code, out, err = first
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, cli.render(json.loads(out)) + "\n")
        self.assertEqual(list(json.loads(out)), sorted(json.loads(out)))
        self.assertEqual(set(json.loads(out)), {
            "schema", "schema_version", "marker", "run_id", "authority", "inputs", "diagnostic", "advisory",
            "certified", "authorizes_action", "auto_retry_allowed", "execution_allowed", "resume_allowed",
            "merging_allowed",
        })
        for leak in (SECRET, "C:/state", "C:/repo", "_evidence", "claude", "result_path", "stderr"):
            self.assertNotIn(leak, out)

    def test_unexpected_failure_is_a_bounded_error_without_traceback(self):
        self.write_run([(fx._summary("a"), fx._result("a"))])
        with mock.patch.object(fi, "assess_pipeline", side_effect=RuntimeError(SECRET)):
            self.refused("REPORT_INTERNAL_ERROR")

    def test_usage_errors_never_echo_argument_values(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--state-root", str(self.tmp), "--bogus", SECRET])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("REPORT_USAGE_INVALID", err.getvalue())
        self.assert_clean_output(err.getvalue())


# ---------------------------------------------------------------------------
class HostInvocationTests(_StateCase):
    def _host(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSTARTUP")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", str(MODULE_PATH), *args], cwd=str(self.outside), env=env,
            capture_output=True, text=True, timeout=120, check=False,
        )

    def test_direct_script_invocation_on_a_simulated_host(self):
        self.write_run([(fx._summary("a"), fx._result("a")), (fx._summary("b"), fx._result("b"))])
        before = _tree_snapshot(str(self.tmp))
        done = self._host("--state-root", str(self.state), "--run-id", PID)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        report = json.loads(done.stdout)
        self.assertEqual(report["diagnostic"]["diagnostic_status"], "SUCCESS")
        self.assert_not_authorized(report)
        refused = self._host("--state-root", str(self.state), "--run-id", "../outside")
        self.assertEqual(refused.returncode, cli.EXIT_REPORT_REFUSED)
        self.assertEqual(refused.stdout, "")
        self.assertTrue(refused.stderr.startswith("error: REPORT_RUN_ID_INVALID: "))
        self.assert_clean_output(refused.stderr)
        self.assertEqual(_tree_snapshot(str(self.tmp)), before)

    def test_cli_loads_no_provider_runner_director_or_process_code(self):
        probe = (
            "import json, sys; sys.path.insert(0, sys.argv[1]);"
            "import scripts.ai.fabric_recovery_report_cli;"
            "print(json.dumps(sorted(m for m in sys.modules)))"
        )
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, "-B", "-c", probe, str(REPO_ROOT)], cwd=str(self.outside), env=env,
                              capture_output=True, text=True, timeout=120, check=True)
        loaded = set(json.loads(done.stdout))
        self.assertEqual({m for m in loaded if m.startswith("scripts.")}, {
            "scripts.ai", "scripts.ai.fabric_recovery_report_cli", "scripts.ai.runner_failure_intelligence",
            "scripts.ai.runner_recovery_advisory",
        })
        for forbidden in ("subprocess", "socket", "http", "urllib.request", "ssl", "threading", "asyncio"):
            self.assertNotIn(forbidden, loaded)


class StaticContractTests(unittest.TestCase):
    def test_module_imports_only_stdlib_and_public_6a_6b(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        self.assertEqual(imported, {
            "__future__", "argparse", "json", "math", "os", "stat", "sys", "pathlib", "typing",
            "scripts.ai.runner_failure_intelligence", "scripts.ai.runner_recovery_advisory",
        })
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("write", "write_text", "write_bytes", "mkdir", "makedirs", "remove", "unlink", "rename",
                          "replace", "rmdir", "symlink", "system", "Popen", "spawnv", "startfile", "execv",
                          "chmod", "utime", "truncate", "read_text", "realpath", "resolve_path"):
            self.assertNotIn(forbidden, attrs)
        for forbidden in ("open", "exec", "eval", "__import__", "compile", "input", "subprocess"):
            self.assertNotIn(forbidden, names)
        private = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                   and isinstance(n.value, ast.Name) and n.value.id in ("fi", "ra") and n.attr.startswith("_")}
        self.assertEqual(private, set())
        opens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "open"]
        self.assertEqual(len(opens), 1)
        self.assertNotIn("O_WRONLY", attrs)
        self.assertNotIn("O_RDWR", attrs)
        self.assertNotIn("O_CREAT", attrs)

    def test_protected_sources_are_unchanged_by_the_suite(self):
        self.assertEqual(_file_hashes(PROTECTED_SOURCES), _SOURCE_HASHES_AT_IMPORT)
        for path in PROTECTED_SOURCES:
            self.assertTrue(path.is_file(), path.name)


def tearDownModule():
    # Re-checked after every test of this module has run.
    if _file_hashes(PROTECTED_SOURCES) != _SOURCE_HASHES_AT_IMPORT:
        raise AssertionError("a protected source file changed while the FCP-6C-02 suite ran")


if __name__ == "__main__":
    unittest.main()
