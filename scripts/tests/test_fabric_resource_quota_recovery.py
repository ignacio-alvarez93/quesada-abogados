"""FCP-10C-02: governed quota recovery and evidence-failure advisor.

Quota/auth holds are produced by the real `PipelineRunner._hold_for_provider`
(only its persistence is replaced by an in-memory host), classifications by
the real `classify_provider_failure`, worker diagnostics by the real FCP-6
`assess_worker` and verdict lines by the Runner's own `extract_verdict`.
Runner result dictionaries mirror the keys `PipelineRunner._write_result`
persists. Provider ids are opaque labels; nothing is executed, retried,
committed or sent anywhere. Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import itertools
import json
import os
import socket
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_provider_routing_policy as rt
from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_resource_quota_observation as qo
from scripts.ai import fabric_resource_quota_recovery as rq
from scripts.ai import fabric_scheduler_capacity as cap
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_provider_availability as availability
from scripts.ai import runner_providers as providers

MODULE_PATH = Path(rq.__file__)
TEST_PATH = Path(__file__).resolve()
AS_OF = "2026-10-31T12:00:00Z"
OBSERVED = "2026-10-31T11:59:00Z"
HIT = datetime(2026, 10, 31, 11, 59, tzinfo=timezone.utc)
PIPELINE = "pipe-1"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "reservation_held",
             "quota_authority", "purchase_allowed", "remote_api_allowed", "state_mutated", "retry_scheduled",
             "resume_from_derived", "commit_created", "history_rewritten", "checkpoint_consolidated",
             "verdict_upgraded")
QUOTA_RESET_MESSAGE = "You've hit your session limit - resets 3pm (Etc/UTC)"
QUOTA_MESSAGE = "quota exceeded for this account"
AUTH_MESSAGE = "Not logged in - please run /login"
WORK_PRODUCT_PATH = "C:/private/evidence/w1/attempt-1/work_product.json"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
COMMIT_1 = "1" * 40
COMMIT_2 = "2" * 40
COMMIT_X = "9" * 40


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


class _PersistenceHost:
    """Replaces only the Runner's disk writes; the transition table and the
    hold logic exercised are the Runner's own."""

    def __init__(self):
        self.tz_lookup = lambda name: timezone.utc
        self.results = []

    def _transition(self, worker, new, reason=None):
        if new not in rp._ALLOWED_TRANSITIONS[worker.worker_state]:
            raise AssertionError(f"illegal transition {worker.state} -> {new.value}")
        worker.state, worker.state_reason = new.value, reason

    def _write_result(self, worker, payload):
        self.results.append(payload)


def _payload(worker, attempt, extra) -> dict:
    """The keys `PipelineRunner._write_result` persists (paths omitted)."""
    return {
        "worker_id": worker.spec.id, "pipeline_id": PIPELINE, "state": worker.state,
        "state_reason": worker.state_reason, "provider": worker.active_provider,
        "requested_provider": worker.spec.provider, "mode": worker.spec.mode,
        "runner_state": attempt.get("runner_state"), "work_status": attempt.get("work_status"),
        "provider_work_status": attempt.get("provider_work_status"),
        "work_status_source": attempt.get("work_status_source"), "attempts": [attempt], "fallbacks_used": [],
        **extra,
    }


def runner_hold(message=QUOTA_RESET_MESSAGE, worker_id="w1", provider="alpha", now=HIT, reconciliation=None):
    """(WorkerRuntime, result.json) of a real Runner provider hold."""
    spec = rp.WorkerSpec(id=worker_id, worktree=".", work_order="wo.md", provider=provider, mode="write")
    worker = rp.WorkerRuntime(spec=spec, order=0, state=rp.WorkerState.RUNNING.value)
    attempt = {"attempt": 1, "executed": True, "status": "COMPLETED", "evidence_complete": True,
               "process_confirmed_stopped": True, "provider_work_status": None}
    if reconciliation is not None:
        attempt["reconciliation"] = reconciliation
    host = _PersistenceHost()
    condition = availability.classify_provider_failure(message=message)
    rp.PipelineRunner._hold_for_provider(host, worker, attempt, condition, None, now)
    return worker, _payload(worker, attempt, host.results[-1])


def success_result(worker_id="w1", provider="alpha", source="RUNNER_ACCEPTANCE", raw="UNVERIFIED",
                   decision="NONE:SUCCESS", state_reason=None, reconciliation=None):
    spec = rp.WorkerSpec(id=worker_id, worktree=".", work_order="wo.md", provider=provider, mode="write")
    worker = rp.WorkerRuntime(spec=spec, order=0, state=rp.WorkerState.SUCCESS.value, state_reason=state_reason)
    attempt = {"attempt": 1, "executed": True, "status": "COMPLETED", "evidence_complete": True,
               "process_confirmed_stopped": True, "runner_state": "SUCCESS", "work_status": "SUCCESS",
               "provider_work_status": raw, "work_status_source": source, "retry_decision": decision}
    if reconciliation is not None:
        attempt["reconciliation"] = reconciliation
    return _payload(worker, attempt, {"outcome": "SUCCESS"})


def ended_result(state, code, worker_id="w1", provider="alpha", **attempt_fields):
    spec = rp.WorkerSpec(id=worker_id, worktree=".", work_order="wo.md", provider=provider, mode="write")
    worker = rp.WorkerRuntime(spec=spec, order=0, state=state, state_reason=code)
    attempt = {"attempt": 1, "executed": True, "status": "COMPLETED", "evidence_complete": True,
               "process_confirmed_stopped": True, "retry_decision": f"NO_RETRY:{code}"}
    attempt.update(attempt_fields)
    return _payload(worker, attempt, {"outcome": state, "code": code})


def summary_of(result) -> dict:
    return {"id": result["worker_id"], "provider": result["provider"], "state": result["state"],
            "state_reason": result["state_reason"], "result_path": "workers/x/result.json"}


def evidence(result, provider="alpha", provider_text=None, auditor_text="VERDICT=PASS", **kw):
    """WorkerEvidence carrying the diagnostic the caller's own real FCP-6
    `assess_worker` produces for exactly these records."""
    fields = dict(worker_id=result["worker_id"] if isinstance(result, dict) else "w1", provider_id=provider,
                  result=result, summary=summary_of(result) if isinstance(result, dict) else None,
                  pipeline_id=PIPELINE, provider_verdict_text=provider_text, auditor_verdict_text=auditor_text)
    fields.update(kw)
    if "diagnostic" not in kw:
        fields["diagnostic"] = fi.assess_worker(fields["worker_id"], fields["result"],
                                                pipeline_id=fields["pipeline_id"], summary=fields["summary"])
    return rq.WorkerEvidence(**fields)


def router_record(provider="alpha", availability_state="NONE", capacity="AVAILABLE", evidence_id=None,
                  observed=OBSERVED):
    facts = rt.ProviderFacts(provider_id=provider, probe_available=True, policy_mode="write",
                             policy_allow_shell=False, policy_supported=True, capabilities=("READ_FILES",),
                             availability=availability_state, capacity=capacity)
    return qo.SourceRecord(evidence_id=evidence_id or f"ev-router-{provider}", source=qc.SOURCE_ROUTER_PROVIDER_FACTS,
                           provider_id=provider, payload=facts, observed_at_utc=observed)


def capacity_record(provider="alpha", availability_state="NONE", capacity="AVAILABLE", slots=2, observed=OBSERVED):
    facts = cap.ProviderCapacityFacts(provider_id=provider, availability=availability_state, capacity=capacity,
                                      proven_slots=slots, observed_at_utc=observed)
    return qo.SourceRecord(evidence_id=f"ev-cap-{provider}", source=qc.SOURCE_SCHEDULER_CAPACITY_FACTS,
                           provider_id=provider, payload=facts)


def wait_record(worker, provider="alpha"):
    return qo.SourceRecord(evidence_id=f"ev-wait-{worker.spec.id}", source=qc.SOURCE_RUNNER_PROVIDER_WAIT,
                           provider_id=provider, payload=worker)


def condition_record(message, provider="alpha", observed=OBSERVED):
    return qo.SourceRecord(evidence_id=f"ev-cond-{provider}", source=qc.SOURCE_RUNNER_PROVIDER_CONDITION,
                           provider_id=provider, payload=availability.classify_provider_failure(message=message),
                           observed_at_utc=observed)


def available(provider="alpha", observed=OBSERVED):
    return (router_record(provider, observed=observed), capacity_record(provider, observed=observed))


def quota_request(*records, as_of=AS_OF, **kw):
    return qo.ObservationRequest(request_id="obs-1", as_of_utc=as_of, records=records, **kw)


def request(records=(), workers=(), as_of=AS_OF, quota_kw=None, **kw):
    fields = dict(request_id="rec-1", quota_request=quota_request(*records, as_of=as_of, **(quota_kw or {})),
                  workers=tuple(workers))
    fields.update(kw)
    return rq.RecoveryRequest(**fields)


def advise(records=(), workers=(), **kw):
    return rq.advise_recovery(request(records, workers, **kw))


# -- composite fixtures ------------------------------------------------------

def component(component_id, commit, *products):
    return rq.ComponentProduct(component_id=component_id, commit_sha=commit, products=tuple(products))


def suite_run(suite, commit=COMMIT_X, **kw):
    fields = dict(suite=suite, suite_id=f"suite-{suite.lower()}", commit_sha=commit, ran=120, failures=0, errors=0,
                  skipped=0, expected_failures=0, unexpected_successes=0, complete=True)
    fields.update(kw)
    return rq.SuiteRunEvidence(**fields)


def direction_act(evidence_, **kw):
    """The Direction act a citation names, bound to `evidence_` as given."""
    fields = dict(authorization_id=evidence_.direction_authorization_id, composite_commit_sha=COMMIT_X,
                  evidence_fingerprint=rq.composite_evidence_fingerprint(evidence_) or SHA_C,
                  attestation_id="host-act-1", authorized_at_utc=OBSERVED)
    fields.update(kw)
    return rq.DirectionAuthorization(**fields)


def composite(attest=True, authorization="dir-auth-1", act=False, **kw):
    fields = dict(
        components=(component("w1", COMMIT_1, ("scripts/ai/mod_a.py", SHA_A)),
                    component("w2", COMMIT_2, ("scripts/tests/test_mod_a.py", SHA_B))),
        composite_commit_sha=COMMIT_X,
        composite_products=(("scripts/ai/mod_a.py", SHA_A), ("scripts/tests/test_mod_a.py", SHA_B)),
        observed_tree=(("scripts/tests/test_mod_a.py", SHA_B), ("scripts/ai/mod_a.py", SHA_A)),
        test_runs=(suite_run(rq.SUITE_GLOBAL), suite_run(rq.SUITE_HISTORICAL)),
        direction_authorization_id=authorization,
    )
    fields.update(kw)
    evidence_ = rq.CompositeRecoveryEvidence(**fields)
    if attest:
        attestation = rq.HostAttestation(attestation_id="host-act-1", composite_commit_sha=COMMIT_X,
                                         evidence_fingerprint=rq.composite_evidence_fingerprint(evidence_) or SHA_C,
                                         attested_at_utc=OBSERVED)
        evidence_ = dataclasses.replace(evidence_, attestation=attestation)
    if act:
        evidence_ = dataclasses.replace(evidence_, direction_authorization=direction_act(evidence_))
    return evidence_


def clean_workers():
    return (evidence(success_result("w1")), evidence(success_result("w2")))


def advise_composite(evidence_=None, workers=None, records=None):
    return advise(available() if records is None else records,
                  clean_workers() if workers is None else workers,
                  composite=composite() if evidence_ is None else evidence_)


class RecoveryTestBase(unittest.TestCase):
    def assertRefused(self, advice, *codes):
        self.assertEqual(advice.outcome, rq.REFUSED)
        for code in codes:
            self.assertIn(code, advice.request_reasons)
        self.assertEqual((advice.request_id, advice.request_fingerprint, advice.as_of_utc, advice.providers,
                          advice.workers, advice.composite, advice.evidence_ids), (None, None, None, (), (), None, ()))

    def assertComposite(self, advice, *codes):
        self.assertEqual(advice.composite.outcome, rq.COMPOSITE_BLOCKED)
        for code in codes:
            self.assertIn(code, advice.composite.reasons)
        self.assertEqual(advice.outcome, rq.BLOCKED)
        self.assertIn(rq.COMPOSITE_CRITERIA_NOT_MET, advice.reasons)


# ---------------------------------------------------------------------------
class VerdictClassifierTests(RecoveryTestBase):
    def test_only_exact_explicit_pass_tokens_read_pass(self):
        for text in ("VERDICT=PASS", "summary\nVERDICT = PASSED\n", "**VERDICT=SUCCESS**", "> VERDICT=pass"):
            reading = rq.classify_explicit_verdict(text)
            self.assertEqual((reading.verdict, reading.reasons, reading.candidates), (rq.VERDICT_PASS, (), 1), text)

    def test_runner_negative_readings_stay_negative(self):
        cases = {"VERDICT=BLOCKED": rq.VERDICT_BLOCKED, "VERDICT=FAIL": rq.VERDICT_FAIL,
                 "VERDICT=NOT_READY": rq.VERDICT_FAIL, "VERDICT=PASS_BLOCKED:x": rq.VERDICT_BLOCKED,
                 "VERDICT=PARTIAL": rq.VERDICT_PARTIAL, "VERDICT=FAILED_SAFETY": rq.VERDICT_FAIL}
        for text, expected in cases.items():
            self.assertEqual(rq.classify_explicit_verdict(text).verdict, expected, text)
            status, _, _, _ = providers.extract_verdict(text)
            self.assertNotEqual(status, providers.WorkStatus.SUCCESS, text)

    def test_non_explicit_positive_tokens_are_never_pass(self):
        for text in ("VERDICT=READY", "VERDICT=OK", "VERDICT=PASS_WITH_NOTES", "VERDICT=DONE"):
            self.assertEqual(providers.extract_verdict(text)[0], providers.WorkStatus.SUCCESS, text)
            reading = rq.classify_explicit_verdict(text)
            self.assertEqual((reading.verdict, reading.reasons), (rq.VERDICT_UNVERIFIED, (rq.VERDICT_NOT_EXPLICIT,)))
        reading = rq.classify_explicit_verdict("VERDICT=MAYBE")
        self.assertEqual((reading.verdict, reading.reasons), (rq.VERDICT_UNVERIFIED, (rq.VERDICT_UNRECOGNIZED,)))
        self.assertEqual(rq.classify_explicit_verdict("VERDICT=UNVERIFIED").verdict, rq.VERDICT_UNVERIFIED)

    def test_disagreeing_lines_are_ambiguous_never_the_last_or_best(self):
        for text in ("VERDICT=PASS\nVERDICT=BLOCKED", "VERDICT=BLOCKED\nVERDICT=PASS", "VERDICT=PASS\nVERDICT=READY",
                     "VERDICT=FAIL\nVERDICT=PARTIAL"):
            reading = rq.classify_explicit_verdict(text)
            self.assertEqual(reading.verdict, rq.VERDICT_AMBIGUOUS, text)
            self.assertIn(rq.VERDICT_CONFLICTING, reading.reasons)
        self.assertEqual(rq.classify_explicit_verdict("VERDICT=PASS\nVERDICT=PASS").verdict, rq.VERDICT_PASS)

    def test_absent_prose_and_malformed_texts_are_never_pass(self):
        self.assertEqual(rq.classify_explicit_verdict(None), rq.VerdictReading(rq.VERDICT_ABSENT, (), 0))
        prose = "The work order says VERDICT=PASS once all tests pass; they did."
        self.assertEqual(rq.classify_explicit_verdict(prose).reasons, (rq.VERDICT_NOT_FOUND,))
        for bad in (b"VERDICT=PASS", 1, ["VERDICT=PASS"], "VERDICT=PASS\n" + "x" * rq.MAX_VERDICT_TEXT_CHARS):
            reading = rq.classify_explicit_verdict(bad)
            self.assertEqual((reading.verdict, reading.reasons), (rq.VERDICT_UNVERIFIED, (rq.VERDICT_TEXT_MALFORMED,)))
        text = "secret-ish note sk-abcdefghijkl\nVERDICT=PASS"
        self.assertNotIn("sk-", json.dumps(rq.classify_explicit_verdict(text).to_dict()))

    def test_readings_refuse_overclaims(self):
        for kwargs in (dict(verdict=rq.VERDICT_PASS, reasons=(rq.VERDICT_NOT_FOUND,), candidates=1),
                       dict(verdict=rq.VERDICT_PASS, reasons=(), candidates=0),
                       dict(verdict=rq.VERDICT_AMBIGUOUS, reasons=(), candidates=2),
                       dict(verdict="GREEN", reasons=(), candidates=1)):
            with self.assertRaises(ValueError):
                rq.VerdictReading(**kwargs)


# ---------------------------------------------------------------------------
class QuotaRecoveryTests(RecoveryTestBase):
    def test_future_reset_hint_is_a_verified_cooldown_owned_by_the_runner(self):
        worker, result = runner_hold()
        advice = advise((wait_record(worker),), (evidence(result, auditor_text=None),))
        view = advice.provider("alpha")
        self.assertEqual((view.recovery, view.status, view.actor, view.action),
                         (rq.COOLDOWN_PENDING, rq.WAITING, rq.ACTOR_RUNNER, rq.AWAIT_RUNNER_ELIGIBILITY))
        self.assertEqual((view.next_eligible_utc, view.eligibility_source),
                         (worker.provider_wait["next_eligible_utc"].replace("+00:00", "Z"), "RESET_HINT"))
        self.assertEqual(view.reasons, (rq.COOLDOWN_VERIFIED_PENDING,))
        self.assertEqual(advice.outcome, rq.WAITING)
        self.assertEqual(advice.worker("w1").action, rq.AWAIT_RUNNER_QUOTA_REEVALUATION)

    def test_backoff_probe_cooldown_is_echoed_as_the_runner_computed_it(self):
        worker, result = runner_hold(message=QUOTA_MESSAGE)
        view = advise((wait_record(worker),), (evidence(result),)).provider("alpha")
        self.assertEqual((view.recovery, view.eligibility_source), (rq.COOLDOWN_PENDING, "BACKOFF_PROBE"))
        self.assertEqual(view.next_eligible_utc, "2026-10-31T12:04:00Z")

    def test_elapsed_eligibility_is_never_a_recovery_inferred_from_the_clock(self):
        worker, result = runner_hold(now=datetime(2026, 10, 31, 14, 59, 30, tzinfo=timezone.utc))
        for as_of, age in (("2026-10-31T15:05:00Z", 900), ("2026-11-01T14:00:00Z", 86400)):
            advice = advise((wait_record(worker),), (evidence(result),), as_of=as_of,
                            quota_kw={"max_evidence_age_seconds": age})
            view = advice.provider("alpha")
            self.assertEqual((view.recovery, view.action), (rq.RECOVERY_UNCONFIRMED, rq.OBSERVE_RUNNER_QUOTA_PROBE))
            self.assertEqual(view.availability, "QUOTA_WAIT")
            self.assertNotEqual(advice.outcome, rq.CLEAR)

    def test_quota_without_runner_eligibility_is_unknown(self):
        advice = advise((condition_record(QUOTA_RESET_MESSAGE),))
        view = advice.provider("alpha")
        self.assertEqual((view.recovery, view.status), (rq.PROVIDER_UNKNOWN, rq.UNKNOWN))
        self.assertIn(rq.ELIGIBILITY_UNOBSERVED, view.reasons)
        self.assertIsNone(view.next_eligible_utc)

    def test_auth_block_requires_a_human_and_is_never_retryable(self):
        worker, result = runner_hold(message=AUTH_MESSAGE)
        advice = advise((wait_record(worker),), (evidence(result),))
        view = advice.provider("alpha")
        self.assertEqual((view.recovery, view.actor, view.action),
                         (rq.AUTH_BLOCKED, rq.ACTOR_HUMAN, rq.RESTORE_PROVIDER_AUTH))
        self.assertEqual(advice.worker("w1").action, rq.RESTORE_PROVIDER_AUTH)
        self.assertEqual(advice.outcome, rq.BLOCKED)
        self.assertFalse(advice.auto_retry_allowed or advice.retry_scheduled)

    def test_observed_availability_with_corroborated_work_is_clear_not_a_permit(self):
        advice = advise(available(), (evidence(success_result()),))
        self.assertEqual(advice.provider("alpha").recovery, rq.AVAILABLE_OBSERVED)
        self.assertEqual(advice.outcome, rq.CLEAR)
        self.assertEqual(advice.evidence_ids, ("ev-cap-alpha", "ev-router-alpha"))
        self.assertFalse(advice.dispatch_allowed or advice.authorizes_action or advice.certified)

    def test_observed_availability_contradicted_by_an_fcp6_quota_wait_is_unknown(self):
        _worker, result = runner_hold()
        advice = advise(available(), (evidence(result),))
        view = advice.provider("alpha")
        self.assertEqual(view.recovery, rq.PROVIDER_UNKNOWN)
        self.assertIn(rq.DIAGNOSTIC_CONTRADICTS_OBSERVATION, view.reasons)
        auth_worker, auth_result = runner_hold(message=AUTH_MESSAGE)
        self.assertEqual(advise(available(), (evidence(auth_result),)).provider("alpha").recovery, rq.AUTH_BLOCKED)

    def test_stale_transient_or_missing_evidence_is_unknown(self):
        stale = advise(available(observed="2026-10-31T10:00:00Z"), (evidence(success_result()),))
        self.assertEqual(stale.provider("alpha").recovery, rq.PROVIDER_UNKNOWN)
        self.assertIn(rq.QUOTA_EVIDENCE_DOUBT, stale.provider("alpha").reasons)
        transient = advise((condition_record("HTTP 429 too many requests"),)).provider("alpha")
        self.assertIn(rq.CONDITION_UNRESOLVED, transient.reasons)
        missing = advise(available(), (evidence(success_result("w9", provider="beta"), provider="beta"),))
        self.assertEqual(missing.provider("beta").reasons, (rq.QUOTA_EVIDENCE_MISSING,))
        self.assertEqual(missing.outcome, rq.UNKNOWN)
        self.assertEqual(advise().outcome, rq.UNKNOWN)
        self.assertEqual(advise().reasons, (rq.NO_EVIDENCE,))

    def test_declared_deadline_turns_holds_into_a_human_window_decision(self):
        worker, result = runner_hold()  # eligible 15:01Z
        cases = (("2026-10-31T12:00:00Z", rq.DEADLINE_REACHED), ("2026-10-31T15:00:00Z",
                                                                 rq.DEADLINE_PRECEDES_ELIGIBILITY))
        for deadline, reason in cases:
            view = advise((wait_record(worker),), (evidence(result),), deadline_utc=deadline).provider("alpha")
            self.assertEqual((view.recovery, view.action), (rq.DEADLINE_BLOCKED, rq.DECIDE_NEW_EXECUTION_WINDOW))
            self.assertIn(reason, view.reasons)
        later = advise((wait_record(worker),), (evidence(result),), deadline_utc="2026-10-31T18:00:00+00:00")
        self.assertEqual((later.provider("alpha").recovery, later.deadline_utc),
                         (rq.COOLDOWN_PENDING, "2026-10-31T18:00:00Z"))
        clear = advise(available(), (evidence(success_result()),), deadline_utc="2026-10-31T11:00:00Z")
        self.assertEqual(clear.provider("alpha").recovery, rq.AVAILABLE_OBSERVED)


# ---------------------------------------------------------------------------
class WorkerOutcomeTests(RecoveryTestBase):
    def test_reuses_fcp6_diagnostics_verbatim(self):
        _worker, result = runner_hold()
        for result_ in (result, success_result(), ended_result("FAILED", "WORK_FAILED")):
            native = fi.assess_worker("w1", result_, pipeline_id=PIPELINE, summary=summary_of(result_))
            view = advise(available(), (evidence(result_),)).worker("w1")
            self.assertEqual((view.diagnostic_reasons, view.native_state), (native.reason_codes, native.native_state))

    def test_forged_foreign_or_unbound_fcp6_diagnostics_are_never_trusted(self):
        failed = ended_result("FAILED", "WORK_FAILED")
        proven = fi.assess_worker("w1", success_result(), pipeline_id=PIPELINE, summary=summary_of(success_result()))
        self.assertEqual(proven.reason_codes, (rq.SUCCESS_CONSISTENT,))
        twin = type("WorkerDiagnostic", (), {"__module__": "elsewhere.runner_failure_intelligence_fake"})
        forged = (
            None, proven.to_dict(), proven,  # a SUCCESS diagnostic paired with a FAILED result
            dataclasses.replace(proven, worker_id="w2"),
            dataclasses.replace(proven, reason_codes=("SUCCESS_CONSISTENT", "NATIVE_FAILED")),
            dataclasses.replace(proven, primary_reason="NATIVE_FAILED"),
            dataclasses.replace(proven, native_state="DONE"), twin(),
        )
        for diagnostic in forged:
            view = advise(available(), (evidence(failed, diagnostic=diagnostic),)).worker("w1")
            self.assertEqual((view.diagnostic_reasons, view.runner_verdict), ((), rq.VERDICT_UNVERIFIED))
            self.assertEqual((view.status, view.action), (rq.UNKNOWN, rq.REVIEW_RUNNER_EVIDENCE))
            self.assertIn(rq.RUNNER_EVIDENCE_INTEGRITY, view.reasons)
            self.assertNotEqual(view.work_verdict, rq.VERDICT_PASS)
        with self.assertRaises(ValueError):
            dataclasses.replace(advise(available(), (evidence(failed),)).worker("w1"), diagnostic_reasons=(),
                                reasons=(rq.RUNNER_WORK_FAILED,))

    def test_real_success_diagnostic_without_result_or_summary_is_integrity_and_blocks(self):
        # F-R5-01: a genuine FCP-6 SUCCESS_CONSISTENT of another run, handed over
        # with no native record at all, used to be trusted as a Runner PASS.
        proven = fi.assess_worker("w1", success_result(), pipeline_id=PIPELINE, summary=summary_of(success_result()))
        self.assertEqual(proven.reason_codes, (rq.SUCCESS_CONSISTENT,))
        orphan = evidence(None, worker_id="w1", summary=None, diagnostic=proven)
        self.assertFalse(rq._diagnostic_ok(proven, orphan))
        view = advise(available(), (orphan,)).worker("w1")
        self.assertEqual((view.diagnostic_reasons, view.runner_verdict), ((), rq.VERDICT_UNVERIFIED))
        self.assertIn(rq.RUNNER_EVIDENCE_INTEGRITY, view.reasons)
        self.assertEqual((view.status, view.action), (rq.UNKNOWN, rq.REVIEW_RUNNER_EVIDENCE))
        advice = advise_composite(composite(act=True), (orphan, evidence(success_result("w2"))))
        self.assertComposite(advice, rq.COMPONENT_EVIDENCE_UNSAFE)
        self.assertTrue(advice.composite.direction_authorization_verified)
        self.assertFalse(advice.checkpoint_consolidated or advice.verdict_upgraded or advice.commit_created)

    def test_success_diagnostic_of_another_attempt_pipeline_or_outcome_never_binds(self):
        proven = fi.assess_worker("w1", success_result(), pipeline_id=PIPELINE, summary=summary_of(success_result()))

        def variant(mutate):
            result_ = success_result()
            mutate(result_)
            return result_

        retried = variant(lambda r: r["attempts"].insert(0, {**r["attempts"][0], "attempt": 0}))
        foreign_pipeline = variant(lambda r: r.update(pipeline_id="pipe-2"))
        coded = variant(lambda r: r.update(code="WORK_FAILED"))
        outcome = variant(lambda r: r.update(outcome="FAILED"))
        incomplete = variant(lambda r: r["attempts"][-1].update(evidence_complete=False))
        unsafe = variant(lambda r: r.update(unauthorized_changed_paths=["scripts/ai/other.py"]))
        cases = (
            evidence(retried, diagnostic=proven), evidence(foreign_pipeline, diagnostic=proven),
            evidence(coded, diagnostic=proven), evidence(outcome, diagnostic=proven),
            evidence(incomplete, diagnostic=proven), evidence(unsafe, diagnostic=proven),
            evidence(success_result(), pipeline_id=None, diagnostic=proven),
            evidence(success_result(), summary=None, diagnostic=proven),  # refs name a summary that is absent
        )
        for ev in cases:
            # Same worker id and same native SUCCESS state: the old check trusted all of these.
            self.assertEqual((ev.worker_id, ev.result["state"], proven.native_state), ("w1", "SUCCESS", "SUCCESS"))
            self.assertFalse(rq._diagnostic_ok(proven, ev))
            view = advise(available(), (ev,)).worker("w1")
            self.assertEqual((view.diagnostic_reasons, view.runner_verdict), ((), rq.VERDICT_UNVERIFIED))
            self.assertIn(rq.RUNNER_EVIDENCE_INTEGRITY, view.reasons)
            self.assertNotEqual(view.work_verdict, rq.VERDICT_PASS)
            advice = advise_composite(composite(act=True), (ev, evidence(success_result("w2"))))
            self.assertComposite(advice, rq.COMPONENT_EVIDENCE_UNSAFE)
        # The same real diagnostic still binds the very records it was produced for.
        self.assertTrue(rq._diagnostic_ok(proven, evidence(success_result(), diagnostic=proven)))

    def test_runner_technical_success_with_provider_textual_blocked_is_divergent(self):
        for text, expected in (("VERDICT=BLOCKED", rq.VERDICT_BLOCKED), ("VERDICT=FAIL", rq.VERDICT_FAIL),
                               ("VERDICT=PASS\nVERDICT=BLOCKED", rq.VERDICT_BLOCKED)):
            view = advise(available(), (evidence(success_result(), provider_text=text),)).worker("w1")
            self.assertEqual(view.runner_verdict, rq.VERDICT_PASS)
            self.assertIn(rq.PROVIDER_VERDICT_DIVERGENT, view.reasons)
            self.assertEqual((view.provider_verdict, view.work_verdict, view.status, view.actor),
                             (expected, expected, rq.BLOCKED, rq.ACTOR_DIRECTION))
        raw = advise(available(), (evidence(success_result(raw="BLOCKED")),)).worker("w1")
        self.assertIn(rq.PROVIDER_VERDICT_DIVERGENT, raw.reasons)

    def test_runner_acceptance_supersedes_only_an_absent_or_unverified_provider_verdict(self):
        for text in (None, "no verdict line", "VERDICT=UNVERIFIED"):
            view = advise(available(), (evidence(success_result(), provider_text=text),)).worker("w1")
            self.assertEqual((view.provider_verdict, view.work_verdict, view.status),
                             (rq.VERDICT_PASS, rq.VERDICT_PASS, rq.CLEAR), text)
        provider_sourced = advise(available(), (evidence(success_result(source="PROVIDER", raw="SUCCESS")),))
        self.assertEqual(provider_sourced.worker("w1").work_verdict, rq.VERDICT_PASS)
        unproven = advise(available(), (evidence(success_result(source="PROVIDER", raw="UNVERIFIED")),))
        self.assertNotEqual(unproven.worker("w1").work_verdict, rq.VERDICT_PASS)

    def test_auditor_blocked_fail_or_ambiguous_is_never_pass(self):
        for text, expected in (("VERDICT=BLOCKED", rq.VERDICT_BLOCKED), ("VERDICT=FAIL", rq.VERDICT_FAIL),
                               ("VERDICT=PASS\nVERDICT=BLOCKED", rq.VERDICT_BLOCKED),
                               ("VERDICT=PARTIAL", rq.VERDICT_BLOCKED)):
            advice = advise(available(), (evidence(success_result(), provider_text="VERDICT=PASS",
                                                   auditor_text=text),))
            view = advice.worker("w1")
            self.assertEqual((view.runner_verdict, view.provider_verdict), (rq.VERDICT_PASS, rq.VERDICT_PASS))
            self.assertEqual(view.work_verdict, expected, text)
            self.assertIn(rq.AUDITOR_VERDICT_NOT_PASS, view.reasons)
            self.assertEqual((view.status, advice.outcome), (rq.BLOCKED, rq.BLOCKED))
            self.assertFalse(advice.verdict_upgraded)

    def test_absent_audit_waits_and_unverified_audit_is_unknown(self):
        absent = advise(available(), (evidence(success_result(), auditor_text=None),))
        view = absent.worker("w1")
        self.assertEqual((view.work_verdict, view.reasons, view.action),
                         (rq.VERDICT_UNVERIFIED, (rq.AUDITOR_VERDICT_ABSENT,), rq.AWAIT_READ_ONLY_AUDIT))
        self.assertEqual(absent.outcome, rq.WAITING)
        unverified = advise(available(), (evidence(success_result(), auditor_text="VERDICT=LGTM"),)).worker("w1")
        self.assertEqual((unverified.status, unverified.reasons), (rq.UNKNOWN, (rq.WORK_UNVERIFIED,)))

    def test_work_verdict_is_monotone_over_every_axis_combination(self):
        texts = (None, "VERDICT=PASS", "VERDICT=FAIL", "VERDICT=BLOCKED", "VERDICT=PARTIAL", "VERDICT=READY",
                 "VERDICT=PASS\nVERDICT=FAIL")
        results = (success_result(), success_result(source="PROVIDER", raw="SUCCESS"),
                   ended_result("FAILED", "WORK_FAILED"), ended_result("BLOCKED", "WORK_BLOCKED"))
        severity = rq.WORK_VERDICTS.index
        for result_, provider_text, auditor_text in itertools.product(results, texts, texts):
            view = advise(available(), (evidence(result_, provider_text=provider_text,
                                                 auditor_text=auditor_text),)).worker("w1")
            for axis in (view.runner_verdict, view.provider_verdict,
                         rq._WORK_VERDICT_OF[view.auditor_reading.verdict]):
                self.assertLessEqual(severity(view.work_verdict), severity(axis))
            if view.work_verdict == rq.VERDICT_PASS:
                self.assertEqual(view.auditor_reading.verdict, rq.VERDICT_PASS)
                self.assertEqual(view.diagnostic_reasons, (rq.SUCCESS_CONSISTENT,))
                self.assertNotIn(view.provider_reading.verdict, rq._NEGATIVE_CLASSES)
            else:
                self.assertTrue(view.reasons)
                self.assertNotEqual(view.status, rq.CLEAR)

    def test_native_runner_continuation_is_reported_never_derived(self):
        reconciliation = {"decision": "PENDING_PROVIDER_CONTINUATION", "prior_attempt": 1,
                          "work_product_path": WORK_PRODUCT_PATH}
        worker, result = runner_hold(reconciliation=reconciliation)
        advice = advise((wait_record(worker),), (evidence(result),))
        view = advice.worker("w1")
        self.assertEqual((view.continuation, view.actor, view.action),
                         (rq.CONTINUATION_NATIVE_PENDING, rq.ACTOR_RUNNER, rq.AWAIT_RUNNER_NATIVE_CONTINUATION))
        text = rq.canonical_json(advice)
        self.assertNotIn("work_product", text)
        self.assertNotIn("private", text)
        self.assertFalse(advice.resume_from_derived or advice.resume_allowed)
        self.assertIsNone(worker.pending_resume_from)

    def test_reconciled_and_unrecognized_continuations(self):
        reconciled = success_result(decision="NONE:SUCCESS:RECONCILED_FROM_PRIOR_ATTEMPT",
                                    state_reason="RECONCILED_FROM_PRIOR_ATTEMPT",
                                    reconciliation={"decision": "RECONCILED_FROM_PRIOR_ATTEMPT"})
        view = advise(available(), (evidence(reconciled),)).worker("w1")
        self.assertEqual((view.continuation, view.status), (rq.CONTINUATION_RECONCILED, rq.CLEAR))
        for odd in ({"decision": "RESUME_NOW"}, "PENDING_PROVIDER_CONTINUATION", {"decision": None}):
            view = advise(available(), (evidence(success_result(reconciliation=odd)),)).worker("w1")
            self.assertEqual((view.continuation, view.status), (rq.CONTINUATION_UNRECOGNIZED, rq.UNKNOWN))

    def test_process_safety_and_interruption_need_a_human(self):
        cases = (
            (ended_result("BLOCKED", "PROVIDER_PROCESS_UNRESOLVED", process_confirmed_stopped=False),
             rq.CONFIRM_PROVIDER_PROCESS_STOPPED),
            (ended_result("BLOCKED", "FAILED_SAFETY"), rq.REVIEW_SAFETY_REFUSAL),
            (ended_result("INTERRUPTED", "INTERRUPTED"), rq.REVIEW_INTERRUPTED_WORK),
        )
        for result_, action in cases:
            view = advise(available(), (evidence(result_),)).worker("w1")
            self.assertEqual((view.status, view.actor, view.action), (rq.BLOCKED, rq.ACTOR_HUMAN, action))

    def test_failed_work_is_for_direction_and_not_recoverable_by_quota(self):
        view = advise(available(), (evidence(ended_result("FAILED", "WORK_FAILED")),)).worker("w1")
        self.assertEqual((view.runner_verdict, view.work_verdict), (rq.VERDICT_FAIL, rq.VERDICT_FAIL))
        self.assertEqual((view.status, view.action), (rq.BLOCKED, rq.REQUEST_DIRECTION))
        self.assertIn(rq.RUNNER_WORK_FAILED, view.reasons)

    def test_corrupt_or_mismatched_runner_evidence_is_unknown(self):
        bad = success_result()
        bad["worker_id"] = "someone-else"
        for ev in (evidence(bad, worker_id="w1"), evidence(None, summary=None), evidence(["not", "a", "mapping"]),
                   evidence(success_result(), provider="beta")):
            records = available() + (available("beta") if ev.provider_id == "beta" else ())
            view = rq.advise_recovery(request(records, (ev,))).worker("w1")
            self.assertEqual((view.status, view.action), (rq.UNKNOWN, rq.REVIEW_RUNNER_EVIDENCE))
        self.assertIn(rq.WORKER_PROVIDER_MISMATCH,
                      advise(available() + available("beta"),
                             (evidence(success_result(), provider="beta"),)).worker("w1").reasons)


# ---------------------------------------------------------------------------
class CompositeRecoveryTests(RecoveryTestBase):
    def test_complete_technical_criterion_without_verified_direction_act_stays_blocked(self):
        advice = advise_composite()
        assessment = advice.composite
        # Every technical criterion holds; only the unverifiable Direction act remains.
        self.assertEqual((assessment.outcome, assessment.reasons),
                         (rq.COMPOSITE_BLOCKED, (rq.DIRECTION_AUTHORIZATION_UNVERIFIED,)))
        self.assertEqual(assessment.component_ids, ("w1", "w2"))
        self.assertEqual(assessment.evidence_fingerprint, rq.composite_evidence_fingerprint(composite()))
        self.assertTrue(assessment.requires_direction_authorization)
        self.assertFalse(assessment.consolidation_performed)
        self.assertEqual(advice.outcome, rq.BLOCKED)
        for flag in ("checkpoint_consolidated", "commit_created", "history_rewritten", "merging_allowed",
                     "authorizes_action"):
            self.assertFalse(getattr(advice, flag), flag)

    def test_path_collision_between_components_blocks(self):
        evidence_ = composite(components=(component("w1", COMMIT_1, ("scripts/ai/mod_a.py", SHA_A)),
                                          component("w2", COMMIT_2, ("scripts/ai/mod_a.py", SHA_A),
                                                    ("scripts/tests/test_mod_a.py", SHA_B))))
        advice = advise_composite(evidence_)
        self.assertComposite(advice, rq.PATH_COLLISION)
        self.assertEqual(advice.composite.collisions, ("scripts/ai/mod_a.py",))

    def test_composite_diff_must_be_exactly_the_union_with_equal_hashes(self):
        extra = composite(composite_products=(("scripts/ai/mod_a.py", SHA_A), ("scripts/tests/test_mod_a.py", SHA_B),
                                              ("scripts/ai/frozen.py", SHA_C)))
        self.assertComposite(advise_composite(extra), rq.DIFF_NOT_UNION_ONLY)
        missing = composite(composite_products=(("scripts/ai/mod_a.py", SHA_A),))
        self.assertComposite(advise_composite(missing), rq.DIFF_NOT_UNION_ONLY)
        changed = composite(composite_products=(("scripts/ai/mod_a.py", SHA_C), ("scripts/tests/test_mod_a.py", SHA_B)))
        self.assertComposite(advise_composite(changed), rq.PRODUCT_HASH_MISMATCH)
        tree = composite(observed_tree=(("scripts/ai/mod_a.py", SHA_A), ("scripts/tests/test_mod_a.py", SHA_C)))
        self.assertComposite(advise_composite(tree), rq.TREE_HASH_MISMATCH)

    def test_global_and_historical_suites_must_be_complete_and_green(self):
        cases = (
            ((suite_run(rq.SUITE_GLOBAL),), rq.TESTS_HISTORICAL_MISSING),
            ((suite_run(rq.SUITE_HISTORICAL),), rq.TESTS_GLOBAL_MISSING),
            ((suite_run(rq.SUITE_GLOBAL), suite_run(rq.SUITE_HISTORICAL, skipped=1)), rq.TESTS_SKIPPED_OR_EXPECTED),
            ((suite_run(rq.SUITE_GLOBAL, expected_failures=1), suite_run(rq.SUITE_HISTORICAL)),
             rq.TESTS_SKIPPED_OR_EXPECTED),
            ((suite_run(rq.SUITE_GLOBAL, unexpected_successes=1), suite_run(rq.SUITE_HISTORICAL)),
             rq.TESTS_SKIPPED_OR_EXPECTED),
            ((suite_run(rq.SUITE_GLOBAL, failures=1), suite_run(rq.SUITE_HISTORICAL)), rq.TESTS_NOT_GREEN),
            ((suite_run(rq.SUITE_GLOBAL, errors=2), suite_run(rq.SUITE_HISTORICAL)), rq.TESTS_NOT_GREEN),
            ((suite_run(rq.SUITE_GLOBAL, complete=False), suite_run(rq.SUITE_HISTORICAL)), rq.TESTS_INCOMPLETE),
            ((suite_run(rq.SUITE_GLOBAL, ran=0), suite_run(rq.SUITE_HISTORICAL)), rq.TESTS_INCOMPLETE),
            ((suite_run(rq.SUITE_GLOBAL, commit=COMMIT_1), suite_run(rq.SUITE_HISTORICAL)), rq.TESTS_NOT_ON_COMPOSITE),
            ((suite_run(rq.SUITE_GLOBAL, ran=True), suite_run(rq.SUITE_HISTORICAL)), rq.TESTS_MALFORMED),
            ([suite_run(rq.SUITE_GLOBAL), suite_run(rq.SUITE_HISTORICAL)], rq.TESTS_MALFORMED),
        )
        for runs, reason in cases:
            self.assertComposite(advise_composite(composite(test_runs=runs)), reason)

    def test_host_attestation_must_bind_commit_and_evidence_fingerprint(self):
        self.assertComposite(advise_composite(composite(attest=False)), rq.HOST_ATTESTATION_MISSING)
        good = composite()
        for changes, reason in (
                (dict(evidence_fingerprint=SHA_C), rq.HOST_ATTESTATION_MISMATCH),
                (dict(composite_commit_sha=COMMIT_1), rq.HOST_ATTESTATION_MISMATCH),
                (dict(attested_at_utc="2026-10-31T12:30:00Z"), rq.HOST_ATTESTATION_INVALID),
                (dict(attestation_id="Host Act"), rq.HOST_ATTESTATION_INVALID)):
            attestation = dataclasses.replace(good.attestation, **changes)
            self.assertComposite(advise_composite(dataclasses.replace(good, attestation=attestation)), reason)
        tampered = dataclasses.replace(good, observed_tree=(("scripts/ai/mod_a.py", SHA_A),
                                                            ("scripts/tests/test_mod_a.py", SHA_C)))
        self.assertComposite(advise_composite(tampered), rq.HOST_ATTESTATION_MISMATCH, rq.TREE_HASH_MISMATCH)
        self.assertComposite(advise_composite(dataclasses.replace(good, attestation={"id": "x"})),
                             rq.HOST_ATTESTATION_INVALID)

    def test_direction_authorization_is_required_and_never_implied(self):
        for authorization in (None, "", "Bad Id", "sk-abcdefghijklmnop"):
            advice = advise_composite(composite(authorization=authorization))
            self.assertComposite(advice, rq.DIRECTION_AUTHORIZATION_MISSING)
            self.assertIsNone(advice.composite.direction_authorization_id)

    def test_components_must_be_bound_safe_audited_and_quota_recovered(self):
        self.assertComposite(advise_composite(workers=(evidence(success_result("w1")),)), rq.COMPONENT_UNBOUND)
        blocked_audit = (evidence(success_result("w1"), auditor_text="VERDICT=BLOCKED"),
                         evidence(success_result("w2")))
        self.assertComposite(advise_composite(workers=blocked_audit), rq.COMPONENT_AUDITOR_NOT_PASS)
        divergent = (evidence(success_result("w1"), provider_text="VERDICT=FAIL"), evidence(success_result("w2")))
        self.assertComposite(advise_composite(workers=divergent), rq.COMPONENT_VERDICT_NOT_PASS)
        unsafe = (evidence(ended_result("BLOCKED", "FAILED_SAFETY", worker_id="w1")), evidence(success_result("w2")))
        self.assertComposite(advise_composite(workers=unsafe), rq.COMPONENT_EVIDENCE_UNSAFE)
        worker, result = runner_hold(worker_id="w2")
        held = advise_composite(workers=(evidence(success_result("w1")), evidence(result)),
                                records=(router_record(), wait_record(worker)))
        self.assertComposite(held, rq.QUOTA_NOT_RECOVERED)
        audits_pending = (evidence(success_result("w1"), auditor_text=None),
                          evidence(success_result("w2"), auditor_text=None))
        # Audits follow the checkpoint: pending audits add no component reason.
        self.assertEqual(advise_composite(workers=audits_pending).composite.reasons,
                         (rq.DIRECTION_AUTHORIZATION_UNVERIFIED,))

    def test_runner_blocked_or_cancelled_components_never_meet_the_criterion(self):
        cases = (
            (ended_result("FAILED", "CHECKPOINT_FAILED", worker_id="w1"), "CHECKPOINT_FAILED"),
            (ended_result("BLOCKED", "PROVIDER_UNAVAILABLE", worker_id="w1"), "PREFLIGHT_REFUSED"),
            (ended_result("CANCELLED", "DEPENDENCY_UNSATISFIED", worker_id="w1"), "DEPENDENCY_CANCELLED"),
            (ended_result("CANCELLED", "CANCELLED", worker_id="w1"), "NATIVE_CANCELLED"),
            (ended_result("FAILED", "EVIDENCE_FINALIZATION_FAILED", worker_id="w1", evidence_complete=False),
             "EVIDENCE_INCOMPLETE"),
            (ended_result("BLOCKED", "WORK_BLOCKED", worker_id="w1"), "NATIVE_BLOCKED"),
            (ended_result("PARTIAL", "WORK_PARTIAL", worker_id="w1"), "PARTIAL_COMPLETION"),
        )
        for result_, code in cases:
            advice = advise_composite(workers=(evidence(result_), evidence(success_result("w2"))))
            self.assertIn(code, advice.worker("w1").diagnostic_reasons)
            self.assertEqual(advice.worker("w1").runner_verdict, rq.VERDICT_BLOCKED, code)
            self.assertComposite(advice, rq.COMPONENT_VERDICT_NOT_PASS)
            self.assertNotEqual(advice.composite.outcome, rq.COMPOSITE_CRITERIA_MET, code)

    def test_unverified_absent_or_pending_components_never_meet_the_criterion(self):
        cases = (
            (evidence(ended_result("RUNNING", "RUNNING", worker_id="w1")), rq.COMPONENT_VERDICT_NOT_PASS),
            (evidence(success_result("w1", source="PROVIDER", raw="UNVERIFIED")), rq.COMPONENT_VERDICT_NOT_PASS),
            (evidence(None, worker_id="w1", summary=None), rq.COMPONENT_EVIDENCE_UNSAFE),
            (evidence(success_result("w1", reconciliation={"decision": "RESUME_NOW"})), rq.COMPONENT_EVIDENCE_UNSAFE),
        )
        for worker, reason in cases:
            advice = advise_composite(workers=(worker, evidence(success_result("w2"))))
            self.assertNotEqual(advice.worker("w1").status, rq.CLEAR)
            self.assertComposite(advice, reason)
        for text in ("VERDICT=BLOCKED", "VERDICT=PARTIAL", "VERDICT=PASS\nVERDICT=BLOCKED", "VERDICT=LGTM"):
            advice = advise_composite(workers=(evidence(success_result("w1"), auditor_text=text),
                                               evidence(success_result("w2"))))
            self.assertNotEqual(advice.worker("w1").work_verdict, rq.VERDICT_PASS, text)
            self.assertComposite(advice, rq.COMPONENT_AUDITOR_NOT_PASS)
            self.assertFalse(advice.verdict_upgraded)

    def test_a_well_formed_direction_authorization_id_is_never_verified_by_itself(self):
        advice = advise_composite()
        self.assertComposite(advice, rq.DIRECTION_AUTHORIZATION_UNVERIFIED)
        self.assertEqual(advice.composite.reasons, (rq.DIRECTION_AUTHORIZATION_UNVERIFIED,))
        self.assertEqual(advice.composite.direction_authorization_id, "dir-auth-1")
        self.assertNotIn(rq.DIRECTION_AUTHORIZATION_MISSING, advice.composite.reasons)
        for forged in (dict(reasons=(), outcome=rq.COMPOSITE_CRITERIA_MET),
                       dict(reasons=(rq.DIRECTION_AUTHORIZATION_MISSING,))):
            with self.assertRaises(ValueError):
                dataclasses.replace(advice.composite, **forged)
        self.assertFalse(advice.authorizes_action or advice.checkpoint_consolidated or advice.commit_created)

    def test_only_a_direction_act_bound_to_the_attested_evidence_verifies_the_citation(self):
        met = advise_composite(composite(act=True))
        self.assertEqual((met.composite.outcome, met.composite.reasons), (rq.COMPOSITE_CRITERIA_MET, ()))
        self.assertTrue(met.composite.direction_authorization_verified)
        self.assertFalse(met.authorizes_action or met.checkpoint_consolidated or met.commit_created)
        good = composite()
        unbound = (
            dict(authorization_id="dir-auth-2"), dict(composite_commit_sha=COMMIT_1),
            dict(evidence_fingerprint=SHA_C), dict(attestation_id="host-act-2"),
            dict(authorization_id="host-act-1"), dict(authorized_at_utc="2026-10-31T11:58:00Z"),
            dict(authorized_at_utc="2026-10-31T12:00:01Z"), dict(authorized_at_utc="soon"),
            dict(authorized_at_utc=None),
        )
        for changes in unbound:
            evidence_ = dataclasses.replace(good, direction_authorization=direction_act(good, **changes))
            if changes.get("authorization_id") == "host-act-1":
                evidence_ = dataclasses.replace(evidence_, direction_authorization_id="host-act-1")
            advice = advise_composite(evidence_)
            self.assertEqual(advice.composite.reasons, (rq.DIRECTION_AUTHORIZATION_UNVERIFIED,), changes)
            self.assertFalse(advice.composite.direction_authorization_verified, changes)
        self.assertComposite(advise_composite(dataclasses.replace(good, direction_authorization={"id": "dir-auth-1"})),
                             rq.DIRECTION_AUTHORIZATION_UNVERIFIED)
        # The act cannot stand in for a missing citation or a missing Host attestation.
        uncited = composite(authorization=None, act=True)
        self.assertComposite(advise_composite(uncited), rq.DIRECTION_AUTHORIZATION_MISSING)
        unattested = composite(attest=False, act=True)
        self.assertEqual(advise_composite(unattested).composite.reasons,
                         (rq.HOST_ATTESTATION_MISSING, rq.DIRECTION_AUTHORIZATION_UNVERIFIED))
        with self.assertRaises(ValueError):
            dataclasses.replace(advise_composite().composite, reasons=(), outcome=rq.COMPOSITE_CRITERIA_MET)
        with self.assertRaises(ValueError):
            dataclasses.replace(met.composite, direction_authorization_verified=False)

    def test_malformed_composite_evidence_blocks_without_a_fingerprint(self):
        for changes in (dict(components=[component("w1", COMMIT_1, ("a.py", SHA_A))]), dict(components=()),
                        dict(composite_products=[("scripts/ai/mod_a.py", SHA_A)]),
                        dict(components=(rq.ComponentProduct("w1", COMMIT_1, [("a.py", SHA_A)]),))):
            advice = advise_composite(composite(attest=False, **changes))
            self.assertComposite(advice, rq.COMPONENTS_MALFORMED)
            self.assertIsNone(advice.composite.evidence_fingerprint)
        for path in ("/etc/passwd", "../outside.py", "scripts\\ai\\x.py", "C:/x.py", "scripts//x.py", "./x.py", ""):
            evidence_ = composite(components=(component("w1", COMMIT_1, (path, SHA_A)),
                                              component("w2", COMMIT_2, ("scripts/tests/test_mod_a.py", SHA_B))))
            self.assertComposite(advise_composite(evidence_), rq.PATH_INVALID)
        self.assertComposite(advise_composite(composite(composite_commit_sha="HEAD")), rq.COMMIT_SHA_INVALID)
        self.assertComposite(advise_composite(composite(composite_commit_sha=COMMIT_1)), rq.COMMIT_DUPLICATE)
        self.assertComposite(advise_composite(composite(components=(
            component("w1", COMMIT_1, ("scripts/ai/mod_a.py", "not-a-hash")),
            component("w2", COMMIT_2, ("scripts/tests/test_mod_a.py", SHA_B))))), rq.PRODUCT_HASH_INVALID)

    def test_evidence_fingerprint_is_order_free_and_excludes_the_binding(self):
        evidence_ = composite(attest=False)
        shuffled = dataclasses.replace(evidence_, components=evidence_.components[::-1],
                                       composite_products=evidence_.composite_products[::-1],
                                       test_runs=evidence_.test_runs[::-1])
        fingerprint = rq.composite_evidence_fingerprint(evidence_)
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(rq.composite_evidence_fingerprint(shuffled), fingerprint)
        self.assertEqual(rq.composite_evidence_fingerprint(composite()), fingerprint)
        self.assertEqual(rq.composite_evidence_fingerprint(composite(authorization=None)), fingerprint)
        self.assertNotEqual(rq.composite_evidence_fingerprint(composite(composite_commit_sha="8" * 40)), fingerprint)
        self.assertIsNone(rq.composite_evidence_fingerprint({"components": ()}))


# ---------------------------------------------------------------------------
class RequestAndOutputTests(RecoveryTestBase):
    def test_invalid_requests_are_explained_refusals_that_echo_nothing(self):
        self.assertRefused(rq.advise_recovery(None), rq.REQUEST_NOT_TYPED)
        self.assertRefused(rq.advise_recovery({"request_id": "x"}), rq.REQUEST_NOT_TYPED)
        cases = (
            (dict(request_id="Bad Id"), rq.REQUEST_ID_INVALID),
            (dict(request_id="sk-abcdefghijklmnop"), rq.ID_SECRET_SHAPED),
            (dict(schema_version=2), rq.SCHEMA_VERSION_UNSUPPORTED),
            (dict(schema_version=True), rq.SCHEMA_VERSION_UNSUPPORTED),
            (dict(deadline_utc="2026-10-31T12:00:00+02:00"), rq.DEADLINE_INVALID),
            (dict(workers=[evidence(success_result())]), rq.WORKERS_MALFORMED),
            (dict(workers=(evidence(success_result()), evidence(success_result()))), rq.WORKER_ID_DUPLICATE),
            (dict(workers=(evidence(success_result(), provider="Alpha!"),)), rq.WORKER_PROVIDER_INVALID),
            (dict(workers=(evidence(success_result(), worker_id="a" * 40),)), rq.ID_SECRET_SHAPED),
            (dict(quota_request=None), rq.QUOTA_REQUEST_REFUSED),
            (dict(composite={"components": ()}), rq.COMPOSITE_NOT_TYPED),
        )
        for changes, code in cases:
            self.assertRefused(rq.advise_recovery(dataclasses.replace(request(available()), **changes)), code)
        self.assertEqual(rq.canonical_json(rq.advise_recovery(None)).count('"request_reasons":["REQUEST_NOT_TYPED"]'),
                         1)

    def test_advice_rederives_everything_it_claims(self):
        advice = advise(available(), (evidence(success_result()),))
        with self.assertRaises(ValueError):
            dataclasses.replace(advice, outcome=rq.WAITING)
        with self.assertRaises(ValueError):
            dataclasses.replace(advice, providers=(), workers=())
        with self.assertRaises(ValueError):
            dataclasses.replace(advice.provider("alpha"), evidence_ids=())
        with self.assertRaises(ValueError):
            dataclasses.replace(advice.provider("alpha"), recovery=rq.COOLDOWN_PENDING)
        worker = advice.worker("w1")
        with self.assertRaises(ValueError):
            dataclasses.replace(worker, auditor_reading=rq.classify_explicit_verdict("VERDICT=BLOCKED"))
        with self.assertRaises(ValueError):
            dataclasses.replace(worker, provider_reading=rq.classify_explicit_verdict("VERDICT=FAIL"))
        with self.assertRaises(ValueError):
            dataclasses.replace(worker, status=rq.BLOCKED)
        met = advise_composite().composite
        with self.assertRaises(ValueError):
            dataclasses.replace(met, direction_authorization_id=None)
        with self.assertRaises(ValueError):
            dataclasses.replace(met, collisions=("scripts/ai/mod_a.py",))
        with self.assertRaises(ValueError):
            dataclasses.replace(advise_composite(composite(authorization=None)).composite, reasons=())

    def test_every_authority_flag_is_false_by_construction(self):
        for advice in (advise(available(), (evidence(success_result()),)), advise_composite(),
                       rq.advise_recovery(None)):
            payload = json.loads(rq.canonical_json(advice))
            for flag in ALL_FLAGS:
                self.assertIs(getattr(advice, flag), False, flag)
                self.assertIs(payload[flag], False, flag)
            self.assertEqual(payload["marker"], rq.RECOVERY_MARKER)
            with self.assertRaises(AttributeError):
                advice.commit_created = True

    def test_canonical_json_is_exact_type_deterministic_and_secret_free(self):
        worker, result = runner_hold()
        req = request((wait_record(worker),), (evidence(result, provider_text="sk-abcdefghijklmnop\nVERDICT=PASS"),))
        first, second = rq.advise_recovery(req), rq.advise_recovery(copy.deepcopy(req))
        self.assertEqual(rq.canonical_json(first), rq.canonical_json(second))
        self.assertEqual(first.request_fingerprint, second.request_fingerprint)
        text = rq.canonical_json(first)
        for leak in ("sk-", "session limit", "resets 3pm", "message"):
            self.assertNotIn(leak, text)
        self.assertEqual(json.loads(text)["schema"], rq.SCHEMA)
        with self.assertRaises(TypeError):
            rq.canonical_json(first.to_dict())


# ---------------------------------------------------------------------------
class PurityTests(RecoveryTestBase):
    def test_advice_never_mutates_inputs_or_runner_state(self):
        worker, result = runner_hold(reconciliation={"decision": "PENDING_PROVIDER_CONTINUATION",
                                                     "work_product_path": WORK_PRODUCT_PATH})
        req = request((wait_record(worker),), (evidence(result),), composite=composite())
        before, runtime_before = copy.deepcopy(req), copy.deepcopy(worker.to_dict())
        rq.advise_recovery(req)
        self.assertEqual(req, before)
        self.assertEqual(worker.to_dict(), runtime_before)
        self.assertEqual(worker.state, rp.WorkerState.WAITING_PROVIDER_QUOTA.value)
        for obj in (req, req.workers[0], req.composite, req.composite.attestation):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(obj, dataclasses.fields(obj)[0].name, "x")

    def test_no_io_processes_network_clock_retry_or_git_entry_points(self):
        worker, result = runner_hold()
        req = request((wait_record(worker),) + available("beta"),
                      (evidence(result), evidence(success_result("w2", provider="beta"), provider="beta")),
                      composite=composite())
        boom = AssertionError("I/O or execution entry point")
        with mock.patch.object(subprocess, "Popen", side_effect=boom), \
                mock.patch.object(subprocess, "run", side_effect=boom), \
                mock.patch.object(builtins, "open", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(os, "stat", side_effect=boom), \
                mock.patch.object(os, "replace", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "_hold_for_provider", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "_refresh", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "_transition", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "_try_prior_work_reconciliation", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "_apply_checkpoint", side_effect=boom), \
                mock.patch.object(rp.DirLease, "try_acquire", side_effect=boom), \
                mock.patch.object(availability, "classify_provider_failure", side_effect=boom), \
                mock.patch.object(availability, "parse_reset_hint", side_effect=boom):
            advice = rq.advise_recovery(req)
            rq.canonical_json(advice)
        self.assertEqual(len(advice.workers), 2)

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_resource_quota_contract", "fabric_resource_quota_observation", "fabric_scheduler_contract",
               "runner_providers")
        self.assertEqual(imported, {"__future__", "collections.abc", "dataclasses", "hashlib", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "DirLease", "ledger.", "_launch", "_start_ready", "_hold_for_provider", "_transition(",
                     "_refresh(", "create_checkpoint", "_apply_checkpoint", "evaluate_resume", "runner_git",
                     "git ", ".now(", "utcnow", "sleep", "while ", "eval(", "exec(", "importlib", "random",
                     "requests.", "urllib", "environ", "classify_provider_failure", "parse_reset_hint",
                     "re.compile", "price", "cost", "currency", "work_product_path", "pending_resume_from",
                     "message_excerpt", "reset_hint", "\"message\"", "stdout", "stderr"):
            self.assertNotIn(word, code, word)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_mutable_module_state_changes(self):
        modules = (rq, qo, qc, fi, providers, availability)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        advise_composite()
        rq.advise_recovery(None)
        rq.classify_explicit_verdict("VERDICT=PASS\nVERDICT=FAIL")
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_reused(self):
        vocabularies = (rq.OUTCOMES, rq.ACTORS, rq.VERDICT_CLASSES, rq.WORK_VERDICTS, rq.READING_REASONS,
                        rq.CONTINUATIONS, rq.PROVIDER_RECOVERIES, rq.ACTIONS, rq.PROVIDER_REASONS, rq.WORKER_REASONS,
                        rq.COMPOSITE_REASONS, rq.ADVICE_REASONS, rq.REQUEST_REASONS, rq.SUITES)
        for vocab in vocabularies:
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        reasons = (rq.PROVIDER_REASONS, rq.WORKER_REASONS, rq.COMPOSITE_REASONS, rq.ADVICE_REASONS,
                   rq.REQUEST_REASONS, rq.READING_REASONS)
        for left, right in itertools.combinations(reasons, 2):
            self.assertFalse(set(left) & set(right), (left, right))
        self.assertEqual(set(rq.PROVIDER_RULES), set(rq.PROVIDER_RECOVERIES))
        self.assertEqual({rule[3] for rule in rq.WORKER_RULES} | {r[2] for r in rq.PROVIDER_RULES.values()}
                         | {rq.NO_ACTION}, set(rq.ACTIONS))
        self.assertEqual(set(rq._CLASS_OF_PROVIDER_WORK_STATUS), {s.value for s in providers.WorkStatus})
        self.assertLessEqual(set(rq._FI_INTEGRITY | rq._FI_FAILED | rq._FI_BLOCKED | set(rq._FI_DIRECT)),
                             set(fi.REASON_PRECEDENCE))
        self.assertIn(rq.SUCCESS_CONSISTENT, fi.REASON_PRECEDENCE)
        self.assertEqual(rq.NO_EVIDENCE, qc.NO_EVIDENCE)
        native = {"PENDING_PROVIDER_CONTINUATION", "RECONCILED_FROM_PRIOR_ATTEMPT", "SKIPPED_WORK_PRODUCT_UNREADABLE"}
        self.assertEqual(set(rq._NATIVE_CONTINUATIONS), native)
        runner_source = Path(rp.__file__).read_text(encoding="utf-8")
        for decision in native:
            self.assertIn(f'"{decision}"', runner_source)

    def test_fcp6_mirror_is_pinned_and_the_frozen_6c04_import_guard_holds(self):
        self.assertEqual(rq.FI_REASON_PRECEDENCE, fi.REASON_PRECEDENCE)
        self.assertEqual(rq.FI_WORKER_STATES, fi.WORKER_STATES)
        self.assertEqual(rq.FI_WORK_STATUS_SOURCES, fi.WORK_STATUS_SOURCES)
        self.assertEqual((rq.FI_UNRECOGNIZED, rq.FI_DIAGNOSTIC_MARKER, rq.FI_SCHEMA_WORKER),
                         (fi.UNRECOGNIZED, fi.DIAGNOSTIC_MARKER, fi.SCHEMA_WORKER))
        self.assertEqual((rq.FI_DIAGNOSTIC_TYPE, rq.FI_MODULE_NAME),
                         (fi.WorkerDiagnostic.__name__, fi.__name__.rsplit(".", 1)[-1]))
        for flag in rq.FI_ZERO_AUTHORITY_FLAGS:
            self.assertIs(getattr(fi.WorkerDiagnostic, flag).fget(None), False)
        for raw in (None, 3, ["X"], "", "SUCCESS", "NO_RETRY:WORK_FAILED", "lower", "A" * 64, "A" * 65, "9X",
                    "X-Y", "SUCCESS ", "WAITING_PROVIDER_QUOTA", "DONE"):
            self.assertEqual(rq._fi_token(raw), fi._token(raw), raw)
            self.assertEqual(rq._fi_state(raw), fi._state_value(raw, set()), raw)
        # The FCP-6C-04 rule, applied to this module: 6A/6B are never imported.
        guarded = {"runner_failure_intelligence", "runner_recovery_advisory"}
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {a.name.rsplit(".", 1)[-1] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                 for a in n.names}
        names |= {n.module.rsplit(".", 1)[-1] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(names & guarded)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
