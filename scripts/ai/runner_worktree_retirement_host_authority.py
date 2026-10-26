"""FCP-4E-02b: cryptographic VERIFICATION of a proposed retirement command (NOT LIVE).

Answers ONE question: "is this envelope a well-formed retirement command,
signed under SIGNATURE_DOMAIN by a key the caller-supplied host
configuration pins for this Director and host, bound exactly to this
internally consistent FCP-4E-02a `RetirementProposal`, inside its time
window?" A positive answer is a cryptographic FACT, NOT a permission, an
approval, an issuance or an attestation of a real host. Every verification
result carries `authorizes_action=False`, `deletion_authorized=False`,
`branch_deletion_authorized=False`, `issued=False`,
`host_identity_authenticated=False`, `queue_scope_attested=False` and
`replay_protection_available=False` (fixed, not constructor arguments), and
`RETIREMENT_AUTHORIZATION_LIVE` / `RETIREMENT_EXECUTION_CAPABLE` are
constant False. This module never mints, signs, persists, issues, consumes
or acts on a command: it contains NO signing code, imports no private-key
API, generates no key, starts no process, calls no Git, opens no ledger,
lease, queue lock or SQLite database and makes no network call.

Command (`RetirementCommand`, format COMMAND_FORMAT)
----------------------------------------------------
Binds the command id, an externally supplied 256-bit hex nonce (its
randomness cannot be proven here), the pinned key id (namespace
`fcp4e02b-retire-key-*`, disjoint from the PR-merge key ids), the Director
id, the host id, the ONE descriptive action RETIRE_SINGLE_WORKTREE_CHECKOUT
(one worktree checkout; it never names or permits a branch deletion), the
proposal, scope and target identity digests, every material target identity
field, the assessment LIMITATIONS and the proposal limitations verbatim, an
empty waiver list and an issued/expires window in strict UTC
(`YYYY-MM-DDTHH:MM:SSZ`) of at most MAX_COMMAND_TTL_SECONDS. The signed
message is SIGNATURE_DOMAIN, a newline and the canonical JSON (sorted keys,
ASCII) of every command field: nothing outside the command is trusted. The
wire envelope is exactly `{"command": {...}, "signature": "<base64>"}`;
duplicate keys, extra claims (`approved`, `permit`, `public_key`,
`execute`, ...), NaN/Infinity, wrong primitive types and oversize documents
are refused, never ignored. The FCP-3B merge domain, formats and key ids
are never accepted here, and a retirement envelope is not a PR-merge one.

Trust configuration (`RetirementHostConfig`, format CONFIG_FORMAT)
------------------------------------------------------------------
The host id, allowed Director ids, pinned key id -> 32-byte Ed25519 PUBLIC
key, revoked key ids and the provenance path the document declares for
itself. `load_retirement_host_config` reads (never writes) one explicit
absolute file outside the repository and every supplied forbidden root and
refuses URIs, traversal, missing files, symlink/junction/hard-link aliases
and POSIX group/world-writable locations when detectable. There is no
default key, no default configuration and no environment lookup. A
configuration is caller-supplied public trust: forbidden roots and file
checks do NOT certify the host identity, Windows ACLs are not inspected,
and the checks are point-in-time (the opened file is re-identified by
device/inode only).

Known residual limitations (VERIFICATION_LIMITATIONS)
-----------------------------------------------------
The caller's clock is not trusted time and never upgrades any flag; the
optional high-water mark is caller-supplied (a durable one is deferred to
FCP-4E-02c). The same envelope verifies again on every call: there is no
replay protection, single use or durable revocation here (02c/02d). Git
state, queue coverage and human approval are not rechecked; a signature
authenticates a key, not human presence. Without the `cryptography`
package (`CRYPTO_AVAILABLE` False) every verification is refused - nothing
falls back to a digest a caller could recompute. Human retirement policy
D-1..D-12 remains pending and is not granted by anything here.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import runner_worktree_retirement as wr
    from scripts.ai import runner_worktree_retirement_authorization as wra
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_worktree_retirement as wr  # type: ignore[no-redef]
    import runner_worktree_retirement_authorization as wra  # type: ignore[no-redef]

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _Ed25519PublicKey
except ImportError:  # host dependency missing: nothing can be verified
    _Ed25519PublicKey = None

RETIREMENT_AUTHORIZATION_LIVE = False
RETIREMENT_EXECUTION_CAPABLE = False

CRYPTO_AVAILABLE = _Ed25519PublicKey is not None
HOST_DEPENDENCY = "cryptography (Ed25519 public-key verification) installed in the isolated host environment"

COMMAND_FORMAT = "fcp4e02b-retirement-command-v1"
CONFIG_FORMAT = "fcp4e02b-host-key-config-v1"
VERIFICATION_SCHEMA = "fcp4e02b-retirement-command-verification-v1"
SIGNATURE_DOMAIN = b"quesada-abogados/fabric/fcp4e02b/worktree-retirement-command/v1"
DOMAIN_SEPARATOR = b"\n"
ACTION_RETIRE_SINGLE_WORKTREE_CHECKOUT = "RETIRE_SINGLE_WORKTREE_CHECKOUT"
MAX_COMMAND_TTL_SECONDS = 300   # provisional D-6 cap for a NEVER-LIVE verifier
MAX_ENVELOPE_BYTES = 32768
MAX_CONFIG_BYTES = 65536
MAX_PINNED_KEYS = 64
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
_SIGNATURE_B64_CHARS = 88
_MAX_TEXT = 4096
_MAX_LIST = 64

# Verification statuses. Neither is a permission.
STATUS_REFUSED = "REFUSED"
STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING = "SIGNATURE_VERIFIED_NON_AUTHORIZING"

VERIFICATION_LIMITATIONS = (
    "SIGNATURE_IS_NOT_PERMISSION",
    "HOST_IDENTITY_NOT_AUTHENTICATED",
    "TRUST_CONFIG_CALLER_SUPPLIED",
    "CALLER_CLOCK_NOT_TRUSTED",
    "NO_REPLAY_PROTECTION",
    "NO_DURABLE_REVOCATION",
    "NONCE_RANDOMNESS_NOT_PROVABLE",
    "GIT_STATE_NOT_RECHECKED",
    "QUEUE_SCOPE_NOT_ATTESTED",
    "HUMAN_PRESENCE_NOT_PROVEN",
    "RETIREMENT_POLICY_PENDING",
)

# Verification refusal codes.
RCV_CRYPTO_UNAVAILABLE = "RCV_CRYPTO_UNAVAILABLE"
RCV_INPUT_INVALID = "RCV_INPUT_INVALID"
RCV_CONFIG_INVALID = "RCV_CONFIG_INVALID"
RCV_PROPOSAL_INVALID = "RCV_PROPOSAL_INVALID"
RCV_PROPOSAL_TAMPERED = "RCV_PROPOSAL_TAMPERED"
RCV_PROPOSAL_SOURCE_MISMATCH = "RCV_PROPOSAL_SOURCE_MISMATCH"
RCV_CLOCK_INVALID = "RCV_CLOCK_INVALID"
RCV_CLOCK_REGRESSION = "RCV_CLOCK_REGRESSION"
RCV_ENVELOPE_MALFORMED = "RCV_ENVELOPE_MALFORMED"
RCV_COMMAND_VERSION_UNSUPPORTED = "RCV_COMMAND_VERSION_UNSUPPORTED"
RCV_COMMAND_MALFORMED = "RCV_COMMAND_MALFORMED"
RCV_NONCE_INVALID = "RCV_NONCE_INVALID"
RCV_SIGNATURE_MALFORMED = "RCV_SIGNATURE_MALFORMED"
RCV_KEY_UNPINNED = "RCV_KEY_UNPINNED"
RCV_KEY_REVOKED = "RCV_KEY_REVOKED"
RCV_DIRECTOR_MISMATCH = "RCV_DIRECTOR_MISMATCH"
RCV_DIRECTOR_NOT_ALLOWED = "RCV_DIRECTOR_NOT_ALLOWED"
RCV_SIGNATURE_INVALID = "RCV_SIGNATURE_INVALID"
RCV_HOST_MISMATCH = "RCV_HOST_MISMATCH"
RCV_ACTION_INVALID = "RCV_ACTION_INVALID"
RCV_LIMITATIONS_ALTERED = "RCV_LIMITATIONS_ALTERED"
RCV_WAIVER_PRESENT = "RCV_WAIVER_PRESENT"
RCV_PROPOSAL_BINDING_MISMATCH = "RCV_PROPOSAL_BINDING_MISMATCH"
RCV_SCOPE_BINDING_MISMATCH = "RCV_SCOPE_BINDING_MISMATCH"
RCV_TARGET_BINDING_MISMATCH = "RCV_TARGET_BINDING_MISMATCH"
RCV_TIMESTAMP_INVALID = "RCV_TIMESTAMP_INVALID"
RCV_TTL_TOO_LONG = "RCV_TTL_TOO_LONG"
RCV_COMMAND_NOT_YET_VALID = "RCV_COMMAND_NOT_YET_VALID"
RCV_COMMAND_EXPIRED = "RCV_COMMAND_EXPIRED"
RCV_INTERNAL_ERROR = "RCV_INTERNAL_ERROR"

VERIFICATION_REFUSAL_CODES = (
    RCV_CRYPTO_UNAVAILABLE, RCV_INPUT_INVALID, RCV_CONFIG_INVALID, RCV_PROPOSAL_INVALID, RCV_PROPOSAL_TAMPERED,
    RCV_PROPOSAL_SOURCE_MISMATCH, RCV_CLOCK_INVALID, RCV_CLOCK_REGRESSION, RCV_ENVELOPE_MALFORMED,
    RCV_COMMAND_VERSION_UNSUPPORTED, RCV_COMMAND_MALFORMED, RCV_NONCE_INVALID, RCV_SIGNATURE_MALFORMED,
    RCV_KEY_UNPINNED, RCV_KEY_REVOKED, RCV_DIRECTOR_MISMATCH, RCV_DIRECTOR_NOT_ALLOWED, RCV_SIGNATURE_INVALID,
    RCV_HOST_MISMATCH, RCV_ACTION_INVALID, RCV_LIMITATIONS_ALTERED, RCV_WAIVER_PRESENT,
    RCV_PROPOSAL_BINDING_MISMATCH, RCV_SCOPE_BINDING_MISMATCH, RCV_TARGET_BINDING_MISMATCH,
    RCV_TIMESTAMP_INVALID, RCV_TTL_TOO_LONG, RCV_COMMAND_NOT_YET_VALID, RCV_COMMAND_EXPIRED, RCV_INTERNAL_ERROR,
)

# Configuration loading refusal codes.
RCV_CONFIG_ROOTS_INVALID = "RCV_CONFIG_ROOTS_INVALID"
RCV_CONFIG_PATH_INVALID = "RCV_CONFIG_PATH_INVALID"
RCV_CONFIG_PATH_FORBIDDEN_ROOT = "RCV_CONFIG_PATH_FORBIDDEN_ROOT"
RCV_CONFIG_PATH_MISSING = "RCV_CONFIG_PATH_MISSING"
RCV_CONFIG_PATH_ALIAS = "RCV_CONFIG_PATH_ALIAS"
RCV_CONFIG_PATH_INSECURE = "RCV_CONFIG_PATH_INSECURE"
RCV_CONFIG_NOT_REGULAR_FILE = "RCV_CONFIG_NOT_REGULAR_FILE"
RCV_CONFIG_OVERSIZE = "RCV_CONFIG_OVERSIZE"
RCV_CONFIG_READ_FAILED = "RCV_CONFIG_READ_FAILED"
RCV_CONFIG_MALFORMED = "RCV_CONFIG_MALFORMED"
RCV_CONFIG_PROVENANCE_MISMATCH = "RCV_CONFIG_PROVENANCE_MISMATCH"

CONFIG_REFUSAL_CODES = (
    RCV_CONFIG_ROOTS_INVALID, RCV_CONFIG_PATH_INVALID, RCV_CONFIG_PATH_FORBIDDEN_ROOT, RCV_CONFIG_PATH_MISSING,
    RCV_CONFIG_PATH_ALIAS, RCV_CONFIG_PATH_INSECURE, RCV_CONFIG_NOT_REGULAR_FILE, RCV_CONFIG_OVERSIZE,
    RCV_CONFIG_READ_FAILED, RCV_CONFIG_MALFORMED, RCV_CONFIG_INVALID, RCV_CONFIG_PROVENANCE_MISMATCH,
)

_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_KEY_ID_RE = re.compile(r"fcp4e02b-retire-key-[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_NONCE_RE = re.compile(r"[0-9a-f]{64}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_HEX_KEY_RE = re.compile(r"[0-9a-f]{64}")
_SHA_RE = {"sha1": re.compile(r"[0-9a-f]{40}"), "sha256": re.compile(r"[0-9a-f]{64}")}
_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_URI_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]+:")
_MIN_NONCE_DISTINCT = 8
_WEAK_PUBLIC_KEYS = (b"\x00" * PUBLIC_KEY_BYTES, b"\x01" + b"\x00" * (PUBLIC_KEY_BYTES - 1))
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class RetirementHostConfigRefused(ValueError):
    """Configuration refused. Carries only a stable code (no path, no content)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RetirementEnvelopeRefused(ValueError):
    """Envelope refused. Carries only a stable code (no field content)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Schemas (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetirementCommand:
    """What the human Director signs. Every field is part of the message."""

    format: str
    command_id: str
    nonce: str
    key_id: str
    director_id: str
    host_id: str
    action: str
    proposal_digest: str
    scope_digest: str
    target_identity_digest: str
    worktree_key: str
    path: str
    worktree_top: str
    git_dir: str
    common_dir: str
    admin_entry: str
    head_ref: str
    head_sha: str
    listed_branch: str
    listed_head: str
    object_format: str
    inventory_record_fingerprint: str
    assessment_fingerprint: str
    limitations: tuple
    proposal_limitations: tuple
    waivers: tuple
    issued_at: str
    expires_at: str


COMMAND_FIELDS = tuple(f.name for f in dataclasses.fields(RetirementCommand))
_LIST_FIELDS = ("limitations", "proposal_limitations", "waivers")
# Target identity fields bound verbatim to `proposal.target` of the same name.
TARGET_BOUND_FIELDS = (
    "worktree_key", "path", "worktree_top", "git_dir", "common_dir", "admin_entry", "head_ref", "head_sha",
    "listed_branch", "listed_head", "object_format", "inventory_record_fingerprint", "assessment_fingerprint",
)


@dataclass(frozen=True)
class SignedRetirementCommand:
    command: RetirementCommand
    signature: bytes


@dataclass(frozen=True)
class PinnedRetirementPublicKey:
    """One Ed25519 PUBLIC key pinned to one Director id. Never a private key."""

    key_id: str
    director_id: str
    public_key: bytes


@dataclass(frozen=True)
class RetirementHostConfig:
    """Caller-supplied public trust configuration. `provenance_path` records
    where it was provisioned; it is a record, not a proof of provisioning."""

    format: str
    host_id: str
    allowed_director_ids: tuple
    keys: tuple
    revoked_key_ids: tuple
    provenance_path: str
    host_identity_authenticated: bool = field(default=False, init=False)


@dataclass(frozen=True)
class RetirementCommandVerification:
    """Outcome of ONE verification. `signature_verified` is a cryptographic
    fact; nothing here is an approval, a permit or an issued command."""

    schema: str
    status: str
    reason_codes: tuple
    signature_verified: bool
    source_records_revalidated: bool
    command_id: Optional[str]
    key_id: Optional[str]
    director_id: Optional[str]
    host_id_label: Optional[str]
    proposal_digest: Optional[str]
    command_message_digest: Optional[str]
    limitations: tuple = field(default=VERIFICATION_LIMITATIONS, init=False)
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)
    branch_deletion_authorized: bool = field(default=False, init=False)
    issued: bool = field(default=False, init=False)
    consumed: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)
    replay_protection_available: bool = field(default=False, init=False)
    human_review_required: bool = field(default=True, init=False)


# ---------------------------------------------------------------------------
# Canonical message and strict parsing
# ---------------------------------------------------------------------------

def canonical_command_message(command: RetirementCommand) -> bytes:
    """Domain, separator and the canonical JSON of every command field. This
    is exactly what the Director signs and what a verifier checks."""
    payload = {}
    for name in COMMAND_FIELDS:
        value = getattr(command, name)
        payload[name] = list(value) if name in _LIST_FIELDS else value
    return SIGNATURE_DOMAIN + DOMAIN_SEPARATOR + json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _unique_pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _Refused(RCV_ENVELOPE_MALFORMED)
    return dict(pairs)


def _reject_constant(_name):
    raise _Refused(RCV_ENVELOPE_MALFORMED)


def _strict_json(raw, limit: int):
    if type(raw) is not bytes or not raw or len(raw) > limit:
        raise _Refused(RCV_ENVELOPE_MALFORMED)
    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except _Refused:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise _Refused(RCV_ENVELOPE_MALFORMED) from None


def _is_text(value, limit: int = _MAX_TEXT) -> bool:
    return (type(value) is str and 0 < len(value) <= limit and value == value.strip() and "\0" not in value)


def _command_from_mapping(value) -> RetirementCommand:
    if type(value) is not dict:
        raise _Refused(RCV_COMMAND_MALFORMED)
    if type(value.get("format")) is str and value["format"] != COMMAND_FORMAT:
        raise _Refused(RCV_COMMAND_VERSION_UNSUPPORTED)
    if set(value) != set(COMMAND_FIELDS):
        raise _Refused(RCV_COMMAND_MALFORMED)
    for name in COMMAND_FIELDS:
        item = value[name]
        if name in _LIST_FIELDS:
            if type(item) is not list or len(item) > _MAX_LIST or not all(_is_text(x, 128) for x in item):
                raise _Refused(RCV_COMMAND_MALFORMED)
        elif type(item) is not str:
            raise _Refused(RCV_COMMAND_MALFORMED)
    command = RetirementCommand(**{n: tuple(value[n]) if n in _LIST_FIELDS else value[n] for n in COMMAND_FIELDS})
    _check_shape(command)
    return command


def _check_shape(c: RetirementCommand) -> None:
    sha_re = _SHA_RE.get(c.object_format)
    ok = (c.format == COMMAND_FORMAT and _LABEL_RE.fullmatch(c.command_id) and _KEY_ID_RE.fullmatch(c.key_id)
          and _LABEL_RE.fullmatch(c.director_id) and _LABEL_RE.fullmatch(c.host_id) and _is_text(c.action, 128)
          and all(_DIGEST_RE.fullmatch(d) for d in (c.proposal_digest, c.scope_digest, c.target_identity_digest))
          and all(_is_text(getattr(c, n)) for n in TARGET_BOUND_FIELDS)
          and sha_re is not None and sha_re.fullmatch(c.head_sha) and sha_re.fullmatch(c.listed_head)
          and _is_text(c.issued_at, 64) and _is_text(c.expires_at, 64))
    if not ok:
        raise _Refused(RCV_COMMAND_MALFORMED)
    if not _NONCE_RE.fullmatch(c.nonce) or len(set(c.nonce)) < _MIN_NONCE_DISTINCT:
        raise _Refused(RCV_NONCE_INVALID)


def _decode_signature(text) -> bytes:
    if type(text) is not str or len(text) != _SIGNATURE_B64_CHARS:
        raise _Refused(RCV_SIGNATURE_MALFORMED)
    try:
        signature = base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, binascii.Error, UnicodeEncodeError):
        raise _Refused(RCV_SIGNATURE_MALFORMED) from None
    # Exact length and the one canonical encoding (no alternative padding bits).
    if len(signature) != SIGNATURE_BYTES or base64.b64encode(signature).decode("ascii") != text:
        raise _Refused(RCV_SIGNATURE_MALFORMED)
    return signature


def parse_retirement_envelope(raw: bytes) -> SignedRetirementCommand:
    """Strict: `{"command", "signature"}` and nothing else, the command with
    exactly its fields and exact types, the signature canonical standard
    base64 of exactly SIGNATURE_BYTES. Parsing verifies NO signature.
    Raises `RetirementEnvelopeRefused` with a stable code."""
    try:
        document = _strict_json(raw, MAX_ENVELOPE_BYTES)
        if type(document) is not dict or set(document) != {"command", "signature"}:
            raise _Refused(RCV_ENVELOPE_MALFORMED)
        command = _command_from_mapping(document["command"])
        return SignedRetirementCommand(command, _decode_signature(document["signature"]))
    except _Refused as exc:
        raise RetirementEnvelopeRefused(exc.code) from None


# ---------------------------------------------------------------------------
# Trust configuration
# ---------------------------------------------------------------------------

def _weak_key(public_key: bytes) -> bool:
    return public_key in _WEAK_PUBLIC_KEYS


def config_errors(config) -> Optional[str]:
    """RCV_CONFIG_INVALID unless `config` is an exact, well-formed public
    trust configuration (unique keys, valid Ed25519 points when the backend
    is available). Shape only: never a proof of where it came from."""
    if type(config) is not RetirementHostConfig or config.format != CONFIG_FORMAT \
            or config.host_identity_authenticated is not False:
        return RCV_CONFIG_INVALID
    keys, directors, revoked = config.keys, config.allowed_director_ids, config.revoked_key_ids
    if type(config.host_id) is not str or not _LABEL_RE.fullmatch(config.host_id) \
            or not _is_text(config.provenance_path) or not os.path.isabs(config.provenance_path) \
            or type(directors) is not tuple or not directors or len(set(directors)) != len(directors) \
            or not all(type(d) is str and _LABEL_RE.fullmatch(d) for d in directors) \
            or type(keys) is not tuple or not keys or len(keys) > MAX_PINNED_KEYS \
            or type(revoked) is not tuple or len(set(revoked)) != len(revoked) \
            or not all(type(k) is str and _KEY_ID_RE.fullmatch(k) for k in revoked):
        return RCV_CONFIG_INVALID
    if not all(type(k) is PinnedRetirementPublicKey and type(k.key_id) is str and _KEY_ID_RE.fullmatch(k.key_id)
               and type(k.director_id) is str and _LABEL_RE.fullmatch(k.director_id)
               and type(k.public_key) is bytes and len(k.public_key) == PUBLIC_KEY_BYTES
               and not _weak_key(k.public_key) for k in keys) \
            or len({k.key_id for k in keys}) != len(keys) or len({k.public_key for k in keys}) != len(keys):
        return RCV_CONFIG_INVALID
    if CRYPTO_AVAILABLE:
        try:
            for k in keys:
                _Ed25519PublicKey.from_public_bytes(k.public_key)
        except Exception:  # noqa: BLE001 - an unusable key is a configuration refusal
            return RCV_CONFIG_INVALID
    return None


def _parse_config(raw: bytes, provenance_path: str) -> RetirementHostConfig:
    try:
        data = _strict_json(raw, MAX_CONFIG_BYTES)
    except _Refused:
        raise RetirementHostConfigRefused(RCV_CONFIG_MALFORMED) from None
    expected = {"format", "host_id", "allowed_director_ids", "keys", "revoked_key_ids", "provenance_path"}
    if type(data) is not dict or set(data) != expected or data["format"] != CONFIG_FORMAT \
            or type(data["keys"]) is not list or type(data["allowed_director_ids"]) is not list \
            or type(data["revoked_key_ids"]) is not list or type(data["provenance_path"]) is not str:
        raise RetirementHostConfigRefused(RCV_CONFIG_INVALID)
    if os.path.normcase(data["provenance_path"]) != os.path.normcase(provenance_path):
        raise RetirementHostConfigRefused(RCV_CONFIG_PROVENANCE_MISMATCH)
    keys = []
    for entry in data["keys"]:
        if type(entry) is not dict or set(entry) != {"key_id", "director_id", "public_key_hex"} \
                or type(entry["public_key_hex"]) is not str or not _HEX_KEY_RE.fullmatch(entry["public_key_hex"]):
            raise RetirementHostConfigRefused(RCV_CONFIG_INVALID)
        keys.append(PinnedRetirementPublicKey(entry["key_id"], entry["director_id"],
                                              bytes.fromhex(entry["public_key_hex"])))
    config = RetirementHostConfig(
        format=data["format"], host_id=data["host_id"], allowed_director_ids=tuple(data["allowed_director_ids"]),
        keys=tuple(keys), revoked_key_ids=tuple(data["revoked_key_ids"]), provenance_path=provenance_path)
    if config_errors(config):
        raise RetirementHostConfigRefused(RCV_CONFIG_INVALID)
    return config


def _components(path: str) -> list:
    return [p for p in re.split(r"[\\/]", path) if p]


def _check_path_text(path) -> str:
    if isinstance(path, Path):
        path = str(path)
    if not _is_text(path) or _URI_RE.match(path) or not os.path.isabs(path):
        raise RetirementHostConfigRefused(RCV_CONFIG_PATH_INVALID)
    if os.name == "nt":
        drive = os.path.splitdrive(path)[0]
        # Drive-letter paths only: no UNC/network, device (\\?\, \\.\) or stream (a:b) paths.
        if not re.fullmatch(r"[A-Za-z]:", drive) or ":" in path[2:]:
            raise RetirementHostConfigRefused(RCV_CONFIG_PATH_INVALID)
    if any(p in (".", "..") for p in _components(path)) or path.endswith(("/", "\\")):
        raise RetirementHostConfigRefused(RCV_CONFIG_PATH_INVALID)
    return os.path.normpath(path)


def _within(child: str, parent: str) -> bool:
    child, parent = os.path.normcase(child), os.path.normcase(parent)
    prefix = parent if parent.endswith(os.sep) else parent + os.sep
    return child == parent or child.startswith(prefix)


def _forbidden_roots(roots) -> tuple:
    if isinstance(roots, (str, bytes, Path)) or not isinstance(roots, (tuple, list)) or not roots:
        raise RetirementHostConfigRefused(RCV_CONFIG_ROOTS_INVALID)
    out = [str(_REPOSITORY_ROOT)]
    for root in roots:
        root = str(root) if isinstance(root, Path) else root
        if not _is_text(root) or not os.path.isabs(root):
            raise RetirementHostConfigRefused(RCV_CONFIG_ROOTS_INVALID)
        out += [os.path.normpath(root), os.path.realpath(root)]
    return tuple(out)


def _is_alias(st) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _mode_insecure(st, *, directory: bool) -> bool:
    """POSIX only: group/world-writable file, world-writable non-sticky
    directory, or a file owned by someone other than this user or root.
    Windows ACLs are not inspected (documented limitation)."""
    if os.name != "posix":
        return False
    mode = st.st_mode
    if directory:
        return bool(mode & stat.S_IWOTH) and not mode & stat.S_ISVTX
    euid = os.geteuid() if hasattr(os, "geteuid") else None
    return bool(mode & (stat.S_IWOTH | stat.S_IWGRP)) or (euid is not None and st.st_uid not in (euid, 0))


def load_retirement_host_config(config_path, *, forbidden_roots) -> RetirementHostConfig:
    """Reads (never writes) ONE explicit, absolute, host-provisioned file
    outside this repository and every forbidden root (repositories,
    worktrees, state, queue, ledger roots: mandatory and non-empty). Raises
    RetirementHostConfigRefused. Passing these checks does NOT authenticate
    the host: the caller chooses the roots and the file."""
    path = _check_path_text(config_path)
    roots = _forbidden_roots(forbidden_roots)
    real = os.path.realpath(path)
    if any(_within(candidate, root) for candidate in (path, real) for root in roots):
        raise RetirementHostConfigRefused(RCV_CONFIG_PATH_FORBIDDEN_ROOT)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise RetirementHostConfigRefused(RCV_CONFIG_PATH_MISSING) from None
    except OSError:
        raise RetirementHostConfigRefused(RCV_CONFIG_READ_FAILED) from None
    if _is_alias(st) or os.path.normcase(real) != os.path.normcase(path):
        raise RetirementHostConfigRefused(RCV_CONFIG_PATH_ALIAS)
    if not stat.S_ISREG(st.st_mode):
        raise RetirementHostConfigRefused(RCV_CONFIG_NOT_REGULAR_FILE)
    if st.st_nlink != 1:
        raise RetirementHostConfigRefused(RCV_CONFIG_PATH_ALIAS)
    if st.st_size > MAX_CONFIG_BYTES:
        raise RetirementHostConfigRefused(RCV_CONFIG_OVERSIZE)
    if _mode_insecure(st, directory=False):
        raise RetirementHostConfigRefused(RCV_CONFIG_PATH_INSECURE)
    parent = os.path.dirname(path)
    while True:
        try:
            pst = os.lstat(parent)
        except OSError:
            raise RetirementHostConfigRefused(RCV_CONFIG_READ_FAILED) from None
        if _is_alias(pst):
            raise RetirementHostConfigRefused(RCV_CONFIG_PATH_ALIAS)
        if _mode_insecure(pst, directory=True):
            raise RetirementHostConfigRefused(RCV_CONFIG_PATH_INSECURE)
        above = os.path.dirname(parent)
        if above == parent:
            break
        parent = above
    raw = _read_exact(path, st)
    return _parse_config(raw, path)


def _read_exact(path: str, st) -> bytes:
    """Read-only open; the opened file must be the same file object that was
    checked (device/inode), a regular file, and at most MAX_CONFIG_BYTES."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise RetirementHostConfigRefused(RCV_CONFIG_READ_FAILED) from None
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino) or not stat.S_ISREG(fst.st_mode):
            raise RetirementHostConfigRefused(RCV_CONFIG_PATH_ALIAS)
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 8192)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_CONFIG_BYTES:
                raise RetirementHostConfigRefused(RCV_CONFIG_OVERSIZE)
            chunks.append(chunk)
    except OSError:
        raise RetirementHostConfigRefused(RCV_CONFIG_READ_FAILED) from None
    finally:
        os.close(fd)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _utc_now(value) -> Optional[datetime]:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        return None
    return value


def _timestamp(value) -> Optional[datetime]:
    """UTC instant of a strict `YYYY-MM-DDTHH:MM:SSZ` string, else None."""
    if type(value) is not str or not _TIMESTAMP_RE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _check_proposal(proposal) -> None:
    """The complete FCP-4E-02a proposal, rechecked: exact types and schemas,
    fixed safety flags, CANDIDATE classification, verbatim limitations and
    all three digests recomputed."""
    if type(proposal) is not wra.RetirementProposal or type(proposal.target) is not wra.RetirementTargetIdentity \
            or type(proposal.scope) is not wra.RetirementScope:
        raise _Refused(RCV_PROPOSAL_INVALID)
    p, t, s = proposal, proposal.target, proposal.scope
    if (p.schema, t.schema, s.schema) != (wra.PROPOSAL_SCHEMA, wra.TARGET_SCHEMA, wra.SCOPE_SCHEMA):
        raise _Refused(RCV_PROPOSAL_INVALID)
    if (p.human_review_required is not True or p.authorizes_action is not False
            or p.deletion_authorized is not False or p.human_command_present is not False or p.issued is not False
            or p.host_identity_authenticated is not False or p.queue_scope_attested is not False
            or t.file_object_id is not None or t.file_object_id_verified is not False
            or t.host_identity_authenticated is not False or s.queue_roots_complete_claim_verified is not False
            or s.queue_scope_attested is not False):
        raise _Refused(RCV_PROPOSAL_INVALID)
    if p.assessment_classification != wr.CANDIDATE_FOR_HUMAN_REVIEW:
        raise _Refused(RCV_PROPOSAL_INVALID)
    try:
        intact = (t.identity_digest == wra.identity_digest(t) and s.scope_digest == wra.scope_digest(s)
                  and p.proposal_digest == wra.proposal_digest(p))
    except (TypeError, ValueError):
        intact = False
    if not intact:
        raise _Refused(RCV_PROPOSAL_TAMPERED)
    if p.limitations != wr.LIMITATIONS or p.proposal_limitations != wra.PROPOSAL_LIMITATIONS:
        raise _Refused(RCV_LIMITATIONS_ALTERED)


def _signature_valid(public_key: bytes, signature: bytes, message: bytes) -> bool:
    if not CRYPTO_AVAILABLE:
        return False
    try:
        _Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except Exception:  # noqa: BLE001 - InvalidSignature or any backend failure
        return False
    return True


class _State:
    def __init__(self):
        self.signature_verified = False
        self.source_records_revalidated = False
        self.command = None
        self.message_digest = None
        self.proposal_digest = None


def verify_retirement_command(envelope, *, config, proposal, now, trusted_high_water_mark=None,
                              report=None, inventory_record=None) -> RetirementCommandVerification:
    """Verifies ONE envelope against the caller-supplied public trust
    `config`, the complete FCP-4E-02a `proposal` (and, when BOTH are given,
    its source `report` and `inventory_record`) and the caller's UTC `now`.
    Never raises. The result never authorizes, issues or consumes anything,
    and the same envelope verifies again: nothing here prevents replay."""
    state = _State()
    try:
        _verify(state, envelope, config, proposal, now, trusted_high_water_mark, report, inventory_record)
    except _Refused as exc:
        return _result(state, exc.code)
    except Exception:  # noqa: BLE001 - nothing unexpected is ever a verification
        return _result(state, RCV_INTERNAL_ERROR)
    return _result(state, None)


def _result(state: _State, code: Optional[str]) -> RetirementCommandVerification:
    c = state.command if state.signature_verified else None
    return RetirementCommandVerification(
        schema=VERIFICATION_SCHEMA,
        status=STATUS_REFUSED if code else STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING,
        reason_codes=(code,) if code else (),
        signature_verified=state.signature_verified,
        source_records_revalidated=state.source_records_revalidated,
        command_id=c.command_id if c else None, key_id=c.key_id if c else None,
        director_id=c.director_id if c else None, host_id_label=c.host_id if c else None,
        proposal_digest=state.proposal_digest, command_message_digest=state.message_digest if c else None,
    )


def _verify(state, envelope, config, proposal, now, high_water_mark, report, inventory_record) -> None:
    if not CRYPTO_AVAILABLE:
        raise _Refused(RCV_CRYPTO_UNAVAILABLE)
    if type(envelope) is not bytes or (report is None) != (inventory_record is None):
        raise _Refused(RCV_INPUT_INVALID)
    if config_errors(config):
        raise _Refused(RCV_CONFIG_INVALID)
    _check_proposal(proposal)
    state.proposal_digest = proposal.proposal_digest
    if report is not None:
        if wra.validate_proposal_against_report(proposal, report, inventory_record):
            raise _Refused(RCV_PROPOSAL_SOURCE_MISMATCH)
        state.source_records_revalidated = True
    if proposal.target.host_id_label != config.host_id:
        raise _Refused(RCV_HOST_MISMATCH)
    now = _utc_now(now)
    if now is None:
        raise _Refused(RCV_CLOCK_INVALID)
    if high_water_mark is not None:
        mark = _utc_now(high_water_mark)
        if mark is None:
            raise _Refused(RCV_CLOCK_INVALID)
        if now < mark:
            raise _Refused(RCV_CLOCK_REGRESSION)

    try:
        signed = parse_retirement_envelope(envelope)
    except RetirementEnvelopeRefused as exc:
        raise _Refused(exc.code) from None
    c = signed.command
    key = next((k for k in config.keys if k.key_id == c.key_id), None)
    if key is None:
        raise _Refused(RCV_KEY_UNPINNED)
    if key.key_id in config.revoked_key_ids:
        raise _Refused(RCV_KEY_REVOKED)
    if key.director_id != c.director_id:
        raise _Refused(RCV_DIRECTOR_MISMATCH)
    if c.director_id not in config.allowed_director_ids:
        raise _Refused(RCV_DIRECTOR_NOT_ALLOWED)
    message = canonical_command_message(c)
    if not _signature_valid(key.public_key, signed.signature, message):
        raise _Refused(RCV_SIGNATURE_INVALID)
    state.signature_verified = True
    state.command = c
    state.message_digest = hashlib.sha256(message).hexdigest()

    if c.host_id != config.host_id:
        raise _Refused(RCV_HOST_MISMATCH)
    if c.action != ACTION_RETIRE_SINGLE_WORKTREE_CHECKOUT:
        raise _Refused(RCV_ACTION_INVALID)
    if c.limitations != wr.LIMITATIONS or c.proposal_limitations != wra.PROPOSAL_LIMITATIONS:
        raise _Refused(RCV_LIMITATIONS_ALTERED)
    if c.waivers != ():
        raise _Refused(RCV_WAIVER_PRESENT)
    if c.proposal_digest != proposal.proposal_digest:
        raise _Refused(RCV_PROPOSAL_BINDING_MISMATCH)
    if c.scope_digest != proposal.scope.scope_digest:
        raise _Refused(RCV_SCOPE_BINDING_MISMATCH)
    target = proposal.target
    if c.target_identity_digest != target.identity_digest \
            or any(getattr(c, name) != getattr(target, name) for name in TARGET_BOUND_FIELDS):
        raise _Refused(RCV_TARGET_BINDING_MISMATCH)

    issued, expires = _timestamp(c.issued_at), _timestamp(c.expires_at)
    if issued is None or expires is None or expires <= issued:
        raise _Refused(RCV_TIMESTAMP_INVALID)
    if expires - issued > timedelta(seconds=MAX_COMMAND_TTL_SECONDS):
        raise _Refused(RCV_TTL_TOO_LONG)
    if issued > now:
        raise _Refused(RCV_COMMAND_NOT_YET_VALID)
    if now >= expires:
        raise _Refused(RCV_COMMAND_EXPIRED)
