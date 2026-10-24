"""FCP-3B-2B1: human decision evidence and authorization boundary.

The intent, the fresh validation and the FCP-3B-2A gate results are REAL
objects built through the existing FCP-1/FCP-2B/FCP-3A/FCP-3B-1/FCP-3B-2A
fixtures (plain git for fixture construction only). Review events are
provider-neutral GitHub-shaped data built here; the module reads nothing
itself except, in host mode, one call of a fake review provider. Every
negative test starts from the complete positive fixture and alters one fact.
No result may ever authorize or allow execution.
"""

import ast
import dataclasses
import inspect
import json
import re
import socket
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import runner_promotion_authorization as rpa
from scripts.ai import runner_promotion_human_authorization as rha
from scripts.ai import runner_promotion_pr_gate as rpg
from scripts.tests import test_runner_promotion_pr_gate as tpg
from scripts.tests.test_runner_integration import _git_dir_state

MODULE_PATH = Path(rha.__file__)
PR = tpg.PR
REPO = rpg.CANONICAL_REPOSITORY
JOBS = rpg.REQUIRED_CI_JOBS
SHA_A = "a" * 40
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
OBSERVED = "2026-10-24T11:59:00Z"
AUTHOR, DIRECTOR, OTHER, BOT = 1001, 2002, 3003, 4004
LOGINS = {AUTHOR: "feature-author", DIRECTOR: "director-q", OTHER: "second-reviewer", BOT: "review-helper[bot]"}
FAVORABLE = (rha.REVIEW_CONSISTENT_UNVERIFIED, rha.REVIEW_READ_UNAUTHENTICATED)
_DEFAULT = object()

RESULT_FIELDS = (
    "classification", "reason_codes", "fingerprint", "mode", "identity", "review_sequence_fingerprint",
    "review_event_count", "reviewer_count", "current_approver_ids", "blocking_reviewer_ids", "stale_approval_count",
    "audit_trail", "review_evidence_consistent", "review_decision_appears_favorable", "executor_requirements_unmet",
    "source_unverified", "source_authenticated", "authenticated_human_command_present",
    "human_command_authenticated", "human_authorization_required", "authorizes_action", "execution_allowed",
    "schema",
)
IDENTITY_FIELDS = (
    "repository", "pr_number", "base_ref", "base_sha", "head_ref", "head_sha", "intent_fingerprint",
    "validation_fingerprint", "gate_context_fingerprint", "gate_result_fingerprint", "fingerprint", "schema",
)


def ts(seconds: int) -> str:
    return (datetime(2026, 10, 24, 11, 0, 0) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def review(sha, rid, state=rha.APPROVED, actor=DIRECTOR, at=None, **changes):
    return dataclasses.replace(rha.ReviewEvent(
        review_id=rid, repository=REPO, pr_number=PR, actor_id=actor, actor_login=LOGINS[actor],
        actor_type="Bot" if actor == BOT else "User", state=state, commit_sha=sha,
        submitted_at=ts(rid if at is None else at),
    ), **changes)


def sequence(head_sha, *events, **changes):
    return dataclasses.replace(rha.ReviewEventSequence(
        repository=REPO, pr_number=PR, pr_head_sha=head_sha, pr_author_id=AUTHOR, head_commit_author_id=AUTHOR,
        events=tuple(events), reported_total=len(events), page_size=100, pages_fetched=max(1, -(-len(events) // 100)),
        complete=True, observed_at=OBSERVED,
    ), **changes)


class FakeReviewProvider:
    """Records every call; returns the configured value or raises."""

    def __init__(self, value=None, fail=False):
        self.value, self.fail, self.calls = value, fail, []

    def read_review_events(self, repository, number):
        self.calls.append((repository, number))
        if self.fail:
            raise RuntimeError("ghp_provider-secret-token-xyz")
        return self.value


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class DecisionAssertions:
    def assertNeverExecutes(self, r):
        self.assertIs(type(r), rha.HumanDecisionEvaluation)
        self.assertIn(r.classification, rha.CLASSIFICATIONS)
        for flag, value in (("human_authorization_required", True), ("human_command_authenticated", False),
                            ("authenticated_human_command_present", False), ("authorizes_action", False),
                            ("execution_allowed", False), ("source_authenticated", False),
                            ("source_unverified", True)):
            self.assertIs(getattr(r, flag), value, flag)
        self.assertEqual(r.executor_requirements_unmet, rha.FUTURE_EXECUTOR_REQUIREMENTS)
        self.assertEqual(r.schema, rha.RESULT_SCHEMA)
        self.assertRegex(r.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(r.fingerprint, rha.evaluation_fingerprint(r))
        for code in rha._ALWAYS + rha._MODE_CODES[r.mode]:
            self.assertIn(code, r.reason_codes)
        self.assertEqual(len(r.reason_codes), len(set(r.reason_codes)))
        self.assertTrue(all(type(c) is str and c.startswith(("HAUTH_", "PR_GATE_", "INTENT_")) for c in r.reason_codes))
        self.assertIs(r.review_evidence_consistent, r.classification != rha.REJECTED)
        self.assertIs(r.review_decision_appears_favorable, r.classification in FAVORABLE)
        if r.identity is not None:
            self.assertIs(type(r.identity), rha.HumanDecisionIdentity)
            self.assertEqual(r.identity.fingerprint, rha.identity_fingerprint(r.identity))
        dumped = json.dumps(dataclasses.asdict(r))
        for leak in ("secret", "token", "ghp_", *LOGINS.values()):
            self.assertNotIn(leak, dumped)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.execution_allowed = True  # type: ignore[misc]
        return r

    def assertRejected(self, r, *codes):
        self.assertNeverExecutes(r)
        self.assertEqual(r.classification, rha.REJECTED, r.reason_codes)
        self.assertNotIn(rha.HAUTH_REVIEW_EVIDENCE_CONSISTENT, r.reason_codes)
        self.assertNotIn(rha.HAUTH_REVIEW_APPEARS_FAVORABLE, r.reason_codes)
        for code in codes:
            self.assertIn(code, r.reason_codes)
        return r

    def assertNotFavorable(self, r, *codes):
        self.assertNeverExecutes(r)
        self.assertEqual(r.classification, rha.REVIEW_NOT_FAVORABLE, r.reason_codes)
        self.assertIn(rha.HAUTH_REVIEW_EVIDENCE_CONSISTENT, r.reason_codes)
        self.assertNotIn(rha.HAUTH_REVIEW_APPEARS_FAVORABLE, r.reason_codes)
        for code in codes:
            self.assertIn(code, r.reason_codes)
        return r

    def assertFavorable(self, r, classification=rha.REVIEW_CONSISTENT_UNVERIFIED):
        self.assertNeverExecutes(r)
        self.assertEqual(r.classification, classification, r.reason_codes)
        self.assertIn(rha.HAUTH_REVIEW_APPEARS_FAVORABLE, r.reason_codes)
        self.assertTrue(r.current_approver_ids)
        self.assertEqual(r.blocking_reviewer_ids, ())
        return r


class SharedDecisionFixture(DecisionAssertions, tpg.SharedGateFixture):
    """One real intent, validation and reviewable FCP-3B-2A gate per class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gate_result = rpg.evaluate_pr_gate(cls.intent, cls.validation, tpg.snapshot(cls.intent), pr_number=PR)

    def setUp(self):
        super().setUp()
        self.assertEqual(self.gate_result.classification, rpg.REVIEWABLE_UNVERIFIED_SNAPSHOT,
                         self.gate_result.reason_codes)
        self.assertEqual(self.gate_result.satisfied_checks, JOBS)
        self.assertEqual(len(JOBS), 6)

    @property
    def head(self):
        return self.intent.head_sha

    def approve(self, rid=1, **changes):
        return review(self.head, rid, **changes)

    def seq(self, *events, **changes):
        return sequence(self.head, *events, **changes)

    def evaluate(self, seq=_DEFAULT, *, gate=_DEFAULT, intent=_DEFAULT, validation=_DEFAULT, pr_number=PR, now=NOW):
        return rha.evaluate_human_decision_evidence(
            self.gate_result if gate is _DEFAULT else gate, self.intent if intent is _DEFAULT else intent,
            self.validation if validation is _DEFAULT else validation,
            self.seq(self.approve()) if seq is _DEFAULT else seq, pr_number=pr_number, now=now)

    def real_gate(self, snap):
        return rpg.evaluate_pr_gate(self.intent, self.validation, snap, pr_number=PR)


# ---------------------------------------------------------------------------
# Positive (pure) - still never executable
# ---------------------------------------------------------------------------

class PositiveTests(SharedDecisionFixture):
    def test_current_human_approval_is_consistent_but_never_authorizing(self):
        r = self.assertFavorable(self.evaluate())
        self.assertEqual(r.mode, rha.MODE_SUPPLIED_SNAPSHOT)
        self.assertEqual(r.reason_codes, (
            rha.HAUTH_REVIEW_EVIDENCE_CONSISTENT, rha.HAUTH_REVIEW_APPEARS_FAVORABLE,
            rha.HAUTH_SOURCE_UNVERIFIED_SNAPSHOT) + rha._ALWAYS)
        self.assertIn(rha.HAUTH_HUMAN_COMMAND_NOT_AUTHENTICATED, r.reason_codes)
        self.assertIn(rha.HAUTH_NOT_AUTHORIZATION, r.reason_codes)
        self.assertEqual((r.current_approver_ids, r.reviewer_count, r.review_event_count), ((DIRECTOR,), 1, 1))
        self.assertEqual(r.review_sequence_fingerprint, rha.review_sequence_fingerprint(self.seq(self.approve())))
        self.assertEqual(r.audit_trail, (rha.ReviewAuditEntry(1, DIRECTOR, rha.APPROVED, True, ts(1),
                                                              rha.AUDIT_COUNTED_APPROVAL),))

    def test_identity_is_derived_from_the_verified_gate_context(self):
        i, c = self.evaluate().identity, self.gate_result.context
        self.assertEqual((i.repository, i.pr_number, i.base_ref, i.head_ref), (REPO, PR, "develop", "feature/fcp2b"))
        self.assertEqual((i.base_sha, i.head_sha), (self.intent.base_sha, self.intent.head_sha))
        self.assertEqual((i.intent_fingerprint, i.validation_fingerprint),
                         (self.intent.fingerprint, self.validation.fingerprint))
        self.assertEqual((i.gate_context_fingerprint, i.gate_result_fingerprint),
                         (c.fingerprint, self.gate_result.fingerprint))
        self.assertEqual(tuple(f.name for f in dataclasses.fields(i)), IDENTITY_FIELDS)

    def test_deterministic_and_serializable(self):
        a, b = self.evaluate(), self.evaluate()
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(dataclasses.asdict(a), sort_keys=True),
                         json.dumps(dataclasses.asdict(b), sort_keys=True))
        self.assertNotEqual(self.evaluate(self.seq(self.approve(2))).fingerprint, a.fingerprint)
        e = self.approve()
        self.assertEqual(rha.review_event_fingerprint(e), rha.review_event_fingerprint(self.approve()))

    def test_comments_never_grant_nor_revoke(self):
        events = (self.approve(1), review(self.head, 2, rha.COMMENTED),
                  review(self.head, 3, rha.COMMENTED, actor=AUTHOR),        # author answering a thread
                  review(self.head, 4, rha.COMMENTED, actor=BOT))           # bot comment: ignored
        r = self.assertFavorable(self.evaluate(self.seq(*events)))
        self.assertEqual([a.disposition for a in r.audit_trail], [
            rha.AUDIT_COUNTED_APPROVAL, rha.AUDIT_NON_DECISIVE_COMMENT, rha.AUDIT_NON_DECISIVE_COMMENT,
            rha.AUDIT_IGNORED_NON_HUMAN])
        self.assertNotFavorable(self.evaluate(self.seq(review(self.head, 1, rha.COMMENTED))),
                                rha.HAUTH_NO_CURRENT_APPROVAL)

    def test_gate_and_inputs_are_not_mutated(self):
        before = (dataclasses.asdict(self.gate_result), dataclasses.asdict(self.intent),
                  dataclasses.asdict(self.validation))
        seq = self.seq(self.approve())
        seq_before = dataclasses.asdict(seq)
        self.evaluate(seq)
        self.assertEqual(before, (dataclasses.asdict(self.gate_result), dataclasses.asdict(self.intent),
                                  dataclasses.asdict(self.validation)))
        self.assertEqual(seq_before, dataclasses.asdict(seq))
        self.assertEqual(self.gate_result.fingerprint, rpg.result_fingerprint(self.gate_result))
        self.assertIs(self.gate_result.authorizes_action, False)


# ---------------------------------------------------------------------------
# FCP-3B-2A gate and FCP-3B-1 binding
# ---------------------------------------------------------------------------

class GateBindingTests(SharedDecisionFixture):
    def test_real_non_reviewable_gates_are_rejected(self):
        i = self.intent
        without_last_job = [r for r in self.runs() if r.name != JOBS[-1]]
        policy = tpg.branch_policy(required_check_names=JOBS + ("security / scan",))
        cases = (
            (tpg.snapshot(i, pr=tpg.pr_meta(i, draft=True)), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.snapshot(i, pr=tpg.pr_meta(i, base_ref="main")), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.snapshot(i, pr=tpg.pr_meta(i, head_ref="feature/other")), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.snapshot(i, pr=tpg.pr_meta(i, head_sha=SHA_A)), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.snapshot(i, pr=tpg.pr_meta(i, base_branch_sha=SHA_A)), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.snapshot(i, checks=tpg.check_listing(i, without_last_job)), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.snapshot(i, checks=tpg.check_listing(i, self.runs(j3=dict(conclusion="failure")))),
             rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.snapshot(i, checks=tpg.check_listing(i, policy=policy)), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.snapshot(i, checks=tpg.check_listing(i, policy=None)), rha.HAUTH_GATE_POLICY_NOT_PROVEN),
        )
        for snap, code in cases:
            with self.subTest(code=code):
                gate = self.real_gate(snap)
                self.assertIs(gate.candidate_reviewable, False)
                r = self.assertRejected(self.evaluate(gate=gate), code)
                self.assertIsNone(r.identity)
                self.assertEqual(r.audit_trail, ())
        unbound = rpg.evaluate_pr_gate(i, None, tpg.snapshot(i), pr_number=PR)   # gate without a context
        self.assertIsNone(unbound.context)
        self.assertRejected(self.evaluate(gate=unbound), rha.HAUTH_GATE_NOT_REVIEWABLE, rha.HAUTH_GATE_CONTEXT_MISSING)

    def test_forged_or_foreign_gate_objects(self):
        g = self.gate_result

        @dataclasses.dataclass(frozen=True)
        class Approved(rpg.PrGateResult):
            approved: bool = True

        forged = (None, {}, dataclasses.asdict(g), tpg._Truthy(), g.context, self.intent, self.validation,
                  Approved(**{f.name: getattr(g, f.name) for f in dataclasses.fields(g)}),
                  dataclasses.replace(g, classification=tpg._Str(rpg.REVIEWABLE_UNVERIFIED_SNAPSHOT)),
                  dataclasses.replace(g, satisfied_checks=list(JOBS)),
                  tpg.reforged(g, rpg.result_fingerprint, context=g))
        for value in forged:
            with self.subTest(value=type(value)):
                self.assertRejected(self.evaluate(gate=value), rha.HAUTH_GATE_MALFORMED)

    def test_tampered_gate_or_context(self):
        g, c = self.gate_result, self.gate_result.context
        tampered = (
            dataclasses.replace(g, fingerprint="0" * 64),
            dataclasses.replace(g, ci_workflow_run_id=g.ci_workflow_run_id + 1),     # digest not recomputed
            tpg.reforged(g, rpg.result_fingerprint, authorizes_action=True),
            tpg.reforged(g, rpg.result_fingerprint, execution_allowed=True),
            tpg.reforged(g, rpg.result_fingerprint, source_authenticated=True),
            tpg.reforged(g, rpg.result_fingerprint, human_decision_present=True),
            tpg.reforged(g, rpg.result_fingerprint, human_approval_required=False),
            tpg.reforged(g, rpg.result_fingerprint, schema="fcp3b2a-pr-gate-result-v2"),
            tpg.reforged(g, rpg.result_fingerprint, mode="AUTHENTICATED_HOST"),
            # Self-consistent digests over content the gate never produces.
            tpg.reforged(g, rpg.result_fingerprint, reason_codes=g.reason_codes[1:]),
            tpg.reforged(g, rpg.result_fingerprint, source_freshness_proven=True),
            tpg.reforged(g, rpg.result_fingerprint, out_of_scope_path_count=1),
            tpg.reforged(g, rpg.result_fingerprint, changed_path_count=0),
            tpg.reforged(g, rpg.result_fingerprint, check_run_count=4),
            tpg.reforged(g, rpg.result_fingerprint, snapshot_fingerprint=None),
        )
        for value in tampered:
            with self.subTest(value=value.fingerprint):
                r = self.assertRejected(self.evaluate(gate=value), rha.HAUTH_GATE_TAMPERED)
                self.assertIsNone(r.identity)
        bad_context = dataclasses.replace(c, head_sha=SHA_A)          # digest not recomputed
        self.assertRejected(self.evaluate(gate=tpg.reforged(g, rpg.result_fingerprint, context=bad_context)),
                            rha.HAUTH_GATE_CONTEXT_TAMPERED)
        old_schema = tpg.reforged(c, rpg.context_fingerprint, schema="fcp3b2a-pr-gate-context-v0")
        self.assertRejected(self.evaluate(gate=tpg.reforged(g, rpg.result_fingerprint, context=old_schema)),
                            rha.HAUTH_GATE_CONTEXT_TAMPERED)

    def test_reforged_gate_claims_are_not_proven(self):
        g = self.gate_result
        rejected = self.real_gate(tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, base_ref="main")))
        cases = (
            (tpg.reforged(rejected, rpg.result_fingerprint, candidate_reviewable=True), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.reforged(g, rpg.result_fingerprint, candidate_reviewable=False), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.reforged(g, rpg.result_fingerprint, classification=rpg.REVIEWABLE_HOST_READ),
             rha.HAUTH_GATE_NOT_REVIEWABLE),
            (tpg.reforged(g, rpg.result_fingerprint, policy_proven=False), rha.HAUTH_GATE_POLICY_NOT_PROVEN),
            (tpg.reforged(g, rpg.result_fingerprint, satisfied_checks=JOBS[:-1]), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.reforged(g, rpg.result_fingerprint, required_checks=JOBS[:-1], satisfied_checks=JOBS[:-1]),
             rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.reforged(g, rpg.result_fingerprint, required_checks=JOBS[1:] + JOBS[:1],
                          satisfied_checks=JOBS[1:] + JOBS[:1]), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.reforged(g, rpg.result_fingerprint, required_checks=JOBS + ("z", "a"),
                          satisfied_checks=JOBS + ("z", "a")), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.reforged(g, rpg.result_fingerprint, required_checks=JOBS + (JOBS[0],),
                          satisfied_checks=JOBS + (JOBS[0],)), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.reforged(g, rpg.result_fingerprint, ci_workflow_run_id=None), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
            (tpg.reforged(g, rpg.result_fingerprint, ci_workflow_run_id=True), rha.HAUTH_GATE_CHECKS_NOT_PROVEN),
        )
        for gate, code in cases:
            with self.subTest(code=code, fp=gate.fingerprint):
                self.assertRejected(self.evaluate(gate=gate), code)

    def test_context_rebound_to_other_pr_head_base_or_intent(self):
        g, c = self.gate_result, self.gate_result.context
        for change in (dict(head_sha=SHA_A), dict(base_sha=SHA_A), dict(head_ref="feature/other"),
                       dict(base_ref="main"), dict(repository="attacker/quesada-abogados"),
                       dict(intent_fingerprint="d" * 64), dict(validation_fingerprint="d" * 64),
                       dict(authorized_scopes=("docs", "src"))):
            with self.subTest(change=change):
                ctx = tpg.reforged(c, rpg.context_fingerprint, **change)
                r = self.assertRejected(self.evaluate(gate=tpg.reforged(g, rpg.result_fingerprint, context=ctx)),
                                        rha.HAUTH_GATE_BINDING_MISMATCH)
                self.assertIsNone(r.identity)

    def test_altered_intent_or_validation(self):
        i, v = self.intent, self.validation
        wider = rpa.prepare_promotion_intent(self.readiness, proposed_action=tpg.FF, authorized_scopes=("docs", "src"))
        cases = (
            (dict(intent=wider), rpg.PR_GATE_VALIDATION_INTENT_MISMATCH),
            (dict(intent=dataclasses.replace(i, head_sha=SHA_A)), rpg.PR_GATE_INTENT_INVALID),
            (dict(intent=tpg.reforged(i, rpa.intent_fingerprint, authorizes_action=True)), rpg.PR_GATE_INTENT_INVALID),
            (dict(intent=None), rpg.PR_GATE_INTENT_INVALID),
            (dict(validation=None), rpg.PR_GATE_VALIDATION_MALFORMED),
            (dict(validation=tpg.reforged(v, rpa.validation_fingerprint, valid=False)),
             rpg.PR_GATE_VALIDATION_NOT_VALID),
            (dict(validation=rpa.validate_promotion_intent(i, self.readiness)), rpg.PR_GATE_VALIDATION_NOT_FRESH_MODE),
        )
        for kw, code in cases:
            with self.subTest(code=code):
                self.assertRejected(self.evaluate(**kw), rha.HAUTH_GATE_BINDING_MISMATCH, code)

    def test_pr_number_is_host_chosen_and_must_match(self):
        for number in (0, -1, True, "42", 42.0, 2 ** 31, None):
            with self.subTest(number=number):
                self.assertRejected(self.evaluate(pr_number=number), rha.HAUTH_PR_NUMBER_INVALID)
        self.assertRejected(self.evaluate(pr_number=PR + 1), rha.HAUTH_PR_NUMBER_MISMATCH)
        # A gate rebuilt for another PR is indistinguishable from a real one
        # (unkeyed digest): its reviews must then be those of that PR.
        ctx = tpg.reforged(self.gate_result.context, rpg.context_fingerprint, pr_number=PR + 1)
        other = tpg.reforged(self.gate_result, rpg.result_fingerprint, context=ctx)
        r = self.assertRejected(self.evaluate(gate=other, pr_number=PR + 1), rha.HAUTH_REVIEW_BINDING_MISMATCH)
        self.assertIn(rha.HAUTH_GATE_PROVENANCE_NOT_PROVEN, r.reason_codes)

    def test_clock_must_be_aware_utc(self):
        for now in (None, NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=2))),
                    "2026-10-24T12:00:00Z", 1729771200):
            with self.subTest(now=now):
                self.assertRejected(self.evaluate(now=now), rha.HAUTH_CLOCK_INVALID)


# ---------------------------------------------------------------------------
# Review events
# ---------------------------------------------------------------------------

class ReviewDecisionTests(SharedDecisionFixture):
    def test_no_current_approval(self):
        r = self.assertNotFavorable(self.evaluate(self.seq()), rha.HAUTH_NO_CURRENT_APPROVAL)
        self.assertEqual((r.reviewer_count, r.review_event_count, r.audit_trail), (0, 0, ()))
        r = self.assertNotFavorable(self.evaluate(self.seq(review(self.intent.base_sha, 1))),
                                    rha.HAUTH_NO_CURRENT_APPROVAL, rha.HAUTH_APPROVAL_STALE_COMMIT)
        self.assertEqual(r.stale_approval_count, 1)
        self.assertEqual(r.audit_trail[0].disposition, rha.AUDIT_STALE_COMMIT_APPROVAL)
        self.assertIs(r.audit_trail[0].on_head_commit, False)

    def test_latest_decisive_state_per_reviewer(self):
        h, old = self.head, self.intent.base_sha
        cases = (
            # (events, favorable, codes, dispositions)
            ((review(old, 1), review(h, 2)), True, (rha.HAUTH_REVIEW_APPEARS_FAVORABLE,),
             (rha.AUDIT_SUPERSEDED, rha.AUDIT_COUNTED_APPROVAL)),
            ((review(h, 1), review(h, 2, rha.CHANGES_REQUESTED)), False,
             (rha.HAUTH_CHANGES_REQUESTED, rha.HAUTH_NO_CURRENT_APPROVAL),
             (rha.AUDIT_SUPERSEDED, rha.AUDIT_BLOCKING_CHANGES_REQUESTED)),
            ((review(h, 1, rha.CHANGES_REQUESTED), review(h, 2)), True, (),
             (rha.AUDIT_SUPERSEDED, rha.AUDIT_COUNTED_APPROVAL)),
            ((review(h, 1, rha.DISMISSED),), False, (rha.HAUTH_NO_CURRENT_APPROVAL, rha.HAUTH_APPROVAL_DISMISSED),
             (rha.AUDIT_DISMISSED,)),
            # A dismissed later review never revives the older approval.
            ((review(h, 1), review(h, 2, rha.DISMISSED)), False, (rha.HAUTH_NO_CURRENT_APPROVAL,),
             (rha.AUDIT_SUPERSEDED, rha.AUDIT_DISMISSED)),
            ((review(h, 1), review(h, 2, rha.CHANGES_REQUESTED, actor=OTHER)), False, (rha.HAUTH_CHANGES_REQUESTED,),
             (rha.AUDIT_COUNTED_APPROVAL, rha.AUDIT_BLOCKING_CHANGES_REQUESTED)),
            # Changes requested on an older commit still block.
            ((review(h, 1), review(old, 2, rha.CHANGES_REQUESTED, actor=OTHER)), False,
             (rha.HAUTH_CHANGES_REQUESTED,), (rha.AUDIT_COUNTED_APPROVAL, rha.AUDIT_BLOCKING_CHANGES_REQUESTED)),
            ((review(h, 1), review(old, 2, actor=OTHER)), True, (rha.HAUTH_APPROVAL_STALE_COMMIT,),
             (rha.AUDIT_COUNTED_APPROVAL, rha.AUDIT_STALE_COMMIT_APPROVAL)),
            ((review(h, 1), review(h, 2, rha.COMMENTED)), True, (),
             (rha.AUDIT_COUNTED_APPROVAL, rha.AUDIT_NON_DECISIVE_COMMENT)),
        )
        for events, favorable, codes, dispositions in cases:
            with self.subTest(events=[(e.review_id, e.actor_id, e.state) for e in events]):
                r = self.evaluate(self.seq(*events))
                if favorable:
                    self.assertFavorable(r)
                else:
                    self.assertNotFavorable(r)
                for code in codes:
                    self.assertIn(code, r.reason_codes)
                self.assertEqual(tuple(a.disposition for a in r.audit_trail), dispositions)
        r = self.evaluate(self.seq(review(h, 1), review(h, 2, rha.CHANGES_REQUESTED, actor=OTHER)))
        self.assertEqual((r.current_approver_ids, r.blocking_reviewer_ids, r.reviewer_count), ((DIRECTOR,), (OTHER,), 2))

    def test_bots_and_non_human_actors(self):
        cases = (
            review(self.head, 1, actor=BOT),
            review(self.head, 1, actor=BOT, state=rha.CHANGES_REQUESTED),
            review(self.head, 1, actor_login="ci-helper[bot]"),               # "User" with a bot login
            review(self.head, 1, actor_type="Organization"),
            review(self.head, 1, actor_type="Mannequin"),
        )
        for event in cases:
            with self.subTest(event=(event.actor_type, event.actor_login, event.state)):
                r = self.assertRejected(self.evaluate(self.seq(event)), rha.HAUTH_REVIEW_ACTOR_NOT_HUMAN)
                self.assertEqual(r.audit_trail[0].disposition, rha.AUDIT_IGNORED_NON_HUMAN)
                self.assertEqual(r.current_approver_ids, ())

    def test_self_approval(self):
        r = self.assertRejected(self.evaluate(self.seq(review(self.head, 1, actor=AUTHOR))),
                                rha.HAUTH_REVIEW_SELF_APPROVAL)
        self.assertEqual(r.audit_trail[0].disposition, rha.AUDIT_SELF_APPROVAL)
        # Even next to a genuine approval.
        self.assertRejected(self.evaluate(self.seq(self.approve(1), review(self.head, 2, actor=AUTHOR))),
                            rha.HAUTH_REVIEW_SELF_APPROVAL)
        # Known head commit author other than the PR author.
        self.assertRejected(self.evaluate(self.seq(self.approve(1), head_commit_author_id=DIRECTOR)),
                            rha.HAUTH_REVIEW_SELF_APPROVAL)
        # Unknown head commit author: not fabricated, marked UNPROVEN.
        r = self.assertFavorable(self.evaluate(self.seq(self.approve(1), head_commit_author_id=None)))
        self.assertIn(rha.HAUTH_COMMIT_AUTHOR_UNPROVEN, r.reason_codes)
        self.assertNotIn(rha.HAUTH_COMMIT_AUTHOR_UNPROVEN, self.evaluate().reason_codes)

    def test_actor_identity_is_numeric_and_consistent(self):
        renamed = (self.approve(1), self.approve(2, actor_login="director-renamed"))
        borrowed = (self.approve(1), review(self.head, 2, actor=OTHER, actor_login=LOGINS[DIRECTOR]))
        for events in (renamed, borrowed):
            with self.subTest(events=events):
                self.assertRejected(self.evaluate(self.seq(*events)), rha.HAUTH_REVIEW_ACTOR_INCONSISTENT)
        self.assertFavorable(self.evaluate(self.seq(self.approve(1), self.approve(2, actor_login="Director-Q"))))
        for change in (dict(actor_id=0), dict(actor_id=-1), dict(actor_id=True), dict(actor_id=None),
                       dict(actor_login=""), dict(actor_login="has space"), dict(actor_login="x" * 40),
                       dict(actor_login="-lead"), dict(actor_login=None), dict(actor_type="user"),
                       dict(actor_type="Enterprise"), dict(actor_type=None)):
            with self.subTest(change=change):
                r = self.assertRejected(self.evaluate(self.seq(self.approve(1, **change))),
                                        rha.HAUTH_REVIEW_ACTOR_INVALID)
                self.assertEqual(r.audit_trail, ())
        for change in (dict(pr_author_id=0), dict(pr_author_id=None), dict(head_commit_author_id=True)):
            with self.subTest(change=change):
                self.assertRejected(self.evaluate(self.seq(self.approve(), **change)), rha.HAUTH_REVIEW_ACTOR_INVALID)

    def test_unknown_states_fail_closed(self):
        for state in ("PENDING", "approved", "REQUEST_CHANGES", "", None, 1):
            with self.subTest(state=state):
                self.assertRejected(self.evaluate(self.seq(self.approve(1), self.approve(2, state=state))),
                                    rha.HAUTH_REVIEW_STATE_UNKNOWN)

    def test_timestamps(self):
        for value in ("2026-10-24T11:01:00", "2026-10-24T11:01:00+00:00", "2026-10-24T13:01:00+02:00",
                      "2026-10-24 11:01:00Z", "2026-10-24T11:01:00.123Z", "2026-02-30T11:01:00Z", "", None,
                      1729767660, "2026-10-24t11:01:00z"):
            with self.subTest(value=value):
                self.assertRejected(self.evaluate(self.seq(self.approve(1, submitted_at=value))),
                                    rha.HAUTH_REVIEW_TIMESTAMP_INVALID)
                self.assertRejected(self.evaluate(self.seq(self.approve(1), observed_at=value)),
                                    rha.HAUTH_REVIEW_TIMESTAMP_INVALID)
        cases = (
            (self.seq(self.approve(1, submitted_at="2026-10-24T11:59:01Z")), rha.HAUTH_REVIEW_TIMESTAMP_FUTURE),
            (self.seq(self.approve(1), observed_at="2026-10-24T12:00:01Z"), rha.HAUTH_REVIEW_TIMESTAMP_FUTURE),
            (self.seq(self.approve(1), observed_at="2026-10-24T11:54:59Z"), rha.HAUTH_REVIEW_SNAPSHOT_STALE),
            (self.seq(self.approve(2, at=10), self.approve(3, at=9)), rha.HAUTH_REVIEW_ORDER_INVALID),
        )
        for seq, code in cases:
            with self.subTest(code=code):
                self.assertRejected(self.evaluate(seq), code)
        self.assertFavorable(self.evaluate(self.seq(self.approve(1), observed_at="2026-10-24T11:55:00Z")))
        self.assertFavorable(self.evaluate(self.seq(self.approve(1, submitted_at=OBSERVED))))
        self.assertFavorable(self.evaluate(self.seq(review(self.head, 1, rha.COMMENTED, at=5), self.approve(2, at=5))))

    def test_listing_must_be_complete(self):
        many = tuple(review(self.head, n, rha.COMMENTED, actor=OTHER) for n in range(1, 151)) + (self.approve(151),)
        self.assertFavorable(self.evaluate(self.seq(*many)))
        cases = (
            self.seq(self.approve(), complete=False), self.seq(self.approve(), complete=1),
            self.seq(self.approve(), complete=None), self.seq(self.approve(), reported_total=2),
            self.seq(self.approve(), reported_total=None), self.seq(self.approve(), reported_total=True),
            self.seq(self.approve(), pages_fetched=2), self.seq(self.approve(), page_size=0),
            self.seq(self.approve(), page_size=101), self.seq(*many, pages_fetched=1),
            self.seq(*many[:100], reported_total=len(many)),                  # only the first page
        )
        for seq in cases:
            with self.subTest(seq=(seq.complete, seq.reported_total, seq.page_size, seq.pages_fetched)):
                self.assertRejected(self.evaluate(seq), rha.HAUTH_REVIEWS_INCOMPLETE)

    def test_duplicate_review_ids(self):
        events = (self.approve(1, at=1), self.approve(1, at=2))
        self.assertRejected(self.evaluate(self.seq(*events)), rha.HAUTH_REVIEW_DUPLICATE_ID)
        events = (self.approve(1), review(self.head, 1, rha.CHANGES_REQUESTED, actor=OTHER, at=2))
        self.assertRejected(self.evaluate(self.seq(*events)), rha.HAUTH_REVIEW_DUPLICATE_ID)

    def test_review_binding_and_head(self):
        cases = (
            (self.seq(self.approve(), pr_head_sha=SHA_A), rha.HAUTH_REVIEW_PR_HEAD_MOVED),
            (self.seq(self.approve(), pr_head_sha=self.head.upper()), rha.HAUTH_REVIEW_SHA_INVALID),
            (self.seq(self.approve(), pr_head_sha="b" * 64), rha.HAUTH_REVIEW_SHA_INVALID),
            (self.seq(self.approve(commit_sha=self.head[:12])), rha.HAUTH_REVIEW_SHA_INVALID),
            (self.seq(self.approve(commit_sha=None)), rha.HAUTH_REVIEW_SHA_INVALID),
            (self.seq(self.approve(), pr_number=PR + 1), rha.HAUTH_REVIEW_BINDING_MISMATCH),
            (self.seq(self.approve(), pr_number=True), rha.HAUTH_REVIEW_BINDING_MISMATCH),
            (self.seq(self.approve(), repository="Ignacio-Alvarez93/Quesada-Abogados"),
             rha.HAUTH_REVIEW_BINDING_MISMATCH),
            (self.seq(self.approve(pr_number=PR + 1)), rha.HAUTH_REVIEW_BINDING_MISMATCH),
            (self.seq(self.approve(repository="attacker/quesada-abogados")), rha.HAUTH_REVIEW_BINDING_MISMATCH),
            (self.seq(self.approve(review_id=0)), rha.HAUTH_REVIEWS_MALFORMED),
            (self.seq(self.approve(review_id=True)), rha.HAUTH_REVIEWS_MALFORMED),
            (self.seq(self.approve(schema="fcp3b2b1-review-event-v2")), rha.HAUTH_REVIEWS_MALFORMED),
        )
        for seq, code in cases:
            with self.subTest(code=code, seq=seq.pr_head_sha):
                self.assertRejected(self.evaluate(seq), code)

    def test_malformed_or_malicious_sequences(self):
        good = self.seq(self.approve())

        @dataclasses.dataclass(frozen=True)
        class Approved(rha.ReviewEventSequence):
            approved: bool = True

        self.assertRejected(self.evaluate(None), rha.HAUTH_REVIEWS_MISSING)
        cases = (
            {}, dataclasses.asdict(good), "APPROVED", True, tpg._Truthy(), self.approve(),
            Approved(**{f.name: getattr(good, f.name) for f in dataclasses.fields(good)}),
            dataclasses.replace(good, events=list(good.events)),
            dataclasses.replace(good, events=(dataclasses.asdict(self.approve()),)),
            dataclasses.replace(good, events=(tpg._Truthy(),)),
            dataclasses.replace(good, events=self.approve()),
            dataclasses.replace(good, events=(self.approve(actor_login=tpg._Str("director-q")),)),
            dataclasses.replace(good, events=(self.approve(state=tpg._Str(rha.APPROVED)),)),
            dataclasses.replace(good, pr_head_sha=tpg._Str(SHA_A)),
            dataclasses.replace(good, complete=tpg._Truthy()),
            dataclasses.replace(good, schema="fcp3b2b1-review-sequence-v2"),
        )
        for value in cases:
            with self.subTest(value=type(value)):
                r = self.assertRejected(self.evaluate(value), rha.HAUTH_REVIEWS_MALFORMED)
                self.assertIsNone(r.review_sequence_fingerprint)
                self.assertEqual(r.audit_trail, ())


# ---------------------------------------------------------------------------
# No authority input; never raises
# ---------------------------------------------------------------------------

class AuthorityBoundaryTests(SharedDecisionFixture):
    def test_no_approval_trust_or_signature_input(self):
        args = (self.gate_result, self.intent, self.validation, self.seq(self.approve()))
        for extra in (dict(approved=True), dict(trust_me=True), dict(token="t"), dict(nonce="n"),
                      dict(signature="s"), dict(hmac_key="k"), dict(certificate="c"), dict(authorizes_action=True),
                      dict(execution_allowed=True), dict(human_command_authenticated=True)):
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                rha.evaluate_human_decision_evidence(*args, pr_number=PR, now=NOW, **extra)
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                rha.read_human_decision_evidence(*args[:3], FakeReviewProvider(args[3]), pr_number=PR, now=NOW,
                                                 **extra)
        with self.assertRaises(TypeError):  # keyword-only PR number and clock
            rha.evaluate_human_decision_evidence(*args, PR, NOW)

    def test_favorable_review_or_green_ci_alone_never_authorizes(self):
        many = tuple(review(self.head, n, actor=a) for n, a in enumerate((DIRECTOR, OTHER), start=1))
        r = self.assertFavorable(self.evaluate(self.seq(*many)))
        self.assertEqual(r.current_approver_ids, (DIRECTOR, OTHER))
        self.assertIs(r.authenticated_human_command_present, False)
        self.assertIs(r.human_command_authenticated, False)
        self.assertIs(r.authorizes_action, False)
        self.assertIs(r.execution_allowed, False)
        self.assertIn(rha.HAUTH_EXECUTOR_CONTRACT_UNMET, r.reason_codes)
        self.assertEqual(self.gate_result.satisfied_checks, JOBS)

    def test_evaluation_never_raises_or_leaks(self):
        for target in ("_bind", "_decide", "_review_findings"):
            with self.subTest(target=target), \
                    mock.patch.object(rha, target, side_effect=RuntimeError("secret-detail-token")):
                r = self.assertRejected(self.evaluate(), rha.HAUTH_EVALUATION_FAILED)
                self.assertIsNone(r.identity)
        with mock.patch.object(rpg, "_bind", side_effect=RuntimeError("secret-detail")):
            self.assertRejected(self.evaluate(), rha.HAUTH_EVALUATION_FAILED)
        with mock.patch.object(rpg, "result_fingerprint", side_effect=RuntimeError("secret")):
            self.assertRejected(self.evaluate(), rha.HAUTH_GATE_TAMPERED)


# ---------------------------------------------------------------------------
# Host read (fake provider, read-only)
# ---------------------------------------------------------------------------

class HostReadTests(SharedDecisionFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        provider = tpg.FakeProvider(tpg.pr_meta(cls.intent), tpg.file_listing(), tpg.check_listing(cls.intent))
        cls.host_gate = rpg.read_pr_gate(cls.intent, provider, cls.fx.wt, pr_number=PR, **cls.kw)

    def read(self, provider, gate=_DEFAULT, pr_number=PR, now=NOW, **kw):
        return rha.read_human_decision_evidence(self.host_gate if gate is _DEFAULT else gate,
                                                kw.get("intent", self.intent), kw.get("validation", self.validation),
                                                provider, pr_number=pr_number, now=now)

    def test_host_read_is_unauthenticated_and_never_authorizing(self):
        self.assertEqual(self.host_gate.classification, rpg.REVIEWABLE_HOST_READ, self.host_gate.reason_codes)
        provider = FakeReviewProvider(self.seq(self.approve()))
        r = self.assertFavorable(self.read(provider), rha.REVIEW_READ_UNAUTHENTICATED)
        self.assertEqual(r.mode, rha.MODE_HOST_PROVIDER_READ)
        self.assertIn(rha.HAUTH_HOST_PROVIDER_READ_UNAUTHENTICATED, r.reason_codes)
        self.assertNotIn(rha.HAUTH_SOURCE_UNVERIFIED_SNAPSHOT, r.reason_codes)
        self.assertEqual(provider.calls, [(REPO, PR)])
        self.assertTrue(all(type(a) in (str, int) for a in provider.calls[0]))
        self.assertEqual(r.identity.gate_result_fingerprint, self.host_gate.fingerprint)
        # A supplied-snapshot gate is accepted too; the review read stays unauthenticated.
        self.assertFavorable(self.read(FakeReviewProvider(self.seq(self.approve())), gate=self.gate_result),
                             rha.REVIEW_READ_UNAUTHENTICATED)

    def test_default_clock_is_system_utc(self):
        observed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        provider = FakeReviewProvider(self.seq(self.approve(submitted_at=observed), observed_at=observed))
        r = rha.read_human_decision_evidence(self.host_gate, self.intent, self.validation, provider, pr_number=PR)
        self.assertFavorable(r, rha.REVIEW_READ_UNAUTHENTICATED)
        stale = FakeReviewProvider(self.seq(self.approve(submitted_at="2019-12-31T23:00:00Z"),
                                            observed_at="2020-01-01T00:00:00Z"))
        r = rha.read_human_decision_evidence(self.host_gate, self.intent, self.validation, stale, pr_number=PR)
        self.assertRejected(r, rha.HAUTH_REVIEW_SNAPSHOT_STALE)

    def test_regression_default_clock_is_read_after_the_provider(self):
        # Bug found in review: the clock was read BEFORE the provider call, so
        # any host read instant taken during the read looked "future" and a
        # genuine host read was always REJECTED.
        log = []

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                log.append("clock")
                return cls(2026, 10, 24, 12, 0, 6, tzinfo=timezone.utc)

        class ReadingProvider(FakeReviewProvider):
            def read_review_events(self, repository, number):
                log.append("read")
                return super().read_review_events(repository, number)

        provider = ReadingProvider(self.seq(self.approve(), observed_at="2026-10-24T12:00:05Z"))
        with mock.patch.object(rha, "datetime", Clock):
            r = rha.read_human_decision_evidence(self.host_gate, self.intent, self.validation, provider, pr_number=PR)
        self.assertFavorable(r, rha.REVIEW_READ_UNAUTHENTICATED)
        self.assertEqual(log, ["read", "clock"])

    def test_provider_failure_is_fail_closed_and_leaks_nothing(self):
        provider = FakeReviewProvider(self.seq(self.approve()), fail=True)
        r = self.assertRejected(self.read(provider), rha.HAUTH_PROVIDER_READ_FAILED)
        self.assertEqual(len(provider.calls), 1)
        self.assertIsNotNone(r.identity)
        for broken in (object(), None, tpg._Truthy()):
            with self.subTest(provider=type(broken)):
                self.assertRejected(self.read(broken), rha.HAUTH_PROVIDER_READ_FAILED)

    def test_provider_returning_missing_or_garbage(self):
        self.assertRejected(self.read(FakeReviewProvider(None)), rha.HAUTH_REVIEWS_MISSING)
        for value in ({}, tpg._Truthy(), [self.approve()], dataclasses.asdict(self.seq(self.approve()))):
            with self.subTest(value=type(value)):
                self.assertRejected(self.read(FakeReviewProvider(value)), rha.HAUTH_REVIEWS_MALFORMED)
        self.assertRejected(self.read(FakeReviewProvider(self.seq(self.approve(), complete=False))),
                            rha.HAUTH_REVIEWS_INCOMPLETE)
        self.assertNotFavorable(self.read(FakeReviewProvider(self.seq())), rha.HAUTH_NO_CURRENT_APPROVAL)

    def test_unbindable_request_reads_nothing(self):
        rejected = self.real_gate(tpg.snapshot(self.intent, pr=tpg.pr_meta(self.intent, draft=True)))
        cases = (
            (dict(gate=rejected), rha.HAUTH_GATE_NOT_REVIEWABLE),
            (dict(gate=tpg.reforged(self.host_gate, rpg.result_fingerprint, execution_allowed=True)),
             rha.HAUTH_GATE_TAMPERED),
            (dict(pr_number=0), rha.HAUTH_PR_NUMBER_INVALID),
            (dict(pr_number=PR + 1), rha.HAUTH_PR_NUMBER_MISMATCH),
            (dict(validation=None), rha.HAUTH_GATE_BINDING_MISMATCH),
            (dict(now=NOW.replace(tzinfo=None)), rha.HAUTH_CLOCK_INVALID),
        )
        for kw, code in cases:
            with self.subTest(code=code):
                provider = FakeReviewProvider(self.seq(self.approve()))
                self.assertRejected(self.read(provider, **kw), code)
                self.assertEqual(provider.calls, [])

    def test_nothing_written_and_no_network(self):
        git_dir = self.fx.repo / ".git"
        before = _git_dir_state([git_dir])
        refuse = mock.Mock(side_effect=AssertionError("network used"))
        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse):
            r = self.read(FakeReviewProvider(self.seq(self.approve())))
            self.evaluate()
        self.assertFavorable(r, rha.REVIEW_READ_UNAUTHENTICATED)
        refuse.assert_not_called()
        self.assertEqual(_git_dir_state([git_dir]), before)
        self.assertEqual(sorted(self.ledger.iterdir()), [])


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

class StructureTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_no_git_process_network_write_or_merge_entry_points(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        imports = {a.name for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names} | {n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("subprocess", "socket", "os", "shutil", "urllib", "http", "requests", "httpx", "github",
                       "runner_git", "runner_pipeline", "runner_factory_ledger", "claude_runner", "runner_promotion",
                       "hmac", "secrets", "ssl", "pickle", "sqlite3", "tempfile", "json", "asyncio", "threading"):
            self.assertNotIn(banned, imports, banned)
        for banned in ("_git", "assess_integration", "analyze_reconciliation", "assess_promotion_readiness",
                       "revalidate_promotion_intent", "read_pr_gate", "run", "Popen", "system", "check_output",
                       "urlopen", "request", "post", "put", "patch", "delete", "merge", "merge_pull_request",
                       "push", "update_ref", "update_branch", "create_ref", "approve", "create_review",
                       "submit_review", "dismiss_review", "create_comment", "open", "write_text", "write_bytes",
                       "mkdir", "unlink", "FactoryLedger", "DirLease", "try_acquire", "exec", "eval", "getenv",
                       "environ", "setattr", "__setattr__", "object"):
            self.assertNotIn(banned, attrs | names, banned)

    def test_provider_is_only_asked_to_read_reviews_once(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "provider"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].func.attr, "read_review_events")
        self.assertEqual([ast.unparse(a) for a in calls[0].args], ["identity.repository", "identity.pr_number"])
        self.assertEqual(calls[0].keywords, [])

    def test_public_surface_has_no_approval_or_execution_entry_point(self):
        public = {n.name for n in self.tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")}
        self.assertEqual(public, {
            "ReviewEvent", "ReviewEventSequence", "ReviewEventProvider", "HumanDecisionIdentity", "ReviewAuditEntry",
            "HumanDecisionEvaluation", "identity_fingerprint", "evaluation_fingerprint", "review_event_fingerprint",
            "review_sequence_fingerprint", "evaluate_human_decision_evidence", "read_human_decision_evidence"})
        protocol = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "ReviewEventProvider")
        self.assertEqual({m.name for m in protocol.body if isinstance(m, ast.FunctionDef)}, {"read_review_events"})
        for func in (rha.evaluate_human_decision_evidence, rha.read_human_decision_evidence):
            params = set(inspect.signature(func).parameters)
            self.assertFalse(params & {"approved", "approval", "trust_me", "token", "nonce", "signature", "key",
                                       "certificate", "credential", "callback", "client", "authorizes_action",
                                       "execution_allowed", "kwargs"}, func.__name__)

    def test_result_and_identity_schema(self):
        self.assertEqual(tuple(f.name for f in dataclasses.fields(rha.HumanDecisionEvaluation)), RESULT_FIELDS)
        self.assertEqual(tuple(f.name for f in dataclasses.fields(rha.HumanDecisionIdentity)), IDENTITY_FIELDS)
        types = (rha.ReviewEvent, rha.ReviewEventSequence, rha.HumanDecisionIdentity, rha.ReviewAuditEntry,
                 rha.HumanDecisionEvaluation)
        for cls in types:
            self.assertTrue(cls.__dataclass_params__.frozen, cls.__name__)
            for f in dataclasses.fields(cls):
                for word in ("token", "approved", "signature", "credential", "secret", "password", "key", "nonce",
                             "url", "title", "body", "permission"):
                    self.assertNotIn(word, f.name, (cls.__name__, f.name))
        defaults = {f.name: f.default for f in dataclasses.fields(rha.HumanDecisionEvaluation)}
        self.assertEqual({k: defaults[k] for k in (
            "source_unverified", "source_authenticated", "authenticated_human_command_present",
            "human_command_authenticated", "human_authorization_required", "authorizes_action",
            "execution_allowed")}, dict(source_unverified=True, source_authenticated=False,
                                        authenticated_human_command_present=False, human_command_authenticated=False,
                                        human_authorization_required=True, authorizes_action=False,
                                        execution_allowed=False))
        self.assertEqual(len({rha.EVENT_SCHEMA, rha.SEQUENCE_SCHEMA, rha.IDENTITY_SCHEMA, rha.RESULT_SCHEMA}), 4)

    def test_no_code_path_constructs_an_authorizing_result(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg in (
                    "authorizes_action", "execution_allowed", "source_authenticated", "human_command_authenticated",
                    "authenticated_human_command_present", "human_authorization_required", "source_unverified",
                    "executor_requirements_unmet"):
                self.fail(f"result flag {node.arg} set outside its default")
        self.assertNotIn("FAST_FORWARD_CANDIDATE_TO_DEVELOP", re.sub(r'"""[\s\S]*?"""', "", self.source))

    def test_future_executor_requirements_are_documented_not_implemented(self):
        doc = rha.__doc__
        for phrase in ("authenticated identity of the human Director", "ONE PR + head SHA + base ref/SHA + action",
                       "short expiry", "revocation", "single-use consumption", "lock/lease",
                       "fresh verification immediately before the operation", "six Fabric CI jobs",
                       "Pull Request Merge API with the", "expected head SHA", "branch protection or the merge queue",
                       "PR is merged", "uncertain states", "BLOCK", "never fall", "direct Git writes"):
            self.assertIn(phrase, " ".join(doc.split()), phrase)
        self.assertEqual(len(set(rha.FUTURE_EXECUTOR_REQUIREMENTS)), len(rha.FUTURE_EXECUTOR_REQUIREMENTS))
        self.assertTrue(all(r.startswith("EXEC_REQ_") for r in rha.FUTURE_EXECUTOR_REQUIREMENTS))

    def test_vocabularies(self):
        self.assertEqual(rha.REVIEW_STATES, ("APPROVED", "CHANGES_REQUESTED", "DISMISSED", "COMMENTED"))
        self.assertNotIn("PENDING", rha.REVIEW_STATES)
        self.assertEqual(rha.CLASSIFICATIONS, (rha.REJECTED, rha.REVIEW_NOT_FAVORABLE,
                                               rha.REVIEW_CONSISTENT_UNVERIFIED, rha.REVIEW_READ_UNAUTHENTICATED))
        self.assertEqual(rpg.REQUIRED_CI_JOBS, JOBS)
        self.assertEqual(len(JOBS), 6)


if __name__ == "__main__":
    unittest.main()
