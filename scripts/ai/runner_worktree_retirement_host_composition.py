"""FCP-4E-02d: NON-LIVE composition of retirement evidence (dry run, NOT LIVE).

Answers ONE question, without changing anything: "do the merged,
independent FCP-4E-02a/02b/02c layers, each re-run here, agree about ONE
proposed worktree retirement command, and does a structurally strict queue
scope manifest cover every queue root the supplied FCP-4D report can
derive?" A positive answer, DRY_RUN_EVIDENCE_CONSISTENT, is an
informational diagnostic, NOT a permission, an approval, an issuance or an
attestation of a real host. Every result carries `authorizes_action=False`,
`deletion_authorized=False`, `branch_deletion_authorized=False`,
`issued=False`, `consumed=False`, `host_identity_authenticated=False`,
`queue_scope_attested=False`, `clock_attested=False`,
`external_queues_excluded=False`, `fresh_host_reassessment_performed=False`
and `source_records_host_verified=False` (fixed, not constructor
arguments), and `RETIREMENT_AUTHORIZATION_LIVE` /
`RETIREMENT_EXECUTION_CAPABLE` are constant False. There is no issuer: no
code path here issues, reserves, consumes or records anything, and
`compose_live` only raises NOT_LIVE without looking at its arguments, the
host or the filesystem. This module starts no process, calls no Git, removes
no file or worktree, takes no DirLease or QueueLock, makes no network call,
signs nothing, generates no key and never calls a ledger writer.

Composition (nothing is re-implemented)
---------------------------------------
* 02a: the real pure `validate_proposal_against_report` re-derives the
  proposal from the caller's report and inventory record (BLOCKED,
  INSUFFICIENT_EVIDENCE, REVIEW_REQUIRED, unknown, tampered or ambiguous
  sources stay refused; nothing is ever upgraded to a CANDIDATE).
* 02b: the real `verify_retirement_command` checks the RAW signed envelope
  against the caller's pinned configuration, the proposal, its sources, the
  caller's clock and the durable 02c high-water mark. A verification result
  or a `signature_verified` value is never accepted as an input.
* 02c: the ledger is opened ONLY with `open_existing` (read-only; a missing
  file is refused and never created) and read with `get_command`,
  `is_revoked`, `audit_trail` and `clock_high_water_mark`. Missing,
  revoked, mismatched (command id, nonce, message digest, proposal, scope,
  target, host label, window) or ambiguous evidence, an unreadable,
  corrupt, foreign or interrupted ledger and a clock behind the mark are
  refused. Nothing is recorded or duplicated.

Queue scope manifest (`QueueScopeManifest`, format MANIFEST_FORMAT)
-------------------------------------------------------------------
An Ed25519-signed (separate domain MANIFEST_SIGNATURE_DOMAIN, key ids
`fcp4e02d-queue-key-*`, caller-pinned `QueueManifestTrustConfig`) document
binding a host label, the canonical common dir, the proposal's report
content and scope digests, a window of at most MAX_MANIFEST_TTL_SECONDS and
canonical, strictly sorted, distinct queue roots, each with its declared
source: the default `<worktree>/runtime/claude_runner/queue` of a named
registered worktree, or an explicitly declared override. It must state
`acknowledged_external_queues_unprovable=true`. Unknown fields, forged
attestation claims, duplicate keys, wrong types, non-canonical path forms,
bad signatures and stale windows are refused, never ignored. Its best
outcome is STRUCTURE_VERIFIED_NOT_ATTESTED: a signature authenticates a
pinned key, and a signed completeness claim is NOT evidence that every
queue was inventoried. Against the report: every registered worktree needs
its default root declared; every non-target default and every override must
be a root the assessment actually read; every read root must be declared.
The target's own default queue can never be a read root (02a refuses roots
overlapping the target) and is only inferred from its CANDIDATE
cleanliness facts, which are caller-supplied.

Known residual limitations (COMPOSITION_LIMITATIONS)
----------------------------------------------------
The host id, configurations, report, record, manifest, clock and ledger
are caller-supplied: comparing them proves internal consistency only and
never authenticates the host or attests time or queue scope. External,
remote and cross-machine queues are not provable. No fresh FCP-4D/DirLease
re-assessment is performed (the assessor rewrites lease diagnostic bytes
and its Git calls have no timeout), and nothing here can switch it on. A
consistent composition can be repeated: it is not single use. Human
retirement policy D-1..D-12 remains pending and is not granted by anything
here; issuance and consumption (FCP-4F) do not exist in this module.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import runner_worktree_retirement_authorization as wra
    from scripts.ai import runner_worktree_retirement_host_authority as rha
    from scripts.ai import runner_worktree_retirement_host_ledger as rlg
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_worktree_retirement_authorization as wra  # type: ignore[no-redef]
    import runner_worktree_retirement_host_authority as rha  # type: ignore[no-redef]
    import runner_worktree_retirement_host_ledger as rlg  # type: ignore[no-redef]

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _Ed25519PublicKey
except ImportError:  # host dependency missing: nothing can be verified
    _Ed25519PublicKey = None

RETIREMENT_AUTHORIZATION_LIVE = False
RETIREMENT_EXECUTION_CAPABLE = False

CRYPTO_AVAILABLE = _Ed25519PublicKey is not None

MANIFEST_FORMAT = "fcp4e02d-queue-scope-manifest-v1"
MANIFEST_TRUST_FORMAT = "fcp4e02d-queue-manifest-key-config-v1"
MANIFEST_VERIFICATION_SCHEMA = "fcp4e02d-queue-scope-manifest-verification-v1"
COMPOSITION_SCHEMA = "fcp4e02d-retirement-evidence-composition-v1"
MANIFEST_SIGNATURE_DOMAIN = b"quesada-abogados/fabric/fcp4e02d/queue-scope-manifest/v1"
DOMAIN_SEPARATOR = b"\n"
MAX_MANIFEST_TTL_SECONDS = 300
MAX_MANIFEST_BYTES = 65536
MAX_MANIFEST_ROOTS = 64
MAX_PINNED_KEYS = 16
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
_SIGNATURE_B64_CHARS = 88

# Same layout as claude_queue.DEFAULT_QUEUE_SUBDIR (checked by the tests).
DEFAULT_QUEUE_SUBDIR_PARTS = ("runtime", "claude_runner", "queue")

SOURCE_REGISTERED_WORKTREE_DEFAULT = "REGISTERED_WORKTREE_DEFAULT_QUEUE"
SOURCE_DECLARED_OVERRIDE = "DECLARED_QUEUE_ROOT_OVERRIDE"
ROOT_SOURCES = (SOURCE_REGISTERED_WORKTREE_DEFAULT, SOURCE_DECLARED_OVERRIDE)

# Statuses. None of them is a permission.
STATUS_REFUSED = "REFUSED"
STATUS_STRUCTURE_VERIFIED_NOT_ATTESTED = "STRUCTURE_VERIFIED_NOT_ATTESTED"
STATUS_DRY_RUN_EVIDENCE_CONSISTENT = "DRY_RUN_EVIDENCE_CONSISTENT"
NOT_LIVE = "NOT_LIVE"

MANIFEST_FIELDS = (
    "format", "manifest_id", "key_id", "signer_id", "host_id", "common_dir", "report_content_digest",
    "scope_digest", "issued_at", "expires_at", "roots", "host_claims_roots_complete",
    "acknowledged_external_queues_unprovable",
)
ROOT_FIELDS = ("root", "source", "worktree_key")
# Claims nothing in a manifest can make; their presence is a forgery, not noise.
FORGED_CLAIM_FIELDS = frozenset((
    "attested", "host_attested", "queue_scope_attested", "host_identity_authenticated", "clock_attested",
    "external_queues_excluded", "queue_roots_complete_verified", "completeness_established", "authorizes_action",
    "deletion_authorized", "approved", "permit", "issued",
))

COMPOSITION_LIMITATIONS = (
    "DRY_RUN_COMPOSITION_IS_NOT_PERMISSION",
    "NO_ISSUANCE_OR_CONSUMPTION",
    "HOST_ID_IS_A_LABEL",
    "HOST_IDENTITY_NOT_AUTHENTICATED",
    "QUEUE_SCOPE_NOT_ATTESTED",
    "SIGNED_MANIFEST_IS_NOT_QUEUE_COMPLETENESS",
    "EXTERNAL_QUEUES_NOT_PROVABLE",
    "TARGET_LOCAL_QUEUE_INFERRED_FROM_CALLER_CLEANLINESS_FACTS",
    "CALLER_CLOCK_NOT_TRUSTED",
    "HIGH_WATER_MARK_NOT_ATTESTED",
    "SOURCE_RECORDS_CALLER_SUPPLIED",
    "CALLER_CRAFTED_CANDIDATE_INDISTINGUISHABLE",
    "FRESH_HOST_REASSESSMENT_NOT_PERFORMED",
    "GIT_STATE_NOT_RECHECKED",
    "PATH_ALIASES_NOT_RESOLVED",
    "REPEATED_EVALUATION_NOT_SINGLE_USE",
    "SIGNATURE_IS_NOT_HUMAN_PRESENCE",
    "RETIREMENT_POLICY_PENDING",
    "LIVE_ACTIVATION_BLOCKED",
)

# What stands between ANY result of this module and a retirement. Fixed:
# nothing here can establish or clear one of them.
BLOCKING_UNCERTAINTIES = (
    "QUEUE_SCOPE_NOT_ATTESTED",
    "EXTERNAL_QUEUES_NOT_PROVABLE",
    "HOST_IDENTITY_NOT_AUTHENTICATED",
    "CLOCK_NOT_ATTESTED",
    "FRESH_HOST_REASSESSMENT_NOT_PERFORMED",
    "HUMAN_RETIREMENT_POLICY_PENDING",
    "LIVE_ACTIVATION_BLOCKED",
)
LIVE_ACTIVATION_BLOCKER = "FCP4E02D_NON_LIVE_PERMANENT"

# Manifest refusal codes.
MQS_CRYPTO_UNAVAILABLE = "MQS_CRYPTO_UNAVAILABLE"
MQS_TRUST_INVALID = "MQS_TRUST_INVALID"
MQS_CLOCK_INVALID = "MQS_CLOCK_INVALID"
MQS_MALFORMED = "MQS_MALFORMED"
MQS_UNKNOWN_FIELD = "MQS_UNKNOWN_FIELD"
MQS_FORGED_CLAIM = "MQS_FORGED_CLAIM"
MQS_VERSION_UNSUPPORTED = "MQS_VERSION_UNSUPPORTED"
MQS_SIGNATURE_MALFORMED = "MQS_SIGNATURE_MALFORMED"
MQS_KEY_UNPINNED = "MQS_KEY_UNPINNED"
MQS_KEY_REVOKED = "MQS_KEY_REVOKED"
MQS_SIGNER_MISMATCH = "MQS_SIGNER_MISMATCH"
MQS_SIGNER_NOT_ALLOWED = "MQS_SIGNER_NOT_ALLOWED"
MQS_SIGNATURE_INVALID = "MQS_SIGNATURE_INVALID"
MQS_HOST_MISMATCH = "MQS_HOST_MISMATCH"
MQS_TIMESTAMP_INVALID = "MQS_TIMESTAMP_INVALID"
MQS_TTL_TOO_LONG = "MQS_TTL_TOO_LONG"
MQS_NOT_YET_VALID = "MQS_NOT_YET_VALID"
MQS_EXPIRED = "MQS_EXPIRED"
MQS_PATH_NOT_CANONICAL = "MQS_PATH_NOT_CANONICAL"
MQS_ROOTS_NOT_SORTED = "MQS_ROOTS_NOT_SORTED"
MQS_DUPLICATE_ROOT = "MQS_DUPLICATE_ROOT"
MQS_SOURCE_UNKNOWN = "MQS_SOURCE_UNKNOWN"
MQS_CONTRADICTORY = "MQS_CONTRADICTORY"
MQS_INTERNAL_ERROR = "MQS_INTERNAL_ERROR"

MANIFEST_REFUSAL_CODES = (
    MQS_CRYPTO_UNAVAILABLE, MQS_TRUST_INVALID, MQS_CLOCK_INVALID, MQS_MALFORMED, MQS_UNKNOWN_FIELD,
    MQS_FORGED_CLAIM, MQS_VERSION_UNSUPPORTED, MQS_SIGNATURE_MALFORMED, MQS_KEY_UNPINNED, MQS_KEY_REVOKED,
    MQS_SIGNER_MISMATCH, MQS_SIGNER_NOT_ALLOWED, MQS_SIGNATURE_INVALID, MQS_HOST_MISMATCH, MQS_TIMESTAMP_INVALID,
    MQS_TTL_TOO_LONG, MQS_NOT_YET_VALID, MQS_EXPIRED, MQS_PATH_NOT_CANONICAL, MQS_ROOTS_NOT_SORTED,
    MQS_DUPLICATE_ROOT, MQS_SOURCE_UNKNOWN, MQS_CONTRADICTORY, MQS_INTERNAL_ERROR,
)

# Composition reason codes.
CMP_ARGUMENT_INVALID = "CMP_ARGUMENT_INVALID"
CMP_CLOCK_INVALID = "CMP_CLOCK_INVALID"
CMP_CRYPTO_UNAVAILABLE = "CMP_CRYPTO_UNAVAILABLE"
CMP_CONFIG_INVALID = "CMP_CONFIG_INVALID"
CMP_PROPOSAL_SOURCE_INVALID = "CMP_PROPOSAL_SOURCE_INVALID"
CMP_COMMAND_NOT_VERIFIED = "CMP_COMMAND_NOT_VERIFIED"
CMP_LEDGER_UNAVAILABLE = "CMP_LEDGER_UNAVAILABLE"
CMP_CLOCK_ROLLBACK = "CMP_CLOCK_ROLLBACK"
CMP_LEDGER_EVIDENCE_MISSING = "CMP_LEDGER_EVIDENCE_MISSING"
CMP_LEDGER_COMMAND_REVOKED = "CMP_LEDGER_COMMAND_REVOKED"
CMP_LEDGER_NONCE_MISMATCH = "CMP_LEDGER_NONCE_MISMATCH"
CMP_LEDGER_DIGEST_MISMATCH = "CMP_LEDGER_DIGEST_MISMATCH"
CMP_LEDGER_EVIDENCE_MISMATCH = "CMP_LEDGER_EVIDENCE_MISMATCH"
CMP_LEDGER_AMBIGUOUS = "CMP_LEDGER_AMBIGUOUS"
CMP_MANIFEST_REFUSED = "CMP_MANIFEST_REFUSED"
CMP_MANIFEST_BINDING_MISMATCH = "CMP_MANIFEST_BINDING_MISMATCH"
CMP_SCOPE_NOT_EVALUATED = "CMP_SCOPE_NOT_EVALUATED"
CMP_SCOPE_REGISTRY_INCONSISTENT = "CMP_SCOPE_REGISTRY_INCONSISTENT"
CMP_SCOPE_DEFAULT_ROOT_MISSING = "CMP_SCOPE_DEFAULT_ROOT_MISSING"
CMP_SCOPE_UNKNOWN_WORKTREE = "CMP_SCOPE_UNKNOWN_WORKTREE"
CMP_SCOPE_ROOT_SOURCE_MISMATCH = "CMP_SCOPE_ROOT_SOURCE_MISMATCH"
CMP_SCOPE_DECLARED_ROOT_NOT_READ = "CMP_SCOPE_DECLARED_ROOT_NOT_READ"
CMP_SCOPE_UNDECLARED_ROOT = "CMP_SCOPE_UNDECLARED_ROOT"
CMP_SCOPE_DEFAULT_ROOT_NOT_READ = "CMP_SCOPE_DEFAULT_ROOT_NOT_READ"
CMP_SCOPE_TARGET_QUEUE_UNPROVEN = "CMP_SCOPE_TARGET_QUEUE_UNPROVEN"
CMP_SCOPE_DECLARED_INCOMPLETE = "CMP_SCOPE_DECLARED_INCOMPLETE"
CMP_INTERNAL_ERROR = "CMP_INTERNAL_ERROR"

COMPOSITION_REASON_CODES = (
    CMP_ARGUMENT_INVALID, CMP_CLOCK_INVALID, CMP_CRYPTO_UNAVAILABLE, CMP_CONFIG_INVALID,
    CMP_PROPOSAL_SOURCE_INVALID, CMP_COMMAND_NOT_VERIFIED, CMP_LEDGER_UNAVAILABLE, CMP_CLOCK_ROLLBACK,
    CMP_LEDGER_EVIDENCE_MISSING, CMP_LEDGER_COMMAND_REVOKED, CMP_LEDGER_NONCE_MISMATCH, CMP_LEDGER_DIGEST_MISMATCH,
    CMP_LEDGER_EVIDENCE_MISMATCH, CMP_LEDGER_AMBIGUOUS, CMP_MANIFEST_REFUSED, CMP_MANIFEST_BINDING_MISMATCH,
    CMP_SCOPE_NOT_EVALUATED, CMP_SCOPE_REGISTRY_INCONSISTENT, CMP_SCOPE_DEFAULT_ROOT_MISSING,
    CMP_SCOPE_UNKNOWN_WORKTREE, CMP_SCOPE_ROOT_SOURCE_MISMATCH, CMP_SCOPE_DECLARED_ROOT_NOT_READ,
    CMP_SCOPE_UNDECLARED_ROOT, CMP_SCOPE_DEFAULT_ROOT_NOT_READ, CMP_SCOPE_TARGET_QUEUE_UNPROVEN,
    CMP_SCOPE_DECLARED_INCOMPLETE, CMP_INTERNAL_ERROR,
)

_KEY_ID_RE = re.compile(r"fcp4e02d-queue-key-[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_WEAK_PUBLIC_KEYS = (b"\x00" * PUBLIC_KEY_BYTES, b"\x01" + b"\x00" * (PUBLIC_KEY_BYTES - 1))
_EVIDENCE_FLAGS = (("authorizes_action", False), ("deletion_authorized", False),
                   ("branch_deletion_authorized", False), ("issued", False), ("consumed", False),
                   ("host_identity_authenticated", False), ("queue_scope_attested", False))
_EVIDENCE_STATES = (rlg.RECORD_STATE_RECORDED_NON_AUTHORIZING, rlg.RECORD_STATE_REVOKED)


class RetirementCompositionNotLive(RuntimeError):
    """Raised by `compose_live`, always. Carries only the stable code."""

    def __init__(self):
        super().__init__(NOT_LIVE)
        self.code = NOT_LIVE


class _Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Schemas (immutable, never authorizing)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QueueRootDeclaration:
    """One declared queue root and where the declaration says it comes from."""

    root: str
    source: str
    worktree_key: Optional[str]


@dataclass(frozen=True)
class QueueScopeManifest:
    """A caller-supplied declaration of queue roots. Even when signed and
    structurally valid it establishes neither completeness nor the host."""

    format: str
    manifest_id: str
    key_id: str
    signer_id: str
    host_id: str
    common_dir: str
    report_content_digest: str
    scope_digest: str
    issued_at: str
    expires_at: str
    roots: tuple
    host_claims_roots_complete: bool
    acknowledged_external_queues_unprovable: bool = field(default=True, init=False)
    completeness_established: bool = field(default=False, init=False)
    external_queues_excluded: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)


@dataclass(frozen=True)
class PinnedQueueManifestKey:
    """One Ed25519 PUBLIC key pinned to one manifest signer id."""

    key_id: str
    signer_id: str
    public_key: bytes


@dataclass(frozen=True)
class QueueManifestTrustConfig:
    """Caller-supplied public trust for manifests. Not a host attestation."""

    format: str
    host_id: str
    allowed_signer_ids: tuple
    keys: tuple
    revoked_key_ids: tuple
    host_identity_authenticated: bool = field(default=False, init=False)


@dataclass(frozen=True)
class QueueScopeManifestVerification:
    """Outcome of ONE manifest check. The best status is
    STRUCTURE_VERIFIED_NOT_ATTESTED: never completeness, never the host."""

    schema: str
    status: str
    reason_codes: tuple
    signature_verified: bool
    manifest_digest: Optional[str]
    manifest: Optional[QueueScopeManifest]
    completeness_established: bool = field(default=False, init=False)
    external_queues_excluded: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    clock_attested: bool = field(default=False, init=False)
    authorizes_action: bool = field(default=False, init=False)


@dataclass(frozen=True)
class RetirementEvidenceComposition:
    """Outcome of ONE dry-run composition: stable reason codes per layer and
    the bindings that agreed. Informational only; it enables nothing."""

    schema: str
    status: str
    reason_codes: tuple
    proposal_findings: tuple
    command_verification_codes: tuple
    ledger_codes: tuple
    manifest_codes: tuple
    signature_verified: bool
    source_records_revalidated: bool
    ledger_evidence_present: bool
    ledger_record_state: Optional[str]
    ledger_clock_high_water_mark: Optional[str]
    manifest_status: Optional[str]
    manifest_signature_verified: bool
    manifest_digest: Optional[str]
    command_id: Optional[str]
    nonce: Optional[str]
    command_message_digest: Optional[str]
    proposal_digest: Optional[str]
    scope_digest: Optional[str]
    target_identity_digest: Optional[str]
    host_id_label: Optional[str]
    limitations: tuple = field(default=COMPOSITION_LIMITATIONS, init=False)
    blocking_uncertainties: tuple = field(default=BLOCKING_UNCERTAINTIES, init=False)
    live_activation_blocker: str = field(default=LIVE_ACTIVATION_BLOCKER, init=False)
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)
    branch_deletion_authorized: bool = field(default=False, init=False)
    issued: bool = field(default=False, init=False)
    consumed: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)
    clock_attested: bool = field(default=False, init=False)
    external_queues_excluded: bool = field(default=False, init=False)
    fresh_host_reassessment_performed: bool = field(default=False, init=False)
    source_records_host_verified: bool = field(default=False, init=False)
    single_use_enforced: bool = field(default=False, init=False)
    human_review_required: bool = field(default=True, init=False)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _exact_utc(value) -> Optional[datetime]:
    """The caller's clock: an exact UTC datetime in a plausible range."""
    if type(value) is not datetime or value.tzinfo is not timezone.utc:
        return None
    if not rlg.MIN_PLAUSIBLE_UTC <= value < rlg.MAX_PLAUSIBLE_UTC:
        return None
    return value


def is_canonical_path(value) -> bool:
    """True when `value` is exactly its own string-normalized absolute key
    (the 02a form): no other case, separator, trailing separator, dot
    component, device/UNC prefix or stream. Never touches the filesystem."""
    if not rha._is_text(value) or rha._URI_RE.match(value) or not os.path.isabs(value):
        return False
    if value.startswith(("//", "\\\\")):
        return False
    if os.name == "nt":
        drive = os.path.splitdrive(value)[0]
        if not re.fullmatch(r"[a-z]:", drive) or ":" in value[2:]:
            return False
    if any(p in (".", "..") for p in rha._components(value)):
        return False
    return os.path.normcase(os.path.normpath(value)) == value


def default_queue_root(worktree_key: str) -> str:
    """The canonical default queue root of a canonical worktree key."""
    return os.path.normcase(os.path.normpath(os.path.join(worktree_key, *DEFAULT_QUEUE_SUBDIR_PARTS)))


def canonical_manifest_message(manifest: QueueScopeManifest) -> bytes:
    """Domain, separator and the canonical JSON of every manifest field.
    This is exactly what an operator's tool signs and what is verified."""
    payload = {}
    for name in MANIFEST_FIELDS:
        value = getattr(manifest, name)
        if name == "roots":
            value = [{"root": d.root, "source": d.source, "worktree_key": d.worktree_key} for d in value]
        payload[name] = value
    return MANIFEST_SIGNATURE_DOMAIN + DOMAIN_SEPARATOR + json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _unique_pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _Refused(MQS_MALFORMED)
    return dict(pairs)


def _reject_constant(_name):
    raise _Refused(MQS_MALFORMED)


def _strict_json(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_MANIFEST_BYTES:
        raise _Refused(MQS_MALFORMED)
    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except _Refused:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise _Refused(MQS_MALFORMED) from None


def _check_field_set(mapping, expected) -> None:
    if type(mapping) is not dict:
        raise _Refused(MQS_MALFORMED)
    extra = set(mapping) - set(expected)
    if extra & FORGED_CLAIM_FIELDS:
        raise _Refused(MQS_FORGED_CLAIM)
    if extra:
        raise _Refused(MQS_UNKNOWN_FIELD)
    if set(mapping) != set(expected):
        raise _Refused(MQS_MALFORMED)


def _manifest_from_mapping(value) -> QueueScopeManifest:
    if type(value) is dict and type(value.get("format")) is str and value["format"] != MANIFEST_FORMAT:
        raise _Refused(MQS_VERSION_UNSUPPORTED)
    _check_field_set(value, MANIFEST_FIELDS)
    for name in MANIFEST_FIELDS:
        item = value[name]
        if name == "roots":
            if type(item) is not list or not 0 < len(item) <= MAX_MANIFEST_ROOTS:
                raise _Refused(MQS_MALFORMED)
        elif name in ("host_claims_roots_complete", "acknowledged_external_queues_unprovable"):
            if type(item) is not bool:
                raise _Refused(MQS_MALFORMED)
        elif not rha._is_text(item):
            raise _Refused(MQS_MALFORMED)
    roots = []
    for entry in value["roots"]:
        _check_field_set(entry, ROOT_FIELDS)
        key = entry["worktree_key"]
        if not rha._is_text(entry["root"]) or not rha._is_text(entry["source"], 128) \
                or not (key is None or rha._is_text(key)):
            raise _Refused(MQS_MALFORMED)
        roots.append(QueueRootDeclaration(entry["root"], entry["source"], key))
    if not (rha._LABEL_RE.fullmatch(value["manifest_id"]) and _KEY_ID_RE.fullmatch(value["key_id"])
            and rha._LABEL_RE.fullmatch(value["signer_id"]) and rha._LABEL_RE.fullmatch(value["host_id"])
            and _DIGEST_RE.fullmatch(value["report_content_digest"]) and _DIGEST_RE.fullmatch(value["scope_digest"])
            and len(value["issued_at"]) <= 64 and len(value["expires_at"]) <= 64):
        raise _Refused(MQS_MALFORMED)
    if value["acknowledged_external_queues_unprovable"] is not True:
        raise _Refused(MQS_CONTRADICTORY)
    return QueueScopeManifest(
        format=value["format"], manifest_id=value["manifest_id"], key_id=value["key_id"],
        signer_id=value["signer_id"], host_id=value["host_id"], common_dir=value["common_dir"],
        report_content_digest=value["report_content_digest"], scope_digest=value["scope_digest"],
        issued_at=value["issued_at"], expires_at=value["expires_at"], roots=tuple(roots),
        host_claims_roots_complete=value["host_claims_roots_complete"])


def _decode_signature(text) -> bytes:
    if type(text) is not str or len(text) != _SIGNATURE_B64_CHARS:
        raise _Refused(MQS_SIGNATURE_MALFORMED)
    try:
        signature = base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, binascii.Error, UnicodeEncodeError):
        raise _Refused(MQS_SIGNATURE_MALFORMED) from None
    if len(signature) != SIGNATURE_BYTES or base64.b64encode(signature).decode("ascii") != text:
        raise _Refused(MQS_SIGNATURE_MALFORMED)
    return signature


def manifest_trust_errors(trust) -> Optional[str]:
    """MQS_TRUST_INVALID unless `trust` is an exact, well-formed public trust
    configuration. Shape only: never a proof of where it came from."""
    if type(trust) is not QueueManifestTrustConfig or trust.format != MANIFEST_TRUST_FORMAT \
            or trust.host_identity_authenticated is not False:
        return MQS_TRUST_INVALID
    keys, signers, revoked = trust.keys, trust.allowed_signer_ids, trust.revoked_key_ids
    if type(trust.host_id) is not str or not rha._LABEL_RE.fullmatch(trust.host_id) \
            or type(signers) is not tuple or not signers or len(set(signers)) != len(signers) \
            or not all(type(s) is str and rha._LABEL_RE.fullmatch(s) for s in signers) \
            or type(keys) is not tuple or not keys or len(keys) > MAX_PINNED_KEYS \
            or type(revoked) is not tuple or len(set(revoked)) != len(revoked) \
            or not all(type(k) is str and _KEY_ID_RE.fullmatch(k) for k in revoked):
        return MQS_TRUST_INVALID
    if not all(type(k) is PinnedQueueManifestKey and type(k.key_id) is str and _KEY_ID_RE.fullmatch(k.key_id)
               and type(k.signer_id) is str and rha._LABEL_RE.fullmatch(k.signer_id)
               and type(k.public_key) is bytes and len(k.public_key) == PUBLIC_KEY_BYTES
               and k.public_key not in _WEAK_PUBLIC_KEYS for k in keys) \
            or len({k.key_id for k in keys}) != len(keys) or len({k.public_key for k in keys}) != len(keys):
        return MQS_TRUST_INVALID
    if CRYPTO_AVAILABLE:
        try:
            for k in keys:
                _Ed25519PublicKey.from_public_bytes(k.public_key)
        except Exception:  # noqa: BLE001 - an unusable key is a configuration refusal
            return MQS_TRUST_INVALID
    return None


def _signature_valid(public_key: bytes, signature: bytes, message: bytes) -> bool:
    if not CRYPTO_AVAILABLE:
        return False
    try:
        _Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except Exception:  # noqa: BLE001 - InvalidSignature or any backend failure
        return False
    return True


def _check_structure(m: QueueScopeManifest) -> None:
    """Canonical common dir and roots, known sources, consistent default
    declarations (a default root is a function of its worktree key, so a
    duplicate owner is a duplicate root), strictly sorted, distinct roots."""
    if not is_canonical_path(m.common_dir):
        raise _Refused(MQS_PATH_NOT_CANONICAL)
    for d in m.roots:
        if not is_canonical_path(d.root) or (d.worktree_key is not None and not is_canonical_path(d.worktree_key)):
            raise _Refused(MQS_PATH_NOT_CANONICAL)
        if d.source not in ROOT_SOURCES:
            raise _Refused(MQS_SOURCE_UNKNOWN)
        if d.source == SOURCE_REGISTERED_WORKTREE_DEFAULT:
            if d.worktree_key is None or d.root != default_queue_root(d.worktree_key):
                raise _Refused(MQS_CONTRADICTORY)
        elif d.worktree_key is not None:
            raise _Refused(MQS_CONTRADICTORY)
    names = [d.root for d in m.roots]
    if len(set(names)) != len(names):
        raise _Refused(MQS_DUPLICATE_ROOT)
    if names != sorted(names):
        raise _Refused(MQS_ROOTS_NOT_SORTED)


# ---------------------------------------------------------------------------
# Manifest verification (structure and signature, never attestation)
# ---------------------------------------------------------------------------

class _ManifestState:
    def __init__(self):
        self.signature_verified = False
        self.digest = None
        self.manifest = None


def verify_queue_scope_manifest(raw, *, trust, now) -> QueueScopeManifestVerification:
    """Strict check of ONE signed manifest envelope `{"manifest", "signature"}`
    against the caller-pinned `trust` and the caller's UTC `now`. Never
    raises. Success is STRUCTURE_VERIFIED_NOT_ATTESTED, nothing more."""
    state = _ManifestState()
    try:
        _verify_manifest(state, raw, trust, now)
    except _Refused as exc:
        return _manifest_result(state, exc.code)
    except Exception:  # noqa: BLE001 - nothing unexpected is ever a verification
        return _manifest_result(state, MQS_INTERNAL_ERROR)
    return _manifest_result(state, None)


def _manifest_result(state: _ManifestState, code: Optional[str]) -> QueueScopeManifestVerification:
    return QueueScopeManifestVerification(
        schema=MANIFEST_VERIFICATION_SCHEMA,
        status=STATUS_REFUSED if code else STATUS_STRUCTURE_VERIFIED_NOT_ATTESTED,
        reason_codes=(code,) if code else (), signature_verified=state.signature_verified,
        manifest_digest=state.digest if state.signature_verified else None,
        manifest=None if code else state.manifest)


def _verify_manifest(state, raw, trust, now) -> None:
    if not (CRYPTO_AVAILABLE and rha.CRYPTO_AVAILABLE):
        raise _Refused(MQS_CRYPTO_UNAVAILABLE)
    if manifest_trust_errors(trust):
        raise _Refused(MQS_TRUST_INVALID)
    now = _exact_utc(now)
    if now is None:
        raise _Refused(MQS_CLOCK_INVALID)
    document = _strict_json(raw)
    _check_field_set(document, ("manifest", "signature"))
    m = _manifest_from_mapping(document["manifest"])
    signature = _decode_signature(document["signature"])
    key = next((k for k in trust.keys if k.key_id == m.key_id), None)
    if key is None:
        raise _Refused(MQS_KEY_UNPINNED)
    if key.key_id in trust.revoked_key_ids:
        raise _Refused(MQS_KEY_REVOKED)
    if key.signer_id != m.signer_id:
        raise _Refused(MQS_SIGNER_MISMATCH)
    if m.signer_id not in trust.allowed_signer_ids:
        raise _Refused(MQS_SIGNER_NOT_ALLOWED)
    message = canonical_manifest_message(m)
    if not _signature_valid(key.public_key, signature, message):
        raise _Refused(MQS_SIGNATURE_INVALID)
    state.signature_verified = True
    state.digest = hashlib.sha256(message).hexdigest()

    if m.host_id != trust.host_id:
        raise _Refused(MQS_HOST_MISMATCH)
    issued, expires = rha._timestamp(m.issued_at), rha._timestamp(m.expires_at)
    if issued is None or expires is None or expires <= issued:
        raise _Refused(MQS_TIMESTAMP_INVALID)
    if expires - issued > timedelta(seconds=MAX_MANIFEST_TTL_SECONDS):
        raise _Refused(MQS_TTL_TOO_LONG)
    if issued > now:
        raise _Refused(MQS_NOT_YET_VALID)
    if now >= expires:
        raise _Refused(MQS_EXPIRED)
    _check_structure(m)
    state.manifest = m


# ---------------------------------------------------------------------------
# Composition (read-only, dry run)
# ---------------------------------------------------------------------------

class _Composition:
    def __init__(self):
        self.codes = []
        self.proposal_findings = ()
        self.command_codes = ()
        self.ledger_codes = ()
        self.manifest_codes = ()
        self.verification = None
        self.command = None
        self.source_records_revalidated = False
        self.ledger_evidence_present = False
        self.ledger_record_state = None
        self.mark = None
        self.manifest = None

    def refuse(self, code: str) -> None:
        self.codes.append(code)


def compose_retirement_evidence(envelope, *, config, proposal, report, inventory_record, manifest_envelope,
                                manifest_trust, ledger_path, ledger_forbidden_roots,
                                now) -> RetirementEvidenceComposition:
    """Re-runs the 02a source validation, the 02b verification of the raw
    `envelope` and read-only 02c ledger queries, then checks the signed queue
    `manifest_envelope` against the report. Never raises and never writes.
    DRY_RUN_EVIDENCE_CONSISTENT enables nothing: see BLOCKING_UNCERTAINTIES."""
    state = _Composition()
    try:
        _compose(state, envelope, config, proposal, report, inventory_record, manifest_envelope, manifest_trust,
                 ledger_path, ledger_forbidden_roots, now)
    except Exception:  # noqa: BLE001 - nothing unexpected is ever consistent
        state.refuse(CMP_INTERNAL_ERROR)
    return _composition_result(state)


def _composition_result(state: _Composition) -> RetirementEvidenceComposition:
    v, c, m = state.verification, state.command, state.manifest
    signed = v is not None and v.signature_verified is True
    codes = tuple(dict.fromkeys(state.codes))
    return RetirementEvidenceComposition(
        schema=COMPOSITION_SCHEMA,
        status=STATUS_REFUSED if codes else STATUS_DRY_RUN_EVIDENCE_CONSISTENT,
        reason_codes=codes, proposal_findings=tuple(state.proposal_findings),
        command_verification_codes=tuple(state.command_codes), ledger_codes=tuple(state.ledger_codes),
        manifest_codes=tuple(state.manifest_codes),
        signature_verified=signed, source_records_revalidated=state.source_records_revalidated,
        ledger_evidence_present=state.ledger_evidence_present, ledger_record_state=state.ledger_record_state,
        ledger_clock_high_water_mark=state.mark,
        manifest_status=m.status if m is not None else None,
        manifest_signature_verified=m is not None and m.signature_verified is True,
        manifest_digest=m.manifest_digest if m is not None else None,
        command_id=v.command_id if signed else None, nonce=c.nonce if c else None,
        command_message_digest=v.command_message_digest if signed else None,
        proposal_digest=v.proposal_digest if v is not None else None,
        scope_digest=c.scope_digest if c else None, target_identity_digest=c.target_identity_digest if c else None,
        host_id_label=v.host_id_label if signed else None,
    )


def _proposal_typed(proposal) -> bool:
    return (type(proposal) is wra.RetirementProposal and type(proposal.target) is wra.RetirementTargetIdentity
            and type(proposal.scope) is wra.RetirementScope)


def _compose(state, envelope, config, proposal, report, inventory_record, manifest_envelope, manifest_trust,
             ledger_path, ledger_forbidden_roots, now) -> None:
    if type(envelope) is not bytes or type(manifest_envelope) is not bytes \
            or isinstance(ledger_forbidden_roots, (str, bytes, Path)) \
            or not isinstance(ledger_forbidden_roots, (tuple, list)) or not ledger_forbidden_roots:
        state.refuse(CMP_ARGUMENT_INVALID)
        return
    now = _exact_utc(now)
    if now is None:
        state.refuse(CMP_CLOCK_INVALID)
        return
    if not (CRYPTO_AVAILABLE and rha.CRYPTO_AVAILABLE):
        state.refuse(CMP_CRYPTO_UNAVAILABLE)
        return
    if rha.config_errors(config):
        state.refuse(CMP_CONFIG_INVALID)
        return
    host = config.host_id
    typed = _proposal_typed(proposal)

    # 02a: the proposal must re-derive exactly from its (untrusted) sources.
    findings = wra.validate_proposal_against_report(proposal, report, inventory_record)
    state.proposal_findings = findings
    if findings:
        state.refuse(CMP_PROPOSAL_SOURCE_INVALID)

    # 02c: read-only open (never created) and the durable mark.
    roots = tuple(ledger_forbidden_roots)
    if typed:
        s, t = proposal.scope, proposal.target
        roots += (s.repository_top, s.common_dir, s.state_root, s.ledger_root, t.worktree_key) + s.queue_roots \
            + s.governed_roots
    ledger, mark = _open_ledger(state, ledger_path, host, roots, now)

    # 02b: the raw envelope, re-verified; a caller's verdict is never input.
    verification = rha.verify_retirement_command(
        envelope, config=config, proposal=proposal, now=now, trusted_high_water_mark=mark, report=report,
        inventory_record=inventory_record)
    state.verification = verification
    state.source_records_revalidated = verification.source_records_revalidated is True
    try:
        state.command = rlg._reverified_command(verification, envelope, host)
    except rlg._Refused as exc:
        state.refuse(CMP_COMMAND_NOT_VERIFIED)
        state.command_codes = tuple(c for c in exc.codes if c != rlg.RLG_VERIFICATION_REFUSED) or exc.codes

    if ledger is not None and state.command is not None:
        _check_evidence(state, ledger, state.command, verification.command_message_digest, mark)

    # Queue scope manifest: structure and signature, then the report scope.
    manifest = verify_queue_scope_manifest(manifest_envelope, trust=manifest_trust, now=now)
    state.manifest = manifest
    state.manifest_codes = manifest.reason_codes
    m = manifest.manifest
    if manifest.status != STATUS_STRUCTURE_VERIFIED_NOT_ATTESTED or m is None:
        state.refuse(CMP_MANIFEST_REFUSED)
    elif m.host_id != host or (typed and (
            m.common_dir != proposal.scope.common_dir
            or m.report_content_digest != proposal.report_content_digest
            or m.scope_digest != proposal.scope.scope_digest)):
        state.refuse(CMP_MANIFEST_BINDING_MISMATCH)
    if findings or m is None or not typed:
        state.refuse(CMP_SCOPE_NOT_EVALUATED)
    else:
        for code in scope_findings(m, proposal, report):
            state.refuse(code)


def _open_ledger(state, ledger_path, host, roots, now):
    try:
        ledger = rlg.open_existing(ledger_path, host_id=host, forbidden_roots=roots)
        mark_text = ledger.clock_high_water_mark()
    except rlg.RetirementLedgerRefused as exc:
        state.refuse(CMP_LEDGER_UNAVAILABLE)
        state.ledger_codes += (exc.code,)
        return None, None
    mark = rlg._instant(mark_text)
    if mark is None:
        state.refuse(CMP_LEDGER_UNAVAILABLE)
        return None, None
    state.mark = mark_text
    if now < mark:
        state.refuse(CMP_CLOCK_ROLLBACK)
    return ledger, mark


def _check_evidence(state, ledger, c, digest: str, mark: datetime) -> None:
    """The ledger must hold exactly one unrevoked record of exactly this
    command, recorded inside its window and not after the durable mark."""
    try:
        evidence = ledger.get_command(c.command_id)
        revoked = ledger.is_revoked(c.command_id)
        trail = ledger.audit_trail()
    except rlg.RetirementLedgerRefused as exc:
        state.refuse(CMP_LEDGER_UNAVAILABLE)
        state.ledger_codes += (exc.code,)
        return
    if revoked is not False:
        state.refuse(CMP_LEDGER_COMMAND_REVOKED)
    if evidence is None:
        state.refuse(CMP_LEDGER_EVIDENCE_MISSING)
    else:
        state.ledger_evidence_present = True
        state.ledger_record_state = evidence.record_state
        if type(evidence) is not rlg.RecordedRetirementCommandEvidence \
                or evidence.record_version != rlg.RECORD_VERSION \
                or evidence.evidence_kind != rlg.EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING \
                or evidence.domain != rlg.LEDGER_DOMAIN or evidence.record_state not in _EVIDENCE_STATES \
                or any(getattr(evidence, name) is not value for name, value in _EVIDENCE_FLAGS):
            state.refuse(CMP_LEDGER_EVIDENCE_MISMATCH)
        if evidence.record_state == rlg.RECORD_STATE_REVOKED:
            state.refuse(CMP_LEDGER_COMMAND_REVOKED)
        if evidence.nonce != c.nonce:
            state.refuse(CMP_LEDGER_NONCE_MISMATCH)
        if evidence.command_message_digest != digest:
            state.refuse(CMP_LEDGER_DIGEST_MISMATCH)
        if (evidence.host_id_label, evidence.command_id, evidence.key_id, evidence.director_id,
                evidence.proposal_digest, evidence.scope_digest, evidence.target_identity_digest,
                evidence.issued_at, evidence.expires_at) != (
                c.host_id, c.command_id, c.key_id, c.director_id, c.proposal_digest, c.scope_digest,
                c.target_identity_digest, c.issued_at, c.expires_at):
            state.refuse(CMP_LEDGER_EVIDENCE_MISMATCH)
        issued, expires = rha._timestamp(evidence.issued_at), rha._timestamp(evidence.expires_at)
        recorded = rlg._instant(evidence.recorded_at)
        if issued is None or expires is None or recorded is None or not issued <= recorded < expires \
                or recorded > mark:
            state.refuse(CMP_LEDGER_EVIDENCE_MISMATCH)
    recorded_events = [e for e in trail if e.event == rlg.EVENT_COMMAND_EVIDENCE_RECORDED]
    same_id = [e for e in recorded_events if e.command_id == c.command_id]
    same_digest = [e.command_id for e in recorded_events if e.digest == digest]
    revocations = [e for e in trail if e.event == rlg.EVENT_COMMAND_REVOKED and e.command_id == c.command_id]
    if len(same_id) != (0 if evidence is None else 1) or len(revocations) != (1 if revoked else 0) \
            or any(command_id != c.command_id for command_id in same_digest) \
            or (evidence is not None and same_id and same_id[0].digest != evidence.command_message_digest):
        state.refuse(CMP_LEDGER_AMBIGUOUS)


def scope_findings(manifest: QueueScopeManifest, proposal, report) -> tuple:
    """Stable codes for `manifest` versus the queue roots the (already
    02a-validated) report and proposal can derive; empty when they agree.
    Pure. An empty result is NOT queue completeness and NOT an attestation:
    external queues remain unprovable."""
    codes = []
    target, scope = proposal.target.worktree_key, proposal.scope
    registered = []
    for record in report.records:
        key = record.worktree_key
        if not is_canonical_path(key) or wra._path_key(key) != key or wra._path_key(record.path) != key:
            codes.append(CMP_SCOPE_REGISTRY_INCONSISTENT)
        else:
            registered.append(key)
    if len(set(registered)) != len(registered) or target not in registered \
            or scope.repository_top not in registered:
        codes.append(CMP_SCOPE_REGISTRY_INCONSISTENT)
    defaults = {k: default_queue_root(k) for k in registered}
    declared = {d.worktree_key: d.root for d in manifest.roots if d.source == SOURCE_REGISTERED_WORKTREE_DEFAULT}
    overrides = {d.root for d in manifest.roots if d.source == SOURCE_DECLARED_OVERRIDE}
    every_root = {d.root for d in manifest.roots}
    read = set(scope.queue_roots)
    if any(k not in declared for k in registered):
        codes.append(CMP_SCOPE_DEFAULT_ROOT_MISSING)
    if any(k not in defaults for k in declared):
        codes.append(CMP_SCOPE_UNKNOWN_WORKTREE)
    if overrides & set(defaults.values()):
        codes.append(CMP_SCOPE_ROOT_SOURCE_MISMATCH)
    if overrides - read:
        codes.append(CMP_SCOPE_DECLARED_ROOT_NOT_READ)
    if read - every_root:
        codes.append(CMP_SCOPE_UNDECLARED_ROOT)
    if any(defaults[k] not in read for k in registered if k != target):
        codes.append(CMP_SCOPE_DEFAULT_ROOT_NOT_READ)
    # The target's own default queue is never read (02a refuses roots that
    # overlap the target); only its caller-supplied cleanliness speaks to it.
    facts = next((r.facts for r in report.records if r.worktree_key == target), None)
    if facts is None or facts.supplemental_checked is not True or type(facts.ignored_count) is not int \
            or facts.ignored_count != 0 or facts.supplemental_status_entries != () \
            or facts.ignored_sensitive != () or facts.queue_items != ():
        codes.append(CMP_SCOPE_TARGET_QUEUE_UNPROVEN)
    if manifest.host_claims_roots_complete is not True or report.queue_roots_complete_claim is not True:
        codes.append(CMP_SCOPE_DECLARED_INCOMPLETE)
    return tuple(dict.fromkeys(codes))


def compose_live(*_args, **_kwargs):
    """Permanent guard: there is no live composition in FCP-4E-02d. Raises
    NOT_LIVE at once, without reading any argument, the host or a file."""
    raise RetirementCompositionNotLive()
