"""FCP-10A-01: Resource / Quota Manager typed contract.

The contract is pure, so every request here is synthetic: provider ids are
opaque labels, observations are hand-written structured facts and nothing
is executed, reserved, bought or sent anywhere. Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_provider_routing_policy as rt
from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_scheduler_capacity as cap
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import fabric_scheduler_window as sw
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_provider_availability as availability

MODULE_PATH = Path(qc.__file__)
TEST_PATH = Path(__file__).resolve()
AS_OF = "2026-10-31T12:00:00Z"
OBSERVED = "2026-10-31T11:59:00Z"
FINGERPRINT = "0" * 64
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "reservation_held",
             "quota_authority", "purchase_allowed", "remote_api_allowed")
QUOTA = availability.ProviderCondition.QUOTA_EXHAUSTED.value
AUTH = availability.ProviderCondition.AUTH_BLOCKED.value
TRANSIENT = availability.ProviderCondition.TRANSIENT_ERROR.value


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def window(kind=qc.WINDOW_ROLLING, seconds=3600, anchor=None):
    return qc.QuotaWindow(kind=kind, duration_seconds=seconds, anchor_utc=anchor)


def limit(limit_id="lim-global", scope=qc.SCOPE_GLOBAL, unit=qc.UNIT_CONCURRENT_EXECUTIONS, maximum=2, **kw):
    return qc.QuotaLimit(limit_id=limit_id, scope=scope, unit=unit, maximum=maximum, **kw)


def policy(limits=None, **kw):
    return qc.QuotaPolicy(policy_id="pol-1", limits=(limit(),) if limits is None else limits, **kw)


def observation(evidence_id="ev-1", provider="alpha", **kw):
    fields = dict(source=qc.SOURCE_RUNNER_PROVIDER_CONDITION, reliability=qc.RELIABILITY_RUNNER_CLASSIFIED,
                  observed_at_utc=OBSERVED, availability="NONE")
    fields.update(kw)
    return qc.QuotaObservation(evidence_id=evidence_id, provider_id=provider, **fields)


def reservation(amounts=((qc.UNIT_CONCURRENT_EXECUTIONS, 1),), **kw):
    fields = dict(reservation_id="res-1", provider_id="alpha", amounts=amounts)
    fields.update(kw)
    return qc.AdvisoryReservation(**fields)


def request(**kw):
    fields = dict(request_id="req-1", as_of_utc=AS_OF, policy=policy(), reservation=reservation(),
                  observations=(observation(),))
    fields.update(kw)
    return qc.QuotaRequest(**fields)


def result(verdict=qc.READY, reasons=(), evidence_ids=("ev-1",), **kw):
    return qc.QuotaResult(verdict=verdict, request_id="req-1", request_fingerprint=FINGERPRINT, request_reasons=(),
                          reasons=reasons, evidence_ids=evidence_ids, **kw)


class QuotaTestBase(unittest.TestCase):
    def assertValid(self, req):
        self.assertEqual(qc.validate_request(req), ())

    def assertRefused(self, req, *codes):
        reasons = qc.validate_request(req)
        self.assertTrue(reasons)
        for code in codes:
            self.assertIn(code, reasons)
        self.assertEqual(reasons, sc._ordered(reasons, qc.REQUEST_REASONS))
        refused = qc.refused_result(reasons)
        self.assertEqual((refused.verdict, refused.request_id, refused.request_fingerprint, refused.reasons,
                          refused.evidence_ids, refused.wait_until_utc), (qc.REFUSE, None, None, (), (), None))
        return reasons


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------
class RequestValidationTests(QuotaTestBase):
    def test_well_formed_request_is_valid(self):
        self.assertValid(request())

    def test_untyped_inputs_are_refused_without_raising(self):
        for garbage in (None, {}, [], "req", 1, object(), request().__dict__):
            self.assertEqual(qc.validate_request(garbage), (qc.REQUEST_NOT_TYPED,))
        self.assertRefused(request(policy={"policy_id": "pol-1"}), qc.POLICY_NOT_TYPED)
        self.assertRefused(request(reservation=None), qc.RESERVATION_NOT_TYPED)
        self.assertRefused(request(observations=[observation()]), qc.OBSERVATIONS_MALFORMED)
        self.assertRefused(request(observations=({"evidence_id": "ev-1"},)), qc.OBSERVATIONS_MALFORMED)

    def test_schema_versions_are_exact_ints(self):
        self.assertRefused(request(schema_version=2), qc.SCHEMA_VERSION_UNSUPPORTED)
        self.assertRefused(request(schema_version=True), qc.SCHEMA_VERSION_UNSUPPORTED)
        self.assertRefused(request(policy=policy(schema_version=True)), qc.POLICY_SCHEMA_VERSION_UNSUPPORTED)

    def test_ids_are_bounded_lowercase_tokens(self):
        for bad in ("", "Req", "1req", "req/1", "..", "req 1", "a" * 49, "ré", None, 7):
            self.assertRefused(request(request_id=bad), qc.REQUEST_ID_INVALID)
        self.assertRefused(request(policy=qc.QuotaPolicy(policy_id="C:\\x", limits=(limit(),))), qc.POLICY_ID_INVALID)
        self.assertRefused(request(policy=policy((limit(limit_id="../x"),))), qc.LIMIT_ID_INVALID)
        self.assertRefused(request(observations=(observation(evidence_id="EV"),)), qc.OBSERVATION_ID_INVALID)
        self.assertRefused(request(reservation=reservation(reservation_id="")), qc.RESERVATION_ID_INVALID)

    def test_str_subclass_ids_are_refused(self):
        class Sneaky(str):
            pass
        self.assertRefused(request(request_id=Sneaky("req-1")), qc.REQUEST_ID_INVALID)

    def test_credential_shaped_ids_are_refused(self):
        self.assertRefused(request(request_id="sk-abcdef123456"), qc.ID_SECRET_SHAPED)
        self.assertRefused(request(observations=(observation(evidence_id="a" * 40),)), qc.ID_SECRET_SHAPED)
        self.assertValid(request(request_id="req-" + "a" * 20))

    def test_ids_are_unique_across_the_whole_request(self):
        self.assertRefused(request(observations=(observation("ev-1"), observation("ev-1"))), qc.ID_DUPLICATE)
        self.assertRefused(request(policy=policy((limit("x"), limit("x", unit=qc.UNIT_REQUESTS, window=window())))),
                           qc.ID_DUPLICATE)
        self.assertRefused(request(request_id="pol-1"), qc.ID_DUPLICATE)
        self.assertRefused(request(reservation=reservation(reservation_id="ev-1")), qc.ID_DUPLICATE)

    def test_timestamps_must_be_strict_utc(self):
        for bad in ("2026-10-31T12:00:00", "2026-10-31T13:00:00+01:00", "2026-10-31 12:00:00Z",
                    "2026-10-31T12:00:00-00:00", "20261031T120000Z", "1999-12-31T23:59:59Z", "", None, 0):
            self.assertRefused(request(as_of_utc=bad), qc.AS_OF_INVALID)
            self.assertRefused(request(observations=(observation(observed_at_utc=bad),)),
                               qc.OBSERVATION_TIME_INVALID)
        self.assertValid(request(as_of_utc="2026-10-31T12:00:00+00:00"))
        self.assertValid(request(as_of_utc="2026-10-31T12:00:00.250Z"))

    def test_validation_reports_every_problem_in_canonical_order(self):
        reasons = self.assertRefused(
            request(request_id="BAD", as_of_utc="nope", policy=policy(()), reservation=reservation(amounts=())),
            qc.REQUEST_ID_INVALID, qc.AS_OF_INVALID, qc.LIMITS_EMPTY, qc.RESERVATION_AMOUNTS_MALFORMED)
        self.assertEqual(len(reasons), 4)


# ---------------------------------------------------------------------------
# Policy, limits, windows and units
# ---------------------------------------------------------------------------
class LimitTests(QuotaTestBase):
    def test_policy_limits_are_a_bounded_non_empty_tuple(self):
        self.assertRefused(request(policy=policy([limit()])), qc.LIMITS_MALFORMED)
        self.assertRefused(request(policy=policy(())), qc.LIMITS_EMPTY)
        many = tuple(limit(f"l{i}", qc.SCOPE_PROVIDER, provider_id=f"p{i}") for i in range(qc.MAX_LIMITS + 1))
        self.assertRefused(request(policy=policy(many)), qc.LIMITS_MALFORMED)
        self.assertRefused(request(policy=policy((limit(), "limit"))), qc.LIMITS_MALFORMED)

    def test_scope_targets_are_exact(self):
        self.assertValid(request(policy=policy((limit(scope=qc.SCOPE_PROVIDER, provider_id="alpha"),))))
        self.assertValid(request(policy=policy((limit(scope=qc.SCOPE_RESOURCE, resource_id="gpu.pool"),))))
        self.assertValid(request(policy=policy((
            limit(scope=qc.SCOPE_RESOURCE, resource_id="gpu.pool", provider_id="alpha"),))))
        for bad in (limit(provider_id="alpha"), limit(resource_id="gpu"), limit(scope=qc.SCOPE_PROVIDER),
                    limit(scope=qc.SCOPE_PROVIDER, provider_id="alpha", resource_id="gpu"),
                    limit(scope=qc.SCOPE_RESOURCE), limit(scope=qc.SCOPE_PROVIDER, provider_id="Alpha!")):
            self.assertRefused(request(policy=policy((bad,))), qc.LIMIT_SCOPE_TARGET_INVALID)
        self.assertRefused(request(policy=policy((limit(scope="TENANT"),))), qc.LIMIT_SCOPE_UNKNOWN)

    def test_units_are_unambiguous_and_never_money(self):
        for bad in ("TOKENS", "USD", "EUR", "CREDITS", "concurrent_executions", None):
            self.assertRefused(request(policy=policy((limit(unit=bad),))), qc.LIMIT_UNIT_UNKNOWN)
        for unit in qc.UNITS:
            for word in ("USD", "EUR", "COST", "PRICE", "CREDIT", "DOLLAR"):
                self.assertNotIn(word, unit)
        self.assertEqual(set(qc.UNIT_MAXIMUM), set(qc.UNITS))

    def test_maximum_is_a_bounded_int_per_unit(self):
        for bad in (0, -1, True, 2.0, "2", qc.MAX_CONCURRENT + 1):
            self.assertRefused(request(policy=policy((limit(maximum=bad),))), qc.LIMIT_MAXIMUM_INVALID)
        self.assertValid(request(policy=policy((limit(maximum=qc.MAX_CONCURRENT),))))
        tokens = qc.UNIT_TOTAL_TOKENS
        self.assertValid(request(policy=policy((limit(unit=tokens, maximum=qc.UNIT_MAXIMUM[tokens], window=window()),))))
        self.assertRefused(request(policy=policy((limit(unit=tokens, maximum=qc.UNIT_MAXIMUM[tokens] + 1,
                                                        window=window()),))), qc.LIMIT_MAXIMUM_INVALID)

    def test_instant_units_forbid_and_cumulative_units_require_a_window(self):
        self.assertRefused(request(policy=policy((limit(window=window()),))), qc.LIMIT_WINDOW_FORBIDDEN)
        for unit in set(qc.UNITS) - qc.INSTANT_UNITS:
            self.assertRefused(request(policy=policy((limit(unit=unit, maximum=1),))), qc.LIMIT_WINDOW_REQUIRED)
            self.assertValid(request(policy=policy((limit(unit=unit, maximum=1, window=window()),))))

    def test_windows_are_typed_bounded_and_anchored_in_utc(self):
        def check(w):
            return request(policy=policy((limit(unit=qc.UNIT_REQUESTS, maximum=10, window=w),)))
        self.assertRefused(check((qc.WINDOW_ROLLING, 60)), qc.WINDOW_NOT_TYPED)
        self.assertRefused(check(window(kind="SLIDING")), qc.WINDOW_KIND_UNKNOWN)
        for bad in (0, -5, True, qc.MAX_WINDOW_SECONDS + 1, 60.0):
            self.assertRefused(check(window(seconds=bad)), qc.WINDOW_DURATION_INVALID)
        self.assertValid(check(window(seconds=qc.MAX_WINDOW_SECONDS)))
        self.assertValid(check(window(qc.WINDOW_FIXED, 86400, "2026-10-31T00:00:00Z")))
        self.assertRefused(check(window(qc.WINDOW_FIXED, 86400)), qc.WINDOW_ANCHOR_INVALID)
        self.assertRefused(check(window(qc.WINDOW_FIXED, 86400, "2026-10-31T02:00:00+02:00")),
                           qc.WINDOW_ANCHOR_INVALID)
        self.assertRefused(check(window(anchor="2026-10-31T00:00:00Z")), qc.WINDOW_ANCHOR_INVALID)

    def test_identical_limits_are_ambiguous_but_distinct_windows_are_not(self):
        a = limit("a", unit=qc.UNIT_REQUESTS, maximum=10, window=window(seconds=60))
        b = limit("b", unit=qc.UNIT_REQUESTS, maximum=20, window=window(seconds=60))
        c = limit("c", unit=qc.UNIT_REQUESTS, maximum=500, window=window(seconds=86400))
        self.assertRefused(request(policy=policy((a, b))), qc.LIMIT_AMBIGUOUS)
        self.assertValid(request(policy=policy((a, c))))
        d = limit("d", unit=qc.UNIT_REQUESTS, maximum=10, window=window(qc.WINDOW_FIXED, 60, "2026-10-31T00:00:00Z"))
        e = limit("e", unit=qc.UNIT_REQUESTS, maximum=10,
                  window=window(qc.WINDOW_FIXED, 60, "2026-10-31T00:00:00+00:00"))
        self.assertRefused(request(policy=policy((d, e))), qc.LIMIT_AMBIGUOUS)

    def test_evidence_age_is_bounded_like_the_capacity_facts(self):
        for bad in (0, True, qc.MAX_EVIDENCE_AGE_SECONDS + 1, "900"):
            self.assertRefused(request(policy=policy(max_evidence_age_seconds=bad)), qc.MAX_EVIDENCE_AGE_INVALID)
        self.assertValid(request(policy=policy(max_evidence_age_seconds=qc.MAX_EVIDENCE_AGE_SECONDS)))


# ---------------------------------------------------------------------------
# Observed evidence and reliability
# ---------------------------------------------------------------------------
class ObservationTests(QuotaTestBase):
    def test_no_observation_is_still_a_valid_question(self):
        self.assertValid(request(observations=()))

    def test_observations_are_bounded(self):
        many = tuple(observation(f"ev-{i}") for i in range(qc.MAX_OBSERVATIONS + 1))
        self.assertRefused(request(observations=many), qc.OBSERVATIONS_MALFORMED)

    def test_source_and_reliability_vocabularies(self):
        self.assertRefused(request(observations=(observation(source="PROVIDER_PROSE"),)),
                           qc.OBSERVATION_SOURCE_UNKNOWN)
        self.assertRefused(request(observations=(observation(reliability="CERTIFIED"),)),
                           qc.OBSERVATION_RELIABILITY_UNKNOWN)

    def test_a_source_can_never_claim_more_reliability_than_it_has(self):
        for source, ceiling in qc.SOURCE_MAX_RELIABILITY.items():
            for level in qc.RELIABILITIES:
                req = request(observations=(observation(source=source, reliability=level),))
                if qc.RELIABILITIES.index(level) <= qc.RELIABILITIES.index(ceiling):
                    self.assertValid(req)
                else:
                    self.assertRefused(req, qc.OBSERVATION_RELIABILITY_OVERCLAIMED)
        self.assertEqual(qc.SOURCE_MAX_RELIABILITY[qc.SOURCE_OPERATOR_DECLARATION], qc.RELIABILITY_UNVERIFIED)

    def test_availability_reuses_the_router_vocabulary(self):
        for state in rt.AVAILABILITY_STATES:
            self.assertValid(request(observations=(observation(availability=state),)))
        for bad in ("OK", "AVAILABLE", "none", None):
            self.assertRefused(request(observations=(observation(availability=bad),)),
                               qc.OBSERVATION_AVAILABILITY_UNKNOWN)

    def test_condition_must_agree_with_availability(self):
        self.assertValid(request(observations=(observation(availability="QUOTA_WAIT", condition=QUOTA),)))
        self.assertValid(request(observations=(observation(availability="AUTH_BLOCKED", condition=AUTH),)))
        self.assertValid(request(observations=(observation(availability="NONE", condition=TRANSIENT),)))
        self.assertValid(request(observations=(observation(availability="UNKNOWN", condition=QUOTA),)))
        for avail, cond in (("NONE", QUOTA), ("QUOTA_WAIT", AUTH), ("AUTH_BLOCKED", QUOTA),
                            ("QUOTA_WAIT", TRANSIENT)):
            self.assertRefused(request(observations=(observation(availability=avail, condition=cond),)),
                               qc.OBSERVATION_CONDITION_CONTRADICTS)
        self.assertRefused(request(observations=(observation(condition="QUOTA_EXHAUSTED"),)),
                           qc.OBSERVATION_CONDITION_UNKNOWN)

    def test_eligibility_mirrors_a_runner_quota_wait(self):
        ok = dict(availability="QUOTA_WAIT", condition=QUOTA, source=qc.SOURCE_RUNNER_PROVIDER_WAIT,
                  next_eligible_utc="2026-10-31T13:00:00Z")
        for source in qc.ELIGIBILITY_SOURCES:
            self.assertValid(request(observations=(observation(eligibility_source=source, **ok),)))
        bad_cases = (
            dict(ok, eligibility_source=None),
            dict(ok, eligibility_source="GUESS"),
            dict(ok, eligibility_source="RESET_HINT", next_eligible_utc="2026-10-31T15:00:00+02:00"),
            dict(ok, eligibility_source="RESET_HINT", availability="NONE", condition=None),
            dict(availability="QUOTA_WAIT", eligibility_source="RESET_HINT"),
        )
        for case in bad_cases:
            self.assertRefused(request(observations=(observation(**case),)), qc.OBSERVATION_ELIGIBILITY_INVALID)

    def test_observed_usage_has_an_explicit_unit_and_bounded_amount(self):
        self.assertValid(request(observations=(observation(usage_unit=qc.UNIT_TOTAL_TOKENS, usage_amount=0),)))
        for unit, amount in ((qc.UNIT_TOTAL_TOKENS, None), (None, 5), ("TOKENS", 5), (qc.UNIT_REQUESTS, True),
                             (qc.UNIT_REQUESTS, -1), (qc.UNIT_CONCURRENT_EXECUTIONS, qc.MAX_CONCURRENT + 1)):
            self.assertRefused(request(observations=(observation(usage_unit=unit, usage_amount=amount),)),
                               qc.OBSERVATION_USAGE_INVALID)

    def test_observation_targets_are_validated(self):
        self.assertRefused(request(observations=(observation(provider="Alpha"),)), qc.OBSERVATION_PROVIDER_INVALID)
        self.assertRefused(request(observations=(observation(provider=None),)), qc.OBSERVATION_PROVIDER_INVALID)
        self.assertRefused(request(observations=(observation(resource_id="/etc"),)),
                           qc.OBSERVATION_RESOURCE_INVALID)


# ---------------------------------------------------------------------------
# Advisory reservation
# ---------------------------------------------------------------------------
class ReservationTests(QuotaTestBase):
    def test_amounts_are_unique_bounded_unit_pairs(self):
        self.assertValid(request(reservation=reservation(
            ((qc.UNIT_CONCURRENT_EXECUTIONS, 1), (qc.UNIT_TOTAL_TOKENS, 50000)))))
        for bad in ((), [(qc.UNIT_EXECUTIONS, 1)], ((qc.UNIT_EXECUTIONS, 0),), ((qc.UNIT_EXECUTIONS, True),),
                    ((qc.UNIT_EXECUTIONS,),), (("USD", 1),), ((qc.UNIT_CONCURRENT_EXECUTIONS, 17),),
                    ([qc.UNIT_EXECUTIONS, 1],)):
            self.assertRefused(request(reservation=reservation(bad)), qc.RESERVATION_AMOUNTS_MALFORMED)
        self.assertRefused(request(reservation=reservation(((qc.UNIT_EXECUTIONS, 1), (qc.UNIT_EXECUTIONS, 2)))),
                           qc.RESERVATION_UNIT_DUPLICATE)

    def test_reservation_target_is_validated(self):
        self.assertRefused(request(reservation=reservation(provider_id="")), qc.RESERVATION_TARGET_INVALID)
        self.assertRefused(request(reservation=reservation(resource_id="A B")), qc.RESERVATION_TARGET_INVALID)
        self.assertValid(request(reservation=reservation(resource_id="gpu.pool")))


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
class ResultTests(unittest.TestCase):
    def test_verdict_vocabulary_and_precedence(self):
        self.assertEqual(qc.VERDICTS, ("READY", "WAIT", "REFUSE", "UNKNOWN"))
        self.assertEqual(qc.verdict_for(()), qc.READY)
        self.assertEqual(qc.verdict_for((qc.LIMIT_SATURATED,)), qc.WAIT)
        self.assertEqual(qc.verdict_for((qc.NO_EVIDENCE, qc.PROVIDER_QUOTA_WAIT)), qc.UNKNOWN)
        self.assertEqual(qc.verdict_for((qc.PROVIDER_AUTH_BLOCKED, qc.NO_EVIDENCE, qc.LIMIT_SATURATED)), qc.REFUSE)

    def test_result_verdict_is_derived_never_claimed(self):
        self.assertEqual(result().verdict, qc.READY)
        for verdict, reasons in ((qc.READY, (qc.NO_EVIDENCE,)), (qc.WAIT, ()), (qc.READY, (qc.PROVIDER_QUOTA_WAIT,)),
                                 (qc.WAIT, (qc.PROVIDER_AUTH_BLOCKED,)), (qc.UNKNOWN, (qc.LIMIT_SATURATED,)),
                                 ("PASS", ())):
            with self.assertRaises(ValueError):
                result(verdict, reasons)

    def test_quota_wait_auth_blocked_and_unknown_stay_fail_closed(self):
        self.assertEqual(result(qc.WAIT, (qc.PROVIDER_QUOTA_WAIT,)).verdict, qc.WAIT)
        self.assertEqual(result(qc.REFUSE, (qc.PROVIDER_AUTH_BLOCKED,)).verdict, qc.REFUSE)
        self.assertEqual(result(qc.UNKNOWN, (qc.AVAILABILITY_UNKNOWN,)).verdict, qc.UNKNOWN)
        for reason in qc.RESULT_REASONS:
            self.assertNotEqual(qc.verdict_for((reason,)), qc.READY)

    def test_ready_must_cite_evidence(self):
        with self.assertRaises(ValueError):
            result(evidence_ids=())
        self.assertEqual(result(qc.UNKNOWN, (qc.NO_EVIDENCE,), evidence_ids=()).evidence_ids, ())

    def test_reasons_and_evidence_ids_are_ordered_and_unique(self):
        for reasons in ((qc.LIMIT_SATURATED, qc.PROVIDER_QUOTA_WAIT), (qc.LIMIT_SATURATED,) * 2, ["LIMIT_SATURATED"],
                        ("SOMETHING_ELSE",)):
            with self.assertRaises(ValueError):
                result(qc.WAIT, reasons)
        for ids in (("ev-2", "ev-1"), ("ev-1", "ev-1"), ["ev-1"], ("EV",)):
            with self.assertRaises(ValueError):
                result(evidence_ids=ids)

    def test_wait_until_only_on_wait_and_normalized_utc(self):
        ok = result(qc.WAIT, (qc.PROVIDER_QUOTA_WAIT,), wait_until_utc="2026-10-31T13:00:00Z")
        self.assertEqual(ok.wait_until_utc, "2026-10-31T13:00:00Z")
        for verdict, reasons, value in ((qc.READY, (), "2026-10-31T13:00:00Z"),
                                        (qc.WAIT, (qc.PROVIDER_QUOTA_WAIT,), "2026-10-31T13:00:00+00:00"),
                                        (qc.WAIT, (qc.PROVIDER_QUOTA_WAIT,), "2026-10-31T15:00:00+02:00"),
                                        (qc.WAIT, (qc.PROVIDER_QUOTA_WAIT,), "soon")):
            with self.assertRaises(ValueError):
                result(verdict, reasons, wait_until_utc=value)

    def test_refused_result_echoes_nothing(self):
        refused = qc.refused_result((qc.AS_OF_INVALID, qc.REQUEST_ID_INVALID))
        self.assertEqual(refused.request_reasons, (qc.REQUEST_ID_INVALID, qc.AS_OF_INVALID))
        with self.assertRaises(ValueError):
            qc.QuotaResult(verdict=qc.REFUSE, request_id="req-1", request_fingerprint=None,
                           request_reasons=(qc.AS_OF_INVALID,), reasons=(), evidence_ids=())
        with self.assertRaises(ValueError):
            qc.QuotaResult(verdict=qc.UNKNOWN, request_id=None, request_fingerprint=None,
                           request_reasons=(qc.AS_OF_INVALID,), reasons=(), evidence_ids=())
        with self.assertRaises(ValueError):
            qc.QuotaResult(verdict=qc.READY, request_id="req-1", request_fingerprint="abc", request_reasons=(),
                           reasons=(), evidence_ids=("ev-1",))

    def test_every_authority_flag_is_false_by_construction(self):
        for res in (result(), qc.refused_result((qc.REQUEST_NOT_TYPED,))):
            payload = res.to_dict()
            for flag in ALL_FLAGS:
                self.assertIs(getattr(res, flag), False, flag)
                self.assertIs(payload[flag], False, flag)
                with self.assertRaises(AttributeError):
                    setattr(res, flag, True)
            self.assertEqual(payload["marker"], qc.QUOTA_MARKER)
        field_names = {f.name for f in dataclasses.fields(qc.QuotaResult)}
        self.assertFalse(field_names & set(ALL_FLAGS))
        with self.assertRaises(TypeError):
            result(certified=True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result().verdict = qc.WAIT

    def test_canonical_json_is_exact_type_stable_and_bounded(self):
        text = qc.canonical_json(result())
        self.assertEqual(text, qc.canonical_json(result()))
        self.assertEqual(json.loads(text)["schema"], qc.SCHEMA)
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, separators=(",", ":")))
        self.assertTrue(text.isascii())

        class Sub(qc.QuotaResult):
            def to_dict(self):
                return {"certified": True}
        with self.assertRaises(TypeError):
            qc.canonical_json(Sub(qc.READY, "req-1", FINGERPRINT, (), (), ("ev-1",)))
        with self.assertRaises(TypeError):
            qc.canonical_json(result().to_dict())


# ---------------------------------------------------------------------------
# Canonical request and fingerprint
# ---------------------------------------------------------------------------
class CanonicalRequestTests(QuotaTestBase):
    def test_canonical_request_is_order_and_offset_independent(self):
        o1, o2 = observation("ev-1"), observation("ev-2", provider="beta", observed_at_utc="2026-10-31T11:00:00Z")
        l1 = limit("l1")
        l2 = limit("l2", qc.SCOPE_PROVIDER, qc.UNIT_REQUESTS, 10, window=window(), provider_id="alpha")
        a = request(observations=(o1, o2), policy=policy((l1, l2)), as_of_utc="2026-10-31T12:00:00+00:00")
        b = request(observations=(o2, o1), policy=policy((l2, l1)), as_of_utc="2026-10-31T12:00:00Z")
        self.assertEqual(qc.canonical_request_json(a), qc.canonical_request_json(b))
        self.assertEqual(qc.request_fingerprint(a), qc.request_fingerprint(b))
        self.assertIn('"as_of_utc":"2026-10-31T12:00:00Z"', qc.canonical_request_json(a))

    def test_fingerprint_tracks_every_material_input(self):
        base = qc.request_fingerprint(request())
        variants = (
            request(request_id="req-2"), request(as_of_utc="2026-10-31T12:00:01Z"),
            request(policy=policy((limit(maximum=3),))), request(policy=policy(max_evidence_age_seconds=60)),
            request(reservation=reservation(((qc.UNIT_CONCURRENT_EXECUTIONS, 2),))),
            request(observations=(observation(availability="UNKNOWN"),)), request(observations=()),
            request(observations=(observation(reliability=qc.RELIABILITY_CALLER_OBSERVED),)),
        )
        prints = {qc.request_fingerprint(v) for v in variants}
        self.assertEqual(len(prints), len(variants))
        self.assertNotIn(base, prints)
        self.assertRegex(base, r"^[0-9a-f]{64}$")

    def test_invalid_requests_have_no_canonical_form(self):
        for bad in (None, request(request_id="BAD")):
            with self.assertRaises(ValueError):
                qc.canonical_request_json(bad)
            with self.assertRaises(ValueError):
                qc.request_fingerprint(bad)

    def test_canonical_request_contains_no_free_text(self):
        payload = json.loads(qc.canonical_request_json(request(observations=(
            observation(availability="QUOTA_WAIT", condition=QUOTA, source=qc.SOURCE_RUNNER_PROVIDER_WAIT,
                        next_eligible_utc="2026-10-31T13:00:00Z", eligibility_source="RESET_HINT"),))))
        keys = set()

        def walk(node):
            if isinstance(node, dict):
                keys.update(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(payload)
        for forbidden in ("message", "message_excerpt", "reset_hint", "stderr", "prompt", "email", "price", "cost",
                          "token", "secret", "customer"):
            self.assertNotIn(forbidden, keys)


# ---------------------------------------------------------------------------
# Determinism, purity and governed surface
# ---------------------------------------------------------------------------
class PurityTests(QuotaTestBase):
    def test_validation_never_mutates_inputs(self):
        req = request()
        before = copy.deepcopy(req)
        qc.validate_request(req)
        qc.canonical_request_json(req)
        self.assertEqual(req, before)
        for obj in (req, req.policy, req.reservation, req.observations[0], req.policy.limits[0]):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(obj, dataclasses.fields(obj)[0].name, "x")

    def test_no_io_processes_network_or_runner_entry_points(self):
        boom = AssertionError("I/O or execution entry point")
        with mock.patch.object(subprocess, "Popen", side_effect=boom), \
                mock.patch.object(builtins, "open", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(os, "stat", side_effect=boom), \
                mock.patch.object(os, "replace", side_effect=boom), \
                mock.patch.object(os, "mkdir", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom), \
                mock.patch.object(rp.DirLease, "try_acquire", side_effect=boom):
            self.assertEqual(qc.validate_request(request()), ())
            qc.request_fingerprint(request())
            qc.canonical_json(result())

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_provider_routing_policy", "fabric_scheduler_capacity", "fabric_scheduler_contract",
               "fabric_scheduler_window", "runner_provider_availability")
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "re", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "DirLease", "lease_dir", "ledger", "_launch", "_start_ready", ".now(", "utcnow", "sleep",
                     "while ", "claude", "codex", "eval(", "exec(", "importlib", "random", "requests.", "urllib",
                     "http", "environ", "propose_route", "classify_provider_failure", "evaluate_capacity(",
                     "price", "cost", "currency"):
            self.assertNotIn(word, code, word)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_mutable_module_state_changes(self):
        modules = (qc, cap, rt, availability)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        qc.validate_request(request())
        qc.validate_request(None)
        qc.request_fingerprint(request())
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_upper_snake(self):
        vocabularies = (qc.VERDICTS, qc.REQUEST_REASONS, qc.RESULT_REASONS, qc.UNITS, qc.LIMIT_SCOPES,
                        qc.WINDOW_KINDS, qc.EVIDENCE_SOURCES, qc.RELIABILITIES, qc.ELIGIBILITY_SOURCES)
        for vocab in vocabularies:
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(qc.REQUEST_REASONS) & set(qc.RESULT_REASONS))
        groups = (qc.REFUSING_REASONS, qc.UNKNOWN_REASONS, qc.WAITING_REASONS)
        self.assertEqual(sum(len(g) for g in groups), len(qc.RESULT_REASONS))
        self.assertEqual(set(qc.SOURCE_MAX_RELIABILITY), set(qc.EVIDENCE_SOURCES))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


# ---------------------------------------------------------------------------
# Runner, Router and Scheduler pins (reused, never redefined)
# ---------------------------------------------------------------------------
class PolicyPinTests(unittest.TestCase):
    def test_bounds_mirror_the_runner_and_scheduler(self):
        self.assertEqual(qc.MAX_CONCURRENT, rp.MAX_PIPELINE_WORKERS)
        self.assertEqual(qc.UNIT_MAXIMUM[qc.UNIT_CONCURRENT_EXECUTIONS], rp.MAX_PIPELINE_WORKERS)
        self.assertEqual(qc.MAX_PROVIDERS, rt.MAX_PROVIDERS)
        self.assertEqual(qc.DEFAULT_MAX_EVIDENCE_AGE_SECONDS, cap.DEFAULT_MAX_FACT_AGE_SECONDS)
        self.assertEqual(qc.MAX_EVIDENCE_AGE_SECONDS, cap.MAX_FACT_AGE_SECONDS)
        self.assertEqual(qc.MAX_WINDOW_SECONDS, int(sw.MAX_HORIZON.total_seconds()))

    def test_availability_and_conditions_are_reused(self):
        self.assertEqual(qc.AVAILABILITY_STATES, rt.AVAILABILITY_STATES)
        self.assertEqual(set(qc.CONDITIONS), {c.value for c in availability.ProviderCondition})
        self.assertIs(qc.CONDITION_AVAILABILITY, cap._CONDITION_AVAILABILITY)
        self.assertEqual(qc.UNKNOWN, sc.UNKNOWN)

    def test_eligibility_sources_are_the_runner_quota_wait_sources(self):
        runner_tree = ast.parse(Path(rp.__file__).read_text(encoding="utf-8"))
        hold = next(n for n in ast.walk(runner_tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_hold_for_provider")
        literals = {n.value for n in ast.walk(hold) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertTrue(set(qc.ELIGIBILITY_SOURCES) <= literals)
        self.assertIn("next_eligible_utc", literals)
        self.assertIn("eligibility_source", literals)

    def test_zero_authority_flags_extend_the_scheduler_contract(self):
        self.assertTrue(issubclass(qc.QuotaResult, sc._NotAuthorized))
        base = sc._NotAuthorized._guarantees()
        guarantees = qc._QuotaGuarantees._guarantees()
        self.assertTrue(set(base) <= set(guarantees))
        self.assertEqual({k for k, v in guarantees.items() if v is not False}, {"marker"})


if __name__ == "__main__":
    unittest.main()
