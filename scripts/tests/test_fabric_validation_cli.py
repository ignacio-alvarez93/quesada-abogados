"""FCP-8D-01: consultative, read-only FCP-8 validation CLI. Offline: the
Director is either the A-02 / B-01 fake services or the real
`FabricDirectorService` over synthetic temporary roots - no Runner
execution, Git, network or write outside the test's own temp directory."""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_validation_cli as cli
from scripts.ai import fabric_validation_dag as vd
from scripts.ai import fabric_validation_report as rp
from scripts.ai import fabric_validation_rules as vr
from scripts.ai import fabric_validation_single as vs
from scripts.tests import test_fabric_validation_dag as td
from scripts.tests import test_fabric_validation_single as ts

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_validation_cli.py"
RUN = ts.RUN
OTHER_RUN = "fdb-20261030t000000000000-ffffffff"
SECRET = "C:/Users/someone/private/sk-secret-token"
FORBIDDEN_TEXT = (ts.EMAIL, ts.SECRET_DIR, td.BLUEPRINT, ts.WORKER, RUN, SECRET, "provider prose", "Traceback",
                  "sk-", "Users", "\\")


def invoke(argv) -> tuple:
    """(exit code, stdout, stderr) of `cli.main(argv)`."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # argparse usage errors / --help
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def snapshot(root: str) -> dict:
    tree = {}
    for base, dirs, files in os.walk(root):
        for name in dirs:
            tree[os.path.relpath(os.path.join(base, name), root)] = None
        for name in files:
            path = os.path.join(base, name)
            tree[os.path.relpath(path, root)] = Path(path).read_bytes()
    return tree


class _Roots(unittest.TestCase):
    """Temporary explicit roots holding the run directory the CLI checks."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.state = os.path.join(self.tmp, "state")
        self.director = os.path.join(self.tmp, "director")
        os.makedirs(os.path.join(self.director, RUN))
        self.write_pipeline_result({"pipeline_id": RUN, "status": "SUCCESS",
                                    "workers": [{"id": ts.WORKER, "state": "SUCCESS"}]})

    def write_pipeline_result(self, payload, run_id=RUN):
        os.makedirs(os.path.join(self.state, run_id), exist_ok=True)
        Path(self.state, run_id, cli.PIPELINE_RESULT_NAME).write_text(json.dumps(payload), encoding="utf-8")

    def argv(self, command="single", run_id=RUN, *extra):
        return [command, "--run-id", run_id, "--state-root", self.state, "--director-root", self.director, *extra]

    def with_service(self, service, argv):
        with mock.patch.object(cli, "build_service", return_value=service) as built:
            result = invoke(argv)
        return result, built

    def single(self, s=None, e=None, d=None, **kwargs):
        s, e, d = ts.consistent() if s is None else (s, e, d)
        service = ts.FakeService(s, e, d, **kwargs)
        (code, out, err), _ = self.with_service(service, self.argv("single"))
        return code, out, err, service

    def dag(self, summary=None, **kwargs):
        service = td.FakeService(td.dag() if summary is None else summary, **kwargs)
        (code, out, err), _ = self.with_service(service, self.argv("dag"))
        return code, out, err, service

    def assert_refused(self, result, code, *engine_codes):
        exit_code, out, err = result[:3]
        self.assertEqual(exit_code, cli.EXIT_REFUSED)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith(f"error: {code}: "), err)
        for engine_code in engine_codes:
            self.assertIn(engine_code, err)
        for text in FORBIDDEN_TEXT:
            self.assertNotIn(text, err)


# ---------------------------------------------------------------------------
class ArgparseTests(_Roots):
    def assert_usage(self, argv):
        code, out, err = invoke(argv)
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error: VALIDATION_USAGE_INVALID"))
        self.assertNotIn(SECRET, err)

    def test_no_command_is_usage_error(self):
        self.assert_usage([])

    def test_each_required_argument_is_mandatory(self):
        full = self.argv("single")
        for flag in ("--run-id", "--state-root", "--director-root"):
            with self.subTest(flag=flag):
                index = full.index(flag)
                self.assert_usage(full[:index] + full[index + 2:])

    def test_only_single_and_dag_commands_exist(self):
        parser = cli.build_arg_parser()
        sub = next(a for a in parser._actions if isinstance(a, cli.argparse._SubParsersAction))
        self.assertEqual(tuple(sub.choices), cli.COMMANDS)

    def test_mutating_commands_are_refused(self):
        for command in ("submit", "run", "recover", "merge", "push", "jobs", "execute"):
            with self.subTest(command=command):
                self.assert_usage([command, "--run-id", RUN])

    def test_mutating_flags_are_refused(self):
        for flag in ("--execute-confirm", "--merge", "--push", "--submit", "--recover"):
            with self.subTest(flag=flag):
                self.assert_usage(self.argv("single") + [flag])

    def test_abbreviated_options_are_refused(self):
        self.assert_usage(["single", "--run", RUN, "--state-root", self.state, "--director-root", self.director])

    def test_unknown_format_is_refused(self):
        self.assert_usage(self.argv("single", RUN, "--format", "yaml"))

    def test_usage_error_never_echoes_values(self):
        self.assert_usage(["single", "--run-id", SECRET, "--state-root", SECRET, "--bogus", SECRET])

    def test_argument_order_is_free(self):
        service = ts.FakeService(*ts.consistent())
        argv = ["single", "--director-root", self.director, "--format", "json", "--state-root", self.state,
                "--run-id", RUN]
        (code, out, _), _ = self.with_service(service, argv)
        (code2, out2, _), _ = self.with_service(ts.FakeService(*ts.consistent()), self.argv("single"))
        self.assertEqual((code, out), (code2, out2))

    def test_options_before_command_are_refused(self):
        self.assert_usage(["--run-id", RUN, "single"])


# ---------------------------------------------------------------------------
class SingleCommandTests(_Roots):
    def test_consistent_run_report_is_verified_and_bound(self):
        code, out, err, _ = self.single()
        envelope = json.loads(out)
        self.assertEqual(err, "")
        expected = rp.build_report(ts.observe_consistent())
        self.assertEqual(envelope["report"], expected.to_dict())
        self.assertEqual(envelope["report_sha256"], expected.report_sha256)
        self.assertEqual(envelope["verdict"], expected.verdict)
        self.assertEqual(code, cli._EXIT_OF_VERDICT[expected.verdict])
        self.assertTrue(rp.verify_report(envelope["report"], observation=ts.observe_consistent()).valid)

    def test_envelope_schema_and_compact_canonical_form(self):
        _, out, _, _ = self.single()
        line = out.rstrip("\n")
        envelope = json.loads(line)
        self.assertEqual(line, cli.render_json(envelope))
        self.assertNotIn(" ", line.replace("ADVISORY ONLY", ""))
        self.assertEqual((envelope["schema"], envelope["schema_version"]), (cli.SCHEMA, cli.SCHEMA_VERSION))
        self.assertEqual((envelope["report_schema"], envelope["report_schema_version"]),
                         (rp.SCHEMA, rp.SCHEMA_VERSION))
        self.assertEqual(envelope["command"], "single")
        self.assertEqual(envelope["report"]["report_sha256"], envelope["report_sha256"])

    def test_output_is_deterministic(self):
        self.assertEqual(self.single()[1], self.single()[1])

    def test_reads_result_evidence_decision_once_in_order(self):
        _, _, _, service = self.single()
        self.assertEqual(service.calls, [("result", RUN), ("evidence", RUN), ("decision", RUN)])
        self.assertEqual(service.forbidden, [])

    def test_failed_worker_requires_human_review(self):
        code, out, _, _ = self.single(*ts.consistent(shared={"worker_state": "FAILED", "work_status": "FAILED"}))
        self.assertEqual(json.loads(out)["verdict"], vr.HUMAN_REVIEW_REQUIRED)
        self.assertEqual(code, cli.EXIT_HUMAN_REVIEW)

    def test_provider_only_success_is_never_complete(self):
        code, out, _, _ = self.single(*ts.consistent(shared={"work_status_source": "PROVIDER"}))
        self.assertNotEqual(json.loads(out)["verdict"], vr.VALIDATION_COMPLETE)
        self.assertNotEqual(code, cli.EXIT_COMPLETE)

    def test_unknown_evidence_is_unproven_not_pass(self):
        code, out, _, _ = self.single(*ts.consistent(shared={"evidence_complete": None}))
        self.assertEqual(json.loads(out)["verdict"], vr.UNPROVEN)
        self.assertEqual(code, cli.EXIT_UNPROVEN)

    def test_text_format_is_token_lines_without_secrets(self):
        code, out, _, _ = self.single()
        (text_code, text, _), _ = self.with_service(ts.FakeService(*ts.consistent()),
                                                    self.argv("single", RUN, "--format", "text"))
        envelope = json.loads(out)
        self.assertEqual(text_code, code)
        self.assertIn(f"report_sha256: {envelope['report_sha256']}", text)
        self.assertIn(f"verdict: {envelope['verdict']}", text)
        self.assertIn("ADVISORY ONLY", text)
        self.assertRaises(ValueError, json.loads, text)
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, text)


# ---------------------------------------------------------------------------
class DagCommandTests(_Roots):
    def test_all_proven_dag_is_verified_and_bound(self):
        code, out, err, service = self.dag()
        envelope = json.loads(out)
        expected = rp.build_report(td.obs(td.dag()))
        self.assertEqual(err, "")
        self.assertEqual(envelope["report"], expected.to_dict())
        self.assertEqual(envelope["command"], "dag")
        self.assertEqual(envelope["report"]["classification"]["source"], vr.SOURCE_DAG_RUN)
        self.assertEqual(code, cli._EXIT_OF_VERDICT[expected.verdict])
        self.assertEqual(service.calls, [RUN])
        self.assertEqual(service.forbidden, [])

    def test_dag_safety_not_projected_is_never_complete(self):
        code, out, _, _ = self.dag()
        self.assertNotEqual(json.loads(out)["verdict"], vr.VALIDATION_COMPLETE)
        self.assertNotEqual(code, cli.EXIT_COMPLETE)

    def test_failed_dag_requires_human_review(self):
        workers = td.chain(3, {1: {"worker_state": "FAILED", "work_status": "FAILED"}})
        code, out, _, _ = self.dag(td.dag(workers, pipeline_status="FAILED"))
        self.assertEqual(json.loads(out)["verdict"], vr.HUMAN_REVIEW_REQUIRED)
        self.assertEqual(code, cli.EXIT_HUMAN_REVIEW)

    def test_dag_report_snapshot_is_stable_across_worker_order_inputs(self):
        first = self.dag()[1]
        second = self.dag()[1]
        self.assertEqual(first, second)
        self.assertEqual(len(json.loads(first)["report"]["classification"]["units"]), 3)

    def test_dag_run_id_must_be_a_director_pipeline_id(self):
        self.write_pipeline_result({"pipeline_id": "plain-run"}, run_id="plain-run")
        result, built = self.with_service(td.FakeService(td.dag()), self.argv("dag", "plain-run"))
        self.assert_refused(result, "VALIDATION_RUN_ID_INVALID")
        built.assert_not_called()


# ---------------------------------------------------------------------------
class MissingInputTests(_Roots):
    def refused_before_service(self, argv, code):
        result, built = self.with_service(ts.FakeService(*ts.consistent()), argv)
        self.assert_refused(result, code)
        built.assert_not_called()

    def test_missing_state_root(self):
        argv = self.argv("single")
        argv[argv.index("--state-root") + 1] = os.path.join(self.tmp, "absent")
        self.refused_before_service(argv, "VALIDATION_STATE_ROOT_INVALID")

    def test_state_root_that_is_a_file(self):
        target = os.path.join(self.tmp, "file")
        Path(target).write_text("x", encoding="utf-8")
        argv = self.argv("single")
        argv[argv.index("--state-root") + 1] = target
        self.refused_before_service(argv, "VALIDATION_STATE_ROOT_INVALID")

    def test_missing_director_root(self):
        argv = self.argv("dag")
        argv[argv.index("--director-root") + 1] = os.path.join(self.tmp, "absent")
        self.refused_before_service(argv, "VALIDATION_DIRECTOR_ROOT_INVALID")

    def test_run_not_found(self):
        self.refused_before_service(self.argv("single", OTHER_RUN), "VALIDATION_RUN_NOT_FOUND")

    def test_run_without_pipeline_result(self):
        os.remove(os.path.join(self.state, RUN, cli.PIPELINE_RESULT_NAME))
        self.refused_before_service(self.argv("single"), "VALIDATION_RUN_NOT_FOUND")

    def test_dag_without_director_request(self):
        os.rmdir(os.path.join(self.director, RUN))
        self.refused_before_service(self.argv("dag"), "VALIDATION_DAG_REQUEST_NOT_FOUND")

    def test_unsafe_run_ids_are_refused_before_any_path(self):
        for run_id in ("../escape", "a/b", "a\\b", "CON", ".hidden", "trailing.", "x" * 65, "é"):
            with self.subTest(run_id=run_id):
                self.refused_before_service(self.argv("single", run_id), "VALIDATION_RUN_ID_INVALID")

    def test_empty_run_id_is_refused(self):
        self.refused_before_service(self.argv("single", ""), "VALIDATION_RUN_ID_INVALID")


# ---------------------------------------------------------------------------
class FailClosedProjectionTests(_Roots):
    def test_read_failure_is_sanitized(self):
        s, e, d = ts.consistent()
        result = self.single(s, e, d, raises={"evidence": OSError(f"cannot open {SECRET} for {ts.EMAIL}")})
        self.assert_refused(result, "VALIDATION_EVIDENCE_UNREADABLE", "EVIDENCE_READ_FAILED")

    def test_cross_run_evidence_is_identity_mismatch(self):
        s, e, d = ts.consistent()
        e = ts.evidence(run_id=OTHER_RUN)
        self.assert_refused(self.single(s, e, d), "VALIDATION_IDENTITY_MISMATCH", "RUN_ID_MISMATCH")

    def test_cross_pipeline_projection_is_identity_mismatch(self):
        s, e, d = ts.consistent(shared={"pipeline_id": OTHER_RUN})
        self.assert_refused(self.single(s, e, d), "VALIDATION_IDENTITY_MISMATCH")

    def test_cross_worker_projection_is_identity_mismatch(self):
        s, e, d = ts.consistent()
        self.assert_refused(self.single(ts.summary(worker_id="w-99"), e, d), "VALIDATION_IDENTITY_MISMATCH",
                            "WORKER_ID_MISMATCH")

    def test_untyped_projection_is_refused(self):
        s, e, d = ts.consistent()
        self.assert_refused(self.single({"run_id": RUN}, e, d), "VALIDATION_PROJECTION_NOT_TYPED",
                            "RESULT_NOT_TYPED")

    def test_missing_worker_identity_is_refused(self):
        s, e, d = ts.consistent(shared={"worker_id": None})
        self.assert_refused(self.single(s, e, d), "VALIDATION_IDENTITY_MISSING", "WORKER_ID_MISSING")

    def test_multiworker_run_requires_dag_command(self):
        s, e, d = ts.consistent()
        error = fd.DirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", f"run {SECRET}")
        self.assert_refused(self.single(s, e, d, raises={"result": error}), "VALIDATION_MULTIWORKER_RUN",
                            "MULTIWORKER_REFUSED")

    def test_dag_provenance_mismatch(self):
        error = fd.DirectorError("DAG_PROVENANCE_MISMATCH", f"{SECRET}: foreign state")
        self.assert_refused(self.dag(raises=error), "VALIDATION_IDENTITY_MISMATCH", "PROVENANCE_REFUSED")

    def test_dag_read_failure(self):
        error = fd.DirectorError("PIPELINE_NOT_FOUND", f"no readable pipeline_result.json under {SECRET}")
        self.assert_refused(self.dag(raises=error), "VALIDATION_EVIDENCE_UNREADABLE", "READ_FAILED")

    def test_dag_summary_not_typed(self):
        self.assert_refused(self.dag({"run_id": RUN}), "VALIDATION_PROJECTION_NOT_TYPED", "SUMMARY_NOT_TYPED")

    def test_dag_cross_run_summary(self):
        self.assert_refused(self.dag(td.dag(run_id=OTHER_RUN, pipeline_id=OTHER_RUN)),
                            "VALIDATION_IDENTITY_MISMATCH")

    def test_dag_invalid_projection(self):
        self.assert_refused(self.dag(td.dag(n=1)), "VALIDATION_PROJECTION_INVALID", "TOO_FEW_WORKERS")

    def test_report_failing_verification_is_refused(self):
        bad = rp.ReportVerification(valid=False, codes=("DIGEST_MISMATCH",))
        real_verify = rp.verify_report

        def verify(report, **kwargs):  # only the CLI's bound re-verification fails
            return bad if "observation" in kwargs else real_verify(report, **kwargs)

        with mock.patch.object(rp, "verify_report", verify):
            self.assert_refused(self.single(), "VALIDATION_REPORT_UNVERIFIED", "DIGEST_MISMATCH")

    def test_unexpected_exception_is_generic_and_sanitized(self):
        with mock.patch.object(cli, "build_service", side_effect=RuntimeError(f"{SECRET} {ts.EMAIL}")):
            result = invoke(self.argv("single"))
        self.assert_refused(result, "VALIDATION_INTERNAL_ERROR")
        self.assertNotIn(ts.EMAIL, result[2])

    def test_unknown_verdict_never_maps_to_success(self):
        self.assertEqual(cli.exit_code_for({"verdict": "SOMETHING_ELSE"}), cli.EXIT_REFUSED)
        self.assertEqual(cli.exit_code_for({}), cli.EXIT_REFUSED)
        self.assertEqual(set(cli._EXIT_OF_VERDICT), set(vr.VERDICTS))
        self.assertEqual(cli._EXIT_OF_VERDICT[vr.VALIDATION_COMPLETE], 0)
        self.assertTrue(all(v != 0 for k, v in cli._EXIT_OF_VERDICT.items() if k != vr.VALIDATION_COMPLETE))


# ---------------------------------------------------------------------------
class ReadOnlyReaderTests(unittest.TestCase):
    def test_reader_exposes_only_the_command_reads(self):
        service = mock.Mock()
        reader = cli._ReadOnlyReader(service, cli.COMMAND_SINGLE)
        for name in ("submit", "run", "recover", "run_blueprint", "submit_blueprint", "result_blueprint",
                     "status", "_load_json", "state_root"):
            with self.subTest(name=name):
                self.assertRaises(AttributeError, getattr, reader, name)
        dag_reader = cli._ReadOnlyReader(service, cli.COMMAND_DAG)
        for name in ("result", "evidence", "decision", "submit_blueprint"):
            with self.subTest(dag=name):
                self.assertRaises(AttributeError, getattr, dag_reader, name)
        self.assertEqual(service.mock_calls, [])

    def test_build_service_passes_only_explicit_roots(self):
        with mock.patch.object(fd, "FabricDirectorService") as service_cls:
            cli.build_service("S", "D")
        service_cls.assert_called_once_with(state_root="S", director_root="D")


# ---------------------------------------------------------------------------
class RealDirectorServiceTests(_Roots):
    """The real `FabricDirectorService` over synthetic roots, with every
    mutating primitive patched to fail and the tree compared before/after."""

    @contextlib.contextmanager
    def no_mutation(self):
        real_open = builtins.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise AssertionError("write attempted")
            return real_open(file, mode, *args, **kwargs)

        def refuse(*_args, **_kwargs):
            raise AssertionError("mutating or external call attempted")

        real_run = subprocess.run
        self.processes = []

        def only_toplevel_query(argv, *args, **kwargs):
            # The Director constructor's own read-only source-repo lookup is
            # the only process allowed; anything else fails the test.
            self.processes.append(list(argv))
            if list(argv)[-2:] != ["rev-parse", "--show-toplevel"]:
                raise AssertionError("process other than git rev-parse --show-toplevel")
            return real_run(argv, *args, **kwargs)

        before = snapshot(self.tmp)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(builtins, "open", guarded_open))
            for target, name in ((os, "mkdir"), (os, "makedirs"), (os, "remove"), (os, "unlink"), (os, "rename"),
                                 (os, "replace"), (os, "rmdir"), (socket, "socket"), (socket, "create_connection")):
                stack.enter_context(mock.patch.object(target, name, refuse))
            stack.enter_context(mock.patch.object(subprocess, "run", only_toplevel_query))
            yield
        self.assertEqual(snapshot(self.tmp), before)

    def test_degenerate_real_run_is_unproven_without_mutation(self):
        with self.no_mutation():
            code, out, err = invoke(self.argv("single"))
        self.assertEqual((code, err), (cli.EXIT_UNPROVEN, ""))
        envelope = json.loads(out)
        self.assertEqual(envelope["verdict"], vr.UNPROVEN)
        self.assertTrue(rp.verify_report(envelope["report"]).valid)
        for text in FORBIDDEN_TEXT:
            self.assertNotIn(text, out)

    def test_real_foreign_pipeline_result_is_identity_mismatch(self):
        self.write_pipeline_result({"pipeline_id": OTHER_RUN, "status": "SUCCESS",
                                    "workers": [{"id": ts.WORKER, "state": "SUCCESS"}]})
        with self.no_mutation():
            result = invoke(self.argv("single"))
        self.assert_refused(result, "VALIDATION_IDENTITY_MISMATCH")

    def test_real_multiworker_run_is_refused_for_single(self):
        self.write_pipeline_result({"pipeline_id": RUN, "status": "SUCCESS", "workers": [
            {"id": "w-01", "state": "SUCCESS"}, {"id": "w-02", "state": "SUCCESS"}]})
        with self.no_mutation():
            result = invoke(self.argv("single"))
        self.assert_refused(result, "VALIDATION_MULTIWORKER_RUN", "MULTIWORKER_REFUSED")

    def test_real_corrupt_pipeline_result_is_unreadable(self):
        Path(self.state, RUN, cli.PIPELINE_RESULT_NAME).write_text("{not json " + SECRET, encoding="utf-8")
        with self.no_mutation():
            result = invoke(self.argv("single"))
        self.assert_refused(result, "VALIDATION_EVIDENCE_UNREADABLE", "RESULT_READ_FAILED")

    def test_real_dag_without_provenance_is_unreadable(self):
        with self.no_mutation():
            result = invoke(self.argv("dag"))
        self.assert_refused(result, "VALIDATION_EVIDENCE_UNREADABLE", "READ_FAILED")


# ---------------------------------------------------------------------------
class AuthorityAndStaticTests(_Roots):
    def test_every_authority_flag_is_false(self):
        for envelope in (json.loads(self.single()[1]), json.loads(self.dag()[1])):
            for flag in cli.AUTHORITY_FLAGS:
                self.assertIs(envelope[flag], False)
                self.assertIs(envelope["report"][flag], False)
            self.assertEqual(envelope["authority"]["execution_authority"], "RUNNER")
            self.assertEqual(envelope["authority"]["pr_ci_authority"], "REMOTE_PR_CI")
            self.assertIs(envelope["authority"]["launcher"], False)
            self.assertEqual(envelope["marker"], cli.OUTPUT_MARKER)

    def test_outputs_carry_no_ids_paths_or_prose(self):
        for out in (self.single()[1], self.dag()[1]):
            for text in FORBIDDEN_TEXT + (self.tmp,):
                self.assertNotIn(text, out)

    def test_module_imports_no_process_network_or_runner_execution(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" for a in node.names} | {node.module}
        forbidden = ("subprocess", "socket", "urllib", "http", "requests", "shutil", "runner_pipeline",
                     "claude_runner", "runner_providers", "runner_promotion", "fabric_director_cli")
        for name in imported:
            for word in forbidden:
                self.assertNotIn(word, name)

    def test_module_calls_no_mutating_director_or_environment_api(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("submit", "submit_blueprint", "run_blueprint", "recover", "submit_and_run",
                          "execute_work_order", "environ", "getenv", "write_text", "write_bytes", "mkdir",
                          "makedirs", "remove", "unlink", "rename", "replace", "system", "popen"):
            self.assertNotIn(forbidden, attributes)
            self.assertNotIn(forbidden, names)

    def test_module_entry_point_runs_as_module(self):
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.ai.fabric_validation_cli", "single", "--run-id", RUN,
             "--state-root", os.path.join(self.tmp, "absent"), "--director-root", self.director],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(completed.returncode, cli.EXIT_REFUSED)
        self.assertEqual(completed.stdout, "")
        self.assertIn("VALIDATION_STATE_ROOT_INVALID", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_engine_contracts_are_reused_not_redefined(self):
        self.assertIs(cli.vs.observe_single_run, vs.observe_single_run)
        self.assertIs(cli.vd.observe_dag_run, vd.observe_dag_run)
        self.assertEqual(cli.AUTHORITY_FLAGS, rp.AUTHORITY_FLAGS)
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("json.loads", source)
        self.assertNotIn("read_text", source)


if __name__ == "__main__":
    unittest.main()
