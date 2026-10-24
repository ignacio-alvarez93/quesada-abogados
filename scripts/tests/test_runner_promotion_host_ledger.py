"""FCP-3B-2B2-HOST-01: durable single-use ledger of the trusted promotion host.

Every ledger lives in a temporary SQLite file created by these tests only,
outside the repository, and removed afterwards. Concurrency uses distinct
ledger instances (distinct connections) in real threads. No network is
reachable while this module runs.
"""

import ast
import dataclasses
import hashlib
import re
import shutil
import socket
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import runner_promotion_executor as rpe
from scripts.ai import runner_promotion_host_ledger as rhl

MODULE_PATH = Path(rhl.__file__)
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
RESOURCE = rhl.LEASE_RESOURCE
HEAD, BASE = "b" * 40, "a" * 40
_NETWORK = []


def _deny_network(*_args, **_kwargs):
    _NETWORK.append("attempt")
    raise OSError("network denied during host ledger tests")


def setUpModule():
    for target, name in ((socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo")):
        patcher = mock.patch.object(target, name, _deny_network)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def op_id(n) -> str:
    return hashlib.sha256(f"op-{n}".encode()).hexdigest()


def stamp(seconds) -> str:
    return (NOW + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def command(op, cmd="cmd-1", nonce=None, expires=600, **changes):
    return dataclasses.replace(rhl.RegisteredCommand(
        command_id=cmd, nonce=nonce or hashlib.sha256(cmd.encode()).hexdigest()[:32], operation_id=op,
        request_fingerprint="f" * 64, key_id="director-key-1", director_id=2002,
        repository="ignacio-alvarez93/quesada-abogados", pr_number=42, base_sha=BASE, head_sha=HEAD,
        action=rpe.ACTION_MERGE_GITHUB_PR, issued_at=stamp(-60), expires_at=stamp(expires),
        message=b"signed-bytes", signature=b"\x01" * 64), **changes)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="fcp-host-ledger-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.path = self.root / "host-ledger.sqlite3"
        self.clock = Clock()
        self.ledger = self.open()

    def open(self, owner="host-a", **kwargs):
        return rhl.HostLedger(self.path, owner=owner, clock=self.clock, **kwargs)

    def refused(self, code, fn, *args, **kwargs):
        with self.assertRaises(rhl.HostLedgerRefused) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def ready(self, ledger=None, op=None, cmd="cmd-1"):
        """Lease + registered command + reservation + permit for `op`."""
        ledger = ledger or self.ledger
        op = op or op_id(1)
        lease = ledger.acquire_lease(op, RESOURCE)
        ledger.register_command(command(op, cmd))
        receipt = ledger.reserve_single_use(op, cmd)
        permit = ledger.issue_operation_permit(op, receipt.reservation_id, cmd)
        return op, lease, receipt, permit

    def rows(self, sql, *args):
        con = sqlite3.connect(str(self.path))
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Location, schema and durability
# ---------------------------------------------------------------------------

class StorageTests(LedgerCase):
    def test_path_must_be_absolute_outside_repository_and_untrusted_roots(self):
        for bad in (":memory:", "", "relative.sqlite3", "file:x?mode=memory"):
            self.refused(rhl.LEDGER_PATH_INVALID, rhl.HostLedger, bad, owner="host-a", clock=self.clock)
        inside = rhl.REPOSITORY_ROOT / "scripts" / "host.sqlite3"
        self.refused(rhl.LEDGER_PATH_UNTRUSTED, rhl.HostLedger, inside, owner="host-a", clock=self.clock)
        self.assertFalse(inside.exists())
        worktree = self.root / "worktree"
        worktree.mkdir()
        self.refused(rhl.LEDGER_PATH_UNTRUSTED, rhl.HostLedger, worktree / "l.sqlite3", owner="host-a",
                     clock=self.clock, untrusted_roots=(worktree,))
        self.refused(rhl.LEDGER_ARGUMENT_INVALID, rhl.HostLedger, self.root / "x.sqlite3", owner="bad owner",
                     clock=self.clock)

    def test_reopen_after_crash_keeps_every_single_use_fact(self):
        op, _, receipt, permit = self.ready()
        self.assertEqual(self.ledger.consume_single_use(receipt.reservation_id).status, rpe.CONSUMED)
        del self.ledger   # simulated crash: no shutdown hook, a new process opens the file
        reopened = self.open(owner="host-b")
        again = reopened.reserve_single_use(op, "cmd-1")
        self.assertEqual(again.status, rpe.RESERVATION_ALREADY_CONSUMED)
        self.refused(rhl.LEDGER_COMMAND_DUPLICATE, reopened.register_command, command(op, "cmd-1"))
        self.assertEqual(reopened.reservation_state(op), (rhl.RES_CONSUMED, None))
        self.assertEqual(self.rows("SELECT value FROM meta WHERE key = 'schema'"), [(rhl.LEDGER_SCHEMA_VERSION,)])

    def test_schema_version_mismatch_is_refused(self):
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE meta SET value = 'other-v0' WHERE key = 'schema'")
        con.commit()
        con.close()
        self.refused(rhl.LEDGER_SCHEMA_MISMATCH, self.open)

    def test_failure_inside_a_transaction_rolls_back_everything(self):
        op = op_id(1)
        self.ledger.acquire_lease(op, RESOURCE)
        with mock.patch.object(rhl, "_audit", side_effect=RuntimeError("disk")):
            with self.assertRaises(RuntimeError):
                self.ledger.register_command(command(op))
        self.assertIsNone(self.ledger.command_for_operation(op))
        self.ledger.register_command(command(op))
        calls = []

        def fail_on_second(con, now, operation_id, event, code):
            calls.append(event)
            if event == "RESERVED":
                raise RuntimeError("crash between insert and audit")
            con.execute("INSERT INTO audit (at, operation_id, event, code) VALUES (?, ?, ?, ?)",
                        (rhl._stamp(now), operation_id, event, code))

        with mock.patch.object(rhl, "_audit", side_effect=fail_on_second):
            with self.assertRaises(RuntimeError):
                self.ledger.reserve_single_use(op, "cmd-1")
        self.assertIsNone(self.ledger.reservation_state(op))   # the reservation insert was rolled back
        self.assertEqual(self.ledger.reserve_single_use(op, "cmd-1").status, rpe.RESERVATION_CREATED)

    def test_clock_must_be_aware_utc(self):
        self.refused(rhl.LEDGER_CLOCK_INVALID, rhl.HostLedger, self.path, owner="host-a",
                     clock=lambda: datetime(2026, 10, 24, 12, 0))
        self.clock.now = None
        self.refused(rhl.LEDGER_CLOCK_INVALID, self.ledger.acquire_lease, op_id(1), RESOURCE)

    def test_sql_triggers_forbid_resetting_history_or_permissions(self):
        op, _, receipt, _ = self.ready()
        self.ledger.consume_single_use(receipt.reservation_id)
        con = sqlite3.connect(str(self.path))
        try:
            for sql in ("UPDATE audit SET code = 'x'", "DELETE FROM audit",
                        "UPDATE reservations SET state = 'RESERVED'", "DELETE FROM reservations",
                        "DELETE FROM commands", "DELETE FROM permits"):
                with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                    con.execute(sql)
        finally:
            con.close()
        self.assertEqual(self.ledger.reservation_state(op), (rhl.RES_CONSUMED, None))


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

class LeaseTests(LedgerCase):
    def test_lease_is_exclusive_owned_and_bounded(self):
        grant = self.ledger.acquire_lease(op_id(1), RESOURCE)
        self.assertIs(type(grant), rpe.LeaseGrant)
        self.assertEqual((grant.operation_id, grant.resource, grant.acquired_at, grant.expires_at),
                         (op_id(1), RESOURCE, stamp(0), stamp(rhl.DEFAULT_LEASE_SECONDS)))
        self.assertEqual(rpe._lease_errors(grant, mock.Mock(idempotency_key=op_id(1), repository=RESOURCE[:-8],
                                                            base_ref="develop"), NOW), [])
        other = self.open(owner="host-b")
        self.assertIsNone(other.acquire_lease(op_id(2), RESOURCE))
        self.refused(rhl.LEDGER_LEASE_OWNER_MISMATCH, other.release_lease, grant.lease_id)
        self.refused(rhl.LEDGER_LEASE_RESOURCE_INVALID, self.ledger.acquire_lease, op_id(3), "other/repo:develop")
        self.ledger.release_lease(grant.lease_id)
        self.refused(rhl.LEDGER_LEASE_NOT_HELD, self.ledger.release_lease, grant.lease_id)
        self.assertIsNotNone(other.acquire_lease(op_id(2), RESOURCE))

    def test_expired_lease_is_taken_over_and_old_owner_loses_everything(self):
        op, grant, receipt, _ = self.ready()
        self.clock.advance(rhl.DEFAULT_LEASE_SECONDS + 1)
        other = self.open(owner="host-b")
        self.assertIsNotNone(other.acquire_lease(op_id(2), RESOURCE))
        refused = self.ledger.consume_single_use(receipt.reservation_id)
        self.assertEqual(refused.status, rpe.CONSUMPTION_REFUSED)
        self.refused(rhl.LEDGER_LEASE_NOT_HELD, self.ledger.release_lease, grant.lease_id)
        events = [(e.event, e.code) for e in self.ledger.audit_trail()]
        self.assertIn(("LEASE_EXPIRED_TAKEOVER", "LEASE_EXPIRED"), events)
        self.assertIn(("CONSUME_REFUSED", rhl.LEDGER_PERMIT_EXPIRED), events)

    def test_expired_lease_of_same_owner_blocks_consumption(self):
        op, _, receipt, _ = self.ready()
        # Keep the permit valid on purpose so that only the lease has expired.
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE permits SET expires_at = ?", (stamp(10_000),))
        con.commit()
        con.close()
        self.clock.advance(rhl.DEFAULT_LEASE_SECONDS)
        self.assertEqual(self.ledger.consume_single_use(receipt.reservation_id).status, rpe.CONSUMPTION_REFUSED)
        self.assertEqual(self.ledger.audit_trail(op)[-1].code, rhl.LEDGER_LEASE_NOT_HELD)

    def test_two_connections_race_for_the_lease_exactly_one_wins(self):
        ledgers = [self.open(owner=f"host-{i}") for i in range(2)]
        for round_ in range(8):
            barrier, results = threading.Barrier(2), [None, None]

            def contend(i):
                barrier.wait()
                results[i] = ledgers[i].acquire_lease(op_id(f"{round_}-{i}"), RESOURCE)

            threads = [threading.Thread(target=contend, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            winners = [i for i, r in enumerate(results) if r is not None]
            self.assertEqual(len(winners), 1, results)
            ledgers[winners[0]].release_lease(results[winners[0]].lease_id)


# ---------------------------------------------------------------------------
# Commands, reservations, permits and consumption
# ---------------------------------------------------------------------------

class SingleUseTests(LedgerCase):
    def test_command_id_nonce_and_operation_are_each_single_use(self):
        op = op_id(1)
        self.ledger.register_command(command(op, "cmd-1", nonce="1" * 32))
        for dup in (command(op_id(2), "cmd-1", nonce="2" * 32), command(op_id(3), "cmd-3", nonce="1" * 32),
                    command(op, "cmd-4", nonce="4" * 32)):
            self.refused(rhl.LEDGER_COMMAND_DUPLICATE, self.ledger.register_command, dup)
        self.refused(rhl.LEDGER_ARGUMENT_INVALID, self.ledger.register_command, {"command_id": "cmd-9"})
        self.assertEqual(self.ledger.command_for_operation(op), command(op, "cmd-1", nonce="1" * 32))

    def test_happy_path_receipts_satisfy_the_executor_checks(self):
        op, _, receipt, permit = self.ready()
        request = mock.Mock(idempotency_key=op, action=rpe.ACTION_MERGE_GITHUB_PR, head_sha=HEAD, base_sha=BASE)
        self.assertEqual(rpe._reservation_errors(receipt, request, "cmd-1"), [])
        self.assertEqual(rpe._permit_errors(permit, request, receipt.reservation_id, "cmd-1", NOW), [])
        consumed = self.ledger.consume_single_use(receipt.reservation_id)
        self.assertEqual(rpe._consumption_errors(consumed, request, receipt.reservation_id), [])
        self.ledger.finalize_reservation(receipt.reservation_id, rpe.FAILED_SAFE)
        self.assertEqual(self.ledger.reservation_state(op), (rhl.RES_FINALIZED, rpe.FAILED_SAFE))
        self.assertEqual([e.event for e in self.ledger.audit_trail(op)],
                         ["LEASE_ACQUIRED", "COMMAND_REGISTERED", "RESERVED", "PERMIT_ISSUED", "CONSUMED",
                          "FINALIZED"])

    def test_duplicate_and_replayed_reservations_are_reported(self):
        op, _, receipt, _ = self.ready()
        self.assertEqual(self.ledger.reserve_single_use(op, "cmd-1").status, rpe.RESERVATION_ALREADY_RESERVED)
        self.ledger.consume_single_use(receipt.reservation_id)
        self.assertEqual(self.ledger.reserve_single_use(op, "cmd-1").status, rpe.RESERVATION_ALREADY_CONSUMED)
        self.ledger.finalize_reservation(receipt.reservation_id, rpe.MERGED_VERIFIED)
        self.assertEqual(self.ledger.reserve_single_use(op, "cmd-1").status, rpe.RESERVATION_ALREADY_CONSUMED)
        self.assertEqual(self.ledger.consume_single_use(receipt.reservation_id).status, rpe.CONSUMPTION_REFUSED)
        self.refused(rhl.LEDGER_ALREADY_FINALIZED, self.ledger.finalize_reservation, receipt.reservation_id,
                     rpe.FAILED_SAFE)
        self.refused(rhl.LEDGER_FINAL_STATE_INVALID, self.ledger.finalize_reservation, receipt.reservation_id,
                     "SUCCESS")

    def test_reservation_needs_registered_command_of_that_operation_and_lease(self):
        op = op_id(1)
        self.refused(rhl.LEDGER_COMMAND_UNKNOWN, self.ledger.reserve_single_use, op, "cmd-1")
        self.ledger.register_command(command(op_id(2), "cmd-2"))
        self.refused(rhl.LEDGER_COMMAND_UNKNOWN, self.ledger.reserve_single_use, op, "cmd-2")
        self.ledger.register_command(command(op, "cmd-1"))
        self.refused(rhl.LEDGER_LEASE_NOT_HELD, self.ledger.reserve_single_use, op, "cmd-1")
        other = self.open(owner="host-b")
        other.acquire_lease(op, RESOURCE)
        self.refused(rhl.LEDGER_LEASE_NOT_HELD, self.ledger.reserve_single_use, op, "cmd-1")

    def test_single_permit_and_expiry(self):
        op, _, receipt, permit = self.ready()
        self.refused(rhl.LEDGER_PERMIT_DUPLICATE, self.ledger.issue_operation_permit, op, receipt.reservation_id,
                     "cmd-1")
        self.refused(rhl.LEDGER_BINDING_MISMATCH, self.ledger.issue_operation_permit, op_id(9),
                     receipt.reservation_id, "cmd-1")
        self.clock.advance(rhl.PERMIT_TTL_SECONDS)
        self.assertEqual(self.ledger.consume_single_use(receipt.reservation_id).status, rpe.CONSUMPTION_REFUSED)
        self.assertEqual(self.ledger.audit_trail(op)[-1].code, rhl.LEDGER_PERMIT_EXPIRED)
        self.assertEqual(self.ledger.reservation_state(op), (rhl.RES_RESERVED, None))

    def test_revocation_before_consumption_blocks_it(self):
        op, _, receipt, _ = self.ready()
        self.ledger.revoke_command("cmd-1", "DIRECTOR-REVOKED")
        self.assertTrue(self.ledger.is_command_revoked("cmd-1"))
        self.assertEqual(self.ledger.consume_single_use(receipt.reservation_id).status, rpe.CONSUMPTION_REFUSED)
        self.assertEqual(self.ledger.audit_trail(op)[-1].code, rhl.LEDGER_COMMAND_REVOKED)
        # Pre-emptive revocation: a revoked id can never be registered.
        self.ledger.revoke_command("cmd-7", "DIRECTOR-REVOKED")
        self.refused(rhl.LEDGER_COMMAND_REVOKED, self.ledger.register_command, command(op_id(7), "cmd-7"))

    def test_revoked_command_cannot_reserve(self):
        op = op_id(1)
        self.ledger.acquire_lease(op, RESOURCE)
        self.ledger.register_command(command(op))
        self.ledger.revoke_command("cmd-1", "DIRECTOR-REVOKED")
        self.refused(rhl.LEDGER_COMMAND_REVOKED, self.ledger.reserve_single_use, op, "cmd-1")

    def test_two_connections_race_to_reserve_exactly_one_is_created(self):
        op = op_id(1)
        self.ledger.acquire_lease(op, RESOURCE)
        self.ledger.register_command(command(op))
        ledgers = [self.open() for _ in range(4)]   # same owner, distinct connections
        barrier, results = threading.Barrier(4), [None] * 4

        def contend(i):
            barrier.wait()
            results[i] = ledgers[i].reserve_single_use(op, "cmd-1").status

        threads = [threading.Thread(target=contend, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(results.count(rpe.RESERVATION_CREATED), 1, results)
        self.assertEqual(results.count(rpe.RESERVATION_ALREADY_RESERVED), 3, results)
        self.assertEqual(len(self.rows("SELECT * FROM reservations")), 1)


# ---------------------------------------------------------------------------
# Merge-send journal and uncertainty
# ---------------------------------------------------------------------------

class MergeJournalTests(LedgerCase):
    def consumed(self):
        op, lease, receipt, permit = self.ready()
        self.ledger.consume_single_use(receipt.reservation_id)
        return op, lease, receipt, permit

    def test_send_requires_consumption_and_happens_once(self):
        op, _, receipt, permit = self.ready()
        args = (permit.permit_id, "ignacio-alvarez93/quesada-abogados", 42, HEAD)
        self.refused(rhl.LEDGER_RESERVATION_STATE, self.ledger.begin_merge_send, *args)
        self.ledger.consume_single_use(receipt.reservation_id)
        self.refused(rhl.LEDGER_BINDING_MISMATCH, self.ledger.begin_merge_send, permit.permit_id,
                     "ignacio-alvarez93/quesada-abogados", 42, "c" * 40)
        self.ledger.begin_merge_send(*args)
        self.refused(rhl.LEDGER_MERGE_ALREADY_ATTEMPTED, self.ledger.begin_merge_send, *args)
        self.ledger.record_merge_response(permit.permit_id, rpe.MERGE_REJECTED_CONFLICT)
        self.refused(rhl.LEDGER_MERGE_NOT_IN_FLIGHT, self.ledger.record_merge_response, permit.permit_id,
                     rpe.MERGE_MERGED)
        self.assertEqual(self.ledger.merge_send_state(op), (rhl.SEND_RESULT_RECORDED, rpe.MERGE_REJECTED_CONFLICT))

    def test_timeout_after_send_is_uncertain_forever(self):
        op, _, receipt, permit = self.consumed()
        self.ledger.begin_merge_send(permit.permit_id, "ignacio-alvarez93/quesada-abogados", 42, HEAD)
        self.ledger.record_merge_response(permit.permit_id, rpe.MERGE_TIMEOUT_AFTER_SEND)
        self.ledger.finalize_reservation(receipt.reservation_id, rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION)
        reopened = self.open(owner="host-b")
        self.assertEqual(reopened.merge_send_state(op), (rhl.SEND_UNCERTAIN, rpe.MERGE_TIMEOUT_AFTER_SEND))
        self.assertEqual(reopened.reserve_single_use(op, "cmd-1").status, rpe.RESERVATION_ALREADY_CONSUMED)
        self.refused(rhl.LEDGER_MERGE_ALREADY_ATTEMPTED, reopened.begin_merge_send, permit.permit_id,
                     "ignacio-alvarez93/quesada-abogados", 42, HEAD)
        con = sqlite3.connect(str(self.path))
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("UPDATE merge_sends SET state = 'SENDING'")
        con.close()

    def test_crash_during_send_recovers_as_uncertain_never_retried(self):
        op, _, receipt, permit = self.consumed()
        self.ledger.begin_merge_send(permit.permit_id, "ignacio-alvarez93/quesada-abogados", 42, HEAD)
        del self.ledger   # crash with the request possibly on the wire
        reopened = self.open(owner="host-b")
        self.assertEqual(reopened.recover_interrupted_merges(), ())   # the lease is still live: not touched
        self.clock.advance(rhl.DEFAULT_LEASE_SECONDS + 1)
        self.assertEqual(reopened.recover_interrupted_merges(), (op,))
        self.assertEqual(reopened.merge_send_state(op), (rhl.SEND_UNCERTAIN, None))
        self.assertEqual(reopened.reservation_state(op),
                         (rhl.RES_FINALIZED, rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION))
        self.assertEqual(reopened.reserve_single_use(op, "cmd-1").status, rpe.RESERVATION_ALREADY_CONSUMED)
        self.refused(rhl.LEDGER_MERGE_ALREADY_ATTEMPTED, reopened.begin_merge_send, permit.permit_id,
                     "ignacio-alvarez93/quesada-abogados", 42, HEAD)
        self.assertIn("MERGE_RECOVERED_UNCERTAIN", [e.event for e in reopened.audit_trail(op)])

    def test_finalize_turns_an_unfinished_send_into_uncertain(self):
        op, _, receipt, permit = self.consumed()
        self.ledger.begin_merge_send(permit.permit_id, "ignacio-alvarez93/quesada-abogados", 42, HEAD)
        self.ledger.finalize_reservation(receipt.reservation_id, rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION)
        self.assertEqual(self.ledger.merge_send_state(op), (rhl.SEND_UNCERTAIN, None))


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class LedgerStructureTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.code = re.sub(r'"""[\s\S]*?"""', "", self.source)

    def test_no_network_process_git_env_or_erp_storage(self):
        imports = {a.name for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names} | {n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("subprocess", "socket", "os", "urllib", "http", "requests", "ssl", "runner_git",
                       "runner_pipeline", "flet", "runner_promotion_host_authority", "runner_promotion_host_github"):
            self.assertNotIn(banned, imports, banned)
        for text in ("environ", "getenv", ".env", "git push", "update-ref", "Authorization", "token", "https://"):
            self.assertNotIn(text, self.code, text)
        self.assertIsNone(re.search(r"(?i)(crm|erp|flet)|quesada\.db", self.code))
        self.assertEqual(_NETWORK, [])

    def test_every_write_goes_through_begin_immediate(self):
        self.assertIn('con.execute("BEGIN IMMEDIATE")', self.source)
        connects = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call)
                    and ast.unparse(n.func) == "sqlite3.connect"]
        self.assertEqual(len(connects), 1)   # only `_connect`, one connection per operation
        self.assertIs(rpe.PRODUCTION_PROMOTION_CAPABLE, False)
        doc = " ".join(rhl.__doc__.split())
        for phrase in ("proves NO isolation", "NOT the CRM/ERP database", "never retried", "BEGIN IMMEDIATE"):
            self.assertIn(phrase, doc, phrase)


if __name__ == "__main__":
    unittest.main()
