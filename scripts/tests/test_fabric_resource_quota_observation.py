"""FCP-10A-02: verifiable quota / availability observation adapter.

Runner facts are produced by the Runner's own code: quota/auth holds by the
real `PipelineRunner._hold_for_provider` (only its persistence is replaced by
an in-memory host) and classifications by the real
`classify_provider_failure`. Router and Scheduler facts are their native
frozen types. Provider ids are opaque labels; nothing is executed, reserved,
bought or sent anywhere. Nothing here is skipped.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_provider_routing_policy as rt
from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_resource_quota_observation as qo
from scripts.ai import fabric_scheduler_capacity as cap
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_provider_availability as availability

MODULE_PATH = Path(qo.__file__)
TEST_PATH = Path(__file__).resolve()
AS_OF = "2026-10-31T12:00:00Z"
OBSERVED = "2026-10-31T11:59:00Z"
HIT = datetime(2026, 10, 31, 11, 59, tzinfo=timezone.utc)
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "reservation_held",
             "quota_authority", "purchase_allowed", "remote_api_allowed")
QUOTA = availability.ProviderCondition.QUOTA_EXHAUSTED.value
AUTH = availability.ProviderCondition.AUTH_BLOCKED.value
TRANSIENT = availability.ProviderCondition.TRANSIENT_ERROR.value
QUOTA_RESET_MESSAGE = "You've hit your session limit - resets 3pm (Etc/UTC)"
QUOTA_MESSAGE = "quota exceeded for this account"
AUTH_MESSAGE = "Not logged in - please run /login"


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


class _PersistenceHost:
    """Replaces only the Runner's disk writes; the transition table and the
    hold logic exercised are the Runner's own."""

    def __init__(self, tz_lookup=None):
        self.tz_lookup = tz_lookup
        self.results = []

    def _transition(self, worker, new, reason=None):
        if new not in rp._ALLOWED_TRANSITIONS[worker.worker_state]:
            raise AssertionError(f"illegal transition {worker.state} -> {new.value}")
        worker.state, worker.state_reason = new.value, reason

    def _write_result(self, worker, payload):
        self.results.append(payload)


def runner_hold(message=QUOTA_RESET_MESSAGE, provider="alpha", now=HIT, previous=None):
    spec = rp.WorkerSpec(id="w1", worktree=".", work_order="wo.md", provider=provider, mode="write")
    worker = rp.WorkerRuntime(spec=spec, order=0, state=rp.WorkerState.RUNNING.value, provider_wait=previous)
    condition = availability.classify_provider_failure(message=message)
    host = _PersistenceHost(tz_lookup=lambda name: timezone.utc)
    rp.PipelineRunner._hold_for_provider(host, worker, {}, condition, None, now)
    return worker


def with_wait(worker, **changes):
    wait = dict(worker.provider_wait)
    for key, value in changes.items():
        if value is ...:
            wait.pop(key, None)
        else:
            wait[key] = value
    return dataclasses.replace(worker, provider_wait=wait)


def router_facts(provider="alpha", availability_state="NONE", capacity="AVAILABLE", **kw):
    fields = dict(provider_id=provider, probe_available=True, policy_mode="write", policy_allow_shell=False,
                  policy_supported=True, capabilities=("READ_FILES", "EDIT_FILES"),
                  availability=availability_state, capacity=capacity)
    fields.update(kw)
    return rt.ProviderFacts(**fields)


def capacity_facts(provider="alpha", availability_state="NONE", capacity="AVAILABLE", slots=2, observed=OBSERVED,
                   last_condition=None):
    return cap.ProviderCapacityFacts(provider_id=provider, availability=availability_state, capacity=capacity,
                                     proven_slots=slots, observed_at_utc=observed, last_condition=last_condition)


def wait_record(worker=None, evidence_id="ev-wait", provider="alpha", **kw):
    return qo.SourceRecord(evidence_id=evidence_id, source=qc.SOURCE_RUNNER_PROVIDER_WAIT, provider_id=provider,
                           payload=runner_hold() if worker is None else worker, **kw)


def condition_record(message=QUOTA_MESSAGE, evidence_id="ev-cond", provider="alpha", observed=OBSERVED, **kw):
    payload = kw.pop("payload", None) or availability.classify_provider_failure(message=message, **kw)
    return qo.SourceRecord(evidence_id=evidence_id, source=qc.SOURCE_RUNNER_PROVIDER_CONDITION,
                           provider_id=provider, payload=payload, observed_at_utc=observed)


def router_record(facts=None, evidence_id="ev-router", provider="alpha", observed=OBSERVED):
    return qo.SourceRecord(evidence_id=evidence_id, source=qc.SOURCE_ROUTER_PROVIDER_FACTS, provider_id=provider,
                           payload=router_facts(provider) if facts is None else facts, observed_at_utc=observed)


def capacity_record(facts=None, evidence_id="ev-cap", provider="alpha", observed=None):
    return qo.SourceRecord(evidence_id=evidence_id, source=qc.SOURCE_SCHEDULER_CAPACITY_FACTS, provider_id=provider,
                           payload=capacity_facts(provider) if facts is None else facts, observed_at_utc=observed)


def request(records=(), **kw):
    fields = dict(request_id="obs-1", as_of_utc=AS_OF, records=records)
    fields.update(kw)
    return qo.ObservationRequest(**fields)


def adapt(*records, **kw):
    return qo.adapt_observations(request(records=records, **kw))


class ObservationTestBase(unittest.TestCase):
    def assertRefused(self, snapshot, *codes):
        self.assertEqual(snapshot.outcome, qo.REFUSED)
        for code in codes:
            self.assertIn(code, snapshot.request_reasons)
        self.assertEqual((snapshot.request_id, snapshot.as_of_utc, snapshot.snapshot_fingerprint, snapshot.records,
                          snapshot.providers, snapshot.observations), (None, None, None, (), (), ()))

    def assertRejected(self, snapshot, *codes, index=0):
        record = snapshot.records[index]
        self.assertEqual((record.status, record.observation, record.certainty), (qo.REJECTED, None, qo.UNCERTAIN))
        for code in codes:
            self.assertIn(code, record.reasons)
        self.assertEqual(snapshot.outcome, qo.UNKNOWN)
        return record

    def view(self, snapshot, provider="alpha"):
        view = snapshot.provider_view(provider)
        self.assertIsNotNone(view)
        return view


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------
class RequestTests(ObservationTestBase):
    def test_untyped_requests_are_refused_without_raising(self):
        for garbage in (None, {}, [], "obs-1", 1, object(), request().__dict__):
            self.assertRefused(qo.adapt_observations(garbage), qo.REQUEST_NOT_TYPED)

    def test_request_scalars_are_exact_and_strict_utc(self):
        self.assertRefused(adapt(schema_version=2), qo.SCHEMA_VERSION_UNSUPPORTED)
        self.assertRefused(adapt(schema_version=True), qo.SCHEMA_VERSION_UNSUPPORTED)
        self.assertRefused(adapt(request_id="Obs 1"), qo.REQUEST_ID_INVALID)
        self.assertRefused(adapt(request_id="a" * 40 + "b"), qo.ID_SECRET_SHAPED)
        for as_of in ("2026-10-31T12:00:00", "2026-10-31T14:00:00+02:00", "yesterday", None):
            self.assertRefused(adapt(as_of_utc=as_of), qo.AS_OF_INVALID)
        for age in (0, True, qc.MAX_EVIDENCE_AGE_SECONDS + 1, 1.5):
            self.assertRefused(adapt(max_evidence_age_seconds=age), qo.MAX_EVIDENCE_AGE_INVALID)

    def test_records_and_provider_ids_are_bounded_tuples(self):
        self.assertRefused(qo.adapt_observations(request(records=[router_record()])), qo.RECORDS_MALFORMED)
        many = tuple(router_record(evidence_id=f"ev-{i}") for i in range(qo.MAX_RECORDS + 1))
        self.assertRefused(qo.adapt_observations(request(records=many)), qo.RECORDS_MALFORMED)
        for ids in (["alpha"], ("alpha", "alpha"), ("Alpha",), ("alpha", 1)):
            self.assertRefused(adapt(provider_ids=ids), qo.PROVIDER_IDS_MALFORMED)
        records = tuple(router_record(router_facts(f"p{i}"), evidence_id=f"ev-{i}", provider=f"p{i}")
                        for i in range(qo.MAX_PROVIDERS))
        self.assertRefused(adapt(*records, provider_ids=("extra",)), qo.PROVIDERS_TOO_MANY)

    def test_nothing_observed_is_never_observed(self):
        snapshot = adapt()
        self.assertEqual((snapshot.outcome, snapshot.snapshot_reasons, snapshot.providers),
                         (qo.UNKNOWN, (qo.NO_EVIDENCE,), ()))
        view = self.view(adapt(provider_ids=("alpha",)))
        self.assertEqual((view.availability, view.capacity, view.certainty), ("UNKNOWN", "UNKNOWN", qo.UNCERTAIN))
        self.assertIn(qo.NO_EVIDENCE, view.reasons)


# ---------------------------------------------------------------------------
# Runner provider waits (produced by the Runner's own hold logic)
# ---------------------------------------------------------------------------
class RunnerWaitTests(ObservationTestBase):
    def test_runner_reset_hint_quota_wait_is_adapted_verbatim(self):
        worker = runner_hold()
        self.assertEqual(worker.state, rp.WorkerState.WAITING_PROVIDER_QUOTA.value)
        record = adapt(wait_record(worker)).records[0]
        obs = record.observation
        self.assertEqual((record.status, obs.availability, obs.condition, obs.eligibility_source),
                         (qo.ADAPTED, "QUOTA_WAIT", QUOTA, qc.ELIGIBILITY_RESET_HINT))
        expected = HIT.replace(hour=15, minute=0) + timedelta(seconds=rp.QUOTA_RESET_MARGIN_SECONDS)
        self.assertEqual(obs.next_eligible_utc, expected.isoformat().replace("+00:00", "Z"))
        self.assertEqual((obs.observed_at_utc, obs.reliability, record.freshness, record.age_seconds),
                         (OBSERVED, qc.RELIABILITY_RUNNER_CLASSIFIED, qo.FRESH, 60))

    def test_runner_backoff_quota_wait_keeps_the_runner_instant(self):
        obs = adapt(wait_record(runner_hold(QUOTA_MESSAGE))).records[0].observation
        self.assertEqual(obs.eligibility_source, qc.ELIGIBILITY_BACKOFF_PROBE)
        expected = HIT + timedelta(seconds=rp.QUOTA_PROBE_BASE_SECONDS)
        self.assertEqual(obs.next_eligible_utc, expected.isoformat().replace("+00:00", "Z"))

    def test_runner_auth_hold_is_auth_blocked_without_eligibility(self):
        worker = runner_hold(AUTH_MESSAGE)
        self.assertEqual(worker.state, rp.WorkerState.BLOCKED_PROVIDER_AUTH.value)
        snapshot = adapt(wait_record(worker), router_record(router_facts(availability_state="AUTH_BLOCKED")))
        obs = snapshot.records[0].observation
        self.assertEqual((obs.availability, obs.condition, obs.next_eligible_utc, obs.eligibility_source),
                         ("AUTH_BLOCKED", AUTH, None, None))
        view = self.view(snapshot)
        self.assertEqual((snapshot.outcome, view.availability, view.certainty, view.reasons),
                         (qo.OBSERVED, "AUTH_BLOCKED", qo.CERTAIN, (qo.AVAILABILITY_AUTH_BLOCKED,)))

    def test_elapsed_eligibility_never_infers_a_quota_reset(self):
        late = "2026-10-31T16:00:00Z"
        snapshot = adapt(wait_record(), as_of_utc=late, max_evidence_age_seconds=qc.MAX_EVIDENCE_AGE_SECONDS)
        view = self.view(snapshot)
        self.assertEqual((view.availability, view.certainty), ("QUOTA_WAIT", qo.UNCERTAIN))
        self.assertIn(qo.QUOTA_RECOVERY_UNCONFIRMED, view.reasons)
        self.assertIn(qo.AVAILABILITY_QUOTA_WAIT, view.reasons)
        self.assertEqual(view.next_eligible_utc, "2026-10-31T15:01:00Z")

    def test_quota_wait_without_runner_eligibility_is_fact_missing_but_held(self):
        for changes in ({"next_eligible_utc": None, "eligibility_source": None}, {"eligibility_source": None},
                        {"next_eligible_utc": ...}):
            snapshot = adapt(wait_record(with_wait(runner_hold(), **changes)))
            view = self.view(snapshot)
            self.assertEqual((view.availability, view.next_eligible_utc), ("QUOTA_WAIT", None))
            self.assertIn(qo.FACT_MISSING, view.reasons)
            self.assertEqual(snapshot.outcome, qo.UNKNOWN)

    def test_internally_contradictory_waits_invent_no_hold(self):
        quota_state_auth_condition = with_wait(runner_hold(), condition=AUTH)
        auth_with_eligibility = with_wait(runner_hold(AUTH_MESSAGE), next_eligible_utc="2026-10-31T13:00:00+00:00",
                                          eligibility_source=qc.ELIGIBILITY_BACKOFF_PROBE)
        for worker in (quota_state_auth_condition, auth_with_eligibility):
            record = adapt(wait_record(worker)).records[0]
            self.assertEqual((record.status, record.observation.availability), (qo.ADAPTED, "UNKNOWN"))
            self.assertIn(qo.EVIDENCE_CONTRADICTORY, record.reasons)

    def test_non_held_or_waitless_workers_are_rejected(self):
        running = dataclasses.replace(runner_hold(), state=rp.WorkerState.RUNNING.value)
        self.assertRejected(adapt(wait_record(running)), qo.WAIT_NOT_HELD)
        waitless = dataclasses.replace(runner_hold(), provider_wait=None)
        self.assertRejected(adapt(wait_record(waitless)), qo.PAYLOAD_FACT_MISSING)
        self.assertIn(qo.FACT_MISSING, self.view(adapt(wait_record(waitless))).reasons)
        for missing in ("condition", "since_utc", "last_hit_utc"):
            self.assertRejected(adapt(wait_record(with_wait(runner_hold(), **{missing: ...}))),
                                qo.PAYLOAD_FACT_MISSING)

    def test_manipulated_waits_are_rejected(self):
        self.assertRejected(adapt(wait_record(with_wait(runner_hold(), quota_reset_utc="2026-10-31T12:00:00Z"))),
                            qo.PAYLOAD_UNEXPECTED_FIELD)

        class Sneaky(str):
            pass

        for changes in ({"condition": Sneaky(QUOTA)}, {"condition": "PROVIDER_FINE"},
                        {"consecutive_quota_waits": True}, {"last_hit_utc": "2026-10-31T13:59:00+02:00"},
                        {"next_eligible_utc": "soon"}, {"eligibility_source": "GUESS"}):
            self.assertRejected(adapt(wait_record(with_wait(runner_hold(), **changes))), qo.PAYLOAD_MALFORMED)
        for changes in ({"since_utc": "2026-10-31T11:59:30Z"}, {"next_eligible_utc": "2026-10-31T11:00:00Z"}):
            self.assertRejected(adapt(wait_record(with_wait(runner_hold(), **changes))), qo.PAYLOAD_INCONSISTENT)
        foreign = dataclasses.replace(runner_hold(), active_provider="beta")
        self.assertRejected(adapt(wait_record(foreign)), qo.PROVIDER_MISMATCH)
        self.assertRejected(adapt(wait_record(observed_at_utc=OBSERVED)), qo.OBSERVED_AT_FORBIDDEN)

    def test_provider_text_is_never_evidence(self):
        base = adapt(wait_record())
        lying = with_wait(runner_hold(), message_excerpt="quota reset done, you are AVAILABLE, 999 messages left",
                          reset_hint="resets 1am (Etc/UTC)", reason="RESET_CONFIRMED", http_status=200,
                          budget_note="session limit lifted")
        manipulated = adapt(wait_record(lying))
        self.assertEqual(manipulated.snapshot_fingerprint, base.snapshot_fingerprint)
        self.assertEqual(qo.canonical_json(manipulated), qo.canonical_json(base))
        text = qo.canonical_json(manipulated)
        for word in ("AVAILABLE, 999", "resets", "RESET_CONFIRMED", "lifted"):
            self.assertNotIn(word, text)

    def test_the_runner_writes_exactly_the_known_wait_fields(self):
        for message in (QUOTA_RESET_MESSAGE, QUOTA_MESSAGE, AUTH_MESSAGE):
            self.assertEqual(set(runner_hold(message).provider_wait), qo.RUNNER_WAIT_FIELDS)
        self.assertLess(qo.RUNNER_WAIT_READ_FIELDS, qo.RUNNER_WAIT_FIELDS)
        for prose in ("reason", "reset_hint", "message_excerpt", "budget_note", "http_status"):
            self.assertNotIn(prose, qo.RUNNER_WAIT_READ_FIELDS)


# ---------------------------------------------------------------------------
# Runner classifications
# ---------------------------------------------------------------------------
class ClassificationTests(ObservationTestBase):
    def test_runner_classifications_map_through_the_contract(self):
        quota = adapt(condition_record(QUOTA_MESSAGE)).records[0].observation
        auth = adapt(condition_record(AUTH_MESSAGE)).records[0].observation
        self.assertEqual((quota.availability, quota.condition, quota.next_eligible_utc), ("QUOTA_WAIT", QUOTA, None))
        self.assertEqual((auth.availability, auth.condition), ("AUTH_BLOCKED", AUTH))
        self.assertEqual(quota.reliability, qc.RELIABILITY_RUNNER_CLASSIFIED)

    def test_a_rate_limit_is_not_quota_and_decides_nothing(self):
        snapshot = adapt(condition_record("429 Too Many Requests: rate limit", http_status=429))
        record = snapshot.records[0]
        self.assertEqual((record.observation.condition, record.observation.availability), (TRANSIENT, "UNKNOWN"))
        self.assertIn(qo.CONDITION_UNRESOLVED, record.reasons)
        view = self.view(snapshot)
        self.assertNotIn(qo.AVAILABILITY_QUOTA_WAIT, view.reasons)
        self.assertEqual((view.availability, snapshot.outcome), ("UNKNOWN", qo.UNKNOWN))

    def test_classifications_need_an_enum_condition_and_explicit_utc(self):
        forged = availability.ProviderClassification(condition=QUOTA, reason="QUOTA_MESSAGE")
        self.assertRejected(adapt(condition_record(payload=forged)), qo.PAYLOAD_MALFORMED)
        for observed in (None, "2026-10-31T11:59:00", "2026-10-31T13:59:00+02:00"):
            self.assertRejected(adapt(condition_record(observed=observed)), qo.OBSERVED_AT_INVALID)


# ---------------------------------------------------------------------------
# Router and Scheduler facts
# ---------------------------------------------------------------------------
class FactsTests(ObservationTestBase):
    def test_fresh_consistent_facts_are_observed_and_certain(self):
        snapshot = adapt(router_record(), capacity_record())
        view = self.view(snapshot)
        self.assertEqual((snapshot.outcome, view.availability, view.capacity, view.proven_slots, view.certainty,
                          view.reasons, view.freshness),
                         (qo.OBSERVED, "NONE", "AVAILABLE", 2, qo.CERTAIN, (), qo.FRESH))
        self.assertEqual(view.evidence_ids, ("ev-cap", "ev-router"))
        self.assertEqual({o.reliability for o in snapshot.observations}, {qc.RELIABILITY_CALLER_OBSERVED})

    def test_full_and_unknown_states_are_reused_as_is(self):
        full = self.view(adapt(router_record(router_facts(capacity="FULL"))))
        self.assertEqual((full.capacity, full.certainty, full.reasons), ("FULL", qo.CERTAIN, (qo.CAPACITY_FULL,)))
        unknown = self.view(adapt(router_record(router_facts(availability_state="UNKNOWN", capacity="UNKNOWN"))))
        self.assertEqual((unknown.availability, unknown.capacity, unknown.certainty),
                         ("UNKNOWN", "UNKNOWN", qo.UNCERTAIN))
        self.assertEqual(unknown.reasons, (qo.AVAILABILITY_UNKNOWN, qo.CAPACITY_UNKNOWN))

    def test_router_only_availability_leaves_capacity_unknown(self):
        view = self.view(adapt(condition_record(AUTH_MESSAGE)))
        self.assertEqual((view.availability, view.capacity), ("AUTH_BLOCKED", "UNKNOWN"))
        self.assertIn(qo.CAPACITY_UNKNOWN, view.reasons)

    def test_malformed_or_mismatched_facts_are_rejected(self):
        class Sneaky(str):
            pass

        for facts in (router_facts(availability_state=Sneaky("NONE")), router_facts(capacity="PLENTY"),
                      router_facts(probe_available=1)):
            self.assertRejected(adapt(router_record(facts)), qo.PAYLOAD_MALFORMED)
        self.assertRejected(adapt(router_record(router_facts("beta"))), qo.PROVIDER_MISMATCH)
        for facts in (capacity_facts(slots=True), capacity_facts(availability_state="FREE"),
                      capacity_facts(observed="noon")):
            self.assertRejected(adapt(capacity_record(facts)), qo.PAYLOAD_MALFORMED)
        self.assertRejected(adapt(capacity_record(capacity_facts(observed="2026-10-31T13:59:00+02:00"))),
                            qo.OBSERVED_AT_INVALID)
        self.assertRejected(adapt(capacity_record(observed=OBSERVED)), qo.OBSERVED_AT_FORBIDDEN)
        self.assertRejected(adapt(capacity_record(capacity_facts("beta"))), qo.PROVIDER_MISMATCH)

    def test_contradictory_capacity_facts_are_unknown(self):
        record = adapt(capacity_record(capacity_facts(last_condition=AUTH))).records[0]
        self.assertEqual((record.observation.availability, record.observation.condition), ("UNKNOWN", AUTH))
        self.assertIn(qo.EVIDENCE_CONTRADICTORY, record.reasons)
        record = adapt(capacity_record(capacity_facts(slots=0))).records[0]
        self.assertEqual(record.capacity, "UNKNOWN")
        self.assertIn(qo.EVIDENCE_CONTRADICTORY, record.reasons)
        consistent = adapt(capacity_record(capacity_facts(availability_state="QUOTA_WAIT", last_condition=QUOTA)))
        self.assertEqual(self.view(consistent).availability, "QUOTA_WAIT")


# ---------------------------------------------------------------------------
# Sources and identifiers
# ---------------------------------------------------------------------------
class SourceTests(ObservationTestBase):
    def test_only_runner_and_router_sources_are_adaptable(self):
        self.assertEqual(set(qo.ADAPTABLE_SOURCES), set(qc.EVIDENCE_SOURCES) - {qc.SOURCE_OPERATOR_DECLARATION})
        declared = qo.SourceRecord(evidence_id="ev-op", source=qc.SOURCE_OPERATOR_DECLARATION, provider_id="alpha",
                                   payload=router_facts(), observed_at_utc=OBSERVED)
        self.assertRejected(adapt(declared), qo.SOURCE_NOT_ADAPTABLE)
        scraped = dataclasses.replace(router_record(), source="SCREEN_SCRAPE")
        self.assertRejected(adapt(scraped), qo.SOURCE_UNKNOWN)

    def test_payload_must_be_the_exact_native_type(self):
        swapped = qo.SourceRecord(evidence_id="ev-x", source=qc.SOURCE_SCHEDULER_CAPACITY_FACTS,
                                  provider_id="alpha", payload=router_facts())
        self.assertRejected(adapt(swapped), qo.PAYLOAD_NOT_TYPED)
        for payload in ({"availability": "NONE"}, "provider is fine", runner_hold().provider_wait, None):
            self.assertRejected(adapt(dataclasses.replace(router_record(), payload=payload)), qo.PAYLOAD_NOT_TYPED)

        class FakeFacts(rt.ProviderFacts):
            pass

        self.assertRejected(adapt(dataclasses.replace(router_record(), payload=FakeFacts(**dataclasses.asdict(
            router_facts())))), qo.PAYLOAD_NOT_TYPED)

    def test_identifiers_are_bounded_secret_free_and_unique(self):
        self.assertRejected(adapt(router_record(evidence_id="EV 1")), qo.EVIDENCE_ID_INVALID)
        self.assertRejected(adapt(router_record(evidence_id="ev" + "x" * 40)), qo.EVIDENCE_ID_SECRET_SHAPED)
        snapshot = adapt(router_record(evidence_id="ev-1"), capacity_record(evidence_id="ev-1"))
        self.assertEqual([r.status for r in snapshot.records], [qo.REJECTED, qo.REJECTED])
        self.assertTrue(all(qo.EVIDENCE_ID_DUPLICATE in r.reasons for r in snapshot.records))
        self.assertEqual(snapshot.observations, ())

    def test_untyped_records_never_raise_and_are_unattributed(self):
        garbage = (None, {"evidence_id": "ev"}, "ev", 3, object(), router_facts())
        snapshot = adapt(router_record(), *garbage)
        self.assertEqual(snapshot.outcome, qo.UNKNOWN)
        self.assertIn(qo.EVIDENCE_UNATTRIBUTED, snapshot.snapshot_reasons)
        for record in snapshot.records[1:]:
            self.assertEqual((record.reasons, record.provider_id), ((qo.RECORD_NOT_TYPED,), None))
        view = self.view(snapshot)
        self.assertEqual((view.availability, view.capacity), ("UNKNOWN", "UNKNOWN"))
        self.assertIn(qo.EVIDENCE_REJECTED, view.reasons)


# ---------------------------------------------------------------------------
# Freshness and aggregation
# ---------------------------------------------------------------------------
class AggregationTests(ObservationTestBase):
    def test_stale_positive_claims_become_unknown_but_stale_holds_stay(self):
        old = "2026-10-31T10:00:00Z"
        stale_ok = adapt(router_record(observed=old), capacity_record(capacity_facts(observed=old)))
        view = self.view(stale_ok)
        self.assertEqual((view.availability, view.capacity, view.freshness), ("UNKNOWN", "UNKNOWN", qo.STALE))
        self.assertIn(qo.EVIDENCE_STALE, view.reasons)
        self.assertEqual(stale_ok.records[0].age_seconds, 7200)
        stale_hold = self.view(adapt(router_record(router_facts(availability_state="QUOTA_WAIT", capacity="FULL"),
                                                   observed=old)))
        self.assertEqual((stale_hold.availability, stale_hold.capacity), ("QUOTA_WAIT", "FULL"))
        self.assertIn(qo.EVIDENCE_STALE, stale_hold.reasons)
        self.assertEqual(adapt(router_record(observed=old), max_evidence_age_seconds=7200).outcome, qo.OBSERVED)

    def test_future_dated_evidence_has_no_age_and_is_unknown(self):
        snapshot = adapt(router_record(observed="2026-10-31T12:00:01Z"), capacity_record())
        record = snapshot.records[0]
        self.assertEqual((record.freshness, record.age_seconds), (qo.FROM_FUTURE, None))
        view = self.view(snapshot)
        self.assertEqual((view.availability, view.freshness, snapshot.outcome),
                         ("UNKNOWN", qo.FROM_FUTURE, qo.UNKNOWN))

    def test_disagreeing_sources_keep_the_most_restrictive_hold(self):
        snapshot = adapt(wait_record(), router_record(), capacity_record())
        view = self.view(snapshot)
        self.assertEqual((view.availability, view.certainty), ("QUOTA_WAIT", qo.UNCERTAIN))
        self.assertIn(qo.EVIDENCE_CONTRADICTORY, view.reasons)
        self.assertEqual(view.capacity, "UNKNOWN")
        both = self.view(adapt(wait_record(), condition_record(AUTH_MESSAGE)))
        self.assertEqual((both.availability, both.next_eligible_utc), ("AUTH_BLOCKED", None))
        self.assertIn(qo.EVIDENCE_CONTRADICTORY, both.reasons)

    def test_available_and_full_disagree_into_full(self):
        view = self.view(adapt(router_record(router_facts(capacity="FULL")), capacity_record()))
        self.assertEqual(view.capacity, "FULL")
        self.assertIn(qo.EVIDENCE_CONTRADICTORY, view.reasons)
        self.assertIn(qo.CAPACITY_FULL, view.reasons)

    def test_a_rejected_record_taints_only_its_provider(self):
        snapshot = adapt(router_record(), capacity_record(),
                         router_record(router_facts("beta", capacity="LOTS"), evidence_id="ev-b", provider="beta"),
                         router_record(router_facts("gamma"), evidence_id="ev-g", provider="gamma"),
                         capacity_record(capacity_facts("gamma"), evidence_id="ev-g2", provider="gamma"))
        self.assertEqual(self.view(snapshot).certainty, qo.CERTAIN)
        self.assertEqual(self.view(snapshot, "gamma").certainty, qo.CERTAIN)
        beta = self.view(snapshot, "beta")
        self.assertEqual((beta.availability, beta.evidence_ids), ("UNKNOWN", ("ev-b",)))
        self.assertIn(qo.EVIDENCE_REJECTED, beta.reasons)
        self.assertEqual(snapshot.outcome, qo.UNKNOWN)

    def test_latest_runner_eligibility_wins_and_only_on_quota_wait(self):
        early = adapt(wait_record(runner_hold(QUOTA_MESSAGE), evidence_id="ev-a"),
                      wait_record(evidence_id="ev-b"))
        view = self.view(early)
        self.assertEqual((view.next_eligible_utc, view.eligibility_source),
                         ("2026-10-31T15:01:00Z", qc.ELIGIBILITY_RESET_HINT))
        self.assertEqual(view.conditions, (QUOTA,))
        auth = self.view(adapt(wait_record(), wait_record(runner_hold(AUTH_MESSAGE), evidence_id="ev-c")))
        self.assertEqual((auth.availability, auth.next_eligible_utc, auth.eligibility_source),
                         ("AUTH_BLOCKED", None, None))

    def test_providers_are_isolated_and_sorted(self):
        snapshot = adapt(condition_record(AUTH_MESSAGE, provider="zeta"), router_record(), capacity_record(),
                         provider_ids=("mu",))
        self.assertEqual([p.provider_id for p in snapshot.providers], ["alpha", "mu", "zeta"])
        self.assertEqual(self.view(snapshot).availability, "NONE")
        self.assertEqual(self.view(snapshot, "zeta").availability, "AUTH_BLOCKED")
        self.assertIn(qo.NO_EVIDENCE, self.view(snapshot, "mu").reasons)


# ---------------------------------------------------------------------------
# Contract integration and output invariants
# ---------------------------------------------------------------------------
class OutputTests(ObservationTestBase):
    def test_adapted_observations_are_valid_contract_evidence(self):
        snapshot = adapt(wait_record(), condition_record(AUTH_MESSAGE, provider="beta"),
                         router_record(router_facts("gamma"), evidence_id="ev-g", provider="gamma"),
                         capacity_record(capacity_facts("gamma"), evidence_id="ev-g2", provider="gamma"))
        observations = snapshot.observations
        self.assertEqual([o.evidence_id for o in observations], sorted(o.evidence_id for o in observations))
        for obs in observations:
            self.assertEqual(qc._observation_reasons(obs), set())
            self.assertEqual(obs.reliability, qc.SOURCE_MAX_RELIABILITY[obs.source])
            self.assertEqual((obs.resource_id, obs.usage_unit, obs.usage_amount), (None, None, None))
        quota_request = qc.QuotaRequest(
            request_id="req-1", as_of_utc=AS_OF,
            policy=qc.QuotaPolicy(policy_id="pol-1", limits=(qc.QuotaLimit(
                limit_id="lim-1", scope=qc.SCOPE_GLOBAL, unit=qc.UNIT_CONCURRENT_EXECUTIONS, maximum=2),)),
            reservation=qc.AdvisoryReservation(reservation_id="res-1", provider_id="alpha",
                                               amounts=((qc.UNIT_CONCURRENT_EXECUTIONS, 1),)),
            observations=observations)
        self.assertEqual(qc.validate_request(quota_request), ())

    def test_snapshot_rederives_everything_it_claims(self):
        snapshot = adapt(wait_record(), router_record())
        self.assertEqual(snapshot.outcome, qo.UNKNOWN)
        with self.assertRaises(ValueError):
            dataclasses.replace(snapshot, outcome=qo.OBSERVED)
        with self.assertRaises(ValueError):
            dataclasses.replace(snapshot, snapshot_fingerprint="0" * 64)
        cleared = dataclasses.replace(self.view(snapshot), availability="NONE",
                                      reasons=(qo.CAPACITY_UNKNOWN,), certainty=qo.UNCERTAIN,
                                      next_eligible_utc=None, eligibility_source=None)
        with self.assertRaises(ValueError):
            dataclasses.replace(snapshot, providers=(cleared,))
        with self.assertRaises(ValueError):
            dataclasses.replace(snapshot, records=snapshot.records[:1])

    def test_views_and_records_refuse_overclaims(self):
        with self.assertRaises(ValueError):
            qo.ProviderQuotaView(provider_id="alpha", availability="NONE", capacity="AVAILABLE",
                                 certainty=qo.CERTAIN, reasons=(qo.EVIDENCE_STALE,), evidence_ids=("ev-1",))
        with self.assertRaises(ValueError):
            qo.ProviderQuotaView(provider_id="alpha", availability="QUOTA_WAIT", capacity="AVAILABLE",
                                 certainty=qo.CERTAIN, reasons=(), evidence_ids=("ev-1",))
        with self.assertRaises(ValueError):
            qo.ProviderQuotaView(provider_id="alpha", availability="NONE", capacity="AVAILABLE",
                                 certainty=qo.CERTAIN, reasons=(), evidence_ids=("ev-1",),
                                 next_eligible_utc="2026-10-31T13:00:00Z",
                                 eligibility_source=qc.ELIGIBILITY_RESET_HINT)
        adapted = adapt(router_record()).records[0]
        with self.assertRaises(ValueError):
            dataclasses.replace(adapted, status=qo.REJECTED, reasons=(qo.PAYLOAD_MALFORMED,), certainty=qo.UNCERTAIN)
        with self.assertRaises(ValueError):
            dataclasses.replace(adapted, freshness=qo.STALE)
        with self.assertRaises(ValueError):
            dataclasses.replace(adapted, observation=dataclasses.replace(
                adapted.observation, reliability=qc.RELIABILITY_RUNNER_CLASSIFIED))

    def test_every_authority_flag_is_false_by_construction(self):
        for snapshot in (adapt(router_record(), capacity_record()), adapt(), qo.adapt_observations(None)):
            data = json.loads(qo.canonical_json(snapshot))
            self.assertEqual(data["marker"], qo.OBSERVATION_MARKER)
            for flag in ALL_FLAGS:
                self.assertIs(getattr(snapshot, flag), False, flag)
                self.assertIs(data[flag], False, flag)
                self.assertNotIn(flag, {f.name for f in dataclasses.fields(snapshot)})
                with self.assertRaises(AttributeError):
                    setattr(snapshot, flag, True)

    def test_canonical_json_is_exact_type_deterministic_and_bounded(self):
        records = (wait_record(), router_record(router_facts("beta"), evidence_id="ev-b", provider="beta"))
        first, second = adapt(*records), adapt(*copy.deepcopy(records))
        self.assertEqual(qo.canonical_json(first), qo.canonical_json(second))
        self.assertEqual(first.snapshot_fingerprint, second.snapshot_fingerprint)
        self.assertNotEqual(first.snapshot_fingerprint, adapt(*records, as_of_utc="2026-10-31T12:00:01Z")
                            .snapshot_fingerprint)
        self.assertEqual(json.loads(qo.canonical_json(first))["schema"], qo.SCHEMA)
        with self.assertRaises(TypeError):
            qo.canonical_json(first.to_dict())
        offset = adapt(*records, as_of_utc="2026-10-31T12:00:00+00:00")
        self.assertEqual(offset.as_of_utc, AS_OF)
        self.assertEqual(offset.snapshot_fingerprint, first.snapshot_fingerprint)


# ---------------------------------------------------------------------------
# Purity and governance
# ---------------------------------------------------------------------------
class PurityTests(ObservationTestBase):
    def test_adaptation_never_mutates_inputs(self):
        worker = runner_hold()
        req = request(records=(wait_record(worker), router_record(), capacity_record()))
        before, wait_before = copy.deepcopy(req), copy.deepcopy(worker.provider_wait)
        qo.adapt_observations(req)
        self.assertEqual(req, before)
        self.assertEqual(worker.provider_wait, wait_before)
        self.assertEqual(worker.state, rp.WorkerState.WAITING_PROVIDER_QUOTA.value)
        for obj in (req, req.records[0]):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(obj, dataclasses.fields(obj)[0].name, "x")

    def test_no_io_processes_network_clock_or_runner_entry_points(self):
        records = (wait_record(), condition_record(), router_record(), capacity_record())
        boom = AssertionError("I/O or execution entry point")
        with mock.patch.object(subprocess, "Popen", side_effect=boom), \
                mock.patch.object(builtins, "open", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(os, "stat", side_effect=boom), \
                mock.patch.object(os, "replace", side_effect=boom), \
                mock.patch.object(os, "mkdir", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "_hold_for_provider", side_effect=boom), \
                mock.patch.object(rp.DirLease, "try_acquire", side_effect=boom), \
                mock.patch.object(availability, "classify_provider_failure", side_effect=boom), \
                mock.patch.object(availability, "parse_reset_hint", side_effect=boom), \
                mock.patch.object(rt, "propose_route", side_effect=boom), \
                mock.patch.object(cap, "evaluate_capacity", side_effect=boom):
            snapshot = qo.adapt_observations(request(records=records))
            qo.canonical_json(snapshot)
        self.assertEqual(len(snapshot.observations), 4)

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_provider_routing_policy", "fabric_resource_quota_contract", "fabric_scheduler_capacity",
               "fabric_scheduler_contract", "runner_pipeline", "runner_provider_availability")
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner",
                     "DirLease", "lease_dir", "ledger", "_launch", "_start_ready", "_hold_for_provider(",
                     ".now(", "utcnow", "sleep", "while ", "claude", "codex", "eval(", "exec(", "importlib",
                     "random", "requests.", "urllib", "environ", "propose_route", "classify_provider_failure",
                     "parse_reset_hint", "extract_reset_hint", "_QUOTA_RE", "evaluate_capacity(", "re.compile",
                     "price", "cost", "currency", "selenium", "scrape", "cookie", "keyring"):
            self.assertNotIn(word, code, word)
        for prose in ("message_excerpt", "reset_hint", "budget_note"):
            self.assertEqual(code.count(f'"{prose}"'), 1, prose)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_mutable_module_state_changes(self):
        modules = (qo, qc, cap, rt, availability)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        adapt(wait_record(), router_record(), capacity_record(), condition_record())
        qo.adapt_observations(None)
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_reused(self):
        vocabularies = (qo.OUTCOMES, qo.RECORD_STATUSES, qo.CERTAINTIES, qo.FRESHNESS, qo.REQUEST_REASONS,
                        qo.RECORD_REASONS, qo.EVIDENCE_REASONS, qo.SNAPSHOT_REASONS)
        for vocab in vocabularies:
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(qo.REQUEST_REASONS) & set(qo.RECORD_REASONS))
        self.assertFalse(set(qo.RECORD_REASONS) & set(qo.EVIDENCE_REASONS))
        self.assertEqual(len(qo.UNCERTAIN_REASONS) + len(qo.HOLD_REASONS), len(qo.EVIDENCE_REASONS))
        for code in (qo.NO_EVIDENCE, qo.EVIDENCE_STALE, qo.EVIDENCE_FROM_FUTURE, qo.EVIDENCE_CONTRADICTORY,
                     qo.AVAILABILITY_UNKNOWN):
            self.assertIn(code, qc.UNKNOWN_REASONS)
        for code in (qo.AVAILABILITY_AUTH_BLOCKED, qo.AVAILABILITY_QUOTA_WAIT, qo.CAPACITY_FULL, qo.CAPACITY_UNKNOWN):
            self.assertIn(code, rt.PROVIDER_REASONS)
        self.assertEqual(qo.AVAILABILITY_STATES, rt.AVAILABILITY_STATES)
        self.assertEqual(qo.CAPACITY_STATES, rt.CAPACITY_STATES)
        self.assertEqual((qo.MAX_RECORDS, qo.MAX_PROVIDERS), (qc.MAX_OBSERVATIONS, rt.MAX_PROVIDERS))

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
