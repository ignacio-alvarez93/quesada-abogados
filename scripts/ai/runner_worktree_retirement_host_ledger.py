"""FCP-4E-02c: isolated, durable, NON-AUTHORIZING retirement host ledger (NOT LIVE).

A library for a FUTURE isolated retirement host: a SQLite file that durably
records EVIDENCE about FCP-4E-02b retirement commands, one-way revocation
tombstones, a monotonic clock high-water mark and an append-only audit
trail. No record is a retirement authorization: there is no issued,
permitted, consumed, executed or deletion-authorized state or operation
here, and every result carries `authorizes_action=False`,
`deletion_authorized=False`, `branch_deletion_authorized=False`,
`issued=False`, `consumed=False`, `host_identity_authenticated=False`,
`queue_scope_attested=False`, `file_acl_verified=False` and
`clock_attested=False` (fixed, not constructor arguments).
`RETIREMENT_AUTHORIZATION_LIVE` / `RETIREMENT_EXECUTION_CAPABLE` are constant
False. This module starts no process, calls no Git, removes no file or
worktree, takes no DirLease or QueueLock, makes no network call, generates no
key, signs nothing and has no live composition. It is separate from (and
never imports) the FCP-3B PR promotion host ledger.

Provisioning and opening
------------------------
`provision` is the ONLY operation that creates a ledger: one explicit
absolute path (no default location) whose name ends with
LEDGER_FILENAME_SUFFIX, created exclusively (O_EXCL; never overwritten,
truncated or recreated) in an existing, non-aliased directory outside this
repository, outside every caller-supplied forbidden root and outside any
directory tree that contains a `.git` entry. `open_existing` opens only an
already provisioned ledger: it checks the file header, then reads through a
real SQLite read-only connection (`mode=ro`, `query_only`) and validates the
exact schema text, triggers, constraints, metadata, host-id binding and
invariants. It never creates, migrates, repairs or updates anything; a
missing file, unknown schema or corruption is refused. Read-only queries
create no side file and change no byte. Every write is one explicitly named
command running in ONE `BEGIN IMMEDIATE` transaction on a fresh `mode=rw`
connection (which cannot create a file); it commits atomically or rolls back
entirely, and a busy database is a refusal, never a retry. A write
interrupted by a crash leaves a hot journal that read-only connections
refuse (RLG_INTERRUPTED_WRITE) until the explicit `recover_interrupted_write`
lets SQLite roll it back. A failed provisioning leaves at most an
unprovisioned file that `open_existing` refuses; nothing deletes it.

Command evidence (one semantics only)
-------------------------------------
`record_reverified_command_evidence` accepts the signed FCP-4E-02b envelope
itself and RE-VERIFIES it inside the write transaction with the existing
02b verifier, the caller-supplied pinned configuration, the complete 02a
proposal, the caller's clock and the durable high-water mark. Only a
consistent SIGNATURE_VERIFIED_NON_AUTHORIZING verification is recorded, as
evidence kind SIGNATURE_REVERIFIED_NON_AUTHORIZING: a signature
authenticates a pinned key, not human presence, and is never an approval.
A verification result object supplied by a caller is never accepted (it
would be forgeable), and no unverified or "submitted claim" recording
exists. Stored: safe ids, labels, digests and the command window as data;
never the envelope, the signature, a key or a filesystem path. Command id,
nonce and canonical-message digest are each UNIQUE; a revoked command id can
never be recorded; recorded rows are immutable. Key revocation stays
governed by the pinned 02b configuration, not by this file.

Clock and audit
---------------
The caller's clock must be an exact UTC `datetime` (`tzinfo is
timezone.utc`). It is read INSIDE the write lock, refused if it is before
the durable high-water mark (equality is allowed) or implausible, and the
mark is advanced in the same transaction as the evidence, tombstone and
audit row. Reads never touch it. A monotonic caller clock is still not
trusted time and not a host attestation; a clock that jumped forward
poisons the mark and every later write refuses (fail closed). Refused
writes change nothing, audit included. SQL triggers make audit, metadata,
evidence and tombstones append-only and the mark forward-only.

Known residual limitations (LEDGER_LIMITATIONS)
-----------------------------------------------
`host_id` and paths are caller-supplied labels: they do NOT authenticate the
host. Windows ACLs are not inspected and POSIX mode checks are point-in-time;
a local SQLite file proves NO isolation and whoever can write the file can
rewrite it, triggers included. Queue scope, Git state and human approval are
not rechecked. Human retirement policy D-1..D-12 remains pending and is not
granted by anything here; issuance (FCP-4E-02d) and consumption (FCP-4F) do
not exist in this module.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import runner_worktree_retirement_host_authority as rha
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_worktree_retirement_host_authority as rha  # type: ignore[no-redef]

RETIREMENT_AUTHORIZATION_LIVE = False
RETIREMENT_EXECUTION_CAPABLE = False

LEDGER_SCHEMA_VERSION = "fcp4e02c-retirement-ledger-v1"
RECORD_VERSION = "fcp4e02c-retirement-command-evidence-v1"
RESULT_SCHEMA = "fcp4e02c-retirement-ledger-result-v1"
LEDGER_DOMAIN = rha.COMMAND_FORMAT
LEDGER_FILENAME_SUFFIX = ".retirement-ledger.sqlite3"
LEDGER_APPLICATION_ID = 0x46433243   # "FC2C" in the SQLite header
LEDGER_USER_VERSION = 4002003
BUSY_TIMEOUT_SECONDS = 5.0
MAX_BUSY_TIMEOUT_SECONDS = 30.0
MIN_PLAUSIBLE_UTC = datetime(2024, 1, 1, tzinfo=timezone.utc)
MAX_PLAUSIBLE_UTC = datetime(2100, 1, 1, tzinfo=timezone.utc)

# The only evidence kind and record states. None of them is a permission.
EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING = "SIGNATURE_REVERIFIED_NON_AUTHORIZING"
RECORD_STATE_RECORDED_NON_AUTHORIZING = "RECORDED_NON_AUTHORIZING"
RECORD_STATE_REVOKED = "REVOKED"

# Operation outcome statuses.
STATUS_REFUSED = "REFUSED"
STATUS_PROVISIONED_EMPTY = "PROVISIONED_EMPTY_NON_AUTHORIZING"
STATUS_RECORDED_NON_AUTHORIZING = RECORD_STATE_RECORDED_NON_AUTHORIZING
STATUS_REVOKED = RECORD_STATE_REVOKED
STATUS_INTERRUPTED_WRITE_ROLLED_BACK = "INTERRUPTED_WRITE_ROLLED_BACK"
STATUS_NO_INTERRUPTED_WRITE = "NO_INTERRUPTED_WRITE"

OP_PROVISION = "PROVISION"
OP_RECORD_REVERIFIED_COMMAND_EVIDENCE = "RECORD_REVERIFIED_COMMAND_EVIDENCE"
OP_REVOKE_COMMAND = "REVOKE_COMMAND"
OP_RECOVER_INTERRUPTED_WRITE = "RECOVER_INTERRUPTED_WRITE"

# Audit events.
EVENT_LEDGER_PROVISIONED = "LEDGER_PROVISIONED"
EVENT_COMMAND_EVIDENCE_RECORDED = "COMMAND_EVIDENCE_RECORDED"
EVENT_COMMAND_REVOKED = "COMMAND_REVOKED"
AUDIT_EVENTS = (EVENT_LEDGER_PROVISIONED, EVENT_COMMAND_EVIDENCE_RECORDED, EVENT_COMMAND_REVOKED)

# Stable revocation reasons (no free text, no personal data).
REVOCATION_REASONS = ("DIRECTOR_WITHDRAWN", "TARGET_STATE_CHANGED", "SUPERSEDED", "SUSPECTED_COMPROMISE",
                      "OPERATOR_HOLD")

LEDGER_LIMITATIONS = (
    "EVIDENCE_IS_NOT_PERMISSION",
    "NO_ISSUANCE_OR_CONSUMPTION",
    "SIGNATURE_IS_NOT_HUMAN_PRESENCE",
    "HOST_ID_IS_A_LABEL",
    "HOST_IDENTITY_NOT_AUTHENTICATED",
    "CALLER_CLOCK_NOT_TRUSTED",
    "HIGH_WATER_MARK_NOT_ATTESTED",
    "FILE_ACL_NOT_INSPECTED",
    "LOCAL_FILE_PROVES_NO_ISOLATION",
    "GIT_STATE_NOT_RECHECKED",
    "QUEUE_SCOPE_NOT_ATTESTED",
    "RETIREMENT_POLICY_PENDING",
)

# Refusal codes.
RLG_ARGUMENT_INVALID = "RLG_ARGUMENT_INVALID"
RLG_HOST_ID_INVALID = "RLG_HOST_ID_INVALID"
RLG_ROOTS_INVALID = "RLG_ROOTS_INVALID"
RLG_PATH_INVALID = "RLG_PATH_INVALID"
RLG_PATH_FORBIDDEN_ROOT = "RLG_PATH_FORBIDDEN_ROOT"
RLG_PATH_INSIDE_REPOSITORY = "RLG_PATH_INSIDE_REPOSITORY"
RLG_PATH_ALIAS = "RLG_PATH_ALIAS"
RLG_PATH_INSECURE = "RLG_PATH_INSECURE"
RLG_PARENT_MISSING = "RLG_PARENT_MISSING"
RLG_PATH_EXISTS = "RLG_PATH_EXISTS"
RLG_PATH_MISSING = "RLG_PATH_MISSING"
RLG_NOT_REGULAR_FILE = "RLG_NOT_REGULAR_FILE"
RLG_SIDE_FILE_PRESENT = "RLG_SIDE_FILE_PRESENT"
RLG_FILE_CHANGED = "RLG_FILE_CHANGED"
RLG_ACL_UNVERIFIABLE = "RLG_ACL_UNVERIFIABLE"
RLG_NOT_A_RETIREMENT_LEDGER = "RLG_NOT_A_RETIREMENT_LEDGER"
RLG_SCHEMA_UNSUPPORTED = "RLG_SCHEMA_UNSUPPORTED"
RLG_SCHEMA_INVALID = "RLG_SCHEMA_INVALID"
RLG_LEDGER_INCONSISTENT = "RLG_LEDGER_INCONSISTENT"
RLG_CORRUPT = "RLG_CORRUPT"
RLG_HOST_MISMATCH = "RLG_HOST_MISMATCH"
RLG_INTERRUPTED_WRITE = "RLG_INTERRUPTED_WRITE"
RLG_BUSY = "RLG_BUSY"
RLG_STORAGE_FAILED = "RLG_STORAGE_FAILED"
RLG_CLOCK_INVALID = "RLG_CLOCK_INVALID"
RLG_CLOCK_IMPLAUSIBLE = "RLG_CLOCK_IMPLAUSIBLE"
RLG_CLOCK_REGRESSION = "RLG_CLOCK_REGRESSION"
RLG_CRYPTO_UNAVAILABLE = "RLG_CRYPTO_UNAVAILABLE"
RLG_VERIFICATION_REFUSED = "RLG_VERIFICATION_REFUSED"
RLG_VERIFICATION_INCONSISTENT = "RLG_VERIFICATION_INCONSISTENT"
RLG_COMMAND_DUPLICATE = "RLG_COMMAND_DUPLICATE"
RLG_NONCE_REUSED = "RLG_NONCE_REUSED"
RLG_MESSAGE_DUPLICATE = "RLG_MESSAGE_DUPLICATE"
RLG_COMMAND_REVOKED = "RLG_COMMAND_REVOKED"
RLG_ALREADY_REVOKED = "RLG_ALREADY_REVOKED"
RLG_REASON_INVALID = "RLG_REASON_INVALID"
RLG_INTERNAL_ERROR = "RLG_INTERNAL_ERROR"

REFUSAL_CODES = (
    RLG_ARGUMENT_INVALID, RLG_HOST_ID_INVALID, RLG_ROOTS_INVALID, RLG_PATH_INVALID, RLG_PATH_FORBIDDEN_ROOT,
    RLG_PATH_INSIDE_REPOSITORY, RLG_PATH_ALIAS, RLG_PATH_INSECURE, RLG_PARENT_MISSING, RLG_PATH_EXISTS,
    RLG_PATH_MISSING, RLG_NOT_REGULAR_FILE, RLG_SIDE_FILE_PRESENT, RLG_FILE_CHANGED, RLG_ACL_UNVERIFIABLE,
    RLG_NOT_A_RETIREMENT_LEDGER, RLG_SCHEMA_UNSUPPORTED, RLG_SCHEMA_INVALID, RLG_LEDGER_INCONSISTENT, RLG_CORRUPT,
    RLG_HOST_MISMATCH, RLG_INTERRUPTED_WRITE, RLG_BUSY, RLG_STORAGE_FAILED, RLG_CLOCK_INVALID,
    RLG_CLOCK_IMPLAUSIBLE, RLG_CLOCK_REGRESSION, RLG_CRYPTO_UNAVAILABLE, RLG_VERIFICATION_REFUSED,
    RLG_VERIFICATION_INCONSISTENT, RLG_COMMAND_DUPLICATE, RLG_NONCE_REUSED, RLG_MESSAGE_DUPLICATE,
    RLG_COMMAND_REVOKED, RLG_ALREADY_REVOKED, RLG_REASON_INVALID, RLG_INTERNAL_ERROR,
)

_SIDE_SUFFIXES = ("-journal", "-wal", "-shm")
_SQLITE_MAGIC = b"SQLite format 3\x00"
_SQLITE_HEADER_BYTES = 100
_SQLITE_BUSY, _SQLITE_LOCKED, _SQLITE_CORRUPT, _SQLITE_NOTADB = 5, 6, 11, 26
_SQLITE_READONLY_ROLLBACK = 776
_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_STAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
_URI_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~/:")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Schema. SQLite stores these statements verbatim; validation compares them
# exactly, so a dropped or altered constraint or trigger is refused.
# ---------------------------------------------------------------------------

_D2 = "[0-9][0-9]"
_COMMAND_STAMP_GLOB = f"{_D2}{_D2}-{_D2}-{_D2}T{_D2}:{_D2}:{_D2}Z"
_STAMP_GLOB = f"{_D2}{_D2}-{_D2}-{_D2}T{_D2}:{_D2}:{_D2}.{_D2}{_D2}{_D2}Z"


def _label(col: str) -> str:
    return f"typeof({col}) = 'text' AND length({col}) BETWEEN 1 AND 128"


def _hex64(col: str) -> str:
    return f"typeof({col}) = 'text' AND length({col}) = 64 AND {col} NOT GLOB '*[^0-9a-f]*'"


def _stamp_check(col: str, pattern: str = _STAMP_GLOB) -> str:
    return f"typeof({col}) = 'text' AND {col} GLOB '{pattern}'"


def _quoted(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


_TABLES = (
    ("meta", f"""CREATE TABLE meta (
    key TEXT PRIMARY KEY CHECK (key IN ('schema_version', 'domain', 'host_id', 'provisioned_at')),
    value TEXT NOT NULL CHECK ({_label('value')}))"""),
    ("clock_high_water", f"""CREATE TABLE clock_high_water (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    high_water TEXT NOT NULL CHECK ({_stamp_check('high_water')}))"""),
    ("command_evidence", f"""CREATE TABLE command_evidence (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    record_version TEXT NOT NULL CHECK (record_version = '{RECORD_VERSION}'),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind = '{EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING}'),
    record_state TEXT NOT NULL CHECK (record_state = '{RECORD_STATE_RECORDED_NON_AUTHORIZING}'),
    domain TEXT NOT NULL CHECK (domain = '{LEDGER_DOMAIN}'),
    host_id TEXT NOT NULL CHECK ({_label('host_id')}),
    command_id TEXT NOT NULL UNIQUE CHECK ({_label('command_id')}),
    nonce TEXT NOT NULL UNIQUE CHECK ({_hex64('nonce')}),
    key_id TEXT NOT NULL CHECK ({_label('key_id')}),
    director_id TEXT NOT NULL CHECK ({_label('director_id')}),
    proposal_digest TEXT NOT NULL CHECK ({_hex64('proposal_digest')}),
    scope_digest TEXT NOT NULL CHECK ({_hex64('scope_digest')}),
    target_identity_digest TEXT NOT NULL CHECK ({_hex64('target_identity_digest')}),
    command_message_digest TEXT NOT NULL UNIQUE CHECK ({_hex64('command_message_digest')}),
    issued_at TEXT NOT NULL CHECK ({_stamp_check('issued_at', _COMMAND_STAMP_GLOB)}),
    expires_at TEXT NOT NULL CHECK ({_stamp_check('expires_at', _COMMAND_STAMP_GLOB)}),
    recorded_at TEXT NOT NULL CHECK ({_stamp_check('recorded_at')}),
    CHECK (expires_at > issued_at))"""),
    ("revocations", f"""CREATE TABLE revocations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL UNIQUE CHECK ({_label('command_id')}),
    host_id TEXT NOT NULL CHECK ({_label('host_id')}),
    reason_code TEXT NOT NULL CHECK (reason_code IN ({_quoted(REVOCATION_REASONS)})),
    revoked_at TEXT NOT NULL CHECK ({_stamp_check('revoked_at')}))"""),
    ("audit", f"""CREATE TABLE audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL CHECK ({_stamp_check('at')}),
    event TEXT NOT NULL CHECK (event IN ({_quoted(AUDIT_EVENTS)})),
    code TEXT NOT NULL CHECK ({_label('code')}),
    command_id TEXT CHECK (command_id IS NULL OR ({_label('command_id')})),
    digest TEXT CHECK (digest IS NULL OR ({_hex64('digest')})))"""),
)


def _deny(name: str, when: str, table: str, condition: str = "") -> tuple:
    clause = f"\n    WHEN {condition}" if condition else ""
    return (name, f"CREATE TRIGGER {name} BEFORE {when} ON {table}{clause}\n"
                  f"    BEGIN SELECT RAISE(ABORT, 'fcp4e02c-ledger-append-only'); END")


_BOUND_TO_LEDGER = ("NEW.host_id IS NOT (SELECT value FROM meta WHERE key = 'host_id')"
                    " OR NEW.{stamp} IS NOT (SELECT high_water FROM clock_high_water WHERE id = 1)")

# Created AFTER the provisioning rows, so metadata and the clock row are
# insert-once; everything else is append-only and bound to the ledger's
# host label and the current high-water mark.
_TRIGGERS = (
    _deny("meta_no_insert", "INSERT", "meta"),
    _deny("meta_no_update", "UPDATE", "meta"),
    _deny("meta_no_delete", "DELETE", "meta"),
    _deny("clock_no_insert", "INSERT", "clock_high_water"),
    _deny("clock_no_delete", "DELETE", "clock_high_water"),
    _deny("clock_forward_only", "UPDATE", "clock_high_water",
          "NEW.id IS NOT OLD.id OR NEW.high_water < OLD.high_water"),
    _deny("command_evidence_no_update", "UPDATE", "command_evidence"),
    _deny("command_evidence_no_delete", "DELETE", "command_evidence"),
    _deny("command_evidence_not_revoked", "INSERT", "command_evidence",
          "EXISTS (SELECT 1 FROM revocations WHERE command_id = NEW.command_id)"),
    _deny("command_evidence_bound", "INSERT", "command_evidence", _BOUND_TO_LEDGER.format(stamp="recorded_at")),
    _deny("revocations_no_update", "UPDATE", "revocations"),
    _deny("revocations_no_delete", "DELETE", "revocations"),
    _deny("revocations_bound", "INSERT", "revocations", _BOUND_TO_LEDGER.format(stamp="revoked_at")),
    _deny("audit_no_update", "UPDATE", "audit"),
    _deny("audit_no_delete", "DELETE", "audit"),
    _deny("audit_ordered", "INSERT", "audit",
          "NEW.at IS NOT (SELECT high_water FROM clock_high_water WHERE id = 1)"
          " OR NEW.at < COALESCE((SELECT MAX(at) FROM audit), '')"),
)

_AUTOINDEXES = ("sqlite_autoindex_meta_1", "sqlite_autoindex_command_evidence_1",
                "sqlite_autoindex_command_evidence_2", "sqlite_autoindex_command_evidence_3",
                "sqlite_autoindex_revocations_1")
_SQLITE_SEQUENCE = ("sqlite_sequence", "CREATE TABLE sqlite_sequence(name,seq)")

EXPECTED_SCHEMA = frozenset(
    [("table", name, sql) for name, sql in _TABLES]
    + [("trigger", name, sql) for name, sql in _TRIGGERS]
    + [("index", name, None) for name in _AUTOINDEXES]
    + [("table",) + _SQLITE_SEQUENCE])


# ---------------------------------------------------------------------------
# Results and records (immutable, never authorizing)
# ---------------------------------------------------------------------------

class RetirementLedgerRefused(ValueError):
    """Refused or failed. Carries only a stable code (no path, no content)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Refused(Exception):
    def __init__(self, *codes: str):
        super().__init__(codes[0])
        self.codes = codes


@dataclass(frozen=True)
class RetirementLedgerResult:
    """Outcome of ONE explicit ledger operation: facts, never a permission."""

    schema: str
    operation: str
    status: str
    reason_codes: tuple
    command_id: Optional[str] = None
    command_message_digest: Optional[str] = None
    signature_reverified: bool = False
    audit_seq: Optional[int] = None
    clock_high_water_mark: Optional[str] = None
    limitations: tuple = field(default=LEDGER_LIMITATIONS, init=False)
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)
    branch_deletion_authorized: bool = field(default=False, init=False)
    issued: bool = field(default=False, init=False)
    consumed: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)
    file_acl_verified: bool = field(default=False, init=False)
    clock_attested: bool = field(default=False, init=False)
    human_review_required: bool = field(default=True, init=False)


@dataclass(frozen=True)
class RecordedRetirementCommandEvidence:
    """Immutable evidence that a command re-verified at `recorded_at`. The
    window is data; `record_state` is RECORDED_NON_AUTHORIZING or REVOKED."""

    record_version: str
    evidence_kind: str
    record_state: str
    domain: str
    host_id_label: str
    command_id: str
    nonce: str
    key_id: str
    director_id: str
    proposal_digest: str
    scope_digest: str
    target_identity_digest: str
    command_message_digest: str
    issued_at: str
    expires_at: str
    recorded_at: str
    revocation_reason_code: Optional[str]
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)
    branch_deletion_authorized: bool = field(default=False, init=False)
    issued: bool = field(default=False, init=False)
    consumed: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)


@dataclass(frozen=True)
class RetirementAuditEvent:
    seq: int
    at: str
    event: str
    code: str
    command_id: Optional[str]
    digest: Optional[str]


# ---------------------------------------------------------------------------
# Path provenance (labels and point-in-time checks, never host identity)
# ---------------------------------------------------------------------------

def _check_path_text(path) -> str:
    if isinstance(path, Path):
        path = str(path)
    if not rha._is_text(path) or rha._URI_RE.match(path) or not os.path.isabs(path):
        raise _Refused(RLG_PATH_INVALID)
    if os.name == "nt":
        drive = os.path.splitdrive(path)[0]
        # Drive-letter paths only: no UNC/network, device (\\?\, \\.\) or stream (a:b) paths.
        if not re.fullmatch(r"[A-Za-z]:", drive) or ":" in path[2:]:
            raise _Refused(RLG_PATH_INVALID)
    if any(p in (".", "..") for p in rha._components(path)) or path.endswith(("/", "\\")):
        raise _Refused(RLG_PATH_INVALID)
    path = os.path.normpath(path)
    if not os.path.basename(path).endswith(LEDGER_FILENAME_SUFFIX) \
            or os.path.basename(path) == LEDGER_FILENAME_SUFFIX:
        raise _Refused(RLG_PATH_INVALID)
    return path


def _forbidden_roots(roots) -> tuple:
    if isinstance(roots, (str, bytes, Path)) or not isinstance(roots, (tuple, list)) or not roots:
        raise _Refused(RLG_ROOTS_INVALID)
    out = [str(_REPOSITORY_ROOT)]
    for root in roots:
        root = str(root) if isinstance(root, Path) else root
        if not rha._is_text(root) or not os.path.isabs(root):
            raise _Refused(RLG_ROOTS_INVALID)
        out += [os.path.normpath(root), os.path.realpath(root)]
    return tuple(out)


def _check_location(path: str, forbidden_roots) -> None:
    """Outside every forbidden root and repository, inside an existing,
    non-aliased directory chain with no group/world-writable parent."""
    roots = _forbidden_roots(forbidden_roots)
    real = os.path.realpath(path)
    if any(rha._within(candidate, root) for candidate in (path, real) for root in roots):
        raise _Refused(RLG_PATH_FORBIDDEN_ROOT)
    parent = os.path.dirname(path)
    try:
        pst = os.lstat(parent)
    except FileNotFoundError:
        raise _Refused(RLG_PARENT_MISSING) from None
    except OSError:
        raise _Refused(RLG_STORAGE_FAILED) from None
    if not rha._is_alias(pst) and not stat.S_ISDIR(pst.st_mode):
        raise _Refused(RLG_PARENT_MISSING)
    if os.name == "posix" and pst.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _Refused(RLG_PATH_INSECURE)
    if os.path.normcase(os.path.realpath(parent)) != os.path.normcase(parent):
        raise _Refused(RLG_PATH_ALIAS)
    directory = parent
    while True:
        try:
            dst = os.lstat(directory)
        except OSError:
            raise _Refused(RLG_STORAGE_FAILED) from None
        if rha._is_alias(dst):
            raise _Refused(RLG_PATH_ALIAS)
        if rha._mode_insecure(dst, directory=True):
            raise _Refused(RLG_PATH_INSECURE)
        if os.path.lexists(os.path.join(directory, ".git")):
            raise _Refused(RLG_PATH_INSIDE_REPOSITORY)
        above = os.path.dirname(directory)
        if above == directory:
            break
        directory = above


def _check_options(host_id, require_verified_acl) -> None:
    if type(require_verified_acl) is not bool:
        raise _Refused(RLG_ARGUMENT_INVALID)
    if require_verified_acl:
        raise _Refused(RLG_ACL_UNVERIFIABLE)   # nothing here can inspect ACLs
    if type(host_id) is not str or not rha._LABEL_RE.fullmatch(host_id):
        raise _Refused(RLG_HOST_ID_INVALID)


def _existing_file(path: str):
    """lstat of the ledger: a single-link regular file that is not an alias."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise _Refused(RLG_PATH_MISSING) from None
    except OSError:
        raise _Refused(RLG_STORAGE_FAILED) from None
    if rha._is_alias(st) or os.path.normcase(os.path.realpath(path)) != os.path.normcase(path):
        raise _Refused(RLG_PATH_ALIAS)
    if not stat.S_ISREG(st.st_mode):
        raise _Refused(RLG_NOT_REGULAR_FILE)
    if st.st_nlink != 1:
        raise _Refused(RLG_PATH_ALIAS)
    if rha._mode_insecure(st, directory=False):
        raise _Refused(RLG_PATH_INSECURE)
    return st


def _check_header(path: str, st) -> None:
    """Reads (never writes) the 100-byte SQLite header of the checked file:
    magic, rollback-journal (non-WAL) format, application id, user version."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise _Refused(RLG_STORAGE_FAILED) from None
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            raise _Refused(RLG_FILE_CHANGED)
        header = os.read(fd, _SQLITE_HEADER_BYTES)
    except OSError:
        raise _Refused(RLG_STORAGE_FAILED) from None
    finally:
        os.close(fd)
    if len(header) != _SQLITE_HEADER_BYTES or not header.startswith(_SQLITE_MAGIC) \
            or int.from_bytes(header[68:72], "big") != LEDGER_APPLICATION_ID:
        raise _Refused(RLG_NOT_A_RETIREMENT_LEDGER)
    page_size = int.from_bytes(header[16:18], "big")
    page_size = 65536 if page_size == 1 else page_size
    if header[18] != 1 or header[19] != 1 or page_size < 512 or fst.st_size % page_size:
        raise _Refused(RLG_SCHEMA_INVALID)
    if int.from_bytes(header[60:64], "big") != LEDGER_USER_VERSION:
        raise _Refused(RLG_SCHEMA_UNSUPPORTED)


def _check_no_wal_files(path: str) -> None:
    if any(os.path.lexists(path + suffix) for suffix in ("-wal", "-shm")):
        raise _Refused(RLG_SIDE_FILE_PRESENT)


# ---------------------------------------------------------------------------
# SQLite plumbing
# ---------------------------------------------------------------------------

def _sqlite_uri(path: str, mode: str) -> str:
    text = path.replace(os.sep, "/")
    if not text.startswith("/"):
        text = "/" + text
    encoded = "".join(ch if ch in _URI_SAFE else "".join(f"%{b:02X}" for b in ch.encode("utf-8")) for ch in text)
    return f"file://{encoded}?mode={mode}"


def _storage_code(exc: sqlite3.Error) -> str:
    code = getattr(exc, "sqlite_errorcode", None)
    if code == _SQLITE_READONLY_ROLLBACK:
        return RLG_INTERRUPTED_WRITE
    primary = code & 0xFF if type(code) is int else None
    if primary in (_SQLITE_BUSY, _SQLITE_LOCKED):
        return RLG_BUSY
    if primary in (_SQLITE_CORRUPT, _SQLITE_NOTADB):
        return RLG_CORRUPT
    if isinstance(exc, sqlite3.IntegrityError):
        return RLG_LEDGER_INCONSISTENT
    return RLG_STORAGE_FAILED


def _connect(path: str, mode: str, timeout: float) -> sqlite3.Connection:
    """`mode` is "ro" (SQLite read-only, also query_only) or "rw" (cannot
    create the file). Never "rwc"."""
    if mode not in ("ro", "rw"):
        raise ValueError(mode)
    con = sqlite3.connect(_sqlite_uri(path, mode), uri=True, timeout=timeout, isolation_level=None)
    try:
        con.execute("PRAGMA trusted_schema = OFF")
        if mode == "ro":
            con.execute("PRAGMA query_only = ON")
        else:
            con.execute("PRAGMA synchronous = FULL")
    except BaseException:
        con.close()
        raise
    return con


def _stamp(instant: datetime) -> str:
    return instant.strftime(_STAMP_FORMAT)


def _instant(text) -> Optional[datetime]:
    if type(text) is not str or not _STAMP_RE.fullmatch(text):
        return None
    try:
        value = datetime.strptime(text, _STAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return value if _stamp(value) == text else None


def _read_clock(clock) -> datetime:
    """The caller's clock, read once: an exact UTC datetime in a plausible
    range. Not trusted time; a broken clock is a refusal."""
    if not callable(clock):
        raise _Refused(RLG_CLOCK_INVALID)
    try:
        now = clock()
    except Exception:  # noqa: BLE001 - a failing clock is a refusal
        raise _Refused(RLG_CLOCK_INVALID) from None
    if type(now) is not datetime or now.tzinfo is not timezone.utc:
        raise _Refused(RLG_CLOCK_INVALID)
    if not MIN_PLAUSIBLE_UTC <= now < MAX_PLAUSIBLE_UTC:
        raise _Refused(RLG_CLOCK_IMPLAUSIBLE)
    return now


def _validate(con: sqlite3.Connection, host_id: str) -> str:
    """Exact schema, metadata, host binding and invariants. Read-only.
    Returns the current high-water mark."""
    if con.execute("PRAGMA application_id").fetchone() != (LEDGER_APPLICATION_ID,):
        raise _Refused(RLG_NOT_A_RETIREMENT_LEDGER)
    if con.execute("PRAGMA user_version").fetchone() != (LEDGER_USER_VERSION,):
        raise _Refused(RLG_SCHEMA_UNSUPPORTED)
    if con.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise _Refused(RLG_CORRUPT)
    master = con.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    if len(master) != len(EXPECTED_SCHEMA) or frozenset(master) != EXPECTED_SCHEMA:
        raise _Refused(RLG_SCHEMA_INVALID)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    if meta.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise _Refused(RLG_SCHEMA_UNSUPPORTED)
    if set(meta) != {"schema_version", "domain", "host_id", "provisioned_at"} or meta["domain"] != LEDGER_DOMAIN \
            or _instant(meta["provisioned_at"]) is None:
        raise _Refused(RLG_LEDGER_INCONSISTENT)
    if meta["host_id"] != host_id:
        raise _Refused(RLG_HOST_MISMATCH)
    rows = con.execute("SELECT high_water FROM clock_high_water").fetchall()
    if len(rows) != 1 or _instant(rows[0][0]) is None or rows[0][0] < meta["provisioned_at"]:
        raise _Refused(RLG_LEDGER_INCONSISTENT)
    high_water = rows[0][0]
    checks = (
        ("SELECT COUNT(*) FROM audit WHERE event = ?", (EVENT_LEDGER_PROVISIONED,), 1),
        ("SELECT event FROM audit ORDER BY seq LIMIT 1", (), EVENT_LEDGER_PROVISIONED),
        ("SELECT at FROM audit ORDER BY seq LIMIT 1", (), meta["provisioned_at"]),
        ("SELECT COUNT(*) FROM audit WHERE at > ?", (high_water,), 0),
        ("SELECT COUNT(*) FROM audit a JOIN audit b ON b.seq > a.seq AND b.at < a.at", (), 0),
        ("SELECT COUNT(*) FROM command_evidence WHERE recorded_at > ? OR host_id <> ?", (high_water, host_id), 0),
        ("SELECT COUNT(*) FROM revocations WHERE revoked_at > ? OR host_id <> ?", (high_water, host_id), 0),
        ("SELECT (SELECT COUNT(*) FROM command_evidence)"
         " - (SELECT COUNT(*) FROM audit WHERE event = ?)", (EVENT_COMMAND_EVIDENCE_RECORDED,), 0),
        ("SELECT (SELECT COUNT(*) FROM revocations)"
         " - (SELECT COUNT(*) FROM audit WHERE event = ?)", (EVENT_COMMAND_REVOKED,), 0),
        ("SELECT COUNT(*) FROM command_evidence c JOIN revocations r ON r.command_id = c.command_id"
         " WHERE r.revoked_at < c.recorded_at", (), 0),
    )
    for sql, args, expected in checks:
        if con.execute(sql, args).fetchone() != (expected,):
            raise _Refused(RLG_LEDGER_INCONSISTENT)
    return high_water


def _refused(operation: str, codes) -> RetirementLedgerResult:
    return RetirementLedgerResult(RESULT_SCHEMA, operation, STATUS_REFUSED, tuple(codes))


# ---------------------------------------------------------------------------
# Explicit provisioning, opening and recovery
# ---------------------------------------------------------------------------

def provision(path, *, host_id: str, forbidden_roots, clock, require_verified_acl: bool = False
              ) -> RetirementLedgerResult:
    """The ONLY way a ledger file comes into existence: created exclusively
    at one explicit path, never over an existing file or side file. Returns a
    result (never raises); the new ledger holds no command evidence."""
    try:
        _check_options(host_id, require_verified_acl)
        path = _check_path_text(path)
        _check_location(path, forbidden_roots)
        if os.path.lexists(path) or any(os.path.lexists(path + s) for s in _SIDE_SUFFIXES):
            raise _Refused(RLG_PATH_EXISTS)
        now = _read_clock(clock)
        return _provision(path, host_id, _stamp(now))
    except _Refused as exc:
        return _refused(OP_PROVISION, exc.codes)
    except Exception:  # noqa: BLE001 - nothing unexpected is ever a success
        return _refused(OP_PROVISION, (RLG_INTERNAL_ERROR,))


def _provision(path: str, host_id: str, now: str) -> RetirementLedgerResult:
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise _Refused(RLG_PATH_EXISTS) from None
    except OSError:
        raise _Refused(RLG_STORAGE_FAILED) from None
    try:
        created = os.fstat(fd)
        try:
            con = _connect(path, "rw", BUSY_TIMEOUT_SECONDS)
        except sqlite3.Error as exc:
            raise _Refused(_storage_code(exc)) from None
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                for _name, sql in _TABLES:
                    con.execute(sql)
                con.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", (
                    ("schema_version", LEDGER_SCHEMA_VERSION), ("domain", LEDGER_DOMAIN),
                    ("host_id", host_id), ("provisioned_at", now)))
                con.execute("INSERT INTO clock_high_water (id, high_water) VALUES (1, ?)", (now,))
                seq = con.execute("INSERT INTO audit (at, event, code) VALUES (?, ?, ?)",
                                  (now, EVENT_LEDGER_PROVISIONED, LEDGER_SCHEMA_VERSION)).lastrowid
                for _name, sql in _TRIGGERS:
                    con.execute(sql)
                con.execute(f"PRAGMA application_id = {LEDGER_APPLICATION_ID}")
                con.execute(f"PRAGMA user_version = {LEDGER_USER_VERSION}")
                _validate(con, host_id)
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        except sqlite3.Error as exc:
            raise _Refused(_storage_code(exc)) from None
        finally:
            con.close()
        st = _existing_file(path)
        if (st.st_dev, st.st_ino) != (created.st_dev, created.st_ino):
            raise _Refused(RLG_FILE_CHANGED)
    finally:
        os.close(fd)
    return RetirementLedgerResult(RESULT_SCHEMA, OP_PROVISION, STATUS_PROVISIONED_EMPTY, (),
                                  audit_seq=seq, clock_high_water_mark=now)


_HANDLE_TOKEN = object()


def open_existing(path, *, host_id: str, forbidden_roots, require_verified_acl: bool = False,
                  busy_timeout_seconds: float = BUSY_TIMEOUT_SECONDS) -> "RetirementLedger":
    """Opens ONE previously provisioned ledger strictly read-only and
    validates it. Creates, migrates and repairs nothing. Raises
    RetirementLedgerRefused with a stable code."""
    try:
        _check_options(host_id, require_verified_acl)
        if type(busy_timeout_seconds) not in (int, float) \
                or not 0 <= busy_timeout_seconds <= MAX_BUSY_TIMEOUT_SECONDS:
            raise _Refused(RLG_ARGUMENT_INVALID)
        path = _check_path_text(path)
        _check_location(path, forbidden_roots)
        st = _existing_file(path)
        ledger = RetirementLedger(_HANDLE_TOKEN, path, host_id, (st.st_dev, st.st_ino), float(busy_timeout_seconds))
        ledger._read(lambda con, high_water: None)
        return ledger
    except _Refused as exc:
        raise RetirementLedgerRefused(exc.codes[0]) from None


def recover_interrupted_write(path, *, host_id: str, forbidden_roots,
                              busy_timeout_seconds: float = BUSY_TIMEOUT_SECONDS) -> RetirementLedgerResult:
    """Explicit writer: lets SQLite roll back a hot journal left by a crashed
    write (restoring the last committed state), then validates. Adds and
    changes no row. Never raises."""
    try:
        _check_options(host_id, False)
        if type(busy_timeout_seconds) not in (int, float) \
                or not 0 <= busy_timeout_seconds <= MAX_BUSY_TIMEOUT_SECONDS:
            raise _Refused(RLG_ARGUMENT_INVALID)
        path = _check_path_text(path)
        _check_location(path, forbidden_roots)
        st = _existing_file(path)
        _check_header(path, st)
        _check_no_wal_files(path)
        journal = path + "-journal"
        had_journal = os.path.lexists(journal)
        try:
            con = _connect(path, "rw", float(busy_timeout_seconds))
        except sqlite3.Error as exc:
            raise _Refused(_storage_code(exc)) from None
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                high_water = _validate(con, host_id)
            finally:
                con.execute("ROLLBACK")
        except sqlite3.Error as exc:
            raise _Refused(_storage_code(exc)) from None
        finally:
            con.close()
        after = _existing_file(path)
        if (after.st_dev, after.st_ino) != (st.st_dev, st.st_ino):
            raise _Refused(RLG_FILE_CHANGED)
        rolled_back = had_journal and not os.path.lexists(journal)
        return RetirementLedgerResult(
            RESULT_SCHEMA, OP_RECOVER_INTERRUPTED_WRITE,
            STATUS_INTERRUPTED_WRITE_ROLLED_BACK if rolled_back else STATUS_NO_INTERRUPTED_WRITE, (),
            clock_high_water_mark=high_water)
    except _Refused as exc:
        return _refused(OP_RECOVER_INTERRUPTED_WRITE, exc.codes)
    except Exception:  # noqa: BLE001
        return _refused(OP_RECOVER_INTERRUPTED_WRITE, (RLG_INTERNAL_ERROR,))


# ---------------------------------------------------------------------------
# The ledger handle
# ---------------------------------------------------------------------------

_EVIDENCE_COLUMNS = ("record_version, evidence_kind, record_state, domain, host_id, command_id, nonce, key_id,"
                     " director_id, proposal_digest, scope_digest, target_identity_digest, command_message_digest,"
                     " issued_at, expires_at, recorded_at")
_VERIFIED_FLAGS = (("authorizes_action", False), ("deletion_authorized", False),
                   ("branch_deletion_authorized", False), ("issued", False), ("consumed", False),
                   ("host_identity_authenticated", False), ("queue_scope_attested", False),
                   ("replay_protection_available", False), ("human_review_required", True))


class RetirementLedger:
    """Handle to ONE provisioned ledger, obtained only from `open_existing`.
    Holds no connection: each call opens a fresh one (thread and process
    safe) after re-checking that the path is still the same file."""

    def __init__(self, token, path: str, host_id: str, identity: tuple, busy_timeout: float):
        if token is not _HANDLE_TOKEN:
            raise TypeError("use open_existing()")
        self._path, self._host_id, self._identity, self._timeout = path, host_id, identity, busy_timeout

    @property
    def host_id_label(self) -> str:
        return self._host_id

    def _check_same_file(self) -> None:
        st = _existing_file(self._path)
        if (st.st_dev, st.st_ino) != self._identity:
            raise _Refused(RLG_FILE_CHANGED)
        _check_header(self._path, st)
        _check_no_wal_files(self._path)

    def _read(self, work):
        """`work(con, high_water)` on a SQLite read-only connection inside a
        deferred read transaction. Writes nothing; refusals raise."""
        self._check_same_file()
        try:
            con = _connect(self._path, "ro", self._timeout)
        except sqlite3.Error as exc:
            raise _Refused(_storage_code(exc)) from None
        try:
            con.execute("BEGIN DEFERRED")
            try:
                return work(con, _validate(con, self._host_id))
            finally:
                con.execute("ROLLBACK")
        except sqlite3.Error as exc:
            raise _Refused(_storage_code(exc)) from None
        finally:
            con.close()

    def _query(self, work):
        try:
            return self._read(work)
        except _Refused as exc:
            raise RetirementLedgerRefused(exc.codes[0]) from None

    def _write(self, operation: str, clock, work) -> RetirementLedgerResult:
        """ONE `BEGIN IMMEDIATE` on a `mode=rw` connection. The clock is read
        under the write lock and checked against the durable mark;
        `work(con, now, high_water)` checks and returns `commit(con, stamp)`,
        which runs after the mark is advanced in the same transaction. Any
        refusal or error rolls everything back."""
        try:
            self._check_same_file()
            try:
                con = _connect(self._path, "rw", self._timeout)
            except sqlite3.Error as exc:
                raise _Refused(_storage_code(exc)) from None
            try:
                con.execute("BEGIN IMMEDIATE")
                try:
                    high_water = _validate(con, self._host_id)
                    now = _read_clock(clock)
                    stamp = _stamp(now)
                    if stamp < high_water:
                        raise _Refused(RLG_CLOCK_REGRESSION)
                    commit = work(con, now, high_water)
                    con.execute("UPDATE clock_high_water SET high_water = ? WHERE id = 1", (stamp,))
                    outcome = commit(con, stamp)
                    _validate(con, self._host_id)
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
                try:
                    con.execute("COMMIT")
                except sqlite3.Error:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise
            except sqlite3.Error as exc:
                raise _Refused(_storage_code(exc)) from None
            finally:
                con.close()
            return outcome
        except _Refused as exc:
            return _refused(operation, exc.codes)
        except Exception:  # noqa: BLE001 - nothing unexpected is ever recorded
            return _refused(operation, (RLG_INTERNAL_ERROR,))

    # Read-only queries ---------------------------------------------------
    def get_command(self, command_id: str) -> Optional[RecordedRetirementCommandEvidence]:
        """The recorded evidence of `command_id` (state REVOKED when a
        tombstone exists), or None. Read-only."""
        if type(command_id) is not str or not rha._LABEL_RE.fullmatch(command_id):
            raise RetirementLedgerRefused(RLG_ARGUMENT_INVALID)

        def work(con, _high_water):
            row = con.execute(f"SELECT {_EVIDENCE_COLUMNS} FROM command_evidence WHERE command_id = ?",
                              (command_id,)).fetchone()
            if row is None:
                return None
            revoked = con.execute("SELECT reason_code FROM revocations WHERE command_id = ?",
                                  (command_id,)).fetchone()
            values = list(row)
            values[2] = RECORD_STATE_REVOKED if revoked else RECORD_STATE_RECORDED_NON_AUTHORIZING
            return RecordedRetirementCommandEvidence(*values, revocation_reason_code=revoked[0] if revoked else None)

        return self._query(work)

    def is_revoked(self, command_id: str) -> bool:
        """True when a tombstone exists (recorded or not). Read-only."""
        if type(command_id) is not str or not rha._LABEL_RE.fullmatch(command_id):
            raise RetirementLedgerRefused(RLG_ARGUMENT_INVALID)
        return self._query(lambda con, _hw: con.execute(
            "SELECT 1 FROM revocations WHERE command_id = ?", (command_id,)).fetchone() is not None)

    def audit_trail(self) -> tuple:
        """Every audit event in commit order. Read-only."""
        return self._query(lambda con, _hw: tuple(RetirementAuditEvent(*row) for row in con.execute(
            "SELECT seq, at, event, code, command_id, digest FROM audit ORDER BY seq").fetchall()))

    def clock_high_water_mark(self) -> str:
        """The durable mark (a caller-clock value, not attested time). Read-only."""
        return self._query(lambda con, high_water: high_water)

    # Explicit writes -----------------------------------------------------
    def record_reverified_command_evidence(self, envelope: bytes, *, config, proposal, clock, report=None,
                                           inventory_record=None) -> RetirementLedgerResult:
        """Re-verifies the signed 02b `envelope` inside the write transaction
        and records non-authorizing evidence of it once. Never raises."""
        op = OP_RECORD_REVERIFIED_COMMAND_EVIDENCE
        if type(envelope) is not bytes or type(config) is not rha.RetirementHostConfig:
            return _refused(op, (RLG_ARGUMENT_INVALID,))
        if config.host_id != self._host_id:
            return _refused(op, (RLG_HOST_MISMATCH,))
        if not rha.CRYPTO_AVAILABLE:
            return _refused(op, (RLG_CRYPTO_UNAVAILABLE,))
        recorded = {}

        def work(con, now, high_water):
            verification = rha.verify_retirement_command(
                envelope, config=config, proposal=proposal, now=now,
                trusted_high_water_mark=_instant(high_water), report=report, inventory_record=inventory_record)
            c = _reverified_command(verification, envelope, self._host_id)
            if con.execute("SELECT 1 FROM revocations WHERE command_id = ?", (c.command_id,)).fetchone():
                raise _Refused(RLG_COMMAND_REVOKED)
            for column, value, code in (("command_id", c.command_id, RLG_COMMAND_DUPLICATE),
                                        ("nonce", c.nonce, RLG_NONCE_REUSED),
                                        ("command_message_digest", verification.command_message_digest,
                                         RLG_MESSAGE_DUPLICATE)):
                if con.execute(f"SELECT 1 FROM command_evidence WHERE {column} = ?", (value,)).fetchone():
                    raise _Refused(code)
            recorded.update(command_id=c.command_id, digest=verification.command_message_digest)

            def commit(con, stamp):
                try:
                    con.execute(
                        f"INSERT INTO command_evidence ({_EVIDENCE_COLUMNS})"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (RECORD_VERSION, EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING,
                         RECORD_STATE_RECORDED_NON_AUTHORIZING, LEDGER_DOMAIN, self._host_id, c.command_id, c.nonce,
                         c.key_id, c.director_id, c.proposal_digest, c.scope_digest, c.target_identity_digest,
                         verification.command_message_digest, c.issued_at, c.expires_at, stamp))
                except sqlite3.IntegrityError:
                    raise _Refused(RLG_COMMAND_DUPLICATE) from None
                seq = _audit(con, stamp, EVENT_COMMAND_EVIDENCE_RECORDED,
                             EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING, c.command_id,
                             verification.command_message_digest)
                return RetirementLedgerResult(
                    RESULT_SCHEMA, op, STATUS_RECORDED_NON_AUTHORIZING, (), command_id=c.command_id,
                    command_message_digest=verification.command_message_digest, signature_reverified=True,
                    audit_seq=seq, clock_high_water_mark=stamp)

            return commit

        return self._write(op, clock, work)

    def revoke_command(self, command_id: str, reason_code: str, *, clock) -> RetirementLedgerResult:
        """One-way tombstone for `command_id`, recorded or not (yet). A
        tombstoned id can never be recorded; there is no un-revoke."""
        op = OP_REVOKE_COMMAND
        if type(command_id) is not str or not rha._LABEL_RE.fullmatch(command_id):
            return _refused(op, (RLG_ARGUMENT_INVALID,))
        if type(reason_code) is not str or reason_code not in REVOCATION_REASONS:
            return _refused(op, (RLG_REASON_INVALID,))

        def work(con, now, high_water):
            if con.execute("SELECT 1 FROM revocations WHERE command_id = ?", (command_id,)).fetchone():
                raise _Refused(RLG_ALREADY_REVOKED)

            def commit(con, stamp):
                con.execute("INSERT INTO revocations (command_id, host_id, reason_code, revoked_at)"
                            " VALUES (?, ?, ?, ?)", (command_id, self._host_id, reason_code, stamp))
                digest = con.execute("SELECT command_message_digest FROM command_evidence WHERE command_id = ?",
                                     (command_id,)).fetchone()
                seq = _audit(con, stamp, EVENT_COMMAND_REVOKED, reason_code, command_id, digest[0] if digest else None)
                return RetirementLedgerResult(RESULT_SCHEMA, op, STATUS_REVOKED, (), command_id=command_id,
                                              audit_seq=seq, clock_high_water_mark=stamp)

            return commit

        return self._write(op, clock, work)


def _reverified_command(verification, envelope: bytes, host_id: str):
    """The command of a verification that is exactly what the 02b verifier
    returns for a good signature, cross-checked against the envelope."""
    if type(verification) is not rha.RetirementCommandVerification:
        raise _Refused(RLG_VERIFICATION_INCONSISTENT)
    if verification.status == rha.STATUS_REFUSED:
        codes = verification.reason_codes
        known = type(codes) is tuple and len(codes) == 1 and codes[0] in rha.VERIFICATION_REFUSAL_CODES
        raise _Refused(RLG_VERIFICATION_REFUSED, *(codes if known else ()))
    if verification.status != rha.STATUS_SIGNATURE_VERIFIED_NON_AUTHORIZING or verification.reason_codes != () \
            or verification.signature_verified is not True or verification.schema != rha.VERIFICATION_SCHEMA \
            or verification.limitations != rha.VERIFICATION_LIMITATIONS \
            or any(getattr(verification, name) is not value for name, value in _VERIFIED_FLAGS):
        raise _Refused(RLG_VERIFICATION_INCONSISTENT)
    try:
        c = rha.parse_retirement_envelope(envelope).command
    except rha.RetirementEnvelopeRefused:
        raise _Refused(RLG_VERIFICATION_INCONSISTENT) from None
    digest = hashlib.sha256(rha.canonical_command_message(c)).hexdigest()
    if (verification.command_id, verification.key_id, verification.director_id, verification.host_id_label,
            verification.proposal_digest, verification.command_message_digest) \
            != (c.command_id, c.key_id, c.director_id, c.host_id, c.proposal_digest, digest) \
            or c.host_id != host_id or c.format != LEDGER_DOMAIN:
        raise _Refused(RLG_VERIFICATION_INCONSISTENT)
    return c


def _audit(con, stamp: str, event: str, code: str, command_id: Optional[str], digest: Optional[str]) -> int:
    return con.execute("INSERT INTO audit (at, event, code, command_id, digest) VALUES (?, ?, ?, ?, ?)",
                       (stamp, event, code, command_id, digest)).lastrowid
