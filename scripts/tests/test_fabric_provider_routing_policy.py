"""FCP-7A-01: Provider Routing Policy V1 - pure, deterministic, fail-closed,
non-executable provider selection proposal. Offline, synthetic facts only."""

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

from scripts.ai import fabric_provider_routing_policy as rp

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_provider_routing_policy.py"
TEST_PATH = Path(__file__).resolve()

ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "auto_retry_allowed", "resume_allowed",
             "merging_allowed", "provider_switch_authorized")


def facts(pid="claude", *, mode="write", allow_shell=False, available=True, supported=True, caps=None,
          availability="NONE", capacity="AVAILABLE"):
    if caps is None:
        caps = ("READ_FILES", "SEARCH_FILES", "STRUCTURED_RESULT")
        if mode == "write":
            caps += ("EDIT_FILES", "WRITE_FILES")
        if allow_shell:
            caps += ("SHELL", "TEST_EXECUTION")
    return rp.ProviderFacts(provider_id=pid, probe_available=available, policy_mode=mode,
                            policy_allow_shell=allow_shell, policy_supported=supported, capabilities=caps,
                            availability=availability, capacity=capacity)


def codex_facts(*, mode="write", allow_shell=False, **kw):
    """Honest mirror of CodexProvider: refuses (no caps) unless allow_shell."""
    if not allow_shell:
        return facts("codex", mode=mode, allow_shell=False, supported=False, caps=(), **kw)
    caps = ("READ_FILES", "SEARCH_FILES", "SHELL", "TEST_EXECUTION")
    if mode == "write":
        caps += ("EDIT_FILES", "WRITE_FILES")
    return facts("codex", mode=mode, allow_shell=True, caps=caps, **kw)


def request(mode="write", **kw):
    kw.setdefault("preference_order", ("claude", "codex"))
    return rp.RoutingRequest(mode=mode, **kw)


def assessment(advisory, pid):
    return next(a for a in advisory.assessments if a.provider_id == pid)


# ---------------------------------------------------------------------------
class SelectionTests(unittest.TestCase):
    def test_first_eligible_in_caller_order_is_proposed(self):
        adv = rp.propose_route(request(), (facts(), codex_facts()))
        self.assertEqual(adv.selected_provider, "claude")
        self.assertEqual(adv.rationale, rp.SELECTED_FIRST_ELIGIBLE_PREFERENCE)

    def test_caller_order_not_snapshot_order_decides(self):
        snapshot = (facts("alpha"), facts("beta"))
        adv = rp.propose_route(request(preference_order=("beta", "alpha")), snapshot)
        self.assertEqual(adv.selected_provider, "beta")
        adv = rp.propose_route(request(preference_order=("alpha", "beta")), tuple(reversed(snapshot)))
        self.assertEqual(adv.selected_provider, "alpha")

    def test_second_preference_used_only_when_first_ineligible_before_execution(self):
        adv = rp.propose_route(request(preference_order=("alpha", "beta")),
                               (facts("alpha", available=False), facts("beta")))
        self.assertEqual(adv.selected_provider, "beta")
        self.assertEqual(assessment(adv, "alpha").reasons[0], rp.PROBE_UNAVAILABLE)

    def test_all_candidates_assessed_even_after_a_selection(self):
        adv = rp.propose_route(request(preference_order=("alpha", "beta", "gamma")),
                               (facts("alpha"), facts("beta"), facts("gamma", capacity="FULL")))
        self.assertEqual([a.provider_id for a in adv.assessments], ["alpha", "beta", "gamma"])
        self.assertEqual([a.eligible for a in adv.assessments], [True, True, False])
        self.assertEqual(assessment(adv, "gamma").reasons, (rp.CAPACITY_FULL,))

    def test_preference_rank_reported(self):
        adv = rp.propose_route(request(preference_order=("alpha", "beta")), (facts("alpha"), facts("beta")))
        self.assertEqual([a.preference_rank for a in adv.assessments], [0, 1])

    def test_all_excluded_yields_no_candidate(self):
        adv = rp.propose_route(request(), (facts(available=False), codex_facts()))
        self.assertIsNone(adv.selected_provider)
        self.assertEqual(adv.rationale, rp.REFUSED_NO_ELIGIBLE_PROVIDER)
        self.assertEqual({pid for pid, _ in adv.rejections()}, {"claude", "codex"})

    def test_empty_snapshot_excludes_every_preference_with_no_facts(self):
        adv = rp.propose_route(request(), ())
        self.assertIsNone(adv.selected_provider)
        self.assertEqual([a.reasons for a in adv.assessments], [(rp.NO_FACTS,), (rp.NO_FACTS,)])


class RequestValidationTests(unittest.TestCase):
    def assertRefused(self, req, code):
        adv = rp.propose_route(req, (facts(), codex_facts()))
        self.assertEqual(adv.rationale, rp.REFUSED_INVALID_REQUEST)
        self.assertIn(code, adv.request_reasons)
        self.assertIsNone(adv.selected_provider)
        self.assertEqual(adv.assessments, ())
        return adv

    def test_untyped_request_refused(self):
        for bad in (None, {"mode": "write"}, ("write",), "write"):
            self.assertRefused(bad, rp.REQUEST_NOT_TYPED)

    def test_request_subclass_refused(self):
        class Sub(rp.RoutingRequest):
            pass
        self.assertRefused(Sub(mode="write", preference_order=("claude",)), rp.REQUEST_NOT_TYPED)

    def test_unknown_mode_refused(self):
        for mode in ("WRITE", "readonly", "", None, 1, "full-access"):
            self.assertRefused(request(mode=mode), rp.MODE_UNKNOWN)

    def test_allow_shell_must_be_real_bool(self):
        for value in (1, "true", None, 0):
            self.assertRefused(request(allow_shell=value), rp.ALLOW_SHELL_NOT_BOOL)

    def test_allow_shell_in_read_only_refused_like_runner_guard(self):
        self.assertRefused(request(mode="read-only", allow_shell=True), rp.ALLOW_SHELL_REQUIRES_WRITE_MODE)

    def test_unknown_capability_refused(self):
        for cap in ("NETWORK", "shell", "read_files", "", "READ_FILES "):
            self.assertRefused(request(required_capabilities=(cap,)), rp.CAPABILITY_UNKNOWN)

    def test_duplicate_capability_refused(self):
        self.assertRefused(request(required_capabilities=("STRUCTURED_RESULT", "STRUCTURED_RESULT")),
                           rp.CAPABILITY_DUPLICATE)

    def test_capabilities_must_be_tuple_of_str(self):
        for bad in (["READ_FILES"], "READ_FILES", (1,), None, {"READ_FILES"}):
            self.assertRefused(request(required_capabilities=bad), rp.CAPABILITIES_MALFORMED)

    def test_shell_capability_never_infers_allow_shell(self):
        self.assertRefused(request(required_capabilities=("SHELL",)), rp.SHELL_REQUESTED_WITHOUT_ALLOW_SHELL)

    def test_empty_preference_without_pin_refused_no_fabricated_priority(self):
        adv = self.assertRefused(request(preference_order=()), rp.PREFERENCE_EMPTY)
        self.assertEqual(adv.preference_order, ())

    def test_duplicate_preference_refused(self):
        self.assertRefused(request(preference_order=("claude", "codex", "claude")), rp.PREFERENCE_DUPLICATE)

    def test_malformed_preference_refused(self):
        for bad in (["claude"], "claude", None, (1,)):
            self.assertRefused(request(preference_order=bad), rp.PREFERENCE_MALFORMED)

    def test_invalid_provider_ids_refused(self):
        for bad in ("Claude", "", " claude", "claude\n", "a" * 33, "../x", "claude;rm", "1abc"):
            self.assertRefused(request(preference_order=(bad,)), rp.PREFERENCE_PROVIDER_ID_INVALID)

    def test_preference_bounded(self):
        order = tuple(f"p{i}" for i in range(rp.MAX_PROVIDERS + 1))
        self.assertRefused(request(preference_order=order), rp.PREFERENCE_TOO_LONG)

    def test_invalid_pin_refused(self):
        for bad in ("CLAUDE", "", 3):
            self.assertRefused(request(pinned_provider=bad), rp.PIN_INVALID)

    def test_pin_outside_preference_refused(self):
        self.assertRefused(request(preference_order=("claude",), pinned_provider="codex"), rp.PIN_NOT_IN_PREFERENCE)

    def test_lock_flags_must_be_bool(self):
        self.assertRefused(request(pinned_provider="claude", prior_attempt_executed=1), rp.LOCK_FLAGS_MALFORMED)
        self.assertRefused(request(pinned_provider="claude", provider_locked="yes"), rp.LOCK_FLAGS_MALFORMED)

    def test_prior_attempt_without_known_pin_fails_closed(self):
        self.assertRefused(request(prior_attempt_executed=True), rp.LOCKED_WITHOUT_PIN)
        self.assertRefused(request(provider_locked=True), rp.LOCKED_WITHOUT_PIN)

    def test_all_request_reasons_reported_in_stable_order(self):
        adv = rp.propose_route(request(mode="x", allow_shell=1, preference_order=("A", "A")), ())
        self.assertEqual(adv.request_reasons, (rp.MODE_UNKNOWN, rp.ALLOW_SHELL_NOT_BOOL, rp.PREFERENCE_DUPLICATE,
                                               rp.PREFERENCE_PROVIDER_ID_INVALID))


class CapabilityTests(unittest.TestCase):
    def test_read_only_requires_exactly_read_and_search(self):
        adv = rp.propose_route(request(mode="read-only"), (facts(mode="read-only"),))
        self.assertEqual(adv.required_capabilities, ("READ_FILES", "SEARCH_FILES"))
        self.assertEqual(adv.selected_provider, "claude")

    def test_write_mode_adds_edit_and_write(self):
        adv = rp.propose_route(request(), (facts(),))
        self.assertEqual(adv.required_capabilities, ("EDIT_FILES", "READ_FILES", "SEARCH_FILES", "WRITE_FILES"))

    def test_write_mode_rejects_provider_without_write_caps(self):
        adv = rp.propose_route(request(), (facts(caps=("READ_FILES", "SEARCH_FILES")),))
        self.assertIsNone(adv.selected_provider)
        self.assertEqual(assessment(adv, "claude").missing_capabilities, ("EDIT_FILES", "WRITE_FILES"))
        self.assertIn(rp.CAPABILITY_MISSING, assessment(adv, "claude").reasons)

    def test_explicit_optional_capability_only_when_requested(self):
        lean = facts(caps=("READ_FILES", "SEARCH_FILES", "EDIT_FILES", "WRITE_FILES"))
        self.assertEqual(rp.propose_route(request(), (lean,)).selected_provider, "claude")
        adv = rp.propose_route(request(required_capabilities=("STRUCTURED_RESULT",)), (lean,))
        self.assertIsNone(adv.selected_provider)
        self.assertEqual(assessment(adv, "claude").missing_capabilities, ("STRUCTURED_RESULT",))

    def test_test_execution_requires_attested_capability(self):
        adv = rp.propose_route(request(required_capabilities=("TEST_EXECUTION",)), (facts(),))
        self.assertIsNone(adv.selected_provider)
        adv = rp.propose_route(request(allow_shell=True, required_capabilities=("TEST_EXECUTION", "SHELL")),
                               (facts(allow_shell=True),))
        self.assertEqual(adv.selected_provider, "claude")

    def test_unknown_capability_in_facts_excluded(self):
        adv = rp.propose_route(request(), (facts(caps=("READ_FILES", "SEARCH_FILES", "EDIT_FILES", "WRITE_FILES",
                                                       "TELEPORT")),))
        self.assertEqual(assessment(adv, "claude").reasons, (rp.FACTS_UNKNOWN_CAPABILITY,))
        self.assertNotIn("TELEPORT", rp.canonical_json(adv))

    def test_capabilities_never_invented_for_known_providers(self):
        adv = rp.propose_route(request(), (facts("claude", caps=()), facts("codex", allow_shell=False, caps=())))
        self.assertIsNone(adv.selected_provider)
        for a in adv.assessments:
            self.assertIn(rp.CAPABILITY_MISSING, a.reasons)

    def test_unavailable_probe_provides_nothing(self):
        adv = rp.propose_route(request(), (facts(available=False),))
        a = assessment(adv, "claude")
        self.assertEqual(a.reasons, (rp.PROBE_UNAVAILABLE, rp.CAPABILITY_MISSING))
        self.assertEqual(a.missing_capabilities, adv.required_capabilities)


class ShellAndPolicyTests(unittest.TestCase):
    def test_codex_not_recommendable_without_allow_shell(self):
        adv = rp.propose_route(request(preference_order=("codex", "claude")), (codex_facts(), facts()))
        self.assertEqual(adv.selected_provider, "claude")
        self.assertEqual(assessment(adv, "codex").reasons,
                         (rp.POLICY_REFUSED, rp.ADAPTER_REQUIRES_SHELL, rp.CAPABILITY_MISSING))

    def test_codex_excluded_without_allow_shell_even_if_facts_claim_support(self):
        lying = facts("codex", caps=("READ_FILES", "SEARCH_FILES", "EDIT_FILES", "WRITE_FILES"))
        adv = rp.propose_route(request(preference_order=("codex",)), (lying,))
        self.assertIsNone(adv.selected_provider)
        self.assertIn(rp.ADAPTER_REQUIRES_SHELL, assessment(adv, "codex").reasons)

    def test_codex_eligible_with_explicit_allow_shell_in_write_mode(self):
        adv = rp.propose_route(request(allow_shell=True, preference_order=("codex", "claude")),
                               (codex_facts(allow_shell=True), facts(allow_shell=True)))
        self.assertEqual(adv.selected_provider, "codex")

    def test_policy_refusal_blocks_recommendation(self):
        adv = rp.propose_route(request(preference_order=("alpha",)), (facts("alpha", supported=False, caps=()),))
        self.assertIsNone(adv.selected_provider)
        self.assertIn(rp.POLICY_REFUSED, assessment(adv, "alpha").reasons)

    def test_refused_policy_with_capabilities_is_inconsistent(self):
        adv = rp.propose_route(request(preference_order=("alpha",)), (facts("alpha", supported=False),))
        self.assertIn(rp.FACTS_INCONSISTENT, assessment(adv, "alpha").reasons)

    def test_shell_capability_without_allow_shell_is_inconsistent(self):
        f = facts(caps=("READ_FILES", "SEARCH_FILES", "EDIT_FILES", "WRITE_FILES", "SHELL"))
        adv = rp.propose_route(request(), (f,))
        self.assertIsNone(adv.selected_provider)
        self.assertIn(rp.FACTS_INCONSISTENT, assessment(adv, "claude").reasons)

    def test_read_only_facts_reporting_write_caps_inconsistent(self):
        f = facts(mode="read-only", caps=("READ_FILES", "SEARCH_FILES", "WRITE_FILES"))
        adv = rp.propose_route(request(mode="read-only"), (f,))
        self.assertIn(rp.FACTS_INCONSISTENT, assessment(adv, "claude").reasons)

    def test_facts_observed_under_another_policy_excluded(self):
        for f in (facts(mode="read-only"), facts(allow_shell=True)):
            adv = rp.propose_route(request(), (f,))
            self.assertIsNone(adv.selected_provider)
            self.assertIn(rp.FACTS_POLICY_MISMATCH, assessment(adv, "claude").reasons)


class AvailabilityTests(unittest.TestCase):
    def test_quota_auth_unknown_availability_block(self):
        for state, code in (("QUOTA_WAIT", rp.AVAILABILITY_QUOTA_WAIT), ("AUTH_BLOCKED", rp.AVAILABILITY_AUTH_BLOCKED),
                            ("UNKNOWN", rp.AVAILABILITY_UNKNOWN)):
            adv = rp.propose_route(request(preference_order=("claude",)), (facts(availability=state),))
            self.assertIsNone(adv.selected_provider, state)
            self.assertEqual(assessment(adv, "claude").reasons, (code,))

    def test_capacity_full_and_unknown_block(self):
        for state, code in (("FULL", rp.CAPACITY_FULL), ("UNKNOWN", rp.CAPACITY_UNKNOWN)):
            adv = rp.propose_route(request(preference_order=("claude",)), (facts(capacity=state),))
            self.assertEqual(assessment(adv, "claude").reasons, (code,))

    def test_unrecognized_states_are_malformed_not_optimistic(self):
        for kw in ({"availability": "OK"}, {"capacity": "PLENTY"}, {"availability": None}, {"capacity": "available"}):
            adv = rp.propose_route(request(preference_order=("claude",)), (facts(**kw),))
            self.assertEqual(assessment(adv, "claude").reasons, (rp.FACTS_MALFORMED,), kw)

    def test_non_bool_fact_flags_malformed(self):
        for kw in ({"available": 1}, {"supported": "yes"}, {"allow_shell": 0}):
            adv = rp.propose_route(request(preference_order=("claude",)), (facts(**kw),))
            self.assertEqual(assessment(adv, "claude").reasons, (rp.FACTS_MALFORMED,), kw)

    def test_fact_capabilities_list_or_duplicates_malformed(self):
        for caps in (["READ_FILES"], ("READ_FILES", "READ_FILES")):
            adv = rp.propose_route(request(preference_order=("claude",)), (facts(caps=caps),))
            self.assertEqual(assessment(adv, "claude").reasons, (rp.FACTS_MALFORMED,))


class PinAndLockTests(unittest.TestCase):
    def test_hard_pin_selects_only_pin(self):
        adv = rp.propose_route(request(pinned_provider="codex", allow_shell=True),
                               (facts(allow_shell=True), codex_facts(allow_shell=True)))
        self.assertEqual(adv.selected_provider, "codex")
        self.assertEqual(adv.rationale, rp.SELECTED_PINNED_PROVIDER)
        self.assertEqual(assessment(adv, "claude").reasons, (rp.NOT_PINNED,))

    def test_ineligible_pin_never_substituted(self):
        adv = rp.propose_route(request(pinned_provider="claude"), (facts(availability="QUOTA_WAIT"), facts("codex")))
        self.assertIsNone(adv.selected_provider)
        self.assertEqual(adv.rationale, rp.REFUSED_PINNED_PROVIDER_INELIGIBLE)

    def test_pin_without_preference_order(self):
        adv = rp.propose_route(rp.RoutingRequest(mode="write", pinned_provider="claude"), (facts(),))
        self.assertEqual(adv.selected_provider, "claude")
        self.assertIsNone(assessment(adv, "claude").preference_rank)

    def test_pin_with_missing_facts_refused(self):
        adv = rp.propose_route(rp.RoutingRequest(mode="write", pinned_provider="claude"), (facts("codex"),))
        self.assertIsNone(adv.selected_provider)
        self.assertEqual(assessment(adv, "claude").reasons, (rp.NO_FACTS,))

    def test_post_attempt_lock_never_proposes_other_provider(self):
        for flags in ({"prior_attempt_executed": True}, {"provider_locked": True},
                      {"prior_attempt_executed": True, "provider_locked": True}):
            adv = rp.propose_route(request(pinned_provider="claude", preference_order=("claude", "beta"), **flags),
                                   (facts(availability="QUOTA_WAIT"), facts("beta")))
            self.assertIsNone(adv.selected_provider, flags)
            self.assertEqual(adv.rationale, rp.REFUSED_LOCKED_PROVIDER_INELIGIBLE)
            self.assertEqual(assessment(adv, "beta").reasons, (rp.PROVIDER_LOCKED_TO_OTHER,))

    def test_no_switch_to_evade_auth_after_attempt(self):
        adv = rp.propose_route(request(pinned_provider="claude", prior_attempt_executed=True),
                               (facts(availability="AUTH_BLOCKED"), facts("codex", allow_shell=False)))
        self.assertIsNone(adv.selected_provider)
        self.assertFalse(adv.provider_switch_authorized)

    def test_locked_eligible_provider_selected_as_locked(self):
        adv = rp.propose_route(request(pinned_provider="claude", provider_locked=True), (facts(), facts("codex")))
        self.assertEqual(adv.selected_provider, "claude")
        self.assertEqual(adv.rationale, rp.SELECTED_LOCKED_PROVIDER)


class SnapshotTests(unittest.TestCase):
    def test_duplicate_facts_excluded_both_orders(self):
        for snapshot in ((facts(), facts(capacity="FULL"), facts("beta")),
                         (facts("beta"), facts(capacity="FULL"), facts())):
            adv = rp.propose_route(request(preference_order=("claude", "beta")), snapshot)
            self.assertEqual(assessment(adv, "claude").reasons, (rp.DUPLICATE_FACTS,))
            self.assertEqual(adv.selected_provider, "beta")

    def test_identical_duplicate_facts_still_excluded(self):
        adv = rp.propose_route(request(preference_order=("claude",)), (facts(), facts()))
        self.assertIsNone(adv.selected_provider)

    def test_unlisted_snapshot_provider_never_selected(self):
        adv = rp.propose_route(request(preference_order=("claude",)), (facts(available=False), facts("zeta")))
        self.assertIsNone(adv.selected_provider)
        self.assertEqual(assessment(adv, "zeta").reasons, (rp.NOT_IN_PREFERENCE_ORDER,))
        self.assertEqual([a.provider_id for a in adv.assessments], ["claude", "zeta"])

    def test_malformed_snapshot_refused_entirely(self):
        for snapshot, code in (([facts()], rp.SNAPSHOT_NOT_TUPLE), (None, rp.SNAPSHOT_NOT_TUPLE),
                               ((facts(), {"provider_id": "codex"}), rp.SNAPSHOT_ENTRY_NOT_TYPED),
                               ((facts("Codex"),), rp.SNAPSHOT_PROVIDER_ID_INVALID),
                               (tuple(facts(f"p{i}") for i in range(rp.MAX_PROVIDERS + 1)), rp.SNAPSHOT_TOO_LARGE)):
            adv = rp.propose_route(request(), snapshot)
            self.assertEqual(adv.rationale, rp.REFUSED_INVALID_SNAPSHOT)
            self.assertIn(code, adv.snapshot_reasons)
            self.assertIsNone(adv.selected_provider)
            self.assertEqual(adv.assessments, ())

    def test_facts_subclass_refused(self):
        class Sub(rp.ProviderFacts):
            pass
        adv = rp.propose_route(request(), (Sub(*dataclasses.astuple(facts())),))
        self.assertEqual(adv.snapshot_reasons, (rp.SNAPSHOT_ENTRY_NOT_TYPED,))


class OutputContractTests(unittest.TestCase):
    def setUp(self):
        self.adv = rp.propose_route(request(), (facts(), codex_facts()))

    def test_flags_constant_false_everywhere(self):
        for adv in (self.adv, rp.propose_route(None, ()), rp.propose_route(request(), None)):
            data = adv.to_dict()
            for flag in ALL_FLAGS:
                self.assertIs(getattr(adv, flag), False, flag)
                self.assertIs(data[flag], False, flag)
            self.assertEqual(data["marker"], rp.ROUTING_MARKER)

    def test_flags_not_constructible_or_replaceable(self):
        fields = {f.name for f in dataclasses.fields(rp.RoutingAdvisory)}
        for flag in ALL_FLAGS:
            self.assertNotIn(flag, fields)
            with self.assertRaises(TypeError):
                dataclasses.replace(self.adv, **{flag: True})
            with self.assertRaises(AttributeError):
                setattr(self.adv, flag, True)
            with self.assertRaises(AttributeError):
                object.__setattr__(self.adv, flag, True)

    def test_advisory_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.adv.selected_provider = "codex"

    def test_hand_made_selection_of_ineligible_provider_rejected(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(self.adv, selected_provider="codex")
        with self.assertRaises(ValueError):
            dataclasses.replace(self.adv, rationale=rp.REFUSED_NO_ELIGIBLE_PROVIDER)
        with self.assertRaises(ValueError):
            dataclasses.replace(self.adv, rationale="DISPATCH_NOW")
        with self.assertRaises(ValueError):
            rp.ProviderAssessment("codex", 0, True, (rp.POLICY_REFUSED,), ())

    def test_hand_made_pinned_substitution_rejected(self):
        adv = rp.propose_route(request(pinned_provider="claude"), (facts(), facts("codex")))
        with self.assertRaises(ValueError):
            dataclasses.replace(adv, selected_provider="codex")

    def test_schema_and_key_set_stable(self):
        data = self.adv.to_dict()
        self.assertEqual(data["schema"], "fcp7a01-provider-routing-advisory-v1")
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(set(data), {
            "schema", "schema_version", "rationale", "selected_provider", "request", "request_reasons",
            "snapshot_reasons", "assessments", "rejections", "marker", *ALL_FLAGS})
        self.assertEqual(set(data["assessments"][0]),
                         {"provider_id", "preference_rank", "eligible", "reasons", "missing_capabilities"})

    def test_rejections_sorted_by_provider_id(self):
        adv = rp.propose_route(request(preference_order=("zeta", "alpha", "mid")),
                               (facts("zeta", capacity="FULL"), facts("alpha", capacity="FULL"),
                                facts("mid", capacity="FULL")))
        self.assertEqual([r["provider_id"] for r in adv.to_dict()["rejections"]], ["alpha", "mid", "zeta"])
        self.assertEqual([a.provider_id for a in adv.assessments], ["zeta", "alpha", "mid"])

    def test_same_inputs_byte_identical_output(self):
        def build():
            return rp.canonical_json(rp.propose_route(request(), (facts(), codex_facts(), facts("zeta"))))
        first = build()
        self.assertEqual(first, build())
        self.assertEqual(json.loads(first), self.adv_dict_for_zeta())
        permuted = rp.canonical_json(rp.propose_route(request(), (facts("zeta"), codex_facts(), facts())))
        self.assertEqual(first, permuted)

    def adv_dict_for_zeta(self):
        return rp.propose_route(request(), (facts(), codex_facts(), facts("zeta"))).to_dict()

    def test_canonical_json_is_compact_sorted_ascii(self):
        text = rp.canonical_json(self.adv)
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=True))

    def test_no_price_latency_or_score_inputs_or_outputs(self):
        forbidden = ("cost", "price", "latency", "quality", "score", "model", "weight", "speed")
        names = {f.name for cls in (rp.RoutingRequest, rp.ProviderFacts) for f in dataclasses.fields(cls)}
        for word in forbidden:
            self.assertFalse([n for n in names if word in n], word)
            self.assertNotIn(word, rp.canonical_json(self.adv).lower())
        with self.assertRaises(TypeError):
            rp.RoutingRequest(mode="write", preference_order=("claude",), cost_weight=1)
        with self.assertRaises(TypeError):
            rp.ProviderFacts("claude", True, "write", False, True, (), "NONE", "AVAILABLE", 0.1)

    def test_selected_output_is_informational_only(self):
        self.assertEqual(self.adv.selected_provider, "claude")
        self.assertFalse(self.adv.execution_allowed or self.adv.authorizes_action or self.adv.certified)
        methods = {n for n in dir(self.adv) if not n.startswith("_") and callable(getattr(self.adv, n))}
        self.assertEqual(methods, {"to_dict", "rejections"})


class PurityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        req = request(required_capabilities=("STRUCTURED_RESULT",))
        snapshot = (facts(), codex_facts(), facts("zeta"))
        before = (copy.deepcopy(req), copy.deepcopy(snapshot))
        rp.propose_route(req, snapshot)
        self.assertEqual((req, snapshot), before)

    def test_inputs_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request().mode = "read-only"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            facts().availability = "NONE"

    def test_no_io_process_or_network(self):
        def boom(*a, **k):
            raise AssertionError("I/O attempted")
        patches = [mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom),
                   mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom),
                   mock.patch.object(os, "listdir", boom), mock.patch.object(os, "scandir", boom),
                   mock.patch.object(os, "stat", boom), mock.patch.object(os, "system", boom)]
        for p in patches:
            p.start()
        try:
            for req, snap in ((request(), (facts(), codex_facts())), (None, None), (request(pinned_provider="x"), ())):
                rp.canonical_json(rp.propose_route(req, snap))
        finally:
            for p in reversed(patches):
                p.stop()

    def test_module_imports_only_pure_stdlib(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imported, {"__future__", "dataclasses", "json", "re", "typing"})
        code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
        code = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
        for word in ("runner_providers", "runner_pipeline", "fabric_director", "subprocess", "shutil", "socket",
                     "open(", "Path(", "os.", "environ", "eval(", "exec(", "__import__", "importlib"):
            self.assertNotIn(word, code, word)

    def test_no_mutable_module_state_changes(self):
        snapshot = {k: copy.deepcopy(v) for k, v in vars(rp).items()
                    if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
        rp.propose_route(request(), (facts(), codex_facts()))
        rp.propose_route(None, None)
        self.assertEqual({k: v for k, v in vars(rp).items() if k in snapshot}, snapshot)

    def test_invalid_ids_and_raw_values_never_echoed(self):
        secret = "sk-ant-api03-SECRETTOKEN"
        outputs = [
            rp.propose_route(request(preference_order=(secret,)), ()),
            rp.propose_route(request(pinned_provider=secret), ()),
            rp.propose_route(request(mode=secret), ()),
            rp.propose_route(request(required_capabilities=(secret,)), ()),
            rp.propose_route(request(), (facts(secret),)),
            rp.propose_route(request(), (facts(availability=secret),)),
            rp.propose_route(request(), (facts(caps=("READ_FILES", secret)),)),
        ]
        for adv in outputs:
            self.assertNotIn("SECRET", rp.canonical_json(adv).upper())
            self.assertIsNone(adv.selected_provider)

    def test_facts_carry_no_free_text_or_secret_fields(self):
        names = {f.name for f in dataclasses.fields(rp.ProviderFacts)}
        self.assertEqual(names, {"provider_id", "probe_available", "policy_mode", "policy_allow_shell",
                                 "policy_supported", "capabilities", "availability", "capacity"})
        for word in ("reason", "message", "token", "key", "secret", "prompt", "stdout", "stderr", "executable"):
            self.assertFalse([n for n in names if word in n], word)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


class NativeVocabularyPinTests(unittest.TestCase):
    """Only the tests import native provider definitions, to prove the local
    vocabulary mirrors them; the policy module never does."""

    @classmethod
    def setUpClass(cls):
        from scripts.ai import runner_providers
        cls.native = runner_providers

    def test_capability_vocabulary_mirrors_native(self):
        self.assertEqual(rp.CAPABILITIES, tuple(c.value for c in self.native.Capability))

    def test_modes_mirror_native(self):
        self.assertEqual(rp.MODES, (self.native.MODE_READ_ONLY, self.native.MODE_WRITE))

    def test_required_capabilities_mirror_native_function(self):
        for mode in rp.MODES:
            for shell in (False, True):
                if shell and mode == rp.MODE_READ_ONLY:
                    continue
                for explicit in ((), ("STRUCTURED_RESULT",), ("TEST_EXECUTION",)):
                    native = self.native.required_capabilities(self.native.ExecutionPolicy(mode, shell), explicit)
                    adv = rp.propose_route(request(mode=mode, allow_shell=shell, required_capabilities=explicit), ())
                    self.assertEqual(adv.required_capabilities, tuple(sorted(c.value for c in native)))

    def test_native_adapters_fed_honestly_route_as_runner_would(self):
        for mode in rp.MODES:
            for shell in (False, True):
                if shell and mode == rp.MODE_READ_ONLY:
                    continue
                policy = self.native.ExecutionPolicy(mode, shell)
                snapshot = []
                for cls in (self.native.ClaudeProvider, self.native.CodexProvider):
                    adapter = cls()
                    snapshot.append(rp.ProviderFacts(
                        provider_id=adapter.provider_id, probe_available=True, policy_mode=mode,
                        policy_allow_shell=shell, policy_supported=adapter.policy_refusal(policy) is None,
                        capabilities=tuple(sorted(c.value for c in adapter.capabilities(policy))),
                        availability="NONE", capacity="AVAILABLE"))
                adv = rp.propose_route(request(mode=mode, allow_shell=shell, preference_order=("codex", "claude")),
                                       tuple(snapshot))
                codex_ok = self.native.CodexProvider().policy_refusal(policy) is None
                self.assertEqual(assessment(adv, "codex").eligible, codex_ok, (mode, shell))
                self.assertEqual(adv.selected_provider, "codex" if codex_ok else "claude")

    def test_shell_mandatory_providers_match_native_refusal(self):
        registry = self.native.build_default_registry()
        refusing = {pid for pid in registry.ids()
                    if registry.create(pid).policy_refusal(self.native.ExecutionPolicy("write", False)) is not None}
        self.assertEqual(refusing, set(rp.SHELL_MANDATORY_PROVIDERS))

    def test_native_registry_ids_are_valid_routing_ids(self):
        for pid in self.native.registered_provider_ids():
            self.assertTrue(rp._valid_provider_id(pid), pid)


if __name__ == "__main__":
    unittest.main()
