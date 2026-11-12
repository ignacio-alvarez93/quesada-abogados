"""WO-DV28-P1: governed activation of "Archivar copia en Box" from the viewer (H1/H2/H3), gate OFF.

Everything runs on the certified sandboxes, never relaxed: P3B1 (``BoxCopyBase``: synthetic CRM,
Bandeja and Box in a TemporaryDirectory, no delete/move/rename/overwrite primitive reachable, Box
files and Bandeja originals compared byte for byte), P3B2/DV27 (``ActivationBase``: the viewer's
gate, contract and single-host decision opened in the sandbox only) and the P3B3 fail-closed SQLite
guard (``SandboxMixin``). No real Box, Box Drive, ``quesada.db`` or ``.env`` is reached.

- ``GateTests``: production flags stay closed in the code; the candidate permission contract is not
  installed; the migration is additive DDL only; the certified copy holds the folder chain from
  COPY to REGISTER; no scattered SQLite in the viewer domain or UI (DATA-008).
- ``GrantContractTests`` / ``ViewerGrantTests`` (H1): explicit, revocable, audited grant of
  ``document.box_copy``; checked at review, at confirmation and right before the copy.
- ``ViewerAuthorityTests`` / ``ProcessAuthorityTests`` (H2): one copy under threads and real
  processes on ONE transactional authority; a store without an exact guarantee is not authority.
- ``ContainmentTests`` (H3): swapped root or folder refused before any write; on Windows, attacks
  against the held chain fail, failures release it, cloud placeholders are accepted and any other
  reparse point is refused. An attack that writes outside the root FAILS the test.
- ``FormatTests``: PDF/JPG/PNG keep their extension and catalog name; originals untouched.
"""
import ast
import hashlib
import os
import re
import sqlite3
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.services import document_inbox_service as inbox
from backend.services import document_viewer_archive_permission_service as permission
from backend.services import document_viewer_archive_repository as intents
from backend.services import document_viewer_box_archive_service as archive
from backend.services import document_viewer_filing_plan_service as filing
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_box_from_viewer as p3b2
from scripts.tests import test_document_viewer_dv25_box_hardening as p3b1
from scripts.tests import test_document_viewer_dv25_filing_plan as p3a
from scripts.tests import test_document_viewer_dv25_security as sec
from scripts.tests import test_dv27_box_copy_activation as dv27


REPO_ROOT = dv24.REPO_ROOT
SERVICE = p3b2.SERVICE
DIALOG = p3b2.ARCHIVE_DIALOG
PERMISSION = sec.PERMISSION
REPOSITORY = sec.REPOSITORY
INBOX_SERVICE = p3b1.INBOX_SERVICE
HOST_POLICY = REPO_ROOT / "backend" / "services" / "document_viewer_archive_host_policy.py"
GRANTS_MIGRATION = REPO_ROOT / "database" / "migrations" / "20261111_dv28_box_permissions.sql"
GRANTS_SQL = GRANTS_MIGRATION.read_text(encoding="utf-8")
KEY = sec.KEY    # P3B1 synthetic catalog: PASAPORTE · SOLICITANTE
NAME = sec.NAME  # "PASAPORTE SOLICITANTE.pdf"
SUBFOLDER = "02 LABORAL/Contratos"
WINDOWS = unittest.skipUnless(os.name == "nt", "H3 prevention targets Windows + Box Drive")


def utc(seconds=0):
    """UTC timestamp in the migration's format (that of SQLite's datetime('now'))."""
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


def apply_grants(db):
    """Test-only bootstrap of the DV28 migration on a temporary database."""
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript(GRANTS_SQL)
        conn.commit()


def function_node(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def call_names(node):
    return [getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            for call in ast.walk(node) if isinstance(call, ast.Call)]


class GrantMixin:
    """Explicit grants of ``document.box_copy`` written test-side, as Dirección's procedure would."""

    def sql(self, statement, params=()):
        with closing(sqlite3.connect(self.db)) as conn:
            cursor = conn.execute(statement, params)
            conn.commit()
            return cursor.lastrowid

    def grant(self, user_id=1, username="ana", by=2, *, granted_at=None, expires_at=None,
              permission_name=permission.BOX_COPY_PERMISSION, reason="Autorizado por Dirección (prueba DV28)"):
        return self.sql(
            "INSERT INTO user_permission_grants (user_id, username, permission, granted_by_user_id, granted_at, "
            "reason, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, permission_name, by, granted_at or utc(-60), reason, expires_at))

    def revoke(self, grant_id, by=2, reason="Retirado por Dirección (prueba DV28)"):
        self.sql("UPDATE user_permission_grants SET revoked_at = ?, revoked_by_user_id = ?, revoke_reason = ? "
                 "WHERE id = ?", (utc(), by, reason, grant_id))


# ---------------------------------------------------------------------- real code


class GateTests(unittest.TestCase):
    def test_production_gate_and_flags_stay_closed(self):
        self.assertEqual(dv27.literal_assignments(SERVICE, "EXECUTION_ENABLED"), [False])
        self.assertEqual(dv27.literal_assignments(SERVICE, "SINGLE_HOST_APPROVED"), [False])
        self.assertEqual(dv27.literal_assignments(SERVICE, "H3_WRITE_CONTAINMENT_VERIFIED"), [False])
        self.assertEqual(dv27.literal_assignments(PERMISSION, "APPROVED_CONTRACT"), [None])
        self.assertEqual(dv27.literal_assignments(REPOSITORY, "MULTI_HOST_GUARANTEE"), [False])
        # DV28-P2: no workstation enrolled and no OS proof provider installed in the code.
        self.assertEqual(dv27.literal_assignments(HOST_POLICY, "ENROLLED_STATION"), [None])
        self.assertEqual(dv27.literal_assignments(HOST_POLICY, "PROOF_PROVIDER"), [None])
        self.assertEqual(archive.activation_blockers(), dv27.CODES)
        self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)
        # The candidate contract exists but nothing installs it: only Dirección (DV28-P2) can.
        self.assertTrue(callable(permission.PersistedGrantContract().grants))
        for path in (SERVICE, DIALOG, *sorted((REPO_ROOT / "frontend").rglob("*.py"))):
            text = path.read_text(encoding="utf-8")
            for name in ("PersistedGrantContract", "APPROVED_CONTRACT =", "user_permission_grants",
                         "20261111_dv28_box_permissions"):
                self.assertNotIn(name, text, path)

    def test_grants_migration_is_versioned_additive_ddl_without_grants(self):
        statements = "\n".join(line for line in GRANTS_SQL.splitlines() if not line.lstrip().startswith("--"))
        self.assertEqual(re.findall(r"(?im)^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|REPLACE)\b", statements), [])
        self.assertEqual(re.findall(r"(?i)\bCREATE\s+(?:UNIQUE\s+)?(\w+)\s+IF NOT EXISTS\s+(\w+)", statements), [
            ("TABLE", "user_permission_grants"), ("INDEX", "uq_user_permission_grants_active"),
            ("TRIGGER", "trg_user_permission_grants_no_delete"),
            ("TRIGGER", "trg_user_permission_grants_revoke_only")])
        self.assertIn("'document.box_copy'", statements)

    def test_the_certified_copy_holds_the_folder_chain_from_copy_to_register(self):
        copy = function_node(INBOX_SERVICE, "_copy_inbox_item_to_box")
        held = [node for node in ast.walk(copy) if isinstance(node, ast.With)
                and any(getattr(item.context_expr.func, "id", None) == "_held_box_folder"
                        for item in node.items if isinstance(item.context_expr, ast.Call))]
        self.assertEqual(len(held), 1)
        inside = call_names(held[0])
        for name in ("_create_box_copy", "_register_box_copy"):
            self.assertEqual(inside.count(name), call_names(copy).count(name), name)  # never outside the hold
            self.assertEqual(inside.count(name), 1, name)
        # Missing folders (Bandeja) are created under a held parent, never through a link.
        folder = function_node(INBOX_SERVICE, "_box_destination_folder")
        [chain] = [node for node in ast.walk(folder) if isinstance(node, ast.With)]
        self.assertIn("mkdir", call_names(chain))
        self.assertEqual(call_names(folder).count("mkdir"), call_names(chain).count("mkdir"))

    def test_no_scattered_sqlite_in_the_viewer_domain_or_ui(self):
        for path in (SERVICE, PERMISSION, REPOSITORY, DIALOG, HOST_POLICY):
            with self.subTest(path.name):
                self.assertNotIn("connect", p3a.called_names(path))
        for path in (PERMISSION, REPOSITORY, DIALOG, HOST_POLICY):
            self.assertFalse(any(m == "sqlite3" or m.startswith("sqlite3.") for m in dv24.imported_modules(path)))


# ---------------------------------------------------------------------- H1


class GrantContractTests(GrantMixin, sec.SandboxCase):
    """The candidate contract alone, on the P3B3 fail-closed sandbox."""

    ANA = {"id": 1, "username": "ana"}

    def setUp(self):
        super().setUp()
        self.schema_before = sec.database_state(self.db)[0]
        apply_grants(self.db)
        self.contract = permission.PersistedGrantContract()
        patcher = patch.object(permission, "APPROVED_CONTRACT", self.contract)
        patcher.start()
        self.addCleanup(patcher.stop)

    def decide(self, actor=None):
        return permission.authorize_archive(dict(actor or self.ANA), db_path=self.db)

    def assert_decision(self, reason, actor=None):
        decision = self.decide(actor)
        self.assertEqual((decision.allowed, decision.reason), (reason == permission.GRANTED, reason))
        return decision

    def test_migration_adds_only_its_objects_and_no_grant(self):
        schema, rows = sec.database_state(self.db)
        added = sorted(name for kind, name, sql in schema if (kind, name, sql) not in self.schema_before)
        self.assertEqual(added, ["trg_user_permission_grants_no_delete", "trg_user_permission_grants_revoke_only",
                                 "uq_user_permission_grants_active", "user_permission_grants"])
        self.assertEqual(rows["user_permission_grants"], [])
        apply_grants(self.db)  # idempotent
        self.assertEqual(sec.database_state(self.db)[0], schema)

    def test_only_an_explicit_live_grant_allows(self):
        # Active, authenticated, even "admin" by its own claims: nothing without an explicit grant.
        for actor in (self.ANA, {**self.ANA, "role": "admin", "is_admin": True, "permissions": ["document.box_copy"]}):
            with self.subTest(actor=actor):
                self.assert_decision(permission.NOT_GRANTED, actor)
        self.grant()
        allowed = self.assert_decision(permission.GRANTED)
        self.assertEqual(allowed.user, self.ANA)
        self.assert_decision(permission.NOT_GRANTED, {"id": 2, "username": "luis"})
        for actor in ({"id": 1, "username": "luis"}, {"id": 99, "username": "nadie"},
                      {"id": 3, "username": "baja"}):
            with self.subTest(actor=actor):
                self.assert_decision(permission.NOT_AUTHENTICATED, actor)

    def test_revocation_expiry_rename_and_inactivity_deny(self):
        first = self.grant()
        self.assert_decision(permission.GRANTED)
        self.revoke(first)
        self.assert_decision(permission.NOT_GRANTED)
        # A new grant is a new row; the revoked one stays as evidence.
        second = self.grant()
        self.assert_decision(permission.GRANTED)
        self.sql("UPDATE users SET username = 'ana.nueva' WHERE id = 1")
        self.assert_decision(permission.NOT_GRANTED, {"id": 1, "username": "ana.nueva"})
        self.sql("UPDATE users SET username = 'ana' WHERE id = 1")
        self.sql("UPDATE users SET is_active = 0 WHERE id = 1")
        self.assert_decision(permission.NOT_AUTHENTICATED)
        self.sql("UPDATE users SET is_active = 1 WHERE id = 1")
        self.revoke(second)
        self.grant(granted_at=utc(-120), expires_at=utc(-60))  # expired
        self.assert_decision(permission.NOT_GRANTED)
        self.grant(user_id=2, username="luis", by=1, granted_at=utc(3600))  # not yet in force
        self.assert_decision(permission.NOT_GRANTED, {"id": 2, "username": "luis"})
        self.assertEqual(len(self.sql_rows()), 4)

    def sql_rows(self):
        return sec.database_state(self.db)[1]["user_permission_grants"]

    def test_grants_are_append_only_and_revoked_once(self):
        grant = self.grant()
        for name, statement, params in (
                ("self grant", "INSERT INTO user_permission_grants (user_id, username, permission, "
                 "granted_by_user_id, granted_at, reason) VALUES (2, 'luis', 'document.box_copy', 2, ?, 'x')",
                 (utc(-60),)),
                ("other permission", "INSERT INTO user_permission_grants (user_id, username, permission, "
                 "granted_by_user_id, granted_at, reason) VALUES (2, 'luis', 'admin', 1, ?, 'x')", (utc(-60),)),
                ("no reason", "INSERT INTO user_permission_grants (user_id, username, permission, "
                 "granted_by_user_id, granted_at, reason) VALUES (2, 'luis', 'document.box_copy', 1, ?, ' ')",
                 (utc(-60),)),
                ("second live grant", "INSERT INTO user_permission_grants (user_id, username, permission, "
                 "granted_by_user_id, granted_at, reason) VALUES (1, 'ana', 'document.box_copy', 2, ?, 'x')",
                 (utc(-30),)),
                ("delete", "DELETE FROM user_permission_grants WHERE id = ?", (grant,)),
                ("rewrite", "UPDATE user_permission_grants SET reason = 'otra' WHERE id = ?", (grant,)),
                ("other user", "UPDATE user_permission_grants SET user_id = 2 WHERE id = ?", (grant,)),
                ("revoke without who and why", "UPDATE user_permission_grants SET revoked_at = ? WHERE id = ?",
                 (utc(), grant))):
            with self.subTest(name), self.assertRaises(sqlite3.DatabaseError):
                self.sql(statement, params)
        self.revoke(grant)
        for name, statement in (("revoke twice", "UPDATE user_permission_grants SET revoke_reason = 'otra' "
                                                 "WHERE id = ?"),
                                ("un-revoke", "UPDATE user_permission_grants SET revoked_at = NULL, "
                                              "revoked_by_user_id = NULL, revoke_reason = NULL WHERE id = ?"),
                                ("delete revoked", "DELETE FROM user_permission_grants WHERE id = ?")):
            with self.subTest(name), self.assertRaises(sqlite3.DatabaseError):
                self.sql(statement, (grant,))
        self.assertEqual(len(self.sql_rows()), 1)

    def test_missing_grants_table_denies(self):
        self.grant()
        self.sql("DROP TABLE user_permission_grants")
        self.assert_decision(permission.CONTRACT_ERROR)


class ViewerGrantTests(GrantMixin, dv27.ActivationBase):
    """H1 through the viewer with the candidate contract installed in the sandbox only."""

    def setUp(self):
        super().setUp()
        apply_grants(self.db)
        self.schema_before = self.schema()  # FilingBase compares the schema in tearDown
        self.patch(permission, "APPROVED_CONTRACT", permission.PersistedGrantContract())
        self.grant_id = self.grant()

    def test_an_explicit_grant_archives_once_and_keeps_everything_else(self):
        source, before_row = self.source(6), self.row(6)
        plan = self.plan6()
        self.assertEqual((plan.authorized, plan.permission_message), (True, ""))
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        self.copy.assert_called_once_with(6, expedient_id=42, subfolder="", nomenclature_key=p3b2.K[0])
        self.assert_added(tree, {f"EXP-42/{dv27.NAME}": ("file", source)})
        self.assertEqual(self.source(6), source)
        row = self.row(6)
        self.assertEqual((row["status"], row["client_id"], row["expedient_id"], row["stored_path"]),
                         ("copied_to_box", 7, 42, before_row["stored_path"]))

    def test_revocation_between_review_and_confirmation_copies_nothing(self):
        plan = self.plan6()
        self.assertTrue(plan.authorized)
        before = self.snapshot()
        self.revoke(self.grant_id)
        self.assert_refused(plan, permission.NOT_GRANTED_MESSAGE)
        self.copy.assert_not_called()
        self.assertEqual(self.intent_rows(), [])
        self.assertEqual(self.snapshot()[:3], before[:3])  # rows, events and Box tree

    def test_revocation_right_before_the_copy_writes_nothing_and_can_be_retried(self):
        real_claim, revoked = intents.SqliteArchiveIntentStore.claim, []

        def claim_then_revoke(store, intent, owner_token, now):
            if not revoked:  # after the confirmation, with the request already being claimed
                self.revoke(self.grant_id)
                revoked.append(True)
            return real_claim(store, intent, owner_token, now)

        self.patch(intents.SqliteArchiveIntentStore, "claim", claim_then_revoke)
        tree = self.tree()
        with self.guard():
            result = self.run_plan(self.plan6())
        self.assertEqual([(item.status, item.message) for item in result.items],
                         [(archive.REJECTED, archive.PERMISSION_REVOKED)])
        self.copy.assert_not_called()
        self.assertEqual(self.tree(), tree)
        self.assertEqual(self.intent_states(), [intents.REJECTED])
        self.assertEqual(self.row(6)["status"], "linked")
        # Nothing was written: a new grant and a new review copy once, on a new fence.
        self.grant_id = self.grant()
        with self.guard():
            result = self.run_plan(self.plan6())
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual(self.query("SELECT state, fence FROM document_viewer_archive_intents"),
                         [{"state": intents.REGISTERED, "fence": 2}])
        self.assert_added(tree, {f"EXP-42/{dv27.NAME}": ("file", self.source(6))})

    def test_a_contract_failure_right_before_the_copy_denies(self):
        real, calls = permission.authorize_archive, []

        def failing_third(actor, *, db_path=None):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("contrato caído (simulado)")
            return real(actor, db_path=db_path)

        self.patch(permission, "authorize_archive", failing_third)
        tree = self.tree()
        with self.guard():
            result = self.run_plan(self.plan6())
        self.assertEqual(len(calls), 3)  # review, confirmation, right before the copy
        self.assertEqual([(item.status, item.message) for item in result.items],
                         [(archive.REJECTED, archive.PERMISSION_REVOKED)])
        self.copy.assert_not_called()
        self.assertEqual(self.tree(), tree)

    def test_a_review_without_permission_never_runs_even_if_granted_later(self):
        self.revoke(self.grant_id)
        claims = {**self.actor, "role": "admin", "is_admin": True, "permissions": ["document.box_copy"]}
        plan = self.plan6(actor=claims)
        self.assertEqual(len(plan.ready), 1)  # the review stays available
        self.assertEqual((plan.authorized, plan.permission_message), (False, permission.NOT_GRANTED_MESSAGE))
        self.grant_id = self.grant()
        self.assert_refused(plan, archive.PERMISSION_CHANGED)
        # An expired grant is no grant.
        self.revoke(self.grant_id)
        self.grant(granted_at=utc(-120), expires_at=utc(-60))
        self.assert_refused(self.plan6(), permission.NOT_GRANTED_MESSAGE)
        self.copy.assert_not_called()
        self.assertEqual(self.intent_rows(), [])

    def test_the_dialog_shows_the_denial_and_never_takes_the_consent(self):
        self.revoke(self.grant_id)
        dialog = self.open_inbox([6, 1])
        before = self.snapshot()
        with self.guard():
            form = self.open_archive(dialog)
            self.assertEqual(form.blocker, "")
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · SOLICITANTE")
            self.assertEqual([item.proposed_name for item in form.plan.ready], [dv27.NAME])
            self.assertEqual(form.status.value, permission.NOT_GRANTED_MESSAGE)
            self.assertTrue(form.confirm.disabled)
            self.confirm(form)
            self.assertIsNone(form.consented)
            self.assertTrue(form.submit_button.disabled)
            self.assertIsNone(form.submit())
            form.close()
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)


# ---------------------------------------------------------------------- H2


class ViewerAuthorityTests(dv27.ActivationBase):
    def test_four_concurrent_reviews_of_one_document_copy_once(self):
        # As four processes on one database: the in-memory guard is not shared.
        self.patch(archive, "_claim", lambda item_id: True)
        self.patch(archive, "_release", lambda item_id: None)
        plans = [self.plan6() for _ in range(4)]
        entered, release, lock, outcomes = threading.Event(), threading.Event(), threading.Lock(), []

        def slow(item_id, **kwargs):
            entered.set()
            release.wait(30)
            return p3b2.REAL_COPY(item_id, **kwargs)

        def worker(plan):
            try:
                value = [(item.status, item.message) for item in self.run_plan(plan).items][0]
            except archive.ArchiveError as exc:
                value = ("error", str(exc))
            with lock:
                outcomes.append(value)

        self.copy.side_effect = slow
        tree = self.tree()
        threads = [threading.Thread(target=worker, args=(plan,)) for plan in plans]
        for thread in threads:
            thread.start()
        try:
            self.assertTrue(entered.wait(30))
            deadline = time.monotonic() + 30
            while len(outcomes) < 3 and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            release.set()
            for thread in threads:
                thread.join(60)
        self.assertEqual(len(outcomes), 4, outcomes)
        self.assertEqual([status for status, _message in outcomes].count(archive.ARCHIVED), 1, outcomes)
        self.assertEqual([outcome for outcome in outcomes if outcome[0] != archive.ARCHIVED],
                         [(archive.REJECTED, archive.IN_FLIGHT)] * 3)
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual(self.intent_states(), [intents.REGISTERED])
        self.assert_added(tree, {f"EXP-42/{dv27.NAME}": ("file", self.source(6))})

    def test_only_an_exact_shared_guarantee_or_formal_decision_is_authority(self):
        store = intents.SqliteArchiveIntentStore(self.db)
        self.assertIsInstance(store, intents.ArchiveIntentStore)  # the contract a central store must meet
        self.assertIs(store.multi_host_guarantee, False)
        plan = self.plan6()
        with patch.object(archive, "SINGLE_HOST_APPROVED", False):
            for claimed in (1, "True", None):
                with self.subTest(claimed=claimed), \
                        patch.object(intents.SqliteArchiveIntentStore, "multi_host_guarantee", claimed):
                    self.assert_refused(plan, archive.MULTI_HOST_PENDING)
        self.copy.assert_not_called()
        self.assertEqual(self.intent_rows(), [])


class ProcessAuthorityTests(sec.SandboxMixin, p3b1.BoxCopyBase):
    """Real independent processes on ONE database: the certified copy runs for real in each."""

    spawn = sec.MultiProcessTests.spawn
    start = sec.MultiProcessTests.start
    files = sec.MultiProcessTests.files
    intent_rows = sec.MultiProcessTests.intents

    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)
        intents.apply_schema(self.db)
        self.item = self.add_item()
        self.intent = intents.ArchiveIntent(
            inbox_item_id=self.item, client_id=7, expedient_id=42, subfolder="", nomenclature_key=KEY,
            source_sha256=p3b1.sha(self.sources[self.item][1]), requested_by_user_id=1)
        self.go = self.root / "go"

    def test_four_processes_on_one_authority_copy_and_register_once(self):
        results = self.start(*[self.spawn(str(index), self.db, hold=1.0) for index in range(4)])
        self.assertEqual([code for code, _answer in results], [0] * 4, results)
        statuses = [answer["status"] for _code, answer in results]
        self.assertEqual(statuses.count(intents.DONE), 1, statuses)
        self.assertLessEqual(set(statuses), {intents.DONE, intents.IN_PROGRESS, intents.ALREADY_DONE})
        self.assertEqual(self.files(), [NAME])
        self.assertEqual((self.box / NAME).read_bytes(), self.sources[self.item][1])
        self.assertEqual(len(self.events(self.item, "copied_to_box")), 1)
        self.assertEqual(self.intent_rows(), [(intents.REGISTERED, str(self.box / NAME))])


# ---------------------------------------------------------------------- H3


class ContainmentTests(sec.SandboxMixin, p3b1.BoxCopyBase):
    """Adversarial swaps against the certified copy, by nomenclature (the viewer's path)."""

    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)
        self.escape = self.root / "escape_dv28"
        self.escape.mkdir()
        self.folder = self.box / "02 LABORAL" / "Contratos"

    def copy_into(self, item, **kwargs):
        return self.copy(item, subfolder=SUBFOLDER, nomenclature_key=KEY, **kwargs)

    def link(self, target, link):
        try:
            self.real["symlink"](target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                raise
            import _winapi
            _winapi.CreateJunction(str(target), str(link))

    def unlink(self, link):
        (self.real["rmdir"] if os.name == "nt" else self.real["unlink"])(link)

    def attack(self):
        """Swap attempts on the destination chain; returns the ones the OS allowed (each undone)."""
        allowed, rename = [], self.real["rename"]
        if not any(self.folder.iterdir()):
            try:
                self.real["rmdir"](self.folder)
            except OSError:
                pass
            else:
                allowed.append("rmdir:Contratos")
                self.folder.mkdir()
        for target in (self.folder, self.folder.parent, self.box, self.box.parent):
            moved = target.with_name(target.name + "_movida")
            try:
                rename(target, moved)
            except OSError:
                continue
            allowed.append(f"rename:{target.name}")
            rename(moved, target)
        return allowed

    RELEASED = ["rename:Contratos", "rename:02 LABORAL", "rename:EXP-42", "rename:box"]

    def test_root_swapped_after_its_validation_is_refused_before_any_write(self):
        (self.escape / "02 LABORAL" / "Contratos").mkdir(parents=True)
        moved = self.box.with_name("EXP-42_original")
        real_root, swapped = inbox._authorized_box_root, []

        def validated_then_swapped(raw):
            root = real_root(raw)
            self.real["rename"](self.box, moved)
            self.link(self.escape, self.box)
            swapped.append(True)
            return root

        item = self.add_item()
        state = self.item_state(item)
        try:
            with patch.object(inbox, "_authorized_box_root", validated_then_swapped), \
                    self.assertRaises(inbox.BoxCopyContainmentError):
                self.copy_into(item)
        finally:
            if swapped:
                self.unlink(self.box)
                self.real["rename"](moved, self.box)
        self.assertEqual(sorted(path.relative_to(self.escape).as_posix() for path in self.escape.rglob("*")),
                         ["02 LABORAL", "02 LABORAL/Contratos"])  # nothing written outside
        self.assertEqual(self.item_state(item), state)
        self.assertEqual(self.events(item), [])

    @WINDOWS
    def test_swaps_while_the_chain_is_held_fail_and_the_copy_stays_inside(self):
        real_create, seen = inbox._create_box_copy, []

        def attacked(*args, **kwargs):
            seen.append(self.attack())  # held: before the file exists, Contratos is still empty
            return real_create(*args, **kwargs)

        item = self.add_item()
        with patch.object(inbox, "_create_box_copy", attacked):
            result = self.copy_into(item)
        self.assertEqual(seen, [[]], "an attack against the held chain succeeded: H3 not contained")
        self.assert_registered(item, result, self.folder / NAME)
        self.assertEqual(result["box_copy"]["containment"], inbox.BOX_CONTAINMENT)
        self.assertEqual(list(self.escape.iterdir()), [])
        self.assertEqual(self.attack(), self.RELEASED)  # released after REGISTER

    @WINDOWS
    def test_swaps_during_the_write_fail(self):
        real_stream, seen = inbox._stream_into, []

        def attacked(src, handle):
            seen.append(self.attack())
            return real_stream(src, handle)

        item = self.add_item()
        with patch.object(inbox, "_stream_into", attacked):
            result = self.copy_into(item)
        self.assertEqual(seen, [[]], "an attack during the write succeeded: H3 not contained")
        self.assert_registered(item, result, self.folder / NAME)
        self.assertEqual(list(self.escape.iterdir()), [])

    @WINDOWS
    def test_every_failure_releases_the_chain_and_keeps_its_file(self):
        def failing_event(conn, item_id, kind, message="", metadata=None):
            raise sqlite3.OperationalError("database is locked (simulado)")

        def corrupt(path):
            return "0" * 64 if self.box in Path(path).parents else hashlib.sha256(Path(path).read_bytes()).hexdigest()

        for stage in ("write", "verify", "register"):
            with self.subTest(stage=stage):
                item = self.add_item(content=b"0123456789" * 3, name=f"Fallo {stage}.pdf")
                state = self.item_state(item)
                patches = {"write": [patch.object(inbox, "_BOX_COPY_CHUNK", 4)],
                           "verify": [patch.object(inbox, "_sha256", corrupt)],
                           "register": [patch.object(inbox, "_record_event", failing_event)]}[stage]
                self.write_limit = 8 if stage == "write" else None
                for patcher in patches:
                    patcher.start()
                try:
                    with self.assertRaises(inbox.BoxCopyIncomplete) as caught:
                        self.copy(item, subfolder=SUBFOLDER, target_filename=f"Fallo {stage}")
                finally:
                    self.write_limit = None
                    for patcher in reversed(patches):
                        patcher.stop()
                self.assertEqual(caught.exception.stage, stage)
                self.assertTrue(Path(caught.exception.written_path).is_file())  # never deleted
                self.assertEqual(Path(caught.exception.written_path).parent, self.folder)
                self.assertEqual(self.item_state(item), state)
                self.assertEqual(self.attack(), self.RELEASED)
        self.assertEqual(list(self.escape.iterdir()), [])

    @WINDOWS
    def test_a_folder_that_cannot_be_held_is_never_written(self):
        item = self.add_item()
        with patch.object(inbox, "_open_box_dir", side_effect=OSError(32, "en uso por otro proceso")):
            error = self.assert_refused(item, error=inbox.BoxCopyContainmentError, subfolder=SUBFOLDER,
                                        nomenclature_key=KEY)
        self.assertEqual(str(error), inbox.BOX_CONTAINMENT_FAILED)
        self.assertEqual(list(self.folder.iterdir()), [])

    @WINDOWS
    def test_cloud_placeholders_are_held_other_reparse_points_are_refused(self):
        real = inbox._open_box_dir

        def as_seen(attributes=lambda value: value, tag=None, final=None):
            def fake(path):
                handle, real_attributes, real_tag, real_final = real(path)
                if Path(path) != self.folder:
                    return handle, real_attributes, real_tag, real_final
                return (handle, attributes(real_attributes), real_tag if tag is None else tag,
                        real_final if final is None else final)
            return fake

        reparse = lambda value: value | 0x400  # noqa: E731
        accepted = {"cloud placeholder": as_seen(reparse, 0x9000001A),
                    "cloud placeholder variant": as_seen(reparse, 0x9000701A)}
        refused = {"junction": as_seen(reparse, 0xA0000003), "symlink": as_seen(reparse, 0xA000000C),
                   "other reparse point": as_seen(reparse, 0x80000013), "reparse without tag": as_seen(reparse, 0),
                   "not a folder": as_seen(lambda value: value & ~0x10),
                   "another folder": as_seen(final=str(self.escape))}
        for name, fake in accepted.items():
            with self.subTest(name), patch.object(inbox, "_open_box_dir", fake):
                item = self.add_item()
                result = self.copy_into(item)
                self.assertEqual(Path(result["copied_to_box_path"]).parent, self.folder)
        self.protect_box()
        for name, fake in refused.items():
            with self.subTest(name), patch.object(inbox, "_open_box_dir", fake):
                self.assert_refused(self.add_item(), error=inbox.BoxCopyContainmentError, subfolder=SUBFOLDER,
                                    nomenclature_key=KEY)
        self.assertEqual(list(self.escape.iterdir()), [])

    def test_collision_identical_reuse_and_no_overwrite_under_the_held_chain(self):
        item = self.add_item()
        self.seed(self.folder / NAME, b"otro documento previo")
        self.seed(self.folder / "PASAPORTE SOLICITANTE_2.pdf", self.sources[item][1])
        self.protect_box()  # both are compared byte for byte (and mtime) in tearDown
        result = self.copy_into(item)
        self.assert_registered(item, result, self.folder / "PASAPORTE SOLICITANTE_2.pdf")
        trace = result["box_copy"]
        self.assertEqual((trace["collision_decision"], trace["provenance"], trace["containment"]),
                         ("reused_identical", "preexisting_unverified", inbox.BOX_CONTAINMENT))
        self.assertEqual(trace["destination_sha256"], trace["source_sha256"])
        self.assertFalse((self.folder / "PASAPORTE SOLICITANTE_3.pdf").exists())


# ---------------------------------------------------------------------- formats


class FormatTests(sec.SandboxMixin, p3b1.BoxCopyBase):
    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)

    def test_pdf_jpg_and_png_keep_their_extension_and_catalog_name(self):
        contents = {"Escaneo.pdf": b"%PDF-1.4 sintetico", "Foto.jpg": b"\xff\xd8\xff\xe0 JPEG sintetico",
                    "Captura.png": b"\x89PNG\r\n\x1a\n sintetico"}
        for name, content in contents.items():
            with self.subTest(name=name):
                item = self.add_item(content=content, name=name)
                source = self.sources[item][0]
                mtime = source.stat().st_mtime_ns
                result = self.copy(item, nomenclature_key=KEY)
                dest = self.box / f"PASAPORTE SOLICITANTE{Path(name).suffix}"
                self.assert_registered(item, result, dest)  # same bytes: no conversion
                self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), (content, mtime))
                self.assertEqual(self.row(item)["stored_path"], str(source))


if __name__ == "__main__":
    unittest.main()
