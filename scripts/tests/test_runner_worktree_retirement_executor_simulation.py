"""FCP-4F-01: simulated retirement executor kernel (SIMULATION ONLY, NOT LIVE).

Every target is synthetic (`sim://fcp4f01/` labels, never a filesystem
path), every decision is an in-memory fixture and every port is the
module's own in-memory port, configured through declarative
`SimulationFaults`. Nothing here runs Git, creates or removes a worktree,
touches a branch, opens a ledger, starts a process or reaches the network;
the side-effect tests patch those entry points and assert they are never
called. Real FCP-4D/02a objects come from the merged pure 02a fixtures
(paths under a root that does not exist). Nothing here is skipped.
"""

import ast
import builtins
import copy
import dataclasses
import hashlib
import importlib.util
import io
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import runner_worktree_retirement as wr
from scripts.ai import runner_worktree_retirement_authorization as wra
from scripts.ai import runner_worktree_retirement_executor_simulation as sim
from scripts.ai import runner_worktree_retirement_host_authority as rha
from scripts.ai import runner_worktree_retirement_host_composition as rcm
from scripts.tests import test_runner_worktree_retirement_authorization as twra

MODULE_PATH = Path(sim.__file__)
TEST_PATH = Path(__file__).resolve()
REPO_ROOT = TEST_PATH.parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
LEDGER_MODULE_NAME = "runner_worktree_retirement_host_ledger"
# sha256 (LF-normalized) of the merged sources at fbd5209; 4F-01 must not change them.
PINNED_SOURCES = {
    "scripts/ai/runner_worktree_inventory.py":
        "95a3c5be639546d1e2f9ed5bdcd12d6fda2a2c8c19a1f03780ee99f0f4c6dbd0",
    "scripts/ai/runner_worktree_retirement.py":
        "58ab30c4de9be940e6984c7f07d66d8201a54e9f51ef3dab123958f3d9a40dbe",
    "scripts/ai/runner_worktree_retirement_authorization.py":
        "c51068e0eff2aa4a20a2edf712d86a716cc784e6a9e52b1c877e5a9d8cc205c0",
    "scripts/ai/runner_worktree_retirement_host_authority.py":
        "3c13c160fed6dd5510c0586a40e4cc31248acce0aadd9ada47d69f7ea1c94ccd",
    "scripts/ai/" + LEDGER_MODULE_NAME + ".py":
        "0079d485dce0e2d183b1952c465cec7828d9b59cc5f2035e82a500c4e20c9fb1",
    "scripts/ai/runner_worktree_retirement_host_composition.py":
        "03adf892e94bb081b4f56ca270de30610b67821795fe087a69a8f3e31fe11cf0",
    "scripts/ai/runner_promotion_executor.py":
        "6409ba12fa1ebde9ffbf72c101280d857325901e0fe37bae4df62d82d489f3c8",
}

T0 = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
HOST = "sim-host-01"
TARGET_ID = "wt-feature"
LABEL = "sim://fcp4f01/worktrees/wt-feature"
QUEUE_MAIN = "sim://fcp4f01/queues/main"
QUEUE_TARGET = "sim://fcp4f01/queues/wt-feature"
BRANCH = "refs/heads/feature/fcp4f01"
BASE = "refs/heads/develop"
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
FIXTURE = "fixture-1"
OTHER = sim.SimulatedWorktree("wt-other", "sim://fcp4f01/worktrees/wt-other", "refs/heads/feature/other",
                              "c" * 40, BASE, BASE_SHA)


def stamp(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
    """The caller's clock: returns the queued instants in order, then the last."""

    def __init__(self, *instants):
        self.instants = list(instants) or [T0]
        self.reads = 0

    def __call__(self):
        self.reads += 1
        return self.instants.pop(0) if len(self.instants) > 1 else self.instants[0]


def make_target(**changes):
    fields = dict(target_id=TARGET_ID, worktree_label=LABEL, head_ref=BRANCH, head_sha=HEAD_SHA, base_ref=BASE,
                  base_sha=BASE_SHA, queue_labels=(QUEUE_MAIN, QUEUE_TARGET))
    fields.update(changes)
    return sim.build_synthetic_target(**fields)


def make_request(target=None, host_label=HOST):
    return sim.build_simulation_request(make_target() if target is None else target, host_label=host_label)


def make_fixture(request=None, fixture_id=FIXTURE, issued=T0 - timedelta(seconds=60),
                 expires=T0 + timedelta(seconds=180)):
    return sim.build_decision_fixture(make_request() if request is None else request, fixture_id=fixture_id,
                                      issued_at=stamp(issued), expires_at=stamp(expires))


def queues(pending=0, attested=True):
    return tuple(sim.SimulatedQueueAttestation(q, pending, attested) for q in (QUEUE_MAIN, QUEUE_TARGET))


def make_port(faults=None, worktree_changes=None, fixtures=(FIXTURE,), clock=None, **changes):
    t = make_target()
    target = sim.SimulatedWorktree(t.target_id, t.worktree_label, t.head_ref, t.head_sha, t.base_ref, t.base_sha)
    target = dataclasses.replace(target, **(worktree_changes or {}))
    fields = dict(host_label=HOST, clock=clock or (lambda: T0), acknowledged_fixture_ids=fixtures,
                  queue_attestations=queues(), faults=faults)
    fields.update(changes)
    return sim.InMemoryRetirementSimulationPort((target, OTHER), **fields)


def forge(obj, **changes):
    """A copy with fields overwritten WITHOUT recomputing any digest."""
    clone = copy.copy(obj)
    for name, value in changes.items():
        object.__setattr__(clone, name, value)
    return clone


def refingerprinted(outcome, **changes):
    """An outcome with fields changed and its fingerprint recomputed, so only
    the semantic invariants can catch the change."""
    clone = forge(outcome, **changes)
    try:
        object.__setattr__(clone, "fingerprint", sim.outcome_fingerprint(clone))
    except TypeError:   # not canonical data (e.g. a list): left unfingerprinted
        pass
    return clone


REAL_WORLD_FLAGS = (("simulation_only", True), ("retirement_authorization_live", False),
                    ("retirement_execution_capable", False), ("authorizes_action", False),
                    ("deletion_authorized", False), ("branch_deletion_authorized", False), ("issued", False),
                    ("consumed", False), ("host_identity_authenticated", False), ("queue_scope_attested", False),
                    ("human_approval_present", False), ("retry_allowed", False))


DEFAULT = object()   # "build the default fixture" (None is a real, absent decision)


class SimulationCase(unittest.TestCase):
    def run_sim(self, request=None, decision=DEFAULT, port=None, clock=None):
        request = make_request() if request is None else request
        decision = make_fixture(request) if decision is DEFAULT else decision
        port = make_port() if port is None else port
        outcome = sim.simulate_retirement(request, decision, port, clock=clock or Clock())
        self.assertSound(outcome)
        return outcome

    def assertSound(self, outcome):
        self.assertIs(type(outcome), sim.SimulatedRetirementOutcome)
        self.assertEqual(sim.outcome_invariant_errors(outcome), ())
        for name, value in REAL_WORLD_FLAGS:
            self.assertIs(getattr(outcome, name), value, name)
        self.assertEqual(outcome.unproven, sim.SIMULATION_UNPROVEN)
        self.assertTrue(set(outcome.reason_codes) <= set(sim.REASON_CODES), outcome.reason_codes)

    def assertRefused(self, outcome, code, port=None):
        self.assertEqual(outcome.state, sim.REFUSED_SIMULATED, outcome.reason_codes)
        self.assertIn(code, outcome.reason_codes)
        self.assertEqual(outcome.simulated_effect_calls, 0)
        self.assertIs(outcome.simulated_effect_recorded, False)
        self.assertNotIn(sim.EFFECT_SIMULATED, outcome.state_trace)
        if port is not None:
            self.assertEqual(port.effect_events(), ())
            self.assertNotIn(sim.STEP_EFFECT, [s for s, _ in port.call_log()])
            self.assertEqual(port.held_leases(), ())

    def assertUncertain(self, outcome, code, port):
        self.assertEqual(outcome.state, sim.UNCERTAIN_SIMULATED, outcome.reason_codes)
        self.assertIn(code, outcome.reason_codes)
        self.assertIn(sim.SIM_NO_RETRY_AFTER_UNCERTAINTY, outcome.reason_codes)
        self.assertIs(outcome.human_reconciliation_required, True)
        self.assertEqual(outcome.simulated_effect_calls, 1)
        self.assertEqual([s for s, _ in port.call_log()].count(sim.STEP_EFFECT), 1)
        self.assertIs(outcome.simulated_postcheck_confirmed, False)
        self.assertEqual(port.held_leases(), ())


# ---------------------------------------------------------------------------
# 1. Positive synthetic path
# ---------------------------------------------------------------------------

class PositivePathTests(SimulationCase):
    def test_positive_synthetic_path_completes_as_a_simulation_only(self):
        port = make_port()
        o = self.run_sim(port=port)
        self.assertEqual(o.state, sim.COMPLETED_SIMULATED)
        self.assertEqual(o.state_trace, (sim.CREATED, sim.CHECKED, sim.LEASE_SIMULATED,
                                         sim.FRESH_REVALIDATED_SIMULATED, sim.CONSUMED_SIMULATED,
                                         sim.EFFECT_SIMULATED, sim.POSTCHECK_SIMULATED, sim.COMPLETED_SIMULATED))
        self.assertEqual(tuple(s.step for s in o.step_trace), sim.STEP_ORDER)
        self.assertTrue(all(s.result == sim.STEP_OK for s in o.step_trace))
        self.assertEqual(o.reason_codes, (sim.SIM_COMPLETED_SIMULATED_ONLY, sim.SIM_SIMULATION_ONLY_NOT_A_RETIREMENT,
                                          sim.SIM_NO_REAL_AUTHORIZATION, sim.SIM_LIVE_EXECUTION_BLOCKED))
        self.assertEqual(sim.ALWAYS_CODES, o.reason_codes[1:])
        self.assertEqual((o.simulated_decision_checked, o.simulated_lease_held, o.simulated_fresh_revalidated,
                          o.simulated_consumed, o.simulated_effect_recorded, o.simulated_postcheck_confirmed),
                         (True,) * 6)
        self.assertEqual(o.simulated_effect_calls, 1)
        self.assertIs(o.human_reconciliation_required, False)
        self.assertEqual((o.attempt_id, o.target_id, o.fixture_id), (make_request().attempt_id, TARGET_ID, FIXTURE))
        # The "effect" is one in-memory event, nothing else.
        events = port.effect_events()
        self.assertEqual(len(events), 1)
        self.assertIs(type(events[0]), sim.SimulatedEffectEvent)
        self.assertEqual((events[0].effect_id, events[0].target_id, events[0].worktree_label),
                         (o.effect_id, TARGET_ID, LABEL))
        self.assertEqual(port.held_leases(), ())
        self.assertEqual(port.consumed_fixture_ids(), (FIXTURE,))

    def test_port_calls_follow_the_gate_order_and_consume_before_effect(self):
        port = make_port()
        self.run_sim(port=port)
        steps = [s for s, _ in port.call_log()]
        self.assertEqual(steps, list(sim.STEP_ORDER[1:]))
        self.assertLess(steps.index(sim.STEP_CONSUME), steps.index(sim.STEP_EFFECT))
        self.assertEqual({a for _, a in port.call_log()}, {make_request().attempt_id})

    def test_module_status_constants_are_not_live(self):
        self.assertIs(sim.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertIs(sim.RETIREMENT_EXECUTION_CAPABLE, False)
        self.assertIs(sim.SIMULATION_ONLY, True)
        for module in (wra, rha, rcm):
            self.assertIs(module.RETIREMENT_AUTHORIZATION_LIVE, False)
            self.assertIs(module.RETIREMENT_EXECUTION_CAPABLE, False)

    def test_outcome_is_deterministic_for_the_same_inputs(self):
        a, b = self.run_sim(), self.run_sim()
        self.assertEqual(a, b)
        self.assertEqual(a.fingerprint, sim.outcome_fingerprint(a))


# ---------------------------------------------------------------------------
# 2. Gate 1: marker, synthetic target, request, port type, clock
# ---------------------------------------------------------------------------

class TargetGateTests(SimulationCase):
    def assertRefusedBeforePort(self, request, code, decision=None):
        port = make_port()
        o = sim.simulate_retirement(request, decision or make_fixture(), port, clock=Clock())
        self.assertSound(o)
        self.assertRefused(o, code, port)
        self.assertEqual(port.call_log(), ())
        self.assertEqual(o.state_trace, (sim.CREATED, sim.REFUSED_SIMULATED))
        self.assertIsNone(o.attempt_id)
        return o

    def test_missing_simulation_marker_is_refused(self):
        self.assertRefusedBeforePort(forge(make_request(), simulation_marker="LIVE"), sim.SIM_MARKER_MISSING)
        target = forge(make_target(), simulation_marker="")
        self.assertRefusedBeforePort(forge(make_request(), target=target), sim.SIM_MARKER_MISSING)

    def test_real_filesystem_paths_are_never_synthetic_targets(self):
        real = (str(REPO_ROOT), str(REPO_ROOT.parent), os.path.abspath(os.sep), "C:\\Users\\x\\wt", "C:/wt",
                "/home/x/wt", "\\\\server\\share\\wt", "//server/share/wt", "relative/wt", "wt",
                "sim://fcp4f01/../wt", "sim://fcp4f01/./wt", "sim://fcp4f01/a\\b", "sim://fcp4f01/",
                "sim://other/wt", "SIM://fcp4f01/wt", "file:///C:/wt", " sim://fcp4f01/wt", "sim://fcp4f01/wt\0")
        for label in real:
            with self.subTest(label=label):
                self.assertFalse(sim.is_synthetic_label(label))
                self.assertRefusedBeforePort(make_request(make_target(worktree_label=label)),
                                             sim.SIM_TARGET_NOT_SYNTHETIC)
        self.assertRefusedBeforePort(make_request(make_target(queue_labels=(str(REPO_ROOT),))),
                                     sim.SIM_TARGET_NOT_SYNTHETIC)
        self.assertTrue(sim.is_synthetic_label(LABEL))

    def test_a_real_02a_target_identity_is_refused(self):
        report, record = twra.fixture()
        proposal = wra.build_retirement_proposal(report, record, host_id=twra.HOST)
        request = forge(make_request(), target=proposal.target)
        self.assertRefusedBeforePort(request, sim.SIM_TARGET_REAL_IDENTITY_REFUSED)
        self.assertEqual(sim.target_errors(proposal.target), [sim.SIM_TARGET_REAL_IDENTITY_REFUSED])

    def test_tampered_target_or_request_is_refused(self):
        t = make_target()
        for changes in ({"head_sha": "d" * 40}, {"base_sha": "e" * 40}, {"worktree_label": LABEL + "-2"},
                        {"head_ref": "refs/heads/other"}, {"queue_labels": (QUEUE_MAIN,)}):
            with self.subTest(changes=changes):
                self.assertRefusedBeforePort(forge(make_request(), target=forge(t, **changes)),
                                             sim.SIM_TARGET_DIGEST_MISMATCH)
        self.assertRefusedBeforePort(forge(make_request(), attempt_id="0" * 64), sim.SIM_REQUEST_TAMPERED)
        self.assertRefusedBeforePort(forge(make_request(), host_label="other-host"), sim.SIM_REQUEST_TAMPERED)
        self.assertRefusedBeforePort(forge(make_request(), target=forge(t, is_real_checkout=True)),
                                     sim.SIM_TARGET_MALFORMED)

    def test_malformed_requests_and_targets_are_refused(self):
        for request in (None, object(), "request", make_target(), forge(make_request(), action="RETIRE_LIVE"),
                        forge(make_request(), schema="v0"), forge(make_request(), authorizes_action=True),
                        make_request(host_label="bad host"), make_request(host_label="")):
            with self.subTest(request=request):
                self.assertRefusedBeforePort(request, sim.SIM_REQUEST_MALFORMED)
        targets = (make_target(target_id="bad id"), make_target(queue_labels=()),
                   forge(make_target(), queue_labels=[QUEUE_MAIN]), make_target(queue_labels=(QUEUE_TARGET, QUEUE_MAIN)),
                   make_target(queue_labels=(QUEUE_MAIN, QUEUE_MAIN)), make_target(queue_labels=(LABEL,)),
                   make_target(head_ref="feature/x"), make_target(head_ref=BASE), make_target(base_ref="develop"),
                   make_target(head_ref="refs/heads/a..b"), forge(make_target(), schema="v0"))
        for target in targets:
            with self.subTest(target=target):
                self.assertRefusedBeforePort(make_request(target), sim.SIM_TARGET_MALFORMED)

    def test_protected_branches_and_invalid_shas_are_refused(self):
        for branch in ("main", "master", "develop"):
            with self.subTest(branch=branch):
                target = make_target(head_ref="refs/heads/" + branch, base_ref="refs/heads/feature/base")
                self.assertRefusedBeforePort(make_request(target), sim.SIM_TARGET_PROTECTED_BRANCH)
        for changes in ({"head_sha": "A" * 40}, {"head_sha": "a" * 39}, {"base_sha": "g" * 40},
                        {"object_format": "sha256"}, {"object_format": "md5"}):
            with self.subTest(changes=changes):
                self.assertRefusedBeforePort(make_request(make_target(**changes)), sim.SIM_TARGET_SHA_INVALID)
        self.assertEqual(self.run_sim(make_request(make_target(head_sha="a" * 64, base_sha="b" * 64,
                                                               object_format="sha256"))).state,
                         sim.REFUSED_SIMULATED)   # the port's registry still names the sha1 target

    def test_only_the_exact_in_memory_port_is_accepted(self):
        calls = []

        class LookAlike:
            port_kind = sim.PORT_KIND_IN_MEMORY_SIMULATION

            def __getattr__(self, name):
                calls.append(name)
                raise AssertionError(name)

        class Subclass(sim.InMemoryRetirementSimulationPort):
            pass

        sub = Subclass((), host_label=HOST, clock=lambda: T0)
        spoofed = make_port()
        spoofed.port_kind = "REAL_HOST"
        for port in (None, LookAlike(), sub, object(), sim.InMemoryRetirementSimulationPort, spoofed):
            with self.subTest(port=port):
                o = sim.simulate_retirement(make_request(), make_fixture(), port, clock=Clock())
                self.assertSound(o)
                self.assertRefused(o, sim.SIM_PORT_NOT_IN_MEMORY_SIMULATION)
        self.assertEqual(calls, [])
        self.assertEqual(sub.call_log(), ())
        self.assertEqual(spoofed.call_log(), ())

    def test_invalid_clocks_are_refused_before_any_port_call(self):
        for clock in (None, "now", T0):
            with self.subTest(clock=clock):
                port = make_port()
                o = sim.simulate_retirement(make_request(), make_fixture(), port, clock=clock)
                self.assertSound(o)
                self.assertRefused(o, sim.SIM_CLOCK_INVALID, port)
                self.assertEqual(port.call_log(), ())

        def broken():
            raise RuntimeError("clock")

        for clock in (lambda: T0.replace(tzinfo=None), lambda: T0.astimezone(timezone(timedelta(hours=1))),
                      lambda: "2026-10-27T12:00:00Z", broken, lambda: datetime(1999, 1, 1, tzinfo=timezone.utc)):
            with self.subTest(clock=clock):
                port = make_port()
                o = self.run_sim(port=port, clock=clock)
                self.assertRefused(o, sim.SIM_CLOCK_INVALID, port)
                self.assertEqual(port.call_log(), ())


# ---------------------------------------------------------------------------
# 3. Gate 2: the fake human-decision fixture
# ---------------------------------------------------------------------------

class DecisionGateTests(SimulationCase):
    def assertDecisionRefused(self, decision, code, port=None):
        port = port or make_port()
        o = self.run_sim(decision=decision, port=port)
        self.assertRefused(o, code, port)
        self.assertEqual(port.consumed_fixture_ids(), ())
        self.assertNotIn(sim.STEP_ACQUIRE_LEASE, [s for s, _ in port.call_log()])
        self.assertIs(o.simulated_decision_checked, False)
        return o, port

    def test_absent_or_foreign_decisions_are_refused_before_any_port_call(self):
        o, port = self.assertDecisionRefused(None, sim.SIM_DECISION_ABSENT)
        self.assertEqual(port.call_log(), ())
        for decision in (object(), "approved", True, {"approved": True}, make_request()):
            with self.subTest(decision=decision):
                o, port = self.assertDecisionRefused(decision, sim.SIM_DECISION_NOT_SIMULATION_FIXTURE)
                self.assertEqual(port.call_log(), ())

    def test_unsealed_or_reforged_fixtures_are_refused(self):
        fx = make_fixture()
        for decision in (forge(fx, fixture_seal=""), forge(fx, fixture_seal="0" * 64), forge(fx, fixture_seal=None),
                         forge(fx, expires_at=stamp(T0 + timedelta(seconds=200))), forge(fx, fixture_id="fixture-2")):
            with self.subTest(decision=decision):
                o, port = self.assertDecisionRefused(decision, sim.SIM_DECISION_UNSEALED)
                self.assertEqual(port.call_log(), ())

    def test_forged_authority_claims_are_refused(self):
        for name in ("is_human_approval", "is_real_permit", "authenticated", "authorizes_action",
                     "deletion_authorized"):
            with self.subTest(name=name):
                self.assertDecisionRefused(forge(make_fixture(), **{name: True}), sim.SIM_DECISION_FORGED_CLAIM)
        with self.assertRaises(TypeError):
            sim.SimulatedHumanDecisionFixture(*(["x"] * 11), authorizes_action=True)

    def test_unauthenticated_fixture_is_not_acknowledged(self):
        # Sealed and well formed, but the in-memory host never registered it.
        o, port = self.assertDecisionRefused(make_fixture(), sim.SIM_DECISION_NOT_ACKNOWLEDGED,
                                             make_port(fixtures=()))
        self.assertEqual([s for s, _ in port.call_log()], [sim.STEP_CHECK_DECISION])
        self.assertDecisionRefused(make_fixture(), sim.SIM_DECISION_REVOKED,
                                   make_port(revoked_fixture_ids=(FIXTURE,)))

    def test_fixture_bound_to_another_attempt_or_identity_is_refused(self):
        other = make_request(make_target(target_id="wt-other", worktree_label=OTHER.worktree_label))
        self.assertDecisionRefused(make_fixture(other), sim.SIM_DECISION_BINDING_MISMATCH)
        self.assertDecisionRefused(make_fixture(make_request(host_label="sim-host-02")),
                                   sim.SIM_DECISION_BINDING_MISMATCH)
        for changes in ({"head_sha": "d" * 40}, {"base_sha": "d" * 40}, {"action": "RETIRE"},
                        {"target_digest": "0" * 64}):
            with self.subTest(changes=changes):
                staged = forge(make_fixture(), **changes)
                object.__setattr__(staged, "fixture_seal", sim.decision_seal(staged))
                self.assertDecisionRefused(staged, sim.SIM_DECISION_BINDING_MISMATCH)

    def test_fixture_window_is_enforced_against_the_simulated_clock(self):
        cases = ((T0 - timedelta(seconds=300), T0, sim.SIM_DECISION_EXPIRED),
                 (T0 + timedelta(seconds=1), T0 + timedelta(seconds=60), sim.SIM_DECISION_NOT_YET_VALID),
                 (T0 - timedelta(seconds=10), T0 + timedelta(seconds=300), sim.SIM_DECISION_TTL_TOO_LONG),
                 (T0, T0, sim.SIM_DECISION_TIMESTAMP_INVALID))
        for issued, expires, code in cases:
            with self.subTest(code=code):
                self.assertDecisionRefused(make_fixture(issued=issued, expires=expires), code)
        bad = sim.build_decision_fixture(make_request(), fixture_id=FIXTURE, issued_at="2026-10-27 12:00:00",
                                         expires_at=stamp(T0 + timedelta(seconds=60)))
        self.assertDecisionRefused(bad, sim.SIM_DECISION_TIMESTAMP_INVALID)

    def test_wrong_marker_or_schema_is_refused(self):
        for changes, code in (({"simulation_marker": "LIVE"}, sim.SIM_MARKER_MISSING),
                              ({"schema": "v0"}, sim.SIM_DECISION_MALFORMED),
                              ({"fixture_id": "bad id"}, sim.SIM_DECISION_MALFORMED)):
            with self.subTest(code=code):
                staged = forge(make_fixture(), **changes)
                object.__setattr__(staged, "fixture_seal", sim.decision_seal(staged))
                self.assertDecisionRefused(staged, code)

    def test_malformed_acknowledgements_are_refused(self):
        req = make_request()
        bad = (sim.SimulatedDecisionAck("APPROVED", req.attempt_id, FIXTURE),
               sim.SimulatedDecisionAck(sim.ACK_ACCEPTED, "0" * 64, FIXTURE),
               sim.SimulatedDecisionAck(sim.ACK_ACCEPTED, req.attempt_id, "fixture-2"),
               sim.SimulatedDecisionAck(sim.ACK_ACCEPTED, req.attempt_id, FIXTURE, schema="v0"), None, True)
        for ack in bad:
            with self.subTest(ack=ack):
                port = make_port()
                with mock.patch.object(sim.InMemoryRetirementSimulationPort, "acknowledge_decision_fixture",
                                       return_value=ack):
                    o = self.run_sim(port=port)
                self.assertRefused(o, sim.SIM_DECISION_ACK_MALFORMED, port)


class UpstreamEvidenceIsNotAuthorityTests(SimulationCase):
    """Real 4D/4E objects offered in place of the decision fixture."""

    def assertNotAuthority(self, evidence, code):
        port = make_port()
        o = self.run_sim(decision=evidence, port=port)
        self.assertRefused(o, code, port)
        self.assertEqual(port.call_log(), ())
        self.assertEqual(port.consumed_fixture_ids(), ())
        return o

    def test_4d_candidate_for_human_review_is_not_sufficient(self):
        report, record = twra.fixture()
        assessment = twra.candidate(report)
        self.assertEqual(assessment.classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)
        for evidence in (assessment, report, assessment.facts, forge(assessment, authorizes_action=True),
                         forge(assessment, deletion_authorized=True)):
            with self.subTest(evidence=type(evidence).__name__):
                self.assertNotAuthority(evidence, sim.SIM_4D_ASSESSMENT_NOT_AUTHORITY)

    def test_4e_02a_proposal_is_not_authority(self):
        report, record = twra.fixture()
        proposal = wra.build_retirement_proposal(report, record, host_id=twra.HOST)
        for evidence in (proposal, proposal.target, proposal.scope, forge(proposal, authorizes_action=True)):
            with self.subTest(evidence=type(evidence).__name__):
                self.assertNotAuthority(evidence, sim.SIM_4E_PROPOSAL_NOT_AUTHORITY)

    def test_4e_02b_signature_verification_is_not_authority(self):
        verification = rha.RetirementCommandVerification(
            schema=rha.VERIFICATION_SCHEMA, status=rha.STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING, reason_codes=(),
            signature_verified=True, source_records_revalidated=True, command_id="retire-cmd-1",
            key_id="fcp4e02b-retire-key-1", director_id="director-1", host_id_label=HOST,
            proposal_digest="1" * 64, command_message_digest="2" * 64)
        for evidence in (verification, forge(verification, authorizes_action=True), b'{"command": {}}'):
            with self.subTest(evidence=type(evidence).__name__):
                self.assertNotAuthority(evidence, sim.SIM_4E_VERIFICATION_NOT_AUTHORITY)

    def test_4e_02d_dry_run_evidence_consistent_is_not_live_authority(self):
        names = [f.name for f in dataclasses.fields(rcm.RetirementEvidenceComposition) if f.init]
        values = {n: None for n in names}
        values.update(schema=rcm.COMPOSITION_SCHEMA, status=rcm.STATUS_DRY_RUN_EVIDENCE_CONSISTENT, reason_codes=(),
                      proposal_findings=(), command_verification_codes=(), ledger_codes=(), manifest_codes=(),
                      signature_verified=True, source_records_revalidated=True, ledger_evidence_present=True,
                      manifest_signature_verified=True)
        composition = rcm.RetirementEvidenceComposition(**values)
        self.assertEqual(composition.status, "DRY_RUN_EVIDENCE_CONSISTENT")
        forged = forge(composition, authorizes_action=True, deletion_authorized=True, issued=True, consumed=True,
                       host_identity_authenticated=True, queue_scope_attested=True)
        for evidence in (composition, forged):
            with self.subTest(forged=evidence is forged):
                o = self.assertNotAuthority(evidence, sim.SIM_4E_DRY_RUN_EVIDENCE_NOT_AUTHORITY)
                self.assertIs(o.authorizes_action, False)
                self.assertIs(o.issued, False)
                self.assertIs(o.consumed, False)

    def test_a_valid_fixture_never_promotes_upstream_evidence(self):
        # Even with a valid fixture, a completed simulation states nothing real.
        o = self.run_sim()
        self.assertEqual(o.state, sim.COMPLETED_SIMULATED)
        self.assertNotIn(wr.CANDIDATE_FOR_HUMAN_REVIEW, o.reason_codes)
        self.assertNotIn(rcm.STATUS_DRY_RUN_EVIDENCE_CONSISTENT, o.reason_codes)
        self.assertIs(o.human_approval_present, False)
        self.assertIs(o.deletion_authorized, False)


# ---------------------------------------------------------------------------
# 4. Gate 3: simulated lease
# ---------------------------------------------------------------------------

class LeaseTests(SimulationCase):
    def test_missing_simulated_lease_refuses_before_any_revalidation(self):
        port = make_port(sim.SimulationFaults(lease_unavailable=True))
        o = self.run_sim(port=port)
        self.assertRefused(o, sim.SIM_LEASE_UNAVAILABLE, port)
        self.assertEqual([s for s, _ in port.call_log()], [sim.STEP_CHECK_DECISION, sim.STEP_ACQUIRE_LEASE])
        self.assertIsNone(o.lease_id)
        self.assertEqual(port.consumed_fixture_ids(), ())

    def test_lease_held_by_another_attempt_is_unavailable(self):
        port = make_port()
        foreign = port.acquire_simulated_lease("0" * 64, "sim-lease:" + TARGET_ID)
        o = self.run_sim(port=port)
        self.assertEqual(o.state, sim.REFUSED_SIMULATED)
        self.assertIn(sim.SIM_LEASE_UNAVAILABLE, o.reason_codes)
        self.assertEqual(port.effect_events(), ())
        self.assertEqual(port.held_leases(), (foreign.lease_id,))   # never released by someone else

    def test_invalid_lease_window_is_refused_and_released(self):
        for ttl, code in ((sim.MAX_LEASE_SECONDS + 1, sim.SIM_LEASE_INVALID), (0, sim.SIM_LEASE_INVALID)):
            with self.subTest(ttl=ttl):
                port = make_port(sim.SimulationFaults(lease_ttl_seconds=ttl))
                o = self.run_sim(port=port)
                self.assertRefused(o, code, port)
                self.assertIn(sim.STEP_RELEASE_LEASE, [s.step for s in o.step_trace])

    def test_malformed_leases_are_refused(self):
        req = make_request()
        bad = (sim.SimulatedLease("sim-lease-9", "0" * 64, "sim-lease:" + TARGET_ID, stamp(T0),
                                  stamp(T0 + timedelta(seconds=60))),
               sim.SimulatedLease("sim-lease-9", req.attempt_id, "sim-lease:other", stamp(T0),
                                  stamp(T0 + timedelta(seconds=60))),
               sim.SimulatedLease("sim-lease-9", req.attempt_id, "sim-lease:" + TARGET_ID, "now", "later"),
               "lease", True)
        for lease in bad:
            with self.subTest(lease=lease):
                port = make_port()
                with mock.patch.object(sim.InMemoryRetirementSimulationPort, "acquire_simulated_lease",
                                       return_value=lease):
                    o = self.run_sim(port=port)
                self.assertRefused(o, sim.SIM_LEASE_INVALID, port)

    def test_lease_expiring_before_the_effect_refuses_after_consumption_without_effect(self):
        port = make_port(sim.SimulationFaults(lease_ttl_seconds=20))
        clock = Clock(T0, T0, T0, T0 + timedelta(seconds=5), T0 + timedelta(seconds=25))
        o = self.run_sim(port=port, clock=clock)
        self.assertRefused(o, sim.SIM_LEASE_EXPIRED, port)
        self.assertIs(o.simulated_consumed, True)          # the fixture is burned ...
        self.assertEqual(port.consumed_fixture_ids(), (FIXTURE,))
        self.assertEqual(o.state_trace[-2:], (sim.CONSUMED_SIMULATED, sim.REFUSED_SIMULATED))  # ... no effect

    def test_lease_expired_at_revalidation_is_refused_before_consumption(self):
        port = make_port(sim.SimulationFaults(lease_ttl_seconds=20))
        clock = Clock(T0, T0, T0, T0 + timedelta(seconds=21))
        o = self.run_sim(port=port, clock=clock)
        self.assertRefused(o, sim.SIM_LEASE_EXPIRED, port)
        self.assertEqual(port.consumed_fixture_ids(), ())


# ---------------------------------------------------------------------------
# 5. Gate 4: fresh simulated revalidation
# ---------------------------------------------------------------------------

class FreshRevalidationTests(SimulationCase):
    def assertFreshRefused(self, code, port):
        o = self.run_sim(port=port)
        self.assertRefused(o, code, port)
        self.assertEqual(port.consumed_fixture_ids(), ())
        self.assertNotIn(sim.STEP_CONSUME, [s for s, _ in port.call_log()])
        self.assertIs(o.simulated_fresh_revalidated, False)
        self.assertIs(o.simulated_lease_held, True)
        return o

    def test_identity_drift_is_refused(self):
        cases = ((("worktree_label", "sim://fcp4f01/worktrees/elsewhere"), sim.SIM_FRESH_WORKTREE_MISMATCH),
                 (("head_ref", "refs/heads/feature/renamed"), sim.SIM_FRESH_BRANCH_MISMATCH),
                 (("head_sha", "d" * 40), sim.SIM_FRESH_HEAD_SHA_MISMATCH),
                 (("base_ref", "refs/heads/main"), sim.SIM_FRESH_BASE_MISMATCH),
                 (("base_sha", "e" * 40), sim.SIM_FRESH_BASE_SHA_MISMATCH))
        for (name, value), code in cases:
            with self.subTest(name=name):
                self.assertFreshRefused(code, make_port(worktree_changes={name: value}))
                self.assertFreshRefused(code, make_port(sim.SimulationFaults(fresh_overrides=((name, value),))))

    def test_target_state_drift_is_refused(self):
        for changes, code in (({"registered": False}, sim.SIM_FRESH_TARGET_NOT_REGISTERED),
                              ({"clean": False}, sim.SIM_FRESH_TARGET_DIRTY),
                              ({"locked": True}, sim.SIM_FRESH_TARGET_LOCKED)):
            with self.subTest(code=code):
                self.assertFreshRefused(code, make_port(worktree_changes=changes))

    def test_absent_mismatched_or_unattested_host_identity_is_refused(self):
        self.assertFreshRefused(sim.SIM_HOST_IDENTITY_ABSENT, make_port(host_label=None))
        self.assertFreshRefused(sim.SIM_HOST_IDENTITY_MISMATCH, make_port(host_label="sim-host-02"))
        self.assertFreshRefused(sim.SIM_HOST_IDENTITY_NOT_ATTESTED_SIMULATED, make_port(host_identity_attested=False))
        self.assertFreshRefused(sim.SIM_FRESH_MALFORMED,
                                make_port(sim.SimulationFaults(fresh_overrides=(("host_label", 7),))))

    def test_absent_or_incomplete_queue_attestations_are_refused(self):
        one = (sim.SimulatedQueueAttestation(QUEUE_MAIN, 0, True),)
        extra = queues() + (sim.SimulatedQueueAttestation("sim://fcp4f01/queues/extra", 0, True),)
        cases = ((dict(queue_attestations=()), sim.SIM_QUEUE_ATTESTATION_ABSENT),
                 (dict(queue_attestations_complete=False), sim.SIM_QUEUE_ATTESTATION_INCOMPLETE),
                 (dict(queue_attestations=one), sim.SIM_QUEUE_ATTESTATION_INCOMPLETE),
                 (dict(queue_attestations=queues(attested=False)), sim.SIM_QUEUE_ATTESTATION_INCOMPLETE),
                 (dict(queue_attestations=queues() + queues()[:1]), sim.SIM_QUEUE_ATTESTATION_INCOMPLETE),
                 (dict(queue_attestations=queues(pending=1)), sim.SIM_QUEUE_NOT_EMPTY),
                 (dict(queue_attestations=(sim.SimulatedQueueAttestation(str(REPO_ROOT), 0, True),)),
                  sim.SIM_QUEUE_ATTESTATION_MALFORMED),
                 (dict(queue_attestations=(sim.SimulatedQueueAttestation(QUEUE_MAIN, -1, True),)),
                  sim.SIM_QUEUE_ATTESTATION_MALFORMED),
                 (dict(queue_attestations=(sim.SimulatedQueueAttestation(QUEUE_MAIN, True, True),)),
                  sim.SIM_QUEUE_ATTESTATION_MALFORMED),
                 (dict(queue_attestations=("queue",)), sim.SIM_QUEUE_ATTESTATION_MALFORMED))
        for changes, code in cases:
            with self.subTest(code=code, changes=changes):
                self.assertFreshRefused(code, make_port(**changes))
        self.assertEqual(self.run_sim(port=make_port(queue_attestations=extra)).state, sim.COMPLETED_SIMULATED)

    def test_stale_or_future_observations_are_refused(self):
        self.assertFreshRefused(sim.SIM_FRESH_STALE,
                                make_port(sim.SimulationFaults(observation_age_seconds=sim.MAX_FRESHNESS_SECONDS + 1)))
        self.assertFreshRefused(sim.SIM_FRESH_FROM_FUTURE, make_port(sim.SimulationFaults(
            fresh_overrides=(("observed_at", stamp(T0 + timedelta(seconds=1))),))))
        self.assertFreshRefused(sim.SIM_FRESH_MALFORMED,
                                make_port(sim.SimulationFaults(fresh_overrides=(("observed_at", "recently"),))))
        ok = make_port(sim.SimulationFaults(observation_age_seconds=sim.MAX_FRESHNESS_SECONDS))
        self.assertEqual(self.run_sim(port=ok).state, sim.COMPLETED_SIMULATED)

    def test_snapshot_bound_to_another_attempt_or_malformed_is_refused(self):
        self.assertFreshRefused(sim.SIM_FRESH_BINDING_MISMATCH,
                                make_port(sim.SimulationFaults(fresh_overrides=(("attempt_id", "0" * 64),))))
        self.assertFreshRefused(sim.SIM_FRESH_BINDING_MISMATCH,
                                make_port(sim.SimulationFaults(fresh_overrides=(("target_id", "wt-other"),))))
        for pairs in ((("registered", 1),), (("schema", "v0"),), (("queue_attestations", []),),
                      (("other_worktrees_digest", "x"),)):
            with self.subTest(pairs=pairs):
                self.assertFreshRefused(sim.SIM_FRESH_MALFORMED,
                                        make_port(sim.SimulationFaults(fresh_overrides=pairs)))

    def test_revocation_between_check_and_consumption_is_refused(self):
        port = make_port(sim.SimulationFaults(revoke_on_recheck=True))
        o = self.run_sim(port=port)
        self.assertRefused(o, sim.SIM_DECISION_REVOKED, port)
        self.assertEqual(port.consumed_fixture_ids(), ())

    def test_fixture_expiring_between_check_and_consumption_is_refused(self):
        fx = make_fixture(issued=T0 - timedelta(seconds=10), expires=T0 + timedelta(seconds=10))
        port = make_port()
        o = self.run_sim(decision=fx, port=port, clock=Clock(T0, T0, T0, T0 + timedelta(seconds=11)))
        self.assertRefused(o, sim.SIM_DECISION_EXPIRED, port)
        self.assertEqual(o.step_trace[-2].step, sim.STEP_RECHECK_DECISION)
        self.assertEqual(port.consumed_fixture_ids(), ())

    def test_simulated_clock_regression_is_refused(self):
        for instants, step in (((T0, T0 - timedelta(seconds=1)), sim.STEP_ACQUIRE_LEASE),
                               ((T0, T0, T0 - timedelta(seconds=1)), sim.STEP_FRESH_REVALIDATE),
                               ((T0, T0, T0, T0 - timedelta(seconds=1)), sim.STEP_RECHECK_DECISION),
                               ((T0, T0, T0, T0, T0 - timedelta(seconds=1)), sim.STEP_EFFECT)):
            with self.subTest(step=step):
                port = make_port()
                o = self.run_sim(port=port, clock=Clock(*instants))
                self.assertRefused(o, sim.SIM_CLOCK_REGRESSION, port)
                self.assertIn(sim.SimulationStep(step, sim.SIM_CLOCK_REGRESSION), o.step_trace)


# ---------------------------------------------------------------------------
# 6. Gates 5-7: consumption, ONE effect, postcondition; port faults
# ---------------------------------------------------------------------------

class ConsumptionAndEffectTests(SimulationCase):
    def test_port_exceptions_before_the_effect_refuse_without_effect(self):
        for step in sim.STEP_ORDER[1:6]:
            with self.subTest(step=step):
                port = make_port(sim.SimulationFaults(raise_at=(step,)))
                o = self.run_sim(port=port)
                self.assertRefused(o, sim.SIM_PORT_FAILED, port)
                self.assertIn(sim.SimulationStep(step, sim.SIM_PORT_FAILED), o.step_trace)
                self.assertEqual([s for s, _ in port.call_log()].count(step), 1)

    def test_consumption_failure_burns_the_attempt_and_never_effects(self):
        port = make_port(sim.SimulationFaults(raise_at=(sim.STEP_CONSUME,)))
        o = self.run_sim(port=port)
        self.assertRefused(o, sim.SIM_CONSUMPTION_FAILED, port)
        self.assertIs(o.simulated_consumed, False)
        for receipt in (None, "ok", sim.SimulatedConsumption("CONSUMED", "c-1", make_request().attempt_id, FIXTURE),
                        sim.SimulatedConsumption(sim.CONSUMPTION_RECORDED, "c-1", "0" * 64, FIXTURE),
                        sim.SimulatedConsumption(sim.CONSUMPTION_RECORDED, "c 1", make_request().attempt_id,
                                                 FIXTURE)):
            with self.subTest(receipt=receipt):
                port = make_port()
                with mock.patch.object(sim.InMemoryRetirementSimulationPort, "consume_simulated_single_use",
                                       return_value=receipt):
                    o = self.run_sim(port=port)
                self.assertRefused(o, sim.SIM_CONSUMPTION_FAILED, port)

    def test_consumption_replay_is_refused_even_if_acknowledgements_are_stale(self):
        port = make_port()
        port.consume_simulated_single_use(make_request().attempt_id, FIXTURE)
        stale = sim.SimulatedDecisionAck(sim.ACK_ACCEPTED, make_request().attempt_id, FIXTURE)
        with mock.patch.object(sim.InMemoryRetirementSimulationPort, "acknowledge_decision_fixture",
                               return_value=stale), \
                mock.patch.object(sim.InMemoryRetirementSimulationPort, "recheck_decision_fixture",
                                  return_value=stale):
            o = self.run_sim(port=port)
        self.assertRefused(o, sim.SIM_REPLAY_DETECTED, port)

    def test_exception_at_the_effect_call_is_uncertain_and_never_retried(self):
        port = make_port(sim.SimulationFaults(raise_at=(sim.STEP_EFFECT,)))
        o = self.run_sim(port=port)
        self.assertUncertain(o, sim.SIM_EFFECT_OUTCOME_UNKNOWN, port)
        self.assertIn(sim.SIM_PORT_FAILED, o.reason_codes)
        self.assertIn(sim.SIM_POSTCHECK_MISMATCH, o.reason_codes)   # nothing happened, but it is not claimed
        self.assertEqual(port.effect_events(), ())
        self.assertIs(o.simulated_effect_recorded, False)

    def test_exception_after_the_effect_is_uncertain_with_one_event(self):
        port = make_port(sim.SimulationFaults(raise_at=(sim.FAULT_AFTER_EFFECT,)))
        o = self.run_sim(port=port)
        self.assertUncertain(o, sim.SIM_EFFECT_OUTCOME_UNKNOWN, port)
        self.assertEqual(len(port.effect_events()), 1)
        self.assertIsNone(o.effect_id)
        self.assertIs(o.simulated_effect_recorded, False)

    def test_unknown_or_contradictory_effect_answers_are_uncertain(self):
        for status, code in ((sim.EFFECT_UNKNOWN, sim.SIM_EFFECT_OUTCOME_UNKNOWN),
                             (sim.EFFECT_REFUSED, sim.SIM_EFFECT_REFUSED_BY_PORT)):
            with self.subTest(status=status):
                port = make_port(sim.SimulationFaults(effect_status=status))
                o = self.run_sim(port=port)
                self.assertUncertain(o, code, port)
                self.assertEqual(len(port.effect_events()), 1)   # the port applied it anyway
        req = make_request()
        for report in (None, sim.SimulatedEffectReport(sim.EFFECT_RECORDED, None, req.attempt_id, TARGET_ID),
                       sim.SimulatedEffectReport(sim.EFFECT_RECORDED, "e-1", "0" * 64, TARGET_ID),
                       sim.SimulatedEffectReport(sim.EFFECT_UNKNOWN, "e-1", req.attempt_id, TARGET_ID),
                       sim.SimulatedEffectReport("DONE", "e-1", req.attempt_id, TARGET_ID)):
            with self.subTest(report=report):
                port = make_port()
                with mock.patch.object(sim.InMemoryRetirementSimulationPort, "apply_simulated_effect",
                                       return_value=report):
                    o = self.run_sim(port=port)
                self.assertEqual(o.state, sim.UNCERTAIN_SIMULATED)
                self.assertEqual(o.simulated_effect_calls, 1)

    def test_postcondition_unread_or_mismatched_is_uncertain(self):
        port = make_port(sim.SimulationFaults(raise_at=(sim.STEP_POSTCHECK,)))
        o = self.run_sim(port=port)
        self.assertUncertain(o, sim.SIM_POSTCHECK_UNREAD, port)
        self.assertIs(o.simulated_effect_recorded, True)
        cases = (("registered", True), ("branch_ref_present", False), ("branch_head_sha", "d" * 40),
                 ("other_worktrees_digest", "0" * 64), ("effect_events_for_target", 2),
                 ("effect_events_for_target", 0), ("worktree_label", "sim://fcp4f01/worktrees/x"),
                 ("attempt_id", "0" * 64), ("registered", 0), ("schema", "v0"))
        for name, value in cases:
            with self.subTest(name=name, value=value):
                port = make_port(sim.SimulationFaults(post_overrides=((name, value),)))
                o = self.run_sim(port=port)
                self.assertUncertain(o, sim.SIM_POSTCHECK_MISMATCH, port)
                self.assertIn(sim.SimulationStep(sim.STEP_POSTCHECK, sim.SIM_POSTCHECK_MISMATCH), o.step_trace)

    def test_lease_release_failure_is_reported(self):
        port = make_port(sim.SimulationFaults(raise_at=(sim.STEP_RELEASE_LEASE,)))
        o = self.run_sim(port=port)
        self.assertEqual(o.state, sim.COMPLETED_SIMULATED)
        self.assertIn(sim.SIM_LEASE_RELEASE_FAILED, o.reason_codes)

    def test_internal_errors_never_escape(self):
        with mock.patch.object(sim, "fresh_errors", side_effect=RuntimeError("bug")):
            port = make_port()
            o = self.run_sim(port=port)
        self.assertRefused(o, sim.SIM_INTERNAL_ERROR, port)
        with mock.patch.object(sim, "_postcheck_ok", side_effect=RuntimeError("bug")):
            port = make_port()
            o = self.run_sim(port=port)
        self.assertUncertain(o, sim.SIM_INTERNAL_ERROR, port)
        with mock.patch.object(sim, "request_errors", side_effect=RuntimeError("bug")):
            o = sim.simulate_retirement(make_request(), make_fixture(), make_port(), clock=Clock())
        self.assertSound(o)
        self.assertRefused(o, sim.SIM_REQUEST_MALFORMED)


class ReplayAndNoRetryTests(SimulationCase):
    def test_sequential_replay_never_double_consumes_or_double_effects(self):
        port = make_port()
        first = self.run_sim(port=port)
        self.assertEqual(first.state, sim.COMPLETED_SIMULATED)
        for _ in range(3):
            o = self.run_sim(port=port)
            self.assertRefused(o, sim.SIM_DECISION_ALREADY_CONSUMED)
        self.assertEqual(len(port.effect_events()), 1)
        self.assertEqual([s for s, _ in port.call_log()].count(sim.STEP_CONSUME), 1)
        self.assertEqual(port.consumed_fixture_ids(), (FIXTURE,))

    def test_a_second_fixture_for_an_already_retired_target_is_refused(self):
        port = make_port(fixtures=(FIXTURE, "fixture-2"))
        self.assertEqual(self.run_sim(port=port).state, sim.COMPLETED_SIMULATED)
        o = self.run_sim(decision=make_fixture(fixture_id="fixture-2"), port=port)
        self.assertRefused(o, sim.SIM_FRESH_TARGET_NOT_REGISTERED)
        self.assertEqual(len(port.effect_events()), 1)
        self.assertEqual(port.consumed_fixture_ids(), (FIXTURE,))

    def test_after_uncertainty_a_rerun_is_refused_and_never_effects_again(self):
        for faults in (sim.SimulationFaults(raise_at=(sim.FAULT_AFTER_EFFECT,)),
                       sim.SimulationFaults(raise_at=(sim.STEP_EFFECT,)),
                       sim.SimulationFaults(effect_status=sim.EFFECT_UNKNOWN)):
            with self.subTest(faults=faults):
                port = make_port(faults)
                o = self.run_sim(port=port)
                self.assertEqual(o.state, sim.UNCERTAIN_SIMULATED)
                self.assertIs(o.retry_allowed, False)
                again = self.run_sim(port=port)
                self.assertRefused(again, sim.SIM_DECISION_ALREADY_CONSUMED)
                self.assertEqual([s for s, _ in port.call_log()].count(sim.STEP_EFFECT), 1)
                self.assertLessEqual(len(port.effect_events()), 1)

    def test_the_in_memory_port_refuses_an_unconsumed_or_unleased_effect(self):
        port = make_port()
        req = make_request()
        report = port.apply_simulated_effect(req.attempt_id, TARGET_ID, "sim-consumption-1", "sim-lease-1")
        self.assertEqual(report.status, sim.EFFECT_REFUSED)
        receipt = port.consume_simulated_single_use(req.attempt_id, FIXTURE)
        report = port.apply_simulated_effect(req.attempt_id, TARGET_ID, receipt.consumption_id, "sim-lease-x")
        self.assertEqual(report.status, sim.EFFECT_REFUSED)
        self.assertEqual(port.consume_simulated_single_use(req.attempt_id, FIXTURE).status, sim.CONSUMPTION_REPLAY)
        self.assertEqual(port.effect_events(), ())


class ConcurrencyTests(SimulationCase):
    def test_a_concurrent_attempt_while_the_lease_is_held_is_refused(self):
        granted, resume = threading.Event(), threading.Event()
        port = make_port(sim.SimulationFaults(pause_after_lease=(granted, resume)))
        results = {}
        worker = threading.Thread(target=lambda: results.setdefault("a", sim.simulate_retirement(
            make_request(), make_fixture(), port, clock=Clock())))
        worker.start()
        try:
            self.assertTrue(granted.wait(5))
            b = self.run_sim(port=port)
            self.assertRefused(b, sim.SIM_LEASE_UNAVAILABLE)
            self.assertEqual(port.effect_events(), ())
        finally:
            resume.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertSound(results["a"])
        self.assertEqual(results["a"].state, sim.COMPLETED_SIMULATED)
        self.assertEqual(len(port.effect_events()), 1)
        self.assertEqual(port.held_leases(), ())

    def race(self, port, decisions):
        start = threading.Barrier(len(decisions))
        outcomes, errors = [None] * len(decisions), []

        def attempt(i):
            try:
                start.wait(5)
                outcomes[i] = sim.simulate_retirement(make_request(), decisions[i], port, clock=Clock())
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(len(decisions))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(errors, [])
        self.assertFalse(any(t.is_alive() for t in threads))
        for o in outcomes:
            self.assertSound(o)
        return outcomes

    def test_racing_attempts_with_one_fixture_admit_at_most_one_effect(self):
        for _ in range(5):
            port = make_port()
            outcomes = self.race(port, [make_fixture()] * 16)
            states = [o.state for o in outcomes]
            self.assertEqual(states.count(sim.COMPLETED_SIMULATED), 1, states)
            self.assertEqual(states.count(sim.REFUSED_SIMULATED), 15, states)
            self.assertEqual(len(port.effect_events()), 1)
            self.assertEqual(sum(o.simulated_effect_calls for o in outcomes), 1)
            self.assertEqual(port.consumed_fixture_ids(), (FIXTURE,))
            self.assertEqual(port.held_leases(), ())

    def test_racing_attempts_with_distinct_fixtures_admit_at_most_one_effect(self):
        ids = tuple("fixture-%d" % i for i in range(8))
        for _ in range(5):
            port = make_port(fixtures=ids)
            outcomes = self.race(port, [make_fixture(fixture_id=i) for i in ids])
            self.assertEqual([o.state for o in outcomes].count(sim.COMPLETED_SIMULATED), 1)
            self.assertEqual(len(port.effect_events()), 1)
            self.assertEqual(sum(o.simulated_effect_calls for o in outcomes), 1)
            self.assertLessEqual(len(port.consumed_fixture_ids()), len(ids))
            self.assertEqual(port.held_leases(), ())


# ---------------------------------------------------------------------------
# 7. Invariant checker, immutability and schema
# ---------------------------------------------------------------------------

class InvariantCheckerTests(SimulationCase):
    def setUp(self):
        self.completed = self.run_sim()
        self.refused = self.run_sim(port=make_port(sim.SimulationFaults(lease_unavailable=True)))
        self.uncertain = self.run_sim(port=make_port(sim.SimulationFaults(effect_status=sim.EFFECT_UNKNOWN)))

    def assertViolates(self, outcome, code):
        self.assertIn(code, sim.outcome_invariant_errors(outcome))
        self.assertFalse(sim.verify_outcome(outcome))

    def test_sound_outcomes_verify(self):
        for o in (self.completed, self.refused, self.uncertain):
            self.assertTrue(sim.verify_outcome(o))

    def test_tampered_fingerprint_and_malformed_values(self):
        self.assertViolates(forge(self.completed, state=sim.REFUSED_SIMULATED), "INV_FINGERPRINT")
        for value in (None, object(), dataclasses.asdict(self.completed),
                      forge(self.completed, step_trace=("OK",)), forge(self.completed, step_trace=[])):
            self.assertEqual(sim.outcome_invariant_errors(value), ("INV_MALFORMED",))

    def test_real_world_flags_cannot_be_turned_on(self):
        for name, value in REAL_WORLD_FLAGS:
            with self.subTest(name=name):
                self.assertViolates(refingerprinted(self.completed, **{name: not value}), "INV_NOT_LIVE")
        self.assertViolates(refingerprinted(self.completed, unproven=()), "INV_NOT_LIVE")
        self.assertViolates(refingerprinted(self.completed, live_activation_blocker="ACTIVE"), "INV_NOT_LIVE")

    def test_state_trace_must_follow_the_transitions(self):
        c = self.completed
        bad = ((sim.CREATED, sim.CONSUMED_SIMULATED, sim.EFFECT_SIMULATED, sim.POSTCHECK_SIMULATED,
                sim.COMPLETED_SIMULATED),
               c.state_trace[:5] + (sim.EFFECT_SIMULATED,) + c.state_trace[5:],
               (sim.CHECKED,) + c.state_trace[1:], c.state_trace[:-1], c.state_trace + (sim.COMPLETED_SIMULATED,),
               list(c.state_trace))
        for trace in bad:
            with self.subTest(trace=trace):
                self.assertViolates(refingerprinted(c, state_trace=trace), "INV_STATE")
        self.assertViolates(refingerprinted(c, state="DELETED"), "INV_STATE")

    def test_consumption_must_precede_the_effect(self):
        c = self.completed
        swapped = (sim.CREATED, sim.CHECKED, sim.LEASE_SIMULATED, sim.FRESH_REVALIDATED_SIMULATED,
                   sim.EFFECT_SIMULATED, sim.CONSUMED_SIMULATED, sim.POSTCHECK_SIMULATED, sim.COMPLETED_SIMULATED)
        self.assertViolates(refingerprinted(c, state_trace=swapped), "INV_CONSUME_BEFORE_EFFECT")
        self.assertViolates(refingerprinted(c, simulated_consumed=False), "INV_CONSUME_BEFORE_EFFECT")
        self.assertViolates(refingerprinted(c, consumption_id=None), "INV_CONSUME_BEFORE_EFFECT")
        steps = list(c.step_trace)
        i, j = [s.step for s in steps].index(sim.STEP_CONSUME), [s.step for s in steps].index(sim.STEP_EFFECT)
        steps[i], steps[j] = steps[j], steps[i]
        self.assertViolates(refingerprinted(c, step_trace=tuple(steps)), "INV_CONSUME_BEFORE_EFFECT")
        self.assertViolates(refingerprinted(c, step_trace=tuple(steps)), "INV_STEP_ORDER")

    def test_effect_counts_refusals_and_uncertainty(self):
        self.assertViolates(refingerprinted(self.completed, simulated_effect_calls=2), "INV_EFFECT_CALLS")
        self.assertViolates(refingerprinted(self.refused, simulated_effect_calls=1), "INV_REFUSAL_WITH_EFFECT")
        self.assertViolates(refingerprinted(self.refused, simulated_effect_recorded=True), "INV_REFUSAL_WITH_EFFECT")
        self.assertViolates(refingerprinted(self.uncertain, human_reconciliation_required=False), "INV_UNCERTAIN")
        self.assertViolates(refingerprinted(self.refused, human_reconciliation_required=True), "INV_UNCERTAIN")
        codes = tuple(c for c in self.uncertain.reason_codes if c != sim.SIM_NO_RETRY_AFTER_UNCERTAINTY)
        self.assertViolates(refingerprinted(self.uncertain, reason_codes=codes), "INV_UNCERTAIN")

    def test_completion_requires_every_simulated_gate(self):
        for name in ("simulated_decision_checked", "simulated_lease_held", "simulated_fresh_revalidated",
                     "simulated_effect_recorded", "simulated_postcheck_confirmed"):
            with self.subTest(name=name):
                self.assertViolates(refingerprinted(self.completed, **{name: False}), "INV_COMPLETED_EVIDENCE")
        self.assertViolates(refingerprinted(self.completed, effect_id=None), "INV_COMPLETED_EVIDENCE")
        self.assertViolates(refingerprinted(self.uncertain, simulated_postcheck_confirmed=True),
                            "INV_COMPLETED_EVIDENCE")

    def test_reason_codes_and_steps_are_closed_vocabularies(self):
        c = self.completed
        for codes in (c.reason_codes + ("APPROVED",), c.reason_codes[:-1], c.reason_codes + c.reason_codes[:1],
                      list(c.reason_codes)):
            with self.subTest(codes=codes):
                self.assertViolates(refingerprinted(c, reason_codes=codes), "INV_REASON_CODES")
        for steps in (c.step_trace + (sim.SimulationStep("GIT_WORKTREE_REMOVE", sim.STEP_OK),),
                      c.step_trace + c.step_trace[-1:], tuple(reversed(c.step_trace))):
            with self.subTest(steps=steps):
                self.assertViolates(refingerprinted(c, step_trace=steps), "INV_STEP_ORDER")


class ImmutabilityAndSchemaTests(SimulationCase):
    VALUE_TYPES = (sim.SyntheticRetirementTarget, sim.SimulatedRetirementRequest, sim.SimulatedHumanDecisionFixture,
                   sim.SimulatedDecisionAck, sim.SimulatedLease, sim.SimulatedQueueAttestation,
                   sim.SimulatedInventorySnapshot, sim.SimulatedConsumption, sim.SimulatedEffectReport,
                   sim.SimulatedPostcondition, sim.SimulatedEffectEvent, sim.SimulatedWorktree,
                   sim.SimulationFaults, sim.SimulationStep, sim.SimulatedRetirementOutcome)

    def test_every_value_type_is_frozen(self):
        for cls in self.VALUE_TYPES:
            self.assertTrue(dataclasses.is_dataclass(cls), cls)
            self.assertTrue(cls.__dataclass_params__.frozen, cls)
        o = self.run_sim()
        for name in ("state", "authorizes_action", "consumed", "state_trace", "simulated_effect_calls"):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(o, name, None)
        self.assertIs(type(o.state_trace), tuple)
        self.assertIs(type(o.step_trace), tuple)
        self.assertIs(type(o.reason_codes), tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            o.step_trace[0].result = "CHANGED"

    def test_real_world_flags_are_not_constructor_arguments(self):
        init = {f.name for f in dataclasses.fields(sim.SimulatedRetirementOutcome) if f.init}
        for name, _ in REAL_WORLD_FLAGS:
            self.assertNotIn(name, init)
        self.assertNotIn("unproven", init)
        for cls, flags in ((sim.SimulatedHumanDecisionFixture, ("is_human_approval", "is_real_permit",
                                                                "authenticated", "authorizes_action",
                                                                "deletion_authorized")),
                           (sim.SimulatedRetirementRequest, ("authorizes_action",)),
                           (sim.SyntheticRetirementTarget, ("is_real_checkout",))):
            init = {f.name for f in dataclasses.fields(cls) if f.init}
            self.assertFalse(init & set(flags), cls)

    def test_outcome_schema_is_pinned(self):
        self.assertEqual([f.name for f in dataclasses.fields(sim.SimulatedRetirementOutcome)], [
            "schema", "state", "reason_codes", "state_trace", "step_trace", "attempt_id", "target_id", "fixture_id",
            "lease_id", "consumption_id", "effect_id", "simulated_effect_calls", "simulated_decision_checked",
            "simulated_lease_held", "simulated_fresh_revalidated", "simulated_consumed",
            "simulated_effect_recorded", "simulated_postcheck_confirmed", "human_reconciliation_required",
            "fingerprint", "unproven", "live_activation_blocker", "simulation_only",
            "retirement_authorization_live", "retirement_execution_capable", "authorizes_action",
            "deletion_authorized", "branch_deletion_authorized", "issued", "consumed",
            "host_identity_authenticated", "queue_scope_attested", "human_approval_present", "retry_allowed"])
        self.assertEqual(sim.OUTCOME_SCHEMA, "fcp4f01-simulated-retirement-outcome-v1")
        # Simulated progress is distinctly named; the real-world `consumed` stays False.
        o = self.run_sim()
        self.assertEqual((o.simulated_consumed, o.consumed), (True, False))
        self.assertNotIn("consumed", {f.name for f in dataclasses.fields(sim.SimulatedRetirementOutcome) if f.init})
        self.assertNotEqual(sim.CONSUMPTION_RECORDED, "CONSUMED")

    def test_state_machine_shape(self):
        self.assertEqual(sim.STATES[:8], (sim.CREATED, sim.CHECKED, sim.LEASE_SIMULATED,
                                          sim.FRESH_REVALIDATED_SIMULATED, sim.CONSUMED_SIMULATED,
                                          sim.EFFECT_SIMULATED, sim.POSTCHECK_SIMULATED, sim.COMPLETED_SIMULATED))
        self.assertEqual(set(sim.TERMINAL_STATES), {sim.COMPLETED_SIMULATED, sim.REFUSED_SIMULATED,
                                                    sim.UNCERTAIN_SIMULATED})
        for terminal in sim.TERMINAL_STATES:
            self.assertNotIn(terminal, sim.TRANSITIONS)
        # After the effect call, refusal is impossible: only uncertainty or completion.
        self.assertNotIn(sim.REFUSED_SIMULATED, sim.TRANSITIONS[sim.EFFECT_SIMULATED])
        self.assertNotIn(sim.REFUSED_SIMULATED, sim.TRANSITIONS[sim.POSTCHECK_SIMULATED])
        self.assertEqual(sim.TRANSITIONS[sim.CONSUMED_SIMULATED], (sim.EFFECT_SIMULATED, sim.REFUSED_SIMULATED))
        reachable = {s for targets in sim.TRANSITIONS.values() for s in targets}
        self.assertEqual(reachable, set(sim.STATES))

    def test_reason_codes_are_stable_unique_and_all_reachable(self):
        self.assertEqual(len(set(sim.REASON_CODES)), len(sim.REASON_CODES))
        self.assertTrue(all(c.startswith("SIM_") and c == getattr(sim, c) for c in sim.REASON_CODES))
        declared = {v for k, v in vars(sim).items() if k.startswith("SIM_") and type(v) is str}
        self.assertEqual(declared, set(sim.REASON_CODES))

    def test_no_code_in_the_module_produces_a_true_real_world_flag(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {n for n, _ in REAL_WORLD_FLAGS} - {"simulation_only"}
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg in names:
                self.assertNotEqual(ast.unparse(node.value), "True", node.arg)
        for line in ("RETIREMENT_AUTHORIZATION_LIVE = False", "RETIREMENT_EXECUTION_CAPABLE = False",
                     "SIMULATION_ONLY = True"):
            self.assertEqual(MODULE_PATH.read_text(encoding="utf-8").count(line), 1, line)


class ReasonCoverageTests(unittest.TestCase):
    def test_every_reason_code_is_exercised_by_an_adversarial_test(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        own = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == type(self).__name__)
        tree.body.remove(own)
        referenced = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                      and isinstance(n.value, ast.Name) and n.value.id == "sim"}
        self.assertEqual(sorted(set(sim.REASON_CODES) - referenced), [])


# ---------------------------------------------------------------------------
# 8. Live entry, isolation and side effects
# ---------------------------------------------------------------------------

class _Exploding:
    def __getattr__(self, name):
        raise AssertionError("argument read: " + name)

    def __bool__(self):
        raise AssertionError("argument read")

    def __eq__(self, other):
        raise AssertionError("argument read")

    __hash__ = None


def _code_without_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


class GuardedEnvironment:
    """Patches every process, network and filesystem-mutation entry point
    with recording mocks; `calls()` lists any that were used."""

    TARGETS = ((subprocess, "Popen"), (subprocess, "run"), (subprocess, "call"), (subprocess, "check_output"),
               (os, "system"), (os, "popen"), (os, "remove"), (os, "unlink"), (os, "rmdir"), (os, "removedirs"),
               (os, "rename"), (os, "replace"), (os, "mkdir"), (os, "makedirs"), (os, "chmod"),
               (shutil, "rmtree"), (shutil, "move"), (shutil, "copy"), (socket, "socket"),
               (socket, "create_connection"), (builtins, "open"), (io, "open"),
               (pathlib.Path, "unlink"), (pathlib.Path, "rmdir"), (pathlib.Path, "mkdir"),
               (pathlib.Path, "write_text"), (pathlib.Path, "write_bytes"), (pathlib.Path, "touch"),
               (pathlib.Path, "rename"), (pathlib.Path, "replace"))

    def __enter__(self):
        self.patches = [mock.patch.object(owner, name, autospec=False) for owner, name in self.TARGETS]
        self.mocks = [(f"{getattr(owner, '__name__', owner)}.{name}", p.start())
                      for p, (owner, name) in zip(self.patches, self.TARGETS)]
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()

    def calls(self):
        return [name for name, m in self.mocks if m.called]


class LiveEntryAndIsolationTests(SimulationCase):
    def test_execute_live_refuses_before_reading_any_argument(self):
        with GuardedEnvironment() as env:
            for args, kwargs in (((), {}), ((_Exploding(), _Exploding()), {"port": _Exploding()}),
                                 ((make_request(), make_fixture(), make_port()), {"clock": Clock()})):
                with self.assertRaises(sim.RetirementSimulationNotLive) as ctx:
                    sim.execute_live(*args, **kwargs)
                self.assertEqual(ctx.exception.code, sim.NOT_LIVE)
                self.assertEqual(str(ctx.exception), sim.NOT_LIVE)
            self.assertEqual(env.calls(), [])
        source = ast.unparse(_code_without_docstrings(ast.parse(MODULE_PATH.read_text(encoding="utf-8"))))
        body = re.search(r"def execute_live\(\*_args, \*\*_kwargs\):\n(.*?)(?=\ndef |\Z)", source, re.S).group(1)
        self.assertEqual(body.strip(), "raise RetirementSimulationNotLive()")

    def test_the_public_surface_has_no_operational_hook(self):
        public = sorted(n for n, v in vars(sim).items() if callable(v) and not n.startswith("_")
                        and getattr(v, "__module__", None) == sim.__name__)
        self.assertEqual(public, sorted([
            "InMemoryRetirementSimulationPort", "RetirementSimulationNotLive",
            "SimulatedConsumption", "SimulatedDecisionAck", "SimulatedEffectEvent", "SimulatedEffectReport",
            "SimulatedHumanDecisionFixture", "SimulatedInventorySnapshot", "SimulatedLease",
            "SimulatedPostcondition", "SimulatedQueueAttestation", "SimulatedRetirementOutcome",
            "SimulatedRetirementPort", "SimulatedRetirementRequest", "SimulatedWorktree", "SimulationFaults",
            "SimulationStep", "SyntheticRetirementTarget", "build_decision_fixture", "build_simulation_request",
            "build_synthetic_target", "decision_errors", "decision_seal", "execute_live", "fresh_errors",
            "is_synthetic_label", "outcome_fingerprint", "outcome_invariant_errors", "request_errors",
            "simulate_retirement", "target_digest", "target_errors", "verify_outcome"]))
        forbidden = re.compile(r"(?i)git|remove|delete|prune|rmtree|unlink|subprocess|shell|exec_|run_live")
        for name in public:
            self.assertIsNone(forbidden.search(name), name)
        port_methods = {n for n in vars(sim.InMemoryRetirementSimulationPort) if not n.startswith("_")}
        self.assertEqual(port_methods, {
            "port_kind", "effect_events", "call_log", "consumed_fixture_ids", "held_leases",
            "acknowledge_decision_fixture", "recheck_decision_fixture", "acquire_simulated_lease",
            "release_simulated_lease", "read_simulated_inventory", "consume_simulated_single_use",
            "apply_simulated_effect", "read_simulated_postcondition"})
        fault_fields = {f.name: f.type for f in dataclasses.fields(sim.SimulationFaults)}
        self.assertNotIn("Callable", " ".join(fault_fields.values()))

    def test_simulations_use_no_process_network_or_filesystem_write(self):
        scenarios = (make_port(), make_port(sim.SimulationFaults(raise_at=(sim.FAULT_AFTER_EFFECT,))),
                     make_port(sim.SimulationFaults(lease_unavailable=True)), make_port(fixtures=()),
                     make_port(sim.SimulationFaults(post_overrides=(("registered", True),))))
        with GuardedEnvironment() as env:
            states = []
            for port in scenarios:
                states.append(sim.simulate_retirement(make_request(), make_fixture(), port, clock=Clock()).state)
                sim.simulate_retirement(make_request(), make_target(), port, clock=Clock())
            self.assertEqual(env.calls(), [])
        self.assertEqual(states, [sim.COMPLETED_SIMULATED, sim.UNCERTAIN_SIMULATED, sim.REFUSED_SIMULATED,
                                  sim.REFUSED_SIMULATED, sim.UNCERTAIN_SIMULATED])

    def test_importing_the_module_has_no_side_effect(self):
        # A separate module object (dataclasses need it registered while it runs),
        # so the module under test and its classes are left untouched.
        name = "fcp4f01_isolated_import_probe"
        before = threading.active_count()
        spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
        probe = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.modules[name] = probe
        try:
            with GuardedEnvironment() as env:
                spec.loader.exec_module(probe)
                self.assertEqual(env.calls(), [])
        finally:
            sys.modules.pop(name, None)
            sys.dont_write_bytecode = previous
        self.assertEqual(threading.active_count(), before)
        self.assertIs(probe.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertFalse([n for n, v in vars(probe).items() if isinstance(v, probe.InMemoryRetirementSimulationPort)])
        self.assertNotIn("fcp4f01_isolated_import_probe", sys.modules)

    def test_source_imports_and_names_are_restricted(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(LEDGER_MODULE_NAME, source)   # 02c is named only by itself and the 02d reader
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {(None, a.name, a.asname) for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {(node.module, a.name, a.asname) for a in node.names}
        self.assertEqual(imported, {
            ("__future__", "annotations", None), (None, "dataclasses", None), (None, "os", None),
            (None, "re", None), (None, "sys", None), (None, "threading", None),
            ("dataclasses", "dataclass", None), ("dataclasses", "field", None), ("datetime", "datetime", None),
            ("datetime", "timedelta", None), ("datetime", "timezone", None), ("pathlib", "Path", None),
            ("typing", "Optional", None), ("typing", "Protocol", None),
            ("scripts.ai", "claude_runner", None), (None, "claude_runner", None),
            ("scripts.ai", "runner_worktree_retirement", "wr"), (None, "runner_worktree_retirement", "wr"),
            ("scripts.ai", "runner_worktree_retirement_authorization", "wra"),
            (None, "runner_worktree_retirement_authorization", "wra"),
            ("scripts.ai", "runner_worktree_retirement_host_authority", "rha"),
            (None, "runner_worktree_retirement_host_authority", "rha"),
            ("scripts.ai", "runner_worktree_retirement_host_composition", "rcm"),
            (None, "runner_worktree_retirement_host_composition", "rcm")})
        os_attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name) and n.value.id == "os"}
        self.assertEqual(os_attrs, {"path"})
        path_attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                      and isinstance(n.value, ast.Attribute) and n.value.attr == "path"
                      and isinstance(n.value.value, ast.Name) and n.value.value.id == "os"}
        self.assertEqual(path_attrs, {"isabs", "splitdrive"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "eval", "exec", "compile", "__import__", "globals", "setattr",
                                  "delattr", "importlib", "subprocess", "socket", "shutil", "sqlite3", "ctypes"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"system", "popen", "remove", "unlink", "rmdir", "rmtree", "rename", "write",
                                  "write_text", "write_bytes", "mkdir", "makedirs", "connect", "urlopen"})
        # Only the module's own sibling modules are used, and of the 02d module only its types/constants.
        rcm_attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                     and isinstance(n.value, ast.Name) and n.value.id == "rcm"}
        self.assertEqual(rcm_attrs, {"RetirementEvidenceComposition", "QueueScopeManifestVerification",
                                     "_exact_utc"})
        constants = {n.value for n in ast.walk(_code_without_docstrings(ast.parse(source)))
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for text in constants:
            self.assertNotRegex(text, r"(?i)\bgit\b|worktree remove|branch -[dD]|rm -|del /")

    def test_no_test_in_this_suite_is_skipped(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("skip", "skipIf", "skipUnless", "skipTest", "expectedFailure"))

    def test_neighbouring_sources_are_unchanged(self):
        for relative, digest in PINNED_SOURCES.items():
            data = (REPO_ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, relative)


# ---------------------------------------------------------------------------
# 9. CI
# ---------------------------------------------------------------------------

class CiWorkflowTests(unittest.TestCase):
    STEP = "FCP-4F-01 retirement executor simulation regression without skipped tests"
    MODULE = "scripts.tests.test_runner_worktree_retirement_executor_simulation"

    def setUp(self):
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def job(self, name):
        return re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.workflow).group(1)

    def test_nine_jobs_and_permissions_unchanged(self):
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", self.workflow))
        self.assertEqual(jobs, twra.CiWorkflowTests.JOBS)
        self.assertIn("permissions:\n  contents: read\n", self.workflow)
        self.assertEqual(self.workflow.count("permissions:"), 1)

    def test_suite_runs_once_zero_skip_in_the_host_trust_job(self):
        job = self.job("fcp3b2b2-host-trust")
        step = re.search(rf"(?ms)^      - name: {re.escape(self.STEP)}\n(.*?)(?=^      - name: |\Z)", job)
        self.assertIsNotNone(step)
        lines = step.group(0).rstrip("\n").split("\n")
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[1], "        run: |")
        for part in ("python -c ", f"unittest.defaultTestLoader.loadTestsFromName('{self.MODULE}')",
                     "print('RETIREMENT_SIMULATION_TESTS_SKIPPED=',len(r.skipped))",
                     "sys.exit(0 if r.wasSuccessful() and not r.skipped else 2)"):
            self.assertIn(part, lines[2], part)
        self.assertEqual(self.workflow.count("test_runner_worktree_retirement_executor_simulation"), 1)
        # After the 02c step; the merged 02d test requires 02d to remain the job's last step.
        self.assertLess(job.index("test_runner_worktree_retirement_host_ledger"), job.index(self.STEP))
        self.assertLess(job.index(self.STEP), job.index("FCP-4E-02d retirement evidence composition"))

    def test_predecessor_ci_contracts_still_hold(self):
        # The merged 02a/02b/02c/02d workflow assertions, unchanged, against this workflow
        # (`debug()` runs each case directly, without the 02d module fixtures).
        from scripts.tests import test_runner_worktree_retirement_host_composition as tcmp
        names = unittest.defaultTestLoader.getTestCaseNames(tcmp.CiWorkflowTests)
        self.assertEqual(len(names), 3)
        for name in names:
            tcmp.CiWorkflowTests(name).debug()


if __name__ == "__main__":
    unittest.main()
