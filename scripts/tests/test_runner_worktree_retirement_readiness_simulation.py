"""FCP-4F-02: retirement host readiness matrix (PURE ANALYSIS, SIMULATION ONLY, NOT LIVE).

Every outcome comes from the merged FCP-4F-01 simulator driven by its own
synthetic fixtures (`sim://fcp4f01/` labels, in-memory port); every
inventory is synthetic and declarative. Nothing here runs Git, touches a
worktree, a branch, a ledger, a process, the network or a real clock; the
side-effect tests patch those entry points and assert they are never
called. No assertion here may produce or expect a live verdict. Nothing
here is skipped.
"""

import ast
import copy
import dataclasses
import hashlib
import importlib.util
import json
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_worktree_retirement as wr
from scripts.ai import runner_worktree_retirement_authorization as wra
from scripts.ai import runner_worktree_retirement_executor_simulation as sim
from scripts.ai import runner_worktree_retirement_host_composition as rcm
from scripts.ai import runner_worktree_retirement_readiness_simulation as rd
from scripts.tests import test_runner_worktree_retirement_authorization as twra
from scripts.tests import test_runner_worktree_retirement_executor_simulation as tsim

MODULE_PATH = Path(rd.__file__)
TEST_PATH = Path(__file__).resolve()
REPO_ROOT = TEST_PATH.parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
# sha256 (LF-normalized) of the merged sources at 532c54b; 4F-02 must not change them.
PINNED_SOURCES = dict(tsim.PINNED_SOURCES, **{
    "scripts/ai/runner_worktree_retirement_executor_simulation.py":
        "37714ed7090a98bc979b33c36f9242c196046a3420108d6cf75bd5c912c37b12",
    "scripts/tests/test_runner_worktree_retirement_executor_simulation.py":
        "e49414076ff8ac2d29a47ef560fd96061e8f4273c451fde04a29747d71c559f1",
    "scripts/tests/test_runner_worktree_retirement_host_composition.py":
        "bc673b40ca3fba163a2a111d8a092c71aabda2961e3ae80eb9700caf5d28c51c",
})
LEDGER_MODULE_NAME = tsim.LEDGER_MODULE_NAME

DECLARED_AT = "2026-10-27T12:00:00Z"
ALL_REQUIREMENTS = rd.REQUIREMENTS

REAL_WORLD_FLAGS = (
    ("verdict", rd.LIVE_NOT_AUTHORIZED), ("live_status", rd.NOT_LIVE),
    ("host_accreditation", rd.HOST_ACCREDITATION_ABSENT), ("policy_status", rd.POLICY_D1_D12_PENDING_NOT_APPROVED),
    ("simulation_only", True), ("destructive_retry_forbidden", True), ("ready_for_live", False),
    ("retirement_authorization_live", False), ("retirement_execution_capable", False),
    ("authorizes_action", False), ("deletion_authorized", False), ("branch_deletion_authorized", False),
    ("issued", False), ("consumed", False), ("host_identity_authenticated", False),
    ("queue_scope_attested", False), ("file_acl_verified", False), ("clock_attested", False),
    ("policy_approved", False), ("human_approval_present", False), ("retry_allowed", False))


def outcome(faults=None, decision=tsim.DEFAULT, request=None, clock=None, **port_changes):
    request = tsim.make_request() if request is None else request
    decision = tsim.make_fixture(request) if decision is tsim.DEFAULT else decision
    port = tsim.make_port(faults, **port_changes)
    o = sim.simulate_retirement(request, decision, port, clock=clock or tsim.Clock())
    assert sim.verify_outcome(o)
    return o


def declare(requirement, claim, name=None):
    label = "sim://fcp4f01/evidence/%s/%s" % (requirement.lower(), (name or claim).lower())
    return rd.SyntheticEvidenceDeclaration(requirement, claim, label)


def proposed(*ids):
    return tuple(rd.SyntheticPolicyReference(i, rd.POLICY_STANCE_PROPOSED) for i in ids)


def inventory(o, declarations=(), policy_references=(), declared_at=DECLARED_AT, inventory_id="inv-1"):
    return rd.build_readiness_inventory(o, inventory_id=inventory_id, declared_at=declared_at,
                                        declarations=declarations, policy_references=policy_references)


def forge(obj, **changes):
    return tsim.forge(obj, **changes)


def refingerprinted(report, **changes):
    clone = forge(report, **changes)
    try:
        object.__setattr__(clone, "fingerprint", rd.report_fingerprint(clone))
    except (TypeError, AttributeError, ValueError):
        pass
    return clone


def every_asserted_claim():
    return tuple(declare(req, claim) for claim, req in rd.ASSERTED_CLAIMS.items())


class ReadinessCase(unittest.TestCase):
    def evaluate(self, o, inv=None):
        inv = inventory(o) if inv is None else inv
        report = rd.evaluate_readiness(o, inv)
        self.assertNeverLive(report)
        return report

    def assertNeverLive(self, report):
        self.assertIs(type(report), rd.RetirementReadinessReport)
        self.assertEqual(rd.readiness_report_invariant_errors(report), ())
        for name, value in REAL_WORLD_FLAGS:
            self.assertEqual(getattr(report, name), value, name)
            self.assertIs(type(getattr(report, name)), type(value), name)
        self.assertEqual(report.live_blockers, rd.LIVE_BLOCKERS)
        self.assertEqual(report.unproven, sim.SIMULATION_UNPROVEN)
        self.assertTrue(set(rd.ALWAYS_CODES) <= set(report.reason_codes))
        self.assertEqual(tuple(r.requirement for r in report.rows), ALL_REQUIREMENTS)
        for row in report.rows:
            self.assertIn(row.status, rd.STATUSES)
            self.assertIs(row.live_proven, False)
            self.assertIs(row.satisfied_for_live, False)
            self.assertTrue(row.missing_proofs)
        self.assertNotIn("READY", canonical_values(report))

    def assertInputRefused(self, report, code):
        self.assertEqual(report.simulation_assessment, rd.INPUT_REFUSED)
        self.assertIn(rd.READINESS_INPUT_REFUSED, report.reason_codes)
        self.assertIn(code, report.reason_codes)
        self.assertTrue(all(r.status == rd.REFUSED for r in report.rows))
        self.assertIsNone(report.inventory_digest)

    def status(self, report):
        return {r.requirement: r.status for r in report.rows}

    def row(self, report, requirement):
        return next(r for r in report.rows if r.requirement == requirement)


def canonical_values(report) -> str:
    """Every value of the report (keys excluded), for 'no ready value' checks."""
    values = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        else:
            values.append(str(v))
    walk(json.loads(rd.canonical_report_json(report)))
    return " ".join(values)


# ---------------------------------------------------------------------------
# 1. Nominal simulation: informational matrix, never live
# ---------------------------------------------------------------------------

class NominalMatrixTests(ReadinessCase):
    def test_completed_simulation_models_preconditions_only(self):
        o = outcome()
        self.assertEqual(o.state, sim.COMPLETED_SIMULATED)
        r = self.evaluate(o)
        self.assertEqual(r.simulation_assessment, rd.SIMULATION_PRECONDITIONS_MODELED)
        self.assertEqual((r.outcome_state, r.outcome_fingerprint, r.outcome_verified),
                         (sim.COMPLETED_SIMULATED, o.fingerprint, True))
        self.assertEqual(self.status(r), {
            rd.REQ_POLICY_D1_D12: rd.POLICY_PENDING, rd.REQ_SEPARATION_OF_DUTIES: rd.UNPROVEN,
            rd.REQ_HUMAN_APPROVAL: rd.SIMULATED_ONLY, rd.REQ_DISPOSABLE_SCOPE: rd.SIMULATED_ONLY,
            rd.REQ_HOST_IDENTITY: rd.SIMULATED_ONLY, rd.REQ_FILESYSTEM_IDENTITY: rd.UNPROVEN,
            rd.REQ_FILE_ACL: rd.UNPROVEN, rd.REQ_TRUSTED_CLOCK: rd.UNPROVEN, rd.REQ_QUEUE_SCOPE: rd.SIMULATED_ONLY,
            rd.REQ_EXTERNAL_LEASE: rd.SIMULATED_ONLY, rd.REQ_FRESH_REVALIDATION: rd.SIMULATED_ONLY,
            rd.REQ_SINGLE_USE_CONSUMPTION: rd.SIMULATED_ONLY,
            rd.REQ_UNCERTAINTY_AND_POSTCONDITION: rd.SIMULATED_ONLY, rd.REQ_RETENTION: rd.UNPROVEN})
        for row in r.rows:
            if row.status == rd.SIMULATED_ONLY:
                self.assertEqual(row.simulation_coverage, rd.COVERAGE_MODELED)
                self.assertIn(rd.READINESS_SIMULATED_BY_4F01_ONLY, row.reason_codes)
            self.assertEqual(row.missing_proofs, rd.MISSING_PROOFS[row.requirement])
            self.assertEqual(row.blocking_dependencies, ())
        for req in (rd.REQ_SEPARATION_OF_DUTIES, rd.REQ_FILESYSTEM_IDENTITY, rd.REQ_FILE_ACL, rd.REQ_RETENTION):
            self.assertEqual(self.row(r, req).simulation_coverage, rd.COVERAGE_NOT_MODELED)
            self.assertIn(rd.READINESS_NOT_MODELED_BY_SIMULATION, self.row(r, req).reason_codes)
        self.assertIs(r.human_reconciliation_required, False)
        self.assertEqual(r.outcome_invariant_codes, ())

    def test_modeled_preconditions_are_not_host_accreditation_or_policy_approval(self):
        r = self.evaluate(outcome())
        self.assertEqual(r.simulation_assessment, rd.SIMULATION_PRECONDITIONS_MODELED)
        self.assertEqual(r.host_accreditation, rd.HOST_ACCREDITATION_ABSENT)
        self.assertEqual(r.policy_status, rd.POLICY_D1_D12_PENDING_NOT_APPROVED)
        self.assertIn(rd.READINESS_SIMULATION_IS_NOT_HOST_ACCREDITATION, r.reason_codes)
        self.assertIn(rd.READINESS_NO_REAL_AUTHORIZATION, r.reason_codes)
        self.assertNotEqual(rd.SIMULATION_PRECONDITIONS_MODELED, rd.HOST_ACCREDITATION_ABSENT)
        self.assertIn("HOST01_ACCREDITATION_ABSENT", r.live_blockers)
        self.assertIn("HUMAN_RETIREMENT_POLICY_D1_D12_PENDING_NOT_APPROVED", r.live_blockers)

    def test_every_caller_field_filled_still_never_live(self):
        o = outcome()
        everything = every_asserted_claim() + tuple(
            declare(req, rd.CLAIM_NOT_INSPECTED) for req in ALL_REQUIREMENTS) + (
            declare(rd.REQ_HOST_IDENTITY, rd.CLAIM_HOST_ID_LABEL_ONLY),
            declare(rd.REQ_QUEUE_SCOPE, rd.CLAIM_EXTERNAL_QUEUE_UNCOVERED))
        claimed = tuple(rd.SyntheticPolicyReference(i, rd.POLICY_STANCE_CLAIMED_APPROVED)
                        for i in rd.POLICY_DECISION_IDS)
        r = self.evaluate(o, inventory(o, everything, claimed))
        self.assertEqual(r.simulation_assessment, rd.SIMULATION_GAPS_REFUSED)
        self.assertEqual(set(self.status(r).values()), {rd.REFUSED})
        self.assertEqual(r.verdict, rd.LIVE_NOT_AUTHORIZED)

    def test_status_and_verdict_vocabularies_hold_no_ready_or_permit_value(self):
        for vocabulary in (rd.STATUSES, rd.ASSESSMENTS, rd.REASON_CODES, rd.LIVE_BLOCKERS,
                           (rd.LIVE_NOT_AUTHORIZED, rd.NOT_LIVE, rd.HOST_ACCREDITATION_ABSENT,
                            rd.POLICY_D1_D12_PENDING_NOT_APPROVED)):
            for value in vocabulary:
                self.assertNotRegex(value, r"READY|PERMIT(?!_)|(?<!NOT_)AUTHORIZED$|(?<!NOT_)APPROVED$|GRANTED|ISSUED",
                                    value)
        self.assertIs(rd.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertIs(rd.RETIREMENT_EXECUTION_CAPABLE, False)
        self.assertIs(rd.SIMULATION_ONLY, True)


# ---------------------------------------------------------------------------
# 2. REFUSED_SIMULATED and UNCERTAIN_SIMULATED outcomes
# ---------------------------------------------------------------------------

class RefusedOutcomeTests(ReadinessCase):
    def assertRefusedAt(self, o, requirement):
        self.assertEqual(o.state, sim.REFUSED_SIMULATED)
        r = self.evaluate(o)
        self.assertEqual(r.simulation_assessment, rd.SIMULATION_REFUSED)
        row = self.row(r, requirement)
        self.assertEqual(row.status, rd.REFUSED, row)
        self.assertIn(rd.READINESS_REFUSED_BY_SIMULATION, row.reason_codes)
        statuses = self.status(r)
        for req in ALL_REQUIREMENTS:
            if requirement in rd.DEPENDENCIES[req]:
                self.assertIn(statuses[req], (rd.REFUSED, rd.BLOCKED_BY_DEPENDENCY), req)
        return r

    def test_refusals_land_on_the_obligation_they_speak_about(self):
        cases = (
            (dict(faults=sim.SimulationFaults(lease_unavailable=True)), rd.REQ_EXTERNAL_LEASE),
            (dict(decision=None), rd.REQ_HUMAN_APPROVAL),
            (dict(fixtures=()), rd.REQ_HUMAN_APPROVAL),
            (dict(host_label="sim-host-02"), rd.REQ_HOST_IDENTITY),
            (dict(host_identity_attested=False), rd.REQ_HOST_IDENTITY),
            (dict(queue_attestations=tsim.queues(pending=1)), rd.REQ_QUEUE_SCOPE),
            (dict(queue_attestations_complete=False), rd.REQ_QUEUE_SCOPE),
            (dict(worktree_changes={"clean": False}), rd.REQ_FRESH_REVALIDATION),
            (dict(clock=lambda: tsim.T0.replace(tzinfo=None)), rd.REQ_TRUSTED_CLOCK),
            (dict(faults=sim.SimulationFaults(raise_at=(sim.STEP_CONSUME,))), rd.REQ_SINGLE_USE_CONSUMPTION),
            (dict(faults=sim.SimulationFaults(raise_at=(sim.STEP_ACQUIRE_LEASE,))), rd.REQ_EXTERNAL_LEASE),
            (dict(faults=sim.SimulationFaults(revoke_on_recheck=True)), rd.REQ_HUMAN_APPROVAL),
        )
        for changes, requirement in cases:
            with self.subTest(requirement=requirement, changes=changes):
                self.assertRefusedAt(outcome(**changes), requirement)

    def test_refusal_before_the_port_marks_scope_refused_and_later_gates_unreached(self):
        request = sim.build_simulation_request(tsim.make_target(worktree_label="C:\\Users\\x\\wt"),
                                               host_label=tsim.HOST)
        o = sim.simulate_retirement(request, tsim.make_fixture(), tsim.make_port(), clock=tsim.Clock())
        self.assertIn(sim.SIM_TARGET_NOT_SYNTHETIC, o.reason_codes)
        r = self.assertRefusedAt(o, rd.REQ_DISPOSABLE_SCOPE)
        self.assertIn(rd.READINESS_GATE_NOT_REACHED_IN_SIMULATION, self.row(r, rd.REQ_HOST_IDENTITY).reason_codes)
        self.assertNotIn(rd.SIMULATED_ONLY, self.status(r).values())
        o = sim.simulate_retirement(forge(tsim.make_request(), simulation_marker="LIVE"), tsim.make_fixture(),
                                    tsim.make_port(), clock=tsim.Clock())
        self.assertRefusedAt(o, rd.REQ_DISPOSABLE_SCOPE)

    def test_replay_lands_on_single_use(self):
        port = tsim.make_port()
        sim.simulate_retirement(tsim.make_request(), tsim.make_fixture(), port, clock=tsim.Clock())
        o = sim.simulate_retirement(tsim.make_request(), tsim.make_fixture(), port, clock=tsim.Clock())
        self.assertIn(sim.SIM_DECISION_ALREADY_CONSUMED, o.reason_codes)
        self.assertRefusedAt(o, rd.REQ_SINGLE_USE_CONSUMPTION)

    def test_lease_expiring_after_consumption_refuses_the_lease_not_the_postcondition(self):
        o = outcome(sim.SimulationFaults(lease_ttl_seconds=20),
                    clock=tsim.Clock(tsim.T0, tsim.T0, tsim.T0, tsim.T0, tsim.T0 + tsim.timedelta(seconds=25)))
        r = self.assertRefusedAt(o, rd.REQ_EXTERNAL_LEASE)
        self.assertEqual(self.row(r, rd.REQ_SINGLE_USE_CONSUMPTION).status, rd.BLOCKED_BY_DEPENDENCY)
        self.assertIn(rd.REQ_FRESH_REVALIDATION, self.row(r, rd.REQ_SINGLE_USE_CONSUMPTION).blocking_dependencies)
        self.assertIs(r.human_reconciliation_required, False)

    def test_lease_release_failure_on_a_completed_simulation_is_a_gap(self):
        o = outcome(sim.SimulationFaults(raise_at=(sim.STEP_RELEASE_LEASE,)))
        self.assertEqual(o.state, sim.COMPLETED_SIMULATED)
        r = self.evaluate(o)
        self.assertEqual(self.row(r, rd.REQ_EXTERNAL_LEASE).status, rd.REFUSED)
        self.assertEqual(r.simulation_assessment, rd.SIMULATION_GAPS_REFUSED)

    def test_every_4f01_reason_code_and_step_maps_to_a_known_obligation(self):
        self.assertEqual(set(rd.SIM_CODE_REQUIREMENT), set(sim.REASON_CODES))
        self.assertEqual(set(rd.SIM_STEP_REQUIREMENT), set(sim.STEP_ORDER))
        for value in list(rd.SIM_CODE_REQUIREMENT.values()) + list(rd.SIM_STEP_REQUIREMENT.values()):
            self.assertTrue(value is None or value in ALL_REQUIREMENTS, value)
        for code in sim.ALWAYS_CODES + (sim.SIM_COMPLETED_SIMULATED_ONLY,):
            self.assertIsNone(rd.SIM_CODE_REQUIREMENT[code])


class UncertainOutcomeTests(ReadinessCase):
    UNCERTAIN = (sim.SimulationFaults(effect_status=sim.EFFECT_UNKNOWN),
                 sim.SimulationFaults(effect_status=sim.EFFECT_REFUSED),
                 sim.SimulationFaults(raise_at=(sim.FAULT_AFTER_EFFECT,)),
                 sim.SimulationFaults(raise_at=(sim.STEP_EFFECT,)),
                 sim.SimulationFaults(raise_at=(sim.STEP_POSTCHECK,)),
                 sim.SimulationFaults(post_overrides=(("registered", True),)),
                 sim.SimulationFaults(post_overrides=(("effect_events_for_target", 2),)))

    def test_uncertain_outcomes_require_reconciliation_and_forbid_destructive_retry(self):
        for faults in self.UNCERTAIN:
            with self.subTest(faults=faults):
                o = outcome(faults)
                self.assertEqual(o.state, sim.UNCERTAIN_SIMULATED)
                r = self.evaluate(o)
                self.assertEqual(r.simulation_assessment, rd.SIMULATION_UNCERTAIN)
                row = self.row(r, rd.REQ_UNCERTAINTY_AND_POSTCONDITION)
                self.assertEqual(row.status, rd.UNCERTAIN_RECONCILIATION_REQUIRED)
                self.assertIn(rd.READINESS_NO_DESTRUCTIVE_RETRY_AFTER_UNCERTAINTY, row.reason_codes)
                self.assertIn(rd.READINESS_UNCERTAIN_RECONCILIATION_REQUIRED, row.reason_codes)
                self.assertIs(r.human_reconciliation_required, True)
                self.assertIs(r.retry_allowed, False)
                self.assertIs(r.destructive_retry_forbidden, True)
                self.assertEqual(self.row(r, rd.REQ_RETENTION).status, rd.BLOCKED_BY_DEPENDENCY)

    def test_no_claim_can_replace_a_reconciliation(self):
        o = outcome(self.UNCERTAIN[0])
        r = self.evaluate(o, inventory(o, every_asserted_claim()))
        row = self.row(r, rd.REQ_UNCERTAINTY_AND_POSTCONDITION)
        self.assertEqual(row.status, rd.UNCERTAIN_RECONCILIATION_REQUIRED)
        self.assertIn(rd.READINESS_UNVERIFIABLE_CLAIM_REFUSED, row.reason_codes)
        self.assertIs(r.human_reconciliation_required, True)

    def test_an_uncertain_outcome_with_a_refused_inventory_still_requires_reconciliation(self):
        o = outcome(self.UNCERTAIN[0])
        r = self.evaluate(o, forge(inventory(o), simulation_marker="LIVE"))
        self.assertInputRefused(r, rd.READINESS_INVENTORY_MARKER_MISSING)
        self.assertIs(r.human_reconciliation_required, True)
        self.assertEqual(r.outcome_state, sim.UNCERTAIN_SIMULATED)


# ---------------------------------------------------------------------------
# 3. Altered outcomes, fingerprints and traces (verified by 4F-01 itself)
# ---------------------------------------------------------------------------

class AlteredOutcomeTests(ReadinessCase):
    def setUp(self):
        self.completed = outcome()
        self.refused = outcome(sim.SimulationFaults(lease_unavailable=True))
        self.uncertain = outcome(sim.SimulationFaults(effect_status=sim.EFFECT_UNKNOWN))

    def assertOutcomeRefused(self, o, invariant=None):
        r = self.evaluate(o, inventory(self.completed))
        self.assertInputRefused(r, rd.READINESS_OUTCOME_UNVERIFIED)
        self.assertEqual((r.outcome_state, r.outcome_fingerprint, r.outcome_verified), (None, None, False))
        if invariant:
            self.assertIn(invariant, r.outcome_invariant_codes)
        return r

    def test_tampered_fingerprint_is_refused(self):
        self.assertOutcomeRefused(forge(self.completed, fingerprint="0" * 64), "INV_FINGERPRINT")
        self.assertOutcomeRefused(forge(self.refused, state=sim.COMPLETED_SIMULATED), "INV_FINGERPRINT")

    def test_refingerprinted_semantic_forgeries_are_refused_by_verify_outcome(self):
        c, u = self.completed, self.uncertain
        cases = ((tsim.refingerprinted(c, authorizes_action=True), "INV_NOT_LIVE"),
                 (tsim.refingerprinted(c, host_identity_authenticated=True), "INV_NOT_LIVE"),
                 (tsim.refingerprinted(c, queue_scope_attested=True), "INV_NOT_LIVE"),
                 (tsim.refingerprinted(c, human_approval_present=True), "INV_NOT_LIVE"),
                 (tsim.refingerprinted(c, state_trace=c.state_trace[:-1]), "INV_STATE"),
                 (tsim.refingerprinted(c, step_trace=tuple(reversed(c.step_trace))), "INV_STEP_ORDER"),
                 (tsim.refingerprinted(c, simulated_effect_calls=2), "INV_EFFECT_CALLS"),
                 (tsim.refingerprinted(u, human_reconciliation_required=False), "INV_UNCERTAIN"),
                 (tsim.refingerprinted(u, state=sim.COMPLETED_SIMULATED,
                                       state_trace=u.state_trace[:-1] + (sim.COMPLETED_SIMULATED,)),
                  "INV_UNCERTAIN"),
                 (tsim.refingerprinted(c, reason_codes=c.reason_codes + ("READY_FOR_LIVE",)), "INV_REASON_CODES"))
        for forged, code in cases:
            with self.subTest(code=code):
                self.assertOutcomeRefused(forged, code)

    def test_non_outcomes_are_refused(self):
        for value in (None, object(), "COMPLETED_SIMULATED", dataclasses.asdict(self.completed), True,
                      tsim.make_request(), tsim.make_fixture(), forge(self.completed, step_trace=[])):
            with self.subTest(value=type(value).__name__):
                r = self.evaluate(value, inventory(self.completed))
                self.assertEqual(r.simulation_assessment, rd.INPUT_REFUSED)
                self.assertTrue({rd.READINESS_OUTCOME_UNVERIFIED, rd.READINESS_UPSTREAM_EVIDENCE_NOT_OUTCOME}
                                & set(r.reason_codes))

    def test_a_subclassed_outcome_is_refused(self):
        class Outcome(sim.SimulatedRetirementOutcome):
            pass

        names = [f.name for f in dataclasses.fields(sim.SimulatedRetirementOutcome) if f.init]
        clone = Outcome(**{n: getattr(self.completed, n) for n in names})
        self.assertOutcomeRefused(clone)

    def test_upstream_4d_4e_evidence_is_never_an_outcome_or_a_permit(self):
        report, record = twra.fixture()
        assessment = twra.candidate(report)
        proposal = wra.build_retirement_proposal(report, record, host_id=twra.HOST)
        names = [f.name for f in dataclasses.fields(rcm.RetirementEvidenceComposition) if f.init]
        values = {n: None for n in names}
        values.update(schema=rcm.COMPOSITION_SCHEMA, status=rcm.STATUS_DRY_RUN_EVIDENCE_CONSISTENT,
                      reason_codes=(), proposal_findings=(), command_verification_codes=(), ledger_codes=(),
                      manifest_codes=(), signature_verified=True, source_records_revalidated=True,
                      ledger_evidence_present=True, manifest_signature_verified=True)
        composition = rcm.RetirementEvidenceComposition(**values)
        forged = forge(composition, authorizes_action=True, issued=True, host_identity_authenticated=True)
        self.assertEqual(assessment.classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)
        for evidence in (assessment, proposal, composition, forged):
            with self.subTest(evidence=type(evidence).__name__):
                r = self.evaluate(evidence, inventory(self.completed))
                self.assertInputRefused(r, rd.READINESS_UPSTREAM_EVIDENCE_NOT_OUTCOME)
                self.assertNotIn(rcm.STATUS_DRY_RUN_EVIDENCE_CONSISTENT, canonical_values(r))
        # Upstream evidence is not a declaration either.
        r = self.evaluate(self.completed, forge(inventory(self.completed), declarations=(composition,)))
        self.assertInputRefused(r, rd.READINESS_DECLARATION_MALFORMED)

    def test_inventory_must_be_bound_to_this_outcome(self):
        other = inventory(self.refused)
        self.assertInputRefused(self.evaluate(self.completed, other), rd.READINESS_INVENTORY_BINDING_MISMATCH)
        for fp in ("", "0" * 64, None, self.completed.fingerprint.upper()):
            with self.subTest(fp=fp):
                inv = forge(inventory(self.completed), outcome_fingerprint=fp)
                self.assertInputRefused(self.evaluate(self.completed, inv), rd.READINESS_INVENTORY_BINDING_MISMATCH)
        unbound = rd.build_readiness_inventory(object(), inventory_id="inv-1", declared_at=DECLARED_AT)
        self.assertEqual(unbound.outcome_fingerprint, "")


# ---------------------------------------------------------------------------
# 4. Impossible evidence, policy, host, ACL, clock, queues, postcondition
# ---------------------------------------------------------------------------

class ImpossibleEvidenceTests(ReadinessCase):
    def setUp(self):
        self.o = outcome()

    def test_each_unverifiable_assertion_is_refused_and_never_elevates(self):
        for claim, requirement in rd.ASSERTED_CLAIMS.items():
            with self.subTest(claim=claim):
                r = self.evaluate(self.o, inventory(self.o, (declare(requirement, claim),)))
                row = self.row(r, requirement)
                self.assertEqual(row.status, rd.REFUSED)
                self.assertIn(rd.READINESS_UNVERIFIABLE_CLAIM_REFUSED, row.reason_codes)
                self.assertEqual(row.declared_evidence, (declare(requirement, claim).evidence_label,))
                self.assertEqual(r.simulation_assessment, rd.SIMULATION_GAPS_REFUSED)
                for req in ALL_REQUIREMENTS:
                    if requirement in rd.DEPENDENCIES[req]:
                        self.assertEqual(self.status(r)[req], rd.BLOCKED_BY_DEPENDENCY, req)

    def test_named_impossible_claims_leave_real_world_flags_false(self):
        for claim, flag in (("HOST_ATTESTED", "host_identity_authenticated"), ("ACL_VERIFIED", "file_acl_verified"),
                            ("QUEUE_COMPLETE", "queue_scope_attested"), ("HUMAN_APPROVED", "human_approval_present"),
                            ("POLICY_APPROVED", "policy_approved"), ("CLOCK_ATTESTED", "clock_attested")):
            with self.subTest(claim=claim):
                r = self.evaluate(self.o, inventory(self.o, (declare(rd.ASSERTED_CLAIMS[claim], claim),)))
                self.assertIs(getattr(r, flag), False)
                self.assertEqual(self.row(r, rd.ASSERTED_CLAIMS[claim]).status, rd.REFUSED)

    def test_self_asserted_manifest_completeness_is_refused(self):
        r = self.evaluate(self.o, inventory(self.o, (declare(rd.REQ_QUEUE_SCOPE, "MANIFEST_COMPLETE"),)))
        self.assertEqual(self.row(r, rd.REQ_QUEUE_SCOPE).status, rd.REFUSED)
        self.assertIs(r.queue_scope_attested, False)
        self.assertIn("PROOF_QUEUE_MANIFEST_SIGNED_AND_VERIFIED", self.row(r, rd.REQ_QUEUE_SCOPE).missing_proofs)

    def test_external_queues_not_covered_remain_a_gap(self):
        r = self.evaluate(self.o, inventory(self.o, (declare(rd.REQ_QUEUE_SCOPE, rd.CLAIM_EXTERNAL_QUEUE_UNCOVERED),)))
        row = self.row(r, rd.REQ_QUEUE_SCOPE)
        self.assertEqual(row.status, rd.SIMULATED_ONLY)
        self.assertIn(rd.READINESS_EXTERNAL_QUEUES_NOT_COVERED, row.reason_codes)
        self.assertIn("PROOF_EXTERNAL_QUEUE_INVENTORY_COMPLETE", row.missing_proofs)

    def test_host_id_without_attestation_is_not_identity(self):
        r = self.evaluate(self.o, inventory(self.o, (declare(rd.REQ_HOST_IDENTITY, rd.CLAIM_HOST_ID_LABEL_ONLY),)))
        row = self.row(r, rd.REQ_HOST_IDENTITY)
        self.assertEqual(row.status, rd.SIMULATED_ONLY)
        self.assertIn(rd.READINESS_HOST_ID_WITHOUT_ATTESTATION, row.reason_codes)
        self.assertIs(r.host_identity_authenticated, False)
        self.assertEqual(r.host_accreditation, rd.HOST_ACCREDITATION_ABSENT)

    def test_acl_not_inspected_stays_unproven(self):
        for claim, code in ((rd.CLAIM_NOT_INSPECTED, rd.READINESS_DECLARED_NOT_INSPECTED),
                            (rd.CLAIM_ABSENT, rd.READINESS_DECLARED_ABSENT)):
            with self.subTest(claim=claim):
                r = self.evaluate(self.o, inventory(self.o, (declare(rd.REQ_FILE_ACL, claim),)))
                row = self.row(r, rd.REQ_FILE_ACL)
                self.assertEqual(row.status, rd.UNPROVEN)
                self.assertIn(code, row.reason_codes)
                self.assertIs(r.file_acl_verified, False)

    def test_caller_supplied_clock_is_never_trusted(self):
        for declared_at in ("2026-10-27T12:00:00Z", "2099-12-31T23:59:59Z", "2020-01-01T00:00:00Z"):
            with self.subTest(declared_at=declared_at):
                r = self.evaluate(self.o, inventory(self.o, declared_at=declared_at))
                row = self.row(r, rd.REQ_TRUSTED_CLOCK)
                self.assertEqual(row.status, rd.UNPROVEN)
                self.assertIn(rd.READINESS_CALLER_CLOCK_NOT_TRUSTED, row.reason_codes)
                self.assertIs(r.clock_attested, False)
        for declared_at in ("now", "2026-10-27 12:00:00", "2019-12-31T23:59:59Z", "2100-01-01T00:00:00Z",
                            "2026-13-01T00:00:00Z", None, 1793102400, tsim.T0):
            with self.subTest(declared_at=declared_at):
                r = self.evaluate(self.o, inventory(self.o, declared_at=declared_at))
                self.assertInputRefused(r, rd.READINESS_INVENTORY_TIMESTAMP_INVALID)

    def test_ambiguous_postcondition_is_never_confirmed_by_a_claim(self):
        o = outcome(sim.SimulationFaults(post_overrides=(("branch_ref_present", False),)))
        r = self.evaluate(o, inventory(o, (declare(rd.REQ_UNCERTAINTY_AND_POSTCONDITION,
                                                   "POSTCONDITION_CONFIRMED_LIVE"),)))
        self.assertEqual(self.row(r, rd.REQ_UNCERTAINTY_AND_POSTCONDITION).status,
                         rd.UNCERTAIN_RECONCILIATION_REQUIRED)
        self.assertEqual(r.simulation_assessment, rd.SIMULATION_UNCERTAIN)


class PolicyPendingTests(ReadinessCase):
    def setUp(self):
        self.o = outcome()

    def test_absent_d1_d12_references_are_pending_and_incomplete(self):
        r = self.evaluate(self.o)
        row = self.row(r, rd.REQ_POLICY_D1_D12)
        self.assertEqual(row.status, rd.POLICY_PENDING)
        self.assertIn(rd.READINESS_POLICY_D1_D12_PENDING, row.reason_codes)
        self.assertIn(rd.READINESS_POLICY_REFERENCES_INCOMPLETE, row.reason_codes)
        self.assertEqual(row.missing_proofs, tuple("PROOF_DIRECCION_APPROVAL_D%d" % i for i in range(1, 13)))

    def test_all_twelve_proposals_stay_pending_and_are_not_approval(self):
        r = self.evaluate(self.o, inventory(self.o, policy_references=proposed(*rd.POLICY_DECISION_IDS)))
        row = self.row(r, rd.REQ_POLICY_D1_D12)
        self.assertEqual(row.status, rd.POLICY_PENDING)
        self.assertIn(rd.READINESS_POLICY_PROPOSAL_NOT_APPROVAL, row.reason_codes)
        self.assertNotIn(rd.READINESS_POLICY_REFERENCES_INCOMPLETE, row.reason_codes)
        self.assertEqual(len(row.missing_proofs), 12)
        self.assertIs(r.policy_approved, False)
        self.assertEqual(r.policy_status, rd.POLICY_D1_D12_PENDING_NOT_APPROVED)

    def test_a_claimed_approval_is_refused_not_inferred(self):
        refs = proposed(*rd.POLICY_DECISION_IDS[:11]) + (
            rd.SyntheticPolicyReference("D-12", rd.POLICY_STANCE_CLAIMED_APPROVED),)
        r = self.evaluate(self.o, inventory(self.o, policy_references=refs))
        self.assertEqual(self.row(r, rd.REQ_POLICY_D1_D12).status, rd.REFUSED)
        self.assertIn(rd.READINESS_UNVERIFIABLE_CLAIM_REFUSED, self.row(r, rd.REQ_POLICY_D1_D12).reason_codes)
        self.assertIs(r.policy_approved, False)
        for req in (rd.REQ_SEPARATION_OF_DUTIES, rd.REQ_HUMAN_APPROVAL, rd.REQ_DISPOSABLE_SCOPE, rd.REQ_RETENTION):
            self.assertEqual(self.status(r)[req], rd.BLOCKED_BY_DEPENDENCY, req)

    def test_policy_references_are_a_closed_vocabulary(self):
        for ref in (rd.SyntheticPolicyReference("D-13", rd.POLICY_STANCE_PROPOSED),
                    rd.SyntheticPolicyReference("D-0", rd.POLICY_STANCE_PROPOSED),
                    rd.SyntheticPolicyReference("d-1", rd.POLICY_STANCE_PROPOSED),
                    rd.SyntheticPolicyReference("D-1", "APPROVED"),
                    rd.SyntheticPolicyReference("D-1", rd.POLICY_STANCE_PROPOSED, schema="v0"), "D-1", None):
            with self.subTest(ref=ref):
                inv = forge(inventory(self.o), policy_references=(ref,))
                self.assertInputRefused(self.evaluate(self.o, inv), rd.READINESS_POLICY_REFERENCE_MALFORMED)
        forged = forge(rd.SyntheticPolicyReference("D-1", rd.POLICY_STANCE_PROPOSED), approved_by_direccion=True)
        inv = forge(inventory(self.o), policy_references=(forged,))
        self.assertInputRefused(self.evaluate(self.o, inv), rd.READINESS_INVENTORY_FORGED_FLAG)
        with self.assertRaises(TypeError):
            rd.SyntheticPolicyReference("D-1", rd.POLICY_STANCE_PROPOSED, approved_by_direccion=True)

    def test_no_policy_default_is_introduced(self):
        self.assertEqual(rd.POLICY_STANCES, (rd.POLICY_STANCE_PROPOSED, rd.POLICY_STANCE_CLAIMED_APPROVED))
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SyntheticPolicyReference":
                stance = [n for n in node.body if isinstance(n, ast.AnnAssign) and n.target.id == "stance"][0]
                self.assertIsNone(stance.value)


# ---------------------------------------------------------------------------
# 5. Causal order, determinism, immutability
# ---------------------------------------------------------------------------

class CausalOrderTests(ReadinessCase):
    def test_dependencies_form_a_dag_in_matrix_order(self):
        self.assertEqual(set(rd.DEPENDENCIES), set(ALL_REQUIREMENTS))
        self.assertEqual(set(rd.MISSING_PROOFS), set(ALL_REQUIREMENTS))
        for req, deps in rd.DEPENDENCIES.items():
            for dep in deps:
                self.assertLess(ALL_REQUIREMENTS.index(dep), ALL_REQUIREMENTS.index(req), (dep, req))
        self.assertEqual(len(set(ALL_REQUIREMENTS)), 14)

    def test_audit_categories_are_all_covered(self):
        for word in ("POLICY", "HUMAN_APPROVAL", "HOST_IDENTITY", "FILESYSTEM", "CLOCK", "QUEUE", "LEASE",
                     "REVALIDATION", "SINGLE_USE", "UNCERTAINTY", "RETENTION", "ACL", "SEPARATION_OF_DUTIES",
                     "DISPOSABLE"):
            self.assertTrue(any(word in req for req in ALL_REQUIREMENTS), word)

    def test_a_root_refusal_blocks_every_transitive_dependent(self):
        o = outcome()
        r = self.evaluate(o, inventory(o, (declare(rd.REQ_HOST_IDENTITY, "HOST_ATTESTED"),)))
        statuses = self.status(r)
        closure, changed = {rd.REQ_HOST_IDENTITY}, True
        while changed:
            changed = False
            for req, deps in rd.DEPENDENCIES.items():
                if req not in closure and set(deps) & closure:
                    closure.add(req)
                    changed = True
        for req in ALL_REQUIREMENTS:
            expected = rd.REFUSED if req == rd.REQ_HOST_IDENTITY else (
                rd.BLOCKED_BY_DEPENDENCY if req in closure else statuses[req])
            self.assertEqual(statuses[req], expected, req)
        for row in r.rows:
            self.assertTrue(set(row.blocking_dependencies) <= set(row.depends_on))
            self.assertEqual(row.depends_on, rd.DEPENDENCIES[row.requirement])
            if row.status == rd.BLOCKED_BY_DEPENDENCY:
                self.assertIn(rd.READINESS_DEPENDENCY_BLOCKED, row.reason_codes)
                self.assertTrue(row.blocking_dependencies)


class DeterminismAndImmutabilityTests(ReadinessCase):
    def test_same_inputs_give_identical_reports_and_serialization(self):
        o = outcome()
        decls = (declare(rd.REQ_FILE_ACL, rd.CLAIM_NOT_INSPECTED),
                 declare(rd.REQ_HOST_IDENTITY, rd.CLAIM_HOST_ID_LABEL_ONLY))
        a = self.evaluate(o, inventory(o, decls, proposed("D-3", "D-1")))
        b = self.evaluate(outcome(), inventory(outcome(), tuple(reversed(decls)), proposed("D-1", "D-3")))
        self.assertEqual(a, b)
        self.assertEqual(rd.canonical_report_json(a), rd.canonical_report_json(b))
        self.assertEqual(a.fingerprint, rd.report_fingerprint(a))
        self.assertEqual(a.inventory_digest, rd.inventory_digest(inventory(o, decls, proposed("D-1", "D-3"))))
        text = rd.canonical_report_json(a)
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False))
        self.assertEqual(json.loads(text)["verdict"], rd.LIVE_NOT_AUTHORIZED)
        self.assertNotEqual(a.fingerprint, self.evaluate(o).fingerprint)

    def test_every_value_type_is_frozen(self):
        for cls in (rd.SyntheticEvidenceDeclaration, rd.SyntheticPolicyReference, rd.SyntheticReadinessInventory,
                    rd.ReadinessRow, rd.RetirementReadinessReport):
            self.assertTrue(cls.__dataclass_params__.frozen, cls)
        r = self.evaluate(outcome())
        for name in ("verdict", "ready_for_live", "rows", "simulation_assessment", "authorizes_action"):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(r, name, None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.rows[0].status = rd.SIMULATED_ONLY
        self.assertIs(type(r.rows), tuple)
        self.assertIs(type(r.reason_codes), tuple)

    def test_real_world_fields_are_not_constructor_arguments(self):
        init = {f.name for f in dataclasses.fields(rd.RetirementReadinessReport) if f.init}
        for name, _ in REAL_WORLD_FLAGS:
            self.assertNotIn(name, init)
        self.assertFalse(init & {"live_blockers", "unproven"})
        for cls, flags in ((rd.ReadinessRow, ("live_proven", "satisfied_for_live")),
                           (rd.SyntheticEvidenceDeclaration, ("proves_live",)),
                           (rd.SyntheticPolicyReference, ("approved_by_direccion",)),
                           (rd.SyntheticReadinessInventory, ("is_host_evidence",))):
            self.assertFalse({f.name for f in dataclasses.fields(cls) if f.init} & set(flags), cls)
        with self.assertRaises(TypeError):
            rd.RetirementReadinessReport(*(["x"] * 11), ready_for_live=True)
        self.assertNotIn("readiness", {f.name for f in dataclasses.fields(rd.SyntheticReadinessInventory)})

    def test_report_schema_is_pinned(self):
        self.assertEqual([f.name for f in dataclasses.fields(rd.RetirementReadinessReport)], [
            "schema", "simulation_assessment", "outcome_state", "outcome_fingerprint", "outcome_verified",
            "outcome_invariant_codes", "inventory_digest", "rows", "reason_codes", "human_reconciliation_required",
            "fingerprint", "verdict", "live_status", "host_accreditation", "policy_status", "live_blockers",
            "unproven", "simulation_only", "destructive_retry_forbidden", "ready_for_live",
            "retirement_authorization_live", "retirement_execution_capable", "authorizes_action",
            "deletion_authorized", "branch_deletion_authorized", "issued", "consumed", "host_identity_authenticated",
            "queue_scope_attested", "file_acl_verified", "clock_attested", "policy_approved",
            "human_approval_present", "retry_allowed"])
        self.assertEqual(rd.REPORT_SCHEMA, "fcp4f02-retirement-readiness-report-v1")


class ReportInvariantTests(ReadinessCase):
    def setUp(self):
        self.report = self.evaluate(outcome())

    def assertViolates(self, report, code):
        self.assertIn(code, rd.readiness_report_invariant_errors(report))
        self.assertFalse(rd.verify_readiness_report(report))

    def test_sound_reports_verify(self):
        for o in (outcome(), outcome(sim.SimulationFaults(lease_unavailable=True)),
                  outcome(sim.SimulationFaults(effect_status=sim.EFFECT_UNKNOWN))):
            self.assertTrue(rd.verify_readiness_report(self.evaluate(o)))
        self.assertTrue(rd.verify_readiness_report(self.evaluate(None, None)))

    def test_externally_raised_readiness_is_refused(self):
        r = self.report
        self.assertViolates(forge(r, ready_for_live=True), "RINV_FINGERPRINT")
        for name, value in REAL_WORLD_FLAGS:
            with self.subTest(name=name):
                bad = "READY_FOR_LIVE" if type(value) is str else (not value)
                self.assertViolates(refingerprinted(r, **{name: bad}), "RINV_NOT_LIVE")
        self.assertViolates(refingerprinted(r, ready_for_live=1), "RINV_NOT_LIVE")
        self.assertViolates(refingerprinted(r, live_blockers=()), "RINV_NOT_LIVE")
        rows = (forge(r.rows[0], status="READY_FOR_LIVE"),) + r.rows[1:]
        self.assertViolates(refingerprinted(r, rows=rows), "RINV_MATRIX")
        rows = (forge(r.rows[0], live_proven=True),) + r.rows[1:]
        self.assertViolates(refingerprinted(r, rows=rows), "RINV_NOT_LIVE")
        rows = (forge(r.rows[0], missing_proofs=()),) + r.rows[1:]
        self.assertViolates(refingerprinted(r, rows=rows), "RINV_MATRIX")
        self.assertViolates(refingerprinted(r, rows=r.rows[:-1]), "RINV_MATRIX")
        self.assertViolates(refingerprinted(r, simulation_assessment="READY_FOR_LIVE"), "RINV_SCHEMA")
        rows = (forge(r.rows[0], status=rd.SIMULATED_ONLY),) + r.rows[1:]
        self.assertViolates(refingerprinted(r, rows=rows), "RINV_POLICY")

    def test_smuggled_attributes_and_wrong_types_are_malformed(self):
        smuggled = copy.copy(self.report)
        object.__setattr__(smuggled, "readiness", "READY_FOR_LIVE")
        for value in (smuggled, None, dataclasses.asdict(self.report), forge(self.report, rows=list(self.report.rows))):
            self.assertEqual(rd.readiness_report_invariant_errors(value), ("RINV_MALFORMED",))

    def test_assessment_and_uncertainty_must_match_the_rows(self):
        u = self.evaluate(outcome(sim.SimulationFaults(effect_status=sim.EFFECT_UNKNOWN)))
        self.assertViolates(refingerprinted(u, human_reconciliation_required=False), "RINV_UNCERTAIN")
        self.assertViolates(refingerprinted(u, simulation_assessment=rd.SIMULATION_PRECONDITIONS_MODELED),
                            "RINV_ASSESSMENT")
        refused = self.evaluate(outcome(sim.SimulationFaults(lease_unavailable=True)))
        self.assertViolates(refingerprinted(refused, simulation_assessment=rd.SIMULATION_PRECONDITIONS_MODELED),
                            "RINV_ASSESSMENT")
        self.assertViolates(refingerprinted(self.report, outcome_verified=False), "RINV_OUTCOME")
        bad = self.evaluate(None, None)
        rows = (forge(bad.rows[0], status=rd.SIMULATED_ONLY),) + bad.rows[1:]
        self.assertViolates(refingerprinted(bad, rows=rows), "RINV_INPUT_REFUSED")
        codes = tuple(c for c in self.report.reason_codes if c != rd.READINESS_LIVE_NOT_AUTHORIZED)
        self.assertViolates(refingerprinted(self.report, reason_codes=codes), "RINV_REASON_CODES")


# ---------------------------------------------------------------------------
# 6. Input schema: unknown types, vocabulary, limits
# ---------------------------------------------------------------------------

class InventorySchemaTests(ReadinessCase):
    def setUp(self):
        self.o = outcome()
        self.inv = inventory(self.o)

    def refused(self, inv, code):
        report = rd.evaluate_readiness(self.o, inv)   # `inv` as given, even None
        self.assertNeverLive(report)
        self.assertInputRefused(report, code)

    def test_non_inventories_and_subclasses_are_refused(self):
        class Inventory(rd.SyntheticReadinessInventory):
            pass

        names = [f.name for f in dataclasses.fields(rd.SyntheticReadinessInventory) if f.init]
        sub = Inventory(**{n: getattr(self.inv, n) for n in names})
        for value in (None, {}, dataclasses.asdict(self.inv), "inventory", sub, tsim.make_fixture(), self.o):
            with self.subTest(value=type(value).__name__):
                self.refused(value, rd.READINESS_INVENTORY_MALFORMED)

    def test_marker_schema_id_and_containers_are_checked(self):
        self.refused(forge(self.inv, simulation_marker=sim.SIMULATION_MARKER), rd.READINESS_INVENTORY_MARKER_MISSING)
        for changes in ({"schema": "v0"}, {"inventory_id": "bad id"}, {"inventory_id": ""}, {"inventory_id": 7},
                        {"inventory_id": "x" * 129}, {"declarations": []}, {"policy_references": None}):
            with self.subTest(changes=changes):
                self.refused(forge(self.inv, **changes), rd.READINESS_INVENTORY_MALFORMED)

    def test_smuggled_readiness_value_and_forged_flags_are_refused(self):
        smuggled = copy.copy(self.inv)
        object.__setattr__(smuggled, "readiness", "READY_FOR_LIVE")
        self.refused(smuggled, rd.READINESS_INVENTORY_UNKNOWN_FIELD)
        self.refused(forge(self.inv, is_host_evidence=True), rd.READINESS_INVENTORY_FORGED_FLAG)
        decl = forge(declare(rd.REQ_HOST_IDENTITY, rd.CLAIM_HOST_ID_LABEL_ONLY), proves_live=True)
        self.refused(forge(self.inv, declarations=(decl,)), rd.READINESS_INVENTORY_FORGED_FLAG)
        decl = copy.copy(declare(rd.REQ_HOST_IDENTITY, rd.CLAIM_HOST_ID_LABEL_ONLY))
        object.__setattr__(decl, "status", rd.SIMULATED_ONLY)
        self.refused(forge(self.inv, declarations=(decl,)), rd.READINESS_DECLARATION_MALFORMED)
        with self.assertRaises(TypeError):
            rd.SyntheticEvidenceDeclaration(rd.REQ_FILE_ACL, "ACL_VERIFIED", "sim://fcp4f01/x", proves_live=True)
        with self.assertRaises(TypeError):
            rd.build_readiness_inventory(self.o, inventory_id="inv-1", declared_at=DECLARED_AT,
                                         readiness="READY_FOR_LIVE")

    def test_unknown_vocabulary_is_refused(self):
        for requirement, claim in ((rd.REQ_HOST_IDENTITY, "READY_FOR_LIVE"), ("READY_FOR_LIVE", rd.CLAIM_ABSENT),
                                   (rd.REQ_FILE_ACL, "acl_verified"), ("HOST", "HOST_ATTESTED"),
                                   (rd.REQ_HOST_IDENTITY, "AUTHORIZED")):
            with self.subTest(requirement=requirement, claim=claim):
                d = rd.SyntheticEvidenceDeclaration(requirement, claim, "sim://fcp4f01/evidence/x")
                self.refused(forge(self.inv, declarations=(d,)), rd.READINESS_DECLARATION_UNKNOWN_VOCABULARY)
        for d in (rd.SyntheticEvidenceDeclaration(rd.REQ_FILE_ACL, None, "sim://fcp4f01/x"),
                  rd.SyntheticEvidenceDeclaration(rd.REQ_FILE_ACL, rd.CLAIM_ABSENT, b"sim://fcp4f01/x"),
                  rd.SyntheticEvidenceDeclaration(rd.REQ_FILE_ACL, rd.CLAIM_ABSENT, "sim://fcp4f01/x", schema="v0"),
                  "HOST_ATTESTED", None, (rd.REQ_HOST_IDENTITY, "HOST_ATTESTED")):
            with self.subTest(d=d):
                self.refused(forge(self.inv, declarations=(d,)), rd.READINESS_DECLARATION_MALFORMED)

    def test_claim_bound_to_another_obligation_is_refused(self):
        for requirement, claim in ((rd.REQ_FILE_ACL, "HOST_ATTESTED"), (rd.REQ_HOST_IDENTITY, "ACL_VERIFIED"),
                                   (rd.REQ_FILE_ACL, rd.CLAIM_HOST_ID_LABEL_ONLY),
                                   (rd.REQ_HOST_IDENTITY, rd.CLAIM_EXTERNAL_QUEUE_UNCOVERED),
                                   (rd.REQ_RETENTION, "POLICY_APPROVED")):
            with self.subTest(claim=claim):
                self.refused(inventory(self.o, (declare(requirement, claim),)),
                             rd.READINESS_DECLARATION_REQUIREMENT_MISMATCH)

    def test_evidence_labels_must_be_synthetic(self):
        for label in (str(REPO_ROOT), "C:\\Users\\x\\acl", "/etc/passwd", "\\\\server\\share", "relative/x",
                      "sim://fcp4f01/../x", "sim://other/x", "file:///C:/x", "https://host/x", "sim://fcp4f01/",
                      "sim://fcp4f01/" + "a" * 300, " sim://fcp4f01/x", "sim://fcp4f01/x\0"):
            with self.subTest(label=label):
                d = rd.SyntheticEvidenceDeclaration(rd.REQ_FILE_ACL, rd.CLAIM_NOT_INSPECTED, label)
                self.refused(forge(self.inv, declarations=(d,)), rd.READINESS_DECLARATION_NOT_SYNTHETIC)

    def test_duplicates_and_non_canonical_order_are_refused(self):
        a = declare(rd.REQ_FILE_ACL, rd.CLAIM_NOT_INSPECTED)
        b = declare(rd.REQ_HOST_IDENTITY, rd.CLAIM_HOST_ID_LABEL_ONLY)
        same_label = rd.SyntheticEvidenceDeclaration(rd.REQ_RETENTION, rd.CLAIM_ABSENT, a.evidence_label)
        same_pair = dataclasses.replace(a, evidence_label="sim://fcp4f01/evidence/other")
        for decls in ((a, a), (a, same_label), (a, same_pair)):
            with self.subTest(decls=decls):
                self.refused(forge(self.inv, declarations=decls), rd.READINESS_DECLARATION_DUPLICATE)
        self.refused(forge(self.inv, policy_references=proposed("D-1", "D-1")), rd.READINESS_DECLARATION_DUPLICATE)
        self.refused(forge(self.inv, declarations=(a, b)), rd.READINESS_INVENTORY_NOT_CANONICAL)
        self.refused(forge(self.inv, policy_references=proposed("D-2", "D-1")), rd.READINESS_INVENTORY_NOT_CANONICAL)
        self.assertEqual(inventory(self.o, (a, b)).declarations, (b, a))

    def test_input_size_limits(self):
        decls = tuple(rd.SyntheticEvidenceDeclaration(rd.REQ_FILE_ACL, rd.CLAIM_NOT_INSPECTED,
                                                      "sim://fcp4f01/evidence/%d" % i)
                      for i in range(rd.MAX_DECLARATIONS + 1))
        self.refused(forge(self.inv, declarations=decls), rd.READINESS_INVENTORY_TOO_LARGE)
        refs = proposed(*rd.POLICY_DECISION_IDS) + proposed("D-1")
        self.refused(forge(self.inv, policy_references=refs), rd.READINESS_INVENTORY_TOO_LARGE)
        valid = tuple(declare(req, claim) for claim, req in rd.ASSERTED_CLAIMS.items()) + tuple(
            declare(req, c) for req in ALL_REQUIREMENTS for c in (rd.CLAIM_NOT_INSPECTED, rd.CLAIM_ABSENT))
        self.assertLessEqual(len(valid), rd.MAX_DECLARATIONS)
        r = self.evaluate(self.o, inventory(self.o, valid, proposed(*rd.POLICY_DECISION_IDS)))
        self.assertNotEqual(r.simulation_assessment, rd.INPUT_REFUSED)

    def test_internal_errors_never_escape_and_refuse(self):
        with mock.patch.object(rd, "_rows", side_effect=RuntimeError("bug")):
            r = self.evaluate(self.o, self.inv)
        self.assertInputRefused(r, rd.READINESS_INTERNAL_ERROR)
        with mock.patch.object(sim, "verify_outcome", side_effect=RuntimeError("bug")):
            r = self.evaluate(self.o, self.inv)
        self.assertInputRefused(r, rd.READINESS_INTERNAL_ERROR)


class VocabularyTests(unittest.TestCase):
    def test_reason_codes_are_stable_unique_and_declared(self):
        self.assertEqual(len(set(rd.REASON_CODES)), len(rd.REASON_CODES))
        self.assertTrue(all(c.startswith("READINESS_") and c == getattr(rd, c) for c in rd.REASON_CODES))
        declared = {v for k, v in vars(rd).items() if k.startswith("READINESS_") and type(v) is str
                    and k != "READINESS_MARKER"}
        self.assertEqual(declared, set(rd.REASON_CODES))
        self.assertEqual(set(rd.CLAIMS), set(rd.NEUTRAL_CLAIMS) | set(rd.ASSERTED_CLAIMS))
        self.assertFalse(set(rd.NEUTRAL_CLAIMS) & set(rd.ASSERTED_CLAIMS))
        self.assertTrue(set(rd.ASSERTED_CLAIMS.values()) <= set(ALL_REQUIREMENTS))
        self.assertEqual(set(rd.SIMULATED_BY) - set(ALL_REQUIREMENTS), set())

    def test_every_reason_code_is_exercised_by_a_test(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        own = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == type(self).__name__)
        tree.body.remove(own)
        referenced = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                      and isinstance(n.value, ast.Name) and n.value.id == "rd"}
        self.assertEqual(sorted(set(rd.REASON_CODES) - referenced), [])


# ---------------------------------------------------------------------------
# 7. Isolation and side effects
# ---------------------------------------------------------------------------

class IsolationTests(ReadinessCase):
    def test_evaluations_use_no_process_network_or_filesystem_write(self):
        outcomes = (outcome(), outcome(sim.SimulationFaults(lease_unavailable=True)),
                    outcome(sim.SimulationFaults(effect_status=sim.EFFECT_UNKNOWN)))
        with tsim.GuardedEnvironment() as env:
            reports = [rd.evaluate_readiness(o, inventory(o, every_asserted_claim())) for o in outcomes]
            reports.append(rd.evaluate_readiness(None, None))
            for r in reports:
                rd.canonical_report_json(r)
                rd.verify_readiness_report(r)
            self.assertEqual(env.calls(), [])
        for r in reports:
            self.assertNeverLive(r)

    def test_importing_the_module_has_no_side_effect(self):
        name = "fcp4f02_isolated_import_probe"
        before = threading.active_count()
        spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
        probe = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.modules[name] = probe
        try:
            with tsim.GuardedEnvironment() as env:
                spec.loader.exec_module(probe)
                self.assertEqual(env.calls(), [])
        finally:
            sys.modules.pop(name, None)
            sys.dont_write_bytecode = previous
        self.assertEqual(threading.active_count(), before)
        self.assertIs(probe.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertIs(probe.RETIREMENT_EXECUTION_CAPABLE, False)

    def test_public_surface_has_no_operational_hook(self):
        public = sorted(n for n, v in vars(rd).items() if callable(v) and not n.startswith("_")
                        and getattr(v, "__module__", None) == rd.__name__)
        self.assertEqual(public, sorted([
            "ReadinessRow", "RetirementReadinessReport", "SyntheticEvidenceDeclaration", "SyntheticPolicyReference",
            "SyntheticReadinessInventory", "build_readiness_inventory", "canonical_report_json", "evaluate_readiness",
            "inventory_digest", "inventory_errors", "outcome_errors", "readiness_report_invariant_errors",
            "report_fingerprint", "verify_readiness_report"]))
        forbidden = re.compile(r"(?i)git|remove|delete|prune|rmtree|unlink|subprocess|shell|exec|live|issue|sign|"
                               r"approve|authori[sz]e|attest|adapter")
        for name in public:
            self.assertIsNone(forbidden.search(name), name)

    def test_source_imports_and_names_are_restricted(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(LEDGER_MODULE_NAME, source)
        self.assertNotIn("execute_live", source)
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {(None, a.name, a.asname) for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {(node.module, a.name, a.asname) for a in node.names}
        self.assertEqual(imported, {
                                       ('__future__', 'annotations', None),
                                       ('dataclasses', 'dataclass', None),
                                       ('dataclasses', 'field', None),
                                       ('datetime', 'datetime', None),
                                       ('datetime', 'timezone', None),
                                       ('scripts.ai', 'runner_worktree_retirement_authorization', 'wra'),
                                       ('scripts.ai', 'runner_worktree_retirement_executor_simulation', 'sim'),
                                       ('scripts.ai', 'runner_worktree_retirement_host_authority', 'rha'),
                                       ('typing', 'Optional', None),
                                       (None, 'dataclasses', None),
                                       (None, 'json', None),
                                   })
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "eval", "exec", "compile", "__import__", "globals", "setattr", "delattr",
                                  "importlib", "subprocess", "socket", "shutil", "sqlite3", "ctypes", "os"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"system", "popen", "remove", "unlink", "rmdir", "rmtree", "rename", "write",
                                  "write_text", "write_bytes", "mkdir", "makedirs", "connect", "urlopen", "now",
                                  "utcnow", "today", "time", "simulate_retirement", "InMemoryRetirementSimulationPort",
                                  "execute_live", "open_existing"})
        # Of 4F-01, only its verifier, types, vocabularies and pure helpers are used: no second engine.
        sim_attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                     and isinstance(n.value, ast.Name) and n.value.id == "sim"}
        self.assertTrue({"verify_outcome", "outcome_invariant_errors", "SimulatedRetirementOutcome",
                         "is_synthetic_label"} <= sim_attrs)
        self.assertEqual({a for a in sim_attrs if a.startswith("_")}, {"_material", "_not_a_fixture_code"})
        self.assertEqual({n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                          and isinstance(n.value, ast.Name) and n.value.id == "rha"}, {"_LABEL_RE", "_timestamp"})
        self.assertEqual({n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                          and isinstance(n.value, ast.Name) and n.value.id == "wra"}, {"_digest", "_jsonable"})
        constants = {n.value for n in ast.walk(tsim._code_without_docstrings(ast.parse(source)))
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for text in constants:
            self.assertNotRegex(text, r"(?i)\bgit\b|worktree remove|branch -[dD]|rm -|del /")
            self.assertNotIn("READY_FOR_LIVE", text)

    def test_no_code_in_the_module_produces_a_true_real_world_flag(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {n for n, v in REAL_WORLD_FLAGS if v is False} | {"live_proven", "satisfied_for_live",
                                                                  "proves_live", "approved_by_direccion",
                                                                  "is_host_evidence"}
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg in names:
                self.assertNotEqual(ast.unparse(node.value), "True", node.arg)
        for line in ("RETIREMENT_AUTHORIZATION_LIVE = False", "RETIREMENT_EXECUTION_CAPABLE = False",
                     "SIMULATION_ONLY = True"):
            self.assertEqual(source.count(line), 1, line)

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
# 8. CI
# ---------------------------------------------------------------------------

class CiWorkflowTests(unittest.TestCase):
    STEP = "FCP-4F-02 retirement readiness matrix regression without skipped tests"
    MODULE = "scripts.tests.test_runner_worktree_retirement_readiness_simulation"

    def setUp(self):
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def job(self, name):
        return re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.workflow).group(1)

    def test_nine_jobs_and_permissions_unchanged(self):
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", self.workflow))
        self.assertEqual(jobs, twra.CiWorkflowTests.JOBS)
        self.assertIn("permissions:\n  contents: read\n", self.workflow)
        self.assertEqual(self.workflow.count("permissions:"), 1)

    def test_suite_runs_once_zero_skip_between_4f01_and_02d(self):
        job = self.job("fcp3b2b2-host-trust")
        step = re.search(rf"(?ms)^      - name: {re.escape(self.STEP)}\n(.*?)(?=^      - name: |\Z)", job)
        self.assertIsNotNone(step)
        lines = step.group(0).rstrip("\n").split("\n")
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[1], "        run: |")
        for part in ("python -c ", f"unittest.defaultTestLoader.loadTestsFromName('{self.MODULE}')",
                     "print('RETIREMENT_READINESS_TESTS_SKIPPED=',len(r.skipped))",
                     "sys.exit(0 if r.wasSuccessful() and not r.skipped else 2)"):
            self.assertIn(part, lines[2], part)
        self.assertEqual(self.workflow.count("test_runner_worktree_retirement_readiness_simulation"), 1)
        self.assertLess(job.index(tsim.CiWorkflowTests.STEP), job.index(self.STEP))
        self.assertLess(job.index(self.STEP), job.index("FCP-4E-02d retirement evidence composition"))

    def test_predecessor_ci_contracts_still_hold(self):
        # The merged 4F-01 (and through it 02a/02b/02c/02d) workflow assertions, unchanged.
        names = unittest.defaultTestLoader.getTestCaseNames(tsim.CiWorkflowTests)
        self.assertEqual(len(names), 3)
        for name in names:
            tsim.CiWorkflowTests(name).debug()


if __name__ == "__main__":
    unittest.main()
