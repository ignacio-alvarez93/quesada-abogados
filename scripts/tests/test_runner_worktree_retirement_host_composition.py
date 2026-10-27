"""FCP-4E-02d: non-live retirement evidence composition (dry run, NOT LIVE).

Proposals are REAL FCP-4E-02a proposals built from the synthetic, pure 02a
fixtures (paths under a root that does not exist; no Git, no real
worktree). Command and queue-manifest signing keys are ephemeral Ed25519
keys generated in memory by these tests only: they stand in for the
Director's and the operator's own tools; the module under test signs
nothing. Every ledger is a disposable SQLite file in a fresh private
temporary "host" directory, provisioned and written ONLY by these tests
through the merged 02c writer API (the composition itself only reads). The
only subprocess is the disposable 02c crash fixture. No network is
reachable. Nothing here is skipped: without `cryptography` the tests FAIL
(CI installs the pinned dependency and enforces zero skips).
"""

import ast
import base64
import dataclasses
import hashlib
import inspect
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import claude_queue
from scripts.ai import runner_worktree_inventory as inv
from scripts.ai import runner_worktree_retirement as wr
from scripts.ai import runner_worktree_retirement_authorization as wra
from scripts.ai import runner_worktree_retirement_host_authority as rha
from scripts.ai import runner_worktree_retirement_host_composition as rhc
from scripts.ai import runner_worktree_retirement_host_ledger as rlg
from scripts.tests import test_runner_worktree_retirement_authorization as twra
from scripts.tests import test_runner_worktree_retirement_host_authority as t
from scripts.tests import test_runner_worktree_retirement_host_ledger as tlg

if rha.CRYPTO_AVAILABLE:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MODULE_PATH = Path(rhc.__file__)
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
# sha256 (LF-normalized) of the merged sources (8b81c77); 02d must not change them.
PINNED_SOURCES = {
    "scripts/ai/runner_worktree_retirement.py":
        "58ab30c4de9be940e6984c7f07d66d8201a54e9f51ef3dab123958f3d9a40dbe",
    "scripts/ai/runner_worktree_inventory.py":
        "95a3c5be639546d1e2f9ed5bdcd12d6fda2a2c8c19a1f03780ee99f0f4c6dbd0",
    "scripts/ai/runner_worktree_retirement_authorization.py":
        "c51068e0eff2aa4a20a2edf712d86a716cc784e6a9e52b1c877e5a9d8cc205c0",
    "scripts/ai/runner_worktree_retirement_host_authority.py":
        "3c13c160fed6dd5510c0586a40e4cc31248acce0aadd9ada47d69f7ea1c94ccd",
    "scripts/ai/runner_worktree_retirement_host_ledger.py":
        "0079d485dce0e2d183b1952c465cec7828d9b59cc5f2035e82a500c4e20c9fb1",
    "scripts/tests/test_runner_worktree_retirement_authorization.py":
        "c4431cc2ab26c0323e01c982a12baf462ffc52361c7095c0c645d113870cbfae",
    "scripts/tests/test_runner_worktree_retirement_host_authority.py":
        "68b5bdf20f0241840808bd8d18968d86c956698727188a62b5c46e9c6d03b9b0",
    # FCP-4E-02d-FIX1: only the 02c provisioning-exposure test was amended to
    # admit this composition as its single AST-checked read-only importer.
    "scripts/tests/test_runner_worktree_retirement_host_ledger.py":
        "cdc25d4dfaaefc64a3d06fc8142101705bd3ed8534643b9696726e207bce9a59",
}

NOW = t.NOW
AT = NOW + timedelta(seconds=10)    # the caller's clock for a composition
HOST = t.HOST
LEDGER_NAME = "host-01" + rlg.LEDGER_FILENAME_SUFFIX
MANIFEST_KEY_ID = "fcp4e02d-queue-key-operator-1"
SIGNER = "host-operator-1"
DEFAULT = rhc.SOURCE_REGISTERED_WORKTREE_DEFAULT
OVERRIDE = rhc.SOURCE_DECLARED_OVERRIDE
MAIN_QUEUE = rhc.default_queue_root(twra.REPO)
TARGET_QUEUE = rhc.default_queue_root(twra.WT)
READ_ROOTS = (twra.QUEUE, MAIN_QUEUE)     # what the synthetic FCP-4D report read
_NETWORK = []
_FIXED_FLAGS = (("authorizes_action", False), ("deletion_authorized", False), ("branch_deletion_authorized", False),
                ("issued", False), ("consumed", False), ("host_identity_authenticated", False),
                ("queue_scope_attested", False), ("clock_attested", False), ("external_queues_excluded", False),
                ("fresh_host_reassessment_performed", False), ("source_records_host_verified", False),
                ("single_use_enforced", False), ("human_review_required", True))
_MANIFEST_RESULT_FLAGS = (("completeness_established", False), ("external_queues_excluded", False),
                          ("queue_scope_attested", False), ("host_identity_authenticated", False),
                          ("clock_attested", False), ("authorizes_action", False))
_MANIFEST_FLAGS = (("acknowledged_external_queues_unprovable", True), ("completeness_established", False),
                   ("external_queues_excluded", False), ("queue_scope_attested", False),
                   ("host_identity_authenticated", False))
_SCOPE_SKIPPED = (rhc.CMP_MANIFEST_REFUSED, rhc.CMP_SCOPE_NOT_EVALUATED)


def _deny_network(*_args, **_kwargs):
    _NETWORK.append("attempt")
    raise OSError("network denied during retirement composition tests")


def setUpModule():
    for target, name in ((socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo")):
        patcher = mock.patch.object(target, name, _deny_network)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def sources(record_changes=None, facts_changes=None, **report_changes):
    """(report, record) of the 02a fixture whose report also read the main
    worktree's default queue root (as a real FCP-4D host would declare it)."""
    report_changes.setdefault("queue_roots", READ_ROOTS)
    return twra.fixture(record_changes, facts_changes, **report_changes)


def build(report, record, host_id=HOST):
    return wra.build_retirement_proposal(report, record, host_id=host_id)


def default_root(key) -> dict:
    return {"root": rhc.default_queue_root(key), "source": DEFAULT, "worktree_key": key}


def override_root(path) -> dict:
    return {"root": path, "source": OVERRIDE, "worktree_key": None}


def standard_roots() -> list:
    return sorted([default_root(twra.REPO), default_root(twra.WT), override_root(twra.QUEUE)],
                  key=lambda d: d["root"])


def manifest_body(proposal, **changes) -> dict:
    body = dict(
        format=rhc.MANIFEST_FORMAT, manifest_id="queue-scope-1", key_id=MANIFEST_KEY_ID, signer_id=SIGNER,
        host_id=HOST, common_dir=proposal.scope.common_dir, report_content_digest=proposal.report_content_digest,
        scope_digest=proposal.scope.scope_digest, issued_at=t.stamp(-30), expires_at=t.stamp(120),
        roots=standard_roots(), host_claims_roots_complete=True, acknowledged_external_queues_unprovable=True)
    body.update(changes)
    return body


def manifest_message(body, domain=rhc.MANIFEST_SIGNATURE_DOMAIN) -> bytes:
    """What the operator's own signing tool would sign (test stand-in)."""
    return domain + b"\n" + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def manifest_envelope(body, private=None, *, signature=None, domain=rhc.MANIFEST_SIGNATURE_DOMAIN,
                      extra=None) -> bytes:
    if signature is None:
        signature = private.sign(manifest_message(body, domain))
    document = {"manifest": body, "signature": base64.b64encode(signature).decode("ascii")
                if isinstance(signature, bytes) else signature}
    document.update(extra or {})
    return json.dumps(document).encode("utf-8")


def make_trust(public, **changes) -> rhc.QueueManifestTrustConfig:
    return dataclasses.replace(rhc.QueueManifestTrustConfig(
        format=rhc.MANIFEST_TRUST_FORMAT, host_id=HOST, allowed_signer_ids=(SIGNER,),
        keys=(rhc.PinnedQueueManifestKey(MANIFEST_KEY_ID, SIGNER, public),), revoked_key_ids=()), **changes)


class _StubLedger:
    """Answers the three read queries with crafted values (unit tests of the
    evidence cross-checks only; never a ledger)."""

    def __init__(self, evidence, revoked, trail, error=None):
        self._evidence, self._revoked, self._trail, self._error = evidence, revoked, trail, error

    def _maybe_fail(self):
        if self._error:
            raise rlg.RetirementLedgerRefused(self._error)

    def get_command(self, _command_id):
        self._maybe_fail()
        return self._evidence

    def is_revoked(self, _command_id):
        return self._revoked

    def audit_trail(self):
        return self._trail


class CompositionCase(unittest.TestCase):
    """A real 02a proposal, a Director key pinned in a caller-supplied 02b
    config, a disposable 02c ledger holding re-verified evidence of the
    signed command, and a signed queue scope manifest."""

    def setUp(self):
        self.assertTrue(rha.CRYPTO_AVAILABLE and rhc.CRYPTO_AVAILABLE,
                        "cryptography is required: these tests never skip")
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="fcp4e02d-")))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.host_dir = self.base / "isolated-host"
        self.host_dir.mkdir(mode=0o700)
        self.untrusted = self.base / "untrusted-worktrees"
        self.untrusted.mkdir(mode=0o700)
        self.roots = (str(self.untrusted),)
        self.path = self.host_dir / LEDGER_NAME
        self.report, self.record = sources()
        self.proposal = build(self.report, self.record)
        self.key = Ed25519PrivateKey.generate()
        self.config = t.make_config(t.raw_public(self.key))
        self.manifest_key = Ed25519PrivateKey.generate()
        self.trust = make_trust(t.raw_public(self.manifest_key))
        self.envelope = self.signed()
        self.assertEqual(self.provision(self.path).status, rlg.STATUS_PROVISIONED_EMPTY)
        self.ledger = self.open(self.path)
        self.assertEqual(self.record_evidence(self.ledger, self.envelope).status,
                         rlg.STATUS_RECORDED_NON_AUTHORIZING)
        self.manifest = self.signed_manifest()

    def tearDown(self):
        self.assertEqual(_NETWORK, [])
        super().tearDown()

    # Helpers ---------------------------------------------------------------
    def signed(self, proposal=None, private=None, **changes) -> bytes:
        return t.envelope(t.command_for(proposal or self.proposal, **changes), private or self.key)

    def signed_manifest(self, proposal=None, private=None, **changes) -> bytes:
        return manifest_envelope(manifest_body(proposal or self.proposal, **changes), private or self.manifest_key)

    def provision(self, path, host_id=HOST, at=NOW):
        return rlg.provision(str(path), host_id=host_id, forbidden_roots=self.roots, clock=lambda: at)

    def open(self, path, host_id=HOST):
        return rlg.open_existing(str(path), host_id=host_id, forbidden_roots=self.roots)

    def record_evidence(self, ledger, envelope, *, proposal=None, report=None, record=None, at=NOW):
        return ledger.record_reverified_command_evidence(
            envelope, config=self.config, proposal=proposal or self.proposal, clock=lambda: at,
            report=report or self.report, inventory_record=record or self.record)

    def fresh_ledger(self, name="other", host_id=HOST, at=NOW):
        path = self.host_dir / (name + rlg.LEDGER_FILENAME_SUFFIX)
        self.assertEqual(self.provision(path, host_id=host_id, at=at).status, rlg.STATUS_PROVISIONED_EMPTY)
        return path, self.open(path, host_id=host_id)

    def compose(self, **changes):
        kwargs = dict(config=self.config, proposal=self.proposal, report=self.report,
                      inventory_record=self.record, manifest_envelope=self.manifest, manifest_trust=self.trust,
                      ledger_path=str(self.path), ledger_forbidden_roots=self.roots, now=AT)
        envelope = changes.pop("envelope", self.envelope)
        kwargs.update(changes)
        return rhc.compose_retirement_evidence(envelope, **kwargs)

    def chain(self, report, record, *, index, roots=None, **manifest_changes) -> dict:
        """A complete consistent chain for other sources: proposal, signed
        command recorded in the shared ledger, and a manifest bound to it."""
        proposal = build(report, record)
        envelope = self.signed(proposal, command_id=f"retire-cmd-chain-{index}", nonce=tlg.nonce(100 + index))
        recorded = self.record_evidence(self.ledger, envelope, proposal=proposal, report=report, record=record)
        self.assertEqual(recorded.status, rlg.STATUS_RECORDED_NON_AUTHORIZING, recorded.reason_codes)
        if roots is not None:
            manifest_changes["roots"] = roots
        return dict(envelope=envelope, proposal=proposal, report=report, inventory_record=record,
                    manifest_envelope=self.signed_manifest(proposal, **manifest_changes))

    def snapshot(self, directory=None):
        directory = Path(directory or self.host_dir)
        files = {}
        for entry in sorted(os.listdir(directory)):
            full = directory / entry
            if full.is_file():
                st = os.stat(full)
                files[entry] = (hashlib.sha256(full.read_bytes()).hexdigest(), st.st_mtime_ns, st.st_size)
            else:
                files[entry] = None
        return files

    # Assertions ------------------------------------------------------------
    def assertFixed(self, result):
        self.assertIs(type(result), rhc.RetirementEvidenceComposition)
        self.assertEqual(result.schema, rhc.COMPOSITION_SCHEMA)
        for name, value in _FIXED_FLAGS:
            self.assertIs(getattr(result, name), value, name)
        self.assertEqual(result.limitations, rhc.COMPOSITION_LIMITATIONS)
        self.assertEqual(result.blocking_uncertainties, rhc.BLOCKING_UNCERTAINTIES)
        self.assertEqual(result.live_activation_blocker, rhc.LIVE_ACTIVATION_BLOCKER)
        for code in result.reason_codes:
            self.assertIn(code, rhc.COMPOSITION_REASON_CODES)
        return result

    def assertConsistent(self, result):
        self.assertFixed(result)
        self.assertEqual((result.status, result.reason_codes), (rhc.STATUS_DRY_RUN_EVIDENCE_CONSISTENT, ()),
                         (result.proposal_findings, result.command_verification_codes, result.ledger_codes,
                          result.manifest_codes))
        return result

    def assertRefused(self, result, *codes, exact=True):
        self.assertFixed(result)
        self.assertEqual(result.status, rhc.STATUS_REFUSED)
        if exact:
            self.assertEqual(set(result.reason_codes), set(codes), result)
        else:
            for code in codes:
                self.assertIn(code, result.reason_codes)
        return result

    def assertManifestRefused(self, raw, code, **compose_changes):
        direct = rhc.verify_queue_scope_manifest(raw, trust=compose_changes.get("manifest_trust", self.trust),
                                                 now=compose_changes.get("now", AT))
        self.assertIs(type(direct), rhc.QueueScopeManifestVerification)
        self.assertEqual((direct.status, direct.reason_codes, direct.manifest), (rhc.STATUS_REFUSED, (code,), None))
        self.assertIn(code, rhc.MANIFEST_REFUSAL_CODES)
        for name, value in _MANIFEST_RESULT_FLAGS:
            self.assertIs(getattr(direct, name), value, name)
        result = self.assertRefused(self.compose(manifest_envelope=raw, **compose_changes), *_SCOPE_SKIPPED)
        self.assertEqual(result.manifest_codes, (code,))
        self.assertEqual(result.manifest_status, rhc.STATUS_REFUSED)
        return result

    def assertSourceRefused(self, result, finding):
        self.assertIn(rhc.CMP_PROPOSAL_SOURCE_INVALID, result.reason_codes)
        self.assertIn(rhc.CMP_SCOPE_NOT_EVALUATED, result.reason_codes)
        self.assertIn(finding, result.proposal_findings)
        self.assertEqual(result.status, rhc.STATUS_REFUSED)
        self.assertFixed(result)


# ---------------------------------------------------------------------------
# 1. Synthetic consistency: informational only, never ready for anything
# ---------------------------------------------------------------------------

class PositiveCompositionTests(CompositionCase):
    def test_consistent_dry_run_reports_every_layer_and_its_bindings(self):
        result = self.assertConsistent(self.compose())
        command = t.command_for(self.proposal)
        digest = hashlib.sha256(rha.canonical_command_message(command)).hexdigest()
        self.assertEqual((result.proposal_findings, result.command_verification_codes, result.ledger_codes,
                          result.manifest_codes), ((), (), (), ()))
        self.assertEqual((result.signature_verified, result.source_records_revalidated,
                          result.ledger_evidence_present, result.ledger_record_state),
                         (True, True, True, rlg.RECORD_STATE_RECORDED_NON_AUTHORIZING))
        self.assertEqual((result.command_id, result.nonce, result.command_message_digest, result.proposal_digest,
                          result.scope_digest, result.target_identity_digest, result.host_id_label),
                         ("retire-cmd-1", t.NONCE, digest, self.proposal.proposal_digest,
                          self.proposal.scope.scope_digest, self.proposal.target.identity_digest, HOST))
        self.assertEqual(result.ledger_clock_high_water_mark, self.ledger.clock_high_water_mark())
        self.assertEqual((result.manifest_status, result.manifest_signature_verified),
                         (rhc.STATUS_STRUCTURE_VERIFIED_NOT_ATTESTED, True))
        self.assertEqual(result.manifest_digest, hashlib.sha256(manifest_message(
            manifest_body(self.proposal))).hexdigest())

    def test_consistency_never_purports_readiness_for_issuance(self):
        result = self.assertConsistent(self.compose())
        # No manifest here (or anywhere in this module) attests queue scope,
        # so the result names the blockers instead of a readiness.
        for blocker in ("QUEUE_SCOPE_NOT_ATTESTED", "EXTERNAL_QUEUES_NOT_PROVABLE", "HOST_IDENTITY_NOT_AUTHENTICATED",
                        "CLOCK_NOT_ATTESTED", "FRESH_HOST_REASSESSMENT_NOT_PERFORMED",
                        "HUMAN_RETIREMENT_POLICY_PENDING", "LIVE_ACTIVATION_BLOCKED"):
            self.assertIn(blocker, result.blocking_uncertainties)
        self.assertIs(result.queue_scope_attested, False)
        for word in ("AUTHORIZED", "ISSUED", "PERMITTED", "ELIGIBLE", "DELETION", "APPROVED", "READY", "PERMIT"):
            self.assertNotIn(word, result.status)
        names = {f.name for f in dataclasses.fields(result)} - {name for name, _ in _FIXED_FLAGS}
        for word in ("ready", "eligible", "permit", "approved", "authorized", "token", "issuable", "grant"):
            self.assertFalse(any(word in name for name in names), word)
        callables = [n for n, v in vars(rhc).items() if callable(v) and not n.startswith("_")]
        for name in callables:
            for word in ("issue", "consume", "reserve", "approve", "permit", "execute", "authorize", "grant"):
                self.assertNotIn(word, name.lower(), name)
        with self.assertRaises(rhc.RetirementCompositionNotLive) as ctx:
            rhc.compose_live(result)
        self.assertEqual((ctx.exception.code, str(ctx.exception)), (rhc.NOT_LIVE, rhc.NOT_LIVE))

    def test_signed_complete_manifest_still_leaves_external_queues_unprovable(self):
        verification = rhc.verify_queue_scope_manifest(self.manifest, trust=self.trust, now=AT)
        self.assertEqual((verification.status, verification.reason_codes, verification.signature_verified),
                         (rhc.STATUS_STRUCTURE_VERIFIED_NOT_ATTESTED, (), True))
        for name, value in _MANIFEST_RESULT_FLAGS:
            self.assertIs(getattr(verification, name), value, name)
        m = verification.manifest
        self.assertIs(m.host_claims_roots_complete, True)   # a signed claim ...
        for name, value in _MANIFEST_FLAGS:                  # ... that establishes nothing
            self.assertIs(getattr(m, name), value, name)
        self.assertEqual(rhc.canonical_manifest_message(m), manifest_message(manifest_body(self.proposal)))
        result = self.assertConsistent(self.compose())
        self.assertIs(result.external_queues_excluded, False)
        self.assertIs(result.queue_scope_attested, False)
        for limitation in ("SIGNED_MANIFEST_IS_NOT_QUEUE_COMPLETENESS", "EXTERNAL_QUEUES_NOT_PROVABLE",
                           "TARGET_LOCAL_QUEUE_INFERRED_FROM_CALLER_CLEANLINESS_FACTS"):
            self.assertIn(limitation, result.limitations)

    def test_repeated_composition_is_identical_and_not_single_use(self):
        before = self.snapshot()
        first, second = self.compose(), self.compose()
        self.assertConsistent(first)
        self.assertEqual(first, second)
        self.assertIs(second.consumed, False)
        self.assertIs(second.single_use_enforced, False)
        self.assertIn("REPEATED_EVALUATION_NOT_SINGLE_USE", second.limitations)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.ledger.audit_trail()), 2)   # provisioned + recorded: nothing added

    def test_fixed_flags_are_not_constructor_arguments(self):
        result = self.compose()
        for cls, flags in ((rhc.RetirementEvidenceComposition, _FIXED_FLAGS),
                           (rhc.QueueScopeManifestVerification, _MANIFEST_RESULT_FLAGS),
                           (rhc.QueueScopeManifest, _MANIFEST_FLAGS)):
            self.assertTrue(cls.__dataclass_params__.frozen, cls.__name__)
            fields = {f.name: f for f in dataclasses.fields(cls)}
            for name, value in flags:
                self.assertIs(fields[name].init, False, name)
                self.assertIs(fields[name].default, value, name)
        for name in ("limitations", "blocking_uncertainties", "live_activation_blocker"):
            self.assertIs({f.name: f for f in dataclasses.fields(result)}[name].init, False, name)
        init = {f.name: getattr(result, f.name) for f in dataclasses.fields(result) if f.init}
        for name, value in _FIXED_FLAGS:
            with self.assertRaises(TypeError):
                rhc.RetirementEvidenceComposition(**init, **{name: not value})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.authorizes_action = True
        with self.assertRaises(ValueError):
            dataclasses.replace(result, queue_scope_attested=True)
        self.assertIs(self.trust.host_identity_authenticated, False)
        self.assertIs({f.name: f for f in dataclasses.fields(rhc.QueueManifestTrustConfig)}[
            "host_identity_authenticated"].init, False)

    def test_chain_helper_is_itself_consistent(self):
        report, record = sources()
        self.assertConsistent(self.compose(**self.chain(report, record, index=1)))

    def test_source_comparison_never_marks_the_host_verified(self):
        # A "fresh" report rebuilt by the caller is still caller-supplied.
        fresh_report, fresh_record = sources()
        result = self.assertConsistent(self.compose(report=fresh_report, inventory_record=fresh_record))
        self.assertIs(result.source_records_revalidated, True)
        self.assertIs(result.source_records_host_verified, False)
        self.assertIs(result.host_identity_authenticated, False)
        self.assertIs(result.fresh_host_reassessment_performed, False)
        for limitation in ("SOURCE_RECORDS_CALLER_SUPPLIED", "CALLER_CRAFTED_CANDIDATE_INDISTINGUISHABLE",
                           "FRESH_HOST_REASSESSMENT_NOT_PERFORMED", "HOST_ID_IS_A_LABEL"):
            self.assertIn(limitation, result.limitations)


# ---------------------------------------------------------------------------
# 2. Classification and source tampering: never upgraded
# ---------------------------------------------------------------------------

class SourceClassificationTests(CompositionCase):
    def test_blocked_insufficient_and_review_sources_are_refused(self):
        for facts, finding in (({"is_self_worktree": True}, wra.REFUSED_BLOCKED),
                               ({"topology_proven": False}, wra.REFUSED_INSUFFICIENT_EVIDENCE),
                               ({"worktree_local_refs": ("refs/worktree/x",)}, wra.REFUSED_REVIEW_REQUIRED)):
            with self.subTest(finding=finding):
                report, record = sources(facts_changes=facts)
                result = self.assertRefused(self.compose(report=report, inventory_record=record),
                                            rhc.CMP_PROPOSAL_SOURCE_INVALID, rhc.CMP_COMMAND_NOT_VERIFIED,
                                            rhc.CMP_SCOPE_NOT_EVALUATED)
                self.assertIn(finding, result.proposal_findings)
                self.assertEqual(result.command_verification_codes, (rha.RCV_PROPOSAL_SOURCE_MISMATCH,))
                with self.assertRaises(wra.RetirementProposalRefused):
                    build(report, record)   # and no proposal can be built for it

    def test_unknown_or_forged_classification_is_never_upgraded(self):
        blocked_report, record = sources(facts_changes={"is_self_worktree": True})
        assessment = twra.candidate(blocked_report)
        self.assertEqual(assessment.classification, wr.BLOCKED)
        for changes in ({"classification": wr.CANDIDATE_FOR_HUMAN_REVIEW, "reason_codes": ()},
                        {"classification": "FUTURE_CLASSIFICATION"}):
            with self.subTest(changes=changes):
                forged = twra.forge(assessment, **changes)
                report = twra.make_report((twra.main_assessment(), forged), queue_roots=READ_ROOTS)
                self.assertSourceRefused(self.compose(report=report, inventory_record=record), wra.REFUSED_TAMPERED)
        dirty = twra.make_record(clean=False)
        self.assertEqual(dirty.classification, inv.DIRTY)
        forged_record = twra.forge(dirty, classification=inv.IDLE_CLEAN_UNBOUND, reason_codes=())
        result = self.compose(inventory_record=forged_record)
        self.assertSourceRefused(result, wra.REFUSED_TAMPERED)

    def test_missing_duplicated_or_absent_sources_are_refused(self):
        a = twra.candidate(self.report)
        missing = twra.make_report((twra.main_assessment(),), queue_roots=READ_ROOTS)
        self.assertSourceRefused(self.compose(report=missing), wra.REFUSED_TARGET_ABSENT)
        duplicated = twra.make_report((twra.main_assessment(), a, a), queue_roots=READ_ROOTS)
        self.assertSourceRefused(self.compose(report=duplicated), wra.REFUSED_AMBIGUOUS)
        self.assertSourceRefused(self.compose(report=None, inventory_record=None), wra.REFUSED_SCHEMA)
        result = self.compose(report=self.report, inventory_record=None)
        self.assertSourceRefused(result, wra.REFUSED_SCHEMA)
        self.assertEqual(result.command_verification_codes, (rha.RCV_INPUT_INVALID,))

    def test_malformed_or_changed_limitations_are_refused(self):
        for limitations in (wr.LIMITATIONS[:-1], wr.LIMITATIONS + ("EXTRA",), "REMOTE_STATE_NOT_LOCALLY_PROVABLE",
                            tuple(reversed(wr.LIMITATIONS))):
            with self.subTest(limitations=limitations):
                report = twra.forge(self.report, limitations=limitations)
                self.assertSourceRefused(self.compose(report=report), wra.REFUSED_LIMITATIONS_ALTERED)

    def test_forged_proposal_digests_or_flags_are_refused(self):
        for changes, finding, rcv in (
                ({"proposal_digest": "0" * 64}, wra.PROPOSAL_DIGEST_MISMATCH, rha.RCV_PROPOSAL_TAMPERED),
                ({"assessment_classification": wr.REVIEW_REQUIRED}, wra.PROPOSAL_DIGEST_MISMATCH,
                 rha.RCV_PROPOSAL_INVALID),
                ({"authorizes_action": True}, wra.PROPOSAL_FLAG_ALTERED, rha.RCV_PROPOSAL_INVALID),
                ({"queue_scope_attested": True}, wra.PROPOSAL_FLAG_ALTERED, rha.RCV_PROPOSAL_INVALID)):
            with self.subTest(changes=changes):
                forged = t.forge(self.proposal, **changes)
                result = self.assertRefused(self.compose(proposal=forged), rhc.CMP_PROPOSAL_SOURCE_INVALID,
                                            rhc.CMP_COMMAND_NOT_VERIFIED, rhc.CMP_SCOPE_NOT_EVALUATED,
                                            exact=False)
                self.assertIn(finding, result.proposal_findings)
                self.assertEqual(result.command_verification_codes, (rcv,))
        forged_scope = t.forge(self.proposal.scope, governed_roots=())
        result = self.compose(proposal=t.forge(self.proposal, scope=forged_scope))
        self.assertIn(wra.SCOPE_DIGEST_MISMATCH, result.proposal_findings)
        self.assertEqual(result.status, rhc.STATUS_REFUSED)

    def test_non_proposal_inputs_fail_closed_without_raising(self):
        for proposal in (None, {}, "proposal", self.report):
            with self.subTest(proposal=type(proposal).__name__):
                result = self.assertRefused(self.compose(proposal=proposal), rhc.CMP_PROPOSAL_SOURCE_INVALID,
                                            rhc.CMP_COMMAND_NOT_VERIFIED, rhc.CMP_SCOPE_NOT_EVALUATED,
                                            exact=False)
                self.assertEqual(result.proposal_findings, (wra.PROPOSAL_TYPE_INVALID,))


# ---------------------------------------------------------------------------
# 3. Identity, report, inventory and scope changes
# ---------------------------------------------------------------------------

class IdentityChangeTests(CompositionCase):
    C2 = os.path.join(twra.ROOT, "repo-2", ".git")
    WT2 = os.path.join(twra.ROOT, "wt-other")
    CHANGES = (
        ("head", {"head_sha": "b" * 40, "listed_head": "b" * 40}, {}),
        ("branch", {"head_ref": "refs/heads/feature/other", "listed_branch": "refs/heads/feature/other"}, {}),
        ("admin_dir", {"git_dir": os.path.join(twra.COMMON, "worktrees", "wt-feature-2")}, {}),
        ("common_dir", {"common_dir": C2, "git_dir": os.path.join(C2, "worktrees", "wt-feature")},
         {"common_dir": C2}),
        ("target_path", {"path": WT2, "worktree_key": WT2, "worktree_top": WT2}, {}),
        ("report_fingerprint", {}, {"fingerprint": "8" * 64}),
        ("inventory_fingerprints", {}, {"first_inventory_fingerprint": "e" * 64,
                                        "second_inventory_fingerprint": "e" * 64}),
        ("governed_roots", {}, {"governed_roots": (os.path.join(twra.ROOT, "governed-2"),)}),
        ("lease_root", {}, {"lease_root": os.path.join(twra.ROOT, "lease")}),
        ("state_root", {}, {"state_root": os.path.join(twra.ROOT, "runtime", "state-2")}),
    )

    def test_changed_sources_refuse_the_signed_proposal(self):
        for name, record_changes, report_changes in self.CHANGES:
            with self.subTest(name=name):
                report, record = sources(record_changes, **report_changes)
                result = self.assertRefused(self.compose(report=report, inventory_record=record),
                                            rhc.CMP_PROPOSAL_SOURCE_INVALID, rhc.CMP_COMMAND_NOT_VERIFIED,
                                            rhc.CMP_SCOPE_NOT_EVALUATED)
                self.assertEqual(result.command_verification_codes, (rha.RCV_PROPOSAL_SOURCE_MISMATCH,))
                self.assertTrue(result.proposal_findings)

    def test_a_proposal_rebuilt_from_changed_sources_is_not_the_signed_one(self):
        for name, record_changes, report_changes in self.CHANGES:
            with self.subTest(name=name):
                report, record = sources(record_changes, **report_changes)
                rebuilt = build(report, record)
                self.assertNotEqual(rebuilt.proposal_digest, self.proposal.proposal_digest)
                result = self.assertRefused(self.compose(proposal=rebuilt, report=report, inventory_record=record),
                                            rhc.CMP_COMMAND_NOT_VERIFIED, rhc.CMP_MANIFEST_BINDING_MISMATCH,
                                            exact=False)
                self.assertEqual(result.proposal_findings, ())
                self.assertEqual(result.command_verification_codes, (rha.RCV_PROPOSAL_BINDING_MISMATCH,))
                self.assertIs(result.ledger_evidence_present, False)


# ---------------------------------------------------------------------------
# 4. Queue scope manifest and report coverage
# ---------------------------------------------------------------------------

class ManifestScopeTests(CompositionCase):
    def compose_roots(self, roots, **changes):
        return self.compose(manifest_envelope=self.signed_manifest(roots=roots, **changes))

    def test_every_registered_default_root_must_be_declared(self):
        self.assertRefused(self.compose_roots(sorted([default_root(twra.WT), override_root(twra.QUEUE)],
                                                     key=lambda d: d["root"])),
                           rhc.CMP_SCOPE_DEFAULT_ROOT_MISSING, rhc.CMP_SCOPE_UNDECLARED_ROOT)
        self.assertRefused(self.compose_roots(sorted([default_root(twra.REPO), override_root(twra.QUEUE)],
                                                     key=lambda d: d["root"])),
                           rhc.CMP_SCOPE_DEFAULT_ROOT_MISSING)

    def test_overrides_must_be_declared_and_actually_read(self):
        self.assertRefused(self.compose_roots(sorted([default_root(twra.REPO), default_root(twra.WT)],
                                                     key=lambda d: d["root"])),
                           rhc.CMP_SCOPE_UNDECLARED_ROOT)
        extra = os.path.join(twra.ROOT, "runtime", "queue-unread")
        self.assertRefused(self.compose_roots(sorted(standard_roots() + [override_root(extra)],
                                                     key=lambda d: d["root"])),
                           rhc.CMP_SCOPE_DECLARED_ROOT_NOT_READ)
        inside_target = os.path.join(twra.WT, "queue-inside-target")
        self.assertRefused(self.compose_roots(sorted(standard_roots() + [override_root(inside_target)],
                                                     key=lambda d: d["root"])),
                           rhc.CMP_SCOPE_DECLARED_ROOT_NOT_READ)

    def test_unknown_worktree_and_wrong_source_are_refused(self):
        ghost = os.path.join(twra.ROOT, "wt-ghost")
        self.assertRefused(self.compose_roots(sorted(standard_roots() + [default_root(ghost)],
                                                     key=lambda d: d["root"])),
                           rhc.CMP_SCOPE_UNKNOWN_WORKTREE)
        as_override = sorted([override_root(MAIN_QUEUE), default_root(twra.WT), override_root(twra.QUEUE)],
                             key=lambda d: d["root"])
        self.assertRefused(self.compose_roots(as_override), rhc.CMP_SCOPE_ROOT_SOURCE_MISMATCH,
                           rhc.CMP_SCOPE_DEFAULT_ROOT_MISSING)

    def test_a_non_target_default_root_the_assessment_never_read_is_refused(self):
        report, record = sources(queue_roots=(twra.QUEUE,))
        self.assertRefused(self.compose(**self.chain(report, record, index=2)), rhc.CMP_SCOPE_DEFAULT_ROOT_NOT_READ)

    def test_registry_records_with_unknown_or_inconsistent_identity_are_refused(self):
        target = twra.candidate(self.report)
        without_main = twra.make_report((target,), queue_roots=READ_ROOTS)
        self.assertRefused(self.compose(**self.chain(without_main, self.record, index=3)),
                           rhc.CMP_SCOPE_REGISTRY_INCONSISTENT, rhc.CMP_SCOPE_UNKNOWN_WORKTREE)
        alias = twra.REPO + os.sep
        main_alias = wr.classify_retirement(wr.RetirementFacts(worktree_key=alias, path=alias))
        aliased = twra.make_report((main_alias, target), queue_roots=READ_ROOTS)
        self.assertRefused(self.compose(**self.chain(aliased, self.record, index=4)),
                           rhc.CMP_SCOPE_REGISTRY_INCONSISTENT, rhc.CMP_SCOPE_UNKNOWN_WORKTREE)

    def test_target_local_queue_is_unproven_without_clean_target_facts(self):
        m = rhc.verify_queue_scope_manifest(self.manifest, trust=self.trust, now=AT).manifest
        self.assertEqual(rhc.scope_findings(m, self.proposal, self.report), ())
        target = twra.candidate(self.report)
        for facts in ({"ignored_count": None}, {"ignored_count": 1}, {"supplemental_checked": False},
                      {"supplemental_status_entries": ("?? runtime/claude_runner/queue/x",)},
                      {"queue_items": ((TARGET_QUEUE, "item-1", "QUEUED", 0),)}):
            with self.subTest(facts=facts):
                forged = twra.forge(target, facts=dataclasses.replace(target.facts, **facts))
                report = twra.forge(self.report, records=(self.report.records[0], forged))
                self.assertIn(rhc.CMP_SCOPE_TARGET_QUEUE_UNPROVEN, rhc.scope_findings(m, self.proposal, report))

    def test_completeness_declared_false_is_refused(self):
        self.assertRefused(self.compose(manifest_envelope=self.signed_manifest(host_claims_roots_complete=False)),
                           rhc.CMP_SCOPE_DECLARED_INCOMPLETE)
        m = rhc.verify_queue_scope_manifest(self.manifest, trust=self.trust, now=AT).manifest
        unclaimed = twra.forge(self.report, queue_roots_complete_claim=False)
        self.assertIn(rhc.CMP_SCOPE_DECLARED_INCOMPLETE, rhc.scope_findings(m, self.proposal, unclaimed))

    def test_duplicate_unsorted_and_contradictory_roots_are_refused(self):
        roots = standard_roots()
        self.assertManifestRefused(self.signed_manifest(roots=sorted(roots + [override_root(twra.QUEUE)],
                                                                     key=lambda d: d["root"])),
                                   rhc.MQS_DUPLICATE_ROOT)
        self.assertNotEqual(list(reversed(roots)), roots)
        self.assertManifestRefused(self.signed_manifest(roots=list(reversed(roots))), rhc.MQS_ROOTS_NOT_SORTED)
        for entry, code in (({"root": twra.QUEUE, "source": OVERRIDE, "worktree_key": twra.REPO},
                             rhc.MQS_CONTRADICTORY),
                            ({"root": MAIN_QUEUE, "source": DEFAULT, "worktree_key": None}, rhc.MQS_CONTRADICTORY),
                            ({"root": MAIN_QUEUE, "source": DEFAULT, "worktree_key": twra.WT}, rhc.MQS_CONTRADICTORY),
                            ({"root": MAIN_QUEUE, "source": "AUTO_DISCOVERED", "worktree_key": None},
                             rhc.MQS_SOURCE_UNKNOWN)):
            with self.subTest(entry=entry):
                self.assertManifestRefused(self.signed_manifest(roots=[entry]), code)
        self.assertManifestRefused(self.signed_manifest(acknowledged_external_queues_unprovable=False),
                                   rhc.MQS_CONTRADICTORY)

    def test_alias_case_and_windows_path_forms_are_refused(self):
        variants = {MAIN_QUEUE + os.sep, MAIN_QUEUE.replace(os.sep, os.sep * 2), os.path.join(MAIN_QUEUE, "x", ".."),
                    os.path.join(MAIN_QUEUE, "."), os.path.join("runtime", "claude_runner", "queue"),
                    MAIN_QUEUE.upper(), MAIN_QUEUE.replace("\\", "/"), "\\\\?\\" + MAIN_QUEUE,
                    "\\\\server\\share\\queue", "file:" + MAIN_QUEUE, MAIN_QUEUE + ":stream"}
        variants.discard(MAIN_QUEUE)
        self.assertGreaterEqual(len(variants), 8)
        for variant in sorted(variants):
            with self.subTest(variant=variant):
                roots = [dict(d, root=variant) if d["root"] == MAIN_QUEUE else d for d in standard_roots()]
                result = self.compose(manifest_envelope=self.signed_manifest(roots=roots))
                self.assertRefused(result, *_SCOPE_SKIPPED)
                self.assertIn(result.manifest_codes[0], (rhc.MQS_PATH_NOT_CANONICAL, rhc.MQS_CONTRADICTORY))
        for key in {twra.REPO.upper(), twra.REPO + os.sep, twra.REPO.replace("\\", "/")} - {twra.REPO}:
            with self.subTest(key=key):
                roots = [dict(d, worktree_key=key) if d["worktree_key"] == twra.REPO else d for d in standard_roots()]
                result = self.compose(manifest_envelope=self.signed_manifest(roots=roots))
                self.assertIn(result.manifest_codes[0], (rhc.MQS_PATH_NOT_CANONICAL, rhc.MQS_CONTRADICTORY))
        self.assertManifestRefused(self.signed_manifest(common_dir=twra.COMMON + os.sep), rhc.MQS_PATH_NOT_CANONICAL)
        self.assertIs(rhc.is_canonical_path(MAIN_QUEUE), True)
        if os.name == "nt":
            for form in ("C:" + MAIN_QUEUE[2:], MAIN_QUEUE.replace("\\", "/"), "\\\\?\\" + MAIN_QUEUE):
                self.assertIs(rhc.is_canonical_path(form), False, form)

    def test_malformed_manifest_documents_are_refused(self):
        body = manifest_body(self.proposal)
        good = manifest_envelope(body, self.manifest_key)
        text = good.decode()
        duplicated = text.replace('"host_id": "host-01"', '"host_id": "host-01", "host_id": "host-01"', 1)
        self.assertNotEqual(duplicated, text)
        documents = [b"", b"{", b"[]", b"null", duplicated.encode(), good + b" " * rhc.MAX_MANIFEST_BYTES,
                     b'{"manifest": {}, "signature": "x"}', "﻿".encode() + good, good.replace(b"{", b"\xff", 1)]
        for name, value in (("roots", {}), ("roots", []), ("roots", [standard_roots()[0]] * 65),
                            ("host_claims_roots_complete", "true"), ("acknowledged_external_queues_unprovable", 1),
                            ("manifest_id", 5), ("manifest_id", ""), ("scope_digest", "A" * 64),
                            ("key_id", "fcp4e02b-retire-key-director-1"), ("issued_at", " " + t.stamp(-30)),
                            ("host_claims_roots_complete", float("nan"))):
            documents.append(manifest_envelope(dict(body, **{name: value}), self.manifest_key))
        missing = dict(body)
        missing.pop("scope_digest")
        documents.append(manifest_envelope(missing, self.manifest_key))
        documents.append(manifest_envelope(dict(body, roots=[{"root": MAIN_QUEUE, "source": DEFAULT}]),
                                           self.manifest_key))
        for raw in documents:
            with self.subTest(raw=raw[:60]):
                self.assertManifestRefused(raw, rhc.MQS_MALFORMED)
        self.assertEqual(rhc.verify_queue_scope_manifest(text, trust=self.trust, now=AT).reason_codes,
                         (rhc.MQS_MALFORMED,))
        self.assertRefused(self.compose(manifest_envelope=text), rhc.CMP_ARGUMENT_INVALID)

    def test_unknown_fields_and_forged_attestation_claims_are_refused(self):
        body = manifest_body(self.proposal)
        for changes in ({"queue_scope_attested": True}, {"external_queues_excluded": True},
                        {"completeness_established": True}, {"host_identity_authenticated": True},
                        {"approved": True}):
            with self.subTest(changes=changes):
                self.assertManifestRefused(manifest_envelope(dict(body, **changes), self.manifest_key),
                                           rhc.MQS_FORGED_CLAIM)
        attested_root = [dict(standard_roots()[0], attested=True)] + standard_roots()[1:]
        self.assertManifestRefused(manifest_envelope(dict(body, roots=attested_root), self.manifest_key),
                                   rhc.MQS_FORGED_CLAIM)
        self.assertManifestRefused(manifest_envelope(body, self.manifest_key, extra={"queue_scope_attested": True}),
                                   rhc.MQS_FORGED_CLAIM)
        for raw in (manifest_envelope(dict(body, comment="trust me"), self.manifest_key),
                    manifest_envelope(body, self.manifest_key, extra={"public_key": "00" * 32}),
                    manifest_envelope(dict(body, roots=[dict(standard_roots()[0], note="x")] + standard_roots()[1:]),
                                      self.manifest_key)):
            self.assertManifestRefused(raw, rhc.MQS_UNKNOWN_FIELD)
        for fmt in ("fcp4e02d-queue-scope-manifest-v2", rha.COMMAND_FORMAT):
            self.assertManifestRefused(self.signed_manifest(format=fmt), rhc.MQS_VERSION_UNSUPPORTED)

    def test_stale_or_badly_timed_manifests_are_refused(self):
        self.assertManifestRefused(self.manifest, rhc.MQS_EXPIRED, now=NOW + timedelta(seconds=120))
        self.assertManifestRefused(self.manifest, rhc.MQS_EXPIRED, now=NOW + timedelta(seconds=125))
        self.assertManifestRefused(self.signed_manifest(issued_at=t.stamp(20), expires_at=t.stamp(100)),
                                   rhc.MQS_NOT_YET_VALID)
        self.assertManifestRefused(self.signed_manifest(expires_at=t.stamp(271)), rhc.MQS_TTL_TOO_LONG)
        self.assertConsistent(self.compose(manifest_envelope=self.signed_manifest(expires_at=t.stamp(270))))
        for issued, expires in (("2026-10-26 11:59:30", t.stamp(120)), (t.stamp(-30), t.stamp(-30)),
                                (t.stamp(60), t.stamp(-30)), ("2026-02-30T12:00:00Z", t.stamp(120))):
            with self.subTest(issued=issued, expires=expires):
                self.assertManifestRefused(self.signed_manifest(issued_at=issued, expires_at=expires),
                                           rhc.MQS_TIMESTAMP_INVALID)

    def test_signature_key_and_signer_failures_are_refused(self):
        body = manifest_body(self.proposal)
        signature = self.manifest_key.sign(manifest_message(body))
        tampered = dict(body, roots=sorted(standard_roots() + [override_root(os.path.join(twra.ROOT, "q2"))],
                                           key=lambda d: d["root"]))
        for raw in (manifest_envelope(tampered, signature=signature),
                    manifest_envelope(body, self.key),                        # the Director's command key
                    manifest_envelope(body, self.manifest_key, domain=rha.SIGNATURE_DOMAIN),
                    manifest_envelope(body, self.manifest_key, domain=rhc.MANIFEST_SIGNATURE_DOMAIN + b"/v2"),
                    manifest_envelope(body, signature="A" * 86 + "==")):
            self.assertManifestRefused(raw, rhc.MQS_SIGNATURE_INVALID)
        for bad in ("A" * 85 + "B==", "A" * 84, base64.b64encode(signature[:63]).decode(), 5, "*" * 88):
            self.assertManifestRefused(manifest_envelope(body, signature=bad), rhc.MQS_SIGNATURE_MALFORMED)
        self.assertManifestRefused(self.signed_manifest(key_id="fcp4e02d-queue-key-unpinned"), rhc.MQS_KEY_UNPINNED)
        self.assertManifestRefused(self.manifest, rhc.MQS_KEY_REVOKED,
                                   manifest_trust=dataclasses.replace(self.trust, revoked_key_ids=(MANIFEST_KEY_ID,)))
        self.assertManifestRefused(self.signed_manifest(signer_id="someone-else"), rhc.MQS_SIGNER_MISMATCH)
        other = make_trust(t.raw_public(self.manifest_key), allowed_signer_ids=("other-operator",))
        self.assertManifestRefused(self.manifest, rhc.MQS_SIGNER_NOT_ALLOWED, manifest_trust=other)

    def test_invalid_trust_configurations_are_refused(self):
        public = t.raw_public(self.manifest_key)
        key = self.trust.keys[0]
        bad = [None, {}, self.config, dataclasses.replace(self.trust, format="v0"),
               dataclasses.replace(self.trust, keys=()), dataclasses.replace(self.trust, keys=(key, key)),
               dataclasses.replace(self.trust, allowed_signer_ids=()),
               dataclasses.replace(self.trust, revoked_key_ids=("fcp4e02b-retire-key-director-1",)),
               make_trust(b"\x00" * 32), make_trust(public[:31]),
               dataclasses.replace(self.trust, keys=(rhc.PinnedQueueManifestKey(t.KEY_ID, SIGNER, public),))]
        forged = dataclasses.replace(self.trust)
        object.__setattr__(forged, "host_identity_authenticated", True)
        bad.append(forged)
        for trust in bad:
            with self.subTest(trust=repr(trust)[:60]):
                self.assertEqual(rhc.manifest_trust_errors(trust), rhc.MQS_TRUST_INVALID)
                self.assertManifestRefused(self.manifest, rhc.MQS_TRUST_INVALID, manifest_trust=trust)

    def test_host_and_report_bindings_are_exact(self):
        self.assertManifestRefused(self.signed_manifest(host_id="host-02"), rhc.MQS_HOST_MISMATCH)
        trust_b = make_trust(t.raw_public(self.manifest_key), host_id="host-02")
        result = self.compose(manifest_envelope=self.signed_manifest(host_id="host-02"), manifest_trust=trust_b)
        self.assertRefused(result, rhc.CMP_MANIFEST_BINDING_MISMATCH)
        self.assertEqual(result.manifest_status, rhc.STATUS_STRUCTURE_VERIFIED_NOT_ATTESTED)
        for changes in ({"report_content_digest": "0" * 64}, {"scope_digest": "1" * 64},
                        {"common_dir": os.path.join(twra.ROOT, "other", ".git")}):
            with self.subTest(changes=changes):
                self.assertRefused(self.compose(manifest_envelope=self.signed_manifest(**changes)),
                                   rhc.CMP_MANIFEST_BINDING_MISMATCH)
        # A manifest for a stale (different) report of the same target.
        stale_report, stale_record = sources(fingerprint="7" * 64)
        stale = build(stale_report, stale_record)
        self.assertRefused(self.compose(manifest_envelope=self.signed_manifest(stale)),
                           rhc.CMP_MANIFEST_BINDING_MISMATCH)

    def test_default_queue_layout_matches_the_queue_module(self):
        self.assertEqual(rhc.DEFAULT_QUEUE_SUBDIR_PARTS, claude_queue.DEFAULT_QUEUE_SUBDIR.parts)
        self.assertEqual(TARGET_QUEUE, os.path.normcase(os.path.join(twra.WT, "runtime", "claude_runner", "queue")))
        self.assertNotIn(TARGET_QUEUE, self.proposal.scope.queue_roots)
        with self.assertRaises(wra.RetirementProposalRefused) as ctx:
            build(*sources(queue_roots=READ_ROOTS + (TARGET_QUEUE,)))
        self.assertEqual(ctx.exception.code, wra.REFUSED_SCOPE_OVERLAP)


# ---------------------------------------------------------------------------
# 5. Signed command (real 02b verification of the raw envelope)
# ---------------------------------------------------------------------------

class CommandVerificationTests(CompositionCase):
    def assertCommandRefused(self, result, rcv, *others):
        self.assertRefused(result, rhc.CMP_COMMAND_NOT_VERIFIED, *others, exact=not others)
        self.assertEqual(result.command_verification_codes, (rcv,))
        self.assertIs(result.ledger_evidence_present, False)
        return result

    def test_a_host_a_command_on_host_b_is_refused(self):
        config_b = t.make_config(t.raw_public(self.key), host_id="host-02")
        result = self.assertCommandRefused(self.compose(config=config_b), rha.RCV_HOST_MISMATCH,
                                           rhc.CMP_LEDGER_UNAVAILABLE, rhc.CMP_MANIFEST_BINDING_MISMATCH)
        self.assertEqual(result.ledger_codes, (rlg.RLG_HOST_MISMATCH,))
        proposal_b = build(self.report, self.record, host_id="host-02")
        envelope_b = self.signed(proposal_b, host_id="host-02")
        self.assertCommandRefused(self.compose(envelope=envelope_b, proposal=proposal_b), rha.RCV_HOST_MISMATCH)

    def test_unpinned_wrong_or_revoked_keys_are_refused(self):
        stranger = Ed25519PrivateKey.generate()
        self.assertCommandRefused(self.compose(envelope=self.signed(private=stranger,
                                                                    key_id="fcp4e02b-retire-key-stranger")),
                                  rha.RCV_KEY_UNPINNED)
        self.assertCommandRefused(self.compose(envelope=self.signed(private=stranger)), rha.RCV_SIGNATURE_INVALID)
        revoked = dataclasses.replace(self.config, revoked_key_ids=(t.KEY_ID,))
        self.assertCommandRefused(self.compose(config=revoked), rha.RCV_KEY_REVOKED)
        self.assertRefused(self.compose(config=dataclasses.replace(self.config, keys=())), rhc.CMP_CONFIG_INVALID)
        self.assertRefused(self.compose(config=self.trust), rhc.CMP_CONFIG_INVALID)

    def test_a_signature_under_another_domain_is_refused(self):
        command = t.command_for(self.proposal)
        body = rha.canonical_command_message(command)[len(rha.SIGNATURE_DOMAIN) + 1:]
        for domain in (rhc.MANIFEST_SIGNATURE_DOMAIN, rha.SIGNATURE_DOMAIN + b"/v2", b""):
            with self.subTest(domain=domain):
                envelope = t.envelope(command, signature=self.key.sign(domain + b"\n" + body))
                self.assertCommandRefused(self.compose(envelope=envelope), rha.RCV_SIGNATURE_INVALID)

    def test_invalid_envelopes_are_refused(self):
        command = t.command_for(self.proposal)
        for raw in (b"{}", b"not json", t.envelope(command, self.key, extra={"approved": True}),
                    t.envelope(command, self.key, drop=("nonce",))):
            with self.subTest(raw=raw[:40]):
                result = self.compose(envelope=raw)
                self.assertRefused(result, rhc.CMP_COMMAND_NOT_VERIFIED)
                self.assertIn(result.command_verification_codes[0], rha.VERIFICATION_REFUSAL_CODES)
        verification = rha.verify_retirement_command(self.envelope, config=self.config, proposal=self.proposal,
                                                     now=AT)
        for forged_input in (verification, "signature_verified=True", None):
            self.assertRefused(self.compose(envelope=forged_input), rhc.CMP_ARGUMENT_INVALID)
        parameters = inspect.signature(rhc.compose_retirement_evidence).parameters
        for name in ("verification", "signature_verified", "verified", "evidence", "assessor", "callback",
                     "reassess", "attested", "live"):
            self.assertFalse(any(name in p for p in parameters), name)

    def test_expired_not_yet_valid_and_overlong_windows_are_refused(self):
        result = self.assertCommandRefused(self.compose(now=NOW + timedelta(seconds=180)), rha.RCV_COMMAND_EXPIRED,
                                           *_SCOPE_SKIPPED)
        self.assertEqual(result.manifest_codes, (rhc.MQS_EXPIRED,))
        future = self.signed(command_id="retire-cmd-future", nonce=tlg.nonce(1), issued_at=t.stamp(60),
                             expires_at=t.stamp(200))
        self.assertCommandRefused(self.compose(envelope=future), rha.RCV_COMMAND_NOT_YET_VALID)
        overlong = self.signed(command_id="retire-cmd-ttl", nonce=tlg.nonce(2), expires_at=t.stamp(241))
        self.assertCommandRefused(self.compose(envelope=overlong), rha.RCV_TTL_TOO_LONG)

    def test_changed_proposal_scope_or_target_bindings_are_refused(self):
        for changes, rcv in (({"proposal_digest": "0" * 64}, rha.RCV_PROPOSAL_BINDING_MISMATCH),
                             ({"scope_digest": "0" * 64}, rha.RCV_SCOPE_BINDING_MISMATCH),
                             ({"target_identity_digest": "0" * 64}, rha.RCV_TARGET_BINDING_MISMATCH),
                             ({"head_sha": "b" * 40, "listed_head": "b" * 40}, rha.RCV_TARGET_BINDING_MISMATCH),
                             ({"git_dir": os.path.join(twra.COMMON, "worktrees", "x")},
                              rha.RCV_TARGET_BINDING_MISMATCH),
                             ({"waivers": ("QUEUE_SCOPE_NOT_ATTESTED",)}, rha.RCV_WAIVER_PRESENT),
                             ({"action": "RETIRE_AND_DELETE_BRANCH"}, rha.RCV_ACTION_INVALID)):
            with self.subTest(changes=changes):
                self.assertCommandRefused(self.compose(envelope=self.signed(**changes)), rcv)

    def test_crypto_unavailable_is_refused_everywhere(self):
        for module in (rha, rhc):
            with self.subTest(module=module.__name__), mock.patch.object(module, "CRYPTO_AVAILABLE", False):
                self.assertRefused(self.compose(), rhc.CMP_CRYPTO_UNAVAILABLE)
                self.assertEqual(rhc.verify_queue_scope_manifest(self.manifest, trust=self.trust, now=AT)
                                 .reason_codes, (rhc.MQS_CRYPTO_UNAVAILABLE,))

    def test_invalid_clocks_are_refused(self):
        for now in (None, "2026-10-26T12:00:10Z", AT.replace(tzinfo=None), AT.replace(tzinfo=tlg._FakeLondon()),
                    datetime(2101, 1, 1, tzinfo=timezone.utc), datetime(2020, 1, 1, tzinfo=timezone.utc)):
            with self.subTest(now=now):
                self.assertRefused(self.compose(now=now), rhc.CMP_CLOCK_INVALID)
                self.assertEqual(rhc.verify_queue_scope_manifest(self.manifest, trust=self.trust, now=now)
                                 .reason_codes, (rhc.MQS_CLOCK_INVALID,))


# ---------------------------------------------------------------------------
# 6. 02c ledger evidence, read only
# ---------------------------------------------------------------------------

class LedgerEvidenceTests(CompositionCase):
    def test_missing_evidence_is_refused(self):
        path, _ledger = self.fresh_ledger()
        result = self.assertRefused(self.compose(ledger_path=str(path)), rhc.CMP_LEDGER_EVIDENCE_MISSING)
        self.assertEqual((result.signature_verified, result.ledger_evidence_present), (True, False))

    def test_revoked_before_recording_is_refused(self):
        path, ledger = self.fresh_ledger()
        self.assertEqual(ledger.revoke_command("retire-cmd-1", "DIRECTOR_WITHDRAWN", clock=lambda: NOW).status,
                         rlg.STATUS_REVOKED)
        self.assertEqual(self.record_evidence(ledger, self.envelope).reason_codes, (rlg.RLG_COMMAND_REVOKED,))
        self.assertRefused(self.compose(ledger_path=str(path)), rhc.CMP_LEDGER_COMMAND_REVOKED,
                           rhc.CMP_LEDGER_EVIDENCE_MISSING)

    def test_revoked_after_recording_is_refused(self):
        self.assertEqual(self.ledger.revoke_command("retire-cmd-1", "SUPERSEDED",
                                                    clock=lambda: NOW + timedelta(seconds=1)).status,
                         rlg.STATUS_REVOKED)
        result = self.assertRefused(self.compose(), rhc.CMP_LEDGER_COMMAND_REVOKED)
        self.assertEqual(result.ledger_record_state, rlg.RECORD_STATE_REVOKED)

    def test_nonce_or_digest_mismatch_with_the_recorded_command_is_refused(self):
        other_nonce = self.signed(nonce=tlg.nonce(7))
        self.assertEqual(self.record_evidence(self.ledger, other_nonce).reason_codes, (rlg.RLG_COMMAND_DUPLICATE,))
        self.assertRefused(self.compose(envelope=other_nonce), rhc.CMP_LEDGER_NONCE_MISMATCH,
                           rhc.CMP_LEDGER_DIGEST_MISMATCH)
        other_window = self.signed(expires_at=t.stamp(170))
        self.assertRefused(self.compose(envelope=other_window), rhc.CMP_LEDGER_DIGEST_MISMATCH,
                           rhc.CMP_LEDGER_EVIDENCE_MISMATCH)

    def test_a_replayed_nonce_under_a_new_command_id_is_refused(self):
        replay = self.signed(command_id="retire-cmd-2")   # same nonce as the recorded command
        self.assertEqual(self.record_evidence(self.ledger, replay).reason_codes, (rlg.RLG_NONCE_REUSED,))
        self.assertRefused(self.compose(envelope=replay), rhc.CMP_LEDGER_EVIDENCE_MISSING)

    def test_ambiguous_or_inconsistent_ledger_answers_are_refused(self):
        command = t.command_for(self.proposal)
        digest = hashlib.sha256(rha.canonical_command_message(command)).hexdigest()
        evidence, trail = self.ledger.get_command("retire-cmd-1"), self.ledger.audit_trail()
        mark = rlg._instant(self.ledger.clock_high_water_mark())

        def run(ledger):
            state = rhc._Composition()
            rhc._check_evidence(state, ledger, command, digest, mark)
            return state

        self.assertEqual(run(_StubLedger(evidence, False, trail)).codes, [])
        recorded = trail[-1]
        twin = rlg.RetirementAuditEvent(recorded.seq + 1, recorded.at, recorded.event, recorded.code,
                                        "retire-cmd-9", digest)
        again = rlg.RetirementAuditEvent(recorded.seq + 1, recorded.at, recorded.event, recorded.code,
                                         "retire-cmd-1", digest)
        revoked_event = rlg.RetirementAuditEvent(recorded.seq + 1, recorded.at, rlg.EVENT_COMMAND_REVOKED,
                                                 "SUPERSEDED", "retire-cmd-1", digest)
        for stub in (_StubLedger(evidence, False, trail + (twin,)), _StubLedger(evidence, False, trail + (again,)),
                     _StubLedger(evidence, False, trail + (revoked_event,)), _StubLedger(evidence, False, trail[:1]),
                     _StubLedger(None, False, trail)):
            with self.subTest(trail=len(stub._trail), evidence=stub._evidence is not None):
                self.assertIn(rhc.CMP_LEDGER_AMBIGUOUS, run(stub).codes)
        for changes in ({"record_version": "v0"}, {"evidence_kind": "SUBMITTED_CLAIM"}, {"domain": "other"},
                        {"record_state": "SOMETHING_ELSE"}, {"director_id": "someone"},
                        {"recorded_at": "2026-10-26T11:58:00.000000Z"},
                        {"recorded_at": "2026-10-26T12:10:00.000000Z"}):
            with self.subTest(changes=changes):
                forged = dataclasses.replace(evidence, **changes)
                self.assertIn(rhc.CMP_LEDGER_EVIDENCE_MISMATCH, run(_StubLedger(forged, False, trail)).codes)
        forged = t.forge(evidence, authorizes_action=True)
        self.assertIn(rhc.CMP_LEDGER_EVIDENCE_MISMATCH, run(_StubLedger(forged, False, trail)).codes)
        failed = run(_StubLedger(evidence, False, trail, error=rlg.RLG_CORRUPT))
        self.assertEqual((failed.codes, failed.ledger_codes), ([rhc.CMP_LEDGER_UNAVAILABLE], (rlg.RLG_CORRUPT,)))
        self.assertIn(rhc.CMP_LEDGER_COMMAND_REVOKED, run(_StubLedger(evidence, None, trail)).codes)

    def test_missing_ledger_is_refused_and_never_created(self):
        before = self.snapshot()
        missing = self.host_dir / ("missing" + rlg.LEDGER_FILENAME_SUFFIX)
        result = self.assertRefused(self.compose(ledger_path=str(missing)), rhc.CMP_LEDGER_UNAVAILABLE)
        self.assertEqual(result.ledger_codes, (rlg.RLG_PATH_MISSING,))
        self.assertFalse(missing.exists())
        self.assertEqual(self.snapshot(), before)
        for path in (str(self.host_dir / "plain.sqlite3"), "relative" + rlg.LEDGER_FILENAME_SUFFIX, None, 5):
            with self.subTest(path=path):
                result = self.assertRefused(self.compose(ledger_path=path), rhc.CMP_LEDGER_UNAVAILABLE)
                self.assertEqual(result.ledger_codes, (rlg.RLG_PATH_INVALID,))
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_foreign_or_misplaced_ledgers_are_refused(self):
        not_ledger = self.host_dir / ("garbage" + rlg.LEDGER_FILENAME_SUFFIX)
        not_ledger.write_bytes(os.urandom(8192))
        corrupt_path, _ = self.fresh_ledger("corrupt")
        data = bytearray(corrupt_path.read_bytes())
        data[4096:8192] = b"\xa5" * 4096
        corrupt_path.write_bytes(bytes(data))
        foreign_path, _ = self.fresh_ledger("foreign", host_id="host-02")
        misplaced = self.untrusted / LEDGER_NAME
        before = self.snapshot()
        for path, codes in ((not_ledger, (rlg.RLG_NOT_A_RETIREMENT_LEDGER,)),
                            (corrupt_path, (rlg.RLG_CORRUPT, rlg.RLG_SCHEMA_INVALID, rlg.RLG_LEDGER_INCONSISTENT)),
                            (foreign_path, (rlg.RLG_HOST_MISMATCH,)), (misplaced, (rlg.RLG_PATH_FORBIDDEN_ROOT,))):
            with self.subTest(path=path.name):
                result = self.assertRefused(self.compose(ledger_path=str(path)), rhc.CMP_LEDGER_UNAVAILABLE)
                self.assertIn(result.ledger_codes[0], codes)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(misplaced.exists())

    def test_scope_roots_are_added_to_the_ledger_forbidden_roots(self):
        with mock.patch.object(rlg, "open_existing", wraps=rlg.open_existing) as opened:
            self.assertConsistent(self.compose())
        roots = opened.call_args.kwargs["forbidden_roots"]
        s = self.proposal.scope
        for root in self.roots + (s.repository_top, s.common_dir, s.state_root, s.ledger_root,
                                  self.proposal.target.worktree_key) + s.queue_roots + s.governed_roots:
            self.assertIn(root, roots)
        self.assertEqual(opened.call_args.kwargs["host_id"], self.config.host_id)
        for bad in ((), [], "", str(self.untrusted), Path(self.untrusted), None):
            with self.subTest(bad=bad):
                self.assertRefused(self.compose(ledger_forbidden_roots=bad), rhc.CMP_ARGUMENT_INVALID)

    def test_clock_behind_the_durable_mark_is_refused(self):
        result = self.assertRefused(self.compose(now=NOW - timedelta(seconds=1)), rhc.CMP_CLOCK_ROLLBACK,
                                    rhc.CMP_COMMAND_NOT_VERIFIED)
        self.assertEqual(result.command_verification_codes, (rha.RCV_CLOCK_REGRESSION,))
        path, ledger = self.fresh_ledger("later")
        self.assertEqual(self.record_evidence(ledger, self.envelope, at=NOW + timedelta(seconds=30)).status,
                         rlg.STATUS_RECORDED_NON_AUTHORIZING)
        self.assertRefused(self.compose(ledger_path=str(path)), rhc.CMP_CLOCK_ROLLBACK, rhc.CMP_COMMAND_NOT_VERIFIED)
        self.assertConsistent(self.compose(ledger_path=str(path), now=NOW + timedelta(seconds=30)))

    def test_an_interrupted_write_is_refused_and_left_for_explicit_recovery(self):
        child = (
            "import os, sqlite3, sys\n"
            "con = sqlite3.connect(sys.argv[1], uri=True, isolation_level=None)\n"
            "con.execute('PRAGMA cache_size = 2')\n"
            "con.execute('BEGIN IMMEDIATE')\n"
            "stamp = '2026-10-26T12:30:00.000000Z'\n"
            "con.execute('UPDATE clock_high_water SET high_water = ?', (stamp,))\n"
            "con.execute(\"INSERT INTO revocations (command_id, host_id, reason_code, revoked_at)"
            " VALUES ('retire-cmd-1', 'host-01', 'SUPERSEDED', ?)\", (stamp,))\n"
            "for i in range(4000):\n"
            "    con.execute(\"INSERT INTO audit (at, event, code) VALUES (?, 'COMMAND_REVOKED', ?)\","
            " (stamp, 'x' * 120))\n"
            "os._exit(3)\n"
        )
        done = subprocess.run([sys.executable, "-I", "-B", "-c", child, rlg._sqlite_uri(str(self.path), "rw")],
                              cwd=str(self.base), timeout=120, capture_output=True)
        self.assertEqual(done.returncode, 3, done.stderr)
        journal = Path(str(self.path) + "-journal")
        self.assertTrue(journal.exists())
        before = self.snapshot()
        result = self.assertRefused(self.compose(), rhc.CMP_LEDGER_UNAVAILABLE)
        self.assertEqual(result.ledger_codes, (rlg.RLG_INTERRUPTED_WRITE,))
        self.assertEqual(self.snapshot(), before)   # no recovery, no rollback, no byte changed
        self.assertTrue(journal.exists())

    def test_wal_side_files_are_refused_and_left_untouched(self):
        side = Path(str(self.path) + "-wal")
        side.write_bytes(b"")
        before = self.snapshot()
        result = self.assertRefused(self.compose(), rhc.CMP_LEDGER_UNAVAILABLE)
        self.assertEqual(result.ledger_codes, (rlg.RLG_SIDE_FILE_PRESENT,))
        self.assertEqual(self.snapshot(), before)

    def test_composition_reads_only_and_never_calls_a_writer(self):
        refusals = [dict(envelope=b"{}"), dict(now=NOW - timedelta(seconds=1)),
                    dict(manifest_envelope=self.signed_manifest(host_id="host-02")),
                    dict(envelope=self.signed(command_id="retire-cmd-2"))]
        before = self.snapshot()
        writers = [mock.patch.object(rlg.RetirementLedger, name, side_effect=AssertionError(name))
                   for name in ("record_reverified_command_evidence", "revoke_command", "_write")]
        writers += [mock.patch.object(rlg, name, side_effect=AssertionError(name))
                    for name in ("provision", "recover_interrupted_write", "_provision")]
        for patcher in writers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertConsistent(self.compose())
        for changes in refusals:
            self.assertEqual(self.compose(**changes).status, rhc.STATUS_REFUSED)
        self.assertEqual(self.snapshot(), before)
        for suffix in ("-journal", "-wal", "-shm"):
            self.assertFalse(os.path.lexists(str(self.path) + suffix), suffix)


# ---------------------------------------------------------------------------
# 7. Security boundary (static)
# ---------------------------------------------------------------------------

def _code_without_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.code = ast.unparse(_code_without_docstrings(ast.parse(self.source)))

    def test_never_live_constants_are_literal_false(self):
        self.assertIs(rhc.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertIs(rhc.RETIREMENT_EXECUTION_CAPABLE, False)
        assigned = [n for n in ast.walk(self.tree) if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                    for target in (n.targets if isinstance(n, ast.Assign) else [n.target])
                    if isinstance(target, ast.Name) and target.id.startswith("RETIREMENT_")]
        self.assertEqual(len(assigned), 2)
        for node in assigned:
            self.assertIsInstance(node.value, ast.Constant)
            self.assertIs(node.value.value, False)
        self.assertNotIn("global ", self.code)

    def test_imports_are_minimal(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module else a.name for a in node.names}
        self.assertEqual(imported, {
            "__future__.annotations", "base64", "binascii", "hashlib", "json", "os", "re", "sys",
            "dataclasses.dataclass", "dataclasses.field", "datetime.datetime", "datetime.timedelta",
            "datetime.timezone", "pathlib.Path", "typing.Optional",
            "scripts.ai.runner_worktree_retirement_authorization", "scripts.ai.runner_worktree_retirement_host_authority",
            "scripts.ai.runner_worktree_retirement_host_ledger", "runner_worktree_retirement_authorization",
            "runner_worktree_retirement_host_authority", "runner_worktree_retirement_host_ledger",
            "cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PublicKey"})
        for forbidden in ("subprocess", "shutil", "socket", "urllib", "http", "sqlite3", "fcntl", "msvcrt",
                          "DirLease", "QueueLock", "runner_integration", "runner_git", "claude_queue",
                          "claude_multiworker", "runner_promotion", "HostLedger", "fabric_director",
                          "Ed25519PrivateKey", "private_bytes", "assess_worktree_retirement", "inventory_worktrees"):
            self.assertNotIn(forbidden, self.code, forbidden)

    def test_no_process_git_filesystem_write_or_ledger_writer_calls(self):
        os_attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name) and n.value.id == "os"}
        self.assertLessEqual(os_attrs, {"path", "name"})
        path_attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)
                      and isinstance(n.value, ast.Attribute) and n.value.attr == "path"
                      and isinstance(n.value.value, ast.Name) and n.value.value.id == "os"}
        self.assertLessEqual(path_attrs, {"isabs", "splitdrive", "normcase", "normpath", "join"})
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                 for n in ast.walk(self.tree) if isinstance(n, ast.Call)}
        for forbidden in ("system", "popen", "Popen", "run", "remove", "unlink", "rmdir", "rmtree", "rename",
                          "replace", "chmod", "chown", "truncate", "symlink", "link", "kill", "startfile", "open",
                          "write", "write_bytes", "write_text", "touch", "makedirs", "mkdir", "sign", "generate",
                          "urlopen", "connect", "execute", "executemany", "exec", "eval", "provision",
                          "record_reverified_command_evidence", "revoke_command", "recover_interrupted_write",
                          "_write", "worktree", "prune"):
            self.assertNotIn(forbidden, calls, forbidden)
        attributes = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for writer in ("provision", "record_reverified_command_evidence", "revoke_command",
                       "recover_interrupted_write", "_write", "_provision", "_connect"):
            self.assertNotIn(writer, attributes, writer)
        self.assertEqual({n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)
                          and isinstance(n.value, ast.Name) and n.value.id == "ledger"},
                         {"get_command", "is_revoked", "audit_trail", "clock_high_water_mark"})
        for text in ("git ", "worktree remove", "worktree prune", "--force", "unlock", "branch -D", "mode=rw",
                     "BEGIN IMMEDIATE", "INSERT", "UPDATE", "DELETE"):
            self.assertNotIn(text, self.code, text)

    def test_compose_live_only_raises(self):
        function = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "compose_live")
        body = _code_without_docstrings(ast.parse(ast.unparse(function))).body[0].body
        self.assertEqual(len(body), 1)
        self.assertIsInstance(body[0], ast.Raise)
        self.assertEqual(ast.unparse(body[0]), "raise RetirementCompositionNotLive()")

        class Trap:
            def __getattr__(self, name):
                raise AssertionError(f"compose_live examined {name}")

        with mock.patch.object(rlg, "open_existing", side_effect=AssertionError("ledger")), \
                mock.patch.object(os.path, "lexists", side_effect=AssertionError("filesystem")):
            for args, kwargs in (((), {}), ((Trap(), Trap()), {"ledger_path": Trap(), "now": Trap()})):
                with self.assertRaises(rhc.RetirementCompositionNotLive) as ctx:
                    rhc.compose_live(*args, **kwargs)
                self.assertEqual(ctx.exception.code, rhc.NOT_LIVE)

    def test_no_authorizing_state_operation_or_flag(self):
        constants = {n.value for n in ast.walk(_code_without_docstrings(ast.parse(self.source)))
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for state in ("ISSUED", "PERMITTED", "CONSUMED", "EXECUTED", "DELETION_AUTHORIZED", "APPROVED", "ELIGIBLE",
                      "ELIGIBLE_FOR_REMOVAL", "AUTHORIZED", "PERMIT", "RESERVED"):
            self.assertFalse(any(re.search(rf"\b{state}\b", c) for c in constants), state)
        names = {n.name for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for name in names:
            for word in ("issue", "consume", "permit", "execute", "approve", "authorize", "reserve", "grant",
                         "delete", "remove", "prune", "attest"):
                self.assertNotIn(word, name.lower(), name)
        live = {name for name in names if "live" in name.lower()}
        self.assertEqual(live, {"compose_live", "RetirementCompositionNotLive"})
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg in dict(_FIXED_FLAGS) | dict(_MANIFEST_RESULT_FLAGS):
                self.assertNotEqual(ast.unparse(node.value), "True", node.arg)
        self.assertNotRegex(self.code, r"(authorizes_action|deletion_authorized|issued|consumed|clock_attested|"
                                       r"host_identity_authenticated|queue_scope_attested|external_queues_excluded|"
                                       r"completeness_established|fresh_host_reassessment_performed|"
                                       r"source_records_host_verified)\s*=\s*True")

    def test_reason_code_registries_are_complete(self):
        self.assertEqual(set(rhc.MANIFEST_REFUSAL_CODES), {v for k, v in vars(rhc).items() if k.startswith("MQS_")})
        self.assertEqual(set(rhc.COMPOSITION_REASON_CODES), {v for k, v in vars(rhc).items() if k.startswith("CMP_")})
        self.assertEqual(len(set(rhc.COMPOSITION_REASON_CODES)), len(rhc.COMPOSITION_REASON_CODES))
        self.assertFalse(rhc.FORGED_CLAIM_FIELDS & set(rhc.MANIFEST_FIELDS + rhc.ROOT_FIELDS))
        self.assertNotEqual(rhc.MANIFEST_SIGNATURE_DOMAIN, rha.SIGNATURE_DOMAIN)
        self.assertFalse(rhc.MANIFEST_SIGNATURE_DOMAIN.startswith(rha.SIGNATURE_DOMAIN))
        self.assertEqual(rhc.MAX_MANIFEST_TTL_SECONDS, rha.MAX_COMMAND_TTL_SECONDS)

    def test_predecessor_sources_are_unchanged(self):
        for relative, digest in PINNED_SOURCES.items():
            text = (REPO_ROOT / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), digest, relative)
        for module in (wra, rha, rlg):
            self.assertIs(module.RETIREMENT_AUTHORIZATION_LIVE, False)
            self.assertIs(module.RETIREMENT_EXECUTION_CAPABLE, False)

    def test_docstring_states_the_boundary(self):
        doc = " ".join(rhc.__doc__.split())
        for phrase in ("is an informational diagnostic, NOT a permission, an approval, an issuance or an attestation"
                       " of a real host", "There is no issuer",
                       "`compose_live` only raises NOT_LIVE without looking at its arguments, the host or the"
                       " filesystem", "never calls a ledger writer",
                       "A verification result or a `signature_verified` value is never accepted as an input",
                       "a missing file is refused and never created", "Nothing is recorded or duplicated",
                       "a signed completeness claim is NOT evidence that every queue was inventoried",
                       "External, remote and cross-machine queues are not provable",
                       "No fresh FCP-4D/DirLease re-assessment is performed", "nothing here can switch it on",
                       "it is not single use", "D-1..D-12 remains pending",
                       "issuance and consumption (FCP-4F) do not exist in this module"):
            self.assertIn(phrase, doc, phrase)
        self.assertEqual(_NETWORK, [])


# ---------------------------------------------------------------------------
# 8. CI
# ---------------------------------------------------------------------------

class CiWorkflowTests(unittest.TestCase):
    STEP = "FCP-4E-02d retirement evidence composition regression without skipped tests"

    def setUp(self):
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def job(self, name):
        return re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.workflow).group(1)

    def test_nine_jobs_unchanged(self):
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", self.workflow))
        self.assertEqual(jobs, twra.CiWorkflowTests.JOBS)
        self.assertIn("permissions:\n  contents: read\n", self.workflow)

    def test_suite_runs_once_zero_skip_after_the_ledger_step_in_the_host_trust_job(self):
        job = self.job("fcp3b2b2-host-trust")
        step = re.search(rf"(?ms)^      - name: {re.escape(self.STEP)}\n(.*?)(?=^      - name: |\Z)", job)
        self.assertIsNotNone(step)
        lines = step.group(0).rstrip("\n").split("\n")
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[1], "        run: |")
        command = lines[2]
        for part in ("python -c ", "unittest.defaultTestLoader.loadTestsFromName("
                     "'scripts.tests.test_runner_worktree_retirement_host_composition')",
                     "print('RETIREMENT_COMPOSITION_TESTS_SKIPPED=',len(r.skipped))",
                     "sys.exit(0 if r.wasSuccessful() and not r.skipped else 2)"):
            self.assertIn(part, command, part)
        self.assertEqual(self.workflow.count("test_runner_worktree_retirement_host_composition"), 1)
        self.assertLess(job.index("Verify Ed25519 dependency available"), job.index(self.STEP))
        self.assertLess(job.index("test_runner_worktree_retirement_host_ledger"), job.index(self.STEP))
        self.assertTrue(job.rstrip("\n").endswith(command))

    def test_predecessor_ci_contracts_still_hold(self):
        # The merged 02b/02c workflow assertions, unchanged, against this workflow.
        tlg.CiWorkflowTests.test_suite_runs_once_with_pinned_crypto_in_the_zero_skip_host_trust_job(self)
        t.CiWorkflowTests.test_suite_runs_with_pinned_crypto_in_the_zero_skip_host_trust_job(self)
        twra.CiWorkflowTests.test_previous_suites_preserved(self)
        twra.CiWorkflowTests.test_proposal_suite_runs_in_the_zero_skip_retirement_job(self)


if __name__ == "__main__":
    unittest.main()
