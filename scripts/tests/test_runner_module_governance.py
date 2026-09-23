import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_module_governance as gov


class FakeClock:
    def __init__(self, start=None):
        self.now = start or datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)
        return self.now


class SequentialIds:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"evt-{self.n:04d}"


class GovernanceTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "factory"
        self.clock = FakeClock()
        self.ids = SequentialIds()
        self.ledger = flog.FactoryLedger(self.root, clock=self.clock, id_factory=self.ids)
        self.gov = gov.ModuleGovernance(self.ledger, clock=self.clock)

    def advance(self):
        self.clock.advance()

    def bring_up_to_ready_for_review(self, policy, builder="codex"):
        self.gov.plan(policy, provider=policy.owner_provider)
        self.advance()
        self.gov.architect(policy, provider=policy.owner_provider)
        self.advance()
        self.gov.start_building(policy, provider=builder)
        self.advance()
        self.gov.request_handoff(policy, provider=builder, checkpoint_commit="c" * 40, evidence_refs=["tests: green"])
        self.advance()


class OwnerBuilderDifferTests(GovernanceTestBase):
    def test_owner_and_builder_can_differ(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex")
        self.gov.plan(policy, provider="claude")
        self.advance()
        self.gov.architect(policy, provider="claude")
        self.advance()
        event = self.gov.start_building(policy, provider="codex")
        self.assertEqual(event["provider"], "codex")
        self.assertEqual(self.gov.current_lifecycle_state("knowledge"), gov.ModuleLifecycleState.BUILDING)


class BuilderCloserDifferTests(GovernanceTestBase):
    def test_builder_and_closer_can_differ(self):
        policy = gov.OwnershipPolicy(
            module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="claude",
        )
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.certify(policy, provider="claude", certification_status="PASSED")
        self.advance()
        event = self.gov.close(policy, provider="claude")
        self.assertEqual(event["closer"], "claude")
        self.assertEqual(self.gov.current_lifecycle_state("knowledge"), gov.ModuleLifecycleState.CLOSED)


class InvalidCloserRejectedTests(GovernanceTestBase):
    def test_closer_not_matching_policy_is_rejected(self):
        policy = gov.OwnershipPolicy(
            module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="codex",
        )
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.certify(policy, provider="claude", certification_status="PASSED")
        self.advance()
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.close(policy, provider="mallory")
        self.assertEqual(ctx.exception.code, "ROLE_NOT_PERMITTED")
        self.assertEqual(self.gov.current_lifecycle_state("knowledge"), gov.ModuleLifecycleState.CERTIFYING)

    def test_unset_closer_provider_permits_nobody(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex")
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.certify(policy, provider="claude", certification_status="PASSED")
        self.advance()
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.close(policy, provider="claude")
        self.assertEqual(ctx.exception.code, "ROLE_NOT_PERMITTED")


class ContributorCannotBecomeOwnerTests(GovernanceTestBase):
    def test_contributor_permission_does_not_imply_ownership(self):
        policy = gov.OwnershipPolicy(
            module="knowledge", owner_provider="claude", allowed_contributors=("alice",),
        )
        self.assertTrue(gov.is_role_permitted(policy, "alice", gov.Role.CONTRIBUTOR.value))
        self.assertFalse(gov.is_role_permitted(policy, "alice", gov.Role.OWNER.value))
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.plan(policy, provider="alice", role=gov.Role.OWNER.value)
        self.assertEqual(ctx.exception.code, "ROLE_NOT_PERMITTED")
        self.assertIsNone(self.gov.current_lifecycle_state("knowledge"))


class BuilderSuccessNotClosedTests(GovernanceTestBase):
    def test_ready_for_review_is_not_closed_and_direct_close_is_rejected(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="claude")
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.assertEqual(self.gov.current_lifecycle_state("knowledge"), gov.ModuleLifecycleState.READY_FOR_REVIEW)
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.close(policy, provider="claude")
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")


class ExplicitClosureRecordsCloserTests(GovernanceTestBase):
    def test_close_records_closer_identity(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="claude")
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.certify(policy, provider="claude", certification_status="PASSED")
        self.advance()
        event = self.gov.close(policy, provider="claude", closer="nacho_1_9_9_3@hotmail.com")
        self.assertEqual(event["closer"], "nacho_1_9_9_3@hotmail.com")
        status = self.gov.status("knowledge")
        self.assertEqual(status["closer"], "nacho_1_9_9_3@hotmail.com")
        self.assertEqual(status["lifecycle_state"], "CLOSED")


class ReworkReturnsToPreCloseStateTests(GovernanceTestBase):
    def test_rework_from_certifying_returns_to_building(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="claude")
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.certify(policy, provider="claude", certification_status="PASSED")
        self.advance()
        self.gov.request_rework(policy, provider="claude", role=gov.Role.AUDITOR.value, reason="missed edge case")
        self.advance()
        self.assertEqual(self.gov.current_lifecycle_state("knowledge"), gov.ModuleLifecycleState.REWORK_REQUIRED)
        event = self.gov.start_building(policy, provider="codex")
        self.assertEqual(event["provider"], "codex")
        self.assertEqual(self.gov.current_lifecycle_state("knowledge"), gov.ModuleLifecycleState.BUILDING)

    def test_rework_cannot_skip_straight_to_closed(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="claude")
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.request_rework(policy, provider="claude", role=gov.Role.AUDITOR.value)
        self.advance()
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.close(policy, provider="claude")
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")


class FullTransitionChainTests(GovernanceTestBase):
    def test_factory_history_represents_full_transition_chain(self):
        policy = gov.OwnershipPolicy(
            module="knowledge", module_version="v1", module_class=gov.MODULE_CLASS_PLATFORM,
            owner_provider="claude", builder_provider="codex", closer_provider="claude",
        )
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.certify(policy, provider="claude", certification_status="PASSED")
        self.advance()
        self.gov.close(policy, provider="claude", closer="ops")

        events = self.ledger.events(module="knowledge")
        chain = [(e["extra"]["lifecycle_state"]) for e in events]
        self.assertEqual(
            chain,
            ["PLANNED", "ARCHITECTED", "BUILDING", "READY_FOR_REVIEW", "AUDITING", "CERTIFYING", "CLOSED"],
        )
        modules = gov.materialize_module_governance(events)
        entry = modules["knowledge@v1"]
        self.assertEqual(entry["lifecycle_state"], "CLOSED")
        self.assertEqual(entry["certification_status"], "PASSED")
        self.assertEqual(entry["closer"], "ops")
        self.assertEqual(entry["module_class"], gov.MODULE_CLASS_PLATFORM)
        self.assertEqual(entry["owner_provider"], "claude")
        self.assertEqual(entry["builder_provider"], "codex")
        self.assertEqual(entry["closer_provider"], "claude")
        self.assertEqual(entry["event_count"], 7)

        # Untouched by governance - the R21-C engine's own module state is
        # never overwritten by a lifecycle value.
        self.assertIsNone(flog.materialize_modules(events)["knowledge@v1"]["state"])


class HandoffContractTests(GovernanceTestBase):
    def test_handoff_record_carries_references_not_transcripts(self):
        policy = gov.OwnershipPolicy(module="billing", owner_provider="claude", builder_provider="codex")
        self.gov.plan(policy, provider="claude")
        self.advance()
        self.gov.architect(policy, provider="claude")
        self.advance()
        self.gov.start_building(policy, provider="codex")
        self.advance()
        handoff = self.gov.request_handoff(
            policy, provider="codex", checkpoint_commit="a" * 40,
            evidence_refs=["workers/w1/evidence/", "certification: PASSED"], known_debt=["TODO: add retry"],
        )
        self.assertEqual(handoff.schema_version, gov.HANDOFF_SCHEMA_VERSION)
        self.assertEqual(handoff.from_role, gov.Role.BUILDER.value)
        self.assertEqual(handoff.checkpoint_commit, "a" * 40)
        self.assertEqual(self.gov.current_lifecycle_state("billing"), gov.ModuleLifecycleState.READY_FOR_REVIEW)
        events = self.ledger.events(module="billing")
        self.assertIn("handoff", events[-1]["extra"])
        self.assertEqual(events[-1]["extra"]["handoff"]["checkpoint_commit"], "a" * 40)

    def test_oversized_evidence_ref_is_rejected(self):
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            gov.build_handoff(
                module="billing", from_role=gov.Role.BUILDER.value, to_role=gov.Role.AUDITOR.value,
                requested_next_role=gov.Role.AUDITOR.value, created_at_utc="2026-09-23T08:00:00+00:00",
                evidence_refs=["x" * 400],
            )
        self.assertEqual(ctx.exception.code, "HANDOFF_REF_TOO_LARGE")

    def test_unknown_role_in_handoff_is_rejected(self):
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            gov.build_handoff(
                module="billing", from_role="NOT_A_ROLE", to_role=gov.Role.AUDITOR.value,
                requested_next_role=gov.Role.AUDITOR.value, created_at_utc="2026-09-23T08:00:00+00:00",
            )
        self.assertEqual(ctx.exception.code, "UNKNOWN_ROLE")


class IllegalTransitionTests(GovernanceTestBase):
    def test_cannot_skip_states(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex")
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.start_building(policy, provider="codex")
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

    def test_closed_module_has_no_further_transitions(self):
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="claude")
        self.bring_up_to_ready_for_review(policy, builder="codex")
        self.gov.start_audit(policy, provider="claude")
        self.advance()
        self.gov.certify(policy, provider="claude")
        self.advance()
        self.gov.close(policy, provider="claude")
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.request_rework(policy, provider="claude", role=gov.Role.AUDITOR.value)
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")

    def test_role_wrong_for_transition_is_rejected_even_if_policy_permits_provider(self):
        # `claude` is permitted as BOTH owner and closer, but may not drive
        # BUILDING with role=CLOSER: role-for-transition is checked too.
        policy = gov.OwnershipPolicy(module="knowledge", owner_provider="claude", closer_provider="claude")
        self.gov.plan(policy, provider="claude")
        self.advance()
        self.gov.architect(policy, provider="claude")
        self.advance()
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.start_building(policy, provider="claude", role=gov.Role.CLOSER.value)
        self.assertEqual(ctx.exception.code, "ROLE_NOT_PERMITTED_FOR_TRANSITION")


if __name__ == "__main__":
    unittest.main()
