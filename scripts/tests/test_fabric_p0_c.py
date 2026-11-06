"""FABRIC-V1-P0-C (A01-F2): adversarial governance tests. `extra_overrides`
may never forge governance-owned keys, a rejected transition writes no
event, and closure requires a consistent PASSED certification. The
legitimate handoff override keeps working."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_module_governance as gov


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "factory"
        clock = _Clock()
        self.ledger = flog.FactoryLedger(self.root, clock=clock)
        self.gov = gov.ModuleGovernance(self.ledger, clock=clock)
        self.policy = gov.OwnershipPolicy(
            module="knowledge", owner_provider="claude", builder_provider="codex", closer_provider="claude",
        )

    def events(self):
        return self.ledger.events(module="knowledge")

    def state(self):
        return self.gov.current_lifecycle_state("knowledge")

    def to_building(self):
        self.gov.plan(self.policy, provider="claude")
        self.gov.architect(self.policy, provider="claude")
        self.gov.start_building(self.policy, provider="codex")

    def to_auditing(self):
        self.to_building()
        self.gov.request_handoff(self.policy, provider="codex", checkpoint_commit="c" * 40)
        self.gov.start_audit(self.policy, provider="claude")


class ReservedExtraOverrideTests(_Base):
    def test_extra_override_lifecycle_closed_is_rejected_without_event(self):
        self.to_building()
        before = self.events()
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov._transition(
                self.policy, provider="codex", role=gov.Role.BUILDER.value,
                to_state=gov.ModuleLifecycleState.READY_FOR_REVIEW,
                extra_overrides={"lifecycle_state": "CLOSED"},
            )
        self.assertEqual(ctx.exception.code, "RESERVED_EXTRA_OVERRIDE")
        self.assertEqual(self.events(), before)
        self.assertEqual(self.state(), gov.ModuleLifecycleState.BUILDING)
        self.assertNotEqual(self.gov.status("knowledge")["lifecycle_state"], "CLOSED")

    def test_every_reserved_key_is_rejected_on_public_transitions(self):
        for key in ("lifecycle_state", "module_class", "owner_provider", "builder_provider", "closer_provider",
                    "providers", "provider", "owner", "closer", "certification_status", "allowed_contributors"):
            with self.subTest(key=key):
                with self.assertRaises(gov.ModuleGovernanceError) as ctx:
                    self.gov.plan(self.policy, provider="claude", extra_overrides={key: "mallory"})
                self.assertEqual(ctx.exception.code, "RESERVED_EXTRA_OVERRIDE")
                self.assertEqual(self.events(), [])
                self.assertIsNone(self.state())

    def test_non_dict_extra_overrides_is_rejected(self):
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.plan(self.policy, provider="claude", extra_overrides=[("lifecycle_state", "CLOSED")])
        self.assertEqual(ctx.exception.code, "INVALID_EXTRA_OVERRIDES")
        self.assertEqual(self.events(), [])

    def test_illegal_transition_writes_no_event(self):
        self.to_building()
        before = self.events()
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.close(self.policy, provider="claude")
        self.assertEqual(ctx.exception.code, "ILLEGAL_LIFECYCLE_TRANSITION")
        self.assertEqual(self.events(), before)

    def test_legitimate_handoff_override_is_preserved(self):
        self.to_building()
        handoff = self.gov.request_handoff(self.policy, provider="codex", checkpoint_commit="a" * 40,
                                           evidence_refs=["tests: green"])
        last = self.events()[-1]
        self.assertEqual(last["extra"]["lifecycle_state"], "READY_FOR_REVIEW")
        self.assertEqual(last["extra"]["handoff"], handoff.to_dict())
        self.assertEqual(last["extra"]["owner_provider"], "claude")
        self.assertEqual(self.state(), gov.ModuleLifecycleState.READY_FOR_REVIEW)


class CertificationBeforeCloseTests(_Base):
    def test_failed_certification_cannot_close(self):
        self.to_auditing()
        self.gov.certify(self.policy, provider="claude", certification_status="FAILED")
        before = self.events()
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.close(self.policy, provider="claude")
        self.assertEqual(ctx.exception.code, "CERTIFICATION_NOT_PASSED")
        self.assertEqual(self.events(), before)
        self.assertEqual(self.state(), gov.ModuleLifecycleState.CERTIFYING)

    def test_inconsistent_later_certification_cannot_close(self):
        self.to_auditing()
        self.gov.certify(self.policy, provider="claude")
        self.ledger.append(flog.CERTIFICATION_FINISHED, module="knowledge", certification_status="FAILED")
        with self.assertRaises(gov.ModuleGovernanceError) as ctx:
            self.gov.close(self.policy, provider="claude")
        self.assertEqual(ctx.exception.code, "CERTIFICATION_NOT_PASSED")
        self.assertEqual(self.state(), gov.ModuleLifecycleState.CERTIFYING)

    def test_empty_certification_status_is_not_coerced_to_passed(self):
        self.to_auditing()
        before = self.events()
        for bad in ("", "   ", 1):
            with self.subTest(bad=bad):
                with self.assertRaises(gov.ModuleGovernanceError) as ctx:
                    self.gov.certify(self.policy, provider="claude", certification_status=bad)
                self.assertEqual(ctx.exception.code, "INVALID_CERTIFICATION_STATUS")
                self.assertEqual(self.events(), before)

    def test_passed_certification_still_closes(self):
        self.to_auditing()
        self.gov.certify(self.policy, provider="claude")
        event = self.gov.close(self.policy, provider="claude")
        self.assertEqual(event["closer"], "claude")
        self.assertEqual(self.state(), gov.ModuleLifecycleState.CLOSED)


if __name__ == "__main__":
    unittest.main()
