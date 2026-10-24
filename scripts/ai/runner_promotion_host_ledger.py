"""FCP-3B-2B2-HOST-01: durable single-use ledger of the trusted promotion host (NOT LIVE).

The persistent half of the `TrustedPromotionHost` contract of
`runner_promotion_executor`: the `LeasePort` and `SingleUseLedgerPort`
methods, plus the durable registry of authenticated human commands, their
revocations, the merge-send journal and an append-only audit trail. It is a
library for a FUTURE isolated host process; nothing here is deployed, and
this delivery produces no live promotion (`rpe.PRODUCTION_PROMOTION_CAPABLE`
stays False).

Storage
-------
One SQLite file, opened with a NEW connection per operation (safe across
threads and processes), every operation inside ONE `BEGIN IMMEDIATE`
transaction that commits atomically or rolls back entirely. UNIQUE
constraints make each command id, nonce and operation single-use; triggers
make the audit trail append-only and forbid any transition back from a
consumed, finalized or uncertain state. The path must be absolute and
outside the repository and every untrusted root (worktrees, provider
directories). This host store is NOT the CRM/ERP database and is never used
by Flet or the ERP. File ACLs, WAL or journal mode choices, backups and the
OS account owning the file belong to the isolated host process: a local
SQLite file by itself proves NO isolation, and whoever can write the file can
rewrite it.

Single use
----------
lease (owner + expiry) -> registered human command -> reservation (one per
operation, one per command) -> one permit -> consumption (requires the
reservation RESERVED, the permit unexpired, the command neither revoked nor
expired and the lease still held by this owner) -> merge-send journal entry
written BEFORE the request leaves the host -> result or UNCERTAIN ->
finalization. A consumed permission is never regenerated: a second
reservation of the same operation reports RESERVATION_ALREADY_CONSUMED, a
second send is refused, and after a crash `recover_interrupted_merges` turns
every unfinished send into UNCERTAIN (never retried) instead of reusable.
Refusals carry stable codes only, never stored values.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import runner_promotion_executor as rpe
    from scripts.ai import runner_promotion_human_authorization as rha
    from scripts.ai import runner_promotion_pr_gate as rpg
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_promotion_executor as rpe  # type: ignore[no-redef]
    import runner_promotion_human_authorization as rha  # type: ignore[no-redef]
    import runner_promotion_pr_gate as rpg  # type: ignore[no-redef]


LEDGER_SCHEMA_VERSION = "fcp3b2b2-host-ledger-v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LEASE_RESOURCE = f"{rpg.CANONICAL_REPOSITORY}:{rpg.BASE_BRANCH}"
DEFAULT_LEASE_SECONDS = 300
PERMIT_TTL_SECONDS = 60
BUSY_TIMEOUT_SECONDS = 10.0

# Reservation states.
RES_RESERVED = "RESERVED"
RES_CONSUMED = "CONSUMED"
RES_FINALIZED = "FINALIZED"
# Merge-send journal states.
SEND_STARTED = "SENDING"
SEND_RESULT_RECORDED = "RESULT_RECORDED"
SEND_UNCERTAIN = "UNCERTAIN"

# Refusal codes.
LEDGER_PATH_INVALID = "LEDGER_PATH_INVALID"
LEDGER_PATH_UNTRUSTED = "LEDGER_PATH_UNTRUSTED"
LEDGER_SCHEMA_MISMATCH = "LEDGER_SCHEMA_MISMATCH"
LEDGER_STORAGE_FAILED = "LEDGER_STORAGE_FAILED"
LEDGER_CLOCK_INVALID = "LEDGER_CLOCK_INVALID"
LEDGER_ARGUMENT_INVALID = "LEDGER_ARGUMENT_INVALID"
LEDGER_LEASE_RESOURCE_INVALID = "LEDGER_LEASE_RESOURCE_INVALID"
LEDGER_LEASE_NOT_HELD = "LEDGER_LEASE_NOT_HELD"
LEDGER_LEASE_OWNER_MISMATCH = "LEDGER_LEASE_OWNER_MISMATCH"
LEDGER_COMMAND_DUPLICATE = "LEDGER_COMMAND_DUPLICATE"
LEDGER_COMMAND_UNKNOWN = "LEDGER_COMMAND_UNKNOWN"
LEDGER_COMMAND_REVOKED = "LEDGER_COMMAND_REVOKED"
LEDGER_COMMAND_EXPIRED = "LEDGER_COMMAND_EXPIRED"
LEDGER_RESERVATION_UNKNOWN = "LEDGER_RESERVATION_UNKNOWN"
LEDGER_RESERVATION_STATE = "LEDGER_RESERVATION_STATE"
LEDGER_BINDING_MISMATCH = "LEDGER_BINDING_MISMATCH"
LEDGER_PERMIT_DUPLICATE = "LEDGER_PERMIT_DUPLICATE"
LEDGER_PERMIT_UNKNOWN = "LEDGER_PERMIT_UNKNOWN"
LEDGER_PERMIT_EXPIRED = "LEDGER_PERMIT_EXPIRED"
LEDGER_MERGE_ALREADY_ATTEMPTED = "LEDGER_MERGE_ALREADY_ATTEMPTED"
LEDGER_MERGE_NOT_IN_FLIGHT = "LEDGER_MERGE_NOT_IN_FLIGHT"
LEDGER_FINAL_STATE_INVALID = "LEDGER_FINAL_STATE_INVALID"
LEDGER_ALREADY_FINALIZED = "LEDGER_ALREADY_FINALIZED"

_ID_RE = rpe._ID_RE
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS commands (
        command_id TEXT PRIMARY KEY, nonce TEXT NOT NULL UNIQUE, operation_id TEXT NOT NULL UNIQUE,
        request_fingerprint TEXT NOT NULL, key_id TEXT NOT NULL, director_id INTEGER NOT NULL,
        repository TEXT NOT NULL, pr_number INTEGER NOT NULL, base_sha TEXT NOT NULL, head_sha TEXT NOT NULL,
        action TEXT NOT NULL, issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, message BLOB NOT NULL,
        signature BLOB NOT NULL, registered_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS revocations (
        command_id TEXT PRIMARY KEY, revoked_at TEXT NOT NULL, reason TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS leases (
        resource TEXT PRIMARY KEY, lease_id TEXT NOT NULL UNIQUE, operation_id TEXT NOT NULL,
        owner TEXT NOT NULL, acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS reservations (
        reservation_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
        command_id TEXT NOT NULL UNIQUE REFERENCES commands(command_id),
        state TEXT NOT NULL CHECK (state IN ('RESERVED', 'CONSUMED', 'FINALIZED')),
        final_state TEXT, created_at TEXT NOT NULL, consumed_at TEXT, finalized_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS permits (
        permit_id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL UNIQUE REFERENCES reservations(reservation_id),
        operation_id TEXT NOT NULL, command_id TEXT NOT NULL, head_sha TEXT NOT NULL, base_sha TEXT NOT NULL,
        issued_at TEXT NOT NULL, expires_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS merge_sends (
        operation_id TEXT PRIMARY KEY, permit_id TEXT NOT NULL UNIQUE REFERENCES permits(permit_id),
        state TEXT NOT NULL CHECK (state IN ('SENDING', 'RESULT_RECORDED', 'UNCERTAIN')),
        response_status TEXT, started_at TEXT NOT NULL, recorded_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS audit (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, operation_id TEXT, event TEXT NOT NULL,
        code TEXT NOT NULL)""",
    # Append-only history and one-way states: SQL itself refuses a reset.
    """CREATE TRIGGER IF NOT EXISTS audit_append_only_update BEFORE UPDATE ON audit
        BEGIN SELECT RAISE(ABORT, 'append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_append_only_delete BEFORE DELETE ON audit
        BEGIN SELECT RAISE(ABORT, 'append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS commands_no_delete BEFORE DELETE ON commands
        BEGIN SELECT RAISE(ABORT, 'single-use'); END""",
    """CREATE TRIGGER IF NOT EXISTS revocations_no_delete BEFORE DELETE ON revocations
        BEGIN SELECT RAISE(ABORT, 'single-use'); END""",
    """CREATE TRIGGER IF NOT EXISTS reservations_no_delete BEFORE DELETE ON reservations
        BEGIN SELECT RAISE(ABORT, 'single-use'); END""",
    """CREATE TRIGGER IF NOT EXISTS reservations_one_way BEFORE UPDATE OF state ON reservations
        WHEN OLD.state = 'FINALIZED' OR (OLD.state = 'CONSUMED' AND NEW.state = 'RESERVED')
        BEGIN SELECT RAISE(ABORT, 'single-use'); END""",
    """CREATE TRIGGER IF NOT EXISTS permits_no_delete BEFORE DELETE ON permits
        BEGIN SELECT RAISE(ABORT, 'single-use'); END""",
    """CREATE TRIGGER IF NOT EXISTS merge_sends_no_delete BEFORE DELETE ON merge_sends
        BEGIN SELECT RAISE(ABORT, 'single-use'); END""",
    """CREATE TRIGGER IF NOT EXISTS merge_sends_one_way BEFORE UPDATE OF state ON merge_sends
        WHEN OLD.state <> 'SENDING' BEGIN SELECT RAISE(ABORT, 'single-use'); END""",
)


class HostLedgerRefused(Exception):
    """A ledger operation was refused or failed. Carries one stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RegisteredCommand:
    """An authenticated human command as registered by the host authority.
    `message` and `signature` are the exact signed bytes, kept so the
    authority can verify again before every use."""

    command_id: str
    nonce: str
    operation_id: str
    request_fingerprint: str
    key_id: str
    director_id: int
    repository: str
    pr_number: int
    base_sha: str
    head_sha: str
    action: str
    issued_at: str
    expires_at: str
    message: bytes
    signature: bytes


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    at: str
    operation_id: Optional[str]
    event: str
    code: str


class _Refused:
    """Returned from inside a transaction so the refusal's audit row commits
    before the refusal is raised."""

    def __init__(self, code):
        self.code = code


def _id_ok(value) -> bool:
    return type(value) is str and _ID_RE.fullmatch(value) is not None


def _digest_ok(value) -> bool:
    return type(value) is str and _DIGEST_RE.fullmatch(value) is not None


def _stamp(instant) -> str:
    return instant.strftime(_STAMP_FORMAT)


def _instant(text):
    return rha._timestamp(text)


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _ledger_path(path, untrusted_roots) -> Path:
    if not isinstance(path, (str, Path)) or str(path) in ("", ":memory:") or str(path).startswith("file:"):
        raise HostLedgerRefused(LEDGER_PATH_INVALID)
    raw = Path(path)
    if not raw.is_absolute():
        raise HostLedgerRefused(LEDGER_PATH_INVALID)
    resolved = raw.resolve()
    roots = (REPOSITORY_ROOT, *(Path(r).resolve() for r in untrusted_roots))
    if any(_inside(resolved, root) for root in roots):
        raise HostLedgerRefused(LEDGER_PATH_UNTRUSTED)
    if not resolved.parent.is_dir() or (resolved.exists() and not resolved.is_file()):
        raise HostLedgerRefused(LEDGER_PATH_INVALID)
    return resolved


class HostLedger:
    """Durable lease and single-use ledger. `owner` is this host process's
    opaque identity; leases are held and released only by their owner.
    Every public method is one atomic transaction on a fresh connection."""

    def __init__(self, path, *, owner: str, clock, lease_seconds: int = DEFAULT_LEASE_SECONDS,
                 untrusted_roots=()):
        self.path = _ledger_path(path, tuple(untrusted_roots))
        if not _id_ok(owner) or not callable(clock) or type(lease_seconds) is not int \
                or not 1 <= lease_seconds <= rpe.MAX_LEASE_SECONDS:
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)
        self.owner, self._clock, self.lease_seconds = owner, clock, lease_seconds
        self._transaction(self._ensure_schema)

    # Transactions -------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA synchronous = FULL")
        return con

    def _transaction(self, work):
        """Runs `work(con, now)` inside BEGIN IMMEDIATE; commits only if it
        returns, rolls back on any exception. A `_Refused` result commits its
        audit row and is raised afterwards."""
        now = self._now()
        try:
            con = self._connect()
        except sqlite3.Error:
            raise HostLedgerRefused(LEDGER_STORAGE_FAILED) from None
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                result = work(con, now)
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        except sqlite3.Error:
            raise HostLedgerRefused(LEDGER_STORAGE_FAILED) from None
        finally:
            con.close()
        if isinstance(result, _Refused):
            raise HostLedgerRefused(result.code)
        return result

    def _now(self):
        try:
            now = self._clock()
        except Exception:  # noqa: BLE001 - a broken clock is a refusal
            raise HostLedgerRefused(LEDGER_CLOCK_INVALID) from None
        if not rha._clock_ok(now):
            raise HostLedgerRefused(LEDGER_CLOCK_INVALID)
        return now.replace(microsecond=0)

    def _ensure_schema(self, con, now):
        for statement in _SCHEMA:
            con.execute(statement)
        row = con.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        if row is None:
            con.execute("INSERT INTO meta (key, value) VALUES ('schema', ?)", (LEDGER_SCHEMA_VERSION,))
            _audit(con, now, None, "LEDGER_CREATED", LEDGER_SCHEMA_VERSION)
        elif row[0] != LEDGER_SCHEMA_VERSION:
            return _Refused(LEDGER_SCHEMA_MISMATCH)
        return None

    def _refuse(self, con, now, operation_id, event, code):
        _audit(con, now, operation_id, event, code)
        return _Refused(code)

    def _live_lease(self, con, operation_id, now) -> bool:
        row = con.execute("SELECT owner, expires_at FROM leases WHERE operation_id = ? AND resource = ?",
                          (operation_id, LEASE_RESOURCE)).fetchone()
        return row is not None and row[0] == self.owner and now < _instant(row[1])

    # LeasePort ----------------------------------------------------------
    def acquire_lease(self, operation_id: str, resource: str) -> Optional[rpe.LeaseGrant]:
        """The exclusive lease of `repository:develop`, or None while another
        unexpired lease exists. An expired lease is taken over and audited."""
        if not _digest_ok(operation_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)
        if resource != LEASE_RESOURCE:
            raise HostLedgerRefused(LEDGER_LEASE_RESOURCE_INVALID)

        def work(con, now):
            row = con.execute("SELECT lease_id, expires_at FROM leases WHERE resource = ?", (resource,)).fetchone()
            if row is not None and now < _instant(row[1]):
                _audit(con, now, operation_id, "LEASE_BUSY", "LEASE_HELD_BY_OTHER")
                return None
            if row is not None:
                con.execute("DELETE FROM leases WHERE resource = ?", (resource,))
                _audit(con, now, operation_id, "LEASE_EXPIRED_TAKEOVER", "LEASE_EXPIRED")
            grant = rpe.LeaseGrant(lease_id=f"lease-{uuid.uuid4().hex}", operation_id=operation_id,
                                   resource=resource, acquired_at=_stamp(now),
                                   expires_at=_stamp(now + timedelta(seconds=self.lease_seconds)))
            con.execute("INSERT INTO leases (resource, lease_id, operation_id, owner, acquired_at, expires_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (resource, grant.lease_id, operation_id, self.owner,
                                                      grant.acquired_at, grant.expires_at))
            _audit(con, now, operation_id, "LEASE_ACQUIRED", "OK")
            return grant

        return self._transaction(work)

    def release_lease(self, lease_id: str) -> None:
        if not _id_ok(lease_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)

        def work(con, now):
            row = con.execute("SELECT owner, operation_id FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
            if row is None:
                return self._refuse(con, now, None, "LEASE_RELEASE_REFUSED", LEDGER_LEASE_NOT_HELD)
            if row[0] != self.owner:
                return self._refuse(con, now, row[1], "LEASE_RELEASE_REFUSED", LEDGER_LEASE_OWNER_MISMATCH)
            con.execute("DELETE FROM leases WHERE lease_id = ?", (lease_id,))
            _audit(con, now, row[1], "LEASE_RELEASED", "OK")
            return None

        self._transaction(work)

    # Command registry (used by the host authority) ---------------------
    def register_command(self, command: RegisteredCommand) -> None:
        """Registers an already authenticated command. Command id, nonce and
        operation are each usable once, ever; a revoked id never registers."""
        if type(command) is not RegisteredCommand or not _id_ok(command.command_id) \
                or not _digest_ok(command.operation_id) or type(command.message) is not bytes \
                or type(command.signature) is not bytes:
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)
        c = command

        def work(con, now):
            if con.execute("SELECT 1 FROM revocations WHERE command_id = ?", (c.command_id,)).fetchone():
                return self._refuse(con, now, c.operation_id, "COMMAND_REFUSED", LEDGER_COMMAND_REVOKED)
            try:
                con.execute(
                    "INSERT INTO commands (command_id, nonce, operation_id, request_fingerprint, key_id, director_id,"
                    " repository, pr_number, base_sha, head_sha, action, issued_at, expires_at, message, signature,"
                    " registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (c.command_id, c.nonce, c.operation_id, c.request_fingerprint, c.key_id, c.director_id,
                     c.repository, c.pr_number, c.base_sha, c.head_sha, c.action, c.issued_at, c.expires_at,
                     c.message, c.signature, _stamp(now)))
            except sqlite3.IntegrityError:
                return self._refuse(con, now, c.operation_id, "COMMAND_REFUSED", LEDGER_COMMAND_DUPLICATE)
            _audit(con, now, c.operation_id, "COMMAND_REGISTERED", "OK")
            return None

        self._transaction(work)

    def revoke_command(self, command_id: str, reason_code: str) -> None:
        """Durable revocation; allowed before the command is even registered."""
        if not _id_ok(command_id) or not _id_ok(reason_code):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)

        def work(con, now):
            con.execute("INSERT OR IGNORE INTO revocations (command_id, revoked_at, reason) VALUES (?, ?, ?)",
                        (command_id, _stamp(now), reason_code))
            row = con.execute("SELECT operation_id FROM commands WHERE command_id = ?", (command_id,)).fetchone()
            _audit(con, now, row[0] if row else None, "COMMAND_REVOKED", reason_code)
            return None

        self._transaction(work)

    def is_command_revoked(self, command_id: str) -> bool:
        return self._transaction(lambda con, now: con.execute(
            "SELECT 1 FROM revocations WHERE command_id = ?", (command_id,)).fetchone() is not None)

    def command_for_operation(self, operation_id: str) -> Optional[RegisteredCommand]:
        def work(con, now):
            row = con.execute(
                "SELECT command_id, nonce, operation_id, request_fingerprint, key_id, director_id, repository,"
                " pr_number, base_sha, head_sha, action, issued_at, expires_at, message, signature"
                " FROM commands WHERE operation_id = ?", (operation_id,)).fetchone()
            return None if row is None else RegisteredCommand(*row[:13], bytes(row[13]), bytes(row[14]))

        return self._transaction(work)

    # SingleUseLedgerPort -------------------------------------------------
    def reserve_single_use(self, operation_id: str, command_id: str) -> rpe.ReservationReceipt:
        """One reservation per operation and per command, under this owner's
        live lease. A second reservation of the operation is reported as
        already reserved or (after consumption or finalization) consumed."""
        if not _digest_ok(operation_id) or not _id_ok(command_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)

        def work(con, now):
            existing = con.execute("SELECT reservation_id, state FROM reservations WHERE operation_id = ?",
                                   (operation_id,)).fetchone()
            if existing is not None:
                status = rpe.RESERVATION_ALREADY_RESERVED if existing[1] == RES_RESERVED \
                    else rpe.RESERVATION_ALREADY_CONSUMED
                _audit(con, now, operation_id, "RESERVE_REPLAY", status)
                return rpe.ReservationReceipt(status, existing[0], operation_id, command_id)
            row = con.execute("SELECT operation_id FROM commands WHERE command_id = ?", (command_id,)).fetchone()
            if row is None or row[0] != operation_id:
                return self._refuse(con, now, operation_id, "RESERVE_REFUSED", LEDGER_COMMAND_UNKNOWN)
            if con.execute("SELECT 1 FROM revocations WHERE command_id = ?", (command_id,)).fetchone():
                return self._refuse(con, now, operation_id, "RESERVE_REFUSED", LEDGER_COMMAND_REVOKED)
            if not self._live_lease(con, operation_id, now):
                return self._refuse(con, now, operation_id, "RESERVE_REFUSED", LEDGER_LEASE_NOT_HELD)
            reservation_id = f"res-{uuid.uuid4().hex}"
            try:
                con.execute("INSERT INTO reservations (reservation_id, operation_id, command_id, state, created_at)"
                            " VALUES (?, ?, ?, ?, ?)", (reservation_id, operation_id, command_id, RES_RESERVED,
                                                        _stamp(now)))
            except sqlite3.IntegrityError:
                return self._refuse(con, now, operation_id, "RESERVE_REFUSED", LEDGER_COMMAND_DUPLICATE)
            _audit(con, now, operation_id, "RESERVED", "OK")
            return rpe.ReservationReceipt(rpe.RESERVATION_CREATED, reservation_id, operation_id, command_id)

        return self._transaction(work)

    def issue_operation_permit(self, operation_id: str, reservation_id: str,
                               command_id: str) -> rpe.OperationPermit:
        """The ONE permit of a RESERVED reservation, bound to the command's
        head and base SHAs, valid PERMIT_TTL_SECONDS."""
        if not _digest_ok(operation_id) or not _id_ok(reservation_id) or not _id_ok(command_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)

        def work(con, now):
            row = con.execute(
                "SELECT r.state, r.operation_id, r.command_id, c.head_sha, c.base_sha FROM reservations r"
                " JOIN commands c ON c.command_id = r.command_id WHERE r.reservation_id = ?",
                (reservation_id,)).fetchone()
            if row is None:
                return self._refuse(con, now, operation_id, "PERMIT_REFUSED", LEDGER_RESERVATION_UNKNOWN)
            if (row[1], row[2]) != (operation_id, command_id):
                return self._refuse(con, now, operation_id, "PERMIT_REFUSED", LEDGER_BINDING_MISMATCH)
            if row[0] != RES_RESERVED:
                return self._refuse(con, now, operation_id, "PERMIT_REFUSED", LEDGER_RESERVATION_STATE)
            if con.execute("SELECT 1 FROM revocations WHERE command_id = ?", (command_id,)).fetchone():
                return self._refuse(con, now, operation_id, "PERMIT_REFUSED", LEDGER_COMMAND_REVOKED)
            if not self._live_lease(con, operation_id, now):
                return self._refuse(con, now, operation_id, "PERMIT_REFUSED", LEDGER_LEASE_NOT_HELD)
            permit = rpe.OperationPermit(
                permit_id=f"permit-{uuid.uuid4().hex}", operation_id=operation_id, reservation_id=reservation_id,
                command_id=command_id, action=rpe.ACTION_MERGE_GITHUB_PR, head_sha=row[3], base_sha=row[4],
                issued_at=_stamp(now), expires_at=_stamp(now + timedelta(seconds=PERMIT_TTL_SECONDS)))
            try:
                con.execute("INSERT INTO permits (permit_id, reservation_id, operation_id, command_id, head_sha,"
                            " base_sha, issued_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (permit.permit_id, reservation_id, operation_id, command_id, permit.head_sha,
                             permit.base_sha, permit.issued_at, permit.expires_at))
            except sqlite3.IntegrityError:
                return self._refuse(con, now, operation_id, "PERMIT_REFUSED", LEDGER_PERMIT_DUPLICATE)
            _audit(con, now, operation_id, "PERMIT_ISSUED", "OK")
            return permit

        return self._transaction(work)

    def consume_single_use(self, reservation_id: str) -> rpe.ConsumptionReceipt:
        """RESERVED -> CONSUMED, exactly once, BEFORE any merge request. Any
        failed condition returns CONSUMPTION_REFUSED (audited) and changes
        nothing."""
        if not _id_ok(reservation_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)

        def work(con, now):
            row = con.execute(
                "SELECT r.state, r.operation_id, r.command_id, p.expires_at, c.expires_at FROM reservations r"
                " JOIN commands c ON c.command_id = r.command_id"
                " LEFT JOIN permits p ON p.reservation_id = r.reservation_id WHERE r.reservation_id = ?",
                (reservation_id,)).fetchone()
            if row is None:
                _audit(con, now, None, "CONSUME_REFUSED", LEDGER_RESERVATION_UNKNOWN)
                return rpe.ConsumptionReceipt(rpe.CONSUMPTION_REFUSED, reservation_id, "unknown")
            state, operation_id, command_id, permit_expires, command_expires = row
            code = None
            if state != RES_RESERVED:
                code = LEDGER_RESERVATION_STATE
            elif permit_expires is None:
                code = LEDGER_PERMIT_UNKNOWN
            elif now >= _instant(permit_expires):
                code = LEDGER_PERMIT_EXPIRED
            elif con.execute("SELECT 1 FROM revocations WHERE command_id = ?", (command_id,)).fetchone():
                code = LEDGER_COMMAND_REVOKED
            elif now >= _instant(command_expires):
                code = LEDGER_COMMAND_EXPIRED
            elif not self._live_lease(con, operation_id, now):
                code = LEDGER_LEASE_NOT_HELD
            if code is not None:
                _audit(con, now, operation_id, "CONSUME_REFUSED", code)
                return rpe.ConsumptionReceipt(rpe.CONSUMPTION_REFUSED, reservation_id, operation_id)
            con.execute("UPDATE reservations SET state = ?, consumed_at = ? WHERE reservation_id = ?",
                        (RES_CONSUMED, _stamp(now), reservation_id))
            _audit(con, now, operation_id, "CONSUMED", "OK")
            return rpe.ConsumptionReceipt(rpe.CONSUMED, reservation_id, operation_id)

        return self._transaction(work)

    def finalize_reservation(self, reservation_id: str, final_state: str) -> None:
        """Records the attempt's terminal state once. An unfinished merge send
        becomes UNCERTAIN; nothing becomes reusable."""
        if not _id_ok(reservation_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)
        if type(final_state) is not str or final_state not in rpe.TERMINAL_STATES:
            raise HostLedgerRefused(LEDGER_FINAL_STATE_INVALID)

        def work(con, now):
            row = con.execute("SELECT state, operation_id FROM reservations WHERE reservation_id = ?",
                              (reservation_id,)).fetchone()
            if row is None:
                return self._refuse(con, now, None, "FINALIZE_REFUSED", LEDGER_RESERVATION_UNKNOWN)
            if row[0] == RES_FINALIZED:
                return self._refuse(con, now, row[1], "FINALIZE_REFUSED", LEDGER_ALREADY_FINALIZED)
            con.execute("UPDATE merge_sends SET state = ?, recorded_at = ? WHERE operation_id = ? AND state = ?",
                        (SEND_UNCERTAIN, _stamp(now), row[1], SEND_STARTED))
            con.execute("UPDATE reservations SET state = ?, final_state = ?, finalized_at = ?"
                        " WHERE reservation_id = ?", (RES_FINALIZED, final_state, _stamp(now), reservation_id))
            _audit(con, now, row[1], "FINALIZED", final_state)
            return None

        self._transaction(work)

    # Merge-send journal (used by the host composition) ------------------
    def begin_merge_send(self, permit_id: str, repository: str, pr_number: int, expected_head_sha: str) -> None:
        """Durably records that the ONE merge request is about to leave the
        host. Refused unless the reservation is CONSUMED, unfinalized and the
        permit matches; refused forever after the first call."""
        if not _id_ok(permit_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)

        def work(con, now):
            row = con.execute(
                "SELECT p.operation_id, p.head_sha, p.expires_at, r.state, c.repository, c.pr_number FROM permits p"
                " JOIN reservations r ON r.reservation_id = p.reservation_id"
                " JOIN commands c ON c.command_id = p.command_id WHERE p.permit_id = ?", (permit_id,)).fetchone()
            if row is None:
                return self._refuse(con, now, None, "MERGE_SEND_REFUSED", LEDGER_PERMIT_UNKNOWN)
            operation_id = row[0]
            if con.execute("SELECT 1 FROM merge_sends WHERE operation_id = ?", (operation_id,)).fetchone():
                return self._refuse(con, now, operation_id, "MERGE_SEND_REFUSED", LEDGER_MERGE_ALREADY_ATTEMPTED)
            if row[3] != RES_CONSUMED:
                return self._refuse(con, now, operation_id, "MERGE_SEND_REFUSED", LEDGER_RESERVATION_STATE)
            if (row[1], row[4], row[5]) != (expected_head_sha, repository, pr_number) or type(pr_number) is not int:
                return self._refuse(con, now, operation_id, "MERGE_SEND_REFUSED", LEDGER_BINDING_MISMATCH)
            if now >= _instant(row[2]):
                return self._refuse(con, now, operation_id, "MERGE_SEND_REFUSED", LEDGER_PERMIT_EXPIRED)
            con.execute("INSERT INTO merge_sends (operation_id, permit_id, state, started_at) VALUES (?, ?, ?, ?)",
                        (operation_id, permit_id, SEND_STARTED, _stamp(now)))
            _audit(con, now, operation_id, "MERGE_SEND_STARTED", "OK")
            return None

        self._transaction(work)

    def record_merge_response(self, permit_id: str, status: str) -> None:
        """SENDING -> RESULT_RECORDED, or UNCERTAIN for TIMEOUT_AFTER_SEND."""
        if not _id_ok(permit_id) or type(status) is not str or status not in rpe.MERGE_STATUSES:
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)
        target = SEND_UNCERTAIN if status == rpe.MERGE_TIMEOUT_AFTER_SEND else SEND_RESULT_RECORDED
        self._record_send(permit_id, target, status)

    def record_merge_uncertain(self, permit_id: str) -> None:
        """SENDING -> UNCERTAIN: the outcome of the request is unknown."""
        if not _id_ok(permit_id):
            raise HostLedgerRefused(LEDGER_ARGUMENT_INVALID)
        self._record_send(permit_id, SEND_UNCERTAIN, SEND_UNCERTAIN)

    def _record_send(self, permit_id, target, status):
        def work(con, now):
            row = con.execute("SELECT operation_id, state FROM merge_sends WHERE permit_id = ?",
                              (permit_id,)).fetchone()
            if row is None or row[1] != SEND_STARTED:
                return self._refuse(con, now, row[0] if row else None, "MERGE_RECORD_REFUSED",
                                    LEDGER_MERGE_NOT_IN_FLIGHT)
            con.execute("UPDATE merge_sends SET state = ?, response_status = ?, recorded_at = ? WHERE permit_id = ?",
                        (target, status, _stamp(now), permit_id))
            _audit(con, now, row[0], "MERGE_" + target, status)
            return None

        self._transaction(work)

    def recover_interrupted_merges(self) -> tuple:
        """After a crash: every merge send still SENDING whose lease is no
        longer live becomes UNCERTAIN and its reservation is finalized as
        UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION. Returns the affected
        operation ids. Nothing is ever retried or made reusable."""
        def work(con, now):
            affected = []
            for (operation_id,) in con.execute("SELECT operation_id FROM merge_sends WHERE state = ?"
                                               " ORDER BY operation_id", (SEND_STARTED,)).fetchall():
                row = con.execute("SELECT expires_at FROM leases WHERE operation_id = ?", (operation_id,)).fetchone()
                if row is not None and now < _instant(row[0]):
                    continue   # still owned by a live attempt
                con.execute("UPDATE merge_sends SET state = ?, recorded_at = ? WHERE operation_id = ?",
                            (SEND_UNCERTAIN, _stamp(now), operation_id))
                con.execute("UPDATE reservations SET state = ?, final_state = ?, finalized_at = ?"
                            " WHERE operation_id = ? AND state <> ?",
                            (RES_FINALIZED, rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION, _stamp(now), operation_id,
                             RES_FINALIZED))
                _audit(con, now, operation_id, "MERGE_RECOVERED_UNCERTAIN", SEND_UNCERTAIN)
                affected.append(operation_id)
            return tuple(affected)

        return self._transaction(work)

    # Inspection -----------------------------------------------------------
    def reservation_state(self, operation_id: str):
        """(state, final_state) of the operation's reservation, or None."""
        return self._transaction(lambda con, now: con.execute(
            "SELECT state, final_state FROM reservations WHERE operation_id = ?", (operation_id,)).fetchone())

    def merge_send_state(self, operation_id: str):
        """(state, response_status) of the operation's merge send, or None."""
        return self._transaction(lambda con, now: con.execute(
            "SELECT state, response_status FROM merge_sends WHERE operation_id = ?", (operation_id,)).fetchone())

    def audit_trail(self, operation_id: Optional[str] = None) -> tuple:
        def work(con, now):
            if operation_id is None:
                rows = con.execute("SELECT seq, at, operation_id, event, code FROM audit ORDER BY seq").fetchall()
            else:
                rows = con.execute("SELECT seq, at, operation_id, event, code FROM audit WHERE operation_id = ?"
                                   " ORDER BY seq", (operation_id,)).fetchall()
            return tuple(AuditEntry(*row) for row in rows)

        return self._transaction(work)


def _audit(con, now, operation_id, event, code) -> None:
    con.execute("INSERT INTO audit (at, operation_id, event, code) VALUES (?, ?, ?, ?)",
                (_stamp(now), operation_id, event, code))
