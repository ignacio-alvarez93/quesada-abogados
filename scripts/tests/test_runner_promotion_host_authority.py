"""FCP-3B-2B2-HOST-01: human command authority of the trusted promotion host.

The request is a REAL `PromotionExecutionRequest` built through the existing
executor fixtures. Signing keys are ephemeral Ed25519 keys generated in
memory by these tests only (they stand in for the human Director; the module
under test has no signing code). Without the `cryptography` package the
signature tests are skipped and the fail-closed tests still run. The ledger
is a temporary SQLite file created by these tests. No network is reachable.
"""

import ast
import base64
import dataclasses
import hashlib
import hmac
import importlib.util
import json
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from scripts.ai import runner_promotion_executor as rpe
from scripts.ai import runner_promotion_host_authority as rauth
from scripts.ai import runner_promotion_host_ledger as rhl
from scripts.tests import test_runner_promotion_executor as tpe

if rauth.CRYPTO_AVAILABLE:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MODULE_PATH = Path(rauth.__file__)
NOW = tpe.NOW
DIRECTOR = tpe.DIRECTOR
KEY_ID = "director-key-1"
_NETWORK = []
_CRYPTO_MODULES = ("cryptography", "cryptography.exceptions", "cryptography.hazmat",
                   "cryptography.hazmat.primitives", "cryptography.hazmat.primitives.asymmetric",
                   "cryptography.hazmat.primitives.asymmetric.ed25519")


def _deny_network(*_args, **_kwargs):
    _NETWORK.append("attempt")
    raise OSError("network denied during host authority tests")


def setUpModule():
    for target, name in ((socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo")):
        patcher = mock.patch.object(target, name, _deny_network)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def stamp(seconds) -> str:
    return (NOW + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_public(private) -> bytes:
    return private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def command_for(request, **changes) -> rauth.HumanMergeCommand:
    return dataclasses.replace(rauth.HumanMergeCommand(
        format=rauth.COMMAND_FORMAT, command_id="cmd-1", nonce="0123456789abcdef0123456789abcdef", key_id=KEY_ID,
        director_id=DIRECTOR, operation_id=request.idempotency_key, request_fingerprint=request.fingerprint,
        repository=request.repository, pr_number=request.pr_number, base_ref=request.base_ref,
        base_sha=request.base_sha, head_ref=request.head_ref, head_sha=request.head_sha, action=request.action,
        merge_method=request.merge_method, issued_at=stamp(-60), expires_at=stamp(540)), **changes)


def envelope(command, private=None, signature=None, extra=None, command_extra=None) -> bytes:
    """What the Director's own signing tool would send (test stand-in)."""
    if signature is None:
        signature = private.sign(rauth.canonical_command_message(command))
    body = {name: getattr(command, name) for name in rauth._COMMAND_FIELDS}
    body.update(command_extra or {})
    document = {"format": rauth.COMMAND_FORMAT, "command": body,
                "signature": base64.b64encode(signature).decode("ascii")}
    document.update(extra or {})
    return json.dumps(document).encode("utf-8")


class NoNetworkMixin:
    def tearDown(self):
        self.assertEqual(_NETWORK, [])
        super().tearDown()


@unittest.skipUnless(rauth.CRYPTO_AVAILABLE, "cryptography not installed: signature verification NOT proven here")
class AuthorityFixture(NoNetworkMixin, tpe.ExecutorFixture):
    """A real request, an in-memory Director key pinned in a host config,
    and a temporary host ledger."""

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="fcp-host-auth-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.now = NOW
        self.ledger = rhl.HostLedger(self.root / "ledger.sqlite3", owner="host-a", clock=lambda: self.now)
        self.private = Ed25519PrivateKey.generate()
        self.config = self.make_config()
        self.authority = rauth.HumanCommandAuthority(self.config, self.ledger, clock=lambda: self.now)

    def make_config(self, **changes):
        return dataclasses.replace(rauth.HostAuthorityConfig(
            keys=(rauth.PinnedDirectorKey(KEY_ID, DIRECTOR, raw_public(self.private)),),
            allowed_director_ids=(DIRECTOR,), revoked_key_ids=(), source=str(self.root / "authority.json")),
            **changes)

    def submit(self, command=None, private=None, request=None, **kwargs):
        command = command or command_for(self.request)
        return self.authority.submit_command(envelope(command, private or self.private, **kwargs),
                                             request or self.request)

    def verify(self, **changes):
        bound = dict(operation_id=self.op, repository=self.request.repository, pr_number=self.request.pr_number,
                     base_sha=self.base, head_sha=self.head, action=rpe.ACTION_MERGE_GITHUB_PR)
        bound.update(changes)
        return self.authority.verify_human_command(**bound)

    def assertRefused(self, submission, code):
        self.assertIs(type(submission), rauth.CommandSubmission)
        self.assertIs(submission.accepted, False)
        self.assertIsNone(submission.command_id)
        self.assertEqual(submission.reason_codes, (code,))
        self.assertIsNone(self.ledger.command_for_operation(self.op))

    def assertVerdict(self, verdict, status):
        self.assertIs(type(verdict), rpe.HostCommandVerdict)
        self.assertEqual(verdict.status, status)
        errors = rpe._command_errors(verdict, self.request, self.now)
        if status == rpe.COMMAND_VERIFIED:
            self.assertEqual(errors, [])
        else:
            self.assertEqual(errors, [rpe._COMMAND_CODES[status]])
            self.assertEqual((verdict.command_id, verdict.director_id), ("none", 0))
        return verdict


# ---------------------------------------------------------------------------
# Authentic vs manipulated
# ---------------------------------------------------------------------------

class SignatureTests(AuthorityFixture):
    def test_authentic_command_is_registered_and_verified_for_exactly_this_operation(self):
        submission = self.submit()
        self.assertEqual((submission.accepted, submission.command_id, submission.reason_codes),
                         (True, "cmd-1", (rauth.AUTH_COMMAND_ACCEPTED,)))
        verdict = self.assertVerdict(self.verify(), rpe.COMMAND_VERIFIED)
        self.assertEqual((verdict.command_id, verdict.operation_id, verdict.director_id, verdict.repository,
                          verdict.pr_number, verdict.base_sha, verdict.head_sha, verdict.action),
                         ("cmd-1", self.op, DIRECTOR, self.request.repository, self.request.pr_number, self.base,
                          self.head, rpe.ACTION_MERGE_GITHUB_PR))
        stored = self.ledger.command_for_operation(self.op)
        self.assertEqual(stored.message, rauth.canonical_command_message(command_for(self.request)))
        self.assertTrue(stored.message.startswith(rauth.SIGNATURE_DOMAIN + b"\n"))
        self.assertIn(b'"format":"fcp3b2b2-host-human-command-v1"', stored.message)

    def test_any_field_altered_after_signing_is_refused(self):
        good = command_for(self.request)
        signature = self.private.sign(rauth.canonical_command_message(good))
        for name, value in (("pr_number", 43), ("head_sha", "c" * 40), ("base_sha", "d" * 40),
                            ("expires_at", stamp(600)), ("nonce", "f" * 32), ("command_id", "cmd-2")):
            altered = dataclasses.replace(good, **{name: value})
            self.assertRefused(self.authority.submit_command(envelope(altered, signature=signature), self.request),
                               rauth.AUTH_SIGNATURE_INVALID)
        flipped = bytes([signature[0] ^ 1]) + signature[1:]
        self.assertRefused(self.submit(signature=flipped), rauth.AUTH_SIGNATURE_INVALID)

    def test_key_generated_elsewhere_cannot_use_a_pinned_key_id(self):
        provider_key = Ed25519PrivateKey.generate()   # e.g. a provider or Runner generated key
        self.assertRefused(self.submit(private=provider_key), rauth.AUTH_SIGNATURE_INVALID)
        self.assertRefused(self.submit(command_for(self.request, key_id="provider-key")), rauth.AUTH_KEY_UNKNOWN)
        # A public key in the payload is refused, never used.
        self.assertRefused(self.submit(command_extra={"public_key_hex": raw_public(provider_key).hex()}),
                           rauth.AUTH_COMMAND_MALFORMED)
        self.assertRefused(self.submit(extra={"public_key": raw_public(provider_key).hex()}),
                           rauth.AUTH_ENVELOPE_MALFORMED)

    def test_unkeyed_digest_or_hmac_computed_by_the_runner_is_not_a_signature(self):
        message = rauth.canonical_command_message(command_for(self.request))
        for forged in (hashlib.sha256(message).digest(), hashlib.sha512(message).digest(),
                       hmac.new(b"runner-chosen-key", message, hashlib.sha512).digest()):
            submission = self.submit(signature=forged)
            self.assertIn(submission.reason_codes, ((rauth.AUTH_ENVELOPE_MALFORMED,), (rauth.AUTH_SIGNATURE_INVALID,)))
            self.assertIs(submission.accepted, False)
        self.assertVerdict(self.verify(), rpe.COMMAND_ABSENT)

    def test_flags_like_approved_or_is_admin_are_refused_not_ignored(self):
        for extra in ({"approved": True}, {"is_admin": True}, {"trusted": True}, {"authorizes_action": True}):
            self.assertRefused(self.submit(command_extra=extra), rauth.AUTH_COMMAND_MALFORMED)
            self.assertRefused(self.submit(extra=extra), rauth.AUTH_ENVELOPE_MALFORMED)
        raw = envelope(command_for(self.request), self.private)
        duplicated = raw.replace(b'"format": "fcp3b2b2-host-human-command-v1", "command"',
                                 b'"format": "fcp3b2b2-host-human-command-v1", "format": "x", "command"', 1)
        self.assertRefused(self.authority.submit_command(duplicated, self.request), rauth.AUTH_ENVELOPE_MALFORMED)
        as_bool = envelope(command_for(self.request), self.private).replace(b'"pr_number": 42', b'"pr_number": true')
        self.assertRefused(self.authority.submit_command(as_bool, self.request), rauth.AUTH_COMMAND_MALFORMED)
        for junk in (b"", b"[]", b"{", "{}".encode("utf-16"), b"x" * (rauth.MAX_ENVELOPE_BYTES + 1), None, "text"):
            self.assertIs(self.authority.submit_command(junk, self.request).accepted, False)


# ---------------------------------------------------------------------------
# Identity, binding, actors and time
# ---------------------------------------------------------------------------

class BindingTests(AuthorityFixture):
    def test_correctly_signed_command_for_another_identity_is_refused(self):
        for name, value in (("operation_id", "e" * 64), ("request_fingerprint", "e" * 64), ("pr_number", 43),
                            ("head_sha", "c" * 40), ("base_sha", "d" * 40), ("head_ref", "feature/other")):
            self.assertRefused(self.submit(command_for(self.request, **{name: value})), rauth.AUTH_BINDING_MISMATCH)
        for name, value in (("repository", "someone/else"), ("base_ref", "main"), ("action", "FAST_FORWARD"),
                            ("merge_method", "squash"), ("format", "v0")):
            self.assertRefused(self.submit(command_for(self.request, **{name: value})), rauth.AUTH_COMMAND_MALFORMED)

    def test_request_must_re_derive(self):
        tampered = dataclasses.replace(self.request, head_sha="c" * 40)
        self.assertRefused(self.submit(request=tampered), rauth.AUTH_REQUEST_INVALID)
        self.assertRefused(self.submit(request={"idempotency_key": self.op}), rauth.AUTH_REQUEST_INVALID)

    def test_actor_must_be_pinned_allowed_and_match_the_key(self):
        self.assertRefused(self.submit(command_for(self.request, director_id=tpe.thu.OTHER)),
                           rauth.AUTH_DIRECTOR_MISMATCH)
        self.authority = rauth.HumanCommandAuthority(self.make_config(allowed_director_ids=()), self.ledger,
                                                     clock=lambda: self.now)
        self.assertRefused(self.submit(), rauth.AUTH_DIRECTOR_NOT_ALLOWED)
        self.authority = rauth.HumanCommandAuthority(self.make_config(revoked_key_ids=(KEY_ID,)), self.ledger,
                                                     clock=lambda: self.now)
        self.assertRefused(self.submit(), rauth.AUTH_KEY_REVOKED)

    def test_time_window_ttl_and_future_issue(self):
        cases = ((dict(issued_at=stamp(-600), expires_at=stamp(-1)), rauth.AUTH_COMMAND_EXPIRED),
                 (dict(issued_at=stamp(-60), expires_at=stamp(rpe.MAX_COMMAND_TTL_SECONDS)), rauth.AUTH_TTL_TOO_LONG),
                 (dict(issued_at=stamp(30), expires_at=stamp(300)), rauth.AUTH_TIMESTAMP_INVALID),
                 (dict(issued_at=stamp(0), expires_at=stamp(0)), rauth.AUTH_TIMESTAMP_INVALID),
                 (dict(issued_at="2026-10-24 12:00:00"), rauth.AUTH_COMMAND_MALFORMED))
        for changes, code in cases:
            self.assertRefused(self.submit(command_for(self.request, **changes)), code)
        self.authority = rauth.HumanCommandAuthority(self.config, self.ledger, clock=lambda: NOW.replace(tzinfo=None))
        self.assertRefused(self.submit(), rauth.AUTH_CLOCK_INVALID)

    def test_expiry_after_registration_is_reported_expired(self):
        self.assertIs(self.submit().accepted, True)
        self.now = NOW + timedelta(seconds=540)
        self.assertVerdict(self.verify(), rpe.COMMAND_EXPIRED)


# ---------------------------------------------------------------------------
# Replay, revocation and absence
# ---------------------------------------------------------------------------

class LifecycleTests(AuthorityFixture):
    def test_replay_of_the_same_or_a_recycled_command_is_refused(self):
        self.assertIs(self.submit().accepted, True)
        again = self.submit()
        self.assertEqual((again.accepted, again.reason_codes), (False, (rauth.AUTH_COMMAND_REPLAYED,)))
        for changes in ({"command_id": "cmd-2"}, {"nonce": "f" * 32}):
            replay = self.submit(command_for(self.request, **changes))
            self.assertEqual(replay.reason_codes, (rauth.AUTH_COMMAND_REPLAYED,))
        self.assertEqual(self.ledger.command_for_operation(self.op).command_id, "cmd-1")

    def test_no_command_means_absent_whatever_the_reviews_say(self):
        # A favorable FCP-3B-2B1 evaluation and GitHub approvals are not a command.
        self.assertEqual(self.request.current_approver_ids, (DIRECTOR,))
        self.assertVerdict(self.verify(), rpe.COMMAND_ABSENT)
        self.assertVerdict(self.verify(operation_id=None), rpe.COMMAND_ABSENT)

    def test_revocation_after_registration_wins_before_any_use(self):
        self.assertIs(self.submit().accepted, True)
        self.authority.revoke_command("cmd-1", "DIRECTOR-REVOKED")
        self.assertVerdict(self.verify(), rpe.COMMAND_REVOKED)
        revoked_key = rauth.HumanCommandAuthority(self.make_config(revoked_key_ids=(KEY_ID,)), self.ledger,
                                                  clock=lambda: self.now)
        self.assertEqual(revoked_key.verify_human_command(self.op, self.request.repository, self.request.pr_number,
                                                          self.base, self.head, rpe.ACTION_MERGE_GITHUB_PR).status,
                         rpe.COMMAND_REVOKED)
        self.ledger.revoke_command("cmd-9", "DIRECTOR-REVOKED")
        pre_revoked = self.submit(command_for(self.request, command_id="cmd-9", nonce="9" * 32,
                                              operation_id=self.op))
        self.assertEqual(pre_revoked.reason_codes, (rauth.AUTH_COMMAND_REVOKED,))

    def test_verification_binds_every_argument_and_re_verifies_stored_bytes(self):
        self.assertIs(self.submit().accepted, True)
        for changes in ({"head_sha": "c" * 40}, {"base_sha": "d" * 40}, {"pr_number": 43},
                        {"repository": "someone/else"}, {"action": "FAST_FORWARD"}, {"pr_number": True}):
            self.assertVerdict(self.verify(**changes), rpe.COMMAND_REJECTED)
        # A host database row edited after registration no longer verifies.
        con = sqlite3.connect(str(self.ledger.path))
        con.execute("UPDATE commands SET head_sha = ?", ("c" * 40,))
        con.commit()
        con.close()
        self.assertVerdict(self.verify(), rpe.COMMAND_REJECTED)
        con = sqlite3.connect(str(self.ledger.path))
        con.execute("UPDATE commands SET head_sha = ?, signature = ?", (self.head, b"\x00" * 64))
        con.commit()
        con.close()
        self.assertVerdict(self.verify(), rpe.COMMAND_REJECTED)

    def test_a_different_key_pinned_later_does_not_verify_old_commands(self):
        self.assertIs(self.submit().accepted, True)
        rotated = rauth.HumanCommandAuthority(
            self.make_config(keys=(rauth.PinnedDirectorKey(KEY_ID, DIRECTOR,
                                                           raw_public(Ed25519PrivateKey.generate())),)),
            self.ledger, clock=lambda: self.now)
        self.assertEqual(rotated.verify_human_command(self.op, self.request.repository, self.request.pr_number,
                                                      self.base, self.head, rpe.ACTION_MERGE_GITHUB_PR).status,
                         rpe.COMMAND_REJECTED)


# ---------------------------------------------------------------------------
# Host configuration
# ---------------------------------------------------------------------------

class ConfigTests(NoNetworkMixin, unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="fcp-host-cfg-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.source = self.root / "host" / "authority.json"

    def document(self, **changes):
        data = {"format": rauth.CONFIG_FORMAT, "keys": [{"key_id": KEY_ID, "director_id": DIRECTOR,
                                                          "public_key_hex": self.public_hex()}],
                "allowed_director_ids": [DIRECTOR], "revoked_key_ids": []}
        data.update(changes)
        return json.dumps(data).encode()

    def public_hex(self):
        if rauth.CRYPTO_AVAILABLE:
            return raw_public(Ed25519PrivateKey.generate()).hex()
        return "11" * 32

    def refused(self, code, *args, **kwargs):
        with self.assertRaises(rauth.HostAuthorityRefused) as caught:
            rauth.load_authority_config(*args, **kwargs)
        self.assertIn(code, caught.exception.reason_codes)

    def test_config_source_must_be_outside_repository_and_untrusted_roots(self):
        self.refused(rauth.AUTH_CONFIG_SOURCE_UNTRUSTED, self.document(),
                     source_path=rauth.REPOSITORY_ROOT / "scripts" / "ai" / "authority.json")
        self.refused(rauth.AUTH_CONFIG_SOURCE_UNTRUSTED, self.document(), source_path="authority.json")
        self.refused(rauth.AUTH_CONFIG_SOURCE_UNTRUSTED, self.document(), source_path=self.source,
                     untrusted_roots=(self.root,))

    @unittest.skipUnless(rauth.CRYPTO_AVAILABLE, "key point validation needs cryptography")
    def test_valid_config_loads_and_strict_shape_is_enforced(self):
        config = rauth.load_authority_config(self.document(), source_path=self.source)
        self.assertEqual((config.allowed_director_ids, config.keys[0].key_id), ((DIRECTOR,), KEY_ID))
        entry = {"key_id": KEY_ID, "director_id": DIRECTOR, "public_key_hex": self.public_hex()}
        for bad in (self.document(keys=[]), self.document(keys=[dict(entry, private_key_hex="22" * 32)]),
                    self.document(keys=[dict(entry, public_key_hex="zz" * 32)]), self.document(keys=[entry, entry]),
                    self.document(signing_seed="00" * 32), self.document(format="other"),
                    self.document(keys=[dict(entry, director_id=True)]), b"not json"):
            self.refused(rauth.AUTH_CONFIG_INVALID, bad, source_path=self.source)

    def test_authority_requires_a_valid_config_and_registry(self):
        for config in (None, rauth.HostAuthorityConfig((), (DIRECTOR,), (), "x")):
            with self.assertRaises(rauth.HostAuthorityRefused):
                rauth.HumanCommandAuthority(config, object(), clock=lambda: NOW)


# ---------------------------------------------------------------------------
# Missing dependency: fail closed
# ---------------------------------------------------------------------------

class CryptoUnavailableTests(NoNetworkMixin, unittest.TestCase):
    """The module loaded with `cryptography` made unimportable."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("fcp_host_authority_without_crypto", MODULE_PATH)
        cls.module = importlib.util.module_from_spec(spec)
        blocked = {name: None for name in _CRYPTO_MODULES}
        with mock.patch.dict(sys.modules, {**blocked, spec.name: cls.module}):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="fcp-host-nocrypto-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.ledger = rhl.HostLedger(self.root / "ledger.sqlite3", owner="host-a", clock=lambda: NOW)
        m = self.module
        config = m.HostAuthorityConfig(keys=(m.PinnedDirectorKey(KEY_ID, DIRECTOR, b"\x11" * 32),),
                                       allowed_director_ids=(DIRECTOR,), revoked_key_ids=(), source="/host/a.json")
        self.authority = m.HumanCommandAuthority(config, self.ledger, clock=lambda: NOW)

    def test_without_cryptography_nothing_is_accepted_or_verified(self):
        m = self.module
        self.assertIs(m.CRYPTO_AVAILABLE, False)
        self.assertIsNone(m._Ed25519PublicKey)
        self.assertFalse(m._signature_valid(b"\x11" * 32, b"\x00" * 64, b"message"))
        submission = self.authority.submit_command(b'{"format": "x"}', None)
        self.assertEqual((submission.accepted, submission.reason_codes), (False, (m.AUTH_CRYPTO_UNAVAILABLE,)))
        op = "a" * 64
        self.ledger.register_command(rhl.RegisteredCommand(
            command_id="cmd-1", nonce="1" * 32, operation_id=op, request_fingerprint="f" * 64, key_id=KEY_ID,
            director_id=DIRECTOR, repository="ignacio-alvarez93/quesada-abogados", pr_number=42,
            base_sha="a" * 40, head_sha="b" * 40, action=rpe.ACTION_MERGE_GITHUB_PR, issued_at=stamp(-60),
            expires_at=stamp(300), message=b"m", signature=b"\x00" * 64))
        verdict = self.authority.verify_human_command(op, "ignacio-alvarez93/quesada-abogados", 42, "a" * 40,
                                                      "b" * 40, rpe.ACTION_MERGE_GITHUB_PR)
        self.assertEqual(verdict.status, rpe.COMMAND_REJECTED)
        self.assertEqual(m.HOST_DEPENDENCY, rauth.HOST_DEPENDENCY)
        self.assertIn("cryptography", m.HOST_DEPENDENCY)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class AuthorityStructureTests(NoNetworkMixin, unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.code = re.sub(r'"""[\s\S]*?"""', "", self.source)

    def test_verification_only_no_signing_secrets_env_or_processes(self):
        imports = {a.name for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names} | {n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("subprocess", "socket", "os", "urllib", "http", "requests", "hmac", "hashlib", "secrets",
                       "runner_git", "runner_pipeline", "runner_promotion_host_github", "Ed25519PrivateKey",
                       "serialization"):
            self.assertNotIn(banned, imports, banned)
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        for banned in ("sign", "generate", "private_bytes", "environ", "getenv", "open", "read_text", "read_bytes",
                       "write_text", "write_bytes", "Popen", "system"):
            self.assertNotIn(banned, attrs | names, banned)
        for text in ("PrivateKey", ".env", "git push", "update-ref", "Authorization", "https://", "GITHUB_TOKEN"):
            self.assertNotIn(text, self.code, text)

    def test_no_live_flag_and_core_unchanged(self):
        self.assertIs(rpe.PRODUCTION_PROMOTION_CAPABLE, False)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword):
                self.assertNotIn(node.arg, ("live_authorized", "production_capable", "human_command_authenticated",
                                            "authorizes_action", "execution_allowed"))
        self.assertNotIn("MODE_LIVE_AUTHORIZED", self.code)
        doc = " ".join(rauth.__doc__.split())
        for phrase in ("NO signing code", "PINNED", "never used", "every submission and every verification is "
                       "refused", "not human presence"):
            self.assertIn(phrase, doc, phrase)
        self.assertEqual(rauth.SIGNATURE_BYTES, 64)
        self.assertEqual(rauth.PUBLIC_KEY_BYTES, 32)


if __name__ == "__main__":
    unittest.main()
