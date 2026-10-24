"""FCP-3B-2B2 (core): governed promotion executor state machine.

The intent, validation, FCP-3B-2A gate and FCP-3B-2B1 evaluation are REAL
objects built through the existing fixtures (plain git for fixture
construction only). Every host port is an in-memory fake with no write
capability; the single-use ledger is a dict. Every negative test starts from
the complete coherent simulated path and alters one fact. No outcome is ever
live, authorized or production capable.
"""

import ast
import dataclasses
import inspect
import json
import re
import socket
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from scripts.ai import runner_promotion_executor as rpe
from scripts.ai import runner_promotion_human_authorization as rha
from scripts.ai import runner_promotion_pr_gate as rpg
from scripts.tests import test_runner_promotion_human_authorization as thu
from scripts.tests import test_runner_promotion_pr_gate as tpg
from scripts.tests.test_runner_integration import _git_dir_state

MODULE_PATH = Path(rpe.__file__)
WORKFLOW_PATH = MODULE_PATH.parents[2] / ".github" / "workflows" / "fabric-ci.yml"
PR = tpg.PR
REPO = rpg.CANONICAL_REPOSITORY
JOBS = rpg.REQUIRED_CI_JOBS
NOW = thu.NOW
MERGE_SHA = "e" * 40
OTHER_SHA = "d" * 40
DIRECTOR = thu.DIRECTOR
LEAKS = ("secret", "ghp_", "Bearer", "password")
_DEFAULT = object()

HAPPY_CALLS = [
    "acquire_lease", "verify_human_command", "read_fresh_state", "reserve_single_use", "issue_operation_permit",
    "verify_human_command", "read_fresh_state", "consume_single_use", "merge_pull_request", "read_postcondition",
    "finalize_reservation", "release_lease",
]
HOST_METHODS = {"acquire_lease", "release_lease", "verify_human_command", "reserve_single_use",
                "issue_operation_permit", "consume_single_use", "finalize_reservation", "read_fresh_state",
                "merge_pull_request", "read_postcondition"}


def stamp(seconds: int) -> str:
    return (NOW + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def protection(**changes):
    return dataclasses.replace(rpe.BranchProtectionState(
        repository=REPO, base_ref="develop", complete=True, pull_request_required=True,
        required_approving_review_count=1, dismiss_stale_reviews=True, required_check_names=JOBS,
        strict_up_to_date=True, enforce_admins=True, allow_force_pushes=False, allow_deletions=False,
        merge_queue_required=False,
    ), **changes)


class Call:
    """A fake answer computed from the port arguments."""

    def __init__(self, fn):
        self.fn = fn


class Seq:
    """Successive answers for successive calls (the last one repeats)."""

    def __init__(self, *answers):
        self.answers = list(answers)


class FakeLedger:
    """In-memory single-use ledger shared across attempts (replay tests)."""

    def __init__(self):
        self.ops, self.ids, self.finalized = {}, {}, []

    def reserve(self, operation_id, command_id):
        if operation_id in self.ops:
            status = rpe.RESERVATION_ALREADY_CONSUMED if self.ops[operation_id] == "consumed" \
                else rpe.RESERVATION_ALREADY_RESERVED
            return rpe.ReservationReceipt(status, "res-dup", operation_id, command_id)
        rid = f"res-{len(self.ids) + 1}"
        self.ops[operation_id], self.ids[rid] = "reserved", operation_id
        return rpe.ReservationReceipt(rpe.RESERVATION_CREATED, rid, operation_id, command_id)

    def consume(self, reservation_id):
        op = self.ids.get(reservation_id)
        if op is None or self.ops[op] != "reserved":
            return rpe.ConsumptionReceipt(rpe.CONSUMPTION_REFUSED, reservation_id, op or "none")
        self.ops[op] = "consumed"
        return rpe.ConsumptionReceipt(rpe.CONSUMED, reservation_id, op)

    def finalize(self, reservation_id, final_state):
        self.finalized.append((reservation_id, final_state))


class FakeHost:
    """Records every call; has no network, Git or file capability at all."""

    host_kind = rpe.HOST_KIND_IN_MEMORY_SIMULATION

    def __init__(self, answers, ledger):
        self.answers, self.ledger, self.calls = dict(answers), ledger, []

    def _answer(self, name, *args):
        self.calls.append((name, args))
        answer = self.answers[name]
        if isinstance(answer, Seq):
            answer = answer.answers.pop(0) if len(answer.answers) > 1 else answer.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer.fn(*args) if isinstance(answer, Call) else answer

    def acquire_lease(self, operation_id, resource):
        return self._answer("acquire_lease", operation_id, resource)

    def release_lease(self, lease_id):
        return self._answer("release_lease", lease_id)

    def verify_human_command(self, operation_id, repository, pr_number, base_sha, head_sha, action):
        return self._answer("verify_human_command", operation_id, repository, pr_number, base_sha, head_sha, action)

    def read_fresh_state(self, repository, pr_number):
        return self._answer("read_fresh_state", repository, pr_number)

    def reserve_single_use(self, operation_id, command_id):
        return self._answer("reserve_single_use", operation_id, command_id)

    def issue_operation_permit(self, operation_id, reservation_id, command_id):
        return self._answer("issue_operation_permit", operation_id, reservation_id, command_id)

    def consume_single_use(self, reservation_id):
        return self._answer("consume_single_use", reservation_id)

    def merge_pull_request(self, repository, pr_number, expected_head_sha, merge_method, permit_id):
        return self._answer("merge_pull_request", repository, pr_number, expected_head_sha, merge_method, permit_id)

    def read_postcondition(self, repository, pr_number):
        return self._answer("read_postcondition", repository, pr_number)

    def finalize_reservation(self, reservation_id, final_state):
        return self._answer("finalize_reservation", reservation_id, final_state)

    def names(self):
        return [name for name, _ in self.calls]

    def merges(self):
        return [args for name, args in self.calls if name == "merge_pull_request"]


def secret_error():
    return RuntimeError("ghp_secret-token-value Bearer password")


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

class ExecutorFixture(thu.SharedDecisionFixture):
    """One real intent, validation, gate, favorable evaluation and request."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        head = cls.intent.head_sha
        cls.reviews = thu.sequence(head, thu.review(head, 1))
        cls.evaluation = rha.evaluate_human_decision_evidence(cls.gate_result, cls.intent, cls.validation,
                                                              cls.reviews, pr_number=PR, now=NOW)
        cls.request = rpe.prepare_execution_request(cls.gate_result, cls.intent, cls.validation, cls.evaluation,
                                                    pr_number=PR)

    @property
    def base(self):
        return self.intent.base_sha

    @property
    def op(self):
        return self.request.idempotency_key

    # Good host answers -------------------------------------------------
    def lease(self, **changes):
        return dataclasses.replace(rpe.LeaseGrant("lease-1", self.op, f"{REPO}:develop", stamp(0), stamp(300)),
                                   **changes)

    def verdict(self, **changes):
        return dataclasses.replace(rpe.HostCommandVerdict(
            status=rpe.COMMAND_VERIFIED, command_id="cmd-1", operation_id=self.op, action=rpe.ACTION_MERGE_GITHUB_PR,
            repository=REPO, pr_number=PR, base_sha=self.base, head_sha=self.head, director_id=DIRECTOR,
            issued_at=stamp(-120), expires_at=stamp(480)), **changes)

    def fresh(self, snap=None, reviews=None, prot=protection(), tip=None, **changes):
        return dataclasses.replace(rpe.FreshPromotionState(
            repository=REPO, pr_number=PR, pr_snapshot=snap or tpg.snapshot(self.intent),
            review_sequence=reviews or self.reviews, protection=prot, develop_tip_sha=tip or self.base), **changes)

    def permit(self, **changes):
        return Call(lambda op, rid, cmd: dataclasses.replace(rpe.OperationPermit(
            permit_id="permit-1", operation_id=op, reservation_id=rid, command_id=cmd,
            action=rpe.ACTION_MERGE_GITHUB_PR, head_sha=self.head, base_sha=self.base, issued_at=stamp(0),
            expires_at=stamp(60)), **changes))

    def merged(self, **changes):
        return dataclasses.replace(rpe.MergeResponse(rpe.MERGE_MERGED, 200, MERGE_SHA), **changes)

    def post(self, **changes):
        return dataclasses.replace(rpe.PostMergeObservation(
            repository=REPO, pr_number=PR, state="closed", merged=True, head_sha=self.head,
            merge_commit_sha=MERGE_SHA, merge_commit_parents=(self.base, self.head), develop_tip_sha=MERGE_SHA),
            **changes)

    def untouched(self):
        return self.post(state="open", merged=False, develop_tip_sha=self.base)

    def host(self, ledger=None, **answers):
        ledger = ledger if ledger is not None else FakeLedger()
        defaults = dict(
            acquire_lease=self.lease(), release_lease=None, verify_human_command=self.verdict(),
            read_fresh_state=self.fresh(), reserve_single_use=Call(ledger.reserve), issue_operation_permit=self.permit(),
            consume_single_use=Call(ledger.consume), merge_pull_request=self.merged(),
            read_postcondition=self.post(), finalize_reservation=Call(ledger.finalize),
        )
        defaults.update(answers)
        return FakeHost(defaults, ledger)

    def simulate(self, host=None, request=_DEFAULT, clock=None):
        return rpe.simulate_promotion(self.request if request is _DEFAULT else request,
                                      self.host() if host is None else host, clock=clock or (lambda: NOW))

    # Assertions ----------------------------------------------------------
    def assertSound(self, o):
        self.assertIs(type(o), rpe.PromotionExecutionOutcome)
        self.assertEqual(rpe.outcome_invariant_errors(o), ())
        self.assertTrue(rpe.verify_outcome(o))
        self.assertIn(o.execution_mode, (rpe.MODE_SIMULATED, rpe.MODE_PRODUCTION_BLOCKED))
        self.assertNotEqual(o.execution_mode, rpe.MODE_LIVE_AUTHORIZED)
        for flag in ("live_authorized", "production_capable", "human_command_authenticated", "retry_allowed"):
            self.assertIs(getattr(o, flag), False, flag)
        self.assertEqual(o.executor_requirements_unmet, rpe.PRODUCTION_ACTIVATION_REQUIREMENTS)
        self.assertEqual(o.fingerprint, rpe.outcome_fingerprint(o))
        dumped = json.dumps(dataclasses.asdict(o))
        for leak in LEAKS:
            self.assertNotIn(leak, dumped)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            o.live_authorized = True  # type: ignore[misc]
        return o

    def assertOutcome(self, o, state, *codes, merges=0):
        self.assertSound(o)
        self.assertEqual(o.state, state, o.reason_codes)
        self.assertEqual(o.merge_call_count, merges)
        for code in codes:
            self.assertIn(code, o.reason_codes)
        if state != rpe.MERGED_VERIFIED:
            self.assertIs(o.merge_performed_by_this_attempt, False)
            self.assertNotIn(rpe.EXEC_MERGED_VERIFIED_SIMULATED, o.reason_codes)
        return o

    def assertHostClean(self, host, merges=0, o=None):
        """Exactly `merges` merge calls, lease released last if acquired, the
        reservation finalized exactly once iff one was obtained, and only
        contract methods called."""
        names = host.names()
        self.assertTrue(set(names) <= HOST_METHODS, names)
        self.assertEqual(len(host.merges()), merges)
        if "acquire_lease" in names and host.answers["acquire_lease"] is not None:
            self.assertEqual(names[-1], "release_lease")
            self.assertEqual(names.count("release_lease"), 1)
        self.assertLessEqual(names.count("finalize_reservation"), 1)
        if o is not None:
            self.assertEqual(names.count("finalize_reservation"), 1 if o.reservation_id else 0)
            if o.reservation_id:
                self.assertEqual(host.calls[names.index("finalize_reservation")][1], (o.reservation_id, o.state))
        if merges:
            self.assertLess(names.index("consume_single_use"), names.index("merge_pull_request"))


# ---------------------------------------------------------------------------
# Plane (a): request preparation
# ---------------------------------------------------------------------------

class RequestTests(ExecutorFixture):
    def test_request_binds_full_identity_and_never_authorizes(self):
        r = self.request
        self.assertEqual((r.repository, r.pr_number, r.base_ref, r.base_sha, r.head_sha, r.action, r.merge_method),
                         (REPO, PR, "develop", self.base, self.head, "MERGE_GITHUB_PR", "merge"))
        self.assertEqual(r.head_ref, self.intent.head_ref[len("refs/heads/"):])
        self.assertEqual((r.intent_fingerprint, r.validation_fingerprint, r.gate_context_fingerprint,
                          r.gate_result_fingerprint, r.review_evaluation_fingerprint),
                         (self.intent.fingerprint, self.validation.fingerprint, self.gate_result.context.fingerprint,
                          self.gate_result.fingerprint, self.evaluation.fingerprint))
        self.assertEqual(r.decision_identity_fingerprint, self.evaluation.identity.fingerprint)
        self.assertEqual(r.current_approver_ids, (DIRECTOR,))
        self.assertEqual((r.human_command_present, r.authorizes_action, r.execution_allowed), (False, False, False))
        self.assertEqual(r.fingerprint, rpe.request_fingerprint(r))
        self.assertRegex(r.idempotency_key, r"^[0-9a-f]{64}$")
        json.dumps(dataclasses.asdict(r))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.authorizes_action = True  # type: ignore[misc]
        # The FCP-3B-2B1 evaluation, even favorable, never authorizes anything.
        self.assertEqual(self.evaluation.classification, rha.REVIEW_CONSISTENT_UNVERIFIED)
        for flag in ("authorizes_action", "execution_allowed", "human_command_authenticated",
                     "authenticated_human_command_present"):
            self.assertIs(getattr(self.evaluation, flag), False, flag)

    def test_idempotency_key_depends_on_every_identity_field(self):
        bound = {f: getattr(self.request, f) for f in (
            "action", "merge_method", "repository", "pr_number", "base_ref", "base_sha", "head_ref", "head_sha",
            "intent_fingerprint", "validation_fingerprint", "gate_context_fingerprint", "gate_result_fingerprint",
            "decision_identity_fingerprint", "review_evaluation_fingerprint", "review_sequence_fingerprint",
            "current_approver_ids")}
        self.assertEqual(rpe._idempotency_key(bound), self.op)
        for name in bound:
            changed = dict(bound, **{name: 7 if name == "pr_number" else ("x",) if name == "current_approver_ids"
                                     else "x"})
            self.assertNotEqual(rpe._idempotency_key(changed), self.op, name)

    def test_prepare_refuses_anything_but_a_favorable_bound_evaluation(self):
        not_favorable = rha.evaluate_human_decision_evidence(
            self.gate_result, self.intent, self.validation, thu.sequence(self.head), pr_number=PR, now=NOW)
        draft_gate = self.real_gate(tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, draft=True)))
        cases = (
            ((self.gate_result, self.intent, self.validation, not_favorable), rpe.EXEC_REQUEST_EVALUATION_NOT_FAVORABLE),
            ((self.gate_result, self.intent, self.validation,
              tpg.reforged(self.evaluation, rha.evaluation_fingerprint, authorizes_action=True)),
             rpe.EXEC_REQUEST_EVALUATION_TAMPERED),
            ((self.gate_result, self.intent, self.validation,
              tpg.reforged(self.evaluation, rha.evaluation_fingerprint, human_command_authenticated=True)),
             rpe.EXEC_REQUEST_EVALUATION_TAMPERED),
            ((self.gate_result, self.intent, self.validation,
              dataclasses.replace(self.evaluation, classification=rha.REVIEW_READ_UNAUTHENTICATED)),
             rpe.EXEC_REQUEST_EVALUATION_TAMPERED),
            ((self.gate_result, self.intent, self.validation, dataclasses.asdict(self.evaluation)),
             rpe.EXEC_REQUEST_EVALUATION_MALFORMED),
            ((draft_gate, self.intent, self.validation, self.evaluation), rpe.EXEC_REQUEST_GATE_BINDING_INVALID),
            ((self.gate_result, self.intent, None, self.evaluation), rpe.EXEC_REQUEST_GATE_BINDING_INVALID),
            ((self.gate_result, self.intent, self.validation, None), rpe.EXEC_REQUEST_EVALUATION_MALFORMED),
        )
        for args, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(rpe.PromotionExecutionRefused) as ctx:
                    rpe.prepare_execution_request(*args, pr_number=PR)
                self.assertIn(code, ctx.exception.reason_codes)
        with self.assertRaises(rpe.PromotionExecutionRefused):
            rpe.prepare_execution_request(self.gate_result, self.intent, self.validation, self.evaluation,
                                          pr_number=PR + 1)
        # An evaluation of another (host-read) gate does not bind to this one.
        host_gate = rpg.read_pr_gate(self.intent, tpg.FakeProvider(tpg.pr_meta(self.intent), tpg.file_listing(),
                                                                   tpg.check_listing(self.intent)),
                                     self.fx.wt, pr_number=PR, **self.kw)
        with self.assertRaises(rpe.PromotionExecutionRefused) as ctx:
            rpe.prepare_execution_request(host_gate, self.intent, self.validation, self.evaluation, pr_number=PR)
        self.assertIn(rpe.EXEC_REQUEST_EVALUATION_BINDING_MISMATCH, ctx.exception.reason_codes)

    def test_tampered_or_forged_request_is_refused_before_any_port(self):
        forged = (
            tpg.reforged(self.request, rpe.request_fingerprint, head_sha=OTHER_SHA),
            tpg.reforged(self.request, rpe.request_fingerprint, action="FAST_FORWARD_CANDIDATE_TO_DEVELOP"),
            tpg.reforged(self.request, rpe.request_fingerprint, merge_method="squash"),
            tpg.reforged(self.request, rpe.request_fingerprint, authorizes_action=True),
            tpg.reforged(self.request, rpe.request_fingerprint, execution_allowed=True),
            tpg.reforged(self.request, rpe.request_fingerprint, human_command_present=True),
            tpg.reforged(self.request, rpe.request_fingerprint, idempotency_key="0" * 64),
            tpg.reforged(self.request, rpe.request_fingerprint, current_approver_ids=(DIRECTOR, 77)),
            dataclasses.replace(self.request, pr_number=PR + 1),
            dataclasses.asdict(self.request), None, tpg._Truthy(),
        )
        for request in forged:
            with self.subTest(request=type(request)):
                host = self.host()
                o = self.assertOutcome(self.simulate(host, request=request), rpe.PRECONDITION_REFUSED)
                self.assertTrue(set(o.reason_codes) & {rpe.EXEC_REQUEST_TAMPERED, rpe.EXEC_REQUEST_MALFORMED})
                self.assertEqual(host.calls, [])
                self.assertEqual(o.state_trace, (rpe.PRECONDITION_REFUSED,))


# ---------------------------------------------------------------------------
# Coherent simulated path and production refusal
# ---------------------------------------------------------------------------

class SimulatedPathTests(ExecutorFixture):
    def test_coherent_simulated_path_merges_exactly_once_and_is_never_live(self):
        host = self.host()
        o = self.assertOutcome(self.simulate(host), rpe.MERGED_VERIFIED, rpe.EXEC_MERGED_VERIFIED_SIMULATED,
                               rpe.EXEC_SIMULATED_NOT_REAL_MERGE, merges=1)
        self.assertEqual(host.names(), HAPPY_CALLS)
        self.assertHostClean(host, merges=1, o=o)
        self.assertEqual(host.merges(), [(REPO, PR, self.head, "merge", "permit-1")])
        self.assertEqual(o.execution_mode, rpe.MODE_SIMULATED)
        self.assertEqual(o.state_trace, (rpe.PREPARED, rpe.RESERVED, rpe.MERGE_ATTEMPTED, rpe.MERGED_VERIFIED))
        self.assertEqual([s.step for s in o.step_trace], [
            rpe.STEP_VALIDATE_REQUEST, rpe.STEP_ACQUIRE_LEASE, rpe.STEP_VERIFY_COMMAND, rpe.STEP_PREFLIGHT_READ,
            rpe.STEP_RESERVE, rpe.STEP_ISSUE_PERMIT, rpe.STEP_FINAL_COMMAND_CHECK, rpe.STEP_FINAL_READ,
            rpe.STEP_CONSUME, rpe.STEP_MERGE, rpe.STEP_POSTCONDITION_READ, rpe.STEP_FINALIZE_RESERVATION,
            rpe.STEP_RELEASE_LEASE])
        self.assertTrue(all(s.result == rpe.STEP_OK for s in o.step_trace))
        self.assertEqual((o.operation_id, o.request_fingerprint, o.command_id, o.reservation_id, o.permit_id,
                          o.lease_id), (self.op, self.request.fingerprint, "cmd-1", "res-1", "permit-1", "lease-1"))
        self.assertEqual((o.merge_commit_sha, o.observed_develop_tip_sha), (MERGE_SHA, MERGE_SHA))
        self.assertTrue(all((o.structural_eligibility_passed, o.host_command_check_passed,
                             o.operation_permit_check_passed, o.remote_postcondition_confirmed,
                             o.merge_performed_by_this_attempt)))
        self.assertEqual(host.ledger.finalized, [("res-1", rpe.MERGED_VERIFIED)])
        self.assertEqual(host.ledger.ops[self.op], "consumed")

    def test_production_entry_always_refuses_and_touches_no_port(self):
        for request in (self.request, None, tpg.reforged(self.request, rpe.request_fingerprint, head_sha=OTHER_SHA)):
            with self.subTest(request=type(request)):
                o = self.assertOutcome(rpe.execute_promotion(request), rpe.AUTHORIZATION_REFUSED,
                                       rpe.EXEC_TRUSTED_HOST_NOT_AVAILABLE,
                                       rpe.EXEC_PRODUCTION_ADAPTER_NOT_IMPLEMENTED)
                self.assertEqual(o.execution_mode, rpe.MODE_PRODUCTION_BLOCKED)
                self.assertEqual([s.step for s in o.step_trace], [rpe.STEP_VALIDATE_REQUEST])
        self.assertEqual(list(inspect.signature(rpe.execute_promotion).parameters), ["request"])
        self.assertIs(rpe.PRODUCTION_PROMOTION_CAPABLE, False)

    def test_without_a_simulation_host_nothing_is_called(self):
        class RealLookingHost(FakeHost):
            host_kind = "PRIVILEGED_GITHUB_HOST"

        class PropertyHost(FakeHost):
            host_kind = property(lambda self: rpe.HOST_KIND_IN_MEMORY_SIMULATION)

        class Unmarked:
            def merge_pull_request(self, *args):
                raise AssertionError("called")

        good = self.host()
        for cls in (RealLookingHost, PropertyHost):
            host = cls(good.answers, FakeLedger())
            with self.subTest(host=cls.__name__):
                self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_TRUSTED_HOST_ABSENT)
                self.assertEqual(host.calls, [])
        for host in (None, Unmarked(), object()):
            with self.subTest(host=type(host)):
                o = rpe.simulate_promotion(self.request, host, clock=lambda: NOW)
                self.assertOutcome(o, rpe.AUTHORIZATION_REFUSED, rpe.EXEC_TRUSTED_HOST_ABSENT)

    def test_favorable_gate_reviews_and_fingerprints_without_human_command_stay_blocked(self):
        for status in (rpe.COMMAND_ABSENT, rpe.COMMAND_REJECTED):
            with self.subTest(status=status):
                host = self.host(verify_human_command=self.verdict(status=status))
                o = self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED)
                self.assertIs(o.structural_eligibility_passed, True)
                self.assertIs(o.host_command_check_passed, False)
                self.assertEqual(host.names(), ["acquire_lease", "verify_human_command", "release_lease"])
                self.assertHostClean(host, o=o)
        # A provider/bot "consent" shaped as a dict or with approval flags is not a verdict.
        for fake in ({"approved": True, "is_trusted": True}, tpg._Truthy(), "COMMAND_VERIFIED", True,
                     dataclasses.asdict(self.verdict())):
            with self.subTest(fake=type(fake)):
                host = self.host(verify_human_command=fake)
                self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_COMMAND_MALFORMED)
                self.assertHostClean(host)

    def test_outcomes_are_deterministic_and_fingerprinted_for_audit(self):
        a, b = self.simulate(self.host()), self.simulate(self.host())
        self.assertEqual(a, b)
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertEqual(json.loads(json.dumps(dataclasses.asdict(a)))["state"], rpe.MERGED_VERIFIED)


# ---------------------------------------------------------------------------
# Plane (b) and lease
# ---------------------------------------------------------------------------

class CommandAndLeaseTests(ExecutorFixture):
    def test_lease_occupied_or_failing(self):
        for answer in (None, secret_error()):
            with self.subTest(answer=type(answer)):
                host = self.host(acquire_lease=answer)
                o = self.assertOutcome(self.simulate(host), rpe.PRECONDITION_REFUSED, rpe.EXEC_LEASE_UNAVAILABLE)
                self.assertEqual(host.names(), ["acquire_lease"])
                self.assertIsNone(o.lease_id)

    def test_invalid_lease_grant_is_released_and_refused(self):
        cases = (
            (self.lease(operation_id="0" * 64), rpe.EXEC_LEASE_INVALID),
            (self.lease(resource=f"{REPO}:main"), rpe.EXEC_LEASE_INVALID),
            (self.lease(acquired_at=stamp(-900), expires_at=stamp(-1)), rpe.EXEC_LEASE_INVALID),
            (self.lease(acquired_at=stamp(-300), expires_at=stamp(0)), rpe.EXEC_LEASE_EXPIRED),
            (self.lease(expires_at=stamp(3600)), rpe.EXEC_LEASE_INVALID),
        )
        for grant, code in cases:
            with self.subTest(code=code, grant=grant):
                host = self.host(acquire_lease=grant)
                self.assertOutcome(self.simulate(host), rpe.PRECONDITION_REFUSED, code)
                self.assertEqual(host.names(), ["acquire_lease", "release_lease"])

    def test_command_expired_revoked_unbound_or_too_long(self):
        cases = (
            (self.verdict(status=rpe.COMMAND_EXPIRED), rpe.EXEC_COMMAND_EXPIRED),
            (self.verdict(status=rpe.COMMAND_REVOKED), rpe.EXEC_COMMAND_REVOKED),
            (self.verdict(issued_at=stamp(-600), expires_at=stamp(0)), rpe.EXEC_COMMAND_EXPIRED),
            (self.verdict(issued_at=stamp(-60), expires_at=stamp(3600)), rpe.EXEC_COMMAND_TTL_TOO_LONG),
            (self.verdict(issued_at=stamp(30), expires_at=stamp(300)), rpe.EXEC_COMMAND_TIMESTAMP_INVALID),
            (self.verdict(issued_at="2026-10-24 11:58:00"), rpe.EXEC_COMMAND_TIMESTAMP_INVALID),
            (self.verdict(head_sha=OTHER_SHA), rpe.EXEC_COMMAND_BINDING_MISMATCH),
            (self.verdict(base_sha=OTHER_SHA), rpe.EXEC_COMMAND_BINDING_MISMATCH),
            (self.verdict(pr_number=PR + 1), rpe.EXEC_COMMAND_BINDING_MISMATCH),
            (self.verdict(operation_id="0" * 64), rpe.EXEC_COMMAND_BINDING_MISMATCH),
            (self.verdict(action="FAST_FORWARD_CANDIDATE_TO_DEVELOP"), rpe.EXEC_COMMAND_BINDING_MISMATCH),
            (self.verdict(repository="someone/fork"), rpe.EXEC_COMMAND_BINDING_MISMATCH),
            (self.verdict(command_id="ghp_secret token"), rpe.EXEC_COMMAND_MALFORMED),
            (self.verdict(director_id=0), rpe.EXEC_COMMAND_MALFORMED),
            (self.verdict(status="APPROVED"), rpe.EXEC_COMMAND_MALFORMED),
            (self.verdict(schema="other"), rpe.EXEC_COMMAND_MALFORMED),
            (secret_error(), rpe.EXEC_HOST_PORT_FAILED),
        )
        for verdict, code in cases:
            with self.subTest(code=code):
                host = self.host(verify_human_command=verdict)
                o = self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED, code)
                self.assertNotIn("reserve_single_use", host.names())
                self.assertIsNone(o.command_id)
                self.assertHostClean(host, o=o)

    def test_command_revoked_or_changed_before_the_operation(self):
        cases = (
            (self.verdict(status=rpe.COMMAND_REVOKED), rpe.EXEC_COMMAND_REVOKED),
            (self.verdict(command_id="cmd-2"), rpe.EXEC_COMMAND_CHANGED),
            (secret_error(), rpe.EXEC_HOST_PORT_FAILED),
        )
        for second, code in cases:
            with self.subTest(code=code):
                host = self.host(verify_human_command=Seq(self.verdict(), second))
                o = self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED, code)
                self.assertEqual(o.state_trace, (rpe.PREPARED, rpe.RESERVED, rpe.AUTHORIZATION_REFUSED))
                self.assertIs(o.host_command_check_passed, False)
                self.assertNotIn("consume_single_use", host.names())
                self.assertHostClean(host, o=o)
                self.assertEqual(host.ledger.finalized, [("res-1", rpe.AUTHORIZATION_REFUSED)])

    def test_command_expiring_between_checks_via_clock(self):
        times = iter([NOW, NOW, NOW, NOW, NOW + timedelta(seconds=481)] + [NOW + timedelta(seconds=481)] * 10)
        host = self.host()
        o = self.assertOutcome(self.simulate(host, clock=lambda: next(times)), rpe.AUTHORIZATION_REFUSED,
                               rpe.EXEC_COMMAND_EXPIRED)
        self.assertIn(rpe.RESERVED, o.state_trace)
        self.assertHostClean(host, o=o)

    def test_invalid_clock_is_refused(self):
        from datetime import datetime
        for clock in (lambda: NOW.replace(tzinfo=None), lambda: "now", lambda: datetime.fromtimestamp(0)):
            host = self.host()
            self.assertOutcome(self.simulate(host, clock=clock), rpe.PRECONDITION_REFUSED, rpe.EXEC_CLOCK_INVALID)
            self.assertEqual(host.calls, [])


# ---------------------------------------------------------------------------
# Plane (c): single use and permit
# ---------------------------------------------------------------------------

class SingleUseTests(ExecutorFixture):
    def test_replay_after_success_is_refused_with_zero_merges(self):
        ledger = FakeLedger()
        first = self.host(ledger)
        self.assertOutcome(self.simulate(first), rpe.MERGED_VERIFIED, merges=1)
        replay = self.host(ledger)
        o = self.assertOutcome(self.simulate(replay), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_REPLAY_DETECTED)
        self.assertEqual(replay.merges(), [])
        self.assertIsNone(o.reservation_id)
        self.assertHostClean(replay, o=o)

    def test_duplicate_reservation_and_burned_reservation(self):
        ledger = FakeLedger()
        refused = self.host(ledger, issue_operation_permit=self.permit(expires_at=stamp(-1), issued_at=stamp(-30)))
        self.assertOutcome(self.simulate(refused), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_PERMIT_EXPIRED)
        # The refused attempt burned its reservation: same operation cannot reserve again.
        again = self.host(ledger)
        self.assertOutcome(self.simulate(again), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_RESERVATION_DUPLICATE)
        self.assertEqual(again.merges(), [])
        concurrent = self.host(reserve_single_use=rpe.ReservationReceipt(
            rpe.RESERVATION_ALREADY_RESERVED, "res-9", self.op, "cmd-1"))
        self.assertOutcome(self.simulate(concurrent), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_RESERVATION_DUPLICATE)

    def test_reservation_receipt_must_bind_operation_and_command(self):
        cases = (
            (rpe.ReservationReceipt(rpe.RESERVATION_CREATED, "res-1", "0" * 64, "cmd-1"),
             rpe.EXEC_RESERVATION_BINDING_MISMATCH),
            (rpe.ReservationReceipt(rpe.RESERVATION_CREATED, "res-1", self.op, "cmd-x"),
             rpe.EXEC_RESERVATION_BINDING_MISMATCH),
            (rpe.ReservationReceipt("OK", "res-1", self.op, "cmd-1"), rpe.EXEC_RESERVATION_MALFORMED),
            ({"status": "RESERVATION_CREATED"}, rpe.EXEC_RESERVATION_MALFORMED),
            (secret_error(), rpe.EXEC_HOST_PORT_FAILED),
        )
        for receipt, code in cases:
            with self.subTest(code=code):
                host = self.host(reserve_single_use=receipt)
                self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED, code)
                self.assertEqual(host.merges(), [])
                self.assertNotIn("finalize_reservation", host.names())
                self.assertHostClean(host)

    def test_permit_must_be_bound_short_and_current(self):
        cases = (
            (self.permit(expires_at=stamp(600)), rpe.EXEC_PERMIT_TTL_TOO_LONG),
            (self.permit(issued_at=stamp(-90), expires_at=stamp(0)), rpe.EXEC_PERMIT_EXPIRED),
            (self.permit(head_sha=OTHER_SHA), rpe.EXEC_PERMIT_BINDING_MISMATCH),
            (self.permit(reservation_id="res-77"), rpe.EXEC_PERMIT_BINDING_MISMATCH),
            (self.permit(command_id="cmd-9"), rpe.EXEC_PERMIT_BINDING_MISMATCH),
            (self.permit(permit_id="has space"), rpe.EXEC_PERMIT_MALFORMED),
            (secret_error(), rpe.EXEC_HOST_PORT_FAILED),
        )
        for permit, code in cases:
            with self.subTest(code=code):
                host = self.host(issue_operation_permit=permit)
                o = self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED, code)
                self.assertIs(o.operation_permit_check_passed, False)
                self.assertNotIn("consume_single_use", host.names())
                self.assertHostClean(host, o=o)

    def test_permit_or_lease_expiring_before_the_operation(self):
        late = NOW + timedelta(seconds=61)
        times = iter([NOW] * 5 + [late] * 10)
        host = self.host()
        self.assertOutcome(self.simulate(host, clock=lambda: next(times)), rpe.AUTHORIZATION_REFUSED,
                           rpe.EXEC_PERMIT_EXPIRED)
        self.assertEqual(host.merges(), [])
        host = self.host(acquire_lease=self.lease(expires_at=stamp(30)),
                         issue_operation_permit=self.permit(expires_at=stamp(100)))
        times = iter([NOW] * 5 + [NOW + timedelta(seconds=45)] * 10)
        self.assertOutcome(self.simulate(host, clock=lambda: next(times)), rpe.PRECONDITION_REFUSED,
                           rpe.EXEC_LEASE_EXPIRED)
        self.assertHostClean(host)

    def test_consumption_failure_is_failed_safe_without_merge(self):
        cases = (
            secret_error(),
            rpe.ConsumptionReceipt(rpe.CONSUMPTION_REFUSED, "res-1", "x"),
            Call(lambda rid: rpe.ConsumptionReceipt(rpe.CONSUMED, "res-other", self.op)),
            None,
        )
        for answer in cases:
            with self.subTest(answer=type(answer)):
                host = self.host(consume_single_use=answer)
                o = self.assertOutcome(self.simulate(host), rpe.FAILED_SAFE, rpe.EXEC_CONSUMPTION_FAILED)
                self.assertEqual(o.state_trace, (rpe.PREPARED, rpe.RESERVED, rpe.FAILED_SAFE))
                self.assertHostClean(host, o=o)
                self.assertEqual(host.ledger.finalized, [("res-1", rpe.FAILED_SAFE)])


# ---------------------------------------------------------------------------
# Plane (a), fresh: PR, checks, reviews, protection, drift
# ---------------------------------------------------------------------------

class FreshStateTests(ExecutorFixture):
    def refused_on_fresh(self, fresh, *codes):
        host = self.host(read_fresh_state=fresh)
        o = self.assertOutcome(self.simulate(host), rpe.PRECONDITION_REFUSED, *codes)
        self.assertEqual(host.names(), ["acquire_lease", "verify_human_command", "read_fresh_state", "release_lease"])
        return o

    def test_checks_incomplete_failed_or_not_six(self):
        runs = self.runs
        cases = (
            (tpg.check_listing(self.intent, runs()[:5]), rpg.PR_GATE_CHECK_MISSING),
            (tpg.check_listing(self.intent, runs(j2=dict(conclusion="failure"))), rpg.PR_GATE_CHECK_FAILED),
            (tpg.check_listing(self.intent, runs(j5=dict(status="in_progress", conclusion=None))),
             rpg.PR_GATE_CHECK_PENDING),
            (tpg.check_listing(self.intent, runs(), complete=False), rpg.PR_GATE_CHECKS_INCOMPLETE),
            (tpg.check_listing(self.intent, runs(j0=dict(workflow_run_id=1))), rpg.PR_GATE_CHECK_RUN_CONFLICT),
            (tpg.check_listing(self.intent, runs(j3=dict(conclusion="skipped"))), rpg.PR_GATE_CHECK_SKIPPED),
        )
        for checks, code in cases:
            with self.subTest(code=code):
                self.refused_on_fresh(self.fresh(tpg.snapshot(self.intent, checks=checks)),
                                      rpe.EXEC_FRESH_GATE_NOT_REVIEWABLE, code)

    def test_branch_policy_unknown_or_ineffective(self):
        cases = (
            (None, rpe.EXEC_PROTECTION_UNKNOWN),
            (protection(complete=False), rpe.EXEC_PROTECTION_UNKNOWN),
            (protection(base_ref="main"), rpe.EXEC_PROTECTION_UNKNOWN),
            (protection(pull_request_required=False), rpe.EXEC_PROTECTION_REVIEWS_NOT_REQUIRED),
            (protection(required_approving_review_count=0), rpe.EXEC_PROTECTION_REVIEWS_NOT_REQUIRED),
            (protection(dismiss_stale_reviews=False), rpe.EXEC_PROTECTION_STALE_REVIEWS_KEPT),
            (protection(required_check_names=JOBS[:5]), rpe.EXEC_PROTECTION_CHECKS_NOT_REQUIRED),
            (protection(required_check_names=JOBS + ("extra",)), rpe.EXEC_PROTECTION_INCONSISTENT),
            (protection(strict_up_to_date=False), rpe.EXEC_PROTECTION_NOT_STRICT),
            (protection(enforce_admins=False), rpe.EXEC_PROTECTION_ADMIN_BYPASS),
            (protection(allow_force_pushes=True), rpe.EXEC_PROTECTION_REWRITE_ALLOWED),
            (protection(allow_deletions=True), rpe.EXEC_PROTECTION_REWRITE_ALLOWED),
            (protection(merge_queue_required=True), rpe.EXEC_MERGE_QUEUE_NOT_SUPPORTED),
            (protection(enforce_admins=1), rpe.EXEC_PROTECTION_MALFORMED),
        )
        for prot, code in cases:
            with self.subTest(code=code):
                self.refused_on_fresh(self.fresh(prot=prot), code)
        # The FCP-3B-2A gate's own policy must be proven too.
        self.refused_on_fresh(self.fresh(tpg.snapshot(self.intent, checks=tpg.check_listing(self.intent, policy=None))),
                              rpe.EXEC_FRESH_GATE_NOT_REVIEWABLE, rpg.PR_GATE_POLICY_NOT_PROVEN)
        linear = tpg.check_listing(self.intent, policy=tpg.branch_policy(
            rule_types=("pull_request", "required_status_checks", "required_linear_history")))
        self.refused_on_fresh(self.fresh(tpg.snapshot(self.intent, checks=linear)),
                              rpe.EXEC_MERGE_METHOD_FORBIDDEN_BY_POLICY)

    def test_head_or_base_diverged(self):
        moved_head = tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, head_sha=OTHER_SHA))
        self.refused_on_fresh(self.fresh(moved_head), rpg.PR_GATE_STALE_HEAD)
        moved_base = tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, base_branch_sha=OTHER_SHA))
        self.refused_on_fresh(self.fresh(moved_base), rpg.PR_GATE_STALE_BASE)
        self.refused_on_fresh(self.fresh(tip=OTHER_SHA), rpe.EXEC_BASE_DRIFT)
        self.refused_on_fresh(self.fresh(repository="someone/fork"), rpe.EXEC_FRESH_BINDING_MISMATCH)
        self.refused_on_fresh(dataclasses.asdict(self.fresh()), rpe.EXEC_FRESH_STATE_MALFORMED)
        self.refused_on_fresh(secret_error(), rpe.EXEC_HOST_PORT_FAILED)

    def test_approvals_dismissed_or_changes_requested(self):
        h = self.head
        cases = (
            (thu.sequence(h, thu.review(h, 1), thu.review(h, 2, state=rha.DISMISSED)), rha.HAUTH_NO_CURRENT_APPROVAL),
            (thu.sequence(h, thu.review(h, 1), thu.review(h, 2, rha.CHANGES_REQUESTED, actor=thu.OTHER)),
             rha.HAUTH_CHANGES_REQUESTED),
            (thu.sequence(h), rha.HAUTH_NO_CURRENT_APPROVAL),
            (thu.sequence(h, thu.review(OTHER_SHA, 1)), rha.HAUTH_APPROVAL_STALE_COMMIT),
            (thu.sequence(h, thu.review(h, 1, actor=thu.BOT)), rha.HAUTH_REVIEW_ACTOR_NOT_HUMAN),
            (thu.sequence(h, thu.review(h, 1), observed_at="2026-10-24T11:00:00Z"), rha.HAUTH_REVIEW_SNAPSHOT_STALE),
        )
        for reviews, code in cases:
            with self.subTest(code=code):
                self.refused_on_fresh(self.fresh(reviews=reviews), rpe.EXEC_FRESH_REVIEWS_NOT_FAVORABLE, code)

    def test_pr_draft_closed_or_already_merged(self):
        meta = lambda **c: self.fresh(tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, **c)))  # noqa: E731
        o = self.refused_on_fresh(meta(draft=True), rpg.PR_GATE_PR_DRAFT)
        self.assertIs(o.observed_already_merged, False)
        self.refused_on_fresh(meta(state="closed"), rpg.PR_GATE_PR_CLOSED)
        o = self.refused_on_fresh(meta(state="closed", merged=True), rpe.EXEC_PR_ALREADY_MERGED_OBSERVED,
                                  rpg.PR_GATE_PR_MERGED)
        # Observed idempotent result, never claimed as this attempt's merge.
        self.assertIs(o.observed_already_merged, True)
        self.assertIs(o.merge_performed_by_this_attempt, False)
        self.assertIsNone(o.merge_commit_sha)

    def test_change_during_preflight_refuses_after_reservation(self):
        changes = (
            self.fresh(tpg.snapshot(self.intent, checks=tpg.check_listing(self.intent, self.runs(
                j0=dict(check_run_id=999))))),
            self.fresh(reviews=thu.sequence(self.head, thu.review(self.head, 1),
                                            thu.review(self.head, 2, actor=thu.OTHER))),
            self.fresh(tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, head_sha=OTHER_SHA))),
            self.fresh(tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, state="closed", merged=True))),
        )
        for second in changes:
            with self.subTest():
                host = self.host(read_fresh_state=Seq(self.fresh(), second))
                o = self.assertOutcome(self.simulate(host), rpe.PRECONDITION_REFUSED)
                self.assertTrue({rpe.EXEC_STATE_CHANGED_DURING_PREFLIGHT, rpe.EXEC_FRESH_GATE_NOT_REVIEWABLE}
                                & set(o.reason_codes), o.reason_codes)
                self.assertEqual(o.state_trace, (rpe.PREPARED, rpe.RESERVED, rpe.PRECONDITION_REFUSED))
                self.assertNotIn("consume_single_use", host.names())
                self.assertHostClean(host, o=o)
                self.assertEqual(host.ledger.finalized, [("res-1", rpe.PRECONDITION_REFUSED)])
        # A newer read instant alone is not drift.
        later = thu.sequence(self.head, thu.review(self.head, 1), observed_at="2026-10-24T11:59:30Z")
        host = self.host(read_fresh_state=Seq(self.fresh(), self.fresh(reviews=later)))
        self.assertOutcome(self.simulate(host), rpe.MERGED_VERIFIED, merges=1)


# ---------------------------------------------------------------------------
# Plane (d): merge answers, uncertainty and postconditions
# ---------------------------------------------------------------------------

class MergeAndPostconditionTests(ExecutorFixture):
    def test_api_rejections_fail_safe_with_one_call_and_no_fallback(self):
        cases = (
            (rpe.MERGE_REJECTED_HEAD_MISMATCH, 409, rpe.EXEC_MERGE_REJECTED_HEAD_MISMATCH),
            (rpe.MERGE_REJECTED_CONFLICT, 409, rpe.EXEC_MERGE_REJECTED_CONFLICT),
            (rpe.MERGE_REJECTED_UNPROCESSABLE, 422, rpe.EXEC_MERGE_REJECTED_UNPROCESSABLE),
            (rpe.MERGE_REJECTED_NOT_MERGEABLE, 405, rpe.EXEC_MERGE_REJECTED_NOT_MERGEABLE),
            (rpe.MERGE_REJECTED_FORBIDDEN, 403, rpe.EXEC_MERGE_REJECTED_FORBIDDEN),
            (rpe.MERGE_NOT_SENT, None, rpe.EXEC_MERGE_NOT_SENT),
        )
        for status, http, code in cases:
            with self.subTest(status=status):
                host = self.host(merge_pull_request=rpe.MergeResponse(status, http, None),
                                 read_postcondition=self.untouched())
                o = self.assertOutcome(self.simulate(host), rpe.FAILED_SAFE, code, merges=1)
                self.assertEqual(o.merge_response_status, status)
                self.assertHostClean(host, merges=1, o=o)
                self.assertEqual(host.names()[-4:], ["merge_pull_request", "read_postcondition",
                                                     "finalize_reservation", "release_lease"])
                self.assertEqual(host.ledger.finalized, [("res-1", rpe.FAILED_SAFE)])
        # A rejection whose postcondition cannot be read is still a safe failure.
        host = self.host(merge_pull_request=rpe.MergeResponse(rpe.MERGE_REJECTED_CONFLICT, 409, None),
                         read_postcondition=secret_error())
        self.assertOutcome(self.simulate(host), rpe.FAILED_SAFE, rpe.EXEC_POSTCONDITION_UNREAD, merges=1)

    def test_rejection_contradicted_by_postcondition_is_uncertain(self):
        host = self.host(merge_pull_request=rpe.MergeResponse(rpe.MERGE_REJECTED_CONFLICT, 409, None),
                         read_postcondition=self.post())
        o = self.assertOutcome(self.simulate(host), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
                               rpe.EXEC_POSTCONDITION_CONTRADICTS, rpe.EXEC_POST_OBSERVED_MERGED_NOT_CLAIMED, merges=1)
        self.assertIs(o.human_reconciliation_required, True)

    def test_timeout_after_send_or_port_failure_is_uncertain_never_retried(self):
        for answer in (rpe.MergeResponse(rpe.MERGE_TIMEOUT_AFTER_SEND, None, None), secret_error(), TimeoutError(),
                       rpe.MergeResponse(rpe.MERGE_MERGED, 409, MERGE_SHA), rpe.MergeResponse("ACCEPTED", 202, None),
                       rpe.MergeResponse(rpe.MERGE_MERGED, 200, None), None):
            for post in (self.untouched(), self.post()):
                with self.subTest(answer=answer, merged=post.merged):
                    host = self.host(merge_pull_request=answer, read_postcondition=post)
                    o = self.assertOutcome(self.simulate(host), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
                                           rpe.EXEC_MERGE_OUTCOME_UNKNOWN, rpe.EXEC_NO_RETRY_AFTER_UNCERTAINTY,
                                           merges=1)
                    self.assertHostClean(host, merges=1, o=o)
                    self.assertIs(o.retry_allowed, False)
                    self.assertIs(o.merge_performed_by_this_attempt, False)
                    if post.merged:
                        self.assertIn(rpe.EXEC_POST_OBSERVED_MERGED_NOT_CLAIMED, o.reason_codes)

    def test_no_second_merge_after_uncertainty(self):
        ledger = FakeLedger()
        first = self.host(ledger, merge_pull_request=secret_error())
        self.assertOutcome(self.simulate(first), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION, merges=1)
        for _ in range(3):
            again = self.host(ledger)
            self.assertOutcome(self.simulate(again), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_REPLAY_DETECTED)
            self.assertEqual(again.merges(), [])
        self.assertEqual(len(first.merges()), 1)

    def test_contradictory_postcondition_after_merged_answer(self):
        cases = (
            (self.post(develop_tip_sha=OTHER_SHA), ()),
            (self.post(merge_commit_parents=(OTHER_SHA, self.head)), (rpe.EXEC_POST_BASE_DRIFT,)),
            (self.post(merge_commit_parents=(self.head,)), (rpe.EXEC_POST_BASE_DRIFT,)),
            (self.post(merged=False, state="open"), ()),
            (self.post(merge_commit_sha=OTHER_SHA), ()),
            (self.post(head_sha=OTHER_SHA), ()),
        )
        for post, extra in cases:
            with self.subTest(post=post):
                host = self.host(read_postcondition=post)
                o = self.assertOutcome(self.simulate(host), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
                                       rpe.EXEC_POSTCONDITION_CONTRADICTS, *extra, merges=1)
                self.assertIs(o.remote_postcondition_confirmed, False)
        for post in (secret_error(), self.post(repository="someone/fork"), dataclasses.asdict(self.post())):
            with self.subTest(post=type(post)):
                host = self.host(read_postcondition=post)
                self.assertOutcome(self.simulate(host), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
                                   rpe.EXEC_POSTCONDITION_UNREAD, merges=1)

    def test_ledger_and_lease_handling_failures(self):
        host = self.host(finalize_reservation=secret_error())
        o = self.assertOutcome(self.simulate(host), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
                               rpe.EXEC_LEDGER_FINALIZE_FAILED, merges=1)
        self.assertEqual(host.names()[-1], "release_lease")
        host = self.host(finalize_reservation=secret_error(),
                         issue_operation_permit=self.permit(head_sha=OTHER_SHA))
        self.assertOutcome(self.simulate(host), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_LEDGER_FINALIZE_FAILED)
        host = self.host(release_lease=secret_error())
        o = self.assertOutcome(self.simulate(host), rpe.MERGED_VERIFIED, rpe.EXEC_LEASE_RELEASE_FAILED, merges=1)
        self.assertEqual(o.step_trace[-1], rpe.ExecutionStep(rpe.STEP_RELEASE_LEASE, rpe.EXEC_HOST_PORT_FAILED))

    def test_unexpected_internal_failure_after_merge_is_uncertain(self):
        with mock.patch.object(rpe._Attempt, "_classify", side_effect=RuntimeError("boom")):
            host = self.host()
            o = self.assertOutcome(self.simulate(host), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
                                   rpe.EXEC_INTERNAL_FAILURE, merges=1)
        self.assertHostClean(host, merges=1, o=o)
        self.assertIs(o.human_reconciliation_required, True)

    def test_no_secret_from_any_port_reaches_the_outcome(self):
        for port in sorted(HOST_METHODS):
            with self.subTest(port=port):
                host = self.host(**{port: secret_error()})
                o = self.assertSound(self.simulate(host))
                self.assertLessEqual(len(host.merges()), 1)
                self.assertNotIn("ghp_", repr(o))

    def test_no_network_and_no_repository_write(self):
        git_dir = self.fx.repo / ".git"
        before = _git_dir_state([git_dir])
        refuse = mock.Mock(side_effect=AssertionError("network used"))
        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse):
            self.assertOutcome(self.simulate(self.host()), rpe.MERGED_VERIFIED, merges=1)
            rpe.execute_promotion(self.request)
        refuse.assert_not_called()
        self.assertEqual(_git_dir_state([git_dir]), before)
        self.assertEqual(sorted(self.ledger.iterdir()), [])


# ---------------------------------------------------------------------------
# Outcome invariants
# ---------------------------------------------------------------------------

class InvariantTests(ExecutorFixture):
    def test_forged_outcomes_are_detected(self):
        good = self.simulate(self.host())
        refused = self.simulate(self.host(verify_human_command=self.verdict(status=rpe.COMMAND_ABSENT)))
        uncertain = self.simulate(self.host(merge_pull_request=secret_error()))
        forge = lambda o, **c: tpg.reforged(o, rpe.outcome_fingerprint, **c)  # noqa: E731
        cases = (
            (dataclasses.replace(good, state=rpe.FAILED_SAFE), "INV_FINGERPRINT"),
            (forge(good, execution_mode=rpe.MODE_LIVE_AUTHORIZED), "INV_NOT_LIVE"),
            (forge(good, live_authorized=True), "INV_NOT_LIVE"),
            (forge(good, production_capable=True), "INV_NOT_LIVE"),
            (forge(good, human_command_authenticated=True), "INV_NOT_LIVE"),
            (forge(good, retry_allowed=True), "INV_NOT_LIVE"),
            (forge(good, merge_call_count=2), "INV_MERGE_CALLS"),
            (forge(good, observed_develop_tip_sha=OTHER_SHA), "INV_VERIFIED_EVIDENCE"),
            (forge(good, host_command_check_passed=False), "INV_VERIFIED_EVIDENCE"),
            (forge(good, state_trace=(rpe.PREPARED, rpe.MERGED_VERIFIED)), "INV_STATE"),
            (forge(good, state=rpe.MERGE_ATTEMPTED), "INV_STATE"),
            (forge(good, reason_codes=()), "INV_REASON_CODES"),
            (forge(refused, merge_performed_by_this_attempt=True), "INV_MERGE_CLAIM"),
            (forge(refused, merge_call_count=1), "INV_MERGE_CALLS"),
            (forge(uncertain, state=rpe.MERGED_VERIFIED,
                   state_trace=uncertain.state_trace[:-1] + (rpe.MERGED_VERIFIED,)), "INV_MERGE_CLAIM"),
            (forge(uncertain, human_reconciliation_required=False), "INV_UNCERTAIN"),
            (forge(rpe.execute_promotion(self.request), lease_id="lease-1"), "INV_PRODUCTION_TOUCHED_HOST"),
            (dataclasses.asdict(good), "INV_MALFORMED"),
        )
        for outcome, code in cases:
            with self.subTest(code=code):
                self.assertIn(code, rpe.outcome_invariant_errors(outcome))
                self.assertIs(rpe.verify_outcome(outcome), False)

    def test_transition_table(self):
        self.assertEqual(set(rpe.STATES), {"PREPARED", "AUTHORIZATION_REFUSED", "PRECONDITION_REFUSED", "RESERVED",
                                           "MERGE_ATTEMPTED", "MERGED_VERIFIED",
                                           "UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION", "FAILED_SAFE"})
        for state in rpe.TERMINAL_STATES:
            self.assertNotIn(state, rpe.TRANSITIONS)
        self.assertNotIn(rpe.MERGE_ATTEMPTED, rpe.TRANSITIONS[rpe.PREPARED])
        self.assertEqual(rpe.TRANSITIONS[rpe.MERGE_ATTEMPTED],
                         (rpe.MERGED_VERIFIED, rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION, rpe.FAILED_SAFE))
        self.assertEqual(rpe.PRODUCTION_ACTIVATION_REQUIREMENTS[:len(rha.FUTURE_EXECUTOR_REQUIREMENTS)],
                         rha.FUTURE_EXECUTOR_REQUIREMENTS)


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

class StructureTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.code = re.sub(r'"""[\s\S]*?"""', "", self.source)

    def test_no_process_git_network_secret_env_or_write_entry_points(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        imports = {a.name for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names} | {n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("subprocess", "socket", "os", "shutil", "urllib", "http", "requests", "httpx", "github",
                       "runner_git", "runner_pipeline", "runner_factory_ledger", "claude_runner", "runner_promotion",
                       "hmac", "hashlib", "secrets", "ssl", "pickle", "sqlite3", "tempfile", "json", "asyncio",
                       "threading", "io", "glob"):
            self.assertNotIn(banned, imports, banned)
        for banned in ("_git", "Popen", "system", "check_output", "check_call", "urlopen", "HTTPConnection",
                       "getresponse", "post", "put", "patch", "delete", "merge", "push", "update_ref",
                       "update_branch", "create_ref", "approve", "create_review", "submit_review", "dismiss_review",
                       "create_comment", "open", "write_text", "write_bytes", "read_text", "read_bytes", "mkdir",
                       "unlink", "rename", "replace_file", "FactoryLedger", "DirLease", "try_acquire", "exec", "eval",
                       "getenv", "environ", "setattr", "__setattr__", "assess_promotion_readiness",
                       "revalidate_promotion_intent", "read_pr_gate", "read_human_decision_evidence",
                       "GITHUB_TOKEN", "token"):
            self.assertNotIn(banned, attrs | names, banned)
        for text in ("api.github.com", "https://", "http://", "Authorization", "Bearer", "git push", "update-ref",
                     "refs/heads/develop", "FAST_FORWARD_CANDIDATE_TO_DEVELOP"):
            self.assertNotIn(text, self.code, text)

    def test_host_calls_are_contract_methods_and_one_merge_site(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and ast.unparse(n.func.value) in ("host", "self.host")]
        self.assertEqual({c.func.attr for c in calls}, HOST_METHODS)
        merges = [c for c in calls if c.func.attr == "merge_pull_request"]
        self.assertEqual(len(merges), 1)
        self.assertEqual([ast.unparse(a) for a in merges[0].args],
                         ["r.repository", "r.pr_number", "r.head_sha", "MERGE_METHOD", "self.permit_id"])
        self.assertEqual(merges[0].keywords, [])
        line = {c.func.attr: c.lineno for c in calls if c.func.attr != "verify_human_command"}
        self.assertLess(line["consume_single_use"], line["merge_pull_request"])
        self.assertLess(line["reserve_single_use"], line["consume_single_use"])
        self.assertLess(line["merge_pull_request"], line["read_postcondition"])
        # The production entry never touches a host.
        prod = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_promotion")
        self.assertFalse([n for n in ast.walk(prod) if isinstance(n, ast.Name) and n.id in ("host", "_Attempt")])

    def test_no_code_path_produces_a_live_or_authorizing_outcome(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg in (
                    "live_authorized", "production_capable", "human_command_authenticated", "retry_allowed",
                    "executor_requirements_unmet", "authorizes_action", "execution_allowed",
                    "human_command_present"):
                self.fail(f"flag {node.arg} set outside its default")
        uses = [n for n in ast.walk(self.tree) if isinstance(n, ast.Name) and n.id == "MODE_LIVE_AUTHORIZED"]
        self.assertEqual(len(uses), 2)   # its definition and the EXECUTION_MODES vocabulary
        self.assertIs(rpe.PRODUCTION_PROMOTION_CAPABLE, False)
        self.assertNotIn("PRODUCTION_PROMOTION_CAPABLE =", self.code.replace("PRODUCTION_PROMOTION_CAPABLE = False", ""))

    def test_public_surface_and_no_bypass_parameters(self):
        public = {n.name for n in self.tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")}
        self.assertEqual(public, {
            "PromotionExecutionRequest", "PromotionExecutionRefused", "LeaseGrant", "HostCommandVerdict",
            "ReservationReceipt", "ConsumptionReceipt", "OperationPermit", "BranchProtectionState",
            "FreshPromotionState", "MergeResponse", "PostMergeObservation", "LeasePort", "HumanCommandPort",
            "SingleUseLedgerPort", "GitHubPromotionPort", "TrustedPromotionHost", "ExecutionStep",
            "PromotionExecutionOutcome", "request_fingerprint", "outcome_fingerprint", "prepare_execution_request",
            "simulate_promotion", "execute_promotion", "outcome_invariant_errors", "verify_outcome"})
        banned = {"approved", "approval", "is_trusted", "trusted", "trust_me", "token", "nonce", "signature", "hmac",
                  "secret", "key", "credential", "authorizes_action", "execution_allowed", "live", "force", "kwargs"}
        for func in (rpe.prepare_execution_request, rpe.simulate_promotion, rpe.execute_promotion):
            self.assertFalse(set(inspect.signature(func).parameters) & banned, func.__name__)
        types = (rpe.PromotionExecutionRequest, rpe.LeaseGrant, rpe.HostCommandVerdict, rpe.ReservationReceipt,
                 rpe.ConsumptionReceipt, rpe.OperationPermit, rpe.BranchProtectionState, rpe.FreshPromotionState,
                 rpe.MergeResponse, rpe.PostMergeObservation, rpe.ExecutionStep, rpe.PromotionExecutionOutcome)
        for cls in types:
            self.assertTrue(cls.__dataclass_params__.frozen, cls.__name__)
            for f in dataclasses.fields(cls):
                for word in ("token", "approved", "trusted", "signature", "hmac", "secret", "password", "nonce",
                             "credential", "url"):
                    self.assertNotIn(word, f.name, (cls.__name__, f.name))
        self.assertEqual(len({rpe.REQUEST_SCHEMA, rpe.OUTCOME_SCHEMA, rpe.IDEMPOTENCY_SCHEMA, rpe.LEASE_SCHEMA,
                              rpe.COMMAND_SCHEMA, rpe.RESERVATION_SCHEMA, rpe.CONSUMPTION_SCHEMA, rpe.PERMIT_SCHEMA,
                              rpe.PROTECTION_SCHEMA, rpe.FRESH_STATE_SCHEMA, rpe.MERGE_RESPONSE_SCHEMA,
                              rpe.POST_SCHEMA}), 12)

    def test_six_ci_jobs_unchanged_and_required(self):
        self.assertEqual(len(JOBS), 6)
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", workflow))
        self.assertEqual(sorted(jobs.values()), sorted(JOBS))
        self.assertEqual(rpe.EXECUTION_ACTIONS, ("MERGE_GITHUB_PR",))
        self.assertEqual(rpe.MERGE_METHOD, "merge")

    def test_docstring_states_the_boundary(self):
        doc = " ".join(rpe.__doc__.split())
        for phrase in ("NOT capable of promoting anything in production", "Merge API", "expected head SHA",
                       "strict (up-to-date) status checks", "merge queue", "never retried",
                       "never as a merge of this attempt", "LIVE_AUTHORIZED", "no code path produces",
                       "not an authenticated identity", "never authentication or signature",
                       "Nothing ever falls back to a direct write"):
            self.assertIn(phrase, doc, phrase)


if __name__ == "__main__":
    unittest.main()
