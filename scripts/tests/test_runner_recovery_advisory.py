"""FCP-6B-01: Recovery Decision Intelligence V1 - advisory-only composition
over FCP-6A-01 diagnostics.

Every diagnostic is produced by FCP-6A-01 itself from the synthetic Runner-
shaped fixtures of its own suite, or built directly as a typed (possibly
forged) diagnostic to prove fail-closed behaviour. No provider, process, Git
repository, file or network is used. Nothing is skipped.
"""

import ast
import builtins
import copy
import dataclasses
import io
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_recovery_advisory as ra
from scripts.tests.test_runner_failure_intelligence import (
    PID, SECRET, STATE_ROOT, _assess, _attempt, _fixtures, _pipeline, _result, _summary,
)

MODULE_PATH = Path(ra.__file__)
TEST_PATH = Path(__file__).resolve()
FLAGS = ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed", "resume_allowed",
         "merging_allowed")
AUTHORIZING_WORDS = ("READY", "SAFE_TO", "ALLOWED", "AUTHORIZ", "APPROVE", "PERMIT", "RESUME", "RERUN", "EXECUTE",
                     "MERGE", "CERTIF", "SUBMIT", "RETRY_NOW", "SCHEDULE", "RESTART", "FIX_")


def _diag(*codes, state=None, kind="NO_RETRY", wid="a", primary=None):
    """A typed FCP-6A-01 worker diagnostic with consistent, ordered codes."""
    ordered = fi._ordered(codes)
    return fi.WorkerDiagnostic(
        worker_id=wid, primary_reason=ordered[0] if primary is None else primary, reason_codes=ordered,
        native_state=state, native_state_reason=None, native_outcome=None, native_code=None,
        native_runner_state=None, native_work_status_source=None, retry_decision_kind=kind,
        retry_decision_code=None, attempts_recorded=None, evidence_refs=(),
    )


def _worker(name):
    summary, result = _fixtures()[name]
    return _assess(result, summary)


def _assess_pipeline(pairs, status=None):
    """pairs: [(summary, result-or-None)] -> FCP-6A-01 PipelineDiagnostic."""
    pipeline = _pipeline([s for s, _ in pairs], status=status)
    return fi.assess_pipeline(pipeline, {s["id"]: r for s, r in pairs if r is not None})


def _success(wid):
    return _summary(wid), _result(wid)


def _all_advisories():
    out = [ra.advise_worker(_worker(name)) for name in _fixtures()]
    out.append(ra.advise_pipeline(_assess_pipeline([_success("a"), _success("b")])))
    out.append(ra.advise_pipeline(_assess_pipeline([_fixtures()["quota"]])))
    return out


# ---------------------------------------------------------------------------
class ContractTests(unittest.TestCase):
    def test_precedence_covers_every_fcp6a_code_exactly_once(self):
        integrity = (ra.DIAGNOSTIC_NOT_TYPED, ra.DIAGNOSTIC_INCONSISTENT)
        self.assertEqual(ra.ADVISORY_PRECEDENCE[:2], integrity)
        self.assertEqual(len(ra.ADVISORY_PRECEDENCE), len(set(ra.ADVISORY_PRECEDENCE)))
        self.assertEqual(set(ra.ADVISORY_PRECEDENCE[2:]), set(fi.REASON_PRECEDENCE))
        self.assertEqual(ra.ADVISORY_PRECEDENCE[-1], "SUCCESS_CONSISTENT")

    def test_categories_are_bounded_and_never_authorizing(self):
        self.assertEqual(set(ra.RESPONSIBILITIES),
                         {"RUNNER_NATIVE", "HUMAN_REVIEW", "CORRECT_WORK", "EVIDENCE_REVIEW", "NONE", "UNKNOWN"})
        self.assertEqual(set(ra._CATEGORY_OF.values()), set(ra.CATEGORY_RULES))
        for category, (responsibility, observation) in ra.CATEGORY_RULES.items():
            self.assertIn(responsibility, ra.RESPONSIBILITIES)
            for token in (category, observation):
                self.assertRegex(token, r"^[A-Z][A-Z_]{0,63}$")
                for word in AUTHORIZING_WORDS:
                    self.assertNotIn(word, token, (token, word))

    def test_only_success_has_no_responsibility_and_conflicts_are_unknown(self):
        self.assertEqual([c for c, (r, _) in ra.CATEGORY_RULES.items() if r == "NONE"], ["HISTORICAL_SUCCESS"])
        for category in ("DIAGNOSTIC_UNUSABLE", "EVIDENCE_INVALID", "EVIDENCE_CONFLICT"):
            self.assertEqual(ra.CATEGORY_RULES[category][0], "UNKNOWN")
        waits = [c for c, (_, o) in ra.CATEGORY_RULES.items() if o == "OBSERVE_EXISTING_WAIT"]
        self.assertEqual(sorted(waits), ["EXISTING_PROVIDER_QUOTA_WAIT", "EXISTING_RETRY_WAIT"])

    def test_module_is_stdlib_only_without_io_or_execution(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module + ":" + ",".join(a.name for a in node.names))
        self.assertEqual(imported, {"__future__:annotations", "json", "dataclasses:dataclass", "typing:Optional",
                                    "scripts.ai:runner_failure_intelligence"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("open", "exec", "eval", "__import__", "compile", "input", "setattr"):
            self.assertNotIn(forbidden, names)
        for forbidden in ("read_text", "write_text", "system", "Popen", "run", "remove", "unlink", "replace",
                          "submit", "recover", "resume", "sleep", "now"):
            self.assertNotIn(forbidden, attrs)
        self.assertFalse(any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree)))

    def test_module_never_names_runner_or_director_machinery(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        docstrings = {id(body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and (body := n.body)
                      and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)}
        tokens = {n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings}
        tokens |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        tokens |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        tokens |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        for word in ("subprocess", "socket", "runner_pipeline", "fabric_director", "claude_runner", "os",
                     "resume_from", "RESUME_WORK_PRODUCT", "Path", "environ"):
            self.assertFalse(any(word == t or word in t.split(".") or (len(word) > 2 and word in t)
                                 for t in tokens), word)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


# ---------------------------------------------------------------------------
class WorkerMatrixTests(unittest.TestCase):
    def _check(self, diag, category, responsibility, observation):
        adv = ra.advise_worker(diag)
        self.assertEqual((adv.category, adv.responsibility, adv.observation),
                         (category, responsibility, observation), adv.reasons)
        self.assertEqual(adv.reasons[0], next(c for c in ra.ADVISORY_PRECEDENCE if c in adv.reasons))
        self.assertEqual(adv.source_schema, fi.SCHEMA_WORKER)
        self.assertEqual(adv.source_primary_reason, diag.primary_reason)
        return adv

    def test_consistent_success_is_historical_observation_only(self):
        adv = self._check(_worker("success"), "HISTORICAL_SUCCESS", "NONE", "NO_FOLLOWUP_INDICATED")
        self.assertEqual(adv.reasons, ("SUCCESS_CONSISTENT",))
        self.assertEqual((adv.worker_id, adv.native_state, adv.retry_decision_kind), ("a", "SUCCESS", "NONE"))
        for flag in FLAGS:
            self.assertIs(getattr(adv, flag), False)

    def test_native_failures_need_human_review(self):
        for name in ("failed_non_transient", "failed_after_retries"):
            with self.subTest(name):
                adv = self._check(_worker(name), "NATIVE_FAILED", "HUMAN_REVIEW", "REVIEW_NATIVE_FAILURE")
                self.assertNotIn("TRANSIENT_RETRY_WAIT", adv.reasons)

    def test_retry_wait_is_existing_runner_wait_not_permission(self):
        adv = self._check(_worker("retry_wait"), "EXISTING_RETRY_WAIT", "RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT")
        self.assertEqual(adv.native_state, "RETRY_WAIT")
        self.assertFalse(adv.auto_retry_allowed or adv.execution_allowed or adv.authorizes_action)

    def test_quota_wait_is_existing_runner_wait_without_new_deadline(self):
        adv = self._check(_worker("quota"), "EXISTING_PROVIDER_QUOTA_WAIT", "RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT")
        text = ra.canonical_json(adv)
        for leaked in ("2026-", "until", "next_eligible", "backoff", "RESET_HINT"):
            self.assertNotIn(leaked, text)

    def test_provider_auth_always_needs_human_credentials_review(self):
        self._check(_worker("auth"), "PROVIDER_AUTH_BLOCKED", "HUMAN_REVIEW", "REVIEW_PROVIDER_CREDENTIALS")
        mixed = _diag("PROVIDER_AUTH_BLOCKED", "PROVIDER_QUOTA_WAIT", "TRANSIENT_RETRY_WAIT",
                      state="BLOCKED_PROVIDER_AUTH", kind="WAIT")
        self._check(mixed, "PROVIDER_AUTH_BLOCKED", "HUMAN_REVIEW", "REVIEW_PROVIDER_CREDENTIALS")

    def test_interrupted_and_unresolved_process_need_ownership_review(self):
        self._check(_worker("interrupted"), "INTERRUPTED", "HUMAN_REVIEW", "REVIEW_PROCESS_OWNERSHIP")
        adv = self._check(_worker("process_unresolved"), "PROCESS_UNRESOLVED", "HUMAN_REVIEW",
                          "REVIEW_PROCESS_OWNERSHIP")
        self.assertIn("NATIVE_BLOCKED", adv.reasons)

    def test_dependency_cancellation_points_upstream(self):
        self._check(_worker("cancelled_dependent"), "DEPENDENCY_CANCELLED", "HUMAN_REVIEW",
                    "REVIEW_UPSTREAM_DEPENDENCY")

    def test_operator_cancellation_is_native_cancelled(self):
        diag = _assess(_result(state="CANCELLED", code="OPERATOR_CANCELLED", state_reason="OPERATOR_CANCELLED",
                               attempts=[]), _summary(state="CANCELLED", reason="OPERATOR_CANCELLED"))
        self._check(diag, "NATIVE_CANCELLED", "HUMAN_REVIEW", "REVIEW_NATIVE_CANCELLATION")

    def test_acceptance_failure_means_correct_work_not_rerun(self):
        self._check(_worker("acceptance_failed"), "ACCEPTANCE_FAILED", "CORRECT_WORK", "REVIEW_WORK_AND_TESTS")

    def test_checkpoint_and_preflight_refusals(self):
        self._check(_worker("checkpoint_failed"), "CHECKPOINT_FAILED", "HUMAN_REVIEW", "REVIEW_CHECKPOINT_FAILURE")
        self._check(_worker("preflight"), "PREFLIGHT_REFUSED", "HUMAN_REVIEW", "REVIEW_PREFLIGHT_REFUSAL")

    def test_incomplete_evidence_outranks_partial_and_is_never_upgraded(self):
        adv = self._check(_worker("partial_evidence"), "EVIDENCE_GAP", "EVIDENCE_REVIEW", "INVESTIGATE_EVIDENCE")
        self.assertEqual(adv.reasons, ("EVIDENCE_INCOMPLETE", "PARTIAL_COMPLETION"))

    def test_clean_partial_means_correct_work(self):
        diag = _assess(_result(state="PARTIAL", code="PARTIAL", state_reason="PARTIAL_WORK",
                               attempts=[_attempt(work_status="PARTIAL", retry_decision="NO_RETRY:PARTIAL")]),
                       _summary(state="PARTIAL", reason="PARTIAL_WORK"))
        self._check(diag, "PARTIAL_COMPLETION", "CORRECT_WORK", "REVIEW_PARTIAL_WORK")

    def test_plain_native_block(self):
        diag = _assess(_result(state="BLOCKED", code="WORKER_BLOCKED", state_reason="WORKER_BLOCKED",
                               attempts=[_attempt(work_status="BLOCKED", retry_decision="NO_RETRY:BLOCKED")]),
                       _summary(state="BLOCKED", reason="WORKER_BLOCKED"))
        self._check(diag, "NATIVE_BLOCKED", "HUMAN_REVIEW", "REVIEW_NATIVE_BLOCK")

    def test_unauthorized_paths_are_safety_refusal(self):
        diag = _assess(_result(state="BLOCKED", code="WORKER_BLOCKED", state_reason="WORKER_BLOCKED",
                               attempts=[_attempt(unauthorized_changed_paths=[f"{STATE_ROOT}/{SECRET}"],
                                                  retry_decision="NO_RETRY:BLOCKED")]),
                       _summary(state="BLOCKED", reason="WORKER_BLOCKED"))
        adv = self._check(diag, "SAFETY_REFUSED", "HUMAN_REVIEW", "REVIEW_SAFETY_REFUSAL")
        self.assertNotIn(SECRET, ra.canonical_json(adv))

    def test_missing_or_unproven_success_is_evidence_gap_never_success(self):
        cases = {
            "missing result": _assess(None, _summary()),
            "unproven": _assess(_result(attempts=[_attempt(evidence_complete=None)]), _summary()),
        }
        for label, diag in cases.items():
            with self.subTest(label):
                adv = self._check(diag, "EVIDENCE_GAP", "EVIDENCE_REVIEW", "INVESTIGATE_EVIDENCE")
                self.assertNotIn("SUCCESS_CONSISTENT", adv.reasons)

    def test_pending_worker_is_observed_runner_run(self):
        diag = _assess(None, _summary(state="RUNNING", result_path=False))
        self._check(diag, "EXISTING_RUN_IN_PROGRESS", "RUNNER_NATIVE", "OBSERVE_EXISTING_RUN")

    def test_conflicting_identity_and_unknown_evidence_is_unknown(self):
        cases = {
            "state conflict": (_assess(_result(state="FAILED"), _summary()), "EVIDENCE_CONFLICT",
                               "REVIEW_EVIDENCE_CONFLICT"),
            "identity": (_assess(_result(wid="b"), _summary()), "EVIDENCE_INVALID", "REVIEW_EVIDENCE_INTEGRITY"),
            "unknown state": (_assess(None, _summary(state="EXPLODED")), "EVIDENCE_INVALID",
                              "REVIEW_EVIDENCE_INTEGRITY"),
        }
        for label, (diag, category, observation) in cases.items():
            with self.subTest(label):
                adv = self._check(diag, category, "UNKNOWN", observation)
                self.assertNotIn("SUCCESS_CONSISTENT", adv.reasons)

    def test_every_fcp6a_code_alone_maps_to_its_documented_category(self):
        for code in fi.REASON_PRECEDENCE:
            with self.subTest(code):
                diag = (_diag(code, state="SUCCESS", kind="NONE") if code == "SUCCESS_CONSISTENT"
                        else _diag(code, wid=None if code == "MALFORMED_EVIDENCE" else "a"))
                adv = ra.advise_worker(diag)
                self.assertEqual(adv.reasons, (code,))
                self.assertEqual(adv.category, ra._CATEGORY_OF[code])
                self.assertEqual((adv.responsibility, adv.observation), ra.CATEGORY_RULES[adv.category])


# ---------------------------------------------------------------------------
class PrecedenceTests(unittest.TestCase):
    def test_documented_pairwise_precedence(self):
        cases = [
            (("CONFLICTING_EVIDENCE", "PROCESS_TERMINATION_UNRESOLVED"), "EVIDENCE_CONFLICT"),
            (("MALFORMED_EVIDENCE", "AGGREGATE_CONTRADICTION"), "EVIDENCE_INVALID"),
            (("PROCESS_TERMINATION_UNRESOLVED", "SAFETY_REFUSAL"), "PROCESS_UNRESOLVED"),
            (("SAFETY_REFUSAL", "PROVIDER_AUTH_BLOCKED"), "SAFETY_REFUSED"),
            (("PROVIDER_AUTH_BLOCKED", "INTERRUPTED_OPERATOR_REVIEW"), "PROVIDER_AUTH_BLOCKED"),
            (("INTERRUPTED_OPERATOR_REVIEW", "CHECKPOINT_FAILED"), "INTERRUPTED"),
            (("CHECKPOINT_FAILED", "ACCEPTANCE_FAILED"), "CHECKPOINT_FAILED"),
            (("ACCEPTANCE_FAILED", "PREFLIGHT_REFUSED"), "ACCEPTANCE_FAILED"),
            (("PREFLIGHT_REFUSED", "EVIDENCE_INCOMPLETE"), "PREFLIGHT_REFUSED"),
            (("EVIDENCE_MISSING", "NATIVE_FAILED"), "EVIDENCE_GAP"),
            (("NATIVE_FAILED", "NATIVE_BLOCKED"), "NATIVE_FAILED"),
            (("NATIVE_BLOCKED", "PARTIAL_COMPLETION"), "NATIVE_BLOCKED"),
            (("PARTIAL_COMPLETION", "NATIVE_CANCELLED"), "PARTIAL_COMPLETION"),
            (("NATIVE_FAILED", "DEPENDENCY_CANCELLED"), "NATIVE_FAILED"),
            (("NATIVE_CANCELLED", "PROVIDER_QUOTA_WAIT"), "NATIVE_CANCELLED"),
            (("PROVIDER_QUOTA_WAIT", "TRANSIENT_RETRY_WAIT"), "EXISTING_PROVIDER_QUOTA_WAIT"),
            (("TRANSIENT_RETRY_WAIT", "NOT_TERMINAL"), "EXISTING_RETRY_WAIT"),
        ]
        for codes, category in cases:
            with self.subTest(codes):
                wid = None if "MALFORMED_EVIDENCE" in codes else "a"
                adv = ra.advise_worker(_diag(*codes, wid=wid))
                self.assertEqual(adv.category, category)
                self.assertEqual(set(adv.reasons), set(codes))

    def test_waits_never_outrank_any_failure_or_review(self):
        reviewable = [c for c in fi.REASON_PRECEDENCE
                      if c not in ("PROVIDER_QUOTA_WAIT", "TRANSIENT_RETRY_WAIT", "NOT_TERMINAL", "SUCCESS_CONSISTENT")]
        for code in reviewable:
            with self.subTest(code):
                wid = None if code == "MALFORMED_EVIDENCE" else "a"
                adv = ra.advise_worker(_diag(code, "PROVIDER_QUOTA_WAIT", "TRANSIENT_RETRY_WAIT", wid=wid))
                self.assertNotEqual(adv.responsibility, "RUNNER_NATIVE")
                self.assertNotIn(adv.observation, ("OBSERVE_EXISTING_WAIT", "NO_FOLLOWUP_INDICATED"))


# ---------------------------------------------------------------------------
class WorkerFailClosedTests(unittest.TestCase):
    def _unusable(self, value):
        adv = ra.advise_worker(value)
        self.assertEqual((adv.category, adv.responsibility, adv.observation),
                         ("DIAGNOSTIC_UNUSABLE", "UNKNOWN", "REVIEW_DIAGNOSTIC_INTEGRITY"))
        self.assertNotIn("SUCCESS_CONSISTENT", adv.reasons)
        return adv

    def test_untyped_or_raw_inputs_are_refused_without_reading(self):
        class Sub(fi.WorkerDiagnostic):
            @property
            def authorizes_action(self):
                return True

        forged = Sub(**{f.name: getattr(_worker("success"), f.name) for f in dataclasses.fields(fi.WorkerDiagnostic)})
        for value in (None, {}, _result(), _worker("success").to_dict(), "SUCCESS_CONSISTENT", 42, forged,
                      _assess_pipeline([_success("a")])):
            with self.subTest(type(value).__name__):
                adv = self._unusable(value)
                self.assertEqual(adv.reasons, (ra.DIAGNOSTIC_NOT_TYPED,))
                self.assertEqual((adv.worker_id, adv.source_schema, adv.native_state), (None, None, None))

    def test_contradictory_typed_diagnostics_fail_closed(self):
        ok = _worker("success")
        cases = {
            "unordered codes": dataclasses.replace(_diag("NATIVE_FAILED", "SAFETY_REFUSAL", state="FAILED"),
                                                   reason_codes=("NATIVE_FAILED", "SAFETY_REFUSAL")),
            "primary mismatch": _diag("NATIVE_FAILED", state="FAILED", primary="SUCCESS_CONSISTENT"),
            "unknown code": dataclasses.replace(ok, primary_reason="READY_TO_RETRY",
                                                reason_codes=("READY_TO_RETRY",)),
            "empty codes": dataclasses.replace(ok, primary_reason="", reason_codes=()),
            "list codes": dataclasses.replace(ok, reason_codes=["SUCCESS_CONSISTENT"]),
            "duplicate codes": dataclasses.replace(ok, reason_codes=("SUCCESS_CONSISTENT", "SUCCESS_CONSISTENT")),
            "success beside failure": dataclasses.replace(
                _diag("NATIVE_FAILED", state="FAILED"), reason_codes=("NATIVE_FAILED", "SUCCESS_CONSISTENT")),
            "success on failed state": dataclasses.replace(ok, native_state="FAILED"),
            "success on retry wait": dataclasses.replace(ok, native_state="RETRY_WAIT"),
            "success with retry kind": dataclasses.replace(ok, retry_decision_kind="RETRY"),
            "failed without native code": _diag("EVIDENCE_UNPROVEN", state="FAILED"),
            "quota state without wait code": _diag("NATIVE_BLOCKED", state="WAITING_PROVIDER_QUOTA"),
            "retry kind without wait code": _diag("NATIVE_FAILED", state="FAILED", kind="RETRY"),
            "bogus kind": _diag("NATIVE_FAILED", state="FAILED", kind="GO"),
            "unrecognized kind without code": _diag("NATIVE_FAILED", state="FAILED", kind="UNRECOGNIZED"),
            "unknown state without code": _diag("NATIVE_FAILED", state="EXPLODED"),
            "unsafe worker id": _diag("NATIVE_FAILED", state="FAILED", wid="../" + SECRET),
            "missing id unflagged": _diag("NATIVE_FAILED", state="FAILED", wid=None),
        }
        for label, diag in cases.items():
            with self.subTest(label):
                adv = self._unusable(diag)
                self.assertEqual(adv.reasons[0], ra.DIAGNOSTIC_INCONSISTENT)
                text = ra.canonical_json(adv)
                for leaked in ("READY_TO_RETRY", "EXPLODED", SECRET, "GO\""):
                    self.assertNotIn(leaked, text)


# ---------------------------------------------------------------------------
class GuaranteeTests(unittest.TestCase):
    def test_no_advisory_ever_authorizes_anything(self):
        for adv in _all_advisories():
            items = [adv, *getattr(adv, "workers", ())]
            for item in items:
                for flag in FLAGS:
                    self.assertIs(getattr(item, flag), False, (item.category, flag))
                data = item.to_dict()
                for flag in FLAGS:
                    self.assertIs(data[flag], False)
                self.assertEqual(data["marker"], ra.ADVISORY_MARKER)

    def test_waits_and_success_explicitly_unauthorized(self):
        for name in ("retry_wait", "quota", "success"):
            with self.subTest(name):
                adv = ra.advise_worker(_worker(name))
                self.assertIn(adv.observation, ("OBSERVE_EXISTING_WAIT", "NO_FOLLOWUP_INDICATED"))
                self.assertEqual([f for f in FLAGS if getattr(adv, f) is not False], [])
                for key in set(adv.to_dict()) - set(FLAGS):
                    for word in ("next", "deadline", "backoff", "resume_from", "command", "action"):
                        self.assertNotIn(word, key)

    def test_flags_cannot_be_set_by_constructor_replace_or_assignment(self):
        adv = ra.advise_worker(_worker("retry_wait"))
        fields = {f.name: getattr(adv, f.name) for f in dataclasses.fields(adv)}
        self.assertEqual(set(fields) & set(FLAGS), set())
        for flag in FLAGS:
            with self.subTest(flag):
                with self.assertRaises(TypeError):
                    ra.WorkerRecoveryAdvisory(**fields, **{flag: True})
                with self.assertRaises(TypeError):
                    dataclasses.replace(adv, **{flag: True})
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(adv, flag, True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            adv.category = "HISTORICAL_SUCCESS"

    def test_advisories_cannot_be_forged_with_other_categories(self):
        adv = ra.advise_worker(_worker("failed_non_transient"))
        forgeries = [
            {"category": "HISTORICAL_SUCCESS", "responsibility": "NONE", "observation": "NO_FOLLOWUP_INDICATED"},
            {"responsibility": "RUNNER_NATIVE"},
            {"observation": "OBSERVE_EXISTING_WAIT"},
            {"category": "READY"},
            {"reasons": ()},
            {"reasons": ("NATIVE_FAILED", "SAFETY_REFUSAL")},
            {"reasons": ("RETRY_ALLOWED",)},
        ]
        for change in forgeries:
            with self.subTest(change):
                with self.assertRaises(ValueError):
                    dataclasses.replace(adv, **change)
        pipe = ra.advise_pipeline(_assess_pipeline([_success("a")]))
        with self.assertRaises(ValueError):
            dataclasses.replace(pipe, workers=({"category": "HISTORICAL_SUCCESS"},))

    def test_source_diagnostics_are_not_mutated(self):
        worker = _worker("quota")
        pipeline = _assess_pipeline([_success("a"), _fixtures()["failed_non_transient"]])
        before = (fi.canonical_json(worker), fi.canonical_json(pipeline), copy.deepcopy(worker),
                  copy.deepcopy(pipeline))
        ra.advise_worker(worker)
        ra.advise_pipeline(pipeline)
        self.assertEqual((fi.canonical_json(worker), fi.canonical_json(pipeline), worker, pipeline), before)

    def test_output_is_deterministic(self):
        for name in _fixtures():
            with self.subTest(name):
                runs = {ra.canonical_json(ra.advise_worker(_worker(name))) for _ in range(3)}
                self.assertEqual(len(runs), 1)
        pairs = [_success("b"), _fixtures()["quota"], _success("c")]
        self.assertEqual(ra.canonical_json(ra.advise_pipeline(_assess_pipeline(pairs))),
                         ra.canonical_json(ra.advise_pipeline(_assess_pipeline(copy.deepcopy(pairs)))))
        self.assertEqual(ra.advise_worker(_worker("auth")), ra.advise_worker(_worker("auth")))

    def test_serialization_never_leaks_raw_evidence(self):
        pipeline = _assess_pipeline([_success("a"), *[v for k, v in _fixtures().items() if k != "success"]])
        texts = [ra.canonical_json(ra.advise_pipeline(pipeline))]
        texts += [ra.canonical_json(ra.advise_worker(_worker(n))) for n in _fixtures()]
        for text in texts:
            for leaked in (SECRET, STATE_ROOT, "C:/", "claude", "2026-", "run-1", "evidence_refs",
                           "native_state_reason", "native_code", "stdout", "stderr"):
                self.assertNotIn(leaked, text)
        self.assertEqual(set(ra.advise_worker(_worker("success")).to_dict()), {
            "schema", "schema_version", "worker_id", "source_schema", "source_primary_reason", "native_state",
            "retry_decision_kind", "category", "responsibility", "observation", "reasons", "marker", *FLAGS,
        })

    def test_advising_performs_no_io_or_process_calls(self):
        worker_diags = [_worker(n) for n in _fixtures()]
        pipeline = _assess_pipeline([_success("a"), _fixtures()["quota"]])
        boom = mock.Mock(side_effect=AssertionError("I/O attempted"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(os, "open", boom), mock.patch.object(os, "stat", boom), \
                mock.patch.object(os, "listdir", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(socket, "socket", boom):
            for diag in worker_diags:
                ra.canonical_json(ra.advise_worker(diag))
            ra.canonical_json(ra.advise_pipeline(pipeline))
        boom.assert_not_called()


# ---------------------------------------------------------------------------
class PipelineTests(unittest.TestCase):
    def test_all_consistent_success_reports_only_no_followup(self):
        diag = _assess_pipeline([_success("a"), _success("b")])
        self.assertEqual(diag.diagnostic_status, "SUCCESS")
        adv = ra.advise_pipeline(diag)
        self.assertEqual((adv.category, adv.responsibility, adv.observation, adv.reasons),
                         ("HISTORICAL_SUCCESS", "NONE", "NO_FOLLOWUP_INDICATED", ("SUCCESS_CONSISTENT",)))
        self.assertEqual((adv.pipeline_id, adv.native_status, adv.diagnostic_status), (PID, "SUCCESS", "SUCCESS"))
        self.assertEqual([w.category for w in adv.workers], ["HISTORICAL_SUCCESS"] * 2)
        self.assertEqual([f for f in FLAGS if getattr(adv, f) is not False], [])

    def test_worker_order_is_preserved_and_every_worker_reported(self):
        fx = _fixtures()
        pairs = [_success("c"), (_summary("a", state="FAILED", reason="CLAUDE_ERROR"),
                                 _result("a", state="FAILED", code="CLAUDE_ERROR", state_reason="CLAUDE_ERROR",
                                         attempts=[_attempt(retry_decision="NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR")])),
                 _success("b"), fx["auth"]]
        pairs[3] = (dict(pairs[3][0], id="z"), dict(pairs[3][1], worker_id="z"))
        diag = _assess_pipeline(pairs)
        adv = ra.advise_pipeline(diag)
        self.assertEqual([w.worker_id for w in adv.workers], ["c", "a", "b", "z"])
        self.assertEqual([w.worker_id for w in adv.workers], [w.worker_id for w in diag.workers])
        self.assertEqual([w.category for w in adv.workers],
                         ["HISTORICAL_SUCCESS", "NATIVE_FAILED", "HISTORICAL_SUCCESS", "PROVIDER_AUTH_BLOCKED"])
        self.assertEqual(adv.category, "PROVIDER_AUTH_BLOCKED")

    def test_failed_root_outranks_dependent_cancellation(self):
        fx = _fixtures()
        failed = (_summary("a", state="FAILED", reason="CLAUDE_ERROR"), fx["failed_non_transient"][1])
        dep = (dict(fx["cancelled_dependent"][0], id="b"), dict(fx["cancelled_dependent"][1], worker_id="b"))
        adv = ra.advise_pipeline(_assess_pipeline([failed, dep]))
        self.assertEqual((adv.category, adv.diagnostic_status), ("NATIVE_FAILED", "FAILED"))
        self.assertEqual([w.category for w in adv.workers], ["NATIVE_FAILED", "DEPENDENCY_CANCELLED"])

    def test_non_success_pipelines_are_never_upgraded(self):
        for name, pair in _fixtures().items():
            if name == "success":
                continue
            with self.subTest(name):
                diag = _assess_pipeline([_success("a"), (dict(pair[0], id="w"),
                                                         None if pair[1] is None else dict(pair[1], worker_id="w"))])
                adv = ra.advise_pipeline(diag)
                self.assertNotEqual(adv.category, "HISTORICAL_SUCCESS")
                self.assertNotIn("SUCCESS_CONSISTENT", adv.reasons)
                self.assertNotEqual(adv.responsibility, "NONE")
                self.assertEqual((adv.native_status, adv.diagnostic_status),
                                 (diag.native_status, diag.diagnostic_status))
                self.assertEqual(len(adv.workers), 2)

    def test_native_success_with_unproven_worker_stays_unverified_evidence_gap(self):
        pairs = [_success("a"), (_summary("b"), _result("b", attempts=[_attempt(evidence_complete=None)]))]
        adv = ra.advise_pipeline(_assess_pipeline(pairs))
        self.assertEqual((adv.native_status, adv.diagnostic_status), ("SUCCESS", "UNVERIFIED"))
        self.assertEqual((adv.category, adv.responsibility), ("EVIDENCE_GAP", "EVIDENCE_REVIEW"))

    def test_existing_waits_at_pipeline_level_stay_runner_native_or_stricter(self):
        quota = ra.advise_pipeline(_assess_pipeline([_fixtures()["quota"]]))
        self.assertEqual((quota.category, quota.responsibility, quota.observation),
                         ("EXISTING_PROVIDER_QUOTA_WAIT", "RUNNER_NATIVE", "OBSERVE_EXISTING_WAIT"))
        retry = ra.advise_pipeline(_assess_pipeline([_fixtures()["retry_wait"]]))
        # FCP-6A-01 reports the not-yet-written result as missing; that gap outranks the wait.
        self.assertEqual(retry.category, "EVIDENCE_GAP")
        self.assertEqual(retry.workers[0].category, "EXISTING_RETRY_WAIT")
        for adv in (quota, retry):
            self.assertFalse(any(getattr(adv, f) for f in FLAGS))

    def test_empty_pipeline_fails_closed(self):
        adv = ra.advise_pipeline(fi.assess_pipeline(_pipeline([]), {}))
        self.assertEqual((adv.category, adv.responsibility, adv.workers), ("EVIDENCE_INVALID", "UNKNOWN", ()))
        self.assertIn("EMPTY_PIPELINE", adv.reasons)

    def test_duplicate_worker_summaries_are_reported_not_dropped(self):
        pipeline = _pipeline([_summary("a"), _summary("a")])
        adv = ra.advise_pipeline(fi.assess_pipeline(pipeline, {"a": _result("a")}))
        self.assertEqual([w.worker_id for w in adv.workers], ["a", "a"])
        self.assertEqual(adv.category, "EVIDENCE_INVALID")
        self.assertTrue(all(w.category == "EVIDENCE_INVALID" for w in adv.workers))

    def test_forged_duplicate_success_is_unusable(self):
        clean = _assess_pipeline([_success("a")])
        forged = dataclasses.replace(clean, workers=(clean.workers[0], clean.workers[0]))
        adv = ra.advise_pipeline(forged)
        self.assertEqual(adv.reasons[:2], (ra.DIAGNOSTIC_INCONSISTENT, "DUPLICATE_WORKER_ID"))
        self.assertEqual(adv.category, "DIAGNOSTIC_UNUSABLE")
        self.assertEqual(len(adv.workers), 2)

    def test_malformed_worker_summaries_fail_closed_and_are_kept(self):
        pipeline = _pipeline([_summary("a")])
        pipeline["workers"] = [_summary("a"), "junk", {"state": "SUCCESS"}]
        pipeline["workers_total"] = 3
        diag = fi.assess_pipeline(pipeline, {"a": _result("a")})
        adv = ra.advise_pipeline(diag)
        self.assertEqual(len(adv.workers), 3)
        self.assertEqual(adv.category, "EVIDENCE_INVALID")
        self.assertEqual([w.category for w in adv.workers[1:]], ["EVIDENCE_INVALID"] * 2)

    def test_aggregate_contradiction_is_conflict_not_success(self):
        pairs = [_success("a"), _fixtures()["failed_non_transient"]]
        pairs[1] = (dict(pairs[1][0], id="b"), dict(pairs[1][1], worker_id="b"))
        adv = ra.advise_pipeline(_assess_pipeline(pairs, status="SUCCESS"))
        self.assertEqual((adv.category, adv.responsibility), ("EVIDENCE_CONFLICT", "UNKNOWN"))
        self.assertEqual(adv.diagnostic_status, "UNVERIFIED")

    def test_forged_pipeline_diagnostics_fail_closed(self):
        clean = _assess_pipeline([_success("a")])
        failed = _assess_pipeline([_fixtures()["failed_non_transient"]])
        cases = {
            "success over failed worker": dataclasses.replace(failed, diagnostic_status="SUCCESS"),
            "success over native failed": dataclasses.replace(
                failed, diagnostic_status="SUCCESS", primary_reason="SUCCESS_CONSISTENT",
                reason_codes=("SUCCESS_CONSISTENT",)),
            "failed upgraded to partial": dataclasses.replace(failed, diagnostic_status="PARTIAL"),
            "unverified relabelled success": dataclasses.replace(
                _assess_pipeline([(_summary(), _result(attempts=[]))]), diagnostic_status="SUCCESS"),
            "worker codes dropped": dataclasses.replace(failed, primary_reason="SUCCESS_CONSISTENT",
                                                        reason_codes=("SUCCESS_CONSISTENT",)),
            "raw worker dict": dataclasses.replace(clean, workers=(clean.workers[0], _result("b"))),
            "workers as list": dataclasses.replace(clean, workers=list(clean.workers)),
            "missing ids unflagged": dataclasses.replace(clean, missing_worker_ids=("b",)),
            "extras unflagged": dataclasses.replace(clean, unidentified_extra_results=1),
            "bool extras": dataclasses.replace(clean, unidentified_extra_results=True),
            "empty but unflagged": dataclasses.replace(clean, workers=()),
            "unknown status": dataclasses.replace(clean, diagnostic_status="CERTIFIED"),
            "unknown native unlabelled": dataclasses.replace(clean, native_status="DONE"),
            "unsafe pipeline id": dataclasses.replace(clean, pipeline_id="../" + SECRET),
        }
        for label, diag in cases.items():
            with self.subTest(label):
                adv = ra.advise_pipeline(diag)
                self.assertEqual((adv.category, adv.responsibility), ("DIAGNOSTIC_UNUSABLE", "UNKNOWN"))
                self.assertNotIn("SUCCESS_CONSISTENT", adv.reasons)
                text = ra.canonical_json(adv)
                for leaked in (SECRET, "CERTIFIED\"", "DONE", "C:/"):
                    self.assertNotIn(leaked, text)
        kept = ra.advise_pipeline(cases["raw worker dict"])
        self.assertEqual([w.category for w in kept.workers], ["HISTORICAL_SUCCESS", "DIAGNOSTIC_UNUSABLE"])

    def test_untyped_pipeline_inputs_are_refused(self):
        for value in (None, {}, _pipeline([_summary()]), _worker("success"), [_worker("success")]):
            with self.subTest(type(value).__name__):
                adv = ra.advise_pipeline(value)
                self.assertEqual((adv.category, adv.reasons, adv.workers),
                                 ("DIAGNOSTIC_UNUSABLE", (ra.DIAGNOSTIC_NOT_TYPED,), ()))
                self.assertEqual((adv.pipeline_id, adv.native_status, adv.diagnostic_status), (None, None, None))

    def test_pipeline_serialization_shape(self):
        adv = ra.advise_pipeline(_assess_pipeline([_success("a"), _fixtures()["quota"]]))
        data = adv.to_dict()
        self.assertEqual(data["schema"], ra.SCHEMA_PIPELINE)
        self.assertEqual(data["source_schema"], fi.SCHEMA_PIPELINE)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual([w["schema"] for w in data["workers"]], [ra.SCHEMA_WORKER] * 2)
        self.assertEqual(set(data) - set(FLAGS), {
            "schema", "schema_version", "pipeline_id", "source_schema", "source_primary_reason", "native_status",
            "diagnostic_status", "category", "responsibility", "observation", "reasons", "workers", "marker",
        })


if __name__ == "__main__":
    unittest.main()
