"""FCP-3B-2B2-HOST-01: human command authority of the trusted promotion host (NOT LIVE).

The `HumanCommandPort` half of the `TrustedPromotionHost` contract of
`runner_promotion_executor`: it verifies an Ed25519-signed human Director
command for ONE merge of ONE pull request and answers the executor with a
`HostCommandVerdict`. It is a library for a FUTURE isolated host process;
this delivery deploys nothing and produces no live promotion
(`rpe.PRODUCTION_PROMOTION_CAPABLE` stays False).

Command (`HumanMergeCommand`, format COMMAND_FORMAT)
---------------------------------------------------
Binds the command id and an unrepeatable nonce, the pinned key id and the
Director id, the operation id (`PromotionExecutionRequest.idempotency_key`,
a digest of the whole request identity) and the request fingerprint, the
canonical repository, the PR number, `develop`, the base and head SHAs, the
head branch, the ONE action `MERGE_GITHUB_PR` with merge method `merge`, and
an issued/expires window in UTC of at most `rpe.MAX_COMMAND_TTL_SECONDS`.
The signed message is SIGNATURE_DOMAIN, a newline and the canonical JSON of
every field (sorted keys, ASCII): domain and version are part of what is
signed. The wire envelope is strict JSON with exactly the expected keys;
any extra claim (`approved`, `is_admin`, a public key, a trust flag) is
refused, never ignored.

Keys
----
Public keys are PINNED by key id and Director id in a `HostAuthorityConfig`
provisioned on the host, outside the repository and every untrusted root;
a key carried by a payload is never used. This module contains NO signing
code and holds no private key: the private key lives with the human
Director, never in the repository, the Runner or a provider, and a command
is never signed by Runner code. Verification needs the `cryptography`
package on the host (Ed25519); if it is missing (`CRYPTO_AVAILABLE` is
False) every submission and every verification is refused - nothing falls
back to an unkeyed digest, which a caller could always recompute.

Lifecycle
---------
`submit_command` verifies the envelope against the pinned key, the
re-derived request and the clock, then registers it once in the host ledger
(command id, nonce and operation are unique there). `verify_human_command`
(the port) re-reads the registered command, verifies its signature AGAIN
with the current configuration and checks key and command revocation,
expiry and the exact binding before answering COMMAND_VERIFIED. A
signature authenticates a key, not human presence, and this module is not a
deployed host: the verdict is only as trustworthy as the host process,
key provisioning and the Director's custody of the private key.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sys
from dataclasses import dataclass, fields
from datetime import timedelta
from pathlib import Path
from typing import Optional, Protocol

try:
    from scripts.ai import runner_promotion_executor as rpe
    from scripts.ai import runner_promotion_host_ledger as rhl
    from scripts.ai import runner_promotion_human_authorization as rha
    from scripts.ai import runner_promotion_pr_gate as rpg
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_promotion_executor as rpe  # type: ignore[no-redef]
    import runner_promotion_host_ledger as rhl  # type: ignore[no-redef]
    import runner_promotion_human_authorization as rha  # type: ignore[no-redef]
    import runner_promotion_pr_gate as rpg  # type: ignore[no-redef]

try:
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _Ed25519PublicKey
except ImportError:  # host dependency missing: nothing can be verified
    _InvalidSignature = None
    _Ed25519PublicKey = None

CRYPTO_AVAILABLE = _Ed25519PublicKey is not None
HOST_DEPENDENCY = "cryptography (Ed25519 verification) installed in the isolated host environment"

COMMAND_FORMAT = "fcp3b2b2-host-human-command-v1"
CONFIG_FORMAT = "fcp3b2b2-host-authority-config-v1"
SIGNATURE_DOMAIN = b"quesada-abogados/fabric/fcp3b2b2/human-merge-command/v1"
REPOSITORY_ROOT = rhl.REPOSITORY_ROOT
MAX_ENVELOPE_BYTES = 16384
MAX_CONFIG_BYTES = 65536
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64

# Refusal codes.
AUTH_CRYPTO_UNAVAILABLE = "AUTH_CRYPTO_UNAVAILABLE"
AUTH_CLOCK_INVALID = "AUTH_CLOCK_INVALID"
AUTH_CONFIG_INVALID = "AUTH_CONFIG_INVALID"
AUTH_CONFIG_SOURCE_UNTRUSTED = "AUTH_CONFIG_SOURCE_UNTRUSTED"
AUTH_ENVELOPE_MALFORMED = "AUTH_ENVELOPE_MALFORMED"
AUTH_COMMAND_MALFORMED = "AUTH_COMMAND_MALFORMED"
AUTH_REQUEST_INVALID = "AUTH_REQUEST_INVALID"
AUTH_BINDING_MISMATCH = "AUTH_BINDING_MISMATCH"
AUTH_KEY_UNKNOWN = "AUTH_KEY_UNKNOWN"
AUTH_KEY_REVOKED = "AUTH_KEY_REVOKED"
AUTH_DIRECTOR_MISMATCH = "AUTH_DIRECTOR_MISMATCH"
AUTH_DIRECTOR_NOT_ALLOWED = "AUTH_DIRECTOR_NOT_ALLOWED"
AUTH_SIGNATURE_INVALID = "AUTH_SIGNATURE_INVALID"
AUTH_TIMESTAMP_INVALID = "AUTH_TIMESTAMP_INVALID"
AUTH_TTL_TOO_LONG = "AUTH_TTL_TOO_LONG"
AUTH_COMMAND_EXPIRED = "AUTH_COMMAND_EXPIRED"
AUTH_COMMAND_REPLAYED = "AUTH_COMMAND_REPLAYED"
AUTH_COMMAND_REVOKED = "AUTH_COMMAND_REVOKED"
AUTH_REGISTRY_FAILED = "AUTH_REGISTRY_FAILED"
AUTH_STORED_COMMAND_INCONSISTENT = "AUTH_STORED_COMMAND_INCONSISTENT"
AUTH_COMMAND_ACCEPTED = "AUTH_COMMAND_ACCEPTED"

_ID_RE = rpe._ID_RE
_NONCE_RE = re.compile(r"[0-9a-f]{32,128}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_HEX_KEY_RE = re.compile(r"[0-9a-f]{64}")
_NONE = "none"   # placeholder id of a verdict without a command (never VERIFIED)


@dataclass(frozen=True)
class HumanMergeCommand:
    """What the human Director signs. Every field is part of the message."""

    format: str
    command_id: str
    nonce: str
    key_id: str
    director_id: int
    operation_id: str
    request_fingerprint: str
    repository: str
    pr_number: int
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    action: str
    merge_method: str
    issued_at: str
    expires_at: str


_COMMAND_FIELDS = tuple(f.name for f in fields(HumanMergeCommand))
_INT_FIELDS = ("director_id", "pr_number")


@dataclass(frozen=True)
class SignedHumanCommand:
    command: HumanMergeCommand
    signature: bytes


@dataclass(frozen=True)
class PinnedDirectorKey:
    """One Ed25519 public key pinned to one Director id on the host."""

    key_id: str
    director_id: int
    public_key: bytes


@dataclass(frozen=True)
class HostAuthorityConfig:
    """Host-provisioned trust configuration. `source` records where the
    host loaded it from; it is a record, not a proof of provisioning."""

    keys: tuple
    allowed_director_ids: tuple
    revoked_key_ids: tuple
    source: str


@dataclass(frozen=True)
class CommandSubmission:
    """Result of one `submit_command`: accepted or refused, codes only."""

    accepted: bool
    command_id: Optional[str]
    reason_codes: tuple


class HostAuthorityRefused(ValueError):
    """Configuration or envelope refused. Carries only stable codes."""

    def __init__(self, reason_codes):
        self.reason_codes = tuple(dict.fromkeys(reason_codes))
        super().__init__(", ".join(self.reason_codes))


class CommandRegistry(Protocol):
    """The durable registry the authority uses (`HostLedger`)."""

    def register_command(self, command: rhl.RegisteredCommand) -> None: ...

    def command_for_operation(self, operation_id: str) -> Optional[rhl.RegisteredCommand]: ...

    def is_command_revoked(self, command_id: str) -> bool: ...

    def revoke_command(self, command_id: str, reason_code: str) -> None: ...


# ---------------------------------------------------------------------------
# Canonical message and strict parsing
# ---------------------------------------------------------------------------

def canonical_command_message(command: HumanMergeCommand) -> bytes:
    """Domain, version and every command field, canonically encoded. This is
    exactly what the Director signs and what the host verifies."""
    payload = {name: getattr(command, name) for name in _COMMAND_FIELDS}
    return SIGNATURE_DOMAIN + b"\n" + json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=True).encode("ascii")


def _unique_pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise HostAuthorityRefused([AUTH_ENVELOPE_MALFORMED])
    return dict(pairs)


def _reject_constant(_name):
    raise HostAuthorityRefused([AUTH_ENVELOPE_MALFORMED])


def _strict_json(raw, limit):
    if type(raw) is not bytes or not raw or len(raw) > limit:
        raise HostAuthorityRefused([AUTH_ENVELOPE_MALFORMED])
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except HostAuthorityRefused:
        raise
    except (ValueError, UnicodeDecodeError):
        raise HostAuthorityRefused([AUTH_ENVELOPE_MALFORMED]) from None


def _command_from_mapping(value) -> HumanMergeCommand:
    if type(value) is not dict or set(value) != set(_COMMAND_FIELDS):
        raise HostAuthorityRefused([AUTH_COMMAND_MALFORMED])
    for name in _COMMAND_FIELDS:
        if type(value[name]) is not (int if name in _INT_FIELDS else str):
            raise HostAuthorityRefused([AUTH_COMMAND_MALFORMED])
    command = HumanMergeCommand(**value)
    if _shape_errors(command):
        raise HostAuthorityRefused([AUTH_COMMAND_MALFORMED])
    return command


def _shape_errors(c: HumanMergeCommand) -> list:
    sha_format = rpg._sha_format(c.head_sha)
    ok = (c.format == COMMAND_FORMAT and _ID_RE.fullmatch(c.command_id) and c.command_id != _NONE
          and _NONCE_RE.fullmatch(c.nonce) and _ID_RE.fullmatch(c.key_id) and rha._int(c.director_id, 1, rha.MAX_ID)
          and _DIGEST_RE.fullmatch(c.operation_id) and _DIGEST_RE.fullmatch(c.request_fingerprint)
          and c.repository == rpg.CANONICAL_REPOSITORY and rha._int(c.pr_number, 1, rpg.MAX_PR_NUMBER)
          and c.base_ref == rpg.BASE_BRANCH and sha_format is not None and rpg._sha_format(c.base_sha) == sha_format
          and type(c.head_ref) is str and 0 < len(c.head_ref) <= 255
          and c.action == rpe.ACTION_MERGE_GITHUB_PR and c.merge_method == rpe.MERGE_METHOD
          and rha._timestamp(c.issued_at) is not None and rha._timestamp(c.expires_at) is not None)
    return [] if ok else [AUTH_COMMAND_MALFORMED]


def parse_command_envelope(raw: bytes) -> SignedHumanCommand:
    """Strict: `{"format", "command", "signature"}` and nothing else, the
    command with exactly its fields and exact types, the signature standard
    base64 of exactly SIGNATURE_BYTES. Raises `HostAuthorityRefused`."""
    document = _strict_json(raw, MAX_ENVELOPE_BYTES)
    if type(document) is not dict or set(document) != {"format", "command", "signature"} \
            or document["format"] != COMMAND_FORMAT or type(document["signature"]) is not str:
        raise HostAuthorityRefused([AUTH_ENVELOPE_MALFORMED])
    command = _command_from_mapping(document["command"])
    try:
        signature = base64.b64decode(document["signature"].encode("ascii"), validate=True)
    except (ValueError, binascii.Error, UnicodeEncodeError):
        raise HostAuthorityRefused([AUTH_ENVELOPE_MALFORMED]) from None
    if len(signature) != SIGNATURE_BYTES:
        raise HostAuthorityRefused([AUTH_ENVELOPE_MALFORMED])
    return SignedHumanCommand(command, signature)


def _command_from_message(message: bytes) -> HumanMergeCommand:
    prefix = SIGNATURE_DOMAIN + b"\n"
    if type(message) is not bytes or not message.startswith(prefix):
        raise HostAuthorityRefused([AUTH_STORED_COMMAND_INCONSISTENT])
    command = _command_from_mapping(_strict_json(message[len(prefix):], MAX_ENVELOPE_BYTES))
    if canonical_command_message(command) != message:
        raise HostAuthorityRefused([AUTH_STORED_COMMAND_INCONSISTENT])
    return command


# ---------------------------------------------------------------------------
# Host configuration
# ---------------------------------------------------------------------------

def _source_trusted(source_path, untrusted_roots) -> Optional[Path]:
    if not isinstance(source_path, (str, Path)) or not str(source_path) or not Path(source_path).is_absolute():
        return None
    resolved = Path(source_path).resolve()
    roots = (REPOSITORY_ROOT, *(Path(r).resolve() for r in untrusted_roots))
    return None if any(rhl._inside(resolved, root) for root in roots) else resolved


def load_authority_config(document: bytes, *, source_path, untrusted_roots=()) -> HostAuthorityConfig:
    """Parses a host configuration document the host read from
    `source_path`, which must be absolute and outside the repository and
    every untrusted root. Exactly the expected keys: a private key, seed or
    any other field is refused. This module never reads the file itself."""
    source = _source_trusted(source_path, tuple(untrusted_roots))
    if source is None:
        raise HostAuthorityRefused([AUTH_CONFIG_SOURCE_UNTRUSTED])
    try:
        data = _strict_json(document, MAX_CONFIG_BYTES)
    except HostAuthorityRefused:
        raise HostAuthorityRefused([AUTH_CONFIG_INVALID]) from None
    expected = {"format", "keys", "allowed_director_ids", "revoked_key_ids"}
    if type(data) is not dict or set(data) != expected or data["format"] != CONFIG_FORMAT \
            or type(data["keys"]) is not list or type(data["allowed_director_ids"]) is not list \
            or type(data["revoked_key_ids"]) is not list:
        raise HostAuthorityRefused([AUTH_CONFIG_INVALID])
    keys = []
    for entry in data["keys"]:
        if type(entry) is not dict or set(entry) != {"key_id", "director_id", "public_key_hex"} \
                or type(entry["public_key_hex"]) is not str or not _HEX_KEY_RE.fullmatch(entry["public_key_hex"]):
            raise HostAuthorityRefused([AUTH_CONFIG_INVALID])
        keys.append(PinnedDirectorKey(entry["key_id"], entry["director_id"], bytes.fromhex(entry["public_key_hex"])))
    config = HostAuthorityConfig(keys=tuple(keys), allowed_director_ids=tuple(data["allowed_director_ids"]),
                                 revoked_key_ids=tuple(data["revoked_key_ids"]), source=str(source))
    errors = config_errors(config)
    if errors:
        raise HostAuthorityRefused(errors)
    return config


def config_errors(config) -> list:
    """Shape of a configuration: at least one key, unique key ids and public
    keys, valid Ed25519 points when the backend is available."""
    if type(config) is not HostAuthorityConfig or type(config.keys) is not tuple or not config.keys \
            or type(config.allowed_director_ids) is not tuple or type(config.revoked_key_ids) is not tuple \
            or type(config.source) is not str:
        return [AUTH_CONFIG_INVALID]
    keys = config.keys
    if not all(type(k) is PinnedDirectorKey and type(k.key_id) is str and _ID_RE.fullmatch(k.key_id)
               and rha._int(k.director_id, 1, rha.MAX_ID) and type(k.public_key) is bytes
               and len(k.public_key) == PUBLIC_KEY_BYTES for k in keys) \
            or len({k.key_id for k in keys}) != len(keys) or len({k.public_key for k in keys}) != len(keys) \
            or not all(rha._int(d, 1, rha.MAX_ID) for d in config.allowed_director_ids) \
            or not all(type(k) is str and _ID_RE.fullmatch(k) for k in config.revoked_key_ids):
        return [AUTH_CONFIG_INVALID]
    if CRYPTO_AVAILABLE:
        try:
            for k in keys:
                _Ed25519PublicKey.from_public_bytes(k.public_key)
        except Exception:  # noqa: BLE001 - an unusable key is a configuration refusal
            return [AUTH_CONFIG_INVALID]
    return []


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------

def _signature_valid(public_key: bytes, signature: bytes, message: bytes) -> bool:
    if not CRYPTO_AVAILABLE:
        return False
    try:
        _Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except Exception:  # noqa: BLE001 - InvalidSignature or any backend failure
        return False
    return True


def _window_error(command, now) -> Optional[str]:
    issued, expires = rha._timestamp(command.issued_at), rha._timestamp(command.expires_at)
    if issued is None or expires is None or expires <= issued or issued > now:
        return AUTH_TIMESTAMP_INVALID
    if expires - issued > timedelta(seconds=rpe.MAX_COMMAND_TTL_SECONDS):
        return AUTH_TTL_TOO_LONG
    return AUTH_COMMAND_EXPIRED if now >= expires else None


class HumanCommandAuthority:
    """Verifies signed human commands against pinned keys and serves the
    executor's `verify_human_command` port from the durable registry."""

    def __init__(self, config: HostAuthorityConfig, registry: CommandRegistry, *, clock):
        errors = config_errors(config)
        if errors or registry is None or not callable(clock):
            raise HostAuthorityRefused(errors or [AUTH_CONFIG_INVALID])
        self.config, self.registry, self._clock = config, registry, clock

    def _now(self):
        try:
            now = self._clock()
        except Exception:  # noqa: BLE001
            return None
        return now if rha._clock_ok(now) else None

    def _key_errors(self, command):
        key = next((k for k in self.config.keys if k.key_id == command.key_id), None)
        if key is None:
            return None, [AUTH_KEY_UNKNOWN]
        if key.key_id in self.config.revoked_key_ids:
            return None, [AUTH_KEY_REVOKED]
        if key.director_id != command.director_id:
            return None, [AUTH_DIRECTOR_MISMATCH]
        if command.director_id not in self.config.allowed_director_ids:
            return None, [AUTH_DIRECTOR_NOT_ALLOWED]
        return key, []

    def submit_command(self, envelope: bytes, request) -> CommandSubmission:
        """Verifies one signed envelope for exactly `request` and registers
        it once. Never raises; refusals carry codes only."""
        try:
            return self._submit(envelope, request)
        except HostAuthorityRefused as exc:
            return CommandSubmission(False, None, exc.reason_codes)
        except Exception:  # noqa: BLE001 - nothing unexpected is ever an acceptance
            return CommandSubmission(False, None, (AUTH_COMMAND_MALFORMED,))

    def _submit(self, envelope, request) -> CommandSubmission:
        if not CRYPTO_AVAILABLE:
            return CommandSubmission(False, None, (AUTH_CRYPTO_UNAVAILABLE,))
        signed = parse_command_envelope(envelope)
        c = signed.command
        key, errors = self._key_errors(c)
        if errors:
            return CommandSubmission(False, None, tuple(errors))
        if not _signature_valid(key.public_key, signed.signature, canonical_command_message(c)):
            return CommandSubmission(False, None, (AUTH_SIGNATURE_INVALID,))
        if type(request) is not rpe.PromotionExecutionRequest or rpe._request_errors(request):
            return CommandSubmission(False, None, (AUTH_REQUEST_INVALID,))
        if (c.operation_id, c.request_fingerprint, c.repository, c.pr_number, c.base_ref, c.base_sha, c.head_ref,
                c.head_sha, c.action, c.merge_method) != (
                request.idempotency_key, request.fingerprint, request.repository, request.pr_number,
                request.base_ref, request.base_sha, request.head_ref, request.head_sha, request.action,
                request.merge_method):
            return CommandSubmission(False, None, (AUTH_BINDING_MISMATCH,))
        now = self._now()
        if now is None:
            return CommandSubmission(False, None, (AUTH_CLOCK_INVALID,))
        problem = _window_error(c, now)
        if problem:
            return CommandSubmission(False, None, (problem,))
        record = rhl.RegisteredCommand(
            command_id=c.command_id, nonce=c.nonce, operation_id=c.operation_id,
            request_fingerprint=c.request_fingerprint, key_id=c.key_id, director_id=c.director_id,
            repository=c.repository, pr_number=c.pr_number, base_sha=c.base_sha, head_sha=c.head_sha,
            action=c.action, issued_at=c.issued_at, expires_at=c.expires_at,
            message=canonical_command_message(c), signature=signed.signature)
        try:
            self.registry.register_command(record)
        except rhl.HostLedgerRefused as exc:
            code = {rhl.LEDGER_COMMAND_DUPLICATE: AUTH_COMMAND_REPLAYED,
                    rhl.LEDGER_COMMAND_REVOKED: AUTH_COMMAND_REVOKED}.get(exc.code, AUTH_REGISTRY_FAILED)
            return CommandSubmission(False, None, (code,))
        return CommandSubmission(True, c.command_id, (AUTH_COMMAND_ACCEPTED,))

    def revoke_command(self, command_id: str, reason_code: str) -> None:
        """Durable revocation through the registry (host side only)."""
        self.registry.revoke_command(command_id, reason_code)

    # HumanCommandPort -----------------------------------------------------
    def verify_human_command(self, operation_id: str, repository: str, pr_number: int, base_sha: str,
                             head_sha: str, action: str) -> rpe.HostCommandVerdict:
        """COMMAND_VERIFIED only for a registered command whose stored bytes
        verify AGAIN under the current pinned key, bound exactly to these
        arguments, unexpired and unrevoked. Never raises."""
        bound = (operation_id, repository, pr_number, base_sha, head_sha, action)
        try:
            return self._verify(*bound)
        except Exception:  # noqa: BLE001 - nothing unexpected is ever a verification
            return _verdict(rpe.COMMAND_REJECTED, *bound)

    def _verify(self, operation_id, repository, pr_number, base_sha, head_sha, action):
        bound = (operation_id, repository, pr_number, base_sha, head_sha, action)
        if not CRYPTO_AVAILABLE:
            return _verdict(rpe.COMMAND_REJECTED, *bound)
        record = self.registry.command_for_operation(operation_id) if type(operation_id) is str else None
        if record is None:
            return _verdict(rpe.COMMAND_ABSENT, *bound)
        try:
            c = _command_from_message(record.message)
        except HostAuthorityRefused:
            return _verdict(rpe.COMMAND_REJECTED, *bound)
        stored = (record.command_id, record.nonce, record.operation_id, record.request_fingerprint, record.key_id,
                  record.director_id, record.repository, record.pr_number, record.base_sha, record.head_sha,
                  record.action, record.issued_at, record.expires_at)
        if stored != (c.command_id, c.nonce, c.operation_id, c.request_fingerprint, c.key_id, c.director_id,
                      c.repository, c.pr_number, c.base_sha, c.head_sha, c.action, c.issued_at, c.expires_at):
            return _verdict(rpe.COMMAND_REJECTED, *bound)
        key, errors = self._key_errors(c)
        if errors:
            return _verdict(rpe.COMMAND_REVOKED if errors == [AUTH_KEY_REVOKED] else rpe.COMMAND_REJECTED, *bound)
        if not _signature_valid(key.public_key, record.signature, record.message):
            return _verdict(rpe.COMMAND_REJECTED, *bound)
        if self.registry.is_command_revoked(c.command_id):
            return _verdict(rpe.COMMAND_REVOKED, *bound)
        if (c.operation_id, c.repository, c.pr_number, c.base_sha, c.head_sha, c.action) != bound \
                or type(pr_number) is not int:
            return _verdict(rpe.COMMAND_REJECTED, *bound)
        now = self._now()
        problem = AUTH_CLOCK_INVALID if now is None else _window_error(c, now)
        if problem == AUTH_COMMAND_EXPIRED:
            return _verdict(rpe.COMMAND_EXPIRED, *bound)
        if problem:
            return _verdict(rpe.COMMAND_REJECTED, *bound)
        return rpe.HostCommandVerdict(
            status=rpe.COMMAND_VERIFIED, command_id=c.command_id, operation_id=c.operation_id, action=c.action,
            repository=c.repository, pr_number=c.pr_number, base_sha=c.base_sha, head_sha=c.head_sha,
            director_id=c.director_id, issued_at=c.issued_at, expires_at=c.expires_at)


def _verdict(status, operation_id, repository, pr_number, base_sha, head_sha, action) -> rpe.HostCommandVerdict:
    """A non-verified verdict: no command identity, no Director, no window."""
    def text(value):
        return value if type(value) is str else ""

    return rpe.HostCommandVerdict(
        status=status, command_id=_NONE, operation_id=text(operation_id), action=text(action),
        repository=text(repository), pr_number=pr_number if type(pr_number) is int else 0, base_sha=text(base_sha),
        head_sha=text(head_sha), director_id=0, issued_at="", expires_at="")
