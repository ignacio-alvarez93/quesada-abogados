"""FCP-11G-07: Fabric Control Plane operator CLI.

The CLI runs in-process (`main(argv)` with captured stdout / stderr) over the
FCP-11G-07 gateway fixtures (Runner-native state, native factory ledger, one
private allowed root); one `python -m` run and one `--help` run use a child
interpreter with no network and no write. Nothing is executed against real
Runner data, sent anywhere or skipped.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_control_plane_cli as cli
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_gateway as gw
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.tests import test_fabric_control_plane_gateway as gwfx
from scripts.tests.test_fabric_resource_quota_report import canonical_temp_dir

MODULE_PATH = Path(cli.__file__)
REPO_ROOT = MODULE_PATH.resolve().parents[2]
AS_OF = gwfx.AS_OF
PID = gwfx.PID
SECRET = gwfx.SECRET


def run(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class CliTestBase(gwfx.GatewayTestBase):
    def argv(self, query, *extra, roots=None, state=None):
        args = ["--query", query, "--state-root", state or str(self.root), "--observed-at-utc", AS_OF]
        for root in roots or (str(self.top),):
            args += ["--allowed-root", root]
        return args + list(extra)

    def assert_clean_failure(self, code, out, err, expected):
        self.assertEqual(code, expected)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error: GATEWAY_"))
        for leak in (str(self.top), SECRET, "Traceback"):
            self.assertNotIn(leak, err)


class EquivalenceTests(CliTestBase):
    def setUp(self):
        super().setUp()
        self.scenario()

    CASES = (
        ("summary", (), {}),
        ("pipelines", ("--limit", "1"), {"limit": 1}),
        ("worker", ("--pipeline-id", PID, "--worker-id", "w2"), {"pipeline_id": PID, "worker_id": "w2"}),
        ("attention", ("--offset", "1", "--limit", "2"), {"offset": 1, "limit": 2}),
        ("resources", (), {}),
    )

    def test_cli_json_equals_the_api_for_every_query(self):
        cases = self.CASES + (("activity", ("--factory-root", str(self.factory), "--event-type", "WORKER_STARTED"),
                               {"factory_root": str(self.factory), "event_type": "WORKER_STARTED"}),)
        for query, extra, kw in cases:
            code, out, err = run(self.argv(query, *extra))
            self.assertEqual((code, err), (cli.EXIT_OK, ""), query)
            self.assertEqual(out, gw.render_json(self.ask(query, **kw)) + "\n", query)

    def test_cli_text_equals_the_api_text(self):
        for query, extra, kw in self.CASES:
            code, out, _ = run(self.argv(query, *extra, "--format", "text"))
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual(out, gw.render_text(self.ask(query, **kw)) + "\n")
            self.assertTrue(out.isascii())

    def test_same_input_same_output_and_no_mutation(self):
        before = gwfx.tree_state(self.top)
        outputs = {run(self.argv("summary"))[1] for _ in range(20)}
        self.assertEqual(len(outputs), 1)
        self.assertEqual(gwfx.tree_state(self.top), before)

    def test_python_dash_m_matches_the_api(self):
        proc = subprocess.run([sys.executable, "-m", "scripts.ai.fabric_control_plane_cli", *self.argv("summary")],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(proc.stdout.strip(), gw.render_json(self.ask("summary")))

    def test_answers_are_exit_zero_whatever_the_observed_state(self):
        out = json.loads(run(self.argv("summary"))[1])
        self.assertNotEqual(out["result"]["attention_class"], "CLEAR")
        self.assertIs(out["authorizes_action"], False)


class UsageTests(CliTestBase):
    def test_help_opens_nothing_and_imports_no_projection(self):
        probe = (
            "import sys, os, socket\n"
            "def refuse(*a, **k): raise AssertionError('opened')\n"
            "os.lstat = os.scandir = os.open = socket.socket = refuse\n"
            "from scripts.ai import fabric_control_plane_cli as cli\n"
            "try:\n    cli.main(['--help'])\nexcept SystemExit as e:\n    code = e.code\n"
            "loaded = [m for m in sys.modules if m.startswith('scripts.ai.') and m != 'scripts.ai.fabric_control_plane_cli']\n"
            "print('EXIT', code, 'LOADED', ','.join(sorted(loaded)) or '-')\n"
        )
        proc = subprocess.run([sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: fabric_control_plane_cli", proc.stdout)
        self.assertTrue(proc.stdout.strip().endswith("EXIT 0 LOADED -"), proc.stdout[-300:])

    def test_invalid_flags_are_usage_errors_without_echo(self):
        cases = (
            [],
            self.argv("summary", "--watch"),
            self.argv("summary", "--write", "x"),
            self.argv("summary", "--serve"),
            self.argv("delete"),
            self.argv("summary", "--limit", "many"),
            self.argv("summary", "--format", "yaml"),
            self.argv("summary", "--state"),  # abbreviation refused
            ["--query", "summary", "--state-root", str(self.root), "--observed-at-utc", AS_OF],  # no allowed root
            ["--query", "summary", "--allowed-root", str(self.top), "--observed-at-utc", AS_OF],
        )
        for argv in cases:
            code, out, err = run(argv)
            self.assertEqual((code, out, err), (cli.EXIT_USAGE, "", cli._USAGE), argv)

    def test_gateway_usage_refusals_exit_two(self):
        for extra in (("--pipeline-id", "../x"), ("--worker-id", SECRET), ("--limit", "0"),
                      ("--limit", str(gw.MAX_LIMIT + 1)), ("--offset", "-1"), ("--event-type", "DROP")):
            code, out, err = run(self.argv("pipelines", *extra))
            self.assert_clean_failure(code, out, err, cli.EXIT_USAGE)
        self.assert_clean_failure(*run(self.argv("worker", "--pipeline-id", PID)), cli.EXIT_USAGE)
        self.assert_clean_failure(*run(self.argv("activity")), cli.EXIT_USAGE)
        bad_instant = self.argv("summary")
        bad_instant[bad_instant.index(AS_OF)] = "yesterday"
        self.assert_clean_failure(*run(bad_instant), cli.EXIT_USAGE)

    def test_external_paths_are_refused_exit_one(self):
        outside = canonical_temp_dir("fcp11g07-cli-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        for argv in (self.argv("summary", state=str(outside)),
                     self.argv("summary", state="relative/state"),
                     self.argv("summary", state=str(self.top / ".." / self.top.name / "state")),
                     self.argv("activity", "--factory-root", str(outside)),
                     self.argv("summary", roots=("relative",)),
                     self.argv("resources", "--report-file", str(outside / "r.json"))):
            code, out, err = run(argv)
            self.assert_clean_failure(code, out, err, cli.EXIT_REFUSED)
            self.assertNotIn(str(outside), err)

    def test_corrupt_json_is_an_answer_not_a_crash(self):
        self.scenario()
        (self.root / PID / "pipeline.json").write_bytes(b"{" + SECRET.encode())
        code, out, err = run(self.argv("pipelines"))
        self.assertEqual((code, err), (cli.EXIT_OK, ""))
        row = json.loads(out)["result"]["pipelines"][0]
        self.assertEqual(row["record_status"]["condition"], cp.CORRUPT)
        self.assertNotIn(SECRET, out)
        self.assertTrue(out.isascii())

    def test_internal_errors_are_safe_exit_one(self):
        with mock.patch.object(snap, "take_snapshot", side_effect=RuntimeError(SECRET)):
            code, out, err = run(self.argv("summary"))
        self.assert_clean_failure(code, out, err, cli.EXIT_REFUSED)
        with mock.patch.object(gw, "render_json", side_effect=ValueError(SECRET)):
            code, out, err = run(self.argv("summary"))
        self.assertEqual(err.strip(), "error: GATEWAY_INTERNAL_ERROR: the response could not be produced")
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))

    def test_oversized_response_is_refused(self):
        self.scenario()
        with mock.patch.object(gw, "MAX_RESPONSE_BYTES", 256):
            code, out, err = run(self.argv("pipelines"))
        self.assert_clean_failure(code, out, err, cli.EXIT_REFUSED)
        self.assertIn("GATEWAY_RESPONSE_TOO_LARGE", err)


class StaticTests(unittest.TestCase):
    def test_only_read_flags_exist(self):
        options = {o for a in cli.build_arg_parser()._actions for o in a.option_strings}
        self.assertEqual(options, {"-h", "--help", "--query", "--allowed-root", "--state-root", "--observed-at-utc",
                                   "--factory-root", "--report-file", "--pipeline-id", "--worker-id",
                                   "--event-type", "--offset", "--limit", "--format"})

    def test_queries_mirror_the_gateway(self):
        self.assertEqual(cli.QUERIES, gw.QUERIES)

    def test_no_network_server_process_git_or_write_primitive(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(imported & {"socket", "http", "urllib", "subprocess", "threading", "asyncio", "sqlite3",
                                     "shutil", "requests"})
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(calls & {"open", "write_text", "write_bytes", "mkdir", "unlink", "system", "popen", "sleep"})
        top_level = {(n.module or "") for n in tree.body if isinstance(n, ast.ImportFrom)}
        self.assertNotIn("scripts.ai", top_level)  # the gateway is imported lazily, after parsing


if __name__ == "__main__":
    unittest.main()
