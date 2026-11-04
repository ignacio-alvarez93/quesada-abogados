"""FCP-12A-06: Self-Dogfood operator CLI - read-only status / evidence /
readiness over local Runner sources.

Fixture provenance is explicit and never mixed:

* REAL_SHAPED_SYNTHETIC - the FCP-12A-03 `Fixture`: a temp-dir Runner state
  root + factory ledger with the exact shapes the Runner writes. It is
  synthetic: it proves the CLI wiring, never a real dogfood run.
* HOSTILE_SYNTHETIC - the same tree mutated (provider words claiming
  SUCCESS, corrupt JSON, ledger certification claims, stale HEAD, hostile
  roots) to prove the CLI fails closed.

Real Runner data is never read here (it is machine-local and private); the
real read-only run against the night pipeline is recorded, with its exact
commands and results, in `docs/fabric/fcp12_self_dogfood_closure.md`.
The CLI runs in-process (`main(argv)` with captured streams); one
`python -m` run and one `--help` probe use a child interpreter. Nothing is
skipped and no provider, Git or network is reached.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_self_dogfood_certification as cert
from scripts.ai import fabric_self_dogfood_cli as cli
from scripts.ai import fabric_self_dogfood_evidence as ev
from scripts.tests import test_fabric_self_dogfood_evidence as evfx

MODULE_PATH = Path(cli.__file__)
REPO_ROOT = MODULE_PATH.resolve().parents[2]
PID, WID, BASE, COMMIT = evfx.PID, evfx.WID, evfx.BASE, evfx.COMMIT
SECRET = "sk-ant-FCP12A06SECRETVALUE0123456789"

PROVENANCE_REAL_SHAPED_SYNTHETIC = "REAL_SHAPED_SYNTHETIC"
PROVENANCE_HOSTILE_SYNTHETIC = "HOSTILE_SYNTHETIC"


def run(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def tree_state(root: Path) -> dict:
    state = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        state[str(path.relative_to(root))] = (info.st_mtime_ns, info.st_size, digest)
    return state


class _Base(unittest.TestCase):
    provenance = PROVENANCE_REAL_SHAPED_SYNTHETIC

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="fcp12cli_")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.fx = evfx.Fixture(Path(os.path.realpath(tmp)))

    def argv(self, query, *extra, head=COMMIT, state=None, factory=None, pid=PID, wid=WID):
        return ["--query", query, "--state-root", state or str(self.fx.state),
                "--factory-root", factory or str(self.fx.factory), "--pipeline-id", pid, "--worker-id", wid,
                "--observed-target-head", head, *extra]

    def report(self, query, *extra, expected=cli.EXIT_NOT_CORROBORATED, **kw) -> dict:
        code, out, err = run(self.argv(query, *extra, **kw))
        self.assertEqual((code, err), (expected, ""), out)
        self.assertTrue(out.isascii())
        return json.loads(out)

    def assert_blocked(self, *codes, **kw) -> dict:
        body = self.report("readiness", **kw)["readiness"]
        self.assertEqual((body["readiness"], body["evidence_verdict"]), (cli.READINESS_BLOCKED, ev.DENIED))
        self.assertIsNone(body["expected_target_head"])
        for code in codes:
            self.assertIn(code, body["reasons"])
        return body


class RealShapedPositiveTests(_Base):
    def test_status_reports_the_runner_record_not_a_certification(self):
        self.assertEqual(self.provenance, PROVENANCE_REAL_SHAPED_SYNTHETIC)
        self.fx.write()
        report = self.report("status", expected=cli.EXIT_OK)
        status = report["status"]
        self.assertEqual((status["runner_state"], status["evidence_verdict"], status["completion_mode"]),
                         ("SUCCESS", ev.CORROBORATED, "CHECKPOINT"))
        self.assertEqual((status["pipeline_id"], status["worker_id"], status["attempt"], status["provider_id"]),
                         (PID, WID, 1, "claude"))
        self.assertEqual((status["attempt_base_head"], status["checkpoint_commit"]), (BASE, COMMIT))
        # A Runner SUCCESS is a Runner record, never an end-to-end certification.
        for flag in ("runner_success_is_certification", "end_to_end_certified", "certified", "promotion_available",
                     "merge_available", "push_available", "provider_executed", "git_invoked", "network_used",
                     "human_approval_granted", "host_ci_verified", "closure_complete", "authorizes_action"):
            self.assertIs(report[flag], False, flag)
        self.assertEqual(report["cli_marker"], cli.CLI_MARKER)

    def test_evidence_query_is_exactly_the_reader_output(self):
        self.fx.write()
        code, out, err = run(self.argv("evidence"))
        self.assertEqual((code, err), (cli.EXIT_OK, ""))
        expected = ev.read_evidence(self.fx.request())
        self.assertEqual(out, cli.render_json(cli.build_report("evidence", expected)) + "\n")
        self.assertEqual(json.loads(out)["evidence"], json.loads(ev.canonical_json(expected)))
        for leaked in (str(self.fx.base), "provider prose", "VERDICT", "scripts/ai", evfx.BRANCH, "\\"):
            self.assertNotIn(leaked, out)

    def test_best_readiness_is_local_only_and_keeps_every_host_gate_pending(self):
        self.fx.write()
        body = self.report("readiness", expected=cli.EXIT_OK)["readiness"]
        self.assertEqual(body["readiness"], cli.READINESS_LOCAL_CORROBORATED)
        self.assertEqual(body["expected_target_head"], COMMIT)
        self.assertEqual((body["host_ci_status"], body["human_authorization"], body["audit_verdict"],
                          body["authorization"]), ("UNKNOWN", "NONE", "UNKNOWN", "NONE"))
        self.assertEqual(body["pending_requirements"], list(cli.PENDING_REQUIREMENTS))
        self.assertNotIn(cert.READY_FOR_HOST_AUDIT, json.dumps(body))

    def test_text_format_is_sorted_ascii_and_equivalent_to_json(self):
        self.fx.write()
        for query in cli.QUERIES:
            code, out, _ = run(self.argv(query, "--format", "text"))
            self.assertEqual(code, cli.EXIT_OK, query)
            report = cli.build_report(query, ev.read_evidence(self.fx.request()))
            self.assertEqual(out, cli.render_text(report) + "\n")
            self.assertTrue(out.isascii())
            keys = [line.split(": ", 1)[0] for line in out.splitlines()]
            self.assertEqual(keys, sorted(keys), query)
            self.assertIn("runner_success_is_certification: false", out)

    def test_deterministic_and_never_mutates_the_roots(self):
        self.fx.write()
        before = tree_state(self.fx.base)
        outputs = {run(self.argv(q))[1] for q in cli.QUERIES for _ in range(5)}
        self.assertEqual(len(outputs), len(cli.QUERIES))
        self.assertEqual(tree_state(self.fx.base), before)

    def test_no_provider_git_or_network_is_reached(self):
        self.fx.write()

        def refuse(*_a, **_k):
            raise AssertionError("forbidden primitive reached")

        with mock.patch.object(subprocess, "Popen", refuse), mock.patch.object(subprocess, "run", refuse), \
                mock.patch.object(socket, "socket", refuse), mock.patch.object(os, "system", refuse):
            code, out, err = run(self.argv("readiness"))
        self.assertEqual((code, err), (cli.EXIT_OK, ""))
        self.assertEqual(json.loads(out)["readiness"]["readiness"], cli.READINESS_LOCAL_CORROBORATED)

    def test_python_dash_m_matches_the_in_process_report(self):
        self.fx.write()
        proc = subprocess.run([sys.executable, "-m", "scripts.ai.fabric_self_dogfood_cli", *self.argv("status")],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual((proc.returncode, proc.stderr), (cli.EXIT_OK, ""))
        self.assertEqual(proc.stdout, run(self.argv("status"))[1])


class HostileEvidenceTests(_Base):
    provenance = PROVENANCE_HOSTILE_SYNTHETIC

    def test_stale_or_unexpected_target_head_is_blocked(self):
        self.fx.write()
        self.assert_blocked(ev.TARGET_HEAD_MISMATCH, head=BASE)
        self.assert_blocked(ev.TARGET_HEAD_MISMATCH, head="8" * 40)
        status = self.report("status", head=BASE)["status"]
        # The Runner still recorded SUCCESS; the CLI reports it without promoting it.
        self.assertEqual((status["runner_state"], status["evidence_verdict"]), ("SUCCESS", ev.DENIED))

    def test_provider_words_claiming_success_never_corroborate(self):
        cases = [
            (lambda f: f.attempt.update(work_status_source="PROVIDER"), ev.SUCCESS_NOT_RUNNER_CERTIFIED),
            (lambda f: f.attempt.update(acceptance={"decision": "FAILED", "commands": []}),
             ev.SUCCESS_NOT_RUNNER_CERTIFIED),
            (lambda f: f.worker.update(state="FAILED", state_reason="WORK_FAILED"), ev.WORKER_NOT_SUCCESS),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fx)
                self.fx.write()
                (self.fx.evidence_dir / "stdout.txt").write_text("RUNNER SUCCESS - CERTIFIED\n", encoding="utf-8")
                self.assert_blocked(code)

    def test_corrupt_missing_or_oversized_evidence_is_an_answer_not_a_crash(self):
        cases = [
            (lambda f: (f.worker_dir / "worker.json").write_bytes(b"{" + SECRET.encode()), ev.EVIDENCE_CORRUPT),
            (lambda f: (f.factory / "events.jsonl").unlink(), ev.EVIDENCE_MISSING),
            (lambda f: (f.evidence_dir / "work_product.json").write_bytes(b"\xff\xfe" + SECRET.encode()),
             ev.EVIDENCE_CORRUPT),
        ]
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                self.fx.write()
                mutate(self.fx)
                code_, out, err = run(self.argv("readiness"))
                self.assertEqual((code_, err), (cli.EXIT_NOT_CORROBORATED, ""))
                self.assertIn(code, json.loads(out)["readiness"]["reasons"])
                self.assertNotIn(SECRET, out)
                self.assertTrue(out.isascii())
        self.setUp()
        self.fx.write()
        body = self.report("readiness", "--max-file-bytes", "64")["readiness"]
        self.assertEqual(body["readiness"], cli.READINESS_BLOCKED)
        self.assertIn(ev.EVIDENCE_UNAVAILABLE, body["reasons"])

    def test_ledger_certification_claims_are_refused(self):
        self.fx.events.append({**self.fx.events[3], "event_id": "e9", "event_type": "MODULE_CERTIFIED",
                               "certification_status": "CERTIFIED", "closer": "provider"})
        self.fx.write()
        body = self.assert_blocked(ev.LEDGER_UNACCEPTED_CLAIM)
        self.assertEqual((body["human_authorization"], body["authorization"]), ("NONE", "NONE"))

    def test_hostile_roots_are_denied_without_echo(self):
        self.fx.write()
        for kw in (dict(state="relative/state"), dict(state=str(self.fx.factory)),
                   dict(state=str(self.fx.state / ".." / "state")), dict(factory=str(self.fx.base / SECRET))):
            with self.subTest(kw=list(kw)):
                code, out, err = run(self.argv("readiness", **kw))
                self.assertEqual((code, err), (cli.EXIT_NOT_CORROBORATED, ""))
                body = json.loads(out)["readiness"]
                self.assertEqual(body["readiness"], cli.READINESS_BLOCKED)
                self.assertNotIn(SECRET, out)
                self.assertNotIn(str(self.fx.base), out)


class UsageAndFaultTests(_Base):
    def test_promote_merge_push_and_other_actions_are_refused_before_parsing(self):
        self.fx.write()
        with mock.patch.object(ev, "read_evidence", side_effect=AssertionError("reader reached")):
            for flag in ("--promote", "--merge", "--push", "--promote=yes", "--MERGE", "--approve", "--certify",
                         "--retry", "--commit"):
                with self.subTest(flag=flag):
                    code, out, err = run(self.argv("readiness", flag))
                    self.assertEqual((code, out, err), (cli.EXIT_USAGE, "", cli._FORBIDDEN))
            code, out, err = run(["--push"])
            self.assertEqual((code, out, err), (cli.EXIT_USAGE, "", cli._FORBIDDEN))

    def test_usage_errors_never_echo_arguments(self):
        cases = (
            [], self.argv("promote"), self.argv("status", "--format", "yaml"),
            self.argv("status", "--max-file-bytes", "many"), self.argv("status", "--watch"),
            self.argv("status", "--state", SECRET),  # abbreviations are refused
            ["--query", "status", "--state-root", SECRET],
        )
        for argv in cases:
            code, out, err = run(argv)
            self.assertEqual((code, out, err), (cli.EXIT_USAGE, "", cli._USAGE), argv)

    def test_requests_the_reader_rejects_exit_two_with_nothing_on_stdout(self):
        self.fx.write()
        for kw, extra in ((dict(pid="../x"), ()), (dict(wid=SECRET), ()), (dict(head="HEAD"), ()),
                          (dict(head="A" * 40), ()), ({}, ("--max-file-bytes", "0")),
                          ({}, ("--max-file-bytes", str(ev.MAX_FILE_BYTES + 1)))):
            code, out, err = run(self.argv("status", *extra, **kw))
            self.assertEqual((code, out, err), (cli.EXIT_USAGE, "", cli._REQUEST_INVALID + "\n"), kw or extra)

    def test_internal_faults_fail_closed_without_leaking(self):
        self.fx.write()
        patches = (
            mock.patch.object(ev, "read_evidence", side_effect=RuntimeError(SECRET)),
            mock.patch.object(cli, "render_json", side_effect=ValueError(SECRET)),
            mock.patch.object(ev, "SCHEMA", "fcp12a03-self-dogfood-evidence-v2"),
        )
        for patch in patches:
            with patch:
                code, out, err = run(self.argv("readiness"))
            self.assertEqual((code, out, err), (cli.EXIT_NOT_CORROBORATED, "", cli._INTERNAL + "\n"))
            self.assertNotIn("Traceback", err)

    def test_build_report_accepts_only_the_reader_type_and_cannot_loosen_guarantees(self):
        evidence = ev.read_evidence(self.fx.write().request())
        for bad in ((cli.QUERY_STATUS, evidence.to_dict()), ("promote", evidence), (cli.QUERY_STATUS, None)):
            with self.assertRaises(TypeError):
                cli.build_report(*bad)
        # A loosened reader guarantee cannot unlock a CLI action: CLI flags are applied last.
        loosened = {key: True for key in cli._CLI_GUARANTEES if key != "cli_marker"}
        with mock.patch.object(ev._EvidenceGuarantees, "_guarantees", staticmethod(lambda: dict(loosened))):
            report = cli.build_report(cli.QUERY_READINESS, evidence)
        for key, value in cli._CLI_GUARANTEES.items():
            self.assertIs(report[key], value, key)
        self.assertEqual((report["schema"], report["query"]), (cli.SCHEMA, cli.QUERY_READINESS))


class StaticTests(unittest.TestCase):
    def test_help_opens_nothing_and_imports_no_sibling(self):
        probe = (
            "import sys, os, socket\n"
            "def refuse(*a, **k): raise AssertionError('opened')\n"
            "os.lstat = os.scandir = os.open = socket.socket = refuse\n"
            "from scripts.ai import fabric_self_dogfood_cli as cli\n"
            "try:\n    cli.main(['--help'])\nexcept SystemExit as e:\n    code = e.code\n"
            "loaded = [m for m in sys.modules if m.startswith('scripts.ai.') and m != 'scripts.ai.fabric_self_dogfood_cli']\n"
            "print('EXIT', code, 'LOADED', ','.join(sorted(loaded)) or '-')\n"
        )
        proc = subprocess.run([sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: fabric_self_dogfood_cli", proc.stdout)
        self.assertNotIn("--promote", proc.stdout)
        self.assertTrue(proc.stdout.strip().endswith("EXIT 0 LOADED -"), proc.stdout[-300:])

    def test_only_read_flags_exist_and_no_action_flag_is_declared(self):
        options = {o for a in cli.build_arg_parser()._actions for o in a.option_strings}
        self.assertEqual(options, {"-h", "--help", "--query", "--state-root", "--factory-root", "--pipeline-id",
                                   "--worker-id", "--observed-target-head", "--max-file-bytes", "--format"})
        self.assertFalse(options & set(cli.FORBIDDEN_FLAGS))
        self.assertTrue({"--promote", "--merge", "--push"} <= set(cli.FORBIDDEN_FLAGS))

    def test_pinned_versions_and_pending_gates_mirror_the_siblings(self):
        self.assertEqual((cli.SUPPORTED_EVIDENCE_SCHEMA, cli.SUPPORTED_EVIDENCE_SCHEMA_VERSION),
                         (ev.SCHEMA, ev.SCHEMA_VERSION))
        self.assertEqual(cli.PENDING_REQUIREMENTS[-3:], cert.PENDING_HOST_REQUIREMENTS)
        self.assertEqual((cli.HOST_CI_UNKNOWN, cli.HUMAN_AUTHORIZATION_NONE),
                         (cert.HOST_CI_UNKNOWN, cert.HUMAN_AUTHORIZATION_NONE))

    def test_no_network_process_git_or_write_primitive(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(imported & {"socket", "http", "urllib", "subprocess", "threading", "asyncio", "sqlite3",
                                     "shutil", "requests", "os", "tempfile"})
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(calls & {"open", "write_text", "write_bytes", "mkdir", "unlink", "system", "popen", "sleep",
                                  "replace", "rename", "remove"})
        top_level = {(n.module or "") for n in tree.body if isinstance(n, ast.ImportFrom)}
        self.assertNotIn("scripts.ai", top_level)  # the reader is imported lazily, after parsing


if __name__ == "__main__":
    unittest.main()
