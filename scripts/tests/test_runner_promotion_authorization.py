"""FCP-3B-1: approval-bound promotion intent and fresh revalidation.

Repositories are throwaways under a temporary directory, built with PLAIN
git through the existing FCP-1/FCP-2B/FCP-3A fixtures (fixture construction
only). The module under test reads nothing itself: every fact comes from
REAL FCP-3A readinesses, and the only read is one FCP-3A
`assess_promotion_readiness` call. Tamper tests start from real readinesses
and intents and alter exactly one fact.
"""

import ast
import dataclasses
import inspect
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_integration as ri
from scripts.ai import runner_pipeline as pipeline
from scripts.ai import runner_promotion as rp
from scripts.ai import runner_promotion_authorization as rpa
from scripts.ai import runner_reconciliation as rr
from scripts.tests.test_runner_integration import (
    _ISOLATED_ENV, REMOTE_URL, _git_dir_state, _rmtree, good_evidence, head, write,
)
from scripts.tests.test_runner_promotion import PromotionTestCase
from scripts.tests.test_runner_reconciliation import SCOPES, Fixture, text

MODULE_PATH = Path(rpa.__file__)
FF = rpa.FAST_FORWARD_CANDIDATE_TO_DEVELOP

INTENT_FIELDS = (
    "status", "proposed_action", "reason_codes", "fingerprint", "readiness_fingerprint",
    "readiness_classification", "reconciliation_fingerprint", "reconciliation_classification",
    "assessment_fingerprint", "assessment_classification", "worktree_key", "head_ref", "head_sha",
    "canonical_base_ref", "base_sha", "attested_sha", "merge_bases", "authorized_scopes",
    "human_approval_required", "authorizes_action", "execution_allowed", "schema",
)
VALIDATION_FIELDS = (
    "valid", "outcome", "reason_codes", "fingerprint", "mode", "intent_fingerprint",
    "fresh_readiness_fingerprint", "fresh_readiness_classification", "mismatched_fields",
    "human_approval_required", "authorizes_action", "execution_allowed", "schema",
)
SHA_A, SHA_B = "a" * 40, "b" * 40
_DEFAULT = object()  # "use the fixture's value", distinct from an explicit None


class _Str(str):
    """A str subclass that lies about equality."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


def reforged_readiness(r, **changes):
    """`r` with `changes`, re-fingerprinted so it is self-consistent."""
    draft = dataclasses.replace(r, **changes)
    return dataclasses.replace(draft, fingerprint=rp.readiness_fingerprint(draft))


def reforged_intent(intent, **changes):
    draft = dataclasses.replace(intent, **changes)
    return dataclasses.replace(draft, fingerprint=rpa.intent_fingerprint(draft))


class IntentAssertions:
    def assertIntent(self, intent):
        self.assertIs(type(intent), rpa.PromotionIntent)
        self.assertEqual(intent.status, rpa.STATUS_PROPOSED)
        self.assertEqual(intent.schema, rpa.INTENT_SCHEMA)
        self.assertIs(intent.human_approval_required, True)
        self.assertIs(intent.authorizes_action, False)
        self.assertIs(intent.execution_allowed, False)
        self.assertRegex(intent.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(intent.fingerprint, rpa.intent_fingerprint(intent))
        for code in (rpa.INTENT_PROPOSAL_ONLY, rpa.INTENT_HUMAN_APPROVAL_REQUIRED, rpa.INTENT_NOT_AUTHORIZATION,
                     rpa.INTENT_FRESH_REVALIDATION_REQUIRED, rpa.INTENT_EXECUTION_CONTRACT_REQUIRED):
            self.assertIn(code, intent.reason_codes)
        json.dumps(dataclasses.asdict(intent))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            intent.authorizes_action = True  # type: ignore[misc]

    def assertValidation(self, v, valid, *reasons, mode=None):
        self.assertIs(type(v), rpa.PromotionIntentValidation)
        self.assertIs(v.valid, valid, v.reason_codes)
        self.assertEqual(v.outcome, rpa.MATCHES_PROPOSAL if valid else rpa.REJECTED)
        self.assertIs(v.human_approval_required, True)
        self.assertIs(v.authorizes_action, False)
        self.assertIs(v.execution_allowed, False)
        self.assertEqual(v.schema, rpa.VALIDATION_SCHEMA)
        self.assertRegex(v.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(v.fingerprint, rpa.validation_fingerprint(v))
        for code in (rpa.INTENT_VALIDATION_NOT_APPROVAL, rpa.INTENT_HUMAN_APPROVAL_REQUIRED,
                     rpa.INTENT_NOT_AUTHORIZATION, *reasons):
            self.assertIn(code, v.reason_codes)
        if valid:
            self.assertIn(rpa.INTENT_MATCHES_FRESH_READINESS, v.reason_codes)
            self.assertEqual(v.mismatched_fields, ())
        else:
            self.assertNotIn(rpa.INTENT_MATCHES_FRESH_READINESS, v.reason_codes)
        if mode is not None:
            self.assertEqual(v.mode, mode)
        self.assertEqual(len(v.reason_codes), len(set(v.reason_codes)))
        json.dumps(dataclasses.asdict(v))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            v.valid = True  # type: ignore[misc]

    def assertRefused(self, *codes, readiness=_DEFAULT, action=FF, scopes=SCOPES):
        readiness = self.readiness if readiness is _DEFAULT else readiness
        with self.assertRaises(rpa.PromotionIntentRefused) as ctx:
            rpa.prepare_promotion_intent(readiness, proposed_action=action, authorized_scopes=scopes)
        for code in codes:
            self.assertIn(code, ctx.exception.reason_codes)
        self.assertTrue(all(c.startswith("INTENT_") for c in ctx.exception.reason_codes))
        self.assertEqual(str(ctx.exception), ", ".join(ctx.exception.reason_codes))
        return ctx.exception


class SharedEligibleFixture(IntentAssertions, unittest.TestCase):
    """One real eligible fixture per class, for the pure (read-free) tests."""

    @classmethod
    def setUpClass(cls):
        env = mock.patch.dict(os.environ, _ISOLATED_ENV)
        env.start()
        cls.addClassCleanup(env.stop)
        cls.root = Path(tempfile.mkdtemp(prefix="fcp3b1-")).resolve()
        cls.addClassCleanup(_rmtree, cls.root)
        cls.fx = Fixture(cls.root)
        cls.fx.head_commit({"src/a.py": text({2: "head\n"})})
        cls.ledger = cls.root / "factory"
        cls.ledger.mkdir()
        cls.readiness = cls.assess()
        cls.intent = rpa.prepare_promotion_intent(cls.readiness, proposed_action=FF, authorized_scopes=SCOPES)
        cls.blocked = cls.assess(ledger_root=None)
        cls.fx.base_commit({"docs/readme.md": "v2\n"})
        cls.review = cls.assess()

    @classmethod
    def assess(cls, **overrides):
        kw = dict(attested_sha=cls.fx.base, authorized_scopes=SCOPES, ledger_root=cls.ledger,
                  evidence=good_evidence(cls.fx.wt))
        kw.update(overrides)
        return rp.assess_promotion_readiness(cls.fx.wt, **kw)

    def setUp(self):
        self.assertEqual(self.readiness.classification, rp.AWAITING_HUMAN_APPROVAL, self.readiness.reason_codes)
        self.assertEqual(self.blocked.classification, rp.BLOCKED)
        self.assertEqual(self.review.classification, rp.RECONCILIATION_REVIEW_REQUIRED)


# ---------------------------------------------------------------------------
# prepare_promotion_intent (pure)
# ---------------------------------------------------------------------------

class PrepareTests(SharedEligibleFixture):
    def test_proposal_only_bound_to_real_readiness(self):
        intent, r = self.intent, self.readiness
        self.assertIntent(intent)
        self.assertEqual(intent.proposed_action, FF)
        self.assertEqual(intent.reason_codes, (
            rpa.INTENT_PROPOSAL_ONLY, rpa.INTENT_HUMAN_APPROVAL_REQUIRED, rpa.INTENT_NOT_AUTHORIZATION,
            rpa.INTENT_FRESH_REVALIDATION_REQUIRED, rpa.INTENT_EXECUTION_CONTRACT_REQUIRED))
        self.assertEqual((intent.readiness_fingerprint, intent.readiness_classification),
                         (r.fingerprint, rp.AWAITING_HUMAN_APPROVAL))
        self.assertEqual((intent.reconciliation_fingerprint, intent.reconciliation_classification),
                         (r.reconciliation_fingerprint, rr.NOT_APPLICABLE))
        self.assertEqual((intent.assessment_fingerprint, intent.assessment_classification),
                         (r.assessment_fingerprint, ri.ELIGIBLE_PENDING_APPROVAL))
        self.assertEqual((intent.worktree_key, intent.head_ref), (r.worktree_key, "refs/heads/feature/fcp2b"))
        self.assertEqual(intent.head_sha, head(self.fx.wt))
        self.assertEqual((intent.base_sha, intent.attested_sha, intent.merge_bases),
                         (self.fx.c0, self.fx.c0, (self.fx.c0,)))
        self.assertNotEqual(intent.head_sha, intent.base_sha)
        self.assertEqual(intent.canonical_base_ref, ri.TRACKING_REF)
        self.assertEqual(intent.authorized_scopes, SCOPES)

    def test_deterministic_repeat_and_serialization(self):
        again = rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=["src"])
        self.assertEqual(again, self.intent)
        self.assertEqual(json.dumps(dataclasses.asdict(again), sort_keys=True),
                         json.dumps(dataclasses.asdict(self.intent), sort_keys=True))
        # Scope order does not change identity; they are stored sorted.
        a = rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=("src", "docs"))
        b = rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=["docs", "src"])
        self.assertEqual(a, b)
        self.assertEqual(a.authorized_scopes, ("docs", "src"))
        self.assertNotEqual(a.fingerprint, self.intent.fingerprint)

    def test_fingerprint_covers_every_field(self):
        for f in dataclasses.fields(rpa.PromotionIntent):
            if f.name == "fingerprint":
                continue
            value = getattr(self.intent, f.name)
            changed = (not value) if isinstance(value, bool) else (value + ("x",) if isinstance(value, tuple)
                                                                      else value + "x")
            forged = dataclasses.replace(self.intent, **{f.name: changed})
            self.assertNotEqual(rpa.intent_fingerprint(forged), self.intent.fingerprint, f.name)

    def test_schema_and_no_approval_surface(self):
        self.assertEqual(tuple(f.name for f in dataclasses.fields(rpa.PromotionIntent)), INTENT_FIELDS)
        self.assertEqual(tuple(f.name for f in dataclasses.fields(rpa.PromotionIntentValidation)), VALIDATION_FIELDS)
        for name in INTENT_FIELDS + VALIDATION_FIELDS:
            for word in ("token", "approved", "approval_id", "callback", "signature", "credential", "receipt",
                         "command", "fresh_flag"):
                self.assertNotIn(word, name)
        self.assertTrue(rpa.PromotionIntent.__dataclass_params__.frozen)
        self.assertTrue(rpa.PromotionIntentValidation.__dataclass_params__.frozen)

    def test_caller_cannot_assert_approval_or_freshness(self):
        for extra in (dict(approved=True), dict(authorizes_action=True), dict(execution_allowed=True),
                      dict(human_approval_required=False), dict(status="APPROVED")):
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=SCOPES, **extra)
        for extra in (dict(fresh=True), dict(approved=True)):
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                rpa.validate_promotion_intent(self.intent, self.readiness, **extra)
        with self.assertRaises(TypeError):  # keyword-only: no positional action/scope smuggling
            rpa.prepare_promotion_intent(self.readiness, FF, SCOPES)

    def test_refuses_blocked_and_review_required(self):
        self.assertRefused(rpa.INTENT_READINESS_BLOCKED, rpa.INTENT_LEDGER_NOT_CHECKED, readiness=self.blocked)
        exc = self.assertRefused(rpa.INTENT_READINESS_REVIEW_REQUIRED, readiness=self.review)
        self.assertNotIn(rpa.INTENT_READINESS_BLOCKED, exc.reason_codes)

    def test_refuses_tampered_readiness(self):
        cases = (
            dataclasses.replace(self.readiness, fingerprint="0" * 64),
            dataclasses.replace(self.readiness, head_sha=SHA_A),  # digest no longer matches
            reforged_readiness(self.readiness, authorizes_action=True),
            reforged_readiness(self.readiness, execution_allowed=True),
            reforged_readiness(self.readiness, human_approval_required=False),
            reforged_readiness(self.readiness, schema="fcp3a-promotion-readiness-v2"),
        )
        for forged in cases:
            with self.subTest(forged=forged):
                exc = self.assertRefused(rpa.INTENT_READINESS_TAMPERED, readiness=forged)
                self.assertEqual(exc.reason_codes, (rpa.INTENT_READINESS_TAMPERED,))

    def test_refuses_self_consistent_but_ineligible_readiness(self):
        cases = (
            dict(classification="APPROVED"), dict(reason_codes=self.readiness.reason_codes[1:]),
            dict(assessment_classification=ri.STALE_BASE), dict(assessment_reason_codes=("X",)),
            dict(reconciliation_classification=rr.NO_TEXTUAL_CONFLICT), dict(reconciliation_reason_codes=()),
            dict(base_status=ri.BASE_STALE), dict(evidence_status=ri.EVIDENCE_STALE),
            dict(semantic_validation_required=True),
        )
        for change in cases:
            with self.subTest(change=change):
                self.assertRefused(rpa.INTENT_READINESS_NOT_ELIGIBLE, readiness=reforged_readiness(
                    self.readiness, **change))
        self.assertRefused(rpa.INTENT_LEDGER_NOT_CHECKED,
                           readiness=reforged_readiness(self.readiness, ledger_checked=False))
        self.assertRefused(rpa.INTENT_READINESS_BLOCKED, rpa.INTENT_LEDGER_NOT_CHECKED,
                           readiness=reforged_readiness(self.readiness, classification=rp.BLOCKED,
                                                        reason_codes=(rp.PROMO_LEDGER_NOT_CHECKED,)))

    def test_refuses_missing_or_malformed_sha(self):
        r = self.readiness
        cases = (
            dict(head_sha=None), dict(head_sha=""), dict(head_sha="abc123"), dict(head_sha=r.head_sha.upper()),
            dict(head_sha=r.head_sha[:-1]), dict(head_sha=r.head_sha + "0"), dict(head_sha="g" * 40),
            dict(head_sha="c" * 64),  # sha256-shaped HEAD with a sha1 base: inconsistent format
            dict(base_sha=None), dict(base_sha="1234"), dict(attested_sha=None), dict(attested_sha=""),
            dict(merge_bases=("x",)), dict(merge_bases=(None,)),
        )
        for change in cases:
            with self.subTest(change=change):
                self.assertRefused(rpa.INTENT_SHA_INVALID, readiness=reforged_readiness(r, **change))

    def test_refuses_head_equal_to_base_attestation_mismatch_and_non_fast_forward(self):
        r = self.readiness
        self.assertRefused(rpa.INTENT_HEAD_EQUALS_BASE, readiness=reforged_readiness(r, head_sha=r.base_sha))
        self.assertRefused(rpa.INTENT_ATTESTATION_MISMATCH, readiness=reforged_readiness(r, attested_sha=SHA_A))
        for merge_bases in ((), (SHA_A,), (r.base_sha, SHA_A), (r.head_sha,)):
            with self.subTest(merge_bases=merge_bases):
                self.assertRefused(rpa.INTENT_NOT_FAST_FORWARD,
                                   readiness=reforged_readiness(r, merge_bases=merge_bases))

    def test_refuses_invalid_identity(self):
        cases = (
            dict(worktree_key=None), dict(worktree_key=""), dict(worktree_key=" x"), dict(worktree_key="a\nb"),
            dict(head_ref=None), dict(head_ref="feature/x"), dict(head_ref="refs/heads/"),
            dict(head_ref=ri.LOCAL_BRANCH_REF), dict(head_ref="refs/heads/a b"), dict(head_ref="refs/tags/v1"),
            dict(reconciliation_fingerprint=None), dict(reconciliation_fingerprint="F" * 64),
            dict(assessment_fingerprint="0" * 63),
        )
        for change in cases:
            with self.subTest(change=change):
                self.assertRefused(rpa.INTENT_IDENTITY_INVALID, readiness=reforged_readiness(self.readiness, **change))

    def test_refuses_non_readiness_and_lying_values(self):
        analysis = self.fx.analyze(ledger_root=self.ledger)
        for value in (None, {}, "AWAITING_HUMAN_APPROVAL", dataclasses.asdict(self.readiness), analysis,
                      self.intent, object()):
            with self.subTest(value=type(value)):
                self.assertRefused(rpa.INTENT_READINESS_MALFORMED, readiness=value)
        lying = reforged_readiness(self.readiness, classification=_Str("BLOCKED"))
        self.assertRefused(rpa.INTENT_READINESS_MALFORMED, readiness=lying)

    def test_refuses_unexpected_or_unsafe_action(self):
        for action in (None, "", "fast_forward_candidate_to_develop", " " + FF, "MERGE_TO_DEVELOP",
                       "git merge --ff-only feature", "git push origin HEAD:develop", (FF,), [FF], _Str(FF),
                       FF.encode(), 1, True):
            with self.subTest(action=action):
                exc = self.assertRefused(rpa.INTENT_ACTION_INVALID, action=action)
                self.assertEqual(exc.reason_codes, (rpa.INTENT_ACTION_INVALID,))

    def test_refuses_invalid_or_empty_scope(self):
        for scopes in ((), []):
            with self.subTest(scopes=scopes):
                self.assertRefused(rpa.INTENT_SCOPE_MISSING, scopes=scopes)
        for scopes in (None, "src", {"src"}, ("src", 1), ("",), (" ",), (" src",), ("src ",), ("src/",),
                       ("./src",), ("src//a",), ("src\\a",), ("/abs",), ("C:/x",), ("../out",), ("src/../x",),
                       ("src/*.py",), ("*",), ("src?",), ("[s]rc",), (".",), ("src", "src"), ("src\0",),
                       ("src\n",), (_Str("src"),), (b"src",)):
            with self.subTest(scopes=scopes):
                self.assertRefused(rpa.INTENT_SCOPE_INVALID, scopes=scopes)

    def test_refusal_is_deterministic_combined_and_leaks_no_value(self):
        r = reforged_readiness(self.readiness, ledger_checked=False, attested_sha=SHA_A)
        first = self.assertRefused(readiness=r, action="git push", scopes=())
        second = self.assertRefused(readiness=r, action="git push", scopes=())
        self.assertEqual(first.reason_codes, second.reason_codes)
        self.assertEqual(first.reason_codes, (
            rpa.INTENT_LEDGER_NOT_CHECKED, rpa.INTENT_ATTESTATION_MISMATCH, rpa.INTENT_ACTION_INVALID,
            rpa.INTENT_SCOPE_MISSING))
        self.assertNotIn(SHA_A, str(first))
        self.assertNotIn("git push", str(first))
        self.assertIsInstance(first, ValueError)

    def test_prepare_never_escapes_unexpected_errors(self):
        with mock.patch.object(rp, "readiness_fingerprint", side_effect=RuntimeError("secret")):
            exc = self.assertRefused(rpa.INTENT_READINESS_TAMPERED)
        self.assertNotIn("secret", str(exc))
        with mock.patch.object(rpa, "_binding_errors", side_effect=RuntimeError("secret")):
            exc = self.assertRefused(rpa.INTENT_READINESS_MALFORMED)
        self.assertNotIn("secret", str(exc))


# ---------------------------------------------------------------------------
# validate_promotion_intent (pure)
# ---------------------------------------------------------------------------

class ValidateTests(SharedEligibleFixture):
    def validate(self, intent=_DEFAULT, fresh=_DEFAULT):
        return rpa.validate_promotion_intent(self.intent if intent is _DEFAULT else intent,
                                             self.readiness if fresh is _DEFAULT else fresh)

    def test_match_is_non_authorizing_and_freshness_unproven(self):
        v = self.validate()
        self.assertValidation(v, True, rpa.INTENT_FRESHNESS_NOT_PROVEN, mode=rpa.MODE_SUPPLIED_READINESS)
        self.assertNotIn(rpa.INTENT_FRESH_FCP3A_READ, v.reason_codes)
        self.assertEqual((v.intent_fingerprint, v.fresh_readiness_fingerprint, v.fresh_readiness_classification),
                         (self.intent.fingerprint, self.readiness.fingerprint, rp.AWAITING_HUMAN_APPROVAL))
        self.assertEqual(v, self.validate())  # deterministic
        self.assertEqual(v.reason_codes, (
            rpa.INTENT_MATCHES_FRESH_READINESS, rpa.INTENT_FRESHNESS_NOT_PROVEN, rpa.INTENT_VALIDATION_NOT_APPROVAL,
            rpa.INTENT_HUMAN_APPROVAL_REQUIRED, rpa.INTENT_NOT_AUTHORIZATION))

    def test_malformed_intent(self):
        for value in (None, {}, dataclasses.asdict(self.intent), self.readiness, "PROPOSED", object()):
            with self.subTest(value=type(value)):
                v = self.validate(intent=value)
                self.assertValidation(v, False, rpa.INTENT_MALFORMED)
                self.assertIsNone(v.intent_fingerprint)
        lying = reforged_intent(self.intent, head_sha=_Str(self.intent.head_sha))
        self.assertValidation(self.validate(intent=lying), False, rpa.INTENT_MALFORMED)

    def test_tampered_intent_digest_or_invariant(self):
        i = self.intent
        cases = (
            dataclasses.replace(i, fingerprint="0" * 64), dataclasses.replace(i, head_sha=SHA_A),
            dataclasses.replace(i, authorized_scopes=("docs", "src")),
            reforged_intent(i, authorizes_action=True), reforged_intent(i, execution_allowed=True),
            reforged_intent(i, human_approval_required=False), reforged_intent(i, status="APPROVED"),
            reforged_intent(i, schema="fcp3b1-promotion-intent-v2"), reforged_intent(i, proposed_action="MERGE"),
            reforged_intent(i, reason_codes=()), reforged_intent(i, readiness_classification=rp.BLOCKED),
            reforged_intent(i, assessment_classification=ri.STALE_BASE),
            reforged_intent(i, reconciliation_classification=rr.FAIL_CLOSED),
            reforged_intent(i, canonical_base_ref=ri.LOCAL_BRANCH_REF),
            reforged_intent(i, authorized_scopes=()), reforged_intent(i, authorized_scopes=("src", "docs")),
            reforged_intent(i, authorized_scopes=("src/*",)), reforged_intent(i, head_sha="nothex"),
            reforged_intent(i, attested_sha=SHA_A), reforged_intent(i, merge_bases=()),
            reforged_intent(i, head_sha=i.base_sha), reforged_intent(i, head_ref=ri.LOCAL_BRANCH_REF),
        )
        for forged in cases:
            with self.subTest(forged=forged):
                v = self.validate(intent=forged)
                self.assertValidation(v, False, rpa.INTENT_TAMPERED)
                self.assertEqual(v.mismatched_fields, ())

    def assertStale(self, v, fields, *codes):
        self.assertValidation(v, False, *codes)
        self.assertEqual(set(v.mismatched_fields), set(fields))

    def test_self_consistent_forged_intent_does_not_match(self):
        i = self.intent
        cases = (
            (dict(readiness_fingerprint="a" * 64), rpa.INTENT_STALE_READINESS),
            (dict(reconciliation_fingerprint="a" * 64), rpa.INTENT_STALE_RECONCILIATION),
            (dict(assessment_fingerprint="a" * 64), rpa.INTENT_STALE_ASSESSMENT),
            (dict(worktree_key="elsewhere"), rpa.INTENT_STALE_WORKTREE),
            (dict(head_ref="refs/heads/other"), rpa.INTENT_STALE_BRANCH),
            (dict(head_sha=SHA_A), rpa.INTENT_STALE_HEAD),
        )
        for change, code in cases:
            with self.subTest(change=change):
                self.assertStale(self.validate(intent=reforged_intent(i, **change)), change, code)
        moved = dict(base_sha=SHA_B, attested_sha=SHA_B, merge_bases=(SHA_B,))
        self.assertStale(self.validate(intent=reforged_intent(i, **moved)), moved, rpa.INTENT_STALE_BASE,
                         rpa.INTENT_STALE_ATTESTATION, rpa.INTENT_STALE_MERGE_BASE)

    def test_fresh_readiness_drift(self):
        r = self.readiness
        cases = (
            (dict(head_sha=SHA_A), rpa.INTENT_STALE_HEAD),
            (dict(head_ref="refs/heads/other"), rpa.INTENT_STALE_BRANCH),
            (dict(worktree_key="elsewhere"), rpa.INTENT_STALE_WORKTREE),
            (dict(assessment_fingerprint="c" * 64), rpa.INTENT_STALE_ASSESSMENT),  # FCP-1 / evidence change
            (dict(reconciliation_fingerprint="d" * 64), rpa.INTENT_STALE_RECONCILIATION),
        )
        for change, code in cases:
            with self.subTest(change=change):
                v = self.validate(fresh=reforged_readiness(r, **change))
                self.assertStale(v, ("readiness_fingerprint", *change), code, rpa.INTENT_STALE_READINESS)
        moved = dict(base_sha=SHA_B, attested_sha=SHA_B, merge_bases=(SHA_B,))
        self.assertStale(self.validate(fresh=reforged_readiness(r, **moved)), ("readiness_fingerprint", *moved),
                         rpa.INTENT_STALE_BASE, rpa.INTENT_STALE_ATTESTATION, rpa.INTENT_STALE_MERGE_BASE)

    def test_fresh_readiness_missing_ineligible_or_tampered(self):
        self.assertValidation(rpa.validate_promotion_intent(self.intent, None), False,
                              rpa.INTENT_FRESH_READINESS_MISSING)
        v = self.validate(fresh=self.blocked)
        self.assertValidation(v, False, rpa.INTENT_FRESH_READINESS_INELIGIBLE, rpa.INTENT_READINESS_BLOCKED,
                              rpa.INTENT_LEDGER_NOT_CHECKED)
        self.assertEqual(v.fresh_readiness_classification, rp.BLOCKED)
        self.assertValidation(self.validate(fresh=self.review), False, rpa.INTENT_FRESH_READINESS_INELIGIBLE,
                              rpa.INTENT_READINESS_REVIEW_REQUIRED)
        tampered = dataclasses.replace(self.readiness, head_sha=SHA_A)
        self.assertValidation(self.validate(fresh=tampered), False, rpa.INTENT_FRESH_READINESS_INELIGIBLE,
                              rpa.INTENT_READINESS_TAMPERED)
        for change in (dict(classification=rp.BLOCKED), dict(ledger_checked=False), dict(authorizes_action=True)):
            with self.subTest(change=change):
                self.assertValidation(self.validate(fresh=reforged_readiness(self.readiness, **change)), False,
                                      rpa.INTENT_FRESH_READINESS_INELIGIBLE)
        for garbage in ({}, "AWAITING_HUMAN_APPROVAL", self.intent, dataclasses.asdict(self.readiness)):
            with self.subTest(garbage=type(garbage)):
                v = self.validate(fresh=garbage)
                self.assertValidation(v, False, rpa.INTENT_FRESH_READINESS_INELIGIBLE, rpa.INTENT_READINESS_MALFORMED)
                self.assertIsNone(v.fresh_readiness_fingerprint)

    def test_scope_binding_is_not_provable_from_a_supplied_readiness(self):
        # The readiness does not record its scopes: a pure comparison cannot
        # tell, and says so. Only a fresh read with these scopes proves them
        # (see RevalidateTests.test_scope_binding_proven_only_by_fresh_read).
        wider = rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=("docs", "src"))
        v = self.validate(intent=wider)
        self.assertValidation(v, True, rpa.INTENT_FRESHNESS_NOT_PROVEN)
        self.assertIs(v.authorizes_action, False)

    def test_validation_never_raises(self):
        with mock.patch.object(rpa, "_intent_errors", side_effect=RuntimeError("secret")):
            v = self.validate()
        self.assertValidation(v, False, rpa.INTENT_MALFORMED)
        self.assertNotIn("secret", json.dumps(dataclasses.asdict(v)))

    def test_forged_validation_or_intent_grants_nothing(self):
        # Nothing in the module consumes a validation or an intent as permission:
        # a forged "approved" validation is just data, and a forged intent
        # claiming authority is rejected.
        forged = rpa.PromotionIntentValidation(valid=True, outcome=rpa.MATCHES_PROPOSAL, reason_codes=(),
                                               fingerprint="0" * 64, mode=rpa.MODE_FRESH_FCP3A_READ,
                                               authorizes_action=True, execution_allowed=True)
        self.assertNotEqual(forged.fingerprint, rpa.validation_fingerprint(forged))
        self.assertValidation(self.validate(intent=forged), False, rpa.INTENT_MALFORMED)
        self.assertValidation(self.validate(intent=reforged_intent(self.intent, authorizes_action=True,
                                                                   execution_allowed=True)),
                              False, rpa.INTENT_TAMPERED)


# ---------------------------------------------------------------------------
# revalidate_promotion_intent (one real FCP-3A read)
# ---------------------------------------------------------------------------

class RevalidateTests(IntentAssertions, PromotionTestCase):
    def setUp(self):
        super().setUp()
        self.h1 = self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.readiness = self.assess()
        self.assertReadiness(self.readiness, rp.AWAITING_HUMAN_APPROVAL)
        self.intent = rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=SCOPES)

    def revalidate(self, intent=_DEFAULT, worktree=None, **overrides):
        worktree, kw = self.kwargs(worktree, **overrides)
        return rpa.revalidate_promotion_intent(self.intent if intent is _DEFAULT else intent, worktree, **kw)

    def assertRejected(self, v, *codes):
        self.assertValidation(v, False, rpa.INTENT_FRESH_FCP3A_READ, *codes, mode=rpa.MODE_FRESH_FCP3A_READ)

    def test_fresh_read_match_is_still_non_authorizing(self):
        v = self.revalidate()
        self.assertValidation(v, True, rpa.INTENT_FRESH_FCP3A_READ, mode=rpa.MODE_FRESH_FCP3A_READ)
        self.assertNotIn(rpa.INTENT_FRESHNESS_NOT_PROVEN, v.reason_codes)
        self.assertEqual(v.fresh_readiness_fingerprint, self.intent.readiness_fingerprint)
        self.assertEqual(v, self.revalidate())  # deterministic
        self.assertValidation(self.revalidate(authorized_scopes=["src"]), True)  # same canonical scopes

    def test_exactly_one_delegation_with_forwarded_inputs(self):
        worktree, kw = self.kwargs(expected_remote_url=REMOTE_URL, lease_root=self.root / "leases", max_paths=17)
        with mock.patch.object(rp, "assess_promotion_readiness", wraps=rp.assess_promotion_readiness) as fcp3a, \
                mock.patch.object(rr, "analyze_reconciliation", wraps=rr.analyze_reconciliation) as fcp2b, \
                mock.patch.object(ri, "assess_integration", wraps=ri.assess_integration) as fcp1, \
                mock.patch.object(ri, "_git", wraps=ri._git) as git:
            v = rpa.revalidate_promotion_intent(self.intent, worktree, **kw)
        fcp3a.assert_called_once_with(worktree, **kw)
        for name in ("evidence", "authorized_scopes", "ledger_root", "lease_root"):
            self.assertIs(fcp3a.call_args.kwargs[name], kw[name])
        self.assertEqual((fcp2b.call_count, fcp1.call_count), (1, 1))  # only FCP-3A's own reads
        # Every git read belongs to that single FCP-1 pass; none is repeated after it.
        with mock.patch.object(ri, "_git", wraps=ri._git) as solo_git:
            rp.assess_promotion_readiness(worktree, **kw)
        self.assertEqual(git.call_count, solo_git.call_count)
        self.assertValidation(v, False, rpa.INTENT_STALE_ASSESSMENT)  # remote URL is fingerprinted by FCP-1

    def test_matches_with_forwarded_remote_and_lease_root_when_prepared_alike(self):
        kw = dict(expected_remote_url=REMOTE_URL, lease_root=self.root / "leases")
        intent = rpa.prepare_promotion_intent(self.assess(**kw), proposed_action=FF, authorized_scopes=SCOPES)
        self.assertValidation(self.revalidate(intent, **kw), True, rpa.INTENT_FRESH_FCP3A_READ)

    def test_malformed_intent_still_reads_exactly_once(self):
        with mock.patch.object(rp, "assess_promotion_readiness", wraps=rp.assess_promotion_readiness) as fcp3a:
            v = self.revalidate(intent=None)
        fcp3a.assert_called_once()
        self.assertRejected(v, rpa.INTENT_MALFORMED)

    def test_head_changed(self):
        self.fx.head_commit({"src/a.py": text({3: "more\n"})})
        v = self.revalidate()
        self.assertRejected(v, rpa.INTENT_STALE_HEAD, rpa.INTENT_STALE_READINESS, rpa.INTENT_STALE_ASSESSMENT,
                            rpa.INTENT_STALE_RECONCILIATION)
        self.assertEqual(v.fresh_readiness_classification, rp.AWAITING_HUMAN_APPROVAL)
        self.assertNotIn(rpa.INTENT_STALE_BASE, v.reason_codes)

    def test_base_advanced_but_still_fast_forward(self):
        self.fx.head_commit({"src/a.py": text({3: "more\n"})})
        intent = rpa.prepare_promotion_intent(self.assess(), proposed_action=FF, authorized_scopes=SCOPES)
        self.fx.set_base(self.h1)  # the canonical base moves onto the candidate's first commit
        v = self.revalidate(intent)
        self.assertRejected(v, rpa.INTENT_STALE_BASE, rpa.INTENT_STALE_ATTESTATION, rpa.INTENT_STALE_MERGE_BASE,
                            rpa.INTENT_STALE_READINESS, rpa.INTENT_STALE_ASSESSMENT)
        self.assertEqual(v.fresh_readiness_classification, rp.AWAITING_HUMAN_APPROVAL)
        self.assertNotIn(rpa.INTENT_STALE_HEAD, v.reason_codes)

    def test_base_advanced_needs_review(self):
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        v = self.revalidate()
        self.assertRejected(v, rpa.INTENT_FRESH_READINESS_INELIGIBLE, rpa.INTENT_READINESS_REVIEW_REQUIRED)
        self.assertEqual(v.fresh_readiness_classification, rp.RECONCILIATION_REVIEW_REQUIRED)

    def test_evidence_changed_or_missing(self):
        v = self.revalidate(evidence=good_evidence(self.fx.wt, run_id="run-SECRET-2"))
        self.assertRejected(v, rpa.INTENT_STALE_ASSESSMENT, rpa.INTENT_STALE_READINESS)
        self.assertNotIn("SECRET", json.dumps(dataclasses.asdict(v)))
        for evidence in (None, good_evidence(self.fx.wt, safety_verdict="UNSAFE")):
            with self.subTest(evidence=evidence):
                self.assertRejected(self.revalidate(evidence=evidence), rpa.INTENT_FRESH_READINESS_INELIGIBLE,
                                    rpa.INTENT_READINESS_BLOCKED)

    def test_attestation_changed(self):
        for attested in (None, self.h1, "0" * 40):
            with self.subTest(attested=attested):
                self.assertRejected(self.revalidate(attested_sha=attested), rpa.INTENT_FRESH_READINESS_INELIGIBLE,
                                    rpa.INTENT_READINESS_BLOCKED)

    def test_scope_drift(self):
        v = self.revalidate(authorized_scopes=("src", "docs"))
        self.assertRejected(v, rpa.INTENT_SCOPE_DRIFT, rpa.INTENT_STALE_ASSESSMENT)
        # FCP-1 normalizes "src/" to "src" (same fingerprint); the intent still refuses the drift.
        v = self.revalidate(authorized_scopes=("src/",))
        self.assertRejected(v, rpa.INTENT_SCOPE_DRIFT)
        self.assertEqual(v.mismatched_fields, ())
        self.assertRejected(self.revalidate(authorized_scopes=()), rpa.INTENT_SCOPE_DRIFT)

    def test_scope_binding_proven_only_by_fresh_read(self):
        wider = rpa.prepare_promotion_intent(self.readiness, proposed_action=FF, authorized_scopes=("docs", "src"))
        v = self.revalidate(wider, authorized_scopes=wider.authorized_scopes)
        self.assertRejected(v, rpa.INTENT_STALE_ASSESSMENT, rpa.INTENT_STALE_READINESS)
        self.assertNotIn(rpa.INTENT_SCOPE_DRIFT, v.reason_codes)

    def test_worktree_changed(self):
        other = self.fx.add_worktree("other-wt", "feature/other", self.fx.c0)
        self.fx.head_commit({"src/a.py": text({4: "other\n"})}, worktree=other)
        v = self.revalidate(worktree=other)
        self.assertRejected(v, rpa.INTENT_STALE_WORKTREE, rpa.INTENT_STALE_BRANCH, rpa.INTENT_STALE_HEAD)
        self.assertEqual(v.fresh_readiness_classification, rp.AWAITING_HUMAN_APPROVAL)

    def test_missing_ledger_is_never_bypassed(self):
        for ledger_root in (None, self.root / "absent"):
            with self.subTest(ledger_root=ledger_root):
                v = self.revalidate(ledger_root=ledger_root)
                self.assertRejected(v, rpa.INTENT_FRESH_READINESS_INELIGIBLE, rpa.INTENT_READINESS_BLOCKED)
        self.assertIn(rpa.INTENT_LEDGER_NOT_CHECKED, self.revalidate(ledger_root=None).reason_codes)

    def test_active_worker_held_lease_and_dirty_tree(self):
        ledger = flog.FactoryLedger(self.ledger)
        ledger.append(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", worktree=str(self.fx.wt))
        self.assertRejected(self.revalidate(), rpa.INTENT_READINESS_BLOCKED)
        clean_ledger = self.root / "factory-clean"
        clean_ledger.mkdir()
        self.assertValidation(self.revalidate(ledger_root=clean_ledger), True)  # the root is not fingerprinted
        competitor = pipeline.DirLease(pipeline.worktree_lease_dir(self.fx.wt.resolve(), None))
        self.assertTrue(competitor.try_acquire({"pipeline_id": "other", "worker_id": "w", "pid": 1}))
        try:
            self.assertRejected(self.revalidate(ledger_root=clean_ledger), rpa.INTENT_READINESS_BLOCKED)
        finally:
            competitor.release()
        write(self.fx.wt / "src" / "untracked.py", "x\n")
        self.assertRejected(self.revalidate(ledger_root=clean_ledger), rpa.INTENT_READINESS_BLOCKED)

    def test_input_refusals_propagate_before_any_read(self):
        for overrides, error in ((dict(max_paths=True), rr.ReconciliationInputError),
                                 (dict(authorized_scopes="src"), rp.PromotionInputError),
                                 (dict(ledger_root=""), rp.PromotionInputError),
                                 (dict(attested_sha=1), rp.PromotionInputError)):
            with self.subTest(overrides=overrides), \
                    mock.patch.object(rr, "analyze_reconciliation") as fcp2b, mock.patch.object(ri, "_git") as git:
                with self.assertRaises(error):
                    self.revalidate(**overrides)
                fcp2b.assert_not_called()
                git.assert_not_called()
        with self.assertRaises(rp.PromotionInputError):
            rpa.revalidate_promotion_intent(self.intent, None, attested_sha=self.fx.base, authorized_scopes=SCOPES)

    def test_delegate_failure_or_garbage_fails_closed(self):
        with mock.patch.object(rp, "assess_promotion_readiness", side_effect=RuntimeError("secret detail")) as fcp3a:
            v = self.revalidate()
        fcp3a.assert_called_once()
        self.assertRejected(v, rpa.INTENT_FRESH_READ_FAILED)
        self.assertNotIn("secret", json.dumps(dataclasses.asdict(v)))
        with mock.patch.object(rp, "assess_promotion_readiness", return_value=None):
            self.assertRejected(self.revalidate(), rpa.INTENT_FRESH_READINESS_MISSING)
        for garbage in ({}, "AWAITING_HUMAN_APPROVAL", self.intent):
            with self.subTest(garbage=type(garbage)), \
                    mock.patch.object(rp, "assess_promotion_readiness", return_value=garbage):
                self.assertRejected(self.revalidate(), rpa.INTENT_READINESS_MALFORMED)

    def test_nothing_written_lease_released_no_network(self):
        git_dir = self.fx.repo / ".git"
        before = _git_dir_state([git_dir])
        files = {p: p.read_bytes() for p in self.fx.wt.rglob("*") if p.is_file() and ".git" not in p.parts}
        refuse = mock.Mock(side_effect=AssertionError("network used"))
        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse):
            v = self.revalidate(expected_remote_url=None)
        self.assertValidation(v, True)
        refuse.assert_not_called()
        self.assertEqual(_git_dir_state([git_dir]), before)
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        self.assertEqual(sorted(self.ledger.iterdir()), [])  # no ledger event, no persisted intent
        probe = pipeline.DirLease(pipeline.worktree_lease_dir(self.fx.wt.resolve(), None))
        self.assertTrue(probe.try_acquire({"pid": 0}))
        probe.release()
        self.assertEqual(self.intent, rpa.prepare_promotion_intent(self.readiness, proposed_action=FF,
                                                                   authorized_scopes=SCOPES))


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

class StructureTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def test_no_git_process_network_or_lower_level_entry_points(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        imports = {a.name for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names} | {n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("subprocess", "socket", "os", "shutil", "runner_git", "runner_pipeline",
                       "runner_factory_ledger", "urllib", "http", "requests", "hmac", "secrets", "pickle", "sqlite3"):
            self.assertNotIn(banned, imports, banned)
        for banned in ("assess_integration", "inspect_candidate", "resolve_canonical_base", "classify_integration",
                       "_git", "_read_facts", "analyze_reconciliation", "classify_reconciliation",
                       "classify_promotion_readiness", "evaluate_write_scope", "run", "Popen", "system",
                       "write_text", "write_bytes", "mkdir", "unlink", "open", "FactoryLedger", "DirLease",
                       "try_acquire", "exec", "eval"):
            self.assertNotIn(banned, attrs | names, banned)

    def test_single_delegation_site(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "assess_promotion_readiness"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0].args), 1)
        self.assertEqual({k.arg for k in calls[0].keywords}, {
            "attested_sha", "authorized_scopes", "expected_remote_url", "evidence", "ledger_root", "lease_root",
            "max_paths"})
        for keyword in calls[0].keywords:  # forwarded unchanged, never rewritten
            self.assertIsInstance(keyword.value, ast.Name)
            self.assertEqual(keyword.value.id, keyword.arg)

    def test_public_surface_has_no_approval_or_execution_entry_point(self):
        public = {n.name for n in self.tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")}
        self.assertEqual(public, {
            "PromotionIntent", "PromotionIntentValidation", "PromotionIntentRefused", "intent_fingerprint",
            "validation_fingerprint", "prepare_promotion_intent", "validate_promotion_intent",
            "revalidate_promotion_intent"})
        for func in (rpa.prepare_promotion_intent, rpa.validate_promotion_intent, rpa.revalidate_promotion_intent):
            params = set(inspect.signature(func).parameters)
            self.assertFalse(params & {"approved", "approval", "fresh", "token", "callback", "authorizes_action",
                                       "execution_allowed", "kwargs"}, func.__name__)
        self.assertEqual(rpa.PROPOSED_ACTIONS, (FF,))

    def test_readiness_contract_used_is_the_fcp3a_one(self):
        self.assertEqual(rpa._ELIGIBLE_READINESS_REASONS[:2], ("FCP1_ELIGIBLE_PENDING_APPROVAL", "FCP2B_NOT_APPLICABLE"))
        self.assertEqual(rp.READINESS_SCHEMA, "fcp3a-promotion-readiness-v1")


if __name__ == "__main__":
    unittest.main()
