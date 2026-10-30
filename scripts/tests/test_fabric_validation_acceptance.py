"""FCP-8C-01: structured acceptance / test-run evidence projection over the
Director's `DirectorRunEvidence.acceptance` record. Offline, synthetic
records shaped exactly like `runner_pipeline._apply_acceptance` output - no
Runner, Git, process, network or file is touched."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import shlex
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_validation_acceptance as va
from scripts.ai import fabric_validation_contract as vc
from scripts.ai import fabric_validation_single as vs
from scripts.tests import test_fabric_validation_single as ts

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_validation_acceptance.py"

RUN = ts.RUN
WORKER = ts.WORKER
SECRET_DIR = ts.SECRET_DIR
EMAIL = ts.EMAIL
CMD_A = "python -m unittest scripts.tests.test_fabric_validation_acceptance"
CMD_B = "python -m py_compile scripts/ai/fabric_validation_acceptance.py"
ALL_FLAGS = ts.ALL_FLAGS
POLICY = va.POLICY_RUNNER_ACCEPTANCE


def entry(command=CMD_A, **overrides) -> dict:
    """One command entry exactly as `_apply_acceptance` writes it."""
    values = {
        "command": command, "argv": shlex.split(command, posix=True), "exit_code": 0, "timed_out": False,
        "interrupted": False, "duration_seconds": 1.5, "stdout_tail": "Ran 40 tests\n\nOK",
        "stderr_tail": "", "process_evidence_path": f"{SECRET_DIR}/process/attempt-1-acceptance-1.json",
        "process_attached": True, "confirmed_dead": True, "process_confirmed_stopped": True,
    }
    values.update(overrides)
    return values


def record(*entries, decision="PASSED", **extra) -> dict:
    return {"decision": decision, "commands": list(entries) if entries else [entry()], **extra}


def evidence(**overrides) -> fd.DirectorRunEvidence:
    values = dict(acceptance=record())
    values.update(overrides)
    return ts.evidence(**values)


def project(e=None, run_id=RUN, policy=POLICY, commands=(CMD_A,)):
    return va.project_acceptance(evidence() if e is None else e, run_id, completion_policy=policy,
                                 acceptance_commands=None if commands is None else list(commands))


class PositiveTests(unittest.TestCase):
    def test_canonical_pass_is_configured_reported_passed(self):
        p = project()
        self.assertEqual(p.status, va.STATUS_PASSED)
        self.assertTrue(p.acceptance_configured and p.acceptance_reported and p.acceptance_passed)
        self.assertFalse(p.acceptance_unproven)
        self.assertIs(p.acceptance_proven, True)
        self.assertEqual(p.codes, ("TEST_COUNTS_NOT_IN_RUNNER_CONTRACT",))
        (c,) = p.commands
        self.assertTrue(c.clean)
        self.assertEqual((c.exit_code, c.exit_code_state, c.process_confirmed_stopped), (0, "ZERO", "TRUE"))

    def test_multi_command_pass_in_declared_order(self):
        e = evidence(acceptance=record(entry(CMD_A), entry(CMD_B)))
        p = project(e, commands=(CMD_A, CMD_B))
        self.assertEqual(p.status, va.STATUS_PASSED)
        self.assertEqual([c.index for c in p.commands], [1, 2])

    def test_provider_verdict_without_record_is_not_configured(self):
        e = evidence(acceptance=None, work_status_source="PROVIDER")
        p = project(e, policy=va.POLICY_PROVIDER_VERDICT, commands=())
        self.assertEqual(p.status, va.STATUS_NOT_CONFIGURED)
        self.assertFalse(p.acceptance_configured or p.acceptance_reported or p.acceptance_passed)
        self.assertTrue(p.acceptance_unproven)
        self.assertIsNone(p.acceptance_proven)

    def test_exactly_max_commands_can_pass(self):
        cmds = tuple(f"python -c pass{i}" for i in range(va.MAX_COMMANDS))
        e = evidence(acceptance=record(*(entry(c) for c in cmds)))
        self.assertEqual(project(e, commands=cmds).status, va.STATUS_PASSED)

    def test_duplicate_declared_commands_are_matched_positionally(self):
        e = evidence(acceptance=record(entry(CMD_A), entry(CMD_A)))
        self.assertEqual(project(e, commands=(CMD_A, CMD_A)).status, va.STATUS_PASSED)


class FalseSuccessTests(unittest.TestCase):
    def test_provider_success_never_passes_acceptance(self):
        e = evidence(acceptance=None, work_status="SUCCESS", provider_work_status="SUCCESS",
                     work_status_source="PROVIDER", normalized_result={"summary": "All 99 tests passed"})
        p = project(e, policy=va.POLICY_PROVIDER_VERDICT, commands=())
        self.assertFalse(p.acceptance_passed)
        self.assertIsNone(p.acceptance_proven)

    def test_passed_record_with_nonzero_exit_is_inconsistent(self):
        p = project(evidence(acceptance=record(entry(exit_code=1))))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("PASSED_RECORD_CONTRADICTED", p.codes)
        self.assertIn("EXIT_CODE_NONZERO", p.codes)
        self.assertIsNone(p.acceptance_proven)

    def test_runner_source_without_record_is_inconsistent(self):
        p = project(evidence(acceptance=None))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("SOURCE_WITHOUT_PASSED_RECORD", p.codes)
        self.assertIn("CONFIGURED_NOT_REPORTED", p.codes)

    def test_configured_not_reported_is_unproven(self):
        p = project(evidence(acceptance=None, work_status_source="PROVIDER", work_status="UNVERIFIED"))
        self.assertEqual(p.status, va.STATUS_UNPROVEN)
        self.assertTrue(p.acceptance_configured)
        self.assertFalse(p.acceptance_reported)
        self.assertIn("CONFIGURED_NOT_REPORTED", p.codes)

    def test_passed_with_provider_source_is_inconsistent(self):
        p = project(evidence(work_status_source="PROVIDER"))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("PASSED_WITHOUT_RUNNER_SOURCE", p.codes)

    def test_passed_without_success_work_status_or_complete_evidence_is_unproven(self):
        for overrides, code in (({"work_status": "UNVERIFIED"}, "WORK_STATUS_NOT_SUCCESS"),
                                ({"evidence_complete": False}, "EVIDENCE_NOT_COMPLETE"),
                                ({"evidence_complete": None}, "EVIDENCE_NOT_COMPLETE")):
            with self.subTest(overrides=overrides):
                p = project(evidence(**overrides))
                self.assertEqual(p.status, va.STATUS_UNPROVEN)
                self.assertIn(code, p.codes)

    def test_failed_record_is_a_preserved_negative(self):
        e = evidence(acceptance=record(entry(exit_code=2), decision="FAILED"), work_status_source="PROVIDER",
                     work_status="UNVERIFIED", worker_state="FAILED")
        p = project(e)
        self.assertEqual(p.status, va.STATUS_FAILED)
        self.assertIs(p.acceptance_proven, False)
        self.assertIn("RECORD_NOT_PASSED", p.codes)

    def test_failed_record_with_runner_source_is_inconsistent_and_keeps_negative_code(self):
        p = project(evidence(acceptance=record(entry(exit_code=1), decision="FAILED")))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("RECORD_NOT_PASSED", p.codes)
        self.assertIn("SOURCE_WITHOUT_PASSED_RECORD", p.codes)

    def test_interrupted_record_is_failed(self):
        e = evidence(acceptance=record(entry(interrupted=True, keyboard_interrupt=True), decision="INTERRUPTED",
                                       keyboard_interrupt=True), work_status_source="PROVIDER")
        p = project(e)
        self.assertEqual(p.status, va.STATUS_FAILED)
        self.assertIn("RECORD_INTERRUPTED", p.codes)


class ProcessProofTests(unittest.TestCase):
    def test_process_unresolved_record_is_failed(self):
        bad = entry(process_confirmed_stopped=False, confirmed_dead=False, termination_unresolved=True)
        e = evidence(acceptance=record(bad, decision="PROCESS_UNRESOLVED", termination_unresolved=True),
                     work_status_source="PROVIDER")
        p = project(e)
        self.assertEqual(p.status, va.STATUS_FAILED)
        self.assertIn("RECORD_PROCESS_UNRESOLVED", p.codes)
        self.assertIn("PROCESS_NOT_CONFIRMED_STOPPED", p.codes)

    def test_passed_with_unconfirmed_stop_is_inconsistent(self):
        p = project(evidence(acceptance=record(entry(process_confirmed_stopped=False))))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("PROCESS_NOT_CONFIRMED_STOPPED", p.codes)

    def test_passed_with_record_level_unresolved_flag_is_inconsistent(self):
        p = project(evidence(acceptance=record(termination_unresolved=True)))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("PASSED_RECORD_CONTRADICTED", p.codes)

    def test_exit_zero_with_missing_process_fields_is_unproven(self):
        bare = {"command": CMD_A, "argv": CMD_A.split(), "exit_code": 0, "timed_out": False, "interrupted": False}
        p = project(evidence(acceptance=record(bare)))
        self.assertEqual(p.status, va.STATUS_UNPROVEN)
        for code in ("EXIT_ZERO_WITHOUT_PROCESS_PROOF", "PROCESS_STOP_UNKNOWN", "PROCESS_ATTACHMENT_UNKNOWN"):
            self.assertIn(code, p.codes)

    def test_exit_zero_without_supervised_process_is_failed(self):
        e = evidence(acceptance=record(entry(process_attached=False, confirmed_dead=False), decision="FAILED"),
                     work_status_source="PROVIDER")
        p = project(e)
        self.assertEqual(p.status, va.STATUS_FAILED)
        self.assertIn("EXIT_ZERO_WITHOUT_PROCESS_PROOF", p.codes)
        self.assertIn("PROCESS_NOT_ATTACHED", p.codes)

    def test_failure_flags_contradict_a_pass(self):
        for flags in ({"error": "EMPTY_COMMAND"}, {"keyboard_interrupt": True}, {"timed_out": True},
                      {"termination_unresolved": "yes"}):
            with self.subTest(flags=flags):
                p = project(evidence(acceptance=record(entry(**flags))))
                self.assertEqual(p.status, va.STATUS_INCONSISTENT)
                self.assertFalse(p.commands[0].clean)


class AuthorizationTests(unittest.TestCase):
    def test_undeclared_command_is_flagged_without_leaking_it(self):
        p = project(evidence(acceptance=record(entry("rm -rf --no-preserve-root /"))))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("UNAUTHORIZED_COMMAND_REFERENCE", p.codes)
        self.assertEqual(p.commands[0].authorized, "FALSE")
        self.assertNotIn("no-preserve-root", va.canonical_json(p))

    def test_argv_substitution_is_detected(self):
        p = project(evidence(acceptance=record(entry(argv=["curl", "http://example.invalid"]))))
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)
        self.assertIn("COMMAND_ARGV_DIVERGES", p.codes)

    def test_extra_command_beyond_declared_is_unauthorized(self):
        p = project(evidence(acceptance=record(entry(CMD_A), entry(CMD_B))))
        self.assertIn("UNAUTHORIZED_COMMAND_REFERENCE", p.codes)
        self.assertEqual(p.status, va.STATUS_INCONSISTENT)

    def test_passed_with_fewer_or_no_commands_is_inconsistent(self):
        p = project(evidence(acceptance=record(entry(CMD_A))), commands=(CMD_A, CMD_B))
        self.assertIn("PASSED_COMMANDS_INCOMPLETE", p.codes)
        empty = project(evidence(acceptance={"decision": "PASSED", "commands": []}))
        self.assertIn("PASSED_WITHOUT_COMMANDS", empty.codes)
        self.assertEqual({p.status, empty.status}, {va.STATUS_INCONSISTENT})

    def test_unknown_configuration_never_passes(self):
        p = project(policy=None, commands=None)
        self.assertEqual(p.status, va.STATUS_UNPROVEN)
        self.assertEqual(p.configuration, va.CONFIG_UNKNOWN)
        self.assertIn("COMMAND_AUTHORIZATION_UNKNOWN", p.codes)
        self.assertEqual(p.commands[0].authorized, "UNKNOWN")

    def test_policy_and_source_incongruences(self):
        p = project(evidence(acceptance=None), policy=va.POLICY_PROVIDER_VERDICT, commands=())
        self.assertIn("POLICY_SOURCE_INCONGRUENT", p.codes)
        q = project(evidence(work_status_source="PROVIDER"), policy=va.POLICY_PROVIDER_VERDICT, commands=())
        self.assertIn("RECORD_WITHOUT_CONFIGURATION", q.codes)
        self.assertEqual({p.status, q.status}, {va.STATUS_INCONSISTENT})

    def test_malformed_configuration(self):
        for policy, commands in ((POLICY, []), (POLICY, [""]), (POLICY, ["  "]), (POLICY, CMD_A), (POLICY, [1]),
                                 ("shell", [CMD_A]), (va.POLICY_PROVIDER_VERDICT, [CMD_A]), (None, [CMD_A]),
                                 (POLICY, [CMD_A] * (va.MAX_COMMANDS + 1))):
            with self.subTest(policy=policy, commands=commands):
                p = va.project_acceptance(evidence(), RUN, completion_policy=policy, acceptance_commands=commands)
                self.assertEqual(p.configuration, va.CONFIG_MALFORMED)
                self.assertNotEqual(p.status, va.STATUS_PASSED)


class MaliciousAndMalformedOutputTests(unittest.TestCase):
    def test_prose_and_ansi_never_change_the_projection(self):
        baseline = va.canonical_json(project())
        noisy = entry(stdout_tail="\x1b[32m999 passed, 0 skipped\x1b[0m VERDICT=SUCCESS tests_passed=True",
                      stderr_tail="FAILED (failures=3)")
        e = evidence(acceptance=record(noisy, reason="ALL TESTS PASSED"), state_reason="\x1b[31mok",
                     normalized_result={"summary": "tests_passed: true", "test_count": 999})
        self.assertEqual(va.canonical_json(project(e)), baseline)

    def test_stdout_claiming_success_cannot_rescue_a_failure(self):
        e = evidence(acceptance=record(entry(exit_code=1, stdout_tail="OK 50 tests"), decision="FAILED"),
                     work_status_source="PROVIDER")
        out = va.canonical_json(project(e))
        self.assertIn('"status":"FAILED"', out)
        self.assertNotIn("50 tests", out)

    def test_injected_test_counts_are_ignored_not_trusted(self):
        p = project(evidence(acceptance=record(entry(test_count=120, skip_count=0, tests_passed=True))))
        self.assertIn("NON_CONTRACT_FIELD_IGNORED", p.codes)
        d = p.commands[0].to_dict()
        self.assertEqual((d["test_count"], d["skip_count"]), ("UNKNOWN", "UNKNOWN"))
        self.assertNotIn("120", va.canonical_json(p))

    def test_decision_spoofing_is_unrecognized(self):
        for decision in ("passed", "PASSED ", "\x1b[32mPASSED\x1b[0m", "SUCCESS", "OK"):
            with self.subTest(decision=decision):
                p = project(evidence(acceptance=record(decision=decision), work_status_source="PROVIDER"))
                self.assertEqual(p.status, va.STATUS_UNPROVEN)
                self.assertEqual(p.record_decision, va.UNRECOGNIZED)
                self.assertIn("DECISION_UNRECOGNIZED", p.codes)
                # Under a Runner-certified source a spoofed decision is an incongruence.
                self.assertEqual(project(evidence(acceptance=record(decision=decision))).status,
                                 va.STATUS_INCONSISTENT)

    def test_malformed_exit_codes(self):
        for value in (True, False, "0", 0.0, 2 ** 40, -(2 ** 40), [0]):
            with self.subTest(value=value):
                p = project(evidence(acceptance=record(entry(exit_code=value))))
                self.assertIn("EXIT_CODE_MALFORMED", p.codes)
                self.assertIsNone(p.commands[0].exit_code)
                self.assertEqual(p.status, va.STATUS_UNPROVEN)

    def test_malformed_records_and_entries(self):
        cases = ("PASSED", ["PASSED"], {"decision": 1}, {"commands": [entry()]}, {"decision": "PASSED", "commands": {}},
                 {"decision": "PASSED", "commands": [entry(), "x"]}, {"decision": "PASSED", "commands": [{1: 2}]},
                 {"decision": "PASSED", "commands": [entry(command=None)]})
        for rec in cases:
            with self.subTest(rec=rec):
                p = project(evidence(acceptance=rec))
                self.assertNotEqual(p.status, va.STATUS_PASSED)
                self.assertFalse(p.acceptance_passed)

    def test_mistyped_flags_are_malformed_not_true(self):
        p = project(evidence(acceptance=record(entry(process_confirmed_stopped=1, confirmed_dead="True"))))
        self.assertIn("COMMAND_FLAG_MALFORMED", p.codes)
        self.assertEqual(p.commands[0].process_confirmed_stopped, "MALFORMED")
        self.assertNotEqual(p.status, va.STATUS_PASSED)

    def test_commands_over_limit_are_not_projected(self):
        e = evidence(acceptance=record(*(entry() for _ in range(va.MAX_COMMANDS + 1))))
        p = project(e)
        self.assertIn("COMMANDS_LIMIT_EXCEEDED", p.codes)
        self.assertEqual(p.commands, ())
        self.assertEqual(p.status, va.STATUS_UNPROVEN)

    def test_no_identity_path_email_or_command_text_in_output(self):
        out = va.canonical_json(project())
        for needle in (RUN, WORKER, SECRET_DIR, EMAIL, "unittest", "Ran 40", "abc1234"):
            self.assertNotIn(needle, out)


class AbsenceAndIdentityTests(unittest.TestCase):
    def test_bare_evidence_is_unproven(self):
        p = project(fd.DirectorRunEvidence(run_id=RUN, pipeline_id=RUN, worker_id=WORKER))
        self.assertEqual(p.status, va.STATUS_UNPROVEN)
        self.assertIn("RECORD_ABSENT", p.codes)
        self.assertIn("WORK_STATUS_SOURCE_MISSING", p.codes)

    def test_passed_without_source_is_unproven(self):
        p = project(evidence(work_status_source=None))
        self.assertEqual(p.status, va.STATUS_UNPROVEN)
        self.assertIn("WORK_STATUS_SOURCE_MISSING", p.codes)

    def test_missing_timeout_and_interrupt_flags_are_unknown(self):
        bare = entry()
        del bare["timed_out"], bare["interrupted"]
        p = project(evidence(acceptance=record(bare)))
        self.assertIn("COMMAND_FLAG_UNKNOWN", p.codes)
        self.assertEqual(p.status, va.STATUS_UNPROVEN)

    def test_missing_exit_code_is_unknown(self):
        p = project(evidence(acceptance=record(entry(exit_code=None))))
        self.assertIn("EXIT_CODE_UNKNOWN", p.codes)
        self.assertEqual(p.commands[0].exit_code_state, "UNKNOWN")
        self.assertEqual(p.status, va.STATUS_UNPROVEN)

    def test_identity_not_attributable(self):
        for e, run_id, code in ((evidence(), "other-run", "RUN_ID_MISMATCH"),
                                (evidence(pipeline_id=None), RUN, "PIPELINE_ID_MISSING"),
                                (evidence(worker_id=""), RUN, "WORKER_ID_MISSING"),
                                (evidence(worker_id=7), RUN, "IDENTITY_MALFORMED")):
            with self.subTest(code=code):
                p = project(e, run_id=run_id)
                self.assertEqual((p.status, p.report, p.commands), (va.STATUS_UNPROVEN, va.REPORT_NOT_ATTRIBUTABLE, ()))
                self.assertIn(code, p.codes)

    def test_invalid_inputs(self):
        for e, run_id in ((ts.summary(), RUN), (dataclasses.asdict(evidence()), RUN), (None, RUN),
                          (evidence(), ""), (evidence(), None)):
            with self.subTest(e=type(e).__name__, run_id=run_id):
                p = va.project_acceptance(e, run_id, completion_policy=POLICY, acceptance_commands=[CMD_A])
                self.assertEqual(p.status, va.STATUS_INVALID_INPUT)
                self.assertFalse(p.acceptance_passed)

    def test_unhashable_source_does_not_raise(self):
        p = project(evidence(work_status_source=["RUNNER_ACCEPTANCE"]))
        self.assertIn("WORK_STATUS_SOURCE_UNRECOGNIZED", p.codes)
        self.assertNotEqual(p.status, va.STATUS_PASSED)


class ContractGuardTests(unittest.TestCase):
    def test_authority_flags_fixed_false(self):
        p = project()
        d = p.to_dict()
        for flag in ALL_FLAGS:
            self.assertIs(getattr(p, flag), False)
            self.assertIs(d[flag], False)
        with self.assertRaises(TypeError):
            dataclasses.replace(p, certified=True)
        self.assertEqual(d["marker"], va.ACCEPTANCE_MARKER)

    def test_hand_made_false_pass_is_refused(self):
        clean = project().commands
        with self.assertRaises(ValueError):
            va.AcceptanceProjection(status=va.STATUS_PASSED, configuration=va.CONFIG_UNKNOWN, report=va.REPORTED,
                                    record_decision="PASSED", commands=clean, codes=())
        with self.assertRaises(ValueError):
            va.AcceptanceProjection(status=va.STATUS_PASSED, configuration=va.CONFIGURED, report=va.REPORTED,
                                    record_decision="PASSED", commands=(), codes=())
        dirty = (dataclasses.replace(clean[0], process_confirmed_stopped="UNKNOWN"),)
        with self.assertRaises(ValueError):
            va.AcceptanceProjection(status=va.STATUS_PASSED, configuration=va.CONFIGURED, report=va.REPORTED,
                                    record_decision="PASSED", commands=dirty, codes=())

    def test_status_code_coherence_guards(self):
        with self.assertRaises(ValueError):
            va.AcceptanceProjection(status=va.STATUS_FAILED, configuration=va.CONFIGURED, report=va.REPORTED,
                                    record_decision="PASSED", commands=(), codes=())
        with self.assertRaises(ValueError):
            va.AcceptanceProjection(status=va.STATUS_INCONSISTENT, configuration=va.CONFIGURED,
                                    report=va.REPORTED, record_decision=None, commands=(), codes=())
        with self.assertRaises(ValueError):
            va.CommandEvidence(index=1, authorized="TRUE", exit_code=True, exit_code_state="ZERO", timed_out="FALSE",
                               interrupted="FALSE", process_attached="TRUE", confirmed_dead="TRUE",
                               process_confirmed_stopped="TRUE", failure_flagged=False)

    def test_canonical_json_rejects_other_types(self):
        class Sub(va.AcceptanceProjection):
            pass
        p = project()
        with self.assertRaises(TypeError):
            va.canonical_json(Sub(**{f.name: getattr(p, f.name) for f in dataclasses.fields(p)}))
        with self.assertRaises(TypeError):
            va.canonical_json(p.to_dict())


class RedundancyAndDeterminismTests(unittest.TestCase):
    def test_deterministic_and_input_not_mutated(self):
        e = evidence(acceptance=record(entry(exit_code=1), entry(exit_code=1)))
        snapshot = copy.deepcopy(e)
        first, second = va.canonical_json(project(e)), va.canonical_json(project(e))
        self.assertEqual(first, second)
        self.assertEqual(e, snapshot)

    def test_repeated_defects_yield_each_code_once(self):
        e = evidence(acceptance=record(*(entry("rm -rf .", exit_code=1) for _ in range(3))))
        p = project(e)
        self.assertEqual(len(p.codes), len(set(p.codes)))
        self.assertEqual(p.codes, va._ordered(p.codes))
        self.assertEqual(len(p.commands), 3)

    def test_codes_vocabulary_is_unique(self):
        self.assertEqual(len(va.CODES), len(set(va.CODES)))
        self.assertTrue(set(va.INCONSISTENCY_CODES) <= set(va.CODES))


class RegressionWithSingleAdapterTests(unittest.TestCase):
    def observe_single(self, evidence_overrides, shared=None):
        return ts.observe_consistent(evidence_overrides=evidence_overrides, shared=shared)

    def test_pass_agrees_with_single_adapter(self):
        o = self.observe_single({"acceptance": record()})
        self.assertIs(o.facts.acceptance_proven, True)
        self.assertIs(project().acceptance_proven, True)

    def test_projection_never_claims_more_than_single_adapter(self):
        # A-02's fixture record lacks process proof: A-02 reads only the
        # decision, this projection requires structural proof and stays UNKNOWN.
        o = ts.observe_consistent()
        p = project(ts.evidence())
        self.assertIs(o.facts.acceptance_proven, True)
        self.assertIsNone(p.acceptance_proven)
        self.assertIn("EXIT_ZERO_WITHOUT_PROCESS_PROOF", p.codes)

    def test_failed_acceptance_negative_in_both(self):
        failed = record(entry(exit_code=1), decision="FAILED")
        shared = {"work_status_source": "PROVIDER", "work_status": "UNVERIFIED", "worker_state": "FAILED"}
        o = self.observe_single({"acceptance": failed}, shared=shared)
        p = project(evidence(acceptance=failed, **shared))
        self.assertIs(o.facts.acceptance_proven, False)
        self.assertIs(p.acceptance_proven, False)

    def test_contract_vocabulary_reused(self):
        self.assertEqual(va.TRI_STATES, vc.STATES)
        self.assertEqual(va.SOURCE_RUNNER_ACCEPTANCE, fd.claude_runner.WORK_STATUS_SOURCE_RUNNER_ACCEPTANCE)
        self.assertEqual(va.POLICY_RUNNER_ACCEPTANCE, fd.claude_runner.COMPLETION_POLICY_RUNNER_ACCEPTANCE)
        self.assertIs(vs.vc, vc)


class NoIoNoAuthorityTests(unittest.TestCase):
    def test_projection_performs_no_io(self):
        def boom(*args, **kwargs):
            raise AssertionError("I/O attempted")
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(os, "system", boom), mock.patch.object(Path, "read_text", boom), \
                mock.patch.object(os, "getenv", boom):
            self.assertEqual(project().status, va.STATUS_PASSED)
            self.assertEqual(project(evidence(acceptance=record(entry("rm -rf /")))).status,
                             va.STATUS_INCONSISTENT)

    def test_module_imports_are_limited(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        allowed = {"__future__", "json", "shlex", "dataclasses", "typing", "scripts.ai", "fabric_director",
                   "fabric_validation_contract"}
        self.assertTrue(imported <= allowed, imported - allowed)

    def test_module_never_reads_prose_fields_or_private_director_readers(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("normalized_result", "state_reason", "_prior_completion_contract", "_load_json",
                          "process_supervision", "safety_reasons"):
            self.assertNotIn(forbidden, attrs)
        reads = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "get" and n.args and isinstance(n.args[0], ast.Constant)]
        read_keys = {n.args[0].value for n in reads}
        self.assertFalse(read_keys & {"stdout_tail", "stderr_tail", "reason", "duration_seconds"}, read_keys)
        for name in ("eval", "exec", "compile", "__import__"):
            self.assertNotIn(f"{name}(", source)


if __name__ == "__main__":
    unittest.main()
