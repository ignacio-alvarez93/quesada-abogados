"""FCP-9D-02: operator CLI for scheduler plan and state.

Offline: every repository is an ephemeral `git init` under a temporary
directory (the Runner pipeline tests' `_make_repo`); `plan` compiles through
the real FCP-9B-02 planner; `status` reads either the FCP-9C-02 fake
service or the real `FabricDirectorService` over a temporary Director
binding and synthetic Runner state. No Runner execution, provider, network
or write outside the test's own temp directory. Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
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

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_director_cli as dcli
from scripts.ai import fabric_scheduler_cli as cli
from scripts.ai import fabric_scheduler_conflicts as cf
from scripts.ai import fabric_scheduler_plan as pl
from scripts.ai import fabric_scheduler_state as st
from scripts.tests import test_fabric_scheduler_state as ts
from scripts.tests.test_runner_pipeline import _make_repo

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_scheduler_cli.py"
AS_OF = "2026-10-30T12:00:00Z"
RUN = ts.RUN
OTHER_RUN = ts.OTHER_RUN
SECRET = "C:/Users/someone/private/sk-secret-token"
WO_TEXT = "Work Order confidential instructions"
FORBIDDEN_TEXT = (SECRET, WO_TEXT, ts.SECRET_DIR, ts.PROSE, "Traceback", "sk-", "Users", "\\")
ALL_FLAGS = ts.ALL_FLAGS


def invoke(argv) -> tuple:
    """(exit code, stdout, stderr) of `cli.main(argv)`."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # argparse usage errors / --help
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def snapshot(root) -> dict:
    tree = {}
    for base, dirs, files in os.walk(root):
        for name in dirs:
            tree[os.path.relpath(os.path.join(base, name), root)] = None
        for name in files:
            path = os.path.join(base, name)
            tree[os.path.relpath(path, root)] = Path(path).read_bytes()
    return tree


class _Base(unittest.TestCase):
    """Temporary repositories, Work Orders and explicit runtime roots,
    created once per class. Tests only ever read them."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="fcp9d02")
        cls.root = Path(cls._tmp).resolve()
        cls.repos = {n: _make_repo(cls.root, n) for n in ("a", "b", "c")}
        (cls.root / "wo").mkdir()
        cls.wos = {}
        for name in cls.repos:
            cls.wos[name] = cls.root / "wo" / f"{name}.md"
            cls.wos[name].write_text(f"{WO_TEXT} {name}\n", encoding="utf-8")
        cls.inputs = cls.root / "inputs"
        cls.inputs.mkdir()
        cls.state = cls.root / "state"
        cls.director = cls.root / "director"
        cls.state.mkdir()
        cls.director.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def node(self, nid, depends_on=(), provider="claude", **extra) -> dict:
        return {"id": nid, "worktree": str(self.repos[nid]), "work_order": str(self.wos[nid]),
                "provider": provider, "mode": "read-only", "depends_on": list(depends_on), **extra}

    def declaration(self, nodes=None, **extra) -> dict:
        nodes = nodes if nodes is not None else [self.node("a"), self.node("b")]
        return {"pipeline_id": "fcp9d02-dag", "max_workers": 2, "nodes": nodes, **extra}

    def blueprint_file(self, declaration=None, name="bp.json", raw=None) -> str:
        path = self.inputs / f"{self.id().rsplit('.', 1)[-1]}-{name}"
        if raw is None:
            raw = json.dumps(declaration if declaration is not None else self.declaration()).encode("utf-8")
        path.write_bytes(raw)
        return str(path)

    def plan_argv(self, path=None, *extra, states=(("a", "QUEUED"), ("b", "QUEUED")), roots=True):
        argv = ["plan", "--blueprint-file", self.blueprint_file() if path is None else path, "--as-of", AS_OF]
        for nid, state in states:
            argv += ["--node-state", f"{nid}={state}"]
        if roots:
            argv += ["--allowed-root", str(self.root)]
        return argv + list(extra)

    def status_argv(self, run_id=RUN, *extra, state=None, director=None):
        return ["status", "--run-id", run_id, "--state-root", str(state or self.state), "--director-root",
                str(director or self.director), "--as-of", AS_OF, *extra]

    def assert_refused(self, result, code, *engine_codes):
        exit_code, out, err = result[:3]
        self.assertEqual(exit_code, cli.EXIT_REFUSED, err)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith(f"error: {code}: "), err)
        for engine_code in engine_codes:
            self.assertIn(engine_code, err)
        for text in FORBIDDEN_TEXT + (str(self.root),):
            self.assertNotIn(text, err)

    def assert_clean_output(self, out):
        for text in FORBIDDEN_TEXT + (str(self.root), self.root.as_posix(), json.dumps(str(self.root))[1:-1]):
            self.assertNotIn(text, out)


class _StatusRoots(_Base):
    """Synthetic runtime for RUN that passes every existence check."""

    def setUp(self):
        for root, names in ((self.state, cli._RUN_FILES), (self.director, cli._REQUEST_FILES)):
            run_dir = root / RUN
            run_dir.mkdir(exist_ok=True)
            for name in names:
                (run_dir / name).write_text("{}", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.state / RUN, True)
        self.addCleanup(shutil.rmtree, self.director / RUN, True)

    def with_service(self, service, argv=None):
        with mock.patch.object(cli, "build_service", return_value=service) as built:
            result = invoke(argv or self.status_argv())
        return result, built

    def fake(self, summary=None, status=None, **kwargs):
        summary = ts.dag() if summary is None else summary
        status = ts.runner_status(summary) if status is None and type(summary) is fd.DirectorDagRunSummary \
            else status
        return ts.FakeService(summary, status, **kwargs)


# ---------------------------------------------------------------------------
class ArgparseTests(_Base):
    def assert_usage(self, argv):
        code, out, err = invoke(argv)
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error: SCHEDULER_USAGE_INVALID"), err)
        self.assertNotIn(SECRET, err)

    def test_no_command_is_usage_error(self):
        self.assert_usage([])

    def test_only_plan_and_status_commands_exist(self):
        parser = cli.build_arg_parser()
        sub = next(a for a in parser._actions if isinstance(a, cli.argparse._SubParsersAction))
        self.assertEqual(tuple(sub.choices), cli.COMMANDS)
        self.assertEqual(cli.COMMANDS, ("plan", "status"))

    def test_mutating_commands_are_refused(self):
        for command in ("submit", "run", "submit-run-blueprint", "run-blueprint", "recover", "retry", "merge",
                        "push", "execute", "dispatch"):
            with self.subTest(command=command):
                self.assert_usage([command, "--run-id", RUN])

    def test_mutating_flags_are_refused(self):
        for flag in ("--execute-confirm", "--confirm", "--merge", "--push", "--auto-retry", "--retry",
                     "--submit", "--fallback-provider", "--resume"):
            with self.subTest(flag=flag):
                self.assert_usage(self.plan_argv(SECRET) + [flag])
                self.assert_usage(self.status_argv() + [flag])

    def test_each_required_argument_is_mandatory(self):
        for full, flags in ((self.plan_argv(SECRET, states=(), roots=False), ("--blueprint-file", "--as-of")),
                            (self.status_argv(), ("--run-id", "--state-root", "--director-root", "--as-of"))):
            for flag in flags:
                with self.subTest(flag=flag):
                    index = full.index(flag)
                    self.assert_usage(full[:index] + full[index + 2:])

    def test_abbreviated_options_unknown_format_and_values_never_echoed(self):
        self.assert_usage(["status", "--run", RUN, "--state-root", SECRET, "--director-root", SECRET,
                           "--as-of", AS_OF])
        self.assert_usage(self.status_argv(RUN, "--format", "yaml"))
        self.assert_usage(["plan", "--blueprint-file", SECRET, "--as-of", AS_OF, "--max-workers", SECRET])
        self.assert_usage(["status", "--run-id", SECRET, "--bogus", SECRET])


# ---------------------------------------------------------------------------
class PlanCommandTests(_Base):
    def direct_plan(self, declaration, states, roots=True, **kw):
        blueprint = dcli.parse_blueprint_bytes(json.dumps(declaration).encode("utf-8"))
        conflicts = cli.conflict_request_for(blueprint, (str(self.root),) if roots else ())
        return pl.plan_dag(pl.DagPlanRequest(blueprint=blueprint, as_of_utc=AS_OF, node_states=states,
                                             conflict_request=conflicts, **kw))

    def test_admissible_plan_is_the_engine_plan_bound_by_digest(self):
        code, out, err = invoke(self.plan_argv())
        envelope = json.loads(out)
        expected = self.direct_plan(self.declaration(), (("a", "QUEUED"), ("b", "QUEUED")))
        self.assertEqual((code, err), (cli.EXIT_OK, ""))
        self.assertEqual(envelope["outcome"], pl.ADMISSIBLE)
        self.assertEqual(envelope["result"], expected.to_dict())
        self.assertEqual(envelope["result_sha256"],
                         cli.hashlib.sha256(pl.canonical_json(expected).encode("ascii")).hexdigest())
        self.assertEqual((envelope["schema"], envelope["result_schema"]), (cli.SCHEMA, pl.SCHEMA))
        self.assertEqual([d["slot"] for d in envelope["result"]["decisions"]], [0, 1])

    def test_conflicts_unassessed_without_allowed_root_is_unknown(self):
        code, out, _ = invoke(self.plan_argv(roots=False))
        envelope = json.loads(out)
        self.assertEqual((code, envelope["outcome"]), (cli.EXIT_UNKNOWN, pl.UNKNOWN))
        for decision in envelope["result"]["decisions"]:
            self.assertIn(pl.CONFLICTS_UNASSESSED, decision["reasons"])
            self.assertIsNone(decision["slot"])

    def test_omitted_node_state_is_unknown_never_assumed(self):
        code, out, _ = invoke(self.plan_argv(states=(("a", "QUEUED"),)))
        result = json.loads(out)["result"]
        self.assertEqual(code, cli.EXIT_UNKNOWN)
        by_id = {d["node_id"]: d for d in result["decisions"]}
        self.assertEqual(by_id["b"]["reasons"], [pl.NODE_STATE_UNKNOWN])
        self.assertIn(pl.PEER_STATE_UNKNOWN, by_id["a"]["reasons"])

    def test_pending_dependency_waits(self):
        declaration = self.declaration([self.node("a"), self.node("b"), self.node("c", ("a", "b"))])
        argv = self.plan_argv(self.blueprint_file(declaration),
                              states=(("a", "RUNNING"), ("b", "SUCCESS"), ("c", "WAITING_DEPENDENCY")))
        code, out, _ = invoke(argv)
        envelope = json.loads(out)
        self.assertEqual((code, envelope["outcome"]), (cli.EXIT_WAITING, pl.WAITING))
        self.assertEqual(envelope["result"]["decisions"][2]["reasons"], [pl.DEPENDENCY_PENDING])

    def test_all_terminal_is_idle(self):
        code, out, _ = invoke(self.plan_argv(states=(("a", "SUCCESS"), ("b", "FAILED"))))
        self.assertEqual((code, json.loads(out)["outcome"]), (cli.EXIT_WAITING, pl.IDLE))

    def test_expired_window_refuses_nodes_with_distinct_exit(self):
        path = self.blueprint_file(self.declaration(deadline_utc="2026-10-30T11:00:00Z"))
        code, out, _ = invoke(self.plan_argv(path))
        envelope = json.loads(out)
        self.assertEqual((code, envelope["outcome"]), (cli.EXIT_NOT_SUCCESSFUL, pl.REFUSED))
        self.assertTrue(all(pl.WINDOW_EXPIRED in d["reasons"] for d in envelope["result"]["decisions"]))

    def test_limits_can_only_narrow(self):
        code, out, _ = invoke(self.plan_argv(None, "--max-workers", "1"))
        result = json.loads(out)["result"]
        self.assertEqual((code, result["effective_max_workers"]), (cli.EXIT_OK, 1))
        self.assertEqual([d["decision"] for d in result["decisions"]], [pl.ADMISSIBLE, pl.WAITING])
        self.assertEqual(result["decisions"][1]["reasons"], [pl.WORKER_LIMIT_REACHED])
        _, out, _ = invoke(self.plan_argv(None, "--max-workers", "9", "--provider-limit", "claude=1"))
        result = json.loads(out)["result"]
        self.assertEqual(result["effective_max_workers"], 2)
        self.assertEqual(result["effective_provider_limits"], [["claude", 1]])
        self.assertEqual(result["decisions"][1]["reasons"], [pl.PROVIDER_LIMIT_REACHED])

    def test_observed_link_on_worktree_makes_conflicts_unidentified(self):
        linked = str(self.repos["b"])
        real_kind = cli._kind
        with mock.patch.object(cli, "_kind", lambda p: "LINK" if p == linked else real_kind(p)):
            code, out, _ = invoke(self.plan_argv())
        by_id = {d["node_id"]: d for d in json.loads(out)["result"]["decisions"]}
        self.assertEqual(code, cli.EXIT_UNKNOWN)
        self.assertIn(pl.CONFLICT_UNIDENTIFIED, by_id["b"]["reasons"])
        self.assertEqual(cli.observe_link_state(linked, (str(self.root),)), cf.LINK_NONE)
        self.assertEqual(cli.observe_link_state(linked, (str(self.inputs),)), cf.LINK_UNKNOWN)
        self.assertEqual(cli.observe_link_state(str(self.root / "absent"), (str(self.root),)), cf.LINK_UNKNOWN)

    def test_plan_is_deterministic_and_text_matches_json(self):
        path = self.blueprint_file()
        first, second = invoke(self.plan_argv(path)), invoke(self.plan_argv(path))
        self.assertEqual(first, second)
        code, text, err = invoke(self.plan_argv(path, "--format", "text"))
        envelope = json.loads(first[1])
        self.assertEqual((code, err), (first[0], ""))
        self.assertIn(f"result_sha256: {envelope['result_sha256']}", text)
        self.assertIn("outcome: ADMISSIBLE", text)
        self.assertIn("node: a ADMISSIBLE slot=0 reasons=-", text)
        self.assertIn("ADVISORY ONLY", text)
        self.assertRaises(ValueError, json.loads, text)
        self.assert_clean_output(text)
        self.assert_clean_output(first[1])

    def test_plan_never_reaches_the_director_and_mutates_nothing(self):
        path = self.blueprint_file()
        before = snapshot(self.root)
        with mock.patch.object(fd, "FabricDirectorService") as service_cls, \
                mock.patch.object(cli, "build_service") as built:
            code, out, _ = invoke(self.plan_argv(path))
        self.assertEqual(code, cli.EXIT_OK)
        service_cls.assert_not_called()
        built.assert_not_called()
        self.assertEqual(snapshot(self.root), before)
        self.assertNotIn("run_id", json.loads(out)["result"])

    def test_existing_director_cli_parser_is_reused(self):
        with mock.patch.object(dcli, "parse_blueprint_bytes", wraps=dcli.parse_blueprint_bytes) as parse:
            invoke(self.plan_argv())
        parse.assert_called_once()
        self.assertIs(cli.dcli, dcli)
        self.assertEqual(cli.BLUEPRINT_FILE_MAX_BYTES, dcli.BLUEPRINT_FILE_MAX_BYTES)


# ---------------------------------------------------------------------------
class PlanRefusalTests(_Base):
    def test_inadmissible_blueprint_paths(self):
        path = self.blueprint_file()
        for bad in ("bp.json", os.path.join(str(self.inputs), "..", "inputs", Path(path).name), ""):
            with self.subTest(path=bad):
                self.assert_refused(invoke(self.plan_argv(bad)), "SCHEDULER_PATH_NOT_ADMISSIBLE")

    def test_missing_or_non_regular_blueprint_file(self):
        for bad in (str(self.inputs / "absent.json"), str(self.inputs)):
            with self.subTest(path=bad):
                self.assert_refused(invoke(self.plan_argv(bad)), "SCHEDULER_BLUEPRINT_FILE_INVALID")

    def test_linked_blueprint_file_is_refused_before_reading(self):
        path = self.blueprint_file()
        real_kind = cli._kind
        with mock.patch.object(cli, "_kind", lambda p: "LINK" if p == path else real_kind(p)), \
                mock.patch.object(builtins, "open", side_effect=AssertionError("read attempted")):
            result = invoke(self.plan_argv(path))
        self.assert_refused(result, "SCHEDULER_PATH_LINK_REFUSED")

    def test_swapped_file_identity_is_refused(self):
        path = self.blueprint_file()
        real = os.lstat(path)
        fake = os.stat_result((real.st_mode, real.st_ino + 1) + tuple(real)[2:])
        with mock.patch.object(cli.os, "fstat", return_value=fake):
            self.assert_refused(invoke(self.plan_argv(path)), "SCHEDULER_PATH_LINK_REFUSED")

    def test_oversized_blueprint_is_refused(self):
        path = self.blueprint_file(raw=b" " * (cli.BLUEPRINT_FILE_MAX_BYTES + 1))
        self.assert_refused(invoke(self.plan_argv(path)), "SCHEDULER_BLUEPRINT_FILE_TOO_LARGE")

    def test_parser_refusals_keep_only_the_native_code(self):
        cases = (
            (b'{"pipeline_id": "' + SECRET.encode() + b'", ', "BLUEPRINT_JSON_INVALID"),
            (b'{"pipeline_id": "x", "pipeline_id": "y", "nodes": []}', "BLUEPRINT_JSON_DUPLICATE_KEY"),
            (json.dumps({**self.declaration(), "secret": SECRET}).encode(), "BLUEPRINT_SCHEMA_INVALID"),
            (b"\xef\xbb\xbf{}", "BLUEPRINT_FILE_NOT_UTF8"),
        )
        for raw, native in cases:
            with self.subTest(native=native):
                result = invoke(self.plan_argv(self.blueprint_file(raw=raw)))
                self.assert_refused(result, "SCHEDULER_BLUEPRINT_INVALID", native)
                self.assertNotIn("secret", result[2])

    def test_invalid_as_of_is_refused_before_any_read(self):
        with mock.patch.object(cli, "read_blueprint_bytes") as read:
            for as_of in ("2026-10-30T12:00:00", "yesterday", ""):
                with self.subTest(as_of=as_of):
                    argv = self.plan_argv(SECRET)
                    argv[argv.index("--as-of") + 1] = as_of
                    self.assert_refused(invoke(argv), "SCHEDULER_AS_OF_INVALID")
        read.assert_not_called()

    def test_malformed_option_values(self):
        for extra in (("--node-state", "a"), ("--node-state", "=QUEUED"), ("--provider-limit", "claude=one"),
                      ("--provider-limit", "claude=-1"), ("--provider-limit", "claude")):
            with self.subTest(extra=extra):
                self.assert_refused(invoke(self.plan_argv(None, *extra)), "SCHEDULER_ARGUMENT_INVALID")

    def test_planner_request_refusals_carry_engine_codes(self):
        cases = (
            ((("a", "DONE"), ("b", "QUEUED")), pl.NODE_STATE_INVALID),
            ((("a", "QUEUED"), ("a", "READY")), pl.NODE_STATE_DUPLICATE),
            ((("a", "QUEUED"), ("zz", "QUEUED")), pl.NODE_STATE_UNKNOWN_NODE),
        )
        path = self.blueprint_file()
        for states, reason in cases:
            with self.subTest(reason=reason):
                self.assert_refused(invoke(self.plan_argv(path, states=states)), "SCHEDULER_PLAN_REFUSED", reason)
        self.assert_refused(invoke(self.plan_argv(path, "--max-workers", "0")), "SCHEDULER_PLAN_REFUSED",
                            pl.MAX_WORKERS_INVALID)

    def test_structural_refusals_are_the_native_compiler_codes(self):
        cycle = self.declaration([self.node("a", ("b",)), self.node("b", ("a",))])
        self.assert_refused(invoke(self.plan_argv(self.blueprint_file(cycle))), "SCHEDULER_PLAN_REFUSED",
                            pl.BLUEPRINT_REFUSED)
        missing = self.declaration([self.node("a"), {**self.node("b"), "worktree": str(self.root / "nope")}])
        self.assert_refused(invoke(self.plan_argv(self.blueprint_file(missing))), "SCHEDULER_PLAN_REFUSED",
                            pl.BLUEPRINT_REFUSED)

    def test_invalid_allowed_root(self):
        for root, code in ((str(self.root / "absent"), "SCHEDULER_ALLOWED_ROOT_INVALID"),
                           (str(self.wos["a"]), "SCHEDULER_ALLOWED_ROOT_INVALID"),
                           ("relative-root", "SCHEDULER_PATH_NOT_ADMISSIBLE")):
            with self.subTest(root=root):
                argv = self.plan_argv(None, roots=False) + ["--allowed-root", root]
                self.assert_refused(invoke(argv), code)


# ---------------------------------------------------------------------------
class StatusCommandTests(_StatusRoots):
    def test_projection_is_the_engine_projection_bound_by_digest(self):
        summary = ts.dag(("SUCCESS", "RUNNING", "QUEUED"))
        (code, out, err), built = self.with_service(self.fake(summary))
        expected = st.observe_scheduler_state(self.fake(summary), RUN, as_of_utc=AS_OF)
        envelope = json.loads(out)
        self.assertEqual(err, "")
        self.assertEqual(envelope["result"], expected.to_dict())
        self.assertEqual(envelope["result_sha256"],
                         cli.hashlib.sha256(st.canonical_json(expected).encode("ascii")).hexdigest())
        self.assertEqual((envelope["outcome"], code), (st.IN_PROGRESS, cli.EXIT_WAITING))
        built.assert_called_once_with(str(self.state), str(self.director))

    def test_reads_result_blueprint_then_status_once_each(self):
        service = self.fake()
        self.with_service(service)
        self.assertEqual(service.calls, [("result_blueprint", RUN), ("status", RUN)])
        self.assertEqual(service.forbidden, [])

    def test_exit_code_follows_the_projected_outcome(self):
        cases = (("SUCCESS", "SUCCESS", "SUCCESS"), ("SUCCESS", "FAILED", "CANCELLED"),
                 ("SUCCESS", "WAITING_PROVIDER_QUOTA", "QUEUED"))
        seen = set()
        for states in cases:
            with self.subTest(states=states):
                (code, out, _), _ = self.with_service(self.fake(ts.dag(states)))
                outcome = json.loads(out)["outcome"]
                seen.add(outcome)
                self.assertEqual(code, cli._EXIT_OF_OUTCOME["status"][outcome])
                self.assertEqual(code == cli.EXIT_OK, outcome == st.SUCCESS)
        self.assertGreaterEqual(len(seen), 2)

    def test_contradictory_runner_status_is_unknown_never_success(self):
        summary = ts.dag()
        status = ts.runner_status(summary, status="RUNNING")
        (code, out, _), _ = self.with_service(self.fake(summary, status))
        self.assertEqual(json.loads(out)["outcome"], st.UNKNOWN)
        self.assertEqual(code, cli.EXIT_UNKNOWN)

    def test_unobservable_reads_are_sanitized_refusals(self):
        cases = ((fd.DirectorError("PIPELINE_NOT_FOUND", f"no pipeline under {SECRET}"), st.READ_FAILED),
                 (fd.DirectorError("DAG_PROVENANCE_MISMATCH", f"{SECRET}: foreign"), st.PROVENANCE_REFUSED),
                 (OSError(f"cannot open {SECRET}"), st.READ_FAILED))
        for exc, reason in cases:
            with self.subTest(reason=reason):
                result, _ = self.with_service(self.fake(None, raises=exc))
                self.assert_refused(result, "SCHEDULER_STATE_UNOBSERVABLE", reason)

    def test_untyped_summary_is_refused(self):
        result, _ = self.with_service(self.fake({"run_id": RUN, "path": SECRET}, {"status": "SUCCESS"}))
        self.assert_refused(result, "SCHEDULER_STATE_REFUSED", st.SUMMARY_NOT_TYPED)

    def test_cross_run_projection_is_identity_mismatch(self):
        summary = ts.dag(run_id=OTHER_RUN, pipeline_id=OTHER_RUN)
        result, _ = self.with_service(self.fake(summary, ts.runner_status(summary)))
        self.assert_refused(result, "SCHEDULER_IDENTITY_MISMATCH")
        summary = ts.dag()
        result, _ = self.with_service(self.fake(summary, ts.runner_status(summary, pipeline_id=OTHER_RUN)))
        self.assert_refused(result, "SCHEDULER_IDENTITY_MISMATCH")

    def test_unexpected_exception_is_generic_and_sanitized(self):
        with mock.patch.object(cli, "build_service", side_effect=RuntimeError(f"{SECRET} {WO_TEXT}")):
            self.assert_refused(invoke(self.status_argv()), "SCHEDULER_INTERNAL_ERROR")

    def test_status_is_deterministic_and_text_has_no_prose_or_paths(self):
        summary = ts.dag(("SUCCESS", "RUNNING", "QUEUED"))
        first, _ = self.with_service(self.fake(summary))
        second, _ = self.with_service(self.fake(summary))
        self.assertEqual(first, second)
        (code, text, err), _ = self.with_service(self.fake(summary), self.status_argv(RUN, "--format", "text"))
        self.assertEqual((code, err), (first[0], ""))
        self.assertIn("outcome: IN_PROGRESS", text)
        self.assertIn("node: w-01 RUNNING heartbeat=VERIFIED", text)
        self.assertIn("ADVISORY ONLY", text)
        self.assert_clean_output(text)
        self.assert_clean_output(first[1])


# ---------------------------------------------------------------------------
class StatusPathTests(_StatusRoots):
    def refused_before_service(self, argv, code):
        result, built = self.with_service(self.fake(), argv)
        self.assert_refused(result, code)
        built.assert_not_called()

    def test_invalid_run_ids_never_become_paths(self):
        for run_id in ("../escape", "fdb-../x", "plain-run", "fdb-UPPER", "fdb-a/b", "fdb-a\\b", "", "fdb-" + "x" * 61):
            with self.subTest(run_id=run_id):
                self.refused_before_service(self.status_argv(run_id), "SCHEDULER_RUN_ID_INVALID")

    def test_inadmissible_or_missing_roots(self):
        cases = (({"state": "relative/state"}, "SCHEDULER_PATH_NOT_ADMISSIBLE"),
                 ({"director": str(self.director) + os.sep + ".." + os.sep + "director"},
                  "SCHEDULER_PATH_NOT_ADMISSIBLE"),
                 ({"state": str(self.root / "absent")}, "SCHEDULER_STATE_ROOT_INVALID"),
                 ({"state": str(self.wos["a"])}, "SCHEDULER_STATE_ROOT_INVALID"),
                 ({"director": str(self.root / "absent")}, "SCHEDULER_DIRECTOR_ROOT_INVALID"))
        for kwargs, code in cases:
            with self.subTest(code=code, **kwargs):
                self.refused_before_service(self.status_argv(RUN, **kwargs), code)

    def test_unknown_run_is_refused(self):
        self.refused_before_service(self.status_argv(OTHER_RUN), "SCHEDULER_RUN_NOT_FOUND")

    def test_incomplete_runtime_is_refused(self):
        for root, name, code in ((self.state, cli.PIPELINE_STATE_NAME, "SCHEDULER_RUN_NOT_FOUND"),
                                 (self.state, cli.PIPELINE_RESULT_NAME, "SCHEDULER_RUN_NOT_FOUND"),
                                 (self.director, fd.DAG_PROVENANCE_FILENAME, "SCHEDULER_DAG_REQUEST_NOT_FOUND"),
                                 (self.director, fd.DAG_PLAN_FILENAME, "SCHEDULER_DAG_REQUEST_NOT_FOUND")):
            with self.subTest(name=name):
                target = root / RUN / name
                target.unlink()
                try:
                    self.refused_before_service(self.status_argv(), code)
                finally:
                    target.write_text("{}", encoding="utf-8")

    def test_links_anywhere_on_the_runtime_are_refused(self):
        real_kind = cli._kind
        for linked in (str(self.state), os.path.join(str(self.state), RUN),
                       os.path.join(str(self.director), RUN, fd.DAG_PLAN_FILENAME),
                       os.path.join(str(self.state), RUN, cli.PIPELINE_RESULT_NAME)):
            with self.subTest(linked=linked):
                with mock.patch.object(cli, "_kind", lambda p, linked=linked: "LINK" if p == linked
                                       else real_kind(p)):
                    self.refused_before_service(self.status_argv(), "SCHEDULER_PATH_LINK_REFUSED")

    def test_invalid_as_of_is_refused_before_any_path(self):
        argv = self.status_argv("../escape")
        argv[argv.index("--as-of") + 1] = "2026-10-30 12:00"
        self.refused_before_service(argv, "SCHEDULER_AS_OF_INVALID")


# ---------------------------------------------------------------------------
class ReadOnlyReaderTests(unittest.TestCase):
    def test_reader_exposes_only_the_two_reads(self):
        service = mock.Mock()
        reader = cli._ReadOnlyReader(service)
        for name in ("submit", "submit_blueprint", "run_blueprint", "run", "recover", "submit_and_run", "result",
                     "evidence", "decision", "_load_json", "state_root"):
            with self.subTest(name=name):
                self.assertRaises(AttributeError, getattr, reader, name)
        self.assertEqual(service.mock_calls, [])

    def test_build_service_passes_only_explicit_roots(self):
        with mock.patch.object(fd, "FabricDirectorService") as service_cls:
            cli.build_service("S", "D")
        service_cls.assert_called_once_with(state_root="S", director_root="D")


# ---------------------------------------------------------------------------
class EndToEndTests(_Base):
    """The real Director over a temporary binding (created by the real
    `submit_blueprint` in setup only) and synthetic Runner state; the CLI
    runs as a module with captured stdout/stderr."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        declaration = {"pipeline_id": "fcp9d02-e2e", "max_workers": 2, "nodes": [
            {"id": n, "worktree": str(cls.repos[n]), "work_order": str(cls.wos[n]), "provider": "claude",
             "mode": "read-only", "depends_on": []} for n in ("a", "b")]}
        cls.e2e_blueprint = cls.inputs / "e2e.json"
        cls.e2e_blueprint.write_text(json.dumps(declaration), encoding="utf-8")
        service = fd.FabricDirectorService(state_root=str(cls.state), director_root=str(cls.director))
        cls.handle = service.submit_blueprint(dcli.parse_blueprint_bytes(cls.e2e_blueprint.read_bytes()))
        run_dir = cls.state / cls.handle.pipeline_id
        run_dir.mkdir()
        (run_dir / "pipeline.json").write_text(json.dumps({
            "pipeline_id": cls.handle.pipeline_id, "manifest_sha256": cls.handle.manifest_sha256,
            "manifest": json.loads(cls.handle.plan.manifest_json)}), encoding="utf-8")
        states = ["QUEUED", "QUEUED"]
        counts = {s: states.count(s) for s in st.NATIVE_STATES}
        (run_dir / "pipeline_result.json").write_text(json.dumps({
            "schema_version": 1, "pipeline_id": cls.handle.pipeline_id, "status": "RUNNING",
            "stop_reason": ts.PROSE, "started_at_utc": "2026-10-30T11:00:00+00:00", "ended_at_utc": None,
            "workers_total": 2, "success": 0, "partial": 0, "blocked": 0, "failed": 0, "cancelled": 0,
            "interrupted": 0, "waiting_provider_quota": 0, "blocked_provider_auth": 0, "state_counts": counts,
            "max_observed_concurrency": 0,
            "workers": [{"id": "a", "state": "QUEUED", "result_path": ts.SECRET_DIR},
                        {"id": "b", "state": "QUEUED", "result_path": ts.SECRET_DIR}]}), encoding="utf-8")

    def module(self, *argv):
        return subprocess.run([sys.executable, "-m", "scripts.ai.fabric_scheduler_cli", *argv], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, timeout=120)

    def status_e2e(self, *extra):
        return self.status_argv(self.handle.pipeline_id, *extra)

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

        def read_only_git(argv, *args, **kwargs):
            if list(argv)[-2:] != ["rev-parse", "--show-toplevel"]:
                raise AssertionError("process other than git rev-parse --show-toplevel")
            return real_run(argv, *args, **kwargs)

        before = snapshot(self.root)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(builtins, "open", guarded_open))
            for target, name in ((os, "mkdir"), (os, "makedirs"), (os, "remove"), (os, "unlink"), (os, "rename"),
                                 (os, "replace"), (os, "rmdir"), (socket, "socket"), (socket, "create_connection"),
                                 (fd.FabricDirectorService, "submit_blueprint"),
                                 (fd.FabricDirectorService, "run_blueprint"), (fd.FabricDirectorService, "run"),
                                 (fd.FabricDirectorService, "recover")):
                stack.enter_context(mock.patch.object(target, name, refuse))
            stack.enter_context(mock.patch.object(subprocess, "run", read_only_git))
            yield
        self.assertEqual(snapshot(self.root), before)

    def test_real_status_in_process_reads_without_mutation(self):
        with self.no_mutation():
            code, out, err = invoke(self.status_e2e())
        envelope = json.loads(out)
        self.assertEqual((code, err), (cli.EXIT_WAITING, ""))
        self.assertEqual(envelope["outcome"], st.IN_PROGRESS)
        self.assertEqual(envelope["result"]["run_id"], self.handle.pipeline_id)
        self.assertEqual(envelope["result"]["manifest_sha256"], self.handle.manifest_sha256)
        self.assertEqual([n["status"] for n in envelope["result"]["nodes"]], [st.PENDING, st.PENDING])
        self.assert_clean_output(out)

    def test_module_status_and_plan_semantics(self):
        completed = self.module(*self.status_e2e("--format", "text"))
        self.assertEqual((completed.returncode, completed.stderr), (cli.EXIT_WAITING, ""))
        self.assertIn("outcome: IN_PROGRESS", completed.stdout)
        self.assert_clean_output(completed.stdout)
        before = snapshot(self.root)
        completed = self.module("plan", "--blueprint-file", str(self.e2e_blueprint), "--as-of", AS_OF,
                                "--node-state", "a=QUEUED", "--node-state", "b=QUEUED",
                                "--allowed-root", str(self.root))
        self.assertEqual((completed.returncode, completed.stderr), (cli.EXIT_OK, ""))
        self.assertEqual(json.loads(completed.stdout)["outcome"], pl.ADMISSIBLE)
        self.assert_clean_output(completed.stdout)
        self.assertEqual(snapshot(self.root), before)

    def test_module_refusals_have_empty_stdout_and_no_traceback(self):
        for argv, code, token in (
                (self.status_argv(OTHER_RUN), cli.EXIT_REFUSED, "SCHEDULER_RUN_NOT_FOUND"),
                (["submit", "--run-id", self.handle.pipeline_id], cli.EXIT_USAGE, "SCHEDULER_USAGE_INVALID"),
                (["plan", "--blueprint-file", str(self.inputs / "absent.json"), "--as-of", AS_OF], cli.EXIT_REFUSED,
                 "SCHEDULER_BLUEPRINT_FILE_INVALID")):
            with self.subTest(token=token):
                completed = self.module(*argv)
                self.assertEqual((completed.returncode, completed.stdout), (code, ""))
                self.assertIn(token, completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertNotIn(str(self.root), completed.stderr)

    def test_foreign_runner_state_is_unobservable(self):
        path = self.state / self.handle.pipeline_id / "pipeline.json"
        original = path.read_bytes()
        try:
            stored = json.loads(original)
            stored["manifest_sha256"] = "f" * 64
            path.write_text(json.dumps(stored), encoding="utf-8")
            self.assert_refused(invoke(self.status_e2e()), "SCHEDULER_STATE_UNOBSERVABLE", st.PROVENANCE_REFUSED)
        finally:
            path.write_bytes(original)


# ---------------------------------------------------------------------------
class AuthorityAndStaticTests(_StatusRoots):
    def test_every_authority_flag_is_false_in_both_commands(self):
        (_, status_out, _), _ = self.with_service(self.fake())
        plan_out = invoke(self.plan_argv())[1]
        for out in (status_out, plan_out):
            envelope = json.loads(out)
            for flag in ALL_FLAGS:
                self.assertIs(envelope[flag], False)
                self.assertIs(envelope["result"][flag], False)
            self.assertEqual(envelope["marker"], cli.OUTPUT_MARKER)
            self.assertEqual(envelope["authority"]["execution_authority"], "RUNNER")
            self.assertEqual(envelope["authority"]["execution_path"], "fabric_director_cli")
            self.assertIs(envelope["authority"]["launcher"], False)
        self.assertEqual(set(cli.AUTHORITY_FLAGS), set(ALL_FLAGS))

    def test_exit_codes_are_stable_and_only_proven_outcomes_are_zero(self):
        self.assertEqual((cli.EXIT_OK, cli.EXIT_REFUSED, cli.EXIT_USAGE, cli.EXIT_WAITING, cli.EXIT_UNKNOWN,
                          cli.EXIT_NOT_SUCCESSFUL), (0, 1, 2, 3, 4, 5))
        self.assertEqual(set(cli._EXIT_OF_OUTCOME["plan"]), set(pl.OUTCOMES))
        self.assertEqual(set(cli._EXIT_OF_OUTCOME["status"]), set(st.OUTCOMES) - {st.REFUSED, st.UNOBSERVABLE})
        zero = {(c, o) for c, table in cli._EXIT_OF_OUTCOME.items() for o, v in table.items() if v == 0}
        self.assertEqual(zero, {("plan", pl.ADMISSIBLE), ("status", st.SUCCESS)})
        self.assertEqual(cli._EXIT_OF_OUTCOME["status"][st.UNKNOWN], cli.EXIT_UNKNOWN)
        for envelope in ({}, {"command": "plan", "outcome": "SOMETHING"}, {"command": "submit", "outcome": "SUCCESS"},
                         {"command": "status", "outcome": st.UNOBSERVABLE}):
            self.assertEqual(cli.exit_code_for(envelope), cli.EXIT_REFUSED)

    def test_module_imports_no_process_network_or_runner_execution(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" for a in node.names} | {node.module}
        forbidden = ("subprocess", "socket", "urllib", "http", "requests", "shutil", "threading", "multiprocessing",
                     "concurrent", "runner_pipeline", "claude_runner", "claude_multiworker", "runner_providers",
                     "runner_promotion", "fabric_scheduler_gateway", "datetime", "time")
        for name in imported:
            for word in forbidden:
                self.assertNotIn(word, name.split("."))

    def test_module_calls_no_mutating_director_or_environment_api(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("submit", "submit_blueprint", "run_blueprint", "recover", "submit_and_run", "run",
                          "execute_work_order", "environ", "getenv", "write_text", "write_bytes", "mkdir",
                          "makedirs", "remove", "unlink", "rename", "replace", "system", "popen", "now", "utcnow",
                          "symlink", "chmod"):
            self.assertNotIn(forbidden, attributes)
            self.assertNotIn(forbidden, names)

    def test_engine_contracts_are_reused_not_redefined(self):
        self.assertIs(cli.pl.plan_dag, pl.plan_dag)
        self.assertIs(cli.st.observe_scheduler_state, st.observe_scheduler_state)
        self.assertIs(cli.dcli.parse_blueprint_bytes, dcli.parse_blueprint_bytes)
        source = MODULE_PATH.read_text(encoding="utf-8")
        for duplicated in ("compile_blueprint", "parse_manifest", "read_pipeline_status", "json.loads",
                           "read_text", "Lease", "Pool"):
            self.assertNotIn(duplicated, source.split('"""', 2)[2])


if __name__ == "__main__":
    unittest.main()
