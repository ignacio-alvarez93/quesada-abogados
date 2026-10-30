"""FCP-7C-01: governed routed-execution CLI - preview is read-only, dispatch
happens only through FabricDirectorService.submit_and_run on an explicit,
binding-matched host confirmation. Offline: synthetic adapters in an
injected registry and a recording Director double (plus one real-Director
integration whose PipelineRunner is replaced by a recorder)."""

from __future__ import annotations

import ast
import builtins
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as director
from scripts.ai import fabric_provider_router_cli as cli
from scripts.ai import fabric_provider_router_gateway as gw
from scripts.ai import fabric_provider_routing_policy as rp
from scripts.ai import runner_pipeline as pipeline
from scripts.tests import test_fabric_provider_router_gateway as gwt

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_provider_router_cli.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
TEST_PATH = Path(__file__).resolve()
SECRET = gwt.SECRET
CI_STEP_NAME = "FCP-7B/7C provider router gateway and governed routed CLI regression without skipped tests"

# Central contracts this WO must not touch (LF-normalized sha256).
PROTECTED_SOURCES = {
    "scripts/ai/fabric_director.py": "8a030529bfbe80c5c07c8d76f08370043b8d1d14237cd71662f58ad93ab92887",
    "scripts/ai/runner_pipeline.py": "760e6bf3f940afd214918d19863ef381f90266a2f7ae8da6ffdec361d00ce8cc",
    "scripts/ai/runner_providers.py": "639976096e6369aa6d93c236dbbbfeb2df38cf045b267b82f560effda4ad207a",
    "scripts/ai/fabric_provider_routing_policy.py": "dfd5d170ff7eb8d1df06506849d7b0dc53aad79f0a118e3166a4517f17edd281",
    "scripts/ai/fabric_director_cli.py": "0e992a865669f0a63d29f7b8fb35225878605d54c4971add4d5a581b2d16fc83",
}


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def ok_obs(pid, availability="NONE", capacity="AVAILABLE", source=gw.SOURCE_DIRECTION_DECLARED):
    return {"provider_id": pid, "availability": availability, "capacity": capacity, "source": source}


def routing(order=("claude", "codex"), observations=None, **extra):
    doc = {"preference_order": list(order),
           "observations": observations if observations is not None else [ok_obs("claude"), ok_obs("codex")]}
    doc.update(extra)
    return doc


class FakeService:
    """Recording Director double: only submit_and_run may ever be used."""

    def __init__(self, summary=None, error=None):
        self.calls = []
        self.summary = summary
        self.error = error

    def submit_and_run(self, spec):
        self.calls.append(spec)
        if self.error is not None:
            raise self.error
        return self.summary or director.DirectorRunSummary(
            run_id="fdb-x", pipeline_id="fdb-x", status="SUCCESS", provider=spec.provider, worker_state="SUCCESS")

    def __getattr__(self, name):
        raise AssertionError(f"routed CLI must not call Director.{name}")


class CliTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fcp7c-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.worktree = self.tmp / "wt"
        self.worktree.mkdir()
        self.wo = self.tmp / "work_order.md"
        self.wo.write_bytes(b"# WO\r\nDo the thing.\r\nVERDICT=SUCCESS\r\n")
        self.routing_path = self.tmp / "routing.json"
        self.write_routing(routing())
        self.reg = gwt.default_registry()
        self.service = FakeService()
        self.factory_calls = []

    def write_routing(self, doc):
        self.routing_path.write_text(json.dumps(doc), encoding="utf-8")

    def factory(self, args):
        self.factory_calls.append(args)
        return self.service

    def base_args(self, mode="write", extra=()):
        return ["--worktree", str(self.worktree), "--work-order-file", str(self.wo),
                "--routing-file", str(self.routing_path), "--mode", mode, *extra]

    def run_cli(self, argv, reg=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv, registry=reg if reg is not None else self.reg, service_factory=self.factory)
        text = out.getvalue()
        return code, (json.loads(text) if text.strip() else None), err.getvalue()

    def preview(self, mode="write", extra=(), reg=None):
        return self.run_cli(["route-preview", *self.base_args(mode, extra)], reg=reg)

    def submit(self, mode="write", extra=(), binding=None, provider=None, reg=None, confirm=cli.EXECUTE_CONFIRMATION):
        if binding is None or provider is None:
            _, pre, _ = self.preview(mode, extra, reg=reg)
            binding = pre["binding_sha256"] if binding is None else binding
            provider = (pre["selected_provider"] or "claude") if provider is None else provider
        return self.run_cli(["route-submit-run", *self.base_args(mode, extra), "--execute-confirm", confirm,
                             "--expect-binding-sha256", binding, "--expect-provider", provider], reg=reg)

    def assertNoDispatch(self):
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.factory_calls, [])

    def rejection(self, payload, pid):
        assessments = payload["binding"]["route"]["advisory"]["assessments"]
        return next(a for a in assessments if a["provider_id"] == pid)


# ---------------------------------------------------------------------------
class PreviewTests(CliTestBase):
    def test_selects_first_eligible_preference_with_reason(self):
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(p["selected_provider"], "claude")
        self.assertEqual(p["rationale"], rp.SELECTED_FIRST_ELIGIBLE_PREFERENCE)
        self.assertEqual(p["dispatch_blockers"], [])
        self.assertEqual(p["execute_confirmation"], cli.EXECUTE_CONFIRMATION)

    def test_preview_never_constructs_the_director(self):
        self.preview()
        self.preview(extra=("--allow-shell",))
        self.assertNoDispatch()

    def test_preview_is_zero_authority(self):
        _, p, _ = self.preview()
        for flag in ("certified", "authorizes_action", "execution_allowed", "auto_retry_allowed",
                     "fallback_allowed", "merging_allowed", "provider_switch_authorized", "dispatched"):
            self.assertIs(p[flag], False, flag)
        self.assertEqual(p["marker"], cli.CLI_MARKER)
        self.assertIs(p["binding"]["route"]["execution_allowed"], False)

    def test_codex_excluded_without_shell_and_reason_explained(self):
        self.write_routing(routing(order=("codex", "claude")))
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(p["selected_provider"], "claude")
        self.assertIn(rp.ADAPTER_REQUIRES_SHELL, self.rejection(p, "codex")["reasons"])
        rejected = {r["provider_id"] for r in p["binding"]["route"]["advisory"]["rejections"]}
        self.assertEqual(rejected, {"codex"})

    def test_codex_selected_only_with_explicit_allow_shell(self):
        self.write_routing(routing(order=("codex", "claude")))
        _, p, _ = self.preview(extra=("--allow-shell",))
        self.assertEqual(p["selected_provider"], "codex")
        self.assertIs(p["binding"]["execution"]["allow_shell"], True)

    def test_no_observations_fail_closed(self):
        self.write_routing(routing(observations=[]))
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertIsNone(p["selected_provider"])
        self.assertEqual(p["rationale"], rp.REFUSED_NO_ELIGIBLE_PROVIDER)
        self.assertEqual(p["dispatch_blockers"], [cli.ROUTE_NOT_SELECTED])
        self.assertIsNone(p["execute_confirmation"])
        for pid in ("claude", "codex"):
            self.assertIn(rp.AVAILABILITY_UNKNOWN, self.rejection(p, pid)["reasons"])
        issues = {(i["provider_id"], i["code"]) for i in p["binding"]["route"]["issues"]}
        self.assertIn(("claude", gw.OBSERVATION_MISSING), issues)

    def test_quota_auth_and_capacity_each_exclude(self):
        cases = ((dict(availability="QUOTA_WAIT"), rp.AVAILABILITY_QUOTA_WAIT),
                 (dict(availability="AUTH_BLOCKED"), rp.AVAILABILITY_AUTH_BLOCKED),
                 (dict(capacity="FULL"), rp.CAPACITY_FULL),
                 (dict(availability="UNKNOWN"), rp.AVAILABILITY_UNKNOWN),
                 (dict(capacity="UNKNOWN"), rp.CAPACITY_UNKNOWN))
        for kw, reason in cases:
            with self.subTest(reason=reason):
                self.write_routing(routing(order=("claude",), observations=[ok_obs("claude", **kw)]))
                code, p, _ = self.preview()
                self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
                self.assertIn(reason, self.rejection(p, "claude")["reasons"])

    def test_unknown_observation_source_degrades_to_unknown(self):
        self.write_routing(routing(order=("claude",), observations=[ok_obs("claude", source="RUNNER_CERTIFIED")]))
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        issues = {i["code"] for i in p["binding"]["route"]["issues"]}
        self.assertIn(gw.OBSERVATION_MALFORMED, issues)

    def test_probe_unavailable_is_not_eligible(self):
        reg = gwt.registry(("claude", {"available": False}), ("codex", {"shell_mandatory": True}))
        code, p, _ = self.preview(reg=reg)
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertIn(rp.PROBE_UNAVAILABLE, self.rejection(p, "claude")["reasons"])

    def test_unregistered_adapter_contributes_no_facts(self):
        self.write_routing(routing(order=("gemini",), observations=[ok_obs("gemini")]))
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertIn(rp.NO_FACTS, self.rejection(p, "gemini")["reasons"])

    def test_provenance_reported(self):
        self.write_routing(routing(observations=[ok_obs("claude", source=gw.SOURCE_RUNNER_STATE_OBSERVED),
                                                 ok_obs("codex")]))
        _, p, _ = self.preview()
        self.assertEqual(p["binding"]["route"]["provenance"], [
            {"provider_id": "claude", "source": gw.SOURCE_RUNNER_STATE_OBSERVED},
            {"provider_id": "codex", "source": gw.SOURCE_DIRECTION_DECLARED}])

    def test_pin_selected_and_never_substituted(self):
        self.write_routing(routing(pinned_provider="codex"))
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["rationale"], rp.REFUSED_PINNED_PROVIDER_INELIGIBLE)
        _, p2, _ = self.preview(extra=("--allow-shell",))
        self.assertEqual((p2["selected_provider"], p2["rationale"]), ("codex", rp.SELECTED_PINNED_PROVIDER))

    def test_pin_owner_conflict_refused_by_gateway(self):
        self.write_routing(routing(pinned_provider="claude", owner_provider="codex", provider_locked=True))
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["rationale"], gw.GATEWAY_REFUSED)
        self.assertIn(gw.PIN_OWNER_CONFLICT, p["binding"]["route"]["gateway_reasons"])

    def test_invalid_request_refused_before_adapters(self):
        cases = ((("--capability", "TELEPATHY"), rp.CAPABILITY_UNKNOWN, "write"),
                 (("--capability", "SHELL"), rp.SHELL_REQUESTED_WITHOUT_ALLOW_SHELL, "write"),
                 (("--allow-shell",), rp.ALLOW_SHELL_REQUIRES_WRITE_MODE, "read-only"))
        for extra, reason, mode in cases:
            with self.subTest(reason=reason):
                code, p, _ = self.preview(mode=mode, extra=extra)
                self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
                self.assertEqual(p["rationale"], rp.REFUSED_INVALID_REQUEST)
                self.assertIn(reason, p["binding"]["route"]["advisory"]["request_reasons"])
                self.assertEqual(p["binding"]["route"]["facts"], [])

    def test_prior_attempt_preview_is_informational_and_blocked(self):
        self.write_routing(routing(pinned_provider="claude", owner_provider="claude", prior_attempt_executed=True))
        code, p, _ = self.preview()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(p["rationale"], rp.SELECTED_LOCKED_PROVIDER)
        self.assertEqual(p["dispatch_blockers"], [cli.PRIOR_ATTEMPT_REQUIRES_GOVERNED_RECOVERY])
        self.assertIsNone(p["execute_confirmation"])

    def test_binding_is_deterministic(self):
        _, a, _ = self.preview()
        _, b, _ = self.preview()
        self.assertEqual(a, b)
        self.assertRegex(a["binding_sha256"], r"^[0-9a-f]{64}$")
        expected = hashlib.sha256(cli._canonical(a["binding"]).encode("ascii")).hexdigest()
        self.assertEqual(a["binding_sha256"], expected)

    def test_binding_covers_work_order_bytes(self):
        _, a, _ = self.preview()
        self.assertEqual(a["binding"]["work_order_sha256"], hashlib.sha256(self.wo.read_bytes()).hexdigest())
        self.wo.write_bytes(self.wo.read_bytes().replace(b"\r\n", b"\n"))
        _, b, _ = self.preview()
        self.assertNotEqual(a["binding_sha256"], b["binding_sha256"])

    def test_binding_covers_every_execution_flag_and_routing_input(self):
        _, base, _ = self.preview()
        variants = {
            "authorize": ("--authorize-path", "scripts/**"), "capability": ("--capability", "TEST_EXECUTION"),
            "model": ("--model", "m1"), "checkpoint": ("--checkpoint-policy", "ON_SUCCESS"),
            "timeout": ("--timeout-seconds", "60"), "metadata": ("--metadata", "k=v"),
            "acceptance": ("--acceptance-command", "python -V"),
        }
        for name, extra in variants.items():
            with self.subTest(name=name):
                _, p, _ = self.preview(extra=extra)
                self.assertNotEqual(p["binding_sha256"], base["binding_sha256"])
        _, ro, _ = self.preview(mode="read-only")
        self.assertNotEqual(ro["binding_sha256"], base["binding_sha256"])
        self.write_routing(routing(observations=[ok_obs("claude"), ok_obs("codex", capacity="FULL")]))
        _, obs_changed, _ = self.preview()
        self.assertEqual(obs_changed["selected_provider"], "claude")
        self.assertNotEqual(obs_changed["binding_sha256"], base["binding_sha256"])

    def test_preview_performs_no_process_or_write_io(self):
        before = sorted(p.name for p in self.tmp.rglob("*"))
        guards = [mock.patch.object(subprocess, "run", side_effect=AssertionError("run")),
                  mock.patch.object(subprocess, "Popen", side_effect=AssertionError("Popen")),
                  mock.patch.object(os, "makedirs", side_effect=AssertionError("makedirs")),
                  mock.patch.object(os, "replace", side_effect=AssertionError("replace")),
                  mock.patch.object(Path, "write_text", side_effect=AssertionError("write_text")),
                  mock.patch.object(Path, "write_bytes", side_effect=AssertionError("write_bytes")),
                  mock.patch.object(Path, "mkdir", side_effect=AssertionError("mkdir"))]
        with contextlib.ExitStack() as stack:
            for g in guards:
                stack.enter_context(g)
            code, _, _ = self.preview()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(sorted(p.name for p in self.tmp.rglob("*")), before)
        self.assertEqual(list(self.worktree.iterdir()), [])

    def test_secrets_from_adapters_never_echoed(self):
        _, p, err = self.preview()
        self.assertNotIn(SECRET, json.dumps(p))
        self.assertNotIn(SECRET, err)


# ---------------------------------------------------------------------------
class InputTests(CliTestBase):
    def assertInputError(self, code_name, argv=None):
        code, payload, err = self.run_cli(argv or ["route-preview", *self.base_args()])
        self.assertEqual(code, cli.EXIT_INPUT_ERROR)
        self.assertIsNone(payload)
        self.assertIn(code_name, err)
        self.assertNoDispatch()

    def test_mode_is_required(self):
        argv = ["route-preview", "--worktree", str(self.worktree), "--work-order-file", str(self.wo),
                "--routing-file", str(self.routing_path)]
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main(argv, registry=self.reg, service_factory=self.factory)
        self.assertEqual(ctx.exception.code, 2)

    def test_routing_schema_violations(self):
        cases = {
            "unknown key": routing(cost=1),
            "missing observations": {"preference_order": ["claude"]},
            "missing order": {"observations": []},
            "flag not bool": routing(provider_locked="yes"),
            "pin not str": routing(pinned_provider=1),
            "order not list": {"preference_order": "claude", "observations": []},
            "order item not str": {"preference_order": [1], "observations": []},
            "observation extra key": routing(observations=[{**ok_obs("claude"), "token": SECRET}]),
            "observation missing key": routing(observations=[{"provider_id": "claude"}]),
            "observation not str": routing(observations=[{**ok_obs("claude"), "capacity": 3}]),
            "not object": ["claude"],
            "null pin": routing(pinned_provider=None),
        }
        for name, doc in cases.items():
            with self.subTest(name=name):
                self.write_routing(doc)
                self.assertInputError("ROUTING_SCHEMA_INVALID")

    def test_routing_json_hardening(self):
        cases = {
            "ROUTING_JSON_DUPLICATE_KEY": b'{"preference_order": [], "preference_order": [], "observations": []}',
            "ROUTING_JSON_INVALID": b'{"preference_order": [NaN], "observations": []}',
            "ROUTING_FILE_NOT_UTF8": b"\xef\xbb\xbf{}",
        }
        for code_name, data in cases.items():
            with self.subTest(code=code_name):
                self.routing_path.write_bytes(data)
                self.assertInputError(code_name)
        self.routing_path.write_bytes(b" " * (cli.ROUTING_FILE_MAX_BYTES + 1))
        self.assertInputError("ROUTING_FILE_TOO_LARGE")

    def test_routing_file_must_be_regular_file(self):
        self.routing_path.unlink()
        self.routing_path.mkdir()
        self.assertInputError("ROUTING_FILE_UNREADABLE")

    def test_work_order_must_be_utf8_and_non_empty(self):
        self.wo.write_bytes(b"\xff\xfe bad")
        self.assertInputError("WORK_ORDER_FILE_NOT_UTF8")
        self.wo.write_bytes(b"  \n")
        self.assertInputError("WORK_ORDER_EMPTY")
        self.wo.unlink()
        self.assertInputError("WORK_ORDER_FILE_UNREADABLE")

    def test_reserved_metadata_keys_refused(self):
        for key in cli.ROUTE_METADATA_KEYS:
            with self.subTest(key=key):
                self.assertInputError("ROUTE_METADATA_RESERVED",
                                      ["route-preview", *self.base_args(extra=("--metadata", f"{key}=x"))])

    def test_input_errors_never_echo_file_content(self):
        self.routing_path.write_text(json.dumps(routing(observations=[{**ok_obs("claude"), SECRET: 1}])),
                                     encoding="utf-8")
        _, _, err = self.run_cli(["route-preview", *self.base_args()])
        self.assertNotIn(SECRET, err)

    def test_submit_input_error_dispatches_nothing(self):
        self.write_routing(routing(cost=1))
        code, _, _ = self.run_cli(["route-submit-run", *self.base_args(), "--execute-confirm",
                                   cli.EXECUTE_CONFIRMATION, "--expect-binding-sha256", "0" * 64,
                                   "--expect-provider", "claude"])
        self.assertEqual(code, cli.EXIT_INPUT_ERROR)
        self.assertNoDispatch()


# ---------------------------------------------------------------------------
class SubmitRunTests(CliTestBase):
    def test_confirmed_submit_dispatches_exactly_once_via_submit_and_run(self):
        code, p, _ = self.submit()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIs(p["dispatched"], True)
        self.assertEqual(len(self.service.calls), 1)
        self.assertEqual(len(self.factory_calls), 1)
        spec = self.service.calls[0]
        self.assertIsInstance(spec, director.DirectorWorkOrderSpec)
        self.assertEqual(spec.provider, "claude")
        self.assertEqual(p["summary"]["status"], "SUCCESS")

    def test_flags_propagated_exactly(self):
        extra = ("--allow-shell", "--capability", "TEST_EXECUTION", "--authorize-path", "scripts/ai/x.py",
                 "--authorize-path", "scripts/tests/**", "--model", "m-explicit", "--checkpoint-policy",
                 "ON_SUCCESS", "--timeout-seconds", "900", "--completion-policy", "runner_acceptance",
                 "--acceptance-command", "python -m unittest -q", "--metadata", "wo=FCP-7C-01")
        code, _, _ = self.submit(extra=extra)
        self.assertEqual(code, cli.EXIT_OK)
        spec = self.service.calls[0]
        self.assertEqual((spec.mode, spec.allow_shell), ("write", True))
        self.assertEqual(spec.required_capabilities, ["TEST_EXECUTION"])
        self.assertEqual(spec.authorize_paths, ["scripts/ai/x.py", "scripts/tests/**"])
        self.assertEqual((spec.model, spec.checkpoint_policy, spec.timeout_seconds),
                         ("m-explicit", "ON_SUCCESS", 900))
        self.assertEqual(spec.completion_policy, "runner_acceptance")
        self.assertEqual(spec.acceptance_commands, ["python -m unittest -q"])
        self.assertEqual(spec.worktree, str(self.worktree))

    def test_omitted_flags_use_director_defaults_never_widened(self):
        self.submit()
        spec = self.service.calls[0]
        default = director.DirectorWorkOrderSpec(worktree="w", work_order_text="t")
        self.assertIs(spec.allow_shell, False)
        self.assertEqual((spec.authorize_paths, spec.required_capabilities), ([], []))
        for name in ("model", "checkpoint_policy", "timeout_seconds", "completion_policy"):
            self.assertEqual(getattr(spec, name), getattr(default, name), name)

    def test_read_only_mode_propagated(self):
        self.submit(mode="read-only")
        self.assertEqual(self.service.calls[0].mode, "read-only")
        self.assertIs(self.service.calls[0].allow_shell, False)

    def test_work_order_text_dispatched_verbatim(self):
        self.submit()
        self.assertEqual(self.service.calls[0].work_order_text.encode("utf-8"), self.wo.read_bytes())

    def test_metadata_preserved_plus_reserved_provenance(self):
        _, pre, _ = self.preview(extra=("--metadata", "a=1", "--metadata", "b=two=2"))
        self.submit(extra=("--metadata", "a=1", "--metadata", "b=two=2"))
        md = self.service.calls[0].metadata
        self.assertEqual({k: md[k] for k in ("a", "b")}, {"a": "1", "b": "two=2"})
        self.assertEqual(md[cli.META_BINDING], pre["binding_sha256"])
        self.assertEqual(md[cli.META_RATIONALE], rp.SELECTED_FIRST_ELIGIBLE_PREFERENCE)
        self.assertEqual(md[cli.META_SELECTED], "claude")
        self.assertEqual(set(md), {"a", "b", *cli.ROUTE_METADATA_KEYS})

    def test_codex_dispatch_keeps_host_shell_and_scope(self):
        self.write_routing(routing(order=("codex", "claude")))
        self.submit(extra=("--allow-shell", "--authorize-path", "only/this.py"))
        spec = self.service.calls[0]
        self.assertEqual((spec.provider, spec.allow_shell, spec.authorize_paths), ("codex", True, ["only/this.py"]))

    def test_selection_never_enables_shell(self):
        self.write_routing(routing(order=("codex", "claude")))
        self.submit()
        spec = self.service.calls[0]
        self.assertEqual((spec.provider, spec.allow_shell), ("claude", False))
        self.assertNotIn("SHELL", spec.required_capabilities)

    def test_confirmation_flag_required_and_exact(self):
        _, pre, _ = self.preview()
        common = ["route-submit-run", *self.base_args(), "--expect-binding-sha256", pre["binding_sha256"],
                  "--expect-provider", "claude"]
        for argv in (common, common + ["--execute-confirm", "RUN_BLUEPRINT"],
                     common + ["--execute-confirm", "run_routed_work_order"], common + ["--execute-confirm", "yes"]):
            with self.subTest(argv=argv[-1]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                    cli.main(argv, registry=self.reg, service_factory=self.factory)
                self.assertEqual(ctx.exception.code, 2)
        self.assertNoDispatch()

    def test_expectations_required(self):
        base = ["route-submit-run", *self.base_args(), "--execute-confirm", cli.EXECUTE_CONFIRMATION]
        for argv in (base + ["--expect-provider", "claude"], base + ["--expect-binding-sha256", "0" * 64]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main(argv, registry=self.reg, service_factory=self.factory)
        self.assertNoDispatch()

    def test_wrong_binding_refused(self):
        code, p, _ = self.submit(binding="0" * 64, provider="claude")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["refusal_codes"], [cli.BINDING_MISMATCH])
        self.assertIs(p["dispatched"], False)
        self.assertNoDispatch()

    def test_wrong_expected_provider_refused(self):
        _, pre, _ = self.preview()
        code, p, _ = self.submit(binding=pre["binding_sha256"], provider="codex")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["refusal_codes"], [cli.EXPECTED_PROVIDER_MISMATCH])
        self.assertNoDispatch()

    def test_handler_rechecks_confirmation_token(self):
        proposal_args = cli.build_arg_parser().parse_args(["route-submit-run", *self.base_args(), "--execute-confirm",
                                                           cli.EXECUTE_CONFIRMATION, "--expect-binding-sha256", "x",
                                                           "--expect-provider", "claude"])
        proposal = cli.build_proposal(proposal_args, registry=self.reg)
        proposal_args.execute_confirm = "RUN_RECOVERY"
        proposal_args.expect_binding_sha256 = proposal.binding_sha256
        self.assertEqual(cli.confirmation_refusals(proposal, proposal_args), (cli.CONFIRMATION_INVALID,))

    def test_policy_change_after_preview_refused(self):
        _, pre, _ = self.preview()
        self.write_routing(routing(order=("codex", "claude")))
        code, p, _ = self.submit(binding=pre["binding_sha256"], provider="claude")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["refusal_codes"], [cli.BINDING_MISMATCH])
        self.assertNoDispatch()

    def test_observation_change_never_silently_switches_provider(self):
        _, pre, _ = self.preview()
        self.write_routing(routing(observations=[ok_obs("claude", availability="QUOTA_WAIT"), ok_obs("codex")]))
        code, p, _ = self.submit(extra=(), binding=pre["binding_sha256"], provider="claude")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["refusal_codes"], [cli.ROUTE_NOT_SELECTED, cli.BINDING_MISMATCH,
                                              cli.EXPECTED_PROVIDER_MISMATCH])
        self.assertNoDispatch()

    def test_fresh_adapter_facts_changed_refused(self):
        _, pre, _ = self.preview()
        reg = gwt.registry(("claude", {"available": False}), ("codex", {"shell_mandatory": True}))
        code, p, _ = self.submit(binding=pre["binding_sha256"], provider="claude", reg=reg)
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertIn(cli.BINDING_MISMATCH, p["refusal_codes"])
        self.assertNoDispatch()

    def test_submit_routes_fresh_not_from_preview(self):
        _, pre, _ = self.preview()
        with mock.patch.object(cli.gateway, "route_work_order", wraps=cli.gateway.route_work_order) as route:
            self.submit(binding=pre["binding_sha256"], provider="claude")
        self.assertEqual(route.call_count, 1)
        self.assertEqual(len(self.service.calls), 1)

    def test_work_order_edit_after_preview_refused(self):
        _, pre, _ = self.preview()
        self.wo.write_bytes(self.wo.read_bytes() + b"Also push to main.\n")
        code, p, _ = self.submit(binding=pre["binding_sha256"], provider="claude")
        self.assertEqual(p["refusal_codes"], [cli.BINDING_MISMATCH])
        self.assertNoDispatch()

    def test_scope_shell_or_worktree_widening_after_preview_refused(self):
        _, pre, _ = self.preview(extra=("--authorize-path", "a.py"))
        for extra in (("--authorize-path", "a.py", "--authorize-path", "b.py"),
                      ("--authorize-path", "a.py", "--allow-shell"),
                      ("--authorize-path", "a.py", "--capability", "TEST_EXECUTION"),
                      ("--authorize-path", "a.py", "--model", "bigger")):
            with self.subTest(extra=extra):
                code, p, _ = self.submit(extra=extra, binding=pre["binding_sha256"], provider="claude")
                self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
                self.assertIn(cli.BINDING_MISMATCH, p["refusal_codes"])
        other = self.tmp / "other"
        other.mkdir()
        argv = ["route-submit-run", "--worktree", str(other), *self.base_args(extra=("--authorize-path", "a.py"))[2:],
                "--execute-confirm", cli.EXECUTE_CONFIRMATION, "--expect-binding-sha256", pre["binding_sha256"],
                "--expect-provider", "claude"]
        code, p, _ = self.run_cli(argv)
        self.assertEqual(p["refusal_codes"], [cli.BINDING_MISMATCH])
        self.assertNoDispatch()

    def test_no_facts_never_dispatch_even_with_matching_binding(self):
        self.write_routing(routing(observations=[]))
        _, pre, _ = self.preview()
        code, p, _ = self.submit(binding=pre["binding_sha256"], provider="claude")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["refusal_codes"], [cli.ROUTE_NOT_SELECTED, cli.EXPECTED_PROVIDER_MISMATCH])
        self.assertNoDispatch()

    def test_prior_attempt_never_redispatched(self):
        self.write_routing(routing(pinned_provider="claude", owner_provider="claude", prior_attempt_executed=True))
        _, pre, _ = self.preview()
        code, p, _ = self.submit(binding=pre["binding_sha256"], provider="claude")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["refusal_codes"], [cli.PRIOR_ATTEMPT_REQUIRES_GOVERNED_RECOVERY])
        self.assertNoDispatch()

    def test_prior_attempt_cannot_switch_to_other_provider(self):
        self.write_routing(routing(pinned_provider="codex", owner_provider="claude", prior_attempt_executed=True))
        _, pre, _ = self.preview(extra=("--allow-shell",))
        code, p, _ = self.submit(extra=("--allow-shell",), binding=pre["binding_sha256"], provider="codex")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertIn(cli.ROUTE_NOT_SELECTED, p["refusal_codes"])
        self.assertIn(cli.PRIOR_ATTEMPT_REQUIRES_GOVERNED_RECOVERY, p["refusal_codes"])
        self.assertNoDispatch()

    def test_provider_lock_without_prior_attempt_dispatches_only_the_owner(self):
        self.write_routing(routing(owner_provider="claude", provider_locked=True))
        code, p, _ = self.submit()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(p["rationale"], rp.SELECTED_LOCKED_PROVIDER)
        self.assertEqual(self.service.calls[0].provider, "claude")

    def test_lock_owner_ineligible_never_substituted(self):
        self.write_routing(routing(owner_provider="claude", provider_locked=True,
                                   observations=[ok_obs("claude", capacity="FULL"), ok_obs("codex")]))
        code, p, _ = self.submit(extra=("--allow-shell",), provider="codex")
        self.assertEqual(code, cli.EXIT_ROUTE_REFUSED)
        self.assertEqual(p["rationale"], rp.REFUSED_LOCKED_PROVIDER_INELIGIBLE)
        self.assertNoDispatch()

    def test_runner_failure_reported_verbatim_without_retry(self):
        self.service.summary = director.DirectorRunSummary(run_id="fdb-f", pipeline_id="fdb-f", status="FAILED",
                                                           worker_state="FAILED", provider="claude")
        code, p, _ = self.submit()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual((p["summary"]["status"], p["summary"]["worker_state"]), ("FAILED", "FAILED"))
        self.assertEqual(len(self.service.calls), 1)
        self.assertIs(p["auto_retry_allowed"], False)
        self.assertIs(p["fallback_allowed"], False)

    def test_director_error_surfaces_once_without_retry_or_fallback(self):
        self.service.error = director.DirectorError("INVALID_WORKTREE", "not a git worktree")
        code, p, err = self.submit()
        self.assertEqual(code, cli.EXIT_INPUT_ERROR)
        self.assertIsNone(p)
        self.assertIn("INVALID_WORKTREE", err)
        self.assertEqual([s.provider for s in self.service.calls], ["claude"])

    def test_pipeline_refusal_exit_code(self):
        self.service.error = pipeline.PipelineError("LEASE_REFUSED", "worktree leased")
        code, _, err = self.submit()
        self.assertEqual(code, pipeline.EXIT_PIPELINE_REFUSED)
        self.assertIn("LEASE_REFUSED", err)
        self.assertEqual(len(self.service.calls), 1)

    def test_refusal_payload_is_structured_and_zero_authority(self):
        _, p, _ = self.submit(binding="f" * 64, provider="nobody")
        for key in ("schema", "rationale", "binding_sha256", "expected_binding_sha256", "refusal_codes", "binding"):
            self.assertIn(key, p)
        self.assertEqual(p["schema"], cli.SUBMIT_SCHEMA)
        for flag in ("certified", "authorizes_action", "auto_retry_allowed", "fallback_allowed",
                     "provider_switch_authorized", "dispatched"):
            self.assertIs(p[flag], False, flag)
        self.assertEqual(p["refusal_codes"], sorted(p["refusal_codes"], key=cli.DISPATCH_REFUSALS.index))

    def test_global_service_args_forwarded_to_director_factory(self):
        state = str(self.tmp / "state")
        _, pre, _ = self.preview()
        argv = ["--state-root", state, "--no-factory-ledger", "route-submit-run", *self.base_args(),
                "--execute-confirm", cli.EXECUTE_CONFIRMATION, "--expect-binding-sha256", pre["binding_sha256"],
                "--expect-provider", "claude"]
        code, _, _ = self.run_cli(argv)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(self.factory_calls[0].state_root, state)
        self.assertIs(self.factory_calls[0].no_factory_ledger, True)

    def test_default_factory_is_director_cli_service_builder(self):
        _, pre, _ = self.preview()
        built = []

        def fake_build(args):
            built.append(args)
            return self.service
        with mock.patch.object(cli.director_cli, "_build_service", side_effect=fake_build), \
                contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["route-submit-run", *self.base_args(), "--execute-confirm", cli.EXECUTE_CONFIRMATION,
                             "--expect-binding-sha256", pre["binding_sha256"], "--expect-provider", "claude"],
                            registry=self.reg)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(len(built), 1)
        self.assertEqual(len(self.service.calls), 1)


# ---------------------------------------------------------------------------
class DirectorIntegrationTests(CliTestBase):
    """Real FabricDirectorService.submit_and_run down to PipelineRunner,
    whose construction is recorded instead of executed."""

    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", str(self.worktree)], check=True, capture_output=True)
        self.runners = []
        test = self

        class RecordingRunner:
            def __init__(self, manifest, state_root, **kwargs):
                test.runners.append((manifest, Path(state_root), kwargs))

            def run(self):
                return None

        self.real = director.FabricDirectorService(
            state_root=self.tmp / "state", factory_root=self.tmp / "factory", director_root=self.tmp / "director",
            self_worktree=str(self.tmp / "self"))
        self.real.result = lambda run_id: director.DirectorRunSummary(run_id=run_id, pipeline_id=run_id,
                                                                     status="SUCCESS")
        patcher = mock.patch.object(director.pipeline, "PipelineRunner", RecordingRunner)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.exec_guard = mock.patch.object(director.claude_runner, "execute_work_order",
                                            side_effect=AssertionError("direct execution"))
        self.exec_guard.start()
        self.addCleanup(self.exec_guard.stop)

    def factory(self, args):
        self.factory_calls.append(args)
        return self.real

    def test_dispatch_descends_to_one_pipeline_runner_with_exact_manifest(self):
        code, p, err = self.submit(extra=("--authorize-path", "scripts/ai/x.py", "--metadata", "k=v",
                                          "--checkpoint-policy", "ON_SUCCESS"))
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertEqual(len(self.runners), 1)
        manifest, state_root, _ = self.runners[0]
        self.assertEqual(state_root, self.tmp / "state")
        self.assertEqual(len(manifest.workers), 1)
        worker = manifest.workers[0]
        self.assertEqual((worker.provider, worker.mode, worker.allow_shell), ("claude", "write", False))
        self.assertEqual(list(worker.authorize_path), ["scripts/ai/x.py"])
        self.assertEqual(list(worker.fallback_providers), [])
        self.assertEqual(worker.metadata["k"], "v")
        self.assertEqual(worker.metadata[cli.META_BINDING], p["binding_sha256"])
        self.assertEqual(worker.checkpoint_policy, "ON_SUCCESS")

    def test_dispatched_work_order_persisted_by_director_only(self):
        self.submit()
        (run_dir,) = list((self.tmp / "director").iterdir())
        persisted = (run_dir / "work_order.md").read_bytes()
        self.assertEqual(persisted, self.wo.read_bytes())
        self.assertEqual(sorted(p.name for p in self.worktree.iterdir()), [".git"])

    def test_refusal_creates_no_director_run(self):
        self.submit(binding="0" * 64, provider="claude")
        self.assertEqual(self.runners, [])
        self.assertFalse((self.tmp / "director").exists())


# ---------------------------------------------------------------------------
class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.code = self.source.split('"""', 2)[-1]
        self.tree = ast.parse(self.source)

    def test_imports_are_limited_to_gateway_and_director_cli(self):
        imported = set()
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                imported |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imported |= {f"{n.module}.{a.name}" for a in n.names}
        self.assertEqual(imported, {
            "__future__.annotations", "argparse", "dataclasses", "hashlib", "json", "sys", "pathlib.Path",
            "typing.Callable", "typing.Optional", "scripts.ai.fabric_director_cli",
            "scripts.ai.fabric_provider_router_gateway",
        })

    def test_no_second_execution_path(self):
        for token in ("execute_work_order", "PipelineRunner", "parse_manifest", "load_manifest", "subprocess",
                      "os.system", "Popen", "run_process", "run_preflight", "build_invocation", "fallback",
                      ".recover(", "run_blueprint", "eval(", "exec(", "importlib", "environ", "git "):
            self.assertNotIn(token, self.code.replace('"fallback_allowed": False', ""), token)
        self.assertIsNone(re.search(r"\.submit\(|\.run\(", self.code))

    def test_single_dispatch_call_site(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in {"submit_and_run", "submit", "run", "recover", "submit_blueprint"}]
        self.assertEqual([c.func.attr for c in calls], ["submit_and_run"])

    def test_provider_never_chosen_outside_gateway(self):
        self.assertEqual(len(re.findall(r"route_work_order\(", self.code)), 1)
        self.assertIn('"provider": proposal.selected_provider', self.code)
        self.assertNotIn("preference_order[0]", self.code)

    def test_no_secrets_or_personal_paths(self):
        for token in ("C:\\", "C:/", "/home/", "/Users/", "Desktop", "token", "api_key", "password", "sk-"):
            self.assertNotIn(token, self.source, token)

    def test_protected_central_contracts_untouched(self):
        for rel, digest in PROTECTED_SOURCES.items():
            self.assertEqual(_lf_sha256(REPO_ROOT / rel), digest, rel)

    def test_vocabularies(self):
        self.assertEqual(cli.EXECUTE_CONFIRMATION, "RUN_ROUTED_WORK_ORDER")
        self.assertEqual(len(set(cli.DISPATCH_REFUSALS)), len(cli.DISPATCH_REFUSALS))
        self.assertTrue(all(k.startswith("fcp7c_route_") for k in cli.ROUTE_METADATA_KEYS))
        self.assertNotEqual(cli.EXIT_ROUTE_REFUSED, pipeline.EXIT_PIPELINE_REFUSED)
        parsed = cli.parse_routing_bytes(cli.ROUTING_JSON_EXAMPLE.encode("utf-8"))
        self.assertEqual(parsed["config"].preference_order, ("claude", "codex"))

    def test_this_suite_skips_nothing(self):
        source = TEST_PATH.read_text(encoding="utf-8")
        for token in ("skip" + "Test", "skip" + "If", "skip" + "Unless", "expected" + "Failure", "unittest." + "skip"):
            self.assertNotIn(token, source)

    def test_open_is_never_used_for_writing(self):
        with mock.patch.object(builtins, "open", side_effect=AssertionError("open")):
            parsed = cli.parse_routing_bytes(json.dumps(routing()).encode("utf-8"))
        self.assertEqual(len(parsed["observations"]), 2)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.lines = self.text.split("\n")

    def _job_steps(self, job):
        block = re.search(rf"(?ms)^  {job}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.text).group(1)
        return re.findall(r"(?m)^      - name: (.+)$", block)

    def test_nine_jobs_read_only(self):
        jobs = re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: ", self.text)
        self.assertEqual(len(jobs), 9)
        self.assertEqual(jobs[0], "fabric-regression")
        self.assertEqual(self.text.count("permissions:"), 1)
        self.assertIn("permissions:\n  contents: read\n", self.text)

    def test_step_in_fabric_regression_before_fcp7a(self):
        steps = self._job_steps("fabric-regression")
        self.assertEqual(steps.count(CI_STEP_NAME), 1)
        idx = steps.index(CI_STEP_NAME)
        self.assertEqual(steps[idx - 1], "Environment")
        self.assertEqual(steps[idx + 1], "FCP-7A-01 provider routing pure policy regression without skipped tests")

    def test_step_gates_both_suites_with_counts_and_zero_skips(self):
        start = self.lines.index(f"      - name: {CI_STEP_NAME}")
        step = "\n".join(self.lines[start:start + 3])
        self.assertEqual(re.findall(r"scripts\.tests\.(\w+)", step),
                         ["test_fabric_provider_router_gateway", "test_fabric_provider_router_cli"])
        for gate in ("r.wasSuccessful()", "min(c) >= 45", "not r.skipped", "not r.expected" + "Failures",
                     "not r.unexpectedSuccesses"):
            self.assertIn(gate, step)
        self.assertEqual(self.text.count("test_fabric_provider_router_cli"), 1)
        self.assertEqual(self.text.count("test_fabric_provider_router_gateway"), 1)

    def test_prior_stage_gates_preserved(self):
        for gate in ("r.testsRun >= 45 and not r.skipped", "r.testsRun >= 35 and not r.skipped",
                     "r.testsRun >= 30 and not r.skipped", "r.testsRun >= 122 and not r.skipped"):
            self.assertIn(gate, self.text)


if __name__ == "__main__":
    unittest.main()
