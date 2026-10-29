"""FCP-6C-03: transversal adversarial regression over FCP-6A-01 + FCP-6B-01.

Every case runs the full read-only chain on synthetic Runner-shaped evidence:
`pipeline_result.json` + `{worker_id: workers/<id>/result.json}` ->
`runner_failure_intelligence.assess_pipeline` ->
`runner_recovery_advisory.advise_pipeline`, and checks cross-module
invariants neither suite pins on its own: a non-success Runner status never
becomes success, a native SUCCESS with gaps degrades to UNVERIFIED, waits and
refusals never derive authority, real FCP-6A output is always consistent for
FCP-6B, and nothing confidential crosses the chain. Fixture builders are
reused from the FCP-6A-01 suite. No provider, process, Git repository, file
or network is used; randomness is never used. Nothing is skipped.
"""

import ast
import copy
import dataclasses
import itertools
import json
import unittest
from pathlib import Path

from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_recovery_advisory as ra
from scripts.tests.test_runner_failure_intelligence import (
    PID, SECRET, STATE_ROOT, _attempt, _fixtures, _pipeline, _result, _summary,
)

TEST_PATH = Path(__file__).resolve()
DIAG_FLAGS = ("certified", "authorizes_action", "auto_retry_allowed", "execution_allowed")
ADVISORY_FLAGS = DIAG_FLAGS + ("resume_allowed", "merging_allowed")
NON_SUCCESS_STATUSES = ("FAILED", "BLOCKED", "PARTIAL", "CANCELLED", "INCOMPLETE")
AUTHORIZING_WORDS = ("ALLOW", "AUTHORIZ", "APPROVE", "PERMIT", "RESUME", "RERUN", "RETRY_NOW", "EXECUTE",
                     "MERGE", "CERTIF", "SUBMIT", "SCHEDULE", "RESTART", "PROMOTE")
SCHEDULE_KEYS = ("next", "eligible", "until", "deadline", "backoff", "resume", "command", "action", "token")
# Bounded upper-case token shaped like a credential: FCP-6A may keep it as a
# native code, FCP-6B must never echo it.
TOKEN_SHAPED_SECRET = "ANTHROPICKEY9F3QX"


def _chain(pipeline_result, worker_results):
    diag = fi.assess_pipeline(pipeline_result, worker_results)
    return diag, ra.advise_pipeline(diag)


def _pairs_chain(pairs, status=None):
    """pairs: [(summary, result-or-None)] -> (diagnostic, advisory). Like a
    caller that looked for every declared `result.json`, an absent file is
    passed as None rather than dropped from the mapping."""
    return _chain(_pipeline([s for s, _ in pairs], status=status), {s["id"]: r for s, r in pairs})


def _success(wid):
    return _summary(wid), _result(wid)


def _named(name, wid):
    """An FCP-6A fixture re-keyed to worker `wid` (a fresh copy)."""
    summary, result = copy.deepcopy(_fixtures()[name])
    summary["id"] = wid
    if result is not None:
        result["worker_id"] = wid
    return summary, result


def _true_leaves(value, path="$"):
    if value is True:
        return [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _true_leaves(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _true_leaves(v, f"{path}[{i}]")]
    return []


def _keys(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _rank(advisory):
    return ra.ADVISORY_PRECEDENCE.index(advisory.reasons[0])


class _ChainCase(unittest.TestCase):
    def assertChainInvariants(self, diag, adv):
        """Cross-module invariants every (diagnostic, advisory) pair must hold."""
        self.assertIs(type(diag), fi.PipelineDiagnostic)
        self.assertIs(type(adv), ra.PipelineRecoveryAdvisory)
        # FCP-6A source is informational only.
        for item in (diag, *diag.workers):
            for flag in DIAG_FLAGS:
                self.assertIs(getattr(item, flag), False, flag)
            self.assertEqual(item.to_dict()["marker"], fi.DIAGNOSTIC_MARKER)
        self.assertIn("INFORMATIONAL", fi.DIAGNOSTIC_MARKER)
        self.assertEqual(_true_leaves(diag.to_dict()), [])
        # FCP-6B advisory never authorizes anything, anywhere in its tree.
        for item in (adv, *adv.workers):
            for flag in ADVISORY_FLAGS:
                self.assertIs(getattr(item, flag), False, flag)
            self.assertEqual(item.to_dict()["marker"], ra.ADVISORY_MARKER)
            self.assertEqual((item.responsibility, item.observation), ra.CATEGORY_RULES[item.category])
            for word in AUTHORIZING_WORDS:
                self.assertNotIn(word, item.observation)
                self.assertNotIn(word, item.category)
        self.assertEqual(_true_leaves(adv.to_dict()), [])
        # The advisory mirrors its source; real FCP-6A output is never unusable.
        self.assertEqual(adv.source_schema, fi.SCHEMA_PIPELINE)
        self.assertEqual([w.source_schema for w in adv.workers], [fi.SCHEMA_WORKER] * len(diag.workers))
        self.assertEqual([w.worker_id for w in adv.workers], [w.worker_id for w in diag.workers])
        self.assertEqual(adv.diagnostic_status, diag.diagnostic_status)
        for item in (adv, *adv.workers):
            self.assertNotIn(ra.DIAGNOSTIC_INCONSISTENT, item.reasons)
            self.assertNotIn(ra.DIAGNOSTIC_NOT_TYPED, item.reasons)
        # Success is never invented and never weaker than any worker.
        if diag.native_status != "SUCCESS":
            self.assertNotEqual(diag.diagnostic_status, "SUCCESS")
        self.assertEqual(adv.category == "HISTORICAL_SUCCESS", diag.diagnostic_status == "SUCCESS")
        self.assertEqual(adv.responsibility == "NONE", diag.diagnostic_status == "SUCCESS")
        for w in adv.workers:
            self.assertLessEqual(_rank(adv), _rank(w))
        for d, w in zip(diag.workers, adv.workers):
            self.assertEqual(w.category == "HISTORICAL_SUCCESS", d.reason_codes == ("SUCCESS_CONSISTENT",))
            if w.category == "HISTORICAL_SUCCESS":
                self.assertEqual(d.native_state, "SUCCESS")


# ---------------------------------------------------------------------------
class NonSuccessNeverUpgradedTests(_ChainCase):
    def test_forced_non_success_status_over_clean_workers_stays_native(self):
        for status in NON_SUCCESS_STATUSES:
            with self.subTest(status):
                diag, adv = _pairs_chain([_success("a"), _success("b")], status=status)
                self.assertChainInvariants(diag, adv)
                self.assertEqual(diag.diagnostic_status, status)
                self.assertIn("AGGREGATE_CONTRADICTION", diag.reason_codes)
                self.assertEqual(adv.category, "EVIDENCE_CONFLICT")
                self.assertEqual(adv.responsibility, "UNKNOWN")
                self.assertTrue(all(w.category == "HISTORICAL_SUCCESS" for w in adv.workers))

    def test_genuine_non_success_pipelines_keep_status_and_need_review(self):
        cases = {
            "FAILED": [_success("a"), _named("failed_non_transient", "b")],
            "BLOCKED": [_success("a"), _named("preflight", "b")],
            "PARTIAL": [_success("a"), (_summary("b", state="PARTIAL", reason="X"),
                                        _result("b", state="PARTIAL", code="X", state_reason="X"))],
            "CANCELLED": [_success("a"), _named("cancelled_dependent", "b")],
            "INCOMPLETE": [_success("a"), _named("retry_wait", "b")],
        }
        for status, pairs in cases.items():
            with self.subTest(status):
                diag, adv = _pairs_chain(pairs)
                self.assertEqual(diag.native_status, status)
                self.assertChainInvariants(diag, adv)
                self.assertEqual(diag.diagnostic_status, status)
                self.assertEqual(adv.native_status, status)
                self.assertNotIn("AGGREGATE_CONTRADICTION", diag.reason_codes)
                self.assertEqual(adv.workers[0].category, "HISTORICAL_SUCCESS")
                self.assertNotEqual(adv.workers[1].category, "HISTORICAL_SUCCESS")

    def test_running_and_draining_with_clean_workers_are_not_success(self):
        for status in ("RUNNING", "DRAINING"):
            with self.subTest(status):
                diag, adv = _pairs_chain([_success("a")], status=status)
                self.assertChainInvariants(diag, adv)
                self.assertEqual(diag.diagnostic_status, status)
                self.assertNotIn("AGGREGATE_CONTRADICTION", diag.reason_codes)
                self.assertEqual(adv.reasons, ("EVIDENCE_UNPROVEN",))
                self.assertEqual(adv.category, "EVIDENCE_GAP")

    def test_future_or_authorizing_pipeline_statuses_are_unknown(self):
        for status in ("MERGED", "CERTIFIED", "APPROVED", "success", "SUCCESS ", 1, None, ["SUCCESS"]):
            with self.subTest(status=status):
                pr = _pipeline([_summary("a")])
                pr["status"] = status
                diag, adv = _chain(pr, {"a": _result("a")})
                self.assertChainInvariants(diag, adv)
                self.assertEqual(diag.diagnostic_status, fi.DIAGNOSTIC_UNKNOWN)
                self.assertEqual(adv.category, "EVIDENCE_INVALID")
                self.assertEqual(adv.responsibility, "UNKNOWN")
                self.assertIn(adv.native_status, (None, ra.UNRECOGNIZED))


class SuccessDegradationTests(_ChainCase):
    def _assert_unverified(self, diag, adv, *codes):
        self.assertChainInvariants(diag, adv)
        self.assertEqual(diag.native_status, "SUCCESS")
        self.assertEqual(diag.diagnostic_status, fi.DIAGNOSTIC_UNVERIFIED)
        self.assertNotEqual(adv.category, "HISTORICAL_SUCCESS")
        self.assertNotIn("SUCCESS_CONSISTENT", diag.reason_codes)
        for code in codes:
            self.assertIn(code, diag.reason_codes)
            self.assertIn(code, adv.reasons)

    def test_baseline_clean_success_is_only_historical(self):
        diag, adv = _pairs_chain([_success("a"), _success("b"), _success("c")])
        self.assertChainInvariants(diag, adv)
        self.assertEqual(diag.diagnostic_status, "SUCCESS")
        self.assertEqual((adv.category, adv.responsibility, adv.reasons),
                         ("HISTORICAL_SUCCESS", "NONE", ("SUCCESS_CONSISTENT",)))

    def test_missing_worker_result_degrades(self):
        pr = _pipeline([_summary("a"), _summary("b")])
        diag, adv = _chain(pr, {"a": _result("a")})
        self._assert_unverified(diag, adv, "MISSING_WORKER_RESULT", "EVIDENCE_MISSING")
        self.assertEqual(diag.missing_worker_ids, ("b",))
        self.assertEqual(adv.category, "EVIDENCE_GAP")
        self.assertEqual([w.category for w in adv.workers], ["HISTORICAL_SUCCESS", "EVIDENCE_GAP"])

    def test_extra_or_unidentified_worker_result_degrades(self):
        pr = _pipeline([_summary("a")])
        for extra in ({"ghost": _result("ghost")}, {"../escape": None}, {7: _result("a")}):
            with self.subTest(extra=sorted(map(str, extra))):
                diag, adv = _chain(pr, {"a": _result("a"), **extra})
                self._assert_unverified(diag, adv, "EXTRA_WORKER_RESULT")
                self.assertEqual(len(diag.workers), 1)
                self.assertEqual(len(diag.extra_worker_ids) + diag.unidentified_extra_results, 1)
                self.assertNotIn("../escape", fi.canonical_json(diag) + ra.canonical_json(adv))

    def test_contradicting_aggregates_degrade(self):
        tampers = {
            "workers_total": lambda p: p.update(workers_total=3),
            "success": lambda p: p.update(success=1),
            "failed": lambda p: p.update(failed=1),
            "state_counts": lambda p: p["state_counts"].update(SUCCESS=5),
            "state_counts_type": lambda p: p.update(state_counts=["SUCCESS", "SUCCESS"]),
            "auth_count": lambda p: p.update(blocked_provider_auth=1),
        }
        for name, tamper in tampers.items():
            with self.subTest(name):
                pr = _pipeline([_summary("a"), _summary("b")])
                tamper(pr)
                diag, adv = _chain(pr, {"a": _result("a"), "b": _result("b")})
                self._assert_unverified(diag, adv, "AGGREGATE_CONTRADICTION")
                self.assertEqual(adv.category, "EVIDENCE_CONFLICT")

    def test_summary_result_state_or_reason_conflict_degrades(self):
        variants = {
            "result_failed": _result("b", state="FAILED", code="X"),
            "outcome_failed": _result("b", outcome="FAILED"),
            "reason_differs": _result("b", state_reason="OTHER"),
        }
        for name, result in variants.items():
            with self.subTest(name):
                summary = _summary("b", reason="ORIGINAL") if name == "reason_differs" else _summary("b")
                diag, adv = _pairs_chain([_success("a"), (summary, result)], status="SUCCESS")
                self._assert_unverified(diag, adv, "CONFLICTING_EVIDENCE")
                self.assertEqual(adv.workers[1].category, "EVIDENCE_CONFLICT")

    def test_unproven_success_attempt_mutations_degrade(self):
        mutations = {
            "evidence_incomplete": {"evidence_complete": False},
            "evidence_flag_absent": {"evidence_complete": None},
            "process_not_stopped": {"process_confirmed_stopped": False},
            "process_flag_truthy_string": {"process_confirmed_stopped": "true"},
            "attempt_not_completed": {"status": "TIMEOUT"},
            "work_status_unverified": {"work_status": "UNVERIFIED"},
            "unknown_status_source": {"work_status_source": "PROVIDER_PROSE"},
            "retry_code_lowercase": {"retry_decision": "NONE:success"},
            "retry_code_other": {"retry_decision": "NONE:SKIPPED"},
            "retry_absent": {"retry_decision": None},
            "fallback_decision": {"retry_decision": "FALLBACK:codex"},
        }
        for name, over in mutations.items():
            with self.subTest(name):
                result = _result("b", attempts=[_attempt(**over)])
                diag, adv = _pairs_chain([_success("a"), (_summary("b"), result)])
                self._assert_unverified(diag, adv)
                self.assertNotEqual(adv.workers[1].category, "HISTORICAL_SUCCESS")
                self.assertNotEqual(adv.workers[1].responsibility, "NONE")

    def test_result_level_source_mismatch_with_attempt_degrades(self):
        result = _result("b")
        result["work_status_source"] = "PROVIDER"
        diag, adv = _pairs_chain([_success("a"), (_summary("b"), result)])
        self._assert_unverified(diag, adv, "EVIDENCE_UNPROVEN")

    def test_schema_version_mismatch_degrades(self):
        for version in (0, 2, "1", None, 1.5, [1]):
            with self.subTest(version=version):
                pr = _pipeline([_summary("a")])
                pr["schema_version"] = version
                diag, adv = _chain(pr, {"a": _result("a")})
                self._assert_unverified(diag, adv, "MALFORMED_EVIDENCE")
                self.assertEqual(adv.category, "EVIDENCE_INVALID")


class NoAuthorityDerivationTests(_ChainCase):
    REVIEW = {
        "auth": ("PROVIDER_AUTH_BLOCKED", "HUMAN_REVIEW"),
        "process_unresolved": ("PROCESS_UNRESOLVED", "HUMAN_REVIEW"),
        "quota": ("EXISTING_PROVIDER_QUOTA_WAIT", "RUNNER_NATIVE"),
        "retry_wait": ("EXISTING_RETRY_WAIT", "RUNNER_NATIVE"),
    }

    def test_auth_quota_wait_and_unresolved_carry_no_schedule_or_authority(self):
        for name, (category, responsibility) in self.REVIEW.items():
            with self.subTest(name):
                diag, adv = _pairs_chain([_success("a"), _named(name, "b")])
                self.assertChainInvariants(diag, adv)
                self.assertEqual((adv.workers[1].category, adv.workers[1].responsibility), (category, responsibility))
                self.assertEqual(adv.category, category)
                data = adv.to_dict()
                keys = {k.lower() for k in _keys(data)} - set(ADVISORY_FLAGS)
                for word in SCHEDULE_KEYS:
                    self.assertFalse([k for k in keys if word in k], word)
                text = ra.canonical_json(adv) + fi.canonical_json(diag)
                for leaked in ("2026-10-28T09:01", "until=", "backoff=", "RESET_HINT"):
                    self.assertNotIn(leaked, text)

    def test_auth_block_outranks_any_native_retry_or_wait_decision(self):
        for decision in ("RETRY:TRANSIENT:CLAUDE_ERROR:backoff=30s", "WAIT:PROVIDER_QUOTA_EXHAUSTED:RESET_HINT",
                         "FALLBACK:codex", "NONE:SUCCESS"):
            with self.subTest(decision):
                summary, result = _named("auth", "b")
                result["attempts"][-1]["retry_decision"] = decision
                diag, adv = _pairs_chain([(summary, result)])
                self.assertChainInvariants(diag, adv)
                # BLOCKED_PROVIDER_AUTH is not terminal for the Runner rollup.
                self.assertEqual((diag.native_status, diag.diagnostic_status), ("INCOMPLETE", "INCOMPLETE"))
                self.assertIn("PROVIDER_AUTH_BLOCKED", diag.reason_codes)
                self.assertEqual(adv.category, "PROVIDER_AUTH_BLOCKED")
                self.assertEqual(adv.observation, "REVIEW_PROVIDER_CREDENTIALS")

    def test_unresolved_process_outranks_success_wait_and_auth(self):
        markers = {
            "termination_flag": {"process_termination_unresolved": True},
            "not_confirmed": {"process_confirmed_stopped": False},
            "recovery_unresolved": {"process_recovery": {"resolution": "UNRESOLVED"}},
            "acceptance_unresolved": {"acceptance": {"decision": "PROCESS_UNRESOLVED"}},
        }
        for base in ("success", "quota", "auth"):
            for name, over in markers.items():
                with self.subTest(base=base, marker=name):
                    summary, result = _named(base, "b")
                    result["attempts"][-1].update(over)
                    diag, adv = _pairs_chain([(summary, result)])
                    self.assertChainInvariants(diag, adv)
                    self.assertIn("PROCESS_TERMINATION_UNRESOLVED", diag.reason_codes)
                    self.assertLessEqual(_rank(adv), ra.ADVISORY_PRECEDENCE.index("PROCESS_TERMINATION_UNRESOLVED"))
                    self.assertNotIn(adv.responsibility, ("NONE", "RUNNER_NATIVE"))

    def test_every_wait_beside_any_failure_loses_runner_native_responsibility(self):
        failures = ("failed_non_transient", "auth", "preflight", "acceptance_failed", "checkpoint_failed",
                    "process_unresolved", "partial_evidence", "cancelled_dependent", "interrupted")
        for wait, failure in itertools.product(("quota", "retry_wait"), failures):
            with self.subTest(wait=wait, failure=failure):
                diag, adv = _pairs_chain([_named(wait, "a"), _named(failure, "b")])
                self.assertChainInvariants(diag, adv)
                self.assertEqual(adv.workers[0].responsibility, "RUNNER_NATIVE")
                self.assertNotEqual(adv.responsibility, "RUNNER_NATIVE")
                self.assertNotEqual(adv.observation, "OBSERVE_EXISTING_WAIT")


class RetryDecisionTamperTests(_ChainCase):
    MALFORMED = ("", "retry:TRANSIENT", "RETRY_NOW", "EXECUTE:NOW", "AUTHORIZED:RETRY", " RETRY:TRANSIENT",
                 123, 1.5, True, ["RETRY", "TRANSIENT"], {"kind": "RETRY"})

    def test_malformed_native_retry_decision_opens_no_executable_option(self):
        for state in ("SUCCESS", "FAILED", "RETRY_WAIT", "WAITING_PROVIDER_QUOTA"):
            for raw in self.MALFORMED:
                with self.subTest(state=state, raw=raw):
                    result = _result("b", state=state, code="X", attempts=[_attempt(retry_decision=raw)])
                    diag, adv = _pairs_chain([(_summary("b", state=state), result)])
                    self.assertChainInvariants(diag, adv)
                    worker = adv.workers[0]
                    self.assertEqual(diag.workers[0].retry_decision_kind, fi.UNRECOGNIZED)
                    self.assertEqual(worker.retry_decision_kind, ra.UNRECOGNIZED)
                    self.assertEqual((worker.category, worker.responsibility), ("EVIDENCE_INVALID", "UNKNOWN"))
                    self.assertEqual((adv.category, adv.responsibility), ("EVIDENCE_INVALID", "UNKNOWN"))
                    if isinstance(raw, str) and raw:
                        self.assertNotIn(raw, ra.canonical_json(adv))

    def test_forged_retry_kind_on_real_diagnostic_is_unusable(self):
        for name, kind in (("failed_non_transient", "EXECUTE"), ("failed_non_transient", "RETRY"),
                           ("success", "WAIT"), ("quota", "AUTHORIZED"), ("retry_wait", None)):
            with self.subTest(name=name, kind=kind):
                diag, _ = _pairs_chain([_named(name, "a")])
                forged_worker = dataclasses.replace(diag.workers[0], retry_decision_kind=kind)
                forged = dataclasses.replace(diag, workers=(forged_worker,))
                adv = ra.advise_pipeline(forged)
                self.assertEqual(adv.workers[0].category, "DIAGNOSTIC_UNUSABLE")
                self.assertEqual(adv.category, "DIAGNOSTIC_UNUSABLE")
                self.assertEqual(adv.responsibility, "UNKNOWN")
                for flag in ADVISORY_FLAGS:
                    self.assertIs(getattr(adv, flag), False)

    def test_forged_success_upgrade_of_real_non_success_diagnostic_is_unusable(self):
        for status in NON_SUCCESS_STATUSES:
            with self.subTest(status):
                diag, _ = _pairs_chain([_success("a"), _success("b")], status=status)
                forgeries = (
                    dataclasses.replace(diag, diagnostic_status="SUCCESS"),
                    dataclasses.replace(diag, diagnostic_status="SUCCESS", reason_codes=("SUCCESS_CONSISTENT",),
                                        primary_reason="SUCCESS_CONSISTENT"),
                    dataclasses.replace(diag, native_status="SUCCESS", diagnostic_status="SUCCESS",
                                        reason_codes=("SUCCESS_CONSISTENT",), primary_reason="SUCCESS_CONSISTENT",
                                        workers=diag.workers + diag.workers),
                )
                for forged in forgeries:
                    adv = ra.advise_pipeline(forged)
                    self.assertEqual(adv.category, "DIAGNOSTIC_UNUSABLE")
                    self.assertNotEqual(adv.responsibility, "NONE")


class IdentityAndShapeTests(_ChainCase):
    def test_duplicate_declared_ids_are_kept_and_never_success(self):
        for second in ("success", "failed_non_transient", "quota"):
            with self.subTest(second):
                first = _success("a")
                pairs = [first, _named(second, "a")]
                pr = _pipeline([s for s, _ in pairs])
                diag, adv = _chain(pr, {"a": first[1]})
                self.assertChainInvariants(diag, adv)
                self.assertEqual([w.worker_id for w in diag.workers], ["a", "a"])
                self.assertTrue(all("DUPLICATE_WORKER_ID" in w.reason_codes for w in diag.workers))
                self.assertEqual(len(adv.workers), 2)
                self.assertEqual(adv.category, "EVIDENCE_INVALID")
                self.assertNotEqual(diag.diagnostic_status, "SUCCESS")

    def test_requeued_summary_with_stale_result_is_conflict(self):
        for status in (None, "SUCCESS"):
            with self.subTest(status=status):
                summary = _summary("b", state="QUEUED", result_path=False)
                diag, adv = _pairs_chain([_success("a"), (summary, _result("b"))], status=status)
                self.assertChainInvariants(diag, adv)
                self.assertIn("CONFLICTING_EVIDENCE", diag.workers[1].reason_codes)
                self.assertEqual(adv.workers[1].category, "EVIDENCE_CONFLICT")
                self.assertEqual(adv.category, "EVIDENCE_CONFLICT")
                self.assertNotEqual(diag.diagnostic_status, "SUCCESS")

    def test_requeued_summary_without_result_is_pending_but_absent_key_is_a_gap(self):
        pairs = [_success("a"), (_summary("b", state="QUEUED", result_path=False), None)]
        looked_up, _ = _pairs_chain(pairs)
        pr = _pipeline([s for s, _ in pairs])
        for name, res in (("looked_up_none", {"a": pairs[0][1], "b": None}), ("key_absent", {"a": pairs[0][1]})):
            with self.subTest(name):
                diag, adv = _chain(copy.deepcopy(pr), res)
                self.assertChainInvariants(diag, adv)
                self.assertEqual(diag.diagnostic_status, "INCOMPLETE")
                self.assertNotIn("EVIDENCE_MISSING", diag.workers[1].reason_codes)
                self.assertEqual(adv.workers[1].category, "EXISTING_RUN_IN_PROGRESS")
                if name == "key_absent":
                    self.assertIn("MISSING_WORKER_RESULT", adv.reasons)
                    self.assertEqual(adv.category, "EVIDENCE_GAP")
                else:
                    self.assertEqual(fi.canonical_json(diag), fi.canonical_json(looked_up))
                    self.assertEqual(adv.category, "EXISTING_RUN_IN_PROGRESS")
                    self.assertEqual(adv.responsibility, "RUNNER_NATIVE")

    def test_pipeline_or_worker_identity_mismatch_is_invalid(self):
        mutations = {
            "result_pipeline_id": lambda pr, res: res["b"].update(pipeline_id="night-2"),
            "result_worker_id": lambda pr, res: res["b"].update(worker_id="c"),
            "result_pipeline_id_absent": lambda pr, res: res["b"].pop("pipeline_id"),
            "pipeline_id_unsafe": lambda pr, res: pr.update(pipeline_id="../night-1"),
            "pipeline_id_absent": lambda pr, res: pr.pop("pipeline_id"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                pr = _pipeline([_summary("a"), _summary("b")])
                res = {"a": _result("a"), "b": _result("b")}
                mutate(pr, res)
                diag, adv = _chain(pr, res)
                self.assertChainInvariants(diag, adv)
                self.assertEqual(diag.diagnostic_status, fi.DIAGNOSTIC_UNVERIFIED)
                self.assertEqual(adv.category, "EVIDENCE_INVALID")
                self.assertEqual(adv.responsibility, "UNKNOWN")
                self.assertNotIn("../", ra.canonical_json(adv))

    def test_malformed_top_level_inputs_fail_closed_through_chain(self):
        for pr, res in ((None, {}), ([], {}), ({}, {}), (_pipeline([_summary("a")]), None),
                        (_pipeline([_summary("a")]), [("a", _result("a"))]), (_pipeline([]), {})):
            with self.subTest(pr=type(pr).__name__, res=type(res).__name__):
                diag, adv = _chain(pr, res)
                self.assertChainInvariants(diag, adv)
                self.assertNotEqual(diag.diagnostic_status, "SUCCESS")
                self.assertEqual(adv.category, "EVIDENCE_INVALID")

    def test_one_bad_worker_among_many_successes_dominates_at_its_index(self):
        for name in sorted(set(_fixtures()) - {"success"}):
            with self.subTest(name):
                pairs = [_success(f"w{i}") for i in range(5)]
                pairs.insert(2, _named(name, "bad"))
                diag, adv = _pairs_chain(pairs)
                self.assertChainInvariants(diag, adv)
                self.assertEqual([w.worker_id for w in adv.workers][2], "bad")
                self.assertNotEqual(adv.workers[2].category, "HISTORICAL_SUCCESS")
                self.assertEqual(sum(w.category == "HISTORICAL_SUCCESS" for w in adv.workers), 5)
                self.assertEqual(adv.reasons[0], adv.workers[2].reasons[0])


class ConfidentialityTests(_ChainCase):
    def test_confidential_free_text_never_crosses_either_layer(self):
        leak = "sk-ant-api03-leak-q9Zx"
        summary, result = _named("failed_non_transient", "b")
        summary.update(provider=leak, state_reason=f"CLAUDE_ERROR:{leak}", provider_condition=f"{leak}:x",
                       worker_path=f"{STATE_ROOT}/{leak}")
        result.update(stdout=leak, stderr=f"Bearer {leak}", message=leak, error=leak, prompt=leak,
                      work_order={"body": leak}, metadata={"token": leak, "nested": [leak]},
                      state_reason=f"CLAUDE_ERROR:{leak}", evidence_error=leak, worktree=f"C:/{leak}",
                      acceptance={"decision": "FAILED", "reason": leak}, artifacts=[leak])
        result["attempts"][-1].update(error_message=leak, stdout=leak, evidence_dir=f"{STATE_ROOT}/{leak}",
                                      retry_decision=f"NO_RETRY:NON_TRANSIENT:{leak}", runner_state=f"bearer {leak}",
                                      run_id=leak)
        diag, adv = _pairs_chain([_success("a"), (summary, result)])
        self.assertChainInvariants(diag, adv)
        for text in (fi.canonical_json(diag), ra.canonical_json(adv), repr(diag), repr(adv)):
            for fragment in (leak, "sk-ant", "Bearer", "q9Zx", SECRET, STATE_ROOT, "C:/"):
                self.assertNotIn(fragment, text)

    def test_token_shaped_native_codes_never_reach_the_advisory(self):
        summary = _summary("b", state="FAILED", reason=f"{TOKEN_SHAPED_SECRET}:v")
        result = _result("b", state="FAILED", code=TOKEN_SHAPED_SECRET, state_reason=f"{TOKEN_SHAPED_SECRET}:v",
                         attempts=[_attempt(runner_state=TOKEN_SHAPED_SECRET,
                                            retry_decision=f"NO_RETRY:{TOKEN_SHAPED_SECRET}")])
        diag, adv = _pairs_chain([(summary, result)])
        self.assertChainInvariants(diag, adv)
        self.assertEqual(diag.workers[0].native_code, TOKEN_SHAPED_SECRET)  # bounded native token in 6A only
        self.assertNotIn(TOKEN_SHAPED_SECRET, ra.canonical_json(adv))
        self.assertNotIn(TOKEN_SHAPED_SECRET, repr(adv))
        self.assertEqual(adv.category, "NATIVE_FAILED")

    def test_unsafe_identifiers_carrying_secrets_are_not_echoed(self):
        unsafe = f"{SECRET}/../x"
        pr = _pipeline([_summary("a"), _summary(unsafe)])
        res = {"a": _result("a"), unsafe: _result(unsafe), f"{SECRET} extra": None}
        diag, adv = _chain(pr, res)
        self.assertChainInvariants(diag, adv)
        self.assertEqual(diag.workers[1].worker_id, None)
        self.assertEqual(diag.unidentified_extra_results, 1)
        for text in (fi.canonical_json(diag), ra.canonical_json(adv)):
            self.assertNotIn(SECRET, text)


class DeterminismAndPurityTests(_ChainCase):
    def _mixed(self):
        return [_success("a"), _named("failed_non_transient", "b"), _named("quota", "c"),
                _named("cancelled_dependent", "d")]

    def test_result_mapping_permutations_are_byte_identical_through_chain(self):
        pairs = self._mixed()
        pr = _pipeline([s for s, _ in pairs])
        items = [(s["id"], r) for s, r in pairs] + [("zz", None)]
        expected = None
        for order in itertools.permutations(items):
            diag, adv = _chain(copy.deepcopy(pr), copy.deepcopy(dict(order)))
            got = (fi.canonical_json(diag), ra.canonical_json(adv))
            if expected is None:
                expected = got
                self.assertChainInvariants(diag, adv)
            self.assertEqual(got, expected)

    def test_declared_order_permutations_preserve_per_worker_identity(self):
        pairs = self._mixed()
        res = {s["id"]: r for s, r in pairs}
        base_diag, base_adv = _pairs_chain(pairs)
        by_id = {w.worker_id: ra.canonical_json(w) for w in base_adv.workers}
        for order in itertools.permutations(pairs):
            with self.subTest(order=[s["id"] for s, _ in order]):
                diag, adv = _chain(_pipeline([copy.deepcopy(s) for s, _ in order]), copy.deepcopy(res))
                self.assertEqual([w.worker_id for w in adv.workers], [s["id"] for s, _ in order])
                self.assertEqual({w.worker_id: ra.canonical_json(w) for w in adv.workers}, by_id)
                self.assertEqual((adv.category, adv.reasons, adv.diagnostic_status),
                                 (base_adv.category, base_adv.reasons, base_adv.diagnostic_status))
                self.assertEqual(diag.reason_codes, base_diag.reason_codes)

    def test_chain_never_mutates_runner_inputs_or_source_diagnostic(self):
        pairs = self._mixed() + [_named(n, f"x{i}") for i, n in enumerate(sorted(_fixtures()))]
        pr = _pipeline([s for s, _ in pairs])
        res = {s["id"]: r for s, r in pairs if r is not None}
        pr_before, res_before = copy.deepcopy(pr), copy.deepcopy(res)
        diag = fi.assess_pipeline(pr, res)
        diag_before = fi.canonical_json(diag)
        adv = ra.advise_pipeline(diag)
        self.assertEqual(pr, pr_before)
        self.assertEqual(res, res_before)
        self.assertEqual(fi.canonical_json(diag), diag_before)
        self.assertChainInvariants(diag, adv)

    def test_repeated_and_interleaved_chains_are_deterministic(self):
        scenarios = [self._mixed(), [_success("a")], [_named("auth", "a"), _named("retry_wait", "b")]]

        def run(i):
            diag, adv = _pairs_chain(copy.deepcopy(scenarios[i]))
            return fi.canonical_json(diag), ra.canonical_json(adv)

        first = [run(i) for i in range(len(scenarios))]
        for _ in range(3):
            for i in (2, 0, 1):
                self.assertEqual(run(i), first[i])
        for _, adv_json in first:
            self.assertEqual(json.loads(adv_json)["source_schema"], fi.SCHEMA_PIPELINE)


class StructuredStateTableTests(_ChainCase):
    RETRY_DECISIONS = ("RETRY:TRANSIENT:TIMEOUT:backoff=30s", "WAIT:PROVIDER_QUOTA_EXHAUSTED:RESET_HINT",
                       "FALLBACK:codex", "NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR", "NONE:SUCCESS", "bogus:1")

    def _variants(self):
        """Deterministic table: every Runner worker state x evidence shape x
        pipeline status mode. Built from sorted vocabularies only."""
        rows = []
        for i, state in enumerate(sorted(fi.WORKER_STATES)):
            decision = self.RETRY_DECISIONS[i % len(self.RETRY_DECISIONS)]
            shapes = {
                "full": [(_summary("b", state=state), _result("b", state=state))],
                "no_result": [(_summary("b", state=state), None)],
                "requeued_stale": [(_summary("b", state=state, result_path=False), _result("b", state=state))],
                "outcome_conflict": [(_summary("b", state=state),
                                      _result("b", state=state, outcome="FAILED" if state == "SUCCESS" else "SUCCESS"))],
                f"retry_decision={decision}": [(_summary("b", state=state), _result("b", state=state, attempts=[
                    _attempt(retry_decision=decision)]))],
                "unresolved": [(_summary("b", state=state), _result("b", state=state, attempts=[
                    _attempt(process_confirmed_stopped=False)]))],
                "beside_success": [_success("a"), (_summary("b", state=state), _result("b", state=state))],
            }
            for shape, pairs in shapes.items():
                for mode in ("native", "forced_success"):
                    rows.append((state, shape, mode, pairs))
        return rows

    def test_table_has_at_least_one_hundred_distinct_variants(self):
        rows = self._variants()
        self.assertGreaterEqual(len(rows), 100)
        self.assertEqual(len({(s, sh, m) for s, sh, m, _ in rows}), len(rows))

    def test_every_table_variant_holds_chain_invariants(self):
        for state, shape, mode, pairs in self._variants():
            with self.subTest(state=state, shape=shape, mode=mode):
                diag, adv = _pairs_chain(copy.deepcopy(pairs), status="SUCCESS" if mode == "forced_success" else None)
                self.assertChainInvariants(diag, adv)
                # Only untouched success evidence (the default attempt is
                # `NONE:SUCCESS`) is consistent; every other shape is a gap.
                clean = state == "SUCCESS" and shape in ("full", "beside_success", "retry_decision=NONE:SUCCESS")
                self.assertEqual(diag.diagnostic_status == "SUCCESS", clean)
                if mode == "native" and state != "SUCCESS":
                    self.assertNotEqual(diag.native_status, "SUCCESS")
                    self.assertEqual(diag.diagnostic_status, diag.native_status)
                worker = adv.workers[-1]
                self.assertEqual(worker.category == "HISTORICAL_SUCCESS", clean)
                if state != "SUCCESS":
                    self.assertNotEqual(worker.responsibility, "NONE")


class SuiteHygieneTests(unittest.TestCase):
    def test_this_suite_skips_nothing_and_patches_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest", "mock", "patch", "random",
                     "subprocess", "socket"):
            self.assertNotIn(word, names, word)


if __name__ == "__main__":
    unittest.main()
