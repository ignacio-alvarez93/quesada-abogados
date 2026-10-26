"""FCP-4E-02b: cryptographic verification of a proposed retirement command (NOT LIVE).

Proposals are REAL FCP-4E-02a proposals built from the synthetic, pure
02a fixtures (paths under a root that does not exist; no Git, no real
worktree). Signing keys are ephemeral Ed25519 keys generated in memory by
these tests only: they stand in for the human Director's own tool, the
module under test has no signing code. Configuration files are written
only into fresh temporary directories outside the repository. No network is
reachable. Nothing here is skipped: without `cryptography` the signature
tests FAIL (CI installs the pinned dependency and enforces zero skips).
"""

import ast
import base64
import builtins
import copy
import dataclasses
import hashlib
import hmac
import importlib.util
import json
import os
import random
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import runner_promotion_host_authority as rauth
from scripts.ai import runner_worktree_retirement as wr
from scripts.ai import runner_worktree_retirement_authorization as wra
from scripts.ai import runner_worktree_retirement_host_authority as rha
from scripts.tests import test_runner_promotion_host_authority as tau
from scripts.tests import test_runner_worktree_retirement_authorization as twra

if rha.CRYPTO_AVAILABLE:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MODULE_PATH = Path(rha.__file__)
WRA_PATH = Path(wra.__file__)
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
# sha256 (LF-normalized) of runner_worktree_retirement_authorization.py as merged in a3fb4fe.
WRA_SOURCE_SHA256 = "c51068e0eff2aa4a20a2edf712d86a716cc784e6a9e52b1c877e5a9d8cc205c0"

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
HOST = twra.HOST
DIRECTOR = "director-quesada-1"
KEY_ID = "fcp4e02b-retire-key-director-1"
NONCE = "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a1c3e5b7d9f2a4c6e8b0d1f3a"
SYNTHETIC_PROVENANCE = os.path.join(os.path.abspath(os.sep), "fcp4e02b-host-provisioned", "retirement-host.json")
_NETWORK = []
_DEFAULT = object()
_CRYPTO_MODULES = ("cryptography", "cryptography.exceptions", "cryptography.hazmat",
                   "cryptography.hazmat.primitives", "cryptography.hazmat.primitives.asymmetric",
                   "cryptography.hazmat.primitives.asymmetric.ed25519")
_FIXED_FLAGS = (("authorizes_action", False), ("deletion_authorized", False), ("branch_deletion_authorized", False),
                ("issued", False), ("consumed", False), ("host_identity_authenticated", False),
                ("queue_scope_attested", False), ("replay_protection_available", False),
                ("human_review_required", True))


def _deny_network(*_args, **_kwargs):
    _NETWORK.append("attempt")
    raise OSError("network denied during retirement host authority tests")


def setUpModule():
    for target, name in ((socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo")):
        patcher = mock.patch.object(target, name, _deny_network)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def stamp(seconds) -> str:
    return (NOW + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_public(private) -> bytes:
    return private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def make_proposal(record_changes=None, host_id=HOST, **report_changes):
    report, record = twra.fixture(record_changes, **report_changes)
    return wra.build_retirement_proposal(report, record, host_id=host_id), report, record


def command_for(proposal, **changes) -> rha.RetirementCommand:
    t = proposal.target
    return dataclasses.replace(rha.RetirementCommand(
        format=rha.COMMAND_FORMAT, command_id="retire-cmd-1", nonce=NONCE, key_id=KEY_ID, director_id=DIRECTOR,
        host_id=HOST, action=rha.ACTION_RETIRE_SINGLE_WORKTREE_CHECKOUT, proposal_digest=proposal.proposal_digest,
        scope_digest=proposal.scope.scope_digest, target_identity_digest=t.identity_digest,
        **{name: getattr(t, name) for name in rha.TARGET_BOUND_FIELDS},
        limitations=wr.LIMITATIONS, proposal_limitations=wra.PROPOSAL_LIMITATIONS, waivers=(),
        issued_at=stamp(-60), expires_at=stamp(180)), **changes)


def body_of(command) -> dict:
    return {n: list(getattr(command, n)) if isinstance(getattr(command, n), tuple) else getattr(command, n)
            for n in rha.COMMAND_FIELDS}


def envelope(command, private=None, signature=None, command_extra=None, extra=None, drop=()) -> bytes:
    """What the Director's own signing tool would send (test stand-in)."""
    if signature is None:
        signature = private.sign(rha.canonical_command_message(command))
    body = body_of(command)
    body.update(command_extra or {})
    for name in drop:
        body.pop(name)
    document = {"command": body, "signature": base64.b64encode(signature).decode("ascii")}
    document.update(extra or {})
    return json.dumps(document).encode("utf-8")


def make_config(public, **changes) -> rha.RetirementHostConfig:
    return dataclasses.replace(rha.RetirementHostConfig(
        format=rha.CONFIG_FORMAT, host_id=HOST, allowed_director_ids=(DIRECTOR,),
        keys=(rha.PinnedRetirementPublicKey(KEY_ID, DIRECTOR, public),), revoked_key_ids=(),
        provenance_path=SYNTHETIC_PROVENANCE), **changes)


def forge(obj, **changes):
    """A copy with fields overwritten WITHOUT recomputing any digest."""
    clone = copy.copy(obj)
    for name, value in changes.items():
        object.__setattr__(clone, name, value)
    return clone


def redigest(proposal, **changes):
    """A proposal with changed fields and every digest recomputed: internally
    consistent, but NOT the proposal the Director signed for."""
    staged = dataclasses.replace(proposal, **changes)
    return dataclasses.replace(staged, proposal_digest=wra.proposal_digest(staged))


class NoNetworkMixin:
    def tearDown(self):
        self.assertEqual(_NETWORK, [])
        super().tearDown()


class VerifierFixture(NoNetworkMixin, unittest.TestCase):
    """A real 02a proposal, an in-memory Director key pinned in a caller-
    supplied public config, and a valid signed command."""

    def setUp(self):
        super().setUp()
        self.assertTrue(rha.CRYPTO_AVAILABLE, "cryptography missing: Ed25519 verification NOT proven (failing, not "
                                              "skipping)")
        self.proposal, self.report, self.record = make_proposal()
        self.private = Ed25519PrivateKey.generate()
        self.config = make_config(raw_public(self.private))
        self.command = command_for(self.proposal)

    def verify(self, raw=_DEFAULT, *, config=_DEFAULT, proposal=_DEFAULT, now=NOW, **kwargs):
        return rha.verify_retirement_command(
            envelope(self.command, self.private) if raw is _DEFAULT else raw,
            config=self.config if config is _DEFAULT else config,
            proposal=self.proposal if proposal is _DEFAULT else proposal, now=now, **kwargs)

    def signed(self, **changes) -> bytes:
        """A correctly signed envelope of a command with `changes`."""
        return envelope(command_for(self.proposal, **changes), self.private)

    def assertNonAuthorizing(self, result):
        self.assertIs(type(result), rha.RetirementCommandVerification)
        self.assertEqual(result.schema, rha.VERIFICATION_SCHEMA)
        for name, value in _FIXED_FLAGS:
            self.assertIs(getattr(result, name), value, name)
        self.assertEqual(result.limitations, rha.VERIFICATION_LIMITATIONS)
        for word in ("approved", "eligible", "permit", "permitted", "authorized", "execute", "token"):
            self.assertFalse(hasattr(result, word), word)
        return result

    def assertRefused(self, result, code, *, signature_verified=False):
        self.assertNonAuthorizing(result)
        self.assertIn(code, rha.VERIFICATION_REFUSAL_CODES)
        self.assertEqual((result.status, result.reason_codes), (rha.STATUS_REFUSED, (code,)))
        self.assertIs(result.signature_verified, signature_verified)
        if not signature_verified:
            self.assertEqual((result.command_id, result.key_id, result.director_id, result.host_id_label,
                              result.command_message_digest), (None,) * 5)
        return result

    def assertVerified(self, result):
        self.assertNonAuthorizing(result)
        self.assertEqual((result.status, result.reason_codes, result.signature_verified),
                         (rha.STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING, (), True))
        return result


# ---------------------------------------------------------------------------
# 1. Valid synthetic command: signature verified, NEVER authorized
# ---------------------------------------------------------------------------

class PositiveVerificationTests(VerifierFixture):
    def test_valid_command_is_signature_verified_but_never_authorized(self):
        result = self.assertVerified(self.verify())
        message = rha.canonical_command_message(self.command)
        self.assertEqual((result.command_id, result.key_id, result.director_id, result.host_id_label,
                          result.proposal_digest, result.command_message_digest, result.source_records_revalidated),
                         ("retire-cmd-1", KEY_ID, DIRECTOR, HOST, self.proposal.proposal_digest,
                          hashlib.sha256(message).hexdigest(), False))
        self.assertNotIn("APPROVED", result.status + "".join(result.limitations))
        for word in ("ISSUED", "PERMITTED", "AUTHENTICATED_HOST", "AUTHORIZED"):
            self.assertNotIn(word, result.status)

    def test_source_records_are_revalidated_when_both_are_supplied(self):
        result = self.assertVerified(self.verify(report=self.report, inventory_record=self.record))
        self.assertIs(result.source_records_revalidated, True)

    def test_fixed_flags_are_not_constructor_arguments(self):
        fields = {f.name: f for f in dataclasses.fields(rha.RetirementCommandVerification)}
        for name, value in _FIXED_FLAGS + (("limitations", rha.VERIFICATION_LIMITATIONS),):
            self.assertIs(fields[name].init, False, name)
            self.assertEqual(fields[name].default, value, name)
        result = self.verify()
        for name, value in _FIXED_FLAGS:
            with self.assertRaises(TypeError):
                rha.RetirementCommandVerification(**{f: getattr(result, f) for f in fields if fields[f].init},
                                                  **{name: not value})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.authorizes_action = True
        config_fields = {f.name: f for f in dataclasses.fields(rha.RetirementHostConfig)}
        self.assertIs(config_fields["host_identity_authenticated"].init, False)
        self.assertIs(self.config.host_identity_authenticated, False)

    def test_same_envelope_twice_is_not_reported_as_replay_protected(self):
        raw = envelope(self.command, self.private)
        first, second = self.verify(raw), self.verify(raw)
        self.assertVerified(first)
        self.assertVerified(second)
        self.assertEqual(first, second)   # no hidden state: no single use here (deferred to FCP-4E-02c)
        self.assertIn("NO_REPLAY_PROTECTION", second.limitations)
        self.assertIs(second.replay_protection_available, False)
        self.assertIs(second.consumed, False)

    def test_canonical_message_is_domain_separated_deterministic_and_covers_every_field(self):
        message = rha.canonical_command_message(self.command)
        prefix = rha.SIGNATURE_DOMAIN + rha.DOMAIN_SEPARATOR
        self.assertTrue(message.startswith(prefix))
        self.assertEqual(rha.SIGNATURE_DOMAIN, b"quesada-abogados/fabric/fcp4e02b/worktree-retirement-command/v1")
        payload = json.loads(message[len(prefix):])
        self.assertEqual(set(payload), set(rha.COMMAND_FIELDS))
        self.assertEqual(message, rha.canonical_command_message(copy.deepcopy(self.command)))
        message.decode("ascii")
        self.assertEqual(message[len(prefix):], json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual(payload["limitations"], list(wr.LIMITATIONS))
        self.assertEqual(payload["proposal_limitations"], list(wra.PROPOSAL_LIMITATIONS))
        self.assertEqual(payload["waivers"], [])
        self.assertEqual(payload["action"], "RETIRE_SINGLE_WORKTREE_CHECKOUT")
        for name in rha.TARGET_BOUND_FIELDS:
            self.assertEqual(payload[name], getattr(self.proposal.target, name), name)

    def test_decoded_envelope_example_has_exactly_command_and_signature(self):
        document = json.loads(envelope(self.command, self.private))
        self.assertEqual(set(document), {"command", "signature"})
        self.assertEqual(len(document["signature"]), 88)
        self.assertEqual(len(base64.b64decode(document["signature"])), rha.SIGNATURE_BYTES)
        self.assertEqual(document["command"]["format"], "fcp4e02b-retirement-command-v1")
        self.assertEqual(document["command"]["host_id"], HOST)
        parsed = rha.parse_retirement_envelope(envelope(self.command, self.private))
        self.assertEqual(parsed.command, self.command)

    def test_trusted_high_water_mark_at_or_before_now_is_accepted(self):
        self.assertVerified(self.verify(trusted_high_water_mark=NOW))
        self.assertVerified(self.verify(trusted_high_water_mark=NOW - timedelta(hours=1)))

    def test_exactly_the_maximum_ttl_is_accepted(self):
        self.assertEqual(rha.MAX_COMMAND_TTL_SECONDS, 300)
        self.assertVerified(self.verify(self.signed(issued_at=stamp(-100), expires_at=stamp(200))))

    def test_inputs_are_not_modified(self):
        before = copy.deepcopy((self.proposal, self.config, self.report, self.record))
        self.verify(report=self.report, inventory_record=self.record)
        self.assertEqual((self.proposal, self.config, self.report, self.record), before)


# ---------------------------------------------------------------------------
# 2. Tampering fails closed
# ---------------------------------------------------------------------------

def _altered_values(command):
    """One shape-valid alternative per signed field (key/director/format are
    covered by the key and version tests)."""
    out = {
        "command_id": "retire-cmd-2", "nonce": "fedcba9876543210" * 4, "host_id": "host-02",
        "action": "RETIRE_SINGLE_WORKTREE_CHECKOUT_AND_DELETE_BRANCH", "proposal_digest": "0" * 64,
        "scope_digest": "1" * 64, "target_identity_digest": "2" * 64, "head_sha": "b" * 40, "listed_head": "b" * 40,
        "limitations": command.limitations[:-1], "proposal_limitations": command.proposal_limitations + ("X",),
        "waivers": ("WAIVE_LEASE_CHECK",), "issued_at": stamp(-30), "expires_at": stamp(120),
    }
    for name in rha.TARGET_BOUND_FIELDS:
        out.setdefault(name, getattr(command, name) + "x")
    out.pop("object_format")
    return out


class TamperTests(VerifierFixture):
    def test_every_signed_field_altered_after_signing_is_refused(self):
        signature = self.private.sign(rha.canonical_command_message(self.command))
        altered = _altered_values(self.command)
        self.assertEqual(set(altered) | {"format", "key_id", "director_id", "object_format"},
                         set(rha.COMMAND_FIELDS))
        for name, value in altered.items():
            raw = envelope(dataclasses.replace(self.command, **{name: value}), signature=signature)
            self.assertRefused(self.verify(raw), rha.RCV_SIGNATURE_INVALID)
        raw = envelope(dataclasses.replace(self.command, object_format="sha256", head_sha="a" * 64,
                                           listed_head="a" * 64), signature=signature)
        self.assertRefused(self.verify(raw), rha.RCV_SIGNATURE_INVALID)

    def test_any_signature_bit_flip_is_refused(self):
        signature = self.private.sign(rha.canonical_command_message(self.command))
        for index in (0, 1, 31, 32, 62, 63):
            for bit in (0, 7):
                flipped = bytearray(signature)
                flipped[index] ^= 1 << bit
                self.assertRefused(self.verify(envelope(self.command, signature=bytes(flipped))),
                                   rha.RCV_SIGNATURE_INVALID)

    def test_correctly_signed_but_unbound_fields_are_refused_with_a_fact_only_signature(self):
        cases = [("host_id", "host-02", rha.RCV_HOST_MISMATCH),
                 ("action", "DELETE_BRANCH", rha.RCV_ACTION_INVALID),
                 ("action", "RETIRE_SINGLE_WORKTREE_CHECKOUT ", None),
                 ("limitations", wr.LIMITATIONS[:-1], rha.RCV_LIMITATIONS_ALTERED),
                 ("limitations", tuple(reversed(wr.LIMITATIONS)), rha.RCV_LIMITATIONS_ALTERED),
                 ("limitations", wr.LIMITATIONS + ("EXTRA",), rha.RCV_LIMITATIONS_ALTERED),
                 ("proposal_limitations", wra.PROPOSAL_LIMITATIONS[1:], rha.RCV_LIMITATIONS_ALTERED),
                 ("waivers", ("WAIVE_LEASE_CHECK",), rha.RCV_WAIVER_PRESENT),
                 ("proposal_digest", "0" * 64, rha.RCV_PROPOSAL_BINDING_MISMATCH),
                 ("scope_digest", "1" * 64, rha.RCV_SCOPE_BINDING_MISMATCH),
                 ("target_identity_digest", "2" * 64, rha.RCV_TARGET_BINDING_MISMATCH)]
        cases += [(name, getattr(self.proposal.target, name) + "x", rha.RCV_TARGET_BINDING_MISMATCH)
                  for name in rha.TARGET_BOUND_FIELDS if name not in ("head_sha", "listed_head", "object_format")]
        cases += [("head_sha", "b" * 40, rha.RCV_TARGET_BINDING_MISMATCH),
                  ("listed_head", "b" * 40, rha.RCV_TARGET_BINDING_MISMATCH)]
        for name, value, code in cases:
            raw = self.signed(**{name: value})
            if code is None:   # not even a well-formed command (trailing space)
                self.assertRefused(self.verify(raw), rha.RCV_COMMAND_MALFORMED)
                continue
            result = self.assertRefused(self.verify(raw), code, signature_verified=True)
            self.assertEqual(result.command_id, "retire-cmd-1")
        raw = self.signed(object_format="sha256", head_sha="a" * 64, listed_head="a" * 64)
        self.assertRefused(self.verify(raw), rha.RCV_TARGET_BINDING_MISMATCH, signature_verified=True)

    def test_untrusted_supplied_proposal_is_rechecked(self):
        p = self.proposal
        cases = [
            (forge(p, report_fingerprint="0" * 64), rha.RCV_PROPOSAL_TAMPERED),
            (forge(p, target=forge(p.target, head_sha="b" * 40)), rha.RCV_PROPOSAL_TAMPERED),
            (forge(p, target=forge(p.target, worktree_key=p.target.worktree_key + "x")), rha.RCV_PROPOSAL_TAMPERED),
            (forge(p, scope=forge(p.scope, queue_roots=())), rha.RCV_PROPOSAL_TAMPERED),
            (forge(p, proposal_digest="0" * 64), rha.RCV_PROPOSAL_TAMPERED),
            (forge(p, authorizes_action=True), rha.RCV_PROPOSAL_INVALID),
            (forge(p, deletion_authorized=True), rha.RCV_PROPOSAL_INVALID),
            (forge(p, issued=True), rha.RCV_PROPOSAL_INVALID),
            (forge(p, human_command_present=True), rha.RCV_PROPOSAL_INVALID),
            (forge(p, host_identity_authenticated=True), rha.RCV_PROPOSAL_INVALID),
            (forge(p, target=forge(p.target, file_object_id_verified=True)), rha.RCV_PROPOSAL_INVALID),
            (forge(p, scope=forge(p.scope, queue_scope_attested=True)), rha.RCV_PROPOSAL_INVALID),
            (forge(p, schema="fcp4e02a-retirement-proposal-v2"), rha.RCV_PROPOSAL_INVALID),
            (redigest(p, assessment_classification=wr.REVIEW_REQUIRED), rha.RCV_PROPOSAL_INVALID),
            (redigest(p, limitations=wr.LIMITATIONS[1:]), rha.RCV_LIMITATIONS_ALTERED),
            (redigest(p, proposal_limitations=()), rha.RCV_LIMITATIONS_ALTERED),
            (dataclasses.asdict(p), rha.RCV_PROPOSAL_INVALID),
            (types.SimpleNamespace(**vars(p)), rha.RCV_PROPOSAL_INVALID),
        ]
        for proposal, code in cases:
            self.assertRefused(self.verify(proposal=proposal), code)
        # Fresh, internally consistent proposals for a different HEAD / root are not the signed one.
        other_head, _, _ = make_proposal({"head_sha": "c" * 40, "listed_head": "c" * 40})
        other_queue, _, _ = make_proposal(queue_roots=(os.path.join(twra.ROOT, "runtime", "queue-2"),))
        for proposal in (other_head, other_queue, redigest(p, report_fingerprint="8" * 64)):
            self.assertRefused(self.verify(proposal=proposal), rha.RCV_PROPOSAL_BINDING_MISMATCH,
                               signature_verified=True)

    def test_source_records_mismatch_or_half_supplied_is_refused(self):
        other_report, other_record = twra.fixture({"head_sha": "c" * 40, "listed_head": "c" * 40})
        self.assertRefused(self.verify(report=other_report, inventory_record=other_record),
                           rha.RCV_PROPOSAL_SOURCE_MISMATCH)
        refused_report, _ = twra.fixture(status=wr.REPORT_FAILED_CLOSED)
        self.assertRefused(self.verify(report=refused_report, inventory_record=self.record),
                           rha.RCV_PROPOSAL_SOURCE_MISMATCH)
        self.assertRefused(self.verify(report=self.report), rha.RCV_INPUT_INVALID)
        self.assertRefused(self.verify(inventory_record=self.record), rha.RCV_INPUT_INVALID)

    def test_proposal_for_another_host_label_is_refused(self):
        other, _, _ = make_proposal(host_id="host-02")
        self.assertRefused(self.verify(proposal=other), rha.RCV_HOST_MISMATCH)
        self.assertRefused(self.verify(config=make_config(raw_public(self.private), host_id="host-02")),
                           rha.RCV_HOST_MISMATCH)


# ---------------------------------------------------------------------------
# 3. Cross-domain: PR-merge commands and the existing PR authority
# ---------------------------------------------------------------------------

class CrossDomainTests(tau.AuthorityFixture):
    """The REAL FCP-3B PR authority (unmodified) and the retirement verifier,
    both pinning the SAME Ed25519 public key."""

    def setUp(self):
        super().setUp()
        self.proposal, _, _ = make_proposal()
        self.retirement_config = make_config(raw_public(self.private))
        self.retirement_command = command_for(self.proposal)

    def verify_retirement(self, raw):
        return rha.verify_retirement_command(raw, config=self.retirement_config, proposal=self.proposal, now=NOW)

    def assertRetirementRefused(self, raw, code):
        result = self.verify_retirement(raw)
        self.assertEqual((result.status, result.reason_codes, result.signature_verified),
                         (rha.STATUS_REFUSED, (code,), False))
        self.assertIs(result.authorizes_action, False)

    def test_pr_merge_command_is_rejected_by_the_retirement_verifier(self):
        pr_raw = tau.envelope(tau.command_for(self.request), self.private)
        self.assertRetirementRefused(pr_raw, rha.RCV_ENVELOPE_MALFORMED)
        pr_document = json.loads(pr_raw)
        rewrapped = json.dumps({"command": pr_document["command"], "signature": pr_document["signature"]}).encode()
        self.assertRetirementRefused(rewrapped, rha.RCV_COMMAND_VERSION_UNSUPPORTED)

    def test_retirement_envelope_does_not_satisfy_the_pr_authority(self):
        raw = envelope(self.retirement_command, self.private)
        self.assertVerifiedRetirement(raw)
        submission = self.authority.submit_command(raw, self.request)
        self.assertEqual((submission.accepted, submission.command_id, submission.reason_codes),
                         (False, None, (rauth.AUTH_ENVELOPE_MALFORMED,)))
        wrapped = dict(json.loads(raw), format=rauth.COMMAND_FORMAT)
        submission = self.authority.submit_command(json.dumps(wrapped).encode(), self.request)
        self.assertEqual((submission.accepted, submission.reason_codes), (False, (rauth.AUTH_COMMAND_MALFORMED,)))
        self.assertIsNone(self.ledger.command_for_operation(self.op))
        self.assertEqual(self.verify().status, rauth.rpe.COMMAND_ABSENT)

    def assertVerifiedRetirement(self, raw):
        result = self.verify_retirement(raw)
        self.assertEqual((result.status, result.signature_verified, result.authorizes_action),
                         (rha.STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING, True, False))

    def test_signatures_do_not_cross_domains(self):
        body = rha.canonical_command_message(self.retirement_command)[len(rha.SIGNATURE_DOMAIN) + 1:]
        for message in (rauth.SIGNATURE_DOMAIN + b"\n" + body, body, b"\n" + body,
                        rauth.canonical_command_message(tau.command_for(self.request))):
            raw = envelope(self.retirement_command, signature=self.private.sign(message))
            self.assertRetirementRefused(raw, rha.RCV_SIGNATURE_INVALID)
        self.assertNotEqual(rha.SIGNATURE_DOMAIN, rauth.SIGNATURE_DOMAIN)
        self.assertFalse(rha.SIGNATURE_DOMAIN.startswith(rauth.SIGNATURE_DOMAIN))
        self.assertFalse(rauth.SIGNATURE_DOMAIN.startswith(rha.SIGNATURE_DOMAIN))
        self.assertNotIn(rha.COMMAND_FORMAT, (rauth.COMMAND_FORMAT, rauth.CONFIG_FORMAT))
        self.assertNotIn(rha.CONFIG_FORMAT, (rauth.COMMAND_FORMAT, rauth.CONFIG_FORMAT))

    def test_pr_key_id_namespace_is_not_accepted(self):
        raw = envelope(command_for(self.proposal, key_id=tau.KEY_ID), self.private)
        self.assertRetirementRefused(raw, rha.RCV_COMMAND_MALFORMED)
        pr_config = make_config(raw_public(self.private),
                                keys=(rha.PinnedRetirementPublicKey(tau.KEY_ID, DIRECTOR, raw_public(self.private)),))
        self.assertEqual(rha.config_errors(pr_config), rha.RCV_CONFIG_INVALID)


# ---------------------------------------------------------------------------
# 4. Strict envelope, keys and Directors
# ---------------------------------------------------------------------------

class EnvelopeStrictnessTests(VerifierFixture):
    def test_duplicate_keys_are_refused(self):
        raw = envelope(self.command, self.private)
        top = raw.replace(b'{"command": ', b'{"signature": "x", "command": ', 1)
        self.assertRefused(self.verify(top), rha.RCV_ENVELOPE_MALFORMED)
        inner = raw.replace(b'"command_id": "retire-cmd-1"', b'"command_id": "retire-cmd-1", "command_id": "x"', 1)
        self.assertNotEqual(inner, raw)
        self.assertRefused(self.verify(inner), rha.RCV_ENVELOPE_MALFORMED)

    def test_extra_claims_and_missing_fields_are_refused_not_ignored(self):
        claims = ({"approved": True}, {"permit": "yes"}, {"public_key": raw_public(self.private).hex()},
                  {"execute": True}, {"authorizes_action": False}, {"issued": True}, {"replay_protected": True})
        for claim in claims + ({"format": rha.COMMAND_FORMAT},):
            self.assertRefused(self.verify(envelope(self.command, self.private, extra=claim)),
                               rha.RCV_ENVELOPE_MALFORMED)
        for claim in claims:
            self.assertRefused(self.verify(envelope(self.command, self.private, command_extra=claim)),
                               rha.RCV_COMMAND_MALFORMED)
        for name in rha.COMMAND_FIELDS:
            self.assertRefused(self.verify(envelope(self.command, self.private, drop=(name,))),
                               rha.RCV_COMMAND_MALFORMED)
        document = json.loads(envelope(self.command, self.private))
        for broken in ({"command": document["command"]}, {"signature": document["signature"]}, [document], "x", 1):
            self.assertRefused(self.verify(json.dumps(broken).encode()), rha.RCV_ENVELOPE_MALFORMED)
        self.assertRefused(self.verify(json.dumps({"command": [1], "signature": document["signature"]}).encode()),
                           rha.RCV_COMMAND_MALFORMED)

    def test_nan_infinity_invalid_utf8_bom_huge_and_deep_documents_are_refused(self):
        raw = envelope(self.command, self.private)
        for literal in (b"NaN", b"Infinity", b"-Infinity"):
            self.assertRefused(self.verify(raw.replace(b'"retire-cmd-1"', literal)), rha.RCV_ENVELOPE_MALFORMED)
        for bad in (raw.replace(b"retire-cmd-1", b"retire-\xff\xfe-1"), b"\xef\xbb\xbf" + raw, b"", b" ",
                    raw[:-1], raw + b"x", b"{" * 20000, b"[" * 15000 + b"]" * 15000,
                    raw[:-1] + b', "pad": "' + b"a" * rha.MAX_ENVELOPE_BYTES + b'"}'):
            self.assertRefused(self.verify(bad), rha.RCV_ENVELOPE_MALFORMED)
        for not_bytes in (raw.decode(), bytearray(raw), memoryview(raw), None, json.loads(raw)):
            self.assertRefused(self.verify(not_bytes), rha.RCV_INPUT_INVALID)

    def test_exact_primitive_types_are_required(self):
        for name in rha.COMMAND_FIELDS:
            values = (1, 0, True, False, None, 1.5, {}) + (("x",) if name in ("limitations", "proposal_limitations",
                                                                                "waivers") else ([],))
            for value in values:
                if name == "format" and type(value) is str:
                    continue
                raw = envelope(self.command, self.private, command_extra={name: value})
                self.assertRefused(self.verify(raw), rha.RCV_COMMAND_MALFORMED)
        for name in ("limitations", "proposal_limitations", "waivers"):
            for bad in ([True], [1], [None], [["x"]], [""], [" x"], ["x"] * 65):
                raw = envelope(self.command, self.private, command_extra={name: bad})
                self.assertRefused(self.verify(raw), rha.RCV_COMMAND_MALFORMED)

    def test_other_command_versions_are_refused(self):
        for version in ("fcp4e02b-retirement-command-v2", "fcp4e02b-retirement-command-v0", "", rauth.COMMAND_FORMAT):
            self.assertRefused(self.verify(self.signed(format=version)), rha.RCV_COMMAND_VERSION_UNSUPPORTED)

    def test_malformed_signatures_are_refused(self):
        signature = self.private.sign(rha.canonical_command_message(self.command))
        good = base64.b64encode(signature).decode()
        last = good[-3]   # 64 bytes -> 86 chars + "==": the 86th char carries 4 unused bits
        noncanonical = good[:-3] + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"[
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".index(last) ^ 1] + "=="
        self.assertEqual(base64.b64decode(noncanonical), signature)
        for bad in (good[:-2], good + "==", good[:-4], base64.b64encode(signature + b"\0").decode(),
                    base64.b64encode(signature[:63]).decode(), good.replace("+", "-").replace("/", "_") + "",
                    " " + good[1:], good[:-1] + "!", noncanonical, signature.hex(), "", 1, None, True,
                    [good], {"sig": good}):
            raw = envelope(self.command, signature=signature, extra={"signature": bad})
            if bad == good:
                continue
            self.assertRefused(self.verify(raw), rha.RCV_SIGNATURE_MALFORMED)

    def test_nonce_must_be_exact_hex_and_not_degenerate(self):
        for nonce in ("0" * 64, "01" * 32, "0123" * 16, NONCE[:-1], NONCE + "0", NONCE.upper(), "g" * 64):
            self.assertRefused(self.verify(self.signed(nonce=nonce)), rha.RCV_NONCE_INVALID)

    def test_unpinned_revoked_and_foreign_keys_and_directors_are_refused(self):
        public = raw_public(self.private)
        self.assertRefused(self.verify(self.signed(key_id="fcp4e02b-retire-key-other")), rha.RCV_KEY_UNPINNED)
        self.assertRefused(self.verify(config=make_config(public, revoked_key_ids=(KEY_ID,))), rha.RCV_KEY_REVOKED)
        self.assertRefused(self.verify(self.signed(director_id="director-other")), rha.RCV_DIRECTOR_MISMATCH)
        other = Ed25519PrivateKey.generate()
        two_keys = make_config(public, keys=(
            rha.PinnedRetirementPublicKey(KEY_ID, DIRECTOR, public),
            rha.PinnedRetirementPublicKey("fcp4e02b-retire-key-2", "director-other", raw_public(other))))
        # A pinned key of ANOTHER (allowed) Director cannot sign for this Director id.
        raw = envelope(command_for(self.proposal, key_id="fcp4e02b-retire-key-2"), other)
        self.assertRefused(self.verify(raw, config=two_keys), rha.RCV_DIRECTOR_MISMATCH)
        self.assertRefused(self.verify(config=make_config(public, allowed_director_ids=("director-z",))),
                           rha.RCV_DIRECTOR_NOT_ALLOWED)
        # A key generated elsewhere (e.g. by a Runner or provider) under the pinned key id.
        self.assertRefused(self.verify(envelope(self.command, other)), rha.RCV_SIGNATURE_INVALID)
        self.assertRefused(self.verify(config=make_config(raw_public(other))), rha.RCV_SIGNATURE_INVALID)

    def test_unkeyed_digests_or_hmacs_are_not_signatures(self):
        message = rha.canonical_command_message(self.command)
        for forged in (hashlib.sha512(message).digest(), hmac.new(b"runner-key", message, hashlib.sha512).digest(),
                       b"\0" * 64, hashlib.sha256(message).digest() * 2):
            self.assertRefused(self.verify(envelope(self.command, signature=forged)), rha.RCV_SIGNATURE_INVALID)

    def test_refusals_leak_no_content_and_never_raise(self):
        secret = "SECRET-" + "9" * 20
        raw = self.signed(key_id="fcp4e02b-retire-key-" + secret, command_id=secret)
        result = self.assertRefused(self.verify(raw), rha.RCV_KEY_UNPINNED)
        self.assertNotIn(secret, repr(result))
        with self.assertRaises(rha.RetirementEnvelopeRefused) as ctx:
            rha.parse_retirement_envelope(raw.replace(b'"command_id"', b'"command_id_x"'))
        self.assertEqual(str(ctx.exception), rha.RCV_COMMAND_MALFORMED)
        self.assertNotIn(secret, str(ctx.exception) + repr(ctx.exception.args))
        with mock.patch.object(rha, "_signature_valid", side_effect=RuntimeError(secret)):
            result = self.assertRefused(self.verify(), rha.RCV_INTERNAL_ERROR)
        self.assertNotIn(secret, repr(result))

    def test_random_mutations_never_raise_or_authorize(self):
        raw = envelope(self.command, self.private)
        rng = random.Random(4202)
        for _ in range(400):
            mutated = bytearray(raw)
            for _ in range(rng.randint(1, 4)):
                mutated[rng.randrange(len(mutated))] = rng.randrange(256)
            result = self.assertNonAuthorizing(self.verify(bytes(mutated)))
            self.assertIn(result.reason_codes, ((),) + tuple((c,) for c in rha.VERIFICATION_REFUSAL_CODES))
            if not result.reason_codes:   # only JSON whitespace changed: the signed command is identical
                self.assertEqual(rha.parse_retirement_envelope(bytes(mutated)).command, self.command)


# ---------------------------------------------------------------------------
# 5. Time
# ---------------------------------------------------------------------------

class TimeTests(VerifierFixture):
    def test_invalid_or_missing_clock_is_refused(self):
        class SubDatetime(datetime):
            pass

        for now in (None, NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=1))), NOW.date(),
                    stamp(0), NOW.timestamp(), lambda: NOW,
                    SubDatetime(2026, 10, 26, 12, tzinfo=timezone.utc)):
            self.assertRefused(self.verify(now=now), rha.RCV_CLOCK_INVALID)

    def test_strict_utc_timestamps(self):
        for value in ("2026-10-26T11:59:00+00:00", "2026-10-26T11:59:00", "2026-10-26T11:59:00z",
                      "2026-10-26 11:59:00Z", "2026-10-26T11:59:00.000Z", "2026-02-30T11:59:00Z",
                      "2026-10-26T24:00:00Z", "２０２６-10-26T11:59:00Z", "1792016340", "2026-10-26T11:59Z"):
            self.assertRefused(self.verify(self.signed(issued_at=value)), rha.RCV_TIMESTAMP_INVALID,
                               signature_verified=True)
            self.assertRefused(self.verify(self.signed(expires_at=value)), rha.RCV_TIMESTAMP_INVALID,
                               signature_verified=True)
        self.assertRefused(self.verify(self.signed(issued_at=stamp(60), expires_at=stamp(60))),
                           rha.RCV_TIMESTAMP_INVALID, signature_verified=True)
        self.assertRefused(self.verify(self.signed(issued_at=stamp(60), expires_at=stamp(0))),
                           rha.RCV_TIMESTAMP_INVALID, signature_verified=True)

    def test_window_ttl_future_and_expiry(self):
        self.assertRefused(self.verify(self.signed(issued_at=stamp(-100), expires_at=stamp(201))),
                           rha.RCV_TTL_TOO_LONG, signature_verified=True)
        self.assertRefused(self.verify(self.signed(issued_at=stamp(-60), expires_at=stamp(3600))),
                           rha.RCV_TTL_TOO_LONG, signature_verified=True)
        self.assertRefused(self.verify(self.signed(issued_at=stamp(1), expires_at=stamp(200))),
                           rha.RCV_COMMAND_NOT_YET_VALID, signature_verified=True)
        self.assertRefused(self.verify(self.signed(issued_at=stamp(-200), expires_at=stamp(0))),
                           rha.RCV_COMMAND_EXPIRED, signature_verified=True)
        self.assertRefused(self.verify(now=NOW + timedelta(seconds=180)), rha.RCV_COMMAND_EXPIRED,
                           signature_verified=True)
        self.assertRefused(self.verify(now=NOW - timedelta(seconds=61)), rha.RCV_COMMAND_NOT_YET_VALID,
                           signature_verified=True)

    def test_clock_regression_against_the_supplied_high_water_mark(self):
        self.assertRefused(self.verify(trusted_high_water_mark=NOW + timedelta(seconds=1)),
                           rha.RCV_CLOCK_REGRESSION)
        for mark in (NOW.replace(tzinfo=None), stamp(0), 0):
            self.assertRefused(self.verify(trusted_high_water_mark=mark), rha.RCV_CLOCK_INVALID)

    def test_no_clock_upgrades_any_flag(self):
        for now in (NOW, NOW - timedelta(seconds=60), NOW + timedelta(seconds=179)):
            result = self.verify(now=now, trusted_high_water_mark=now)
            self.assertVerified(result)
            self.assertIn("CALLER_CLOCK_NOT_TRUSTED", result.limitations)


# ---------------------------------------------------------------------------
# 6. Trust configuration: shape and safe loading
# ---------------------------------------------------------------------------

class ConfigShapeTests(VerifierFixture):
    def test_bad_configs_are_refused(self):
        public = raw_public(self.private)
        other = raw_public(Ed25519PrivateKey.generate())
        key = rha.PinnedRetirementPublicKey
        bad = [
            dict(format=rauth.CONFIG_FORMAT), dict(host_id=""), dict(host_id="host 01"), dict(host_id=1),
            dict(allowed_director_ids=()), dict(allowed_director_ids=[DIRECTOR]),
            dict(allowed_director_ids=(DIRECTOR, DIRECTOR)), dict(allowed_director_ids=(1,)), dict(keys=()),
            dict(keys=[key(KEY_ID, DIRECTOR, public)]),
            dict(keys=(key(KEY_ID, DIRECTOR, public), key(KEY_ID, DIRECTOR, other))),
            dict(keys=(key(KEY_ID, DIRECTOR, public), key("fcp4e02b-retire-key-2", DIRECTOR, public))),
            dict(keys=(key(KEY_ID, DIRECTOR, public[:31]),)), dict(keys=(key(KEY_ID, DIRECTOR, public.hex()),)),
            dict(keys=(key(KEY_ID, DIRECTOR, b"\0" * 32),)), dict(keys=(key(KEY_ID, DIRECTOR, b"\1" + b"\0" * 31),)),
            dict(keys=(key("director-key-1", DIRECTOR, public),)), dict(keys=(key(KEY_ID, 7, public),)),
            dict(keys=((KEY_ID, DIRECTOR, public),)), dict(keys=(key(KEY_ID, DIRECTOR, public),) * 65),
            dict(revoked_key_ids=("director-key-1",)), dict(revoked_key_ids=(KEY_ID, KEY_ID)),
            dict(revoked_key_ids=[KEY_ID]), dict(provenance_path="relative.json"), dict(provenance_path=""),
        ]
        for changes in bad:
            config = make_config(public, **changes)
            self.assertEqual(rha.config_errors(config), rha.RCV_CONFIG_INVALID, changes)
            self.assertRefused(self.verify(config=config), rha.RCV_CONFIG_INVALID)
        forged = forge(self.config, host_identity_authenticated=True)
        self.assertRefused(self.verify(config=forged), rha.RCV_CONFIG_INVALID)
        for not_config in (None, dataclasses.asdict(self.config), types.SimpleNamespace(**vars(self.config))):
            self.assertRefused(self.verify(config=not_config), rha.RCV_CONFIG_INVALID)
        self.assertIsNone(rha.config_errors(self.config))


class ConfigLoaderTests(NoNetworkMixin, unittest.TestCase):
    """Real files in a fresh temporary directory (canonical, realpath'd),
    never inside the repository or any real worktree."""

    def setUp(self):
        super().setUp()
        self.assertTrue(rha.CRYPTO_AVAILABLE, "cryptography missing (failing, not skipping)")
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="fcp4e02b-hostcfg-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.assertFalse(rha._within(self.root, str(REPO_ROOT)))
        self.private = Ed25519PrivateKey.generate()
        self.forbidden = (str(REPO_ROOT), twra.ROOT)
        self.path = self.write("retirement-host.json")

    def document(self, path, **changes):
        doc = {"format": rha.CONFIG_FORMAT, "host_id": HOST, "allowed_director_ids": [DIRECTOR],
               "keys": [{"key_id": KEY_ID, "director_id": DIRECTOR, "public_key_hex": raw_public(self.private).hex()}],
               "revoked_key_ids": [], "provenance_path": path}
        doc.update(changes)
        return json.dumps(doc).encode("utf-8")

    def write(self, name, data=None, directory=None, **changes):
        path = os.path.join(directory or self.root, name)
        with open(path, "wb") as handle:
            handle.write(self.document(path, **changes) if data is None else data)
        if os.name == "posix":
            os.chmod(path, 0o600)
        return path

    def load(self, path=_DEFAULT, forbidden=None):
        return rha.load_retirement_host_config(self.path if path is _DEFAULT else path,
                                               forbidden_roots=self.forbidden if forbidden is None else forbidden)

    def assertLoadRefused(self, code, path=_DEFAULT, forbidden=None):
        self.assertIn(code, rha.CONFIG_REFUSAL_CODES)
        with self.assertRaises(rha.RetirementHostConfigRefused) as ctx:
            self.load(path, forbidden)
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(str(ctx.exception), code)   # no path or content in the message

    def test_valid_file_loads_and_verifies_end_to_end_without_authorizing(self):
        config = self.load()
        self.assertEqual(config, make_config(raw_public(self.private), provenance_path=self.path))
        self.assertIs(config.host_identity_authenticated, False)
        self.assertEqual(rha.load_retirement_host_config(Path(self.path), forbidden_roots=[REPO_ROOT]), config)
        proposal, _, _ = make_proposal()
        result = rha.verify_retirement_command(envelope(command_for(proposal), self.private), config=config,
                                               proposal=proposal, now=NOW)
        self.assertEqual((result.status, result.signature_verified, result.authorizes_action, result.issued,
                          result.host_identity_authenticated), (rha.STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING, True,
                                                                False, False, False))

    def test_revoked_key_loads_but_never_verifies(self):
        config = self.load(self.write("revoked.json", revoked_key_ids=[KEY_ID]))
        proposal, _, _ = make_proposal()
        result = rha.verify_retirement_command(envelope(command_for(proposal), self.private), config=config,
                                               proposal=proposal, now=NOW)
        self.assertEqual(result.reason_codes, (rha.RCV_KEY_REVOKED,))

    def test_bad_documents_are_refused(self):
        dup = self.write("dup.json", data=b"")
        with open(dup, "wb") as handle:
            handle.write(self.document(dup)[:-1] + b', "host_id": "host-02"}')
        self.assertLoadRefused(rha.RCV_CONFIG_MALFORMED, dup)
        for name, data in (("nan.json", b'{"format": NaN}'), ("utf.json", b'{"format": "\xff"}'),
                           ("empty.json", b""), ("garbage.json", b"not json"), ("list.json", b"[]")):
            code = rha.RCV_CONFIG_INVALID if data == b"[]" else rha.RCV_CONFIG_MALFORMED
            self.assertLoadRefused(code, self.write(name, data=data))
        public_hex = raw_public(self.private).hex()
        for name, changes in (
                ("pr.json", {"format": rauth.CONFIG_FORMAT}), ("priv.json", {"private_key_hex": "11" * 32}),
                ("seed.json", {"seed": "11" * 32}), ("trusted.json", {"host_identity_authenticated": True}),
                ("hex.json", {"keys": [{"key_id": KEY_ID, "director_id": DIRECTOR, "public_key_hex": "zz" * 32}]}),
                ("upper.json", {"keys": [{"key_id": KEY_ID, "director_id": DIRECTOR,
                                          "public_key_hex": public_hex.upper()}]}),
                ("extra.json", {"keys": [{"key_id": KEY_ID, "director_id": DIRECTOR, "public_key_hex": public_hex,
                                          "private_key_hex": "11" * 32}]}),
                ("nokeys.json", {"keys": []}), ("dirs.json", {"allowed_director_ids": "x"})):
            self.assertLoadRefused(rha.RCV_CONFIG_INVALID, self.write(name, **changes))
        missing = self.write("missing-field.json", data=json.dumps(
            {k: v for k, v in json.loads(self.document(self.path)).items() if k != "revoked_key_ids"}).encode())
        self.assertLoadRefused(rha.RCV_CONFIG_INVALID, missing)

    def test_provenance_must_name_this_exact_file(self):
        copied = os.path.join(self.root, "copied.json")
        with open(copied, "wb") as handle:
            handle.write(self.document(self.path))
        self.assertLoadRefused(rha.RCV_CONFIG_PROVENANCE_MISMATCH, copied)
        self.assertLoadRefused(rha.RCV_CONFIG_PROVENANCE_MISMATCH,
                               self.write("relative-prov.json", provenance_path="retirement-host.json"))

    def test_invalid_path_forms_are_refused(self):
        name = os.path.basename(self.path)
        bad = ["", "retirement-host.json", os.path.join("relative", name), "file:" + self.path,
               "file:///" + self.path.replace(os.sep, "/"), "FILE://" + self.path,
               os.path.join(self.root, "sub", "..", name), os.path.join(self.root, ".", name), self.path + os.sep,
               self.path + "\0", " " + self.path, None, 1, b"/x", ["x"]]
        if os.name == "nt":
            bad += [r"\\server\share\retirement-host.json", "\\\\?\\" + self.path, "\\\\.\\" + self.path,
                    self.path + ":stream", self.path[2:], "C:relative.json"]
        for path in bad:
            self.assertLoadRefused(rha.RCV_CONFIG_PATH_INVALID, path)

    def test_forbidden_roots_must_be_explicit_and_are_enforced(self):
        for roots in ((), [], None, self.root, "relative", ("relative",), ("",), (1,), b"x"):
            with self.assertRaises(rha.RetirementHostConfigRefused) as ctx:
                rha.load_retirement_host_config(self.path, forbidden_roots=roots)
            self.assertEqual(ctx.exception.code, rha.RCV_CONFIG_ROOTS_INVALID)
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_FORBIDDEN_ROOT, forbidden=(self.root,))
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_FORBIDDEN_ROOT, forbidden=(os.path.dirname(self.root),))
        # Inside this repository (never created): refused before the file is even looked at.
        in_repo = os.path.join(str(REPO_ROOT), "scripts", "fcp4e02b-never-created-host.json")
        self.assertFalse(os.path.lexists(in_repo))
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_FORBIDDEN_ROOT, in_repo, forbidden=(twra.ROOT,))
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_FORBIDDEN_ROOT, os.path.join(twra.WT, "host.json"))
        self.assertFalse(os.path.lexists(in_repo))

    def test_missing_directory_and_oversize_are_refused(self):
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_MISSING, os.path.join(self.root, "absent.json"))
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_MISSING, os.path.join(self.root, "absent-dir", "x.json"))
        os.mkdir(os.path.join(self.root, "a-directory"))
        self.assertLoadRefused(rha.RCV_CONFIG_NOT_REGULAR_FILE, os.path.join(self.root, "a-directory"))
        self.assertLoadRefused(rha.RCV_CONFIG_OVERSIZE,
                               self.write("big.json", data=b" " * (rha.MAX_CONFIG_BYTES + 1)))

    def test_hard_link_alias_is_refused(self):
        alias = os.path.join(self.root, "hardlink.json")
        os.link(self.path, alias)
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_ALIAS)
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_ALIAS, alias)

    def test_directory_link_or_junction_in_the_path_is_refused(self):
        real_dir = os.path.join(self.root, "real")
        os.mkdir(real_dir)
        link_dir = os.path.join(self.root, "linked")
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(real_dir, link_dir)   # needs no privilege
        else:
            os.symlink(real_dir, link_dir, target_is_directory=True)
        self.addCleanup(lambda: os.path.lexists(link_dir) and (os.rmdir if os.name == "nt" else os.unlink)(link_dir))
        via_link = os.path.join(link_dir, "host.json")
        with open(os.path.join(real_dir, "host.json"), "wb") as handle:
            handle.write(self.document(via_link))
        if os.name == "posix":
            os.chmod(os.path.join(real_dir, "host.json"), 0o600)
        self.assertLoadRefused(rha.RCV_CONFIG_PATH_ALIAS, via_link)

    def test_file_symlink_is_refused_when_detected(self):
        real_lstat = os.lstat
        target = os.path.normcase(self.path)

        def lstat_as_link(path, *args, **kwargs):
            st = real_lstat(path, *args, **kwargs)
            if os.path.normcase(os.fspath(path)) == target:
                return os.stat_result((stat.S_IFLNK | 0o777,) + tuple(st)[1:10])
            return st

        with mock.patch.object(os, "lstat", lstat_as_link), \
                mock.patch.object(os.path, "realpath", lambda p, *a, **k: os.fspath(p)):
            self.assertLoadRefused(rha.RCV_CONFIG_PATH_ALIAS)
        if os.name == "posix":
            link = os.path.join(self.root, "symlink.json")
            os.symlink(self.path, link)
            self.assertLoadRefused(rha.RCV_CONFIG_PATH_ALIAS, link)

    def test_file_swapped_between_check_and_open_is_refused(self):
        real_fstat = os.fstat

        def swapped(fd):
            st = real_fstat(fd)
            values = list(tuple(st)[:10])
            values[1] = st.st_ino + 1
            return os.stat_result(tuple(values))

        with mock.patch.object(os, "fstat", swapped):
            self.assertLoadRefused(rha.RCV_CONFIG_PATH_ALIAS)

    def test_insecure_permissions_are_refused_where_detectable(self):
        f = types.SimpleNamespace
        with mock.patch.object(rha.os, "name", "posix"):
            self.assertTrue(rha._mode_insecure(f(st_mode=stat.S_IFREG | 0o666, st_uid=0), directory=False))
            self.assertTrue(rha._mode_insecure(f(st_mode=stat.S_IFREG | 0o620, st_uid=0), directory=False))
            self.assertFalse(rha._mode_insecure(f(st_mode=stat.S_IFREG | 0o600, st_uid=0), directory=False))
            self.assertTrue(rha._mode_insecure(f(st_mode=stat.S_IFDIR | 0o777, st_uid=0), directory=True))
            self.assertFalse(rha._mode_insecure(f(st_mode=stat.S_IFDIR | 0o1777, st_uid=0), directory=True))
            self.assertFalse(rha._mode_insecure(f(st_mode=stat.S_IFDIR | 0o755, st_uid=0), directory=True))
        if os.name == "posix":
            os.chmod(self.path, 0o666)
            self.assertLoadRefused(rha.RCV_CONFIG_PATH_INSECURE)
            os.chmod(self.path, 0o600)
            os.chmod(self.root, 0o777)
            self.addCleanup(os.chmod, self.root, 0o700)
            self.assertLoadRefused(rha.RCV_CONFIG_PATH_INSECURE)
        else:
            # Windows ACLs are NOT inspected: documented limitation, never claimed as checked.
            self.assertFalse(rha._mode_insecure(f(st_mode=stat.S_IFREG | 0o666, st_uid=0), directory=False))
            self.assertIn("Windows ACLs are not inspected", " ".join(rha.__doc__.split()))

    def test_loading_is_read_only(self):
        def boom(*args, **kwargs):
            raise AssertionError("write attempted")

        opened = []
        real_open = os.open

        def recording_open(path, flags, *args, **kwargs):
            opened.append(flags)
            return real_open(path, flags, *args, **kwargs)

        patches = [mock.patch.object(builtins, "open", boom), mock.patch.object(os, "write", boom),
                   mock.patch.object(os, "remove", boom), mock.patch.object(os, "unlink", boom),
                   mock.patch.object(os, "replace", boom), mock.patch.object(os, "rename", boom),
                   mock.patch.object(os, "mkdir", boom), mock.patch.object(os, "chmod", boom),
                   mock.patch.object(os, "truncate", boom), mock.patch.object(os, "open", recording_open),
                   mock.patch.object(subprocess, "Popen", boom)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.load()
        self.assertEqual(len(opened), 1)
        for flag in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"):
            self.assertFalse(opened[0] & getattr(os, flag), flag)


# ---------------------------------------------------------------------------
# 7. Missing cryptography and the CI dependency
# ---------------------------------------------------------------------------

class CryptoUnavailableTests(NoNetworkMixin, unittest.TestCase):
    """The module loaded with `cryptography` made unimportable."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("fcp4e02b_without_crypto", MODULE_PATH)
        cls.module = importlib.util.module_from_spec(spec)
        blocked = {name: None for name in _CRYPTO_MODULES}
        with mock.patch.dict(sys.modules, {**blocked, spec.name: cls.module}):
            spec.loader.exec_module(cls.module)

    def test_without_cryptography_nothing_verifies(self):
        m = self.module
        self.assertIs(m.CRYPTO_AVAILABLE, False)
        self.assertIsNone(m._Ed25519PublicKey)
        self.assertEqual(m.HOST_DEPENDENCY, rha.HOST_DEPENDENCY)
        self.assertTrue(rha.CRYPTO_AVAILABLE, "the real module must have cryptography (CI installs it)")
        private = Ed25519PrivateKey.generate()
        proposal, report, record = make_proposal()
        command = command_for(proposal)
        signature = private.sign(m.canonical_command_message(command))
        self.assertFalse(m._signature_valid(raw_public(private), signature, m.canonical_command_message(command)))
        config = m.RetirementHostConfig(format=m.CONFIG_FORMAT, host_id=HOST, allowed_director_ids=(DIRECTOR,),
                                        keys=(m.PinnedRetirementPublicKey(KEY_ID, DIRECTOR, raw_public(private)),),
                                        revoked_key_ids=(), provenance_path=SYNTHETIC_PROVENANCE)
        self.assertIsNone(m.config_errors(config))   # shape only; never a verification
        for raw in (envelope(command, signature=signature), b"", None, envelope(command, signature=b"\0" * 64)):
            result = m.verify_retirement_command(raw, config=config, proposal=proposal, now=NOW, report=report,
                                                 inventory_record=record)
            self.assertEqual((result.status, result.reason_codes, result.signature_verified, result.authorizes_action),
                             (m.STATUS_REFUSED, (m.RCV_CRYPTO_UNAVAILABLE,), False, False))


# ---------------------------------------------------------------------------
# 9. Structure, purity and never-live boundaries
# ---------------------------------------------------------------------------

class StructureTests(NoNetworkMixin, unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.code = re.sub(r'"""[\s\S]*?"""', "", self.source)

    def test_imports_are_exactly_the_verification_set(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" for a in node.names}
        self.assertEqual(imported, {
            "__future__.annotations", "base64", "binascii", "dataclasses", "hashlib", "json", "os", "re", "stat",
            "sys", "dataclasses.dataclass", "dataclasses.field", "datetime.datetime", "datetime.timedelta",
            "datetime.timezone", "pathlib.Path", "typing.Optional",
            "scripts.ai.runner_worktree_retirement", "scripts.ai.runner_worktree_retirement_authorization",
            "runner_worktree_retirement", "runner_worktree_retirement_authorization",
            "cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PublicKey",
        })

    def test_no_private_key_signing_process_git_ledger_network_or_issuance(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for banned in ("sign", "generate", "private_bytes", "from_private_bytes", "Ed25519PrivateKey",
                       "serialization", "environ", "getenv", "putenv", "Popen", "system", "run", "call",
                       "check_output", "spawn", "startfile", "remove", "unlink", "rmdir", "rmtree", "rename",
                       "mkdir", "makedirs", "chmod", "write", "write_text", "write_bytes", "truncate", "symlink",
                       "link", "connect", "urlopen", "HostLedger", "HumanCommandAuthority", "DirLease", "QueueLock",
                       "acquire", "release", "register_command", "revoke_command", "submit_command"):
            self.assertNotIn(banned, names | attrs, banned)
        self.assertNotIn("open", names)   # no builtin open(); os.open is allowlisted read-only below
        for text in ("PrivateKey", "subprocess", "socket", "sqlite", "hmac", "secrets", "urllib", "http",
                     "requests", "runner_promotion", "runner_git", "runner_integration", "runner_worktree_inventory",
                     "claude_queue", "claude_multiworker", "runner_pipeline", "runner_factory_ledger", "_git(",
                     "worktree remove", "prune", "branch -D", "update-ref", "O_WRONLY", "O_RDWR", "O_CREAT",
                     "O_TRUNC", "O_APPEND", "GITHUB_TOKEN", ".env", "compose_live", "fcp3b2b2"):
            self.assertNotIn(text, self.code, text)

    def test_os_usage_is_allowlisted_and_read_only(self):
        used = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                used.setdefault(node.value.id, set()).add(node.attr)
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name) and node.value.value.id == "os"):
                used.setdefault("os.path", set()).add(node.attr)
        self.assertLessEqual(used.get("os", set()),
                             {"path", "name", "sep", "lstat", "fstat", "open", "read", "close", "O_RDONLY",
                              "geteuid"})
        self.assertLessEqual(used.get("os.path", set()),
                             {"isabs", "splitdrive", "normcase", "normpath", "realpath", "dirname"})
        self.assertLessEqual(used.get("wra", set()), {
            "RetirementProposal", "RetirementTargetIdentity", "RetirementScope", "PROPOSAL_SCHEMA", "TARGET_SCHEMA",
            "SCOPE_SCHEMA", "identity_digest", "scope_digest", "proposal_digest", "PROPOSAL_LIMITATIONS",
            "validate_proposal_against_report"})
        self.assertLessEqual(used.get("wr", set()), {"LIMITATIONS", "CANDIDATE_FOR_HUMAN_REVIEW"})
        self.assertEqual(used.get("_Ed25519PublicKey", set()), {"from_public_bytes"})

    def test_no_issuing_or_acting_entry_points(self):
        defs = [n.name for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for name in defs:
            tokens = set(name.lower().split("_"))
            for word in ("issue", "consume", "permit", "approve", "sign", "mint", "execute", "live", "compose",
                         "register", "persist", "store", "write", "save", "provision", "retire", "delete",
                         "remove", "prune", "grant", "authorize"):
                self.assertNotIn(word, tokens, name)
        public = {n for n in dir(rha) if not n.startswith("_") and callable(getattr(rha, n))}
        self.assertLessEqual({n for n in public if n.islower()}, {
            "canonical_command_message", "parse_retirement_envelope", "config_errors",
            "load_retirement_host_config", "verify_retirement_command", "dataclass", "field", "datetime",
            "timedelta", "timezone"})
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg in dict(_FIXED_FLAGS):
                self.fail(f"fixed flag passed as keyword: {node.arg}")

    def test_never_live_constants_are_assigned_once_to_false(self):
        assigns = [n for n in ast.walk(self.tree) if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))]
        for name in ("RETIREMENT_AUTHORIZATION_LIVE", "RETIREMENT_EXECUTION_CAPABLE"):
            hits = [n for n in assigns for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
                    if isinstance(t, ast.Name) and t.id == name]
            self.assertEqual(len(hits), 1, name)
            self.assertIs(hits[0].value.value, False)
            self.assertIs(getattr(rha, name), False)
        self.assertIs(wra.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertIs(wra.RETIREMENT_EXECUTION_CAPABLE, False)
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_output_vocabulary_never_claims_issuance_approval_or_host_authentication(self):
        constants = {v for k, v in vars(rha).items() if k.isupper() and isinstance(v, str)}
        constants |= {x for x in rha.VERIFICATION_LIMITATIONS}
        for value in constants:
            for word in ("ISSUED", "APPROVED", "PERMITTED", "AUTHENTICATED_HOST", "ELIGIBLE"):
                self.assertNotIn(word, value, value)
        self.assertEqual(len(set(rha.VERIFICATION_REFUSAL_CODES)), len(rha.VERIFICATION_REFUSAL_CODES))
        self.assertEqual(len(set(rha.CONFIG_REFUSAL_CODES)), len(rha.CONFIG_REFUSAL_CODES))
        self.assertTrue(all(c.startswith("RCV_") for c in rha.VERIFICATION_REFUSAL_CODES + rha.CONFIG_REFUSAL_CODES))
        self.assertFalse(any(c.startswith("AUTH_") for c in rha.VERIFICATION_REFUSAL_CODES))

    def test_verification_touches_no_filesystem_process_database_or_network(self):
        proposal, report, record = make_proposal()
        private = Ed25519PrivateKey.generate()
        raw = envelope(command_for(proposal), private)
        config = make_config(raw_public(private))

        def boom(*args, **kwargs):
            raise AssertionError("side effect attempted")

        patches = [mock.patch.object(builtins, "open", boom), mock.patch.object(os, "open", boom),
                   mock.patch.object(os, "stat", boom), mock.patch.object(os, "lstat", boom),
                   mock.patch.object(os, "scandir", boom), mock.patch.object(os, "listdir", boom),
                   mock.patch.object(os, "getcwd", boom), mock.patch.object(os.path, "realpath", boom),
                   mock.patch.object(subprocess, "Popen", boom), mock.patch.object(sqlite3, "connect", boom),
                   mock.patch.object(Path, "resolve", boom), mock.patch.object(Path, "exists", boom)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        result = rha.verify_retirement_command(raw, config=config, proposal=proposal, now=NOW, report=report,
                                               inventory_record=record)
        self.assertEqual((result.status, result.reason_codes), (rha.STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING, ()))

    def test_02a_source_is_unmodified(self):
        digest = hashlib.sha256(WRA_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()
        self.assertEqual(digest, WRA_SOURCE_SHA256)

    def test_docstring_states_the_boundary(self):
        doc = " ".join(rha.__doc__.split())
        for phrase in ("NOT a permission, an approval, an issuance or an attestation of a real host",
                       "NO signing code", "never mints, signs, persists, issues, consumes or acts on a command",
                       "it never names or permits a branch deletion", "do NOT certify the host identity",
                       "there is no replay protection", "every verification is refused",
                       "D-1..D-12 remains pending", "a signature authenticates a key, not human presence"):
            self.assertIn(phrase, doc, phrase)


# ---------------------------------------------------------------------------
# CI
# ---------------------------------------------------------------------------

class CiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def job(self, name):
        return re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.workflow).group(1)

    def test_nine_jobs_unchanged(self):
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", self.workflow))
        self.assertEqual(jobs, twra.CiWorkflowTests.JOBS)

    def test_suite_runs_with_pinned_crypto_in_the_zero_skip_host_trust_job(self):
        job = self.job("fcp3b2b2-host-trust")
        self.assertIn("runs-on: windows-latest", job)
        self.assertIn('python -m pip install "cryptography==50.0.2"', job)
        self.assertIn("from scripts.ai.runner_worktree_retirement_host_authority import CRYPTO_AVAILABLE as R", job)
        ns = re.search(r"ns=\(([^)]*)\)", job).group(1)
        self.assertEqual(re.findall(r"'([^']+)'", ns), [
            "scripts.tests.test_runner_promotion_host_authority", "scripts.tests.test_runner_promotion_host_ledger",
            "scripts.tests.test_runner_promotion_host_github",
            "scripts.tests.test_runner_worktree_retirement_host_authority",
        ])
        self.assertIn("result.wasSuccessful() and not result.skipped", job)
        others = self.workflow.replace(job, "")
        self.assertNotIn("test_runner_worktree_retirement_host_authority", others)

    def test_previous_suites_preserved(self):
        twra.CiWorkflowTests.test_previous_suites_preserved(self)
        twra.CiWorkflowTests.test_proposal_suite_runs_in_the_zero_skip_retirement_job(self)


if __name__ == "__main__":
    unittest.main()
