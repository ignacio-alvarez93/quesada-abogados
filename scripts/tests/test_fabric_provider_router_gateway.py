"""FCP-7B-01: Provider Routing Gateway - read-only pre-dispatch adapter from
registered adapter facts + explicit Direction preference to an FCP-7A
advisory. Offline: synthetic adapters in an injected registry only."""

from __future__ import annotations

import ast
import builtins
import dataclasses
import json
import os
import shutil
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_provider_router_gateway as gw
from scripts.ai import fabric_provider_routing_policy as rp
from scripts.ai import runner_providers as providers

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_provider_router_gateway.py"
POLICY_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_provider_routing_policy.py"
TEST_PATH = Path(__file__).resolve()

ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "auto_retry_allowed", "resume_allowed",
             "merging_allowed", "provider_switch_authorized")
C = providers.Capability
SECRET = "sk-test-SECRET-token-0000"


class FakeProvider(providers.Provider):
    """Honest synthetic adapter (Claude-like by default). Any attempt to
    build or execute an invocation fails the test."""
    provider_id = "claude"
    display_name = "fake"
    available = True
    shell_mandatory = False
    calls: list = []

    def probe(self):
        type(self).calls.append(("probe", self.provider_id))
        if not self.available:
            return providers.ProviderProbe(self.provider_id, False, reason=f"not on PATH {SECRET}")
        return providers.ProviderProbe(self.provider_id, True, executable=f"/home/someone/{SECRET}/bin",
                                       version=f"1.0 {SECRET}")

    def policy_refusal(self, policy):
        if self.shell_mandatory and not policy.allow_shell:
            return f"requires shell {SECRET}"
        return None

    def capabilities(self, policy):
        if self.policy_refusal(policy) is not None:
            return frozenset()
        caps = {C.READ_FILES, C.SEARCH_FILES}
        if not self.shell_mandatory:
            caps.add(C.STRUCTURED_RESULT)
        if policy.mode == providers.MODE_WRITE:
            caps |= {C.EDIT_FILES, C.WRITE_FILES}
        if policy.allow_shell:
            caps |= {C.SHELL, C.TEST_EXECUTION}
        return frozenset(caps)

    def build_invocation(self, **kw):
        raise AssertionError("gateway must never build an invocation")

    def execute(self, *a, **kw):
        raise AssertionError("gateway must never execute a provider")

    def normalize_result(self, *a, **kw):
        raise AssertionError("gateway must never normalize a result")


def adapter(pid, **attrs):
    return type(f"Fake_{pid.replace('-', '_')}", (FakeProvider,), {"provider_id": pid, **attrs})


def registry(*specs):
    """specs: (pid, attrs) or pid."""
    reg = providers.ProviderRegistry()
    for spec in specs:
        pid, attrs = (spec, {}) if isinstance(spec, str) else spec
        reg.register(pid, adapter(pid, **attrs))
    return reg


def default_registry():
    return registry("claude", ("codex", {"shell_mandatory": True}))


def obs(pid, availability="NONE", capacity="AVAILABLE", source=gw.SOURCE_DIRECTION_DECLARED):
    return gw.ProviderObservation(provider_id=pid, availability=availability, capacity=capacity, source=source)


def all_ok(*pids):
    return tuple(obs(p) for p in pids)


def intent(mode="write", **kw):
    return gw.WorkOrderRoutingIntent(mode=mode, **kw)


def config(order=("claude", "codex"), pin=None):
    return gw.DirectionRoutingConfig(preference_order=order, pinned_provider=pin)


def route(it=None, cfg=None, observations=None, reg=None):
    return gw.route_work_order(
        it if it is not None else intent(), cfg if cfg is not None else config(),
        observations if observations is not None else all_ok("claude", "codex"),
        registry=reg if reg is not None else default_registry(),
    )


def assessment(result, pid):
    return next(a for a in result.advisory.assessments if a.provider_id == pid)


def issue_codes(result, pid):
    return tuple(code for p, code in result.issues if p == pid)


# ---------------------------------------------------------------------------
class SelectionTests(unittest.TestCase):
    def test_first_preference_selected_when_all_facts_reliable(self):
        res = route()
        self.assertEqual(res.selected_provider, "claude")
        self.assertEqual(res.rationale, rp.SELECTED_FIRST_ELIGIBLE_PREFERENCE)
        self.assertEqual(res.issues, ())

    def test_direction_order_not_registry_order_decides(self):
        reg = registry("alpha", "beta")
        res = route(cfg=config(("beta", "alpha")), observations=all_ok("alpha", "beta"), reg=reg)
        self.assertEqual(res.selected_provider, "beta")

    def test_second_preference_when_first_cli_absent(self):
        reg = registry(("alpha", {"available": False}), "beta")
        res = route(cfg=config(("alpha", "beta")), observations=all_ok("alpha", "beta"), reg=reg)
        self.assertEqual(res.selected_provider, "beta")
        self.assertIn(rp.PROBE_UNAVAILABLE, assessment(res, "alpha").reasons)

    def test_all_cli_absent_refuses(self):
        reg = registry(("alpha", {"available": False}), ("beta", {"available": False}))
        res = route(cfg=config(("alpha", "beta")), observations=all_ok("alpha", "beta"), reg=reg)
        self.assertIsNone(res.selected_provider)
        self.assertEqual(res.rationale, rp.REFUSED_NO_ELIGIBLE_PROVIDER)

    def test_explicit_capability_respected(self):
        res = route(it=intent(required_capabilities=("STRUCTURED_RESULT",), allow_shell=True))
        self.assertEqual(res.selected_provider, "claude")
        res = route(it=intent(required_capabilities=("STRUCTURED_RESULT",), allow_shell=True),
                    cfg=config(("codex", "claude")))
        self.assertEqual(res.selected_provider, "claude")
        self.assertIn("STRUCTURED_RESULT", assessment(res, "codex").missing_capabilities)

    def test_read_only_mode_selected(self):
        res = route(it=intent("read-only"))
        self.assertEqual(res.selected_provider, "claude")
        self.assertEqual(res.facts[0].policy_mode, "read-only")


class EmptyAndUnknownTests(unittest.TestCase):
    def test_empty_observation_snapshot_refuses_with_unknown(self):
        res = route(observations=())
        self.assertIsNone(res.selected_provider)
        for f in res.facts:
            self.assertEqual((f.availability, f.capacity), ("UNKNOWN", "UNKNOWN"))
        self.assertIn(rp.AVAILABILITY_UNKNOWN, assessment(res, "claude").reasons)
        self.assertIn(rp.CAPACITY_UNKNOWN, assessment(res, "claude").reasons)
        self.assertIn(gw.OBSERVATION_MISSING, issue_codes(res, "claude"))

    def test_empty_registry_yields_no_facts(self):
        res = route(reg=providers.ProviderRegistry())
        self.assertEqual(res.facts, ())
        self.assertIsNone(res.selected_provider)
        self.assertEqual(assessment(res, "claude").reasons, (rp.NO_FACTS,))
        self.assertIn(gw.ADAPTER_UNREGISTERED, issue_codes(res, "claude"))

    def test_quota_wait_excludes(self):
        res = route(observations=(obs("claude", "QUOTA_WAIT"), obs("codex")))
        self.assertIn(rp.AVAILABILITY_QUOTA_WAIT, assessment(res, "claude").reasons)

    def test_auth_blocked_excludes(self):
        res = route(observations=(obs("claude", "AUTH_BLOCKED"), obs("codex")))
        self.assertIn(rp.AVAILABILITY_AUTH_BLOCKED, assessment(res, "claude").reasons)
        self.assertIsNone(res.selected_provider)  # codex refused without shell

    def test_capacity_full_excludes_and_falls_to_next_preference(self):
        reg = registry("alpha", "beta")
        res = route(cfg=config(("alpha", "beta")), reg=reg,
                    observations=(obs("alpha", capacity="FULL"), obs("beta")))
        self.assertEqual(res.selected_provider, "beta")
        self.assertIn(rp.CAPACITY_FULL, assessment(res, "alpha").reasons)

    def test_explicit_unknown_observation_excludes(self):
        res = route(observations=(obs("claude", "UNKNOWN", "UNKNOWN"),))
        self.assertIsNone(res.selected_provider)

    def test_probe_is_not_authorization(self):
        # A successful probe alone never yields a recommendation.
        res = route(observations=())
        self.assertTrue(all(f.probe_available for f in res.facts))
        self.assertIsNone(res.selected_provider)


class ObservationValidationTests(unittest.TestCase):
    def test_unknown_availability_string_becomes_unknown_not_none(self):
        res = route(observations=(obs("claude", "OK"),))
        self.assertEqual(res.facts[0].availability, "UNKNOWN")
        self.assertIn(gw.OBSERVATION_MALFORMED, issue_codes(res, "claude"))
        self.assertIsNone(res.selected_provider)

    def test_unknown_capacity_string_becomes_unknown(self):
        res = route(observations=(obs("claude", capacity="PLENTY"),))
        self.assertEqual(res.facts[0].capacity, "UNKNOWN")
        self.assertIsNone(res.selected_provider)

    def test_runner_certification_source_refused(self):
        for source in ("RUNNER_CERTIFIED", "CERTIFIED", "", None, 7):
            res = route(observations=(obs("claude", source=source),))
            self.assertIsNone(res.selected_provider, source)
            self.assertIn(gw.OBSERVATION_MALFORMED, issue_codes(res, "claude"))
            self.assertEqual(res.provenance, (("claude", None), ("codex", None)))

    def test_runner_state_observed_source_accepted(self):
        res = route(observations=(obs("claude", source=gw.SOURCE_RUNNER_STATE_OBSERVED),))
        self.assertEqual(res.selected_provider, "claude")
        self.assertEqual(res.provenance[0], ("claude", gw.SOURCE_RUNNER_STATE_OBSERVED))

    def test_duplicate_observations_both_discarded(self):
        for pair in ((obs("claude"), obs("claude")), (obs("claude"), obs("claude", "QUOTA_WAIT"))):
            res = route(observations=pair)
            self.assertIn(gw.OBSERVATION_DUPLICATE, issue_codes(res, "claude"))
            self.assertEqual(res.facts[0].availability, "UNKNOWN")
            self.assertIsNone(res.selected_provider)

    def test_observation_container_must_be_tuple(self):
        res = route(observations=[obs("claude")])
        self.assertEqual(res.gateway_reasons, (gw.OBSERVATIONS_NOT_TUPLE,))
        self.assertIsNone(res.advisory)

    def test_untyped_observation_refused(self):
        res = route(observations=({"provider_id": "claude", "availability": "NONE"},))
        self.assertEqual(res.gateway_reasons, (gw.OBSERVATION_NOT_TYPED,))

    def test_invalid_observation_provider_id_refused(self):
        res = route(observations=(obs("Claude"),))
        self.assertEqual(res.gateway_reasons, (gw.OBSERVATION_PROVIDER_ID_INVALID,))

    def test_too_many_observations_refused(self):
        many = tuple(obs(f"p{i}") for i in range(rp.MAX_PROVIDERS + 1))
        self.assertIn(gw.OBSERVATIONS_TOO_LARGE, route(observations=many).gateway_reasons)

    def test_observation_for_unnamed_provider_unused(self):
        res = route(observations=all_ok("claude", "codex", "other"))
        self.assertIn(("other", gw.OBSERVATION_UNUSED), res.issues)
        self.assertNotIn("other", [f.provider_id for f in res.facts])

    def test_observation_subclass_refused(self):
        class Sub(gw.ProviderObservation):
            pass
        res = route(observations=(Sub("claude", "NONE", "AVAILABLE", gw.SOURCE_DIRECTION_DECLARED),))
        self.assertEqual(res.gateway_reasons, (gw.OBSERVATION_NOT_TYPED,))


class AdapterFactsTests(unittest.TestCase):
    def test_facts_mirror_adapter_under_exact_policy(self):
        res = route(it=intent(allow_shell=True))
        claude = res.facts[0]
        self.assertEqual((claude.policy_mode, claude.policy_allow_shell, claude.policy_supported), ("write", True, True))
        expected = adapter("claude")().capabilities(providers.ExecutionPolicy("write", True))
        self.assertEqual(claude.capabilities, tuple(sorted(c.value for c in expected)))

    def test_adapter_raising_on_resolution_contributes_no_facts(self):
        reg = providers.ProviderRegistry()
        reg.register("claude", lambda: (_ for _ in ()).throw(RuntimeError(SECRET)))
        res = route(reg=reg, cfg=config(("claude",)))
        self.assertEqual(res.facts, ())
        self.assertIn(gw.ADAPTER_RESOLUTION_FAILED, issue_codes(res, "claude"))
        self.assertNotIn(SECRET, gw.canonical_json(res))

    def test_probe_raising_contributes_no_facts(self):
        def boom(self):
            raise OSError(SECRET)
        res = route(reg=registry(("claude", {"probe": boom})), cfg=config(("claude",)))
        self.assertEqual(assessment(res, "claude").reasons, (rp.NO_FACTS,))
        self.assertIn(gw.PROBE_FAILED, issue_codes(res, "claude"))

    def test_malformed_probe_contributes_no_facts(self):
        bad = (
            lambda self: {"available": True},
            lambda self: providers.ProviderProbe("other", True),
            lambda self: providers.ProviderProbe("claude", 1),
        )
        for probe in bad:
            res = route(reg=registry(("claude", {"probe": probe})), cfg=config(("claude",)))
            self.assertEqual(res.facts, ())
            self.assertIn(gw.PROBE_MALFORMED, issue_codes(res, "claude"))

    def test_identity_mismatch_contributes_no_facts(self):
        reg = providers.ProviderRegistry()
        reg.register("claude", adapter("codex"))
        res = route(reg=reg, cfg=config(("claude",)))
        self.assertIn(gw.ADAPTER_IDENTITY_MISMATCH, issue_codes(res, "claude"))
        reg = providers.ProviderRegistry()
        reg.register("claude", object)
        self.assertIn(gw.ADAPTER_IDENTITY_MISMATCH, issue_codes(route(reg=reg, cfg=config(("claude",))), "claude"))

    def test_malformed_capabilities_contribute_no_facts(self):
        for caps in (["READ_FILES"], frozenset({"READ_FILES"}), None):
            res = route(reg=registry(("claude", {"capabilities": lambda self, p, c=caps: c})), cfg=config(("claude",)))
            self.assertEqual(res.facts, ())
            self.assertIn(gw.ADAPTER_CAPABILITIES_MALFORMED, issue_codes(res, "claude"))

    def test_policy_refusal_raising_or_non_string_contributes_no_facts(self):
        def raises(self, p):
            raise ValueError(SECRET)
        for refusal in (raises, lambda self, p: 42):
            res = route(reg=registry(("claude", {"policy_refusal": refusal})), cfg=config(("claude",)))
            self.assertEqual(res.facts, ())
            self.assertIn(gw.ADAPTER_POLICY_FAILED, issue_codes(res, "claude"))

    def test_inconsistent_adapter_reported_as_is_and_excluded(self):
        lying = {"policy_refusal": lambda self, p: "refused",
                 "capabilities": lambda self, p: frozenset({C.READ_FILES, C.SEARCH_FILES})}
        res = route(reg=registry(("claude", lying)), cfg=config(("claude",)))
        self.assertFalse(res.facts[0].policy_supported)
        self.assertEqual(res.facts[0].capabilities, ("READ_FILES", "SEARCH_FILES"))
        self.assertIn(rp.FACTS_INCONSISTENT, assessment(res, "claude").reasons)

    def test_future_provider_registered_routes_without_code_change(self):
        reg = registry("claude", "gemini-cli")
        res = route(reg=reg, cfg=config(("gemini-cli", "claude")), observations=all_ok("claude", "gemini-cli"))
        self.assertEqual(res.selected_provider, "gemini-cli")

    def test_future_provider_unregistered_never_selected(self):
        res = route(cfg=config(("gemini-cli", "claude")), observations=all_ok("claude", "gemini-cli"))
        self.assertEqual(res.selected_provider, "claude")
        self.assertEqual(assessment(res, "gemini-cli").reasons, (rp.NO_FACTS,))
        self.assertIn(gw.ADAPTER_UNREGISTERED, issue_codes(res, "gemini-cli"))


class ShellAndCodexTests(unittest.TestCase):
    def test_codex_without_shell_refused_by_its_adapter(self):
        res = route(cfg=config(("codex",)))
        codex = res.facts[0]
        self.assertFalse(codex.policy_supported)
        self.assertEqual(codex.capabilities, ())
        reasons = assessment(res, "codex").reasons
        self.assertIn(rp.POLICY_REFUSED, reasons)
        self.assertIn(rp.ADAPTER_REQUIRES_SHELL, reasons)
        self.assertIsNone(res.selected_provider)

    def test_codex_with_shell_in_write_mode_selected(self):
        res = route(it=intent(allow_shell=True), cfg=config(("codex", "claude")))
        self.assertEqual(res.selected_provider, "codex")
        self.assertTrue(res.facts[0].policy_allow_shell)

    def test_read_only_with_shell_refused_before_any_probe(self):
        FakeProvider.calls = []
        res = route(it=intent("read-only", allow_shell=True), cfg=config(("codex",)))
        self.assertEqual(res.advisory.request_reasons, (rp.ALLOW_SHELL_REQUIRES_WRITE_MODE,))
        self.assertEqual(res.facts, ())
        self.assertEqual(FakeProvider.calls, [])

    def test_codex_read_only_without_shell_never_simulated(self):
        res = route(it=intent("read-only"), cfg=config(("codex",)))
        self.assertIsNone(res.selected_provider)
        self.assertEqual(res.facts[0].policy_mode, "read-only")
        self.assertFalse(res.facts[0].policy_allow_shell)

    def test_shell_capability_without_allow_shell_refused(self):
        res = route(it=intent(required_capabilities=("SHELL",)))
        self.assertEqual(res.advisory.request_reasons, (rp.SHELL_REQUESTED_WITHOUT_ALLOW_SHELL,))

    def test_mixed_policies_each_observed_under_requested_policy(self):
        for mode, shell in (("read-only", False), ("write", False), ("write", True)):
            res = route(it=intent(mode, allow_shell=shell))
            self.assertTrue(all((f.policy_mode, f.policy_allow_shell) == (mode, shell) for f in res.facts))
            self.assertNotIn(rp.FACTS_POLICY_MISMATCH, assessment(res, "claude").reasons)


class PinAndLockTests(unittest.TestCase):
    def test_direction_pin_selects_only_pin(self):
        res = route(cfg=config(("claude", "codex"), pin="codex"), it=intent(allow_shell=True))
        self.assertEqual(res.selected_provider, "codex")
        self.assertEqual(res.rationale, rp.SELECTED_PINNED_PROVIDER)

    def test_ineligible_pin_never_substituted(self):
        res = route(cfg=config(("claude", "codex"), pin="codex"))
        self.assertIsNone(res.selected_provider)
        self.assertEqual(res.rationale, rp.REFUSED_PINNED_PROVIDER_INELIGIBLE)

    def test_pinned_only_pin_is_probed(self):
        FakeProvider.calls = []
        route(cfg=config(("claude", "codex"), pin="codex"), it=intent(allow_shell=True))
        self.assertEqual(FakeProvider.calls, [("probe", "codex")])

    def test_prior_attempt_without_pin_refused(self):
        FakeProvider.calls = []
        res = route(it=intent(prior_attempt_executed=True))
        self.assertEqual(res.advisory.request_reasons, (rp.LOCKED_WITHOUT_PIN,))
        self.assertIsNone(res.selected_provider)
        self.assertEqual(FakeProvider.calls, [])

    def test_provider_locked_without_pin_refused(self):
        res = route(it=intent(provider_locked=True))
        self.assertEqual(res.advisory.request_reasons, (rp.LOCKED_WITHOUT_PIN,))

    def test_owner_becomes_pin_when_locked(self):
        res = route(it=intent(prior_attempt_executed=True, owner_provider="claude"))
        self.assertEqual(res.selected_provider, "claude")
        self.assertEqual(res.rationale, rp.SELECTED_LOCKED_PROVIDER)
        self.assertEqual(res.routing_request.pinned_provider, "claude")

    def test_locked_owner_ineligible_never_switched(self):
        res = route(it=intent(prior_attempt_executed=True, owner_provider="claude"),
                    observations=(obs("claude", "AUTH_BLOCKED"), obs("codex")))
        self.assertIsNone(res.selected_provider)
        self.assertEqual(res.rationale, rp.REFUSED_LOCKED_PROVIDER_INELIGIBLE)
        self.assertFalse(res.provider_switch_authorized)

    def test_owner_pin_conflict_refused(self):
        res = route(it=intent(provider_locked=True, owner_provider="claude"), cfg=config(pin="codex"))
        self.assertEqual(res.gateway_reasons, (gw.PIN_OWNER_CONFLICT,))
        self.assertIsNone(res.advisory)
        self.assertIsNone(res.selected_provider)

    def test_owner_and_matching_pin_accepted(self):
        res = route(it=intent(provider_locked=True, owner_provider="claude"), cfg=config(pin="claude"))
        self.assertEqual(res.selected_provider, "claude")

    def test_owner_without_lock_refused(self):
        res = route(it=intent(owner_provider="claude"))
        self.assertEqual(res.gateway_reasons, (gw.OWNER_WITHOUT_LOCK,))

    def test_pin_not_in_preference_refused_by_policy(self):
        res = route(cfg=config(("claude",), pin="codex"))
        self.assertEqual(res.advisory.request_reasons, (rp.PIN_NOT_IN_PREFERENCE,))


class RequestValidationTests(unittest.TestCase):
    def test_untyped_intent_and_config_refused(self):
        res = gw.route_work_order({"mode": "write"}, ("claude",), (), registry=default_registry())
        self.assertEqual(res.gateway_reasons, (gw.INTENT_NOT_TYPED, gw.CONFIG_NOT_TYPED))
        self.assertEqual(res.rationale, gw.GATEWAY_REFUSED)

    def test_invalid_request_never_probes(self):
        FakeProvider.calls = []
        bad = (
            (intent("admin"), config()),
            (intent(allow_shell="yes"), config()),
            (intent(required_capabilities=("TELEPORT",)), config()),
            (intent(), config(("claude", "claude"))),
            (intent(), config(())),
            (intent(), config(("Bad Id",))),
            (intent(prior_attempt_executed="no"), config()),
        )
        for it, cfg in bad:
            res = route(it=it, cfg=cfg)
            self.assertEqual(res.rationale, rp.REFUSED_INVALID_REQUEST)
            self.assertEqual(res.facts, ())
        self.assertEqual(FakeProvider.calls, [])

    def test_duplicate_capabilities_refused(self):
        res = route(it=intent(required_capabilities=("READ_FILES", "READ_FILES")))
        self.assertEqual(res.advisory.request_reasons, (rp.CAPABILITY_DUPLICATE,))

    def test_explicit_config_is_required_no_default_ranking(self):
        res = gw.route_work_order(intent(), gw.DirectionRoutingConfig(), all_ok("claude"),
                                  registry=default_registry())
        self.assertEqual(res.advisory.request_reasons, (rp.PREFERENCE_EMPTY,))
        self.assertIsNone(res.selected_provider)


class EquivalenceTests(unittest.TestCase):
    def test_advisory_identical_to_direct_policy_call(self):
        cases = (
            (intent(), config(), all_ok("claude", "codex")),
            (intent(allow_shell=True), config(("codex", "claude")), all_ok("claude", "codex")),
            (intent(), config(), (obs("claude", "QUOTA_WAIT"),)),
            (intent(prior_attempt_executed=True, owner_provider="claude"), config(), ()),
            (intent("read-only"), config(("codex", "claude"), pin="claude"), all_ok("claude")),
        )
        for it, cfg, ob in cases:
            res = gw.route_work_order(it, cfg, ob, registry=default_registry())
            direct = rp.propose_route(res.routing_request, res.facts)
            self.assertEqual(res.advisory, direct)
            self.assertEqual(rp.canonical_json(res.advisory), rp.canonical_json(direct))

    def test_advisory_is_fcp7a_type_and_schema(self):
        res = route()
        self.assertIs(type(res.advisory), rp.RoutingAdvisory)
        self.assertEqual(res.to_dict()["advisory"]["schema"], rp.SCHEMA)

    def test_policy_module_not_mutated(self):
        before = {k: v for k, v in vars(rp).items() if not k.startswith("__")}
        route()
        route(observations=())
        self.assertEqual({k: v for k, v in vars(rp).items() if not k.startswith("__")}, before)

    def test_gateway_reuses_policy_and_defines_no_selection(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        self.assertFalse(names & {"propose_route", "RoutingRequest", "ProviderFacts", "RoutingAdvisory"})
        self.assertIn("policy.propose_route", MODULE_PATH.read_text(encoding="utf-8"))


class OutputContractTests(unittest.TestCase):
    def test_flags_false_on_every_outcome(self):
        outcomes = (route(), route(observations=()), route(observations=[]), route(it=intent("x")))
        for res in outcomes:
            for flag in ALL_FLAGS:
                self.assertIs(getattr(res, flag), False)
                self.assertIs(res.to_dict()[flag], False)
            if res.advisory is not None:
                for flag in ALL_FLAGS:
                    self.assertIs(getattr(res.advisory, flag), False)

    def test_flags_not_constructible_or_replaceable(self):
        res = route()
        for flag in ALL_FLAGS:
            with self.assertRaises(TypeError):
                dataclasses.replace(res, **{flag: True})
            with self.assertRaises(AttributeError):
                setattr(res, flag, True)

    def test_result_frozen_and_inconsistent_construction_rejected(self):
        res = route()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            res.advisory = None
        with self.assertRaises(ValueError):
            dataclasses.replace(res, gateway_reasons=(gw.PIN_OWNER_CONFLICT,))
        with self.assertRaises(ValueError):
            dataclasses.replace(res, provenance=(("claude", "RUNNER_CERTIFIED"),))

    def test_deterministic_byte_identical(self):
        outs = {gw.canonical_json(route(observations=(obs("codex"), obs("claude", capacity="FULL"))))
                for _ in range(5)}
        self.assertEqual(len(outs), 1)
        json.loads(outs.pop())

    def test_observation_order_does_not_change_result(self):
        a = route(observations=(obs("claude"), obs("codex"), obs("zeta")))
        b = route(observations=(obs("zeta"), obs("codex"), obs("claude")))
        self.assertEqual(gw.canonical_json(a), gw.canonical_json(b))

    def test_facts_follow_direction_order(self):
        res = route(cfg=config(("codex", "claude")))
        self.assertEqual([f.provider_id for f in res.facts], ["codex", "claude"])

    def test_no_secret_path_or_version_leaks(self):
        for res in (route(), route(reg=registry(("claude", {"available": False})), cfg=config(("claude",))),
                    route(cfg=config(("codex",)))):
            text = gw.canonical_json(res)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("/home/", text)
            self.assertNotIn("executable", text)
            self.assertNotIn("version\"", text.replace("schema_version\"", ""))

    def test_no_cost_latency_or_quality_fields(self):
        text = gw.canonical_json(route()).lower()
        for word in ("cost", "price", "latency", "speed", "quality", "score"):
            self.assertNotIn(word, text)
        fields = {f.name for cls in (gw.WorkOrderRoutingIntent, gw.DirectionRoutingConfig, gw.ProviderObservation)
                  for f in dataclasses.fields(cls)}
        self.assertFalse({"cost", "latency", "quality", "score", "weight", "rank"} & fields)

    def test_invalid_input_never_echoed(self):
        res = route(it=intent(f"mode-{SECRET}"), cfg=config((SECRET,)))
        self.assertNotIn(SECRET, gw.canonical_json(res))


class PurityTests(unittest.TestCase):
    def test_no_process_file_network_or_git_io(self):
        guards = {
            "subprocess.run": mock.patch.object(subprocess, "run", side_effect=AssertionError("run")),
            "subprocess.Popen": mock.patch.object(subprocess, "Popen", side_effect=AssertionError("Popen")),
            "open": mock.patch.object(builtins, "open", side_effect=AssertionError("open")),
            "socket": mock.patch.object(socket, "socket", side_effect=AssertionError("socket")),
            "os.replace": mock.patch.object(os, "replace", side_effect=AssertionError("replace")),
            "os.makedirs": mock.patch.object(os, "makedirs", side_effect=AssertionError("makedirs")),
            "os.remove": mock.patch.object(os, "remove", side_effect=AssertionError("remove")),
        }
        for g in guards.values():
            g.start()
        try:
            route()
            route(observations=())
            route(it=intent(prior_attempt_executed=True, owner_provider="claude"))
        finally:
            for g in guards.values():
                g.stop()

    def test_no_invocation_built_or_executed(self):
        # FakeProvider raises from build_invocation/execute/normalize_result.
        res = route(it=intent(allow_shell=True))
        self.assertIsNotNone(res.selected_provider)

    def test_director_and_runner_never_imported_or_called(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[-1] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                imported |= {a.name for a in n.names} | {(n.module or "").split(".")[-1]}
        self.assertEqual(imported - {"ai", "scripts"}, {
            "annotations", "__future__", "json", "dataclass", "dataclasses", "Callable", "Optional", "typing",
            "fabric_provider_routing_policy", "runner_providers",
        })
        source = MODULE_PATH.read_text(encoding="utf-8")
        for token in ("fabric_director", "runner_pipeline", "claude_runner", "runner_git", ".submit(",
                      "build_invocation(", ".execute(", "run_process", "run_preflight", "subprocess",
                      "open(", "os.", "environ", "eval(", "exec(", "__import__", "importlib", "Path("):
            code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith(("#", "*", "`")))
            self.assertNotIn(token, code.split('"""', 2)[-1], token)

    def test_inputs_not_mutated_and_frozen(self):
        it, cfg, ob = intent(), config(), all_ok("claude", "codex")
        snap = (dataclasses.astuple(it), dataclasses.astuple(cfg), tuple(dataclasses.astuple(o) for o in ob))
        gw.route_work_order(it, cfg, ob, registry=default_registry())
        self.assertEqual(snap, (dataclasses.astuple(it), dataclasses.astuple(cfg),
                                tuple(dataclasses.astuple(o) for o in ob)))
        for value in (it, cfg, ob[0]):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                value.provider_id = "x"

    def test_registry_not_mutated(self):
        reg = default_registry()
        before = reg.ids()
        route(reg=reg)
        self.assertEqual(reg.ids(), before)

    def test_default_registry_used_when_none_injected(self):
        fake = default_registry()
        with mock.patch.object(gw.providers, "resolve_provider", side_effect=fake.create) as resolve:
            res = gw.route_work_order(intent(), config(), all_ok("claude", "codex"))
        self.assertEqual([c.args[0] for c in resolve.call_args_list], ["claude", "codex"])
        self.assertEqual(res.selected_provider, "claude")

    def test_native_adapters_with_cli_absent_never_spawn(self):
        with mock.patch.object(shutil, "which", return_value=None), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("spawned")):
            res = gw.route_work_order(intent(allow_shell=True), config(), all_ok("claude", "codex"),
                                      registry=providers.build_default_registry())
        self.assertIsNone(res.selected_provider)
        for f in res.facts:
            self.assertFalse(f.probe_available)

    def test_native_adapters_routed_honestly(self):
        with mock.patch.object(shutil, "which", return_value="cli"), \
                mock.patch.object(providers, "probe_executable_version", return_value=SECRET):
            reg = providers.build_default_registry()
            no_shell = gw.route_work_order(intent(), config(("codex", "claude")), all_ok("claude", "codex"),
                                           registry=reg)
            shell = gw.route_work_order(intent(allow_shell=True), config(("codex", "claude")),
                                        all_ok("claude", "codex"), registry=reg)
        self.assertEqual(no_shell.selected_provider, "claude")
        self.assertIn(rp.ADAPTER_REQUIRES_SHELL, assessment(no_shell, "codex").reasons)
        self.assertEqual(shell.selected_provider, "codex")
        self.assertNotIn(SECRET, gw.canonical_json(shell))

    def test_no_personal_absolute_paths_in_module(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for token in ("C:\\", "C:/", "/home/", "/Users/", "Desktop"):
            self.assertNotIn(token, source)

    def test_policy_file_unchanged_marker(self):
        self.assertIn('SCHEMA = "fcp7a01-provider-routing-advisory-v1"', POLICY_PATH.read_text(encoding="utf-8"))

    def test_this_suite_skips_nothing(self):
        source = TEST_PATH.read_text(encoding="utf-8")
        for token in ("skip" + "Test", "skip" + "If", "skip" + "Unless", "expected" + "Failure", "unittest." + "skip"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
